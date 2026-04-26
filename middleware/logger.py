"""Journalisation des requêtes HTTP (durée, statut, endpoint)."""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sayibi.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        user_id = getattr(request.state, "user_id", None)
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s status=%s duration_ms=%.2f user_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            user_id,
        )
        return response


def setup_logging(debug: bool = False, log_level: str = "INFO") -> None:
    if debug:
        level = logging.DEBUG
    else:
        level = getattr(logging, log_level.upper(), None)
        if not isinstance(level, int):
            level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
