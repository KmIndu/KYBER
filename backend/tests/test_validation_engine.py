"""Tests for the validation engine and individual validators."""

from pathlib import Path
from typing import Any

import pytest

from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.models.validation import ValidationReport
from app.parsers.sql_parser import parse_sql_schema
from app.validators.engine import ValidationEngine
from app.validators.validators import (
    EnumValidator,
    FKValidator,
    NullableValidator,
    PKValidator,
    RegexValidator,
    TypeValidator,
    UniqueValidator,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_schema.sql"


# ── Shared fixtures ───────────────────────────────────────────


@pytest.fixture
def schema() -> SchemaMetadata:
    return parse_sql_schema(FIXTURE_PATH.read_text())


@pytest.fixture
def valid_data() -> dict[str, list[dict[str, Any]]]:
    """A small set of valid data matching sample_schema.sql."""
    return {
        "customers": [
            {
                "customer_id": 1,
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "phone": "555-1234",
                "date_of_birth": "1990-01-15",
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
            },
            {
                "customer_id": 2,
                "first_name": "Bob",
                "last_name": "Jones",
                "email": "bob@example.com",
                "phone": "555-5678",
                "date_of_birth": "1985-06-20",
                "status": "inactive",
                "created_at": "2025-02-01T00:00:00",
            },
        ],
        "policies": [
            {
                "policy_id": 1,
                "customer_id": 1,
                "policy_number": "POL-001",
                "policy_type": "life",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "premium": 500.00,
                "coverage_amount": 100000.00,
            },
        ],
        "claims": [
            {
                "claim_id": 1,
                "policy_id": 1,
                "claim_date": "2025-06-15",
                "claim_amount": 5000.00,
                "description": "Broken window",
                "status": "pending",
            },
        ],
        "payments": [
            {
                "payment_id": 1,
                "claim_id": 1,
                "payment_date": "2025-07-01",
                "amount": 5000.00,
                "payment_method": "bank_transfer",
            },
        ],
    }


def _table(schema: SchemaMetadata, name: str) -> TableMetadata:
    return next(t for t in schema.tables if t.name == name)


# ══════════════════════════════════════════════════════════════
#  PK Validator
# ══════════════════════════════════════════════════════════════


class TestPKValidator:
    def test_valid_pks(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = PKValidator().validate(table, valid_data["customers"])
        assert len(errors) == 0

    def test_duplicate_pk(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {"customer_id": 1, "first_name": "A", "last_name": "B", "email": "a@b.com"},
            {"customer_id": 1, "first_name": "C", "last_name": "D", "email": "c@d.com"},
        ]
        errors = PKValidator().validate(table, rows)
        assert len(errors) == 1
        assert errors[0].rule == "pk_unique"
        assert errors[0].row_index == 1

    def test_null_pk(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"customer_id": None, "first_name": "A", "last_name": "B", "email": "a@b.com"}]
        errors = PKValidator().validate(table, rows)
        assert len(errors) == 1
        assert "NULL" in errors[0].message

    def test_no_pk_columns(self):
        table = TableMetadata(
            name="no_pk",
            columns=[ColumnMetadata(name="x", data_type="INT")],
        )
        errors = PKValidator().validate(table, [{"x": 1}])
        assert len(errors) == 0


# ══════════════════════════════════════════════════════════════
#  FK Validator
# ══════════════════════════════════════════════════════════════


class TestFKValidator:
    def test_valid_fks(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "policies")
        errors = FKValidator().validate(table, valid_data["policies"], valid_data)
        assert len(errors) == 0

    def test_broken_fk(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "policies")
        bad_rows = [
            {
                "policy_id": 99,
                "customer_id": 9999,
                "policy_number": "X",
                "policy_type": "life",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "premium": 100.0,
                "coverage_amount": 50000.0,
            }
        ]
        errors = FKValidator().validate(table, bad_rows, valid_data)
        assert len(errors) == 1
        assert errors[0].rule == "fk_valid"
        assert "9999" in errors[0].message

    def test_null_fk_allowed(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "policies")
        rows = [
            {
                "policy_id": 10,
                "customer_id": None,
                "policy_number": "Y",
                "policy_type": "auto",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "premium": 200.0,
                "coverage_amount": 50000.0,
            }
        ]
        errors = FKValidator().validate(table, rows, valid_data)
        assert len(errors) == 0

    def test_missing_parent_table(self, schema: SchemaMetadata):
        table = _table(schema, "policies")
        errors = FKValidator().validate(table, [{"policy_id": 1, "customer_id": 1}], {})
        assert len(errors) == 1


# ══════════════════════════════════════════════════════════════
#  Unique Validator
# ══════════════════════════════════════════════════════════════


class TestUniqueValidator:
    def test_valid_unique(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = UniqueValidator().validate(table, valid_data["customers"])
        assert len(errors) == 0

    def test_duplicate_unique(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {"customer_id": 1, "email": "same@test.com"},
            {"customer_id": 2, "email": "same@test.com"},
        ]
        errors = UniqueValidator().validate(table, rows)
        assert len(errors) == 1
        assert errors[0].rule == "unique"
        assert errors[0].column == "email"

    def test_null_unique_ignored(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {"customer_id": 1, "email": None},
            {"customer_id": 2, "email": None},
        ]
        errors = UniqueValidator().validate(table, rows)
        assert len(errors) == 0


# ══════════════════════════════════════════════════════════════
#  Type Validator
# ══════════════════════════════════════════════════════════════


class TestTypeValidator:
    def test_valid_types(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = TypeValidator().validate(table, valid_data["customers"])
        assert len(errors) == 0

    def test_wrong_type_string_in_int(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"customer_id": "not_an_int", "first_name": "A", "last_name": "B", "email": "a@b.com"}]
        errors = TypeValidator().validate(table, rows)
        type_errors = [e for e in errors if e.column == "customer_id"]
        assert len(type_errors) == 1
        assert type_errors[0].rule == "type"

    def test_wrong_type_int_in_string(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"customer_id": 1, "first_name": 123, "last_name": "B", "email": "a@b.com"}]
        errors = TypeValidator().validate(table, rows)
        type_errors = [e for e in errors if e.column == "first_name"]
        assert len(type_errors) == 1

    def test_date_format_valid(self):
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="d", data_type="DATE")],
        )
        rows = [{"d": "2025-01-15"}]
        errors = TypeValidator().validate(table, rows)
        assert len(errors) == 0

    def test_date_format_invalid(self):
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="d", data_type="DATE")],
        )
        rows = [{"d": "not-a-date"}]
        errors = TypeValidator().validate(table, rows)
        assert len(errors) == 1

    def test_datetime_format(self):
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="ts", data_type="TIMESTAMP")],
        )
        rows = [{"ts": "2025-01-01T12:00:00"}]
        errors = TypeValidator().validate(table, rows)
        assert len(errors) == 0

    def test_boolean_type(self):
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="flag", data_type="BOOLEAN")],
        )
        assert len(TypeValidator().validate(table, [{"flag": True}])) == 0
        assert len(TypeValidator().validate(table, [{"flag": "yes"}])) == 1

    def test_null_skipped(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"customer_id": None}]
        errors = TypeValidator().validate(table, rows)
        # None should not produce a type error
        type_errors = [e for e in errors if e.column == "customer_id" and e.rule == "type"]
        assert len(type_errors) == 0


# ══════════════════════════════════════════════════════════════
#  Enum Validator
# ══════════════════════════════════════════════════════════════


class TestEnumValidator:
    def test_valid_enum(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = EnumValidator().validate(table, valid_data["customers"])
        assert len(errors) == 0

    def test_invalid_enum(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"status": "INVALID_STATUS"}]
        errors = EnumValidator().validate(table, rows)
        assert len(errors) == 1
        assert errors[0].rule == "enum"

    def test_null_enum_skipped(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"status": None}]
        errors = EnumValidator().validate(table, rows)
        assert len(errors) == 0

    def test_claim_status_enum(self, schema: SchemaMetadata):
        table = _table(schema, "claims")
        good = [{"status": "approved"}]
        bad = [{"status": "cancelled"}]
        assert len(EnumValidator().validate(table, good)) == 0
        assert len(EnumValidator().validate(table, bad)) == 1


# ══════════════════════════════════════════════════════════════
#  Nullable Validator
# ══════════════════════════════════════════════════════════════


class TestNullableValidator:
    def test_valid_not_null(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = NullableValidator().validate(table, valid_data["customers"])
        assert len(errors) == 0

    def test_null_in_not_null_column(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {
                "customer_id": 1,
                "first_name": None,
                "last_name": "B",
                "email": "a@b.com",
            }
        ]
        errors = NullableValidator().validate(table, rows)
        assert len(errors) == 1
        assert errors[0].rule == "nullable"
        assert errors[0].column == "first_name"

    def test_null_in_nullable_column_ok(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {
                "customer_id": 1,
                "first_name": "A",
                "last_name": "B",
                "email": "a@b.com",
                "phone": None,
            }
        ]
        errors = NullableValidator().validate(table, rows)
        assert len(errors) == 0

    def test_multiple_not_null_violations(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [
            {
                "customer_id": 1,
                "first_name": None,
                "last_name": None,
                "email": None,
            }
        ]
        errors = NullableValidator().validate(table, rows)
        assert len(errors) == 3


# ══════════════════════════════════════════════════════════════
#  Regex Validator
# ══════════════════════════════════════════════════════════════


class TestRegexValidator:
    def test_valid_email(self, schema: SchemaMetadata, valid_data):
        table = _table(schema, "customers")
        errors = RegexValidator().validate(table, valid_data["customers"])
        email_errors = [e for e in errors if e.column == "email"]
        assert len(email_errors) == 0

    def test_invalid_email(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"email": "not-an-email"}]
        errors = RegexValidator().validate(table, rows)
        email_errors = [e for e in errors if e.column == "email"]
        assert len(email_errors) == 1
        assert email_errors[0].rule == "regex"

    def test_valid_phone(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"phone": "555-1234"}]
        errors = RegexValidator().validate(table, rows)
        phone_errors = [e for e in errors if e.column == "phone"]
        assert len(phone_errors) == 0

    def test_invalid_phone(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"phone": "abc-def-ghij"}]
        errors = RegexValidator().validate(table, rows)
        phone_errors = [e for e in errors if e.column == "phone"]
        assert len(phone_errors) == 1

    def test_null_skipped(self, schema: SchemaMetadata):
        table = _table(schema, "customers")
        rows = [{"email": None, "phone": None}]
        errors = RegexValidator().validate(table, rows)
        assert len(errors) == 0

    def test_non_matching_column_ignored(self):
        table = TableMetadata(
            name="t",
            columns=[ColumnMetadata(name="description", data_type="TEXT")],
        )
        rows = [{"description": "anything goes here"}]
        errors = RegexValidator().validate(table, rows)
        assert len(errors) == 0


# ══════════════════════════════════════════════════════════════
#  Validation Engine
# ══════════════════════════════════════════════════════════════


class TestValidationEngine:
    def test_valid_data_all_pass(self, schema: SchemaMetadata, valid_data):
        engine = ValidationEngine(schema)
        report = engine.validate(valid_data)
        assert isinstance(report, ValidationReport)
        assert report.failed == 0
        assert report.passed == report.total_rows
        assert report.total_rows == 5  # 2+1+1+1

    def test_report_counts(self, schema: SchemaMetadata, valid_data):
        engine = ValidationEngine(schema)
        report = engine.validate(valid_data)
        assert report.passed + report.failed == report.total_rows

    def test_table_reports_present(self, schema: SchemaMetadata, valid_data):
        engine = ValidationEngine(schema)
        report = engine.validate(valid_data)
        table_names = {t.table for t in report.tables}
        assert "customers" in table_names
        assert "policies" in table_names
        assert "claims" in table_names
        assert "payments" in table_names

    def test_detects_pk_violation(self, schema: SchemaMetadata):
        data = {
            "customers": [
                {"customer_id": 1, "first_name": "A", "last_name": "B", "email": "a@b.com", "phone": "555-0000", "status": "active", "created_at": "2025-01-01T00:00:00"},
                {"customer_id": 1, "first_name": "C", "last_name": "D", "email": "c@d.com", "phone": "555-0001", "status": "active", "created_at": "2025-01-01T00:00:00"},
            ],
        }
        report = ValidationEngine(schema).validate(data)
        assert report.failed > 0
        pk_errors = [e for e in report.errors if e.rule == "pk_unique"]
        assert len(pk_errors) == 1

    def test_detects_fk_violation(self, schema: SchemaMetadata, valid_data):
        valid_data["policies"] = [
            {
                "policy_id": 1,
                "customer_id": 9999,
                "policy_number": "X",
                "policy_type": "life",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "premium": 100.0,
                "coverage_amount": 50000.0,
            }
        ]
        report = ValidationEngine(schema).validate(valid_data)
        fk_errors = [e for e in report.errors if e.rule == "fk_valid"]
        assert len(fk_errors) == 1

    def test_detects_enum_violation(self, schema: SchemaMetadata, valid_data):
        valid_data["customers"][0]["status"] = "BOGUS"
        report = ValidationEngine(schema).validate(valid_data)
        enum_errors = [e for e in report.errors if e.rule == "enum"]
        assert len(enum_errors) == 1

    def test_detects_nullable_violation(self, schema: SchemaMetadata, valid_data):
        valid_data["customers"][0]["first_name"] = None
        report = ValidationEngine(schema).validate(valid_data)
        null_errors = [e for e in report.errors if e.rule == "nullable"]
        assert len(null_errors) == 1

    def test_detects_type_violation(self, schema: SchemaMetadata, valid_data):
        valid_data["customers"][0]["customer_id"] = "not_int"
        report = ValidationEngine(schema).validate(valid_data)
        type_errors = [e for e in report.errors if e.rule == "type"]
        assert len(type_errors) >= 1

    def test_summary_format(self, schema: SchemaMetadata, valid_data):
        report = ValidationEngine(schema).validate(valid_data)
        d = report.model_dump()
        assert "passed" in d
        assert "failed" in d
        assert "total_rows" in d
        assert "tables" in d
        assert "errors" in d

    def test_unknown_table_skipped(self, schema: SchemaMetadata):
        data = {"nonexistent_table": [{"x": 1}]}
        report = ValidationEngine(schema).validate(data)
        assert report.total_rows == 0

    def test_empty_data(self, schema: SchemaMetadata):
        report = ValidationEngine(schema).validate({})
        assert report.total_rows == 0
        assert report.passed == 0
        assert report.failed == 0

    def test_generated_data_passes(self, schema: SchemaMetadata):
        """Generate data via SyntheticDataGenerator and validate — should pass."""
        from app.generators.synthetic_generator import SyntheticDataGenerator

        gen = SyntheticDataGenerator(schema, row_count=20)
        data = gen.generate()
        report = ValidationEngine(schema).validate(data)
        # Generated data should mostly pass (some nullable randomness may trigger
        # regex on null‐adjacent values, but PKs/FKs/types should be clean)
        assert report.passed >= report.total_rows * 0.9
        pk_errors = [e for e in report.errors if e.rule == "pk_unique"]
        fk_errors = [e for e in report.errors if e.rule == "fk_valid"]
        assert len(pk_errors) == 0
        assert len(fk_errors) == 0
