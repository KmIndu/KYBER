"""Negative / edge-case data generator.

Derives invalid test rows from a valid dataset by systematically violating
constraints: broken FKs, null required fields, invalid emails, duplicate
PKs, boundary values, invalid enums, and invalid regex patterns.
"""

from __future__ import annotations

import logging
import random
import re
import string
from typing import Any

from app.generators.synthetic_generator import SyntheticDataGenerator
from app.models.negative import NegativeDataset, NegativeRow, NegativeToggles
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.utils.sql_types import (
    base_type as _base_type,
    extract_enum_from_check as _extract_enum_from_check,
    extract_max_length as _extract_max_length,
)

logger = logging.getLogger(__name__)

# ── Invalid email patterns ────────────────────────────────────

_INVALID_EMAILS = [
    "plainaddress",
    "@missing-local.com",
    "user@",
    "user@.com",
    "user@domain..com",
    "user name@domain.com",
    "user@domain,com",
    "user@domain@domain.com",
    ".user@domain.com",
    "user.@domain.com",
    "user@-domain.com",
    "user@domain.c",
]


class NegativeCaseGenerator:
    """Generate invalid / edge-case test data from parsed schema metadata.

    Works alongside SyntheticDataGenerator: first generates a valid dataset,
    then derives invalid rows by systematically violating constraints.
    """

    def __init__(
        self,
        schema: SchemaMetadata,
        row_count: int = 10,
        toggles: NegativeToggles | None = None,
    ) -> None:
        self._schema = schema
        self._row_count = row_count
        self._toggles = toggles or NegativeToggles()
        self._valid_data: dict[str, list[dict[str, Any]]] = {}
        self._invalid_rows: list[NegativeRow] = []

    def generate(self) -> NegativeDataset:
        """Generate both valid and invalid datasets.

        The total number of invalid rows produced will be exactly
        ``self._row_count``.  The generator first discovers all possible
        violation templates from the schema, then scales them (repeating
        with randomised base rows) to hit the requested count exactly.
        """
        # Step 1: generate valid data via existing pipeline
        gen = SyntheticDataGenerator(self._schema, self._row_count)
        self._valid_data = gen.generate()

        table_map = {t.name: t for t in self._schema.tables}

        # Step 2: derive *template* invalid rows per toggle
        for table_name, rows in self._valid_data.items():
            table = table_map[table_name]
            if not rows:
                continue
            base_row = rows[0]

            if self._toggles.invalid_emails:
                self._gen_invalid_emails(table, base_row)

            if self._toggles.null_required_fields:
                self._gen_null_required(table, base_row)

            if self._toggles.duplicate_values:
                self._gen_duplicates(table, rows)

            if self._toggles.broken_foreign_keys:
                self._gen_broken_fks(table, base_row)

            if self._toggles.boundary_values:
                self._gen_boundary_values(table, base_row)

            if self._toggles.invalid_enums:
                self._gen_invalid_enums(table, base_row)

            if self._toggles.invalid_regex_patterns:
                self._gen_invalid_regex(table, base_row)

        # Step 3: scale to exactly row_count
        self._invalid_rows = self._scale_to_target(
            self._invalid_rows, self._row_count, table_map
        )

        # Build summary
        summary: dict[str, int] = {}
        for neg in self._invalid_rows:
            summary[neg.violation] = summary.get(neg.violation, 0) + 1

        return NegativeDataset(
            valid=self._valid_data,
            invalid=self._invalid_rows,
            summary=summary,
        )

    # ── Scale to exact target count ───────────────────────────

    def _scale_to_target(
        self,
        templates: list[NegativeRow],
        target: int,
        table_map: dict[str, TableMetadata],
    ) -> list[NegativeRow]:
        """Scale the list of negative rows to exactly ``target`` entries.

        If fewer templates exist than target, cycles through them using
        different base rows from the valid dataset to create varied copies.
        If more templates exist than target, truncates (keeping a balanced
        distribution across violation types).
        """
        if not templates:
            return templates

        if len(templates) == target:
            return templates

        if len(templates) > target:
            # Trim evenly across violation types
            return self._trim_to_target(templates, target)

        # Need to scale UP: repeat templates with randomised base rows
        result = list(templates)
        remaining = target - len(result)

        # Gather all valid rows per table for variation
        table_rows: dict[str, list[dict[str, Any]]] = self._valid_data

        while remaining > 0:
            batch_size = min(remaining, len(templates))
            for i in range(batch_size):
                template = templates[i % len(templates)]
                # Pick a random base row from the same table
                available_rows = table_rows.get(template.table, [])
                if available_rows:
                    base_row = random.choice(available_rows)
                    # Re-apply the violation on the new base row
                    new_row = dict(base_row)
                    new_row[template.column] = template.row.get(template.column)
                else:
                    new_row = dict(template.row)

                result.append(
                    NegativeRow(
                        table=template.table,
                        violation=template.violation,
                        column=template.column,
                        description=template.description,
                        row=new_row,
                    )
                )
            remaining = target - len(result)

        return result[:target]

    def _trim_to_target(
        self, rows: list[NegativeRow], target: int
    ) -> list[NegativeRow]:
        """Trim rows to target while keeping a balanced violation type distribution."""
        if len(rows) <= target:
            return rows[:target]

        # Group by violation type
        by_type: dict[str, list[NegativeRow]] = {}
        for r in rows:
            by_type.setdefault(r.violation, []).append(r)

        # Distribute target evenly, then fill remainder round-robin
        num_types = len(by_type)
        per_type = target // num_types
        extra = target % num_types

        result: list[NegativeRow] = []
        overflow: list[NegativeRow] = []

        for i, (vtype, vrows) in enumerate(by_type.items()):
            take = per_type + (1 if i < extra else 0)
            result.extend(vrows[:take])
            # Keep leftover rows for backfill if some types were short
            if len(vrows) > take:
                overflow.extend(vrows[take:])

        # If some types had fewer rows than their allotment, backfill from overflow
        if len(result) < target and overflow:
            needed = target - len(result)
            result.extend(overflow[:needed])

        return result[:target]

    # ── Invalid emails ────────────────────────────────────────

    def _gen_invalid_emails(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        email_cols = [
            c for c in table.columns if re.search(r"email", c.name, re.I)
        ]
        for col in email_cols:
            for bad_email in _INVALID_EMAILS:
                row = dict(base_row)
                row[col.name] = bad_email
                self._invalid_rows.append(
                    NegativeRow(
                        table=table.name,
                        violation="invalid_email",
                        column=col.name,
                        description=f"Invalid email format: {bad_email}",
                        row=row,
                    )
                )

    # ── Null required fields ──────────────────────────────────

    def _gen_null_required(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        required_cols = [
            c
            for c in table.columns
            if not c.nullable and not c.is_primary_key
        ]
        for col in required_cols:
            row = dict(base_row)
            row[col.name] = None
            self._invalid_rows.append(
                NegativeRow(
                    table=table.name,
                    violation="null_required",
                    column=col.name,
                    description=f"NULL in NOT NULL column: {col.name}",
                    row=row,
                )
            )

    # ── Duplicate values ──────────────────────────────────────

    def _gen_duplicates(
        self, table: TableMetadata, rows: list[dict[str, Any]]
    ) -> None:
        unique_cols = [c for c in table.columns if c.is_unique or c.is_primary_key]
        for col in unique_cols:
            if not rows:
                continue
            existing_value = rows[0].get(col.name)
            # Create a second row that reuses the same unique value
            dup_row = dict(rows[-1]) if len(rows) > 1 else dict(rows[0])
            dup_row[col.name] = existing_value
            self._invalid_rows.append(
                NegativeRow(
                    table=table.name,
                    violation="duplicate_value",
                    column=col.name,
                    description=f"Duplicate value '{existing_value}' in unique column: {col.name}",
                    row=dup_row,
                )
            )

    # ── Broken foreign keys ───────────────────────────────────

    def _gen_broken_fks(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        for fk in table.foreign_keys:
            # Collect actual parent PK values to ensure we pick something NOT in them
            parent_rows = self._valid_data.get(fk.references_table, [])
            parent_values = {r.get(fk.references_column) for r in parent_rows}

            # Generate a value guaranteed to not exist in parent
            bad_value = -999999
            while bad_value in parent_values:
                bad_value -= 1

            row = dict(base_row)
            row[fk.column] = bad_value
            self._invalid_rows.append(
                NegativeRow(
                    table=table.name,
                    violation="broken_fk",
                    column=fk.column,
                    description=(
                        f"FK {fk.column} → {fk.references_table}.{fk.references_column}"
                        f" references non-existent value: {bad_value}"
                    ),
                    row=row,
                )
            )

    # ── Boundary values ───────────────────────────────────────

    def _gen_boundary_values(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        for col in table.columns:
            base = _base_type(col.data_type)
            check = col.check_constraint or ""

            # Numeric boundaries from CHECK (col > N)
            if base in ("integer", "float"):
                m_gt = re.search(r">\s*([\d.]+)", check)
                if m_gt:
                    boundary = float(m_gt.group(1))
                    # Value at boundary (equals, not greater-than)
                    at_boundary = int(boundary) if base == "integer" else boundary
                    row = dict(base_row)
                    row[col.name] = at_boundary
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"At boundary: {col.name} = {at_boundary} (constraint: > {boundary})",
                            row=row,
                        )
                    )
                    # Value below boundary
                    below = int(boundary) - 1 if base == "integer" else boundary - 0.01
                    row2 = dict(base_row)
                    row2[col.name] = below
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"Below boundary: {col.name} = {below} (constraint: > {boundary})",
                            row=row2,
                        )
                    )
                    # Zero
                    row3 = dict(base_row)
                    row3[col.name] = 0
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"Zero value: {col.name} = 0",
                            row=row3,
                        )
                    )
                    # Negative
                    row4 = dict(base_row)
                    row4[col.name] = -1
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"Negative value: {col.name} = -1",
                            row=row4,
                        )
                    )

            # String length boundaries
            if base == "string":
                max_len = _extract_max_length(col.data_type)
                if max_len:
                    # Over max length
                    over = "x" * (max_len + 10)
                    row = dict(base_row)
                    row[col.name] = over
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"Over max length ({max_len}): {col.name} len={len(over)}",
                            row=row,
                        )
                    )
                    # Empty string
                    row2 = dict(base_row)
                    row2[col.name] = ""
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="boundary_value",
                            column=col.name,
                            description=f"Empty string: {col.name}",
                            row=row2,
                        )
                    )

    # ── Invalid enums ─────────────────────────────────────────

    def _gen_invalid_enums(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        for col in table.columns:
            enum_values = _extract_enum_from_check(col.check_constraint)
            if not enum_values:
                continue
            # Value not in the enum
            bad_values = [
                "INVALID_STATUS",
                "unknown",
                "",
                "null",
                "42",
            ]
            for bad in bad_values:
                if bad not in enum_values:
                    row = dict(base_row)
                    row[col.name] = bad
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="invalid_enum",
                            column=col.name,
                            description=f"Invalid enum '{bad}' not in {enum_values}",
                            row=row,
                        )
                    )
                    break  # one bad value per column is enough

    # ── Invalid regex patterns ────────────────────────────────

    def _gen_invalid_regex(
        self, table: TableMetadata, base_row: dict[str, Any]
    ) -> None:
        for col in table.columns:
            base = _base_type(col.data_type)
            if base != "string":
                continue

            # Email columns get specific invalid patterns (already covered above),
            # but for general string columns we inject type-mismatch values.
            if re.search(r"email", col.name, re.I):
                continue  # handled by invalid_emails toggle

            # Phone columns: inject non-numeric
            if re.search(r"phone|mobile|cell", col.name, re.I):
                bad_phones = ["abc-def-ghij", "!@#$%", "12"]
                for bad in bad_phones:
                    row = dict(base_row)
                    row[col.name] = bad
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="invalid_regex",
                            column=col.name,
                            description=f"Invalid phone format: {bad}",
                            row=row,
                        )
                    )
                break

            # Date-named string columns: inject non-date
            if re.search(r"date|time", col.name, re.I):
                bad_dates = ["not-a-date", "2025-13-45", "99/99/9999"]
                for bad in bad_dates:
                    row = dict(base_row)
                    row[col.name] = bad
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="invalid_regex",
                            column=col.name,
                            description=f"Invalid date format: {bad}",
                            row=row,
                        )
                    )
                break

            # UUID columns: inject invalid UUID
            if re.search(r"uuid|guid", col.name, re.I):
                bad_uuids = ["not-a-uuid", "12345", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"]
                for bad in bad_uuids:
                    row = dict(base_row)
                    row[col.name] = bad
                    self._invalid_rows.append(
                        NegativeRow(
                            table=table.name,
                            violation="invalid_regex",
                            column=col.name,
                            description=f"Invalid UUID format: {bad}",
                            row=row,
                        )
                    )
                break
