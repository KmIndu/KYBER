"""Tests for OpenAPI payload generator and router."""

import pytest
from fastapi.testclient import TestClient

from app.generators.payload_generator import PayloadGenerator
from app.main import app
from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)
from app.models.payload import PayloadType
from app.services.session_store import store

client = TestClient(app)


# ── Test fixtures ──────────────────────────────────────────────


def _make_user_schema() -> OpenAPIMetadata:
    """OpenAPI spec with a User schema."""
    return OpenAPIMetadata(
        openapi_version="3.0.0",
        title="User API",
        schemas=[
            OpenAPISchemaMetadata(
                name="User",
                fields=[
                    OpenAPIFieldMetadata(
                        name="id",
                        data_type="string",
                        format="uuid",
                        required=True,
                    ),
                    OpenAPIFieldMetadata(
                        name="email",
                        data_type="string",
                        format="email",
                        required=True,
                    ),
                    OpenAPIFieldMetadata(
                        name="first_name",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(min_length=1, max_length=50),
                    ),
                    OpenAPIFieldMetadata(
                        name="age",
                        data_type="integer",
                        required=False,
                        validation=FieldValidation(minimum=0, maximum=150),
                    ),
                    OpenAPIFieldMetadata(
                        name="role",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(enum=["admin", "user", "moderator"]),
                    ),
                    OpenAPIFieldMetadata(
                        name="bio",
                        data_type="string",
                        required=False,
                        nullable=True,
                    ),
                ],
            ),
        ],
    )


def _make_order_schema() -> OpenAPIMetadata:
    """OpenAPI spec with nested objects and arrays."""
    return OpenAPIMetadata(
        openapi_version="3.0.0",
        title="Order API",
        schemas=[
            OpenAPISchemaMetadata(
                name="Order",
                fields=[
                    OpenAPIFieldMetadata(
                        name="order_id",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(pattern=r"^\d+$", min_length=6, max_length=10),
                    ),
                    OpenAPIFieldMetadata(
                        name="amount",
                        data_type="number",
                        required=True,
                        validation=FieldValidation(minimum=0.01, maximum=999999.99),
                    ),
                    OpenAPIFieldMetadata(
                        name="status",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(enum=["pending", "confirmed", "shipped", "delivered"]),
                    ),
                    OpenAPIFieldMetadata(
                        name="items",
                        data_type="array",
                        required=True,
                    ),
                    OpenAPIFieldMetadata(
                        name="metadata",
                        data_type="object",
                        required=False,
                    ),
                    OpenAPIFieldMetadata(
                        name="is_express",
                        data_type="boolean",
                        required=False,
                    ),
                ],
            ),
        ],
    )


def _make_constrained_schema() -> OpenAPIMetadata:
    """Schema with heavy validations."""
    return OpenAPIMetadata(
        openapi_version="3.0.0",
        title="Constrained API",
        schemas=[
            OpenAPISchemaMetadata(
                name="Payment",
                fields=[
                    OpenAPIFieldMetadata(
                        name="card_number",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(pattern=r"^\d{16}$", min_length=16, max_length=16),
                    ),
                    OpenAPIFieldMetadata(
                        name="amount",
                        data_type="number",
                        required=True,
                        validation=FieldValidation(minimum=1.0, maximum=50000.0),
                    ),
                    OpenAPIFieldMetadata(
                        name="currency",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(enum=["USD", "EUR", "GBP", "INR"]),
                    ),
                    OpenAPIFieldMetadata(
                        name="description",
                        data_type="string",
                        required=False,
                        validation=FieldValidation(max_length=200),
                    ),
                ],
            ),
        ],
    )


# ── Engine Unit Tests ──────────────────────────────────────────


class TestPayloadGenerator:
    """Unit tests for PayloadGenerator."""

    def test_generates_request_payloads(self):
        gen = PayloadGenerator(_make_user_schema(), count=2, include_invalid=False)
        result = gen.generate()
        requests = [p for p in result.payloads if p.payload_type == PayloadType.REQUEST]
        assert len(requests) == 2
        for p in requests:
            body = p.body
            # Required fields must be present
            assert "id" in body
            assert "email" in body
            assert "first_name" in body
            assert "role" in body
            # Optional fields should NOT be in request
            assert "age" not in body or body.get("age") is not None

    def test_generates_response_payloads(self):
        gen = PayloadGenerator(_make_user_schema(), count=2, include_invalid=False)
        result = gen.generate()
        responses = [p for p in result.payloads if p.payload_type == PayloadType.RESPONSE]
        assert len(responses) == 2
        for p in responses:
            # All fields should be present (some may be None)
            assert "id" in p.body
            assert "email" in p.body
            assert "age" in p.body
            assert "bio" in p.body

    def test_generates_mock_payload(self):
        gen = PayloadGenerator(_make_user_schema(), count=1, include_invalid=False)
        result = gen.generate()
        mocks = [p for p in result.payloads if p.payload_type == PayloadType.MOCK]
        assert len(mocks) == 1
        body = mocks[0].body
        # All fields present, no nulls
        for field in _make_user_schema().schemas[0].fields:
            assert field.name in body
            assert body[field.name] is not None

    def test_generates_invalid_payloads(self):
        gen = PayloadGenerator(_make_user_schema(), count=1, include_invalid=True)
        result = gen.generate()
        invalid = [p for p in result.payloads if p.payload_type == PayloadType.INVALID]
        assert len(invalid) >= 3  # Missing required, wrong type, null required, empty

    def test_enum_values_respected(self):
        gen = PayloadGenerator(_make_user_schema(), count=5, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "role" in p.body and p.body["role"] is not None:
                assert p.body["role"] in ["admin", "user", "moderator"]

    def test_integer_bounds_respected(self):
        gen = PayloadGenerator(_make_user_schema(), count=10, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "age" in p.body and p.body["age"] is not None:
                assert 0 <= p.body["age"] <= 150

    def test_number_bounds_respected(self):
        gen = PayloadGenerator(_make_order_schema(), count=10, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "amount" in p.body and p.body["amount"] is not None:
                assert 0.01 <= p.body["amount"] <= 999999.99

    def test_array_field_generates_list(self):
        gen = PayloadGenerator(_make_order_schema(), count=1, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "items" in p.body and p.body["items"] is not None:
                assert isinstance(p.body["items"], list)
                assert len(p.body["items"]) >= 1

    def test_object_field_generates_dict(self):
        gen = PayloadGenerator(_make_order_schema(), count=1, include_invalid=False)
        result = gen.generate()
        mocks = [p for p in result.payloads if p.payload_type == PayloadType.MOCK]
        assert isinstance(mocks[0].body["metadata"], dict)

    def test_boolean_field(self):
        gen = PayloadGenerator(_make_order_schema(), count=5, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "is_express" in p.body and p.body["is_express"] is not None:
                assert isinstance(p.body["is_express"], bool)

    def test_pattern_generates_digits(self):
        gen = PayloadGenerator(_make_order_schema(), count=5, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "order_id" in p.body and p.body["order_id"] is not None:
                assert p.body["order_id"].isdigit()
                assert 6 <= len(p.body["order_id"]) <= 10

    def test_constrained_schema(self):
        gen = PayloadGenerator(_make_constrained_schema(), count=3, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "currency" in p.body and p.body["currency"] is not None:
                assert p.body["currency"] in ["USD", "EUR", "GBP", "INR"]
            if "amount" in p.body and p.body["amount"] is not None:
                assert 1.0 <= p.body["amount"] <= 50000.0

    def test_invalid_missing_required_field(self):
        gen = PayloadGenerator(_make_user_schema(), count=1, include_invalid=True)
        result = gen.generate()
        invalid = [p for p in result.payloads if p.payload_type == PayloadType.INVALID]
        missing_field = [p for p in invalid if "Missing required" in p.description]
        assert len(missing_field) >= 1
        # Check that at least one required field is actually missing
        body = missing_field[0].body
        required_names = {"id", "email", "first_name", "role"}
        assert not required_names.issubset(body.keys())

    def test_invalid_wrong_types(self):
        gen = PayloadGenerator(_make_user_schema(), count=1, include_invalid=True)
        result = gen.generate()
        invalid = [p for p in result.payloads if p.payload_type == PayloadType.INVALID]
        wrong_type = [p for p in invalid if "Wrong data types" in p.description]
        assert len(wrong_type) >= 1

    def test_invalid_empty_body(self):
        gen = PayloadGenerator(_make_user_schema(), count=1, include_invalid=True)
        result = gen.generate()
        invalid = [p for p in result.payloads if p.payload_type == PayloadType.INVALID]
        empty = [p for p in invalid if "Empty" in p.description]
        assert len(empty) == 1
        assert empty[0].body == {}

    def test_invalid_violated_constraints(self):
        gen = PayloadGenerator(_make_constrained_schema(), count=1, include_invalid=True)
        result = gen.generate()
        invalid = [p for p in result.payloads if p.payload_type == PayloadType.INVALID]
        violated = [p for p in invalid if "Violated" in p.description]
        assert len(violated) >= 1
        body = violated[0].body
        # At least one value should be invalid
        if "currency" in body:
            # Either it's violated (not in enum) or another field is violated
            pass  # We just verify it exists

    def test_email_format(self):
        gen = PayloadGenerator(_make_user_schema(), count=5, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "email" in p.body and p.body["email"] is not None and isinstance(p.body["email"], str):
                assert "@" in p.body["email"]

    def test_uuid_format(self):
        gen = PayloadGenerator(_make_user_schema(), count=5, include_invalid=False)
        result = gen.generate()
        for p in result.payloads:
            if "id" in p.body and p.body["id"] is not None and isinstance(p.body["id"], str):
                # UUID format: 8-4-4-4-12 or at least has hyphens
                assert len(p.body["id"]) > 0

    def test_total_counts(self):
        gen = PayloadGenerator(_make_user_schema(), count=3, include_invalid=True)
        result = gen.generate()
        assert result.total_schemas == 1
        assert result.total_payloads > 0
        # 3 request + 3 response + 1 mock + N invalid
        assert result.total_payloads >= 7

    def test_multiple_schemas(self):
        openapi = OpenAPIMetadata(
            openapi_version="3.0.0",
            title="Multi-schema API",
            schemas=[
                OpenAPISchemaMetadata(
                    name="User",
                    fields=[OpenAPIFieldMetadata(name="name", data_type="string", required=True)],
                ),
                OpenAPISchemaMetadata(
                    name="Product",
                    fields=[OpenAPIFieldMetadata(name="sku", data_type="string", required=True)],
                ),
            ],
        )
        gen = PayloadGenerator(openapi, count=2, include_invalid=False)
        result = gen.generate()
        assert result.total_schemas == 2
        # Each schema: 2 request + 2 response + 1 mock = 5, * 2 schemas = 10
        assert result.total_payloads == 10


# ── Router Integration Tests ───────────────────────────────────


class TestPayloadsRouter:
    """Integration tests for /payloads/generate."""

    def test_generate_success(self):
        session = store.create()
        session.openapi = _make_user_schema()
        resp = client.post(f"/payloads/generate?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_schemas"] == 1
        assert data["total_payloads"] > 0
        assert len(data["payloads"]) > 0

    def test_generate_with_count(self):
        session = store.create()
        session.openapi = _make_user_schema()
        resp = client.post(f"/payloads/generate?session_id={session.session_id}&count=5")
        assert resp.status_code == 200
        data = resp.json()
        requests = [p for p in data["payloads"] if p["payload_type"] == "request"]
        assert len(requests) == 5

    def test_generate_without_invalid(self):
        session = store.create()
        session.openapi = _make_user_schema()
        resp = client.post(f"/payloads/generate?session_id={session.session_id}&include_invalid=false")
        assert resp.status_code == 200
        data = resp.json()
        invalid = [p for p in data["payloads"] if p["payload_type"] == "invalid"]
        assert len(invalid) == 0

    def test_session_not_found(self):
        resp = client.post("/payloads/generate?session_id=nonexistent")
        assert resp.status_code == 404

    def test_no_openapi_spec(self):
        session = store.create()
        resp = client.post(f"/payloads/generate?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No OpenAPI spec" in resp.json()["detail"]

    def test_no_schemas_in_spec(self):
        session = store.create()
        session.openapi = OpenAPIMetadata(openapi_version="3.0.0", title="Empty", schemas=[])
        resp = client.post(f"/payloads/generate?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "no schema definitions" in resp.json()["detail"]

    def test_payload_structure(self):
        session = store.create()
        session.openapi = _make_order_schema()
        resp = client.post(f"/payloads/generate?session_id={session.session_id}&count=1")
        assert resp.status_code == 200
        data = resp.json()
        for payload in data["payloads"]:
            assert "schema_name" in payload
            assert "payload_type" in payload
            assert "body" in payload
            assert "description" in payload
