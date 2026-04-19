"""Client Groq — LLM (Llama) et transcription Whisper."""

from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from core.config import get_settings

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
WHISPER_MODEL = "whisper-large-v3"


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }


async def chat_completion(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    *,
    json_mode: bool = False,
) -> Dict[str, Any]:
    """Appel chat non-streaming. Si json_mode=True, force une réponse JSON objet (modèles compatibles)."""
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY manquant")
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(GROQ_CHAT_URL, headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


async def chat_completion_stream(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> AsyncIterator[str]:
    """Flux SSE OpenAI-compatible : yield des morceaux de texte."""
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY manquant")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    headers = {**_headers(), "Accept": "text/event-stream"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            GROQ_CHAT_URL,
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        import json

                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
                    except (KeyError, ValueError, IndexError):
                        continue


async def transcribe_audio(
    file_bytes: bytes,
    filename: str,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcription audio via Whisper Groq (multipart)."""
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY manquant")
    ct = content_type or "application/octet-stream"
    files = {"file": (filename, file_bytes, ct)}
    data = {"model": WHISPER_MODEL, "response_format": "verbose_json"}
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(GROQ_WHISPER_URL, headers=headers, data=data, files=files)
        r.raise_for_status()
        return r.json()


def extract_text_and_usage(completion: Dict[str, Any]) -> tuple[str, Optional[int]]:
    """Extrait le texte et le nombre de tokens totaux de la réponse Groq."""
    try:
        text = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        text = ""
    usage = completion.get("usage") or {}
    total = usage.get("total_tokens")
    return text, total
