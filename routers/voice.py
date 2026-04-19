"""Voix — transcription Whisper Groq, synthèse TTS."""

import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from models.voice import SynthesizeRequest
from services import groq_service, tts_service
from services.usage_service import log_usage

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """Audio → texte (Groq Whisper). Formats : webm, mp3, wav, m4a."""
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        return error_response("Fichier trop volumineux (max ~25 Mo)", 400)
    try:
        data = await groq_service.transcribe_audio(
            raw,
            file.filename or "audio.webm",
            file.content_type,
        )
    except Exception as e:
        return error_response(str(e), 502)
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
        return error_response(str(e), 502)
    await log_usage(user_id, "/voice/synthesize", len(body.text), "tts")
    if raw:
        return Response(content=audio, media_type=mime)
    b64 = base64.standard_b64encode(audio).decode("ascii")
    return success_response(
        {"audio_base64": b64, "mime_type": mime},
        "Synthèse OK",
    )
