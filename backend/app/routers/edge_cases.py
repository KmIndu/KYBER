"""Edge-case analysis router.

  POST /edge-cases/analyze  — analyze schema and return edge-case rules
  POST /edge-cases/smart    — generate scenario-aware smart edge cases
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.generators.edge_case_engine import EdgeCaseAnalysisEngine
from app.generators.smart_edge_case_engine import SmartEdgeCaseEngine
from app.models.edge_case import EdgeCaseAnalysis, EdgeCaseToggles
from app.services.session_store import store

router = APIRouter(prefix="/edge-cases", tags=["Edge Cases"])
logger = logging.getLogger(__name__)


def _get_session(session_id: str):
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


@router.post("/analyze", response_model=EdgeCaseAnalysis)
async def analyze_edge_cases(
    session_id: str = Query(..., description="Session ID from /upload"),
    null_values: bool = Query(default=True, description="Generate null-value rules"),
    boundary_values: bool = Query(default=True, description="Generate boundary-value rules"),
    negative_values: bool = Query(default=True, description="Generate negative-value rules"),
    overflow_values: bool = Query(default=True, description="Generate overflow-value rules"),
    invalid_formats: bool = Query(default=True, description="Generate invalid-format rules"),
    duplicate_values: bool = Query(default=True, description="Generate duplicate-value rules"),
    type_mismatch: bool = Query(default=True, description="Generate type-mismatch rules"),
    empty_values: bool = Query(default=True, description="Generate empty-value rules"),
    special_chars: bool = Query(default=True, description="Generate special-character rules"),
):
    """Analyze a parsed schema and return a structured catalog of edge-case test values."""
    session = _get_session(session_id)

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload files and call /parse first.",
        )

    toggles = EdgeCaseToggles(
        null_values=null_values,
        boundary_values=boundary_values,
        negative_values=negative_values,
        overflow_values=overflow_values,
        invalid_formats=invalid_formats,
        duplicate_values=duplicate_values,
        type_mismatch=type_mismatch,
        empty_values=empty_values,
        special_chars=special_chars,
    )

    # Collect AI edge cases if available (from prior AI analysis)
    ai_edge_cases = []
    # AI reasoning results are not stored on session yet, but if they were:
    # ai_edge_cases = session.ai_reasoning.edge_cases if session.ai_reasoning else []

    logger.info(
        "Edge-case analysis started — session %s, %d tables",
        session_id,
        len(session.schema.tables),
        extra={
            "stage": "edge_case_analysis",
            "session_id": session_id,
            "event": "analysis_started",
        },
    )

    engine = EdgeCaseAnalysisEngine(
        schema=session.schema,
        toggles=toggles,
        ai_edge_cases=ai_edge_cases,
    )
    analysis = engine.analyze(session_id=session_id)

    logger.info(
        "Edge-case analysis complete — %d rules across %d columns",
        analysis.total_rules,
        analysis.columns_analyzed,
        extra={
            "stage": "edge_case_analysis",
            "session_id": session_id,
            "event": "analysis_completed",
            "total_rules": analysis.total_rules,
        },
    )

    return analysis


@router.post("/smart")
async def smart_edge_cases(
    session_id: str = Query(..., description="Session ID from /upload"),
    scenarios_per_table: int = Query(
        default=5, ge=1, le=20,
        description="Max scenarios to generate per table",
    ),
):
    """Generate scenario-aware smart edge cases — complete failure rows with coherent values."""
    session = _get_session(session_id)

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload files and call /parse first.",
        )

    logger.info(
        "Smart edge-case generation started — session %s, %d tables",
        session_id,
        len(session.schema.tables),
        extra={
            "stage": "smart_edge_case",
            "session_id": session_id,
            "event": "generation_started",
        },
    )

    engine = SmartEdgeCaseEngine(
        schema=session.schema,
        target_scenarios_per_table=scenarios_per_table,
    )
    result = engine.generate(session_id=session_id)

    logger.info(
        "Smart edge-case generation complete — %d scenarios for %d tables",
        len(result.scenarios),
        result.tables_analyzed,
        extra={
            "stage": "smart_edge_case",
            "session_id": session_id,
            "event": "generation_completed",
            "total_scenarios": len(result.scenarios),
        },
    )

    return JSONResponse(content=result.to_dict())
