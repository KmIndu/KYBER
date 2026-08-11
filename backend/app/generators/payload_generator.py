"""OpenAPI payload generator.

Generates realistic JSON payloads from parsed OpenAPI schema definitions:
- Valid request payloads (all required fields, constraints respected)
- Response payloads (full objects with all fields populated)
- Mock API bodies (complete objects for stubbing)
- Invalid payloads (violated constraints for negative testing)

Supports: nested objects, arrays, enums, regex patterns, min/max,
required fields, nullable fields, and format-aware generation.
"""

from __future__ import annotations

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from faker import Faker

from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)
from app.models.payload import (
    GeneratedPayload,
    PayloadGenerationResult,
    PayloadType,
)

fake = Faker()


class PayloadGenerator:
    """Generate API-ready JSON payloads from OpenAPI schema definitions."""

    def __init__(
        self,
        openapi: OpenAPIMetadata,
        count: int = 3,
        include_invalid: bool = True,
    ) -> None:
        self._openapi = openapi
        self._count = max(1, count)
        self._include_invalid = include_invalid
        self._schema_map: dict[str, OpenAPISchemaMetadata] = {
            s.name: s for s in openapi.schemas
        }

    def generate(self) -> PayloadGenerationResult:
        """Generate payloads for all schemas in the spec."""
        payloads: list[GeneratedPayload] = []

        for schema in self._openapi.schemas:
            # Generate valid request payloads (required fields only)
            for i in range(self._count):
                payloads.append(GeneratedPayload(
                    schema_name=schema.name,
                    payload_type=PayloadType.REQUEST,
                    body=self._gen_request_payload(schema),
                    description=f"Valid request payload #{i + 1} for {schema.name}",
                ))

            # Generate response payloads (all fields populated)
            for i in range(self._count):
                payloads.append(GeneratedPayload(
                    schema_name=schema.name,
                    payload_type=PayloadType.RESPONSE,
                    body=self._gen_response_payload(schema),
                    description=f"Response payload #{i + 1} for {schema.name}",
                ))

            # Generate mock API bodies (full objects)
            payloads.append(GeneratedPayload(
                schema_name=schema.name,
                payload_type=PayloadType.MOCK,
                body=self._gen_mock_payload(schema),
                description=f"Mock API body for {schema.name}",
            ))

            # Generate invalid payloads
            if self._include_invalid:
                payloads.extend(self._gen_invalid_payloads(schema))

        return PayloadGenerationResult(
            total_schemas=len(self._openapi.schemas),
            total_payloads=len(payloads),
            payloads=payloads,
        )

    # ── Valid request payload (required fields only) ───────────

    def _gen_request_payload(self, schema: OpenAPISchemaMetadata) -> dict[str, Any]:
        """Generate payload with only required fields populated."""
        body: dict[str, Any] = {}
        for field in schema.fields:
            if field.required:
                body[field.name] = self._gen_field_value(field)
        return body

    # ── Response payload (all fields) ──────────────────────────

    def _gen_response_payload(self, schema: OpenAPISchemaMetadata) -> dict[str, Any]:
        """Generate payload with all fields populated (simulating API response)."""
        body: dict[str, Any] = {}
        for field in schema.fields:
            if field.nullable and random.random() < 0.1:
                body[field.name] = None
            else:
                body[field.name] = self._gen_field_value(field)
        return body

    # ── Mock payload (all fields, no nulls) ────────────────────

    def _gen_mock_payload(self, schema: OpenAPISchemaMetadata) -> dict[str, Any]:
        """Generate a complete mock body (all fields, no nulls)."""
        body: dict[str, Any] = {}
        for field in schema.fields:
            body[field.name] = self._gen_field_value(field)
        return body

    # ── Invalid payloads ───────────────────────────────────────

    def _gen_invalid_payloads(self, schema: OpenAPISchemaMetadata) -> list[GeneratedPayload]:
        """Generate multiple invalid payloads with different violations."""
        payloads: list[GeneratedPayload] = []

        # 1. Missing required fields
        required_fields = [f for f in schema.fields if f.required]
        if required_fields:
            body = self._gen_response_payload(schema)
            # Remove a random required field
            field_to_remove = random.choice(required_fields)
            body.pop(field_to_remove.name, None)
            payloads.append(GeneratedPayload(
                schema_name=schema.name,
                payload_type=PayloadType.INVALID,
                body=body,
                description=f"Missing required field '{field_to_remove.name}'",
            ))

        # 2. Wrong types
        body = self._gen_response_payload(schema)
        for field in schema.fields[:3]:  # Corrupt up to 3 fields
            body[field.name] = self._gen_wrong_type(field)
        payloads.append(GeneratedPayload(
            schema_name=schema.name,
            payload_type=PayloadType.INVALID,
            body=body,
            description="Wrong data types for fields",
        ))

        # 3. Violated constraints (min/max/pattern/enum)
        constrained_fields = [
            f for f in schema.fields
            if f.validation.minimum is not None
            or f.validation.maximum is not None
            or f.validation.min_length is not None
            or f.validation.max_length is not None
            or f.validation.pattern is not None
            or f.validation.enum
        ]
        if constrained_fields:
            body = self._gen_response_payload(schema)
            for field in constrained_fields:
                body[field.name] = self._gen_violated_constraint(field)
            payloads.append(GeneratedPayload(
                schema_name=schema.name,
                payload_type=PayloadType.INVALID,
                body=body,
                description="Violated field constraints (min/max/pattern/enum)",
            ))

        # 4. Null required fields
        if required_fields:
            body = self._gen_response_payload(schema)
            for field in required_fields[:2]:
                body[field.name] = None
            payloads.append(GeneratedPayload(
                schema_name=schema.name,
                payload_type=PayloadType.INVALID,
                body=body,
                description="Null values for required fields",
            ))

        # 5. Empty body
        payloads.append(GeneratedPayload(
            schema_name=schema.name,
            payload_type=PayloadType.INVALID,
            body={},
            description="Empty request body",
        ))

        return payloads

    # ── Field value generation ─────────────────────────────────

    def _gen_field_value(self, field: OpenAPIFieldMetadata) -> Any:
        """Generate a valid value for a field based on type, format, and validation."""
        v = field.validation

        # Enum takes priority
        if v.enum:
            return random.choice(v.enum)

        # Regex pattern
        if v.pattern:
            return self._gen_from_pattern(v.pattern, v.min_length, v.max_length)

        # Type-based generation
        dtype = field.data_type.lower()

        if dtype == "string":
            return self._gen_string_value(field)
        elif dtype == "integer":
            return self._gen_integer_value(v)
        elif dtype == "number":
            return self._gen_number_value(v)
        elif dtype == "boolean":
            return random.choice([True, False])
        elif dtype == "array":
            return self._gen_array_value(field)
        elif dtype == "object":
            return self._gen_nested_object(field)
        else:
            return self._gen_string_value(field)

    def _gen_string_value(self, field: OpenAPIFieldMetadata) -> str:
        """Generate a string value respecting format and validation."""
        v = field.validation
        fmt = (field.format or "").lower()

        # Format-specific generation
        if fmt == "email":
            return fake.email()
        elif fmt == "date":
            return _random_date().isoformat()
        elif fmt == "date-time":
            return _random_datetime().isoformat()
        elif fmt == "uri" or fmt == "url":
            return fake.url()
        elif fmt == "uuid":
            return str(uuid.uuid4())
        elif fmt == "ipv4":
            return fake.ipv4()
        elif fmt == "ipv6":
            return fake.ipv6()
        elif fmt == "phone":
            return fake.phone_number()
        elif fmt == "password":
            return fake.password(length=12)
        elif fmt == "byte":
            import base64
            return base64.b64encode(fake.binary(length=16)).decode()
        elif fmt == "binary":
            return "0x" + "".join(random.choices("0123456789abcdef", k=16))

        # Name heuristic from field name
        name_lower = field.name.lower()
        if "email" in name_lower:
            return fake.email()
        elif "phone" in name_lower or "mobile" in name_lower:
            return fake.phone_number()
        elif "first" in name_lower and "name" in name_lower:
            return fake.first_name()
        elif "last" in name_lower and "name" in name_lower:
            return fake.last_name()
        elif "name" in name_lower:
            return fake.name()
        elif "address" in name_lower or "street" in name_lower:
            return fake.street_address()
        elif "city" in name_lower:
            return fake.city()
        elif "country" in name_lower:
            return fake.country()
        elif "url" in name_lower or "link" in name_lower:
            return fake.url()
        elif "description" in name_lower or "note" in name_lower:
            return fake.sentence()
        elif "id" in name_lower:
            return str(uuid.uuid4())[:8]

        # Respect length constraints
        min_len = v.min_length or 1
        max_len = v.max_length or 50
        length = random.randint(min_len, max(min_len, max_len))
        return fake.text(max_nb_chars=max(length, 5))[:length]

    def _gen_integer_value(self, v: FieldValidation) -> int:
        """Generate integer within min/max bounds."""
        lo = int(v.minimum) if v.minimum is not None else 1
        hi = int(v.maximum) if v.maximum is not None else 10000
        return random.randint(lo, max(lo, hi))

    def _gen_number_value(self, v: FieldValidation) -> float:
        """Generate float within min/max bounds."""
        lo = float(v.minimum) if v.minimum is not None else 0.01
        hi = float(v.maximum) if v.maximum is not None else 99999.99
        return round(random.uniform(lo, max(lo, hi)), 2)

    def _gen_array_value(self, field: OpenAPIFieldMetadata) -> list[Any]:
        """Generate an array with 1–5 items."""
        count = random.randint(1, 5)
        # Generate simple typed items based on field name heuristics
        name_lower = field.name.lower()
        if "id" in name_lower:
            return [str(uuid.uuid4())[:8] for _ in range(count)]
        elif "email" in name_lower:
            return [fake.email() for _ in range(count)]
        elif "tag" in name_lower or "label" in name_lower:
            return [fake.word() for _ in range(count)]
        elif "name" in name_lower:
            return [fake.name() for _ in range(count)]
        elif "number" in name_lower or "num" in name_lower:
            return [random.randint(1, 1000) for _ in range(count)]
        else:
            return [fake.word() for _ in range(count)]

    def _gen_nested_object(self, field: OpenAPIFieldMetadata) -> dict[str, Any]:
        """Generate a nested object.

        If the field name matches a known schema, use that schema.
        Otherwise generate a generic object.
        """
        # Check if there's a matching schema
        for schema_name, schema in self._schema_map.items():
            if schema_name.lower() == field.name.lower():
                return self._gen_response_payload(schema)

        # Generic nested object
        return {
            "id": str(uuid.uuid4())[:8],
            "type": fake.word(),
            "value": fake.sentence(nb_words=3),
        }

    def _gen_from_pattern(
        self,
        pattern: str,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> str:
        """Generate a string that attempts to match a regex pattern.

        Uses simple heuristic expansion for common patterns.
        """
        # Common patterns
        if pattern in (r"^\d+$", r"\d+"):
            length = random.randint(min_length or 1, max_length or 10)
            return "".join(random.choices(string.digits, k=length))
        elif pattern in (r"^[A-Z]+$", r"[A-Z]+"):
            length = random.randint(min_length or 1, max_length or 10)
            return "".join(random.choices(string.ascii_uppercase, k=length))
        elif "email" in pattern.lower() or "@" in pattern:
            return fake.email()
        elif pattern.startswith(r"^\+"):
            # Phone-like pattern
            return fake.phone_number()

        # Try to generate from pattern character classes
        return self._expand_regex(pattern, min_length or 5, max_length or 20)

    def _expand_regex(self, pattern: str, min_len: int, max_len: int) -> str:
        """Simple regex expander for common character classes."""
        result: list[str] = []
        length = random.randint(min_len, max_len)

        # Strip anchors
        clean = pattern.lstrip("^").rstrip("$")

        # Detect dominant character class
        if r"\d" in clean:
            charset = string.digits
        elif r"\w" in clean:
            charset = string.ascii_letters + string.digits
        elif "[A-Z]" in clean or "[A-Za-z]" in clean:
            charset = string.ascii_letters
        elif "[a-z]" in clean:
            charset = string.ascii_lowercase
        else:
            charset = string.ascii_letters + string.digits

        for _ in range(length):
            result.append(random.choice(charset))

        return "".join(result)

    # ── Invalid value generators ───────────────────────────────

    def _gen_wrong_type(self, field: OpenAPIFieldMetadata) -> Any:
        """Generate a value of the wrong type for the field."""
        dtype = field.data_type.lower()
        if dtype == "string":
            return random.randint(1, 9999)  # int instead of str
        elif dtype in ("integer", "number"):
            return fake.word()  # str instead of number
        elif dtype == "boolean":
            return "not_a_boolean"
        elif dtype == "array":
            return "not_an_array"
        elif dtype == "object":
            return "not_an_object"
        else:
            return None

    def _gen_violated_constraint(self, field: OpenAPIFieldMetadata) -> Any:
        """Generate a value that violates the field's constraints."""
        v = field.validation

        # Violate enum
        if v.enum:
            return "INVALID_ENUM_VALUE_" + fake.word()

        # Violate minimum
        if v.minimum is not None:
            return v.minimum - random.randint(1, 100)

        # Violate maximum
        if v.maximum is not None:
            return v.maximum + random.randint(1, 100)

        # Violate min_length
        if v.min_length is not None and v.min_length > 1:
            return "x"  # Too short

        # Violate max_length
        if v.max_length is not None:
            return "x" * (v.max_length + 10)  # Too long

        # Violate pattern
        if v.pattern:
            return "!!!INVALID!!!"

        return None


# ── Utility functions ──────────────────────────────────────────


def _random_date() -> date:
    start = date(2020, 1, 1)
    end = date(2026, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _random_datetime() -> datetime:
    start = datetime(2020, 1, 1)
    end = datetime(2026, 12, 31)
    delta = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, delta))
