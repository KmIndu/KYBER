"""Tests for business rule reasoning engine and router."""

import pytest
from fastapi.testclient import TestClient

from app.generators.business_rule_engine import BusinessRuleEngine
from app.main import app
from app.models.bdd import BDDMetadata, BDDRule, BDDScenario
from app.models.business_rule import RuleCategory, RuleSource, RuleSeverity
from app.models.openapi import (
    FieldValidation,
    OpenAPIFieldMetadata,
    OpenAPIMetadata,
    OpenAPISchemaMetadata,
)
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.services.session_store import store

client = TestClient(app)


# ── Test Fixtures ─────────────────────────────────────────────


def _make_bdd() -> BDDMetadata:
    return BDDMetadata(
        feature="User Registration",
        scenarios=[
            BDDScenario(
                name="Age validation",
                rules=[
                    BDDRule(field="age", condition="is below 18", result="registration should fail"),
                    BDDRule(field="age", condition="is at least 18", result="registration should succeed"),
                ],
                raw_steps=["Given user age is below 18", "Then registration should fail"],
            ),
            BDDScenario(
                name="KYC verification",
                rules=[
                    BDDRule(field="kyc_status", condition="is not verified", result="account should be restricted"),
                    BDDRule(field="identity_document", condition="is not provided", result="KYC should fail"),
                ],
            ),
            BDDScenario(
                name="Loan approval",
                rules=[
                    BDDRule(field="credit_score", condition="is above 700", result="loan should be approved"),
                    BDDRule(field="income", condition="is between 30000 and 500000", result="eligibility is confirmed"),
                ],
            ),
        ],
    )


def _make_schema() -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="age", data_type="INTEGER", nullable=False),
                    ColumnMetadata(name="email", data_type="VARCHAR(100)", nullable=False, is_unique=True),
                    ColumnMetadata(name="kyc_status", data_type="VARCHAR(20)", nullable=False),
                    ColumnMetadata(name="passport_number", data_type="VARCHAR(20)", nullable=True),
                    ColumnMetadata(name="annual_income", data_type="DECIMAL(12,2)", nullable=True),
                    ColumnMetadata(name="account_balance", data_type="DECIMAL(12,2)", nullable=False),
                    ColumnMetadata(
                        name="status",
                        data_type="VARCHAR(20)",
                        nullable=False,
                        check_constraint="status IN ('active', 'inactive', 'suspended', 'closed')",
                    ),
                    ColumnMetadata(name="is_eligible", data_type="BOOLEAN", nullable=False),
                    ColumnMetadata(name="approved_by", data_type="VARCHAR(50)", nullable=True),
                    ColumnMetadata(name="expiry_date", data_type="DATE", nullable=True),
                ],
                primary_keys=["id"],
                check_constraints=["age >= 0 AND age <= 150"],
            ),
            TableMetadata(
                name="policies",
                columns=[
                    ColumnMetadata(name="policy_id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="premium_amount", data_type="DECIMAL(10,2)", nullable=False),
                    ColumnMetadata(name="coverage_amount", data_type="DECIMAL(12,2)", nullable=False),
                    ColumnMetadata(name="valid_until", data_type="DATE", nullable=False),
                    ColumnMetadata(
                        name="approval_status",
                        data_type="VARCHAR(20)",
                        check_constraint="approval_status IN ('pending', 'approved', 'rejected')",
                    ),
                ],
                primary_keys=["policy_id"],
            ),
        ]
    )


def _make_openapi() -> OpenAPIMetadata:
    return OpenAPIMetadata(
        openapi_version="3.0.0",
        title="Insurance API",
        schemas=[
            OpenAPISchemaMetadata(
                name="Application",
                fields=[
                    OpenAPIFieldMetadata(
                        name="applicant_age",
                        data_type="integer",
                        required=True,
                        validation=FieldValidation(minimum=18, maximum=65),
                    ),
                    OpenAPIFieldMetadata(
                        name="status",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(enum=["submitted", "under_review", "approved", "rejected"]),
                    ),
                    OpenAPIFieldMetadata(
                        name="annual_income",
                        data_type="number",
                        required=True,
                        validation=FieldValidation(minimum=10000, maximum=10000000),
                    ),
                    OpenAPIFieldMetadata(
                        name="policy_number",
                        data_type="string",
                        required=True,
                        validation=FieldValidation(pattern=r"^POL-\d{8}$"),
                    ),
                    OpenAPIFieldMetadata(
                        name="kyc_document_id",
                        data_type="string",
                        required=True,
                    ),
                ],
            ),
        ],
    )


# ── BDD Inference Tests ───────────────────────────────────────


class TestBDDInference:
    def test_age_restriction_from_bdd(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        age_rules = [r for r in result.rules if r.category == RuleCategory.AGE_RESTRICTION]
        assert len(age_rules) >= 2  # "below 18" and "at least 18"

    def test_kyc_rules_from_bdd(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        kyc_rules = [r for r in result.rules if r.category == RuleCategory.KYC]
        assert len(kyc_rules) >= 1

    def test_financial_rules_from_bdd(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        # credit_score "above 700" + "loan should be approved" → APPROVAL
        # income "between 30000 and 500000" + "eligibility" → ELIGIBILITY
        approval = [r for r in result.rules if r.category == RuleCategory.APPROVAL]
        eligibility = [r for r in result.rules if r.category == RuleCategory.ELIGIBILITY]
        assert len(approval) >= 1
        assert len(eligibility) >= 1

    def test_validation_rules_generated(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        # "below 18" → lt operator
        lt_rules = [v for v in result.validation_rules if v.operator == "lt"]
        assert len(lt_rules) >= 1
        assert lt_rules[0].value == 18.0

    def test_gte_validation(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        gte_rules = [v for v in result.validation_rules if v.operator == "gte" and v.field == "age"]
        assert len(gte_rules) >= 1
        assert gte_rules[0].value == 18.0

    def test_between_validation(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        between_rules = [v for v in result.validation_rules if v.operator == "between"]
        assert len(between_rules) >= 1
        assert between_rules[0].value == 30000.0
        assert between_rules[0].value_max == 500000.0

    def test_edge_cases_from_bdd(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        assert result.total_edge_cases > 0
        # Should have boundary test cases for age=18
        age_edges = [e for e in result.edge_cases if "age" in str(e.test_inputs)]
        assert len(age_edges) >= 3  # at boundary, below, above, null

    def test_bdd_source_tagged(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        assert all(r.source == RuleSource.BDD for r in result.rules)

    def test_severity_from_fail_result(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        # "registration should fail" → CRITICAL
        fail_rules = [r for r in result.rules if "fail" in r.description]
        assert any(r.severity == RuleSeverity.CRITICAL for r in fail_rules)


# ── Schema Inference Tests ────────────────────────────────────


class TestSchemaInference:
    def test_age_column_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        age_rules = [r for r in result.rules if r.category == RuleCategory.AGE_RESTRICTION]
        assert len(age_rules) >= 1

    def test_kyc_columns_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        kyc_rules = [r for r in result.rules if r.category == RuleCategory.KYC]
        # kyc_status and passport_number
        assert len(kyc_rules) >= 2

    def test_financial_columns_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        fin_rules = [r for r in result.rules if r.category == RuleCategory.FINANCIAL]
        # annual_income, account_balance, premium_amount, coverage_amount
        assert len(fin_rules) >= 3

    def test_status_transition_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        status_rules = [r for r in result.rules if r.category == RuleCategory.STATUS_TRANSITION]
        # status column with enum + approval_status
        assert len(status_rules) >= 2

    def test_eligibility_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        elig_rules = [r for r in result.rules if r.category == RuleCategory.ELIGIBILITY]
        assert len(elig_rules) >= 1

    def test_approval_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        approval_rules = [r for r in result.rules if r.category == RuleCategory.APPROVAL]
        # approved_by column
        assert len(approval_rules) >= 1

    def test_temporal_detected(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        temporal_rules = [r for r in result.rules if r.category == RuleCategory.TEMPORAL]
        # expiry_date, valid_until
        assert len(temporal_rules) >= 2

    def test_check_constraint_rule(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        # "age >= 0 AND age <= 150" check constraint
        threshold_rules = [r for r in result.rules if r.category == RuleCategory.THRESHOLD or "Check constraint" in r.name]
        assert len(threshold_rules) >= 1

    def test_schema_source_tagged(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        assert all(r.source == RuleSource.SCHEMA for r in result.rules)

    def test_edge_cases_for_financial(self):
        engine = BusinessRuleEngine(schema=_make_schema())
        result = engine.analyze()
        fin_edges = [e for e in result.edge_cases if "amount" in str(e.test_inputs) or "balance" in str(e.test_inputs) or "income" in str(e.test_inputs)]
        assert len(fin_edges) >= 3


# ── OpenAPI Inference Tests ───────────────────────────────────


class TestOpenAPIInference:
    def test_age_restriction_from_api(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        age_rules = [r for r in result.rules if r.category == RuleCategory.AGE_RESTRICTION]
        assert len(age_rules) >= 1
        assert age_rules[0].source == RuleSource.OPENAPI

    def test_enum_business_rule(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        status_rules = [r for r in result.rules if "status" in r.name.lower()]
        assert len(status_rules) >= 1

    def test_range_constraint_from_api(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        income_rules = [r for r in result.rules if "income" in r.name.lower()]
        assert len(income_rules) >= 1

    def test_pattern_format_rule(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        pattern_rules = [r for r in result.rules if r.category == RuleCategory.FORMAT]
        assert len(pattern_rules) >= 1
        # Pattern match validation
        pattern_vals = [v for v in result.validation_rules if v.operator == "matches"]
        assert len(pattern_vals) >= 1

    def test_api_edge_cases(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        # Age below min (17), above max (66)
        age_edges = [e for e in result.edge_cases if "applicant_age" in str(e.test_inputs)]
        assert len(age_edges) >= 4  # at_min, at_max, below_min, above_max

    def test_api_validation_rules(self):
        engine = BusinessRuleEngine(openapi=_make_openapi())
        result = engine.analyze()
        # income: >= 10000, <= 10000000
        income_vals = [v for v in result.validation_rules if v.field == "annual_income"]
        assert len(income_vals) >= 2


# ── Combined Sources Tests ────────────────────────────────────


class TestCombinedSources:
    def test_all_sources_combined(self):
        engine = BusinessRuleEngine(
            schema=_make_schema(), bdd=_make_bdd(), openapi=_make_openapi()
        )
        result = engine.analyze()
        assert result.total_rules > 0
        assert result.total_validation_rules > 0
        assert result.total_edge_cases > 0
        # Multiple sources present
        assert RuleSource.BDD.value in result.rules_by_source
        assert RuleSource.SCHEMA.value in result.rules_by_source
        assert RuleSource.OPENAPI.value in result.rules_by_source

    def test_rules_by_category_populated(self):
        engine = BusinessRuleEngine(
            schema=_make_schema(), bdd=_make_bdd(), openapi=_make_openapi()
        )
        result = engine.analyze()
        assert len(result.rules_by_category) >= 4

    def test_metadata_generated(self):
        engine = BusinessRuleEngine(bdd=_make_bdd())
        result = engine.analyze()
        assert len(result.metadata) == len(result.rules)
        for m in result.metadata:
            assert m.rule_id.startswith("BR-")
            assert m.confidence > 0

    def test_rule_ids_unique(self):
        engine = BusinessRuleEngine(
            schema=_make_schema(), bdd=_make_bdd(), openapi=_make_openapi()
        )
        result = engine.analyze()
        ids = [r.rule_id for r in result.rules]
        assert len(ids) == len(set(ids))

    def test_empty_sources(self):
        engine = BusinessRuleEngine()
        result = engine.analyze()
        assert result.total_rules == 0


# ── Router Integration Tests ──────────────────────────────────


class TestBusinessRulesRouter:
    def test_analyze_with_schema(self):
        session = store.create()
        session.schema = _make_schema()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rules"] > 0
        assert "rules" in data
        assert "validation_rules" in data
        assert "edge_cases" in data
        assert "metadata" in data
        assert "rules_by_category" in data
        assert "rules_by_source" in data

    def test_analyze_with_bdd(self):
        session = store.create()
        session.bdd = _make_bdd()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rules"] > 0
        assert data["rules_by_source"]["bdd"] > 0

    def test_analyze_with_openapi(self):
        session = store.create()
        session.openapi = _make_openapi()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rules"] > 0

    def test_analyze_all_sources(self):
        session = store.create()
        session.schema = _make_schema()
        session.bdd = _make_bdd()
        session.openapi = _make_openapi()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "bdd" in data["rules_by_source"]
        assert "schema" in data["rules_by_source"]
        assert "openapi" in data["rules_by_source"]

    def test_session_not_found(self):
        resp = client.post("/business-rules/analyze?session_id=nonexistent")
        assert resp.status_code == 404

    def test_no_data_sources(self):
        session = store.create()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        assert resp.status_code == 400
        assert "No data sources" in resp.json()["detail"]

    def test_response_structure(self):
        session = store.create()
        session.schema = _make_schema()
        resp = client.post(f"/business-rules/analyze?session_id={session.session_id}")
        data = resp.json()
        # Check a rule's structure
        rule = data["rules"][0]
        assert "rule_id" in rule
        assert "name" in rule
        assert "category" in rule
        assert "source" in rule
        assert "severity" in rule
        assert "description" in rule
        assert "condition" in rule
        assert "fields" in rule
