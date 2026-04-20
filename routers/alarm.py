"""Alarmes CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from models.alarm import AlarmCreateBody, AlarmUpdateBody
from services import alarm_service

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.post("")
async def create_alarm(body: AlarmCreateBody, user_id: str = Depends(get_current_user_id)):
    try:
        data = await alarm_service.create_alarm(user_id, body.model_dump())
        return success_response(data, "Alarme créée")
    except Exception as e:
        return error_response(str(e), 400)


@router.get("")
async def list_alarms(user_id: str = Depends(get_current_user_id)):
    try:
        data = await alarm_service.list_alarms(user_id)
        return success_response(data, "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/{alarm_id}")
async def get_alarm(alarm_id: str, user_id: str = Depends(get_current_user_id)):
    data = await alarm_service.get_alarm(user_id, alarm_id)
    if not data:
        return error_response("Alarme introuvable", 404)
    return success_response(data, "OK")


@router.put("/{alarm_id}")
async def update_alarm(
    alarm_id: str,
    body: AlarmUpdateBody,
    user_id: str = Depends(get_current_user_id),
):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        return success_response({}, "Rien à modifier")
    try:
        data = await alarm_service.update_alarm(user_id, alarm_id, patch)
        if not data:
            return error_response("Alarme introuvable", 404)
        return success_response(data, "Alarme mise à jour")
    except Exception as e:
        return error_response(str(e), 400)


@router.delete("/{alarm_id}")
async def delete_alarm(alarm_id: str, user_id: str = Depends(get_current_user_id)):
    ok = await alarm_service.delete_alarm(user_id, alarm_id)
    return success_response({"deleted": ok}, "Alarme supprimée")


@router.post("/{alarm_id}/enable")
async def enable_alarm(alarm_id: str, user_id: str = Depends(get_current_user_id)):
    data = await alarm_service.update_alarm(
        user_id,
        alarm_id,
        {"is_enabled": True, "status": "scheduled"},
    )
    if not data:
        return error_response("Alarme introuvable", 404)
    return success_response(data, "Alarme activée")


@router.post("/{alarm_id}/disable")
async def disable_alarm(alarm_id: str, user_id: str = Depends(get_current_user_id)):
    data = await alarm_service.update_alarm(
        user_id,
        alarm_id,
        {"is_enabled": False, "status": "cancelled"},
    )
    if not data:
        return error_response("Alarme introuvable", 404)
    return success_response(data, "Alarme désactivée")


@router.post("/{alarm_id}/dismiss")
async def dismiss_alarm(alarm_id: str, user_id: str = Depends(get_current_user_id)):
    data = await alarm_service.update_alarm(
        user_id,
        alarm_id,
        {"status": "dismissed", "is_enabled": False},
    )
    if not data:
        return error_response("Alarme introuvable", 404)
    await alarm_service.mark_alarm_event(user_id, alarm_id, "dismissed", {})
    return success_response(data, "Alarme clôturée")

