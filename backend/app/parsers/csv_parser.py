"""CSV parser — infers schema metadata from CSV content.

Reads headers and samples rows to detect data types, nullability,
uniqueness, and potential primary/foreign key relationships.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import Counter

from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)

logger = logging.getLogger(__name__)

_MAX_SAMPLE_ROWS = 500


class CSVParserError(Exception):
    """Raised when CSV parsing fails."""


def parse_csv_schema(
    text: str,
    table_name: str = "imported_table",
) -> SchemaMetadata:
    """Infer a SQL schema from CSV content.

    Reads headers as column names and samples up to 500 rows to
    detect types, nullability, uniqueness, and potential keys.
    """
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)

    try:
        headers = next(reader)
    except StopIteration:
        raise CSVParserError("CSV file is empty — no header row found")

    headers = [_clean_header(h) for h in headers]
    if not headers or all(h == "" for h in headers):
        raise CSVParserError("CSV has no usable column headers")

    # De-duplicate empty/duplicate headers
    seen: dict[str, int] = {}
    clean_headers: list[str] = []
    for h in headers:
        if not h:
            h = "column"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        clean_headers.append(h)
    headers = clean_headers

    # Sample rows
    rows: list[list[str]] = []
    for row in reader:
        rows.append(row)
        if len(rows) >= _MAX_SAMPLE_ROWS:
            break

    if not rows:
        # Header-only CSV — all columns VARCHAR, nullable
        columns = [
            ColumnMetadata(name=h, data_type="VARCHAR", nullable=True)
            for h in headers
        ]
        return SchemaMetadata(
            tables=[TableMetadata(name=table_name, columns=columns)]
        )

    # Analyse each column
    columns: list[ColumnMetadata] = []
    primary_keys: list[str] = []
    n_rows = len(rows)

    for col_idx, col_name in enumerate(headers):
        values = [
            row[col_idx].strip() if col_idx < len(row) else ""
            for row in rows
        ]

        non_empty = [v for v in values if v != ""]
        has_nulls = len(non_empty) < n_rows
        data_type = _infer_type(non_empty)
        is_unique = len(set(non_empty)) == len(non_empty) and len(non_empty) == n_rows

        is_pk = False
        if is_unique and not has_nulls and _looks_like_id(col_name):
            is_pk = True
            primary_keys.append(col_name)

        columns.append(
            ColumnMetadata(
                name=col_name,
                data_type=data_type,
                nullable=has_nulls,
                is_primary_key=is_pk,
                is_unique=is_unique and not is_pk,
            )
        )

    # Detect potential foreign keys (columns named *_id that aren't PK)
    fks: list[ForeignKeyMetadata] = []
    for col in columns:
        if col.name.endswith("_id") and not col.is_primary_key:
            ref_table = col.name[:-3]  # "customer_id" → "customer"
            fks.append(
                ForeignKeyMetadata(
                    column=col.name,
                    references_table=ref_table,
                    references_column="id",
                )
            )

    table = TableMetadata(
        name=table_name,
        columns=columns,
        primary_keys=primary_keys,
        foreign_keys=fks,
    )

    logger.info(
        "CSV parsed — table '%s', %d columns, %d rows sampled, %d PKs, %d FKs",
        table_name,
        len(columns),
        n_rows,
        len(primary_keys),
        len(fks),
        extra={"stage": "parsing", "event": "csv_parsed"},
    )

    return SchemaMetadata(tables=[table])


# ── Helpers ───────────────────────────────────────────────────

_HEADER_CLEAN_RE = re.compile(r"[^\w]+")


def _clean_header(raw: str) -> str:
    """Normalise a CSV header into a SQL-friendly column name."""
    cleaned = raw.strip().strip("\ufeff").strip('"').strip("'").strip()
    cleaned = _HEADER_CLEAN_RE.sub("_", cleaned).strip("_").lower()
    return cleaned


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_BOOL_RE = re.compile(r"^(?:true|false|yes|no|0|1)$", re.IGNORECASE)
_DATE_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$"
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _infer_type(values: list[str]) -> str:
    """Infer a SQL data type from a sample of non-empty string values."""
    if not values:
        return "VARCHAR"

    type_counts: Counter[str] = Counter()
    max_len = 0

    for v in values:
        max_len = max(max_len, len(v))
        if _INT_RE.match(v):
            n = int(v)
            if -(2**31) <= n <= 2**31 - 1:
                type_counts["INTEGER"] += 1
            else:
                type_counts["BIGINT"] += 1
        elif _FLOAT_RE.match(v):
            type_counts["DECIMAL"] += 1
        elif _BOOL_RE.match(v):
            type_counts["BOOLEAN"] += 1
        elif _DATE_RE.match(v):
            if "T" in v or " " in v:
                type_counts["TIMESTAMP"] += 1
            else:
                type_counts["DATE"] += 1
        elif _UUID_RE.match(v):
            type_counts["UUID"] += 1
        elif _EMAIL_RE.match(v):
            type_counts["VARCHAR"] += 1
        else:
            type_counts["VARCHAR"] += 1

    if not type_counts:
        return "VARCHAR"

    dominant, dominant_count = type_counts.most_common(1)[0]
    # If ≥80% of values agree on a type, use it
    if dominant_count / len(values) >= 0.8:
        return dominant

    return "VARCHAR"


_ID_PATTERNS = re.compile(r"(?:^id$|^pk$|^key$|^uuid$)", re.IGNORECASE)


def _looks_like_id(col_name: str) -> bool:
    """Heuristic: does the column name look like a primary key?
    
    Matches bare 'id', 'pk', 'key', 'uuid' but NOT compound FK
    names like 'customer_id'.
    """
    return bool(_ID_PATTERNS.search(col_name))
