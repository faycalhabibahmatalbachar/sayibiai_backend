"""Génération d'images réelle — Gemini (modalités IMAGE) puis repli OpenAI DALL·E."""

import base64
import logging
import uuid
from typing import List, Optional, Tuple

import httpx

from core.config import get_settings
from services import storage_service

logger = logging.getLogger(__name__)

# Modèles testés côté Google AI Studio (génération native).
_GEMINI_IMAGE_MODELS = (
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.0-flash-exp-image-generation",
    "gemini-2.0-flash-exp",
)


def _gemini_endpoint(model: str) -> str:
    s = get_settings()
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={s.gemini_api_key}"
    )


async def _try_gemini_native_image(prompt: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Retourne (png_bytes, mime) ou (None, None)."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return None, None

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "temperature": 0.8,
        },
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        for model in _GEMINI_IMAGE_MODELS:
            try:
                r = await client.post(_gemini_endpoint(model), json=body)
                if r.status_code >= 400:
                    logger.warning("Gemini image %s HTTP %s: %s", model, r.status_code, r.text[:300])
                    continue
                data = r.json()
                parts = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [])
                )
                for p in parts:
                    inline = p.get("inlineData") or p.get("inline_data")
                    if not inline:
                        continue
                    b64 = inline.get("data")
                    mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                    if b64:
                        return base64.b64decode(b64), mime
            except Exception as e:
                logger.warning("Gemini image model %s: %s", model, e)
                continue
    return None, None


async def _try_openai_dalle(prompt: str) -> Tuple[Optional[bytes], Optional[str]]:
    settings = get_settings()
    key = (settings.openai_api_key or "").strip()
    if not key:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt[:3900],
                    "n": 1,
                    "size": "1024x1024",
                    "quality": "standard",
                },
            )
            r.raise_for_status()
            data = r.json()
            url = (data.get("data") or [{}])[0].get("url")
            if not url:
                return None, None
            gr = await client.get(url)
            gr.raise_for_status()
            return gr.content, "image/png"
    except Exception as e:
        logger.warning("OpenAI image: %s", e)
        return None, None


async def generate_image_and_upload(
    prompt: str,
    user_id: str,
) -> Tuple[str, List[str]]:
    """
    Génère une image, upload R2 si possible.
    Retourne (texte court pour l'historique, liste d'URLs publiques).
    """
    raw: Optional[bytes] = None
    mime = "image/png"

    raw, mime = await _try_gemini_native_image(prompt)
    if not raw:
        raw, mime = await _try_openai_dalle(prompt)

    if not raw:
        raise RuntimeError(
            "Aucun moteur d'images disponible : configurez GEMINI_API_KEY (génération native) "
            "et/ou OPENAI_API_KEY (DALL·E 3).",
        )

    ext = "png" if "png" in mime else "jpg"
    fname = f"sayibi_img_{uuid.uuid4().hex[:10]}.{ext}"
    ct = mime if "/" in mime else "image/png"
    _key, url = await storage_service.upload_bytes(
        raw,
        f"generated/images/{user_id}",
        fname,
        ct,
    )
    caption = (
        "Voici l'image générée. Vous pouvez la télécharger via le lien ci-dessous.\n\n"
        f"![]({url})"
    )
    return caption, [url]

