"""Service de cache Redis — TTLs métier et helpers."""

import hashlib
import json
import logging
from typing import Any, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)

# TTL en secondes
TTL_LLM_RESPONSE = 3600          # 1h
TTL_IMAGE_URL = 0                 # Permanent (pas d'expiry)
TTL_TRANSCRIPT = 0                # Permanent
TTL_VIDEO_ANALYSIS = 86400        # 24h
TTL_CONTACTS = 300                # 5min
TTL_SOCIAL_POST_PENDING = 604800  # 7 jours max
TTL_SOCIAL_TRENDING = 900         # 15min


def _get_redis():
    """Retourne le client Redis Upstash ou None si non configuré."""
    try:
        import redis.asyncio as aioredis
        s = get_settings()
        if not s.upstash_redis_url:
            return None
        return aioredis.from_url(
            s.upstash_redis_url,
            password=s.upstash_redis_token or None,
            decode_responses=True,
            socket_connect_timeout=5,
        )
    except Exception as e:
        logger.debug("Redis init error: %s", e)
        return None


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


async def get(key: str) -> Optional[Any]:
    """Récupère une valeur depuis Redis. Retourne None si absent/erreur."""
    try:
        r = _get_redis()
        if not r:
            return None
        async with r:
            raw = await r.get(key)
            if raw is None:
                return None
            return json.loads(raw)
    except Exception as e:
        logger.debug("cache get error [%s]: %s", key, e)
        return None


async def set(key: str, value: Any, ttl: int = 3600) -> bool:
    """Stocke une valeur dans Redis. Retourne True si succès."""
    try:
        r = _get_redis()
        if not r:
            return False
        raw = json.dumps(value, ensure_ascii=False)
        async with r:
            if ttl and ttl > 0:
                await r.setex(key, ttl, raw)
            else:
                await r.set(key, raw)
        return True
    except Exception as e:
        logger.debug("cache set error [%s]: %s", key, e)
        return False


async def delete(key: str) -> bool:
    try:
        r = _get_redis()
        if not r:
            return False
        async with r:
            await r.delete(key)
        return True
    except Exception as e:
        logger.debug("cache delete error [%s]: %s", key, e)
        return False


async def get_llm_response(message: str) -> Optional[str]:
    key = f"llm:{_hash_key(message)}"
    result = await get(key)
    return result.get("text") if isinstance(result, dict) else None


async def set_llm_response(message: str, response: str) -> None:
    key = f"llm:{_hash_key(message)}"
    await set(key, {"text": response}, ttl=TTL_LLM_RESPONSE)


async def get_image_url(optimized_prompt: str) -> Optional[str]:
    key = f"img:{_hash_key(optimized_prompt)}"
    result = await get(key)
    return result.get("url") if isinstance(result, dict) else None


async def set_image_url(optimized_prompt: str, url: str) -> None:
    key = f"img:{_hash_key(optimized_prompt)}"
    await set(key, {"url": url}, ttl=TTL_IMAGE_URL)


async def get_transcript(audio_hash: str) -> Optional[str]:
    key = f"transcript:{audio_hash}"
    result = await get(key)
    return result.get("text") if isinstance(result, dict) else None


async def set_transcript(audio_hash: str, text: str) -> None:
    key = f"transcript:{audio_hash}"
    await set(key, {"text": text}, ttl=TTL_TRANSCRIPT)


async def get_video_analysis(video_url: str) -> Optional[dict]:
    key = f"video_analysis:{_hash_key(video_url)}"
    return await get(key)


async def set_video_analysis(video_url: str, analysis: dict) -> None:
    key = f"video_analysis:{_hash_key(video_url)}"
    await set(key, analysis, ttl=TTL_VIDEO_ANALYSIS)


async def get_contacts(user_id: str, query: str) -> Optional[list]:
    key = f"contacts:{user_id}:{_hash_key(query)}"
    return await get(key)


async def set_contacts(user_id: str, query: str, results: list) -> None:
    key = f"contacts:{user_id}:{_hash_key(query)}"
    await set(key, results, ttl=TTL_CONTACTS)


async def get_social_trending(platform: str) -> Optional[list]:
    key = f"trending:{platform}"
    return await get(key)


async def set_social_trending(platform: str, trends: list) -> None:
    key = f"trending:{platform}"
    await set(key, trends, ttl=TTL_SOCIAL_TRENDING)


async def invalidate_user_contacts(user_id: str) -> None:
    """Invalide toutes les entrées de contacts pour un utilisateur."""
    try:
        r = _get_redis()
        if not r:
            return
        async with r:
            keys = await r.keys(f"contacts:{user_id}:*")
            if keys:
                await r.delete(*keys)
    except Exception as e:
        logger.debug("cache invalidate error: %s", e)


# Rate limiting helpers
async def get_rate_count(user_id: str, resource: str, window: str = "day") -> int:
    key = f"rate:{user_id}:{resource}:{window}"
    result = await get(key)
    return int(result) if result is not None else 0


async def increment_rate_count(user_id: str, resource: str, window: str = "day") -> int:
    """Incrémente et retourne le nouveau compteur. TTL = 1 jour."""
    try:
        r = _get_redis()
        if not r:
            return 0
        key = f"rate:{user_id}:{resource}:{window}"
        async with r:
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, 86400)
            return int(count)
    except Exception as e:
        logger.debug("rate increment error: %s", e)
        return 0
