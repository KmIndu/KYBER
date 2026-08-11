"""Constraint Enforcement Engine — schema-aware enforcement with reusable validators.

Enforces:
- nullable constraints (NOT NULL)
- regex patterns (explicit CHECK patterns + column-name heuristics)
- enums (CHECK IN(...) values)
- uniqueness (single-column UNIQUE)
- ranges (numeric min/max, string length)
- composite keys (multi-column uniqueness)

Each enforcer is a standalone reusable class that can be used independently
or orchestrated by the ConstraintEnforcementEngine.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.models.constraint import (
    ConstraintSummary,
    ConstraintType,
    ConstraintViolation,
    EnforcementReport,
    TableEnforcementReport,
)
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.utils.sql_types import (
    base_type as _base_type,
    extract_enum_from_check,
    extract_max_length,
)


# ── Reusable Enforcer Classes ─────────────────────────────────


class NullableEnforcer:
    """Enforce NOT NULL constraints on columns."""

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []
        not_null_cols = [c for c in table.columns if not c.nullable]

        for col in not_null_cols:
            for i, row in enumerate(rows):
                if row.get(col.name) is None:
                    violations.append(
                        ConstraintViolation(
                            table=table.name,
                            row_index=i,
                            columns=[col.name],
                            constraint_type=ConstraintType.NULLABLE,
                            constraint_definition=f"{col.name} NOT NULL",
                            value="NULL",
                            expected="non-null value",
                            message=f"NULL value in NOT NULL column '{col.name}' at row {i}",
                        )
                    )
        return violations

    def count_checks(self, table: TableMetadata, row_count: int) -> int:
        """Count total nullable checks performed."""
        not_null_cols = [c for c in table.columns if not c.nullable]
        return len(not_null_cols) * row_count


class RegexEnforcer:
    """Enforce regex pattern constraints.

    Checks:
    1. Explicit CHECK constraints containing regex patterns
    2. Column-name heuristics (email, phone, uuid patterns)
    """

    _NAME_PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
        (
            re.compile(r"email", re.I),
            re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$"),
            "email format (user@domain.tld)",
        ),
        (
            re.compile(r"phone|mobile|cell", re.I),
            re.compile(r"^[\d\s\-\(\)\+\.]+(x\d+)?$"),
            "phone format",
        ),
        (
            re.compile(r"uuid|guid", re.I),
            re.compile(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                re.I,
            ),
            "UUID format (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)",
        ),
        (
            re.compile(r"^ip_?addr|ip_?address$", re.I),
            re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
            "IPv4 format",
        ),
        (
            re.compile(r"url|website|homepage", re.I),
            re.compile(r"^https?://\S+$"),
            "URL format (https://...)",
        ),
        (
            re.compile(r"zip_?code|postal_?code", re.I),
            re.compile(r"^\d{5}(-\d{4})?$"),
            "ZIP code format (XXXXX or XXXXX-XXXX)",
        ),
    ]

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []

        for col in table.columns:
            patterns = self._get_patterns(col)
            if not patterns:
                continue

            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue
                if not isinstance(val, str):
                    continue

                for regex, description, definition in patterns:
                    if not regex.match(val):
                        violations.append(
                            ConstraintViolation(
                                table=table.name,
                                row_index=i,
                                columns=[col.name],
                                constraint_type=ConstraintType.REGEX,
                                constraint_definition=definition,
                                value=str(val),
                                expected=description,
                                message=(
                                    f"Value '{val}' does not match pattern "
                                    f"'{description}' for '{col.name}' at row {i}"
                                ),
                            )
                        )
        return violations

    def count_checks(self, table: TableMetadata, rows: list[dict[str, Any]]) -> int:
        """Count regex checks performed (only non-null string values)."""
        count = 0
        for col in table.columns:
            patterns = self._get_patterns(col)
            if not patterns:
                continue
            for row in rows:
                val = row.get(col.name)
                if val is not None and isinstance(val, str):
                    count += len(patterns)
        return count

    def _get_patterns(
        self, col: ColumnMetadata
    ) -> list[tuple[re.Pattern[str], str, str]]:
        """Get all applicable regex patterns for a column."""
        patterns: list[tuple[re.Pattern[str], str, str]] = []

        # Explicit CHECK constraint with regex-like pattern
        if col.check_constraint:
            explicit = self._extract_regex_from_check(col.check_constraint)
            if explicit:
                patterns.append(
                    (explicit, f"pattern: {explicit.pattern}", f"CHECK({col.check_constraint})")
                )

        # Name-based heuristics
        for name_pat, value_pat, desc in self._NAME_PATTERNS:
            if name_pat.search(col.name):
                patterns.append((value_pat, desc, f"{col.name} ~ {desc}"))
                break  # Only one heuristic match per column

        return patterns

    @staticmethod
    def _extract_regex_from_check(check: str) -> re.Pattern[str] | None:
        """Try to extract a regex from a CHECK constraint like CHECK(col ~ '^pattern$')."""
        m = re.search(r"~\s*'([^']+)'", check)
        if m:
            try:
                return re.compile(m.group(1))
            except re.error:
                return None
        # LIKE pattern conversion
        m = re.search(r"LIKE\s+'([^']+)'", check, re.I)
        if m:
            like = m.group(1)
            regex_str = "^" + like.replace("%", ".*").replace("_", ".") + "$"
            try:
                return re.compile(regex_str)
            except re.error:
                return None
        return None


class EnumEnforcer:
    """Enforce CHECK IN(...) enum constraints."""

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []

        for col in table.columns:
            enum_values = extract_enum_from_check(col.check_constraint)
            if not enum_values:
                continue

            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue
                if str(val) not in enum_values:
                    violations.append(
                        ConstraintViolation(
                            table=table.name,
                            row_index=i,
                            columns=[col.name],
                            constraint_type=ConstraintType.ENUM,
                            constraint_definition=f"{col.name} IN ({', '.join(enum_values)})",
                            value=str(val),
                            expected=f"one of: {enum_values}",
                            message=(
                                f"Value '{val}' not in allowed values {enum_values} "
                                f"for '{col.name}' at row {i}"
                            ),
                        )
                    )
        return violations

    def count_checks(self, table: TableMetadata, rows: list[dict[str, Any]]) -> int:
        """Count enum checks performed."""
        count = 0
        for col in table.columns:
            enum_values = extract_enum_from_check(col.check_constraint)
            if enum_values:
                count += sum(1 for row in rows if row.get(col.name) is not None)
        return count


class UniqueEnforcer:
    """Enforce single-column UNIQUE constraints."""

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []

        unique_cols = [c for c in table.columns if c.is_unique]
        pk_cols = set(table.primary_keys) | {
            c.name for c in table.columns if c.is_primary_key
        }

        for col in unique_cols:
            if col.name in pk_cols:
                continue  # PK uniqueness handled separately

            seen: dict[Any, int] = {}
            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue  # NULLs don't violate UNIQUE
                if val in seen:
                    violations.append(
                        ConstraintViolation(
                            table=table.name,
                            row_index=i,
                            columns=[col.name],
                            constraint_type=ConstraintType.UNIQUE,
                            constraint_definition=f"UNIQUE({col.name})",
                            value=str(val),
                            expected=f"unique value (first seen at row {seen[val]})",
                            message=(
                                f"Duplicate value '{val}' in UNIQUE column '{col.name}' "
                                f"at row {i} (first at row {seen[val]})"
                            ),
                        )
                    )
                else:
                    seen[val] = i
        return violations

    def count_checks(self, table: TableMetadata, rows: list[dict[str, Any]]) -> int:
        """Count uniqueness checks performed."""
        unique_cols = [c for c in table.columns if c.is_unique]
        pk_cols = set(table.primary_keys) | {
            c.name for c in table.columns if c.is_primary_key
        }
        cols = [c for c in unique_cols if c.name not in pk_cols]
        count = 0
        for col in cols:
            count += sum(1 for row in rows if row.get(col.name) is not None)
        return count


class RangeEnforcer:
    """Enforce numeric range (min/max) and string length constraints.

    Extracts range information from:
    - CHECK constraints like CHECK(age >= 0 AND age <= 150)
    - VARCHAR(n) length limits
    - DECIMAL(p,s) precision constraints
    """

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []

        for col in table.columns:
            constraints = self._extract_range(col)
            if not constraints:
                continue

            min_val, max_val, max_len = constraints

            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue

                # Numeric range check
                if min_val is not None and isinstance(val, (int, float)):
                    if val < min_val:
                        violations.append(
                            ConstraintViolation(
                                table=table.name,
                                row_index=i,
                                columns=[col.name],
                                constraint_type=ConstraintType.RANGE,
                                constraint_definition=f"{col.name} >= {min_val}",
                                value=str(val),
                                expected=f">= {min_val}",
                                message=(
                                    f"Value {val} below minimum {min_val} "
                                    f"for '{col.name}' at row {i}"
                                ),
                            )
                        )

                if max_val is not None and isinstance(val, (int, float)):
                    if val > max_val:
                        violations.append(
                            ConstraintViolation(
                                table=table.name,
                                row_index=i,
                                columns=[col.name],
                                constraint_type=ConstraintType.RANGE,
                                constraint_definition=f"{col.name} <= {max_val}",
                                value=str(val),
                                expected=f"<= {max_val}",
                                message=(
                                    f"Value {val} above maximum {max_val} "
                                    f"for '{col.name}' at row {i}"
                                ),
                            )
                        )

                # String length check
                if max_len is not None and isinstance(val, str):
                    if len(val) > max_len:
                        violations.append(
                            ConstraintViolation(
                                table=table.name,
                                row_index=i,
                                columns=[col.name],
                                constraint_type=ConstraintType.RANGE,
                                constraint_definition=f"LENGTH({col.name}) <= {max_len}",
                                value=f"'{val[:50]}...' (len={len(val)})",
                                expected=f"length <= {max_len}",
                                message=(
                                    f"String length {len(val)} exceeds max {max_len} "
                                    f"for '{col.name}' at row {i}"
                                ),
                            )
                        )
        return violations

    def count_checks(self, table: TableMetadata, rows: list[dict[str, Any]]) -> int:
        """Count range checks performed."""
        count = 0
        for col in table.columns:
            constraints = self._extract_range(col)
            if constraints:
                count += sum(1 for row in rows if row.get(col.name) is not None)
        return count

    def _extract_range(
        self, col: ColumnMetadata
    ) -> tuple[float | None, float | None, int | None] | None:
        """Extract (min_val, max_val, max_length) from column definition."""
        min_val: float | None = None
        max_val: float | None = None
        max_len: int | None = None

        # String length from type definition
        base = _base_type(col.data_type)
        if base == "string":
            max_len = extract_max_length(col.data_type)

        # Numeric range from CHECK constraint
        if col.check_constraint:
            min_val, max_val = self._parse_range_check(col.check_constraint, col.name)

        if min_val is None and max_val is None and max_len is None:
            return None
        return min_val, max_val, max_len

    @staticmethod
    def _parse_range_check(
        check: str, col_name: str
    ) -> tuple[float | None, float | None]:
        """Parse min/max from CHECK constraints like 'age >= 0 AND age <= 150'."""
        min_val: float | None = None
        max_val: float | None = None

        # Pattern: col >= N or col > N
        for m in re.finditer(
            rf"{re.escape(col_name)}\s*>=?\s*([\d.]+)", check, re.I
        ):
            val = float(m.group(1))
            if min_val is None or val > min_val:
                min_val = val

        # Pattern: N <= col
        for m in re.finditer(
            rf"([\d.]+)\s*<=?\s*{re.escape(col_name)}", check, re.I
        ):
            val = float(m.group(1))
            if min_val is None or val > min_val:
                min_val = val

        # Pattern: col <= N or col < N
        for m in re.finditer(
            rf"{re.escape(col_name)}\s*<=?\s*([\d.]+)", check, re.I
        ):
            val = float(m.group(1))
            if val != min_val:
                if max_val is None or val < max_val:
                    max_val = val

        # Pattern: N >= col
        for m in re.finditer(
            rf"([\d.]+)\s*>=?\s*{re.escape(col_name)}", check, re.I
        ):
            val = float(m.group(1))
            if max_val is None or val < max_val:
                max_val = val

        return min_val, max_val


class CompositeKeyEnforcer:
    """Enforce multi-column uniqueness (composite keys and multi-column UNIQUE constraints).

    Checks:
    - Composite primary keys (multi-column PKs)
    - Multi-column UNIQUE constraints from unique_constraints field
    """

    def enforce(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []

        # Composite PK (multi-column primary key)
        pk_cols = table.primary_keys or [
            c.name for c in table.columns if c.is_primary_key
        ]
        if len(pk_cols) > 1:
            violations.extend(
                self._check_composite(table.name, pk_cols, rows, "PRIMARY KEY")
            )

        # Multi-column UNIQUE constraints
        for constraint_cols in table.unique_constraints:
            if len(constraint_cols) > 1:
                violations.extend(
                    self._check_composite(table.name, constraint_cols, rows, "UNIQUE")
                )

        return violations

    def count_checks(self, table: TableMetadata, row_count: int) -> int:
        """Count composite key checks."""
        count = 0
        pk_cols = table.primary_keys or [
            c.name for c in table.columns if c.is_primary_key
        ]
        if len(pk_cols) > 1:
            count += row_count
        for constraint_cols in table.unique_constraints:
            if len(constraint_cols) > 1:
                count += row_count
        return count

    def _check_composite(
        self,
        table_name: str,
        cols: list[str],
        rows: list[dict[str, Any]],
        constraint_label: str,
    ) -> list[ConstraintViolation]:
        """Check that multi-column combination is unique."""
        violations: list[ConstraintViolation] = []
        seen: dict[tuple, int] = {}
        col_str = ", ".join(cols)

        for i, row in enumerate(rows):
            key = tuple(row.get(c) for c in cols)
            # Skip if any component is None
            if any(v is None for v in key):
                continue
            if key in seen:
                violations.append(
                    ConstraintViolation(
                        table=table_name,
                        row_index=i,
                        columns=cols,
                        constraint_type=ConstraintType.COMPOSITE_KEY,
                        constraint_definition=f"{constraint_label}({col_str})",
                        value=str(key),
                        expected=f"unique combination of ({col_str}) (first at row {seen[key]})",
                        message=(
                            f"Duplicate composite key ({col_str}) = {key} "
                            f"at row {i} (first at row {seen[key]})"
                        ),
                    )
                )
            else:
                seen[key] = i

        return violations


# ── Orchestrator Engine ───────────────────────────────────────


class ConstraintEnforcementEngine:
    """Schema-aware constraint enforcement engine.

    Orchestrates all reusable enforcers across a dataset and produces
    a detailed EnforcementReport with per-table and per-constraint-type
    breakdowns.
    """

    def __init__(self, schema: SchemaMetadata) -> None:
        self._schema = schema
        self._table_map = {t.name: t for t in schema.tables}
        # Reusable enforcer instances
        self._nullable = NullableEnforcer()
        self._regex = RegexEnforcer()
        self._enum = EnumEnforcer()
        self._unique = UniqueEnforcer()
        self._range = RangeEnforcer()
        self._composite = CompositeKeyEnforcer()

    def enforce(
        self, data: dict[str, list[dict[str, Any]]]
    ) -> EnforcementReport:
        """Run all enforcers and produce a comprehensive report."""
        all_violations: list[ConstraintViolation] = []
        table_reports: list[TableEnforcementReport] = []
        total_rows = 0
        total_checks = 0
        type_counters: dict[ConstraintType, dict[str, int]] = defaultdict(
            lambda: {"checks": 0, "violations": 0}
        )

        for table_name, rows in data.items():
            table = self._table_map.get(table_name)
            if not table:
                continue

            row_count = len(rows)
            total_rows += row_count
            table_violations: list[ConstraintViolation] = []
            table_checks = 0

            # Nullable enforcement
            nullable_v = self._nullable.enforce(table, rows)
            nullable_checks = self._nullable.count_checks(table, row_count)
            table_violations.extend(nullable_v)
            table_checks += nullable_checks
            type_counters[ConstraintType.NULLABLE]["checks"] += nullable_checks
            type_counters[ConstraintType.NULLABLE]["violations"] += len(nullable_v)

            # Regex enforcement
            regex_v = self._regex.enforce(table, rows)
            regex_checks = self._regex.count_checks(table, rows)
            table_violations.extend(regex_v)
            table_checks += regex_checks
            type_counters[ConstraintType.REGEX]["checks"] += regex_checks
            type_counters[ConstraintType.REGEX]["violations"] += len(regex_v)

            # Enum enforcement
            enum_v = self._enum.enforce(table, rows)
            enum_checks = self._enum.count_checks(table, rows)
            table_violations.extend(enum_v)
            table_checks += enum_checks
            type_counters[ConstraintType.ENUM]["checks"] += enum_checks
            type_counters[ConstraintType.ENUM]["violations"] += len(enum_v)

            # Uniqueness enforcement
            unique_v = self._unique.enforce(table, rows)
            unique_checks = self._unique.count_checks(table, rows)
            table_violations.extend(unique_v)
            table_checks += unique_checks
            type_counters[ConstraintType.UNIQUE]["checks"] += unique_checks
            type_counters[ConstraintType.UNIQUE]["violations"] += len(unique_v)

            # Range enforcement
            range_v = self._range.enforce(table, rows)
            range_checks = self._range.count_checks(table, rows)
            table_violations.extend(range_v)
            table_checks += range_checks
            type_counters[ConstraintType.RANGE]["checks"] += range_checks
            type_counters[ConstraintType.RANGE]["violations"] += len(range_v)

            # Composite key enforcement
            composite_v = self._composite.enforce(table, rows)
            composite_checks = self._composite.count_checks(table, row_count)
            table_violations.extend(composite_v)
            table_checks += composite_checks
            type_counters[ConstraintType.COMPOSITE_KEY]["checks"] += composite_checks
            type_counters[ConstraintType.COMPOSITE_KEY]["violations"] += len(composite_v)

            # Build per-table summary
            table_type_summary = self._build_table_summary(
                table, rows, row_count,
                nullable_v, regex_v, enum_v, unique_v, range_v, composite_v,
                nullable_checks, regex_checks, enum_checks, unique_checks,
                range_checks, composite_checks,
            )

            table_reports.append(
                TableEnforcementReport(
                    table=table_name,
                    total_rows=row_count,
                    total_checks=table_checks,
                    violations=table_violations,
                    constraints_summary=table_type_summary,
                )
            )
            all_violations.extend(table_violations)
            total_checks += table_checks

        # Build global summary
        summary_by_type = [
            ConstraintSummary(
                constraint_type=ct,
                total_checks=counters["checks"],
                passed=counters["checks"] - counters["violations"],
                failed=counters["violations"],
            )
            for ct, counters in type_counters.items()
            if counters["checks"] > 0
        ]

        compliance_rate = (
            (total_checks - len(all_violations)) / total_checks
            if total_checks > 0
            else 1.0
        )

        return EnforcementReport(
            total_rows=total_rows,
            total_constraints_checked=total_checks,
            total_violations=len(all_violations),
            compliance_rate=round(compliance_rate, 4),
            tables=table_reports,
            violations=all_violations,
            summary_by_type=summary_by_type,
        )

    @staticmethod
    def _build_table_summary(
        table: TableMetadata,
        rows: list[dict[str, Any]],
        row_count: int,
        nullable_v: list,
        regex_v: list,
        enum_v: list,
        unique_v: list,
        range_v: list,
        composite_v: list,
        nullable_checks: int,
        regex_checks: int,
        enum_checks: int,
        unique_checks: int,
        range_checks: int,
        composite_checks: int,
    ) -> list[ConstraintSummary]:
        """Build per-constraint-type summary for a table."""
        summaries = []
        pairs = [
            (ConstraintType.NULLABLE, nullable_checks, len(nullable_v)),
            (ConstraintType.REGEX, regex_checks, len(regex_v)),
            (ConstraintType.ENUM, enum_checks, len(enum_v)),
            (ConstraintType.UNIQUE, unique_checks, len(unique_v)),
            (ConstraintType.RANGE, range_checks, len(range_v)),
            (ConstraintType.COMPOSITE_KEY, composite_checks, len(composite_v)),
        ]
        for ct, checks, fails in pairs:
            if checks > 0:
                summaries.append(
                    ConstraintSummary(
                        constraint_type=ct,
                        total_checks=checks,
                        passed=checks - fails,
                        failed=fails,
                    )
                )
        return summaries
