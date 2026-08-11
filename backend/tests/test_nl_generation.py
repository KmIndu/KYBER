"""Tests for the natural-language schema inference and generation module."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.ai.prompts import NL_SYSTEM_PROMPT, build_nl_schema_prompt
from app.ai.service import infer_schema_from_prompt
from app.main import app
from app.models.nl import (
    InferredColumn,
    InferredConstraint,
    InferredEntity,
    InferredRelationship,
    NLGenerateResponse,
    NLGenerateTableInfo,
    NLRequest,
    NLSchemaResult,
)
from app.parsers.nl_schema_parser import (
    NLParserError,
    infer_schema_offline,
    parse_nl_response,
)

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════
# NL Pydantic Models
# ═══════════════════════════════════════════════════════════════


class TestNLModels:
    def test_nl_request_valid(self):
        req = NLRequest(prompt="Generate banking data")
        assert req.prompt == "Generate banking data"
        assert req.row_count == 10
        assert req.include_invalid is False

    def test_nl_request_custom(self):
        req = NLRequest(prompt="Insurance claims", row_count=500, include_invalid=True)
        assert req.row_count == 500
        assert req.include_invalid is True

    def test_nl_request_min_length(self):
        with pytest.raises(Exception):
            NLRequest(prompt="Hi")

    def test_nl_request_max_length(self):
        with pytest.raises(Exception):
            NLRequest(prompt="x" * 2001)

    def test_nl_request_row_count_bounds(self):
        with pytest.raises(Exception):
            NLRequest(prompt="some valid prompt", row_count=0)
        with pytest.raises(Exception):
            NLRequest(prompt="some valid prompt", row_count=1000001)

    def test_inferred_entity(self):
        col = InferredColumn(name="id", data_type="INTEGER", is_primary_key=True)
        entity = InferredEntity(name="users", columns=[col])
        assert entity.name == "users"
        assert len(entity.columns) == 1
        assert entity.columns[0].is_primary_key is True

    def test_inferred_relationship(self):
        rel = InferredRelationship(
            from_table="orders", from_column="user_id",
            to_table="users", to_column="id",
        )
        assert rel.from_table == "orders"
        assert rel.to_column == "id"

    def test_inferred_constraint(self):
        c = InferredConstraint(table="users", column="age", rule="age >= 18")
        assert c.rule == "age >= 18"

    def test_nl_schema_result_defaults(self):
        r = NLSchemaResult()
        assert r.domain == ""
        assert r.entities == []
        assert r.schema.tables == []

    def test_nl_generate_response(self):
        r = NLGenerateResponse(session_id="abc123", prompt="test")
        assert r.session_id == "abc123"
        assert r.total_rows == 0


# ═══════════════════════════════════════════════════════════════
# NL Prompts
# ═══════════════════════════════════════════════════════════════


class TestNLPrompts:
    def test_nl_system_prompt_exists(self):
        assert "database schema architect" in NL_SYSTEM_PROMPT

    def test_build_nl_schema_prompt(self):
        prompt = build_nl_schema_prompt("Generate banking data")
        assert "Generate banking data" in prompt
        assert "entities" in prompt
        assert "relationships" in prompt
        assert "Return JSON" in prompt

    def test_prompt_escapes_user_input(self):
        prompt = build_nl_schema_prompt('Test with "quotes" and {braces}')
        assert "Test with" in prompt


# ═══════════════════════════════════════════════════════════════
# NL Schema Parser — parse_nl_response
# ═══════════════════════════════════════════════════════════════


class TestNLSchemaParser:
    def test_parse_valid_json(self):
        ai_json = json.dumps({
            "domain": "banking",
            "entities": [
                {
                    "name": "customers",
                    "description": "Bank customers",
                    "columns": [
                        {"name": "id", "data_type": "INTEGER", "nullable": False, "is_primary_key": True},
                        {"name": "name", "data_type": "VARCHAR(100)", "nullable": False},
                        {"name": "email", "data_type": "VARCHAR(255)", "nullable": False, "is_unique": True},
                    ],
                },
                {
                    "name": "accounts",
                    "columns": [
                        {"name": "id", "data_type": "INTEGER", "nullable": False, "is_primary_key": True},
                        {"name": "customer_id", "data_type": "INTEGER", "nullable": False},
                        {"name": "balance", "data_type": "DECIMAL(10,2)", "nullable": False},
                    ],
                },
            ],
            "relationships": [
                {"from_table": "accounts", "from_column": "customer_id", "to_table": "customers", "to_column": "id"},
            ],
            "constraints": [
                {"table": "accounts", "column": "balance", "rule": "balance >= 0"},
            ],
        })

        result = parse_nl_response(ai_json)
        assert result.domain == "banking"
        assert len(result.entities) == 2
        assert len(result.relationships) == 1
        assert len(result.constraints) == 1

        # Schema is built
        assert len(result.schema.tables) == 2
        customers = result.schema.tables[0]
        assert customers.name == "customers"
        assert len(customers.columns) == 3
        assert customers.primary_keys == ["id"]

        accounts = result.schema.tables[1]
        assert len(accounts.foreign_keys) == 1
        assert accounts.foreign_keys[0].references_table == "customers"

        # Generation order
        assert result.generation_order[0] == "customers"
        assert "accounts" in result.generation_order

        # DDL generated
        assert "CREATE TABLE customers" in result.generated_sql
        assert "CREATE TABLE accounts" in result.generated_sql
        assert "FOREIGN KEY" in result.generated_sql

    def test_parse_json_in_code_fence(self):
        raw = '```json\n{"domain": "test", "entities": [], "relationships": [], "constraints": []}\n```'
        result = parse_nl_response(raw)
        assert result.domain == "test"

    def test_parse_invalid_json_raises(self):
        with pytest.raises(NLParserError, match="Invalid JSON"):
            parse_nl_response("not json at all")

    def test_parse_non_object_raises(self):
        with pytest.raises(NLParserError, match="Expected JSON object"):
            parse_nl_response("[1, 2, 3]")

    def test_parse_empty_entities(self):
        result = parse_nl_response('{"domain": "empty", "entities": [], "relationships": []}')
        assert result.domain == "empty"
        assert len(result.schema.tables) == 0

    def test_parse_handles_missing_fields(self):
        result = parse_nl_response('{"domain": "partial"}')
        assert result.domain == "partial"
        assert result.entities == []

    def test_parse_skips_malformed_entities(self):
        raw = json.dumps({
            "domain": "test",
            "entities": [
                "not_a_dict",
                {"name": "valid", "columns": [{"name": "id", "data_type": "INTEGER"}]},
            ],
            "relationships": ["not_a_dict"],
        })
        result = parse_nl_response(raw)
        assert len(result.entities) == 1


# ═══════════════════════════════════════════════════════════════
# Offline Schema Inference
# ═══════════════════════════════════════════════════════════════


class TestOfflineInference:
    def test_banking_domain(self):
        result = infer_schema_offline("Generate banking customer data with failed KYC cases")
        assert result.domain == "banking"
        table_names = [t.name for t in result.schema.tables]
        assert "customers" in table_names
        assert "accounts" in table_names
        assert "transactions" in table_names
        # KYC check constraint
        customers = next(t for t in result.schema.tables if t.name == "customers")
        kyc_col = next(c for c in customers.columns if c.name == "kyc_status")
        assert "failed" in kyc_col.check_constraint

    def test_insurance_domain(self):
        result = infer_schema_offline("Generate insurance claims with fraud edge cases")
        assert result.domain == "insurance"
        table_names = [t.name for t in result.schema.tables]
        assert "policyholders" in table_names
        assert "policies" in table_names
        assert "claims" in table_names
        assert "payments" in table_names

    def test_ecommerce_domain(self):
        result = infer_schema_offline("Create e-commerce product catalog with orders")
        assert result.domain == "e-commerce"
        table_names = [t.name for t in result.schema.tables]
        assert "customers" in table_names
        assert "products" in table_names
        assert "orders" in table_names
        assert "order_items" in table_names

    def test_healthcare_domain(self):
        result = infer_schema_offline("Generate hospital patient records with prescriptions")
        assert result.domain == "healthcare"
        table_names = [t.name for t in result.schema.tables]
        assert "patients" in table_names
        assert "doctors" in table_names
        assert "appointments" in table_names
        assert "prescriptions" in table_names

    def test_education_domain(self):
        result = infer_schema_offline("Create student enrollment data for university courses")
        assert result.domain == "education"
        table_names = [t.name for t in result.schema.tables]
        assert "students" in table_names
        assert "courses" in table_names
        assert "enrollments" in table_names

    def test_generic_fallback(self):
        result = infer_schema_offline("Generate some test data for my application")
        assert result.domain == "general"
        table_names = [t.name for t in result.schema.tables]
        assert "users" in table_names
        assert "records" in table_names

    def test_generation_order_respects_fks(self):
        result = infer_schema_offline("banking account transactions")
        # Parent tables come before children
        order = result.generation_order
        assert order.index("customers") < order.index("accounts")
        assert order.index("accounts") < order.index("transactions")

    def test_generated_sql_is_valid_ddl(self):
        result = infer_schema_offline("insurance policy claims")
        assert "CREATE TABLE" in result.generated_sql
        assert "PRIMARY KEY" in result.generated_sql
        assert "FOREIGN KEY" in result.generated_sql

    def test_all_tables_have_primary_keys(self):
        for prompt in ["banking data", "insurance claims", "e-commerce orders", "hospital patients", "student courses"]:
            result = infer_schema_offline(prompt)
            for table in result.schema.tables:
                assert len(table.primary_keys) > 0, f"Table {table.name} has no PK in domain from '{prompt}'"

    def test_foreign_keys_reference_valid_tables(self):
        result = infer_schema_offline("banking data with transactions")
        table_names = {t.name for t in result.schema.tables}
        for table in result.schema.tables:
            for fk in table.foreign_keys:
                assert fk.references_table in table_names, (
                    f"FK in {table.name} references unknown table {fk.references_table}"
                )


# ═══════════════════════════════════════════════════════════════
# AI Service — infer_schema_from_prompt (offline mode)
# ═══════════════════════════════════════════════════════════════


class TestAIServiceNL:
    def test_infer_schema_offline_mode(self):
        """Without gateway config, should fall back to offline inference."""
        result = infer_schema_from_prompt("Generate banking data")
        assert result.domain == "banking"
        assert len(result.schema.tables) > 0

    def test_infer_returns_valid_schema(self):
        result = infer_schema_from_prompt("Insurance claim processing data")
        schema = result.schema
        assert len(schema.tables) >= 3
        for table in schema.tables:
            assert table.name
            assert len(table.columns) > 0


# ═══════════════════════════════════════════════════════════════
# Router — POST /nl/infer-schema
# ═══════════════════════════════════════════════════════════════


class TestNLInferSchemaEndpoint:
    def test_infer_schema_banking(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Generate banking customer data"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "banking"
        assert len(data["entities"]) >= 2
        assert len(data["schema"]["tables"]) >= 2
        assert len(data["generation_order"]) >= 2
        assert "CREATE TABLE" in data["generated_sql"]

    def test_infer_schema_insurance(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Generate insurance claims with edge cases"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "insurance"
        assert any(e["name"] == "claims" for e in data["entities"])

    def test_infer_schema_ecommerce(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Create e-commerce product orders"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "e-commerce"

    def test_infer_schema_prompt_too_short(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Hi"})
        assert resp.status_code == 422

    def test_infer_schema_custom_row_count(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Banking data", "row_count": 500})
        assert resp.status_code == 200

    def test_infer_schema_returns_relationships(self):
        resp = client.post("/nl/infer-schema", json={"prompt": "Generate banking account transactions"})
        data = resp.json()
        assert len(data["relationships"]) >= 1
        rel = data["relationships"][0]
        assert "from_table" in rel
        assert "to_table" in rel


# ═══════════════════════════════════════════════════════════════
# Router — POST /nl/generate
# ═══════════════════════════════════════════════════════════════


class TestNLGenerateEndpoint:
    def test_generate_banking(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate banking customer data with transactions",
            "row_count": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "banking"
        assert data["total_rows"] > 0
        assert data["session_id"]
        assert len(data["tables"]) >= 2
        assert "CREATE TABLE" in data["generated_sql"]
        assert data["generation_order"]

    def test_generate_insurance(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate insurance claims data",
            "row_count": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "insurance"
        assert data["total_rows"] > 0

    def test_generate_with_negatives(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate banking KYC data",
            "row_count": 5,
            "include_invalid": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["negative_cases"] > 0

    def test_generate_creates_session(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate e-commerce order data",
            "row_count": 3,
        })
        data = resp.json()
        session_id = data["session_id"]

        # Session should be usable for /summary and /download
        summary = client.get(f"/summary?session_id={session_id}")
        assert summary.status_code == 200
        assert summary.json()["tables_parsed"] > 0

    def test_generate_validation_report(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate hospital patient data",
            "row_count": 5,
        })
        data = resp.json()
        assert "validation" in data
        assert data["validation"] is not None
        assert data["validation"]["total_rows"] > 0

    def test_generate_downloads_work(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate student enrollment data",
            "row_count": 3,
        })
        session_id = resp.json()["session_id"]

        for fmt in ["csv", "json", "sql"]:
            dl = client.get(f"/download/{fmt}?session_id={session_id}")
            assert dl.status_code == 200, f"Download {fmt} failed"
            assert dl.headers["content-type"] == "application/zip"

    def test_generate_preview_works(self):
        resp = client.post("/nl/generate", json={
            "prompt": "Generate banking customer data",
            "row_count": 5,
        })
        data = resp.json()
        session_id = data["session_id"]
        table_name = data["tables"][0]["table_name"]

        preview = client.get(f"/preview/{table_name}?session_id={session_id}")
        assert preview.status_code == 200
        assert preview.json()["total_rows"] > 0

    def test_generate_prompt_too_short(self):
        resp = client.post("/nl/generate", json={"prompt": "Hi"})
        assert resp.status_code == 422

    def test_generate_row_count_bounds(self):
        resp = client.post("/nl/generate", json={"prompt": "Generate banking data", "row_count": 0})
        assert resp.status_code == 422
        resp = client.post("/nl/generate", json={"prompt": "Generate banking data", "row_count": 1000001})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
# DDL Generation
# ═══════════════════════════════════════════════════════════════


class TestDDLGeneration:
    def test_ddl_has_all_tables(self):
        result = infer_schema_offline("banking transactions")
        for table in result.schema.tables:
            assert f"CREATE TABLE {table.name}" in result.generated_sql

    def test_ddl_has_foreign_keys(self):
        result = infer_schema_offline("insurance claims")
        assert "FOREIGN KEY" in result.generated_sql
        assert "REFERENCES" in result.generated_sql

    def test_ddl_has_check_constraints(self):
        result = infer_schema_offline("banking KYC data")
        assert "CHECK" in result.generated_sql

    def test_ddl_has_not_null(self):
        result = infer_schema_offline("banking data")
        assert "NOT NULL" in result.generated_sql

    def test_ddl_has_unique(self):
        result = infer_schema_offline("banking data")
        assert "UNIQUE" in result.generated_sql
