"""Semantic column understanding, interdependency & scenario-driven generation API.

GET /semantics              — Column semantic metadata
GET /semantics/dependencies — Column interdependency graph
POST /semantics/scenarios   — Scenario-driven row generation
GET /semantics/scenarios/list — Available scenario templates
POST /semantics/templates/generate — Template-driven row generation
GET /semantics/templates/list — Available reusable templates
POST /semantics/templates/register — Register a custom template
POST /semantics/derivations/resolve — Derive dependent columns
GET /semantics/derivations/rules — List derivation rules
POST /semantics/derivations/report — Full derivation report with provenance
GET /semantics/context — Business context for schema
GET /semantics/context/table — Business context for a single table
POST /semantics/orchestrate — Orchestrated scenario-first generation
GET /semantics/orchestrate/stages — List generation flow stages
GET /semantics/relational — Full relational context analysis
GET /semantics/relational/chains — Entity chains
GET /semantics/relational/constraints — State constraints for a child table
POST /semantics/relational/propagate — Propagate parent scenario to child
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.generators.dependency_engine import detect_dependencies, detect_schema_dependencies
from app.generators.scenario_engine import generate_scenario_rows, get_available_scenarios
from app.generators.scenario_template_engine import (
    generate_scenario_rows_from_templates,
    list_available_templates,
    register_custom_template,
)
from app.generators.derivation_engine import (
    get_derivation_report,
    list_derivation_rules,
    resolve_derived_columns,
)
from app.generators.business_context_engine import (
    analyze_schema_context,
    analyze_table_context,
)
from app.generators.orchestration_engine import (
    get_generation_flow_stages,
    orchestrate_generation,
    orchestrate_table_generation,
)
from app.generators.relational_context_engine import (
    analyze_relational_context,
    get_entity_chains,
    get_state_constraints,
    propagate_parent_scenario,
)
from app.generators.semantic_engine import analyze_schema, analyze_table
from app.services.session_store import store

router = APIRouter(prefix="/semantics", tags=["Semantics"])


@router.get("")
async def get_column_semantics(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str | None = Query(None, description="Optional: analyze a single table"),
) -> dict[str, Any]:
    """Return semantic metadata for all columns in the parsed schema.

    Response format per column:
    {
      "column": "status",
      "semantic_type": "status",
      "business_role": "state_machine_field",
      "entity_role": "workflow_state",
      "workflow_relevance": "state_transition",
      "contextual_relationships": [...],
      "inferred_domain": "insurance",
      "resolved_meaning": "current workflow state of AdjudicationResult; in insurance context"
    }
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    if table:
        # Single table analysis
        target = next((t for t in schema.tables if t.name == table), None)
        if not target:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{table}' not found in schema",
            )
        return {"table": table, "columns": analyze_table(target)}

    # Full schema analysis
    return {"tables": analyze_schema(schema.tables)}


@router.get("/dependencies")
async def get_column_dependencies(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str | None = Query(None, description="Optional: analyze a single table"),
) -> dict[str, Any]:
    """Return column interdependency graph for the parsed schema.

    Response format:
    {
      "dependencies": [
        {
          "source": "status",
          "target": "comments",
          "relationship": "state_drives_explanation",
          "direction": "source_drives_target",
          "confidence": 0.94,
          "reasoning": "'status' determines workflow state; 'comments' explains why"
        }
      ]
    }
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    if table:
        target = next((t for t in schema.tables if t.name == table), None)
        if not target:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{table}' not found in schema",
            )
        return {"table": table, "dependencies": detect_dependencies(target)}

    # Full schema
    return {"tables": detect_schema_dependencies(schema.tables)}


@router.post("/scenarios")
async def generate_scenarios(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str = Query(..., description="Table to generate scenario rows for"),
    rows: int = Query(100, ge=1, le=10000, description="Number of rows to generate"),
) -> dict[str, Any]:
    """Generate rows using scenario-driven logic.

    Instead of random independent values, each row is derived from a
    coherent business scenario with cross-column consistency.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    target = next((t for t in schema.tables if t.name == table), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    result = generate_scenario_rows(target, n=rows)
    return result.to_dict()


@router.get("/scenarios/list")
async def list_scenarios(
    domain: str | None = Query(None, description="Filter by domain (insurance, banking, etc.)"),
) -> dict[str, Any]:
    """List available scenario templates by domain."""
    return get_available_scenarios(domain)


# ═══════════════════════════════════════════════════════════════
# Reusable Template Engine Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post("/templates/generate")
async def generate_from_template_registry(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str = Query(..., description="Table to generate rows for"),
    rows: int = Query(100, ge=1, le=10000, description="Number of rows"),
    domain: str | None = Query(None, description="Override domain detection"),
    include_edge_cases: bool = Query(True, description="Include edge case templates"),
    edge_case_ratio: float = Query(0.15, ge=0.0, le=1.0, description="Fraction of edge case rows"),
) -> dict[str, Any]:
    """Generate rows using the reusable scenario template registry.

    Each row originates from a named template with full provenance tracking.
    Templates support inheritance, configurable weights, and domain-awareness.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    target = next((t for t in schema.tables if t.name == table), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    column_names = [c.name for c in target.columns]
    check_constraints = {c.name: c.check_constraint for c in target.columns}

    result = generate_scenario_rows_from_templates(
        table_name=table,
        column_names=column_names,
        n=rows,
        domain=domain,
        include_edge_cases=include_edge_cases,
        edge_case_ratio=edge_case_ratio,
        check_constraints=check_constraints,
    )
    return result.to_dict()


@router.get("/templates/list")
async def list_templates(
    domain: str | None = Query(None, description="Filter by domain"),
    category: str | None = Query(None, description="Filter by category (happy_path, edge_case, boundary)"),
    tag: str | None = Query(None, description="Filter by tag"),
) -> dict[str, Any]:
    """List all available reusable scenario templates.

    Templates can be filtered by domain, category, or tag.
    """
    return list_available_templates(domain=domain, category=category, tag=tag)


class RegisterTemplateRequest(BaseModel):
    """Request body for registering a custom template."""
    name: str = Field(..., description="Unique template name")
    domain: str = Field(..., description="Business domain (insurance, banking, etc.)")
    category: str = Field("happy_path", description="Category: happy_path, edge_case, boundary, invalid")
    description: str = Field(..., description="Human-readable description")
    fields: dict[str, Any] = Field(..., description="Field pattern -> value mapping")
    weight: float = Field(1.0, ge=0.0, description="Probability weight")
    parent: str | None = Field(None, description="Parent template name for inheritance")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")


@router.post("/templates/register")
async def register_template(body: RegisterTemplateRequest) -> dict[str, Any]:
    """Register a custom scenario template at runtime.

    Custom templates can inherit from built-in templates and override
    specific fields while maintaining the parent's other values.
    """
    try:
        result = register_custom_template(
            name=body.name,
            domain=body.domain,
            category=body.category,
            description=body.description,
            fields=body.fields,
            weight=body.weight,
            parent=body.parent,
            tags=body.tags,
        )
        return {"status": "registered", "template": result}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# Derivation Rule Engine Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post("/derivations/resolve")
async def resolve_derivations(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str = Query(..., description="Table to derive columns for"),
    rows: int = Query(100, ge=1, le=10000, description="Number of rows"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Derive dependent column values from source business context.

    Applies deterministic derivation rules with dependency chaining
    and conflict prevention. Returns derived values with provenance.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    target = next((t for t in schema.tables if t.name == table), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    column_names = [c.name for c in target.columns]
    check_constraints = {c.name: c.check_constraint for c in target.columns if c.check_constraint}

    report = get_derivation_report(
        table_name=table,
        column_names=column_names,
        n=rows,
        domain=domain,
        check_constraints=check_constraints,
    )
    return report


@router.get("/derivations/rules")
async def list_rules(
    domain: str | None = Query(None, description="Filter rules by domain"),
) -> dict[str, Any]:
    """List all available derivation rules.

    Rules define deterministic mappings between source and target columns
    (e.g., full_name → email, country → phone_code, status → rejection_reason).
    """
    rules = list_derivation_rules(domain=domain)
    return {"rules": rules, "count": len(rules)}


@router.post("/derivations/report")
async def derivation_report(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str = Query(..., description="Table to analyze"),
    rows: int = Query(10, ge=1, le=1000, description="Number of rows for sample"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Full derivation report with provenance, conflict resolution, and validation.

    Shows which rules fired, dependency chain execution order,
    conflicts resolved by priority, and any validation failures.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    target = next((t for t in schema.tables if t.name == table), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    column_names = [c.name for c in target.columns]
    check_constraints = {c.name: c.check_constraint for c in target.columns if c.check_constraint}

    report = get_derivation_report(
        table_name=table,
        column_names=column_names,
        n=rows,
        domain=domain,
        check_constraints=check_constraints,
    )
    return {"table": table, "domain": domain, "sample_rows": rows, **report}


# ═══════════════════════════════════════════════════════════════
# Business Context Inference Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get("/context")
async def get_schema_business_context(
    session_id: str = Query(..., description="Session ID from /upload"),
) -> dict[str, Any]:
    """Analyze the full schema to understand business meaning.

    Returns business domain, table purposes, lifecycle states,
    key workflows, and entity relationships across all tables.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    return analyze_schema_context(schema)


@router.get("/context/table")
async def get_table_business_context(
    session_id: str = Query(..., description="Session ID from /upload"),
    table: str = Query(..., description="Table name to analyze"),
) -> dict[str, Any]:
    """Analyze a single table to understand its business meaning.

    Returns business domain, table purpose, lifecycle states,
    workflows, and entity relationships for the specified table.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    target = next((t for t in schema.tables if t.name == table), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    return analyze_table_context(target)


@router.post("/orchestrate")
async def orchestrate_data_generation(
    session_id: str = Query(..., description="Session ID from /upload"),
    rows: int = Query(10, ge=1, le=10000, description="Number of rows per table"),
    table: str | None = Query(None, description="Optional: orchestrate a single table"),
    domain: str | None = Query(None, description="Override domain detection"),
    country: str = Query("us", description="Country for locale-specific data"),
) -> dict[str, Any]:
    """Orchestrated scenario-first data generation.

    Runs the full 8-stage pipeline: schema → business context → semantic meaning
    → dependencies → scenario assignment → derivation → validation → final rows.

    Each row starts from a coherent business scenario; all column values are
    derived deterministically from that scenario context.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    effective_domain = domain or session.domain or "unknown"

    if table:
        target = next((t for t in schema.tables if t.name == table), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")
        row_data, report = orchestrate_table_generation(
            target, row_count=rows, country=country, domain=effective_domain,
        )
        return {
            "table": table,
            "rows": row_data,
            "row_count": len(row_data),
            "report": report,
        }

    data, reports = orchestrate_generation(
        schema, row_count=rows, country=country, domain=effective_domain,
    )
    return {
        "tables": {name: {"rows": r, "row_count": len(r)} for name, r in data.items()},
        "reports": reports,
        "total_rows": sum(len(r) for r in data.values()),
    }


@router.get("/orchestrate/stages")
async def list_orchestration_stages() -> dict[str, Any]:
    """List the ordered generation flow stages.

    Returns the 8-stage pipeline definition showing how scenario-first
    generation works from schema understanding through final row assembly.
    """
    stages = get_generation_flow_stages()
    return {"stages": stages, "count": len(stages)}


@router.get("/relational")
async def get_relational_context(
    session_id: str = Query(..., description="Session ID from /upload"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Full relational context analysis.

    Returns the relationship graph with business role classification,
    entity chains, state constraints, and scenario propagation rules.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    effective_domain = domain or session.domain or "unknown"
    return analyze_relational_context(schema, domain=effective_domain)


@router.get("/relational/chains")
async def get_relational_chains(
    session_id: str = Query(..., description="Session ID from /upload"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Get detected entity chains in the schema.

    Entity chains represent ordered business flows like:
    customer → account → transaction
    policy → claim → payment
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    effective_domain = domain or session.domain or "unknown"
    chains = get_entity_chains(schema, domain=effective_domain)
    return {"entity_chains": chains, "count": len(chains)}


@router.get("/relational/constraints")
async def get_relational_constraints(
    session_id: str = Query(..., description="Session ID from /upload"),
    child_table: str = Query(..., description="Child table to check constraints for"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Get state constraints for a child table based on generated parent data.

    Shows what scenarios are allowed/forbidden for the child table given
    the parent entity's current state distribution.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    # Use session's generated data as parent data
    parent_data = session.generated_data if hasattr(session, "generated_data") and session.generated_data else {}
    effective_domain = domain or session.domain or "unknown"
    return get_state_constraints(schema, child_table, parent_data, domain=effective_domain)


@router.post("/relational/propagate")
async def propagate_scenario(
    session_id: str = Query(..., description="Session ID from /upload"),
    parent_table: str = Query(..., description="Parent table name"),
    child_table: str = Query(..., description="Child table name"),
    domain: str | None = Query(None, description="Override domain detection"),
) -> dict[str, Any]:
    """Propagate parent scenario context to child generation hints.

    For each parent row, produces scenario hints that should constrain
    how child rows linked to that parent are generated.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    schema = session.schema
    if not schema or not schema.tables:
        raise HTTPException(status_code=400, detail="No parsed schema in session. Run /parse first.")

    parent_data = session.generated_data if hasattr(session, "generated_data") and session.generated_data else {}
    parent_rows = parent_data.get(parent_table, [])
    if not parent_rows:
        return {"propagations": [], "message": f"No generated data for parent table '{parent_table}'"}

    effective_domain = domain or session.domain or "unknown"
    propagations = propagate_parent_scenario(
        schema, parent_table, child_table, parent_rows, domain=effective_domain,
    )
    return {"propagations": propagations, "count": len(propagations)}
