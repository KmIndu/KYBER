import pytest
from pathlib import Path

from app.parsers.sql_parser import parse_sql_schema
from app.services.relationship_engine import (
    RelationshipGraph,
    CircularDependencyError,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _load_sample_schema():
    sql = (FIXTURES / "sample_schema.sql").read_text(encoding="utf-8")
    return parse_sql_schema(sql)


def _make_schema_with_cycle():
    sql = """
    CREATE TABLE a (
        id INT PRIMARY KEY,
        b_id INT,
        FOREIGN KEY (b_id) REFERENCES b(id)
    );
    CREATE TABLE b (
        id INT PRIMARY KEY,
        a_id INT,
        FOREIGN KEY (a_id) REFERENCES a(id)
    );
    """
    return parse_sql_schema(sql)


def _make_single_table():
    sql = "CREATE TABLE standalone (id INT PRIMARY KEY, name VARCHAR(100));"
    return parse_sql_schema(sql)


def _make_self_ref():
    sql = """
    CREATE TABLE employee (
        id INT PRIMARY KEY,
        manager_id INT,
        FOREIGN KEY (manager_id) REFERENCES employee(id)
    );
    """
    return parse_sql_schema(sql)


# ── Graph construction ────────────────────────────────────────


class TestGraphConstruction:
    def test_all_tables_as_nodes(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert set(graph.graph.nodes) == {"customers", "policies", "claims", "payments"}

    def test_edge_count(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.graph.number_of_edges() == 3

    def test_edges_represent_fk(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.graph.has_edge("policies", "customers")
        assert graph.graph.has_edge("claims", "policies")
        assert graph.graph.has_edge("payments", "claims")

    def test_no_reverse_edges(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert not graph.graph.has_edge("customers", "policies")


# ── Generation order ──────────────────────────────────────────


class TestGenerationOrder:
    def test_order_parents_first(self):
        graph = RelationshipGraph(_load_sample_schema())
        order = graph.get_generation_order()
        assert order.index("customers") < order.index("policies")
        assert order.index("policies") < order.index("claims")
        assert order.index("claims") < order.index("payments")

    def test_order_is_complete(self):
        graph = RelationshipGraph(_load_sample_schema())
        order = graph.get_generation_order()
        assert len(order) == 4

    def test_exact_order(self):
        graph = RelationshipGraph(_load_sample_schema())
        order = graph.get_generation_order()
        assert order == ["customers", "policies", "claims", "payments"]

    def test_single_table(self):
        graph = RelationshipGraph(_make_single_table())
        order = graph.get_generation_order()
        assert order == ["standalone"]


# ── Parent / child queries ────────────────────────────────────


class TestParentChild:
    def test_parent_tables(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.get_parent_tables("policies") == ["customers"]

    def test_child_tables(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.get_child_tables("customers") == ["policies"]

    def test_root_tables(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.get_root_tables() == ["customers"]

    def test_leaf_tables(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.get_leaf_tables() == ["payments"]

    def test_unknown_table(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.get_parent_tables("nonexistent") == []
        assert graph.get_child_tables("nonexistent") == []


# ── Circular dependency detection ─────────────────────────────


class TestCircularDependencies:
    def test_no_cycle_in_sample(self):
        graph = RelationshipGraph(_load_sample_schema())
        assert graph.has_circular_dependencies() is False

    def test_cycle_detected(self):
        graph = RelationshipGraph(_make_schema_with_cycle())
        assert graph.has_circular_dependencies() is True

    def test_get_cycles(self):
        graph = RelationshipGraph(_make_schema_with_cycle())
        cycles = graph.get_circular_dependencies()
        assert len(cycles) >= 1
        # Cycle should contain both a and b
        flat = [item for cycle in cycles for item in cycle]
        assert "a" in flat
        assert "b" in flat

    def test_generation_order_raises_on_cycle(self):
        graph = RelationshipGraph(_make_schema_with_cycle())
        with pytest.raises(CircularDependencyError):
            graph.get_generation_order()


# ── Self-referencing tables ───────────────────────────────────


class TestSelfReference:
    def test_self_ref_detected(self):
        graph = RelationshipGraph(_make_self_ref())
        assert graph.graph.has_edge("employee", "employee")

    def test_self_ref_has_cycle(self):
        graph = RelationshipGraph(_make_self_ref())
        assert graph.has_circular_dependencies() is True

    def test_self_ref_in_validation(self):
        graph = RelationshipGraph(_make_self_ref())
        issues = graph.validate()
        assert any("Self-referencing" in i for i in issues)


# ── Edge details ──────────────────────────────────────────────


class TestEdgeDetails:
    def test_edge_detail_content(self):
        graph = RelationshipGraph(_load_sample_schema())
        edges = graph.get_edge_details()
        assert len(edges) == 3
        policy_edge = next(e for e in edges if e["child_table"] == "policies")
        assert policy_edge["parent_table"] == "customers"
        assert policy_edge["child_column"] == "customer_id"
        assert policy_edge["parent_column"] == "customer_id"


# ── Validation ────────────────────────────────────────────────


class TestValidation:
    def test_clean_schema_no_issues(self):
        graph = RelationshipGraph(_load_sample_schema())
        issues = graph.validate()
        assert issues == []

    def test_cycle_reported(self):
        graph = RelationshipGraph(_make_schema_with_cycle())
        issues = graph.validate()
        assert any("Circular" in i for i in issues)

    def test_isolated_table_reported(self):
        graph = RelationshipGraph(_make_single_table())
        issues = graph.validate()
        assert any("Isolated" in i for i in issues)


# ── Visualization ─────────────────────────────────────────────


class TestVisualization:
    def test_ascii_output(self):
        graph = RelationshipGraph(_load_sample_schema())
        ascii_out = graph.to_ascii()
        assert "customers" in ascii_out
        assert "payments" in ascii_out

    def test_adjacency_dict(self):
        graph = RelationshipGraph(_load_sample_schema())
        adj = graph.to_adjacency_dict()
        assert adj["policies"] == ["customers"]
        assert adj["customers"] == []

    def test_empty_graph(self):
        from app.models.schema import SchemaMetadata
        graph = RelationshipGraph(SchemaMetadata(tables=[]))
        assert graph.to_ascii() == "(empty graph)"
        assert graph.to_adjacency_dict() == {}
