"""Tests for test environment integration module.

Covers:
- Postman collection generation
- Mock payload generation
- SQL INSERT generation
- API-ready JSON payloads
- Swagger test suite
- CI/CD config
- Integration engine bundle
- Integration router endpoints
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest

from app.exporters.integration_engine import (
    IntegrationEngine,
    build_api_payloads,
    build_ci_config,
    build_mock_payloads,
    build_postman_collection,
    build_qa_pipeline_config,
    build_sql_inserts,
    build_swagger_test_suite,
)
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def sample_schema() -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="name", data_type="VARCHAR", nullable=False),
                    ColumnMetadata(name="email", data_type="VARCHAR", nullable=False),
                    ColumnMetadata(name="active", data_type="BOOLEAN", nullable=True),
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
                    ColumnMetadata(name="status", data_type="VARCHAR", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[
                    ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
                ],
            ),
        ]
    )


@pytest.fixture
def sample_data() -> dict:
    return {
        "customers": [
            {"id": 1, "name": "Alice", "email": "alice@test.com", "active": True},
            {"id": 2, "name": "Bob", "email": "bob@test.com", "active": False},
        ],
        "orders": [
            {"id": 1, "customer_id": 1, "total": 99.99, "status": "completed"},
            {"id": 2, "customer_id": 2, "total": 49.50, "status": "pending"},
        ],
    }


@pytest.fixture
def generation_order() -> list[str]:
    return ["customers", "orders"]


# ── Postman Collection Tests ─────────────────────────────────


class TestPostmanCollection:
    def test_collection_structure(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        assert "info" in col
        assert "item" in col
        assert col["info"]["name"] == "Synthetic Data API Tests"
        assert "schema" in col["info"]
        assert "getpostman.com" in col["info"]["schema"]

    def test_collection_has_folder_per_table(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        folder_names = [f["name"] for f in col["item"]]
        assert "customers" in folder_names
        assert "orders" in folder_names

    def test_crud_operations_generated(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        customers_folder = next(f for f in col["item"] if f["name"] == "customers")
        item_names = [i["name"] for i in customers_folder["item"]]
        assert "Create customers" in item_names
        assert "List customers" in item_names
        assert "Get customers by id" in item_names
        assert "Update customers" in item_names
        assert "Delete customers" in item_names

    def test_bulk_endpoint_included(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        customers_folder = next(f for f in col["item"] if f["name"] == "customers")
        item_names = [i["name"] for i in customers_folder["item"]]
        assert "Bulk create customers" in item_names

    def test_request_has_body(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        customers_folder = next(f for f in col["item"] if f["name"] == "customers")
        create_req = next(i for i in customers_folder["item"] if i["name"] == "Create customers")
        assert "body" in create_req["request"]
        body = json.loads(create_req["request"]["body"]["raw"])
        assert "name" in body

    def test_test_scripts_present(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        customers_folder = next(f for f in col["item"] if f["name"] == "customers")
        create_req = next(i for i in customers_folder["item"] if i["name"] == "Create customers")
        assert "event" in create_req
        scripts = create_req["event"][0]["script"]["exec"]
        assert any("201" in line for line in scripts)

    def test_custom_base_url(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data, base_url="https://api.example.com")
        customers_folder = next(f for f in col["item"] if f["name"] == "customers")
        create_req = next(i for i in customers_folder["item"] if i["name"] == "Create customers")
        assert "https://api.example.com" in create_req["request"]["url"]["raw"]

    def test_valid_json_output(self, sample_schema, sample_data):
        col = build_postman_collection(sample_schema, sample_data)
        text = json.dumps(col)
        parsed = json.loads(text)
        assert parsed["info"]["name"] == col["info"]["name"]


# ── Mock Payload Tests ────────────────────────────────────────


class TestMockPayloads:
    def test_one_payload_per_table(self, sample_schema, sample_data):
        mocks = build_mock_payloads(sample_schema, sample_data)
        assert len(mocks) == 2
        entities = [m.entity for m in mocks]
        assert "customers" in entities
        assert "orders" in entities

    def test_valid_rows_included(self, sample_schema, sample_data):
        mocks = build_mock_payloads(sample_schema, sample_data)
        cust = next(m for m in mocks if m.entity == "customers")
        assert len(cust.valid) == 2
        assert cust.valid[0]["name"] == "Alice"

    def test_invalid_empty_without_negative(self, sample_schema, sample_data):
        mocks = build_mock_payloads(sample_schema, sample_data, None)
        cust = next(m for m in mocks if m.entity == "customers")
        assert cust.invalid == []

    def test_boundary_placeholder(self, sample_schema, sample_data):
        mocks = build_mock_payloads(sample_schema, sample_data)
        for m in mocks:
            assert m.boundary == []


# ── SQL INSERT Tests ──────────────────────────────────────────


class TestSQLInserts:
    def test_basic_output(self, sample_schema, sample_data, generation_order):
        sql = build_sql_inserts(sample_schema, sample_data, generation_order)
        assert "BEGIN;" in sql
        assert "COMMIT;" in sql
        assert "INSERT INTO customers" in sql
        assert "INSERT INTO orders" in sql

    def test_fk_order_respected(self, sample_schema, sample_data, generation_order):
        sql = build_sql_inserts(sample_schema, sample_data, generation_order)
        cust_pos = sql.index("INSERT INTO customers")
        order_pos = sql.index("INSERT INTO orders")
        assert cust_pos < order_pos

    def test_value_escaping(self, sample_schema, sample_data, generation_order):
        sql = build_sql_inserts(sample_schema, sample_data, generation_order)
        assert "'Alice'" in sql
        assert "'alice@test.com'" in sql

    def test_null_handling(self, sample_schema, generation_order):
        data = {"customers": [{"id": 1, "name": "Test", "email": None, "active": None}], "orders": []}
        sql = build_sql_inserts(sample_schema, data, generation_order)
        assert "NULL" in sql

    def test_boolean_values(self, sample_schema, sample_data, generation_order):
        sql = build_sql_inserts(sample_schema, sample_data, generation_order)
        assert "TRUE" in sql
        assert "FALSE" in sql

    def test_row_counts_in_header(self, sample_schema, sample_data, generation_order):
        sql = build_sql_inserts(sample_schema, sample_data, generation_order)
        assert "Tables: 2" in sql
        assert "Total rows: 4" in sql

    def test_empty_table(self, sample_schema, generation_order):
        data = {"customers": [], "orders": []}
        sql = build_sql_inserts(sample_schema, data, generation_order)
        assert "No data for customers" in sql


# ── API Payload Tests ─────────────────────────────────────────


class TestAPIPayloads:
    def test_one_payload_per_table(self, sample_schema, sample_data):
        payloads = build_api_payloads(sample_schema, sample_data)
        assert len(payloads) == 2

    def test_pks_stripped(self, sample_schema, sample_data):
        payloads = build_api_payloads(sample_schema, sample_data)
        cust = next(p for p in payloads if p.entity == "customers")
        for row in cust.payloads:
            assert "id" not in row

    def test_endpoint_format(self, sample_schema, sample_data):
        payloads = build_api_payloads(sample_schema, sample_data)
        cust = next(p for p in payloads if p.entity == "customers")
        assert cust.endpoint == "/api/customers"
        assert cust.method == "POST"
        assert cust.content_type == "application/json"

    def test_payload_data_correct(self, sample_schema, sample_data):
        payloads = build_api_payloads(sample_schema, sample_data)
        cust = next(p for p in payloads if p.entity == "customers")
        assert len(cust.payloads) == 2
        assert cust.payloads[0]["name"] == "Alice"


# ── Swagger Test Suite Tests ──────────────────────────────────


class TestSwaggerTestSuite:
    def test_suite_structure(self, sample_schema, sample_data):
        suite = build_swagger_test_suite(sample_schema, sample_data)
        assert suite.title == "Synthetic Data API Test Suite"
        assert len(suite.tests) > 0

    def test_crud_operations_per_table(self, sample_schema, sample_data):
        suite = build_swagger_test_suite(sample_schema, sample_data)
        op_ids = [t.operation_id for t in suite.tests]
        assert "create_customers" in op_ids
        assert "list_customers" in op_ids
        assert "get_customers" in op_ids
        assert "create_customers_invalid" in op_ids

    def test_invalid_test_case_422(self, sample_schema, sample_data):
        suite = build_swagger_test_suite(sample_schema, sample_data)
        invalid = next(t for t in suite.tests if t.operation_id == "create_customers_invalid")
        assert invalid.expected_status == 422
        assert invalid.request_body == {}

    def test_custom_base_url(self, sample_schema, sample_data):
        suite = build_swagger_test_suite(sample_schema, sample_data, base_url="https://prod.api.com")
        assert suite.base_url == "https://prod.api.com"

    def test_create_has_body(self, sample_schema, sample_data):
        suite = build_swagger_test_suite(sample_schema, sample_data)
        create = next(t for t in suite.tests if t.operation_id == "create_customers")
        assert create.request_body is not None
        assert "name" in create.request_body


# ── CI/CD Config Tests ────────────────────────────────────────


class TestCIConfig:
    def test_workflow_structure(self, sample_schema):
        ci = build_ci_config(sample_schema)
        assert ci["name"] == "synthetic-data-tests"
        assert "jobs" in ci
        assert "seed-database" in ci["jobs"]
        assert "api-tests" in ci["jobs"]
        assert "swagger-validation" in ci["jobs"]

    def test_postgres_service(self, sample_schema):
        ci = build_ci_config(sample_schema)
        services = ci["jobs"]["seed-database"]["services"]
        assert "postgres" in services

    def test_newman_step(self, sample_schema):
        ci = build_ci_config(sample_schema)
        steps = ci["jobs"]["api-tests"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert "Install Newman" in step_names
        assert "Run Postman collection" in step_names

    def test_qa_pipeline(self, sample_schema):
        qa = build_qa_pipeline_config(sample_schema)
        assert "qa_pipeline" in qa
        pipeline = qa["qa_pipeline"]
        assert len(pipeline["stages"]) == 5
        stage_names = [s["name"] for s in pipeline["stages"]]
        assert "data-seeding" in stage_names
        assert "api-smoke-tests" in stage_names
        assert "cleanup" in stage_names


# ── Integration Engine Tests ──────────────────────────────────


class TestIntegrationEngine:
    def test_bundle_generation(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test123",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        assert bundle.session_id == "test123"
        assert bundle.total_tables == 2
        assert bundle.total_rows == 4
        assert len(bundle.artifacts) == 7

    def test_zip_contents(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test456",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            names = zf.namelist()
            assert "postman_collection.json" in names
            assert "mock_payloads.json" in names
            assert "sql_inserts.sql" in names
            assert "api_payloads.json" in names
            assert "swagger_tests.json" in names
            assert "ci_pipeline.json" in names
            assert "qa_pipeline.json" in names
            assert "_manifest.json" in names

    def test_zip_postman_valid_json(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test789",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            postman = json.loads(zf.read("postman_collection.json"))
            assert "info" in postman
            assert len(postman["item"]) == 2

    def test_zip_sql_inserts_content(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test_sql",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            sql = zf.read("sql_inserts.sql").decode()
            assert "BEGIN;" in sql
            assert "COMMIT;" in sql
            assert "INSERT INTO customers" in sql

    def test_per_table_payloads(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test_per_table",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            names = zf.namelist()
            assert "payloads/customers.json" in names
            assert "payloads/orders.json" in names

    def test_manifest(self, sample_schema, sample_data, generation_order, tmp_path):
        engine = IntegrationEngine(output_dir=str(tmp_path))
        bundle = engine.generate_bundle(
            session_id="test_manifest",
            schema=sample_schema,
            data=sample_data,
            generation_order=generation_order,
        )
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            manifest = json.loads(zf.read("_manifest.json"))
            assert manifest["session_id"] == "test_manifest"
            assert manifest["total_tables"] == 2
            assert manifest["total_rows"] == 4
            assert len(manifest["artifacts"]) == 7


# ── Router Integration Tests ─────────────────────────────────


class TestIntegrationRouter:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def _create_session_with_data(self, client):
        """Upload SQL, parse, generate → return session_id."""
        sql = b"""
        CREATE TABLE customers (
            id INT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(200)
        );
        CREATE TABLE orders (
            id INT PRIMARY KEY,
            customer_id INT REFERENCES customers(id),
            total DECIMAL(10,2)
        );
        """
        upload = client.post("/upload", files=[("files", ("schema.sql", sql, "text/plain"))])
        sid = upload.json()["session_id"]
        client.post(f"/parse?session_id={sid}")
        client.post(f"/generate?session_id={sid}&row_count=5&include_valid=true")
        return sid

    def test_generate_integration(self, client):
        sid = self._create_session_with_data(client)
        resp = client.post(f"/integration/generate?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "artifacts" in body
        assert len(body["artifacts"]) == 7
        assert body["total_tables"] == 2

    def test_download_integration(self, client):
        sid = self._create_session_with_data(client)
        client.post(f"/integration/generate?session_id={sid}")
        resp = client.get(f"/integration/download?session_id={sid}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_get_postman_collection(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/postman?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "info" in body
        assert "item" in body

    def test_get_api_payloads(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/payloads?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        entities = [p["entity"] for p in body]
        assert "customers" in entities

    def test_get_sql_inserts(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/sql?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "sql" in body
        assert "BEGIN;" in body["sql"]
        assert "INSERT INTO customers" in body["sql"]

    def test_get_swagger_tests(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/swagger?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "tests" in body
        assert len(body["tests"]) > 0

    def test_get_mock_payloads(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/mocks?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2

    def test_get_ci_config(self, client):
        sid = self._create_session_with_data(client)
        resp = client.get(f"/integration/ci?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "ci_cd" in body
        assert "qa_pipeline" in body

    def test_no_data_returns_400(self, client):
        sql = b"CREATE TABLE t (id INT PRIMARY KEY);"
        upload = client.post("/upload", files=[("files", ("s.sql", sql, "text/plain"))])
        sid = upload.json()["session_id"]
        client.post(f"/parse?session_id={sid}")
        # Skip /generate
        resp = client.post(f"/integration/generate?session_id={sid}")
        assert resp.status_code == 400
        assert "generate" in resp.json()["detail"].lower()

    def test_no_schema_returns_400(self, client):
        resp = client.get("/integration/ci?session_id=nonexistent")
        assert resp.status_code == 404

    def test_download_without_generate_returns_400(self, client):
        sid = self._create_session_with_data(client)
        # Don't call /integration/generate
        resp = client.get(f"/integration/download?session_id={sid}")
        assert resp.status_code == 400
