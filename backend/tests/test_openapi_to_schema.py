"""Tests for OpenAPI → SchemaMetadata converter."""

from app.converters.openapi_to_schema import openapi_to_schema
from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)


def _make_field(name, data_type="string", fmt=None, required=False, **kw):
    return OpenAPIFieldMetadata(
        name=name, data_type=data_type, format=fmt, required=required,
        nullable=not required, validation=FieldValidation(**kw),
    )


def test_basic_conversion():
    meta = OpenAPIMetadata(
        openapi_version="3.0.0",
        title="Test",
        schemas=[
            OpenAPISchemaMetadata(
                name="User",
                fields=[
                    _make_field("id", "integer", required=True),
                    _make_field("name", "string"),
                    _make_field("email", "string", fmt="email", required=True),
                ],
            ),
        ],
    )
    schema = openapi_to_schema(meta)
    assert len(schema.tables) == 1
    t = schema.tables[0]
    assert t.name == "User"
    assert len(t.columns) == 3
    # id should be detected as PK
    assert t.primary_keys == ["id"]
    id_col = t.columns[0]
    assert id_col.data_type == "INTEGER"
    assert id_col.is_primary_key is True


def test_type_mapping():
    meta = OpenAPIMetadata(
        schemas=[
            OpenAPISchemaMetadata(
                name="Types",
                fields=[
                    _make_field("a", "integer"),
                    _make_field("b", "number"),
                    _make_field("c", "boolean"),
                    _make_field("d", "string", fmt="date-time"),
                    _make_field("e", "string", fmt="uuid"),
                ],
            ),
        ],
    )
    schema = openapi_to_schema(meta)
    cols = {c.name: c for c in schema.tables[0].columns}
    assert cols["a"].data_type == "INTEGER"
    assert cols["b"].data_type == "DECIMAL"
    assert cols["c"].data_type == "BOOLEAN"
    assert cols["d"].data_type == "DATETIME"
    assert cols["e"].data_type == "UUID"


def test_enum_check_constraint():
    meta = OpenAPIMetadata(
        schemas=[
            OpenAPISchemaMetadata(
                name="Status",
                fields=[
                    _make_field("status", "string", enum=["active", "inactive"]),
                ],
            ),
        ],
    )
    schema = openapi_to_schema(meta)
    col = schema.tables[0].columns[0]
    assert "IN" in col.check_constraint
    assert "'active'" in col.check_constraint


def test_empty_schemas():
    meta = OpenAPIMetadata(schemas=[])
    schema = openapi_to_schema(meta)
    assert schema.tables == []


def test_multiple_schemas():
    meta = OpenAPIMetadata(
        schemas=[
            OpenAPISchemaMetadata(name="A", fields=[_make_field("x", "string")]),
            OpenAPISchemaMetadata(name="B", fields=[_make_field("y", "integer")]),
        ],
    )
    schema = openapi_to_schema(meta)
    assert len(schema.tables) == 2
    assert {t.name for t in schema.tables} == {"A", "B"}
