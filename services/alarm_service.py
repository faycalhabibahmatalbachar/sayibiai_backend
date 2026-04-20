"""Services alarmes: CRUD + tick scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.database import get_supabase_admin
from services import fcm_service


def _db():
    return get_supabase_admin()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _next_trigger_from_repeat(current: datetime, repeat_rule: Optional[str]) -> Optional[datetime]:
    rr = (repeat_rule or "").strip().lower()
    if rr == "daily":
        return current.replace(second=0, microsecond=0) + timedelta(days=1)
    return None


async def create_alarm(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    c = _db()
    if not c:
        raise RuntimeError("Base indisponible")
    scheduled_for = _ensure_utc(payload["scheduled_for"]).isoformat()
    request_id = payload.get("request_id")
    if request_id:
        try:
            existing = (
                c.table("alarms")
                .select("*")
                .eq("user_id", user_id)
                .eq("metadata->>request_id", str(request_id))
                .limit(1)
                .execute()
            ).data or []
            if existing:
                return existing[0]
        except Exception:
            pass
    row = {
        "user_id": user_id,
        "title": payload["title"],
        "message": payload.get("message"),
        "scheduled_for": scheduled_for,
        "timezone": payload.get("timezone") or "Africa/Ndjamena",
        "repeat_rule": payload.get("repeat_rule"),
        "delivery_channel": payload.get("delivery_channel") or "push",
        "status": "scheduled",
        "is_enabled": True,
        "next_trigger_at": scheduled_for,
        "metadata": {
            **(payload.get("metadata") or {}),
            **({"request_id": request_id} if request_id else {}),
        },
    }
    res = c.table("alarms").insert(row).execute()
    data = res.data or []
    return data[0] if data else row


async def list_alarms(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    c = _db()
    if not c:
        return []
    return (
        c.table("alarms")
        .select("*")
        .eq("user_id", user_id)
        .order("scheduled_for", desc=False)
        .limit(limit)
        .execute()
    ).data or []


async def get_alarm(user_id: str, alarm_id: str) -> Optional[Dict[str, Any]]:
    c = _db()
    if not c:
        return None
    rows = (
        c.table("alarms")
        .select("*")
        .eq("id", alarm_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


async def update_alarm(user_id: str, alarm_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    c = _db()
    if not c:
        raise RuntimeError("Base indisponible")
    data = dict(patch)
    if "scheduled_for" in data and data["scheduled_for"] is not None:
        dt = _ensure_utc(data["scheduled_for"]).isoformat()
        data["scheduled_for"] = dt
        data["next_trigger_at"] = dt
    res = c.table("alarms").update(data).eq("id", alarm_id).eq("user_id", user_id).execute()
    rows = res.data or []
    return rows[0] if rows else await get_alarm(user_id, alarm_id)


async def delete_alarm(user_id: str, alarm_id: str) -> bool:
    c = _db()
    if not c:
        return False
    c.table("alarms").delete().eq("id", alarm_id).eq("user_id", user_id).execute()
    return True


async def mark_alarm_event(user_id: str, alarm_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    c = _db()
    if not c:
        return
    try:
        c.table("alarm_events").insert(
            {"alarm_id": alarm_id, "user_id": user_id, "event_type": event_type, "payload": payload or {}}
        ).execute()
    except Exception:
        pass


async def run_due_alarms_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    c = _db()
    if not c:
        return {"processed": 0, "sent": 0, "failed": 0}
    n = _ensure_utc(now or datetime.now(timezone.utc)).isoformat()
    due = (
        c.table("alarms")
        .select("*")
        .eq("is_enabled", True)
        .in_("status", ["scheduled", "failed"])
        .lte("next_trigger_at", n)
        .limit(200)
        .execute()
    ).data or []

    processed = 0
    sent = 0
    failed = 0
    for alarm in due:
        processed += 1
        user_id = str(alarm.get("user_id") or "")
        alarm_id = str(alarm.get("id") or "")
        title = str(alarm.get("title") or "SAYIBI — Alarme")
        body = str(alarm.get("message") or "Rappel arrivé à échéance.")
        ok = False
        # multi-device tokens
        tokens = []
        try:
            rows = c.table("fcm_device_tokens").select("token").eq("user_id", user_id).execute().data or []
            tokens = [str(r.get("token")) for r in rows if r.get("token")]
        except Exception:
            tokens = []
        if not tokens:
            try:
                row = c.table("users").select("fcm_token").eq("id", user_id).single().execute()
                tk = (row.data or {}).get("fcm_token") if row.data else None
                if tk:
                    tokens = [str(tk)]
            except Exception:
                pass
        for tk in list(dict.fromkeys(tokens)):
            try:
                await fcm_service.send_notification(
                    tk,
                    title,
                    body,
                    {"type": "alarm_due", "alarm_id": alarm_id, "user_id": user_id},
                )
                ok = True
            except Exception:
                continue

        if ok:
            sent += 1
            patch = {"status": "triggered", "last_triggered_at": n}
            next_dt = _next_trigger_from_repeat(
                _ensure_utc(datetime.now(timezone.utc)),
                alarm.get("repeat_rule"),
            )
            if next_dt is not None:
                patch["next_trigger_at"] = next_dt.isoformat()
                patch["is_enabled"] = True
                patch["status"] = "scheduled"
            else:
                patch["next_trigger_at"] = None
                patch["is_enabled"] = False
            c.table("alarms").update(patch).eq("id", alarm_id).execute()
            await mark_alarm_event(user_id, alarm_id, "triggered", {"channel": "push"})
        else:
            failed += 1
            c.table("alarms").update({"status": "failed"}).eq("id", alarm_id).execute()
            await mark_alarm_event(user_id, alarm_id, "failed", {"reason": "no_push_delivery"})
    return {"processed": processed, "sent": sent, "failed": failed}

