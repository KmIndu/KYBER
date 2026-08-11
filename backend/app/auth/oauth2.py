"""OAuth2 / OIDC helpers — provider-agnostic SSO flow.

Supports any OAuth2/OIDC provider (Azure AD, Okta, Keycloak, Google, etc.)
by configuring the four standard endpoints via environment variables.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from app.utils.config import settings

# In-memory state store (CSRF protection for the auth flow)
_pending_states: set[str] = set()


def get_authorization_url() -> tuple[str, str]:
    """Build the provider's authorization URL and return (url, state)."""
    state = secrets.token_urlsafe(32)
    _pending_states.add(state)

    params = {
        "client_id": settings.OAUTH2_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.OAUTH2_REDIRECT_URI,
        "scope": settings.OAUTH2_SCOPES,
        "state": state,
    }
    url = f"{settings.OAUTH2_AUTHORIZATION_URL}?{urlencode(params)}"
    return url, state


def validate_state(state: str) -> bool:
    """Check and consume a state token (one-time use)."""
    if state in _pending_states:
        _pending_states.discard(state)
        return True
    return False


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange the authorization code for access & id tokens."""
    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        resp = await client.post(
            settings.OAUTH2_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.OAUTH2_CLIENT_ID,
                "client_secret": settings.OAUTH2_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.OAUTH2_REDIRECT_URI,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_userinfo(access_token: str) -> dict:
    """Call the provider's userinfo endpoint."""
    async with httpx.AsyncClient(timeout=10, verify=False) as client:
        resp = await client.get(
            settings.OAUTH2_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()
