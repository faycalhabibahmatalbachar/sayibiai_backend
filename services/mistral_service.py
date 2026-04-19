"""Client Mistral AI — excellent pour le français."""

from typing import Any, Dict, List, Optional

import httpx

from core.config import get_settings

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-large-latest"


async def chat_completion(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY manquant")
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(MISTRAL_URL, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


def extract_text_and_usage(completion: Dict[str, Any]) -> tuple[str, Optional[int]]:
    try:
        text = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        text = ""
    usage = completion.get("usage") or {}
    total = usage.get("total_tokens")
    return text, total
