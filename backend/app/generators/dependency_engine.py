"""Column Interdependency Detection Engine.

Identifies columns whose values semantically depend on each other within
a table — producing a dependency graph with confidence scoring and
relationship metadata.

Examples detected:
  status ↔ comments (state drives explanation)
  first_name ↔ email (identity coherence)
  country ↔ phone_code (geographic constraint)
  approval_status ↔ rejection_reason (conditional presence)
"""

from __future__ import annotations

import re
from typing import Any

from app.generators.context_inference import _infer_domain
from app.models.schema import ColumnMetadata, TableMetadata


# ── Dependency rule definitions ───────────────────────────────
# Each rule: (source_pattern, target_pattern, relationship_type, base_confidence, direction)
# direction: "bidirectional" or "source_drives_target"

_DEPENDENCY_RULES: list[tuple[re.Pattern, re.Pattern, str, float, str]] = [
    # Status / state → explanation fields
    (re.compile(r"^status$|_status$|^state$|_state$|^decision$", re.I),
     re.compile(r"notes?$|comments?$|remarks?$|observation", re.I),
     "state_drives_explanation", 0.94, "source_drives_target"),

    # Approval/decision status → reason
    (re.compile(r"status|decision|verdict|outcome", re.I),
     re.compile(r"reason$|_reason$|justification|rationale", re.I),
     "decision_drives_justification", 0.92, "source_drives_target"),

    # Status → conditional fields (denial_reason only present when denied)
    (re.compile(r"^status$|_status$|^decision$|approval", re.I),
     re.compile(r"denial_reason|reject_reason|decline_reason", re.I),
     "conditional_presence", 0.96, "source_drives_target"),

    # Person name components → email
    (re.compile(r"first_name|last_name|full_name|^name$", re.I),
     re.compile(r"email|e_mail", re.I),
     "identity_coherence", 0.91, "bidirectional"),

    # First name ↔ last name (identity pair)
    (re.compile(r"first_name|given_name|fname", re.I),
     re.compile(r"last_name|surname|family_name|lname", re.I),
     "identity_pair", 0.88, "bidirectional"),

    # Country/region → phone format
    (re.compile(r"country|nation|region", re.I),
     re.compile(r"phone|mobile|telephone|contact_number", re.I),
     "geographic_constraint", 0.85, "source_drives_target"),

    # Country → postal/zip format
    (re.compile(r"country|nation", re.I),
     re.compile(r"postal_code|zip_code|pincode", re.I),
     "geographic_constraint", 0.87, "source_drives_target"),

    # Country → state/province
    (re.compile(r"country|nation", re.I),
     re.compile(r"^state$|province|region", re.I),
     "geographic_hierarchy", 0.90, "source_drives_target"),

    # State → city
    (re.compile(r"^state$|province|region", re.I),
     re.compile(r"^city$|city_name", re.I),
     "geographic_hierarchy", 0.88, "source_drives_target"),

    # Policy status → claim eligibility
    (re.compile(r"policy_status|policy_state", re.I),
     re.compile(r"claim_status|claim_state|claim_eligible", re.I),
     "business_constraint", 0.89, "source_drives_target"),

    # Org fields: org_id ↔ org_name
    (re.compile(r"org_id|organization_id|company_id", re.I),
     re.compile(r"org_name|organization_name|company_name", re.I),
     "entity_identity", 0.97, "bidirectional"),

    # Project: project_id ↔ project_name
    (re.compile(r"project_id", re.I),
     re.compile(r"project_name", re.I),
     "entity_identity", 0.97, "bidirectional"),

    # Amount → currency
    (re.compile(r"amount|total|price|cost|fee|balance", re.I),
     re.compile(r"currency|currency_code", re.I),
     "monetary_qualifier", 0.83, "bidirectional"),

    # Date fields temporal ordering (created < updated)
    (re.compile(r"created_at|creation_date|start_date|opened_at", re.I),
     re.compile(r"updated_at|modified_at|end_date|closed_at|completed_at", re.I),
     "temporal_ordering", 0.92, "source_drives_target"),

    # Submitted date → review date → decision date
    (re.compile(r"submit|submission|filed", re.I),
     re.compile(r"review_date|reviewed_at", re.I),
     "temporal_ordering", 0.90, "source_drives_target"),

    # Escalated flag → escalation fields
    (re.compile(r"escalated|is_escalated", re.I),
     re.compile(r"escalation_reason|escalated_to|escalation_date", re.I),
     "conditional_presence", 0.93, "source_drives_target"),

    # Boolean flags → conditional detail
    (re.compile(r"^is_|^has_|^can_|^allow", re.I),
     re.compile(r"_reason$|_detail$|_description$", re.I),
     "flag_drives_detail", 0.78, "source_drives_target"),

    # Payment method → reference format
    (re.compile(r"payment_method|pay_method|payment_type", re.I),
     re.compile(r"reference_number|ref_number|transaction_ref|cheque_number", re.I),
     "method_drives_format", 0.86, "source_drives_target"),

    # Actor (_by) → timestamp (_at/_date for same action)
    (re.compile(r"(reviewed|approved|created|updated|assigned|processed)_by", re.I),
     re.compile(r"(review|approval|creation|update|assignment|process)_(date|at|time)", re.I),
     "action_timestamp_pair", 0.91, "bidirectional"),

    # Quantity → unit
    (re.compile(r"quantity|qty|dosage|dose", re.I),
     re.compile(r"unit|uom|measure", re.I),
     "quantity_unit_pair", 0.84, "bidirectional"),

    # Before/after pairs (same prefix)
    (re.compile(r"_before$|_old$|_previous$", re.I),
     re.compile(r"_after$|_new$|_current$", re.I),
     "delta_pair", 0.95, "bidirectional"),
]

# ── Suffix-based actor+timestamp pairing ──────────────────────
# Detects patterns like reviewed_by + review_date even without explicit regex

_ACTOR_SUFFIXES = ("_by",)
_TIMESTAMP_SUFFIXES = ("_date", "_at", "_time", "_on")


def _detect_actor_timestamp_pairs(
    columns: list[str],
) -> list[dict[str, Any]]:
    """Detect actor+timestamp pairs by matching shared action prefixes."""
    deps: list[dict[str, Any]] = []
    actor_cols = {}
    for col in columns:
        col_lower = col.lower()
        for suffix in _ACTOR_SUFFIXES:
            if col_lower.endswith(suffix):
                prefix = col_lower[: -len(suffix)]
                actor_cols[prefix] = col

    for col in columns:
        col_lower = col.lower()
        for suffix in _TIMESTAMP_SUFFIXES:
            if col_lower.endswith(suffix):
                prefix = col_lower[: -len(suffix)]
                if prefix in actor_cols:
                    deps.append({
                        "source": actor_cols[prefix],
                        "target": col,
                        "relationship": "action_timestamp_pair",
                        "direction": "bidirectional",
                        "confidence": 0.91,
                        "reasoning": f"Actor '{actor_cols[prefix]}' and timestamp '{col}' share action prefix '{prefix}'",
                    })
    return deps


# ── Before/after delta detection ──────────────────────────────

_BEFORE_SUFFIXES = ("_before", "_old", "_previous", "_start")
_AFTER_SUFFIXES = ("_after", "_new", "_current", "_end")


def _detect_delta_pairs(columns: list[str]) -> list[dict[str, Any]]:
    """Detect before/after column pairs sharing a common base."""
    deps: list[dict[str, Any]] = []
    before_map: dict[str, str] = {}

    for col in columns:
        col_lower = col.lower()
        for suffix in _BEFORE_SUFFIXES:
            if col_lower.endswith(suffix):
                base = col_lower[: -len(suffix)]
                before_map[base] = col

    for col in columns:
        col_lower = col.lower()
        for suffix in _AFTER_SUFFIXES:
            if col_lower.endswith(suffix):
                base = col_lower[: -len(suffix)]
                if base in before_map:
                    deps.append({
                        "source": before_map[base],
                        "target": col,
                        "relationship": "delta_pair",
                        "direction": "bidirectional",
                        "confidence": 0.95,
                        "reasoning": f"Before/after pair for metric '{base}'",
                    })
    return deps


# ── Domain-specific boost ─────────────────────────────────────

_DOMAIN_BOOSTS: dict[str, dict[str, float]] = {
    "insurance": {
        "conditional_presence": 0.03,
        "decision_drives_justification": 0.03,
        "business_constraint": 0.04,
    },
    "banking": {
        "monetary_qualifier": 0.04,
        "geographic_constraint": 0.03,
    },
    "healthcare": {
        "quantity_unit_pair": 0.04,
    },
}


# ── Public API ────────────────────────────────────────────────


class ColumnDependency:
    """A single detected dependency between two columns."""

    __slots__ = ("source", "target", "relationship", "direction", "confidence", "reasoning")

    def __init__(
        self,
        source: str,
        target: str,
        relationship: str,
        direction: str,
        confidence: float,
        reasoning: str,
    ):
        self.source = source
        self.target = target
        self.relationship = relationship
        self.direction = direction
        self.confidence = min(confidence, 1.0)
        self.reasoning = reasoning

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship,
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "reasoning": self.reasoning,
        }


def detect_dependencies(table: TableMetadata) -> list[dict[str, Any]]:
    """Detect column interdependencies within a table.

    Returns a list of dependency edges with confidence scores.
    """
    domain = _infer_domain(table.name)
    col_names = [c.name for c in table.columns]
    col_lowers = {c.name: c.name.lower() for c in table.columns}
    domain_boost = _DOMAIN_BOOSTS.get(domain, {})

    dependencies: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    # Rule-based detection
    for src_pat, tgt_pat, rel_type, base_conf, direction in _DEPENDENCY_RULES:
        for src_col, src_lower in col_lowers.items():
            if not src_pat.search(src_lower):
                continue
            for tgt_col, tgt_lower in col_lowers.items():
                if src_col == tgt_col:
                    continue
                if not tgt_pat.search(tgt_lower):
                    continue

                # Avoid duplicate pairs
                pair_key = (min(src_col, tgt_col), max(src_col, tgt_col))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Apply domain boost
                confidence = base_conf + domain_boost.get(rel_type, 0.0)

                dependencies.append(ColumnDependency(
                    source=src_col,
                    target=tgt_col,
                    relationship=rel_type,
                    direction=direction,
                    confidence=confidence,
                    reasoning=_build_reasoning(src_col, tgt_col, rel_type, domain),
                ).to_dict())

    # Actor+timestamp pair detection (structural)
    for dep in _detect_actor_timestamp_pairs(col_names):
        pair_key = (min(dep["source"], dep["target"]), max(dep["source"], dep["target"]))
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            dependencies.append(dep)

    # Delta pair detection (before/after)
    for dep in _detect_delta_pairs(col_names):
        pair_key = (min(dep["source"], dep["target"]), max(dep["source"], dep["target"]))
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            dependencies.append(dep)

    # FK-implied dependencies (cross-table, noted for completeness)
    for fk in table.foreign_keys:
        # FK columns depend on the referenced table's state
        for col in col_names:
            if col == fk.column:
                continue
            col_lower = col.lower()
            ref_table_lower = fk.references_table.lower()
            # If a column name contains the referenced entity, it's likely dependent
            if ref_table_lower.replace("_", "") in col_lower.replace("_", ""):
                pair_key = (min(fk.column, col), max(fk.column, col))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    dependencies.append({
                        "source": fk.column,
                        "target": col,
                        "relationship": "fk_implied_dependency",
                        "direction": "source_drives_target",
                        "confidence": 0.80,
                        "reasoning": f"FK '{fk.column}' references {fk.references_table}; "
                                     f"'{col}' likely derived from same entity",
                    })

    # Sort by confidence descending
    dependencies.sort(key=lambda d: d["confidence"], reverse=True)
    return dependencies


def detect_schema_dependencies(
    tables: list[TableMetadata],
) -> dict[str, list[dict[str, Any]]]:
    """Detect dependencies across all tables in the schema."""
    return {table.name: detect_dependencies(table) for table in tables}


def _build_reasoning(source: str, target: str, rel_type: str, domain: str) -> str:
    """Generate a human-readable reasoning string for the dependency."""
    _REASONING_TEMPLATES: dict[str, str] = {
        "state_drives_explanation": "'{source}' determines workflow state; '{target}' explains why",
        "decision_drives_justification": "'{source}' captures decision outcome; '{target}' provides justification",
        "conditional_presence": "'{target}' is only meaningful when '{source}' has specific values",
        "identity_coherence": "'{source}' and '{target}' must reflect the same person's identity",
        "identity_pair": "'{source}' and '{target}' form a person's complete name",
        "geographic_constraint": "'{source}' determines valid format/values for '{target}'",
        "geographic_hierarchy": "'{source}' constrains valid values for '{target}'",
        "entity_identity": "'{source}' and '{target}' represent the same entity's ID and label",
        "monetary_qualifier": "'{source}' and '{target}' form a complete monetary value",
        "temporal_ordering": "'{source}' must precede '{target}' chronologically",
        "flag_drives_detail": "Boolean '{source}' determines whether '{target}' is populated",
        "method_drives_format": "'{source}' determines the format/type of '{target}'",
        "action_timestamp_pair": "'{source}' and '{target}' record who did something and when",
        "quantity_unit_pair": "'{source}' and '{target}' form a complete measurement",
        "delta_pair": "'{source}' and '{target}' represent before/after values of the same metric",
        "business_constraint": "Business rule links '{source}' state to '{target}' eligibility",
    }

    template = _REASONING_TEMPLATES.get(rel_type, "'{source}' and '{target}' are semantically related")
    reasoning = template.format(source=source, target=target)
    if domain != "general":
        reasoning += f" ({domain} domain)"
    return reasoning
