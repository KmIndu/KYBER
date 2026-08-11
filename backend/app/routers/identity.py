"""Identity derivation router.

  POST /identity/derive       — derive emails/usernames from a single name
  POST /identity/derive-batch — derive for multiple names with uniqueness
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.generators.identity_derivation_engine import IdentityDerivationEngine

router = APIRouter(prefix="/identity", tags=["Identity Derivation"])
logger = logging.getLogger(__name__)


# ── Request/Response Models ───────────────────────────────────


class DeriveRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    locale: str | None = None
    company_domain: str | None = None
    company_pattern: str | None = None
    num_emails: int = Field(default=3, ge=1, le=10)
    num_usernames: int = Field(default=3, ge=1, le=10)


class NameEntry(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None


class DeriveBatchRequest(BaseModel):
    names: list[NameEntry] = Field(..., min_length=1)
    locale: str | None = None
    company_domain: str | None = None
    company_pattern: str | None = None
    num_emails: int = Field(default=3, ge=1, le=10)
    num_usernames: int = Field(default=3, ge=1, le=10)


# ── Endpoints ─────────────────────────────────────────────────


@router.post("/derive")
async def derive_identity(req: DeriveRequest):
    """Derive emails and usernames from a person's name."""
    engine = IdentityDerivationEngine(
        locale=req.locale,
        company_domain=req.company_domain,
        company_pattern=req.company_pattern,
    )

    result = engine.derive(
        first_name=req.first_name,
        last_name=req.last_name,
        full_name=req.full_name,
        num_emails=req.num_emails,
        num_usernames=req.num_usernames,
    )

    return result.to_dict()


@router.post("/derive-batch")
async def derive_batch(req: DeriveBatchRequest):
    """Derive identities for multiple names with uniqueness guarantees."""
    engine = IdentityDerivationEngine(
        locale=req.locale,
        company_domain=req.company_domain,
        company_pattern=req.company_pattern,
    )

    names = [entry.model_dump() for entry in req.names]
    result = engine.derive_batch(
        names=names,
        num_emails=req.num_emails,
        num_usernames=req.num_usernames,
    )

    return result.to_dict()
