"""Modération de contenu — OpenAI Moderation API + règles locales."""

import hashlib
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from core.config import get_settings
from core.database import get_supabase_admin

logger = logging.getLogger(__name__)

# Catégories à bloquer immédiatement
_BLOCK_CATEGORIES = {
    "sexual/minors",
    "hate/threatening",
    "violence/graphic",
    "self-harm/intent",
    "self-harm/instructions",
}

# Seuils de confiance par catégorie
_THRESHOLD: Dict[str, float] = {
    "sexual": 0.85,
    "sexual/minors": 0.5,
    "hate": 0.85,
    "hate/threatening": 0.6,
    "harassment": 0.9,
    "harassment/threatening": 0.7,
    "violence": 0.9,
    "violence/graphic": 0.7,
    "self-harm": 0.85,
    "self-harm/intent": 0.5,
    "self-harm/instructions": 0.5,
}


async def check_content(
    text: str,
    user_id: str,
    context: str = "text",
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Vérifie si le contenu est acceptable.
    Retourne (is_safe, message_refus, flags).
    """
    s = get_settings()
    flags: List[str] = []

    # Filtre local rapide pour les cas évidents
    lower = text.lower()
    local_triggers = ["child pornography", "cp porn", "snuff film", "terrorism guide"]
    for trigger in local_triggers:
        if trigger in lower:
            flags.append("local_filter")
            await _log_moderation(user_id, text, flags, context, blocked=True)
            return False, "Ce contenu ne peut pas être traité.", flags

    # Appel OpenAI Moderation si clé disponible
    if s.openai_api_key:
        try:
            flagged, openai_flags = await _openai_moderation(text, s.openai_api_key)
            if flagged:
                flags.extend(openai_flags)
                await _log_moderation(user_id, text, flags, context, blocked=True)
                # Incrémenter le compteur de violations
                await _increment_violation_count(user_id)
                return (
                    False,
                    "Ce contenu a été refusé car il ne respecte pas nos conditions d'utilisation.",
                    flags,
                )
        except Exception as e:
            logger.warning("Moderation API error: %s", e)

    await _log_moderation(user_id, text, flags, context, blocked=False)
    return True, None, flags


async def _openai_moderation(text: str, api_key: str) -> Tuple[bool, List[str]]:
    """Appelle l'API Moderation d'OpenAI."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/moderations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": text},
        )
        r.raise_for_status()
        data = r.json()

    result = data.get("results", [{}])[0]
    flagged = result.get("flagged", False)
    categories = result.get("categories", {})
    scores = result.get("category_scores", {})

    triggered: List[str] = []
    for cat, is_set in categories.items():
        score = scores.get(cat, 0.0)
        threshold = _THRESHOLD.get(cat, 0.8)
        if cat in _BLOCK_CATEGORIES and score > 0.3:
            triggered.append(cat)
        elif is_set and score > threshold:
            triggered.append(cat)

    return bool(triggered), triggered


async def _log_moderation(
    user_id: str,
    text: str,
    flags: List[str],
    context: str,
    blocked: bool,
) -> None:
    """Stocke l'événement de modération (prompt haché pour la vie privée)."""
    try:
        c = get_supabase_admin()
        if not c:
            return
        hashed_prompt = hashlib.sha256(text.encode()).hexdigest()
        c.table("moderation_logs").insert(
            {
                "user_id": user_id,
                "prompt_hash": hashed_prompt,
                "flags": flags,
                "context": context,
                "blocked": blocked,
            }
        ).execute()
    except Exception as e:
        logger.debug("moderation log error: %s", e)


async def _increment_violation_count(user_id: str) -> None:
    """Incrémente le compteur de violations ; alerte après 3."""
    try:
        c = get_supabase_admin()
        if not c:
            return
        res = (
            c.table("moderation_logs")
            .select("id")
            .eq("user_id", user_id)
            .eq("blocked", True)
            .execute()
        )
        count = len(res.data or [])
        if count >= 3:
            logger.warning("User %s has %d moderation violations!", user_id, count)
    except Exception as e:
        logger.debug("violation count error: %s", e)
