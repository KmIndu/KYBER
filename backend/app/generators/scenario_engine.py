"""Scenario-Driven Synthetic Data Generation Engine.

Instead of generating random independent field values, this engine:
1. Determines a business scenario first
2. Derives ALL coherent field values from that scenario

Each row is generated as a complete story — fields are never independent.
"""

from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Any, Callable

from app.generators.context_inference import _infer_domain, _DOMAIN_KEYWORDS
from app.models.schema import ColumnMetadata, TableMetadata


# ── Scenario categories ───────────────────────────────────────

SCENARIO_CATEGORIES = ("happy_path", "edge_case", "invalid", "boundary")


# ── Scenario template structure ───────────────────────────────

class ScenarioTemplate:
    """A coherent business scenario with derived field values."""

    __slots__ = ("name", "category", "domain", "field_values", "description")

    def __init__(
        self,
        name: str,
        category: str,
        domain: str,
        field_values: dict[str, Any],
        description: str,
    ):
        self.name = name
        self.category = category
        self.domain = domain
        self.field_values = field_values  # col_pattern → value or callable
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "domain": self.domain,
            "description": self.description,
        }


# ── Column matching helpers ───────────────────────────────────

def _col_matches(col_name: str, patterns: list[str]) -> bool:
    """Check if column name matches any pattern (substring match)."""
    col_lower = col_name.lower()
    return any(p in col_lower for p in patterns)


def _find_col(columns: list[str], patterns: list[str]) -> str | None:
    """Find first column matching any pattern."""
    for col in columns:
        if _col_matches(col, patterns):
            return col
    return None


# ── Insurance scenarios ───────────────────────────────────────

_INSURANCE_SCENARIOS: list[ScenarioTemplate] = [
    # Happy path
    ScenarioTemplate(
        name="claim_approved_standard",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "approved",
            "denial_reason|reject_reason": None,
            "approved_amount": lambda: round(random.uniform(5000, 50000), 2),
            "notes|comment": "Claim verified and approved. All documentation complete.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 30)),
            "reviewed_by": lambda: random.choice(["Sarah Johnson", "Michael Chen", "Priya Patel", "James Wilson", "Lisa Thompson"]),
            "payment_method|pay_method": lambda: random.choice(["eft", "cheque", "direct_deposit"]),
        },
        description="Standard claim approved with full documentation",
    ),
    ScenarioTemplate(
        name="claim_approved_after_escalation",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "approved",
            "denial_reason|reject_reason": None,
            "approved_amount": lambda: round(random.uniform(50000, 150000), 2),
            "notes|comment": "Escalated to senior adjuster. Approved after additional review.",
            "escalated": True,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(7, 60)),
            "reviewed_by": lambda: random.choice(["Director Maria Lopez", "VP David Park", "Senior Adj. Robert Kim"]),
            "payment_method|pay_method": lambda: random.choice(["eft", "wire_transfer"]),
        },
        description="High-value claim approved after management escalation",
    ),
    ScenarioTemplate(
        name="claim_denied_insufficient_documentation",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "insufficient_documentation",
            "approved_amount": 0,
            "notes|comment": "Required medical records not provided within 30-day window.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 14)),
            "reviewed_by": lambda: random.choice(["Sarah Johnson", "Michael Chen", "Priya Patel"]),
        },
        description="Claim denied due to missing documentation",
    ),
    ScenarioTemplate(
        name="claim_denied_policy_lapsed",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "policy_lapsed",
            "approved_amount": 0,
            "notes|comment": "Policy lapsed due to non-payment. Incident occurred after coverage end date.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 7)),
            "reviewed_by": lambda: random.choice(["Automated System", "Policy Verification Bot"]),
        },
        description="Claim denied because policy was not active",
    ),
    ScenarioTemplate(
        name="claim_denied_pre_existing",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "pre_existing_condition",
            "approved_amount": 0,
            "notes|comment": "Condition documented in medical history prior to policy effective date.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(3, 21)),
            "reviewed_by": lambda: random.choice(["Medical Review Board", "Dr. Patricia Wells", "Clinical Analyst Team"]),
        },
        description="Claim denied for pre-existing condition",
    ),
    ScenarioTemplate(
        name="claim_denied_fraud_suspected",
        category="edge_case",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "fraud_suspected",
            "approved_amount": 0,
            "notes|comment": "Irregularities detected. Case referred to Special Investigations Unit.",
            "escalated": True,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 5)),
            "reviewed_by": lambda: random.choice(["SIU Team Lead", "Fraud Analyst K. Rogers", "Investigations Director"]),
        },
        description="Claim flagged for potential fraud",
    ),
    ScenarioTemplate(
        name="claim_pending_additional_info",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "pending_info",
            "denial_reason|reject_reason": None,
            "approved_amount": None,
            "notes|comment": "Awaiting additional medical records from treating physician.",
            "escalated": False,
            "review_date|reviewed_at": None,
            "reviewed_by": lambda: random.choice(["Claims Processor A. Smith", "Intake Analyst B. Davis"]),
        },
        description="Claim awaiting additional information from claimant",
    ),
    ScenarioTemplate(
        name="claim_partial_approval",
        category="happy_path",
        domain="insurance",
        field_values={
            "status|decision": "partial",
            "denial_reason|reject_reason": None,
            "approved_amount": lambda: round(random.uniform(1000, 15000), 2),
            "notes|comment": "Partial approval — some items not covered under current plan.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 14)),
            "reviewed_by": lambda: random.choice(["Sarah Johnson", "Michael Chen", "Priya Patel", "James Wilson"]),
        },
        description="Claim partially approved with some exclusions",
    ),
    # Edge cases
    ScenarioTemplate(
        name="claim_denied_waiting_period",
        category="edge_case",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "waiting_period",
            "approved_amount": 0,
            "notes|comment": "Claim filed during initial waiting period. Coverage begins after 90 days.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 10)),
            "reviewed_by": lambda: random.choice(["Policy Admin System", "Eligibility Check Engine"]),
        },
        description="Claim denied because waiting period not satisfied",
    ),
    ScenarioTemplate(
        name="claim_denied_exclusion",
        category="edge_case",
        domain="insurance",
        field_values={
            "status|decision": "denied",
            "denial_reason|reject_reason": "exclusion_applies",
            "approved_amount": 0,
            "notes|comment": "Treatment falls under policy exclusion clause section 4.2.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(2, 14)),
            "reviewed_by": lambda: random.choice(["Contract Review Team", "Policy Analyst M. Brown"]),
        },
        description="Claim denied due to policy exclusion clause",
    ),
    # Boundary
    ScenarioTemplate(
        name="claim_at_policy_limit",
        category="boundary",
        domain="insurance",
        field_values={
            "status|decision": "approved",
            "denial_reason|reject_reason": None,
            "approved_amount": lambda: round(random.uniform(99000, 100000), 2),
            "notes|comment": "Approved at policy maximum. Future claims may exhaust remaining coverage.",
            "escalated": True,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 7)),
            "reviewed_by": lambda: random.choice(["Senior Adjuster T. Martinez", "Coverage Limit Reviewer"]),
        },
        description="Claim approved at maximum policy limit",
    ),
    ScenarioTemplate(
        name="claim_zero_amount",
        category="boundary",
        domain="insurance",
        field_values={
            "status|decision": "approved",
            "denial_reason|reject_reason": None,
            "approved_amount": 0.00,
            "notes|comment": "Deductible exceeds claim amount. No payout required.",
            "escalated": False,
            "review_date|reviewed_at": lambda: date.today() - timedelta(days=random.randint(1, 3)),
            "reviewed_by": lambda: random.choice(["Auto-Adjudication System", "Deductible Calculator"]),
        },
        description="Claim where deductible exceeds amount — zero payout",
    ),
]

# ── Banking scenarios ─────────────────────────────────────────

_BANKING_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="transaction_completed",
        category="happy_path",
        domain="banking",
        field_values={
            "status|state": "completed",
            "amount|balance": lambda: round(random.uniform(100, 50000), 2),
            "notes|comment": "Transaction processed successfully.",
            "error_code|err_code": None,
            "transaction_type|txn_type": lambda: random.choice(["transfer", "payment", "deposit"]),
            "currency|currency_code": lambda: random.choice(["USD", "CAD", "GBP", "EUR"]),
        },
        description="Successful transaction completion",
    ),
    ScenarioTemplate(
        name="transaction_failed_insufficient_funds",
        category="happy_path",
        domain="banking",
        field_values={
            "status|state": "failed",
            "amount|balance": lambda: round(random.uniform(5000, 100000), 2),
            "notes|comment": "Transaction declined — insufficient funds in source account.",
            "error_code|err_code": "INSUFFICIENT_FUNDS",
            "transaction_type|txn_type": lambda: random.choice(["transfer", "payment", "withdrawal"]),
        },
        description="Transaction failed due to insufficient balance",
    ),
    ScenarioTemplate(
        name="transaction_pending_review",
        category="happy_path",
        domain="banking",
        field_values={
            "status|state": "pending_review",
            "amount|balance": lambda: round(random.uniform(10000, 500000), 2),
            "notes|comment": "Large transaction flagged for compliance review.",
            "error_code|err_code": None,
            "transaction_type|txn_type": lambda: random.choice(["wire_transfer", "international_transfer"]),
        },
        description="High-value transaction held for compliance review",
    ),
    ScenarioTemplate(
        name="transaction_reversed",
        category="edge_case",
        domain="banking",
        field_values={
            "status|state": "reversed",
            "amount|balance": lambda: round(random.uniform(50, 10000), 2),
            "notes|comment": "Transaction reversed per customer dispute.",
            "error_code|err_code": "CUSTOMER_DISPUTE",
            "transaction_type|txn_type": "payment",
        },
        description="Transaction reversed after customer dispute",
    ),
    ScenarioTemplate(
        name="transaction_fraud_blocked",
        category="edge_case",
        domain="banking",
        field_values={
            "status|state": "blocked",
            "amount|balance": lambda: round(random.uniform(1000, 50000), 2),
            "notes|comment": "Blocked by fraud detection system. Anomalous pattern detected.",
            "error_code|err_code": "FRAUD_ALERT",
            "transaction_type|txn_type": lambda: random.choice(["transfer", "payment"]),
        },
        description="Transaction blocked by fraud detection",
    ),
    ScenarioTemplate(
        name="transaction_at_daily_limit",
        category="boundary",
        domain="banking",
        field_values={
            "status|state": "completed",
            "amount|balance": lambda: random.choice([10000.00, 25000.00, 50000.00]),
            "notes|comment": "Transaction at daily limit. Further transactions may be restricted.",
            "error_code|err_code": None,
            "transaction_type|txn_type": "transfer",
        },
        description="Transaction exactly at daily transfer limit",
    ),
]

# ── Healthcare scenarios ──────────────────────────────────────

_HEALTHCARE_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="patient_admitted_routine",
        category="happy_path",
        domain="healthcare",
        field_values={
            "status|state": "admitted",
            "notes|comment": "Patient admitted for scheduled procedure. Vitals stable.",
            "priority|severity": "routine",
            "diagnosis_code|icd_code": lambda: random.choice(["K80.20", "M17.11", "I25.10", "J44.1"]),
            "attending_doctor|doctor_name|physician": lambda: random.choice(["Dr. Sarah Mitchell", "Dr. James Park", "Dr. Aisha Khan"]),
            "discharge_date|discharged_at": None,
        },
        description="Routine patient admission",
    ),
    ScenarioTemplate(
        name="patient_discharged_recovered",
        category="happy_path",
        domain="healthcare",
        field_values={
            "status|state": "discharged",
            "notes|comment": "Patient recovered well. Prescribed follow-up in 2 weeks.",
            "priority|severity": "routine",
            "discharge_date|discharged_at": lambda: date.today() - timedelta(days=random.randint(0, 7)),
        },
        description="Patient discharged after successful recovery",
    ),
    ScenarioTemplate(
        name="patient_emergency_critical",
        category="edge_case",
        domain="healthcare",
        field_values={
            "status|state": "critical",
            "notes|comment": "Emergency admission. Patient in ICU. Family notified.",
            "priority|severity": "critical",
            "diagnosis_code|icd_code": lambda: random.choice(["I21.0", "I63.9", "J96.01", "S06.6"]),
            "attending_doctor|doctor_name|physician": lambda: random.choice(["Dr. Emergency Team", "Dr. R. Gupta (ICU)", "Dr. L. Chen (Trauma)"]),
            "discharge_date|discharged_at": None,
        },
        description="Emergency critical admission",
    ),
    ScenarioTemplate(
        name="patient_awaiting_results",
        category="happy_path",
        domain="healthcare",
        field_values={
            "status|state": "awaiting_results",
            "notes|comment": "Lab samples collected. Awaiting pathology report.",
            "priority|severity": "normal",
            "diagnosis_code|icd_code": None,
            "discharge_date|discharged_at": None,
        },
        description="Patient waiting for diagnostic results",
    ),
]

# ── HR scenarios ──────────────────────────────────────────────

_HR_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="employee_active_good_standing",
        category="happy_path",
        domain="hr",
        field_values={
            "status|state": "active",
            "notes|comment": "Employee in good standing. Annual review completed.",
            "performance_rating|rating": lambda: random.choice(["exceeds_expectations", "meets_expectations"]),
            "department|dept": lambda: random.choice(["Engineering", "Finance", "Operations", "Marketing", "HR"]),
            "termination_reason|exit_reason": None,
        },
        description="Active employee in good standing",
    ),
    ScenarioTemplate(
        name="employee_on_probation",
        category="happy_path",
        domain="hr",
        field_values={
            "status|state": "probation",
            "notes|comment": "New hire — probation review scheduled at 90 days.",
            "performance_rating|rating": "pending_review",
            "department|dept": lambda: random.choice(["Engineering", "Finance", "Operations"]),
            "termination_reason|exit_reason": None,
        },
        description="New employee on probation period",
    ),
    ScenarioTemplate(
        name="employee_terminated_performance",
        category="edge_case",
        domain="hr",
        field_values={
            "status|state": "terminated",
            "notes|comment": "Termination for cause — repeated performance issues documented.",
            "performance_rating|rating": "unsatisfactory",
            "termination_reason|exit_reason": "performance",
            "termination_date|exit_date": lambda: date.today() - timedelta(days=random.randint(1, 90)),
        },
        description="Employee terminated for performance issues",
    ),
    ScenarioTemplate(
        name="employee_on_leave",
        category="happy_path",
        domain="hr",
        field_values={
            "status|state": "on_leave",
            "notes|comment": lambda: random.choice([
                "Approved medical leave — expected return in 6 weeks.",
                "Parental leave approved. Replacement assigned.",
                "Personal leave — approved by department head.",
            ]),
            "performance_rating|rating": "meets_expectations",
            "termination_reason|exit_reason": None,
        },
        description="Employee on approved leave",
    ),
]

# ── E-commerce scenarios ──────────────────────────────────────

_ECOMMERCE_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="order_delivered_successfully",
        category="happy_path",
        domain="ecommerce",
        field_values={
            "status|state": "delivered",
            "notes|comment": "Package delivered. Signature obtained.",
            "payment_status|pay_status": "paid",
            "shipping_method|ship_method": lambda: random.choice(["express", "standard", "priority"]),
            "return_reason|refund_reason": None,
            "amount|total|order_total": lambda: round(random.uniform(25, 500), 2),
        },
        description="Order successfully delivered",
    ),
    ScenarioTemplate(
        name="order_returned_defective",
        category="edge_case",
        domain="ecommerce",
        field_values={
            "status|state": "returned",
            "notes|comment": "Customer reported defective item. Return label sent.",
            "payment_status|pay_status": "refund_pending",
            "return_reason|refund_reason": "defective_product",
            "amount|total|order_total": lambda: round(random.uniform(50, 300), 2),
        },
        description="Order returned due to defective product",
    ),
    ScenarioTemplate(
        name="order_cancelled_by_customer",
        category="happy_path",
        domain="ecommerce",
        field_values={
            "status|state": "cancelled",
            "notes|comment": "Cancelled by customer before shipment.",
            "payment_status|pay_status": "refunded",
            "return_reason|refund_reason": "customer_request",
            "amount|total|order_total": lambda: round(random.uniform(10, 200), 2),
        },
        description="Order cancelled before fulfillment",
    ),
    ScenarioTemplate(
        name="order_payment_failed",
        category="edge_case",
        domain="ecommerce",
        field_values={
            "status|state": "payment_failed",
            "notes|comment": "Payment declined. Customer notified to update payment method.",
            "payment_status|pay_status": "failed",
            "return_reason|refund_reason": None,
            "amount|total|order_total": lambda: round(random.uniform(100, 2000), 2),
        },
        description="Order not processed due to payment failure",
    ),
]

# ── DevOps scenarios ──────────────────────────────────────────

_DEVOPS_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="pipeline_success",
        category="happy_path",
        domain="devops",
        field_values={
            "status|state": "success",
            "notes|comment": "Build and all tests passed. Deployed to staging.",
            "error_message|err_msg": None,
            "duration|elapsed|execution_time": lambda: random.randint(30, 300),
            "exit_code|return_code": 0,
        },
        description="Successful pipeline execution",
    ),
    ScenarioTemplate(
        name="pipeline_failed_tests",
        category="happy_path",
        domain="devops",
        field_values={
            "status|state": "failed",
            "notes|comment": "Unit tests failed — 3 assertions broken after merge.",
            "error_message|err_msg": "AssertionError: Expected 200, got 500 in test_api_health",
            "duration|elapsed|execution_time": lambda: random.randint(60, 180),
            "exit_code|return_code": 1,
        },
        description="Pipeline failed due to test failures",
    ),
    ScenarioTemplate(
        name="scan_vulnerabilities_found",
        category="edge_case",
        domain="devops",
        field_values={
            "status|state": "completed_with_findings",
            "notes|comment": "Security scan completed. 5 critical CVEs identified.",
            "error_message|err_msg": None,
            "duration|elapsed|execution_time": lambda: random.randint(120, 600),
            "vulns_critical|critical_count": lambda: random.randint(1, 8),
            "vulns_high|high_count": lambda: random.randint(2, 15),
        },
        description="Security scan found critical vulnerabilities",
    ),
    ScenarioTemplate(
        name="deployment_rollback",
        category="edge_case",
        domain="devops",
        field_values={
            "status|state": "rolled_back",
            "notes|comment": "Health check failed post-deploy. Automatic rollback triggered.",
            "error_message|err_msg": "HealthCheckTimeout: Service /health did not respond within 30s",
            "duration|elapsed|execution_time": lambda: random.randint(30, 90),
            "exit_code|return_code": 2,
        },
        description="Deployment rolled back after health check failure",
    ),
]

# ── Domain → scenarios registry ───────────────────────────────

_DOMAIN_SCENARIOS: dict[str, list[ScenarioTemplate]] = {
    "insurance": _INSURANCE_SCENARIOS,
    "banking": _BANKING_SCENARIOS,
    "healthcare": _HEALTHCARE_SCENARIOS,
    "hr": _HR_SCENARIOS,
    "ecommerce": _ECOMMERCE_SCENARIOS,
    "devops": _DEVOPS_SCENARIOS,
}

# ── General fallback scenarios ────────────────────────────────

_GENERAL_SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        name="record_active",
        category="happy_path",
        domain="general",
        field_values={
            "status|state": "active",
            "notes|comment": "Record active and in good standing.",
            "is_active|active": True,
        },
        description="Standard active record",
    ),
    ScenarioTemplate(
        name="record_pending_review",
        category="happy_path",
        domain="general",
        field_values={
            "status|state": "pending",
            "notes|comment": "Awaiting review by assigned team.",
            "is_active|active": True,
        },
        description="Record pending review",
    ),
    ScenarioTemplate(
        name="record_completed",
        category="happy_path",
        domain="general",
        field_values={
            "status|state": "completed",
            "notes|comment": "All steps completed successfully.",
            "is_active|active": False,
        },
        description="Completed/closed record",
    ),
    ScenarioTemplate(
        name="record_rejected",
        category="edge_case",
        domain="general",
        field_values={
            "status|state": "rejected",
            "notes|comment": "Rejected — does not meet acceptance criteria.",
            "reason|rejection_reason": "criteria_not_met",
            "is_active|active": False,
        },
        description="Record rejected",
    ),
]


# ── Scenario resolution engine ────────────────────────────────

def _resolve_value(val: Any) -> Any:
    """Resolve a value — if callable, invoke it."""
    if callable(val):
        return val()
    return val


def _match_scenario_field(col_name: str, field_pattern: str) -> bool:
    """Check if a column name matches a scenario field pattern (pipe-separated)."""
    col_lower = col_name.lower()
    patterns = field_pattern.split("|")
    return any(p in col_lower for p in patterns)


def _apply_scenario_to_row(
    scenario: ScenarioTemplate,
    columns: list[ColumnMetadata],
    check_constraints: dict[str, str | None],
) -> dict[str, Any]:
    """Apply a scenario template to produce a coherent row.

    For each column, if the scenario defines a value for a matching pattern,
    use that value. CHECK constraints override scenario values when they
    define an enum.
    """
    from app.utils.sql_types import extract_enum_from_check

    row: dict[str, Any] = {}
    for col in columns:
        # Skip PK columns — they'll be generated separately
        if col.is_primary_key:
            row[col.name] = None  # placeholder, filled by generator
            continue

        # Try to find a matching field in the scenario
        matched_value = _UNSET
        for field_pattern, value in scenario.field_values.items():
            if _match_scenario_field(col.name, field_pattern):
                matched_value = _resolve_value(value)
                break

        if matched_value is _UNSET:
            row[col.name] = None  # no scenario value — will be filled by fallback
            continue

        # If column has CHECK enum, validate/coerce the scenario value
        enum_values = extract_enum_from_check(check_constraints.get(col.name))
        if enum_values and matched_value is not None:
            # Find best match from allowed enum
            matched_str = str(matched_value).lower()
            exact = [e for e in enum_values if e.lower() == matched_str]
            if exact:
                row[col.name] = exact[0]
            else:
                # Fuzzy: find enum value containing scenario value or vice versa
                fuzzy = [e for e in enum_values if matched_str in e.lower() or e.lower() in matched_str]
                row[col.name] = fuzzy[0] if fuzzy else random.choice(enum_values)
        else:
            row[col.name] = matched_value

    return row


# Sentinel for "no value set"
_UNSET = object()


# ── Scenario selection strategy ───────────────────────────────

def _select_scenarios(
    scenarios: list[ScenarioTemplate],
    n: int,
    distribution: dict[str, float] | None = None,
) -> list[ScenarioTemplate]:
    """Select n scenarios with a realistic distribution across categories.

    Default distribution:
      happy_path: 60%
      edge_case: 20%
      boundary: 10%
      invalid: 10%
    """
    dist = distribution or {
        "happy_path": 0.60,
        "edge_case": 0.20,
        "boundary": 0.10,
        "invalid": 0.10,
    }

    # Group scenarios by category
    by_category: dict[str, list[ScenarioTemplate]] = {}
    for s in scenarios:
        by_category.setdefault(s.category, []).append(s)

    selected: list[ScenarioTemplate] = []
    for _ in range(n):
        # Pick category based on distribution
        roll = random.random()
        cumulative = 0.0
        chosen_cat = "happy_path"
        for cat, weight in dist.items():
            cumulative += weight
            if roll <= cumulative:
                chosen_cat = cat
                break

        # Pick from available scenarios in that category (with fallback)
        pool = by_category.get(chosen_cat) or by_category.get("happy_path", scenarios)
        selected.append(random.choice(pool))

    return selected


# ── Public API ────────────────────────────────────────────────

class ScenarioResult:
    """Result of scenario-driven generation for a single table."""

    __slots__ = ("table_name", "domain", "scenarios_used", "rows", "dependency_mappings")

    def __init__(
        self,
        table_name: str,
        domain: str,
        scenarios_used: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        dependency_mappings: list[dict[str, Any]],
    ):
        self.table_name = table_name
        self.domain = domain
        self.scenarios_used = scenarios_used
        self.rows = rows
        self.dependency_mappings = dependency_mappings

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "domain": self.domain,
            "scenarios_used": self.scenarios_used,
            "row_count": len(self.rows),
            "rows": self.rows,
            "dependency_mappings": self.dependency_mappings,
        }


def generate_scenario_rows(
    table: TableMetadata,
    n: int = 100,
    distribution: dict[str, float] | None = None,
) -> ScenarioResult:
    """Generate n rows for a table using scenario-driven logic.

    Each row is derived from a complete business scenario — fields are
    never generated independently.
    """
    domain = _infer_domain(table.name)
    if domain == "general":
        # Try inferring from column names
        col_text = " ".join(c.name.lower() for c in table.columns)
        domain = _infer_domain(col_text)

    scenarios = _DOMAIN_SCENARIOS.get(domain, _GENERAL_SCENARIOS)

    # Select scenarios for n rows
    selected = _select_scenarios(scenarios, n, distribution)

    # Build check constraint map
    check_constraints: dict[str, str | None] = {
        c.name: c.check_constraint for c in table.columns
    }

    # Generate rows
    rows: list[dict[str, Any]] = []
    scenarios_used: list[dict[str, Any]] = []
    scenario_counts: dict[str, int] = {}

    for scenario in selected:
        row = _apply_scenario_to_row(scenario, table.columns, check_constraints)
        rows.append(row)
        scenario_counts[scenario.name] = scenario_counts.get(scenario.name, 0) + 1

    # Build scenario usage summary
    for name, count in scenario_counts.items():
        template = next(s for s in scenarios if s.name == name)
        scenarios_used.append({
            **template.to_dict(),
            "count": count,
            "percentage": round(count / n * 100, 1),
        })
    scenarios_used.sort(key=lambda x: x["count"], reverse=True)

    # Build dependency mappings (which fields were driven by which scenario fields)
    dep_mappings = _extract_dependency_mappings(table.columns, scenarios)

    return ScenarioResult(
        table_name=table.name,
        domain=domain,
        scenarios_used=scenarios_used,
        rows=rows,
        dependency_mappings=dep_mappings,
    )


def _extract_dependency_mappings(
    columns: list[ColumnMetadata],
    scenarios: list[ScenarioTemplate],
) -> list[dict[str, Any]]:
    """Extract which columns are interdependent based on scenario templates."""
    # Find columns that co-appear in scenario field_values
    dependencies: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    col_names = [c.name for c in columns]

    for scenario in scenarios:
        # Find which actual columns this scenario controls
        controlled_cols: list[str] = []
        for col in col_names:
            for field_pattern in scenario.field_values:
                if _match_scenario_field(col, field_pattern):
                    controlled_cols.append(col)
                    break

        # All controlled columns are interdependent
        for i, src in enumerate(controlled_cols):
            for tgt in controlled_cols[i + 1:]:
                pair = (min(src, tgt), max(src, tgt))
                if pair not in seen:
                    seen.add(pair)
                    dependencies.append({
                        "source": src,
                        "target": tgt,
                        "relationship": "scenario_co_dependency",
                        "scenario": scenario.name,
                    })

    return dependencies


def get_available_scenarios(domain: str | None = None) -> dict[str, Any]:
    """List all available scenarios, optionally filtered by domain."""
    result: dict[str, list[dict[str, Any]]] = {}

    if domain:
        scenarios = _DOMAIN_SCENARIOS.get(domain, _GENERAL_SCENARIOS)
        result[domain] = [s.to_dict() for s in scenarios]
    else:
        for d, scenarios in _DOMAIN_SCENARIOS.items():
            result[d] = [s.to_dict() for s in scenarios]
        result["general"] = [s.to_dict() for s in _GENERAL_SCENARIOS]

    return {"domains": result}
