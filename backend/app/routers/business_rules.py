"""Router for business rule reasoning — infer rules from BDD, schema, and OpenAPI."""

from fastapi import APIRouter, HTTPException, Query

from app.generators.business_rule_engine import BusinessRuleEngine
from app.models.business_rule import BusinessRuleResult
from app.services.session_store import store

router = APIRouter(prefix="/business-rules", tags=["Business Rules"])


@router.post("/analyze", response_model=BusinessRuleResult)
async def analyze_business_rules(
    session_id: str = Query(..., description="Session ID"),
):
    """Infer business rules from session's BDD, schema, and OpenAPI data.

    Returns validation rules, edge-case scenarios, and rule metadata.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.schema and not session.bdd and not session.openapi:
        raise HTTPException(
            status_code=400,
            detail="No data sources available. Upload and parse at least one file (SQL, BDD, or OpenAPI).",
        )

    engine = BusinessRuleEngine(
        schema=session.schema,
        bdd=session.bdd,
        openapi=session.openapi,
    )
    result = engine.analyze()
    return result
