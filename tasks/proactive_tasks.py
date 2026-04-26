"""Tâches Celery proactives — calendrier, trafic, météo, mémoire."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

from tasks.celery_app import app

logger = logging.getLogger(__name__)


def _get_db():
    from core.database import get_supabase_admin
    return get_supabase_admin()


def _get_settings():
    from core.config import get_settings
    return get_settings()


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def check_calendar_and_traffic(self):
    """
    Vérifie le calendrier et le trafic pour tous les utilisateurs actifs.
    Déclenche des notifications proactives si nécessaire.
    """
    import asyncio
    try:
        asyncio.run(_async_check_calendar_traffic())
    except Exception as exc:
        logger.error("check_calendar_and_traffic error: %s", exc)
        raise self.retry(exc=exc)


async def _async_check_calendar_traffic():
    c = _get_db()
    s = _get_settings()
    if not c:
        return

    # Récupérer utilisateurs avec proactivité activée
    try:
        res = (
            c.table("proactivity_settings")
            .select("user_id,allowed_hours,enabled_triggers,calendar_access_token")
            .eq("enabled", True)
            .eq("calendar_connected", True)
            .execute()
        )
        users = res.data or []
    except Exception as e:
        logger.error("Failed to fetch proactive users: %s", e)
        return

    now = datetime.now(timezone.utc)
    for user_setting in users:
        user_id = user_setting.get("user_id")
        if not user_id:
            continue

        # Vérifier les plages horaires autorisées
        allowed = user_setting.get("allowed_hours", {})
        if not _is_in_allowed_hours(now, allowed):
            continue

        enabled_triggers = user_setting.get("enabled_triggers", [])
        access_token = user_setting.get("calendar_access_token", "")

        if not access_token:
            continue

        try:
            await _check_user_calendar(user_id, access_token, s, enabled_triggers, c)
        except Exception as e:
            logger.warning("Calendar check error for user %s: %s", user_id, e)


def _is_in_allowed_hours(now: datetime, allowed: dict) -> bool:
    """Vérifie si l'heure actuelle est dans les plages autorisées."""
    try:
        start_str = allowed.get("start", "08:00")
        end_str = allowed.get("end", "22:00")
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        return start_minutes <= current_minutes <= end_minutes
    except Exception:
        return True


async def _check_user_calendar(
    user_id: str,
    access_token: str,
    s: Any,
    enabled_triggers: List[str],
    db: Any,
):
    """Vérifie les événements calendrier d'un utilisateur et génère des triggers."""
    now = datetime.now(timezone.utc)
    time_window = now + timedelta(hours=2)

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": now.isoformat(),
                "timeMax": time_window.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 5,
            },
        )
        if r.status_code >= 400:
            return
        items = r.json().get("items", [])

    for event in items:
        location = event.get("location", "")
        start_str = event.get("start", {}).get("dateTime")
        if not start_str:
            continue

        # Vérifier trafic si l'événement a un lieu
        if "traffic" in enabled_triggers and location and s.google_maps_api_key if hasattr(s, "google_maps_api_key") else False:
            await _check_traffic_for_event(user_id, event, location, db, s)

        # Détecter les conflits d'agenda
        if "calendar_conflict" in enabled_triggers:
            await _check_calendar_conflicts(user_id, items, db)


async def _check_traffic_for_event(
    user_id: str,
    event: dict,
    destination: str,
    db: Any,
    s: Any,
):
    """Vérifie le trafic vers le lieu d'un événement."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={
                    "origins": "current+location",
                    "destinations": destination,
                    "departure_time": "now",
                    "traffic_model": "best_guess",
                    "key": s.google_maps_api_key if hasattr(s, "google_maps_api_key") else "",
                },
            )
            if r.status_code >= 400:
                return
            data = r.json()

        element = (
            data.get("rows", [{}])[0]
            .get("elements", [{}])[0]
        )
        duration_in_traffic = element.get("duration_in_traffic", {}).get("value", 0)
        duration_normal = element.get("duration", {}).get("value", 0)

        if duration_normal > 0 and duration_in_traffic > duration_normal * 1.2:
            # Trafic 20% plus long que normal — créer une alerte proactive
            trigger_data = {
                "event_title": event.get("summary", "Événement"),
                "destination": destination,
                "normal_duration": duration_normal,
                "traffic_duration": duration_in_traffic,
                "traffic_delay": duration_in_traffic - duration_normal,
            }
            await _create_proactive_trigger(user_id, "traffic", trigger_data, db)
    except Exception as e:
        logger.debug("Traffic check error: %s", e)


async def _check_calendar_conflicts(user_id: str, events: List[dict], db: Any):
    """Détecte les conflits de plages dans l'agenda."""
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            e1 = events[i]
            e2 = events[j]
            start1 = e1.get("start", {}).get("dateTime")
            end1 = e1.get("end", {}).get("dateTime")
            start2 = e2.get("start", {}).get("dateTime")
            if start1 and end1 and start2:
                if start2 < end1:
                    trigger_data = {
                        "event1": e1.get("summary", "Événement 1"),
                        "event2": e2.get("summary", "Événement 2"),
                    }
                    await _create_proactive_trigger(user_id, "calendar_conflict", trigger_data, db)
                    return


async def _create_proactive_trigger(
    user_id: str,
    trigger_type: str,
    trigger_data: dict,
    db: Any,
):
    """Crée un enregistrement de trigger proactif et envoie une notification push."""
    try:
        import uuid
        db.table("proactive_calls").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "trigger_type": trigger_type,
            "trigger_data": trigger_data,
            "call_timestamp": "now()",
        }).execute()

        # Envoyer notification push
        from services.notification_service import send_to_user_devices
        messages = {
            "traffic": "⚠️ Trafic dense pour votre prochain événement. Partez plus tôt !",
            "calendar_conflict": "📅 Conflit d'agenda détecté. Vérifiez votre calendrier.",
            "weather": "🌧️ Météo défavorable pour votre événement extérieur.",
        }
        msg = messages.get(trigger_type, "ℹ️ Alerte proactive de ChadGPT")
        await send_to_user_devices(user_id, title="ChadGPT", body=msg, data={"type": trigger_type})
    except Exception as e:
        logger.warning("Create proactive trigger error: %s", e)


@app.task(bind=True, max_retries=3, default_retry_delay=120)
def check_weather_for_events(self):
    """Vérifie la météo pour les événements extérieurs des prochaines 3h."""
    import asyncio
    try:
        asyncio.run(_async_check_weather())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _async_check_weather():
    c = _get_db()
    s = _get_settings()
    if not c:
        return

    try:
        res = (
            c.table("proactivity_settings")
            .select("user_id,calendar_access_token")
            .eq("enabled", True)
            .execute()
        )
        users = res.data or []
    except Exception:
        return

    openweather_key = getattr(s, "openweathermap_api_key", "")
    if not openweather_key:
        return

    now = datetime.now(timezone.utc)
    for user_setting in users:
        user_id = user_setting.get("user_id")
        if not user_id:
            continue
        try:
            await _check_user_weather(user_id, openweather_key, c)
        except Exception as e:
            logger.warning("Weather check error for %s: %s", user_id, e)


async def _check_user_weather(user_id: str, api_key: str, db: Any):
    """Vérifie la météo pour les événements extérieurs d'un utilisateur."""
    now = datetime.now(timezone.utc)
    try:
        res = (
            db.table("calendar_events_cache")
            .select("*")
            .eq("user_id", user_id)
            .gt("start_time", now.isoformat())
            .lt("start_time", (now + timedelta(hours=3)).isoformat())
            .not_.is_("location", "null")
            .execute()
        )
        events = res.data or []
    except Exception:
        return

    for event in events:
        location = event.get("location", "")
        if not location:
            continue

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": location, "appid": api_key, "lang": "fr"},
            )
            if r.status_code >= 400:
                continue
            weather = r.json()

        conditions = [w.get("main", "") for w in weather.get("weather", [])]
        bad_conditions = {"Rain", "Thunderstorm", "Snow", "Drizzle", "Tornado", "Squall"}
        if any(c in bad_conditions for c in conditions):
            await _create_proactive_trigger(
                user_id,
                "weather",
                {
                    "event_title": event.get("title", "Événement"),
                    "location": location,
                    "conditions": conditions,
                },
                db,
            )


@app.task(bind=True)
def memory_consolidation(self):
    """Consolide les snippets de mémoire utilisateur (run nocturne)."""
    import asyncio
    try:
        asyncio.run(_async_memory_consolidation())
    except Exception as exc:
        logger.error("memory_consolidation error: %s", exc)


async def _async_memory_consolidation():
    """Extrait les faits importants des 24 dernières heures et crée des memory_snippets."""
    c = _get_db()
    s = _get_settings()
    if not c or not s.openai_api_key:
        return

    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(hours=24)).isoformat()

    try:
        # Récupérer les utilisateurs actifs dans les 24 dernières heures
        sessions_res = (
            c.table("chat_sessions")
            .select("user_id")
            .gt("created_at", yesterday)
            .execute()
        )
        user_ids = list(set(s["user_id"] for s in (sessions_res.data or [])))
    except Exception as e:
        logger.error("Memory consolidation fetch users error: %s", e)
        return

    for user_id in user_ids:
        try:
            await _consolidate_user_memory(user_id, yesterday, c, s)
        except Exception as e:
            logger.warning("Memory consolidation error for %s: %s", user_id, e)


async def _consolidate_user_memory(user_id: str, since: str, db: Any, s: Any):
    """Extrait et consolide les faits importants pour un utilisateur."""
    import json, uuid, httpx

    # Récupérer les messages récents
    sessions = db.table("chat_sessions").select("id").eq("user_id", user_id).gt("created_at", since).execute()
    if not sessions.data:
        return

    session_ids = [s["id"] for s in sessions.data]
    messages_res = (
        db.table("messages")
        .select("role,content")
        .in_("session_id", session_ids)
        .eq("role", "user")
        .execute()
    )
    messages = messages_res.data or []
    if not messages:
        return

    combined_text = "\n".join(m.get("content", "")[:200] for m in messages[:20])

    prompt = (
        "Analyse ces messages d'un utilisateur et extrais les faits importants "
        "sur lui (préférences, habitudes, informations clés, projets). "
        "Réponds en JSON avec une liste 'facts' de strings concises.\n\n"
        f"Messages:\n{combined_text}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.openai_api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "max_tokens": 500,
            },
        )
        if r.status_code >= 400:
            return
        content = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        facts = parsed.get("facts", [])

    for fact in facts[:10]:
        try:
            db.table("memory_snippets").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": fact,
                "importance_score": 0.7,
            }).execute()
        except Exception:
            pass
