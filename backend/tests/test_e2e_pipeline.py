"""End-to-end integration tests — full upload → parse → generate → download → summary → preview flow."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_store import store

FIXTURES = Path(__file__).parent / "fixtures"

SQL_SCHEMA = """\
CREATE TABLE customers (
    customer_id INT PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE policies (
    policy_id INT PRIMARY KEY,
    customer_id INT NOT NULL,
    policy_number VARCHAR(50) UNIQUE NOT NULL,
    premium DECIMAL(12, 2) NOT NULL CHECK (premium > 0),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE claims (
    claim_id INT PRIMARY KEY,
    policy_id INT NOT NULL,
    claim_amount DECIMAL(12, 2) NOT NULL CHECK (claim_amount > 0),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);
"""


@pytest.fixture(autouse=True)
def _clear():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ── Full E2E: upload → parse → generate → download → summary → preview ──


class TestFullPipelineE2E:
    """Walk through the entire user journey as the frontend would."""

    def _upload(self, client, sql_text=SQL_SCHEMA):
        resp = client.post(
            "/upload",
            files=[("files", ("schema.sql", sql_text.encode(), "text/plain"))],
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "session_id" in body
        assert len(body["files"]) == 1
        assert body["files"][0]["file_type"] == "sql"
        return body["session_id"]

    def _parse(self, client, session_id):
        resp = client.post(f"/parse?session_id={session_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tables"]
        assert body["generation_order"]
        return body

    def _generate(self, client, session_id, row_count=20, **kwargs):
        params = {"session_id": session_id, "row_count": row_count, **kwargs}
        resp = client.post("/generate", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_rows"] > 0
        assert body["validation"]
        return body

    def _download(self, client, session_id, fmt):
        resp = client.get(f"/download/{fmt}?session_id={session_id}")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        return zf

    def _summary(self, client, session_id):
        resp = client.get(f"/summary?session_id={session_id}")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _preview(self, client, session_id, table_name, limit=5):
        resp = client.get(
            f"/preview/{table_name}?session_id={session_id}&limit={limit}"
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # ── Happy path ────────────────────────────────────────

    def test_full_workflow_valid_cases(self, client):
        """Upload SQL → parse → generate valid → download all formats → summary → preview."""
        # Upload
        sid = self._upload(client)

        # Parse
        parse = self._parse(client, sid)
        assert parse["generation_order"] == ["customers", "policies", "claims"]
        assert len(parse["tables"]) == 3

        # Generate
        gen = self._generate(client, sid, row_count=25)
        assert gen["row_count"] == 25
        assert gen["total_rows"] == 75  # 25 * 3 tables
        assert gen["validation"]["failed"] == 0

        # Download all 3 formats
        for fmt in ("csv", "json", "sql"):
            zf = self._download(client, sid, fmt)
            names = zf.namelist()
            assert "_export_summary.json" in names
            assert len(names) >= 4  # 3 tables + summary

        # Summary
        summary = self._summary(client, sid)
        assert summary["tables_parsed"] == 3
        assert summary["total_rows"] == 75
        assert summary["row_count"] == 25
        assert len(summary["exports"]) == 3
        assert summary["generated_at"] is not None

        # Preview each table
        for table in ["customers", "policies", "claims"]:
            preview = self._preview(client, sid, table, limit=5)
            assert preview["table_name"] == table
            assert preview["total_rows"] == 25
            assert preview["preview_count"] == 5
            assert len(preview["rows"]) == 5
            assert len(preview["columns"]) > 0

    def test_full_workflow_with_negative_cases(self, client):
        """Upload → parse → generate with invalid + boundary → verify negative count."""
        sid = self._upload(client)
        self._parse(client, sid)

        gen = self._generate(
            client,
            sid,
            row_count=10,
            include_valid=True,
            include_invalid=True,
            include_boundary=True,
            include_duplicates=True,
        )
        assert gen["negative_cases"] > 0
        # total_rows = valid (30) + negative rows merged in
        assert gen["total_rows"] >= 30

    def test_full_workflow_only_negative_cases(self, client):
        """Generate with include_valid=false — valid rows are zero but negative cases exist."""
        sid = self._upload(client)
        self._parse(client, sid)

        params = {
            "session_id": sid,
            "row_count": 10,
            "include_valid": False,
            "include_invalid": True,
        }
        resp = client.post("/generate", params=params)
        assert resp.status_code == 200
        body = resp.json()
        assert body["negative_cases"] > 0
        # Negative rows are now merged into total_rows for preview/export
        assert body["total_rows"] == body["negative_cases"]

    # ── Error scenarios the frontend must handle ──────────

    def test_generate_before_parse_fails(self, client):
        """Frontend should get a clear 400 if generate called before parse."""
        sid = self._upload(client)
        resp = client.post(f"/generate?session_id={sid}")
        assert resp.status_code == 400
        assert "parse" in resp.json()["detail"].lower()

    def test_download_before_generate_fails(self, client):
        """Frontend should get 400 if download called before generate."""
        sid = self._upload(client)
        self._parse(client, sid)
        resp = client.get(f"/download/csv?session_id={sid}")
        assert resp.status_code == 400

    def test_invalid_session_id(self, client):
        """Frontend should get 404 for bad session IDs."""
        for endpoint in ["/parse", "/generate"]:
            resp = client.post(f"{endpoint}?session_id=nonexistent")
            assert resp.status_code == 404

        for endpoint in ["/summary", "/download/csv", "/preview/customers"]:
            resp = client.get(f"{endpoint}?session_id=nonexistent")
            assert resp.status_code == 404

    def test_unsupported_file_type(self, client):
        """Frontend should get 400 for unsupported file extension."""
        resp = client.post(
            "/upload",
            files=[("files", ("data.pdf", b"binary", "application/octet-stream"))],
        )
        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()

    def test_empty_upload(self, client):
        """Frontend should handle when no files sent."""
        resp = client.post("/upload", files=[])
        assert resp.status_code == 422  # FastAPI validation

    def test_preview_missing_table(self, client):
        """Frontend should handle 404 for non-existent table preview."""
        sid = self._upload(client)
        self._parse(client, sid)
        self._generate(client, sid, row_count=5)

        resp = client.get(f"/preview/nonexistent?session_id={sid}")
        assert resp.status_code == 404

    # ── Data integrity checks ─────────────────────────────

    def test_csv_download_has_correct_data(self, client):
        """Verify CSV ZIP contains correct table files with row data."""
        sid = self._upload(client)
        self._parse(client, sid)
        self._generate(client, sid, row_count=5)

        zf = self._download(client, sid, "csv")
        for table in ["customers", "policies", "claims"]:
            content = zf.read(f"{table}.csv").decode("utf-8")
            lines = [l for l in content.strip().split("\n") if l]
            assert len(lines) == 6  # 1 header + 5 data rows

    def test_json_download_has_correct_data(self, client):
        """Verify JSON ZIP contains valid JSON arrays with correct row count."""
        import json

        sid = self._upload(client)
        self._parse(client, sid)
        self._generate(client, sid, row_count=5)

        zf = self._download(client, sid, "json")
        for table in ["customers", "policies", "claims"]:
            data = json.loads(zf.read(f"{table}.json").decode("utf-8"))
            assert isinstance(data, list)
            assert len(data) == 5

    def test_sql_download_has_insert_statements(self, client):
        """Verify SQL ZIP contains INSERT INTO statements."""
        sid = self._upload(client)
        self._parse(client, sid)
        self._generate(client, sid, row_count=3)

        zf = self._download(client, sid, "sql")
        for table in ["customers", "policies", "claims"]:
            content = zf.read(f"{table}.sql").decode("utf-8")
            assert "INSERT INTO" in content
            # Multi-value INSERT batches: 3 value tuples in one statement
            assert content.count("INSERT INTO") >= 1

    def test_validation_passes_for_valid_data(self, client):
        """All generated valid data should pass validation."""
        sid = self._upload(client)
        self._parse(client, sid)
        gen = self._generate(client, sid, row_count=50)

        v = gen["validation"]
        assert v["total_rows"] == 150  # 50 * 3
        assert v["passed"] == 150
        assert v["failed"] == 0
        assert len(v["tables"]) == 3
        for t in v["tables"]:
            assert t["failed"] == 0

    def test_generation_order_preserves_fk_integrity(self, client):
        """Generation order must be: customers → policies → claims."""
        sid = self._upload(client)
        parse = self._parse(client, sid)
        order = parse["generation_order"]
        assert order.index("customers") < order.index("policies")
        assert order.index("policies") < order.index("claims")


# ── OpenAPI-only E2E flow ─────────────────────────────────────

OPENAPI_SPEC = """\
openapi: "3.0.0"
info:
  title: Pet Store
  version: "1.0"
paths: {}
components:
  schemas:
    Pet:
      type: object
      required:
        - id
        - name
      properties:
        id:
          type: integer
        name:
          type: string
        status:
          type: string
          enum:
            - available
            - pending
            - sold
    Owner:
      type: object
      properties:
        owner_id:
          type: integer
        email:
          type: string
          format: email
"""


class TestOpenAPIOnlyE2E:
    """Full e2e with only an OpenAPI spec (no SQL)."""

    def test_openapi_full_flow(self, client):
        # Upload OpenAPI YAML
        resp = client.post(
            "/upload",
            files=[("files", ("petstore.yaml", OPENAPI_SPEC.encode(), "text/plain"))],
        )
        assert resp.status_code == 201
        sid = resp.json()["session_id"]
        assert resp.json()["files"][0]["file_type"] == "openapi"

        # Parse — should create schema from OpenAPI
        resp = client.post(f"/parse?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["openapi_schemas"] == 2
        assert len(body["tables"]) == 2
        assert body["generation_order"]

        # Generate
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        assert resp.status_code == 200
        gen = resp.json()
        assert gen["total_rows"] == 10  # 5 * 2 tables
        assert gen["validation"]

        # Summary
        resp = client.get(f"/summary?session_id={sid}")
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["tables_parsed"] == 2
        assert summary["total_rows"] == 10

        # Download
        resp = client.get(f"/download/csv?session_id={sid}")
        assert resp.status_code == 200

        # Preview
        resp = client.get(f"/preview/Pet?session_id={sid}")
        assert resp.status_code == 200
        assert resp.json()["total_rows"] == 5


# ── BDD-only E2E flow ────────────────────────────────────────

BDD_FEATURE = """\
Feature: Loan Application
  Scenario: Valid loan application
    Given age is above 18
    And income is above 30000
    And email is valid
    Then the application should succeed

  Scenario: Underage applicant
    Given age is below 18
    Then the application should fail
"""


class TestBDDOnlyE2E:
    """Full e2e with only a BDD feature file."""

    def test_bdd_full_flow(self, client):
        # Upload BDD feature
        resp = client.post(
            "/upload",
            files=[("files", ("loan.feature", BDD_FEATURE.encode(), "text/plain"))],
        )
        assert resp.status_code == 201
        sid = resp.json()["session_id"]
        assert resp.json()["files"][0]["file_type"] == "bdd"

        # Parse — should derive schema from BDD rules
        resp = client.post(f"/parse?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bdd_scenarios"] >= 2
        assert len(body["tables"]) >= 1
        assert body["generation_order"]

        # Generate
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        assert resp.status_code == 200
        gen = resp.json()
        assert gen["total_rows"] >= 5
        assert gen["validation"]

        # Summary
        resp = client.get(f"/summary?session_id={sid}")
        assert resp.status_code == 200

        # Download
        resp = client.get(f"/download/json?session_id={sid}")
        assert resp.status_code == 200

        # Preview
        resp = client.get(f"/preview/bdd_data?session_id={sid}")
        assert resp.status_code == 200
        assert resp.json()["total_rows"] == 5
