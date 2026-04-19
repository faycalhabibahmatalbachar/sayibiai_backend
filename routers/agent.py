"""Mode agent — tours JSON, journalisation, apprentissage contacts."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from core.deps import get_current_user_id
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from models.agent import AgentLogRequest, AgentTurnRequest, ContactResolutionBody
from services import agent_nlu_service

router = APIRouter(prefix="/agent", tags=["agent"])


def _db():
    return get_supabase_admin()


@router.post("/turn")
async def agent_turn(body: AgentTurnRequest, user_id: str = Depends(get_current_user_id)):
    """Un tour NLU : renvoie la structure JSON agent (thinking, action, payload, …)."""
    try:
        resp, tokens = await agent_nlu_service.run_agent_turn(user_id, body)
    except Exception as e:
        return error_response(str(e), 500)
    data: Dict[str, Any] = resp.model_dump()
    if tokens is not None:
        data["tokens_used"] = tokens
    return success_response(data, resp.message_to_user or "OK")


@router.post("/log")
async def agent_log(body: AgentLogRequest, user_id: str = Depends(get_current_user_id)):
    """Enregistre une exécution ou une erreur côté client (SMS envoyé, etc.)."""
    c = _db()
    if not c:
        return success_response({"stored": False}, "Sans DB")
    try:
        row = {
            "user_id": user_id,
            "action_type": body.action_type,
            "contact_id": body.contact_id,
            "phone_masked": body.phone_masked,
            "message_preview": (body.message_preview or "")[:500] if body.message_preview else None,
            "status": body.status,
            "ambiguity_type": body.ambiguity_type,
            "confidence": body.confidence,
            "client_meta": body.client_meta,
        }
        c.table("agent_action_logs").insert(row).execute()
        return success_response({"stored": True}, "Action enregistrée")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/contact-resolution")
async def save_contact_resolution(
    body: ContactResolutionBody,
    user_id: str = Depends(get_current_user_id),
):
    """Mémorise le contact choisi pour une requête (homonymes)."""
    c = _db()
    if not c:
        return success_response({"stored": False}, "Sans DB")
    try:
        qn = body.query.strip().lower()[:200]
        c.table("contact_resolutions").insert(
            {
                "user_id": user_id,
                "query": qn,
                "contact_id_chosen": body.contact_id_chosen[:500],
                "display_name_snapshot": (body.display_name_snapshot or "")[:300] or None,
                "resolution_type": body.resolution_type[:80],
            }
        ).execute()
        return success_response({"stored": True}, "Préférence enregistrée")
    except Exception as e:
        return error_response(str(e), 500)
