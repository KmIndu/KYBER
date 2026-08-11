"""Convert BDDMetadata → SchemaMetadata for generator pipeline compatibility.

Extracts unique field names from all BDD rules, infers SQL types from
conditions, and builds a single ``bdd_data`` table.
"""

from __future__ import annotations

import re

from app.models.bdd import BDDMetadata, BDDRule
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata


def bdd_to_schema(bdd: BDDMetadata) -> SchemaMetadata:
    """Build a SchemaMetadata from BDD rules' field references."""
    field_info: dict[str, _FieldHint] = {}

    for scenario in bdd.scenarios:
        for rule in scenario.rules:
            name = _normalize_field_name(rule.field)
            if not name:
                continue
            hint = field_info.setdefault(name, _FieldHint())
            _update_hint(hint, rule.condition)

    if not field_info:
        return SchemaMetadata(tables=[])

    columns: list[ColumnMetadata] = []
    for name, hint in field_info.items():
        columns.append(ColumnMetadata(
            name=name,
            data_type=hint.sql_type(),
            nullable=hint.nullable,
            default=None,
            is_primary_key=False,
            is_unique=False,
            check_constraint=hint.check_constraint(),
        ))

    table = TableMetadata(
        name="bdd_data",
        columns=columns,
        primary_keys=[],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
    )

    return SchemaMetadata(tables=[table])


class _FieldHint:
    """Accumulates type hints from BDD conditions."""

    def __init__(self) -> None:
        self.is_numeric = False
        self.is_string = False
        self.is_email = False
        self.nullable = True
        self.lower: float | None = None
        self.upper: float | None = None

    def sql_type(self) -> str:
        if self.is_email:
            return "VARCHAR"
        if self.is_numeric:
            return "INTEGER"
        return "VARCHAR"

    def check_constraint(self) -> str | None:
        parts: list[str] = []
        if self.lower is not None:
            parts.append(f">= {self.lower}")
        if self.upper is not None:
            parts.append(f"<= {self.upper}")
        return " AND ".join(parts) if parts else None


_NUMBER_RE = re.compile(r"[-+]?\d+\.?\d*")


def _normalize_field_name(raw: str) -> str:
    """Lowercase, strip, collapse spaces → underscores."""
    return re.sub(r"\s+", "_", raw.strip().lower())


def _update_hint(hint: _FieldHint, condition: str) -> None:
    """Refine field hint based on condition string."""
    if not condition:
        return

    cond = condition.lower()

    if "null" in cond:
        hint.nullable = True
        return
    if "not_null" in cond:
        hint.nullable = False
        return
    if "email" in cond or "invalid_format" in cond or "valid_format" in cond:
        hint.is_email = True
        hint.is_string = True
        return

    # Numeric comparisons
    nums = _NUMBER_RE.findall(condition)
    if nums:
        hint.is_numeric = True
        for n in nums:
            val = float(n)
            if "<" in cond:
                hint.upper = val
            elif ">" in cond:
                hint.lower = val
            elif "between" in cond:
                if hint.lower is None:
                    hint.lower = val
                else:
                    hint.upper = val
