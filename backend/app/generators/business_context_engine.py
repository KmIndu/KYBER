"""Business Context Inference Engine.

Analyzes schema structure holistically to understand the business meaning
of entire tables before generation begins.  Returns rich context including:

- business domain (insurance, banking, healthcare, hr, ecommerce, devops)
- table purpose (transaction, master, lookup, audit, junction)
- lifecycle states (the workflow stages a record goes through)
- key workflows (the business processes the table supports)
- entity relationships (how tables relate to business entities)

This pre-generation analysis improves data quality by giving downstream
engines (identity, workflow, derivation, scenario) full business awareness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.schema import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata


# ── Domain keyword scoring ────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, dict[str, float]] = {
    "insurance": {
        "policy": 2.5, "premium": 2.5, "claim": 2.5, "coverage": 2.5,
        "underwriting": 3.0, "beneficiary": 2.0, "insured": 2.5,
        "policyholder": 3.0, "deductible": 2.5, "rider": 2.0,
        "endorsement": 2.0, "actuary": 3.0, "annuity": 3.0,
        "reinsurance": 3.0, "sum_assured": 3.0, "maturity": 2.0,
        "surrender": 2.0, "nominee": 2.5, "indemnity": 3.0,
        "peril": 2.0, "exclusion": 2.0, "copay": 2.0,
        "coinsurance": 3.0, "adjudication": 3.0, "loss_ratio": 3.0,
        "claimant": 3.0, "settlement": 2.0,
    },
    "banking": {
        "account": 1.5, "balance": 2.0, "transaction": 2.0, "transfer": 2.5,
        "deposit": 2.5, "withdrawal": 2.5, "ledger": 2.5, "loan": 2.0,
        "mortgage": 3.0, "interest_rate": 2.5, "credit": 1.5, "debit": 2.0,
        "atm": 3.0, "swift": 3.0, "iban": 3.0, "routing_number": 3.0,
        "overdraft": 3.0, "savings": 2.0, "checking": 3.0, "bank": 2.0,
        "kyc": 3.0, "aml": 3.0, "wire_transfer": 3.0,
        "collateral": 2.5, "escrow": 3.0, "remittance": 3.0,
    },
    "healthcare": {
        "patient": 2.5, "diagnosis": 3.0, "prescription": 3.0,
        "medication": 2.5, "physician": 2.5, "hospital": 2.0,
        "clinic": 2.0, "appointment": 2.0, "medical_record": 3.0,
        "icd": 3.0, "cpt": 3.0, "ehr": 3.0, "emr": 3.0,
        "lab_result": 3.0, "vital_signs": 3.0, "allergy": 2.0,
        "immunization": 2.5, "pharmacy": 2.0, "dosage": 2.5,
        "treatment": 2.0, "hipaa": 3.0, "discharge": 2.0,
        "triage": 3.0, "referral": 2.0,
    },
    "hr": {
        "employee": 2.5, "salary": 2.5, "department": 2.0, "hire_date": 3.0,
        "termination": 2.5, "payroll": 3.0, "benefits": 2.0, "leave": 2.0,
        "performance_review": 3.0, "onboarding": 3.0, "resignation": 3.0,
        "compensation": 2.5, "headcount": 3.0, "attendance": 2.0,
        "job_title": 2.0, "recruiter": 3.0, "candidate": 2.0,
        "promotion": 2.5, "appraisal": 3.0, "workforce": 2.5,
    },
    "ecommerce": {
        "product": 2.0, "cart": 3.0, "order": 2.0, "inventory": 2.5,
        "sku": 3.0, "catalog": 2.5, "price": 1.5, "discount": 2.0,
        "coupon": 3.0, "shipment": 2.5, "shipping": 2.0, "warehouse": 2.5,
        "checkout": 3.0, "wishlist": 3.0, "refund": 2.0,
        "supplier": 2.0, "purchase_order": 2.5, "barcode": 2.5,
        "shopping": 3.0, "merchandise": 3.0, "fulfillment": 3.0,
    },
    "devops": {
        "pipeline": 2.0, "deployment": 2.5, "container": 2.0, "kubernetes": 3.0,
        "docker": 3.0, "ci_cd": 3.0, "artifact": 2.0, "build": 1.5,
        "release": 2.0, "incident": 2.0, "alert": 2.0, "monitoring": 2.0,
        "scan": 2.0, "vulnerability": 2.5, "remediation": 2.5,
        "terraform": 3.0, "ansible": 3.0, "helm": 3.0,
        "sre": 3.0, "runbook": 3.0, "postmortem": 3.0,
    },
}

# ── Table purpose classification ──────────────────────────────

_TABLE_PURPOSE_PATTERNS: list[tuple[str, list[re.Pattern], float]] = [
    # Transaction tables: record business events
    ("transaction", [
        re.compile(r"claim|order|payment|transaction|transfer|invoice|receipt|shipment|booking", re.I),
    ], 0.9),
    # Audit / log tables
    ("audit_log", [
        re.compile(r"audit|log|history|event|changelog|trace|activity", re.I),
    ], 0.9),
    # Master / reference tables
    ("master_entity", [
        re.compile(r"customer|employee|patient|member|user|account|policy|product|vendor|supplier|provider|agent|client", re.I),
    ], 0.85),
    # Lookup / dimension tables
    ("lookup", [
        re.compile(r"type|category|status_code|lookup|reference|config|setting|code|country|currency|language", re.I),
    ], 0.8),
    # Junction / bridge tables
    ("junction", [
        re.compile(r"_x_|_link|_map|_bridge|_assoc|_rel", re.I),
    ], 0.85),
    # Verification / compliance
    ("verification", [
        re.compile(r"kyc|aml|verification|compliance|screening|identity_check", re.I),
    ], 0.9),
    # Queue / workflow staging
    ("workflow_queue", [
        re.compile(r"queue|task|job|workflow|work_item|assignment|approval", re.I),
    ], 0.85),
]

# ── Lifecycle state detection ─────────────────────────────────

_LIFECYCLE_INDICATORS: dict[str, dict[str, list[str]]] = {
    "insurance": {
        "claim": ["submitted", "under_review", "adjudicated", "approved", "denied", "settled", "closed", "reopened"],
        "policy": ["quoted", "applied", "underwritten", "issued", "active", "lapsed", "cancelled", "renewed", "expired"],
        "underwriting": ["received", "risk_assessed", "medical_review", "approved", "declined", "counter_offered"],
    },
    "banking": {
        "loan": ["applied", "credit_check", "approved", "disbursed", "repaying", "defaulted", "closed", "written_off"],
        "transaction": ["initiated", "pending", "authorized", "settled", "reversed", "failed"],
        "kyc": ["submitted", "document_review", "verified", "rejected", "expired", "re_verification"],
        "account": ["opened", "active", "dormant", "frozen", "closed"],
    },
    "healthcare": {
        "appointment": ["scheduled", "checked_in", "in_progress", "completed", "no_show", "cancelled"],
        "claim": ["submitted", "pre_authorization", "adjudicated", "paid", "denied", "appealed"],
        "patient": ["registered", "admitted", "in_treatment", "discharged", "follow_up"],
        "referral": ["requested", "approved", "scheduled", "completed", "expired"],
    },
    "hr": {
        "employee": ["hired", "onboarding", "active", "on_leave", "probation", "terminated", "retired"],
        "recruitment": ["applied", "screening", "interview", "offered", "accepted", "rejected", "withdrawn"],
        "leave": ["requested", "approved", "rejected", "in_progress", "completed", "cancelled"],
        "performance": ["self_assessment", "manager_review", "calibration", "finalized", "acknowledged"],
    },
    "ecommerce": {
        "order": ["placed", "confirmed", "processing", "shipped", "delivered", "returned", "refunded", "cancelled"],
        "payment": ["initiated", "authorized", "captured", "settled", "refunded", "chargebacked", "failed"],
        "return": ["requested", "approved", "received", "inspected", "refunded", "rejected"],
        "shipment": ["created", "picked", "packed", "shipped", "in_transit", "delivered", "failed_delivery"],
    },
    "devops": {
        "deployment": ["planned", "building", "testing", "deploying", "deployed", "rolled_back", "failed"],
        "incident": ["detected", "triaged", "investigating", "mitigating", "resolved", "postmortem"],
        "pipeline": ["queued", "running", "succeeded", "failed", "cancelled", "retrying"],
        "vulnerability": ["discovered", "triaged", "assigned", "in_remediation", "fixed", "verified", "accepted_risk"],
    },
}

# ── Workflow pattern detection ────────────────────────────────

_WORKFLOW_SIGNALS: dict[str, list[tuple[re.Pattern, str]]] = {
    "approval_workflow": [
        (re.compile(r"approved_by|approver|approval_date|approval_status", re.I), "approval gate"),
        (re.compile(r"submitted_by|submitter|submission_date", re.I), "submission"),
        (re.compile(r"reviewer|reviewed_by|review_date", re.I), "review stage"),
    ],
    "escalation_workflow": [
        (re.compile(r"escalated|escalation|escalated_to|escalation_reason", re.I), "escalation trigger"),
        (re.compile(r"priority|severity|urgency", re.I), "prioritization"),
        (re.compile(r"sla|due_date|deadline|response_time", re.I), "SLA tracking"),
    ],
    "assignment_workflow": [
        (re.compile(r"assigned_to|assignee|assignment_date|owner", re.I), "assignment"),
        (re.compile(r"queue|pool|team|department", re.I), "work distribution"),
    ],
    "verification_workflow": [
        (re.compile(r"verified|verification|verified_by|verify_date", re.I), "verification"),
        (re.compile(r"document|evidence|proof|attachment", re.I), "documentation"),
        (re.compile(r"check|screen|validate|confirm", re.I), "validation"),
    ],
    "financial_workflow": [
        (re.compile(r"amount|total|balance|payment|fee|charge", re.I), "financial value"),
        (re.compile(r"currency|exchange_rate", re.I), "currency context"),
        (re.compile(r"invoice|receipt|ledger|journal", re.I), "financial record"),
    ],
    "lifecycle_workflow": [
        (re.compile(r"created_at|created_on|opened_at|start_date", re.I), "lifecycle start"),
        (re.compile(r"closed_at|completed_at|end_date|resolved_at", re.I), "lifecycle end"),
        (re.compile(r"status|state|phase|stage", re.I), "state tracking"),
        (re.compile(r"updated_at|modified_at|last_updated", re.I), "modification tracking"),
    ],
}

# ── Entity detection patterns ─────────────────────────────────

_ENTITY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (column_name_pattern, entity_type, relationship_kind)
    (re.compile(r"customer_id|client_id|member_id|customer_number", re.I), "customer", "belongs_to"),
    (re.compile(r"policy_id|policy_number|policy_no", re.I), "policy", "belongs_to"),
    (re.compile(r"claim_id|claim_number|claim_no", re.I), "claim", "belongs_to"),
    (re.compile(r"order_id|order_number|order_no", re.I), "order", "belongs_to"),
    (re.compile(r"account_id|account_number|account_no", re.I), "account", "belongs_to"),
    (re.compile(r"patient_id|patient_number", re.I), "patient", "belongs_to"),
    (re.compile(r"employee_id|emp_id|emp_no", re.I), "employee", "belongs_to"),
    (re.compile(r"product_id|product_code|sku", re.I), "product", "references"),
    (re.compile(r"transaction_id|txn_id|txn_no", re.I), "transaction", "records"),
    (re.compile(r"payment_id|payment_ref", re.I), "payment", "records"),
    (re.compile(r"invoice_id|invoice_number", re.I), "invoice", "records"),
    (re.compile(r"vendor_id|supplier_id", re.I), "vendor", "belongs_to"),
    (re.compile(r"department_id|dept_id", re.I), "department", "categorized_by"),
    (re.compile(r"project_id|project_code", re.I), "project", "belongs_to"),
    (re.compile(r"agent_id|adjuster_id|assessor_id", re.I), "agent", "handled_by"),
    (re.compile(r"branch_id|location_id|store_id", re.I), "location", "located_at"),
]


# ── Data classes ──────────────────────────────────────────────

@dataclass
class EntityRelationship:
    """A detected business entity relationship."""
    entity_type: str
    column: str
    relationship: str
    inferred_from: str  # "column_name", "foreign_key", "table_name"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "column": self.column,
            "relationship": self.relationship,
            "inferred_from": self.inferred_from,
        }


@dataclass
class WorkflowSignal:
    """A detected workflow pattern."""
    workflow_type: str
    signals: list[dict[str, str]]  # [{column, role}]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "signals": self.signals,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class TableContext:
    """Full business context for a single table."""
    table_name: str
    business_domain: str
    domain_confidence: float
    table_purpose: str
    purpose_confidence: float
    lifecycle_states: list[str]
    lifecycle_entity: str | None  # e.g., "claim", "order"
    workflows: list[WorkflowSignal]
    entities: list[EntityRelationship]
    column_count: int
    has_status_column: bool
    has_temporal_columns: bool
    has_monetary_columns: bool
    has_actor_columns: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "business_domain": self.business_domain,
            "domain_confidence": round(self.domain_confidence, 2),
            "table_purpose": self.table_purpose,
            "purpose_confidence": round(self.purpose_confidence, 2),
            "lifecycle_states": self.lifecycle_states,
            "lifecycle_entity": self.lifecycle_entity,
            "workflows": [w.to_dict() for w in self.workflows],
            "entities": [e.to_dict() for e in self.entities],
            "structural_summary": {
                "column_count": self.column_count,
                "has_status_column": self.has_status_column,
                "has_temporal_columns": self.has_temporal_columns,
                "has_monetary_columns": self.has_monetary_columns,
                "has_actor_columns": self.has_actor_columns,
            },
        }


@dataclass
class SchemaContext:
    """Full business context for an entire schema."""
    primary_domain: str
    domain_confidence: float
    domain_scores: dict[str, float]
    tables: list[TableContext]
    cross_table_relationships: list[dict[str, Any]]
    entity_map: dict[str, list[str]]  # entity_type → [table_names]
    workflow_summary: list[str]  # unique workflow types across all tables

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_domain": self.primary_domain,
            "domain_confidence": round(self.domain_confidence, 2),
            "domain_scores": {k: round(v, 2) for k, v in self.domain_scores.items()},
            "table_count": len(self.tables),
            "tables": [t.to_dict() for t in self.tables],
            "cross_table_relationships": self.cross_table_relationships,
            "entity_map": self.entity_map,
            "workflow_summary": self.workflow_summary,
        }


# ── Helpers ───────────────────────────────────────────────────

def _singularize(word: str) -> str:
    """Simple English singularization for table names."""
    if word.endswith("ies"):
        return word[:-3] + "y"  # policies → policy
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]  # addresses → address
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]  # customers → customer
    return word


# ── Business Context Inference Engine ─────────────────────────

class BusinessContextEngine:
    """Analyzes schema structure to understand business meaning."""

    def analyze_table(self, table: TableMetadata, schema_domain: str | None = None) -> TableContext:
        """Analyze a single table and return its business context."""
        col_names = [c.name for c in table.columns]
        col_names_lower = [c.lower() for c in col_names]
        all_text = table.name.lower() + " " + " ".join(col_names_lower)

        # 1. Detect domain
        domain, domain_conf = self._score_domain(table.name, col_names)
        # If schema-level domain is available and table domain is weak, prefer schema
        if schema_domain and domain_conf < 0.4:
            domain = schema_domain
            domain_conf = 0.5  # moderate confidence from schema context

        # 2. Classify table purpose
        purpose, purpose_conf = self._classify_purpose(table)

        # 3. Detect lifecycle states
        lifecycle_states, lifecycle_entity = self._detect_lifecycle(table, domain)

        # 4. Detect workflows
        workflows = self._detect_workflows(col_names)

        # 5. Detect entity relationships
        entities = self._detect_entities(table)

        # 6. Structural analysis
        has_status = any(re.search(r"status|state|phase|stage", c, re.I) for c in col_names)
        has_temporal = any(re.search(r"_at$|_on$|_date$|_time$|created|updated", c, re.I) for c in col_names)
        has_monetary = any(re.search(r"amount|total|price|cost|fee|balance|premium", c, re.I) for c in col_names)
        has_actor = any(re.search(r"_by$|assignee|reviewer|approver|owner", c, re.I) for c in col_names)

        return TableContext(
            table_name=table.name,
            business_domain=domain,
            domain_confidence=domain_conf,
            table_purpose=purpose,
            purpose_confidence=purpose_conf,
            lifecycle_states=lifecycle_states,
            lifecycle_entity=lifecycle_entity,
            workflows=workflows,
            entities=entities,
            column_count=len(table.columns),
            has_status_column=has_status,
            has_temporal_columns=has_temporal,
            has_monetary_columns=has_monetary,
            has_actor_columns=has_actor,
        )

    def analyze_schema(self, schema: SchemaMetadata) -> SchemaContext:
        """Analyze an entire schema and return holistic business context."""
        if not schema.tables:
            return SchemaContext(
                primary_domain="unknown",
                domain_confidence=0.0,
                domain_scores={},
                tables=[],
                cross_table_relationships=[],
                entity_map={},
                workflow_summary=[],
            )

        # First pass: detect schema-level domain
        all_col_names: list[str] = []
        all_table_names: list[str] = []
        for t in schema.tables:
            all_table_names.append(t.name)
            all_col_names.extend(c.name for c in t.columns)

        schema_domain, schema_conf = self._score_domain_from_text(
            " ".join(all_table_names) + " " + " ".join(all_col_names)
        )

        # Second pass: analyze each table with schema-level context
        table_contexts: list[TableContext] = []
        for t in schema.tables:
            ctx = self.analyze_table(t, schema_domain=schema_domain)
            table_contexts.append(ctx)

        # Cross-table relationships from foreign keys
        cross_rels = self._detect_cross_table_relationships(schema)

        # Entity map: which tables reference which entities
        entity_map: dict[str, list[str]] = {}
        for tc in table_contexts:
            for ent in tc.entities:
                entity_map.setdefault(ent.entity_type, [])
                if tc.table_name not in entity_map[ent.entity_type]:
                    entity_map[ent.entity_type].append(tc.table_name)

        # Aggregate workflow types
        all_workflows: set[str] = set()
        for tc in table_contexts:
            for wf in tc.workflows:
                all_workflows.add(wf.workflow_type)

        # Refine schema domain from table-level analyses
        domain_votes: dict[str, float] = {}
        for tc in table_contexts:
            domain_votes[tc.business_domain] = domain_votes.get(tc.business_domain, 0) + tc.domain_confidence
        if domain_votes:
            best = max(domain_votes, key=lambda d: domain_votes[d])
            total = sum(domain_votes.values())
            if total > 0:
                schema_domain = best
                schema_conf = domain_votes[best] / total

        # Compute normalized domain scores
        domain_scores: dict[str, float] = {}
        total = sum(domain_votes.values()) if domain_votes else 1.0
        for d, v in domain_votes.items():
            domain_scores[d] = v / total if total > 0 else 0.0

        return SchemaContext(
            primary_domain=schema_domain,
            domain_confidence=schema_conf,
            domain_scores=domain_scores,
            tables=table_contexts,
            cross_table_relationships=cross_rels,
            entity_map=entity_map,
            workflow_summary=sorted(all_workflows),
        )

    # ── Domain scoring ────────────────────────────────────────

    def _score_domain(self, table_name: str, col_names: list[str]) -> tuple[str, float]:
        """Score domain from table name + column names."""
        text = table_name.lower() + " " + " ".join(c.lower() for c in col_names)
        return self._score_domain_from_text(text)

    def _score_domain_from_text(self, text: str) -> tuple[str, float]:
        """Score domain from arbitrary text."""
        scores: dict[str, float] = {d: 0.0 for d in _DOMAIN_KEYWORDS}
        words = set(re.findall(r"[a-z_]+", text.lower()))
        # Also check bigrams for compound terms
        text_lower = text.lower()

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            for kw, weight in keywords.items():
                if kw in words or kw in text_lower:
                    scores[domain] += weight

        total = sum(scores.values())
        if total == 0:
            return "general", 0.0

        best = max(scores, key=lambda d: scores[d])
        confidence = scores[best] / total
        return best, confidence

    # ── Table purpose classification ──────────────────────────

    def _classify_purpose(self, table: TableMetadata) -> tuple[str, float]:
        """Classify a table's purpose from its name and structure."""
        tbl_lower = table.name.lower()
        col_names_lower = [c.name.lower() for c in table.columns]

        # Check name-based patterns
        best_purpose = "general"
        best_conf = 0.0

        for purpose, patterns, conf in _TABLE_PURPOSE_PATTERNS:
            for pat in patterns:
                if pat.search(tbl_lower):
                    if conf > best_conf:
                        best_purpose = purpose
                        best_conf = conf

        # Structural heuristics for junction tables
        if best_conf < 0.7:
            fk_count = len(table.foreign_keys)
            col_count = len(table.columns)
            if fk_count >= 2 and col_count <= fk_count + 3:
                best_purpose = "junction"
                best_conf = 0.85

        # Structural heuristics for lookup tables
        if best_conf < 0.7:
            col_count = len(table.columns)
            has_code = any("code" in c or "type" in c for c in col_names_lower)
            has_desc = any("name" in c or "description" in c or "label" in c for c in col_names_lower)
            if col_count <= 5 and has_code and has_desc:
                best_purpose = "lookup"
                best_conf = 0.75

        # Structural heuristics for audit tables
        if best_conf < 0.7:
            has_timestamp = any(re.search(r"timestamp|created_at|event_time|logged_at", c) for c in col_names_lower)
            has_action = any(re.search(r"action|event_type|operation|activity", c) for c in col_names_lower)
            if has_timestamp and has_action:
                best_purpose = "audit_log"
                best_conf = 0.8

        return best_purpose, best_conf

    # ── Lifecycle detection ───────────────────────────────────

    def _detect_lifecycle(self, table: TableMetadata, domain: str) -> tuple[list[str], str | None]:
        """Detect lifecycle states for a table based on domain and table name."""
        tbl_lower = table.name.lower()
        col_names = [c.name for c in table.columns]

        # Check for CHECK constraints that define status enums
        check_states = self._extract_states_from_checks(table)
        if check_states:
            entity = self._guess_lifecycle_entity(tbl_lower)
            return check_states, entity

        # Try domain-specific lifecycle mapping
        domain_lifecycles = _LIFECYCLE_INDICATORS.get(domain, {})
        best_match: str | None = None
        best_states: list[str] = []

        for entity_key, states in domain_lifecycles.items():
            if entity_key in tbl_lower:
                best_match = entity_key
                best_states = states
                break

        if best_states:
            return best_states, best_match

        # Generic lifecycle from column structure
        has_status = any(re.search(r"^status$|_status$|^state$|_state$", c, re.I) for c in col_names)
        has_created = any(re.search(r"created|opened|started|submitted", c, re.I) for c in col_names)
        has_closed = any(re.search(r"closed|completed|resolved|ended", c, re.I) for c in col_names)

        if has_status:
            # Generic lifecycle
            generic = ["created", "active", "in_progress"]
            if has_closed:
                generic.extend(["completed", "closed"])
            return generic, self._guess_lifecycle_entity(tbl_lower)

        return [], None

    def _extract_states_from_checks(self, table: TableMetadata) -> list[str]:
        """Extract lifecycle states from CHECK constraints on status columns."""
        for col in table.columns:
            if not col.check_constraint:
                continue
            col_lower = col.name.lower()
            if not re.search(r"status|state|phase|stage", col_lower):
                continue
            # Parse IN (...) constraint
            match = re.search(
                r"IN\s*\(\s*(.+?)\s*\)",
                col.check_constraint,
                re.IGNORECASE,
            )
            if match:
                raw = match.group(1)
                states = [v.strip().strip("'\"") for v in raw.split(",")]
                return [s for s in states if s]
        return []

    def _guess_lifecycle_entity(self, table_name: str) -> str | None:
        """Guess the lifecycle entity from the table name."""
        candidates = [
            "claim", "policy", "order", "payment", "transaction",
            "loan", "account", "patient", "appointment", "employee",
            "ticket", "request", "case", "task", "shipment",
            "invoice", "return", "referral", "incident", "deployment",
        ]
        for c in candidates:
            if c in table_name.lower():
                return c
        return None

    # ── Workflow detection ────────────────────────────────────

    def _detect_workflows(self, col_names: list[str]) -> list[WorkflowSignal]:
        """Detect workflow patterns from column names."""
        workflows: list[WorkflowSignal] = []

        for wf_type, signal_patterns in _WORKFLOW_SIGNALS.items():
            matched_signals: list[dict[str, str]] = []
            for col in col_names:
                for pat, role in signal_patterns:
                    if pat.search(col):
                        matched_signals.append({"column": col, "role": role})

            if matched_signals:
                # Confidence based on how many distinct signal roles matched
                distinct_roles = len(set(s["role"] for s in matched_signals))
                total_roles = len(signal_patterns)
                confidence = min(0.5 + (distinct_roles / total_roles) * 0.5, 1.0)
                workflows.append(WorkflowSignal(
                    workflow_type=wf_type,
                    signals=matched_signals,
                    confidence=confidence,
                ))

        return sorted(workflows, key=lambda w: -w.confidence)

    # ── Entity detection ──────────────────────────────────────

    def _detect_entities(self, table: TableMetadata) -> list[EntityRelationship]:
        """Detect business entity relationships from columns and foreign keys."""
        entities: list[EntityRelationship] = []
        seen: set[tuple[str, str]] = set()

        # From foreign keys (highest confidence)
        for fk in table.foreign_keys:
            entity_type = _singularize(fk.references_table.lower())
            key = (entity_type, fk.column)
            if key not in seen:
                seen.add(key)
                entities.append(EntityRelationship(
                    entity_type=entity_type,
                    column=fk.column,
                    relationship="belongs_to",
                    inferred_from="foreign_key",
                ))

        # From column name patterns
        for col in table.columns:
            for pat, entity_type, relationship in _ENTITY_PATTERNS:
                if pat.search(col.name):
                    key = (entity_type, col.name)
                    if key not in seen:
                        seen.add(key)
                        entities.append(EntityRelationship(
                            entity_type=entity_type,
                            column=col.name,
                            relationship=relationship,
                            inferred_from="column_name",
                        ))

        # From table name itself (the table IS an entity)
        table_entity = self._guess_lifecycle_entity(table.name)
        if table_entity:
            key = (table_entity, table.name)
            if key not in seen:
                seen.add(key)
                entities.append(EntityRelationship(
                    entity_type=table_entity,
                    column=table.name,
                    relationship="is_entity",
                    inferred_from="table_name",
                ))

        return entities

    # ── Cross-table relationships ─────────────────────────────

    def _detect_cross_table_relationships(self, schema: SchemaMetadata) -> list[dict[str, Any]]:
        """Detect relationships between tables from foreign keys."""
        rels: list[dict[str, Any]] = []

        for table in schema.tables:
            for fk in table.foreign_keys:
                rels.append({
                    "from_table": table.name,
                    "from_column": fk.column,
                    "to_table": fk.references_table,
                    "to_column": fk.references_column,
                    "relationship_type": self._infer_fk_relationship_type(table, fk),
                })

        return rels

    def _infer_fk_relationship_type(self, table: TableMetadata, fk: ForeignKeyMetadata) -> str:
        """Infer the nature of a FK relationship."""
        # If FK column is part of primary key → junction/bridge table
        if fk.column in table.primary_keys:
            return "composition"
        # If FK column is unique → one-to-one
        col_meta = next((c for c in table.columns if c.name == fk.column), None)
        if col_meta and col_meta.is_unique:
            return "one_to_one"
        # Default: many-to-one
        return "many_to_one"


# ── Module-level singleton ────────────────────────────────────

_default_engine: BusinessContextEngine | None = None


def get_default_engine() -> BusinessContextEngine:
    """Get or create the default business context engine."""
    global _default_engine
    if _default_engine is None:
        _default_engine = BusinessContextEngine()
    return _default_engine


# ── Public API ────────────────────────────────────────────────

def analyze_table_context(table: TableMetadata, schema_domain: str | None = None) -> dict[str, Any]:
    """Analyze a single table and return its business context as dict."""
    engine = get_default_engine()
    return engine.analyze_table(table, schema_domain=schema_domain).to_dict()


def analyze_schema_context(schema: SchemaMetadata) -> dict[str, Any]:
    """Analyze an entire schema and return holistic business context."""
    engine = get_default_engine()
    return engine.analyze_schema(schema).to_dict()


def infer_table_domain(table: TableMetadata) -> str:
    """Quick domain inference for a single table — returns domain string."""
    engine = get_default_engine()
    ctx = engine.analyze_table(table)
    return ctx.business_domain


def infer_schema_domain(schema: SchemaMetadata) -> str:
    """Quick domain inference for an entire schema — returns domain string."""
    engine = get_default_engine()
    ctx = engine.analyze_schema(schema)
    return ctx.primary_domain


def get_table_lifecycle(table: TableMetadata, domain: str | None = None) -> list[str]:
    """Get lifecycle states for a table."""
    engine = get_default_engine()
    ctx = engine.analyze_table(table, schema_domain=domain)
    return ctx.lifecycle_states


def get_table_workflows(table: TableMetadata) -> list[dict[str, Any]]:
    """Get detected workflows for a table."""
    engine = get_default_engine()
    ctx = engine.analyze_table(table)
    return [w.to_dict() for w in ctx.workflows]
