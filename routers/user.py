"""Profil utilisateur, réglages, usage, fichiers."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    device_id: Optional[str] = None
    platform: Optional[str] = None


class NotifyTestBody(BaseModel):
    title: Optional[str] = "SAYIBI — test"
    body: Optional[str] = "Votre application a reçu une notification de test."


class ContextNotifyBody(BaseModel):
    title: str
    body: str
    data: Optional[Dict[str, Any]] = None


def _db():
    return get_supabase_admin()


def _log_notification(
    c,
    user_id: str,
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]],
    message_id: Optional[str],
) -> None:
    try:
        c.table("notifications").insert(
            {
                "user_id": user_id,
                "title": title[:200],
                "body": body[:1000],
                "data": data or {},
                "fcm_message_id": message_id,
            }
        ).execute()
    except Exception:
        pass


def _load_device_tokens(c, user_id: str) -> List[str]:
    tokens: List[str] = []
    # New multi-device table (si présente)
    try:
        rows = (
            c.table("fcm_device_tokens")
            .select("token")
            .eq("user_id", user_id)
            .execute()
        ).data or []
        for r in rows:
            t = (r or {}).get("token")
            if isinstance(t, str) and t.strip():
                tokens.append(t.strip())
    except Exception:
        pass
    # Fallback token legacy
    try:
        row = (
            c.table("users")
            .select("fcm_token")
            .eq("id", user_id)
            .single()
            .execute()
        )
        t = (row.data or {}).get("fcm_token") if row.data else None
        if isinstance(t, str) and t.strip():
            tokens.append(t.strip())
    except Exception:
        pass
    # unique
    return list(dict.fromkeys(tokens))


@router.post("/fcm-token")
async def register_fcm_token(body: FcmTokenBody, user_id: str = Depends(get_current_user_id)):
    """Enregistre le token FCM de l'appareil (notifications push)."""
    c = _db()
    if not c:
        return success_response({"stored": False}, "Sans DB — token non persisté")
    try:
        # Legacy single token (compat)
        c.table("users").update({"fcm_token": body.token}).eq("id", user_id).execute()
        # Multi-device token table (optionnelle)
        try:
            c.table("fcm_device_tokens").upsert(
                {
                    "user_id": user_id,
                    "device_id": (body.device_id or body.token)[:255],
                    "platform": (body.platform or "unknown")[:40],
                    "token": body.token,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="user_id,device_id",
            ).execute()
        except Exception:
            pass
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
    tokens = _load_device_tokens(c, user_id)
    if not tokens:
        return error_response(
            "Aucun fcm_token enregistré — appelez d'abord POST /api/v1/user/fcm-token depuis l'app",
            400,
        )
    title = (body.title or "SAYIBI — test").strip()
    msg = (body.body or "Test").strip()
    successes: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for token in tokens:
        sent = False
        last_error = ""
        for _ in range(3):
            try:
                result = await fcm_service.send_notification(
                    token,
                    title,
                    msg,
                    {"type": "sayibi_test", "user_id": user_id},
                )
                message_id = result.get("name") if isinstance(result, dict) else None
                _log_notification(
                    c,
                    user_id,
                    title=title,
                    body=msg,
                    data={"type": "sayibi_test", "user_id": user_id},
                    message_id=message_id,
                )
                successes.append({"token_suffix": token[-8:], "name": message_id})
                sent = True
                break
            except Exception as e:
                last_error = str(e)
        if not sent:
            failures.append({"token_suffix": token[-8:], "error": last_error[:240]})
            try:
                c.table("notification_dlq").insert(
                    {
                        "user_id": user_id,
                        "token_suffix": token[-8:],
                        "title": title,
                        "body": msg,
                        "error_message": last_error[:500],
                    }
                ).execute()
            except Exception:
                pass
    return success_response(
        {"successes": successes, "failures": failures},
        "Notification traitée",
    )


@router.post("/notify-contextual")
async def user_notify_contextual(body: ContextNotifyBody, user_id: str = Depends(get_current_user_id)):
    """Push contextuel (docs prêts, erreurs actions, rappels, etc.) avec retry."""
    if not fcm_service.fcm_v1_configured():
        return error_response("FCM v1 non configuré (credentials Firebase)", 503)
    c = _db()
    if not c:
        return error_response("Base indisponible", 503)
    tokens = _load_device_tokens(c, user_id)
    if not tokens:
        return error_response("Aucun appareil enregistré", 400)

    payload_data = body.data or {}
    successes: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for token in tokens:
        sent = False
        last_error = ""
        for _ in range(3):
            try:
                result = await fcm_service.send_notification(
                    token,
                    body.title,
                    body.body,
                    payload_data,
                )
                message_id = result.get("name") if isinstance(result, dict) else None
                _log_notification(
                    c,
                    user_id,
                    title=body.title,
                    body=body.body,
                    data=payload_data,
                    message_id=message_id,
                )
                successes.append({"token_suffix": token[-8:], "name": message_id})
                sent = True
                break
            except Exception as e:
                last_error = str(e)
        if not sent:
            failures.append({"token_suffix": token[-8:], "error": last_error[:240]})
    return success_response(
        {"successes": successes, "failures": failures},
        "Notification contextuelle traitée",
    )


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
