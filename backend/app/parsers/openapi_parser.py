"""OpenAPI / Swagger parser — extracts normalized field metadata from spec definitions.

Supports both OpenAPI 3.x (``components.schemas``) and Swagger 2.x
(``definitions``).  Accepts YAML or JSON input.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)

logger = logging.getLogger(__name__)


class OpenAPIParserError(Exception):
    """Raised when OpenAPI parsing fails."""


def parse_openapi_spec(content: str, *, is_json: bool = False) -> OpenAPIMetadata:
    """Parse an OpenAPI/Swagger spec (YAML or JSON) and return normalized metadata."""
    try:
        if is_json:
            spec = json.loads(content)
        else:
            spec = yaml.safe_load(content)
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise OpenAPIParserError(f"Failed to parse spec: {e}") from e

    if not isinstance(spec, dict):
        raise OpenAPIParserError("Spec must be a YAML/JSON object")

    openapi_version = _detect_version(spec)
    title = spec.get("info", {}).get("title", "")

    raw_schemas = _extract_schemas(spec, openapi_version)

    schemas: list[OpenAPISchemaMetadata] = []
    for schema_name, schema_obj in raw_schemas.items():
        if not isinstance(schema_obj, dict):
            continue
        parsed = _parse_schema_object(schema_name, schema_obj)
        schemas.append(parsed)

    if not schemas:
        logger.warning(
            "No schemas found in OpenAPI spec",
            extra={"stage": "parsing", "event": "openapi_no_schemas"},
        )
    else:
        logger.info(
            "OpenAPI parser extracted %d schemas",
            len(schemas),
            extra={"stage": "parsing", "event": "openapi_schemas_extracted"},
        )

    return OpenAPIMetadata(
        openapi_version=openapi_version,
        title=title,
        schemas=schemas,
    )


def _detect_version(spec: dict[str, Any]) -> str:
    if "openapi" in spec:
        return str(spec["openapi"])
    if "swagger" in spec:
        return str(spec["swagger"])
    return "unknown"


def _extract_schemas(spec: dict[str, Any], version: str) -> dict[str, Any]:
    """Extract schema definitions from different spec versions."""
    # OpenAPI 3.x: components.schemas
    if version.startswith("3"):
        return spec.get("components", {}).get("schemas", {})

    # Swagger 2.x: definitions
    if version.startswith("2"):
        return spec.get("definitions", {})

    # Try both as fallback
    schemas = spec.get("components", {}).get("schemas", {})
    if not schemas:
        schemas = spec.get("definitions", {})
    return schemas


def _parse_schema_object(
    name: str, schema: dict[str, Any]
) -> OpenAPISchemaMetadata:
    """Parse a single schema definition into normalized metadata."""
    required_fields = set(schema.get("required", []))
    properties = schema.get("properties", {})

    fields: list[OpenAPIFieldMetadata] = []
    for field_name, field_def in properties.items():
        if not isinstance(field_def, dict):
            continue
        fields.append(_parse_field(field_name, field_def, field_name in required_fields))

    return OpenAPISchemaMetadata(name=name, fields=fields)


def _parse_field(
    name: str, field_def: dict[str, Any], is_required: bool
) -> OpenAPIFieldMetadata:
    """Parse a single field/property definition."""
    data_type = field_def.get("type", "object")
    fmt = field_def.get("format")
    nullable = field_def.get("nullable", not is_required)
    default = str(field_def["default"]) if "default" in field_def else None

    validation = FieldValidation(
        minimum=field_def.get("minimum"),
        maximum=field_def.get("maximum"),
        min_length=field_def.get("minLength"),
        max_length=field_def.get("maxLength"),
        pattern=field_def.get("pattern"),
        enum=[str(e) for e in field_def.get("enum", [])],
    )

    return OpenAPIFieldMetadata(
        name=name,
        data_type=data_type,
        format=fmt,
        required=is_required,
        nullable=nullable,
        default=default,
        validation=validation,
    )
