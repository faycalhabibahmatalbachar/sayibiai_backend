"""Router Media — génération vidéo, édition, analyse."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import video_service, moderation_service

router = APIRouter(prefix="/media", tags=["media"])


# ---------------------------------------------------------------------------
# Modèles Pydantic
# ---------------------------------------------------------------------------

class VideoGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    duration: int = Field(default=5, ge=3, le=30)
    provider: str = Field(default="runway")


class VideoEditRequest(BaseModel):
    video_url: str
    edit_type: str = Field(..., description="anonymize|inpaint|translate|colorize")
    edit_params: dict = {}


class VideoAnalyzeRequest(BaseModel):
    video_url: str
    analysis_type: str = Field(default="full", description="full|transcript|anomaly|summary")


# ---------------------------------------------------------------------------
# Routes vidéo
# ---------------------------------------------------------------------------

@router.post("/videos/generate")
async def generate_video(
    body: VideoGenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Lance une génération vidéo text-to-video (job asynchrone)."""
    is_safe, refusal_msg, flags = await moderation_service.check_content(
        body.prompt, user_id, context="video_generation"
    )
    if not is_safe:
        return error_response(refusal_msg or "Contenu refusé", 400)

    try:
        result = await video_service.generate_video(
            prompt=body.prompt,
            user_id=user_id,
            duration=body.duration,
            provider=body.provider,
        )
        return success_response(result, "Job de génération vidéo lancé")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/videos/status/{job_id}")
async def get_video_status(
    job_id: str,
    provider: str = Query(default="runway"),
    user_id: str = Depends(get_current_user_id),
):
    """Vérifie le statut d'un job de génération vidéo."""
    try:
        result = await video_service.get_video_status(job_id, provider)
        return success_response(result, "Statut récupéré")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/videos/analyze")
async def analyze_video(
    body: VideoAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Analyse le contenu d'une vidéo (transcript, objets, anomalies)."""
    try:
        result = await video_service.analyze_video(
            video_url=body.video_url,
            user_id=user_id,
            analysis_type=body.analysis_type,
        )
        return success_response(result, "Analyse terminée")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/videos/history")
async def get_video_history(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Historique des vidéos générées."""
    try:
        history = await video_service.get_video_history(user_id, limit)
        return success_response(history, "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/videos/edit")
async def edit_video(
    body: VideoEditRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Édite une vidéo (anonymisation, inpainting, traduction, colorisation)."""
    # Pour l'instant retourne un placeholder — implémentation complète nécessite
    # des services spécialisés (Runway Inpaint, etc.)
    return success_response(
        {
            "status": "queued",
            "edit_type": body.edit_type,
            "note": "Édition vidéo en file d'attente. Fonctionnalité avancée.",
        },
        "Demande d'édition enregistrée",
    )
