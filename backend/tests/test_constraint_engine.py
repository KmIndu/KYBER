"""Tests for constraint enforcement engine and router."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.constraint import ConstraintType, EnforcementReport
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.session_store import store
from app.validators.constraint_engine import (
    CompositeKeyEnforcer,
    ConstraintEnforcementEngine,
    EnumEnforcer,
    NullableEnforcer,
    RangeEnforcer,
    RegexEnforcer,
    UniqueEnforcer,
)

client = TestClient(app)


# ── Test Fixtures ─────────────────────────────────────────────


def _users_table() -> TableMetadata:
    return TableMetadata(
        name="users",
        columns=[
            ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
            ColumnMetadata(name="email", data_type="VARCHAR(100)", nullable=False, is_unique=True),
            ColumnMetadata(name="name", data_type="VARCHAR(50)", nullable=False),
            ColumnMetadata(name="age", data_type="INTEGER", nullable=True, check_constraint="age >= 0 AND age <= 150"),
            ColumnMetadata(
                name="status",
                data_type="VARCHAR(20)",
                nullable=False,
                check_constraint="status IN ('active', 'inactive', 'banned')",
            ),
            ColumnMetadata(name="bio", data_type="TEXT", nullable=True),
            ColumnMetadata(name="phone", data_type="VARCHAR(20)", nullable=True),
        ],
        primary_keys=["id"],
    )


def _orders_table() -> TableMetadata:
    return TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="order_id", data_type="INTEGER", nullable=False, is_primary_key=True),
            ColumnMetadata(name="user_id", data_type="INTEGER", nullable=False),
            ColumnMetadata(name="product_id", data_type="INTEGER", nullable=False),
            ColumnMetadata(name="quantity", data_type="INTEGER", nullable=False, check_constraint="quantity >= 1 AND quantity <= 1000"),
            ColumnMetadata(name="total", data_type="DECIMAL(10,2)", nullable=False, check_constraint="total >= 0.01 AND total <= 999999.99"),
        ],
        primary_keys=["order_id"],
        foreign_keys=[
            ForeignKeyMetadata(column="user_id", references_table="users", references_column="id"),
        ],
        unique_constraints=[["user_id", "product_id"]],
    )


def _composite_pk_table() -> TableMetadata:
    return TableMetadata(
        name="enrollments",
        columns=[
            ColumnMetadata(name="student_id", data_type="INTEGER", nullable=False, is_primary_key=True),
            ColumnMetadata(name="course_id", data_type="INTEGER", nullable=False, is_primary_key=True),
            ColumnMetadata(name="semester", data_type="VARCHAR(10)", nullable=False),
        ],
        primary_keys=["student_id", "course_id"],
    )


def _make_schema() -> SchemaMetadata:
    return SchemaMetadata(tables=[_users_table(), _orders_table(), _composite_pk_table()])


# ── NullableEnforcer Tests ────────────────────────────────────


class TestNullableEnforcer:
    def test_no_violations_when_valid(self):
        enforcer = NullableEnforcer()
        table = _users_table()
        rows = [
            {"id": 1, "email": "a@b.com", "name": "Alice", "age": 25, "status": "active", "bio": None, "phone": None},
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_detects_null_in_not_null_column(self):
        enforcer = NullableEnforcer()
        table = _users_table()
        rows = [
            {"id": 1, "email": None, "name": "Alice", "age": 25, "status": "active"},
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].columns == ["email"]
        assert violations[0].constraint_type == ConstraintType.NULLABLE

    def test_null_in_nullable_column_ok(self):
        enforcer = NullableEnforcer()
        table = _users_table()
        rows = [
            {"id": 1, "email": "a@b.com", "name": "Bob", "age": None, "status": "active"},
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_multiple_violations(self):
        enforcer = NullableEnforcer()
        table = _users_table()
        rows = [
            {"id": None, "email": None, "name": None, "status": None},
        ]
        violations = enforcer.enforce(table, rows)
        # id, email, name, status are NOT NULL
        assert len(violations) == 4

    def test_count_checks(self):
        enforcer = NullableEnforcer()
        table = _users_table()
        # NOT NULL columns: id, email, name, status = 4
        assert enforcer.count_checks(table, 10) == 40


# ── RegexEnforcer Tests ───────────────────────────────────────


class TestRegexEnforcer:
    def test_valid_email(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"email": "user@example.com"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_invalid_email(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"email": "not-an-email"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].constraint_type == ConstraintType.REGEX
        assert "email" in violations[0].columns

    def test_valid_phone(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"phone": "+1-555-1234", "email": "a@b.com"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_invalid_phone(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"phone": "abc-not-phone", "email": "a@b.com"}]
        violations = enforcer.enforce(table, rows)
        phone_violations = [v for v in violations if "phone" in v.columns]
        assert len(phone_violations) == 1

    def test_null_values_skipped(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"email": None, "phone": None}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_non_string_values_skipped(self):
        enforcer = RegexEnforcer()
        table = _users_table()
        rows = [{"email": 12345, "phone": 999}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_explicit_check_regex(self):
        enforcer = RegexEnforcer()
        table = TableMetadata(
            name="codes",
            columns=[
                ColumnMetadata(
                    name="code",
                    data_type="VARCHAR(10)",
                    check_constraint="code ~ '^[A-Z]{3}\\d{3}$'",
                ),
            ],
        )
        rows = [{"code": "ABC123"}, {"code": "invalid"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].row_index == 1

    def test_like_pattern(self):
        enforcer = RegexEnforcer()
        table = TableMetadata(
            name="items",
            columns=[
                ColumnMetadata(
                    name="sku",
                    data_type="VARCHAR(20)",
                    check_constraint="sku LIKE 'SKU-%'",
                ),
            ],
        )
        rows = [{"sku": "SKU-001"}, {"sku": "PROD-001"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].row_index == 1


# ── EnumEnforcer Tests ────────────────────────────────────────


class TestEnumEnforcer:
    def test_valid_enum_value(self):
        enforcer = EnumEnforcer()
        table = _users_table()
        rows = [{"status": "active"}, {"status": "inactive"}, {"status": "banned"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_invalid_enum_value(self):
        enforcer = EnumEnforcer()
        table = _users_table()
        rows = [{"status": "deleted"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].constraint_type == ConstraintType.ENUM
        assert "deleted" in violations[0].value

    def test_null_enum_skipped(self):
        enforcer = EnumEnforcer()
        table = _users_table()
        rows = [{"status": None}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_multiple_invalid(self):
        enforcer = EnumEnforcer()
        table = _users_table()
        rows = [{"status": "foo"}, {"status": "bar"}, {"status": "active"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 2


# ── UniqueEnforcer Tests ──────────────────────────────────────


class TestUniqueEnforcer:
    def test_no_duplicates(self):
        enforcer = UniqueEnforcer()
        table = _users_table()
        rows = [{"email": "a@b.com"}, {"email": "c@d.com"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_detects_duplicates(self):
        enforcer = UniqueEnforcer()
        table = _users_table()
        rows = [{"email": "a@b.com"}, {"email": "a@b.com"}, {"email": "c@d.com"}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].row_index == 1
        assert violations[0].constraint_type == ConstraintType.UNIQUE

    def test_null_doesnt_violate_unique(self):
        enforcer = UniqueEnforcer()
        table = _users_table()
        rows = [{"email": None}, {"email": None}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_pk_columns_excluded(self):
        enforcer = UniqueEnforcer()
        # Make id both PK and unique — shouldn't be checked by UniqueEnforcer
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True, is_unique=True)],
            primary_keys=["id"],
        )
        rows = [{"id": 1}, {"id": 1}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0  # PK uniqueness handled elsewhere


# ── RangeEnforcer Tests ───────────────────────────────────────


class TestRangeEnforcer:
    def test_value_within_range(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"age": 0}, {"age": 75}, {"age": 150}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_value_below_minimum(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"age": -1}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].constraint_type == ConstraintType.RANGE
        assert ">= 0" in violations[0].expected

    def test_value_above_maximum(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"age": 200}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert "<= 150" in violations[0].expected

    def test_string_length_within_limit(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"email": "x" * 100}]  # VARCHAR(100)
        violations = enforcer.enforce(table, rows)
        # email is VARCHAR(100), 100 chars is fine
        email_range = [v for v in violations if "email" in v.columns]
        assert len(email_range) == 0

    def test_string_exceeds_length(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"email": "x" * 101}]  # VARCHAR(100), 101 chars violates
        violations = enforcer.enforce(table, rows)
        email_range = [v for v in violations if "email" in v.columns]
        assert len(email_range) == 1
        assert "length" in email_range[0].message

    def test_decimal_range(self):
        enforcer = RangeEnforcer()
        table = _orders_table()
        rows = [{"total": 0.005}, {"quantity": 0}]  # Both below minimum
        violations = enforcer.enforce(table, rows)
        total_v = [v for v in violations if "total" in v.columns]
        qty_v = [v for v in violations if "quantity" in v.columns]
        assert len(total_v) == 1
        assert len(qty_v) == 1

    def test_null_values_skipped(self):
        enforcer = RangeEnforcer()
        table = _users_table()
        rows = [{"age": None}]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0


# ── CompositeKeyEnforcer Tests ────────────────────────────────


class TestCompositeKeyEnforcer:
    def test_no_duplicate_composite_pk(self):
        enforcer = CompositeKeyEnforcer()
        table = _composite_pk_table()
        rows = [
            {"student_id": 1, "course_id": 101, "semester": "Fall"},
            {"student_id": 1, "course_id": 102, "semester": "Fall"},
            {"student_id": 2, "course_id": 101, "semester": "Spring"},
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_duplicate_composite_pk(self):
        enforcer = CompositeKeyEnforcer()
        table = _composite_pk_table()
        rows = [
            {"student_id": 1, "course_id": 101, "semester": "Fall"},
            {"student_id": 1, "course_id": 101, "semester": "Spring"},  # Dup PK
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].constraint_type == ConstraintType.COMPOSITE_KEY
        assert violations[0].columns == ["student_id", "course_id"]

    def test_multi_column_unique_constraint(self):
        enforcer = CompositeKeyEnforcer()
        table = _orders_table()
        rows = [
            {"order_id": 1, "user_id": 1, "product_id": 10, "quantity": 1, "total": 10.0},
            {"order_id": 2, "user_id": 1, "product_id": 10, "quantity": 2, "total": 20.0},  # Dup
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 1
        assert violations[0].columns == ["user_id", "product_id"]

    def test_null_in_composite_key_skipped(self):
        enforcer = CompositeKeyEnforcer()
        table = _composite_pk_table()
        rows = [
            {"student_id": 1, "course_id": None, "semester": "Fall"},
            {"student_id": 1, "course_id": None, "semester": "Spring"},
        ]
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0

    def test_single_column_pk_not_checked(self):
        enforcer = CompositeKeyEnforcer()
        table = _users_table()  # Single-column PK
        rows = [{"id": 1}, {"id": 1}]  # Dup, but single PK not checked here
        violations = enforcer.enforce(table, rows)
        assert len(violations) == 0


# ── Full Engine Tests ─────────────────────────────────────────


class TestConstraintEnforcementEngine:
    def test_clean_data_full_compliance(self):
        schema = _make_schema()
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "users": [
                {"id": 1, "email": "alice@example.com", "name": "Alice", "age": 30, "status": "active", "bio": None, "phone": "+1-555-0001"},
                {"id": 2, "email": "bob@example.com", "name": "Bob", "age": 25, "status": "inactive", "bio": "Dev", "phone": "+1-555-0002"},
            ],
            "orders": [
                {"order_id": 1, "user_id": 1, "product_id": 10, "quantity": 5, "total": 49.99},
                {"order_id": 2, "user_id": 2, "product_id": 20, "quantity": 1, "total": 9.99},
            ],
            "enrollments": [
                {"student_id": 1, "course_id": 101, "semester": "Fall"},
                {"student_id": 1, "course_id": 102, "semester": "Fall"},
            ],
        }
        report = engine.enforce(data)
        assert report.total_violations == 0
        assert report.compliance_rate == 1.0
        assert report.total_rows == 6
        assert report.total_constraints_checked > 0

    def test_detects_multiple_violation_types(self):
        schema = SchemaMetadata(tables=[_users_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "users": [
                {"id": None, "email": "not-email", "name": "A", "age": -5, "status": "unknown", "phone": "abc"},
            ],
        }
        report = engine.enforce(data)
        assert report.total_violations > 0
        types_found = {v.constraint_type for v in report.violations}
        # Should have nullable (id=None), regex (email, phone), enum (status), range (age)
        assert ConstraintType.NULLABLE in types_found
        assert ConstraintType.REGEX in types_found
        assert ConstraintType.ENUM in types_found
        assert ConstraintType.RANGE in types_found

    def test_report_structure(self):
        schema = SchemaMetadata(tables=[_users_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "users": [
                {"id": 1, "email": "a@b.com", "name": "X", "age": 20, "status": "active", "phone": "+1-555"},
            ],
        }
        report = engine.enforce(data)
        assert len(report.tables) == 1
        assert report.tables[0].table == "users"
        assert report.tables[0].total_rows == 1
        assert len(report.summary_by_type) > 0

    def test_compliance_rate_calculation(self):
        schema = SchemaMetadata(tables=[_users_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "users": [
                {"id": 1, "email": "a@b.com", "name": "X", "age": 20, "status": "active", "phone": "+1-555"},
                {"id": 2, "email": "b@c.com", "name": "Y", "age": 200, "status": "active", "phone": "+1-555"},
            ],
        }
        report = engine.enforce(data)
        # age=200 violates range, so not 100%
        assert 0.0 < report.compliance_rate < 1.0

    def test_unknown_table_skipped(self):
        schema = SchemaMetadata(tables=[_users_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {"unknown_table": [{"col": "val"}]}
        report = engine.enforce(data)
        assert report.total_rows == 0
        assert report.total_violations == 0

    def test_summary_by_type(self):
        schema = SchemaMetadata(tables=[_users_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "users": [
                {"id": 1, "email": "a@b.com", "name": "X", "age": 20, "status": "active", "phone": "+1-555"},
            ],
        }
        report = engine.enforce(data)
        for summary in report.summary_by_type:
            assert summary.total_checks >= summary.passed
            assert summary.passed + summary.failed == summary.total_checks

    def test_composite_key_in_full_run(self):
        schema = SchemaMetadata(tables=[_composite_pk_table()])
        engine = ConstraintEnforcementEngine(schema)
        data = {
            "enrollments": [
                {"student_id": 1, "course_id": 101, "semester": "Fall"},
                {"student_id": 1, "course_id": 101, "semester": "Spring"},  # Dup composite PK
            ],
        }
        report = engine.enforce(data)
        composite_v = [v for v in report.violations if v.constraint_type == ConstraintType.COMPOSITE_KEY]
        assert len(composite_v) == 1


# ── Router Integration Tests ──────────────────────────────────


class TestConstraintsRouter:
    def test_enforce_success(self):
        session = store.create()
        session.schema = SchemaMetadata(tables=[_users_table()])
        session.data = {
            "users": [
                {"id": 1, "email": "a@b.com", "name": "Alice", "age": 25, "status": "active", "phone": "+1-555-1234"},
            ],
        }
        resp = client.post(f"/constraints/enforce?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_rows" in data
        assert "total_constraints_checked" in data
        assert "total_violations" in data
        assert "compliance_rate" in data
        assert "violations" in data
        assert "summary_by_type" in data

    def test_enforce_with_violations(self):
        session = store.create()
        session.schema = SchemaMetadata(tables=[_users_table()])
        session.data = {
            "users": [
                {"id": None, "email": "bad", "name": None, "age": -1, "status": "x", "phone": "nope"},
            ],
        }
        resp = client.post(f"/constraints/enforce?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_violations"] > 0
        assert data["compliance_rate"] < 1.0

    def test_session_not_found(self):
        resp = client.post("/constraints/enforce?session_id=nonexistent")
        assert resp.status_code == 404

    def test_no_schema(self):
        session = store.create()
        resp = client.post(f"/constraints/enforce?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No schema" in resp.json()["detail"]

    def test_no_data(self):
        session = store.create()
        session.schema = SchemaMetadata(tables=[_users_table()])
        resp = client.post(f"/constraints/enforce?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No generated data" in resp.json()["detail"]
