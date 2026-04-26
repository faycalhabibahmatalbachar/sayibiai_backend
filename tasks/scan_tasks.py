"""Tâches Celery — nettoyage des fichiers temporaires et enregistrements."""

import logging
from datetime import datetime, timezone, timedelta

from tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(bind=True)
def cleanup_temp_files(self):
    """Supprime les fichiers vidéo temporaires de plus de 2h et les enregistrements expirés."""
    import asyncio
    try:
        asyncio.run(_async_cleanup())
    except Exception as exc:
        logger.error("cleanup_temp_files error: %s", exc)


async def _async_cleanup():
    from core.database import get_supabase_admin
    c = get_supabase_admin()
    if not c:
        return

    now = datetime.now(timezone.utc)

    # Supprimer les vidéos en état "pending" de plus de 2h
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    try:
        c.table("generated_videos").delete().eq(
            "status", "pending"
        ).lt("created_at", two_hours_ago).execute()
        logger.info("Cleaned up stale pending videos")
    except Exception as e:
        logger.warning("Video cleanup error: %s", e)

    # Supprimer les enregistrements d'appels de plus de 30 jours (opt-in courte durée)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    try:
        c.table("inbound_calls").update({
            "recording_url": None,
        }).lt("created_at", thirty_days_ago).execute()
        logger.info("Cleaned up old call recordings")
    except Exception as e:
        logger.warning("Call recording cleanup error: %s", e)

    # Nettoyer les sessions de surveillance de plus de 7 jours
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    try:
        c.table("screen_sessions").delete().lt("session_start", seven_days_ago).execute()
        logger.info("Cleaned up old screen sessions")
    except Exception as e:
        logger.warning("Screen session cleanup error: %s", e)
