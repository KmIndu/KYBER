"""Smart Edge-Case Engine â€” generates scenario-aware failure rows.

Produces coherent failure scenarios per domain (insurance, banking,
healthcare, ecommerce, HR) where all fields in a row tell a consistent
failure story â€” e.g., a rejected claim with no approved_amount, a fraud
flag with escalation, a timeout with no completion date.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.schema import SchemaMetadata, TableMetadata


# â”€â”€ Result Models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class FailureScenario:
    """A single coherent failure scenario for one table."""
    scenario_id: str
    table: str
    name: str
    category: str  # rejection, timeout, duplication, fraud, system_error, etc.
    description: str
    field_values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "table": self.table,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "field_values": self.field_values,
        }


@dataclass
class SmartEdgeCaseResult:
    """Result from smart edge-case generation."""
    session_id: str
    domain_detected: str
    tables_analyzed: int
    scenarios: list[FailureScenario]
    scenarios_per_category: dict[str, int] = field(default_factory=dict)
    coverage_summary: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_scenarios(self) -> int:
        return len(self.scenarios)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "domain_detected": self.domain_detected,
            "tables_analyzed": self.tables_analyzed,
            "total_scenarios": self.total_scenarios,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "scenarios_per_category": self.scenarios_per_category,
            "coverage_summary": self.coverage_summary,
        }


# â”€â”€ Domain Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DOMAIN_SIGNALS: dict[str, list[re.Pattern]] = {
    "insurance": [
        re.compile(r"claim|policy|premium|coverage|adjuster|beneficiar|expiry|insur", re.I),
    ],
    "banking": [
        re.compile(r"transaction|account|balance|transfer|ledger|payment.*status|deposit|withdraw", re.I),
    ],
    "healthcare": [
        re.compile(r"patient|diagnosis|prescription|appointment|hospital|doctor|medical|health_record", re.I),
    ],
    "ecommerce": [
        re.compile(r"order|cart|product|shipment|inventory|coupon|checkout|shipping", re.I),
    ],
    "hr": [
        re.compile(r"employee|salary|leave|department|termination|hiring|payroll|attendance", re.I),
    ],
}


# â”€â”€ Scenario Templates Per Domain â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _insurance_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate insurance-specific failure scenarios."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    # Rejection scenario
    if "claim_status" in cols or "status" in cols:
        vals: dict[str, Any] = {}
        status_col = "claim_status" if "claim_status" in cols else "status"
        vals[status_col] = "rejected"
        if "denial_reason" in cols:
            vals["denial_reason"] = "Insufficient documentation"
        if "approved_amount" in cols:
            vals["approved_amount"] = 0
        if "document_verified" in cols:
            vals["document_verified"] = False
        if "is_active" in cols:
            vals["is_active"] = False
        if "notes" in cols:
            vals["notes"] = "Claim rejected due to missing medical records"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="claim_rejection_missing_docs",
            category="rejection",
            description="Claim rejected because required documentation is missing",
            field_values=vals,
        ))

    # Fraud scenario
    if "fraud_flag" in cols or "escalated" in cols:
        vals = {}
        if "fraud_flag" in cols:
            vals["fraud_flag"] = True
        if "escalated" in cols:
            vals["escalated"] = True
        if "claim_status" in cols:
            vals["claim_status"] = "under_investigation"
        elif "status" in cols:
            vals["status"] = "under_investigation"
        if "is_active" in cols:
            vals["is_active"] = True
        if "notes" in cols:
            vals["notes"] = "Suspicious pattern detected â€” escalated to SIU"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="fraud_escalation",
            category="fraud",
            description="Claim flagged for suspected fraud and escalated",
            field_values=vals,
        ))

    # Duplicate scenario
    if "is_duplicate" in cols:
        vals = {"is_duplicate": True}
        if "original_ref" in cols:
            vals["original_ref"] = "CLM-2024-00123"
        if "claim_status" in cols:
            vals["claim_status"] = "duplicate"
        elif "status" in cols:
            vals["status"] = "duplicate"
        if "approved_amount" in cols:
            vals["approved_amount"] = 0
        if "notes" in cols:
            vals["notes"] = "Duplicate claim â€” original reference attached"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="duplicate_claim",
            category="duplication",
            description="Claim identified as a duplicate submission",
            field_values=vals,
        ))

    # Expired policy scenario
    if "policy_status" in cols or "expiry_date" in cols:
        vals = {}
        if "policy_status" in cols:
            vals["policy_status"] = "expired"
        if "is_active" in cols:
            vals["is_active"] = False
        if "expiry_date" in cols:
            vals["expiry_date"] = "2023-01-01"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="expired_policy",
            category="rejection",
            description="Policy expired before claim submission",
            field_values=vals,
        ))

    return scenarios


def _banking_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate banking-specific failure scenarios."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    # Timeout scenario
    status_col = next((c for c in cols if "status" in c.lower()), None)
    if status_col:
        vals: dict[str, Any] = {status_col: "timeout"}
        if "completed_at" in cols:
            vals["completed_at"] = None
        if "is_successful" in cols:
            vals["is_successful"] = False
        if "error_code" in cols:
            vals["error_code"] = "TIMEOUT_EXCEEDED"
        if "error_message" in cols:
            vals["error_message"] = "Transaction timed out after maximum wait period"
        if "retry_count" in cols:
            vals["retry_count"] = 3
        if "notes" in cols:
            vals["notes"] = "Gateway timeout â€” max retries exhausted"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="transaction_timeout",
            category="timeout",
            description="Transaction timed out after maximum retry attempts",
            field_values=vals,
        ))

    # Insufficient funds
    if status_col and "balance_after" in cols:
        vals = {status_col: "failed"}
        if "error_code" in cols:
            vals["error_code"] = "INSUFFICIENT_FUNDS"
        if "error_message" in cols:
            vals["error_message"] = "Account balance insufficient for transaction"
        if "is_successful" in cols:
            vals["is_successful"] = False
        if "completed_at" in cols:
            vals["completed_at"] = None
        if "balance_after" in cols:
            vals["balance_after"] = 0.0
        if "notes" in cols:
            vals["notes"] = "Declined â€” insufficient balance"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="insufficient_funds",
            category="rejection",
            description="Transaction declined due to insufficient funds",
            field_values=vals,
        ))

    # Duplicate transaction
    if "is_duplicate" in cols:
        vals = {"is_duplicate": True}
        if "original_ref" in cols:
            vals["original_ref"] = "TXN-2024-98765"
        if status_col:
            vals[status_col] = "duplicate"
        if "is_successful" in cols:
            vals["is_successful"] = False
        if "error_code" in cols:
            vals["error_code"] = "DUPLICATE_TRANSACTION"
        if "notes" in cols:
            vals["notes"] = "Duplicate detected â€” original reference linked"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="duplicate_transaction",
            category="duplication",
            description="Transaction identified as a duplicate",
            field_values=vals,
        ))

    # System error
    if status_col and "error_code" in cols:
        vals = {status_col: "error"}
        vals["error_code"] = "SYSTEM_ERROR_500"
        if "error_message" in cols:
            vals["error_message"] = "Internal processing error"
        if "is_successful" in cols:
            vals["is_successful"] = False
        if "completed_at" in cols:
            vals["completed_at"] = None
        if "notes" in cols:
            vals["notes"] = "System error â€” pending manual review"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="system_error",
            category="system_error",
            description="Transaction failed due to internal system error",
            field_values=vals,
        ))

    return scenarios


def _ecommerce_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate e-commerce failure scenarios."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    status_col = next((c for c in cols if "status" in c.lower() and "inventory" not in c.lower()), None)

    # Payment failed
    if "payment_success" in cols or status_col:
        vals: dict[str, Any] = {}
        if "payment_success" in cols:
            vals["payment_success"] = False
        if status_col:
            vals[status_col] = "payment_failed"
        if "shipped" in cols:
            vals["shipped"] = False
        if "ship_date" in cols:
            vals["ship_date"] = None
        if "error_code" in cols:
            vals["error_code"] = "PAYMENT_DECLINED"
        if "fraud_flag" in cols:
            vals["fraud_flag"] = False
        if "notes" in cols:
            vals["notes"] = "Payment declined by processor"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="payment_failure",
            category="rejection",
            description="Order payment was declined",
            field_values=vals,
        ))

    # Out of stock
    if "inventory_status" in cols:
        vals = {"inventory_status": "out_of_stock"}
        if status_col:
            vals[status_col] = "cancelled"
        if "shipped" in cols:
            vals["shipped"] = False
        if "ship_date" in cols:
            vals["ship_date"] = None
        if "notes" in cols:
            vals["notes"] = "Cancelled â€” product out of stock"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="out_of_stock",
            category="system_error",
            description="Order cancelled due to inventory unavailability",
            field_values=vals,
        ))

    # Fraud hold
    if "fraud_flag" in cols:
        vals = {"fraud_flag": True}
        if status_col:
            vals[status_col] = "on_hold"
        if "shipped" in cols:
            vals["shipped"] = False
        if "address_verified" in cols:
            vals["address_verified"] = False
        if "notes" in cols:
            vals["notes"] = "Order held for fraud review â€” address mismatch"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="fraud_hold",
            category="fraud",
            description="Order held due to suspected fraud",
            field_values=vals,
        ))

    return scenarios


def _hr_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate HR failure scenarios."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    status_col = next((c for c in cols if "status" in c.lower()), None)

    # Termination
    if "termination_date" in cols or (status_col and "employee" in tbl.lower()):
        vals: dict[str, Any] = {}
        if status_col:
            vals[status_col] = "terminated"
        if "is_active" in cols:
            vals["is_active"] = False
        if "termination_date" in cols:
            vals["termination_date"] = "2024-06-15"
        if "access_revoked" in cols:
            vals["access_revoked"] = True
        if "notes" in cols:
            vals["notes"] = "Employment terminated â€” exit process completed"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="employee_termination",
            category="rejection",
            description="Employee terminated and access revoked",
            field_values=vals,
        ))

    # Leave denial
    if "leave_status" in cols or "rejection_reason" in cols:
        vals = {}
        if status_col:
            vals[status_col] = "denied"
        if "approved" in cols:
            vals["approved"] = False
        if "rejection_reason" in cols:
            vals["rejection_reason"] = "Insufficient leave balance"
        if "balance" in cols:
            vals["balance"] = 0
        if "notes" in cols:
            vals["notes"] = "Leave denied â€” balance exhausted"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="leave_denial_no_balance",
            category="rejection",
            description="Leave request denied due to insufficient balance",
            field_values=vals,
        ))

    return scenarios


def _healthcare_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate healthcare failure scenarios."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    status_col = next((c for c in cols if "status" in c.lower()), None)

    if status_col:
        vals: dict[str, Any] = {status_col: "cancelled"}
        if "notes" in cols:
            vals["notes"] = "Appointment cancelled by patient"
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="appointment_cancellation",
            category="rejection",
            description="Healthcare appointment cancelled",
            field_values=vals,
        ))

    return scenarios


def _generic_scenarios(table: TableMetadata) -> list[FailureScenario]:
    """Generate generic failure scenarios when domain is unknown."""
    cols = {c.name for c in table.columns}
    scenarios: list[FailureScenario] = []
    tbl = table.name

    status_col = next((c for c in cols if "status" in c.lower()), None)

    if status_col:
        # Generic failure
        vals: dict[str, Any] = {status_col: "failed"}
        if "is_valid" in cols:
            vals["is_valid"] = False
        if "has_errors" in cols:
            vals["has_errors"] = True
        if "amount" in cols:
            vals["amount"] = 0
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="generic_failure",
            category="system_error",
            description="Record failed processing",
            field_values=vals,
        ))

        # Generic rejection
        vals2: dict[str, Any] = {status_col: "rejected"}
        if "is_valid" in cols:
            vals2["is_valid"] = False
        if "has_errors" in cols:
            vals2["has_errors"] = True
        scenarios.append(FailureScenario(
            scenario_id=str(uuid.uuid4()),
            table=tbl, name="generic_rejection",
            category="rejection",
            description="Record rejected during validation",
            field_values=vals2,
        ))

    return scenarios


# â”€â”€ Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DOMAIN_GENERATORS: dict[str, Any] = {
    "insurance": _insurance_scenarios,
    "banking": _banking_scenarios,
    "healthcare": _healthcare_scenarios,
    "ecommerce": _ecommerce_scenarios,
    "hr": _hr_scenarios,
}


class SmartEdgeCaseEngine:
    """Generates domain-aware, scenario-coherent failure rows."""

    def __init__(
        self,
        schema: SchemaMetadata,
        target_scenarios_per_table: int = 5,
    ) -> None:
        self._schema = schema
        self._target = target_scenarios_per_table

    def _detect_domain(self) -> str:
        """Detect the business domain from table/column names."""
        scores: dict[str, int] = {d: 0 for d in _DOMAIN_SIGNALS}

        all_names = []
        for table in self._schema.tables:
            all_names.append(table.name)
            for col in table.columns:
                all_names.append(col.name)

        text = " ".join(all_names)

        for domain, patterns in _DOMAIN_SIGNALS.items():
            for pat in patterns:
                scores[domain] += len(pat.findall(text))

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best] == 0:
            return "general"
        return best

    def generate(self, session_id: str = "") -> SmartEdgeCaseResult:
        """Generate smart edge-case scenarios for all tables."""
        domain = self._detect_domain()
        scenarios: list[FailureScenario] = []
        coverage: dict[str, list[str]] = {}

        gen_fn = _DOMAIN_GENERATORS.get(domain, _generic_scenarios)

        for table in self._schema.tables:
            table_scenarios = gen_fn(table)

            # If domain-specific generator produced nothing, try generic
            if not table_scenarios:
                table_scenarios = _generic_scenarios(table)

            # Limit to target per table
            table_scenarios = table_scenarios[:self._target]
            scenarios.extend(table_scenarios)
            coverage[table.name] = [s.name for s in table_scenarios]

        # Build category counts
        per_category: dict[str, int] = {}
        for s in scenarios:
            per_category[s.category] = per_category.get(s.category, 0) + 1

        return SmartEdgeCaseResult(
            session_id=session_id,
            domain_detected=domain,
            tables_analyzed=len(self._schema.tables),
            scenarios=scenarios,
            scenarios_per_category=per_category,
            coverage_summary=coverage,
        )
