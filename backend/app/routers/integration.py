"""Test environment integration router.

Endpoints for generating integration-ready artifacts:
  POST /integration/generate  — generate full integration bundle
  GET  /integration/download  — download integration ZIP
  GET  /integration/postman   — download Postman collection only
  GET  /integration/payloads  — download API payloads only
  GET  /integration/sql       — download SQL inserts only
  GET  /integration/swagger   — download Swagger test suite only
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.exporters.integration_engine import (
    IntegrationEngine,
    IntegrationError,
    build_api_payloads,
    build_ci_config,
    build_mock_payloads,
    build_postman_collection,
    build_qa_pipeline_config,
    build_sql_inserts,
    build_swagger_test_suite,
)
from app.models.integration import IntegrationBundle, IntegrationGuide
from app.services.session_store import store

router = APIRouter(prefix="/integration", tags=["Integration"])
logger = logging.getLogger(__name__)


def _get_session(session_id: str):
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


def _require_data(session):
    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload files and call /parse first.",
        )
    if not session.data:
        raise HTTPException(
            status_code=400,
            detail="No generated data. Call /generate first.",
        )


# ── POST /integration/generate ───────────────────────────────


@router.post("/generate", response_model=IntegrationBundle)
async def generate_integration(
    session_id: str = Query(..., description="Session ID from /upload"),
    base_url: str = Query(default="http://localhost:8080", description="Target API base URL"),
    artifacts: str | None = Query(default=None, description="Comma-separated artifact formats to include (e.g. 'postman,sql_insert'). If empty, all are generated."),
):
    """Generate integration artifacts. Optionally filter by artifact type."""
    session = _get_session(session_id)
    _require_data(session)

    logger.info(
        "Integration generation started — session %s",
        session_id,
        extra={"stage": "integration", "session_id": session_id, "event": "integration_started"},
    )

    engine = IntegrationEngine()
    # Parse artifact filter
    include_formats = None
    if artifacts:
        include_formats = set(f.strip() for f in artifacts.split(",") if f.strip())
    try:
        bundle = engine.generate_bundle(
            session_id=session_id,
            schema=session.schema,
            data=session.data,
            generation_order=session.generation_order,
            negative=session.negative,
            base_url=base_url,
            include_formats=include_formats,
        )
    except IntegrationError as e:
        logger.error(
            "Integration generation failed: %s", e,
            extra={"stage": "integration", "session_id": session_id, "event": "integration_error"},
        )
        raise HTTPException(status_code=500, detail=f"Integration generation failed: {e}")

    session.integration_bundle = bundle

    logger.info(
        "Integration bundle generated — %d artifacts",
        len(bundle.artifacts),
        extra={"stage": "integration", "session_id": session_id, "event": "integration_completed"},
    )

    return bundle


# ── GET /integration/download ─────────────────────────────────


@router.get("/download")
async def download_integration(
    session_id: str = Query(..., description="Session ID"),
):
    """Download the full integration bundle ZIP."""
    session = _get_session(session_id)
    bundle = getattr(session, "integration_bundle", None)
    if not bundle:
        raise HTTPException(
            status_code=400,
            detail="No integration bundle. Call POST /integration/generate first.",
        )
    if not os.path.exists(bundle.zip_path):
        raise HTTPException(status_code=410, detail="Integration ZIP no longer available")

    return FileResponse(
        path=bundle.zip_path,
        media_type="application/zip",
        filename=os.path.basename(bundle.zip_path),
    )


# ── GET /integration/postman ─────────────────────────────────


@router.get("/postman")
async def get_postman_collection(
    session_id: str = Query(..., description="Session ID"),
    base_url: str = Query(default="{{base_url}}", description="Target API base URL"),
):
    """Get the Postman collection JSON directly (no ZIP)."""
    session = _get_session(session_id)
    _require_data(session)

    collection = build_postman_collection(
        session.schema, session.data, base_url=base_url
    )
    return JSONResponse(content=collection)


# ── GET /integration/payloads ─────────────────────────────────


@router.get("/payloads")
async def get_api_payloads(
    session_id: str = Query(..., description="Session ID"),
):
    """Get API-ready JSON payloads per entity."""
    session = _get_session(session_id)
    _require_data(session)

    payloads = build_api_payloads(session.schema, session.data)
    return JSONResponse(content=[p.model_dump() for p in payloads])


# ── GET /integration/sql ──────────────────────────────────────


@router.get("/sql")
async def get_sql_inserts(
    session_id: str = Query(..., description="Session ID"),
):
    """Get database-ready SQL INSERT script."""
    session = _get_session(session_id)
    _require_data(session)

    sql = build_sql_inserts(session.schema, session.data, session.generation_order)
    return JSONResponse(content={"sql": sql, "tables": len(session.schema.tables)})


# ── GET /integration/swagger ─────────────────────────────────


@router.get("/swagger")
async def get_swagger_tests(
    session_id: str = Query(..., description="Session ID"),
    base_url: str = Query(default="http://localhost:8080", description="Target API base URL"),
):
    """Get Swagger test suite JSON."""
    session = _get_session(session_id)
    _require_data(session)

    suite = build_swagger_test_suite(session.schema, session.data, base_url=base_url)
    return JSONResponse(content=suite.model_dump())


# ── GET /integration/mocks ───────────────────────────────────


@router.get("/mocks")
async def get_mock_payloads(
    session_id: str = Query(..., description="Session ID"),
):
    """Get mock payloads (valid/invalid/boundary per entity)."""
    session = _get_session(session_id)
    _require_data(session)

    mocks = build_mock_payloads(session.schema, session.data, session.negative)
    return JSONResponse(content=[m.model_dump() for m in mocks])


# ── GET /integration/ci ───────────────────────────────────────


@router.get("/ci")
async def get_ci_config(
    session_id: str = Query(..., description="Session ID"),
):
    """Get CI/CD pipeline configuration (GitHub Actions format)."""
    session = _get_session(session_id)
    if not session.schema:
        raise HTTPException(status_code=400, detail="No schema. Upload and parse first.")

    ci = build_ci_config(session.schema)
    qa = build_qa_pipeline_config(session.schema)
    return JSONResponse(content={"ci_cd": ci, "qa_pipeline": qa})


# ── POST /integration/guide ──────────────────────────────────


@router.post("/guide", response_model=IntegrationGuide)
async def generate_guide(
    session_id: str = Query(..., description="Session ID"),
):
    """Generate an AI-powered integration guide for using the generated datasets."""
    from app.ai.service import generate_integration_guide

    session = _get_session(session_id)
    _require_data(session)

    logger.info(
        "Integration guide requested — session %s",
        session_id,
        extra={"stage": "integration_guide", "session_id": session_id, "event": "guide_requested"},
    )

    guide = generate_integration_guide(
        session_id=session_id,
        schema=session.schema,
        data=session.data,
        generation_order=session.generation_order,
        has_integration_bundle=session.integration_bundle is not None,
    )

    logger.info(
        "Integration guide generated — %d sections, provider=%s",
        len(guide.sections),
        guide.provider,
        extra={
            "stage": "integration_guide",
            "session_id": session_id,
            "event": "guide_completed",
            "sections": len(guide.sections),
        },
    )

    return guide
