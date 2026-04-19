"""Attache user_id à request.state pour le logging."""

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.security import get_subject_from_token


class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            request.state.user_id = get_subject_from_token(auth[7:].strip())
        else:
            request.state.user_id = None
        return await call_next(request)
