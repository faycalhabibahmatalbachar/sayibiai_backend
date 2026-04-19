"""JWT — création et vérification des tokens d'accès et de rafraîchissement."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

from core.config import get_settings


def create_access_token(
    subject: str,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Émet un JWT d'accès (sub = identifiant utilisateur)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token_value() -> str:
    """Génère une valeur opaque pour le refresh token (stockée côté Redis)."""
    return secrets.token_urlsafe(48)


def decode_token(token: str) -> Dict[str, Any]:
    """Décode et valide un JWT ; lève JWTError si invalide."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


def get_subject_from_token(token: str) -> Optional[str]:
    """Extrait le subject (user_id) d'un JWT valide."""
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if payload.get("type") != "access":
            return None
        return str(sub) if sub is not None else None
    except JWTError:
        return None
