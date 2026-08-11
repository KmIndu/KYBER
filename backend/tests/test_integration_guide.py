"""Tests for the AI integration assistant / guide module.

Covers:
- Offline guide generation (deterministic)
- Guide model validation
- Integration guide router endpoint
- Output parser for guide responses
- Gateway fallback to offline
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.ai.output_parser import parse_guide_response, OutputParserError
from app.ai.service import generate_integration_guide
from app.main import app
from app.models.integration import (
    GuideStep,
    IntegrationGuide,
    IntegrationGuideSection,
)
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.session_store import store

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def schema() -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="name", data_type="VARCHAR", nullable=False),
                    ColumnMetadata(name="email", data_type="VARCHAR", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="customer_id", data_type="INTEGER", nullable=False),
                    ColumnMetadata(name="total", data_type="DECIMAL", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[
                    ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
                ],
            ),
        ]
    )


@pytest.fixture
def data() -> dict:
    return {
        "customers": [
            {"id": 1, "name": "Alice", "email": "alice@test.com"},
            {"id": 2, "name": "Bob", "email": "bob@test.com"},
        ],
        "orders": [
            {"id": 1, "customer_id": 1, "total": 99.99},
            {"id": 2, "customer_id": 2, "total": 149.50},
        ],
    }


@pytest.fixture
def generation_order() -> list[str]:
    return ["customers", "orders"]


@pytest.fixture
def session_with_data(schema, data, generation_order):
    """Create a session with schema + generated data."""
    session = store.create()
    session.schema = schema
    session.data = data
    session.generation_order = generation_order
    yield session
    store.delete(session.session_id)


# ── Model tests ──────────────────────────────────────────────


class TestGuideModels:
    def test_guide_step_creation(self):
        step = GuideStep(
            step_number=1,
            title="Create table",
            description="Run the DDL",
            code_snippet="CREATE TABLE t (id INT);",
            language="sql",
        )
        assert step.step_number == 1
        assert step.language == "sql"
        assert "CREATE TABLE" in step.code_snippet

    def test_guide_section_creation(self):
        section = IntegrationGuideSection(
            scenario="Import CSV into PostgreSQL",
            summary="Load CSV files using psql \\copy",
            prerequisites=["PostgreSQL installed"],
            steps=[
                GuideStep(step_number=1, title="Run DDL", description="Create tables"),
            ],
            tips=["Use transactions"],
        )
        assert section.scenario == "Import CSV into PostgreSQL"
        assert len(section.steps) == 1
        assert len(section.tips) == 1

    def test_integration_guide_creation(self):
        guide = IntegrationGuide(
            session_id="test123",
            overview="Test overview",
            sections=[],
            provider="offline",
        )
        assert guide.session_id == "test123"
        assert guide.provider == "offline"
        assert guide.generated_at is not None

    def test_guide_serialization(self):
        guide = IntegrationGuide(
            session_id="abc",
            overview="Overview text",
            sections=[
                IntegrationGuideSection(
                    scenario="Test",
                    summary="Summary",
                    steps=[
                        GuideStep(
                            step_number=1,
                            title="Step 1",
                            description="Do thing",
                            code_snippet="echo hello",
                            language="bash",
                        )
                    ],
                )
            ],
            provider="offline",
        )
        d = guide.model_dump()
        assert d["session_id"] == "abc"
        assert len(d["sections"]) == 1
        assert d["sections"][0]["steps"][0]["language"] == "bash"


# ── Offline guide generation tests ───────────────────────────


class TestOfflineGuideGeneration:
    def test_basic_guide_generation(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="test-session",
            schema=schema,
            data=data,
            generation_order=generation_order,
            has_integration_bundle=False,
        )
        assert isinstance(guide, IntegrationGuide)
        assert guide.session_id == "test-session"
        assert guide.provider == "offline"
        assert len(guide.sections) >= 4  # CSV→PG, CSV→MySQL, SQL, API, pytest

    def test_guide_overview_includes_table_info(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        assert "customers" in guide.overview
        assert "orders" in guide.overview
        assert "4 rows" in guide.overview

    def test_guide_has_postgres_section(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        pg_sections = [s for s in guide.sections if "PostgreSQL" in s.scenario]
        assert len(pg_sections) == 1
        pg = pg_sections[0]
        assert len(pg.steps) >= 2
        assert any("\\copy" in s.code_snippet for s in pg.steps)
        assert len(pg.prerequisites) > 0

    def test_guide_has_mysql_section(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        mysql_sections = [s for s in guide.sections if "MySQL" in s.scenario]
        assert len(mysql_sections) == 1
        mysql = mysql_sections[0]
        assert any("LOAD DATA" in s.code_snippet for s in mysql.steps)

    def test_guide_has_sql_insert_section(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        sql_sections = [s for s in guide.sections if "SQL INSERT" in s.scenario]
        assert len(sql_sections) == 1

    def test_guide_has_api_payload_section(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        api_sections = [s for s in guide.sections if "API" in s.scenario]
        assert len(api_sections) == 1
        api = api_sections[0]
        assert any(s.language == "python" for s in api.steps)
        assert any(s.language == "bash" for s in api.steps)

    def test_guide_has_pytest_section(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        pytest_sections = [s for s in guide.sections if "Python" in s.scenario or "pytest" in s.scenario.lower()]
        assert len(pytest_sections) == 1

    def test_guide_with_integration_bundle_adds_postman(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
            has_integration_bundle=True,
        )
        postman_sections = [s for s in guide.sections if "Postman" in s.scenario]
        assert len(postman_sections) == 1
        assert any("newman" in s.code_snippet.lower() for s in postman_sections[0].steps)

    def test_guide_without_integration_bundle_no_postman(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
            has_integration_bundle=False,
        )
        postman_sections = [s for s in guide.sections if "Postman" in s.scenario]
        assert len(postman_sections) == 0

    def test_guide_respects_generation_order(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        pg = [s for s in guide.sections if "PostgreSQL" in s.scenario][0]
        # The import step should list customers before orders
        import_step = [s for s in pg.steps if "\\copy" in s.code_snippet][0]
        cust_idx = import_step.code_snippet.index("customers")
        ord_idx = import_step.code_snippet.index("orders")
        assert cust_idx < ord_idx

    def test_code_snippets_are_nonempty(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
            has_integration_bundle=True,
        )
        for section in guide.sections:
            for step in section.steps:
                if step.code_snippet:
                    assert len(step.code_snippet) > 5

    def test_all_steps_have_numbers(self, schema, data, generation_order):
        guide = generate_integration_guide(
            session_id="x",
            schema=schema,
            data=data,
            generation_order=generation_order,
            has_integration_bundle=True,
        )
        for section in guide.sections:
            for i, step in enumerate(section.steps):
                assert step.step_number == i + 1


# ── Output parser tests ──────────────────────────────────────


class TestGuideOutputParser:
    def test_parse_valid_guide_response(self):
        raw_json = json.dumps({
            "overview": "A test dataset with 2 tables.",
            "sections": [
                {
                    "scenario": "Import CSV into PostgreSQL",
                    "summary": "Use psql \\copy",
                    "prerequisites": ["PostgreSQL"],
                    "steps": [
                        {
                            "step_number": 1,
                            "title": "Create tables",
                            "description": "Run DDL",
                            "code_snippet": "psql -f schema.sql",
                            "language": "bash",
                        }
                    ],
                    "tips": ["Use transactions"],
                }
            ],
        })
        guide = parse_guide_response(raw_json, "sess123", "gateway")
        assert guide.session_id == "sess123"
        assert guide.provider == "gateway"
        assert len(guide.sections) == 1
        assert guide.sections[0].scenario == "Import CSV into PostgreSQL"
        assert guide.sections[0].steps[0].language == "bash"

    def test_parse_guide_with_code_fences(self):
        raw = '```json\n{"overview":"test","sections":[]}\n```'
        guide = parse_guide_response(raw, "s1")
        assert guide.overview == "test"
        assert len(guide.sections) == 0

    def test_parse_guide_with_extra_text(self):
        raw = 'Here is the guide:\n{"overview":"ok","sections":[{"scenario":"X","summary":"Y","steps":[]}]}'
        guide = parse_guide_response(raw, "s2")
        assert guide.overview == "ok"
        assert len(guide.sections) == 1

    def test_parse_guide_invalid_json_raises(self):
        with pytest.raises(OutputParserError):
            parse_guide_response("not json at all {{{", "s3")

    def test_parse_guide_skips_malformed_steps(self):
        raw = json.dumps({
            "overview": "test",
            "sections": [
                {
                    "scenario": "S1",
                    "summary": "Sum",
                    "steps": [
                        {"step_number": 1, "title": "Good", "description": "OK", "code_snippet": "x"},
                        "not a dict",
                        42,
                    ],
                }
            ],
        })
        guide = parse_guide_response(raw, "s4")
        assert len(guide.sections[0].steps) == 1

    def test_parse_guide_empty_sections(self):
        raw = json.dumps({"overview": "empty", "sections": []})
        guide = parse_guide_response(raw, "s5")
        assert len(guide.sections) == 0

    def test_parse_guide_missing_optional_fields(self):
        raw = json.dumps({
            "overview": "minimal",
            "sections": [
                {
                    "scenario": "Test",
                    "summary": "Min",
                    "steps": [
                        {"step_number": 1, "title": "S", "description": "D"},
                    ],
                }
            ],
        })
        guide = parse_guide_response(raw, "s6")
        step = guide.sections[0].steps[0]
        assert step.code_snippet == ""
        assert step.language == ""


# ── Router endpoint tests ────────────────────────────────────


class TestGuideRouter:
    def test_guide_endpoint_success(self, session_with_data):
        sid = session_with_data.session_id
        resp = client.post(f"/integration/guide?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert body["provider"] == "offline"
        assert len(body["sections"]) >= 4
        assert body["overview"] != ""

    def test_guide_endpoint_no_session(self):
        resp = client.post("/integration/guide?session_id=nonexistent")
        assert resp.status_code == 404

    def test_guide_endpoint_no_data(self):
        session = store.create()
        try:
            resp = client.post(f"/integration/guide?session_id={session.session_id}")
            assert resp.status_code == 400
        finally:
            store.delete(session.session_id)

    def test_guide_endpoint_no_schema(self):
        session = store.create()
        session.data = {"t": [{"a": 1}]}
        try:
            resp = client.post(f"/integration/guide?session_id={session.session_id}")
            assert resp.status_code == 400
        finally:
            store.delete(session.session_id)

    def test_guide_sections_have_steps(self, session_with_data):
        sid = session_with_data.session_id
        resp = client.post(f"/integration/guide?session_id={sid}")
        body = resp.json()
        for section in body["sections"]:
            assert len(section["steps"]) >= 1
            for step in section["steps"]:
                assert "title" in step
                assert "description" in step
                assert "step_number" in step

    def test_guide_with_integration_bundle(self, session_with_data):
        from app.models.integration import IntegrationBundle
        session_with_data.integration_bundle = IntegrationBundle(
            session_id=session_with_data.session_id,
            zip_path="/tmp/test.zip",
            artifacts=[],
            total_tables=2,
            total_rows=4,
        )
        sid = session_with_data.session_id
        resp = client.post(f"/integration/guide?session_id={sid}")
        body = resp.json()
        postman = [s for s in body["sections"] if "Postman" in s["scenario"]]
        assert len(postman) == 1

    def test_guide_response_model_fields(self, session_with_data):
        sid = session_with_data.session_id
        resp = client.post(f"/integration/guide?session_id={sid}")
        body = resp.json()
        assert "session_id" in body
        assert "generated_at" in body
        assert "overview" in body
        assert "sections" in body
        assert "provider" in body


# ── Gateway fallback test ────────────────────────────────────


class TestGatewayFallback:
    @patch("app.ai.service._get_config")
    def test_falls_back_to_offline_when_no_gateway(self, mock_config, schema, data, generation_order):
        from app.models.ai import AIProviderConfig
        mock_config.return_value = AIProviderConfig(gateway_url="", api_token="")

        guide = generate_integration_guide(
            session_id="fallback-test",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        assert guide.provider == "offline"
        assert len(guide.sections) >= 4

    @patch("app.ai.service._send_guide_request")
    @patch("app.ai.service._get_config")
    def test_falls_back_on_gateway_error(self, mock_config, mock_send, schema, data, generation_order):
        from app.ai.gateway_provider import GatewayError
        from app.models.ai import AIProviderConfig

        mock_config.return_value = AIProviderConfig(
            gateway_url="http://fake.gateway", api_token="token123"
        )
        mock_send.side_effect = GatewayError("Connection refused")

        guide = generate_integration_guide(
            session_id="fallback-err",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        assert guide.provider == "offline"

    @patch("app.ai.service._send_guide_request")
    @patch("app.ai.service._get_config")
    def test_uses_gateway_when_available(self, mock_config, mock_send, schema, data, generation_order):
        from app.models.ai import AIProviderConfig

        mock_config.return_value = AIProviderConfig(
            gateway_url="http://fake.gateway", api_token="token123"
        )
        mock_send.return_value = json.dumps({
            "overview": "AI-generated overview",
            "sections": [
                {
                    "scenario": "Import CSV",
                    "summary": "AI summary",
                    "prerequisites": ["DB"],
                    "steps": [
                        {"step_number": 1, "title": "S1", "description": "D1", "code_snippet": "cmd", "language": "bash"},
                    ],
                    "tips": ["Tip 1"],
                }
            ],
        })

        guide = generate_integration_guide(
            session_id="gw-test",
            schema=schema,
            data=data,
            generation_order=generation_order,
        )
        assert guide.provider == "gateway"
        assert guide.overview == "AI-generated overview"
        assert len(guide.sections) == 1
