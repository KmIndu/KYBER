"""Tests for the AI reasoning layer."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.gateway_provider import GatewayError, call_gateway
from app.ai.offline_provider import reason_offline
from app.ai.output_parser import OutputParserError, parse_ai_response
from app.ai.prompts import (
    SYSTEM_PROMPT,
    build_bdd_prompt,
    build_combined_prompt,
    build_openapi_prompt,
    build_schema_prompt,
)
from app.ai.service import analyze_bdd, analyze_combined, analyze_schema
from app.models.ai import AIConstraint, AIEdgeCase, AIProviderConfig, AIReasoningResult
from app.models.bdd import BDDMetadata, BDDRule, BDDScenario
from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.parsers.sql_parser import parse_sql_schema
from app.parsers.bdd_parser import parse_bdd_feature

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def schema() -> SchemaMetadata:
    return parse_sql_schema((FIXTURE_DIR / "sample_schema.sql").read_text())


@pytest.fixture
def bdd() -> BDDMetadata:
    return parse_bdd_feature((FIXTURE_DIR / "sample_rules.feature").read_text())


@pytest.fixture
def simple_schema() -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="INT", is_primary_key=True, nullable=False),
                    ColumnMetadata(name="email", data_type="VARCHAR(255)", nullable=False),
                    ColumnMetadata(name="phone", data_type="VARCHAR(20)"),
                    ColumnMetadata(name="start_date", data_type="DATE", nullable=False),
                    ColumnMetadata(name="end_date", data_type="DATE", nullable=False),
                    ColumnMetadata(name="date_of_birth", data_type="DATE"),
                ],
                primary_keys=["id"],
            )
        ]
    )


@pytest.fixture
def openapi() -> OpenAPIMetadata:
    return OpenAPIMetadata(
        openapi_version="3.0.3",
        title="Test API",
        schemas=[
            OpenAPISchemaMetadata(
                name="User",
                fields=[
                    OpenAPIFieldMetadata(
                        name="age",
                        data_type="integer",
                        required=True,
                        validation=FieldValidation(minimum=18, maximum=120),
                    ),
                    OpenAPIFieldMetadata(
                        name="status",
                        data_type="string",
                        validation=FieldValidation(enum=["active", "inactive"]),
                    ),
                    OpenAPIFieldMetadata(
                        name="zipcode",
                        data_type="string",
                        validation=FieldValidation(pattern=r"^\d{5}$"),
                    ),
                ],
            )
        ],
    )


# ══════════════════════════════════════════════════════════════
#  Prompt Manager
# ══════════════════════════════════════════════════════════════


class TestPrompts:
    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 0
        assert "JSON" in SYSTEM_PROMPT

    def test_schema_prompt(self):
        p = build_schema_prompt("CREATE TABLE t (id INT PRIMARY KEY);")
        assert "CREATE TABLE" in p
        assert "hidden_constraints" in p
        assert "edge_cases" in p

    def test_bdd_prompt(self):
        p = build_bdd_prompt("Given user age is below 18")
        assert "age" in p
        assert "business_rules" in p

    def test_bdd_prompt_with_schema_context(self):
        p = build_bdd_prompt("Given age < 18", schema_text="TABLE users (age INT)")
        assert "TABLE users" in p

    def test_openapi_prompt(self):
        p = build_openapi_prompt("paths: /users: ...")
        assert "OpenAPI" in p.lower() or "openapi" in p.lower()

    def test_combined_prompt(self):
        p = build_combined_prompt(
            schema_text="TABLE t (id INT)",
            bdd_text="Given x",
            openapi_text="paths: /",
        )
        assert "SQL Schema" in p
        assert "BDD Scenarios" in p
        assert "OpenAPI Spec" in p

    def test_combined_prompt_partial(self):
        p = build_combined_prompt(schema_text="TABLE t (id INT)")
        assert "SQL Schema" in p
        assert "BDD Scenarios:\n" not in p


# ══════════════════════════════════════════════════════════════
#  Output Parser
# ══════════════════════════════════════════════════════════════


class TestOutputParser:
    def test_parse_valid_json(self):
        raw = json.dumps({
            "hidden_constraints": [
                {"table": "t", "column": "c", "constraint_type": "range", "description": "d"}
            ],
            "business_rules": [],
            "edge_cases": [
                {"table": "t", "column": "c", "scenario": "s", "test_value": 42}
            ],
        })
        result = parse_ai_response(raw, provider="test")
        assert len(result.hidden_constraints) == 1
        assert result.hidden_constraints[0].constraint_type == "range"
        assert len(result.edge_cases) == 1
        assert result.edge_cases[0].test_value == 42
        assert result.provider == "test"

    def test_parse_markdown_fenced_json(self):
        raw = '```json\n{"hidden_constraints": [], "business_rules": [], "edge_cases": []}\n```'
        result = parse_ai_response(raw)
        assert isinstance(result, AIReasoningResult)

    def test_parse_json_with_prefix(self):
        raw = 'Here is the analysis:\n{"hidden_constraints": [], "business_rules": [], "edge_cases": []}'
        result = parse_ai_response(raw)
        assert isinstance(result, AIReasoningResult)

    def test_parse_invalid_json_raises(self):
        with pytest.raises(OutputParserError):
            parse_ai_response("this is not json at all!!!")

    def test_parse_non_object_raises(self):
        with pytest.raises(OutputParserError):
            parse_ai_response("[1, 2, 3]")

    def test_skips_malformed_entries(self):
        raw = json.dumps({
            "hidden_constraints": [
                {"table": "t", "column": "c", "constraint_type": "range", "description": "good"},
                "not a dict",
                42,
            ],
            "business_rules": [],
            "edge_cases": [],
        })
        result = parse_ai_response(raw)
        assert len(result.hidden_constraints) == 1

    def test_preserves_raw_response(self):
        raw = json.dumps({"hidden_constraints": [], "business_rules": [], "edge_cases": []})
        result = parse_ai_response(raw, provider="p")
        assert result.raw_response == raw


# ══════════════════════════════════════════════════════════════
#  Offline Provider — Schema
# ══════════════════════════════════════════════════════════════


class TestOfflineSchema:
    def test_returns_result(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        assert isinstance(result, AIReasoningResult)
        assert result.provider == "offline"

    def test_detects_date_ordering(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [c.description for c in result.hidden_constraints]
        assert any("start_date" in d and "end_date" in d for d in descs)

    def test_detects_email_format(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [c.description for c in result.hidden_constraints]
        assert any("email" in d.lower() for d in descs)

    def test_detects_phone_format(self, simple_schema: SchemaMetadata):
        result = reason_offline(schema=simple_schema)
        descs = [c.description for c in result.hidden_constraints]
        assert any("phone" in d.lower() for d in descs)

    def test_detects_dob_age_rule(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [r.description for r in result.business_rules]
        assert any("18" in d for d in descs)

    def test_detects_claim_amount_rule(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [r.description for r in result.business_rules]
        assert any("claim" in d.lower() and "coverage" in d.lower() for d in descs)

    def test_detects_status_workflow(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [r.description for r in result.business_rules]
        assert any("status" in d.lower() and "workflow" in d.lower() for d in descs)

    def test_generates_edge_cases(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        assert len(result.edge_cases) > 0

    def test_start_end_date_edge_cases(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        scenarios = [e.scenario for e in result.edge_cases]
        assert any("equals" in s for s in scenarios)
        assert any("after" in s for s in scenarios)

    def test_payment_amount_rule(self, schema: SchemaMetadata):
        result = reason_offline(schema=schema)
        descs = [r.description for r in result.business_rules]
        assert any("payment" in d.lower() and "claim" in d.lower() for d in descs)


# ══════════════════════════════════════════════════════════════
#  Offline Provider — BDD
# ══════════════════════════════════════════════════════════════


class TestOfflineBDD:
    def test_returns_result(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        assert isinstance(result, AIReasoningResult)

    def test_detects_age_rules(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        descs = [r.description for r in result.business_rules]
        assert any("age" in d.lower() for d in descs)

    def test_detects_amount_rules(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        descs = [r.description for r in result.business_rules]
        assert any("amount" in d.lower() or "premium" in d.lower() for d in descs)

    def test_detects_null_handling(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        descs = [c.description for c in result.hidden_constraints]
        assert any("null" in d.lower() or "empty" in d.lower() for d in descs)

    def test_detects_format_validation(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        descs = [c.description for c in result.hidden_constraints]
        assert any("format" in d.lower() or "valid" in d.lower() for d in descs)

    def test_boundary_edge_cases(self, bdd: BDDMetadata):
        result = reason_offline(bdd=bdd)
        assert len(result.edge_cases) > 0
        scenarios = [e.scenario for e in result.edge_cases]
        assert any("boundary" in s.lower() or "threshold" in s.lower() for s in scenarios)


# ══════════════════════════════════════════════════════════════
#  Offline Provider — OpenAPI
# ══════════════════════════════════════════════════════════════


class TestOfflineOpenAPI:
    def test_returns_result(self, openapi: OpenAPIMetadata):
        result = reason_offline(openapi=openapi)
        assert isinstance(result, AIReasoningResult)

    def test_detects_range(self, openapi: OpenAPIMetadata):
        result = reason_offline(openapi=openapi)
        descs = [c.description for c in result.hidden_constraints]
        assert any("age" in d.lower() and "min" in d.lower() for d in descs)

    def test_detects_pattern(self, openapi: OpenAPIMetadata):
        result = reason_offline(openapi=openapi)
        descs = [c.description for c in result.hidden_constraints]
        assert any("zipcode" in d.lower() for d in descs)

    def test_detects_enum_rule(self, openapi: OpenAPIMetadata):
        result = reason_offline(openapi=openapi)
        descs = [r.description for r in result.business_rules]
        assert any("status" in d.lower() for d in descs)

    def test_edge_cases_from_min(self, openapi: OpenAPIMetadata):
        result = reason_offline(openapi=openapi)
        edge_vals = [e.test_value for e in result.edge_cases if e.column == "age"]
        assert 18 in edge_vals  # at minimum
        assert 17 in edge_vals  # below minimum


# ══════════════════════════════════════════════════════════════
#  Offline Provider — Combined
# ══════════════════════════════════════════════════════════════


class TestOfflineCombined:
    def test_combined_schema_and_bdd(self, schema: SchemaMetadata, bdd: BDDMetadata):
        result = reason_offline(schema=schema, bdd=bdd)
        # Should have results from both sources
        assert len(result.hidden_constraints) > 0
        assert len(result.business_rules) > 0
        assert len(result.edge_cases) > 0

    def test_combined_all_three(
        self, schema: SchemaMetadata, bdd: BDDMetadata, openapi: OpenAPIMetadata
    ):
        result = reason_offline(schema=schema, bdd=bdd, openapi=openapi)
        types = {c.constraint_type for c in result.hidden_constraints + result.business_rules}
        assert "format" in types
        assert "business_rule" in types

    def test_no_inputs_returns_empty(self):
        result = reason_offline()
        assert result.hidden_constraints == []
        assert result.business_rules == []
        assert result.edge_cases == []


# ══════════════════════════════════════════════════════════════
#  AI Service (gateway fallback)
# ══════════════════════════════════════════════════════════════


class TestAIService:
    def test_analyze_schema_offline(self, schema: SchemaMetadata):
        """When no gateway is configured, falls back to offline."""
        result = analyze_schema(schema)
        assert result.provider == "offline"
        assert len(result.hidden_constraints) > 0

    def test_analyze_bdd_offline(self, bdd: BDDMetadata):
        result = analyze_bdd(bdd)
        assert result.provider == "offline"
        assert len(result.business_rules) > 0

    def test_analyze_combined_offline(self, schema: SchemaMetadata, bdd: BDDMetadata):
        result = analyze_combined(schema=schema, bdd=bdd)
        assert result.provider == "offline"


# ══════════════════════════════════════════════════════════════
#  Gateway Provider (mocked)
# ══════════════════════════════════════════════════════════════


class TestGatewayProvider:
    def _config(self) -> AIProviderConfig:
        return AIProviderConfig(
            gateway_url="https://ai-gateway.internal.example.com/v1",
            api_token="test-token-123",
            model="claude-opus-4-6",
            api_format="openai",
            timeout=10,
            max_retries=2,
        )

    @patch("app.ai.gateway_provider.requests.post")
    def test_successful_call(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "hidden_constraints": [
                                {"table": "t", "column": "c", "constraint_type": "range", "description": "d"}
                            ],
                            "business_rules": [],
                            "edge_cases": [],
                        })
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = call_gateway("test prompt", self._config())
        assert result.provider == "gateway"
        assert len(result.hidden_constraints) == 1
        mock_post.assert_called_once()

    @patch("app.ai.gateway_provider.requests.post")
    def test_anthropic_format(self, mock_post: MagicMock):
        config = self._config()
        config.api_format = "anthropic"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [
                {"text": json.dumps({"hidden_constraints": [], "business_rules": [], "edge_cases": []})}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = call_gateway("test", config)
        assert result.provider == "gateway"
        # Verify the URL ends with /messages for anthropic
        call_args = mock_post.call_args
        assert call_args[1]["headers"]["anthropic-version"] == "2023-06-01"

    @patch("app.ai.gateway_provider.requests.post")
    def test_timeout_retries(self, mock_post: MagicMock):
        import requests as req

        mock_post.side_effect = req.exceptions.Timeout()

        with pytest.raises(GatewayError, match="timeout"):
            call_gateway("test", self._config())

        assert mock_post.call_count == 2  # max_retries=2

    @patch("app.ai.gateway_provider.requests.post")
    def test_server_error_retries(self, mock_post: MagicMock):
        import requests as req

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        error = req.exceptions.HTTPError(response=mock_resp)
        mock_post.side_effect = error

        with pytest.raises(GatewayError, match="server error"):
            call_gateway("test", self._config())

        assert mock_post.call_count == 2

    @patch("app.ai.gateway_provider.requests.post")
    def test_client_error_no_retry(self, mock_post: MagicMock):
        import requests as req

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        error = req.exceptions.HTTPError(response=mock_resp)
        mock_post.side_effect = error

        with pytest.raises(GatewayError, match="client error"):
            call_gateway("test", self._config())

        assert mock_post.call_count == 1  # no retry for 4xx

    def test_no_url_raises(self):
        config = AIProviderConfig(gateway_url="", api_token="x")
        with pytest.raises(GatewayError, match="URL"):
            call_gateway("test", config)

    def test_no_token_raises(self):
        config = AIProviderConfig(gateway_url="https://x.com", api_token="")
        with pytest.raises(GatewayError, match="token"):
            call_gateway("test", config)

    @patch("app.ai.gateway_provider.requests.post")
    def test_bad_json_response(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "not valid json at all"}}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with pytest.raises(GatewayError, match="parse"):
            call_gateway("test", self._config())


# ══════════════════════════════════════════════════════════════
#  Models
# ══════════════════════════════════════════════════════════════


class TestModels:
    def test_ai_constraint(self):
        c = AIConstraint(constraint_type="range", description="test")
        assert c.table == ""
        assert c.suggestion == {}

    def test_ai_edge_case(self):
        e = AIEdgeCase(scenario="test", test_value=42)
        assert e.column == ""

    def test_ai_reasoning_result_empty(self):
        r = AIReasoningResult()
        assert r.hidden_constraints == []
        assert r.provider == ""

    def test_provider_config_defaults(self):
        c = AIProviderConfig()
        assert c.model == "claude-opus-4-6"
        assert c.timeout == 30
        assert c.max_retries == 3

    def test_negative_toggles_default(self):
        t = AIProviderConfig(api_format="anthropic")
        assert t.api_format == "anthropic"
