"""Tests for the edge-case analysis engine and router.

Covers:
- All 9 edge-case categories
- Toggle on/off behaviour
- AI edge-case merging
- Column summaries
- Empty schema handling
- Router endpoint (success, 404, 400)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.generators.edge_case_engine import EdgeCaseAnalysisEngine
from app.main import app
from app.models.ai import AIEdgeCase
from app.models.edge_case import (
    EdgeCaseAnalysis,
    EdgeCaseCategory,
    EdgeCaseColumnSummary,
    EdgeCaseRule,
    EdgeCaseToggles,
)
from app.models.schema import (
    ColumnMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.session_store import store

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def int_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="age", data_type="INTEGER", nullable=False,
        check_constraint="age >= 0 AND age <= 150",
    )


@pytest.fixture
def varchar_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="name", data_type="VARCHAR(100)", nullable=True,
    )


@pytest.fixture
def email_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True,
    )


@pytest.fixture
def pk_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="id", data_type="INTEGER", nullable=False, is_primary_key=True,
    )


@pytest.fixture
def date_col() -> ColumnMetadata:
    return ColumnMetadata(name="created_at", data_type="DATE", nullable=True)


@pytest.fixture
def float_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="price", data_type="DECIMAL(10,2)", nullable=False,
        check_constraint="price > 0",
    )


@pytest.fixture
def bool_col() -> ColumnMetadata:
    return ColumnMetadata(name="active", data_type="BOOLEAN", nullable=False)


@pytest.fixture
def tinyint_col() -> ColumnMetadata:
    return ColumnMetadata(name="status", data_type="TINYINT", nullable=False)


@pytest.fixture
def uuid_col() -> ColumnMetadata:
    return ColumnMetadata(name="uuid", data_type="VARCHAR(36)", nullable=False)


@pytest.fixture
def phone_col() -> ColumnMetadata:
    return ColumnMetadata(name="phone", data_type="VARCHAR(20)", nullable=True)


@pytest.fixture
def date_str_col() -> ColumnMetadata:
    """A string column named 'date_of_birth'."""
    return ColumnMetadata(name="date_of_birth", data_type="VARCHAR(10)", nullable=True)


@pytest.fixture
def enum_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="status",
        data_type="VARCHAR(20)",
        nullable=False,
        check_constraint="status IN ('active','inactive','pending')",
    )


@pytest.fixture
def simple_table(int_col, varchar_col, email_col, pk_col) -> TableMetadata:
    return TableMetadata(
        name="users",
        columns=[pk_col, int_col, varchar_col, email_col],
        primary_keys=["id"],
    )


@pytest.fixture
def simple_schema(simple_table) -> SchemaMetadata:
    return SchemaMetadata(tables=[simple_table])


@pytest.fixture
def full_schema(
    int_col, varchar_col, email_col, pk_col, date_col, float_col, bool_col,
) -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="users",
                columns=[pk_col, int_col, varchar_col, email_col],
                primary_keys=["id"],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    float_col,
                    date_col,
                    bool_col,
                ],
                primary_keys=["id"],
            ),
        ]
    )


@pytest.fixture
def toggles_all_on() -> EdgeCaseToggles:
    return EdgeCaseToggles()


@pytest.fixture
def toggles_all_off() -> EdgeCaseToggles:
    return EdgeCaseToggles(
        null_values=False,
        boundary_values=False,
        negative_values=False,
        overflow_values=False,
        invalid_formats=False,
        duplicate_values=False,
        type_mismatch=False,
        empty_values=False,
        special_chars=False,
    )


def _rules_of(result: EdgeCaseAnalysis, cat: EdgeCaseCategory) -> list[EdgeCaseRule]:
    return [r for r in result.rules if r.category == cat]


# ── Basic structure ───────────────────────────────────────────


class TestBasicAnalysis:
    def test_returns_analysis_object(self, simple_schema, toggles_all_on):
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles_all_on)
        result = engine.analyze(session_id="test-1")
        assert isinstance(result, EdgeCaseAnalysis)

    def test_session_id_propagated(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze(session_id="my-session")
        assert result.session_id == "my-session"

    def test_total_rules_matches(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        assert result.total_rules == len(result.rules)

    def test_summary_counts_match(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        total_from_summary = sum(result.summary.values())
        assert total_from_summary == result.total_rules

    def test_tables_analyzed(self, full_schema):
        engine = EdgeCaseAnalysisEngine(full_schema)
        result = engine.analyze()
        assert result.tables_analyzed == 2

    def test_columns_analyzed(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        assert result.columns_analyzed > 0

    def test_has_column_summaries(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        assert len(result.column_summaries) > 0
        for cs in result.column_summaries:
            assert isinstance(cs, EdgeCaseColumnSummary)
            assert cs.rule_count > 0

    def test_empty_schema(self):
        schema = SchemaMetadata(tables=[])
        engine = EdgeCaseAnalysisEngine(schema)
        result = engine.analyze()
        assert result.total_rules == 0
        assert result.tables_analyzed == 0
        assert result.columns_analyzed == 0


# ── NULL rules ────────────────────────────────────────────────


class TestNullRules:
    def test_not_null_column_gets_null_rule(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        null_rules = _rules_of(result, EdgeCaseCategory.NULL)
        # age is NOT NULL → should have a "should be rejected" null rule
        age_nulls = [r for r in null_rules if r.column == "age"]
        assert any("rejected" in r.expected_behavior for r in age_nulls)

    def test_nullable_column_gets_accepted_rule(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        null_rules = _rules_of(result, EdgeCaseCategory.NULL)
        name_nulls = [r for r in null_rules if r.column == "name"]
        assert any("accepted" in r.expected_behavior for r in name_nulls)

    def test_pk_excluded_from_null_rules(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        null_rules = _rules_of(result, EdgeCaseCategory.NULL)
        pk_nulls = [r for r in null_rules if r.column == "id"]
        # PK not-null should not get a null rule (engine skips PK)
        assert len(pk_nulls) == 0

    def test_null_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(null_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.NULL)) == 0


# ── Boundary rules ────────────────────────────────────────────


class TestBoundaryRules:
    def test_integer_check_constraint_boundaries(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        bound_rules = _rules_of(result, EdgeCaseCategory.BOUNDARY)
        age_bounds = [r for r in bound_rules if r.column == "age"]
        # Should have: at lower(0), below lower(-1), at upper(150), above upper(151), zero(0)
        assert len(age_bounds) >= 4

    def test_at_lower_bound(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        bound_rules = _rules_of(result, EdgeCaseCategory.BOUNDARY)
        assert any(r.column == "age" and r.test_value == 0 for r in bound_rules)

    def test_above_upper_bound(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        bound_rules = _rules_of(result, EdgeCaseCategory.BOUNDARY)
        assert any(
            r.column == "age" and r.test_value == 151 and "rejected" in r.expected_behavior
            for r in bound_rules
        )

    def test_string_max_length_boundary(self):
        col = ColumnMetadata(name="label", data_type="VARCHAR(50)", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, negative_values=False, overflow_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        bound_rules = _rules_of(result, EdgeCaseCategory.BOUNDARY)
        # Exactly at max, over max, single char
        assert any(r.test_value == "x" * 50 for r in bound_rules)
        assert any(r.test_value == "x" * 60 for r in bound_rules)
        assert any(r.test_value == "a" for r in bound_rules)

    def test_date_boundaries(self):
        col = ColumnMetadata(name="dob", data_type="DATE", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, negative_values=False, overflow_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        bound_rules = _rules_of(result, EdgeCaseCategory.BOUNDARY)
        assert any(r.test_value == "1970-01-01" for r in bound_rules)
        assert any(r.test_value == "2099-12-31" for r in bound_rules)

    def test_boundary_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(boundary_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.BOUNDARY)) == 0


# ── Negative rules ────────────────────────────────────────────


class TestNegativeRules:
    def test_integer_gets_negative_rules(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        neg_rules = _rules_of(result, EdgeCaseCategory.NEGATIVE)
        age_negs = [r for r in neg_rules if r.column == "age"]
        assert any(r.test_value == -1 for r in age_negs)
        assert any(r.test_value == -999 for r in age_negs)

    def test_float_gets_negative_rules(self):
        col = ColumnMetadata(name="amount", data_type="DECIMAL(10,2)", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, overflow_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        neg_rules = _rules_of(result, EdgeCaseCategory.NEGATIVE)
        assert any(r.test_value == -1.0 for r in neg_rules)

    def test_string_no_negative_rules(self):
        col = ColumnMetadata(name="label", data_type="VARCHAR(50)", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, overflow_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.NEGATIVE)) == 0

    def test_negative_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(negative_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.NEGATIVE)) == 0


# ── Overflow rules ────────────────────────────────────────────


class TestOverflowRules:
    def test_integer_overflow(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        ov_rules = _rules_of(result, EdgeCaseCategory.OVERFLOW)
        age_ov = [r for r in ov_rules if r.column == "age"]
        assert len(age_ov) >= 2  # INT min/max

    def test_tinyint_overflow_specific(self):
        col = ColumnMetadata(name="level", data_type="TINYINT", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        ov = _rules_of(result, EdgeCaseCategory.OVERFLOW)
        assert any(r.test_value == -129 for r in ov)
        assert any(r.test_value == 256 for r in ov)

    def test_float_overflow(self):
        col = ColumnMetadata(name="val", data_type="DECIMAL(10,2)", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        ov = _rules_of(result, EdgeCaseCategory.OVERFLOW)
        assert any(r.test_value == 1e308 for r in ov)
        assert any(r.test_value == -1e308 for r in ov)

    def test_string_overflow(self):
        col = ColumnMetadata(name="label", data_type="VARCHAR(10)", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            invalid_formats=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        ov = _rules_of(result, EdgeCaseCategory.OVERFLOW)
        assert any(len(str(r.test_value)) == 100 for r in ov)  # 10 * 10

    def test_overflow_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(overflow_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.OVERFLOW)) == 0


# ── Invalid format rules ─────────────────────────────────────


class TestInvalidFormatRules:
    def test_email_column_gets_format_rules(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        fmt_rules = _rules_of(result, EdgeCaseCategory.INVALID_FORMAT)
        email_fmt = [r for r in fmt_rules if r.column == "email"]
        assert len(email_fmt) >= 5  # 6 invalid patterns

    def test_phone_column(self):
        col = ColumnMetadata(name="phone", data_type="VARCHAR(20)", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        fmt_rules = _rules_of(result, EdgeCaseCategory.INVALID_FORMAT)
        assert len(fmt_rules) >= 3

    def test_uuid_column(self):
        col = ColumnMetadata(name="uuid", data_type="VARCHAR(36)", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        fmt_rules = _rules_of(result, EdgeCaseCategory.INVALID_FORMAT)
        assert any("UUID" in r.description for r in fmt_rules)

    def test_date_string_column(self):
        col = ColumnMetadata(name="date_of_birth", data_type="VARCHAR(10)", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        fmt_rules = _rules_of(result, EdgeCaseCategory.INVALID_FORMAT)
        assert any("date" in r.description.lower() for r in fmt_rules)

    def test_enum_check_invalid_format(self):
        col = ColumnMetadata(
            name="status", data_type="VARCHAR(20)", nullable=False,
            check_constraint="status IN ('active','inactive','pending')",
        )
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, duplicate_values=False, type_mismatch=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        fmt_rules = _rules_of(result, EdgeCaseCategory.INVALID_FORMAT)
        assert any(r.test_value == "__INVALID__" for r in fmt_rules)

    def test_format_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(invalid_formats=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.INVALID_FORMAT)) == 0


# ── Duplicate rules ───────────────────────────────────────────


class TestDuplicateRules:
    def test_pk_gets_duplicate_rule(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        dup_rules = _rules_of(result, EdgeCaseCategory.DUPLICATE)
        assert any(r.column == "id" and "primary key" in r.description.lower() for r in dup_rules)

    def test_unique_column_gets_duplicate_rule(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        dup_rules = _rules_of(result, EdgeCaseCategory.DUPLICATE)
        assert any(r.column == "email" and "UNIQUE" in r.description for r in dup_rules)

    def test_regular_column_no_duplicate_rule(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        dup_rules = _rules_of(result, EdgeCaseCategory.DUPLICATE)
        assert not any(r.column == "name" for r in dup_rules)

    def test_duplicate_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(duplicate_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.DUPLICATE)) == 0


# ── Type mismatch rules ──────────────────────────────────────


class TestTypeMismatchRules:
    def test_integer_type_mismatch(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        tm_rules = _rules_of(result, EdgeCaseCategory.TYPE_MISMATCH)
        age_tm = [r for r in tm_rules if r.column == "age"]
        assert any(r.test_value == "not_a_number" for r in age_tm)
        assert any(r.test_value is True for r in age_tm)

    def test_boolean_type_mismatch(self):
        col = ColumnMetadata(name="active", data_type="BOOLEAN", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, invalid_formats=False, duplicate_values=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        tm = _rules_of(result, EdgeCaseCategory.TYPE_MISMATCH)
        assert any(r.test_value == "maybe" for r in tm)
        assert any(r.test_value == 42 for r in tm)

    def test_date_type_mismatch(self):
        col = ColumnMetadata(name="dob", data_type="DATE", nullable=True)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, invalid_formats=False, duplicate_values=False,
            empty_values=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        tm = _rules_of(result, EdgeCaseCategory.TYPE_MISMATCH)
        assert any(r.test_value == 12345 for r in tm)

    def test_type_mismatch_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(type_mismatch=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.TYPE_MISMATCH)) == 0


# ── Empty rules ───────────────────────────────────────────────


class TestEmptyRules:
    def test_string_gets_empty_rules(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        empty_rules = _rules_of(result, EdgeCaseCategory.EMPTY)
        name_empty = [r for r in empty_rules if r.column == "name"]
        assert any(r.test_value == "" for r in name_empty)
        assert any(r.test_value == "   " for r in name_empty)

    def test_integer_no_empty_rules(self):
        col = ColumnMetadata(name="count", data_type="INTEGER", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, invalid_formats=False, duplicate_values=False,
            type_mismatch=False, special_chars=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.EMPTY)) == 0

    def test_empty_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(empty_values=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.EMPTY)) == 0


# ── Special chars rules ──────────────────────────────────────


class TestSpecialCharRules:
    def test_string_gets_special_chars(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        sc_rules = _rules_of(result, EdgeCaseCategory.SPECIAL_CHARS)
        name_sc = [r for r in sc_rules if r.column == "name"]
        assert any("SQL injection" in r.description for r in name_sc)
        assert any("XSS" in r.description for r in name_sc)

    def test_integer_no_special_chars(self):
        col = ColumnMetadata(name="count", data_type="INTEGER", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        toggles = EdgeCaseToggles(
            null_values=False, boundary_values=False, negative_values=False,
            overflow_values=False, invalid_formats=False, duplicate_values=False,
            type_mismatch=False, empty_values=False,
        )
        engine = EdgeCaseAnalysisEngine(schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.SPECIAL_CHARS)) == 0

    def test_special_chars_toggle_off(self, simple_schema):
        toggles = EdgeCaseToggles(special_chars=False)
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles)
        result = engine.analyze()
        assert len(_rules_of(result, EdgeCaseCategory.SPECIAL_CHARS)) == 0


# ── All toggles off ──────────────────────────────────────────


class TestTogglesAllOff:
    def test_no_rules_when_all_off(self, simple_schema, toggles_all_off):
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles_all_off)
        result = engine.analyze()
        assert result.total_rules == 0
        assert len(result.rules) == 0


# ── AI edge-case merging ─────────────────────────────────────


class TestAIMerging:
    def test_ai_cases_merged(self, simple_schema, toggles_all_off):
        ai_cases = [
            AIEdgeCase(
                table="users",
                column="age",
                scenario="Age exactly 18 (legal boundary)",
                test_value=18,
            ),
            AIEdgeCase(
                table="users",
                column="age",
                scenario="Age 999 (unrealistic)",
                test_value=999,
            ),
        ]
        engine = EdgeCaseAnalysisEngine(simple_schema, toggles_all_off, ai_edge_cases=ai_cases)
        result = engine.analyze()
        assert result.total_rules == 2
        assert all(r.source == "ai" for r in result.rules)
        assert any(r.test_value == 18 for r in result.rules)
        assert any(r.test_value == 999 for r in result.rules)

    def test_ai_cases_combined_with_engine(self, simple_schema):
        ai_cases = [
            AIEdgeCase(
                table="users",
                column="age",
                scenario="Age = 21 (drinking age)",
                test_value=21,
            ),
        ]
        engine = EdgeCaseAnalysisEngine(simple_schema, ai_edge_cases=ai_cases)
        result = engine.analyze()
        engine_rules = [r for r in result.rules if r.source == "engine"]
        ai_rules = [r for r in result.rules if r.source == "ai"]
        assert len(engine_rules) > 0
        assert len(ai_rules) == 1


# ── Column summaries ─────────────────────────────────────────


class TestColumnSummaries:
    def test_summaries_cover_all_columns_with_rules(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        summary_keys = {(cs.table, cs.column) for cs in result.column_summaries}
        rule_keys = {(r.table, r.column) for r in result.rules}
        assert summary_keys == rule_keys

    def test_summary_rule_count(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        for cs in result.column_summaries:
            expected = len([r for r in result.rules if r.table == cs.table and r.column == cs.column])
            assert cs.rule_count == expected

    def test_summary_categories_populated(self, simple_schema):
        engine = EdgeCaseAnalysisEngine(simple_schema)
        result = engine.analyze()
        for cs in result.column_summaries:
            assert len(cs.categories) > 0


# ── Router endpoint ──────────────────────────────────────────


class TestEdgeCaseRouter:
    @pytest.fixture(autouse=True)
    def _clean(self):
        yield
        store.clear()

    def _create_session(self, schema: SchemaMetadata) -> str:
        sess = store.create()
        sess.schema = schema
        return sess.session_id

    def test_analyze_success(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/edge-cases/analyze?session_id={sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rules"] > 0
        assert "rules" in data
        assert "summary" in data

    def test_analyze_with_toggles(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(
            f"/edge-cases/analyze?session_id={sid}&null_values=false&boundary_values=false"
            "&negative_values=false&overflow_values=false&invalid_formats=false"
            "&duplicate_values=false&type_mismatch=false&empty_values=false&special_chars=false"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rules"] == 0

    def test_analyze_session_not_found(self):
        resp = client.post("/edge-cases/analyze?session_id=nonexistent")
        assert resp.status_code == 404

    def test_analyze_no_schema(self):
        sess = store.create()
        sid = sess.session_id
        resp = client.post(f"/edge-cases/analyze?session_id={sid}")
        assert resp.status_code == 400

    def test_analyze_partial_toggles(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(
            f"/edge-cases/analyze?session_id={sid}&null_values=true"
            "&boundary_values=false&negative_values=false&overflow_values=false"
            "&invalid_formats=false&duplicate_values=false&type_mismatch=false"
            "&empty_values=false&special_chars=false"
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should only have null rules
        cats = set(r["category"] for r in data["rules"])
        assert cats == {"null"} or len(cats) == 0  # depends on schema NULL columns

    def test_response_matches_model(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/edge-cases/analyze?session_id={sid}")
        data = resp.json()
        analysis = EdgeCaseAnalysis(**data)
        assert analysis.total_rules == data["total_rules"]
        assert len(analysis.rules) == len(data["rules"])
