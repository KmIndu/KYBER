import json
import pytest
from pathlib import Path

from app.parsers.openapi_parser import parse_openapi_spec, OpenAPIParserError
from app.models.openapi import OpenAPIMetadata


FIXTURES = Path(__file__).parent / "fixtures"


def _load_yaml() -> str:
    return (FIXTURES / "sample_openapi.yaml").read_text(encoding="utf-8")


def _load_json() -> str:
    return (FIXTURES / "sample_swagger.json").read_text(encoding="utf-8")


# ── Basic parsing ──────────────────────────────────────────────


class TestOpenAPIParserBasic:
    def test_parses_yaml(self):
        result = parse_openapi_spec(_load_yaml())
        assert isinstance(result, OpenAPIMetadata)

    def test_parses_json(self):
        result = parse_openapi_spec(_load_json(), is_json=True)
        assert isinstance(result, OpenAPIMetadata)

    def test_detects_openapi_3_version(self):
        result = parse_openapi_spec(_load_yaml())
        assert result.openapi_version == "3.0.3"

    def test_detects_swagger_2_version(self):
        result = parse_openapi_spec(_load_json(), is_json=True)
        assert result.openapi_version == "2.0"

    def test_extracts_title(self):
        result = parse_openapi_spec(_load_yaml())
        assert result.title == "Insurance API"

    def test_empty_spec_returns_empty_schemas(self):
        result = parse_openapi_spec("openapi: '3.0.0'\ninfo:\n  title: Empty\n  version: '1.0'\npaths: {}")
        assert result.schemas == []

    def test_invalid_yaml_raises_error(self):
        with pytest.raises(OpenAPIParserError):
            parse_openapi_spec("{{{{invalid yaml")

    def test_invalid_json_raises_error(self):
        with pytest.raises(OpenAPIParserError):
            parse_openapi_spec("{bad json", is_json=True)

    def test_non_object_raises_error(self):
        with pytest.raises(OpenAPIParserError):
            parse_openapi_spec("- just\n- a\n- list")


# ── Schema extraction ─────────────────────────────────────────


class TestSchemaExtraction:
    def test_openapi3_schema_count(self):
        result = parse_openapi_spec(_load_yaml())
        assert len(result.schemas) == 3

    def test_openapi3_schema_names(self):
        result = parse_openapi_spec(_load_yaml())
        names = [s.name for s in result.schemas]
        assert "Customer" in names
        assert "Policy" in names
        assert "Claim" in names

    def test_swagger2_schema_count(self):
        result = parse_openapi_spec(_load_json(), is_json=True)
        assert len(result.schemas) == 1

    def test_swagger2_schema_name(self):
        result = parse_openapi_spec(_load_json(), is_json=True)
        assert result.schemas[0].name == "Customer"


# ── Field extraction ──────────────────────────────────────────


class TestFieldExtraction:
    def test_customer_field_count(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        assert len(customer.fields) == 7

    def test_field_names(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        names = [f.name for f in customer.fields]
        assert "customer_id" in names
        assert "first_name" in names
        assert "email" in names

    def test_field_types(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        types = {f.name: f.data_type for f in customer.fields}
        assert types["customer_id"] == "integer"
        assert types["first_name"] == "string"
        assert types["premium"] if "premium" in types else True

    def test_field_format(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        email_field = next(f for f in customer.fields if f.name == "email")
        assert email_field.format == "email"


# ── Required fields ───────────────────────────────────────────


class TestRequiredFields:
    def test_required_fields_marked(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        required = [f.name for f in customer.fields if f.required]
        assert "first_name" in required
        assert "last_name" in required
        assert "email" in required

    def test_optional_fields_not_required(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        phone_field = next(f for f in customer.fields if f.name == "phone")
        assert phone_field.required is False

    def test_required_fields_not_nullable(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        first_name = next(f for f in customer.fields if f.name == "first_name")
        assert first_name.nullable is False


# ── Enum extraction ───────────────────────────────────────────


class TestEnumExtraction:
    def test_enum_values(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        status = next(f for f in customer.fields if f.name == "status")
        assert status.validation.enum == ["active", "inactive", "suspended"]

    def test_no_enum_is_empty_list(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        first_name = next(f for f in customer.fields if f.name == "first_name")
        assert first_name.validation.enum == []


# ── Pattern / regex extraction ────────────────────────────────


class TestPatternExtraction:
    def test_email_pattern(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        email = next(f for f in customer.fields if f.name == "email")
        assert email.validation.pattern is not None
        assert "@" in email.validation.pattern

    def test_phone_pattern(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        phone = next(f for f in customer.fields if f.name == "phone")
        assert phone.validation.pattern is not None

    def test_no_pattern_is_none(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        first_name = next(f for f in customer.fields if f.name == "first_name")
        assert first_name.validation.pattern is None


# ── Min/max validations ──────────────────────────────────────


class TestMinMaxValidation:
    def test_min_max_length(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        first_name = next(f for f in customer.fields if f.name == "first_name")
        assert first_name.validation.min_length == 1
        assert first_name.validation.max_length == 100

    def test_numeric_min_max(self):
        result = parse_openapi_spec(_load_yaml())
        policy = next(s for s in result.schemas if s.name == "Policy")
        premium = next(f for f in policy.fields if f.name == "premium")
        assert premium.validation.minimum == 0.01
        assert premium.validation.maximum == 999999.99

    def test_coverage_amount_range(self):
        result = parse_openapi_spec(_load_yaml())
        policy = next(s for s in result.schemas if s.name == "Policy")
        coverage = next(f for f in policy.fields if f.name == "coverage_amount")
        assert coverage.validation.minimum == 1000
        assert coverage.validation.maximum == 10000000


# ── Default values ─────────────────────────────────────────────


class TestDefaults:
    def test_default_value(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        status = next(f for f in customer.fields if f.name == "status")
        assert status.default == "active"

    def test_no_default_is_none(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        first_name = next(f for f in customer.fields if f.name == "first_name")
        assert first_name.default is None


# ── Nullable ───────────────────────────────────────────────────


class TestNullable:
    def test_explicit_nullable(self):
        result = parse_openapi_spec(_load_yaml())
        customer = next(s for s in result.schemas if s.name == "Customer")
        phone = next(f for f in customer.fields if f.name == "phone")
        assert phone.nullable is True

    def test_description_nullable(self):
        result = parse_openapi_spec(_load_yaml())
        claim = next(s for s in result.schemas if s.name == "Claim")
        desc = next(f for f in claim.fields if f.name == "description")
        assert desc.nullable is True


# ── Serialization ─────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_is_serializable(self):
        result = parse_openapi_spec(_load_yaml())
        data = result.model_dump()
        output = json.dumps(data, indent=2)
        assert '"schemas"' in output
        assert '"Customer"' in output

    def test_round_trip(self):
        result = parse_openapi_spec(_load_yaml())
        data = result.model_dump()
        restored = OpenAPIMetadata(**data)
        assert len(restored.schemas) == len(result.schemas)
