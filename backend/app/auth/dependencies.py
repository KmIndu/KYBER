"""FastAPI dependencies for route-level authentication."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_handler import decode_access_token
from app.utils.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict | None:
    """Return the current authenticated user or raise 401.

    When AUTH_ENABLED is False every request is allowed through and this
    dependency returns a stub user dict so downstream code works unchanged.
    """
    if not settings.AUTH_ENABLED:
        return {"sub": "anonymous", "name": "Anonymous", "email": ""}

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired or invalid")

    return claims
