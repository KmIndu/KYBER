"""History router — list, view, delete past generation runs per user."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Query

from app.auth.jwt_handler import decode_access_token
from app.services.history_store import history_store
from app.services.session_store import Session, store
from app.models.schema import SchemaMetadata
from app.models.negative import NegativeDataset

router = APIRouter(prefix="/history", tags=["History"])
logger = logging.getLogger(__name__)


def _get_email(token: str) -> str:
    """Extract email from JWT, raise 401 on failure."""
    claims = decode_access_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    email = claims.get("email") or claims.get("sub") or ""
    if not email:
        raise HTTPException(status_code=401, detail="Cannot identify user")
    return email.lower().strip()


@router.get("")
async def list_history(token: str = Query(..., description="JWT token")):
    """Return all past generation records for the authenticated user (newest first)."""
    import asyncio
    email = _get_email(token)
    records = await asyncio.to_thread(history_store.list_for_user, email)
    return {"records": records, "total": len(records)}


@router.get("/{record_id}")
async def get_history_record(
    record_id: str,
    token: str = Query(..., description="JWT token"),
):
    """Return full details (including row data) for a specific record."""
    email = _get_email(token)
    record = history_store.get(email, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.delete("/{record_id}")
async def delete_history_record(
    record_id: str,
    token: str = Query(..., description="JWT token"),
):
    """Delete a single history record."""
    email = _get_email(token)
    deleted = history_store.delete(email, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"message": "Record deleted"}


@router.delete("")
async def clear_history(token: str = Query(..., description="JWT token")):
    """Delete all history records for the authenticated user."""
    email = _get_email(token)
    count = history_store.delete_all(email)
    return {"message": f"Deleted {count} record(s)", "deleted": count}


@router.patch("/{record_id}")
async def update_history_record(
    record_id: str,
    token: str = Query(..., description="JWT token"),
    body: dict = Body(...),
):
    """Update a history record with analysis results (edge_cases, partitions, etc)."""
    email = _get_email(token)
    allowed = {"edge_cases", "partitions", "integration_bundle", "integration_guide"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    ok = history_store.update(email, record_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"message": "Record updated", "fields": list(updates.keys())}


@router.post("/{record_id}/restore")
async def restore_session_from_history(
    record_id: str,
    token: str = Query(..., description="JWT token"),
):
    """Recreate a live session from a history record so analysis
    endpoints (edge cases, partitions, integration) work."""
    email = _get_email(token)
    record = history_store.get(email, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    # Create a new session and populate it from history
    session = store.create()
    session.generation_order = record.get("generation_order", [])
    session.data = record.get("data")
    session.row_count = record.get("row_count", 0)

    # Restore parsed schema if saved
    schema_dict = record.get("schema")
    if schema_dict:
        try:
            session.schema = SchemaMetadata.model_validate(schema_dict)
        except Exception:
            logger.warning("Could not restore schema for record %s", record_id)

    # Restore negative data if saved
    neg_dict = record.get("negative_data")
    if neg_dict:
        try:
            session.negative = NegativeDataset.model_validate(neg_dict)
        except Exception:
            logger.warning("Could not restore negative data for record %s", record_id)

    logger.info("Session restored from history: %s -> %s", record_id, session.session_id)
    return {"session_id": session.session_id}
