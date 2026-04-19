"""Limitation de débit par utilisateur via Redis (Upstash compatible)."""

import time
from typing import Callable, Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from core.redis_client import get_async_redis
from core.security import get_subject_from_token

DEFAULT_LIMIT = 100
WINDOW_SECONDS = 3600


async def check_rate_limit(identifier: str, limit: int = DEFAULT_LIMIT) -> None:
    """Compteur fixe par fenêtre horaire ; lève 429 si dépassement."""
    r = await get_async_redis()
    if not r:
        return
    window_bucket = int(time.time()) // WINDOW_SECONDS
    key = f"rl:{identifier}:{window_bucket}"
    val = await r.incr(key)
    if val == 1:
        await r.expire(key, WINDOW_SECONDS + 30)
    if val > limit:
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes. Réessayez plus tard.",
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limite globale par utilisateur JWT ou par IP."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in ("/health", "/", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        if request.url.path.startswith("/api/v1/internal/"):
            return await call_next(request)
        auth = request.headers.get("authorization") or ""
        identifier: Optional[str] = None
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            identifier = get_subject_from_token(token)
        if not identifier:
            identifier = f"ip:{request.client.host}" if request.client else "ip:unknown"
        else:
            identifier = f"user:{identifier}"
        try:
            await check_rate_limit(identifier)
        except HTTPException as e:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=e.status_code,
                content={
                    "success": False,
                    "data": None,
                    "message": e.detail,
                    "code": e.status_code,
                },
            )
        return await call_next(request)
