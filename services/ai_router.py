"""Routage intelligent entre LLM + injection recherche web + historique."""

import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langdetect import detect

from core.config import get_settings
from core.models_config import (
    SayibiModel,
    augment_message_for_create_mode,
    resolve_sayibi_preference,
)
from services import (
    chat_creation_service,
    device_intent,
    gemini_service,
    groq_service,
    image_gen_service,
    mistral_service,
    search_service,
)

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


def _sms_system_addon(destination_e164: str) -> str:
    return (
        "\n\n[Mode SMS — l’utilisateur enverra ce texte depuis SON téléphone (carte SIM), "
        "sans passerelle payante. "
        f"Destinataire (ne pas recopier le numéro dans le corps du message) : {destination_e164}. "
        "Réponds par le SEUL texte du SMS, sans introduction ni guillemets, sans markdown. "
        "Message court et naturel.]"
    )


def system_prompt_for_lang(
    lang: str,
    personality: Optional[str],
    expert_mode: bool,
) -> str:
    """Construit le message système multilingue."""
    base_fr = (
        "Tu es SAYIBI AI, assistant bienveillant et précis pour le Tchad et le monde francophone. "
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
    *,
    force: bool = False,
) -> str:
    """Si besoin (ou si force), exécute une recherche web et résume pour le prompt."""
    if not force and not should_search_web(message):
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
    *,
    force_web_search: bool = False,
    document_id: Optional[str] = None,
    create_mode: bool = False,
    create_type: Optional[str] = None,
    model_preference: Optional[str] = None,
    sms_destination_e164: Optional[str] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    """Retourne (langue détectée, messages OpenAI pour l'API)."""
    lang = language if language and language != "auto" else detect_language_text(user_message)
    prepared = augment_message_for_create_mode(user_message, create_mode, create_type)
    if document_id:
        prepared = (
            f"{prepared}\n\n"
            f"[Référence document: {document_id} — l'utilisateur a joint un fichier à analyser.]"
        )
    enriched = await maybe_inject_web_context(prepared, lang, force=force_web_search)
    sys_msg = system_prompt_for_lang(lang, personality, expert_mode)
    if sms_destination_e164:
        sys_msg += _sms_system_addon(sms_destination_e164)
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
    groq_ov, mistral_ov, routing_hint, display_label = resolve_sayibi_preference(model_preference)
    if pref in ("groq", "gemini", "mistral"):
        routing_hint = pref

    def _label(actual: str) -> str:
        if model_preference and str(model_preference).lower().startswith("sayibi-"):
            return f"{display_label} ({actual})"
        return actual

    async def try_mistral(model_name: Optional[str] = None) -> Tuple[str, Optional[int]]:
        comp = await mistral_service.chat_completion(
            messages,
            model=model_name or mistral_service.DEFAULT_MODEL,
        )
        return mistral_service.extract_text_and_usage(comp)

    async def try_groq(model_name: Optional[str] = None) -> Tuple[str, Optional[int]]:
        comp = await groq_service.chat_completion(
            messages,
            model=model_name or groq_service.DEFAULT_MODEL,
        )
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
        return text, _label(model_used), tok

    if routing_hint == "mistral" and settings.mistral_api_key:
        text, tok = await try_mistral(mistral_ov)
        used = mistral_ov or mistral_service.DEFAULT_MODEL
        return text, _label(used), tok
    if routing_hint == "groq" and settings.groq_api_key:
        text, tok = await try_groq(groq_ov)
        used = groq_ov or groq_service.DEFAULT_MODEL
        return text, _label(used), tok
    if routing_hint == "gemini" and settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, _label(model_used), tok

    if pref == "mistral" and settings.mistral_api_key:
        text, tok = await try_mistral(mistral_ov)
        used = mistral_ov or mistral_service.DEFAULT_MODEL
        return text, _label(used), tok
    if pref == "groq" and settings.groq_api_key:
        text, tok = await try_groq(groq_ov)
        used = groq_ov or groq_service.DEFAULT_MODEL
        return text, _label(used), tok
    if pref == "gemini" and settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, _label(model_used), tok

    if lang == "fr" and settings.mistral_api_key:
        try:
            text, tok = await try_mistral(mistral_ov)
            used = mistral_ov or mistral_service.DEFAULT_MODEL
            return text, _label(used), tok
        except Exception:
            pass

    if settings.groq_api_key:
        try:
            text, tok = await try_groq(groq_ov)
            used = groq_ov or groq_service.DEFAULT_MODEL
            return text, _label(used), tok
        except Exception:
            pass

    if settings.gemini_api_key:
        text, tok, model_used = await try_gemini_text()
        return text, _label(model_used), tok

    if settings.mistral_api_key:
        text, tok = await try_mistral(mistral_ov)
        used = mistral_ov or mistral_service.DEFAULT_MODEL
        return text, _label(used), tok

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
    *,
    force_web_search: bool = False,
    document_id: Optional[str] = None,
    create_mode: bool = False,
    create_type: Optional[str] = None,
    user_id: str = "",
) -> Tuple[str, str, Optional[int], Dict[str, Any]]:
    """
    Retourne (réponse texte, nom du modèle utilisé, tokens estimés, métadonnées).
    Métadonnées : image_urls, sources (web), generated_file, etc.
    """
    meta: Dict[str, Any] = {}
    pref = (model_preference or "auto").strip().lower()

    if pref == SayibiModel.IMAGES.value:
        text, urls = await image_gen_service.generate_image_and_upload(
            user_message,
            user_id or "anon",
        )
        meta["image_urls"] = urls
        return text, "Sayibi Images", None, meta

    if create_mode and create_type:
        text, model, tok, cmeta = await chat_creation_service.create_from_chat(
            user_message,
            create_type,
            user_id or "anon",
        )
        meta.update(cmeta)
        return text, model, tok, meta

    sms = device_intent.parse_send_sms_intent(user_message)

    if force_web_search:
        try:
            meta["sources"] = await search_service.web_search(user_message, max_results=6)
        except Exception:
            meta["sources"] = []
        try:
            meta["search_images"] = await search_service.web_image_search(user_message, max_results=8)
        except Exception:
            meta["search_images"] = []

    lang, messages = await build_chat_messages(
        user_message,
        history,
        language,
        personality,
        expert_mode,
        force_web_search=force_web_search,
        document_id=document_id,
        create_mode=False,
        create_type=None,
        model_preference=model_preference,
        sms_destination_e164=sms.to_e164 if sms else None,
    )
    text, model_used, tokens = await _route_llm(messages, lang, model_preference, need_vision)
    if sms:
        meta["device_action"] = {
            "type": "send_sms",
            "to": sms.to_e164,
            "body": text.strip(),
        }
    return text, model_used, tokens, meta


async def stream_chat(
    user_message: str,
    history: List[Dict[str, str]],
    language: Optional[str],
    model_preference: Optional[str],
    personality: Optional[str] = None,
    expert_mode: bool = False,
    *,
    force_web_search: bool = False,
    document_id: Optional[str] = None,
    create_mode: bool = False,
    create_type: Optional[str] = None,
    user_id: str = "",
    metadata_out: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[str]:
    """Flux texte — Groq streaming seulement si routage groq/auto ; sinon génération réelle ou fallback."""
    settings = get_settings()
    meta = metadata_out if metadata_out is not None else {}
    pref = (model_preference or "auto").strip().lower()

    if pref == SayibiModel.IMAGES.value:
        for ch in "✨ Génération de l'image avec le moteur SAYIBI…\n\n":
            yield ch
        text, urls = await image_gen_service.generate_image_and_upload(
            user_message,
            user_id or "anon",
        )
        meta["image_urls"] = urls
        for ch in text:
            yield ch
        return

    if create_mode and create_type:
        for ch in "📄 Génération du document (fichier réel)…\n\n":
            yield ch
        text, _, _, cmeta = await chat_creation_service.create_from_chat(
            user_message,
            create_type,
            user_id or "anon",
        )
        meta.update(cmeta)
        for ch in text:
            yield ch
        return

    sms = device_intent.parse_send_sms_intent(user_message)

    if force_web_search:
        if "sources" not in meta:
            try:
                meta["sources"] = await search_service.web_search(user_message, max_results=6)
            except Exception:
                meta["sources"] = []
        if "search_images" not in meta:
            try:
                meta["search_images"] = await search_service.web_image_search(user_message, max_results=8)
            except Exception:
                meta["search_images"] = []

    lang, messages = await build_chat_messages(
        user_message,
        history,
        language,
        personality,
        expert_mode,
        force_web_search=force_web_search,
        document_id=document_id,
        create_mode=False,
        create_type=None,
        model_preference=model_preference,
        sms_destination_e164=sms.to_e164 if sms else None,
    )
    groq_ov, _, routing_hint, _ = resolve_sayibi_preference(model_preference)
    p2 = (model_preference or "auto").lower()
    if p2 in ("groq", "gemini", "mistral"):
        routing_hint = p2

    stream_model = groq_ov or groq_service.DEFAULT_MODEL
    if settings.groq_api_key and routing_hint in ("auto", "groq"):
        acc: List[str] = []
        async for chunk in groq_service.chat_completion_stream(messages, model=stream_model):
            acc.append(chunk)
            yield chunk
        if sms:
            meta["device_action"] = {
                "type": "send_sms",
                "to": sms.to_e164,
                "body": "".join(acc).strip(),
            }
        return

    text, _, _ = await _route_llm(messages, lang, model_preference, False)
    for ch in text:
        yield ch
    if sms:
        meta["device_action"] = {
            "type": "send_sms",
            "to": sms.to_e164,
            "body": text.strip(),
        }
