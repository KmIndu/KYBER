"""Equivalence partitioning router.

  POST /partitions/analyze  — analyze schema and return equivalence partitions
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.generators.partition_engine import EquivalencePartitioningEngine
from app.models.partition import DatasetSplitConfig, PartitionAnalysis
from app.services.session_store import store

router = APIRouter(prefix="/partitions", tags=["Partitions"])
logger = logging.getLogger(__name__)


def _get_session(session_id: str):
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


@router.post("/analyze", response_model=PartitionAnalysis)
async def analyze_partitions(
    session_id: str = Query(..., description="Session ID from /upload"),
    rows_per_partition: int = Query(
        default=3, ge=1, le=50,
        description="Number of sample rows to generate per partition (used when split is disabled)",
    ),
    total_rows: int | None = Query(
        default=None, ge=1, le=10000,
        description="Total rows to generate (enables split mode)",
    ),
    valid_pct: float = Query(
        default=80.0, ge=0, le=100,
        description="Percentage of rows for valid partitions",
    ),
    invalid_pct: float = Query(
        default=10.0, ge=0, le=100,
        description="Percentage of rows for invalid partitions",
    ),
    boundary_pct: float = Query(
        default=10.0, ge=0, le=100,
        description="Percentage of rows for boundary partitions",
    ),
    duplicate_pct: float = Query(
        default=0.0, ge=0, le=100,
        description="Percentage of rows for duplicate partitions",
    ),
):
    """Analyze a parsed schema and return equivalence partitions with sample datasets."""
    session = _get_session(session_id)

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload files and call /parse first.",
        )

    # Build split config if total_rows is provided
    split_config: DatasetSplitConfig | None = None
    if total_rows is not None:
        pct_sum = round(valid_pct + invalid_pct + boundary_pct + duplicate_pct, 2)
        if pct_sum != 100.0:
            raise HTTPException(
                status_code=422,
                detail=f"Percentages must equal 100 (got {pct_sum})",
            )
        split_config = DatasetSplitConfig(
            valid_pct=valid_pct,
            invalid_pct=invalid_pct,
            boundary_pct=boundary_pct,
            duplicate_pct=duplicate_pct,
        )

    logger.info(
        "Partition analysis started — session %s, %d tables",
        session_id,
        len(session.schema.tables),
        extra={
            "stage": "partition_analysis",
            "session_id": session_id,
            "event": "analysis_started",
        },
    )

    engine = EquivalencePartitioningEngine(
        schema=session.schema,
        rows_per_partition=rows_per_partition,
        split_config=split_config,
        total_rows=total_rows,
    )
    analysis = engine.analyze(session_id=session_id)

    logger.info(
        "Partition analysis complete — %d partitions, %d generated rows",
        analysis.total_partitions,
        analysis.total_generated_rows,
        extra={
            "stage": "partition_analysis",
            "session_id": session_id,
            "event": "analysis_completed",
            "total_partitions": analysis.total_partitions,
            "total_generated_rows": analysis.total_generated_rows,
        },
    )

    return analysis
