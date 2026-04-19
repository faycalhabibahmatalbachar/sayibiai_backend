"""Connexion Redis asynchrone partagée (Upstash)."""

import logging
from typing import Optional

import redis.asyncio as redis

from core.config import get_settings

logger = logging.getLogger(__name__)

_redis: Optional[redis.Redis] = None


async def get_async_redis() -> Optional[redis.Redis]:
    global _redis
    settings = get_settings()
    url = (settings.upstash_redis_url or "").strip()
    if not url:
        return None
    # L’endpoint REST (https://…upstash.io) sert à l’API HTTP /ping, pas au client redis-py.
    if url.startswith("http://") or url.startswith("https://"):
        logger.warning(
            "UPSTASH_REDIS_URL est en HTTPS (REST). Pour le rate limit, utilisez l’URL "
            "Redis (rediss://…) depuis Upstash → votre DB → Connect."
        )
        return None
    if _redis is None:
        _redis = redis.from_url(url, decode_responses=True)
    return _redis


def reset_async_redis() -> None:
    """Invalide le client partagé (ex. après erreur de connexion) pour forcer une reconnexion."""
    global _redis
    _redis = None
