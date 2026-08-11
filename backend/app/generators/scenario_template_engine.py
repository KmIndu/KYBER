"""Reusable Scenario Template Engine.

A registry-based system for managing business scenario templates that
drive synthetic row generation. Every row originates from a named template,
enabling reproducibility, auditability, and coherence.

Features:
- Template registry with register/lookup/list/filter operations
- Domain-aware templates (insurance, banking, healthcare, hr, ecommerce, devops)
- Configurable per-template probability weights
- Scenario inheritance (child templates override parent fields)
- Edge-case and boundary template support
- Row-level provenance (each row tagged with its originating template)
- Custom template registration for user-defined scenarios

Integration:
- Used by the generation pipeline to assign each row a scenario
- Returns enriched rows with _scenario_template metadata
"""

from __future__ import annotations

import copy
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════
# CORE DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════


@dataclass
class FieldSpec:
    """Specification for a single field in a scenario template."""
    pattern: str           # pipe-separated column name patterns (e.g., "status|decision")
    value: Any             # static value, callable, or None
    required: bool = True  # whether the field must exist in table for template to apply
    nullable: bool = True  # whether the value can be None

    def resolve(self) -> Any:
        """Resolve the field value — invoke callable if needed."""
        if callable(self.value):
            return self.value()
        return self.value


@dataclass
class ScenarioTemplate:
    """A reusable business scenario template.

    Templates define a coherent set of field values that together represent
    a complete business scenario. All fields in a template are logically
    consistent with each other.
    """

    # Identity
    name: str                          # Unique identifier (e.g., "approved_loan")
    domain: str                        # Business domain
    category: str                      # happy_path, edge_case, boundary, invalid
    description: str                   # Human-readable description

    # Field specifications
    fields: dict[str, FieldSpec] = field(default_factory=dict)

    # Probability & control
    weight: float = 1.0                # Relative probability weight
    parent: str | None = None          # Parent template name (for inheritance)
    tags: list[str] = field(default_factory=list)  # Searchable tags

    # Edge case metadata
    is_edge_case: bool = False
    edge_case_type: str | None = None  # "rare_event", "boundary_value", "error_condition", etc.

    def to_dict(self) -> dict[str, Any]:
        """Serialize template metadata (excludes field callables)."""
        return {
            "name": self.name,
            "domain": self.domain,
            "category": self.category,
            "description": self.description,
            "weight": self.weight,
            "parent": self.parent,
            "tags": self.tags,
            "is_edge_case": self.is_edge_case,
            "edge_case_type": self.edge_case_type,
            "field_count": len(self.fields),
            "field_patterns": list(self.fields.keys()),
        }


@dataclass
class RowProvenance:
    """Tracks which template generated a row."""
    template_name: str
    template_domain: str
    template_category: str
    row_index: int


@dataclass
class TemplateGenerationResult:
    """Result of template-driven generation for a table."""
    table_name: str
    domain: str
    total_rows: int
    rows: list[dict[str, Any]]
    provenance: list[RowProvenance]
    template_distribution: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "domain": self.domain,
            "total_rows": self.total_rows,
            "template_distribution": {
                name: {
                    "count": count,
                    "percentage": round(count / max(self.total_rows, 1) * 100, 1),
                }
                for name, count in self.template_distribution.items()
            },
            "provenance_sample": [
                {
                    "row_index": p.row_index,
                    "template": p.template_name,
                    "category": p.template_category,
                }
                for p in self.provenance[:20]  # Sample for API response
            ],
        }


# ═══════════════════════════════════════════════════════════════
# TEMPLATE REGISTRY
# ═══════════════════════════════════════════════════════════════


class TemplateRegistry:
    """Central registry for scenario templates.

    Provides registration, lookup, inheritance resolution, and
    probability-weighted selection.
    """

    def __init__(self) -> None:
        self._templates: dict[str, ScenarioTemplate] = {}
        self._by_domain: dict[str, list[str]] = {}  # domain → [template_names]
        self._by_category: dict[str, list[str]] = {}
        self._by_tag: dict[str, list[str]] = {}
        self._inheritance_cache: dict[str, ScenarioTemplate] = {}

    # ── Registration ─────────────────────────────────────────

    def register(self, template: ScenarioTemplate) -> None:
        """Register a template in the registry."""
        if template.name in self._templates:
            raise ValueError(f"Template '{template.name}' already registered")

        self._templates[template.name] = template
        self._by_domain.setdefault(template.domain, []).append(template.name)
        self._by_category.setdefault(template.category, []).append(template.name)
        for tag in template.tags:
            self._by_tag.setdefault(tag, []).append(template.name)
        # Invalidate inheritance cache
        self._inheritance_cache.pop(template.name, None)

    def register_many(self, templates: list[ScenarioTemplate]) -> None:
        """Register multiple templates."""
        for t in templates:
            self.register(t)

    def deregister(self, name: str) -> bool:
        """Remove a template from the registry. Returns True if found."""
        template = self._templates.pop(name, None)
        if template is None:
            return False
        self._by_domain.get(template.domain, []).remove(name) if name in self._by_domain.get(template.domain, []) else None
        self._by_category.get(template.category, []).remove(name) if name in self._by_category.get(template.category, []) else None
        for tag in template.tags:
            if name in self._by_tag.get(tag, []):
                self._by_tag[tag].remove(name)
        self._inheritance_cache.pop(name, None)
        return True

    # ── Lookup ───────────────────────────────────────────────

    def get(self, name: str) -> ScenarioTemplate | None:
        """Get a template by name."""
        return self._templates.get(name)

    def get_resolved(self, name: str) -> ScenarioTemplate | None:
        """Get a template with inheritance resolved (fields merged from parent chain)."""
        if name in self._inheritance_cache:
            return self._inheritance_cache[name]

        template = self._templates.get(name)
        if template is None:
            return None

        resolved = self._resolve_inheritance(template)
        self._inheritance_cache[name] = resolved
        return resolved

    def list_all(self) -> list[ScenarioTemplate]:
        """List all registered templates."""
        return list(self._templates.values())

    def list_by_domain(self, domain: str) -> list[ScenarioTemplate]:
        """List templates for a specific domain."""
        names = self._by_domain.get(domain, [])
        return [self._templates[n] for n in names if n in self._templates]

    def list_by_category(self, category: str) -> list[ScenarioTemplate]:
        """List templates by category (happy_path, edge_case, etc.)."""
        names = self._by_category.get(category, [])
        return [self._templates[n] for n in names if n in self._templates]

    def list_by_tag(self, tag: str) -> list[ScenarioTemplate]:
        """List templates matching a tag."""
        names = self._by_tag.get(tag, [])
        return [self._templates[n] for n in names if n in self._templates]

    def search(self, query: str) -> list[ScenarioTemplate]:
        """Search templates by name, description, or tags."""
        q = query.lower()
        results = []
        for t in self._templates.values():
            if (q in t.name.lower() or q in t.description.lower()
                    or any(q in tag.lower() for tag in t.tags)):
                results.append(t)
        return results

    @property
    def domains(self) -> list[str]:
        """List all domains with registered templates."""
        return list(self._by_domain.keys())

    @property
    def size(self) -> int:
        """Number of registered templates."""
        return len(self._templates)

    # ── Inheritance resolution ───────────────────────────────

    def _resolve_inheritance(self, template: ScenarioTemplate) -> ScenarioTemplate:
        """Resolve template inheritance chain, merging fields from ancestors."""
        if template.parent is None:
            return template

        # Build inheritance chain (child → parent → grandparent → ...)
        chain: list[ScenarioTemplate] = [template]
        visited: set[str] = {template.name}
        current = template

        while current.parent:
            if current.parent in visited:
                break  # Circular inheritance protection
            parent = self._templates.get(current.parent)
            if parent is None:
                break  # Parent not found
            chain.append(parent)
            visited.add(parent.name)
            current = parent

        # Merge fields from root ancestor to child (child overrides parent)
        merged_fields: dict[str, FieldSpec] = {}
        for ancestor in reversed(chain):
            merged_fields.update(ancestor.fields)

        # Create resolved template (shallow copy with merged fields)
        resolved = ScenarioTemplate(
            name=template.name,
            domain=template.domain,
            category=template.category,
            description=template.description,
            fields=merged_fields,
            weight=template.weight,
            parent=template.parent,
            tags=template.tags,
            is_edge_case=template.is_edge_case,
            edge_case_type=template.edge_case_type,
        )
        return resolved

    # ── Selection with configurable probabilities ────────────

    def select(
        self,
        n: int,
        domain: str | None = None,
        category_weights: dict[str, float] | None = None,
        include_edge_cases: bool = True,
        edge_case_ratio: float = 0.15,
    ) -> list[ScenarioTemplate]:
        """Select n templates using probability-weighted sampling.

        Args:
            n: Number of templates to select.
            domain: Filter to specific domain (None = all).
            category_weights: Override default category distribution.
            include_edge_cases: Whether to include edge_case/boundary templates.
            edge_case_ratio: Fraction of rows from edge cases (when included).

        Returns:
            List of n resolved templates (inheritance applied).
        """
        # Get candidate templates
        if domain:
            candidates = self.list_by_domain(domain)
            # Add general templates as fallback
            general = self.list_by_domain("general")
            if not candidates:
                candidates = general
        else:
            candidates = self.list_all()

        if not candidates:
            return []

        # Split into main and edge-case pools
        main_pool: list[ScenarioTemplate] = []
        edge_pool: list[ScenarioTemplate] = []

        for t in candidates:
            if t.is_edge_case or t.category in ("edge_case", "boundary"):
                edge_pool.append(t)
            else:
                main_pool.append(t)

        # If no main pool, use all candidates
        if not main_pool:
            main_pool = candidates
            edge_pool = []

        # Determine how many edge-case vs main selections
        if include_edge_cases and edge_pool:
            n_edge = max(1, int(n * edge_case_ratio))
            n_main = n - n_edge
        else:
            n_main = n
            n_edge = 0

        selected: list[ScenarioTemplate] = []

        # Select main templates (weighted by template.weight and category_weights)
        selected.extend(self._weighted_select(main_pool, n_main, category_weights))

        # Select edge-case templates
        if n_edge > 0 and edge_pool:
            selected.extend(self._weighted_select(edge_pool, n_edge, None))

        # Shuffle to interleave edge cases naturally
        random.shuffle(selected)

        # Resolve inheritance for all selected
        return [self.get_resolved(t.name) or t for t in selected]

    def _weighted_select(
        self,
        pool: list[ScenarioTemplate],
        n: int,
        category_weights: dict[str, float] | None,
    ) -> list[ScenarioTemplate]:
        """Select from pool using per-template weights and category biases."""
        if not pool:
            return []

        # Compute effective weight for each template
        effective_weights: list[float] = []
        default_category_weights = {
            "happy_path": 1.0,
            "edge_case": 0.6,
            "boundary": 0.4,
            "invalid": 0.3,
        }
        cat_weights = category_weights or default_category_weights

        for t in pool:
            base = t.weight
            cat_mult = cat_weights.get(t.category, 1.0)
            effective_weights.append(base * cat_mult)

        # Normalize
        total = sum(effective_weights)
        if total == 0:
            effective_weights = [1.0] * len(pool)
            total = len(pool)

        return random.choices(pool, weights=effective_weights, k=n)


# ═══════════════════════════════════════════════════════════════
# TEMPLATE APPLICATION
# ═══════════════════════════════════════════════════════════════


_TEMPLATE_MATCH_EXCLUSIONS: dict[str, re.Pattern[str]] = {
    # "status" should NOT match columns with RAG/virus/color/moderation semantics
    "status": re.compile(r"rag|virus|color|moderation", re.I),
    "state": re.compile(r"rag|virus|color|moderation", re.I),
    # "comment"/"notes"/"remarks" should NOT match numeric/flag columns
    "comment": re.compile(r"count|flag|id$", re.I),
    "notes": re.compile(r"count|flag|id$", re.I),
    "remarks": re.compile(r"count|flag|id$", re.I),
}


def _match_field_pattern(col_name: str, pattern: str) -> bool:
    """Check if column name matches a pipe-separated pattern."""
    col_lower = col_name.lower()
    for p in pattern.split("|"):
        p = p.strip()
        if p in col_lower:
            # Check exclusions — skip if column has specialized semantics
            exclusion = _TEMPLATE_MATCH_EXCLUSIONS.get(p)
            if exclusion and exclusion.search(col_lower):
                continue
            return True
    return False


def apply_template_to_row(
    template: ScenarioTemplate,
    column_names: list[str],
    check_constraints: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    """Apply a resolved template to generate a single row.

    Returns a dict of column_name → value for columns that the template
    provides values for. Columns not covered by the template get None.
    """
    from app.utils.sql_types import extract_enum_from_check

    checks = check_constraints or {}
    row: dict[str, Any] = {}

    for col in column_names:
        matched_spec: FieldSpec | None = None
        for pattern, spec in template.fields.items():
            if _match_field_pattern(col, pattern):
                matched_spec = spec
                break

        if matched_spec is None:
            row[col] = None  # Not covered by template — fallback generator will fill
            continue

        value = matched_spec.resolve()

        # Validate against CHECK enum if present
        enum_values = extract_enum_from_check(checks.get(col))
        if enum_values and value is not None:
            val_str = str(value).lower()
            exact = [e for e in enum_values if e.lower() == val_str]
            if exact:
                value = exact[0]
            else:
                fuzzy = [e for e in enum_values if val_str in e.lower() or e.lower() in val_str]
                value = fuzzy[0] if fuzzy else random.choice(enum_values)

        row[col] = value

    return row


# ═══════════════════════════════════════════════════════════════
# TEMPLATE GENERATION ENGINE
# ═══════════════════════════════════════════════════════════════


def generate_from_templates(
    table_name: str,
    column_names: list[str],
    n: int,
    registry: TemplateRegistry,
    domain: str | None = None,
    category_weights: dict[str, float] | None = None,
    include_edge_cases: bool = True,
    edge_case_ratio: float = 0.15,
    check_constraints: dict[str, list[str] | None] | None = None,
) -> TemplateGenerationResult:
    """Generate n rows from registered templates.

    Each row is tagged with its originating template for traceability.

    Args:
        table_name: Name of the table being generated.
        column_names: List of column names.
        n: Number of rows to generate.
        registry: Template registry to select from.
        domain: Domain filter (auto-detected if not provided).
        category_weights: Override category probability distribution.
        include_edge_cases: Whether to include edge case templates.
        edge_case_ratio: Fraction of edge case rows.
        check_constraints: Column CHECK constraints for enum validation.

    Returns:
        TemplateGenerationResult with rows, provenance, and distribution.
    """
    # Auto-detect domain from table name if not provided
    if domain is None or domain == "unknown":
        from app.generators.context_inference import _infer_domain
        domain = _infer_domain(table_name)

    # Select templates
    selected = registry.select(
        n=n,
        domain=domain,
        category_weights=category_weights,
        include_edge_cases=include_edge_cases,
        edge_case_ratio=edge_case_ratio,
    )

    # If registry has no templates for this domain, return empty
    if not selected:
        return TemplateGenerationResult(
            table_name=table_name,
            domain=domain or "unknown",
            total_rows=0,
            rows=[],
            provenance=[],
            template_distribution={},
        )

    # Generate rows
    rows: list[dict[str, Any]] = []
    provenance: list[RowProvenance] = []
    distribution: dict[str, int] = {}

    for idx, template in enumerate(selected):
        row = apply_template_to_row(template, column_names, check_constraints)
        # Tag row with provenance metadata
        row["_scenario_template"] = template.name
        rows.append(row)
        provenance.append(RowProvenance(
            template_name=template.name,
            template_domain=template.domain,
            template_category=template.category,
            row_index=idx,
        ))
        distribution[template.name] = distribution.get(template.name, 0) + 1

    return TemplateGenerationResult(
        table_name=table_name,
        domain=domain or "unknown",
        total_rows=len(rows),
        rows=rows,
        provenance=provenance,
        template_distribution=distribution,
    )


# ═══════════════════════════════════════════════════════════════
# BUILT-IN TEMPLATE DEFINITIONS
# ═══════════════════════════════════════════════════════════════


def _build_insurance_templates() -> list[ScenarioTemplate]:
    """Build insurance domain templates."""
    return [
        # ── Base templates (parents) ──
        ScenarioTemplate(
            name="insurance_base_approved",
            domain="insurance", category="happy_path",
            description="Base template for approved insurance scenarios",
            fields={
                "status|decision|outcome": FieldSpec("status|decision|outcome", "approved"),
                "denial_reason|reject_reason|rejection_reason": FieldSpec("denial_reason|reject_reason|rejection_reason", None),
                "is_active|active": FieldSpec("is_active|active", False),
                "is_closed|completed": FieldSpec("is_closed|completed", True),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks", "Claim verified and approved."),
            },
            weight=2.5,
            tags=["approved", "positive", "base"],
        ),
        ScenarioTemplate(
            name="insurance_base_denied",
            domain="insurance", category="happy_path",
            description="Base template for denied insurance scenarios",
            fields={
                "status|decision|outcome": FieldSpec("status|decision|outcome", "denied"),
                "approved_amount|payout": FieldSpec("approved_amount|payout", 0),
                "is_active|active": FieldSpec("is_active|active", False),
                "is_closed|completed": FieldSpec("is_closed|completed", True),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks", "Claim denied."),
            },
            weight=2.0,
            tags=["denied", "negative", "base"],
        ),
        ScenarioTemplate(
            name="insurance_base_pending",
            domain="insurance", category="happy_path",
            description="Base template for pending insurance scenarios",
            fields={
                "status|decision|outcome": FieldSpec("status|decision|outcome", "pending"),
                "denial_reason|reject_reason|rejection_reason": FieldSpec("denial_reason|reject_reason|rejection_reason", None),
                "approved_amount|payout": FieldSpec("approved_amount|payout", None),
                "is_active|active": FieldSpec("is_active|active", True),
                "is_closed|completed": FieldSpec("is_closed|completed", False),
                "review_date|reviewed_at": FieldSpec("review_date|reviewed_at", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks", "Awaiting review."),
            },
            weight=1.5,
            tags=["pending", "waiting", "base"],
        ),

        # ── Inherited: Approved variants ──
        ScenarioTemplate(
            name="approved_claim_standard",
            domain="insurance", category="happy_path",
            description="Standard claim approved with full documentation",
            parent="insurance_base_approved",
            fields={
                "approved_amount|payout": FieldSpec("approved_amount|payout",
                    lambda: round(random.uniform(5000, 50000), 2)),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Claim verified and approved. All documentation complete."),
                "review_date|reviewed_at": FieldSpec("review_date|reviewed_at",
                    lambda: date.today() - timedelta(days=random.randint(1, 30))),
                "reviewed_by|adjuster": FieldSpec("reviewed_by|adjuster",
                    lambda: random.choice(["Sarah Johnson", "Michael Chen", "Priya Patel", "James Wilson"])),
                "payment_method|pay_method": FieldSpec("payment_method|pay_method",
                    lambda: random.choice(["eft", "cheque", "direct_deposit"])),
            },
            weight=3.0,
            tags=["approved", "standard", "common"],
        ),
        ScenarioTemplate(
            name="approved_claim_after_escalation",
            domain="insurance", category="happy_path",
            description="High-value claim approved after management escalation",
            parent="insurance_base_approved",
            fields={
                "approved_amount|payout": FieldSpec("approved_amount|payout",
                    lambda: round(random.uniform(50000, 200000), 2)),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Escalated to senior adjuster. Approved after additional review."),
                "escalated|is_escalated": FieldSpec("escalated|is_escalated", True),
                "reviewed_by|adjuster": FieldSpec("reviewed_by|adjuster",
                    lambda: random.choice(["Director Maria Lopez", "VP David Park", "Senior Adj. Robert Kim"])),
            },
            weight=1.0,
            tags=["approved", "escalated", "high_value"],
        ),
        ScenarioTemplate(
            name="approved_claim_partial",
            domain="insurance", category="happy_path",
            description="Claim partially approved with some exclusions",
            parent="insurance_base_approved",
            fields={
                "status|decision|outcome": FieldSpec("status|decision|outcome", "partial"),
                "approved_amount|payout": FieldSpec("approved_amount|payout",
                    lambda: round(random.uniform(1000, 15000), 2)),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Partial approval — some items not covered under current plan."),
            },
            weight=1.5,
            tags=["approved", "partial"],
        ),

        # ── Inherited: Denied variants ──
        ScenarioTemplate(
            name="denied_claim_insufficient_docs",
            domain="insurance", category="happy_path",
            description="Claim denied due to missing documentation",
            parent="insurance_base_denied",
            fields={
                "denial_reason|reject_reason|rejection_reason": FieldSpec(
                    "denial_reason|reject_reason|rejection_reason", "insufficient_documentation"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Required medical records not provided within 30-day window."),
                "reviewed_by|adjuster": FieldSpec("reviewed_by|adjuster",
                    lambda: random.choice(["Sarah Johnson", "Michael Chen", "Priya Patel"])),
            },
            weight=2.0,
            tags=["denied", "documentation", "common"],
        ),
        ScenarioTemplate(
            name="denied_claim_policy_lapsed",
            domain="insurance", category="happy_path",
            description="Claim denied because policy was not active",
            parent="insurance_base_denied",
            fields={
                "denial_reason|reject_reason|rejection_reason": FieldSpec(
                    "denial_reason|reject_reason|rejection_reason", "policy_lapsed"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Policy lapsed due to non-payment. Incident occurred after coverage end date."),
            },
            weight=1.5,
            tags=["denied", "lapsed"],
        ),
        ScenarioTemplate(
            name="denied_claim_pre_existing",
            domain="insurance", category="edge_case",
            description="Claim denied for pre-existing condition",
            parent="insurance_base_denied",
            fields={
                "denial_reason|reject_reason|rejection_reason": FieldSpec(
                    "denial_reason|reject_reason|rejection_reason", "pre_existing_condition"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Condition documented in medical history prior to policy effective date."),
            },
            weight=1.0,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["denied", "pre_existing", "edge_case"],
        ),
        ScenarioTemplate(
            name="fraudulent_claim",
            domain="insurance", category="edge_case",
            description="Claim flagged for potential fraud",
            parent="insurance_base_denied",
            fields={
                "denial_reason|reject_reason|rejection_reason": FieldSpec(
                    "denial_reason|reject_reason|rejection_reason", "fraud_suspected"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Irregularities detected. Case referred to Special Investigations Unit."),
                "escalated|is_escalated": FieldSpec("escalated|is_escalated", True),
                "reviewed_by|adjuster": FieldSpec("reviewed_by|adjuster",
                    lambda: random.choice(["SIU Team Lead", "Fraud Analyst K. Rogers", "Investigations Director"])),
            },
            weight=0.5,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["denied", "fraud", "edge_case", "escalated"],
        ),

        # ── Inherited: Pending variants ──
        ScenarioTemplate(
            name="pending_claim_additional_info",
            domain="insurance", category="happy_path",
            description="Claim awaiting additional information from claimant",
            parent="insurance_base_pending",
            fields={
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Awaiting additional medical records from treating physician."),
                "reviewed_by|adjuster": FieldSpec("reviewed_by|adjuster",
                    lambda: random.choice(["Claims Processor A. Smith", "Intake Analyst B. Davis"])),
            },
            weight=1.5,
            tags=["pending", "additional_info"],
        ),

        # ── Boundary templates ──
        ScenarioTemplate(
            name="claim_at_policy_limit",
            domain="insurance", category="boundary",
            description="Claim approved at maximum policy limit",
            parent="insurance_base_approved",
            fields={
                "approved_amount|payout": FieldSpec("approved_amount|payout",
                    lambda: round(random.uniform(99000, 100000), 2)),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Approved at policy maximum. Future claims may exhaust remaining coverage."),
                "escalated|is_escalated": FieldSpec("escalated|is_escalated", True),
            },
            weight=0.3,
            is_edge_case=True,
            edge_case_type="boundary_value",
            tags=["approved", "boundary", "limit"],
        ),
        ScenarioTemplate(
            name="claim_zero_deductible",
            domain="insurance", category="boundary",
            description="Claim where deductible exceeds amount — zero payout",
            parent="insurance_base_approved",
            fields={
                "approved_amount|payout": FieldSpec("approved_amount|payout", 0.00),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Deductible exceeds claim amount. No payout required."),
            },
            weight=0.2,
            is_edge_case=True,
            edge_case_type="boundary_value",
            tags=["approved", "boundary", "zero_payout"],
        ),
    ]


def _build_banking_templates() -> list[ScenarioTemplate]:
    """Build banking domain templates."""
    return [
        # ── Base templates ──
        ScenarioTemplate(
            name="banking_base_completed",
            domain="banking", category="happy_path",
            description="Base template for completed banking transactions",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "completed"),
                "error_code|err_code": FieldSpec("error_code|err_code", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks", "Transaction processed successfully."),
            },
            weight=2.0,
            tags=["completed", "positive", "base"],
        ),
        ScenarioTemplate(
            name="banking_base_failed",
            domain="banking", category="happy_path",
            description="Base template for failed banking transactions",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "failed"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks", "Transaction failed."),
            },
            weight=1.5,
            tags=["failed", "negative", "base"],
        ),

        # ── Inherited: Completed variants ──
        ScenarioTemplate(
            name="successful_payment",
            domain="banking", category="happy_path",
            description="Successful payment transaction",
            parent="banking_base_completed",
            fields={
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: round(random.uniform(50, 25000), 2)),
                "transaction_type|txn_type|type": FieldSpec("transaction_type|txn_type|type", "payment"),
                "currency|currency_code": FieldSpec("currency|currency_code",
                    lambda: random.choice(["USD", "CAD", "GBP", "EUR"])),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Payment processed and confirmed."),
            },
            weight=3.0,
            tags=["payment", "success", "common"],
        ),
        ScenarioTemplate(
            name="successful_transfer",
            domain="banking", category="happy_path",
            description="Successful fund transfer",
            parent="banking_base_completed",
            fields={
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: round(random.uniform(100, 50000), 2)),
                "transaction_type|txn_type|type": FieldSpec("transaction_type|txn_type|type", "transfer"),
                "currency|currency_code": FieldSpec("currency|currency_code",
                    lambda: random.choice(["USD", "CAD", "GBP", "EUR"])),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Transfer completed. Funds available in recipient account."),
            },
            weight=2.5,
            tags=["transfer", "success", "common"],
        ),
        ScenarioTemplate(
            name="approved_loan",
            domain="banking", category="happy_path",
            description="Loan application approved",
            parent="banking_base_completed",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "approved"),
                "amount|total|balance|loan_amount": FieldSpec("amount|total|balance|loan_amount",
                    lambda: round(random.uniform(10000, 500000), 2)),
                "transaction_type|txn_type|type": FieldSpec("transaction_type|txn_type|type", "loan"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Loan approved. Disbursement scheduled."),
                "interest_rate|rate": FieldSpec("interest_rate|rate",
                    lambda: round(random.uniform(3.5, 12.0), 2)),
            },
            weight=1.5,
            tags=["loan", "approved", "positive"],
        ),

        # ── Inherited: Failed variants ──
        ScenarioTemplate(
            name="failed_transaction_insufficient_funds",
            domain="banking", category="happy_path",
            description="Transaction failed due to insufficient balance",
            parent="banking_base_failed",
            fields={
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: round(random.uniform(5000, 100000), 2)),
                "error_code|err_code": FieldSpec("error_code|err_code", "INSUFFICIENT_FUNDS"),
                "transaction_type|txn_type|type": FieldSpec("transaction_type|txn_type|type",
                    lambda: random.choice(["transfer", "payment", "withdrawal"])),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Transaction declined — insufficient funds in source account."),
            },
            weight=2.0,
            tags=["failed", "insufficient_funds", "common"],
        ),
        ScenarioTemplate(
            name="failed_kyc",
            domain="banking", category="edge_case",
            description="Account or transaction blocked due to KYC failure",
            parent="banking_base_failed",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "blocked"),
                "error_code|err_code": FieldSpec("error_code|err_code", "KYC_FAILED"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "KYC verification failed. Account restricted pending identity verification."),
                "is_active|active": FieldSpec("is_active|active", False),
            },
            weight=0.8,
            is_edge_case=True,
            edge_case_type="error_condition",
            tags=["kyc", "blocked", "compliance", "edge_case"],
        ),
        ScenarioTemplate(
            name="fraud_blocked_transaction",
            domain="banking", category="edge_case",
            description="Transaction blocked by fraud detection",
            parent="banking_base_failed",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "blocked"),
                "error_code|err_code": FieldSpec("error_code|err_code", "FRAUD_ALERT"),
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: round(random.uniform(1000, 50000), 2)),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Blocked by fraud detection system. Anomalous pattern detected."),
            },
            weight=0.5,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["fraud", "blocked", "edge_case"],
        ),

        # ── Pending/review ──
        ScenarioTemplate(
            name="transaction_pending_compliance",
            domain="banking", category="happy_path",
            description="Large transaction held for compliance review",
            fields={
                "status|state|transaction_status": FieldSpec("status|state|transaction_status", "pending_review"),
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: round(random.uniform(10000, 500000), 2)),
                "error_code|err_code": FieldSpec("error_code|err_code", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Large transaction flagged for compliance review."),
                "transaction_type|txn_type|type": FieldSpec("transaction_type|txn_type|type", "wire_transfer"),
            },
            weight=1.0,
            tags=["pending", "compliance", "review"],
        ),

        # ── Boundary ──
        ScenarioTemplate(
            name="transaction_at_daily_limit",
            domain="banking", category="boundary",
            description="Transaction exactly at daily transfer limit",
            parent="banking_base_completed",
            fields={
                "amount|total|balance": FieldSpec("amount|total|balance",
                    lambda: random.choice([10000.00, 25000.00, 50000.00])),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Transaction at daily limit. Further transactions may be restricted."),
            },
            weight=0.3,
            is_edge_case=True,
            edge_case_type="boundary_value",
            tags=["boundary", "limit"],
        ),

        # ── Inactive account ──
        ScenarioTemplate(
            name="inactive_account",
            domain="banking", category="edge_case",
            description="Dormant/inactive account flagged for review",
            fields={
                "status|state|account_status": FieldSpec("status|state|account_status", "inactive"),
                "is_active|active": FieldSpec("is_active|active", False),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Account dormant for 12+ months. Flagged for closure review."),
                "last_activity|last_transaction_date": FieldSpec("last_activity|last_transaction_date",
                    lambda: date.today() - timedelta(days=random.randint(365, 730))),
            },
            weight=0.6,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["inactive", "dormant", "edge_case"],
        ),
    ]


def _build_healthcare_templates() -> list[ScenarioTemplate]:
    """Build healthcare domain templates."""
    return [
        ScenarioTemplate(
            name="healthcare_base_admitted",
            domain="healthcare", category="happy_path",
            description="Base template for admitted patients",
            fields={
                "status|state|patient_status": FieldSpec("status|state|patient_status", "admitted"),
                "is_active|active": FieldSpec("is_active|active", True),
                "discharge_date|discharged_at": FieldSpec("discharge_date|discharged_at", None),
            },
            weight=2.0,
            tags=["admitted", "base"],
        ),
        ScenarioTemplate(
            name="patient_routine_admission",
            domain="healthcare", category="happy_path",
            description="Routine patient admission for scheduled procedure",
            parent="healthcare_base_admitted",
            fields={
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Patient admitted for scheduled procedure. Vitals stable."),
                "priority|severity|triage": FieldSpec("priority|severity|triage", "routine"),
                "diagnosis_code|icd_code": FieldSpec("diagnosis_code|icd_code",
                    lambda: random.choice(["K80.20", "M17.11", "I25.10", "J44.1"])),
                "attending_doctor|doctor_name|physician": FieldSpec("attending_doctor|doctor_name|physician",
                    lambda: random.choice(["Dr. Sarah Mitchell", "Dr. James Park", "Dr. Aisha Khan"])),
            },
            weight=3.0,
            tags=["admitted", "routine", "common"],
        ),
        ScenarioTemplate(
            name="patient_discharged_recovered",
            domain="healthcare", category="happy_path",
            description="Patient discharged after successful recovery",
            fields={
                "status|state|patient_status": FieldSpec("status|state|patient_status", "discharged"),
                "is_active|active": FieldSpec("is_active|active", False),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Patient recovered well. Prescribed follow-up in 2 weeks."),
                "priority|severity|triage": FieldSpec("priority|severity|triage", "routine"),
                "discharge_date|discharged_at": FieldSpec("discharge_date|discharged_at",
                    lambda: date.today() - timedelta(days=random.randint(0, 7))),
            },
            weight=2.5,
            tags=["discharged", "recovered", "positive"],
        ),
        ScenarioTemplate(
            name="patient_emergency_critical",
            domain="healthcare", category="edge_case",
            description="Emergency critical admission",
            parent="healthcare_base_admitted",
            fields={
                "status|state|patient_status": FieldSpec("status|state|patient_status", "critical"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Emergency admission. Patient in ICU. Family notified."),
                "priority|severity|triage": FieldSpec("priority|severity|triage", "critical"),
                "diagnosis_code|icd_code": FieldSpec("diagnosis_code|icd_code",
                    lambda: random.choice(["I21.0", "I63.9", "J96.01", "S06.6"])),
            },
            weight=0.7,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["emergency", "critical", "edge_case"],
        ),
        ScenarioTemplate(
            name="patient_awaiting_results",
            domain="healthcare", category="happy_path",
            description="Patient waiting for diagnostic results",
            parent="healthcare_base_admitted",
            fields={
                "status|state|patient_status": FieldSpec("status|state|patient_status", "awaiting_results"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Lab samples collected. Awaiting pathology report."),
                "priority|severity|triage": FieldSpec("priority|severity|triage", "normal"),
                "diagnosis_code|icd_code": FieldSpec("diagnosis_code|icd_code", None),
            },
            weight=1.5,
            tags=["awaiting", "diagnostic"],
        ),
    ]


def _build_hr_templates() -> list[ScenarioTemplate]:
    """Build HR domain templates."""
    return [
        ScenarioTemplate(
            name="hr_base_active",
            domain="hr", category="happy_path",
            description="Base template for active employees",
            fields={
                "status|state|employee_status": FieldSpec("status|state|employee_status", "active"),
                "is_active|active": FieldSpec("is_active|active", True),
                "termination_reason|exit_reason": FieldSpec("termination_reason|exit_reason", None),
                "termination_date|exit_date": FieldSpec("termination_date|exit_date", None),
            },
            weight=2.0,
            tags=["active", "base"],
        ),
        ScenarioTemplate(
            name="employee_good_standing",
            domain="hr", category="happy_path",
            description="Active employee in good standing",
            parent="hr_base_active",
            fields={
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Employee in good standing. Annual review completed."),
                "performance_rating|rating": FieldSpec("performance_rating|rating",
                    lambda: random.choice(["exceeds_expectations", "meets_expectations"])),
                "department|dept": FieldSpec("department|dept",
                    lambda: random.choice(["Engineering", "Finance", "Operations", "Marketing", "HR"])),
            },
            weight=3.0,
            tags=["active", "good_standing", "common"],
        ),
        ScenarioTemplate(
            name="employee_on_probation",
            domain="hr", category="happy_path",
            description="New hire on probation period",
            parent="hr_base_active",
            fields={
                "status|state|employee_status": FieldSpec("status|state|employee_status", "probation"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "New hire — probation review scheduled at 90 days."),
                "performance_rating|rating": FieldSpec("performance_rating|rating", "pending_review"),
            },
            weight=1.0,
            tags=["probation", "new_hire"],
        ),
        ScenarioTemplate(
            name="employee_terminated_performance",
            domain="hr", category="edge_case",
            description="Employee terminated for performance issues",
            fields={
                "status|state|employee_status": FieldSpec("status|state|employee_status", "terminated"),
                "is_active|active": FieldSpec("is_active|active", False),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Termination for cause — repeated performance issues documented."),
                "performance_rating|rating": FieldSpec("performance_rating|rating", "unsatisfactory"),
                "termination_reason|exit_reason": FieldSpec("termination_reason|exit_reason", "performance"),
                "termination_date|exit_date": FieldSpec("termination_date|exit_date",
                    lambda: date.today() - timedelta(days=random.randint(1, 90))),
            },
            weight=0.6,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["terminated", "performance", "edge_case"],
        ),
        ScenarioTemplate(
            name="employee_on_leave",
            domain="hr", category="happy_path",
            description="Employee on approved leave",
            parent="hr_base_active",
            fields={
                "status|state|employee_status": FieldSpec("status|state|employee_status", "on_leave"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    lambda: random.choice([
                        "Approved medical leave — expected return in 6 weeks.",
                        "Parental leave approved. Replacement assigned.",
                        "Personal leave — approved by department head.",
                    ])),
            },
            weight=1.0,
            tags=["leave", "approved"],
        ),
    ]


def _build_ecommerce_templates() -> list[ScenarioTemplate]:
    """Build ecommerce domain templates."""
    return [
        ScenarioTemplate(
            name="ecommerce_base_delivered",
            domain="ecommerce", category="happy_path",
            description="Base template for delivered orders",
            fields={
                "status|state|order_status": FieldSpec("status|state|order_status", "delivered"),
                "payment_status|pay_status": FieldSpec("payment_status|pay_status", "paid"),
                "return_reason|refund_reason": FieldSpec("return_reason|refund_reason", None),
            },
            weight=2.0,
            tags=["delivered", "positive", "base"],
        ),
        ScenarioTemplate(
            name="order_delivered_standard",
            domain="ecommerce", category="happy_path",
            description="Order successfully delivered",
            parent="ecommerce_base_delivered",
            fields={
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Package delivered. Signature obtained."),
                "shipping_method|ship_method": FieldSpec("shipping_method|ship_method",
                    lambda: random.choice(["express", "standard", "priority"])),
                "amount|total|order_total": FieldSpec("amount|total|order_total",
                    lambda: round(random.uniform(25, 500), 2)),
            },
            weight=3.5,
            tags=["delivered", "success", "common"],
        ),
        ScenarioTemplate(
            name="order_returned_defective",
            domain="ecommerce", category="edge_case",
            description="Order returned due to defective product",
            fields={
                "status|state|order_status": FieldSpec("status|state|order_status", "returned"),
                "payment_status|pay_status": FieldSpec("payment_status|pay_status", "refund_pending"),
                "return_reason|refund_reason": FieldSpec("return_reason|refund_reason", "defective_product"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Customer reported defective item. Return label sent."),
                "amount|total|order_total": FieldSpec("amount|total|order_total",
                    lambda: round(random.uniform(50, 300), 2)),
            },
            weight=0.8,
            is_edge_case=True,
            edge_case_type="error_condition",
            tags=["returned", "defective", "edge_case"],
        ),
        ScenarioTemplate(
            name="order_cancelled_by_customer",
            domain="ecommerce", category="happy_path",
            description="Order cancelled before fulfillment",
            fields={
                "status|state|order_status": FieldSpec("status|state|order_status", "cancelled"),
                "payment_status|pay_status": FieldSpec("payment_status|pay_status", "refunded"),
                "return_reason|refund_reason": FieldSpec("return_reason|refund_reason", "customer_request"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Cancelled by customer before shipment."),
                "amount|total|order_total": FieldSpec("amount|total|order_total",
                    lambda: round(random.uniform(10, 200), 2)),
            },
            weight=1.5,
            tags=["cancelled", "customer_request"],
        ),
        ScenarioTemplate(
            name="order_payment_failed",
            domain="ecommerce", category="edge_case",
            description="Order not processed due to payment failure",
            fields={
                "status|state|order_status": FieldSpec("status|state|order_status", "payment_failed"),
                "payment_status|pay_status": FieldSpec("payment_status|pay_status", "failed"),
                "return_reason|refund_reason": FieldSpec("return_reason|refund_reason", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Payment declined. Customer notified to update payment method."),
                "amount|total|order_total": FieldSpec("amount|total|order_total",
                    lambda: round(random.uniform(100, 2000), 2)),
            },
            weight=0.7,
            is_edge_case=True,
            edge_case_type="error_condition",
            tags=["payment_failed", "edge_case"],
        ),
    ]


def _build_devops_templates() -> list[ScenarioTemplate]:
    """Build devops domain templates."""
    return [
        ScenarioTemplate(
            name="pipeline_success",
            domain="devops", category="happy_path",
            description="Successful pipeline execution",
            fields={
                "status|state|pipeline_status": FieldSpec("status|state|pipeline_status", "success"),
                "error_message|err_msg": FieldSpec("error_message|err_msg", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Build and all tests passed. Deployed to staging."),
                "duration|elapsed|execution_time": FieldSpec("duration|elapsed|execution_time",
                    lambda: random.randint(30, 300)),
                "exit_code|return_code": FieldSpec("exit_code|return_code", 0),
            },
            weight=3.0,
            tags=["success", "pipeline", "common"],
        ),
        ScenarioTemplate(
            name="pipeline_failed_tests",
            domain="devops", category="happy_path",
            description="Pipeline failed due to test failures",
            fields={
                "status|state|pipeline_status": FieldSpec("status|state|pipeline_status", "failed"),
                "error_message|err_msg": FieldSpec("error_message|err_msg",
                    "AssertionError: Expected 200, got 500 in test_api_health"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Unit tests failed — 3 assertions broken after merge."),
                "duration|elapsed|execution_time": FieldSpec("duration|elapsed|execution_time",
                    lambda: random.randint(60, 180)),
                "exit_code|return_code": FieldSpec("exit_code|return_code", 1),
            },
            weight=2.0,
            tags=["failed", "tests", "pipeline"],
        ),
        ScenarioTemplate(
            name="deployment_rollback",
            domain="devops", category="edge_case",
            description="Deployment rolled back after health check failure",
            fields={
                "status|state|pipeline_status": FieldSpec("status|state|pipeline_status", "rolled_back"),
                "error_message|err_msg": FieldSpec("error_message|err_msg",
                    "HealthCheckTimeout: Service /health did not respond within 30s"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Health check failed post-deploy. Automatic rollback triggered."),
                "duration|elapsed|execution_time": FieldSpec("duration|elapsed|execution_time",
                    lambda: random.randint(30, 90)),
                "exit_code|return_code": FieldSpec("exit_code|return_code", 2),
            },
            weight=0.6,
            is_edge_case=True,
            edge_case_type="error_condition",
            tags=["rollback", "deployment", "edge_case"],
        ),
        ScenarioTemplate(
            name="scan_vulnerabilities_critical",
            domain="devops", category="edge_case",
            description="Security scan found critical vulnerabilities",
            fields={
                "status|state|pipeline_status": FieldSpec("status|state|pipeline_status", "completed_with_findings"),
                "error_message|err_msg": FieldSpec("error_message|err_msg", None),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Security scan completed. Critical CVEs identified."),
                "duration|elapsed|execution_time": FieldSpec("duration|elapsed|execution_time",
                    lambda: random.randint(120, 600)),
                "vulns_critical|critical_count": FieldSpec("vulns_critical|critical_count",
                    lambda: random.randint(1, 8)),
            },
            weight=0.5,
            is_edge_case=True,
            edge_case_type="rare_event",
            tags=["scan", "vulnerabilities", "security", "edge_case"],
        ),
    ]


def _build_general_templates() -> list[ScenarioTemplate]:
    """Build domain-agnostic general templates."""
    return [
        ScenarioTemplate(
            name="general_active_record",
            domain="general", category="happy_path",
            description="Standard active record",
            fields={
                "status|state": FieldSpec("status|state", "active"),
                "is_active|active": FieldSpec("is_active|active", True),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Record active and in good standing."),
            },
            weight=2.5,
            tags=["active", "standard"],
        ),
        ScenarioTemplate(
            name="general_pending_review",
            domain="general", category="happy_path",
            description="Record pending review",
            fields={
                "status|state": FieldSpec("status|state", "pending"),
                "is_active|active": FieldSpec("is_active|active", True),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Awaiting review by assigned team."),
            },
            weight=1.5,
            tags=["pending", "review"],
        ),
        ScenarioTemplate(
            name="general_completed",
            domain="general", category="happy_path",
            description="Completed/closed record",
            fields={
                "status|state": FieldSpec("status|state", "completed"),
                "is_active|active": FieldSpec("is_active|active", False),
                "is_closed|completed": FieldSpec("is_closed|completed", True),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "All steps completed successfully."),
            },
            weight=2.0,
            tags=["completed", "closed"],
        ),
        ScenarioTemplate(
            name="general_rejected",
            domain="general", category="edge_case",
            description="Record rejected",
            fields={
                "status|state": FieldSpec("status|state", "rejected"),
                "is_active|active": FieldSpec("is_active|active", False),
                "reason|rejection_reason": FieldSpec("reason|rejection_reason", "criteria_not_met"),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Rejected — does not meet acceptance criteria."),
            },
            weight=0.8,
            is_edge_case=True,
            tags=["rejected", "edge_case"],
        ),
        ScenarioTemplate(
            name="general_error_state",
            domain="general", category="edge_case",
            description="Record in error state",
            fields={
                "status|state": FieldSpec("status|state", "error"),
                "is_active|active": FieldSpec("is_active|active", False),
                "error_message|err_msg": FieldSpec("error_message|err_msg",
                    "Processing error encountered. Manual intervention required."),
                "notes|comment|remarks": FieldSpec("notes|comment|remarks",
                    "Error during processing. Escalated to support."),
            },
            weight=0.4,
            is_edge_case=True,
            edge_case_type="error_condition",
            tags=["error", "edge_case"],
        ),
    ]


# ═══════════════════════════════════════════════════════════════
# GLOBAL DEFAULT REGISTRY
# ═══════════════════════════════════════════════════════════════


def build_default_registry() -> TemplateRegistry:
    """Build the default registry with all built-in templates."""
    registry = TemplateRegistry()
    registry.register_many(_build_insurance_templates())
    registry.register_many(_build_banking_templates())
    registry.register_many(_build_healthcare_templates())
    registry.register_many(_build_hr_templates())
    registry.register_many(_build_ecommerce_templates())
    registry.register_many(_build_devops_templates())
    registry.register_many(_build_general_templates())
    return registry


# Module-level singleton (lazily built)
_default_registry: TemplateRegistry | None = None


def get_default_registry() -> TemplateRegistry:
    """Get the global default template registry (lazy singleton)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE PUBLIC API
# ═══════════════════════════════════════════════════════════════


def generate_scenario_rows_from_templates(
    table_name: str,
    column_names: list[str],
    n: int,
    domain: str | None = None,
    category_weights: dict[str, float] | None = None,
    include_edge_cases: bool = True,
    edge_case_ratio: float = 0.15,
    check_constraints: dict[str, list[str] | None] | None = None,
    registry: TemplateRegistry | None = None,
) -> TemplateGenerationResult:
    """Generate n scenario-driven rows using the template registry.

    This is the main entry point for the generation pipeline.
    Each row is tagged with _scenario_template for traceability.
    """
    reg = registry or get_default_registry()
    return generate_from_templates(
        table_name=table_name,
        column_names=column_names,
        n=n,
        registry=reg,
        domain=domain,
        category_weights=category_weights,
        include_edge_cases=include_edge_cases,
        edge_case_ratio=edge_case_ratio,
        check_constraints=check_constraints,
    )


def list_available_templates(
    domain: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """List available templates with optional filtering."""
    reg = get_default_registry()

    if tag:
        templates = reg.list_by_tag(tag)
    elif category:
        templates = reg.list_by_category(category)
    elif domain:
        templates = reg.list_by_domain(domain)
    else:
        templates = reg.list_all()

    # Group by domain
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for t in templates:
        by_domain.setdefault(t.domain, []).append(t.to_dict())

    return {
        "total_templates": len(templates),
        "domains": list(by_domain.keys()),
        "templates": by_domain,
    }


def register_custom_template(
    name: str,
    domain: str,
    category: str,
    description: str,
    fields: dict[str, Any],
    weight: float = 1.0,
    parent: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Register a custom user-defined template at runtime.

    Args:
        name: Unique template name.
        domain: Business domain.
        category: happy_path, edge_case, boundary, or invalid.
        description: Human-readable description.
        fields: Dict of field_pattern → value (static values only for API).
        weight: Probability weight.
        parent: Optional parent template name for inheritance.
        tags: Optional searchable tags.

    Returns:
        Confirmation dict with template metadata.
    """
    reg = get_default_registry()

    # Convert simple field dict to FieldSpec objects
    field_specs: dict[str, FieldSpec] = {}
    for pattern, value in fields.items():
        field_specs[pattern] = FieldSpec(pattern=pattern, value=value)

    template = ScenarioTemplate(
        name=name,
        domain=domain,
        category=category,
        description=description,
        fields=field_specs,
        weight=weight,
        parent=parent,
        tags=tags or [],
        is_edge_case=category in ("edge_case", "boundary"),
        edge_case_type="custom" if category in ("edge_case", "boundary") else None,
    )

    reg.register(template)
    return template.to_dict()
