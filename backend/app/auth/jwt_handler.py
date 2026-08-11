"""JWT token creation and verification for session management."""

from __future__ import annotations

import time
from typing import Any

import jwt

from app.utils.config import settings


def create_access_token(data: dict[str, Any]) -> str:
    """Create a signed JWT containing the given claims."""
    payload = data.copy()
    payload["exp"] = int(time.time()) + settings.JWT_EXPIRY_MINUTES * 60
    payload["iat"] = int(time.time())
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT.  Returns claims dict or None on failure."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
