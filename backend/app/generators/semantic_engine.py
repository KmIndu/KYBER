"""Semantic Column Understanding Engine.

Analyzes columns to determine their business meaning, workflow relevance,
entity role, and contextual relationships — returning structured metadata
that downstream systems use for intelligent data generation.
"""

from __future__ import annotations

import re
from typing import Any

from app.generators.context_inference import _infer_domain, _JARGON
from app.generators.semantic_types import SemanticType, detect_semantic_type
from app.models.schema import ColumnMetadata, ForeignKeyMetadata, TableMetadata


# ── Semantic type → business role mapping ─────────────────────

_SEMANTIC_TO_BUSINESS_ROLE: dict[str, str] = {
    # Identity fields
    "first_name": "identity_field",
    "last_name": "identity_field",
    "full_name": "identity_field",
    "email": "identity_field",
    "phone": "contact_field",
    "mobile": "contact_field",
    "ssn": "identity_field",
    "passport": "identity_field",
    "national_id": "identity_field",
    "pan": "identity_field",
    "username": "identity_field",

    # Workflow / state
    "status": "state_machine_field",

    # Temporal
    "timestamp": "audit_field",
    "created_at": "audit_field",
    "updated_at": "audit_field",
    "date": "temporal_field",
    "time": "temporal_field",
    "date_of_birth": "demographic_field",

    # Financial
    "amount": "monetary_field",
    "currency": "monetary_qualifier",
    "premium_amount": "monetary_field",
    "coverage_amount": "monetary_field",
    "account_number": "financial_identifier",
    "iban": "financial_identifier",
    "swift_code": "financial_identifier",
    "routing_number": "financial_identifier",
    "credit_card": "financial_identifier",

    # Insurance
    "policy_id": "business_identifier",
    "claim_number": "business_identifier",

    # Healthcare
    "patient_id": "business_identifier",
    "diagnosis_code": "clinical_classifier",
    "medication_name": "clinical_entity",
    "dosage": "clinical_qualifier",

    # Retail
    "sku": "product_identifier",
    "barcode": "product_identifier",
    "product_name": "product_entity",

    # Address / Location
    "street_address": "location_field",
    "city": "location_field",
    "state": "location_field",
    "country": "location_field",
    "postal_code": "location_field",
    "full_address": "location_field",

    # Descriptive
    "description": "explanation_field",

    # DevOps
    "git_branch": "technical_reference",
    "git_repo_url": "technical_reference",
    "hostname": "technical_reference",
    "version": "technical_qualifier",
    "error_message": "diagnostic_field",
    "error_code": "diagnostic_field",
    "service_name": "system_entity",
    "ip_address": "technical_reference",
    "url": "technical_reference",

    # Demographics
    "gender": "demographic_field",
    "age": "demographic_field",
    "company": "organizational_entity",

    # Fallback
    "uuid": "surrogate_key",
    "unknown": "unclassified",
}

# ── Entity role classification ────────────────────────────────

_ENTITY_ROLES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"_id$|^id$", re.I), "primary_entity_key"),
    (re.compile(r"_fk$|references_", re.I), "foreign_reference"),
    (re.compile(r"created_at|created_on|creation_date", re.I), "creation_timestamp"),
    (re.compile(r"updated_at|modified_at|last_updated", re.I), "modification_timestamp"),
    (re.compile(r"(created|updated|modified|approved|reviewed|assigned)_by", re.I), "actor_reference"),
    (re.compile(r"^is_|^has_|^can_|^allow", re.I), "boolean_flag"),
    (re.compile(r"_count$|_total$|_qty$|_num$", re.I), "aggregate_metric"),
    (re.compile(r"_date$|_time$|_at$|_on$", re.I), "temporal_marker"),
    (re.compile(r"_amount$|_price$|_cost$|_fee$|_balance$", re.I), "monetary_value"),
    (re.compile(r"_name$|_title$|_label$", re.I), "descriptive_label"),
    (re.compile(r"_type$|_kind$|_category$|_class$", re.I), "classification_attribute"),
    (re.compile(r"_status$|^status$|^state$|_state$", re.I), "workflow_state"),
    (re.compile(r"_code$|_key$", re.I), "coded_value"),
    (re.compile(r"notes?$|comments?$|remarks?$|description$", re.I), "free_text"),
    (re.compile(r"_url$|_link$|_uri$|_path$", re.I), "resource_locator"),
    (re.compile(r"_flag$|_indicator$|^enabled$|^active$", re.I), "boolean_flag"),
    (re.compile(r"_percentage$|_percent$|_rate$|_ratio$", re.I), "ratio_metric"),
]

# ── Workflow relevance classification ─────────────────────────

_WORKFLOW_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^status$|_status$|^state$|_state$|^decision$", re.I), "state_transition"),
    (re.compile(r"approved|rejected|denied|pending|escalated", re.I), "approval_gate"),
    (re.compile(r"created_at|submitted_at|opened_at", re.I), "lifecycle_start"),
    (re.compile(r"closed_at|completed_at|resolved_at|paid_at", re.I), "lifecycle_end"),
    (re.compile(r"(assigned|reviewed|approved|processed)_by", re.I), "human_action"),
    (re.compile(r"priority|severity|urgency", re.I), "prioritization"),
    (re.compile(r"due_date|deadline|sla|expiry", re.I), "time_constraint"),
    (re.compile(r"escalated|escalation", re.I), "escalation_trigger"),
    (re.compile(r"reason|justification|rationale", re.I), "decision_support"),
    (re.compile(r"result|outcome|verdict|decision", re.I), "decision_output"),
]

# ── Contextual relationships ──────────────────────────────────

_RELATIONSHIP_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (pattern on col_name, relationship_type, related_concept)
    (re.compile(r"customer_id|client_id|member_id", re.I), "belongs_to", "customer"),
    (re.compile(r"policy_id|policy_number", re.I), "belongs_to", "policy"),
    (re.compile(r"claim_id|claim_number", re.I), "belongs_to", "claim"),
    (re.compile(r"order_id|order_number", re.I), "belongs_to", "order"),
    (re.compile(r"account_id|account_number", re.I), "belongs_to", "account"),
    (re.compile(r"patient_id", re.I), "belongs_to", "patient"),
    (re.compile(r"employee_id|emp_id", re.I), "belongs_to", "employee"),
    (re.compile(r"project_id", re.I), "belongs_to", "project"),
    (re.compile(r"transaction_id|txn_id", re.I), "belongs_to", "transaction"),
    (re.compile(r"payment_id", re.I), "belongs_to", "payment"),
    (re.compile(r"_amount$|_total$|_price$", re.I), "quantifies", "monetary_value"),
    (re.compile(r"_date$|_time$|_at$", re.I), "timestamps", "event"),
    (re.compile(r"_by$", re.I), "performed_by", "actor"),
    (re.compile(r"_reason$|_notes?$|_comments?$", re.I), "explains", "decision"),
]


# ── Public API ────────────────────────────────────────────────


class ColumnSemantics:
    """Structured semantic metadata for a single column."""

    __slots__ = (
        "column",
        "semantic_type",
        "business_role",
        "entity_role",
        "workflow_relevance",
        "contextual_relationships",
        "inferred_domain",
        "resolved_meaning",
    )

    def __init__(
        self,
        column: str,
        semantic_type: str,
        business_role: str,
        entity_role: str,
        workflow_relevance: str | None,
        contextual_relationships: list[dict[str, str]],
        inferred_domain: str,
        resolved_meaning: str,
    ):
        self.column = column
        self.semantic_type = semantic_type
        self.business_role = business_role
        self.entity_role = entity_role
        self.workflow_relevance = workflow_relevance
        self.contextual_relationships = contextual_relationships
        self.inferred_domain = inferred_domain
        self.resolved_meaning = resolved_meaning

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "column": self.column,
            "semantic_type": self.semantic_type,
            "business_role": self.business_role,
            "entity_role": self.entity_role,
            "workflow_relevance": self.workflow_relevance,
            "contextual_relationships": self.contextual_relationships,
            "inferred_domain": self.inferred_domain,
            "resolved_meaning": self.resolved_meaning,
        }
        return result


def _resolve_meaning(col_name: str, table_name: str) -> str:
    """Produce a human-readable meaning summary from column + table context."""
    col_lower = col_name.lower()
    tbl_lower = table_name.lower()

    # Expand jargon tokens
    tokens = re.split(r"[_\s]+", col_lower)
    expanded = []
    for t in tokens:
        if t in _JARGON:
            expanded.append(_JARGON[t])
        else:
            expanded.append(t)

    meaning_parts = []

    # Detect entity key
    if col_lower.endswith("_id") or col_lower == "id":
        entity = col_lower.replace("_id", "") or tbl_lower
        meaning_parts.append(f"unique identifier for {entity}")
    elif col_lower.endswith("_by"):
        action = col_lower.replace("_by", "")
        meaning_parts.append(f"person/system that {action} the record")
    elif col_lower.endswith("_at") or col_lower.endswith("_date") or col_lower.endswith("_on"):
        event = col_lower.replace("_at", "").replace("_date", "").replace("_on", "")
        meaning_parts.append(f"timestamp when {event} occurred")
    elif col_lower.endswith("_amount") or col_lower.endswith("_total"):
        subject = col_lower.replace("_amount", "").replace("_total", "")
        meaning_parts.append(f"monetary value of {subject}")
    elif col_lower.endswith("_count") or col_lower.endswith("_num"):
        subject = col_lower.replace("_count", "").replace("_num", "")
        meaning_parts.append(f"count of {subject}")
    elif col_lower.endswith("_name"):
        entity = col_lower.replace("_name", "")
        meaning_parts.append(f"display name of {entity}")
    elif col_lower.endswith("_type") or col_lower.endswith("_category"):
        subject = col_lower.replace("_type", "").replace("_category", "")
        meaning_parts.append(f"classification category for {subject}")
    elif col_lower.endswith("_status") or col_lower == "status":
        meaning_parts.append(f"current workflow state of {tbl_lower}")
    elif col_lower.endswith("_reason") or col_lower == "reason":
        meaning_parts.append(f"justification or explanation for a decision")
    elif col_lower.endswith("_number") or col_lower.endswith("_no") or col_lower.endswith("_ref"):
        entity = col_lower.replace("_number", "").replace("_no", "").replace("_ref", "")
        meaning_parts.append(f"reference number for {entity}")
    else:
        meaning_parts.append(" ".join(expanded))

    # Add table context
    domain = _infer_domain(table_name)
    if domain != "general":
        meaning_parts.append(f"in {domain} context")

    return "; ".join(meaning_parts)


def _classify_entity_role(col_name: str, is_pk: bool, is_fk: bool) -> str:
    """Determine the entity role of a column."""
    if is_pk:
        return "primary_entity_key"
    if is_fk:
        return "foreign_reference"

    for pattern, role in _ENTITY_ROLES:
        if pattern.search(col_name):
            return role
    return "data_attribute"


def _classify_workflow_relevance(col_name: str) -> str | None:
    """Determine if/how a column participates in workflow."""
    for pattern, relevance in _WORKFLOW_PATTERNS:
        if pattern.search(col_name):
            return relevance
    return None


def _find_contextual_relationships(
    col_name: str, fk_refs: list[ForeignKeyMetadata]
) -> list[dict[str, str]]:
    """Identify contextual relationships for a column."""
    relationships: list[dict[str, str]] = []

    # Explicit FK relationship
    for fk in fk_refs:
        if fk.column == col_name:
            relationships.append({
                "type": "references",
                "target": f"{fk.references_table}.{fk.references_column}",
            })

    # Pattern-based implicit relationships
    for pattern, rel_type, concept in _RELATIONSHIP_PATTERNS:
        if pattern.search(col_name):
            relationships.append({
                "type": rel_type,
                "target": concept,
            })
            break  # one implicit match is enough

    return relationships


def _infer_domain_from_columns(table: TableMetadata) -> str:
    """Fallback domain inference using column names when table name is generic."""
    col_text = " ".join(c.name.lower() for c in table.columns)
    domain = _infer_domain(col_text)
    return domain


def analyze_column(
    col: ColumnMetadata,
    table: TableMetadata,
    table_domain: str | None = None,
) -> ColumnSemantics:
    """Analyze a single column and return its semantic metadata."""
    domain = table_domain or _infer_domain(table.name)
    if domain == "general":
        # Fallback: infer from column names in the table
        domain = _infer_domain_from_columns(table)

    # Detect semantic type using existing engine
    sem_type = detect_semantic_type(col.name, domain=domain)
    sem_type_str = sem_type.value if sem_type != SemanticType.UNKNOWN else "unknown"

    # Business role
    business_role = _SEMANTIC_TO_BUSINESS_ROLE.get(sem_type_str, "data_attribute")

    # Entity role
    is_pk = col.name in table.primary_keys
    fk_cols = {fk.column for fk in table.foreign_keys}
    is_fk = col.name in fk_cols
    entity_role = _classify_entity_role(col.name, is_pk, is_fk)

    # Workflow relevance
    workflow_relevance = _classify_workflow_relevance(col.name)

    # Contextual relationships
    ctx_rels = _find_contextual_relationships(col.name, table.foreign_keys)

    # Human-readable meaning
    resolved_meaning = _resolve_meaning(col.name, table.name)

    return ColumnSemantics(
        column=col.name,
        semantic_type=sem_type_str,
        business_role=business_role,
        entity_role=entity_role,
        workflow_relevance=workflow_relevance,
        contextual_relationships=ctx_rels,
        inferred_domain=domain,
        resolved_meaning=resolved_meaning,
    )


def analyze_table(table: TableMetadata) -> list[dict[str, Any]]:
    """Analyze all columns in a table and return semantic metadata list."""
    # Compute domain once for the whole table
    domain = _infer_domain(table.name)
    if domain == "general":
        domain = _infer_domain_from_columns(table)

    results = []
    for col in table.columns:
        semantics = analyze_column(col, table, table_domain=domain)
        results.append(semantics.to_dict())
    return results


def analyze_schema(tables: list[TableMetadata]) -> dict[str, list[dict[str, Any]]]:
    """Analyze all tables and return a table_name → column_semantics mapping."""
    return {table.name: analyze_table(table) for table in tables}
