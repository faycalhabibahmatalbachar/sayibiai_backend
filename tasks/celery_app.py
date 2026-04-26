"""Application Celery — configuration et initialisation."""

import os
from celery import Celery
from celery.schedules import crontab

from core.config import get_settings

s = get_settings()

# Broker et backend via Redis (Upstash)
BROKER_URL = s.upstash_redis_url or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = s.upstash_redis_url or os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

app = Celery(
    "chadgpt",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "tasks.proactive_tasks",
        "tasks.social_tasks",
        "tasks.scan_tasks",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Rate limiting global
    task_annotations={
        "tasks.proactive_tasks.check_calendar_and_traffic": {"rate_limit": "12/m"},
        "tasks.social_tasks.social_media_monitor": {"rate_limit": "4/m"},
    },
)

# Schedule Celery Beat
app.conf.beat_schedule = {
    # Vérification calendrier + trafic toutes les 5 minutes
    "check-calendar-traffic": {
        "task": "tasks.proactive_tasks.check_calendar_and_traffic",
        "schedule": 300,  # 5 minutes
    },
    # Météo toutes les 30 minutes
    "check-weather": {
        "task": "tasks.proactive_tasks.check_weather_for_events",
        "schedule": 1800,
    },
    # Monitoring réseaux sociaux toutes les 15 minutes
    "monitor-social": {
        "task": "tasks.social_tasks.social_media_monitor",
        "schedule": 900,
    },
    # Auto-publication des posts programmés toutes les minutes
    "auto-publish-posts": {
        "task": "tasks.social_tasks.social_auto_publish",
        "schedule": 60,
    },
    # Consolidation de mémoire chaque jour à 3h
    "memory-consolidation": {
        "task": "tasks.proactive_tasks.memory_consolidation",
        "schedule": crontab(hour=3, minute=0),
    },
    # Nettoyage des fichiers temporaires toutes les heures
    "cleanup-temp": {
        "task": "tasks.scan_tasks.cleanup_temp_files",
        "schedule": 3600,
    },
}

if __name__ == "__main__":
    app.start()
