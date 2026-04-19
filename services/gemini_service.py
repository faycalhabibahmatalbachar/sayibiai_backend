"""Google Gemini — texte et vision (PDF/images) avec bascule automatique entre modèles."""

import base64
import logging
from typing import Any, Dict, List, Tuple

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

# Si GEMINI_MODELS est vide ou invalide (ne devrait pas arriver avec le défaut config).
_FALLBACK_MODEL_CHAIN: Tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)

# Erreurs typiques : quota (429), modèle indisponible / mauvais id (404), surcharge (503), timeouts réseau côté API.
_RETRYABLE_STATUS = frozenset({408, 404, 429, 500, 502, 503, 504})


def model_chain() -> List[str]:
    """Liste ordonnée des modèles (priorité décroissante)."""
    s = get_settings()
    chain = s.gemini_model_chain()
    return chain if chain else list(_FALLBACK_MODEL_CHAIN)


def _endpoint(model: str, action: str = "generateContent") -> str:
    settings = get_settings()
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:{action}?key={settings.gemini_api_key}"
    )


async def generate_text(
    system_instruction: str,
    user_parts: List[Dict[str, Any]],
    temperature: float = 0.7,
) -> Tuple[Dict[str, Any], str]:
    """
    Génération texte multi-modal (parts peuvent être text ou inline_data).

    Retourne (réponse JSON API, identifiant du modèle ayant répondu).
    En cas d’échec récupérable (quota, modèle indisponible, etc.), bascule automatiquement
    vers le modèle suivant dans GEMINI_MODELS.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY manquant")
    body = {
        "systemInstruction": {
            "role": "user",
            "parts": [{"text": system_instruction}],
        },
        "contents": [{"role": "user", "parts": user_parts}],
        "generationConfig": {"temperature": temperature},
    }
    models = model_chain()
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, model in enumerate(models):
            url = _endpoint(model, "generateContent")
            try:
                r = await client.post(url, json=body)
                if r.status_code in _RETRYABLE_STATUS and i < len(models) - 1:
                    logger.warning(
                        "Gemini model %s HTTP %s — essai du modèle suivant",
                        model,
                        r.status_code,
                    )
                    last_error = RuntimeError(
                        f"Gemini {model} HTTP {r.status_code}",
                    )
                    continue
                r.raise_for_status()
                return r.json(), model
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in _RETRYABLE_STATUS and i < len(models) - 1:
                    logger.warning(
                        "Gemini model %s HTTP %s — essai du modèle suivant",
                        model,
                        code,
                    )
                    last_error = e
                    continue
                raise
            except httpx.RequestError as e:
                if i < len(models) - 1:
                    logger.warning(
                        "Gemini model %s erreur réseau (%s) — essai du modèle suivant",
                        model,
                        e,
                    )
                    last_error = e
                    continue
                raise

    if last_error:
        raise last_error
    raise RuntimeError("Aucun modèle Gemini disponible dans la chaîne")


def parse_response_text(resp: Dict[str, Any]) -> str:
    """Extrait le texte principal de la réponse Gemini."""
    try:
        parts = resp["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError):
        return ""


async def describe_image_bytes(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
) -> str:
    """OCR / description d'image via Gemini Vision."""
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": mime_type, "data": b64}},
    ]
    resp, _model = await generate_text(
        "Tu es un assistant expert en extraction de texte et d'informations.",
        parts,
    )
    return parse_response_text(resp)


async def describe_pdf_bytes(pdf_bytes: bytes, prompt: str) -> str:
    """Analyse d'un PDF via inline_data application/pdf."""
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "application/pdf", "data": b64}},
    ]
    resp, _model = await generate_text(
        "Tu résumes et extrais les informations clés des documents PDF.",
        parts,
    )
    return parse_response_text(resp)
