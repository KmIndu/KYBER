"""Referential integrity router.

  POST /integrity/validate-schema — validate schema FK relationships
  POST /integrity/validate-data   — validate generated data integrity
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.models.integrity import IntegrityReport
from app.services.integrity_engine import ReferentialIntegrityEngine
from app.services.session_store import store

router = APIRouter(prefix="/integrity", tags=["Referential Integrity"])
logger = logging.getLogger(__name__)


@router.post("/validate-schema", response_model=IntegrityReport)
async def validate_schema_integrity(
    session_id: str = Query(..., description="Session ID from /upload"),
):
    """Validate schema-level referential integrity (graph validation)."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload and parse files first.",
        )

    engine = ReferentialIntegrityEngine(session.schema)
    report = engine.validate_schema()

    logger.info(
        "Schema integrity validated — session %s: valid=%s, issues=%d",
        session_id,
        report.valid,
        report.total_issues,
        extra={
            "stage": "integrity",
            "session_id": session_id,
            "valid": report.valid,
            "errors": report.errors,
        },
    )

    return report


@router.post("/validate-data", response_model=IntegrityReport)
async def validate_data_integrity(
    session_id: str = Query(..., description="Session ID from /upload"),
):
    """Validate referential integrity of generated data (orphan detection)."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload and parse files first.",
        )

    if not session.data:
        raise HTTPException(
            status_code=400,
            detail="No generated data available. Call POST /generate first.",
        )

    engine = ReferentialIntegrityEngine(session.schema)
    report = engine.validate_data(session.data)

    logger.info(
        "Data integrity validated — session %s: valid=%s, orphans=%d",
        session_id,
        report.valid,
        sum(1 for i in report.issues if i.issue_type == "orphan_row"),
        extra={
            "stage": "integrity",
            "session_id": session_id,
            "valid": report.valid,
            "total_issues": report.total_issues,
        },
    )

    return report
