"""Omni-agent API: image generation, calls, and screen awareness."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import omni_agent_service

router = APIRouter(prefix="/omni", tags=["omni"])


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    session_id: Optional[str] = None
    style: str = "realistic"
    quality_level: str = "detailed"


class EditImageRequest(BaseModel):
    parent_image_id: str
    original_prompt: str
    edit_prompt: str
    session_id: Optional[str] = None
    style: str = "realistic"
    quality_level: str = "detailed"


@router.post("/generate-image")
async def generate_image(
    req: GenerateImageRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = await omni_agent_service.create_generated_image(
            user_id=user_id,
            session_id=req.session_id,
            original_prompt=req.prompt,
            style=req.style,
            quality_level=req.quality_level,
        )
        if result.get("blocked"):
            return error_response(result.get("message", "Requête bloquée"), 400, result)
        return success_response(result["record"], "Image générée")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/edit-image")
async def edit_image(
    req: EditImageRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = await omni_agent_service.create_generated_image(
            user_id=user_id,
            session_id=req.session_id,
            original_prompt=req.original_prompt,
            style=req.style,
            quality_level=req.quality_level,
            parent_image_id=req.parent_image_id,
            edit_prompt=req.edit_prompt,
        )
        if result.get("blocked"):
            return error_response(result.get("message", "Requête bloquée"), 400, result)
        return success_response(result["record"], "Image modifiée")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/call-settings")
async def get_call_settings(user_id: str = Depends(get_current_user_id)):
    try:
        row = await omni_agent_service.get_call_settings(user_id)
        return success_response(row, "Call settings")
    except Exception as e:
        # Table missing: return defaults without crashing
        return success_response(omni_agent_service._default_call_settings(user_id), "Defaults")


@router.post("/call-settings")
async def update_call_settings(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
):
    try:
        row = await omni_agent_service.save_call_settings(user_id, payload)
        return success_response(row, "Paramètres d'appel mis à jour")
    except Exception as e:
        return success_response({"user_id": user_id, **payload, "saved_locally": True}, "Local only — migrate DB")


@router.put("/call-settings")
async def put_call_settings(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
):
    """Alias PUT pour mise à jour des paramètres d'appel."""
    try:
        row = await omni_agent_service.save_call_settings(user_id, payload)
        return success_response(row, "Paramètres d'appel mis à jour")
    except Exception as e:
        return success_response({"user_id": user_id, **payload, "saved_locally": True}, "Local only — migrate DB")


@router.post("/inbound-call/webhook")
async def inbound_call_webhook(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
):
    try:
        row = await omni_agent_service.process_inbound_call(user_id, payload)
        return success_response(row, "Appel traité")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/screen/session")
async def create_screen_session(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
):
    try:
        row = await omni_agent_service.create_screen_session(user_id, payload)
        return success_response(row, "Session écran enregistrée")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/screen/alert")
async def create_screen_alert(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
):
    try:
        row = await omni_agent_service.create_screen_alert(user_id, payload)
        return success_response(row, "Alerte écran enregistrée")
    except Exception as e:
        return error_response(str(e), 500)


@router.websocket("/screen/ws")
async def screen_ws(websocket: WebSocket):
    await websocket.accept()
    previous_signature = ""
    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            payload["previous_signature"] = previous_signature
            result = await omni_agent_service.analyze_screen_frame(payload)
            previous_signature = result.get("signature", previous_signature)
            await websocket.send_text(json.dumps(result))
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011)
