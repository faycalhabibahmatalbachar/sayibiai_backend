"""NLU mode agent : réponse JSON structurée (Groq) + indices d’apprentissage Supabase."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from core.config import get_settings
from core.database import get_supabase_admin
from models.agent import AgentStructuredResponse, AgentTurnRequest
from services import groq_service

# Prompt condensé — aligné sur la spec SAYIBI Agent v2 (intentions, permissions, confirmation).
AGENT_SYSTEM_PROMPT = """Tu es le moteur NLU et d'orchestration de SAYIBI AI pour actions natives (SMS, appels, agenda, etc.).

Règles critiques :
1) Analyse l'intention et extrais les entités (contact_name, phone_number, message_content, time, location, urgency).
2) Avant toute action sensible, vérifie les permissions nécessaires (contacts, sms, phone, calendar, camera, location). Si inconnu, utilise action "permission_needed" avec required_permissions.
3) Jamais d'envoi SMS / appel / email / suppression sans confirmation explicite de l'utilisateur. Si l'action est prête mais pas confirmée : "confirm_needed".
4) Ambiguïtés : plusieurs contacts → "clarify_contact" avec matches ; plusieurs numéros → "clarify_number". Aucun contact → "ask_missing_info".
5) Si le message est une confirmation ("oui", "ok", "envoie", "vas-y", "confirme") et que pending décrit une action en attente → "execute_action" avec les champs du pending. Si annulation ("non", "annule") → action "cancelled".
6) Si le client a fourni contact_search_results, utilise-les pour décider (ne invente pas de contacts).
7) message_to_user : français naturel, court. Masque partiellement les numéros dans les messages utilisateur (+235 6 12 ••• •• 78).
8) Les outils réels sont côté client ; si tu as besoin de données contacts, réponds par action "search_contacts" avec payload.query (le client renverra les résultats au tour suivant).
9) Pour les médias locaux du téléphone: utilise "search_local_media" avec payload.query (et éventuellement payload.media_type=image|video). Pour ouvrir un élément choisi: "open_local_media" avec payload.path.

Valeurs autorisées pour "action" (string) :
search_contacts | get_contact_details | send_sms | make_call | send_email | send_whatsapp |
create_event | search_events | update_event | delete_event | create_reminder | set_alarm | update_alarm | delete_alarm | view_alarms |
check_permission | request_permission | open_app | take_photo | get_location | search_local_media | open_local_media |
web_search | open_map | get_directions |
confirm_needed | clarify_contact | clarify_number | ask_missing_info |
permission_needed | alternative_suggested | execute_action | cancelled |
log_action | error | rate_limit_exceeded

Tu réponds UNIQUEMENT par un objet JSON valide avec exactement ces clés :
thinking, action, payload, next_steps, message_to_user, confidence, ambiguities
- payload : objet (peut être vide)
- next_steps : tableau de strings
- ambiguities : tableau (strings ou objets courts)
- confidence : nombre entre 0 et 1
"""


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        return m.group(1).strip()
    return t


def _parse_agent_json(raw: str) -> AgentStructuredResponse:
    cleaned = _strip_json_fence(raw)
    data = json.loads(cleaned)
    return AgentStructuredResponse.model_validate(data)


def _hint_query_from_body(body: AgentTurnRequest) -> str:
    if body.pending and isinstance(body.pending, dict):
        pl = body.pending.get("payload")
        if isinstance(pl, dict):
            for k in ("query", "contact_name"):
                v = pl.get(k)
                if v:
                    return str(v).strip().lower()[:200]
    return body.message.strip().lower()[:200]


async def _contact_resolution_hints(user_id: str, query: str) -> str:
    """Résumé textuel des choix passés pour une requête (ex. prénom)."""
    c = get_supabase_admin()
    if not c or not query.strip():
        return ""
    qn = query.strip().lower()[:200]
    try:
        res = (
            c.table("contact_resolutions")
            .select("contact_id_chosen, display_name_snapshot")
            .eq("user_id", user_id)
            .eq("query", qn)
            .order("created_at", desc=True)
            .limit(40)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return ""
        from collections import Counter

        keys = [r["contact_id_chosen"] for r in rows]
        cnt = Counter(keys)
        top = cnt.most_common(3)
        parts = []
        for cid, n in top:
            name = next(
                (r.get("display_name_snapshot") for r in rows if r["contact_id_chosen"] == cid),
                cid,
            )
            parts.append(f"{name or cid} (×{n})")
        return "Préférences enregistrées pour cette requête : " + ", ".join(parts) + ". Privilégier ces contacts si pertinent."
    except Exception:
        return ""


async def run_agent_turn(user_id: str, body: AgentTurnRequest) -> tuple[AgentStructuredResponse, Optional[int]]:
    """Un tour de conversation agent ; retourne (réponse structurée, tokens Groq si dispo)."""
    settings = get_settings()
    if not settings.groq_api_key:
        return (
            AgentStructuredResponse(
                thinking="Groq non configuré",
                action="error",
                payload={"error_type": "configuration", "error_message": "GROQ_API_KEY manquant"},
                message_to_user="Le mode agent n'est pas disponible (configuration serveur).",
                confidence=0.0,
            ),
            None,
        )

    hint_query = _hint_query_from_body(body)
    hints = await _contact_resolution_hints(user_id, hint_query)

    ctx_parts: List[str] = []
    if body.pending:
        ctx_parts.append("État pending (JSON) :\n" + json.dumps(body.pending, ensure_ascii=False))
    if body.contact_search_results is not None:
        ctx_parts.append(
            "Résultats search_contacts (JSON) :\n"
            + json.dumps(body.contact_search_results, ensure_ascii=False)[:12000]
        )
    if body.permission_state:
        ctx_parts.append("Permissions client :\n" + json.dumps(body.permission_state, ensure_ascii=False))
    if body.memory_context:
        ctx_parts.append(
            "Mémoire client (historique des actions précédentes) :\n"
            + body.memory_context.strip()[:8000]
        )
    if hints:
        ctx_parts.append(hints)

    user_content = body.message.strip()
    if ctx_parts:
        user_content = "\n\n".join(ctx_parts) + "\n\n---\nMessage utilisateur :\n" + user_content

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw_text = ""
    tokens: Optional[int] = None
    try:
        try:
            comp = await groq_service.chat_completion(
                messages,
                temperature=0.2,
                max_tokens=2048,
                json_mode=True,
            )
        except httpx.HTTPStatusError:
            comp = await groq_service.chat_completion(
                messages,
                temperature=0.2,
                max_tokens=2048,
                json_mode=False,
            )
        raw_text, tokens = groq_service.extract_text_and_usage(comp)
        return _parse_agent_json(raw_text), tokens
    except (json.JSONDecodeError, ValidationError):
        try:
            comp = await groq_service.chat_completion(
                messages,
                temperature=0.1,
                max_tokens=2048,
                json_mode=False,
            )
            raw_text, tokens = groq_service.extract_text_and_usage(comp)
            return _parse_agent_json(raw_text), tokens
        except Exception as e2:
            return (
                AgentStructuredResponse(
                    thinking="Parse JSON échoué",
                    action="error",
                    payload={"error_type": "parse_error", "error_message": str(e2)},
                    message_to_user="Je n'ai pas pu interpréter la réponse. Reformulez ou réessayez.",
                    confidence=0.0,
                ),
                tokens,
            )
    except Exception as e:
        return (
            AgentStructuredResponse(
                thinking=str(e),
                action="error",
                payload={"error_type": "agent_failure", "error_message": str(e)},
                message_to_user="Une erreur est survenue. Réessayez dans un instant.",
                confidence=0.0,
            ),
            None,
        )
