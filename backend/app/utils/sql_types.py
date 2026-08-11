"""Shared SQL type mapping and constraint-extraction utilities.

Centralizes the type-mapping logic used by generators, validators, and
converters so that changes to type recognition propagate everywhere.
"""

from __future__ import annotations

import re

# ── SQL type → base-category mapping ──────────────────────────

SQL_TYPE_MAP: dict[str, str] = {
    "INT": "integer",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "SMALLINT": "integer",
    "TINYINT": "integer",
    "SERIAL": "integer",
    "BIGSERIAL": "integer",
    "SMALLSERIAL": "integer",
    "MEDIUMINT": "integer",
    "FLOAT": "float",
    "DOUBLE": "float",
    "REAL": "float",
    "DECIMAL": "float",
    "NUMERIC": "float",
    "VARCHAR": "string",
    "CHAR": "string",
    "TEXT": "string",
    "NVARCHAR": "string",
    "NCHAR": "string",
    "BOOLEAN": "boolean",
    "BOOL": "boolean",
    "DATE": "date",
    "DATETIME": "datetime",
    "TIMESTAMP": "datetime",
    "UUID": "uuid",
    "BLOB": "string",
}


def base_type(data_type: str) -> str:
    """Map a SQL type string (e.g. ``VARCHAR(100)``) to a base category.

    Returns one of: ``integer``, ``float``, ``string``, ``boolean``,
    ``date``, ``datetime``, ``uuid``.  Defaults to ``string`` for
    unrecognised types.
    """
    upper = data_type.upper().split("(")[0].strip()
    return SQL_TYPE_MAP.get(upper, "string")


def extract_enum_from_check(check: str | None) -> list[str] | None:
    """Extract allowed values from a ``CHECK (col IN ('a','b','c'))`` clause.

    Returns ``None`` when the check expression does not contain an ``IN (...)``
    clause, or the list of extracted string values otherwise.
    """
    if not check:
        return None
    m = re.search(r"IN\s*\(([^)]+)\)", check, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1)
    values = [v.strip().strip("'\"") for v in raw.split(",")]
    return values if values else None


def extract_max_length(data_type: str) -> int | None:
    """Extract the length argument from ``VARCHAR(100)`` / ``TEXT(50)`` etc.

    Returns ``None`` when the type has no length specifier.
    """
    m = re.search(r"\((\d+)", data_type)
    return int(m.group(1)) if m else None


def extract_precision(data_type: str) -> int:
    """Extract decimal precision from ``DECIMAL(12,2)`` / ``NUMERIC(15,4)``.

    Defaults to ``2`` when no precision is specified.
    """
    m = re.search(r",\s*(\d+)\)", data_type)
    return int(m.group(1)) if m else 2
