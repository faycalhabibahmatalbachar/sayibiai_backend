"""Firebase Cloud Messaging HTTP v1 — OAuth2 via compte de service."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from core.config import get_settings

logger = logging.getLogger(__name__)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def _load_credentials():
    """Charge les credentials Google pour l'API FCM v1."""
    s = get_settings()
    raw_json = (s.firebase_credentials_json or "").strip()
    path = (s.firebase_credentials_path or "").strip()

    if raw_json:
        try:
            info = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValueError("FIREBASE_CREDENTIALS_JSON invalide (JSON)") from e
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=[_FCM_SCOPE],
        )

    if path:
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f"Fichier introuvable: {expanded}")
        return service_account.Credentials.from_service_account_file(
            expanded,
            scopes=[_FCM_SCOPE],
        )

    raise ValueError(
        "FCM v1 non configuré : définir FIREBASE_CREDENTIALS_JSON ou FIREBASE_CREDENTIALS_PATH",
    )


def get_fcm_credentials():
    """Retourne les credentials ; mis en cache processus via lru_cache si besoin."""
    return _load_credentials()


def get_project_id() -> str:
    creds = _load_credentials()
    pid = getattr(creds, "project_id", None) or getattr(creds, "_project_id", None)
    if not pid:
        raise ValueError("project_id manquant dans le compte de service Firebase")
    return str(pid)


def get_access_token() -> str:
    creds = _load_credentials()
    creds.refresh(Request())
    token = creds.token
    if not token:
        raise RuntimeError("Impossible d'obtenir un access token OAuth2 pour FCM")
    return token


def fcm_v1_configured() -> bool:
    try:
        _load_credentials()
        return True
    except Exception:
        return False


def _stringify_data(data: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not data:
        return {}
    out: Dict[str, str] = {}
    for k, v in data.items():
        if v is None:
            continue
        out[str(k)] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return out


async def send_notification(
    fcm_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Envoie une notification FCM via l'API v1 (projects.messages:send).
    Les valeurs du champ `data` doivent être des chaînes (normalisées ici).
    """
    project_id = get_project_id()
    access_token = get_access_token()
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    payload: Dict[str, Any] = {
        "message": {
            "token": fcm_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "android": {"priority": "HIGH"},
            "apns": {
                "headers": {"apns-priority": "10"},
            },
        }
    }
    str_data = _stringify_data(data)
    if str_data:
        payload["message"]["data"] = str_data

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            logger.warning("FCM v1 error %s: %s", r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()
