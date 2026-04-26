"""Service de génération et d'analyse vidéo — Runway Gen-3, Sora (async jobs)."""

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.config import get_settings
from core.database import get_supabase_admin
from services import storage_service, watermark_service
from services.prompt_engineering import build_image_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Génération vidéo text-to-video
# ---------------------------------------------------------------------------

async def generate_video(
    prompt: str,
    user_id: str,
    duration: int = 5,
    provider: str = "runway",
) -> Dict[str, Any]:
    """
    Lance une génération vidéo async.
    Retourne { job_id, status, provider, record_id }.
    """
    s = get_settings()

    # Enrichissement prompt
    optimized_prompt, _ = await build_image_prompt(prompt, style="realistic")

    record_id = str(uuid.uuid4())
    job_id: Optional[str] = None
    status = "pending"

    if provider == "runway" and s.runway_api_key:
        job_id, status = await _runway_submit(optimized_prompt, duration, s.runway_api_key)
    else:
        # Fallback: enregistrement en attente pour traitement manuel
        status = "queued_no_provider"
        job_id = f"mock_{uuid.uuid4().hex[:12]}"

    # Persister en base
    try:
        c = get_supabase_admin()
        if c:
            c.table("generated_videos").insert({
                "id": record_id,
                "user_id": user_id,
                "original_prompt": prompt,
                "optimized_prompt": optimized_prompt,
                "duration_seconds": duration,
                "provider": provider,
                "job_id": job_id,
                "status": status,
            }).execute()
    except Exception as e:
        logger.warning("Video DB insert error: %s", e)

    return {
        "record_id": record_id,
        "job_id": job_id,
        "status": status,
        "provider": provider,
    }


async def _runway_submit(prompt: str, duration: int, api_key: str) -> Tuple[str, str]:
    """Soumet un job à Runway Gen-3 Alpha."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Runway-Version": "2024-11-06",
                "Content-Type": "application/json",
            },
            json={
                "promptText": prompt,
                "duration": duration,
                "ratio": "1280:720",
                "model": "gen3a_turbo",
            },
        )
        if r.status_code >= 400:
            logger.warning("Runway submit error %s: %s", r.status_code, r.text[:300])
            return f"error_{uuid.uuid4().hex[:8]}", "failed"
        data = r.json()
        job_id = data.get("id", str(uuid.uuid4()))
        return job_id, "processing"


async def get_video_status(job_id: str, provider: str = "runway") -> Dict[str, Any]:
    """Vérifie le statut d'un job de génération vidéo."""
    s = get_settings()

    if provider == "runway" and s.runway_api_key:
        return await _runway_status(job_id, s.runway_api_key)

    # Mise à jour base de données
    try:
        c = get_supabase_admin()
        if c:
            res = c.table("generated_videos").select("*").eq("job_id", job_id).execute()
            if res.data:
                return res.data[0]
    except Exception as e:
        logger.warning("Video status DB error: %s", e)

    return {"job_id": job_id, "status": "unknown"}


async def _runway_status(job_id: str, api_key: str) -> Dict[str, Any]:
    """Polling du statut Runway."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"https://api.dev.runwayml.com/v1/tasks/{job_id}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-Runway-Version": "2024-11-06",
                },
            )
            if r.status_code >= 400:
                return {"job_id": job_id, "status": "failed"}
            data = r.json()
            status_map = {"PENDING": "pending", "RUNNING": "processing", "SUCCEEDED": "completed", "FAILED": "failed"}
            runway_status = data.get("status", "PENDING")
            status = status_map.get(runway_status, "processing")

            result = {"job_id": job_id, "status": status}
            if status == "completed":
                output = data.get("output", [])
                if output:
                    video_url = output[0] if isinstance(output, list) else output
                    # Watermark + upload
                    watermarked_url = await _watermark_and_upload_video(video_url, job_id)
                    result["video_url"] = watermarked_url or video_url

                    # Mise à jour base
                    try:
                        c = get_supabase_admin()
                        if c:
                            c.table("generated_videos").update({
                                "status": "completed",
                                "video_url": video_url,
                                "watermarked_url": watermarked_url,
                            }).eq("job_id", job_id).execute()
                    except Exception:
                        pass

            return result
    except Exception as e:
        logger.warning("Runway status error: %s", e)
        return {"job_id": job_id, "status": "failed", "error": str(e)}


async def _watermark_and_upload_video(video_url: str, job_id: str) -> Optional[str]:
    """Télécharge, watermarke et réupload une vidéo."""
    try:
        import tempfile, os
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(video_url)
            if r.status_code >= 400:
                return None
            video_bytes = r.content

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
            tmp_in.write(video_bytes)
            tmp_path = tmp_in.name

        out_path = tmp_path + "_wm.mp4"
        success = await watermark_service.apply_video_watermark_overlay(tmp_path, out_path)

        upload_path = out_path if success else tmp_path
        with open(upload_path, "rb") as f:
            video_data = f.read()

        fname = f"chadgpt_video_{job_id[:12]}.mp4"
        _, url = await storage_service.upload_bytes(
            video_data,
            "generated/videos",
            fname,
            "video/mp4",
        )
        os.unlink(tmp_path)
        if success and os.path.exists(out_path):
            os.unlink(out_path)
        return url
    except Exception as e:
        logger.warning("Video watermark/upload error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Analyse de vidéo
# ---------------------------------------------------------------------------

async def analyze_video(
    video_url: str,
    user_id: str,
    analysis_type: str = "full",
) -> Dict[str, Any]:
    """
    Analyse une vidéo (transcript, résumé, anomalies, moments clés).
    Utilise Gemini 1.5 Pro ou GPT-4o Vision sur frames extraites.
    """
    s = get_settings()

    # Vérifier cache
    from services.cache_service import get_video_analysis, set_video_analysis
    cached = await get_video_analysis(video_url)
    if cached:
        return cached

    result: Dict[str, Any] = {
        "video_url": video_url,
        "analysis_type": analysis_type,
        "transcript": "",
        "summary": "",
        "key_moments": [],
        "objects_detected": [],
        "anomalies_detected": [],
    }

    # Extraction audio pour transcription
    if analysis_type in ("full", "transcript"):
        try:
            transcript = await _extract_and_transcribe(video_url, s)
            result["transcript"] = transcript
        except Exception as e:
            logger.warning("Transcript extraction error: %s", e)

    # Analyse frame par frame avec Gemini Vision
    if analysis_type in ("full", "summary", "anomaly") and s.gemini_api_key:
        try:
            vision_analysis = await _analyze_frames_with_gemini(video_url, s.gemini_api_key)
            result.update(vision_analysis)
        except Exception as e:
            logger.warning("Frame analysis error: %s", e)

    # Persister
    try:
        c = get_supabase_admin()
        if c:
            c.table("video_analyses").insert({
                "user_id": user_id,
                "video_url": video_url,
                "analysis_type": analysis_type,
                "full_analysis": result,
                "transcript": result.get("transcript", ""),
                "summary": result.get("summary", ""),
                "key_moments": result.get("key_moments", []),
                "objects_detected": result.get("objects_detected", []),
                "anomalies_detected": result.get("anomalies_detected", []),
            }).execute()
    except Exception as e:
        logger.warning("Video analysis DB error: %s", e)

    await set_video_analysis(video_url, result)
    return result


async def _extract_and_transcribe(video_url: str, s: Any) -> str:
    """Télécharge la vidéo et transcrit l'audio avec Whisper."""
    if not s.openai_api_key:
        return ""
    try:
        import tempfile, os
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(video_url)
            if r.status_code >= 400:
                return ""
            video_bytes = r.content

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        # Whisper via OpenAI
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(tmp_path, "rb") as f:
                r = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {s.openai_api_key}"},
                    files={"file": ("video.mp4", f, "video/mp4")},
                    data={"model": "whisper-1"},
                )
            if r.status_code < 400:
                transcript = r.json().get("text", "")
            else:
                transcript = ""
        os.unlink(tmp_path)
        return transcript
    except Exception as e:
        logger.warning("Transcription error: %s", e)
        return ""


async def _analyze_frames_with_gemini(video_url: str, api_key: str) -> dict:
    """Analyse des frames vidéo extraites avec Gemini Vision."""
    import base64, tempfile, os
    try:
        # Télécharger vidéo
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(video_url)
            if r.status_code >= 400:
                return {}

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = tmp.name

        # Extraire frames avec ffmpeg
        frames_dir = tempfile.mkdtemp()
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", tmp_path,
            "-vf", "fps=1/5",  # 1 frame toutes les 5 secondes
            "-frames:v", "10",  # max 10 frames
            f"{frames_dir}/frame_%03d.jpg"
        ], capture_output=True, timeout=60)

        frame_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".jpg")])
        if not frame_files:
            return {}

        # Encoder frames en base64
        frames_b64 = []
        for fname in frame_files[:5]:
            with open(f"{frames_dir}/{fname}", "rb") as f:
                frames_b64.append(base64.b64encode(f.read()).decode())

        # Analyser avec Gemini
        parts = [{"text": "Analyse cette séquence vidéo. Identifie: objets principaux, personnes, actions, anomalies, moments clés. Réponds en JSON avec: summary, objects_detected, anomalies_detected, key_moments."}]
        for b64 in frames_b64:
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64}})

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"temperature": 0.3},
                }
            )

        import json
        if r.status_code < 400:
            raw = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            # Nettoyer JSON
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            try:
                return json.loads(raw)
            except Exception:
                return {"summary": raw}

        # Cleanup
        os.unlink(tmp_path)
        for f in frame_files:
            try:
                os.unlink(f"{frames_dir}/{f}")
            except Exception:
                pass
        os.rmdir(frames_dir)

    except Exception as e:
        logger.warning("Gemini frame analysis error: %s", e)
    return {}


async def get_video_history(user_id: str, limit: int = 20) -> List[dict]:
    """Historique des vidéos générées par l'utilisateur."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("generated_videos")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Video history error: %s", e)
        return []
