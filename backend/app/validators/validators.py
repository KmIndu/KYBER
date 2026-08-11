"""Reusable validator classes for synthetic data validation.

Each validator checks one constraint type across a table's rows
and returns a list of ``ValidationError`` instances.

Validators
----------
- **PKValidator** — primary-key uniqueness and non-null
- **FKValidator** — foreign-key referential integrity
- **UniqueValidator** — UNIQUE column duplicate detection
- **TypeValidator** — data-type conformance
- **EnumValidator** — CHECK(IN(...)) allowed-value conformance
- **NullableValidator** — NOT NULL enforcement
- **RegexValidator** — format heuristics (email, phone, UUID)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.models.schema import ColumnMetadata, ForeignKeyMetadata, TableMetadata
from app.models.validation import ValidationError
from app.utils.sql_types import base_type as _base_type, extract_enum_from_check


# ── Primary Key Validator ─────────────────────────────────────


class PKValidator:
    """Validate that primary key values are unique and non-null."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        pk_cols = table.primary_keys or [
            c.name for c in table.columns if c.is_primary_key
        ]
        if not pk_cols:
            return errors

        seen: dict[str, set] = {col: set() for col in pk_cols}

        for i, row in enumerate(rows):
            for col in pk_cols:
                val = row.get(col)
                if val is None:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col,
                            rule="pk_unique",
                            expected="non-null",
                            actual="None",
                            message=f"Primary key '{col}' is NULL at row {i}",
                        )
                    )
                elif val in seen[col]:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col,
                            rule="pk_unique",
                            expected="unique",
                            actual=str(val),
                            message=f"Duplicate primary key '{col}' = {val} at row {i}",
                        )
                    )
                else:
                    seen[col].add(val)

        return errors


# ── Foreign Key Validator ─────────────────────────────────────


class FKValidator:
    """Validate that foreign key values exist in the referenced parent table."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
        all_data: dict[str, list[dict[str, Any]]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for fk in table.foreign_keys:
            parent_rows = all_data.get(fk.references_table, [])
            parent_values = {r.get(fk.references_column) for r in parent_rows}

            for i, row in enumerate(rows):
                val = row.get(fk.column)
                if val is None:
                    continue  # nullable FK is allowed unless NOT NULL
                if val not in parent_values:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=fk.column,
                            rule="fk_valid",
                            expected=f"value in {fk.references_table}.{fk.references_column}",
                            actual=str(val),
                            message=(
                                f"FK '{fk.column}' = {val} not found in "
                                f"{fk.references_table}.{fk.references_column} at row {i}"
                            ),
                        )
                    )

        return errors


# ── Uniqueness Validator ──────────────────────────────────────


class UniqueValidator:
    """Validate that UNIQUE columns have no duplicate values."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        unique_cols = [c for c in table.columns if c.is_unique and not c.is_primary_key]

        for col in unique_cols:
            seen: set = set()
            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue  # NULL doesn't count for uniqueness
                if val in seen:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col.name,
                            rule="unique",
                            expected="unique",
                            actual=str(val),
                            message=f"Duplicate value '{val}' in unique column '{col.name}' at row {i}",
                        )
                    )
                else:
                    seen.add(val)

        return errors


# ── Data Type Validator ───────────────────────────────────────


class TypeValidator:
    """Validate that column values match the expected data type."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for col in table.columns:
            base = _base_type(col.data_type)
            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue

                if not _check_type(val, base):
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col.name,
                            rule="type",
                            expected=base,
                            actual=type(val).__name__,
                            message=(
                                f"Type mismatch in '{col.name}' at row {i}: "
                                f"expected {base}, got {type(val).__name__}"
                            ),
                        )
                    )

        return errors


def _check_type(value: Any, base: str) -> bool:
    """Check if a value matches the expected base type."""
    if base == "integer":
        return isinstance(value, (int,)) and not isinstance(value, bool)
    elif base == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    elif base == "boolean":
        return isinstance(value, bool)
    elif base == "string":
        return isinstance(value, str)
    elif base == "date":
        if isinstance(value, str):
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
        return isinstance(value, date) and not isinstance(value, datetime)
    elif base == "datetime":
        if isinstance(value, str):
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}T", value))
        return isinstance(value, datetime)
    elif base == "uuid":
        if isinstance(value, str):
            return bool(
                re.match(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    value,
                    re.I,
                )
            )
        return False
    return True  # unknown types pass


# ── Enum Validator ────────────────────────────────────────────


class EnumValidator:
    """Validate that column values are within CHECK(IN(...)) constraints."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for col in table.columns:
            enum_values = extract_enum_from_check(col.check_constraint)
            if not enum_values:
                continue

            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue
                if str(val) not in enum_values:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col.name,
                            rule="enum",
                            expected=str(enum_values),
                            actual=str(val),
                            message=(
                                f"Value '{val}' not in allowed enum {enum_values} "
                                f"for '{col.name}' at row {i}"
                            ),
                        )
                    )

        return errors


# ── Nullable Validator ────────────────────────────────────────


class NullableValidator:
    """Validate that NOT NULL columns have no NULL values."""

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        not_null_cols = [c for c in table.columns if not c.nullable]

        for col in not_null_cols:
            for i, row in enumerate(rows):
                if row.get(col.name) is None:
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col.name,
                            rule="nullable",
                            expected="non-null",
                            actual="None",
                            message=f"NULL in NOT NULL column '{col.name}' at row {i}",
                        )
                    )

        return errors


# ── Regex / Format Validator ──────────────────────────────────


class RegexValidator:
    """Validate column values against format heuristics (email, phone, UUID)."""

    _PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
        (
            re.compile(r"email", re.I),
            re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$"),
            "valid email format",
        ),
        (
            re.compile(r"phone|mobile|cell", re.I),
            re.compile(r"^[\d\s\-\(\)\+\.]+(x\d+)?$"),
            "valid phone format",
        ),
        (
            re.compile(r"uuid|guid", re.I),
            re.compile(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                re.I,
            ),
            "valid UUID format",
        ),
    ]

    def validate(
        self,
        table: TableMetadata,
        rows: list[dict[str, Any]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for col in table.columns:
            pattern_info = self._match_column(col.name)
            if not pattern_info:
                continue

            regex, description = pattern_info
            for i, row in enumerate(rows):
                val = row.get(col.name)
                if val is None:
                    continue
                if not isinstance(val, str):
                    continue
                if not regex.match(val):
                    errors.append(
                        ValidationError(
                            table=table.name,
                            row_index=i,
                            column=col.name,
                            rule="regex",
                            expected=description,
                            actual=str(val),
                            message=(
                                f"Value '{val}' does not match {description} "
                                f"for '{col.name}' at row {i}"
                            ),
                        )
                    )

        return errors

    def _match_column(
        self, col_name: str
    ) -> tuple[re.Pattern[str], str] | None:
        """Return (value_regex, description) if the column name matches a known format."""
        for name_pat, value_pat, desc in self._PATTERNS:
            if name_pat.search(col_name):
                return value_pat, desc
        return None
