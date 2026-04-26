"""
Configuration des modèles ChadGpt (identifiants API sayibi-* conservés pour compatibilité).
Chaque entrée mappe vers un ou plusieurs modèles LLM réels.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class SayibiModel(str, Enum):
    AUTO = "auto"
    REFLEXION = "sayibi-reflexion"
    IMAGES = "sayibi-images"
    NADIRX = "sayibi-nadirx"
    VOIX = "sayibi-voix"
    CODE = "sayibi-code"
    CREATION = "sayibi-creation"


@dataclass
class ModelConfig:
    display_name: str
    tagline: str
    description: str
    backend_model: str
    provider: str  # groq | gemini | mistral
    capabilities: List[str]
    icon: str
    color: str
    supports_images: bool
    supports_vision: bool
    supports_files: bool


SAYIBI_MODELS: dict[SayibiModel, ModelConfig] = {
    SayibiModel.AUTO: ModelConfig(
        display_name="Auto",
        tagline="Laisse ChadGpt choisir",
        description="Sélection automatique du meilleur modèle selon votre requête",
        backend_model="llama-3.3-70b-versatile",
        provider="groq",
        capabilities=["chat", "analyse", "code", "creation"],
        icon="⚡",
        color="#6C63FF",
        supports_images=False,
        supports_vision=True,
        supports_files=True,
    ),
    SayibiModel.REFLEXION: ModelConfig(
        display_name="ChadGpt Réflexion",
        tagline="Notre modèle le plus intelligent",
        description="Raisonnement profond, analyses complexes, problèmes difficiles. "
        "Prend le temps de réfléchir avant de répondre.",
        backend_model="deepseek-r1-distill-llama-70b",
        provider="groq",
        capabilities=["deep_thinking", "math", "logic", "research", "complex_analysis"],
        icon="🧠",
        color="#8B5CF6",
        supports_images=False,
        supports_vision=False,
        supports_files=True,
    ),
    SayibiModel.IMAGES: ModelConfig(
        display_name="ChadGpt Images",
        tagline="Crée des images depuis vos descriptions",
        description="Génération d'images professionnelles, illustrations, designs "
        "depuis une description texte.",
        backend_model="gemini-2.0-flash-exp",
        provider="gemini",
        capabilities=["image_generation", "image_editing", "visual_creation"],
        icon="🎨",
        color="#EC4899",
        supports_images=True,
        supports_vision=True,
        supports_files=False,
    ),
    SayibiModel.NADIRX: ModelConfig(
        display_name="ChadGpt NadirX",
        tagline="Expert analyse & données",
        description="Analyse de documents complexes, tableaux, données financières, "
        "contrats juridiques. Le plus précis pour l'extraction d'informations.",
        backend_model="gemini-1.5-pro",
        provider="gemini",
        capabilities=["document_analysis", "data_extraction", "ocr", "tables", "contracts"],
        icon="📊",
        color="#00D4AA",
        supports_images=True,
        supports_vision=True,
        supports_files=True,
    ),
    SayibiModel.VOIX: ModelConfig(
        display_name="ChadGpt Voix",
        tagline="Optimisé pour les conversations vocales",
        description="Réponses courtes, claires et naturelles. "
        "Idéal pour l'assistant vocal mains-libres.",
        backend_model="mixtral-8x7b-32768",
        provider="groq",
        capabilities=["voice_chat", "fast_response", "concise"],
        icon="🎙️",
        color="#F59E0B",
        supports_images=False,
        supports_vision=False,
        supports_files=False,
    ),
    SayibiModel.CODE: ModelConfig(
        display_name="ChadGpt Code",
        tagline="Développeur IA expert",
        description="Génération, débogage et explication de code. "
        "Supporte +50 langages de programmation.",
        backend_model="llama-3.3-70b-versatile",
        provider="groq",
        capabilities=["code_generation", "debug", "explain", "refactor"],
        icon="💻",
        color="#3B82F6",
        supports_images=False,
        supports_vision=True,
        supports_files=True,
    ),
    SayibiModel.CREATION: ModelConfig(
        display_name="ChadGpt Création",
        tagline="Génère CV, lettres & rapports Pro",
        description="Spécialisé dans la création de documents professionnels "
        "avec mise en page, design et formatage avancé.",
        backend_model="mistral-large-latest",
        provider="mistral",
        capabilities=["cv_generation", "letter_writing", "report", "excel", "pdf"],
        icon="✨",
        color="#10B981",
        supports_images=False,
        supports_vision=False,
        supports_files=True,
    ),
}


def _match_sayibi(pref: str) -> Optional[SayibiModel]:
    p = (pref or "").strip().lower()
    for m in SayibiModel:
        if m.value == p:
            return m
    return None


def resolve_sayibi_preference(
    model_preference: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    À partir de model_preference (auto, groq, gemini, mistral, sayibi-*) retourne:
    (groq_model_override, mistral_model_override, routing_hint, display_label)

    routing_hint: 'groq' | 'gemini' | 'mistral' | 'auto' | None
    Si une préférence sayibi-* est reconnue, routing_hint indique le fournisseur à privilégier.
    """
    raw = (model_preference or "auto").strip().lower()
    if raw in ("groq", "gemini", "mistral", "auto"):
        return None, None, raw if raw != "auto" else "auto", raw

    sm = _match_sayibi(raw)
    if sm is None:
        return None, None, "auto", raw

    cfg = SAYIBI_MODELS[sm]
    display = cfg.display_name
    if cfg.provider == "groq":
        return cfg.backend_model, None, "groq", display
    if cfg.provider == "mistral":
        return None, cfg.backend_model, "mistral", display
    if cfg.provider == "gemini":
        return None, None, "gemini", display
    return None, None, "auto", display


def augment_message_for_create_mode(
    message: str,
    create_mode: bool,
    create_type: Optional[str],
) -> str:
    if not create_mode:
        return message
    ct = (create_type or "cv").lower()
    hints = {
        "cv": "[Mode création: CV professionnel — structure claire, sections, ton formel.]",
        "letter": "[Mode création: lettre de motivation — ton adapté, mise en forme.]",
        "report": "[Mode création: rapport PDF — plan, titres, synthèse.]",
        "excel": "[Mode création: tableur — colonnes, formules suggérées, tableau clair.]",
    }
    return f"{message}\n\n{hints.get(ct, hints['cv'])}"
