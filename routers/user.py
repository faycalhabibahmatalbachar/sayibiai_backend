"""Profil utilisateur, réglages, usage, fichiers."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.deps import get_current_user_id
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from services import fcm_service

router = APIRouter(prefix="/user", tags=["user"])


class UserSettingsBody(BaseModel):
    language: Optional[str] = None
    theme: Optional[str] = None
    notifications: Optional[bool] = None
    model_preference: Optional[str] = None


class FcmTokenBody(BaseModel):
    token: str


class NotifyTestBody(BaseModel):
    title: Optional[str] = "SAYIBI — test"
    body: Optional[str] = "Votre application a reçu une notification de test."


def _db():
    return get_supabase_admin()


@router.post("/fcm-token")
async def register_fcm_token(body: FcmTokenBody, user_id: str = Depends(get_current_user_id)):
    """Enregistre le token FCM de l'appareil (notifications push)."""
    c = _db()
    if not c:
        return success_response({"stored": False}, "Sans DB — token non persisté")
    try:
        c.table("users").update({"fcm_token": body.token}).eq("id", user_id).execute()
        return success_response({"stored": True}, "Token FCM enregistré")
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/notify-test")
async def user_notify_test(body: NotifyTestBody, user_id: str = Depends(get_current_user_id)):
    """
    Envoie une notification FCM v1 au **token enregistré** pour l'utilisateur connecté
    (`POST /user/fcm-token` doit avoir été appelé depuis l'app au préalable).
    """
    if not fcm_service.fcm_v1_configured():
        return error_response("FCM v1 non configuré (credentials Firebase)", 503)
    c = _db()
    if not c:
        return error_response("Base indisponible", 503)
    try:
        row = (
            c.table("users")
            .select("fcm_token")
            .eq("id", user_id)
            .single()
            .execute()
        )
        token = (row.data or {}).get("fcm_token") if row.data else None
    except Exception as e:
        return error_response(str(e), 500)
    if not token:
        return error_response(
            "Aucun fcm_token enregistré — appelez d'abord POST /api/v1/user/fcm-token depuis l'app",
            400,
        )
    title = (body.title or "SAYIBI — test").strip()
    msg = (body.body or "Test").strip()
    try:
        result = await fcm_service.send_notification(
            token,
            title,
            msg,
            {"type": "sayibi_test", "user_id": user_id},
        )
        return success_response(result, "Notification envoyée")
    except Exception as e:
        return error_response(str(e), 502)


@router.get("/profile")
async def get_profile(user_id: str = Depends(get_current_user_id)):
    """Profil utilisateur."""
    c = _db()
    if not c:
        return success_response({"id": user_id}, "Profil minimal (sans DB)")
    try:
        row = c.table("users").select("*").eq("id", user_id).single().execute()
        return success_response(row.data or {"id": user_id}, "OK")
    except Exception:
        return success_response({"id": user_id}, "OK")


@router.put("/settings")
async def put_settings(body: UserSettingsBody, user_id: str = Depends(get_current_user_id)):
    """Met à jour les préférences."""
    c = _db()
    if not c:
        return success_response(body.model_dump(exclude_none=True), "Réglages (sans persistance DB)")
    data: Dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        return success_response({}, "Rien à mettre à jour")
    try:
        c.table("users").update(data).eq("id", user_id).execute()
        return success_response(data, "Réglages enregistrés")
    except Exception as e:
        msg = str(e).lower()
        if "notifications" in msg and ("column" in msg or "does not exist" in msg):
            return error_response(
                "Colonne « notifications » absente en base — exécutez "
                "sayibi_backend/sql/migrations/001_user_settings_fix.sql sur Supabase.",
                500,
            )
        if "model_preference" in msg and ("check" in msg or "violates" in msg):
            return error_response(
                "Contrainte model_preference trop stricite — exécutez "
                "sayibi_backend/sql/migrations/001_user_settings_fix.sql sur Supabase.",
                500,
            )
        return error_response(str(e), 500)


@router.get("/usage")
async def get_usage(user_id: str = Depends(get_current_user_id)):
    """Statistiques d'usage (tokens / requêtes) — agrégation simple."""
    c = _db()
    if not c:
        return success_response(
            {
                "tokens_today": 0,
                "tokens_month": 0,
                "requests_today": 0,
                "requests_month": 0,
            },
            "Sans table usage_logs",
        )
    now = datetime.now(timezone.utc)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        logs = (
            c.table("usage_logs")
            .select("tokens_used,endpoint,created_at")
            .eq("user_id", user_id)
            .gte("created_at", start_month)
            .execute()
        )
        rows = logs.data or []
        tokens_month = sum(int(r.get("tokens_used") or 0) for r in rows)
        reqs_month = len(rows)
        today_rows = [r for r in rows if (r.get("created_at") or "") >= start_day]
        tokens_today = sum(int(r.get("tokens_used") or 0) for r in today_rows)
        reqs_today = len(today_rows)
        return success_response(
            {
                "tokens_today": tokens_today,
                "tokens_month": tokens_month,
                "requests_today": reqs_today,
                "requests_month": reqs_month,
            },
            "OK",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/files")
async def list_files(user_id: str = Depends(get_current_user_id)):
    """Fichiers générés et documents uploadés."""
    c = _db()
    if not c:
        return success_response({"generated": [], "documents": []}, "Sans DB")
    try:
        gen = (
            c.table("generated_files")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        docs = (
            c.table("documents")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return success_response(
            {"generated": gen.data or [], "documents": docs.data or []},
            "OK",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, user_id: str = Depends(get_current_user_id)):
    """Supprime une entrée fichier (généré ou document)."""
    c = _db()
    if not c:
        return success_response(None, "Rien à supprimer")
    try:
        c.table("generated_files").delete().eq("id", file_id).eq("user_id", user_id).execute()
        c.table("documents").delete().eq("id", file_id).eq("user_id", user_id).execute()
        return success_response({"id": file_id}, "Suppression demandée")
    except Exception as e:
        return error_response(str(e), 500)
