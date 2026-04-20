"""Notification service unifié: retries/backoff + DLQ + logs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import get_supabase_admin
from services import fcm_service


def _db():
    return get_supabase_admin()


def _is_retryable_error(message: str) -> bool:
    m = (message or "").lower()
    retryable_markers = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "temporarily unavailable",
        "connection",
        "reset",
    )
    return any(marker in m for marker in retryable_markers)


def _dedup_tokens(tokens: List[str]) -> List[str]:
    return list(dict.fromkeys([t.strip() for t in tokens if isinstance(t, str) and t.strip()]))


def load_device_tokens(user_id: str, c=None) -> List[str]:
    client = c or _db()
    if not client:
        return []
    tokens: List[str] = []
    try:
        rows = client.table("fcm_device_tokens").select("token").eq("user_id", user_id).execute().data or []
        for row in rows:
            token = (row or {}).get("token")
            if isinstance(token, str) and token.strip():
                tokens.append(token)
    except Exception:
        pass
    try:
        row = client.table("users").select("fcm_token").eq("id", user_id).single().execute()
        token = (row.data or {}).get("fcm_token") if row.data else None
        if isinstance(token, str) and token.strip():
            tokens.append(token)
    except Exception:
        pass
    return _dedup_tokens(tokens)


def _log_notification(
    user_id: str,
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]],
    message_id: Optional[str],
    c=None,
) -> None:
    client = c or _db()
    if not client:
        return
    try:
        client.table("notifications").insert(
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


def _push_dlq(
    user_id: str,
    *,
    token_suffix: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]],
    error_message: str,
    c=None,
) -> None:
    client = c or _db()
    if not client:
        return
    try:
        client.table("notification_dlq").insert(
            {
                "user_id": user_id,
                "token_suffix": token_suffix,
                "title": title[:200],
                "body": body[:1000],
                "error_message": error_message[:500],
                "payload": data or {},
                "retry_count": 3,
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception:
        # Compat schéma minimal (sans payload/retry_count/last_attempt_at).
        try:
            client.table("notification_dlq").insert(
                {
                    "user_id": user_id,
                    "token_suffix": token_suffix,
                    "title": title[:200],
                    "body": body[:1000],
                    "error_message": error_message[:500],
                }
            ).execute()
        except Exception:
            pass


async def send_to_user_devices(
    user_id: str,
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
    c=None,
) -> Dict[str, Any]:
    client = c or _db()
    if not client:
        return {"successes": [], "failures": [{"token_suffix": "n/a", "error": "Base indisponible"}]}

    tokens = load_device_tokens(user_id, client)
    if not tokens:
        return {"successes": [], "failures": [{"token_suffix": "n/a", "error": "Aucun appareil enregistré"}]}

    successes: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for token in tokens:
        sent = False
        last_error = ""
        for attempt in range(max_attempts):
            try:
                result = await fcm_service.send_notification(token, title, body, data)
                message_id = result.get("name") if isinstance(result, dict) else None
                _log_notification(
                    user_id,
                    title=title,
                    body=body,
                    data=data,
                    message_id=message_id,
                    c=client,
                )
                successes.append({"token_suffix": token[-8:], "name": message_id})
                sent = True
                break
            except Exception as e:
                last_error = str(e)
                if attempt + 1 >= max_attempts:
                    break
                if not _is_retryable_error(last_error):
                    break
                delay = 0.2 * (2**attempt)
                await asyncio.sleep(delay)

        if not sent:
            failures.append({"token_suffix": token[-8:], "error": last_error[:240]})
            _push_dlq(
                user_id,
                token_suffix=token[-8:],
                title=title,
                body=body,
                data=data,
                error_message=last_error,
                c=client,
            )

    return {"successes": successes, "failures": failures}
