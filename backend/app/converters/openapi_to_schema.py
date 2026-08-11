"""Convert OpenAPIMetadata → SchemaMetadata for generator pipeline compatibility.

Maps each OpenAPI schema definition to a ``TableMetadata`` with inferred
SQL types, CHECK constraints from enums/ranges, and PK auto-detection.
"""

from __future__ import annotations

from app.models.openapi import OpenAPIMetadata, OpenAPIFieldMetadata
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

# OpenAPI type → SQL type mapping
_TYPE_MAP: dict[str, str] = {
    "string": "VARCHAR",
    "integer": "INTEGER",
    "number": "DECIMAL",
    "boolean": "BOOLEAN",
    "array": "TEXT",
    "object": "TEXT",
}

# format hints → more specific SQL types
_FORMAT_MAP: dict[str, str] = {
    "int32": "INTEGER",
    "int64": "BIGINT",
    "float": "FLOAT",
    "double": "DOUBLE",
    "date": "DATE",
    "date-time": "DATETIME",
    "uuid": "UUID",
    "email": "VARCHAR",
    "uri": "VARCHAR",
    "url": "VARCHAR",
}


def openapi_to_schema(openapi: OpenAPIMetadata) -> SchemaMetadata:
    """Convert every OpenAPI schema definition into a TableMetadata."""
    tables: list[TableMetadata] = []

    for api_schema in openapi.schemas:
        columns: list[ColumnMetadata] = []

        for f in api_schema.fields:
            col = _field_to_column(f)
            columns.append(col)

        table = TableMetadata(
            name=api_schema.name,
            columns=columns,
            primary_keys=[],
            foreign_keys=[],
            unique_constraints=[],
            check_constraints=[],
        )

        # If an "id" column exists, treat it as the PK
        for col in columns:
            if col.name.lower() == "id":
                col.is_primary_key = True
                table.primary_keys = [col.name]
                break

        tables.append(table)

    return SchemaMetadata(tables=tables)


def _field_to_column(field: OpenAPIFieldMetadata) -> ColumnMetadata:
    """Map a single OpenAPI field to a ColumnMetadata."""
    base = field.data_type.lower()

    # Use format-specific type when available
    if field.format and field.format.lower() in _FORMAT_MAP:
        sql_type = _FORMAT_MAP[field.format.lower()]
    else:
        sql_type = _TYPE_MAP.get(base, "VARCHAR")

    # Build check_constraint from validation rules
    checks: list[str] = []
    v = field.validation
    if v.enum:
        vals = ", ".join(f"'{e}'" for e in v.enum)
        checks.append(f"{field.name} IN ({vals})")
    if v.minimum is not None:
        checks.append(f"{field.name} >= {v.minimum}")
    if v.maximum is not None:
        checks.append(f"{field.name} <= {v.maximum}")
    if v.pattern:
        checks.append(f"PATTERN:{v.pattern}")

    check_constraint = " AND ".join(checks) if checks else None

    return ColumnMetadata(
        name=field.name,
        data_type=sql_type,
        nullable=field.nullable,
        default=field.default,
        is_primary_key=False,
        is_unique=False,
        check_constraint=check_constraint,
    )
