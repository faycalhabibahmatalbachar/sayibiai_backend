"""Routes internes (debug / ops) — protégées par secret partagé."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from core.responses import error_response, success_response
from services import alarm_service, fcm_service

router = APIRouter(prefix="/internal", tags=["internal"])


class InternalFcmTestBody(BaseModel):
    fcm_token: str = Field(..., min_length=10)
    title: str = "SAYIBI — test"
    body: str = "Notification de test (endpoint interne)."
    data: Optional[Dict[str, str]] = None


@router.post("/fcm-test")
async def internal_fcm_test(
    body: InternalFcmTestBody,
    x_sayibi_internal_secret: str = Header(..., alias="X-Sayibi-Internal-Secret"),
):
    """
    Envoie une notification FCM v1 vers un jeton arbitraire (QA / support).

    Exige `SAYIBI_INTERNAL_SECRET` côté serveur et le même valeur dans l'en-tête
    `X-Sayibi-Internal-Secret`.
    """
    expected = (get_settings().sayibi_internal_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SAYIBI_INTERNAL_SECRET non configuré sur le serveur",
        )
    if x_sayibi_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Secret interne invalide")

    if not fcm_service.fcm_v1_configured():
        return error_response("FCM v1 non configuré (credentials Firebase)", 503)

    try:
        result: Dict[str, Any] = await fcm_service.send_notification(
            body.fcm_token,
            body.title,
            body.body,
            body.data,
        )
        return success_response(result, "Message FCM envoyé")
    except Exception as e:
        return error_response(str(e), 502)


@router.post("/alarms/tick")
async def internal_alarms_tick(
    x_sayibi_internal_secret: str = Header(..., alias="X-Sayibi-Internal-Secret"),
):
    """
    Tick scheduler interne : déclenche les alarmes dues et envoie les push fallback.
    """
    expected = (get_settings().sayibi_internal_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SAYIBI_INTERNAL_SECRET non configuré sur le serveur",
        )
    if x_sayibi_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Secret interne invalide")
    try:
        data = await alarm_service.run_due_alarms_tick()
        return success_response(data, "Tick alarmes exécuté")
    except Exception as e:
        return error_response(str(e), 500)
