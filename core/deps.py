"""Dépendances FastAPI — utilisateur courant depuis JWT."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.security import get_subject_from_token

security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Extrait l'identifiant utilisateur du Bearer JWT."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
        )
    sub = get_subject_from_token(credentials.credentials)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
        )
    return sub


async def optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Utilisateur optionnel (routes publiques avec enrichissement si connecté)."""
    if not credentials or not credentials.credentials:
        return None
    return get_subject_from_token(credentials.credentials)
