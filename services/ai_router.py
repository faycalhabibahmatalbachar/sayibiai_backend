"""Routage intelligent entre LLM + injection recherche web + historique."""

import re
from typing import AsyncIterator, Dict, List, Optional, Tuple

from langdetect import detect

from core.config import get_settings
from services import gemini_service, groq_service, mistral_service, search_service

# Mots-clés simples pour déclencher une recherche web (FR/EN)
WEB_HINT_PATTERNS = re.compile(
    r"\b(aujourd'hui|actualit|prix|météo|weather|news|latest|who is|combien coûte|"
    r"cours de|taux de|score)\b",
    re.IGNORECASE,
)


def detect_language_text(text: str) -> str:
    """Détection automatique fr / ar / en (repli en)."""
    t = text.strip()
    if not t:
        return "en"
    try:
        code = detect(t)
    except Exception:
        return "en"
    if code.startswith("ar"):
        return "ar"
    if code.startswith("fr"):
        return "fr"
    return "en"


def system_prompt_for_lang(
    lang: str,
    personality: Optional[str],
    expert_mode: bool,
) -> str:
    """Construit le message système multilingue."""
    base_fr = (
        "Tu es SAYIBI AI, assistant bienveillant et précis pour l'Afrique et le monde francophone. "
        "Réponds dans la même langue que l'utilisateur. "
    )
    if expert_mode:
        base_fr += "Mode expert : détails techniques et nuances autorisés. "
    else:
        base_fr += "Mode simple : phrases courtes et claires. "
    if personality:
        base_fr += f"Rôle demandé : {personality}. "
    if lang == "ar":
        return (
            "أنت مساعد SAYIBI AI. أجب بالعربية بوضوح واحترام. "
            + (f"الدور: {personality}. " if personality else "")
        )
    if lang == "en":
        return (
            "You are SAYIBI AI, a helpful multilingual assistant. Answer clearly in English. "
            + (f"Persona: {personality}. " if personality else "")
        )
    return base_fr


def should_search_web(message: str) -> bool:
    """Heuristique : requête factuelle / temps réel."""
    if WEB_HINT_PATTERNS.search(message):
        return True
    if message.strip().endswith("?"):
        lower = message.lower()
        if any(
            w in lower
            for w in (
                "qui est",
                "what is",
                "when did",
                "où ",
                "where ",
                "combien",
                "how much",
            )
        ):
            return True
    return False


async def maybe_inject_web_context(
    message: str,
    _lang: str,
) -> str:
    """Si besoin, exécute une recherche web et résume brièvement pour le prompt."""
    if not should_search_web(message):
        return message
    try:
        results = await search_service.web_search(message, max_results=4)
    except Exception:
        return message
    if not results:
        return message
    lines = []
    for r in results[:4]:
        lines.append(f"- {r.get('title','')}: {r.get('snippet','')[:400]} ({r.get('url','')})")
    block = "\n".join(lines)
    return (
        f"{message}\n\n[Contexte web récent pour appuyer la réponse — sources :\n{block}\n]"
    )


async def build_chat_messages(
    user_message: str,
    history: List[Dict[str, str]],
    language: Optional[str],
    personality: Optional[str],
    expert_mode: bool,
) -> Tuple[str, List[Dict[str, str]]]:
    """Retourne (langue détectée, messages OpenAI pour l'API)."""
    lang = language if language and language != "auto" else detect_language_text(user_message)
    enriched = await maybe_inject_web_context(user_message, lang)
    sys_msg = system_prompt_for_lang(lang, personality, expert_mode)
    messages: List[Dict[str, str]] = [{"role": "system", "content": sys_msg}]
    for h in history[-10:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": enriched})
    return lang, messages


async def _route_llm(
    messages: List[Dict[str, str]],
    lang: str,
    model_preference: Optional[str],
    need_vision: bool = False,
) -> Tuple[str, str, Optional[int]]:
    """Chaîne de fallback LLM à partir d'une liste de messages déjà construite."""
    settings = get_settings()
    sys_msg = messages[0]["content"]
    pref = (model_preference or "auto").lower()

    async def try_mistral() -> Tuple[str, Optional[int]]:
        comp = await mistral_service.chat_completion(messages)
        return mistral_service.extract_text_and_usage(comp)

    async def try_groq() -> Tuple[str, Optional[int]]:
        comp = await groq_service.chat_completion(messages)
        return groq_service.extract_text_and_usage(comp)

    async def try_gemini_text() -> Tuple[str, Optional[int], str]:
        parts = []
        for m in messages:
            parts.append(f"{m['role']}: {m['content']}")
        user_block = "\n".join(parts)
        resp, model_used = await gemini_service.generate_text(
            sys_msg,
            [{"text": user_block}],
        )
        text = gemini_service.parse_response_text(resp)
        return text, None, model_used

    if need_vision and settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, model_used, tok

    if pref == "mistral" and settings.mistral_api_key:
        text, tok = await try_mistral()
        return text, "mistral-large-latest", tok
    if pref == "groq" and settings.groq_api_key:
        text, tok = await try_groq()
        return text, groq_service.DEFAULT_MODEL, tok
    if pref == "gemini" and settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, model_used, tok

    if lang == "fr" and settings.mistral_api_key:
        try:
            text, tok = await try_mistral()
            return text, "mistral-large-latest", tok
        except Exception:
            pass

    if settings.groq_api_key:
        try:
            text, tok = await try_groq()
            return text, groq_service.DEFAULT_MODEL, tok
        except Exception:
            pass

    if settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, model_used, tok

    if settings.mistral_api_key:
        text, tok = await try_mistral()
        return text, "mistral-large-latest", tok

    raise RuntimeError(
        "Aucune clé LLM configurée (GROQ, GEMINI ou MISTRAL).",
    )


async def run_chat(
    user_message: str,
    history: List[Dict[str, str]],
    language: Optional[str],
    model_preference: Optional[str],
    personality: Optional[str] = None,
    expert_mode: bool = False,
    need_vision: bool = False,
) -> Tuple[str, str, Optional[int]]:
    """Retourne (réponse texte, nom du modèle utilisé, tokens estimés)."""
    lang, messages = await build_chat_messages(
        user_message,
        history,
        language,
        personality,
        expert_mode,
    )
    return await _route_llm(messages, lang, model_preference, need_vision)


async def stream_chat(
    user_message: str,
    history: List[Dict[str, str]],
    language: Optional[str],
    model_preference: Optional[str],
    personality: Optional[str] = None,
    expert_mode: bool = False,
) -> AsyncIterator[str]:
    """Flux texte — Groq streaming si dispo et préférence compatible."""
    settings = get_settings()
    lang, messages = await build_chat_messages(
        user_message,
        history,
        language,
        personality,
        expert_mode,
    )
    pref = (model_preference or "auto").lower()

    if settings.groq_api_key and pref in ("auto", "groq"):
        async for chunk in groq_service.chat_completion_stream(messages):
            yield chunk
        return

    text, _, _ = await _route_llm(messages, lang, model_preference, False)
    for ch in text:
        yield ch
