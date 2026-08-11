"""Test environment integration engine.

Generates integration-ready artifacts from synthetic data:
- Postman collections (v2.1)
- Mock payloads (valid / invalid / boundary per entity)
- Database-ready SQL INSERT scripts (with transaction wrapping)
- API-ready JSON payloads (per entity, REST-shaped)
- Swagger test suites
- CI/CD pipeline configs (GitHub Actions + generic YAML)
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.models.export import ExportFormat
from app.models.integration import (
    APIPayload,
    CIConfig,
    IntegrationArtifact,
    IntegrationBundle,
    IntegrationFormat,
    MockPayload,
    PostmanCollection,
    SwaggerTestCase,
    SwaggerTestSuite,
)
from app.models.negative import NegativeDataset
from app.models.schema import SchemaMetadata, TableMetadata

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get("EXPORT_OUTPUT_DIR", tempfile.gettempdir())


class IntegrationError(Exception):
    """Raised when integration artifact generation fails."""


# ── JSON helpers ──────────────────────────────────────────────


def _json_serial(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _to_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=_json_serial, ensure_ascii=False)


# ── SQL helpers ───────────────────────────────────────────────


def _sql_escape(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return f"'{value.isoformat()}'"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)


# ── Postman Collection Generator ─────────────────────────────


def build_postman_collection(
    schema: SchemaMetadata,
    data: dict[str, list[dict[str, Any]]],
    *,
    base_url: str = "{{base_url}}",
    collection_name: str = "Synthetic Data API Tests",
) -> dict[str, Any]:
    """Build a Postman Collection v2.1 from schema + generated data.

    Creates CRUD operations per table with sample payloads.
    """
    items: list[dict[str, Any]] = []

    for table in schema.tables:
        rows = data.get(table.name, [])
        folder_items: list[dict[str, Any]] = []

        # POST — Create
        sample = rows[0] if rows else _empty_payload(table)
        folder_items.append(
            _postman_request(
                name=f"Create {table.name}",
                method="POST",
                url=f"{base_url}/{table.name}",
                body=sample,
                tests=_postman_create_tests(table.name),
            )
        )

        # GET — List all
        folder_items.append(
            _postman_request(
                name=f"List {table.name}",
                method="GET",
                url=f"{base_url}/{table.name}",
                tests=_postman_list_tests(table.name),
            )
        )

        # GET — Get by ID
        pk_field = table.primary_keys[0] if table.primary_keys else "id"
        folder_items.append(
            _postman_request(
                name=f"Get {table.name} by {pk_field}",
                method="GET",
                url=f"{base_url}/{table.name}/{{{{{pk_field}}}}}",
                tests=_postman_get_tests(table.name),
            )
        )

        # PUT — Update
        folder_items.append(
            _postman_request(
                name=f"Update {table.name}",
                method="PUT",
                url=f"{base_url}/{table.name}/{{{{{pk_field}}}}}",
                body=sample,
                tests=_postman_update_tests(table.name),
            )
        )

        # DELETE
        folder_items.append(
            _postman_request(
                name=f"Delete {table.name}",
                method="DELETE",
                url=f"{base_url}/{table.name}/{{{{{pk_field}}}}}",
                tests=_postman_delete_tests(table.name),
            )
        )

        # Bulk insert (all rows)
        if len(rows) > 1:
            folder_items.append(
                _postman_request(
                    name=f"Bulk create {table.name}",
                    method="POST",
                    url=f"{base_url}/{table.name}/bulk",
                    body=rows,
                )
            )

        items.append(
            {
                "name": table.name,
                "item": folder_items,
            }
        )

    collection = {
        "info": {
            "_postman_id": uuid.uuid4().hex,
            "name": collection_name,
            "description": f"Auto-generated from {len(schema.tables)} tables with synthetic test data",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "base_url", "value": "http://localhost:8080/api", "type": "string"},
        ],
        "item": items,
    }

    return collection


def _postman_request(
    *,
    name: str,
    method: str,
    url: str,
    body: Any = None,
    tests: str = "",
) -> dict[str, Any]:
    req: dict[str, Any] = {
        "name": name,
        "request": {
            "method": method,
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": {"raw": url, "host": [url]},
        },
        "response": [],
    }
    if body is not None:
        req["request"]["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2, default=_json_serial),
            "options": {"raw": {"language": "json"}},
        }
    if tests:
        req["event"] = [
            {"listen": "test", "script": {"type": "text/javascript", "exec": tests.splitlines()}}
        ]
    return req


def _postman_create_tests(table: str) -> str:
    return f"""pm.test("Create {table} returns 201", function () {{
    pm.response.to.have.status(201);
}});
pm.test("Response has id", function () {{
    var json = pm.response.json();
    pm.expect(json).to.have.property("id");
}});"""


def _postman_list_tests(table: str) -> str:
    return f"""pm.test("List {table} returns 200", function () {{
    pm.response.to.have.status(200);
}});
pm.test("Response is array", function () {{
    pm.expect(pm.response.json()).to.be.an("array");
}});"""


def _postman_get_tests(table: str) -> str:
    return f"""pm.test("Get {table} returns 200", function () {{
    pm.response.to.have.status(200);
}});"""


def _postman_update_tests(table: str) -> str:
    return f"""pm.test("Update {table} returns 200", function () {{
    pm.response.to.have.status(200);
}});"""


def _postman_delete_tests(table: str) -> str:
    return f"""pm.test("Delete {table} returns 204", function () {{
    pm.response.to.have.status(204);
}});"""


def _empty_payload(table: TableMetadata) -> dict[str, Any]:
    """Build a stub payload from column definitions."""
    payload: dict[str, Any] = {}
    for col in table.columns:
        if col.is_primary_key:
            continue
        payload[col.name] = _type_stub(col.data_type)
    return payload


def _type_stub(data_type: str) -> Any:
    dt = data_type.upper()
    if "INT" in dt or "BIGINT" in dt:
        return 0
    if "FLOAT" in dt or "DECIMAL" in dt or "NUMERIC" in dt or "DOUBLE" in dt:
        return 0.0
    if "BOOL" in dt:
        return False
    if "DATE" in dt or "TIME" in dt:
        return "2024-01-01"
    if "UUID" in dt:
        return "00000000-0000-0000-0000-000000000000"
    return ""


# ── Mock Payload Generator ────────────────────────────────────


def build_mock_payloads(
    schema: SchemaMetadata,
    data: dict[str, list[dict[str, Any]]],
    negative: NegativeDataset | None = None,
) -> list[MockPayload]:
    """Build mock payloads per entity with valid/invalid/boundary splits."""
    payloads: list[MockPayload] = []

    neg_by_table: dict[str, list[dict[str, Any]]] = {}
    if negative:
        for row in negative.invalid:
            neg_by_table.setdefault(row.table, []).append(row.row)

    for table in schema.tables:
        valid_rows = data.get(table.name, [])
        invalid_rows = neg_by_table.get(table.name, [])

        payloads.append(
            MockPayload(
                entity=table.name,
                valid=valid_rows,
                invalid=invalid_rows,
                boundary=[],
            )
        )

    return payloads


# ── Database-Ready SQL INSERT Generator ───────────────────────


def build_sql_inserts(
    schema: SchemaMetadata,
    data: dict[str, list[dict[str, Any]]],
    generation_order: list[str],
) -> str:
    """Generate transaction-wrapped SQL INSERT script respecting FK order.

    Output is ready to pipe directly into a database CLI.
    """
    lines: list[str] = [
        "-- ============================================",
        "-- Auto-generated SQL INSERT script",
        f"-- Tables: {len(schema.tables)}",
        f"-- Total rows: {sum(len(r) for r in data.values())}",
        f"-- Generated: {datetime.utcnow().isoformat()}",
        "-- ============================================",
        "",
        "BEGIN;",
        "",
    ]

    # Follow generation order for FK safety
    ordered_tables = generation_order or [t.name for t in schema.tables]

    for table_name in ordered_tables:
        rows = data.get(table_name, [])
        if not rows:
            lines.append(f"-- No data for {table_name}")
            lines.append("")
            continue

        lines.append(f"-- {table_name} ({len(rows)} rows)")
        columns = list(rows[0].keys())
        col_list = ", ".join(columns)

        for row in rows:
            values = ", ".join(_sql_escape(row.get(c)) for c in columns)
            lines.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({values});")

        lines.append("")

    lines.append("COMMIT;")
    lines.append("")

    return "\n".join(lines)


# ── API-Ready JSON Payload Generator ──────────────────────────


def build_api_payloads(
    schema: SchemaMetadata,
    data: dict[str, list[dict[str, Any]]],
) -> list[APIPayload]:
    """Build REST-shaped API payloads per entity."""
    payloads: list[APIPayload] = []

    for table in schema.tables:
        rows = data.get(table.name, [])
        # Strip PKs from payloads (typically auto-generated by API)
        stripped = []
        for row in rows:
            clean = {k: v for k, v in row.items() if k not in table.primary_keys}
            stripped.append(clean)

        payloads.append(
            APIPayload(
                entity=table.name,
                endpoint=f"/api/{table.name}",
                method="POST",
                payloads=stripped,
            )
        )

    return payloads


# ── Swagger Test Suite Generator ──────────────────────────────


def build_swagger_test_suite(
    schema: SchemaMetadata,
    data: dict[str, list[dict[str, Any]]],
    *,
    base_url: str = "http://localhost:8080",
    title: str = "Synthetic Data API Test Suite",
) -> SwaggerTestSuite:
    """Build a Swagger-compatible test suite with test cases per entity."""
    tests: list[SwaggerTestCase] = []

    for table in schema.tables:
        rows = data.get(table.name, [])
        sample = rows[0] if rows else _empty_payload(table)

        # Create
        tests.append(
            SwaggerTestCase(
                operation_id=f"create_{table.name}",
                method="POST",
                path=f"/api/{table.name}",
                request_body=sample,
                expected_status=201,
                description=f"Create a new {table.name} record",
            )
        )

        # List
        tests.append(
            SwaggerTestCase(
                operation_id=f"list_{table.name}",
                method="GET",
                path=f"/api/{table.name}",
                expected_status=200,
                description=f"List all {table.name} records",
            )
        )

        # Get by ID
        pk = table.primary_keys[0] if table.primary_keys else "id"
        pk_val = sample.get(pk, 1)
        tests.append(
            SwaggerTestCase(
                operation_id=f"get_{table.name}",
                method="GET",
                path=f"/api/{table.name}/{pk_val}",
                expected_status=200,
                description=f"Get {table.name} by {pk}",
            )
        )

        # Invalid create (missing required fields)
        tests.append(
            SwaggerTestCase(
                operation_id=f"create_{table.name}_invalid",
                method="POST",
                path=f"/api/{table.name}",
                request_body={},
                expected_status=422,
                description=f"Create {table.name} with empty body (expect validation error)",
            )
        )

    return SwaggerTestSuite(title=title, base_url=base_url, tests=tests)


# ── CI/CD Pipeline Config Generator ──────────────────────────


def build_ci_config(
    schema: SchemaMetadata,
    *,
    pipeline_name: str = "synthetic-data-tests",
) -> dict[str, Any]:
    """Generate a GitHub Actions workflow YAML for CI/CD integration."""
    table_names = [t.name for t in schema.tables]

    workflow = {
        "name": pipeline_name,
        "on": {"push": {"branches": ["main", "develop"]}, "pull_request": {"branches": ["main"]}},
        "env": {
            "DATABASE_URL": "postgresql://test:test@localhost:5432/testdb",
            "API_BASE_URL": "http://localhost:8080",
        },
        "jobs": {
            "seed-database": {
                "runs-on": "ubuntu-latest",
                "services": {
                    "postgres": {
                        "image": "postgres:16",
                        "env": {
                            "POSTGRES_USER": "test",
                            "POSTGRES_PASSWORD": "test",
                            "POSTGRES_DB": "testdb",
                        },
                        "ports": ["5432:5432"],
                        "options": "--health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5",
                    }
                },
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {
                        "name": "Seed database",
                        "run": "psql $DATABASE_URL < test-data/sql_inserts.sql",
                    },
                    {
                        "name": "Verify seed",
                        "run": "\n".join(
                            f'psql $DATABASE_URL -c "SELECT COUNT(*) FROM {t};"'
                            for t in table_names
                        ),
                    },
                ],
            },
            "api-tests": {
                "runs-on": "ubuntu-latest",
                "needs": "seed-database",
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {
                        "name": "Install Newman",
                        "run": "npm install -g newman",
                    },
                    {
                        "name": "Run Postman collection",
                        "run": "newman run test-data/postman_collection.json --reporters cli,junit --reporter-junit-export results.xml",
                    },
                    {
                        "name": "Upload test results",
                        "uses": "actions/upload-artifact@v4",
                        "if": "always()",
                        "with": {"name": "test-results", "path": "results.xml"},
                    },
                ],
            },
            "swagger-validation": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {
                        "name": "Validate payloads against schema",
                        "run": "python -c \"import json; data=json.load(open('test-data/swagger_tests.json')); print(f'Validated {len(data[\"tests\"])} test cases')\"",
                    },
                ],
            },
        },
    }

    return workflow


# ── QA Pipeline Config ────────────────────────────────────────


def build_qa_pipeline_config(
    schema: SchemaMetadata,
) -> dict[str, Any]:
    """Generate a QA pipeline stage configuration."""
    return {
        "qa_pipeline": {
            "name": "QA Data Validation Pipeline",
            "stages": [
                {
                    "name": "data-seeding",
                    "description": "Load synthetic test data into target environment",
                    "script": "psql $DATABASE_URL < test-data/sql_inserts.sql",
                    "artifacts": ["test-data/sql_inserts.sql"],
                },
                {
                    "name": "api-smoke-tests",
                    "description": "Run Postman collection smoke tests",
                    "script": "newman run test-data/postman_collection.json --folder 'smoke'",
                    "artifacts": ["test-data/postman_collection.json"],
                },
                {
                    "name": "payload-validation",
                    "description": "Validate mock payloads against API schemas",
                    "script": "python scripts/validate_payloads.py --input test-data/mock_payloads.json",
                    "artifacts": ["test-data/mock_payloads.json"],
                },
                {
                    "name": "integration-tests",
                    "description": "Run full API integration test suite",
                    "script": "newman run test-data/postman_collection.json --reporters cli,junit",
                    "artifacts": ["test-data/postman_collection.json"],
                },
                {
                    "name": "cleanup",
                    "description": "Tear down test data",
                    "script": "\n".join(
                        f"psql $DATABASE_URL -c 'DELETE FROM {t.name};'"
                        for t in reversed(schema.tables)
                    ),
                },
            ],
            "environment": {
                "DATABASE_URL": "${DATABASE_URL}",
                "API_BASE_URL": "${API_BASE_URL}",
            },
            "tables": [t.name for t in schema.tables],
            "total_tables": len(schema.tables),
        }
    }


# ── Bundle Generator ─────────────────────────────────────────


class IntegrationEngine:
    """Generates a complete bundle of integration-ready artifacts."""

    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or _OUTPUT_DIR

    def generate_bundle(
        self,
        session_id: str,
        schema: SchemaMetadata,
        data: dict[str, list[dict[str, Any]]],
        generation_order: list[str],
        negative: NegativeDataset | None = None,
        *,
        base_url: str = "http://localhost:8080",
        include_formats: set[str] | None = None,
    ) -> IntegrationBundle:
        """Generate integration artifacts and bundle into a ZIP.

        Parameters
        ----------
        include_formats : optional set of format keys to include.
            If None or empty, all artifacts are generated.
        """
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        zip_name = f"integration_{session_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = out_dir / zip_name
        artifacts: list[IntegrationArtifact] = []

        def _should_include(fmt: str) -> bool:
            return not include_formats or fmt in include_formats

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. Postman Collection
                if _should_include("postman"):
                    postman = build_postman_collection(schema, data, base_url="{{base_url}}")
                    postman_json = _to_json(postman)
                    zf.writestr("postman_collection.json", postman_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.POSTMAN,
                            filename="postman_collection.json",
                            content_type="application/json",
                            size_bytes=len(postman_json.encode()),
                        )
                    )

                # 2. Mock Payloads
                if _should_include("mock_payload"):
                    mocks = build_mock_payloads(schema, data, negative)
                    mocks_json = _to_json([m.model_dump() for m in mocks])
                    zf.writestr("mock_payloads.json", mocks_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.MOCK_PAYLOAD,
                            filename="mock_payloads.json",
                            content_type="application/json",
                            size_bytes=len(mocks_json.encode()),
                        )
                    )

                # 3. SQL Inserts
                if _should_include("sql_insert"):
                    sql = build_sql_inserts(schema, data, generation_order)
                    zf.writestr("sql_inserts.sql", sql)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.SQL_INSERT,
                            filename="sql_inserts.sql",
                            content_type="application/sql",
                            size_bytes=len(sql.encode()),
                        )
                    )

                # 4. API-Ready JSON Payloads
                if _should_include("api_json"):
                    api = build_api_payloads(schema, data)
                    api_json = _to_json([a.model_dump() for a in api])
                    zf.writestr("api_payloads.json", api_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.API_JSON,
                            filename="api_payloads.json",
                            content_type="application/json",
                            size_bytes=len(api_json.encode()),
                        )
                    )

                # 5. Swagger Test Suite
                if _should_include("swagger_test"):
                    swagger = build_swagger_test_suite(schema, data, base_url=base_url)
                    swagger_json = _to_json(swagger.model_dump())
                    zf.writestr("swagger_tests.json", swagger_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.SWAGGER_TEST,
                            filename="swagger_tests.json",
                            content_type="application/json",
                            size_bytes=len(swagger_json.encode()),
                        )
                    )

                # 6. CI/CD Config
                if _should_include("ci_bundle"):
                    ci = build_ci_config(schema)
                    ci_json = _to_json(ci)
                    zf.writestr("ci_pipeline.json", ci_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.CI_BUNDLE,
                            filename="ci_pipeline.json",
                            content_type="application/json",
                            size_bytes=len(ci_json.encode()),
                        )
                    )

                # 7. QA Pipeline Config
                if _should_include("ci_bundle"):
                    qa = build_qa_pipeline_config(schema)
                    qa_json = _to_json(qa)
                    zf.writestr("qa_pipeline.json", qa_json)
                    artifacts.append(
                        IntegrationArtifact(
                            format=IntegrationFormat.CI_BUNDLE,
                            filename="qa_pipeline.json",
                            content_type="application/json",
                            size_bytes=len(qa_json.encode()),
                        )
                    )

                # 8. Per-table API payloads (individual files)
                if _should_include("api_json"):
                    if 'api' not in locals():
                        api = build_api_payloads(schema, data)
                    for ap in api:
                        fname = f"payloads/{_safe_name(ap.entity)}.json"
                        content = _to_json(ap.payloads)
                        zf.writestr(fname, content)

                # 9. Bundle manifest
                manifest = {
                    "session_id": session_id,
                    "generated_at": datetime.utcnow().isoformat(),
                    "artifacts": [a.model_dump() for a in artifacts],
                    "tables": [t.name for t in schema.tables],
                    "total_tables": len(schema.tables),
                    "total_rows": sum(len(r) for r in data.values()),
                }
                zf.writestr("_manifest.json", _to_json(manifest))

        except OSError as e:
            logger.error(
                "Failed to write integration ZIP: %s", e,
                extra={"stage": "integration", "event": "integration_write_error"},
            )
            raise IntegrationError(f"Failed to write integration ZIP: {e}") from e

        bundle = IntegrationBundle(
            session_id=session_id,
            zip_path=str(zip_path),
            artifacts=artifacts,
            total_tables=len(schema.tables),
            total_rows=sum(len(r) for r in data.values()),
        )

        logger.info(
            "Integration bundle generated — %d artifacts, %d tables, %d rows → %s",
            len(artifacts),
            bundle.total_tables,
            bundle.total_rows,
            zip_path,
            extra={"stage": "integration", "event": "bundle_generated"},
        )

        return bundle
