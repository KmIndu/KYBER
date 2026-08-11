"""Tests for the unified pipeline router — /upload, /parse, /generate, /download/*, /summary."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_store import store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clear_sessions():
    """Clean session store between tests."""
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sql_file():
    return ("sample_schema.sql", open(FIXTURES / "sample_schema.sql", "rb"), "text/plain")


@pytest.fixture
def openapi_file():
    return ("sample_openapi.yaml", open(FIXTURES / "sample_openapi.yaml", "rb"), "text/plain")


@pytest.fixture
def bdd_file():
    return ("sample_rules.feature", open(FIXTURES / "sample_rules.feature", "rb"), "text/plain")


# ── Helper ────────────────────────────────────────────────────


def _upload_sql(client) -> str:
    """Upload SQL fixture, return session_id."""
    with open(FIXTURES / "sample_schema.sql", "rb") as f:
        resp = client.post("/upload", files=[("files", ("schema.sql", f, "text/plain"))])
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _upload_all(client) -> str:
    """Upload SQL + OpenAPI + BDD, return session_id."""
    with (
        open(FIXTURES / "sample_schema.sql", "rb") as sql,
        open(FIXTURES / "sample_openapi.yaml", "rb") as api,
        open(FIXTURES / "sample_rules.feature", "rb") as bdd,
    ):
        resp = client.post(
            "/upload",
            files=[
                ("files", ("schema.sql", sql, "text/plain")),
                ("files", ("api.yaml", api, "text/plain")),
                ("files", ("rules.feature", bdd, "text/plain")),
            ],
        )
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _upload_parse_generate(client, row_count=5) -> str:
    """Full pipeline through generate, return session_id."""
    sid = _upload_sql(client)
    resp = client.post(f"/parse?session_id={sid}")
    assert resp.status_code == 200
    resp = client.post(f"/generate?session_id={sid}&row_count={row_count}")
    assert resp.status_code == 200
    return sid


# ── POST /upload ──────────────────────────────────────────────


class TestUpload:
    def test_upload_sql(self, client):
        sid = _upload_sql(client)
        assert len(sid) == 16

    def test_upload_returns_201(self, client):
        with open(FIXTURES / "sample_schema.sql", "rb") as f:
            resp = client.post("/upload", files=[("files", ("s.sql", f, "text/plain"))])
        assert resp.status_code == 201

    def test_upload_file_info(self, client):
        with open(FIXTURES / "sample_schema.sql", "rb") as f:
            resp = client.post("/upload", files=[("files", ("schema.sql", f, "text/plain"))])
        body = resp.json()
        assert body["files"][0]["file_type"] == "sql"
        assert body["files"][0]["filename"] == "schema.sql"
        assert body["files"][0]["size_bytes"] > 0

    def test_upload_multiple_files(self, client):
        sid = _upload_all(client)
        session = store.get(sid)
        assert session.raw_sql is not None
        assert session.raw_openapi is not None
        assert session.raw_bdd is not None

    def test_upload_unsupported_file(self, client):
        f = io.BytesIO(b"some data")
        resp = client.post("/upload", files=[("files", ("readme.md", f, "text/plain"))])
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_upload_invalid_encoding(self, client):
        f = io.BytesIO(b"\xff\xfe invalid")
        resp = client.post("/upload", files=[("files", ("bad.sql", f, "text/plain"))])
        # May or may not fail depending on decode — just ensure no 500
        assert resp.status_code in (201, 400)

    def test_upload_creates_session(self, client):
        assert store.count == 0
        _upload_sql(client)
        assert store.count == 1


# ── POST /parse ───────────────────────────────────────────────


class TestParse:
    def test_parse_sql_only(self, client):
        sid = _upload_sql(client)
        resp = client.post(f"/parse?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert len(body["tables"]) > 0
        assert len(body["generation_order"]) > 0

    def test_parse_table_info(self, client):
        sid = _upload_sql(client)
        resp = client.post(f"/parse?session_id={sid}")
        tables = {t["name"]: t for t in resp.json()["tables"]}
        assert "customers" in tables
        assert tables["customers"]["column_count"] > 0
        assert "customer_id" in tables["customers"]["primary_keys"]

    def test_parse_all_file_types(self, client):
        sid = _upload_all(client)
        resp = client.post(f"/parse?session_id={sid}")
        body = resp.json()
        assert body["openapi_schemas"] > 0
        assert body["bdd_scenarios"] > 0
        assert len(body["tables"]) > 0

    def test_parse_invalid_session(self, client):
        resp = client.post("/parse?session_id=nonexistent")
        assert resp.status_code == 404

    def test_parse_no_files(self, client):
        # Create session manually with no files
        session = store.create()
        resp = client.post(f"/parse?session_id={session.session_id}")
        assert resp.status_code == 400

    def test_parse_generation_order(self, client):
        sid = _upload_sql(client)
        resp = client.post(f"/parse?session_id={sid}")
        order = resp.json()["generation_order"]
        # customers must come before anything that references it
        assert order.index("customers") < order.index("policies")

    def test_parse_check_constraints(self, client):
        sid = _upload_sql(client)
        resp = client.post(f"/parse?session_id={sid}")
        tables = {t["name"]: t for t in resp.json()["tables"]}
        # customers has CHECK(status IN ...)
        assert tables["customers"]["has_check_constraints"] is True


# ── POST /generate ────────────────────────────────────────────


class TestGenerate:
    def test_generate_basic(self, client):
        sid = _upload_sql(client)
        client.post(f"/parse?session_id={sid}")
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 5
        assert body["total_rows"] > 0

    def test_generate_table_info(self, client):
        sid = _upload_sql(client)
        client.post(f"/parse?session_id={sid}")
        resp = client.post(f"/generate?session_id={sid}&row_count=3")
        tables = {t["table_name"]: t for t in resp.json()["tables"]}
        assert "customers" in tables
        assert tables["customers"]["row_count"] == 3

    def test_generate_includes_validation(self, client):
        sid = _upload_sql(client)
        client.post(f"/parse?session_id={sid}")
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        body = resp.json()
        assert "validation" in body
        assert body["validation"]["total_rows"] > 0

    def test_generate_without_parse(self, client):
        sid = _upload_sql(client)
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        assert resp.status_code == 400
        assert "parse" in resp.json()["detail"].lower()

    def test_generate_invalid_session(self, client):
        resp = client.post("/generate?session_id=nope&row_count=5")
        assert resp.status_code == 404

    def test_generate_row_count_min(self, client):
        resp = client.post("/generate?session_id=x&row_count=0")
        assert resp.status_code == 422  # Pydantic validation

    def test_generate_row_count_max(self, client):
        resp = client.post("/generate?session_id=x&row_count=1000001")
        assert resp.status_code == 422

    def test_generate_creates_exports(self, client):
        """Exports are lazy — not created during generate, but on first download."""
        sid = _upload_parse_generate(client, row_count=3)
        session = store.get(sid)
        # Exports are lazy: not populated until download is requested
        assert len(session.exports) == 0
        # But data is available for lazy export
        assert session.data is not None


# ── GET /download/* ───────────────────────────────────────────


class TestDownload:
    def test_download_csv(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/download/csv?session_id={sid}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        # Verify it's a valid ZIP
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert any(n.endswith(".csv") for n in names)
        assert "_export_summary.json" in names

    def test_download_json(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/download/json?session_id={sid}")
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert any(n.endswith(".json") and not n.startswith("_") for n in names)

    def test_download_sql(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/download/sql?session_id={sid}")
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        sql_files = [n for n in zf.namelist() if n.endswith(".sql")]
        assert len(sql_files) > 0
        # Verify INSERT statements
        content = zf.read(sql_files[0]).decode()
        assert "INSERT INTO" in content

    def test_download_without_generate(self, client):
        sid = _upload_sql(client)
        client.post(f"/parse?session_id={sid}")
        resp = client.get(f"/download/csv?session_id={sid}")
        assert resp.status_code == 400

    def test_download_invalid_session(self, client):
        resp = client.get("/download/csv?session_id=nope")
        assert resp.status_code == 404

    def test_download_csv_content_parseable(self, client):
        sid = _upload_parse_generate(client, row_count=3)
        resp = client.get(f"/download/csv?session_id={sid}")
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
        content = zf.read(csv_files[0]).decode()
        import csv
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) >= 1

    def test_download_json_content_parseable(self, client):
        sid = _upload_parse_generate(client, row_count=3)
        resp = client.get(f"/download/json?session_id={sid}")
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        json_files = [n for n in zf.namelist() if n.endswith(".json") and not n.startswith("_")]
        parsed = json.loads(zf.read(json_files[0]).decode())
        assert isinstance(parsed, list)
        assert len(parsed) >= 1


# ── GET /summary ──────────────────────────────────────────────


class TestSummary:
    def test_summary_after_generate(self, client):
        sid = _upload_parse_generate(client, row_count=5)
        resp = client.get(f"/summary?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert body["tables_parsed"] > 0
        assert body["total_rows"] > 0
        assert body["row_count"] == 5
        assert body["generated_at"] is not None

    def test_summary_includes_uploads(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/summary?session_id={sid}")
        body = resp.json()
        assert len(body["uploaded_files"]) == 1
        assert body["uploaded_files"][0]["file_type"] == "sql"

    def test_summary_includes_validation(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/summary?session_id={sid}")
        body = resp.json()
        assert body["validation"] is not None
        assert "total_rows" in body["validation"]

    def test_summary_includes_download_links(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/summary?session_id={sid}")
        body = resp.json()
        exports = body["exports"]
        assert len(exports) == 3
        formats = {e["format"] for e in exports}
        assert formats == {"csv", "json", "sql"}
        for e in exports:
            assert "session_id=" in e["url"]

    def test_summary_generation_order(self, client):
        sid = _upload_parse_generate(client)
        resp = client.get(f"/summary?session_id={sid}")
        body = resp.json()
        assert len(body["generation_order"]) > 0
        assert body["generation_order"][0] == "customers"

    def test_summary_invalid_session(self, client):
        resp = client.get("/summary?session_id=nope")
        assert resp.status_code == 404

    def test_summary_before_generate(self, client):
        sid = _upload_sql(client)
        client.post(f"/parse?session_id={sid}")
        resp = client.get(f"/summary?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_rows"] == 0
        assert body["exports"] == []


# ── Full pipeline integration ─────────────────────────────────


class TestFullPipeline:
    def test_upload_parse_generate_download_summary(self, client):
        """End-to-end: upload → parse → generate → download all → summary."""
        # Upload
        sid = _upload_all(client)

        # Parse
        resp = client.post(f"/parse?session_id={sid}")
        assert resp.status_code == 200
        parse_body = resp.json()
        assert len(parse_body["tables"]) > 0
        assert parse_body["openapi_schemas"] > 0
        assert parse_body["bdd_scenarios"] > 0

        # Generate
        resp = client.post(f"/generate?session_id={sid}&row_count=5")
        assert resp.status_code == 200
        gen_body = resp.json()
        assert gen_body["total_rows"] > 0
        assert gen_body["validation"]["total_rows"] > 0

        # Download all three formats
        for fmt in ("csv", "json", "sql"):
            resp = client.get(f"/download/{fmt}?session_id={sid}")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/zip"

        # Summary
        resp = client.get(f"/summary?session_id={sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["exports"]) == 3
        assert body["generated_at"] is not None

    def test_multiple_sessions_isolated(self, client):
        """Two sessions don't interfere with each other."""
        sid1 = _upload_parse_generate(client, row_count=3)
        sid2 = _upload_parse_generate(client, row_count=7)

        r1 = client.get(f"/summary?session_id={sid1}").json()
        r2 = client.get(f"/summary?session_id={sid2}").json()

        assert r1["row_count"] == 3
        assert r2["row_count"] == 7
        assert r1["session_id"] != r2["session_id"]
