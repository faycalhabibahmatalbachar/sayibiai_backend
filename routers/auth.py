"""Authentification — Supabase + JWT applicatif + refresh Redis."""

import logging
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

import httpx
import redis.exceptions as redis_exc
from fastapi import APIRouter, Request

from core.config import get_settings
from core.database import get_supabase, get_supabase_admin
from core.redis_client import get_async_redis, reset_async_redis
from core.responses import error_response, success_response
from core.security import create_access_token, create_refresh_token_value
from models.auth import (
    GoogleAuthRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SupabaseSessionRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)

_refresh_memory: Dict[str, str] = {}


async def _store_refresh(refresh_token: str, user_id: str) -> None:
    settings = get_settings()
    ttl = int(timedelta(days=settings.refresh_token_expire_days).total_seconds())
    r = await get_async_redis()
    if r:
        try:
            await r.setex(f"refresh:{refresh_token}", ttl, user_id)
            return
        except redis_exc.RedisError as exc:
            logger.warning("Redis setex refresh indisponible, fallback mémoire: %s", exc)
            reset_async_redis()
    _refresh_memory[refresh_token] = user_id


async def _get_refresh_user(refresh_token: str) -> Optional[str]:
    r = await get_async_redis()
    if r:
        try:
            return await r.get(f"refresh:{refresh_token}")
        except redis_exc.RedisError as exc:
            logger.warning("Redis get refresh: %s", exc)
            reset_async_redis()
    return _refresh_memory.get(refresh_token)


async def _delete_refresh(refresh_token: str) -> None:
    r = await get_async_redis()
    if r:
        try:
            await r.delete(f"refresh:{refresh_token}")
        except redis_exc.RedisError as exc:
            logger.warning("Redis delete refresh: %s", exc)
            reset_async_redis()
    _refresh_memory.pop(refresh_token, None)


def _tokens_payload(user_id: str, email: Optional[str]) -> Dict[str, Any]:
    settings = get_settings()
    access = create_access_token(user_id, {"email": email} if email else {})
    refresh = create_refresh_token_value()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user_id": user_id,
    }


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    """Crée un compte Supabase et retourne les jetons applicatifs."""
    client = get_supabase()
    if not client:
        return error_response("Supabase non configuré", 503)
    try:
        display = (body.name or "").strip()
        settings = get_settings()
        redirect = settings.public_app_url.rstrip("/") + "/"
        res = client.auth.sign_up(
            {
                "email": body.email,
                "password": body.password,
                "options": {
                    "email_redirect_to": redirect,
                    "data": {
                        "full_name": display,
                        "name": display,
                    },
                },
            },
        )
    except Exception as e:
        return error_response(str(e), 400)
    user = getattr(res, "user", None)
    if not user:
        return success_response(
            None,
            "Compte créé — confirmez votre email si requis par le projet Supabase",
        )
    try:
        uid = str(user.id)
        email = user.email or body.email
        payload = _tokens_payload(uid, email)
        try:
            await _store_refresh(payload["refresh_token"], uid)
        except Exception as exc:
            logger.warning("Refresh token non stocké (Redis ou mémoire): %s", exc)
        admin = get_supabase_admin()
        if admin:
            try:
                admin.table("users").upsert(
                    {"id": uid, "email": email, "full_name": display},
                ).execute()
            except Exception as exc:
                logger.debug("Upsert profil users ignoré: %s", exc)
        return success_response(payload, "Inscription réussie")
    except Exception as e:
        logger.exception("register: échec après sign_up Supabase")
        return error_response("Erreur serveur lors de l'inscription", 500)


@router.post("/login")
async def login(body: LoginRequest):
    """Connexion email / mot de passe."""
    client = get_supabase()
    if not client:
        return error_response("Supabase non configuré", 503)
    try:
        res = client.auth.sign_in_with_password(
            {"email": body.email, "password": body.password},
        )
    except Exception as e:
        return error_response(str(e), 401)
    user = getattr(res, "user", None)
    if not user:
        return error_response("Identifiants invalides", 401)
    try:
        uid = str(user.id)
        email = user.email
        payload = _tokens_payload(uid, email)
        await _store_refresh(payload["refresh_token"], uid)
        return success_response(payload, "Connexion réussie")
    except Exception:
        logger.exception("login: échec après sign_in Supabase")
        return error_response("Erreur serveur lors de la connexion", 500)


@router.post("/supabase-session")
async def supabase_session(body: SupabaseSessionRequest):
    """
    Échange le JWT utilisateur Supabase (fragment #access_token après clic sur le lien
    de confirmation e-mail) contre les jetons applicatifs (JWT SAYIBI + refresh).
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return error_response("Supabase non configuré", 503)
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {body.supabase_access_token}",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as hc:
            r = await hc.get(url, headers=headers)
    except Exception as e:
        logger.warning("supabase-session: erreur HTTP %s", e)
        return error_response("Impossible de joindre Supabase", 502)
    if r.status_code >= 400:
        return error_response("Session Supabase invalide ou expirée", 401)
    try:
        user = r.json()
    except Exception:
        return error_response("Réponse Supabase invalide", 502)
    uid = user.get("id")
    if not uid:
        return error_response("Utilisateur introuvable", 401)
    email = user.get("email")
    try:
        payload = _tokens_payload(str(uid), email)
        await _store_refresh(payload["refresh_token"], str(uid))
        return success_response(payload, "Session établie")
    except Exception:
        logger.exception("supabase-session: échec après validation Supabase")
        return error_response("Erreur serveur lors de l'établissement de session", 500)


@router.post("/refresh")
async def refresh_token(body: RefreshRequest):
    """Rafraîchit le JWT à partir du refresh token opaque."""
    uid = await _get_refresh_user(body.refresh_token)
    if not uid:
        return error_response("Refresh token invalide", 401)
    client = get_supabase_admin() or get_supabase()
    email = None
    if client:
        try:
            row = client.table("users").select("email").eq("id", uid).single().execute()
            if row.data:
                email = row.data.get("email")
        except Exception:
            pass
    settings = get_settings()
    access = create_access_token(uid, {"email": email} if email else {})
    new_refresh = create_refresh_token_value()
    await _delete_refresh(body.refresh_token)
    await _store_refresh(new_refresh, uid)
    return success_response(
        {
            "access_token": access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
        },
        "Token rafraîchi",
    )


@router.post("/google")
async def google_auth(body: GoogleAuthRequest):
    """
    OAuth Google : id_token (ou access_token) échangé via l'API Auth Supabase.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return error_response("Supabase non configuré", 503)
    if not body.id_token and not body.access_token:
        return error_response("id_token ou access_token requis", 400)
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/token?grant_type=id_token"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Content-Type": "application/json",
    }
    json_body: Dict[str, Any] = {"provider": "google"}
    if body.id_token:
        json_body["id_token"] = body.id_token
    if body.access_token:
        json_body["access_token"] = body.access_token
    try:
        async with httpx.AsyncClient(timeout=45.0) as hc:
            r = await hc.post(url, headers=headers, json=json_body)
    except Exception as e:
        return error_response(str(e), 502)
    if r.status_code >= 400:
        return error_response(r.text or "Échec échange Google", 401)
    data = r.json()
    user = data.get("user") or {}
    uid = user.get("id") or str(uuid.uuid4())
    email = user.get("email")
    payload = _tokens_payload(str(uid), email)
    await _store_refresh(payload["refresh_token"], str(uid))
    return success_response(payload, "Connexion Google réussie")
