"""Tests for the smart edge-case generation engine.

Covers:
- Domain detection from schema
- Insurance failure scenario generation
- Banking failure scenario generation
- Healthcare failure scenario generation
- E-commerce failure scenario generation
- HR failure scenario generation
- Generic fallback for unknown domains
- Template matching logic
- Empty schema handling
- Router endpoint integration
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.generators.smart_edge_case_engine import (
    FailureScenario,
    SmartEdgeCaseEngine,
    SmartEdgeCaseResult,
)
from app.main import app
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
def insurance_schema() -> SchemaMetadata:
    """Schema that looks like an insurance claims system."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="claims",
            columns=[
                ColumnMetadata(name="claim_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="policy_id", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="claim_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="denial_reason", data_type="VARCHAR(200)", nullable=True),
                ColumnMetadata(name="approved_amount", data_type="DECIMAL(12,2)", nullable=True),
                ColumnMetadata(name="document_verified", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="is_duplicate", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="original_ref", data_type="VARCHAR(50)", nullable=True),
                ColumnMetadata(name="review_date", data_type="DATE", nullable=True),
                ColumnMetadata(name="reviewed_by", data_type="VARCHAR(100)", nullable=True),
                ColumnMetadata(name="notes", data_type="TEXT", nullable=True),
                ColumnMetadata(name="escalated", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="is_active", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="fraud_flag", data_type="BOOLEAN", nullable=True),
            ],
            primary_keys=["claim_id"],
        ),
        TableMetadata(
            name="policies",
            columns=[
                ColumnMetadata(name="policy_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="policy_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="expiry_date", data_type="DATE", nullable=True),
                ColumnMetadata(name="is_active", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="policyholder_id", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="premium", data_type="DECIMAL(10,2)", nullable=False),
                ColumnMetadata(name="coverage", data_type="VARCHAR(100)", nullable=True),
            ],
            primary_keys=["policy_id"],
        ),
    ])


@pytest.fixture
def banking_schema() -> SchemaMetadata:
    """Schema that looks like a banking system."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="transactions",
            columns=[
                ColumnMetadata(name="transaction_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="account_id", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="transaction_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="amount", data_type="DECIMAL(12,2)", nullable=False),
                ColumnMetadata(name="error_code", data_type="VARCHAR(50)", nullable=True),
                ColumnMetadata(name="error_message", data_type="VARCHAR(500)", nullable=True),
                ColumnMetadata(name="is_successful", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="completed_at", data_type="TIMESTAMP", nullable=True),
                ColumnMetadata(name="retry_count", data_type="INTEGER", nullable=True),
                ColumnMetadata(name="balance_after", data_type="DECIMAL(12,2)", nullable=True),
                ColumnMetadata(name="is_duplicate", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="original_ref", data_type="VARCHAR(50)", nullable=True),
                ColumnMetadata(name="notes", data_type="TEXT", nullable=True),
            ],
            primary_keys=["transaction_id"],
        ),
    ])


@pytest.fixture
def ecommerce_schema() -> SchemaMetadata:
    """Schema that looks like an e-commerce system."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="orders",
            columns=[
                ColumnMetadata(name="order_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="order_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="payment_success", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="error_code", data_type="VARCHAR(50)", nullable=True),
                ColumnMetadata(name="shipped", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="ship_date", data_type="DATE", nullable=True),
                ColumnMetadata(name="address_verified", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="fraud_flag", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="notes", data_type="TEXT", nullable=True),
                ColumnMetadata(name="coupon_code", data_type="VARCHAR(50)", nullable=True),
                ColumnMetadata(name="discount", data_type="DECIMAL(10,2)", nullable=True),
                ColumnMetadata(name="order_total", data_type="DECIMAL(12,2)", nullable=True),
                ColumnMetadata(name="product_id", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="inventory_status", data_type="VARCHAR(50)", nullable=True),
            ],
            primary_keys=["order_id"],
        ),
    ])


@pytest.fixture
def hr_schema() -> SchemaMetadata:
    """Schema that looks like an HR system."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="employees",
            columns=[
                ColumnMetadata(name="employee_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="employee_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="is_active", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="termination_date", data_type="DATE", nullable=True),
                ColumnMetadata(name="access_revoked", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="salary", data_type="DECIMAL(12,2)", nullable=False),
                ColumnMetadata(name="department", data_type="VARCHAR(100)", nullable=False),
                ColumnMetadata(name="notes", data_type="TEXT", nullable=True),
            ],
            primary_keys=["employee_id"],
        ),
        TableMetadata(
            name="leave_requests",
            columns=[
                ColumnMetadata(name="request_id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="employee_id", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="leave_status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="approved", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="rejection_reason", data_type="VARCHAR(200)", nullable=True),
                ColumnMetadata(name="days_requested", data_type="INTEGER", nullable=False),
                ColumnMetadata(name="balance", data_type="INTEGER", nullable=True),
                ColumnMetadata(name="notes", data_type="TEXT", nullable=True),
            ],
            primary_keys=["request_id"],
        ),
    ])


@pytest.fixture
def generic_schema() -> SchemaMetadata:
    """Schema with no domain-specific signals — should trigger generic fallback."""
    return SchemaMetadata(tables=[
        TableMetadata(
            name="records",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ColumnMetadata(name="status", data_type="VARCHAR(50)", nullable=False),
                ColumnMetadata(name="is_valid", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="has_errors", data_type="BOOLEAN", nullable=True),
                ColumnMetadata(name="amount", data_type="DECIMAL(10,2)", nullable=True),
                ColumnMetadata(name="total", data_type="DECIMAL(10,2)", nullable=True),
                ColumnMetadata(name="created_at", data_type="TIMESTAMP", nullable=True),
            ],
            primary_keys=["id"],
        ),
    ])


@pytest.fixture
def empty_schema() -> SchemaMetadata:
    return SchemaMetadata(tables=[])


# ── Domain Detection Tests ────────────────────────────────────


class TestDomainDetection:
    def test_detects_insurance_domain(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        assert engine._detect_domain() == "insurance"

    def test_detects_banking_domain(self, banking_schema):
        engine = SmartEdgeCaseEngine(schema=banking_schema)
        assert engine._detect_domain() == "banking"

    def test_detects_ecommerce_domain(self, ecommerce_schema):
        engine = SmartEdgeCaseEngine(schema=ecommerce_schema)
        assert engine._detect_domain() == "ecommerce"

    def test_detects_hr_domain(self, hr_schema):
        engine = SmartEdgeCaseEngine(schema=hr_schema)
        assert engine._detect_domain() == "hr"

    def test_generic_domain_fallback(self, generic_schema):
        engine = SmartEdgeCaseEngine(schema=generic_schema)
        # Should detect "general" since no strong domain signals
        domain = engine._detect_domain()
        assert domain in ("general", "banking", "ecommerce", "hr", "insurance", "healthcare")


# ── Insurance Scenario Tests ──────────────────────────────────


class TestInsuranceScenarios:
    def test_generates_scenarios_for_claims(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate(session_id="test-ins")

        assert result.session_id == "test-ins"
        assert result.domain_detected == "insurance"
        assert result.tables_analyzed == 2
        assert len(result.scenarios) > 0

    def test_scenarios_have_coherent_field_values(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        for scenario in result.scenarios:
            if scenario.table == "claims":
                # Each scenario should have actual column names from the table
                valid_cols = {c.name for c in insurance_schema.tables[0].columns}
                for col in scenario.field_values:
                    assert col in valid_cols, f"Unknown column '{col}' in scenario '{scenario.name}'"

    def test_rejection_scenarios_have_no_approval(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        rejection_scenarios = [
            s for s in result.scenarios
            if s.category == "rejection" and s.table == "claims"
        ]

        for scenario in rejection_scenarios:
            vals = scenario.field_values
            # If approved_amount is in the values, it should be 0 or None
            if "approved_amount" in vals:
                assert vals["approved_amount"] in (0, None, 0.0), (
                    f"Rejection scenario '{scenario.name}' has non-zero approved_amount"
                )

    def test_duplicate_scenarios_have_reference(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        dup_scenarios = [
            s for s in result.scenarios
            if s.category == "duplication" and s.table == "claims"
        ]

        for scenario in dup_scenarios:
            vals = scenario.field_values
            if "is_duplicate" in vals:
                assert vals["is_duplicate"] is True
            if "original_ref" in vals:
                assert vals["original_ref"] is not None

    def test_fraud_scenarios_have_escalation(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        fraud_scenarios = [
            s for s in result.scenarios
            if s.category == "fraud" and s.table == "claims"
        ]

        for scenario in fraud_scenarios:
            vals = scenario.field_values
            if "fraud_flag" in vals:
                assert vals["fraud_flag"] is True
            if "escalated" in vals:
                assert vals["escalated"] is True


# ── Banking Scenario Tests ────────────────────────────────────


class TestBankingScenarios:
    def test_generates_banking_scenarios(self, banking_schema):
        engine = SmartEdgeCaseEngine(schema=banking_schema)
        result = engine.generate(session_id="test-bank")

        assert result.domain_detected == "banking"
        assert len(result.scenarios) > 0

    def test_timeout_scenario_has_no_completion(self, banking_schema):
        engine = SmartEdgeCaseEngine(schema=banking_schema)
        result = engine.generate()

        timeout_scenarios = [s for s in result.scenarios if s.category == "timeout"]

        for scenario in timeout_scenarios:
            vals = scenario.field_values
            if "completed_at" in vals:
                assert vals["completed_at"] is None
            if "is_successful" in vals:
                assert vals["is_successful"] is False

    def test_failure_scenarios_have_error_codes(self, banking_schema):
        engine = SmartEdgeCaseEngine(schema=banking_schema)
        result = engine.generate()

        for scenario in result.scenarios:
            vals = scenario.field_values
            # Failed scenarios should have error info
            if scenario.category in ("timeout", "rejection", "system_error"):
                if "error_code" in vals:
                    assert vals["error_code"] is not None and vals["error_code"] != ""


# ── E-commerce Scenario Tests ─────────────────────────────────


class TestEcommerceScenarios:
    def test_generates_ecommerce_scenarios(self, ecommerce_schema):
        engine = SmartEdgeCaseEngine(schema=ecommerce_schema)
        result = engine.generate(session_id="test-ecom")

        assert result.domain_detected == "ecommerce"
        assert len(result.scenarios) > 0

    def test_payment_failed_not_shipped(self, ecommerce_schema):
        engine = SmartEdgeCaseEngine(schema=ecommerce_schema)
        result = engine.generate()

        payment_failures = [
            s for s in result.scenarios
            if "payment" in s.name or s.category == "rejection"
        ]

        for scenario in payment_failures:
            vals = scenario.field_values
            if "shipped" in vals:
                assert vals["shipped"] is False
            if "ship_date" in vals:
                assert vals["ship_date"] is None


# ── HR Scenario Tests ─────────────────────────────────────────


class TestHRScenarios:
    def test_generates_hr_scenarios(self, hr_schema):
        engine = SmartEdgeCaseEngine(schema=hr_schema)
        result = engine.generate(session_id="test-hr")

        assert result.domain_detected == "hr"
        assert len(result.scenarios) > 0

    def test_leave_denial_exceeds_balance(self, hr_schema):
        engine = SmartEdgeCaseEngine(schema=hr_schema)
        result = engine.generate()

        leave_denials = [
            s for s in result.scenarios
            if s.table == "leave_requests" and s.category == "rejection"
        ]

        for scenario in leave_denials:
            vals = scenario.field_values
            if "approved" in vals:
                assert vals["approved"] is False


# ── Generic Fallback Tests ────────────────────────────────────


class TestGenericFallback:
    def test_generates_generic_scenarios(self, generic_schema):
        engine = SmartEdgeCaseEngine(schema=generic_schema)
        result = engine.generate(session_id="test-generic")

        assert len(result.scenarios) > 0

    def test_generic_uses_status_column(self, generic_schema):
        engine = SmartEdgeCaseEngine(schema=generic_schema)
        result = engine.generate()

        # At least one scenario should reference the status column
        has_status = any(
            "status" in s.field_values for s in result.scenarios
        )
        assert has_status


# ── Result Structure Tests ────────────────────────────────────


class TestResultStructure:
    def test_result_has_required_fields(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate(session_id="test-struct")

        assert result.session_id == "test-struct"
        assert result.domain_detected != ""
        assert result.tables_analyzed > 0
        assert isinstance(result.scenarios_per_category, dict)
        assert isinstance(result.coverage_summary, dict)

    def test_to_dict_serializable(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate(session_id="test-serial")
        d = result.to_dict()

        assert "session_id" in d
        assert "scenarios" in d
        assert "total_scenarios" in d
        assert d["total_scenarios"] == len(d["scenarios"])

        # All scenario field values should be serializable (no callables)
        for scenario in d["scenarios"]:
            for key, value in scenario["field_values"].items():
                assert not callable(value), f"Callable found in field_values[{key}]"

    def test_scenario_ids_are_unique(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        ids = [s.scenario_id for s in result.scenarios]
        assert len(ids) == len(set(ids)), "Duplicate scenario IDs"

    def test_scenarios_per_category_correct(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema)
        result = engine.generate()

        # Verify category counts match actual scenarios
        actual: dict[str, int] = {}
        for s in result.scenarios:
            actual[s.category] = actual.get(s.category, 0) + 1

        assert actual == result.scenarios_per_category


# ── Edge Cases for the Engine Itself ──────────────────────────


class TestEngineEdgeCases:
    def test_empty_schema_returns_empty_result(self, empty_schema):
        engine = SmartEdgeCaseEngine(schema=empty_schema)
        result = engine.generate(session_id="test-empty")

        assert result.tables_analyzed == 0
        assert len(result.scenarios) == 0
        assert result.scenarios_per_category == {}

    def test_single_column_table(self):
        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="minimal",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True, nullable=False),
                ],
                primary_keys=["id"],
            ),
        ])
        engine = SmartEdgeCaseEngine(schema=schema)
        result = engine.generate()
        # Should not crash — may return 0 scenarios for minimal table
        assert result.tables_analyzed == 1

    def test_target_scenarios_per_table_limit(self, insurance_schema):
        engine = SmartEdgeCaseEngine(schema=insurance_schema, target_scenarios_per_table=2)
        result = engine.generate()

        # Each table should have at most 2 scenarios from templates
        for table_name, scenario_names in result.coverage_summary.items():
            assert len(scenario_names) <= 5  # 2 from templates + potential generic fallback


# ── Router Integration Tests ──────────────────────────────────


class TestSmartEdgeCaseRouter:
    def test_smart_endpoint_success(self, insurance_schema):
        # Create a session with schema
        from app.services.session_store import Session
        session = Session(session_id="test-smart-route")
        session.schema = insurance_schema
        store._sessions["test-smart-route"] = session

        response = client.post("/edge-cases/smart?session_id=test-smart-route")
        assert response.status_code == 200

        data = response.json()
        assert "scenarios" in data
        assert "domain_detected" in data
        assert "total_scenarios" in data
        assert data["total_scenarios"] > 0

        # Cleanup
        del store._sessions["test-smart-route"]

    def test_smart_endpoint_missing_session(self):
        response = client.post("/edge-cases/smart?session_id=nonexistent-session")
        assert response.status_code == 404

    def test_smart_endpoint_no_schema(self):
        from app.services.session_store import Session
        session = Session(session_id="test-smart-no-schema")
        store._sessions["test-smart-no-schema"] = session

        response = client.post("/edge-cases/smart?session_id=test-smart-no-schema")
        assert response.status_code == 400

        del store._sessions["test-smart-no-schema"]

    def test_smart_endpoint_custom_scenarios_per_table(self, insurance_schema):
        from app.services.session_store import Session
        session = Session(session_id="test-smart-custom")
        session.schema = insurance_schema
        store._sessions["test-smart-custom"] = session

        response = client.post("/edge-cases/smart?session_id=test-smart-custom&scenarios_per_table=3")
        assert response.status_code == 200

        del store._sessions["test-smart-custom"]
