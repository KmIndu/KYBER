"""Generation Flow Orchestration Engine.

Implements scenario-first generation: each row starts from a coherent
business scenario and derives all column values through a deterministic
pipeline of stages.

Generation Flow (per table):
  1. Understand schema       → column types, constraints, keys
  2. Understand business ctx → domain, table purpose, lifecycle
  3. Infer semantic meaning  → column roles, relationships
  4. Detect dependencies     → cross-column derivation graph
  5. Determine scenario      → select scenario template per row
  6. Derive dependent values → fill columns from scenario context
  7. Validate consistency    → check for contradictions
  8. Generate final row      → fill remaining columns + corrections

CRITICAL: Generation is scenario-first, NOT column-first.
Each row is born from a scenario that defines its business context,
then all other values are derived to be consistent with that scenario.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

logger = logging.getLogger(__name__)


# ── Flow Stage Definition ─────────────────────────────────────

class StageError(Exception):
    """Raised when a pipeline stage fails."""


@dataclass
class StageResult:
    """Result from a single pipeline stage execution."""
    stage_name: str
    success: bool
    duration_ms: float
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    corrections_applied: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "errors": self.errors if self.errors else None,
            "corrections": self.corrections_applied if self.corrections_applied else None,
        }


@dataclass
class OrchestrationReport:
    """Full report from an orchestrated generation run."""
    table_name: str
    row_count: int
    domain: str
    stages: list[StageResult]
    total_duration_ms: float
    rows_generated: int
    rows_corrected: int
    validation_pass_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "row_count": self.row_count,
            "domain": self.domain,
            "stages": [s.to_dict() for s in self.stages],
            "total_duration_ms": round(self.total_duration_ms, 2),
            "rows_generated": self.rows_generated,
            "rows_corrected": self.rows_corrected,
            "validation_pass_rate": round(self.validation_pass_rate, 4),
        }


@dataclass
class TableGenerationContext:
    """Accumulated context built through the pipeline stages for one table."""
    table: TableMetadata
    n: int
    domain: str
    country: str
    check_constraints: dict[str, str]  # col_name → constraint expression

    # Stage 1: Schema understanding
    column_types: dict[str, str] = field(default_factory=dict)  # col → base_type
    pk_columns: list[str] = field(default_factory=list)
    fk_columns: dict[str, tuple[str, str]] = field(default_factory=dict)  # col → (ref_table, ref_col)
    nullable_columns: set[str] = field(default_factory=set)
    unique_columns: set[str] = field(default_factory=set)

    # Stage 2: Business context
    table_purpose: str = "general"
    lifecycle_states: list[str] = field(default_factory=list)
    lifecycle_entity: str | None = None
    workflows: list[dict[str, Any]] = field(default_factory=list)

    # Stage 3: Semantic meaning
    column_roles: dict[str, str] = field(default_factory=dict)  # col → role
    status_columns: list[str] = field(default_factory=list)
    temporal_columns: list[str] = field(default_factory=list)
    monetary_columns: list[str] = field(default_factory=list)
    identity_columns: list[str] = field(default_factory=list)

    # Stage 4: Dependencies
    dependency_graph: list[dict[str, Any]] = field(default_factory=list)
    derivation_sources: dict[str, list[str]] = field(default_factory=dict)  # target → [sources]

    # Stage 5: Scenario assignment (per-row)
    row_scenarios: list[dict[str, Any]] = field(default_factory=list)  # one per row

    # Stage 6: Derived values
    derived_values: dict[str, list[Any]] = field(default_factory=dict)

    # Stage 7: Validation results
    issues_found: int = 0
    corrections_applied: int = 0

    # Stage 8: Final rows
    rows: list[dict[str, Any]] = field(default_factory=list)

    # FK parent data (from previously-generated tables)
    fk_parent_data: dict[str, list[Any]] = field(default_factory=dict)


# ── Pipeline Stages ───────────────────────────────────────────

def _stage_understand_schema(ctx: TableGenerationContext) -> StageResult:
    """Stage 1: Parse and understand schema structure."""
    start = time.perf_counter()
    from app.utils.sql_types import base_type as _base_type

    for col in ctx.table.columns:
        ctx.column_types[col.name] = _base_type(col.data_type)
        if col.is_primary_key:
            ctx.pk_columns.append(col.name)
        if col.nullable:
            ctx.nullable_columns.add(col.name)
        if col.is_unique or col.is_primary_key:
            ctx.unique_columns.add(col.name)

    for fk in ctx.table.foreign_keys:
        ctx.fk_columns[fk.column] = (fk.references_table, fk.references_column)

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="understand_schema",
        success=True,
        duration_ms=duration,
        data={
            "columns": len(ctx.table.columns),
            "pks": len(ctx.pk_columns),
            "fks": len(ctx.fk_columns),
            "checks": len(ctx.check_constraints),
        },
    )


def _stage_understand_business_context(ctx: TableGenerationContext) -> StageResult:
    """Stage 2: Infer business context for the table."""
    start = time.perf_counter()
    from app.generators.business_context_engine import analyze_table_context

    try:
        table_ctx = analyze_table_context(ctx.table, schema_domain=ctx.domain)
        ctx.table_purpose = table_ctx.get("table_purpose", "general")
        ctx.lifecycle_states = table_ctx.get("lifecycle_states", [])
        ctx.lifecycle_entity = table_ctx.get("lifecycle_entity")
        ctx.workflows = table_ctx.get("workflows", [])

        # Update domain if we have higher confidence from table analysis
        inferred_domain = table_ctx.get("business_domain", ctx.domain)
        if inferred_domain and inferred_domain != "general" and ctx.domain in ("unknown", "general"):
            ctx.domain = inferred_domain
    except Exception as e:
        logger.warning("Business context stage fallback: %s", e)

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="understand_business_context",
        success=True,
        duration_ms=duration,
        data={
            "purpose": ctx.table_purpose,
            "domain": ctx.domain,
            "lifecycle_states": len(ctx.lifecycle_states),
            "workflows": len(ctx.workflows),
        },
    )


def _stage_infer_semantic_meaning(ctx: TableGenerationContext) -> StageResult:
    """Stage 3: Determine semantic meaning of each column."""
    start = time.perf_counter()

    _STATUS_PAT = re.compile(r"status|state|phase|stage|decision|outcome", re.I)
    _STATUS_SKIP_PAT = re.compile(r"rag|color|moderation|virus", re.I)
    _TEMPORAL_PAT = re.compile(r"_at$|_on$|_date$|_time$|created|updated|submitted|closed|completed", re.I)
    _MONETARY_PAT = re.compile(r"amount|total|price|cost|fee|balance|premium|payment", re.I)
    _IDENTITY_PAT = re.compile(r"name|email|username|phone|mobile|full_name|first_name|last_name", re.I)
    _ACTOR_PAT = re.compile(r"_by$|assignee|reviewer|approver|owner|adjuster", re.I)

    for col in ctx.table.columns:
        col_name = col.name
        # Classify column role
        if col.is_primary_key:
            ctx.column_roles[col_name] = "primary_key"
        elif col_name in ctx.fk_columns:
            ctx.column_roles[col_name] = "foreign_key"
        elif _STATUS_PAT.search(col_name) and not _STATUS_SKIP_PAT.search(col_name):
            ctx.column_roles[col_name] = "status"
            ctx.status_columns.append(col_name)
        elif _TEMPORAL_PAT.search(col_name):
            ctx.column_roles[col_name] = "temporal"
            ctx.temporal_columns.append(col_name)
        elif _MONETARY_PAT.search(col_name):
            ctx.column_roles[col_name] = "monetary"
            ctx.monetary_columns.append(col_name)
        elif _IDENTITY_PAT.search(col_name):
            ctx.column_roles[col_name] = "identity"
            ctx.identity_columns.append(col_name)
        elif _ACTOR_PAT.search(col_name):
            ctx.column_roles[col_name] = "actor"
        else:
            ctx.column_roles[col_name] = "data"

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="infer_semantic_meaning",
        success=True,
        duration_ms=duration,
        data={
            "status_cols": len(ctx.status_columns),
            "temporal_cols": len(ctx.temporal_columns),
            "monetary_cols": len(ctx.monetary_columns),
            "identity_cols": len(ctx.identity_columns),
        },
    )


def _stage_detect_dependencies(ctx: TableGenerationContext) -> StageResult:
    """Stage 4: Build the dependency graph across columns."""
    start = time.perf_counter()
    from app.generators.dependency_engine import detect_dependencies

    try:
        deps = detect_dependencies(ctx.table)
        ctx.dependency_graph = deps

        # Build derivation source map: target → [source columns]
        for dep in deps:
            if dep.get("direction") == "source_drives_target":
                target = dep["target"]
                source = dep["source"]
                ctx.derivation_sources.setdefault(target, []).append(source)
    except Exception as e:
        logger.warning("Dependency detection fallback: %s", e)

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="detect_dependencies",
        success=True,
        duration_ms=duration,
        data={
            "dependencies_found": len(ctx.dependency_graph),
            "derivable_columns": len(ctx.derivation_sources),
        },
    )


def _stage_determine_scenario(ctx: TableGenerationContext) -> StageResult:
    """Stage 5: Assign a scenario to each row (SCENARIO-FIRST).

    This is the critical stage — each row gets a business scenario that
    defines its coherent state before any column values are generated.
    """
    start = time.perf_counter()
    from app.generators.scenario_template_engine import generate_scenario_rows_from_templates

    all_col_names = [c.name for c in ctx.table.columns]
    template_result = generate_scenario_rows_from_templates(
        table_name=ctx.table.name,
        column_names=all_col_names,
        n=ctx.n,
        domain=ctx.domain,
        check_constraints=ctx.check_constraints,
    )

    # Store per-row scenario context
    for i in range(ctx.n):
        scenario: dict[str, Any] = {}
        if template_result.rows and i < len(template_result.rows):
            scenario["template_values"] = template_result.rows[i]
        if template_result.provenance and i < len(template_result.provenance):
            prov = template_result.provenance[i]
            scenario["template_name"] = prov.template_name
            scenario["domain"] = prov.template_domain
            scenario["category"] = prov.template_category
        else:
            scenario["template_name"] = "default"
            scenario["domain"] = ctx.domain
            scenario["category"] = "happy_path"

        # Inject lifecycle state from scenario template or random from available
        if ctx.lifecycle_states and not any(
            v for k, v in (scenario.get("template_values") or {}).items()
            if k in ctx.status_columns and v is not None
        ):
            # Assign lifecycle state weighted toward common states
            weight_map = _lifecycle_weights(ctx.lifecycle_states)
            state = random.choices(ctx.lifecycle_states, weights=weight_map, k=1)[0]
            scenario["assigned_lifecycle_state"] = state

        ctx.row_scenarios.append(scenario)

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="determine_scenario",
        success=True,
        duration_ms=duration,
        data={
            "scenarios_assigned": len(ctx.row_scenarios),
            "templates_used": len(set(
                s.get("template_name", "unknown") for s in ctx.row_scenarios
            )),
        },
    )


def _stage_derive_dependent_values(ctx: TableGenerationContext) -> StageResult:
    """Stage 6: Derive all dependent column values from scenario context.

    Scenario-first: the scenario defines the business state, then all
    other values are derived to be consistent with that state.
    """
    start = time.perf_counter()
    all_col_names = [c.name for c in ctx.table.columns]
    from app.utils.sql_types import base_type as _base_type

    # Build scenario-driven seed values per column
    scenario_seeds: dict[str, list[Any]] = {col: [None] * ctx.n for col in all_col_names}

    # Apply template values from scenarios (highest priority)
    for i, scenario in enumerate(ctx.row_scenarios):
        template_vals = scenario.get("template_values") or {}
        for col, val in template_vals.items():
            if col in scenario_seeds and val is not None:
                scenario_seeds[col][i] = val
        # Apply assigned lifecycle state to status columns
        assigned_state = scenario.get("assigned_lifecycle_state")
        if assigned_state:
            for status_col in ctx.status_columns:
                if scenario_seeds[status_col][i] is None:
                    scenario_seeds[status_col][i] = assigned_state

    # Country-aware override: currency columns must match the generation country
    # (scenario templates may provide random currencies that conflict with country)
    from app.generators.realistic_provider import RealisticProvider as _RP
    _country_provider = _RP(country=ctx.country, domain=ctx.domain)
    _CURRENCY_PAT = re.compile(r"^currency$|currency_code|^ccy$", re.I)
    for col in all_col_names:
        if _CURRENCY_PAT.search(col):
            country_currency = _country_provider._gen_currency()
            for i in range(ctx.n):
                scenario_seeds[col][i] = country_currency

    # Resolve FK values (mandatory — structural constraint)
    for fk_col, (ref_table, ref_col) in ctx.fk_columns.items():
        parent_vals = ctx.fk_parent_data.get(fk_col, [])
        if parent_vals:
            n_parents = len(parent_vals)
            scenario_seeds[fk_col] = [
                parent_vals[i % n_parents] for i in range(ctx.n)
            ]

    # Resolve identity-consistent columns (name ↔ email ↔ username)
    from app.generators.identity_provider import resolve_identity_columns
    # Exclude PK, FK, integer columns from identity
    excluded = set(ctx.fk_columns.keys()) | set(ctx.pk_columns)
    for col in ctx.table.columns:
        if _base_type(col.data_type) in ("integer", "float"):
            excluded.add(col.name)
    identity_candidates = [c for c in all_col_names if c not in excluded]
    identity_linked = resolve_identity_columns(
        ctx.table.name, identity_candidates, ctx.n,
        country=ctx.country,
        domain=ctx.domain,
    ) or {}

    # Merge identity into seeds (don't override scenario values)
    for col, vals in identity_linked.items():
        for i in range(ctx.n):
            if scenario_seeds[col][i] is None:
                scenario_seeds[col][i] = vals[i]

    # Resolve workflow-consistent columns
    from app.generators.workflow_engine import resolve_workflow_columns
    workflow_linked = resolve_workflow_columns(
        ctx.table.name, all_col_names, ctx.n,
        domain=ctx.domain,
        check_constraints=ctx.check_constraints,
    ) or {}

    # Merge workflow into seeds (scenario values override)
    for col, vals in workflow_linked.items():
        for i in range(ctx.n):
            if scenario_seeds[col][i] is None:
                scenario_seeds[col][i] = vals[i]

    # Resolve contextual comments
    from app.generators.contextual_comments import resolve_contextual_comments
    remaining = [c for c in all_col_names if c not in workflow_linked]
    # Get status values for comment alignment
    status_vals = None
    if ctx.status_columns:
        status_vals = scenario_seeds.get(ctx.status_columns[0])
    contextual = resolve_contextual_comments(
        ctx.table.name, remaining, ctx.n,
        domain=ctx.domain,
        status_values=status_vals,
    ) or {}

    for col, vals in contextual.items():
        for i in range(ctx.n):
            if scenario_seeds[col][i] is None:
                scenario_seeds[col][i] = vals[i]

    # Resolve correlated column groups
    from app.generators.context_inference import resolve_correlated_columns
    correlated = resolve_correlated_columns(
        ctx.table.name, all_col_names, ctx.n,
        check_constraints=ctx.check_constraints,
    ) or {}

    for col, vals in correlated.items():
        for i in range(ctx.n):
            if scenario_seeds[col][i] is None:
                scenario_seeds[col][i] = vals[i]

    # Resolve derivation engine (name→email, country→phone_code, status→reason)
    from app.generators.derivation_engine import resolve_derived_columns
    # Build existing values dict from seeds (non-None values)
    existing_for_derivation: dict[str, list[Any]] = {}
    for col, vals in scenario_seeds.items():
        if any(v is not None for v in vals):
            existing_for_derivation[col] = vals

    derived = resolve_derived_columns(
        ctx.table.name, all_col_names, ctx.n,
        domain=ctx.domain,
        existing_values=existing_for_derivation,
        check_constraints=ctx.check_constraints,
    ) or {}

    for col, vals in derived.items():
        for i in range(ctx.n):
            if scenario_seeds[col][i] is None and vals[i] is not None:
                scenario_seeds[col][i] = vals[i]

    ctx.derived_values = scenario_seeds

    duration = (time.perf_counter() - start) * 1000
    filled_count = sum(
        1 for col in all_col_names
        for v in scenario_seeds.get(col, [])
        if v is not None
    )
    total_cells = len(all_col_names) * ctx.n
    return StageResult(
        stage_name="derive_dependent_values",
        success=True,
        duration_ms=duration,
        data={
            "fill_rate": round(filled_count / total_cells, 4) if total_cells else 0,
            "identity_cols": len(identity_linked),
            "workflow_cols": len(workflow_linked),
            "derived_cols": len(derived),
        },
    )


def _stage_validate_consistency(ctx: TableGenerationContext) -> StageResult:
    """Stage 7: Validate row coherence and apply corrections.

    Checks each row-in-progress for contradictions and fixes them
    deterministically before finalizing.
    """
    start = time.perf_counter()
    corrections = 0
    all_col_names = [c.name for c in ctx.table.columns]

    # Quick coherence check per row: status vs. conditional fields
    for i in range(ctx.n):
        row_vals = {col: ctx.derived_values.get(col, [None] * ctx.n)[i] for col in all_col_names}

        # Rule: negative status should not have approval-related dates
        for status_col in ctx.status_columns:
            status = row_vals.get(status_col)
            if not status or not isinstance(status, str):
                continue
            status_lower = status.lower()

            is_negative = status_lower in {
                "rejected", "denied", "declined", "failed", "cancelled",
                "refused", "closed_denied",
            }
            is_positive = status_lower in {
                "approved", "completed", "resolved", "paid", "settled",
                "accepted", "closed_approved",
            }
            is_waiting = status_lower in {
                "pending", "submitted", "in_review", "under_review",
                "processing", "queued", "open",
            }

            # Fix contradictions
            for col in all_col_names:
                col_lower = col.lower()
                val = ctx.derived_values.get(col, [None] * ctx.n)[i]

                # Rejection reason should only exist for negative statuses
                if re.search(r"rejection_reason|deny_reason|decline_reason", col_lower):
                    if is_positive and val is not None:
                        ctx.derived_values[col][i] = None
                        corrections += 1
                    elif is_waiting and val is not None:
                        ctx.derived_values[col][i] = None
                        corrections += 1

                # Approval date should only exist for positive statuses
                if re.search(r"approval_date|approved_at|completion_date", col_lower):
                    if is_negative and val is not None:
                        ctx.derived_values[col][i] = None
                        corrections += 1
                    elif is_waiting and val is not None:
                        ctx.derived_values[col][i] = None
                        corrections += 1

                # is_active should be False for terminal negative states
                if re.search(r"^is_active$|^active$|active_flag", col_lower):
                    if is_negative and val is True:
                        ctx.derived_values[col][i] = False
                        corrections += 1
                    elif is_positive and val is False:
                        ctx.derived_values[col][i] = True
                        corrections += 1

                # is_closed should align with terminal states
                if re.search(r"^is_closed$|^closed$|closed_flag", col_lower):
                    if (is_negative or is_positive) and val is False:
                        ctx.derived_values[col][i] = True
                        corrections += 1
                    elif is_waiting and val is True:
                        ctx.derived_values[col][i] = False
                        corrections += 1

    ctx.issues_found = corrections
    ctx.corrections_applied = corrections

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="validate_consistency",
        success=True,
        duration_ms=duration,
        corrections_applied=corrections,
        data={
            "rows_checked": ctx.n,
            "corrections_applied": corrections,
        },
    )


def _stage_generate_final_rows(ctx: TableGenerationContext) -> StageResult:
    """Stage 8: Assemble final rows, filling remaining gaps with bulk generation.

    Any column that still has None values after scenario + derivation + correction
    gets filled with type-appropriate random values.
    """
    start = time.perf_counter()
    all_col_names = [c.name for c in ctx.table.columns]
    from app.utils.sql_types import base_type as _base_type, extract_enum_from_check
    from app.generators.semantic_types import SemanticType, detect_semantic_type
    from app.generators.realistic_provider import RealisticProvider
    from faker import Faker
    import uuid
    from datetime import date, timedelta, datetime
    import string

    fake = Faker()
    provider = RealisticProvider(country=ctx.country, domain=ctx.domain)
    from app.generators.context_inference import resolve_contextual_values

    _DATE_START = date(2020, 1, 1)
    _DATE_DAYS = (date(2026, 12, 31) - _DATE_START).days
    _DT_START = datetime(2020, 1, 1)
    _DT_SECS = int((datetime(2026, 12, 31) - _DT_START).total_seconds())

    # Identify conditional columns that should stay None based on row status
    _CONDITIONAL_POSITIVE = re.compile(r"approval_date|approved_at|completion_date|approval_amount", re.I)
    _CONDITIONAL_NEGATIVE = re.compile(r"rejection_reason|deny_reason|decline_reason|cancellation_reason", re.I)

    # Build rows from derived_values, filling gaps
    rows: list[dict[str, Any]] = []
    unique_tracker: dict[str, set] = {}

    for i in range(ctx.n):
        row: dict[str, Any] = {}

        # Determine row status for conditional column handling
        row_status = None
        for sc in ctx.status_columns:
            sv = ctx.derived_values.get(sc, [None] * ctx.n)[i]
            if sv and isinstance(sv, str):
                row_status = sv.lower()
                break

        is_negative = row_status in {
            "rejected", "denied", "declined", "failed", "cancelled",
            "refused", "closed_denied",
        } if row_status else False
        is_positive = row_status in {
            "approved", "completed", "resolved", "paid", "settled",
            "accepted", "closed_approved",
        } if row_status else False

        for col in ctx.table.columns:
            val = ctx.derived_values.get(col.name, [None] * ctx.n)[i]

            if val is not None:
                row[col.name] = val
                continue

            # Skip conditional columns that conflict with row status
            if col.nullable:
                if _CONDITIONAL_NEGATIVE.search(col.name) and (is_positive or not is_negative):
                    row[col.name] = None
                    continue
                if _CONDITIONAL_POSITIVE.search(col.name) and (is_negative or not is_positive):
                    row[col.name] = None
                    continue

            # PK integer → sequential
            if col.is_primary_key and _base_type(col.data_type) == "integer":
                row[col.name] = i + 1
                continue

            # CHECK constraint enum
            enum_vals = extract_enum_from_check(col.check_constraint)
            if enum_vals:
                row[col.name] = random.choice(enum_vals)
                continue

            # Context inference (table + column name awareness)
            col_key = f"{ctx.table.name}.{col.name}"
            if col_key not in unique_tracker:
                ctx_pool = resolve_contextual_values(ctx.table.name, col.name, ctx.n * 3)
                if ctx_pool is not None:
                    unique_tracker[f"_pool_{col_key}"] = ctx_pool
            ctx_pool = unique_tracker.get(f"_pool_{col_key}")
            if ctx_pool:
                if col.is_unique or col.is_primary_key:
                    if col_key not in unique_tracker:
                        unique_tracker[col_key] = set()
                    seen = unique_tracker[col_key]
                    candidate = ctx_pool[i % len(ctx_pool)]
                    suffix = 0
                    while candidate in seen:
                        suffix += 1
                        candidate = f"{ctx_pool[i % len(ctx_pool)]}_{suffix}"
                    seen.add(candidate)
                    row[col.name] = candidate
                else:
                    row[col.name] = random.choice(ctx_pool)
                continue

            # Semantic type
            sem_type = detect_semantic_type(col.name, domain=ctx.domain)
            if sem_type != SemanticType.UNKNOWN:
                val = provider.generate(sem_type)
                if col.is_unique or col.is_primary_key:
                    if col_key not in unique_tracker:
                        unique_tracker[col_key] = set()
                    seen = unique_tracker[col_key]
                    suffix = 0
                    while val in seen:
                        suffix += 1
                        val = f"{provider.generate(sem_type)}_{suffix}"
                    seen.add(val)
                row[col.name] = val
                continue

            # Type-based fallback
            base = _base_type(col.data_type)
            if base == "integer":
                row[col.name] = random.randint(1, 10000)
            elif base == "float":
                row[col.name] = round(random.uniform(0.01, 99999.99), 2)
            elif base == "boolean":
                row[col.name] = random.choice([True, False])
            elif base == "date":
                row[col.name] = (_DATE_START + timedelta(days=random.randint(0, _DATE_DAYS))).isoformat()
            elif base == "datetime":
                row[col.name] = (_DT_START + timedelta(seconds=random.randint(0, _DT_SECS))).isoformat()
            elif base == "uuid":
                row[col.name] = str(uuid.uuid4())
            else:
                row[col.name] = fake.word()

            # Enforce uniqueness for fallback values
            if col.is_unique or col.is_primary_key:
                if col_key not in unique_tracker:
                    unique_tracker[col_key] = set()
                seen = unique_tracker[col_key]
                suffix = 0
                while row[col.name] in seen:
                    suffix += 1
                    row[col.name] = f"{fake.word()}_{suffix}"
                seen.add(row[col.name])

            # Nullable: 10% chance of None
            if col.nullable and not col.is_primary_key and random.random() < 0.1:
                row[col.name] = None

        rows.append(row)

    ctx.rows = rows

    duration = (time.perf_counter() - start) * 1000
    return StageResult(
        stage_name="generate_final_rows",
        success=True,
        duration_ms=duration,
        data={
            "rows_assembled": len(rows),
            "columns_per_row": len(all_col_names),
        },
    )


# ── Helpers ───────────────────────────────────────────────────

def _lifecycle_weights(states: list[str]) -> list[float]:
    """Generate probability weights for lifecycle states.

    Middle states (active/in-progress) are more common than terminal states.
    """
    n = len(states)
    if n <= 1:
        return [1.0]
    if n == 2:
        return [1.0, 1.0]

    # Bell-curve-like weighting: middle states more common
    weights = []
    for i in range(n):
        # Position 0..1
        pos = i / (n - 1)
        # Peak at 0.3 (early-middle states are most common)
        w = 1.0 + 2.0 * (1.0 - abs(pos - 0.3) * 2.0)
        weights.append(max(w, 0.5))

    return weights


# ── Orchestration Engine ──────────────────────────────────────

class GenerationOrchestrator:
    """Orchestrates the scenario-first generation flow.

    The orchestrator runs 8 stages in sequence for each table,
    building up row context from business scenario → derived values
    → validated final rows.
    """

    # Ordered pipeline stages
    _STAGES: list[Callable[[TableGenerationContext], StageResult]] = [
        _stage_understand_schema,
        _stage_understand_business_context,
        _stage_infer_semantic_meaning,
        _stage_detect_dependencies,
        _stage_determine_scenario,
        _stage_derive_dependent_values,
        _stage_validate_consistency,
        _stage_generate_final_rows,
    ]

    def __init__(
        self,
        schema: SchemaMetadata,
        row_count: int = 10,
        country: str = "us",
        domain: str = "unknown",
        max_retries: int = 2,
    ):
        self._schema = schema
        self._row_count = row_count
        self._country = country
        self._domain = domain
        self._max_retries = max_retries
        self._generated: dict[str, list[dict[str, Any]]] = {}
        self._reports: dict[str, OrchestrationReport] = {}

    @property
    def reports(self) -> dict[str, OrchestrationReport]:
        return self._reports

    def generate(self) -> dict[str, list[dict[str, Any]]]:
        """Generate data for all tables using orchestrated scenario-first flow."""
        from app.services.relationship_engine import RelationshipGraph

        graph = RelationshipGraph(self._schema)
        order = graph.get_generation_order()
        table_map = {t.name: t for t in self._schema.tables}

        for table_name in order:
            table = table_map[table_name]
            rows, report = self._orchestrate_table(table)
            self._generated[table_name] = rows
            self._reports[table_name] = report

            logger.info(
                "Orchestrated generation: %s — %d rows in %.1fms (corrections: %d)",
                table_name,
                len(rows),
                report.total_duration_ms,
                report.rows_corrected,
                extra={
                    "stage": "orchestration",
                    "event": "table_orchestrated",
                    "table": table_name,
                    "duration_ms": report.total_duration_ms,
                },
            )

        return self._generated

    def generate_table(self, table: TableMetadata) -> tuple[list[dict[str, Any]], OrchestrationReport]:
        """Generate data for a single table (standalone mode)."""
        return self._orchestrate_table(table)

    def _orchestrate_table(
        self, table: TableMetadata
    ) -> tuple[list[dict[str, Any]], OrchestrationReport]:
        """Run the full 8-stage pipeline for one table."""
        start = time.perf_counter()

        # Build initial context
        check_constraints = {
            c.name: c.check_constraint for c in table.columns if c.check_constraint
        }
        ctx = TableGenerationContext(
            table=table,
            n=self._row_count,
            domain=self._domain,
            country=self._country,
            check_constraints=check_constraints,
        )

        # Pre-populate FK parent data from already-generated tables
        for fk in table.foreign_keys:
            parent_rows = self._generated.get(fk.references_table, [])
            if parent_rows:
                ctx.fk_parent_data[fk.column] = [
                    r.get(fk.references_column) for r in parent_rows
                ]

        # Execute stages with retry support
        stage_results: list[StageResult] = []
        for stage_fn in self._STAGES:
            result = self._execute_stage_with_retry(stage_fn, ctx)
            stage_results.append(result)
            if not result.success:
                logger.error(
                    "Stage %s failed for table %s: %s",
                    result.stage_name, table.name, result.errors,
                )
                break

        total_duration = (time.perf_counter() - start) * 1000

        # Calculate validation pass rate
        total_cells = len(table.columns) * ctx.n
        pass_rate = 1.0 - (ctx.corrections_applied / total_cells) if total_cells > 0 else 1.0

        report = OrchestrationReport(
            table_name=table.name,
            row_count=ctx.n,
            domain=ctx.domain,
            stages=stage_results,
            total_duration_ms=total_duration,
            rows_generated=len(ctx.rows),
            rows_corrected=ctx.corrections_applied,
            validation_pass_rate=pass_rate,
        )

        return ctx.rows, report

    def _execute_stage_with_retry(
        self, stage_fn: Callable, ctx: TableGenerationContext
    ) -> StageResult:
        """Execute a stage with retry on failure."""
        last_error: str = ""
        for attempt in range(self._max_retries + 1):
            try:
                result = stage_fn(ctx)
                return result
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Stage retry %d/%d: %s",
                    attempt + 1, self._max_retries + 1, e,
                )

        return StageResult(
            stage_name=stage_fn.__name__.replace("_stage_", ""),
            success=False,
            duration_ms=0,
            errors=[last_error],
        )


# ── Public API ────────────────────────────────────────────────

def orchestrate_generation(
    schema: SchemaMetadata,
    row_count: int = 10,
    country: str = "us",
    domain: str = "unknown",
    max_retries: int = 2,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Run fully orchestrated scenario-first generation.

    Returns:
        (data, reports) where data is table_name → rows
        and reports is table_name → OrchestrationReport.to_dict()
    """
    orch = GenerationOrchestrator(
        schema=schema,
        row_count=row_count,
        country=country,
        domain=domain,
        max_retries=max_retries,
    )
    data = orch.generate()
    reports = {name: r.to_dict() for name, r in orch.reports.items()}
    return data, reports


def orchestrate_table_generation(
    table: TableMetadata,
    row_count: int = 10,
    country: str = "us",
    domain: str = "unknown",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run orchestrated generation for a single table.

    Returns:
        (rows, report_dict)
    """
    orch = GenerationOrchestrator(
        schema=SchemaMetadata(tables=[table]),
        row_count=row_count,
        country=country,
        domain=domain,
    )
    rows, report = orch.generate_table(table)
    return rows, report.to_dict()


def get_generation_flow_stages() -> list[dict[str, str]]:
    """Return the ordered list of generation flow stages."""
    return [
        {"stage": 1, "name": "understand_schema", "description": "Parse column types, constraints, keys, and structure"},
        {"stage": 2, "name": "understand_business_context", "description": "Infer domain, table purpose, lifecycle states, workflows"},
        {"stage": 3, "name": "infer_semantic_meaning", "description": "Classify columns by role: status, temporal, monetary, identity, actor"},
        {"stage": 4, "name": "detect_dependencies", "description": "Build cross-column derivation graph"},
        {"stage": 5, "name": "determine_scenario", "description": "Assign coherent business scenario to each row (scenario-first)"},
        {"stage": 6, "name": "derive_dependent_values", "description": "Fill columns from scenario context using derivation rules"},
        {"stage": 7, "name": "validate_consistency", "description": "Check for contradictions and apply deterministic corrections"},
        {"stage": 8, "name": "generate_final_rows", "description": "Fill remaining gaps and assemble final rows"},
    ]
