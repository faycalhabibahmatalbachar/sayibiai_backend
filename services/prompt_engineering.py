"""Prompt Engineering invisible — enrichissement automatique des prompts utilisateurs."""

import logging
from typing import Dict, List, Optional, Tuple

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

# Templates par style d'image
_IMAGE_STYLE_TEMPLATES: Dict[str, str] = {
    "realistic": (
        "A photorealistic {subject}, {details}, {composition}, {lighting}, "
        "shot with Canon EOS R5 85mm f/1.4, shallow depth of field, "
        "professional color grading, 8K ultra detailed"
    ),
    "cartoon": (
        "A vibrant cartoon illustration of {subject}, clean lines, flat colors, "
        "Disney/Pixar style, high contrast, expressive characters, concept art quality"
    ),
    "artistic": (
        "A fine art painting of {subject}, impressionist brushstrokes, "
        "rich textures, museum quality, masterful composition, gallery artwork"
    ),
    "3d": (
        "A 3D rendered {subject}, octane render, ray tracing, subsurface scattering, "
        "photorealistic materials, Blender quality, volumetric lighting, 4K render"
    ),
    "anime": (
        "Anime style illustration of {subject}, vibrant colors, clean linework, "
        "Studio Ghibli aesthetic, detailed background, cinematic composition"
    ),
    "minimalist": (
        "Minimalist design of {subject}, clean white space, simple geometric forms, "
        "limited color palette, Swiss design style, high visual impact"
    ),
    "dark": (
        "Dark and dramatic {subject}, moody atmosphere, chiaroscuro lighting, "
        "cinematic noir, deep shadows, high contrast, atmospheric depth"
    ),
}

_DEFAULT_STYLE = "realistic"


async def build_image_prompt(
    raw_prompt: str,
    style: str = "realistic",
    quality_level: str = "standard",
) -> Tuple[str, Dict[str, str]]:
    """
    Enrichit un prompt image brut.
    Retourne (optimized_prompt, metadata_dict).
    """
    s = get_settings()
    style = style.lower() if style else _DEFAULT_STYLE
    template = _IMAGE_STYLE_TEMPLATES.get(style, _IMAGE_STYLE_TEMPLATES[_DEFAULT_STYLE])

    # Analyse du prompt via LLM si OpenAI disponible
    if s.openai_api_key:
        try:
            enriched, meta = await _analyze_with_llm(raw_prompt, style, template, s.openai_api_key)
            return enriched, meta
        except Exception as e:
            logger.warning("LLM prompt enrichment failed: %s", e)

    # Fallback: enrichissement simple basé sur templates
    enriched = _simple_enrich(raw_prompt, style, template, quality_level)
    return enriched, {
        "original": raw_prompt,
        "style": style,
        "method": "template",
    }


async def _analyze_with_llm(
    raw_prompt: str,
    style: str,
    template: str,
    api_key: str,
) -> Tuple[str, Dict[str, str]]:
    """Utilise GPT-4o-mini pour enrichir le prompt."""
    system_msg = (
        "Tu es un expert en génération d'images IA. Analyse le prompt utilisateur "
        "et extrais: sujet principal, détails visuels, composition, éclairage. "
        "Réponds UNIQUEMENT en JSON avec les clés: subject, details, composition, "
        "lighting, added_elements. Sois concis, en anglais."
    )
    user_msg = f"Prompt: {raw_prompt}\nStyle demandé: {style}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 300,
                "temperature": 0.3,
            },
        )
        r.raise_for_status()
        data = r.json()

    import json
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    subject = parsed.get("subject", raw_prompt)
    details = parsed.get("details", "")
    composition = parsed.get("composition", "centered composition")
    lighting = parsed.get("lighting", "natural lighting")
    added = parsed.get("added_elements", "")

    optimized = template.format(
        subject=subject,
        details=details,
        composition=composition,
        lighting=lighting,
    )
    if added:
        optimized += f", {added}"

    return optimized, {
        "original": raw_prompt,
        "subject": subject,
        "style": style,
        "method": "llm",
        "added_elements": added,
    }


def _simple_enrich(
    raw_prompt: str,
    style: str,
    template: str,
    quality_level: str,
) -> str:
    """Enrichissement local sans LLM."""
    quality_suffix = ""
    if quality_level == "hd":
        quality_suffix = ", ultra detailed, 8K resolution, masterpiece quality"
    elif quality_level == "standard":
        quality_suffix = ", detailed, high quality"

    enriched = template.format(
        subject=raw_prompt,
        details="highly detailed",
        composition="balanced composition",
        lighting="perfect lighting",
    )
    return enriched + quality_suffix


async def build_social_post(
    topic: str,
    platform: str,
    tone: str = "professional",
    user_history: Optional[List[dict]] = None,
    trending_tags: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Génère un post optimisé pour les réseaux sociaux.
    Retourne un dict avec 3 variantes A/B/C.
    """
    s = get_settings()
    platform_guides = {
        "twitter": "280 caractères max, accroche percutante, 2-3 hashtags, call-to-action",
        "instagram": "Caption engageante, storytelling, 5-10 hashtags pertinents, emojis",
        "linkedin": "Ton professionnel, contenu de valeur, 1-3 hashtags, conclusion forte",
        "facebook": "Conversationnel, accroche question ou histoire, 1-2 hashtags",
        "tiktok": "Énergetique, tendances actuelles, hook dans les 3 premières secondes, hashtags viraux",
    }
    guide = platform_guides.get(platform.lower(), "Post engageant avec hashtags adaptés")

    if not s.openai_api_key:
        return _fallback_social_post(topic, platform, tone)

    try:
        return await _llm_social_post(topic, platform, tone, guide, trending_tags or [], s.openai_api_key)
    except Exception as e:
        logger.warning("Social post LLM error: %s", e)
        return _fallback_social_post(topic, platform, tone)


async def _llm_social_post(
    topic: str,
    platform: str,
    tone: str,
    guide: str,
    trending: List[str],
    api_key: str,
) -> Dict[str, str]:
    trending_str = ", ".join(trending[:10]) if trending else "aucun"
    system_msg = (
        f"Tu es expert en marketing digital et social media. "
        f"Génère des posts {platform} ({guide}). "
        f"Ton: {tone}. Trending topics: {trending_str}. "
        f"Réponds en JSON avec: variant_a, variant_b, variant_c, "
        f"suggested_hashtags (liste), best_posting_time (string)."
    )

    import json
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": f"Sujet: {topic}"},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 800,
                "temperature": 0.8,
            },
        )
        r.raise_for_status()
        data = r.json()

    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "variant_a": parsed.get("variant_a", ""),
        "variant_b": parsed.get("variant_b", ""),
        "variant_c": parsed.get("variant_c", ""),
        "suggested_hashtags": parsed.get("suggested_hashtags", []),
        "best_posting_time": parsed.get("best_posting_time", "18h-20h"),
    }


def _fallback_social_post(topic: str, platform: str, tone: str) -> Dict[str, str]:
    base = f"🚀 {topic}\n\n#AI #Innovation #{platform.capitalize()}"
    return {
        "variant_a": base,
        "variant_b": f"Découvrez: {topic}\n\n#Tech #Innovation",
        "variant_c": f"💡 {topic} — Qu'en pensez-vous ?\n\n#Réflexion",
        "suggested_hashtags": ["#AI", "#Innovation", f"#{platform}"],
        "best_posting_time": "18h-20h",
    }


async def build_call_secretary_greeting(
    user_name: str,
    caller_name: Optional[str],
    current_time: str,
    custom_template: Optional[str] = None,
) -> str:
    """Construit le message d'accueil du secrétariat vocal."""
    if custom_template:
        msg = custom_template
        msg = msg.replace("{user_name}", user_name)
        msg = msg.replace("{caller_name}", caller_name or "vous")
        msg = msg.replace("{time}", current_time)
        return msg

    caller_part = f", {caller_name}" if caller_name else ""
    return (
        f"Bonjour{caller_part}, vous êtes bien en contact avec le secrétariat de {user_name}. "
        f"Il est actuellement {current_time}. "
        f"Je suis l'assistant de {user_name} et je peux prendre votre message. "
        f"Comment puis-je vous aider ?"
    )


async def build_call_summary_prompt(transcription: str) -> str:
    """Construit le prompt pour résumer un appel entrant."""
    return f"""Analyse cette transcription d'un appel téléphonique et génère un résumé structuré en JSON avec:
- caller_reason: raison principale de l'appel (string)
- urgency_level: "urgent" | "normal" | "non_urgent" | "spam"
- sentiment: "calme" | "pressé" | "énervé" | "heureux"
- key_message: message principal à transmettre (string)
- suggested_actions: liste d'actions suggérées (array de strings)
- callback_needed: true/false

Transcription:
{transcription}

Réponds UNIQUEMENT en JSON valide."""
