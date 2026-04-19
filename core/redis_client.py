"""Connexion Redis asynchrone partagée (Upstash)."""

from typing import Optional

import redis.asyncio as redis

from core.config import get_settings

_redis: Optional[redis.Redis] = None


async def get_async_redis() -> Optional[redis.Redis]:
    global _redis
    settings = get_settings()
    if not settings.upstash_redis_url:
        return None
    if _redis is None:
        _redis = redis.from_url(
            settings.upstash_redis_url,
            decode_responses=True,
        )
    return _redis
