"""Edge-case analysis engine.

Analyzes a schema and produces a structured catalog of edge-case test
values per column.  Supports configurable categories, type-aware
boundaries, and integration with AI-inferred edge cases.

Categories:
  - null        : NULL in NOT NULL columns
  - boundary    : min/max from CHECK, at-boundary, just-outside
  - negative    : negative numbers where positive expected
  - overflow    : type-specific overflow (INT max, string over length)
  - invalid_format : bad emails, phones, dates, UUIDs
  - duplicate   : repeated values for UNIQUE / PK columns
  - type_mismatch  : wrong type injected (string in INT column)
  - empty       : empty strings, zero-length values
  - special_chars  : SQL injection patterns, unicode, control chars
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models.ai import AIEdgeCase
from app.models.edge_case import (
    EdgeCaseAnalysis,
    EdgeCaseCategory,
    EdgeCaseColumnSummary,
    EdgeCaseRule,
    EdgeCaseToggles,
)
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.utils.sql_types import (
    base_type as _base_type,
    extract_enum_from_check as _extract_enum_from_check,
    extract_max_length as _extract_max_length,
)

logger = logging.getLogger(__name__)

# ── Type-specific overflow values ─────────────────────────────

_INT_OVERFLOW: dict[str, list[tuple[Any, str]]] = {
    "TINYINT": [(-129, "below TINYINT min"), (256, "above TINYINT max")],
    "SMALLINT": [(-32769, "below SMALLINT min"), (32768, "above SMALLINT max")],
    "INT": [(-2147483649, "below INT min"), (2147483648, "above INT max")],
    "INTEGER": [(-2147483649, "below INTEGER min"), (2147483648, "above INTEGER max")],
    "BIGINT": [(-9223372036854775809, "below BIGINT min"), (9223372036854775808, "above BIGINT max")],
}

# ── Invalid format patterns ───────────────────────────────────

_INVALID_EMAILS = [
    ("plainaddress", "no @ symbol"),
    ("@missing-local.com", "missing local part"),
    ("user@", "missing domain"),
    ("user@.com", "domain starts with dot"),
    ("user@domain..com", "double dot in domain"),
    ("user name@domain.com", "space in local part"),
]

_INVALID_PHONES = [
    ("abc-def-ghij", "alphabetic characters"),
    ("!@#$%", "special characters only"),
    ("12", "too short"),
    ("+" + "9" * 20, "too long"),
]

_INVALID_DATES = [
    ("not-a-date", "non-date string"),
    ("2025-13-45", "impossible month/day"),
    ("99/99/9999", "invalid date format"),
    ("0000-00-00", "zero date"),
]

_INVALID_UUIDS = [
    ("not-a-uuid", "non-UUID string"),
    ("12345", "too short"),
    ("zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", "invalid hex characters"),
]

_SPECIAL_CHAR_VALUES = [
    ("'; DROP TABLE users; --", "SQL injection attempt"),
    ("<script>alert('xss')</script>", "XSS attempt"),
    ("\\0\\0\\0", "null bytes"),
    ("\t\n\r", "control characters"),
    ("𝕳𝖊𝖑𝖑𝖔", "unicode mathematical symbols"),
    ("a" * 10000, "extremely long string"),
]


class EdgeCaseAnalysisEngine:
    """Analyze a schema and produce a catalog of edge-case test values."""

    def __init__(
        self,
        schema: SchemaMetadata,
        toggles: EdgeCaseToggles | None = None,
        ai_edge_cases: list[AIEdgeCase] | None = None,
    ) -> None:
        self._schema = schema
        self._toggles = toggles or EdgeCaseToggles()
        self._ai_edge_cases = ai_edge_cases or []
        self._rules: list[EdgeCaseRule] = []

    def analyze(self, session_id: str = "") -> EdgeCaseAnalysis:
        """Run the full analysis and return structured results."""
        self._rules = []

        for table in self._schema.tables:
            for col in table.columns:
                self._analyze_column(table, col)

        # Merge AI-inferred edge cases
        self._merge_ai_edge_cases()

        # Build summaries
        summary: dict[str, int] = {}
        for r in self._rules:
            summary[r.category.value] = summary.get(r.category.value, 0) + 1

        col_summaries = self._build_column_summaries()

        analyzed_cols = len({(r.table, r.column) for r in self._rules})
        analyzed_tables = len({r.table for r in self._rules})

        return EdgeCaseAnalysis(
            session_id=session_id,
            rules=self._rules,
            summary=summary,
            column_summaries=col_summaries,
            total_rules=len(self._rules),
            tables_analyzed=analyzed_tables,
            columns_analyzed=analyzed_cols,
        )

    def _analyze_column(self, table: TableMetadata, col: ColumnMetadata) -> None:
        """Generate edge-case rules for a single column."""
        base = _base_type(col.data_type)

        if self._toggles.null_values:
            self._gen_null_rules(table, col)

        if self._toggles.boundary_values:
            self._gen_boundary_rules(table, col, base)

        if self._toggles.negative_values:
            self._gen_negative_rules(table, col, base)

        if self._toggles.overflow_values:
            self._gen_overflow_rules(table, col, base)

        if self._toggles.invalid_formats:
            self._gen_invalid_format_rules(table, col, base)

        if self._toggles.duplicate_values:
            self._gen_duplicate_rules(table, col)

        if self._toggles.type_mismatch:
            self._gen_type_mismatch_rules(table, col, base)

        if self._toggles.empty_values:
            self._gen_empty_rules(table, col, base)

        if self._toggles.special_chars:
            self._gen_special_char_rules(table, col, base)

    # ── NULL values ───────────────────────────────────────────

    def _gen_null_rules(self, table: TableMetadata, col: ColumnMetadata) -> None:
        if not col.nullable and not col.is_primary_key:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.NULL,
                description=f"NULL in NOT NULL column '{col.name}'",
                test_value=None,
                expected_behavior="should be rejected — column is NOT NULL",
                data_type=col.data_type,
            ))
        if col.nullable:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.NULL,
                description=f"NULL in nullable column '{col.name}'",
                test_value=None,
                expected_behavior="should be accepted — column allows NULL",
                data_type=col.data_type,
            ))

    # ── Boundary values ───────────────────────────────────────

    def _gen_boundary_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        check = col.check_constraint or ""

        if base in ("integer", "float"):
            self._gen_numeric_boundaries(table, col, base, check)
        elif base == "string":
            self._gen_string_boundaries(table, col)
        elif base == "date":
            self._gen_date_boundaries(table, col)

    def _gen_numeric_boundaries(
        self, table: TableMetadata, col: ColumnMetadata, base: str, check: str
    ) -> None:
        # Extract bounds from CHECK constraints
        lo: float | int | None = None
        hi: float | int | None = None

        m_gt = re.search(r">\s*([\d.]+)", check)
        m_gte = re.search(r">=\s*([\d.]+)", check)
        m_lt = re.search(r"<\s*([\d.]+)", check)
        m_lte = re.search(r"<=\s*([\d.]+)", check)

        if m_gte:
            lo = float(m_gte.group(1))
        elif m_gt:
            lo = float(m_gt.group(1))
        if m_lte:
            hi = float(m_lte.group(1))
        elif m_lt:
            hi = float(m_lt.group(1))

        cast = int if base == "integer" else float

        if lo is not None:
            # At lower boundary
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} = {cast(lo)} (at lower bound)",
                test_value=cast(lo),
                expected_behavior="at boundary — check if accepted or rejected",
                data_type=col.data_type,
            ))
            # Just below lower boundary
            below = cast(lo) - (1 if base == "integer" else 0.01)
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} = {below} (below lower bound)",
                test_value=below,
                expected_behavior="should be rejected — below minimum",
                data_type=col.data_type,
            ))

        if hi is not None:
            # At upper boundary
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} = {cast(hi)} (at upper bound)",
                test_value=cast(hi),
                expected_behavior="at boundary — check if accepted or rejected",
                data_type=col.data_type,
            ))
            # Just above upper boundary
            above = cast(hi) + (1 if base == "integer" else 0.01)
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} = {above} (above upper bound)",
                test_value=above,
                expected_behavior="should be rejected — above maximum",
                data_type=col.data_type,
            ))

        # Standard numeric boundaries (always useful)
        self._rules.append(EdgeCaseRule(
            table=table.name,
            column=col.name,
            category=EdgeCaseCategory.BOUNDARY,
            description=f"{col.name} = 0 (zero value)",
            test_value=cast(0),
            expected_behavior="check zero handling",
            data_type=col.data_type,
        ))

        # Enum-like values from check constraints
        enums = _extract_enum_from_check(col.check_constraint)
        if enums:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"Invalid enum value for {col.name} (not in {enums})",
                test_value="INVALID_VALUE",
                expected_behavior="should be rejected — not in allowed set",
                data_type=col.data_type,
            ))

    def _gen_string_boundaries(
        self, table: TableMetadata, col: ColumnMetadata
    ) -> None:
        max_len = _extract_max_length(col.data_type)
        if max_len:
            # Exactly at max length
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} at max length ({max_len} chars)",
                test_value="x" * max_len,
                expected_behavior="should be accepted — exactly at limit",
                data_type=col.data_type,
            ))
            # Over max length
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} over max length ({max_len + 10} chars)",
                test_value="x" * (max_len + 10),
                expected_behavior="should be rejected — exceeds max length",
                data_type=col.data_type,
            ))
            # Single character
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.BOUNDARY,
                description=f"{col.name} = single character",
                test_value="a",
                expected_behavior="should be accepted — within length",
                data_type=col.data_type,
            ))

    def _gen_date_boundaries(
        self, table: TableMetadata, col: ColumnMetadata
    ) -> None:
        self._rules.append(EdgeCaseRule(
            table=table.name,
            column=col.name,
            category=EdgeCaseCategory.BOUNDARY,
            description=f"{col.name} = epoch date (1970-01-01)",
            test_value="1970-01-01",
            expected_behavior="check minimum date handling",
            data_type=col.data_type,
        ))
        self._rules.append(EdgeCaseRule(
            table=table.name,
            column=col.name,
            category=EdgeCaseCategory.BOUNDARY,
            description=f"{col.name} = far future date (2099-12-31)",
            test_value="2099-12-31",
            expected_behavior="check far-future date handling",
            data_type=col.data_type,
        ))

    # ── Negative values ───────────────────────────────────────

    def _gen_negative_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        if base not in ("integer", "float"):
            return

        cast = int if base == "integer" else float
        self._rules.append(EdgeCaseRule(
            table=table.name,
            column=col.name,
            category=EdgeCaseCategory.NEGATIVE,
            description=f"{col.name} = -1 (negative value)",
            test_value=cast(-1),
            expected_behavior="check negative number handling",
            data_type=col.data_type,
        ))
        self._rules.append(EdgeCaseRule(
            table=table.name,
            column=col.name,
            category=EdgeCaseCategory.NEGATIVE,
            description=f"{col.name} = {cast(-999)} (large negative)",
            test_value=cast(-999),
            expected_behavior="check large negative handling",
            data_type=col.data_type,
        ))

    # ── Overflow values ───────────────────────────────────────

    def _gen_overflow_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        if base in ("integer",):
            type_upper = col.data_type.upper().split("(")[0].strip()
            overflows = _INT_OVERFLOW.get(type_upper, _INT_OVERFLOW.get("INT", []))
            for val, desc in overflows:
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.OVERFLOW,
                    description=f"{col.name}: {desc} ({val})",
                    test_value=val,
                    expected_behavior="should be rejected — type overflow",
                    data_type=col.data_type,
                ))
        elif base == "float":
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.OVERFLOW,
                description=f"{col.name} = 1e308 (near float max)",
                test_value=1e308,
                expected_behavior="should be rejected — float overflow",
                data_type=col.data_type,
            ))
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.OVERFLOW,
                description=f"{col.name} = -1e308 (near float min)",
                test_value=-1e308,
                expected_behavior="should be rejected — float underflow",
                data_type=col.data_type,
            ))
        elif base == "string":
            max_len = _extract_max_length(col.data_type)
            if max_len:
                overflow_len = max_len * 10
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.OVERFLOW,
                    description=f"{col.name}: string {overflow_len} chars (10x max length)",
                    test_value="A" * overflow_len,
                    expected_behavior="should be rejected — exceeds max length",
                    data_type=col.data_type,
                ))

    # ── Invalid formats ───────────────────────────────────────

    def _gen_invalid_format_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        name_lower = col.name.lower()

        if re.search(r"email", name_lower):
            for bad_val, reason in _INVALID_EMAILS:
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.INVALID_FORMAT,
                    description=f"Invalid email: {reason}",
                    test_value=bad_val,
                    expected_behavior="should be rejected — invalid email format",
                    data_type=col.data_type,
                ))
        elif re.search(r"phone|mobile|cell", name_lower):
            for bad_val, reason in _INVALID_PHONES:
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.INVALID_FORMAT,
                    description=f"Invalid phone: {reason}",
                    test_value=bad_val,
                    expected_behavior="should be rejected — invalid phone format",
                    data_type=col.data_type,
                ))
        elif re.search(r"date|time", name_lower) and base == "string":
            for bad_val, reason in _INVALID_DATES:
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.INVALID_FORMAT,
                    description=f"Invalid date: {reason}",
                    test_value=bad_val,
                    expected_behavior="should be rejected — invalid date format",
                    data_type=col.data_type,
                ))
        elif re.search(r"uuid|guid", name_lower):
            for bad_val, reason in _INVALID_UUIDS:
                self._rules.append(EdgeCaseRule(
                    table=table.name,
                    column=col.name,
                    category=EdgeCaseCategory.INVALID_FORMAT,
                    description=f"Invalid UUID: {reason}",
                    test_value=bad_val,
                    expected_behavior="should be rejected — invalid UUID format",
                    data_type=col.data_type,
                ))

        # Enum-check columns: inject invalid enum value
        enums = _extract_enum_from_check(col.check_constraint)
        if enums:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.INVALID_FORMAT,
                description=f"Value not in enum: {enums}",
                test_value="__INVALID__",
                expected_behavior="should be rejected — not an allowed value",
                data_type=col.data_type,
            ))

    # ── Duplicate values ──────────────────────────────────────

    def _gen_duplicate_rules(self, table: TableMetadata, col: ColumnMetadata) -> None:
        if col.is_primary_key:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.DUPLICATE,
                description=f"Duplicate primary key in '{col.name}'",
                test_value="<duplicate_of_existing>",
                expected_behavior="should be rejected — PK must be unique",
                data_type=col.data_type,
            ))
        if col.is_unique:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.DUPLICATE,
                description=f"Duplicate value in UNIQUE column '{col.name}'",
                test_value="<duplicate_of_existing>",
                expected_behavior="should be rejected — UNIQUE constraint",
                data_type=col.data_type,
            ))

    # ── Type mismatch ─────────────────────────────────────────

    def _gen_type_mismatch_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        mismatches: list[tuple[Any, str]] = []

        if base in ("integer", "float"):
            mismatches = [
                ("not_a_number", "string instead of number"),
                (True, "boolean instead of number"),
            ]
        elif base == "boolean":
            mismatches = [
                ("maybe", "non-boolean string"),
                (42, "integer instead of boolean"),
            ]
        elif base in ("date", "datetime"):
            mismatches = [
                (12345, "integer instead of date"),
                ("not-a-date", "non-date string"),
            ]

        for val, desc in mismatches:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.TYPE_MISMATCH,
                description=f"{col.name}: {desc}",
                test_value=val,
                expected_behavior="should be rejected — wrong data type",
                data_type=col.data_type,
            ))

    # ── Empty values ──────────────────────────────────────────

    def _gen_empty_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        if base == "string":
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.EMPTY,
                description=f"{col.name} = empty string",
                test_value="",
                expected_behavior="check if empty string is treated as NULL",
                data_type=col.data_type,
            ))
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.EMPTY,
                description=f"{col.name} = whitespace only",
                test_value="   ",
                expected_behavior="check whitespace-only handling",
                data_type=col.data_type,
            ))

    # ── Special characters ────────────────────────────────────

    def _gen_special_char_rules(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        if base != "string":
            return

        for val, desc in _SPECIAL_CHAR_VALUES:
            self._rules.append(EdgeCaseRule(
                table=table.name,
                column=col.name,
                category=EdgeCaseCategory.SPECIAL_CHARS,
                description=f"{col.name}: {desc}",
                test_value=val,
                expected_behavior="should be sanitized or rejected",
                data_type=col.data_type,
            ))

    # ── AI edge-case merging ──────────────────────────────────

    def _merge_ai_edge_cases(self) -> None:
        """Merge AI-inferred edge cases into the rule set."""
        for ai_case in self._ai_edge_cases:
            self._rules.append(EdgeCaseRule(
                table=ai_case.table,
                column=ai_case.column,
                category=EdgeCaseCategory.BOUNDARY,
                description=ai_case.scenario,
                test_value=ai_case.test_value,
                expected_behavior="AI-inferred edge case",
                data_type="",
                source="ai",
            ))

    # ── Summary helpers ───────────────────────────────────────

    def _build_column_summaries(self) -> list[EdgeCaseColumnSummary]:
        """Build per-column rule summaries."""
        col_map: dict[tuple[str, str], EdgeCaseColumnSummary] = {}

        for rule in self._rules:
            key = (rule.table, rule.column)
            if key not in col_map:
                col_map[key] = EdgeCaseColumnSummary(
                    table=rule.table,
                    column=rule.column,
                    data_type=rule.data_type,
                )
            summary = col_map[key]
            summary.rule_count += 1
            if rule.category.value not in summary.categories:
                summary.categories.append(rule.category.value)

        return list(col_map.values())
