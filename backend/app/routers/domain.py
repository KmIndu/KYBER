"""Domain detection router.

  POST /domain/detect  — detect business domain from session data
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.generators.domain_engine import DomainDetectionEngine
from app.models.domain import DomainResult
from app.services.session_store import store

router = APIRouter(prefix="/domain", tags=["Domain Detection"])
logger = logging.getLogger(__name__)


@router.post("/detect", response_model=DomainResult)
async def detect_domain(
    session_id: str = Query(..., description="Session ID from /upload"),
):
    """Detect the business domain from parsed schema, OpenAPI, and BDD data."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.schema and not session.openapi and not session.bdd:
        raise HTTPException(
            status_code=400,
            detail="No parsed data available. Upload files and call /parse first.",
        )

    engine = DomainDetectionEngine(
        schema=session.schema,
        openapi=session.openapi,
        bdd=session.bdd,
    )
    result = engine.detect()

    logger.info(
        "Domain detected: %s (confidence=%.2f) — session %s",
        result.domain,
        result.confidence,
        session_id,
        extra={
            "stage": "domain_detection",
            "session_id": session_id,
            "domain": result.domain,
            "confidence": result.confidence,
        },
    )

    return result
