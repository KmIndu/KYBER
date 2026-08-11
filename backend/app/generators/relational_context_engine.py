"""Relational Context Understanding Engine.

Understands relationships not just between tables structurally (FK),
but also between business states across related entities.

Examples:
  customer ↔ account ↔ transaction (entity chain)
  claim ↔ policy ↔ approval_status (state inheritance)
  order ↔ payment ↔ refund (lifecycle chain)

Capabilities:
- Relationship graph with business role classification
- Contextual relationship inference (beyond FK structure)
- Workflow state propagation across parent-child tables
- Parent-child scenario propagation (child inherits parent context)
- FK-aware scenario generation constraints

Key Concept: A child table's rows must be CONSISTENT with the parent
entity's business state. If a policy is cancelled, its claims cannot
be in 'approved' state. If an account is closed, new transactions
should not be 'pending'.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.models.schema import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata

logger = logging.getLogger(__name__)


# ── Relationship Classification ───────────────────────────────

class RelationshipRole:
    """Business role classifications for table relationships."""
    MASTER_DETAIL = "master_detail"          # customer → orders
    PARENT_CHILD = "parent_child"            # policy → claims
    ENTITY_TRANSACTION = "entity_transaction"  # account → transactions
    LIFECYCLE_AUDIT = "lifecycle_audit"       # order → order_history
    LOOKUP_REFERENCE = "lookup_reference"     # order.status_id → statuses
    JUNCTION = "junction"                    # student_courses
    COMPOSITION = "composition"              # address is part of customer
    WORKFLOW_CHAIN = "workflow_chain"         # claim → approval → payment


@dataclass
class RelationalEdge:
    """A business-aware relationship between two tables."""
    from_table: str
    to_table: str
    from_column: str
    to_column: str
    role: str  # RelationshipRole value
    cardinality: str  # "one_to_many", "one_to_one", "many_to_many"
    state_propagation: str  # "none", "inherits", "constrains", "triggers"
    confidence: float
    business_context: str  # Human-readable description

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_table": self.from_table,
            "to_table": self.to_table,
            "from_column": self.from_column,
            "to_column": self.to_column,
            "role": self.role,
            "cardinality": self.cardinality,
            "state_propagation": self.state_propagation,
            "confidence": round(self.confidence, 2),
            "business_context": self.business_context,
        }


@dataclass
class StateConstraint:
    """A constraint that a parent state places on child rows."""
    parent_table: str
    parent_status_column: str
    parent_state: str
    child_table: str
    child_status_column: str | None  # None means the child's own status col
    allowed_child_states: list[str]
    forbidden_child_states: list[str]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_table": self.parent_table,
            "parent_status_column": self.parent_status_column,
            "parent_state": self.parent_state,
            "child_table": self.child_table,
            "child_status_column": self.child_status_column,
            "allowed_child_states": self.allowed_child_states,
            "forbidden_child_states": self.forbidden_child_states,
            "explanation": self.explanation,
        }


@dataclass
class ScenarioPropagation:
    """Defines how a parent's scenario context propagates to children."""
    parent_table: str
    child_table: str
    propagation_type: str  # "state_inheritance", "value_constraint", "temporal_order"
    rules: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_table": self.parent_table,
            "child_table": self.child_table,
            "propagation_type": self.propagation_type,
            "rules": self.rules,
        }


@dataclass
class RelationalContext:
    """Full relational context for a schema."""
    domain: str
    edges: list[RelationalEdge]
    entity_chains: list[list[str]]  # Ordered entity chains e.g. [customer, account, transaction]
    state_constraints: list[StateConstraint]
    scenario_propagations: list[ScenarioPropagation]
    root_entities: list[str]  # Tables at the top of entity hierarchy
    terminal_entities: list[str]  # Tables at the bottom (leaf transactions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "relationship_graph": [e.to_dict() for e in self.edges],
            "entity_chains": self.entity_chains,
            "state_constraints": [c.to_dict() for c in self.state_constraints],
            "scenario_propagations": [p.to_dict() for p in self.scenario_propagations],
            "root_entities": self.root_entities,
            "terminal_entities": self.terminal_entities,
            "summary": {
                "total_relationships": len(self.edges),
                "entity_chain_count": len(self.entity_chains),
                "state_constraint_count": len(self.state_constraints),
                "propagation_rule_count": len(self.scenario_propagations),
            },
        }


# ── State Propagation Rules ──────────────────────────────────
# Define how parent statuses constrain child statuses across domains.

_TERMINAL_NEGATIVE_STATES = frozenset({
    "cancelled", "terminated", "closed", "rejected", "denied",
    "expired", "suspended", "inactive", "deleted", "void",
    "closed_denied", "lapsed",
})

_TERMINAL_POSITIVE_STATES = frozenset({
    "completed", "settled", "paid", "resolved", "fulfilled",
    "delivered", "closed_approved", "matured",
})

_PENDING_STATES = frozenset({
    "pending", "open", "submitted", "in_review", "under_review",
    "processing", "queued", "draft", "new", "initiated",
})

_ACTIVE_STATES = frozenset({
    "active", "in_progress", "approved", "in_force",
    "running", "live", "enabled",
})

# When parent is in a terminal negative state, children are constrained:
_NEGATIVE_PARENT_ALLOWS_CHILD: frozenset[str] = frozenset({
    "cancelled", "terminated", "closed", "rejected", "denied",
    "void", "expired", "inactive", "refunded",
})

# When parent is pending, children should not be in terminal positive states:
_PENDING_PARENT_FORBIDS_CHILD: frozenset[str] = frozenset({
    "completed", "settled", "paid", "fulfilled", "delivered",
    "approved", "resolved",
})


# ── Table Purpose Pattern Matching ───────────────────────────

_TRANSACTION_PAT = re.compile(
    r"transaction|payment|transfer|order_item|line_item|charge|"
    r"invoice_item|ledger_entry|debit|credit|disbursement", re.I
)
_AUDIT_PAT = re.compile(
    r"_log$|_history$|_audit$|_event$|_change$|_tracking$|"
    r"audit_trail|changelog|activity_log", re.I
)
_LOOKUP_PAT = re.compile(
    r"^status_|^type_|^category_|_types$|_statuses$|_categories$|"
    r"_codes$|_lookup$|_ref$|_reference$", re.I
)
_MASTER_PAT = re.compile(
    r"customer|account|user|employee|patient|member|vendor|"
    r"supplier|company|organization|person|agent|client", re.I
)
_LIFECYCLE_PAT = re.compile(
    r"policy|claim|order|application|request|case|ticket|"
    r"contract|loan|mortgage|project|campaign", re.I
)

_STATUS_COL_PAT = re.compile(
    r"^status$|_status$|^state$|_state$|^phase$|^stage$|"
    r"^decision$|^outcome$|^result$", re.I
)


# ── Domain-Specific Workflow Chains ──────────────────────────
# Define known business entity chains per domain.

_DOMAIN_ENTITY_CHAINS: dict[str, list[list[str]]] = {
    "insurance": [
        ["customer", "policy", "claim", "payment"],
        ["customer", "policy", "endorsement"],
        ["policy", "coverage", "benefit"],
        ["claim", "assessment", "settlement"],
        ["claim", "approval", "payment"],
    ],
    "banking": [
        ["customer", "account", "transaction"],
        ["customer", "loan", "payment"],
        ["customer", "account", "card", "transaction"],
        ["loan", "collateral"],
        ["account", "statement"],
    ],
    "healthcare": [
        ["patient", "encounter", "diagnosis"],
        ["patient", "appointment", "visit"],
        ["patient", "prescription", "medication"],
        ["encounter", "procedure", "billing"],
        ["patient", "insurance_claim", "payment"],
    ],
    "hr": [
        ["employee", "leave_request", "approval"],
        ["employee", "performance_review"],
        ["department", "employee", "payroll"],
        ["candidate", "application", "interview", "offer"],
        ["employee", "benefit_enrollment"],
    ],
    "ecommerce": [
        ["customer", "order", "order_item", "shipment"],
        ["customer", "cart", "cart_item"],
        ["order", "payment", "refund"],
        ["product", "inventory", "warehouse"],
        ["order", "return", "refund"],
    ],
    "devops": [
        ["repository", "pipeline", "build", "deployment"],
        ["service", "incident", "alert"],
        ["release", "artifact", "deployment"],
        ["scan", "vulnerability", "remediation"],
    ],
}


# ── Engine Implementation ─────────────────────────────────────

class RelationalContextEngine:
    """Understands cross-table business relationships and state propagation."""

    def analyze(self, schema: SchemaMetadata, domain: str = "unknown") -> RelationalContext:
        """Analyze the full schema to build relational context."""
        if not schema.tables:
            return RelationalContext(
                domain=domain,
                edges=[],
                entity_chains=[],
                state_constraints=[],
                scenario_propagations=[],
                root_entities=[],
                terminal_entities=[],
            )

        # Resolve domain if unknown
        if domain in ("unknown", "general"):
            domain = self._infer_domain(schema)

        table_map = {t.name: t for t in schema.tables}

        # Step 1: Build business-aware relationship edges
        edges = self._build_relationship_edges(schema, table_map, domain)

        # Step 2: Detect entity chains
        entity_chains = self._detect_entity_chains(schema, edges, domain)

        # Step 3: Derive state constraints from relationships
        state_constraints = self._derive_state_constraints(edges, table_map, domain)

        # Step 4: Build scenario propagation rules
        scenario_propagations = self._build_propagation_rules(edges, table_map, state_constraints)

        # Step 5: Identify root and terminal entities
        root_entities = self._find_root_entities(edges, table_map)
        terminal_entities = self._find_terminal_entities(edges, table_map)

        return RelationalContext(
            domain=domain,
            edges=edges,
            entity_chains=entity_chains,
            state_constraints=state_constraints,
            scenario_propagations=scenario_propagations,
            root_entities=root_entities,
            terminal_entities=terminal_entities,
        )

    def get_parent_state_constraints(
        self,
        schema: SchemaMetadata,
        child_table: str,
        parent_data: dict[str, list[dict[str, Any]]],
        domain: str = "unknown",
    ) -> dict[str, Any]:
        """Get constraints on a child table given parent row data.

        Used during generation: before generating child rows, check what
        scenarios are allowed given the parent's current state.

        Returns:
            {
                "allowed_scenarios": [...],
                "forbidden_states": [...],
                "parent_state_distribution": {...},
                "constraints": [...]
            }
        """
        ctx = self.analyze(schema, domain=domain)
        table_map = {t.name: t for t in schema.tables}
        child_meta = table_map.get(child_table)
        if not child_meta:
            return {"allowed_scenarios": [], "forbidden_states": [], "constraints": []}

        constraints_for_child = [
            c for c in ctx.state_constraints if c.child_table == child_table
        ]

        # Determine parent state distribution from parent data
        parent_state_dist: dict[str, dict[str, int]] = {}
        forbidden: set[str] = set()
        allowed: set[str] | None = None

        for constraint in constraints_for_child:
            parent_rows = parent_data.get(constraint.parent_table, [])
            if not parent_rows:
                continue

            # Count parent states
            for row in parent_rows:
                pstate = row.get(constraint.parent_status_column)
                if pstate:
                    key = f"{constraint.parent_table}.{constraint.parent_status_column}"
                    parent_state_dist.setdefault(key, {})
                    parent_state_dist[key][pstate] = parent_state_dist[key].get(pstate, 0) + 1

                    # If this parent state matches the constraint, apply it
                    if pstate.lower() == constraint.parent_state.lower():
                        forbidden.update(constraint.forbidden_child_states)
                        if constraint.allowed_child_states:
                            if allowed is None:
                                allowed = set(constraint.allowed_child_states)
                            else:
                                allowed &= set(constraint.allowed_child_states)

        return {
            "child_table": child_table,
            "forbidden_states": sorted(forbidden),
            "allowed_states": sorted(allowed) if allowed else None,
            "parent_state_distribution": parent_state_dist,
            "constraints_applied": len(constraints_for_child),
            "constraints": [c.to_dict() for c in constraints_for_child],
        }

    def propagate_scenario(
        self,
        schema: SchemaMetadata,
        parent_table: str,
        child_table: str,
        parent_rows: list[dict[str, Any]],
        domain: str = "unknown",
    ) -> list[dict[str, Any]]:
        """Propagate parent scenarios to generate child scenario hints.

        For each parent row, produces a scenario context that should
        influence how the child rows (linked to that parent) are generated.

        Returns list of dicts with keys:
            - parent_row_index: int
            - parent_state: str or None
            - child_scenario_hints: dict of constraints/suggestions
        """
        ctx = self.analyze(schema, domain=domain)
        table_map = {t.name: t for t in schema.tables}
        parent_meta = table_map.get(parent_table)
        child_meta = table_map.get(child_table)
        if not parent_meta or not child_meta:
            return []

        # Find the edge between these tables
        edge = next(
            (e for e in ctx.edges
             if (e.from_table == child_table and e.to_table == parent_table)
             or (e.from_table == parent_table and e.to_table == child_table)),
            None,
        )

        # Find parent status column
        parent_status_col = self._find_status_column(parent_meta)
        child_status_col = self._find_status_column(child_meta)

        # Find state constraints for this pair
        pair_constraints = [
            c for c in ctx.state_constraints
            if c.parent_table == parent_table and c.child_table == child_table
        ]

        results: list[dict[str, Any]] = []
        for idx, parent_row in enumerate(parent_rows):
            parent_state = parent_row.get(parent_status_col) if parent_status_col else None
            hints: dict[str, Any] = {}

            if parent_state:
                parent_state_lower = parent_state.lower()
                hints["parent_state"] = parent_state

                # Apply constraints
                for constraint in pair_constraints:
                    if constraint.parent_state.lower() == parent_state_lower:
                        if constraint.allowed_child_states:
                            hints["allowed_states"] = constraint.allowed_child_states
                        if constraint.forbidden_child_states:
                            hints["forbidden_states"] = constraint.forbidden_child_states

                # Infer temporal ordering
                if parent_state_lower in _TERMINAL_NEGATIVE_STATES:
                    hints["temporal_hint"] = "parent_terminated"
                    hints["prefer_states"] = ["cancelled", "closed", "void"]
                elif parent_state_lower in _TERMINAL_POSITIVE_STATES:
                    hints["temporal_hint"] = "parent_completed"
                    hints["prefer_states"] = ["completed", "settled", "paid", "delivered"]
                elif parent_state_lower in _PENDING_STATES:
                    hints["temporal_hint"] = "parent_pending"
                    hints["prefer_states"] = ["pending", "draft", "new", "initiated"]
                elif parent_state_lower in _ACTIVE_STATES:
                    hints["temporal_hint"] = "parent_active"
                    hints["prefer_states"] = ["active", "in_progress", "processing"]

                # Propagate relevant parent values
                if edge and edge.state_propagation in ("inherits", "constrains"):
                    hints["propagation_type"] = edge.state_propagation

            results.append({
                "parent_row_index": idx,
                "parent_state": parent_state,
                "child_scenario_hints": hints,
            })

        return results

    # ── Internal Methods ──────────────────────────────────────

    def _infer_domain(self, schema: SchemaMetadata) -> str:
        """Infer domain from schema table/column names."""
        from app.generators.business_context_engine import infer_schema_domain
        return infer_schema_domain(schema)

    def _build_relationship_edges(
        self,
        schema: SchemaMetadata,
        table_map: dict[str, TableMetadata],
        domain: str,
    ) -> list[RelationalEdge]:
        """Build business-aware relationship edges from FK constraints."""
        edges: list[RelationalEdge] = []

        for table in schema.tables:
            for fk in table.foreign_keys:
                parent_table = table_map.get(fk.references_table)
                if not parent_table:
                    continue

                role = self._classify_relationship_role(table, parent_table, fk, domain)
                cardinality = self._determine_cardinality(table, fk)
                state_prop = self._determine_state_propagation(table, parent_table, fk, role)
                context = self._describe_relationship(table.name, parent_table.name, role)

                edges.append(RelationalEdge(
                    from_table=table.name,
                    to_table=parent_table.name,
                    from_column=fk.column,
                    to_column=fk.references_column,
                    role=role,
                    cardinality=cardinality,
                    state_propagation=state_prop,
                    confidence=self._edge_confidence(role, cardinality),
                    business_context=context,
                ))

        # Also infer implicit relationships (no FK but naming conventions)
        implicit = self._infer_implicit_relationships(schema, table_map, edges, domain)
        edges.extend(implicit)

        return edges

    def _classify_relationship_role(
        self,
        child: TableMetadata,
        parent: TableMetadata,
        fk: ForeignKeyMetadata,
        domain: str,
    ) -> str:
        """Classify the business role of a FK relationship."""
        child_name = child.name.lower()
        parent_name = parent.name.lower()
        fk_col = fk.column.lower()

        # Junction table: FK column is part of PK
        if fk.column in child.primary_keys:
            return RelationshipRole.JUNCTION

        # Audit/history table
        if _AUDIT_PAT.search(child_name):
            return RelationshipRole.LIFECYCLE_AUDIT

        # Lookup/reference table
        if _LOOKUP_PAT.search(parent_name):
            return RelationshipRole.LOOKUP_REFERENCE

        # Transaction table referencing a master entity
        if _TRANSACTION_PAT.search(child_name) and _MASTER_PAT.search(parent_name):
            return RelationshipRole.ENTITY_TRANSACTION

        # Master entity referencing another master (composition)
        if _MASTER_PAT.search(child_name) and _MASTER_PAT.search(parent_name):
            return RelationshipRole.COMPOSITION

        # Lifecycle entity referencing master
        if _LIFECYCLE_PAT.search(child_name) and _MASTER_PAT.search(parent_name):
            return RelationshipRole.PARENT_CHILD

        # Lifecycle entity referencing lifecycle (workflow chain)
        if _LIFECYCLE_PAT.search(child_name) and _LIFECYCLE_PAT.search(parent_name):
            return RelationshipRole.WORKFLOW_CHAIN

        # Transaction referencing lifecycle
        if _TRANSACTION_PAT.search(child_name) and _LIFECYCLE_PAT.search(parent_name):
            return RelationshipRole.ENTITY_TRANSACTION

        # Default: parent-child based on naming
        if _MASTER_PAT.search(parent_name):
            return RelationshipRole.MASTER_DETAIL

        return RelationshipRole.PARENT_CHILD

    def _determine_cardinality(self, child: TableMetadata, fk: ForeignKeyMetadata) -> str:
        """Determine relationship cardinality."""
        col_meta = next((c for c in child.columns if c.name == fk.column), None)

        # FK in PK = junction (many-to-many)
        if fk.column in child.primary_keys:
            return "many_to_many"

        # FK is unique = one-to-one
        if col_meta and col_meta.is_unique:
            return "one_to_one"

        return "one_to_many"

    def _determine_state_propagation(
        self,
        child: TableMetadata,
        parent: TableMetadata,
        fk: ForeignKeyMetadata,
        role: str,
    ) -> str:
        """Determine how parent state affects child state."""
        # Lookup/reference tables don't propagate state
        if role == RelationshipRole.LOOKUP_REFERENCE:
            return "none"

        # Junction tables don't propagate state
        if role == RelationshipRole.JUNCTION:
            return "none"

        # Audit tables inherit state implicitly
        if role == RelationshipRole.LIFECYCLE_AUDIT:
            return "inherits"

        # Check if both parent and child have status columns
        parent_has_status = any(_STATUS_COL_PAT.search(c.name) for c in parent.columns)
        child_has_status = any(_STATUS_COL_PAT.search(c.name) for c in child.columns)

        if parent_has_status and child_has_status:
            # Workflow chain: strong state inheritance
            if role == RelationshipRole.WORKFLOW_CHAIN:
                return "inherits"
            # Parent-child: parent constrains child
            if role in (RelationshipRole.PARENT_CHILD, RelationshipRole.ENTITY_TRANSACTION):
                return "constrains"
            # Master-detail: master constrains detail
            if role == RelationshipRole.MASTER_DETAIL:
                return "constrains"

        # Parent has status but child doesn't: triggers
        if parent_has_status and not child_has_status:
            return "triggers"

        return "none"

    def _describe_relationship(self, child_name: str, parent_name: str, role: str) -> str:
        """Generate human-readable description of the relationship."""
        role_descriptions = {
            RelationshipRole.MASTER_DETAIL: f"{child_name} is a detail record of {parent_name}",
            RelationshipRole.PARENT_CHILD: f"{child_name} belongs to {parent_name}",
            RelationshipRole.ENTITY_TRANSACTION: f"{child_name} is a transaction against {parent_name}",
            RelationshipRole.LIFECYCLE_AUDIT: f"{child_name} tracks the history of {parent_name}",
            RelationshipRole.LOOKUP_REFERENCE: f"{child_name} references the {parent_name} lookup",
            RelationshipRole.JUNCTION: f"{child_name} is a junction linking to {parent_name}",
            RelationshipRole.COMPOSITION: f"{child_name} is composed with {parent_name}",
            RelationshipRole.WORKFLOW_CHAIN: f"{child_name} follows {parent_name} in the workflow",
        }
        return role_descriptions.get(role, f"{child_name} references {parent_name}")

    def _edge_confidence(self, role: str, cardinality: str) -> float:
        """Calculate confidence score for classified edge."""
        base = 0.7
        # Higher confidence for clear patterns
        if role in (RelationshipRole.LIFECYCLE_AUDIT, RelationshipRole.JUNCTION):
            base = 0.9
        elif role in (RelationshipRole.ENTITY_TRANSACTION, RelationshipRole.WORKFLOW_CHAIN):
            base = 0.85
        elif role in (RelationshipRole.LOOKUP_REFERENCE,):
            base = 0.9

        # Implicit (inferred) edges have lower confidence
        return base

    def _infer_implicit_relationships(
        self,
        schema: SchemaMetadata,
        table_map: dict[str, TableMetadata],
        existing_edges: list[RelationalEdge],
        domain: str,
    ) -> list[RelationalEdge]:
        """Infer relationships that don't have explicit FKs but are implied by naming."""
        implicit: list[RelationalEdge] = []
        existing_pairs = {(e.from_table, e.to_table) for e in existing_edges}
        table_names = [t.name for t in schema.tables]

        for table in schema.tables:
            for col in table.columns:
                col_lower = col.name.lower()
                # Pattern: <table_name>_id without FK constraint
                if col_lower.endswith("_id") and not col.is_primary_key:
                    potential_parent = col_lower[:-3]  # Strip _id
                    # Try to find matching table
                    matched_table = None
                    for tn in table_names:
                        tn_lower = tn.lower()
                        if tn_lower == potential_parent or tn_lower == potential_parent + "s":
                            matched_table = tn
                            break
                        # Try singularizing
                        if _singularize(tn_lower) == potential_parent:
                            matched_table = tn
                            break

                    if matched_table and (table.name, matched_table) not in existing_pairs:
                        parent_meta = table_map[matched_table]
                        role = self._classify_relationship_role(
                            table, parent_meta,
                            ForeignKeyMetadata(
                                column=col.name,
                                references_table=matched_table,
                                references_column="id",
                            ),
                            domain,
                        )
                        implicit.append(RelationalEdge(
                            from_table=table.name,
                            to_table=matched_table,
                            from_column=col.name,
                            to_column="id",
                            role=role,
                            cardinality="one_to_many",
                            state_propagation=self._determine_state_propagation(
                                table, parent_meta,
                                ForeignKeyMetadata(
                                    column=col.name,
                                    references_table=matched_table,
                                    references_column="id",
                                ),
                                role,
                            ),
                            confidence=0.5,  # Lower confidence for inferred
                            business_context=f"{table.name} implicitly references {matched_table} via {col.name}",
                        ))
                        existing_pairs.add((table.name, matched_table))

        return implicit

    def _detect_entity_chains(
        self,
        schema: SchemaMetadata,
        edges: list[RelationalEdge],
        domain: str,
    ) -> list[list[str]]:
        """Detect ordered entity chains in the schema.

        An entity chain represents a business flow:
        customer → account → transaction
        policy → claim → payment
        """
        # Start from known domain chains and match against actual tables
        known_chains = _DOMAIN_ENTITY_CHAINS.get(domain, [])
        table_names_lower = {t.name.lower(): t.name for t in schema.tables}

        matched_chains: list[list[str]] = []

        for template_chain in known_chains:
            matched: list[str] = []
            for entity in template_chain:
                # Try exact match, plural, or substring
                actual = (
                    table_names_lower.get(entity)
                    or table_names_lower.get(entity + "s")
                    or table_names_lower.get(entity + "es")
                    or self._fuzzy_table_match(entity, table_names_lower)
                )
                if actual:
                    matched.append(actual)
                else:
                    break  # Chain is broken

            if len(matched) >= 2:
                matched_chains.append(matched)

        # Also discover chains from edge relationships
        edge_chains = self._discover_chains_from_edges(edges)
        for chain in edge_chains:
            if chain not in matched_chains and len(chain) >= 2:
                matched_chains.append(chain)

        return matched_chains

    def _fuzzy_table_match(self, entity: str, table_map: dict[str, str]) -> str | None:
        """Fuzzy match an entity name against table names."""
        for tn_lower, tn_actual in table_map.items():
            if entity in tn_lower or tn_lower in entity:
                return tn_actual
            if _singularize(tn_lower) == entity:
                return tn_actual
        return None

    def _discover_chains_from_edges(self, edges: list[RelationalEdge]) -> list[list[str]]:
        """Discover entity chains by following edge paths."""
        # Build adjacency: child → parent
        child_to_parent: dict[str, list[str]] = {}
        for edge in edges:
            if edge.role in (RelationshipRole.LOOKUP_REFERENCE, RelationshipRole.JUNCTION):
                continue
            child_to_parent.setdefault(edge.from_table, []).append(edge.to_table)

        # Find all tables that are leaves (have parents but aren't parents themselves)
        all_parents = {p for parents in child_to_parent.values() for p in parents}
        all_children = set(child_to_parent.keys())
        leaves = all_children - all_parents

        # Walk from each leaf up to the root
        chains: list[list[str]] = []
        for leaf in leaves:
            chain = [leaf]
            visited = {leaf}
            current = leaf
            while current in child_to_parent:
                parents = child_to_parent[current]
                # Pick the parent that isn't a lookup
                next_parent = None
                for p in parents:
                    if p not in visited:
                        next_parent = p
                        break
                if not next_parent:
                    break
                chain.append(next_parent)
                visited.add(next_parent)
                current = next_parent

            if len(chain) >= 2:
                chains.append(list(reversed(chain)))  # Root first

        return chains

    def _derive_state_constraints(
        self,
        edges: list[RelationalEdge],
        table_map: dict[str, TableMetadata],
        domain: str,
    ) -> list[StateConstraint]:
        """Derive state constraints from relationships.

        When a parent is in a terminal state, child rows should be constrained.
        """
        constraints: list[StateConstraint] = []

        for edge in edges:
            if edge.state_propagation == "none":
                continue

            parent_meta = table_map.get(edge.to_table)
            child_meta = table_map.get(edge.from_table)
            if not parent_meta or not child_meta:
                continue

            parent_status = self._find_status_column(parent_meta)
            child_status = self._find_status_column(child_meta)

            if not parent_status:
                continue

            # Get valid states from check constraints
            parent_states = self._extract_states(parent_meta, parent_status)
            child_states = self._extract_states(child_meta, child_status) if child_status else []

            # Generate constraints for terminal negative parent states
            for state in parent_states:
                if state.lower() in _TERMINAL_NEGATIVE_STATES:
                    allowed = [s for s in child_states if s.lower() in _NEGATIVE_PARENT_ALLOWS_CHILD]
                    forbidden = [s for s in child_states if s.lower() in (_ACTIVE_STATES | _PENDING_STATES)]

                    if allowed or forbidden:
                        constraints.append(StateConstraint(
                            parent_table=edge.to_table,
                            parent_status_column=parent_status,
                            parent_state=state,
                            child_table=edge.from_table,
                            child_status_column=child_status,
                            allowed_child_states=allowed if allowed else child_states,
                            forbidden_child_states=forbidden,
                            explanation=(
                                f"When {edge.to_table}.{parent_status} is '{state}', "
                                f"{edge.from_table} should not be in active/pending states"
                            ),
                        ))

                elif state.lower() in _PENDING_STATES:
                    forbidden = [s for s in child_states if s.lower() in _TERMINAL_POSITIVE_STATES]
                    if forbidden:
                        constraints.append(StateConstraint(
                            parent_table=edge.to_table,
                            parent_status_column=parent_status,
                            parent_state=state,
                            child_table=edge.from_table,
                            child_status_column=child_status,
                            allowed_child_states=[],  # empty means no restriction besides forbidden
                            forbidden_child_states=forbidden,
                            explanation=(
                                f"When {edge.to_table}.{parent_status} is '{state}', "
                                f"{edge.from_table} should not be in terminal positive states"
                            ),
                        ))

        return constraints

    def _build_propagation_rules(
        self,
        edges: list[RelationalEdge],
        table_map: dict[str, TableMetadata],
        state_constraints: list[StateConstraint],
    ) -> list[ScenarioPropagation]:
        """Build scenario propagation rules from edges and constraints."""
        propagations: list[ScenarioPropagation] = []

        for edge in edges:
            if edge.state_propagation == "none":
                continue

            rules: list[dict[str, Any]] = []
            parent_meta = table_map.get(edge.to_table)
            child_meta = table_map.get(edge.from_table)
            if not parent_meta or not child_meta:
                continue

            # State inheritance rules
            if edge.state_propagation == "inherits":
                parent_status = self._find_status_column(parent_meta)
                child_status = self._find_status_column(child_meta)
                if parent_status and child_status:
                    rules.append({
                        "rule_type": "state_mirror",
                        "source_column": f"{edge.to_table}.{parent_status}",
                        "target_column": f"{edge.from_table}.{child_status}",
                        "description": "Child state should mirror or follow parent state",
                    })

            # Constraint rules
            if edge.state_propagation == "constrains":
                relevant = [c for c in state_constraints
                            if c.parent_table == edge.to_table and c.child_table == edge.from_table]
                for c in relevant:
                    rules.append({
                        "rule_type": "state_constraint",
                        "trigger": f"{c.parent_table}.{c.parent_status_column} = '{c.parent_state}'",
                        "forbidden": c.forbidden_child_states,
                        "allowed": c.allowed_child_states if c.allowed_child_states else None,
                    })

            # Temporal ordering rules
            parent_temporal = [c.name for c in parent_meta.columns
                              if re.search(r"_at$|_on$|_date$|created|updated", c.name, re.I)]
            child_temporal = [c.name for c in child_meta.columns
                             if re.search(r"_at$|_on$|_date$|created|updated", c.name, re.I)]
            if parent_temporal and child_temporal:
                rules.append({
                    "rule_type": "temporal_ordering",
                    "description": f"{edge.from_table} timestamps must be >= {edge.to_table} creation",
                    "parent_reference": parent_temporal[0],
                    "child_reference": child_temporal[0],
                })

            if rules:
                propagations.append(ScenarioPropagation(
                    parent_table=edge.to_table,
                    child_table=edge.from_table,
                    propagation_type=edge.state_propagation,
                    rules=rules,
                ))

        return propagations

    def _find_root_entities(
        self, edges: list[RelationalEdge], table_map: dict[str, TableMetadata]
    ) -> list[str]:
        """Find tables that are only parents (not children) — entity roots."""
        children = {e.from_table for e in edges}
        parents = {e.to_table for e in edges}
        roots = parents - children
        # Also include tables with no relationships if they look like master entities
        all_tables = set(table_map.keys())
        orphans = all_tables - children - parents
        for t in orphans:
            if _MASTER_PAT.search(t):
                roots.add(t)
        return sorted(roots)

    def _find_terminal_entities(
        self, edges: list[RelationalEdge], table_map: dict[str, TableMetadata]
    ) -> list[str]:
        """Find tables that are only children (not parents) — leaf entities."""
        children = {e.from_table for e in edges}
        parents = {e.to_table for e in edges}
        terminals = children - parents
        return sorted(terminals)

    def _find_status_column(self, table: TableMetadata) -> str | None:
        """Find the primary status column in a table."""
        for col in table.columns:
            if _STATUS_COL_PAT.search(col.name):
                return col.name
        return None

    def _extract_states(self, table: TableMetadata, status_col: str | None) -> list[str]:
        """Extract valid states from check constraints."""
        if not status_col:
            return []
        col_meta = next((c for c in table.columns if c.name == status_col), None)
        if not col_meta or not col_meta.check_constraint:
            return []

        from app.utils.sql_types import extract_enum_from_check
        return extract_enum_from_check(col_meta.check_constraint) or []


# ── Helpers ───────────────────────────────────────────────────

def _singularize(word: str) -> str:
    """Simple English singularization."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# ── Module-level singleton ────────────────────────────────────

_engine: RelationalContextEngine | None = None


def _get_engine() -> RelationalContextEngine:
    global _engine
    if _engine is None:
        _engine = RelationalContextEngine()
    return _engine


# ── Public API ────────────────────────────────────────────────

def analyze_relational_context(
    schema: SchemaMetadata,
    domain: str = "unknown",
) -> dict[str, Any]:
    """Analyze the full relational context of a schema.

    Returns a comprehensive understanding of cross-table relationships,
    including business roles, state constraints, and propagation rules.
    """
    engine = _get_engine()
    ctx = engine.analyze(schema, domain=domain)
    return ctx.to_dict()


def get_state_constraints(
    schema: SchemaMetadata,
    child_table: str,
    parent_data: dict[str, list[dict[str, Any]]],
    domain: str = "unknown",
) -> dict[str, Any]:
    """Get state constraints for a child table based on parent data.

    Used during generation to determine what scenarios are allowed
    for child rows given the parent entity's current state.
    """
    engine = _get_engine()
    return engine.get_parent_state_constraints(schema, child_table, parent_data, domain)


def propagate_parent_scenario(
    schema: SchemaMetadata,
    parent_table: str,
    child_table: str,
    parent_rows: list[dict[str, Any]],
    domain: str = "unknown",
) -> list[dict[str, Any]]:
    """Propagate parent scenario context to child generation hints.

    Returns per-parent-row hints that should constrain how child rows
    linked to that parent are generated.
    """
    engine = _get_engine()
    return engine.propagate_scenario(schema, parent_table, child_table, parent_rows, domain)


def get_entity_chains(
    schema: SchemaMetadata,
    domain: str = "unknown",
) -> list[list[str]]:
    """Get detected entity chains in the schema."""
    engine = _get_engine()
    ctx = engine.analyze(schema, domain=domain)
    return ctx.entity_chains


def get_relationship_graph(
    schema: SchemaMetadata,
    domain: str = "unknown",
) -> list[dict[str, Any]]:
    """Get the classified relationship graph."""
    engine = _get_engine()
    ctx = engine.analyze(schema, domain=domain)
    return [e.to_dict() for e in ctx.edges]
