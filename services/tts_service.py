"""Synthèse vocale — ElevenLabs, Kokoro (HTTP), ou repli message."""

from typing import Optional, Tuple

import httpx

from core.config import get_settings


async def synthesize_elevenlabs(
    text: str,
    voice_id: Optional[str] = None,
) -> bytes:
    """TTS ElevenLabs (mp3)."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY manquant")
    vid = voice_id or "21m00Tcm4TlvDq8ikWAM"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.content


async def synthesize_kokoro(text: str, language: str = "fr") -> bytes:
    """TTS Kokoro via service auto-hébergé (POST /synthesize attendu)."""
    settings = get_settings()
    if not settings.kokoro_tts_url:
        raise RuntimeError("KOKORO_TTS_URL manquant")
    url = settings.kokoro_tts_url.rstrip("/") + "/synthesize"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            url,
            json={"text": text, "language": language},
        )
        r.raise_for_status()
        return r.content


async def synthesize(
    text: str,
    language: str = "fr",
    voice: Optional[str] = None,
    prefer_kokoro: bool = False,
) -> Tuple[bytes, str]:
    """
    Retourne (audio_bytes, mime_type).
    Ordre : Kokoro si demandé et configuré, sinon ElevenLabs.
    """
    if prefer_kokoro and get_settings().kokoro_tts_url:
        data = await synthesize_kokoro(text, language)
        return data, "audio/mpeg"
    if get_settings().elevenlabs_api_key:
        data = await synthesize_elevenlabs(text, voice)
        return data, "audio/mpeg"
    if get_settings().kokoro_tts_url:
        data = await synthesize_kokoro(text, language)
        return data, "audio/mpeg"
    raise RuntimeError("Aucun service TTS configuré (ElevenLabs ou Kokoro)")
