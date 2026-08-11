"""Tests for the negative test case generator."""

import re
from pathlib import Path

import pytest

from app.generators.negative_generator import NegativeCaseGenerator
from app.models.negative import NegativeDataset, NegativeRow, NegativeToggles
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.parsers.sql_parser import parse_sql_schema


# ── Fixtures ──────────────────────────────────────────────────

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_schema.sql"


@pytest.fixture
def schema() -> SchemaMetadata:
    return parse_sql_schema(FIXTURE_PATH.read_text())


@pytest.fixture
def full_result(schema: SchemaMetadata) -> NegativeDataset:
    gen = NegativeCaseGenerator(schema, row_count=5)
    return gen.generate()


def _violations(result: NegativeDataset, kind: str) -> list[NegativeRow]:
    return [r for r in result.invalid if r.violation == kind]


# ── Basic structure ───────────────────────────────────────────


class TestBasicNegative:
    def test_returns_negative_dataset(self, full_result: NegativeDataset):
        assert isinstance(full_result, NegativeDataset)

    def test_has_valid_data(self, full_result: NegativeDataset):
        assert full_result.valid
        assert "customers" in full_result.valid

    def test_has_invalid_rows(self, full_result: NegativeDataset):
        assert len(full_result.invalid) > 0

    def test_has_summary(self, full_result: NegativeDataset):
        assert full_result.summary
        total = sum(full_result.summary.values())
        assert total == len(full_result.invalid)

    def test_valid_rows_have_correct_count(self, full_result: NegativeDataset):
        for table_name, rows in full_result.valid.items():
            assert len(rows) == 5


# ── Invalid emails ────────────────────────────────────────────


class TestInvalidEmails:
    def test_generates_invalid_emails(self, full_result: NegativeDataset):
        bad_emails = _violations(full_result, "invalid_email")
        assert len(bad_emails) > 0

    def test_invalid_email_column(self, full_result: NegativeDataset):
        bad_emails = _violations(full_result, "invalid_email")
        for r in bad_emails:
            assert r.column == "email"
            assert r.table == "customers"

    def test_invalid_email_formats(self, full_result: NegativeDataset):
        bad_emails = _violations(full_result, "invalid_email")
        values = {r.row["email"] for r in bad_emails}
        # Should include things like missing @, double dots, etc.
        assert any("@" not in v for v in values)
        assert any(v.startswith("@") for v in values)

    def test_toggle_off_skips_emails(self, schema: SchemaMetadata):
        toggles = NegativeToggles(invalid_emails=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "invalid_email")) == 0


# ── Null required fields ──────────────────────────────────────


class TestNullRequired:
    def test_generates_null_required(self, full_result: NegativeDataset):
        nulls = _violations(full_result, "null_required")
        assert len(nulls) > 0

    def test_null_in_not_null_columns(self, full_result: NegativeDataset):
        nulls = _violations(full_result, "null_required")
        for r in nulls:
            assert r.row[r.column] is None

    def test_includes_expected_columns(self, full_result: NegativeDataset):
        nulls = _violations(full_result, "null_required")
        cols = {r.column for r in nulls}
        # customers has first_name, last_name, email as NOT NULL non-PK
        assert "first_name" in cols
        assert "last_name" in cols

    def test_toggle_off_skips_nulls(self, schema: SchemaMetadata):
        toggles = NegativeToggles(null_required_fields=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "null_required")) == 0


# ── Duplicate values ──────────────────────────────────────────


class TestDuplicateValues:
    def test_generates_duplicates(self, full_result: NegativeDataset):
        dups = _violations(full_result, "duplicate_value")
        assert len(dups) > 0

    def test_duplicate_on_unique_columns(self, full_result: NegativeDataset):
        dups = _violations(full_result, "duplicate_value")
        # email is UNIQUE, customer_id is PK — both should appear
        cols = {(r.table, r.column) for r in dups}
        assert ("customers", "email") in cols or ("customers", "customer_id") in cols

    def test_duplicate_value_matches_existing(self, full_result: NegativeDataset):
        dups = _violations(full_result, "duplicate_value")
        for r in dups:
            # The duplicate value should be the same as the first row's value
            first_row = full_result.valid[r.table][0]
            assert r.row[r.column] == first_row[r.column]

    def test_toggle_off_skips_duplicates(self, schema: SchemaMetadata):
        toggles = NegativeToggles(duplicate_values=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "duplicate_value")) == 0


# ── Broken foreign keys ──────────────────────────────────────


class TestBrokenForeignKeys:
    def test_generates_broken_fks(self, full_result: NegativeDataset):
        broken = _violations(full_result, "broken_fk")
        assert len(broken) > 0

    def test_broken_fk_tables(self, full_result: NegativeDataset):
        broken = _violations(full_result, "broken_fk")
        tables = {r.table for r in broken}
        # policies, claims, payments all have FKs
        assert "policies" in tables
        assert "claims" in tables
        assert "payments" in tables

    def test_broken_fk_value_not_in_parent(self, full_result: NegativeDataset):
        broken = _violations(full_result, "broken_fk")
        for r in broken:
            fk_value = r.row[r.column]
            # Value should not exist in parent table
            assert fk_value == -999999 or fk_value < 0

    def test_toggle_off_skips_fks(self, schema: SchemaMetadata):
        toggles = NegativeToggles(broken_foreign_keys=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "broken_fk")) == 0


# ── Boundary values ───────────────────────────────────────────


class TestBoundaryValues:
    def test_generates_boundary_values(self, full_result: NegativeDataset):
        bounds = _violations(full_result, "boundary_value")
        assert len(bounds) > 0

    def test_zero_and_negative(self, full_result: NegativeDataset):
        bounds = _violations(full_result, "boundary_value")
        values = [r.row[r.column] for r in bounds]
        assert 0 in values
        assert -1 in values

    def test_at_boundary(self, full_result: NegativeDataset):
        bounds = _violations(full_result, "boundary_value")
        # premium has CHECK (premium > 0), so boundary at 0 should appear
        premium_bounds = [r for r in bounds if r.column == "premium"]
        assert len(premium_bounds) > 0

    def test_string_length_boundary(self, full_result: NegativeDataset):
        bounds = _violations(full_result, "boundary_value")
        # Should have over-length strings for VARCHAR columns
        over_length = [r for r in bounds if "Over max length" in r.description]
        assert len(over_length) > 0

    def test_empty_string_boundary(self, full_result: NegativeDataset):
        bounds = _violations(full_result, "boundary_value")
        empty = [r for r in bounds if "Empty string" in r.description]
        assert len(empty) > 0

    def test_toggle_off_skips_boundaries(self, schema: SchemaMetadata):
        toggles = NegativeToggles(boundary_values=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "boundary_value")) == 0


# ── Invalid enums ─────────────────────────────────────────────


class TestInvalidEnums:
    def test_generates_invalid_enums(self, full_result: NegativeDataset):
        enums = _violations(full_result, "invalid_enum")
        assert len(enums) > 0

    def test_invalid_enum_columns(self, full_result: NegativeDataset):
        enums = _violations(full_result, "invalid_enum")
        # customers.status and claims.status have CHECK(IN(...))
        cols = {(r.table, r.column) for r in enums}
        assert ("customers", "status") in cols or ("claims", "status") in cols

    def test_invalid_enum_not_in_allowed(self, full_result: NegativeDataset):
        enums = _violations(full_result, "invalid_enum")
        for r in enums:
            # The invalid value should NOT be one of the valid enum values
            val = r.row[r.column]
            assert val in ["INVALID_STATUS", "unknown", "", "null", "42"]

    def test_toggle_off_skips_enums(self, schema: SchemaMetadata):
        toggles = NegativeToggles(invalid_enums=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "invalid_enum")) == 0


# ── Invalid regex ─────────────────────────────────────────────


class TestInvalidRegex:
    def test_generates_invalid_regex(self, full_result: NegativeDataset):
        regexes = _violations(full_result, "invalid_regex")
        # customers.phone is a phone column → should produce invalid phone formats
        assert len(regexes) > 0

    def test_invalid_phone_formats(self, full_result: NegativeDataset):
        regexes = _violations(full_result, "invalid_regex")
        phone_rows = [r for r in regexes if r.column == "phone"]
        assert len(phone_rows) > 0
        for r in phone_rows:
            assert r.row["phone"] in ["abc-def-ghij", "!@#$%", "12"]

    def test_toggle_off_skips_regex(self, schema: SchemaMetadata):
        toggles = NegativeToggles(invalid_regex_patterns=False)
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(_violations(result, "invalid_regex")) == 0


# ── Toggles ───────────────────────────────────────────────────


class TestToggles:
    def test_all_off_produces_no_invalid(self, schema: SchemaMetadata):
        toggles = NegativeToggles(
            invalid_emails=False,
            null_required_fields=False,
            duplicate_values=False,
            broken_foreign_keys=False,
            boundary_values=False,
            invalid_enums=False,
            invalid_regex_patterns=False,
        )
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        assert len(result.invalid) == 0
        # Valid data should still be generated
        assert len(result.valid) > 0

    def test_default_toggles_all_on(self):
        t = NegativeToggles()
        assert t.invalid_emails is True
        assert t.null_required_fields is True
        assert t.duplicate_values is True
        assert t.broken_foreign_keys is True
        assert t.boundary_values is True
        assert t.invalid_enums is True
        assert t.invalid_regex_patterns is True

    def test_only_one_toggle(self, schema: SchemaMetadata):
        toggles = NegativeToggles(
            invalid_emails=False,
            null_required_fields=False,
            duplicate_values=False,
            broken_foreign_keys=True,  # only this
            boundary_values=False,
            invalid_enums=False,
            invalid_regex_patterns=False,
        )
        gen = NegativeCaseGenerator(schema, row_count=3, toggles=toggles)
        result = gen.generate()
        violations = {r.violation for r in result.invalid}
        assert violations == {"broken_fk"}


# ── Valid vs invalid separation ───────────────────────────────


class TestValidInvalidSeparation:
    def test_valid_and_invalid_are_separate(self, full_result: NegativeDataset):
        # Valid data should have proper rows
        for rows in full_result.valid.values():
            for row in rows:
                assert isinstance(row, dict)
        # Invalid data should be NegativeRow objects
        for neg in full_result.invalid:
            assert isinstance(neg, NegativeRow)
            assert neg.violation
            assert neg.column
            assert neg.table

    def test_summary_matches_invalid_count(self, full_result: NegativeDataset):
        total = sum(full_result.summary.values())
        assert total == len(full_result.invalid)

    def test_all_violation_types_in_summary(self, full_result: NegativeDataset):
        types = {r.violation for r in full_result.invalid}
        for t in types:
            assert t in full_result.summary
            assert full_result.summary[t] > 0


# ── Minimal schema ────────────────────────────────────────────


class TestMinimalSchema:
    def test_single_table_no_fks(self):
        schema = SchemaMetadata(
            tables=[
                TableMetadata(
                    name="users",
                    columns=[
                        ColumnMetadata(name="id", data_type="INT", is_primary_key=True, nullable=False),
                        ColumnMetadata(name="email", data_type="VARCHAR(255)", is_unique=True, nullable=False),
                        ColumnMetadata(name="name", data_type="VARCHAR(100)", nullable=False),
                    ],
                    primary_keys=["id"],
                )
            ]
        )
        gen = NegativeCaseGenerator(schema, row_count=3)
        result = gen.generate()
        assert len(result.valid["users"]) == 3
        assert len(result.invalid) > 0
        violations = {r.violation for r in result.invalid}
        assert "invalid_email" in violations
        assert "null_required" in violations
        assert "duplicate_value" in violations
        assert "boundary_value" in violations
        # No FKs → no broken_fk
        assert "broken_fk" not in violations

    def test_table_with_enum_only(self):
        schema = SchemaMetadata(
            tables=[
                TableMetadata(
                    name="items",
                    columns=[
                        ColumnMetadata(name="id", data_type="INT", is_primary_key=True, nullable=False),
                        ColumnMetadata(
                            name="color",
                            data_type="VARCHAR(20)",
                            check_constraint="color IN ('red', 'blue', 'green')",
                        ),
                    ],
                    primary_keys=["id"],
                )
            ]
        )
        toggles = NegativeToggles(
            invalid_emails=False,
            null_required_fields=False,
            duplicate_values=False,
            broken_foreign_keys=False,
            boundary_values=False,
            invalid_enums=True,
            invalid_regex_patterns=False,
        )
        gen = NegativeCaseGenerator(schema, row_count=2, toggles=toggles)
        result = gen.generate()
        enums = _violations(result, "invalid_enum")
        assert len(enums) == 1
        assert enums[0].row["color"] not in ["red", "blue", "green"]
