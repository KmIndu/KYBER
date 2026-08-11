"""Tests for domain detection engine and router."""

import pytest
from fastapi.testclient import TestClient

from app.generators.domain_engine import DomainDetectionEngine
from app.main import app
from app.models.bdd import BDDMetadata, BDDScenario
from app.models.openapi import OpenAPIFieldMetadata, OpenAPIMetadata, OpenAPISchemaMetadata
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.services.session_store import store

client = TestClient(app)


# ── Engine unit tests ──────────────────────────────────────────


class TestDomainDetectionEngine:
    """Unit tests for DomainDetectionEngine."""

    def test_banking_schema(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="accounts",
                columns=[
                    ColumnMetadata(name="account_id", data_type="int"),
                    ColumnMetadata(name="balance", data_type="decimal"),
                    ColumnMetadata(name="transaction_date", data_type="date"),
                    ColumnMetadata(name="deposit_amount", data_type="decimal"),
                ],
            ),
            TableMetadata(
                name="transactions",
                columns=[
                    ColumnMetadata(name="transfer_id", data_type="int"),
                    ColumnMetadata(name="withdrawal_amount", data_type="decimal"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert result.domain == "banking"
        assert result.confidence > 0.7
        assert len(result.signals) > 0
        assert result.all_scores["banking"] > result.all_scores["insurance"]

    def test_insurance_schema(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="policies",
                columns=[
                    ColumnMetadata(name="policy_id", data_type="int"),
                    ColumnMetadata(name="premium", data_type="decimal"),
                    ColumnMetadata(name="coverage_amount", data_type="decimal"),
                    ColumnMetadata(name="deductible", data_type="decimal"),
                ],
            ),
            TableMetadata(
                name="claims",
                columns=[
                    ColumnMetadata(name="claim_id", data_type="int"),
                    ColumnMetadata(name="claim_amount", data_type="decimal"),
                    ColumnMetadata(name="nominee", data_type="varchar"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert result.domain == "insurance"
        assert result.confidence > 0.7

    def test_healthcare_schema(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="patients",
                columns=[
                    ColumnMetadata(name="patient_id", data_type="int"),
                    ColumnMetadata(name="diagnosis", data_type="varchar"),
                    ColumnMetadata(name="prescription", data_type="text"),
                    ColumnMetadata(name="physician_id", data_type="int"),
                ],
            ),
            TableMetadata(
                name="medical_records",
                columns=[
                    ColumnMetadata(name="medication", data_type="varchar"),
                    ColumnMetadata(name="dosage", data_type="varchar"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert result.domain == "healthcare"
        assert result.confidence > 0.7

    def test_retail_schema(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="products",
                columns=[
                    ColumnMetadata(name="product_id", data_type="int"),
                    ColumnMetadata(name="sku", data_type="varchar"),
                    ColumnMetadata(name="price", data_type="decimal"),
                    ColumnMetadata(name="inventory_count", data_type="int"),
                ],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="order_id", data_type="int"),
                    ColumnMetadata(name="cart_total", data_type="decimal"),
                    ColumnMetadata(name="checkout_date", data_type="date"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert result.domain == "retail"
        assert result.confidence > 0.7

    def test_unknown_domain_generic_schema(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="items",
                columns=[
                    ColumnMetadata(name="id", data_type="int"),
                    ColumnMetadata(name="name", data_type="varchar"),
                    ColumnMetadata(name="created_at", data_type="timestamp"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert result.domain == "unknown"
        assert result.confidence == 0.0

    def test_empty_schema(self):
        engine = DomainDetectionEngine(schema=None, openapi=None, bdd=None)
        result = engine.detect()
        assert result.domain == "unknown"
        assert result.confidence == 0.0
        assert result.signals == []

    def test_openapi_insurance_detection(self):
        openapi = OpenAPIMetadata(
            openapi_version="3.0.0",
            title="Insurance Claims API",
            schemas=[
                OpenAPISchemaMetadata(
                    name="Policy",
                    fields=[
                        OpenAPIFieldMetadata(name="premium", data_type="number"),
                        OpenAPIFieldMetadata(name="coverage", data_type="number"),
                        OpenAPIFieldMetadata(name="policyholder", data_type="string"),
                    ],
                ),
                OpenAPISchemaMetadata(
                    name="Claim",
                    fields=[
                        OpenAPIFieldMetadata(name="claim_amount", data_type="number"),
                        OpenAPIFieldMetadata(name="deductible", data_type="number"),
                    ],
                ),
            ],
        )
        engine = DomainDetectionEngine(openapi=openapi)
        result = engine.detect()
        assert result.domain == "insurance"
        assert result.confidence > 0.7

    def test_bdd_healthcare_detection(self):
        bdd = BDDMetadata(
            feature="Patient Management",
            scenarios=[
                BDDScenario(
                    name="Schedule appointment for patient",
                    raw_steps=[
                        "Given a patient with diagnosis diabetes",
                        "When the physician prescribes medication",
                        "Then the prescription is added to ehr",
                    ],
                ),
            ],
        )
        engine = DomainDetectionEngine(bdd=bdd)
        result = engine.detect()
        assert result.domain == "healthcare"
        assert result.confidence > 0.5

    def test_mixed_signals_confidence(self):
        """When multiple domains have signals, confidence reflects relative strength."""
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="accounts",
                columns=[
                    ColumnMetadata(name="balance", data_type="decimal"),
                    ColumnMetadata(name="product_name", data_type="varchar"),
                ],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        # Should still pick a winner
        assert result.domain in ("banking", "retail")
        # Confidence should be lower than a pure-domain case
        assert 0.0 < result.confidence < 1.0
        # All scores should sum to ~1.0
        total = sum(result.all_scores.values())
        assert abs(total - 1.0) < 0.05

    def test_all_scores_populated(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="policies",
                columns=[ColumnMetadata(name="premium", data_type="decimal")],
            ),
        ])
        engine = DomainDetectionEngine(schema=schema)
        result = engine.detect()
        assert "banking" in result.all_scores
        assert "insurance" in result.all_scores
        assert "healthcare" in result.all_scores
        assert "retail" in result.all_scores

    def test_combined_schema_and_bdd(self):
        """Engine combines signals from multiple sources."""
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="orders",
                columns=[ColumnMetadata(name="cart_id", data_type="int")],
            ),
        ])
        bdd = BDDMetadata(
            feature="Shopping Cart",
            scenarios=[
                BDDScenario(
                    name="Add product to cart",
                    raw_steps=[
                        "Given a product in the catalog",
                        "When customer adds to cart",
                        "Then checkout total is updated",
                    ],
                ),
            ],
        )
        engine = DomainDetectionEngine(schema=schema, bdd=bdd)
        result = engine.detect()
        assert result.domain == "retail"
        assert result.confidence > 0.7


# ── Router integration tests ──────────────────────────────────


class TestDomainRouter:
    """Integration tests for POST /domain/detect."""

    def test_detect_success(self):
        session = store.create()
        session.schema = SchemaMetadata(tables=[
            TableMetadata(
                name="policies",
                columns=[
                    ColumnMetadata(name="premium", data_type="decimal"),
                    ColumnMetadata(name="claim_amount", data_type="decimal"),
                ],
            ),
        ])
        resp = client.post(f"/domain/detect?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "insurance"
        assert data["confidence"] > 0.0
        assert "signals" in data
        assert "all_scores" in data

    def test_detect_session_not_found(self):
        resp = client.post("/domain/detect?session_id=nonexistent-id")
        assert resp.status_code == 404

    def test_detect_no_parsed_data(self):
        session = store.create()
        resp = client.post(f"/domain/detect?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No parsed data" in resp.json()["detail"]

    def test_detect_missing_session_id(self):
        resp = client.post("/domain/detect")
        assert resp.status_code == 422
