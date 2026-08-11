"""JSON Schema parser — extracts table/column metadata from JSON Schema files.

Supports:
- Direct JSON Schema (type: object, properties: {...})
- Meta-schemas (nested properties.properties)
- Titled schemas (uses "title" as table name)
"""

from __future__ import annotations

import json
import logging
import os
import re

from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

logger = logging.getLogger(__name__)


class JSONSchemaParserError(Exception):
    """Raised when JSON Schema parsing fails."""


# ── Type mapping ──────────────────────────────────────────────

_TYPE_MAP = {
    "string": "VARCHAR(255)",
    "integer": "INTEGER",
    "number": "DECIMAL(18,4)",
    "boolean": "BOOLEAN",
    "array": "TEXT",
    "object": "TEXT",
}

_FORMAT_MAP = {
    "date-time": "TIMESTAMP",
    "date": "DATE",
    "time": "TIME",
    "email": "VARCHAR(255)",
    "uri": "VARCHAR(500)",
    "uuid": "UUID",
    "int32": "INTEGER",
    "int64": "BIGINT",
    "float": "FLOAT",
    "double": "DOUBLE PRECISION",
}


def parse_jsonschema(content: str, *, table_name: str = "imported_table") -> SchemaMetadata:
    """Parse a JSON Schema document into SchemaMetadata."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as e:
        raise JSONSchemaParserError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise JSONSchemaParserError("JSON Schema must be an object at root level")

    # Determine the table name from the schema title or filename
    title = data.get("title", "").strip()
    if title:
        tbl_name = re.sub(r"[^\w]+", "_", title).strip("_").lower() or table_name
    else:
        tbl_name = table_name

    # Find the properties to extract columns from
    properties, required = _find_properties(data)

    if not properties:
        raise JSONSchemaParserError(
            "No properties found in JSON Schema. "
            "Expected an object schema with 'properties' at root or nested level."
        )

    columns = _extract_columns(properties, required)

    if not columns:
        raise JSONSchemaParserError("No columns could be extracted from the schema properties.")

    table = TableMetadata(
        name=tbl_name,
        columns=columns,
        primary_keys=_guess_primary_keys(columns),
    )

    logger.info(
        "JSON Schema parser extracted %d columns for table '%s'",
        len(columns),
        tbl_name,
        extra={"stage": "parsing", "event": "jsonschema_parsed", "table": tbl_name},
    )

    return SchemaMetadata(tables=[table])


def _find_properties(data: dict) -> tuple[dict, set[str]]:
    """Find the most useful properties dict within the schema.

    Handles:
    - Standard: { type: object, properties: { col: {type: string} } }
    - Meta-schema: { properties: { properties: { properties: { col: ... } } } }
    """
    # Case 1: Direct schema with type=object and properties containing typed fields
    if data.get("type") == "object" and "properties" in data:
        props = data["properties"]
        required = set(data.get("required", []))

        # Check if a deeper nested level has more properties (meta-schema pattern)
        nested_props_obj = props.get("properties")
        if isinstance(nested_props_obj, dict):
            deeper = nested_props_obj.get("properties", {})
            if isinstance(deeper, dict) and len(deeper) > len(props):
                # Deeper level has more fields — it's a meta-schema, use the deeper level
                inner_required = set(nested_props_obj.get("required", []))
                return deeper, inner_required

        # Check if the properties contain actual field definitions (have "type" keys)
        has_typed_fields = any(
            isinstance(v, dict) and "type" in v and v.get("type") in ("string", "integer", "number", "boolean", "array")
            for v in props.values()
        )

        if has_typed_fields:
            return props, required

        # Meta-schema: look for properties.properties.properties
        if isinstance(nested_props_obj, dict):
            deeper = nested_props_obj.get("properties", {})
            if isinstance(deeper, dict):
                inner_required = set(nested_props_obj.get("required", []))
                return deeper, inner_required

    # Case 2: Has "properties" key directly (no explicit type: object)
    if "properties" in data and isinstance(data["properties"], dict):
        return data["properties"], set(data.get("required", []))

    # Case 3: definitions / $defs contain schemas
    defs = data.get("definitions") or data.get("$defs") or {}
    for def_name, def_obj in defs.items():
        if isinstance(def_obj, dict) and "properties" in def_obj:
            return def_obj["properties"], set(def_obj.get("required", []))

    return {}, set()


def _extract_columns(properties: dict, required: set[str]) -> list[ColumnMetadata]:
    """Convert JSON Schema properties to ColumnMetadata list."""
    columns = []

    for name, field_def in properties.items():
        if not isinstance(field_def, dict):
            continue

        # Skip meta-keys like $schema
        if name.startswith("$"):
            continue

        col = _field_to_column(name, field_def, name in required)
        if col:
            columns.append(col)

    return columns


def _field_to_column(name: str, field_def: dict, is_required: bool) -> ColumnMetadata | None:
    """Convert a single field definition to a ColumnMetadata."""
    # Get the type — it might be directly in the field, or nested in field.properties.type
    field_type = field_def.get("type")

    # For meta-schema entries: { type: "object", properties: { type: { type: "string" } } }
    if field_type == "object" and "properties" in field_def:
        inner = field_def["properties"]
        # If this looks like a meta-schema field desc, extract the described type
        if "type" in inner and isinstance(inner["type"], dict):
            # The 'type' field description — this means the actual type is unknown
            # Use format hint if available
            fmt = inner.get("format", {})
            if isinstance(fmt, dict):
                fmt_val = fmt.get("enum", [None])[0] if "enum" in fmt else None
            else:
                fmt_val = None
            data_type = _FORMAT_MAP.get(fmt_val, "VARCHAR(255)") if fmt_val else "VARCHAR(255)"
        else:
            data_type = "TEXT"
    elif isinstance(field_type, list):
        # Nullable type: ["string", "null"]
        non_null = [t for t in field_type if t != "null"]
        actual_type = non_null[0] if non_null else "string"
        fmt = field_def.get("format", "")
        data_type = _FORMAT_MAP.get(fmt, _TYPE_MAP.get(actual_type, "VARCHAR(255)"))
    elif field_type:
        fmt = field_def.get("format", "")
        data_type = _FORMAT_MAP.get(fmt, _TYPE_MAP.get(field_type, "VARCHAR(255)"))
    else:
        data_type = "VARCHAR(255)"

    nullable = not is_required

    # Clean up column name (decode SharePoint-style encoded chars)
    clean_name = _clean_column_name(name)

    # Infer better data type from column name when schema is a meta-schema
    # and all columns default to VARCHAR(255)
    if data_type == "VARCHAR(255)":
        data_type = _infer_type_from_name(clean_name)

    return ColumnMetadata(
        name=clean_name,
        data_type=data_type,
        nullable=nullable,
    )


def _clean_column_name(name: str) -> str:
    """Decode SharePoint-style hex-encoded column names like x005f_x0020."""
    # Replace _x00XX_ patterns with actual chars
    def hex_replace(m):
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return m.group(0)

    cleaned = re.sub(r"_x([0-9a-fA-F]{4})_", hex_replace, name)
    # Also handle x005f (underscore encoding)
    cleaned = re.sub(r"x005f_", "_", cleaned)
    # Remove double underscores
    cleaned = re.sub(r"__+", "_", cleaned).strip("_")
    return cleaned or name


# ── Name-based type inference ───────────────────────────────────

_NAME_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    # Booleans
    (re.compile(r"^Is[A-Z]|^Has[A-Z]|^Can[A-Z]|^Should[A-Z]|^Allow|^Enable|^Disable|^Restricted$|^Attachments$|^NoExecute$", re.I), "BOOLEAN"),
    # Dates / Timestamps
    (re.compile(r"^Created$|^Modified$|^Last_Modified$|^Last_x0020_Modified$|^Created_Date$|Created_x0020_Date|Modified_Date|LastModifiedDate|SMLastModifiedDate", re.I), "TIMESTAMP"),
    (re.compile(r"created[_\s]?(at|on|date|time)|updated[_\s]?(at|on|date|time)|modified[_\s]?(at|on|date|time)", re.I), "TIMESTAMP"),
    (re.compile(r"Date_|_Date$|When.*Date|Date.*When|Turn.*Green|_date$", re.I), "DATE"),
    # Integer columns
    (re.compile(r"^ID$|^id$", re.I), "INTEGER"),
    (re.compile(r"Count$|_Count$|ChildCount|FileCount", re.I), "INTEGER"),
    (re.compile(r"Size$|_Size$|StreamSize|TotalSize", re.I), "BIGINT"),
    (re.compile(r"^Order$|^sort_?order$|^sequence$|^owshiddenversion$", re.I), "INTEGER"),
    (re.compile(r"FSObjType|SortBehavior", re.I), "INTEGER"),
    # UUIDs
    (re.compile(r"UniqueId|ParentUniqueId|^GUID$|ScopeId|SyncClientId|InstanceID|WorkflowInstanceID", re.I), "UUID"),
]


def _infer_type_from_name(col_name: str) -> str:
    """Infer SQL data type from column name patterns.

    Called when the JSON Schema doesn't provide explicit type info
    (e.g., meta-schema where all columns are described as objects).
    """
    for pattern, sql_type in _NAME_TYPE_RULES:
        if pattern.search(col_name):
            return sql_type
    return "VARCHAR(255)"


def _guess_primary_keys(columns: list[ColumnMetadata]) -> list[str]:
    """Try to identify likely primary key columns."""
    pk_patterns = ("id", "guid", "uniqueid", "uid")
    for col in columns:
        if col.name.lower() in pk_patterns:
            return [col.name]
    # Check for columns ending in 'Id' or 'ID'
    for col in columns:
        if col.name.lower() == "id":
            return [col.name]
    return []
