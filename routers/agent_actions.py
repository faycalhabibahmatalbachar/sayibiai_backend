"""Actions agent backend: SMS queue + contacts resources."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import sms_action_service

router = APIRouter(prefix="/agent/actions", tags=["agent-actions"])


class SmsDraftBody(BaseModel):
    to_e164: str = Field(..., min_length=3)
    body: str = Field(..., min_length=1, max_length=2000)
    contact_identity_id: Optional[str] = None
    request_id: Optional[str] = None
    client_meta: Optional[Dict[str, Any]] = None


class SmsStatusBody(BaseModel):
    status: str = Field(..., pattern="^(draft|confirmed|sent|failed|cancelled)$")
    error_message: Optional[str] = None


class ContactsSyncBody(BaseModel):
    contacts: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/sms/draft")
async def sms_draft(body: SmsDraftBody, user_id: str = Depends(get_current_user_id)):
    try:
        row = await sms_action_service.create_sms_draft(
            user_id,
            to_e164=body.to_e164,
            body=body.body,
            contact_identity_id=body.contact_identity_id,
            request_id=body.request_id,
            client_meta=body.client_meta,
        )
        return success_response(row, "Brouillon SMS créé")
    except Exception as e:
        return error_response(str(e), 400)


@router.post("/sms/{sms_id}/status")
async def sms_update_status(
    sms_id: str,
    body: SmsStatusBody,
    user_id: str = Depends(get_current_user_id),
):
    row = await sms_action_service.update_sms_status(
        user_id,
        sms_id,
        body.status,
        error_message=body.error_message,
    )
    if not row:
        return error_response("Entrée SMS introuvable", 404)
    return success_response(row, "Statut mis à jour")


@router.post("/sms/confirm")
async def sms_confirm(body: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    sms_id = str(body.get("sms_id") or "").strip()
    if not sms_id:
        return error_response("sms_id requis", 400)
    row = await sms_action_service.update_sms_status(user_id, sms_id, "confirmed")
    if not row:
        return error_response("Entrée SMS introuvable", 404)
    return success_response(row, "SMS confirmé")


@router.post("/sms/execute")
async def sms_execute(body: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    sms_id = str(body.get("sms_id") or "").strip()
    if not sms_id:
        return error_response("sms_id requis", 400)
    list_rows = await sms_action_service.list_sms_actions(user_id, limit=200)
    row = next((r for r in list_rows if str(r.get("id")) == sms_id), None)
    if not row:
        return error_response("Entrée SMS introuvable", 404)
    payload = {
        "action_type": "send_sms",
        "sms_id": sms_id,
        "to_e164": row.get("to_e164"),
        "body": row.get("body"),
    }
    return success_response(payload, "Exécution côté client requise")


@router.get("/sms")
async def sms_list(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=50, ge=1, le=200),
):
    data = await sms_action_service.list_sms_actions(user_id, limit=limit)
    return success_response(data, "OK")


@router.post("/contacts/sync")
async def contacts_sync(body: ContactsSyncBody, user_id: str = Depends(get_current_user_id)):
    data = await sms_action_service.sync_contacts(user_id, body.contacts)
    return success_response(data, "Contacts synchronisés")


@router.get("/contacts/search")
async def contacts_search(
    q: str = Query(..., min_length=1),
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=10, ge=1, le=50),
):
    data = await sms_action_service.search_contacts(user_id, q, limit=limit)
    return success_response(data, "OK")

