"""Router for constraint enforcement — validates generated data against schema constraints."""

from fastapi import APIRouter, HTTPException, Query

from app.models.constraint import EnforcementReport
from app.services.session_store import store
from app.validators.constraint_engine import ConstraintEnforcementEngine

router = APIRouter(prefix="/constraints", tags=["Constraints"])


@router.post("/enforce", response_model=EnforcementReport)
async def enforce_constraints(
    session_id: str = Query(..., description="Session ID"),
):
    """Enforce all schema constraints on generated data and return a detailed report.

    Checks: nullable, regex, enums, uniqueness, ranges, composite keys.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.schema:
        raise HTTPException(
            status_code=400, detail="No schema in session. Upload and parse a SQL file first."
        )

    if not session.data:
        raise HTTPException(
            status_code=400, detail="No generated data in session. Run generation first."
        )

    engine = ConstraintEnforcementEngine(session.schema)
    report = engine.enforce(session.data)
    return report
