"""Router Surveillance — screen awareness + caméra temps réel via WebSocket."""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.config import get_settings
from core.database import get_supabase_admin
from core.deps import get_current_user_id
from core.responses import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/surveillance", tags=["surveillance"])

# Seuil de similarité des frames (ignorer si trop similaires)
DEFAULT_SIMILARITY_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------

class ScreenSettingsRequest(BaseModel):
    enabled: bool = True
    alert_on_sensitive: bool = True
    alert_on_errors: bool = True
    notify_push: bool = True
    capture_interval_seconds: int = Field(default=3, ge=1, le=30)


class CameraSettingsRequest(BaseModel):
    enabled: bool = True
    alert_on_motion: bool = True
    alert_on_unknown_person: bool = False
    notify_push: bool = True
    record_on_alert: bool = True


# ---------------------------------------------------------------------------
# WebSocket — Screen Awareness
# ---------------------------------------------------------------------------

@router.websocket("/screen/stream")
async def screen_stream(websocket: WebSocket):
    """
    WebSocket stream de captures d'écran pour screen awareness.
    Le client envoie des frames JPEG en base64, le serveur retourne des alertes.
    """
    await websocket.accept()
    import base64, hashlib, httpx

    s = get_settings()
    session_id = None
    frames_analyzed = 0
    alerts_triggered = 0
    prev_frame_hash = None

    try:
        # Récupérer user_id depuis le premier message (auth token)
        auth_msg = await websocket.receive_json()
        token = auth_msg.get("token", "")
        from core.security import get_subject_from_token
        user_id = get_subject_from_token(token)
        if not user_id:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close(code=1008)
            return

        # Créer session
        try:
            c = get_supabase_admin()
            if c:
                res = c.table("screen_sessions").insert({
                    "user_id": user_id,
                    "session_start": "now()",
                }).execute()
                if res.data:
                    session_id = res.data[0].get("id")
        except Exception:
            pass

        await websocket.send_json({"status": "connected", "session_id": session_id})

        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break

            frame_b64 = msg.get("frame")
            if not frame_b64:
                continue

            # Détecter changement significatif
            frame_hash = hashlib.md5(frame_b64[:2000].encode()).hexdigest()
            if prev_frame_hash == frame_hash:
                await websocket.send_json({"type": "no_change"})
                continue
            prev_frame_hash = frame_hash
            frames_analyzed += 1

            # Analyser avec Gemini Vision
            alert = await _analyze_screen_frame(frame_b64, s)
            if alert:
                alerts_triggered += 1
                # Stocker l'alerte
                try:
                    if c and session_id:
                        c.table("screen_alerts").insert({
                            "session_id": session_id,
                            "alert_type": alert.get("type", "info"),
                            "app_context": alert.get("app_context", ""),
                            "message": alert.get("message", ""),
                            "suggestion": alert.get("suggestion", ""),
                        }).execute()
                except Exception:
                    pass

                await websocket.send_json({"type": "alert", "alert": alert})
            else:
                await websocket.send_json({"type": "ok"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Screen stream error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        # Fermer session
        try:
            c = get_supabase_admin()
            if c and session_id:
                c.table("screen_sessions").update({
                    "session_end": "now()",
                    "frames_analyzed": frames_analyzed,
                    "alerts_triggered": alerts_triggered,
                }).eq("id", session_id).execute()
        except Exception:
            pass


async def _analyze_screen_frame(frame_b64: str, s: Any) -> Optional[Dict]:
    """Analyse une frame d'écran avec GPT-4o Vision ou Gemini."""
    prompt = (
        "Analyse ce screenshot d'écran d'ordinateur/téléphone. "
        "Si tu détectes quelque chose d'important (erreur, message urgent, "
        "alerte, tentative de phishing, contenu sensible, opportunité importante), "
        "réponds en JSON: {type, app_context, message, suggestion, highlight_box}. "
        "Si tout est normal, réponds uniquement: RIEN"
    )

    if s.gemini_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={s.gemini_api_key}",
                    json={
                        "contents": [{
                            "role": "user",
                            "parts": [
                                {"text": prompt},
                                {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                            ],
                        }],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300},
                    }
                )
            if response.status_code < 400:
                raw = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if raw.strip().upper() == "RIEN" or not raw.strip():
                    return None
                if "{" in raw:
                    start = raw.index("{")
                    end = raw.rindex("}") + 1
                    return json.loads(raw[start:end])
        except Exception as e:
            logger.debug("Screen frame analysis error: %s", e)

    return None


# ---------------------------------------------------------------------------
# WebSocket — Camera Surveillance
# ---------------------------------------------------------------------------

@router.websocket("/camera/stream")
async def camera_stream(websocket: WebSocket):
    """
    WebSocket stream vidéo caméra pour surveillance en temps réel.
    1 frame/seconde, comparaison de similarité, alerte si anomalie.
    """
    await websocket.accept()
    import base64, hashlib

    s = get_settings()
    session_id = None
    frames_analyzed = 0
    alerts_triggered = 0
    prev_hash = None

    try:
        auth_msg = await websocket.receive_json()
        token = auth_msg.get("token", "")
        from core.security import get_subject_from_token
        user_id = get_subject_from_token(token)
        if not user_id:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close(code=1008)
            return

        try:
            c = get_supabase_admin()
            if c:
                res = c.table("video_surveillance_sessions").insert({
                    "user_id": user_id,
                    "camera_source": auth_msg.get("camera_source", "front"),
                    "session_start": "now()",
                }).execute()
                if res.data:
                    session_id = res.data[0].get("id")
        except Exception:
            pass

        await websocket.send_json({"status": "connected", "session_id": session_id})

        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break

            frame_b64 = msg.get("frame")
            if not frame_b64:
                continue

            # Comparaison hash pour ignorer les frames identiques
            frame_hash = hashlib.md5(frame_b64[:3000].encode()).hexdigest()
            if prev_hash and frame_hash == prev_hash:
                await websocket.send_json({"type": "no_change"})
                continue
            prev_hash = frame_hash
            frames_analyzed += 1

            # Analyser la frame
            alert = await _analyze_camera_frame(frame_b64, s)
            if alert:
                alerts_triggered += 1
                try:
                    c = get_supabase_admin()
                    if c and session_id:
                        c.table("surveillance_alerts").insert({
                            "session_id": session_id,
                            "alert_type": alert.get("type", "motion"),
                            "alert_description": alert.get("description", ""),
                            "timestamp": "now()",
                            "user_acknowledged": False,
                        }).execute()
                except Exception:
                    pass

                await websocket.send_json({"type": "alert", "alert": alert})
            else:
                await websocket.send_json({"type": "clear"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Camera stream error: %s", e)
    finally:
        try:
            c = get_supabase_admin()
            if c and session_id:
                c.table("video_surveillance_sessions").update({
                    "session_end": "now()",
                    "frames_analyzed": frames_analyzed,
                    "alerts_triggered": alerts_triggered,
                }).eq("id", session_id).execute()
        except Exception:
            pass


async def _analyze_camera_frame(frame_b64: str, s: Any) -> Optional[Dict]:
    """Analyse une frame caméra avec Gemini Vision."""
    prompt = (
        "Tu surveilles une caméra de sécurité. Analyse cette image. "
        "Détecte: mouvement suspect, personne inconnue, chute, feu, intrusion, ou situation dangereuse. "
        "Si situation normale → réponds: RIEN\n"
        "Sinon → JSON: {type, description, severity: 'low'|'medium'|'high', suggested_action}"
    )

    if s.gemini_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={s.gemini_api_key}",
                    json={
                        "contents": [{
                            "role": "user",
                            "parts": [
                                {"text": prompt},
                                {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                            ],
                        }],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
                    }
                )
                if r.status_code < 400:
                    raw = (
                        r.json().get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if raw.strip().upper() == "RIEN" or not raw.strip():
                        return None
                    if "{" in raw:
                        start = raw.index("{")
                        end = raw.rindex("}") + 1
                        return json.loads(raw[start:end])
        except Exception as e:
            logger.debug("Camera frame analysis error: %s", e)
    return None


# ---------------------------------------------------------------------------
# Routes REST — Alertes et paramètres
# ---------------------------------------------------------------------------

@router.get("/screen/alerts")
async def get_screen_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Alertes screen awareness récentes."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("screen_alerts")
            .select("*, screen_sessions!inner(user_id)")
            .eq("screen_sessions.user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/camera/alerts")
async def get_camera_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Alertes caméra récentes."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("surveillance_alerts")
            .select("*, video_surveillance_sessions!inner(user_id)")
            .eq("video_surveillance_sessions.user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/camera/sessions")
async def get_camera_sessions(
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
):
    """Sessions de surveillance caméra."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("video_surveillance_sessions")
            .select("*")
            .eq("user_id", user_id)
            .order("session_start", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.put("/screen/settings")
async def update_screen_settings(
    body: ScreenSettingsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Met à jour les paramètres de screen awareness."""
    try:
        c = get_supabase_admin()
        if c:
            c.table("screen_settings").upsert({
                "user_id": user_id,
                **body.model_dump(),
            }).execute()
        return success_response({"updated": True}, "Paramètres mis à jour")
    except Exception as e:
        return error_response(str(e), 500)


@router.put("/camera/settings")
async def update_camera_settings(
    body: CameraSettingsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Met à jour les paramètres de surveillance caméra."""
    try:
        c = get_supabase_admin()
        if c:
            c.table("camera_settings").upsert({
                "user_id": user_id,
                **body.model_dump(),
            }).execute()
        return success_response({"updated": True}, "Paramètres mis à jour")
    except Exception as e:
        return error_response(str(e), 500)
