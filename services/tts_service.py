"""Synthèse vocale — ElevenLabs, Kokoro (HTTP), ou repli message."""

from typing import Any, Dict, Optional, Tuple

import httpx

from core.config import get_settings

ELEVENLABS_BUILTIN_VOICES: Dict[str, str] = {
    "ahmat": "TTtB1x9U8PF0Vgf20IAP",
    "brahim": "93nuHbke4dTER9x2pDwE",
    "mariam": "tMyQcCxfGDdIt7wJ2RQw",
    "hassane": "c365oriviHmAhyLhpuN6",
}


async def elevenlabs_health_check() -> Dict[str, Any]:
    """
    Vérifie la connectivité ElevenLabs et la validité de la voix par défaut.
    Utilise /v1/voices (léger) pour diagnostiquer rapidement la config.
    """
    settings = get_settings()
    out: Dict[str, Any] = {
        "configured": bool(settings.elevenlabs_api_key),
        "default_voice_id": settings.elevenlabs_default_voice_id,
        "model_id": settings.elevenlabs_model_id,
        "builtin_voices": ELEVENLABS_BUILTIN_VOICES,
        "ok": False,
    }
    if not settings.elevenlabs_api_key:
        out["error"] = "ELEVENLABS_API_KEY manquant"
        return out

    headers = {"xi-api-key": settings.elevenlabs_api_key}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get("https://api.elevenlabs.io/v1/voices", headers=headers)
        r.raise_for_status()
        payload = r.json() if r.content else {}
        voices = payload.get("voices") if isinstance(payload, dict) else []
        if not isinstance(voices, list):
            voices = []
        ids = [str(v.get("voice_id")) for v in voices if isinstance(v, dict) and v.get("voice_id")]
        out["voices_count"] = len(ids)
        out["default_voice_exists"] = settings.elevenlabs_default_voice_id in ids
        out["ok"] = True
        return out


async def synthesize_elevenlabs(
    text: str,
    voice_id: Optional[str] = None,
) -> bytes:
    """TTS ElevenLabs (mp3)."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY manquant")

    def _normalized_voice_id(candidate: Optional[str]) -> str:
        v = (candidate or "").strip()
        if not v or v.lower() in {"default", "auto"}:
            return settings.elevenlabs_default_voice_id or ELEVENLABS_BUILTIN_VOICES["ahmat"]
        alias = ELEVENLABS_BUILTIN_VOICES.get(v.lower())
        if alias:
            return alias
        return v

    vid = _normalized_voice_id(voice_id)
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": text,
        "model_id": settings.elevenlabs_model_id,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            return r.content
        except httpx.HTTPStatusError as e:
            # Si voice_id invalide côté client, on retente sur la voix par défaut serveur.
            status = e.response.status_code if e.response is not None else None
            fallback_voice = settings.elevenlabs_default_voice_id or ELEVENLABS_BUILTIN_VOICES["ahmat"]
            if status == 404 and vid != fallback_voice:
                r2 = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{fallback_voice}",
                    headers=headers,
                    json=body,
                )
                r2.raise_for_status()
                return r2.content
            raise


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
    errors: list[str] = []

    async def _try(name: str, fn):
        try:
            data = await fn()
            if data:
                return data
        except Exception as e:
            errors.append(f"{name}: {e}")
        return None

    if prefer_kokoro and get_settings().kokoro_tts_url:
        data = await _try("kokoro", lambda: synthesize_kokoro(text, language))
        if data:
            return data, "audio/mpeg"

    if get_settings().elevenlabs_api_key:
        data = await _try("elevenlabs", lambda: synthesize_elevenlabs(text, voice))
        if data:
            return data, "audio/mpeg"

    if get_settings().kokoro_tts_url:
        data = await _try("kokoro", lambda: synthesize_kokoro(text, language))
        if data:
            return data, "audio/mpeg"

    detail = f" ({'; '.join(errors)})" if errors else ""
    raise RuntimeError("Aucun service TTS opérationnel (ElevenLabs/Kokoro)" + detail)
