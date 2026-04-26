"""Router Avatar — gestion et génération de vidéos avec avatars IA."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import avatar_service

router = APIRouter(prefix="/avatar", tags=["avatar"])


class CreateAvatarRequest(BaseModel):
    avatar_name: str = Field(..., min_length=1, max_length=100)
    photo_url: str
    voice_id: Optional[str] = None


class AvatarRespondRequest(BaseModel):
    avatar_id: str
    message_text: str = Field(..., min_length=1, max_length=2000)
    response_text: Optional[str] = None


@router.get("/list")
async def list_avatars(user_id: str = Depends(get_current_user_id)):
    """Liste les avatars disponibles (presets HeyGen + custom utilisateur)."""
    try:
        presets = await avatar_service.list_preset_avatars()
        custom = await avatar_service.get_user_avatars(user_id)
        return success_response(
            {"presets": presets, "custom": custom},
            "Avatars récupérés",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/create")
async def create_avatar(
    body: CreateAvatarRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Crée un avatar personnalisé depuis une photo."""
    try:
        result = await avatar_service.create_custom_avatar(
            user_id=user_id,
            avatar_name=body.avatar_name,
            photo_url=body.photo_url,
            voice_id=body.voice_id,
        )
        return success_response(result, "Avatar créé")
    except Exception as e:
        return error_response(str(e), 500)


@router.delete("/{avatar_id}")
async def delete_avatar(
    avatar_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Supprime un avatar de l'utilisateur."""
    ok = await avatar_service.delete_avatar(user_id, avatar_id)
    if ok:
        return success_response({"deleted": avatar_id}, "Avatar supprimé")
    return error_response("Avatar introuvable", 404)


@router.put("/{avatar_id}/default")
async def set_default_avatar(
    avatar_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Définit un avatar comme avatar par défaut."""
    ok = await avatar_service.set_default_avatar(user_id, avatar_id)
    return success_response({"default": avatar_id, "updated": ok}, "Avatar par défaut mis à jour")


@router.post("/respond")
async def avatar_respond(
    body: AvatarRespondRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Génère une réponse vidéo de l'avatar pour un message donné."""
    try:
        result = await avatar_service.generate_avatar_response(
            user_id=user_id,
            avatar_id=body.avatar_id,
            message_text=body.message_text,
            response_text=body.response_text,
        )
        return success_response(result, "Réponse avatar générée")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/conversations/history")
async def get_avatar_history(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Historique des conversations avec les avatars."""
    history = await avatar_service.get_avatar_conversation_history(user_id, limit)
    return success_response(history, "OK")
