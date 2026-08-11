"""Tests for referential integrity engine and router."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.integrity import IntegrityIssueType
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.integrity_engine import ReferentialIntegrityEngine
from app.services.session_store import store

client = TestClient(app)


# ── Helpers ────────────────────────────────────────────────────


def _make_valid_schema() -> SchemaMetadata:
    """Schema with valid FK relationships: users → orders → order_items."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="users",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="name", data_type="varchar(50)"),
            ],
        ),
        TableMetadata(
            name="orders",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="user_id", data_type="integer"),
                ColumnMetadata(name="total", data_type="decimal"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="user_id", references_table="users", references_column="id"),
            ],
        ),
        TableMetadata(
            name="order_items",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="order_id", data_type="integer"),
                ColumnMetadata(name="product", data_type="varchar(100)"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="order_id", references_table="orders", references_column="id"),
            ],
        ),
    ])


def _make_circular_schema() -> SchemaMetadata:
    """Schema with circular dependency: A → B → A."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="table_a",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="b_id", data_type="integer"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="b_id", references_table="table_b", references_column="id"),
            ],
        ),
        TableMetadata(
            name="table_b",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="a_id", data_type="integer"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="a_id", references_table="table_a", references_column="id"),
            ],
        ),
    ])


def _make_broken_fk_schema() -> SchemaMetadata:
    """Schema with FK referencing non-existent table."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="orders",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="customer_id", data_type="integer"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
            ],
        ),
    ])


def _make_broken_column_schema() -> SchemaMetadata:
    """Schema with FK referencing non-existent column."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="users",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="name", data_type="varchar(50)"),
            ],
        ),
        TableMetadata(
            name="orders",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="user_id", data_type="integer"),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="user_id", references_table="users", references_column="user_code"),
            ],
        ),
    ])


def _make_self_ref_schema() -> SchemaMetadata:
    """Schema with self-referencing FK (e.g., employee → manager)."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="employees",
            columns=[
                ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                ColumnMetadata(name="manager_id", data_type="integer", nullable=True),
            ],
            foreign_keys=[
                ForeignKeyMetadata(column="manager_id", references_table="employees", references_column="id"),
            ],
        ),
    ])


# ── Engine Unit Tests ──────────────────────────────────────────


class TestReferentialIntegrityEngine:
    """Unit tests for ReferentialIntegrityEngine."""

    def test_valid_schema_no_issues(self):
        engine = ReferentialIntegrityEngine(_make_valid_schema())
        report = engine.validate_schema()
        assert report.valid is True
        assert report.errors == 0
        # May have info-level isolated tables
        assert all(i.severity != "error" for i in report.issues)

    def test_generation_order_parents_first(self):
        engine = ReferentialIntegrityEngine(_make_valid_schema())
        order = engine.get_generation_order()
        assert order.index("users") < order.index("orders")
        assert order.index("orders") < order.index("order_items")

    def test_circular_dependency_detected(self):
        engine = ReferentialIntegrityEngine(_make_circular_schema())
        report = engine.validate_schema()
        assert report.valid is False
        assert report.errors > 0
        assert len(report.cycles) > 0
        circular_issues = [i for i in report.issues if i.issue_type == IntegrityIssueType.CIRCULAR_DEPENDENCY]
        assert len(circular_issues) > 0

    def test_missing_parent_table_detected(self):
        engine = ReferentialIntegrityEngine(_make_broken_fk_schema())
        report = engine.validate_schema()
        assert report.valid is False
        missing = [i for i in report.issues if i.issue_type == IntegrityIssueType.MISSING_PARENT_TABLE]
        assert len(missing) == 1
        assert missing[0].table == "orders"
        assert missing[0].related_table == "customers"

    def test_missing_parent_column_detected(self):
        engine = ReferentialIntegrityEngine(_make_broken_column_schema())
        report = engine.validate_schema()
        assert report.valid is False
        missing = [i for i in report.issues if i.issue_type == IntegrityIssueType.MISSING_PARENT_COLUMN]
        assert len(missing) == 1
        assert missing[0].related_column == "user_code"

    def test_self_reference_detected(self):
        engine = ReferentialIntegrityEngine(_make_self_ref_schema())
        report = engine.validate_schema()
        self_refs = [i for i in report.issues if i.issue_type == IntegrityIssueType.SELF_REFERENCE]
        assert len(self_refs) == 1
        assert self_refs[0].severity == "warning"
        assert self_refs[0].table == "employees"

    def test_isolated_table_detected(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="users",
                columns=[ColumnMetadata(name="id", data_type="integer", is_primary_key=True)],
            ),
            TableMetadata(
                name="logs",
                columns=[ColumnMetadata(name="id", data_type="integer", is_primary_key=True)],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                    ColumnMetadata(name="user_id", data_type="integer"),
                ],
                foreign_keys=[
                    ForeignKeyMetadata(column="user_id", references_table="users", references_column="id"),
                ],
            ),
        ])
        engine = ReferentialIntegrityEngine(schema)
        report = engine.validate_schema()
        isolated = [i for i in report.issues if i.issue_type == IntegrityIssueType.ISOLATED_TABLE]
        assert len(isolated) == 1
        assert isolated[0].table == "logs"

    def test_orphan_rows_detected(self):
        schema = _make_valid_schema()
        engine = ReferentialIntegrityEngine(schema)
        data = {
            "users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            "orders": [
                {"id": 1, "user_id": 1, "total": 100},
                {"id": 2, "user_id": 999, "total": 50},  # orphan
            ],
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        report = engine.validate_data(data)
        orphans = [i for i in report.issues if i.issue_type == IntegrityIssueType.ORPHAN_ROW]
        assert len(orphans) == 1
        assert orphans[0].table == "orders"
        assert orphans[0].value == "999"
        assert orphans[0].row_index == 1

    def test_no_orphans_in_valid_data(self):
        schema = _make_valid_schema()
        engine = ReferentialIntegrityEngine(schema)
        data = {
            "users": [{"id": 1, "name": "Alice"}],
            "orders": [{"id": 1, "user_id": 1, "total": 100}],
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        report = engine.validate_data(data)
        orphans = [i for i in report.issues if i.issue_type == IntegrityIssueType.ORPHAN_ROW]
        assert len(orphans) == 0

    def test_dangling_references_detected(self):
        schema = _make_valid_schema()
        engine = ReferentialIntegrityEngine(schema)
        data = {
            "users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            "orders": [{"id": 1, "user_id": 1, "total": 100}],  # user 2 unreferenced
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        report = engine.validate_data(data)
        dangling = [i for i in report.issues if i.issue_type == IntegrityIssueType.DANGLING_REFERENCE]
        assert len(dangling) >= 1
        assert any(i.value == "2" for i in dangling)

    def test_parent_child_map(self):
        engine = ReferentialIntegrityEngine(_make_valid_schema())
        pc_map = engine.get_parent_child_map()
        assert "orders" in pc_map.get("users", [])
        assert "order_items" in pc_map.get("orders", [])

    def test_report_includes_edges(self):
        engine = ReferentialIntegrityEngine(_make_valid_schema())
        report = engine.validate_schema()
        assert len(report.dependency_edges) == 2
        assert len(report.root_tables) > 0
        assert "users" in report.root_tables

    def test_report_generation_order_on_cycle(self):
        engine = ReferentialIntegrityEngine(_make_circular_schema())
        report = engine.validate_schema()
        assert report.generation_order == []  # Can't determine order with cycles

    def test_nullable_fk_not_flagged_as_orphan(self):
        schema = _make_valid_schema()
        engine = ReferentialIntegrityEngine(schema)
        data = {
            "users": [{"id": 1, "name": "Alice"}],
            "orders": [{"id": 1, "user_id": None, "total": 100}],  # nullable FK
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        report = engine.validate_data(data)
        orphans = [i for i in report.issues if i.issue_type == IntegrityIssueType.ORPHAN_ROW]
        assert len(orphans) == 0


# ── Router Integration Tests ───────────────────────────────────


class TestIntegrityRouter:
    """Integration tests for /integrity endpoints."""

    def test_validate_schema_success(self):
        session = store.create()
        session.schema = _make_valid_schema()
        resp = client.post(f"/integrity/validate-schema?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert "generation_order" in data
        assert "dependency_edges" in data

    def test_validate_schema_with_issues(self):
        session = store.create()
        session.schema = _make_circular_schema()
        resp = client.post(f"/integrity/validate-schema?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["errors"] > 0
        assert len(data["cycles"]) > 0

    def test_validate_data_success(self):
        session = store.create()
        session.schema = _make_valid_schema()
        session.data = {
            "users": [{"id": 1, "name": "Alice"}],
            "orders": [{"id": 1, "user_id": 1, "total": 100}],
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        resp = client.post(f"/integrity/validate-data?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_validate_data_with_orphans(self):
        session = store.create()
        session.schema = _make_valid_schema()
        session.data = {
            "users": [{"id": 1, "name": "Alice"}],
            "orders": [{"id": 1, "user_id": 999, "total": 100}],
            "order_items": [{"id": 1, "order_id": 1, "product": "Widget"}],
        }
        resp = client.post(f"/integrity/validate-data?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        orphans = [i for i in data["issues"] if i["issue_type"] == "orphan_row"]
        assert len(orphans) == 1

    def test_validate_schema_no_session(self):
        resp = client.post("/integrity/validate-schema?session_id=nonexistent")
        assert resp.status_code == 404

    def test_validate_schema_no_schema(self):
        session = store.create()
        resp = client.post(f"/integrity/validate-schema?session_id={session.session_id}")
        assert resp.status_code == 400

    def test_validate_data_no_data(self):
        session = store.create()
        session.schema = _make_valid_schema()
        resp = client.post(f"/integrity/validate-data?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No generated data" in resp.json()["detail"]
