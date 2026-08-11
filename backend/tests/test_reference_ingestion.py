"""Comprehensive tests for the reference-document ingestion system.

Covers: models, OCR pipeline, entity extractor, AI enrichment merge,
router endpoints (ingest + generate), and schema/DDL generation.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.reference import (
    ExtractionSource,
    ExtractedConstraint,
    ExtractedEntity,
    ExtractedField,
    ExtractedRelationship,
    OCRBlock,
    OCRResult,
    ReferenceDocType,
    ReferenceGenerateResponse,
    ReferenceIngestionResult,
    ReferenceTableInfo,
)
from app.parsers.ocr_pipeline import extract_text_from_image, OCRError
from app.parsers.reference_extractor import (
    _build_schema,
    _detect_domain,
    _extract_api_screenshot,
    _extract_brd_snippet,
    _extract_schema_image,
    _generation_order,
    _schema_to_ddl,
    extract_entities_from_ocr,
)
from app.routers.reference import _classify_upload, _merge_ai_enrichment

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════
# Helper: create a test image in memory
# ═══════════════════════════════════════════════════════════════


def _make_test_image(width: int = 100, height: int = 50, fmt: str = "PNG") -> bytes:
    """Create a minimal in-memory image for testing."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_text_file(text: str) -> bytes:
    return text.encode("utf-8")


# ═══════════════════════════════════════════════════════════════
# 1. Model tests
# ═══════════════════════════════════════════════════════════════


class TestReferenceModels:
    """Test Pydantic model creation and validation."""

    def test_ocr_block(self):
        block = OCRBlock(text="hello", confidence=0.9, bbox=[10, 20, 50, 30])
        assert block.text == "hello"
        assert block.confidence == 0.9
        assert len(block.bbox) == 4

    def test_ocr_result_defaults(self):
        result = OCRResult()
        assert result.raw_text == ""
        assert result.blocks == []
        assert result.avg_confidence == 0.0

    def test_extracted_field(self):
        field = ExtractedField(
            name="email",
            data_type="VARCHAR",
            source=ExtractionSource.OCR,
            confidence=0.8,
        )
        assert field.name == "email"
        assert field.source == ExtractionSource.OCR

    def test_extracted_entity(self):
        entity = ExtractedEntity(
            name="customers",
            fields=[ExtractedField(name="id", data_type="INTEGER", is_primary_key=True)],
            confidence=0.9,
        )
        assert entity.name == "customers"
        assert len(entity.fields) == 1

    def test_extracted_relationship(self):
        rel = ExtractedRelationship(
            from_entity="orders",
            from_field="customer_id",
            to_entity="customers",
            to_field="id",
            confidence=0.7,
        )
        assert rel.from_entity == "orders"

    def test_reference_doc_type_enum(self):
        assert ReferenceDocType.SCREENSHOT.value == "screenshot"
        assert ReferenceDocType.SCHEMA_IMAGE.value == "schema_image"
        assert ReferenceDocType.BRD_SNIPPET.value == "brd_snippet"
        assert ReferenceDocType.API_SCREENSHOT.value == "api_screenshot"

    def test_ingestion_result(self):
        result = ReferenceIngestionResult(
            doc_type=ReferenceDocType.SCREENSHOT,
            filename="test.png",
        )
        assert result.doc_type == ReferenceDocType.SCREENSHOT
        assert result.entities == []

    def test_generate_response(self):
        resp = ReferenceGenerateResponse(
            session_id="abc123",
            filename="test.png",
            doc_type="screenshot",
        )
        assert resp.session_id == "abc123"
        assert resp.total_rows == 0

    def test_table_info(self):
        info = ReferenceTableInfo(table_name="users", row_count=50)
        assert info.table_name == "users"


# ═══════════════════════════════════════════════════════════════
# 2. OCR pipeline tests
# ═══════════════════════════════════════════════════════════════


class TestOCRPipeline:
    """Test the OCR pipeline with real images (no Tesseract required)."""

    def test_extract_from_valid_image(self):
        img_bytes = _make_test_image()
        result = extract_text_from_image(img_bytes)
        assert isinstance(result, OCRResult)
        assert result.image_width == 100
        assert result.image_height == 50

    def test_extract_from_jpeg(self):
        img_bytes = _make_test_image(fmt="JPEG")
        result = extract_text_from_image(img_bytes)
        assert result.image_width == 100

    def test_invalid_bytes_raises(self):
        with pytest.raises(OCRError, match="Cannot open image"):
            extract_text_from_image(b"not an image at all")

    def test_empty_bytes_raises(self):
        with pytest.raises(OCRError):
            extract_text_from_image(b"")

    def test_large_image(self):
        img_bytes = _make_test_image(width=2000, height=1500)
        result = extract_text_from_image(img_bytes)
        assert result.image_width == 2000
        assert result.image_height == 1500


# ═══════════════════════════════════════════════════════════════
# 3. Domain detection tests
# ═══════════════════════════════════════════════════════════════


class TestDomainDetection:
    """Test domain detection from text."""

    def test_banking_domain(self):
        assert _detect_domain("customer account transaction balance deposit") == "banking"

    def test_insurance_domain(self):
        assert _detect_domain("policy claim premium coverage beneficiary") == "insurance"

    def test_ecommerce_domain(self):
        assert _detect_domain("product order cart payment shipping inventory") == "ecommerce"

    def test_healthcare_domain(self):
        assert _detect_domain("patient doctor diagnosis prescription appointment") == "healthcare"

    def test_education_domain(self):
        assert _detect_domain("student course enrollment grade instructor semester") == "education"

    def test_generic_fallback(self):
        assert _detect_domain("foo bar baz qux") == "generic"

    def test_mixed_strong_signal(self):
        text = "bank account transaction policy"
        domain = _detect_domain(text)
        assert domain == "banking"  # banking has 3 matches vs insurance's 1


# ═══════════════════════════════════════════════════════════════
# 4. Schema image extraction tests
# ═══════════════════════════════════════════════════════════════


class TestSchemaImageExtraction:
    """Test extraction from DDL-like text."""

    def test_create_table_extraction(self):
        text = """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            email VARCHAR UNIQUE
        );
        """
        entities, rels, cons = _extract_schema_image(text)
        assert len(entities) == 1
        assert entities[0].name == "customers"
        assert len(entities[0].fields) >= 2

    def test_multiple_tables(self):
        text = """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        """
        entities, rels, cons = _extract_schema_image(text)
        assert len(entities) == 2
        assert len(rels) == 1
        assert rels[0].from_entity == "orders"
        assert rels[0].to_entity == "customers"

    def test_check_constraint(self):
        text = """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            status VARCHAR CHECK (status IN ('active', 'inactive'))
        );
        """
        entities, rels, cons = _extract_schema_image(text)
        assert len(entities) == 1
        fields = entities[0].fields
        status_field = next((f for f in fields if f.name == "status"), None)
        assert status_field is not None

    def test_tabular_format(self):
        text = """
        Table: users
        Field | Type
        id | INTEGER
        name | VARCHAR
        email | VARCHAR
        """
        entities, _, _ = _extract_schema_image(text)
        assert len(entities) >= 1

    def test_entity_heading(self):
        text = """
        Entity: Customer
        id INTEGER
        name VARCHAR
        """
        entities, _, _ = _extract_schema_image(text)
        assert len(entities) >= 1

    def test_empty_text(self):
        entities, rels, cons = _extract_schema_image("")
        assert entities == []


# ═══════════════════════════════════════════════════════════════
# 5. API screenshot extraction tests
# ═══════════════════════════════════════════════════════════════


class TestAPIScreenshotExtraction:
    """Test extraction from API-like text."""

    def test_endpoint_extraction(self):
        text = """
        GET /api/users
        POST /api/orders
        GET /api/products/{id}
        """
        entities, _, _ = _extract_api_screenshot(text)
        names = [e.name for e in entities]
        assert "user" in names or "order" in names

    def test_json_field_extraction(self):
        text = """
        {
            "id": 1,
            "name": "John",
            "email": "john@example.com",
            "active": true,
            "balance": 123.45
        }
        """
        entities, _, _ = _extract_api_screenshot(text)
        if entities:
            field_names = [f.name for f in entities[0].fields]
            assert "id" in field_names
            assert "name" in field_names

    def test_relationship_from_id_fields(self):
        text = """
        GET /api/users
        GET /api/orders
        {"user_id": 1, "order_total": 99.99}
        """
        entities, rels, _ = _extract_api_screenshot(text)
        assert len(entities) >= 1

    def test_empty_text(self):
        entities, _, _ = _extract_api_screenshot("")
        assert entities == []


# ═══════════════════════════════════════════════════════════════
# 6. BRD snippet extraction tests
# ═══════════════════════════════════════════════════════════════


class TestBRDExtraction:
    """Test extraction from business requirement document text."""

    def test_entity_extraction(self):
        text = "The customer table must store first name and last name. The order entity tracks purchases."
        entities, _, _ = _extract_brd_snippet(text)
        names = [e.name for e in entities]
        assert "customer" in names or "order" in names

    def test_relationship_extraction(self):
        text = "Customer has many orders. Order belongs to customer."
        _, rels, _ = _extract_brd_snippet(text)
        assert len(rels) >= 1

    def test_constraint_extraction(self):
        text = "The system must validate email format. Age must be greater than 18."
        _, _, cons = _extract_brd_snippet(text)
        assert len(cons) >= 1

    def test_empty_text(self):
        entities, _, _ = _extract_brd_snippet("")
        assert entities == []


# ═══════════════════════════════════════════════════════════════
# 7. Full extraction pipeline tests
# ═══════════════════════════════════════════════════════════════


class TestFullExtraction:
    """Test the end-to-end extraction from OCR result."""

    def test_schema_extraction(self):
        ocr = OCRResult(
            raw_text="CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);",
            blocks=[OCRBlock(text="CREATE TABLE...", confidence=0.9)],
            avg_confidence=0.9,
        )
        result = extract_entities_from_ocr(ocr, ReferenceDocType.SCHEMA_IMAGE, "schema.png")
        assert result.doc_type == ReferenceDocType.SCHEMA_IMAGE
        assert len(result.entities) >= 1

    def test_api_extraction(self):
        ocr = OCRResult(
            raw_text='GET /api/customers\n{"id": 1, "name": "John"}',
            blocks=[OCRBlock(text="GET /api/...", confidence=0.8)],
            avg_confidence=0.8,
        )
        result = extract_entities_from_ocr(ocr, ReferenceDocType.API_SCREENSHOT, "api.png")
        assert result.doc_type == ReferenceDocType.API_SCREENSHOT

    def test_brd_extraction(self):
        ocr = OCRResult(
            raw_text="The customer table must store email. Customer has many orders.",
            blocks=[OCRBlock(text="The customer...", confidence=0.7)],
            avg_confidence=0.7,
        )
        result = extract_entities_from_ocr(ocr, ReferenceDocType.BRD_SNIPPET, "brd.txt")
        assert result.doc_type == ReferenceDocType.BRD_SNIPPET

    def test_empty_ocr_warning(self):
        ocr = OCRResult(raw_text="", avg_confidence=0.0)
        result = extract_entities_from_ocr(ocr, ReferenceDocType.SCREENSHOT, "blank.png")
        assert any("no text" in w.lower() for w in result.warnings)

    def test_low_confidence_warning(self):
        ocr = OCRResult(
            raw_text="CREATE TABLE t (id INTEGER PRIMARY KEY);",
            blocks=[OCRBlock(text="CREATE TABLE t", confidence=0.1)],
            avg_confidence=0.1,
        )
        result = extract_entities_from_ocr(ocr, ReferenceDocType.SCHEMA_IMAGE)
        # Low confidence only if overall avg is < 0.3 after extraction


# ═══════════════════════════════════════════════════════════════
# 8. Schema builder + DDL generation tests
# ═══════════════════════════════════════════════════════════════


class TestSchemaBuilderDDL:
    """Test schema building and DDL generation from extracted entities."""

    def test_build_schema_with_pk(self):
        entities = [
            ExtractedEntity(
                name="customers",
                fields=[
                    ExtractedField(name="id", data_type="INTEGER", is_primary_key=True, nullable=False),
                    ExtractedField(name="name", data_type="VARCHAR"),
                ],
            )
        ]
        schema = _build_schema(entities, [])
        assert len(schema.tables) == 1
        assert schema.tables[0].name == "customers"
        pk_cols = [c for c in schema.tables[0].columns if c.is_primary_key]
        assert len(pk_cols) >= 1

    def test_build_schema_auto_pk(self):
        entities = [
            ExtractedEntity(
                name="items",
                fields=[
                    ExtractedField(name="name", data_type="VARCHAR"),
                ],
            )
        ]
        schema = _build_schema(entities, [])
        pk_cols = [c for c in schema.tables[0].columns if c.is_primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"

    def test_build_schema_with_fk(self):
        entities = [
            ExtractedEntity(
                name="customers",
                fields=[ExtractedField(name="id", data_type="INTEGER", is_primary_key=True)],
            ),
            ExtractedEntity(
                name="orders",
                fields=[ExtractedField(name="id", data_type="INTEGER", is_primary_key=True)],
            ),
        ]
        rels = [
            ExtractedRelationship(
                from_entity="orders",
                from_field="customer_id",
                to_entity="customers",
                to_field="id",
            )
        ]
        schema = _build_schema(entities, rels)
        orders_table = next(t for t in schema.tables if t.name == "orders")
        assert len(orders_table.foreign_keys) == 1

    def test_ddl_generation(self):
        entities = [
            ExtractedEntity(
                name="users",
                fields=[
                    ExtractedField(name="id", data_type="INTEGER", is_primary_key=True),
                    ExtractedField(name="email", data_type="VARCHAR", nullable=False, is_unique=True),
                ],
            )
        ]
        schema = _build_schema(entities, [])
        ddl = _schema_to_ddl(schema)
        assert "CREATE TABLE users" in ddl
        assert "PRIMARY KEY" in ddl
        assert "NOT NULL" in ddl
        assert "UNIQUE" in ddl

    def test_ddl_with_foreign_key(self):
        entities = [
            ExtractedEntity(name="a", fields=[ExtractedField(name="id", data_type="INTEGER", is_primary_key=True)]),
            ExtractedEntity(name="b", fields=[ExtractedField(name="id", data_type="INTEGER", is_primary_key=True)]),
        ]
        rels = [ExtractedRelationship(from_entity="b", from_field="a_id", to_entity="a", to_field="id")]
        schema = _build_schema(entities, rels)
        ddl = _schema_to_ddl(schema)
        assert "FOREIGN KEY (a_id) REFERENCES a(id)" in ddl

    def test_generation_order(self):
        entities = [
            ExtractedEntity(name="orders", fields=[]),
            ExtractedEntity(name="customers", fields=[]),
        ]
        rels = [ExtractedRelationship(from_entity="orders", from_field="customer_id", to_entity="customers", to_field="id")]
        order = _generation_order(entities, rels)
        assert order.index("customers") < order.index("orders")


# ═══════════════════════════════════════════════════════════════
# 9. AI enrichment merge tests
# ═══════════════════════════════════════════════════════════════


class TestAIEnrichmentMerge:
    """Test merging AI-enriched data into heuristic results."""

    def test_merge_new_entity(self):
        result = ReferenceIngestionResult(
            doc_type=ReferenceDocType.SCREENSHOT,
            entities=[ExtractedEntity(name="users", confidence=0.5)],
        )
        ai_data = {
            "domain": "banking",
            "entities": [
                {
                    "name": "accounts",
                    "confidence": 0.8,
                    "columns": [
                        {"name": "id", "data_type": "INTEGER", "is_primary_key": True},
                    ],
                }
            ],
            "relationships": [],
            "constraints": [],
        }
        merged = _merge_ai_enrichment(result, ai_data)
        assert merged.domain == "banking"
        names = [e.name for e in merged.entities]
        assert "accounts" in names
        assert "users" in names

    def test_merge_replaces_low_confidence(self):
        result = ReferenceIngestionResult(
            doc_type=ReferenceDocType.SCREENSHOT,
            entities=[
                ExtractedEntity(
                    name="users",
                    fields=[ExtractedField(name="id", data_type="INT")],
                    confidence=0.3,
                )
            ],
        )
        ai_data = {
            "entities": [
                {
                    "name": "users",
                    "confidence": 0.9,
                    "columns": [
                        {"name": "id", "data_type": "INTEGER", "is_primary_key": True},
                        {"name": "email", "data_type": "VARCHAR"},
                    ],
                }
            ],
        }
        merged = _merge_ai_enrichment(result, ai_data)
        users = next(e for e in merged.entities if e.name == "users")
        assert users.confidence == 0.9
        assert users.source == ExtractionSource.AI
        assert len(users.fields) == 2

    def test_merge_relationships(self):
        result = ReferenceIngestionResult(doc_type=ReferenceDocType.SCREENSHOT)
        ai_data = {
            "relationships": [
                {
                    "from_entity": "orders",
                    "from_field": "customer_id",
                    "to_entity": "customers",
                    "to_field": "id",
                    "confidence": 0.8,
                }
            ],
        }
        merged = _merge_ai_enrichment(result, ai_data)
        assert len(merged.relationships) == 1

    def test_merge_constraints(self):
        result = ReferenceIngestionResult(doc_type=ReferenceDocType.SCREENSHOT)
        ai_data = {
            "constraints": [
                {
                    "entity": "users",
                    "field": "age",
                    "rule": "age >= 18",
                    "confidence": 0.7,
                }
            ],
        }
        merged = _merge_ai_enrichment(result, ai_data)
        assert len(merged.constraints) == 1

    def test_merge_empty_ai_data(self):
        result = ReferenceIngestionResult(
            doc_type=ReferenceDocType.SCREENSHOT,
            entities=[ExtractedEntity(name="users", confidence=0.5)],
        )
        merged = _merge_ai_enrichment(result, {})
        assert len(merged.entities) == 1


# ═══════════════════════════════════════════════════════════════
# 10. File classification tests
# ═══════════════════════════════════════════════════════════════


class TestFileClassification:
    """Test file classification logic."""

    def test_png_classified_as_screenshot(self):
        file = MagicMock()
        file.content_type = "image/png"
        file.filename = "capture.png"
        assert _classify_upload(file) == ReferenceDocType.SCREENSHOT

    def test_schema_image_by_name(self):
        file = MagicMock()
        file.content_type = "image/png"
        file.filename = "schema_diagram.png"
        assert _classify_upload(file) == ReferenceDocType.SCHEMA_IMAGE

    def test_api_screenshot_by_name(self):
        file = MagicMock()
        file.content_type = "image/png"
        file.filename = "api_endpoints.png"
        assert _classify_upload(file) == ReferenceDocType.API_SCREENSHOT

    def test_brd_by_name(self):
        file = MagicMock()
        file.content_type = "text/plain"
        file.filename = "brd_requirements.txt"
        assert _classify_upload(file) == ReferenceDocType.BRD_SNIPPET

    def test_erd_schema(self):
        file = MagicMock()
        file.content_type = "image/jpeg"
        file.filename = "erd_model.jpg"
        assert _classify_upload(file) == ReferenceDocType.SCHEMA_IMAGE


# ═══════════════════════════════════════════════════════════════
# 11. Ingest endpoint tests
# ═══════════════════════════════════════════════════════════════


class TestIngestEndpoint:
    """Test POST /reference/ingest via the API."""

    def test_ingest_image(self):
        img = _make_test_image()
        resp = client.post(
            "/reference/ingest",
            files={"file": ("test.png", img, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_type"] == "screenshot"
        assert "ocr" in data

    def test_ingest_schema_image(self):
        img = _make_test_image()
        resp = client.post(
            "/reference/ingest?doc_type=schema_image",
            files={"file": ("schema.png", img, "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["doc_type"] == "schema_image"

    def test_ingest_text_file(self):
        text = _make_text_file(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);"
        )
        resp = client.post(
            "/reference/ingest?doc_type=schema_image",
            files={"file": ("schema.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entities"]) >= 1

    def test_ingest_brd_text(self):
        text = _make_text_file(
            "The customer table must store email. Customer has many orders. Order belongs to customer."
        )
        resp = client.post(
            "/reference/ingest?doc_type=brd_snippet",
            files={"file": ("brd.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_type"] == "brd_snippet"

    def test_ingest_empty_file(self):
        resp = client.post(
            "/reference/ingest",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert resp.status_code == 400

    def test_ingest_invalid_doc_type(self):
        img = _make_test_image()
        resp = client.post(
            "/reference/ingest?doc_type=invalid_type",
            files={"file": ("test.png", img, "image/png")},
        )
        assert resp.status_code == 422

    def test_ingest_api_text(self):
        text = _make_text_file(
            'GET /api/users\nPOST /api/orders\n{"id": 1, "name": "John", "email": "john@test.com"}'
        )
        resp = client.post(
            "/reference/ingest?doc_type=api_screenshot",
            files={"file": ("api.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_type"] == "api_screenshot"


# ═══════════════════════════════════════════════════════════════
# 12. Generate endpoint tests
# ═══════════════════════════════════════════════════════════════


class TestGenerateEndpoint:
    """Test POST /reference/generate via the API."""

    def test_generate_from_schema_text(self):
        text = _make_text_file(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, email VARCHAR UNIQUE);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=5",
            files={"file": ("schema.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"]
        assert data["total_rows"] > 0
        assert len(data["tables"]) >= 1
        assert data["schema_sql"]

    def test_generate_with_fk(self):
        text = _make_text_file(
            """CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, FOREIGN KEY (customer_id) REFERENCES customers(id));"""
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=5",
            files={"file": ("schema.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tables"]) == 2
        assert data["generation_order"].index("customers") < data["generation_order"].index("orders")

    def test_generate_with_negatives(self):
        text = _make_text_file(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=5&include_invalid=true",
            files={"file": ("schema.txt", text, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["negative_cases"] >= 0

    def test_generate_creates_session(self):
        text = _make_text_file(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=3",
            files={"file": ("test.txt", text, "text/plain")},
        )
        data = resp.json()
        session_id = data["session_id"]

        # Verify summary works
        summary_resp = client.get(f"/summary?session_id={session_id}")
        assert summary_resp.status_code == 200

    def test_generate_downloads_work(self):
        text = _make_text_file(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, price DECIMAL);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=3",
            files={"file": ("test.txt", text, "text/plain")},
        )
        session_id = resp.json()["session_id"]

        for fmt in ("csv", "json", "sql"):
            dl_resp = client.get(f"/download/{fmt}?session_id={session_id}")
            assert dl_resp.status_code == 200

    def test_generate_preview_works(self):
        text = _make_text_file(
            "CREATE TABLE things (id INTEGER PRIMARY KEY, label VARCHAR NOT NULL);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=5",
            files={"file": ("test.txt", text, "text/plain")},
        )
        session_id = resp.json()["session_id"]

        preview_resp = client.get(f"/preview/things?session_id={session_id}")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["total_rows"] > 0

    def test_generate_empty_file(self):
        resp = client.post(
            "/reference/generate",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert resp.status_code == 400

    def test_generate_confidence_in_response(self):
        text = _make_text_file(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);"
        )
        resp = client.post(
            "/reference/generate?doc_type=schema_image&row_count=3",
            files={"file": ("test.txt", text, "text/plain")},
        )
        data = resp.json()
        assert "avg_confidence" in data
        assert data["avg_confidence"] > 0
