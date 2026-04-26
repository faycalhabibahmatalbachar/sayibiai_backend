"""Génération d'images réelle — Gemini natif (robuste, multi-modèles)."""

import base64
import logging
import uuid
from typing import List, Optional, Tuple

import httpx

from core.config import get_settings
from services import storage_service

logger = logging.getLogger(__name__)


def finalize_prompt_for_image_generation(user_message: str) -> str:
    """
    Enrichit la demande : résultat fiable + impact visuel même si l’utilisateur est peu descriptif.
    Pas de « cours théorique » dans l’image — uniquement le rendu.
    """
    base = (user_message or "").strip()
    if len(base) < 3:
        base = (
            "Composition visuelle forte, sujet central clair, esthétique soignée, "
            "forte lisibilité ; peut être minimaliste ou monochrome si pertinent."
        )
    rules = (
        "\n\n[Consignes de rendu : image fidèle au sujet, cohérente, sans artefacts absurdes. "
        "Si la demande est vague : privilégier une composition équilibrée, esthétique marquée, "
        "éventuellement noir et blanc ou palette sobre. Éviter tout pavé de texte dans l’image "
        "sauf si explicitement demandé.]"
    )
    return base + rules

# Modèles testés côté Google AI Studio (génération native).
_GEMINI_IMAGE_MODELS = (
    "gemini-2.5-flash-image-preview",
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


def _gemini_list_models_endpoint() -> str:
    s = get_settings()
    return f"https://generativelanguage.googleapis.com/v1beta/models?key={s.gemini_api_key}"


def _normalize_model_name(name: str) -> str:
    # Google ListModels returns names like "models/gemini-2.5-flash".
    return name.split("/", 1)[1] if "/" in name else name


async def _discover_gemini_image_models(client: httpx.AsyncClient) -> List[str]:
    """Discover currently available Gemini models that can generate image output."""
    try:
        r = await client.get(_gemini_list_models_endpoint())
        if r.status_code >= 400:
            logger.warning("Gemini ListModels HTTP %s: %s", r.status_code, r.text[:300])
            return []
        payload = r.json()
    except Exception as e:
        logger.warning("Gemini ListModels failed: %s", e)
        return []

    models = payload.get("models")
    if not isinstance(models, list):
        return []

    discovered: List[str] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        name_raw = m.get("name")
        methods = m.get("supportedGenerationMethods") or m.get("supported_generation_methods") or []
        if not isinstance(name_raw, str) or not isinstance(methods, list):
            continue
        if "generateContent" not in methods:
            continue
        lower = name_raw.lower()
        # Heuristic: keep image-capable model families.
        if ("image" not in lower) and ("imagen" not in lower):
            continue
        discovered.append(_normalize_model_name(name_raw))
    return discovered


def _ordered_unique_models(dynamic_models: List[str]) -> List[str]:
    out: List[str] = []
    for model in [*dynamic_models, *_GEMINI_IMAGE_MODELS]:
        if model and model not in out:
            out.append(model)
    return out


def _request_body(prompt: str, image_only: bool) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"] if image_only else ["TEXT", "IMAGE"],
            "temperature": 0.8,
        },
    }


async def _try_gemini_native_image(prompt: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Retourne (png_bytes, mime) ou (None, None)."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return None, None

    async with httpx.AsyncClient(timeout=180.0) as client:
        dynamic_models = await _discover_gemini_image_models(client)
        model_candidates = _ordered_unique_models(dynamic_models)
        for model in model_candidates:
            # Deux variantes de payload + retries courts sur erreurs transitoires.
            for image_only in (True, False):
                body = _request_body(prompt, image_only=image_only)
                for attempt in range(3):
                    try:
                        r = await client.post(_gemini_endpoint(model), json=body)
                        if r.status_code >= 400:
                            logger.warning(
                                "Gemini image %s HTTP %s (try %s): %s",
                                model,
                                r.status_code,
                                attempt + 1,
                                r.text[:300],
                            )
                            if r.status_code in (408, 429, 500, 502, 503, 504):
                                continue
                            break
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
                        logger.warning(
                            "Gemini image model %s error (try %s): %s",
                            model,
                            attempt + 1,
                            e,
                        )
                        continue
    return None, None


async def image_health_check() -> dict:
    """
    Vérifie en live quels modèles Gemini image répondent effectivement.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        return {
            "configured": False,
            "available_models": [],
            "working_models": [],
            "errors": {"config": "GEMINI_API_KEY manquant"},
        }

    probe_prompt = "Simple geometric blue circle on white background."
    working: List[str] = []
    errors: dict = {}
    discovered: List[str] = []
    candidates: List[str] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        discovered = await _discover_gemini_image_models(client)
        candidates = _ordered_unique_models(discovered)
        for model in candidates:
            try:
                body = _request_body(probe_prompt, image_only=True)
                r = await client.post(_gemini_endpoint(model), json=body)
                if r.status_code >= 400:
                    errors[model] = f"HTTP {r.status_code}"
                    continue
                data = r.json()
                parts = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [])
                )
                has_image = False
                for p in parts:
                    inline = p.get("inlineData") or p.get("inline_data")
                    if inline and inline.get("data"):
                        has_image = True
                        break
                if has_image:
                    working.append(model)
                else:
                    errors[model] = "No image bytes in response"
            except Exception as e:
                errors[model] = str(e)[:220]
    return {
        "configured": True,
        "available_models": candidates,
        "discovered_models": discovered,
        "working_models": working,
        "errors": errors,
    }


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
        raise RuntimeError(
            "Génération d’image indisponible : vérifiez GEMINI_API_KEY et l'accès "
            "aux modèles image Gemini (AI Studio).",
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
    caption = f"![]({url})"
    return caption, [url]

