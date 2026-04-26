"""Router Proactivité — triggers calendrier, trafic, météo, agenda."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.config import get_settings
from core.database import get_supabase_admin
from core.deps import get_current_user_id
from core.responses import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/proactivity", tags=["proactivity"])


class ProactivitySettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    urgency_threshold: Optional[str] = None
    allowed_hours: Optional[dict] = None
    enabled_triggers: Optional[List[str]] = None


class CalendarConnectRequest(BaseModel):
    provider: str = Field(default="google", description="google|outlook")
    auth_code: str
    redirect_uri: str


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

@router.get("/settings")
async def get_settings_route(user_id: str = Depends(get_current_user_id)):
    """Retourne les paramètres de proactivité de l'utilisateur."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response({}, "OK")
        res = c.table("proactivity_settings").select("*").eq("user_id", user_id).execute()
        if res.data:
            return success_response(res.data[0], "OK")
        # Paramètres par défaut
        defaults = {
            "user_id": user_id,
            "enabled": False,
            "urgency_threshold": "urgent",
            "allowed_hours": {"start": "08:00", "end": "22:00"},
            "enabled_triggers": ["traffic", "weather", "calendar_conflict"],
            "calendar_connected": False,
        }
        return success_response(defaults, "Paramètres par défaut")
    except Exception as e:
        return error_response(str(e), 500)


@router.put("/settings")
async def update_settings(
    body: ProactivitySettingsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Met à jour les paramètres de proactivité."""
    try:
        c = get_supabase_admin()
        if c:
            update_data = {"user_id": user_id}
            if body.enabled is not None:
                update_data["enabled"] = body.enabled
            if body.urgency_threshold is not None:
                update_data["urgency_threshold"] = body.urgency_threshold
            if body.allowed_hours is not None:
                update_data["allowed_hours"] = body.allowed_hours
            if body.enabled_triggers is not None:
                update_data["enabled_triggers"] = body.enabled_triggers
            c.table("proactivity_settings").upsert(update_data).execute()
        return success_response({"updated": True}, "Paramètres mis à jour")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/history")
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """Historique des interventions proactives."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")
        res = (
            c.table("proactive_calls")
            .select("*")
            .eq("user_id", user_id)
            .order("call_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


# ---------------------------------------------------------------------------
# Calendrier
# ---------------------------------------------------------------------------

@router.post("/calendar/connect")
async def connect_calendar(
    body: CalendarConnectRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Connecte Google Calendar via OAuth."""
    s = get_settings()
    try:
        # Échanger le code contre des tokens
        token_data = await _exchange_google_oauth(
            body.auth_code,
            body.redirect_uri,
            s,
        )
        if not token_data:
            return error_response("Échec de l'authentification Google", 400)

        # Stocker les tokens et mettre à jour les paramètres
        c = get_supabase_admin()
        if c:
            c.table("proactivity_settings").upsert({
                "user_id": user_id,
                "calendar_connected": True,
                "calendar_provider": body.provider,
                "calendar_access_token": token_data.get("access_token", ""),
                "calendar_refresh_token": token_data.get("refresh_token", ""),
            }).execute()

        return success_response(
            {"connected": True, "provider": body.provider},
            "Calendrier connecté",
        )
    except Exception as e:
        return error_response(str(e), 500)


async def _exchange_google_oauth(auth_code: str, redirect_uri: str, s: Any) -> Optional[dict]:
    """Échange un code OAuth Google contre des tokens."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": auth_code,
                    "client_id": s.google_oauth_client_id if hasattr(s, 'google_oauth_client_id') else "",
                    "client_secret": s.google_oauth_client_secret if hasattr(s, 'google_oauth_client_secret') else "",
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if r.status_code < 400:
                return r.json()
    except Exception as e:
        logger.warning("Google OAuth exchange error: %s", e)
    return None


@router.post("/calendar/sync")
async def sync_calendar(user_id: str = Depends(get_current_user_id)):
    """Force la synchronisation de l'agenda."""
    try:
        events = await _fetch_calendar_events(user_id)
        return success_response(
            {"synced": len(events), "events": events[:5]},
            f"{len(events)} événements synchronisés",
        )
    except Exception as e:
        return error_response(str(e), 500)


async def _fetch_calendar_events(user_id: str) -> List[dict]:
    """Récupère les événements Google Calendar."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        settings_res = c.table("proactivity_settings").select("*").eq("user_id", user_id).execute()
        if not settings_res.data:
            return []
        settings = settings_res.data[0]
        access_token = settings.get("calendar_access_token", "")
        if not access_token:
            return []

        now = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "timeMin": now,
                    "maxResults": 20,
                    "singleEvents": True,
                    "orderBy": "startTime",
                },
            )
            if r.status_code >= 400:
                return []
            items = r.json().get("items", [])

        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            event = {
                "external_id": item.get("id"),
                "title": item.get("summary", "Sans titre"),
                "start_time": start.get("dateTime") or start.get("date"),
                "end_time": end.get("dateTime") or end.get("date"),
                "location": item.get("location", ""),
                "participants": [
                    a.get("email") for a in item.get("attendees", [])
                ],
                "provider": "google",
            }
            events.append(event)
            try:
                c.table("calendar_events_cache").upsert({
                    "user_id": user_id,
                    **event,
                    "last_synced": "now()",
                }).execute()
            except Exception:
                pass

        return events
    except Exception as e:
        logger.warning("Calendar sync error: %s", e)
        return []


@router.get("/trigger-check")
async def trigger_check(user_id: str = Depends(get_current_user_id)):
    """Force une vérification des déclencheurs proactifs (debug)."""
    try:
        triggers_found = []

        # Vérifier calendrier
        events = await _fetch_calendar_events(user_id)
        if events:
            triggers_found.append({
                "type": "calendar",
                "events": [e.get("title") for e in events[:3]],
            })

        return success_response(
            {"triggers": triggers_found, "checked_at": datetime.now(timezone.utc).isoformat()},
            f"{len(triggers_found)} déclencheurs vérifiés",
        )
    except Exception as e:
        return error_response(str(e), 500)
