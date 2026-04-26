"""Image utilities — health / diagnostics."""

from fastapi import APIRouter, Depends

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import image_gen_service

router = APIRouter(prefix="/image", tags=["image"])


@router.get("/health")
async def image_health(_user_id: str = Depends(get_current_user_id)):
    """Teste en live quels modèles Gemini image sont réellement opérationnels."""
    try:
        data = await image_gen_service.image_health_check()
        return success_response(data, "Image health OK")
    except Exception as e:
        return error_response(str(e), 500)
