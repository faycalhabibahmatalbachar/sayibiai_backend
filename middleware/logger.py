"""Journalisation des requêtes HTTP (durée, statut, endpoint)."""

import logging
import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sayibi.request")


def _extract_user_id_from_request(request: Request) -> Optional[str]:
    """Extrait user_id depuis le JWT Bearer sans le vérifier (logging only)."""
    # Priorité 1: déjà défini sur request.state
    uid = getattr(request.state, "user_id", None)
    if uid:
        return uid
    # Priorité 2: décoder le JWT sans validation pour le log
    try:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            import base64, json
            token = auth[7:]
            parts = token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                # Padding base64
                padding = 4 - len(payload_b64) % 4
                if padding != 4:
                    payload_b64 += "=" * padding
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                return payload.get("sub") or payload.get("user_id")
    except Exception:
        pass
    return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        user_id = _extract_user_id_from_request(request)
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s status=%s duration_ms=%.2f user_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            user_id or "anon",
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
