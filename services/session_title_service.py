"""Titre de conversation court, généré après le premier échange."""

from __future__ import annotations

import re
from typing import Optional

from core.config import get_settings
from services import groq_service


def _fallback_title(user_message: str) -> str:
    t = re.sub(r"\s+", " ", (user_message or "").strip())
    if len(t) <= 52:
        return t or "Conversation"
    return t[:49].rstrip() + "…"


async def propose_conversation_title(user_message: str, assistant_message: str) -> str:
    """
    Titre court (cœur du sujet), sans guillemets, pour la liste d’historique.
    Repli : début du message utilisateur.
    """
    u = (user_message or "").strip()[:800]
    a = (assistant_message or "").strip()[:800]
    if not u:
        return "Conversation"

    settings = get_settings()
    if not settings.groq_api_key:
        return _fallback_title(u)

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu nommes une conversation de chat. Réponds par UNE seule ligne : un titre court "
                    "(4 à 10 mots max), sans guillemets, sans ponctuation finale inutile, "
                    "captant le thème principal. Langue : même que le message utilisateur. "
                    "Pas de préfixe du type « Conversation : »."
                ),
            },
            {
                "role": "user",
                "content": f"Message utilisateur :\n{u}\n\nPremière réponse assistant (extrait) :\n{a[:400]}",
            },
        ]
        comp = await groq_service.chat_completion(
            messages,
            model=groq_service.DEFAULT_MODEL,
            temperature=0.4,
            max_tokens=48,
        )
        text, _ = groq_service.extract_text_and_usage(comp)
        title = re.sub(r"[\r\n]+", " ", (text or "").strip())
        title = title.strip("\"'«»")
        if len(title) < 3:
            return _fallback_title(u)
        return title[:120]
    except Exception:
        return _fallback_title(u)
