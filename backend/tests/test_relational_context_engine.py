"""Tests for the Relational Context Understanding Engine."""

import pytest

from app.models.schema import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata
from app.generators.relational_context_engine import (
    RelationalContextEngine,
    RelationalEdge,
    RelationshipRole,
    analyze_relational_context,
    get_entity_chains,
    get_relationship_graph,
    get_state_constraints,
    propagate_parent_scenario,
)


# ── Test Fixtures ─────────────────────────────────────────────

def _insurance_schema() -> SchemaMetadata:
    """Insurance domain: customers → policies → claims → payments."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="customers",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="full_name", data_type="VARCHAR(100)"),
                ColumnMetadata(name="email", data_type="VARCHAR(100)"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('active','inactive','suspended')",
                ),
            ],
            foreign_keys=[],
        ),
        TableMetadata(
            name="policies",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="customer_id", data_type="INTEGER"),
                ColumnMetadata(name="policy_number", data_type="VARCHAR(20)"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('active','cancelled','expired','in_force','lapsed')",
                ),
                ColumnMetadata(name="premium", data_type="DECIMAL(10,2)"),
                ColumnMetadata(name="created_at", data_type="TIMESTAMP"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
            ],
        ),
        TableMetadata(
            name="claims",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="policy_id", data_type="INTEGER"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('pending','approved','rejected','settled','closed')",
                ),
                ColumnMetadata(name="amount", data_type="DECIMAL(10,2)"),
                ColumnMetadata(name="submitted_at", data_type="TIMESTAMP"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="policy_id", references_table="policies", references_column="id"),
            ],
        ),
        TableMetadata(
            name="payments",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="claim_id", data_type="INTEGER"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('pending','completed','failed','reversed')",
                ),
                ColumnMetadata(name="amount", data_type="DECIMAL(10,2)"),
                ColumnMetadata(name="paid_at", data_type="TIMESTAMP"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="claim_id", references_table="claims", references_column="id"),
            ],
        ),
    ])


def _ecommerce_schema() -> SchemaMetadata:
    """Ecommerce: customers → orders → order_items."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="customers",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="name", data_type="VARCHAR(100)"),
                ColumnMetadata(name="email", data_type="VARCHAR(100)"),
            ],
            foreign_keys=[],
        ),
        TableMetadata(
            name="orders",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="customer_id", data_type="INTEGER"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('pending','shipped','delivered','cancelled')",
                ),
                ColumnMetadata(name="total", data_type="DECIMAL(10,2)"),
                ColumnMetadata(name="created_at", data_type="TIMESTAMP"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
            ],
        ),
        TableMetadata(
            name="order_items",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="order_id", data_type="INTEGER"),
                ColumnMetadata(name="product_name", data_type="VARCHAR(100)"),
                ColumnMetadata(name="quantity", data_type="INTEGER"),
                ColumnMetadata(name="price", data_type="DECIMAL(10,2)"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="order_id", references_table="orders", references_column="id"),
            ],
        ),
    ])


def _implicit_schema() -> SchemaMetadata:
    """Schema with implicit relationships (no FK, naming conventions only)."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="accounts",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="name", data_type="VARCHAR(100)"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('active','closed','suspended')",
                ),
            ],
            foreign_keys=[],
        ),
        TableMetadata(
            name="transactions",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(name="account_id", data_type="INTEGER"),
                ColumnMetadata(name="amount", data_type="DECIMAL(10,2)"),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('pending','completed','failed')",
                ),
            ],
            foreign_keys=[],  # No explicit FK
        ),
    ])


# ── Test Classes ──────────────────────────────────────────────

class TestRelationshipGraph:
    """Test relationship graph construction."""

    def test_edges_detected_from_fks(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        assert result["summary"]["total_relationships"] >= 3

    def test_edge_roles_classified(self):
        schema = _insurance_schema()
        edges = get_relationship_graph(schema, domain="insurance")
        roles = {e["role"] for e in edges}
        # Should detect various business roles
        assert len(roles) >= 2

    def test_customer_is_root_entity(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        assert "customers" in result["root_entities"]

    def test_payments_is_terminal_entity(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        assert "payments" in result["terminal_entities"]

    def test_state_propagation_detected(self):
        schema = _insurance_schema()
        edges = get_relationship_graph(schema, domain="insurance")
        propagation_types = {e["state_propagation"] for e in edges}
        # Should have at least one edge with state propagation
        assert propagation_types - {"none"}, "Should detect state propagation in insurance schema"

    def test_cardinality_is_correct(self):
        schema = _insurance_schema()
        edges = get_relationship_graph(schema, domain="insurance")
        for edge in edges:
            assert edge["cardinality"] in ("one_to_many", "one_to_one", "many_to_many")


class TestImplicitRelationships:
    """Test inference of implicit relationships from naming."""

    def test_detects_implicit_fk(self):
        schema = _implicit_schema()
        edges = get_relationship_graph(schema, domain="banking")
        # Should detect transactions.account_id → accounts.id
        assert any(
            e["from_table"] == "transactions" and e["to_table"] == "accounts"
            for e in edges
        )

    def test_implicit_has_lower_confidence(self):
        schema = _implicit_schema()
        edges = get_relationship_graph(schema, domain="banking")
        implicit_edge = next(
            (e for e in edges if e["from_table"] == "transactions"), None
        )
        assert implicit_edge is not None
        assert implicit_edge["confidence"] <= 0.6


class TestEntityChains:
    """Test entity chain detection."""

    def test_insurance_chain_detected(self):
        schema = _insurance_schema()
        chains = get_entity_chains(schema, domain="insurance")
        # Should find at least one chain with 2+ tables
        assert len(chains) >= 1
        assert all(len(c) >= 2 for c in chains)

    def test_chain_ordering_root_first(self):
        schema = _insurance_schema()
        chains = get_entity_chains(schema, domain="insurance")
        # In insurance, customer/policy should come before claims/payments
        for chain in chains:
            if "customers" in chain and "claims" in chain:
                assert chain.index("customers") < chain.index("claims")

    def test_ecommerce_chain(self):
        schema = _ecommerce_schema()
        chains = get_entity_chains(schema, domain="ecommerce")
        assert len(chains) >= 1


class TestStateConstraints:
    """Test state constraint derivation."""

    def test_cancelled_policy_constrains_claims(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        constraints = result["state_constraints"]

        # Find constraints where cancelled policy affects claims
        cancelled_constraints = [
            c for c in constraints
            if c["parent_table"] == "policies"
            and c["parent_state"] in ("cancelled", "expired", "lapsed")
            and c["child_table"] == "claims"
        ]
        assert len(cancelled_constraints) >= 1

    def test_forbidden_states_are_active(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        constraints = result["state_constraints"]

        for c in constraints:
            # Terminal negative parent states should forbid active child states
            if c["parent_state"] in ("cancelled", "expired", "lapsed"):
                # Should forbid at least some active/pending states
                assert len(c["forbidden_child_states"]) > 0

    def test_pending_parent_constrains_positive_child(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        constraints = result["state_constraints"]

        pending_constraints = [
            c for c in constraints
            if c["parent_state"] == "pending"
        ]
        for c in pending_constraints:
            # pending parent should forbid settled/completed child
            forbidden_lower = {f.lower() for f in c["forbidden_child_states"]}
            assert forbidden_lower & {"completed", "settled", "approved"}


class TestScenarioPropagation:
    """Test parent-child scenario propagation."""

    def test_propagation_for_cancelled_parent(self):
        schema = _insurance_schema()
        parent_rows = [
            {"id": 1, "status": "cancelled", "customer_id": 1},
            {"id": 2, "status": "active", "customer_id": 2},
            {"id": 3, "status": "expired", "customer_id": 3},
        ]
        results = propagate_parent_scenario(
            schema, "policies", "claims", parent_rows, domain="insurance"
        )
        assert len(results) == 3

        # Cancelled parent should produce forbidden/prefer hints
        cancelled_hint = results[0]
        assert cancelled_hint["parent_state"] == "cancelled"
        hints = cancelled_hint["child_scenario_hints"]
        assert hints.get("temporal_hint") == "parent_terminated"

    def test_propagation_for_active_parent(self):
        schema = _insurance_schema()
        parent_rows = [
            {"id": 1, "status": "active", "customer_id": 1},
        ]
        results = propagate_parent_scenario(
            schema, "policies", "claims", parent_rows, domain="insurance"
        )
        hints = results[0]["child_scenario_hints"]
        assert hints.get("temporal_hint") == "parent_active"

    def test_propagation_for_pending_parent(self):
        schema = _insurance_schema()
        parent_rows = [
            {"id": 1, "status": "pending", "customer_id": 1},
        ]
        results = propagate_parent_scenario(
            schema, "claims", "payments", parent_rows, domain="insurance"
        )
        hints = results[0]["child_scenario_hints"]
        assert hints.get("temporal_hint") == "parent_pending"


class TestStateConstraintLookup:
    """Test get_state_constraints with actual parent data."""

    def test_constraints_with_cancelled_parent(self):
        schema = _insurance_schema()
        parent_data = {
            "policies": [
                {"id": 1, "status": "cancelled"},
                {"id": 2, "status": "active"},
            ],
        }
        result = get_state_constraints(schema, "claims", parent_data, domain="insurance")
        assert result["child_table"] == "claims"
        # cancelled policy should produce forbidden states for claims
        assert len(result["forbidden_states"]) > 0

    def test_constraints_no_parent_data(self):
        schema = _insurance_schema()
        result = get_state_constraints(schema, "claims", {}, domain="insurance")
        assert result["constraints_applied"] >= 0


class TestRelationalContextOutput:
    """Test the full context output structure."""

    def test_output_has_all_fields(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        assert "domain" in result
        assert "relationship_graph" in result
        assert "entity_chains" in result
        assert "state_constraints" in result
        assert "scenario_propagations" in result
        assert "root_entities" in result
        assert "terminal_entities" in result
        assert "summary" in result

    def test_domain_is_detected(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="unknown")
        # Should detect insurance from table/column names
        assert result["domain"] != "unknown"

    def test_propagation_rules_have_structure(self):
        schema = _insurance_schema()
        result = analyze_relational_context(schema, domain="insurance")
        for prop in result["scenario_propagations"]:
            assert "parent_table" in prop
            assert "child_table" in prop
            assert "propagation_type" in prop
            assert "rules" in prop
            assert len(prop["rules"]) >= 1


class TestWorkflowChains:
    """Test workflow chain detection between lifecycle tables."""

    def test_claim_to_payment_is_workflow_chain(self):
        schema = _insurance_schema()
        edges = get_relationship_graph(schema, domain="insurance")
        # claims → payments should be detected as workflow chain or entity_transaction
        claim_payment_edge = next(
            (e for e in edges if e["from_table"] == "payments" and e["to_table"] == "claims"),
            None,
        )
        assert claim_payment_edge is not None
        assert claim_payment_edge["role"] in (
            RelationshipRole.WORKFLOW_CHAIN,
            RelationshipRole.ENTITY_TRANSACTION,
            RelationshipRole.PARENT_CHILD,
        )
