"""Détection d’intention « générer une image » pour déclencher l’outil API (même en mode auto)."""

from __future__ import annotations

import re
from typing import Optional

# Demande explicite de création visuelle (évite les faux positifs sur le mot « image » seul).
_IMAGE_INTENT = re.compile(
    r"(?is)"
    r"(?:"
    r"\b(?:génère|générer|crée|créer|dessine|dessiner|affiche|montre|fais-moi|fais moi|create|generate|draw|make|paint)\b"
    r".{0,80}?"
    r"\b(?:une?\s+)?(?:image|visuel|visuelle|logo|affiche|illustration|bannière|banniere|poster|photo|dessin|graphique)\b"
    r"|"
    r"\b(?:je\s+veux|j'aimerais|besoin\s+d['’])\s*(?:une?\s+)?(?:image|logo|affiche|illustration)\b"
    r"|"
    r"\b(?:une?\s+)?(?:image|logo)\s+(?:de|du|des|pour|avec|d['’]|qui|montrant)\b"
    r"|"
    r"\b(?:montre|donne)[- ]moi\s+(?:une?\s+)?(?:image|visuel)\b"
    r")",
)


def should_use_image_generation_tool(
    model_preference: str,
    user_message: str,
    *,
    document_creation_flow: bool = False,
) -> bool:
    """
    True → appeler le moteur d’images (API Gemini), pas seulement le chat texte.
    - Modèle « ChadGpt · Images » : toujours (sauf génération de document).
    - Autres modèles (dont auto) : seulement si l’intention « créer une image » est détectée.
    """
    if document_creation_flow:
        return False
    t = (user_message or "").strip()
    if not t:
        return False
    pref = (model_preference or "auto").strip().lower()
    if pref == "sayibi-images":
        return True
    return bool(_IMAGE_INTENT.search(t))
