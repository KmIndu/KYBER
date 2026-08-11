"""Application configuration — reads from environment variables.

All settings have sensible defaults for local development.  Override via
``.env`` file or environment variables in production.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Centralised application settings read from environment variables."""

    # Core
    APP_NAME: str = os.getenv("APP_NAME", "Synthetic Data Generator")
    APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # OAuth2 / SSO
    OAUTH2_PROVIDER: str = os.getenv("OAUTH2_PROVIDER", "generic")  # generic | azure | okta | keycloak
    OAUTH2_CLIENT_ID: str = os.getenv("OAUTH2_CLIENT_ID", "")
    OAUTH2_CLIENT_SECRET: str = os.getenv("OAUTH2_CLIENT_SECRET", "")
    OAUTH2_AUTHORITY: str = os.getenv("OAUTH2_AUTHORITY", "")  # e.g. https://login.microsoftonline.com/{tenant}/v2.0
    OAUTH2_REDIRECT_URI: str = os.getenv("OAUTH2_REDIRECT_URI", "http://localhost:5173/auth/callback")
    OAUTH2_SCOPES: str = os.getenv("OAUTH2_SCOPES", "openid profile email")
    OAUTH2_AUTHORIZATION_URL: str = os.getenv("OAUTH2_AUTHORIZATION_URL", "")
    OAUTH2_TOKEN_URL: str = os.getenv("OAUTH2_TOKEN_URL", "")
    OAUTH2_USERINFO_URL: str = os.getenv("OAUTH2_USERINFO_URL", "")
    OAUTH2_LOGOUT_URL: str = os.getenv("OAUTH2_LOGOUT_URL", "")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production-use-a-strong-secret")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRY_MINUTES: int = int(os.getenv("JWT_EXPIRY_MINUTES", "15"))
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "true").lower() == "true"

    # SMTP / OTP email settings
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "noreply@sunlife.com")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    OTP_EXPIRY_SECONDS: int = int(os.getenv("OTP_EXPIRY_SECONDS", "300"))  # 5 minutes

    # Microsoft Graph API (for sending OTP emails in production)
    GRAPH_CLIENT_ID: str = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET: str = os.getenv("GRAPH_CLIENT_SECRET", "")
    GRAPH_TENANT_ID: str = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_SENDER_EMAIL: str = os.getenv("GRAPH_SENDER_EMAIL", "noreply@sunlife.com")

    # AI provider keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # AI gateway
    AI_GATEWAY_URL: str = os.getenv("AI_GATEWAY_URL", "")
    AI_GATEWAY_TOKEN: str = os.getenv("AI_GATEWAY_TOKEN", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "claude-opus-4-6")
    AI_API_FORMAT: str = os.getenv("AI_API_FORMAT", "openai")
    AI_TIMEOUT: int = int(os.getenv("AI_TIMEOUT", "30"))
    AI_MAX_RETRIES: int = int(os.getenv("AI_MAX_RETRIES", "3"))


settings = Settings()
