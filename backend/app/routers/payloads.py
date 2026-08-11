"""OpenAPI payload generation router.

  POST /payloads/generate — generate API-ready JSON payloads from OpenAPI spec
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.generators.payload_generator import PayloadGenerator
from app.models.payload import PayloadGenerationResult
from app.services.session_store import store

router = APIRouter(prefix="/payloads", tags=["Payload Generation"])
logger = logging.getLogger(__name__)


@router.post("/generate", response_model=PayloadGenerationResult)
async def generate_payloads(
    session_id: str = Query(..., description="Session ID from /upload"),
    count: int = Query(default=3, ge=1, le=100, description="Payloads per type per schema"),
    include_invalid: bool = Query(default=True, description="Generate invalid payloads"),
):
    """Generate API-ready JSON payloads from parsed OpenAPI schemas."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.openapi:
        raise HTTPException(
            status_code=400,
            detail="No OpenAPI spec available. Upload an OpenAPI file and call /parse first.",
        )

    if not session.openapi.schemas:
        raise HTTPException(
            status_code=400,
            detail="OpenAPI spec has no schema definitions to generate payloads from.",
        )

    generator = PayloadGenerator(
        openapi=session.openapi,
        count=count,
        include_invalid=include_invalid,
    )
    result = generator.generate()

    logger.info(
        "Payloads generated — session %s: %d schemas, %d payloads",
        session_id,
        result.total_schemas,
        result.total_payloads,
        extra={
            "stage": "payload_generation",
            "session_id": session_id,
            "total_schemas": result.total_schemas,
            "total_payloads": result.total_payloads,
        },
    )

    return result
