"""Router Réseaux Sociaux — connexion OAuth, publication, monitoring, analytics."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import social_service

router = APIRouter(prefix="/social", tags=["social"])


# ---------------------------------------------------------------------------
# Modèles Pydantic
# ---------------------------------------------------------------------------

class ConnectAccountRequest(BaseModel):
    platform: str
    access_token: str
    refresh_token: Optional[str] = None
    account_username: str = ""
    token_expires_at: Optional[str] = None


class CreatePostRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    platforms: List[str] = Field(..., min_length=1)
    media_urls: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None
    ai_generated: bool = False


class SchedulePostRequest(BaseModel):
    content: str = Field(..., min_length=1)
    platforms: List[str]
    media_urls: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None
    scheduled_for: str = Field(..., description="ISO 8601 datetime")


class GeneratePostRequest(BaseModel):
    topic: str = Field(..., min_length=3)
    platform: str = "twitter"
    tone: str = "professional"


class ReplyRequest(BaseModel):
    reply_text: str = Field(..., min_length=1)
    ai_generated: bool = False


class SocialSettingsRequest(BaseModel):
    auto_publish: Optional[bool] = None
    publish_frequency: Optional[dict] = None
    content_themes: Optional[List[str]] = None
    tone_of_voice: Optional[str] = None
    auto_reply_comments: Optional[bool] = None


# ---------------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------------

@router.post("/accounts/connect")
async def connect_account(
    body: ConnectAccountRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Connecte un compte réseau social via OAuth."""
    try:
        result = await social_service.connect_account(
            user_id=user_id,
            platform=body.platform,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
            account_username=body.account_username,
            token_expires_at=body.token_expires_at,
        )
        return success_response(result, f"Compte {body.platform} connecté")
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/accounts")
async def list_accounts(user_id: str = Depends(get_current_user_id)):
    """Liste les comptes sociaux connectés."""
    accounts = await social_service.get_user_accounts(user_id)
    return success_response(accounts, "OK")


@router.delete("/accounts/{account_id}")
async def disconnect_account(
    account_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Déconnecte un compte réseau social."""
    ok = await social_service.disconnect_account(user_id, account_id)
    if ok:
        return success_response({"disconnected": account_id}, "Compte déconnecté")
    return error_response("Compte introuvable", 404)


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

@router.post("/posts/create")
async def create_post(
    body: CreatePostRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Crée et publie un post sur une ou plusieurs plateformes."""
    try:
        result = await social_service.create_post(
            user_id=user_id,
            content=body.content,
            platforms=body.platforms,
            media_urls=body.media_urls,
            hashtags=body.hashtags,
            ai_generated=body.ai_generated,
        )
        return success_response(result, "Post publié")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/posts/schedule")
async def schedule_post(
    body: SchedulePostRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Programme un post pour publication différée."""
    try:
        result = await social_service.create_post(
            user_id=user_id,
            content=body.content,
            platforms=body.platforms,
            media_urls=body.media_urls,
            hashtags=body.hashtags,
            schedule_for=body.scheduled_for,
        )
        return success_response(result, "Post programmé")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/posts/generate")
async def generate_post(
    body: GeneratePostRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Génère un post optimisé IA basé sur les tendances."""
    try:
        result = await social_service.generate_ai_post(
            user_id=user_id,
            topic=body.topic,
            platform=body.platform,
            tone=body.tone,
        )
        return success_response(result, "Post généré")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/posts/history")
async def get_post_history(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Historique des posts publiés."""
    posts = await social_service.get_post_history(user_id, limit)
    return success_response(posts, "OK")


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------

@router.get("/interactions")
async def get_inbox(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    """Inbox unifié de toutes les interactions sociales."""
    interactions = await social_service.get_inbox(user_id, limit)
    return success_response(interactions, "OK")


@router.post("/interactions/{interaction_id}/reply")
async def reply_to_interaction(
    interaction_id: str,
    body: ReplyRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Répond à une interaction sociale."""
    result = await social_service.reply_to_interaction(
        user_id=user_id,
        interaction_id=interaction_id,
        reply_text=body.reply_text,
        ai_generated=body.ai_generated,
    )
    return success_response(result, "Réponse envoyée")


# ---------------------------------------------------------------------------
# Analytics & Settings
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def get_analytics(user_id: str = Depends(get_current_user_id)):
    """Analytics hebdomadaires des posts et interactions."""
    data = await social_service.get_analytics(user_id)
    return success_response(data, "OK")


@router.get("/settings")
async def get_settings(user_id: str = Depends(get_current_user_id)):
    settings = await social_service.get_settings_social(user_id)
    return success_response(settings, "OK")


@router.put("/settings")
async def update_settings(
    body: SocialSettingsRequest,
    user_id: str = Depends(get_current_user_id),
):
    ok = await social_service.update_settings_social(
        user_id, body.model_dump(exclude_none=True)
    )
    return success_response({"updated": ok}, "Paramètres mis à jour")
