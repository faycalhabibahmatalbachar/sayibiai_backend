"""Voix — transcription Whisper Groq, synthèse TTS."""

import base64
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from core.config import get_settings
from core.database import get_supabase_admin
from core.deps import get_current_user_id
from core.responses import error_response, success_response
from models.voice import SynthesizeRequest
from services import groq_service, tts_service
from services.usage_service import log_usage

router = APIRouter(prefix="/voice", tags=["voice"])


def _safe_upstream_error_message(exc: httpx.HTTPStatusError) -> str:
    """Return a short/safe message from upstream response body."""
    response = exc.response
    try:
        payload = response.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg[:220]
            msg = payload.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg[:220]
    except ValueError:
        pass
    body = (response.text or "").strip()
    return body[:220] if body else "Erreur du service de transcription en amont"


@router.get("/health")
async def voice_health(user_id: str = Depends(get_current_user_id)):
    """État live STT/TTS (Groq + ElevenLabs/Kokoro) pour diagnostic mobile."""
    # user_id injecté pour garder endpoint protégé/authentifié.
    _ = user_id
    settings = get_settings()
    providers = {
        "stt_groq_configured": bool(settings.groq_api_key),
        "tts_elevenlabs_configured": bool(settings.elevenlabs_api_key),
        "tts_kokoro_configured": bool(settings.kokoro_tts_url),
    }
    eleven = {}
    try:
        eleven = await tts_service.elevenlabs_health_check()
    except Exception as e:
        eleven = {"ok": False, "configured": providers["tts_elevenlabs_configured"], "error": str(e)}
    return success_response(
        {
            "providers": providers,
            "elevenlabs": eleven,
        },
        "Voice health OK",
    )


@router.post("/transcribe")
async def transcribe(
    file: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    user_id: str = Depends(get_current_user_id),
):
    """Audio → texte (Groq Whisper). Formats : webm, mp3, wav, m4a."""
    source = file or audio
    if source is None:
        return error_response("Champ audio manquant (file)", 422)
    raw = await source.read()
    if not raw:
        return error_response("Fichier audio vide", 400)
    if len(raw) > 25 * 1024 * 1024:
        return error_response("Fichier trop volumineux (max ~25 Mo)", 400)
    try:
        data = await groq_service.transcribe_audio(
            raw,
            source.filename or "audio.webm",
            source.content_type,
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if 400 <= status < 500:
            return error_response(
                f"Requête de transcription invalide: {_safe_upstream_error_message(e)}",
                400,
            )
        return error_response("Service de transcription indisponible", 502)
    except httpx.TimeoutException:
        return error_response("Délai dépassé côté service de transcription", 504)
    except httpx.RequestError:
        return error_response("Impossible de joindre le service de transcription", 502)
    except Exception as e:
        return error_response(f"Erreur transcription: {e}", 502)
    text = data.get("text") or ""
    lang = data.get("language")
    duration = None
    if isinstance(data.get("segments"), list) and data["segments"]:
        try:
            duration = float(data["segments"][-1].get("end") or 0)
        except Exception:
            duration = None
    await log_usage(user_id, "/voice/transcribe", None, groq_service.WHISPER_MODEL)
    return success_response(
        {"text": text, "language": lang, "duration": duration},
        "Transcription OK",
    )


@router.post("/synthesize")
async def synthesize(
    body: SynthesizeRequest,
    user_id: str = Depends(get_current_user_id),
    raw: bool = False,
):
    """Texte → audio MP3 (ElevenLabs ou Kokoro)."""
    try:
        audio, mime = await tts_service.synthesize(
            body.text,
            body.language,
            body.voice,
            prefer_kokoro=False,
        )
    except Exception as e:
        msg = str(e)
        if "ElevenLabs" in msg or "ELEVENLABS" in msg:
            return error_response(msg, 502)
        if "Aucun service TTS opérationnel" in msg:
            return error_response(msg, 503)
        return error_response(msg, 502)
    await log_usage(user_id, "/voice/synthesize", len(body.text), "tts")
    if raw:
        return Response(content=audio, media_type=mime)
    b64 = base64.standard_b64encode(audio).decode("ascii")
    return success_response(
        {"audio_base64": b64, "mime_type": mime},
        "Synthèse OK",
    )


@router.get("/call-log")
async def get_call_log(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
):
    """Historique des appels gérés par le secrétariat vocal."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("inbound_calls")
            .select("*")
            .eq("user_id", user_id)
            .order("call_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/sms/inbound")
async def inbound_sms_webhook(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    """
    Reçoit un SMS entrant depuis le bridge Flutter natif.
    Stocke et analyse avec LLM. Retourne une réponse automatique si configurée.
    """
    try:
        import uuid
        phone = payload.get("phone", "")
        body = payload.get("body", "")
        c = get_supabase_admin()
        if c:
            c.table("sms_log").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "direction": "inbound",
                "phone_number": phone,
                "body": body,
                "ai_generated": False,
                "read": False,
            }).execute()

        # Vérifier si réponse auto activée
        auto_reply = None
        if c:
            settings = c.table("call_settings").select("auto_sms_reply,auto_sms_template").eq("user_id", user_id).execute()
            if settings.data and settings.data[0].get("auto_sms_reply"):
                template = settings.data[0].get("auto_sms_template", "")
                auto_reply = {"phone": phone, "body": template}

        return success_response(
            {"stored": True, "auto_reply": auto_reply},
            "SMS traité",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/sms/confirm-sent")
async def confirm_sms_sent(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    """Confirme l'envoi d'un SMS depuis Flutter."""
    try:
        c = get_supabase_admin()
        if c:
            c.table("sms_log").insert({
                "user_id": user_id,
                "direction": "outbound",
                "phone_number": payload.get("phone", ""),
                "body": payload.get("body", ""),
                "ai_generated": payload.get("ai_generated", False),
            }).execute()
        return success_response({"confirmed": True}, "SMS confirmé")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/sms/history")
async def get_sms_history(
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
):
    """Historique des SMS entrants et sortants."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("sms_log")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)
