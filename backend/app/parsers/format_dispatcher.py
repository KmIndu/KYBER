"""Unified format dispatcher — auto-detect file type and route to correct parser.

Provides content-sniffing beyond file-extension matching so that,
for example, a `.json` file containing a flat array is routed to
the CSV/tabular parser instead of the OpenAPI parser.

Public entry point:
    detect_and_parse(content, filename) → SchemaMetadata
"""

from __future__ import annotations

import json
import logging
import os
import re

from app.models.schema import SchemaMetadata

logger = logging.getLogger(__name__)

# ── Supported format enum ─────────────────────────────────────

FORMATS = ("sql", "openapi", "jsonschema", "bdd", "csv", "xlsx", "xml")

# ── Extension map ─────────────────────────────────────────────

_EXT_MAP: dict[str, str] = {
    ".sql": "sql",
    ".yaml": "openapi",
    ".yml": "openapi",
    ".feature": "bdd",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xml": "xml",
}

# Extensions that need content-sniffing to disambiguate
_AMBIGUOUS_EXTS = {".json", ".txt"}


# ── Public API ────────────────────────────────────────────────


class FormatDetectionError(Exception):
    """Raised when the file format cannot be determined."""


class FormatParseError(Exception):
    """Raised when the detected parser fails."""


def classify_format(filename: str, content: bytes | str) -> str:
    """Determine the file format using extension + content sniffing.

    Returns one of the FORMATS strings.
    """
    ext = _ext(filename)

    # Unambiguous extension → direct lookup
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]

    # Ambiguous extensions need sniffing
    text = _as_text(content)

    if ext == ".json":
        return _sniff_json(text)

    if ext == ".txt":
        return _sniff_txt(text)

    # No known extension — try content sniffing
    if text is not None:
        sniffed = _sniff_content(text)
        if sniffed:
            return sniffed

    raise FormatDetectionError(
        f"Cannot determine format of '{filename}'. "
        f"Supported extensions: {', '.join(sorted(set(_EXT_MAP) | _AMBIGUOUS_EXTS))}"
    )


def detect_and_parse(
    content: bytes | str,
    filename: str,
    *,
    table_name: str | None = None,
) -> SchemaMetadata:
    """Detect format and parse into SchemaMetadata.

    This is the main entry point for the multi-format ingestion layer.
    """
    fmt = classify_format(filename, content)
    tbl = table_name or _derive_table_name(filename)

    logger.info(
        "Format detected: %s for file '%s'",
        fmt,
        filename,
        extra={"stage": "parsing", "event": "format_detected", "format": fmt},
    )

    return _dispatch(fmt, content, tbl, filename)


# ── Dispatcher ────────────────────────────────────────────────


def _dispatch(
    fmt: str,
    content: bytes | str,
    table_name: str,
    filename: str,
) -> SchemaMetadata:
    """Route to the appropriate parser."""
    text = _as_text(content)

    if fmt == "sql":
        from app.parsers.sql_parser import SQLParserError, parse_sql_schema

        try:
            return parse_sql_schema(text)
        except SQLParserError as e:
            raise FormatParseError(f"SQL parse error: {e}") from e

    if fmt == "openapi":
        from app.converters.openapi_to_schema import openapi_to_schema
        from app.parsers.openapi_parser import OpenAPIParserError, parse_openapi_spec

        is_json = filename.lower().endswith(".json")
        try:
            openapi = parse_openapi_spec(text, is_json=is_json)
        except OpenAPIParserError as e:
            raise FormatParseError(f"OpenAPI parse error: {e}") from e
        return openapi_to_schema(openapi)

    if fmt == "jsonschema":
        from app.parsers.jsonschema_parser import JSONSchemaParserError, parse_jsonschema

        try:
            return parse_jsonschema(text, table_name=table_name)
        except JSONSchemaParserError as e:
            raise FormatParseError(f"JSON Schema parse error: {e}") from e

    if fmt == "bdd":
        from app.converters.bdd_to_schema import bdd_to_schema
        from app.parsers.bdd_parser import parse_bdd_feature

        bdd = parse_bdd_feature(text)
        if not bdd.scenarios:
            raise FormatParseError("No BDD scenarios found in file")
        return bdd_to_schema(bdd)

    if fmt == "csv":
        from app.parsers.csv_parser import CSVParserError, parse_csv_schema

        try:
            return parse_csv_schema(text, table_name=table_name)
        except CSVParserError as e:
            raise FormatParseError(f"CSV parse error: {e}") from e

    if fmt == "xlsx":
        from app.parsers.xlsx_parser import XLSXParserError, parse_xlsx_schema

        raw = content if isinstance(content, bytes) else content.encode("latin-1")
        try:
            return parse_xlsx_schema(raw, default_table_name=table_name)
        except XLSXParserError as e:
            raise FormatParseError(f"XLSX parse error: {e}") from e

    if fmt == "xml":
        from app.parsers.xml_parser import XMLParserError, parse_xml_schema

        try:
            return parse_xml_schema(text, default_table_name=table_name)
        except XMLParserError as e:
            raise FormatParseError(f"XML parse error: {e}") from e

    raise FormatDetectionError(f"No parser registered for format '{fmt}'")


# ── Content sniffing heuristics ───────────────────────────────

# OpenAPI indicators
_OPENAPI_KEYS = re.compile(
    r'"(?:openapi|swagger|info|paths|components|definitions)"', re.IGNORECASE
)

_SQL_DDL_RE = re.compile(
    r"(?:CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)", re.IGNORECASE
)

_XML_START_RE = re.compile(r"^\s*<(?:\?xml|[a-zA-Z])")

_GHERKIN_RE = re.compile(
    r"^\s*(?:Feature:|Scenario:|Given |When |Then |And |But )", re.MULTILINE
)


def _sniff_json(text: str) -> str:
    """Determine whether a .json file is OpenAPI, JSON Schema, or tabular data."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Not valid JSON — treat as plain text / BDD
        return "bdd"

    if isinstance(data, dict):
        keys_lower = {k.lower() for k in data.keys()}
        if keys_lower & {"openapi", "swagger", "paths", "info"}:
            return "openapi"
        # Detect JSON Schema: has "type" + "properties", or "$schema", or "definitions"/$defs
        if ("properties" in data and ("type" in data or "$schema" in data)) or "$defs" in data or "definitions" in data:
            return "jsonschema"
        # Single-object JSON → treat as CSV-like (one row)
        return "csv"

    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return "csv"
        return "csv"

    return "openapi"  # fallback for scalar JSON


def _sniff_txt(text: str) -> str:
    """Determine whether a .txt file is BDD, SQL, or CSV."""
    if _GHERKIN_RE.search(text):
        return "bdd"
    if _SQL_DDL_RE.search(text):
        return "sql"
    # Check if it looks like CSV (has commas/tabs with consistent column counts)
    lines = text.strip().splitlines()[:20]
    if len(lines) >= 2:
        delim = _guess_delimiter(lines)
        if delim:
            counts = [line.count(delim) for line in lines]
            if counts[0] > 0 and len(set(counts)) <= 2:
                return "csv"
    return "bdd"


def _sniff_content(text: str) -> str | None:
    """Try to determine format from content alone (no extension)."""
    stripped = text.lstrip()
    if _SQL_DDL_RE.search(text[:2000]):
        return "sql"
    if _XML_START_RE.match(stripped):
        return "xml"
    if _GHERKIN_RE.search(text[:2000]):
        return "bdd"
    try:
        data = json.loads(text)
        if isinstance(data, dict) and {"openapi", "swagger", "paths", "info"} & {
            k.lower() for k in data
        }:
            return "openapi"
        return "csv"
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ── Utility ───────────────────────────────────────────────────


def _ext(filename: str) -> str:
    _, ext = os.path.splitext(filename.lower())
    return ext


def _as_text(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _derive_table_name(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    cleaned = re.sub(r"[^\w]+", "_", base).strip("_").lower()
    return cleaned or "imported_table"


def _guess_delimiter(lines: list[str]) -> str | None:
    for delim in (",", "\t", "|", ";"):
        if all(delim in line for line in lines[:5]):
            return delim
    return None
