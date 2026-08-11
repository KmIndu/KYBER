"""Workflow state consistency engine.

Ensures workflow-related fields remain logically consistent within each row:
- status=approved → success comments, no rejection_reason
- status=rejected → rejection_reason filled, no success_message
- status=closed → is_active=false, closed_date set
- status=pending → no completed_date, active_flag=true

Implements:
- State machine modeling per domain
- Valid transition mapping
- Contradiction prevention rules
- Workflow-aware generation of all related fields
- Status validation with boolean/date/message coherence
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any


# ── State Machine Definitions ────────────────────────────────
# Each domain defines states with their properties:
# - which fields should be filled/empty
# - what boolean flags should be set
# - what kind of messages/reasons are appropriate

@dataclass
class StateProperties:
    """Properties associated with a workflow state."""
    # Whether this state implies the record is "active"
    is_active: bool = True
    # Whether this state implies the record is "closed"/"done"
    is_closed: bool = False
    # Whether a completion/resolution date should be set
    has_completion_date: bool = False
    # Whether a rejection/denial reason should be present
    has_rejection_reason: bool = False
    # Whether a success/approval message should be present
    has_success_message: bool = False
    # Whether an error/failure message should be present
    has_error_message: bool = False
    # Whether the record is in a terminal state
    is_terminal: bool = False
    # Notes/comments template category
    notes_category: str = "neutral"
    # Probability weight for this state in generation
    weight: float = 1.0


# ── Domain State Machines ────────────────────────────────────

_INSURANCE_STATES: dict[str, StateProperties] = {
    "pending": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "under_review": StateProperties(
        is_active=True, notes_category="progress", weight=1.5,
    ),
    "approved": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "denied": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.5,
    ),
    "rejected": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.0,
    ),
    "closed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="resolution", weight=1.0,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
    "expired": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="expiry", weight=0.5,
    ),
}

_BANKING_STATES: dict[str, StateProperties] = {
    "pending": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "processing": StateProperties(
        is_active=True, notes_category="progress", weight=1.5,
    ),
    "approved": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "rejected": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.5,
    ),
    "completed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=2.0,
    ),
    "failed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_error_message=True, is_terminal=True, notes_category="negative", weight=1.0,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
    "on_hold": StateProperties(
        is_active=True, notes_category="waiting", weight=0.5,
    ),
}

_HEALTHCARE_STATES: dict[str, StateProperties] = {
    "scheduled": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "active": StateProperties(
        is_active=True, notes_category="progress", weight=2.0,
    ),
    "in_treatment": StateProperties(
        is_active=True, notes_category="progress", weight=1.5,
    ),
    "discharged": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=2.0,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
    "completed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=1.5,
    ),
    "no_show": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="negative", weight=0.5,
    ),
}

_DEVOPS_STATES: dict[str, StateProperties] = {
    "queued": StateProperties(
        is_active=True, notes_category="waiting", weight=1.0,
    ),
    "in_progress": StateProperties(
        is_active=True, notes_category="progress", weight=2.0,
    ),
    "running": StateProperties(
        is_active=True, notes_category="progress", weight=1.5,
    ),
    "success": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "passed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=2.0,
    ),
    "failed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_error_message=True, is_terminal=True, notes_category="negative", weight=2.0,
    ),
    "error": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_error_message=True, is_terminal=True, notes_category="negative", weight=1.0,
    ),
    "skipped": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="neutral", weight=0.5,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
}

_HR_STATES: dict[str, StateProperties] = {
    "submitted": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "under_review": StateProperties(
        is_active=True, notes_category="progress", weight=1.5,
    ),
    "approved": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "rejected": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.5,
    ),
    "withdrawn": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
    "onboarding": StateProperties(
        is_active=True, notes_category="progress", weight=1.0,
    ),
    "active": StateProperties(
        is_active=True, notes_category="neutral", weight=2.0,
    ),
    "terminated": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="negative", weight=0.5,
    ),
}

_ECOMMERCE_STATES: dict[str, StateProperties] = {
    "pending": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "confirmed": StateProperties(
        is_active=True, notes_category="progress", weight=2.0,
    ),
    "shipped": StateProperties(
        is_active=True, notes_category="progress", weight=2.0,
    ),
    "delivered": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "returned": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.0,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="cancellation", weight=1.0,
    ),
    "refunded": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="resolution", weight=0.5,
    ),
}

_GENERAL_STATES: dict[str, StateProperties] = {
    "active": StateProperties(
        is_active=True, notes_category="progress", weight=2.5,
    ),
    "pending": StateProperties(
        is_active=True, notes_category="waiting", weight=2.0,
    ),
    "in_progress": StateProperties(
        is_active=True, notes_category="progress", weight=2.0,
    ),
    "completed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=3.0,
    ),
    "approved": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_success_message=True, is_terminal=True, notes_category="positive", weight=2.0,
    ),
    "rejected": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_rejection_reason=True, is_terminal=True, notes_category="negative", weight=1.5,
    ),
    "failed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        has_error_message=True, is_terminal=True, notes_category="negative", weight=1.0,
    ),
    "closed": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="resolution", weight=1.5,
    ),
    "cancelled": StateProperties(
        is_active=False, is_closed=True, has_completion_date=True,
        is_terminal=True, notes_category="cancellation", weight=0.5,
    ),
}

_DOMAIN_STATE_MACHINES: dict[str, dict[str, StateProperties]] = {
    "insurance": _INSURANCE_STATES,
    "banking": _BANKING_STATES,
    "healthcare": _HEALTHCARE_STATES,
    "devops": _DEVOPS_STATES,
    "hr": _HR_STATES,
    "ecommerce": _ECOMMERCE_STATES,
    "retail": _ECOMMERCE_STATES,
    "general": _GENERAL_STATES,
}


# ── Message/Reason Pools ─────────────────────────────────────

_REJECTION_REASONS: dict[str, list[str]] = {
    "insurance": [
        "Pre-existing condition exclusion applies",
        "Policy was not active at time of incident",
        "Insufficient documentation provided",
        "Claim exceeds maximum coverage limit",
        "Filed past submission deadline",
        "Duplicate claim already processed",
        "Non-covered procedure per policy terms",
        "Exclusion clause 4.2(b) applies",
    ],
    "banking": [
        "Insufficient funds in account",
        "Failed AML/KYC compliance check",
        "Credit score below minimum threshold",
        "Suspicious activity flag raised",
        "Daily transaction limit exceeded",
        "Invalid beneficiary account details",
        "Document verification failed",
        "Risk assessment threshold exceeded",
    ],
    "healthcare": [
        "Insurance pre-authorization denied",
        "Patient not eligible for procedure",
        "Referral not obtained from primary care",
        "Out-of-network provider not covered",
        "Prior treatment protocol not completed",
        "Medical necessity criteria not met",
    ],
    "hr": [
        "Does not meet minimum qualifications",
        "Failed background verification",
        "Position already filled",
        "Incomplete application package",
        "Salary expectations exceed budget",
        "Organizational restructuring — position eliminated",
    ],
    "ecommerce": [
        "Item out of stock — cannot fulfill",
        "Shipping address unverifiable",
        "Payment method declined",
        "Suspected fraudulent order",
        "Item no longer available from supplier",
        "Delivery restriction to specified region",
    ],
    "devops": [
        "Build compilation error in source module",
        "Critical CVE detected — blocking deployment",
        "Test coverage below threshold (< 80%)",
        "Integration tests timed out",
        "Docker image build failed — dependency conflict",
        "Security scan found HIGH severity issues",
        "Deployment target health check failed",
        "Configuration drift detected in environment",
    ],
    "general": [
        "Does not meet requirements",
        "Insufficient information provided",
        "Non-compliant with policy",
        "Out of scope for this process",
        "Returned for corrections",
        "Duplicate submission detected",
        "Authorization not granted",
        "Resource constraints prevent processing",
    ],
}

_SUCCESS_MESSAGES: dict[str, list[str]] = {
    "insurance": [
        "Claim approved — payment processing initiated",
        "All documentation verified successfully",
        "Coverage confirmed — settlement authorized",
        "Auto-approved: within policy limits",
        "Senior adjuster approved after review",
    ],
    "banking": [
        "Transaction completed successfully",
        "Funds transferred — confirmation sent",
        "Loan approved — disbursement scheduled",
        "Compliance review passed — cleared",
        "Account opened — welcome kit dispatched",
    ],
    "healthcare": [
        "Treatment completed — positive outcome",
        "Patient discharged — recovery on track",
        "Procedure successful — follow-up scheduled",
        "All vitals within normal range",
        "Treatment goals achieved ahead of schedule",
    ],
    "hr": [
        "Application approved — offer letter sent",
        "Leave request approved by manager",
        "Promotion approved — effective next cycle",
        "Training certification completed",
        "Performance review completed — exceeds expectations",
    ],
    "ecommerce": [
        "Order delivered — confirmed by recipient",
        "Refund processed — credited to original payment",
        "Return accepted — replacement shipped",
        "Order fulfilled — tracking number sent",
        "Payment confirmed — order processing",
    ],
    "devops": [
        "Build passed — all 847 tests green",
        "Deployment successful — health checks passing",
        "Security scan clean — no vulnerabilities found",
        "Pipeline completed in 3m 42s",
        "All quality gates passed — merged to main",
    ],
    "general": [
        "Request completed successfully",
        "All criteria met — approved",
        "Processing finished — no issues found",
        "Verified and closed — no further action",
        "Completed within SLA timeframe",
    ],
}

_ERROR_MESSAGES: dict[str, list[str]] = {
    "insurance": [
        "System error during policy validation",
        "External service timeout — retry required",
        "Document OCR processing failed",
        "Payment gateway returned error code 502",
    ],
    "banking": [
        "Core banking system timeout",
        "SWIFT network communication failure",
        "Transaction deadlock — automatic rollback",
        "Settlement system returned error",
    ],
    "healthcare": [
        "Lab system integration error",
        "Electronic health record sync failed",
        "Pharmacy system connectivity lost",
        "Imaging system returned invalid response",
    ],
    "devops": [
        "Container runtime OOM killed process",
        "Network timeout connecting to artifact registry",
        "Pipeline agent lost connection",
        "Kubernetes pod CrashLoopBackOff",
        "Memory limit exceeded during analysis",
        "Git authentication token expired",
    ],
    "general": [
        "Unexpected system error occurred",
        "External dependency timeout",
        "Processing failed — manual intervention required",
        "Service unavailable — retry scheduled",
    ],
}

_CANCELLATION_NOTES: dict[str, list[str]] = {
    "insurance": [
        "Cancelled at policyholder request",
        "Withdrawn — claimant found alternative resolution",
        "Superseded by updated claim submission",
    ],
    "banking": [
        "Cancelled by account holder",
        "Transaction recalled before settlement",
        "Customer chose alternative product",
    ],
    "healthcare": [
        "Cancelled at patient request",
        "Rescheduled to different date",
        "Provider unavailable — patient notified",
    ],
    "hr": [
        "Withdrawn by applicant",
        "Position closed — hiring freeze",
        "Candidate accepted other offer",
    ],
    "ecommerce": [
        "Cancelled by customer before shipping",
        "Seller cancelled — item unavailable",
        "Order auto-cancelled — payment timeout",
    ],
    "general": [
        "Cancelled at requestor's instruction",
        "No longer needed — withdrawn",
        "Superseded by newer request",
    ],
}


# ── Column Detection Patterns ────────────────────────────────

# Status columns
_STATUS_COL_PATTERN = re.compile(
    r"^status$|_status$|^state$|workflow[_\s]?state|^stage$", re.I
)
# Columns that match _STATUS_COL_PATTERN but have specialized semantics
_STATUS_COL_SKIP = re.compile(r"rag|virus|color|moderation", re.I)

# Boolean flag columns
_ACTIVE_FLAG_PATTERNS = [
    (re.compile(r"is[_\s]?active|active[_\s]?flag|is[_\s]?enabled", re.I), "active_true"),
    (re.compile(r"is[_\s]?closed|is[_\s]?complete|is[_\s]?done|is[_\s]?resolved", re.I), "closed_true"),
    (re.compile(r"is[_\s]?cancelled|is[_\s]?deleted|is[_\s]?archived", re.I), "cancelled_true"),
    (re.compile(r"is[_\s]?approved|is[_\s]?verified|is[_\s]?confirmed", re.I), "approved_true"),
    (re.compile(r"is[_\s]?rejected|is[_\s]?denied|is[_\s]?failed", re.I), "rejected_true"),
    (re.compile(r"is[_\s]?pending|is[_\s]?waiting|is[_\s]?queued", re.I), "pending_true"),
]

# Reason/message columns
_REASON_COL_PATTERNS = [
    (re.compile(r"rejection[_\s]?reason|denial[_\s]?reason|deny[_\s]?reason|"
                r"decline[_\s]?reason|refuse[_\s]?reason|fail[_\s]?reason", re.I), "rejection_reason"),
    (re.compile(r"approval[_\s]?note|success[_\s]?message|approval[_\s]?message|"
                r"completion[_\s]?note|resolution[_\s]?note", re.I), "success_message"),
    (re.compile(r"error[_\s]?message|failure[_\s]?message|error[_\s]?detail|"
                r"exception[_\s]?message|fail[_\s]?message", re.I), "error_message"),
    (re.compile(r"cancel[_\s]?reason|cancellation[_\s]?reason|"
                r"withdrawal[_\s]?reason", re.I), "cancellation_reason"),
    (re.compile(r"reason$|_reason$", re.I), "generic_reason"),
    (re.compile(r"notes?$|comment[s]?$|remark[s]?$", re.I), "notes"),
]

# Date columns tied to workflow state
_WORKFLOW_DATE_PATTERNS = [
    (re.compile(r"completed[_\s]?(at|on|date|time)|completion[_\s]?(date|time)", re.I), "completion_date"),
    (re.compile(r"closed[_\s]?(at|on|date|time)|close[_\s]?date", re.I), "completion_date"),
    (re.compile(r"resolved[_\s]?(at|on|date|time)|resolution[_\s]?(date|time)", re.I), "completion_date"),
    (re.compile(r"approved[_\s]?(at|on|date|time)|approval[_\s]?(date|time)", re.I), "completion_date"),
    (re.compile(r"rejected[_\s]?(at|on|date|time)|rejection[_\s]?(date|time)", re.I), "completion_date"),
    (re.compile(r"cancelled[_\s]?(at|on|date|time)|cancellation[_\s]?(date|time)", re.I), "completion_date"),
    (re.compile(r"started[_\s]?(at|on|date|time)|start[_\s]?(date|time)", re.I), "start_date"),
    (re.compile(r"submitted[_\s]?(at|on|date|time)|submission[_\s]?(date|time)", re.I), "start_date"),
]


@dataclass
class WorkflowColumnMapping:
    """Mapping of detected workflow-related columns in a table."""
    status_col: str | None = None
    active_flag_cols: dict[str, str] = field(default_factory=dict)  # col → flag_type
    reason_cols: dict[str, str] = field(default_factory=dict)       # col → reason_type
    date_cols: dict[str, str] = field(default_factory=dict)         # col → date_type


def detect_workflow_columns(column_names: list[str]) -> WorkflowColumnMapping:
    """Detect all workflow-related columns in a table.

    Returns a mapping of column names to their workflow role.
    """
    mapping = WorkflowColumnMapping()

    for col_name in column_names:
        # Status column
        if _STATUS_COL_PATTERN.search(col_name) and not _STATUS_COL_SKIP.search(col_name):
            mapping.status_col = col_name
            continue

        # Boolean flags
        for pattern, flag_type in _ACTIVE_FLAG_PATTERNS:
            if pattern.search(col_name):
                mapping.active_flag_cols[col_name] = flag_type
                break
        else:
            # Reason/message columns
            for pattern, reason_type in _REASON_COL_PATTERNS:
                if pattern.search(col_name):
                    mapping.reason_cols[col_name] = reason_type
                    break
            else:
                # Workflow dates
                for pattern, date_type in _WORKFLOW_DATE_PATTERNS:
                    if pattern.search(col_name):
                        mapping.date_cols[col_name] = date_type
                        break

    return mapping


def _infer_domain_from_table(table_name: str) -> str:
    """Infer business domain from table name."""
    tbl = table_name.lower()
    if any(k in tbl for k in ("claim", "policy", "premium", "coverage", "insur", "underwr")):
        return "insurance"
    if any(k in tbl for k in ("account", "transaction", "transfer", "loan", "payment", "bank")):
        return "banking"
    if any(k in tbl for k in ("patient", "appointment", "diagnosis", "treatment", "prescri", "medical")):
        return "healthcare"
    if any(k in tbl for k in ("pipeline", "deploy", "build", "scan", "release", "ci_", "cd_")):
        return "devops"
    if any(k in tbl for k in ("employee", "candidate", "applicant", "leave", "payroll", "recruit")):
        return "hr"
    if any(k in tbl for k in ("order", "cart", "product", "shipment", "delivery", "refund")):
        return "ecommerce"
    return "general"


def _pick_status_for_enum(
    allowed_statuses: list[str],
    state_machine: dict[str, StateProperties],
) -> tuple[str, StateProperties]:
    """Pick a status from the allowed list and find its closest state properties."""
    status = random.choice(allowed_statuses)
    s_normalized = status.lower().replace(" ", "_").replace("-", "_")

    # Try exact match
    if s_normalized in state_machine:
        return status, state_machine[s_normalized]

    # Try substring matching
    for key, props in state_machine.items():
        if key in s_normalized or s_normalized in key:
            return status, props

    # Infer from common keywords
    if any(k in s_normalized for k in ("approv", "success", "pass", "complet", "deliver")):
        return status, StateProperties(
            is_active=False, is_closed=True, has_completion_date=True,
            has_success_message=True, is_terminal=True, notes_category="positive",
        )
    if any(k in s_normalized for k in ("reject", "denied", "fail", "error", "decline")):
        return status, StateProperties(
            is_active=False, is_closed=True, has_completion_date=True,
            has_rejection_reason=True, is_terminal=True, notes_category="negative",
        )
    if any(k in s_normalized for k in ("cancel", "withdraw", "abort")):
        return status, StateProperties(
            is_active=False, is_closed=True, has_completion_date=True,
            is_terminal=True, notes_category="cancellation",
        )
    if any(k in s_normalized for k in ("pend", "wait", "queue", "submit", "hold")):
        return status, StateProperties(
            is_active=True, notes_category="waiting",
        )
    if any(k in s_normalized for k in ("active", "progress", "running", "process")):
        return status, StateProperties(
            is_active=True, notes_category="progress",
        )
    if any(k in s_normalized for k in ("close", "archiv", "done", "resolv")):
        return status, StateProperties(
            is_active=False, is_closed=True, has_completion_date=True,
            is_terminal=True, notes_category="resolution",
        )

    # Default: neutral active state
    return status, StateProperties(is_active=True, notes_category="neutral")


def _generate_date_value(has_date: bool) -> str | None:
    """Generate a date value or None based on state."""
    if not has_date:
        return None
    start = date(2023, 1, 1)
    days = (date(2026, 5, 1) - start).days
    d = start + timedelta(days=random.randint(0, days))
    return d.isoformat()


def _generate_datetime_value(has_date: bool) -> str | None:
    """Generate a datetime value or None based on state."""
    if not has_date:
        return None
    start = datetime(2023, 1, 1)
    secs = int((datetime(2026, 5, 1) - start).total_seconds())
    dt = start + timedelta(seconds=random.randint(0, secs))
    return dt.isoformat()


def resolve_workflow_columns(
    table_name: str,
    column_names: list[str],
    n: int,
    domain: str = "unknown",
    check_constraints: dict[str, str] | None = None,
) -> dict[str, list[Any]] | None:
    """Generate workflow-consistent column values for a table.

    Detects workflow columns, picks coherent states, and generates all
    related fields (status, flags, reasons, dates) that don't contradict.

    Args:
        table_name: Name of the table being generated.
        column_names: All column names in the table.
        n: Number of rows to generate.
        domain: Business domain (insurance, banking, etc.)
        check_constraints: Dict of col_name → CHECK constraint SQL for enum extraction.

    Returns:
        Dict mapping column_name → list of n values for all workflow-related columns,
        or None if no workflow columns detected (need status + at least one other).
    """
    from app.utils.sql_types import extract_enum_from_check

    mapping = detect_workflow_columns(column_names)

    # Need a status column plus at least one other workflow column
    if not mapping.status_col:
        return None
    has_related = (
        mapping.active_flag_cols or mapping.reason_cols or mapping.date_cols
    )
    if not has_related:
        return None

    # Determine domain
    effective_domain = domain if domain != "unknown" else _infer_domain_from_table(table_name)
    state_machine = _DOMAIN_STATE_MACHINES.get(effective_domain, _GENERAL_STATES)

    # Check if status has a CHECK constraint enum
    checks = check_constraints or {}
    allowed_statuses: list[str] | None = None
    if mapping.status_col and mapping.status_col in checks:
        allowed_statuses = extract_enum_from_check(checks[mapping.status_col])

    # Use state machine statuses if no CHECK constraint
    if not allowed_statuses:
        # Weight-based selection
        states_list = list(state_machine.keys())
        weights = [state_machine[s].weight for s in states_list]
        allowed_statuses = states_list

    # Get reason pools
    rejection_pool = _REJECTION_REASONS.get(effective_domain, _REJECTION_REASONS["general"])
    success_pool = _SUCCESS_MESSAGES.get(effective_domain, _SUCCESS_MESSAGES["general"])
    error_pool = _ERROR_MESSAGES.get(effective_domain, _ERROR_MESSAGES["general"])
    cancel_pool = _CANCELLATION_NOTES.get(effective_domain, _CANCELLATION_NOTES.get("general", ["Cancelled"]))

    # Generate n coherent rows
    result: dict[str, list[Any]] = {col: [] for col in [mapping.status_col]
                                     + list(mapping.active_flag_cols.keys())
                                     + list(mapping.reason_cols.keys())
                                     + list(mapping.date_cols.keys())}

    for _ in range(n):
        # Pick a state (weighted if using state machine statuses directly)
        if allowed_statuses:
            if all(s in state_machine for s in allowed_statuses):
                weights = [state_machine[s].weight for s in allowed_statuses]
                status = random.choices(allowed_statuses, weights=weights, k=1)[0]
                props = state_machine[status]
            else:
                status, props = _pick_status_for_enum(allowed_statuses, state_machine)
        else:
            status, props = _pick_status_for_enum(list(state_machine.keys()), state_machine)

        # Set status
        result[mapping.status_col].append(status)

        # Set boolean flags — logically consistent with state
        for col, flag_type in mapping.active_flag_cols.items():
            if flag_type == "active_true":
                result[col].append(props.is_active)
            elif flag_type == "closed_true":
                result[col].append(props.is_closed)
            elif flag_type == "cancelled_true":
                result[col].append(props.notes_category == "cancellation")
            elif flag_type == "approved_true":
                result[col].append(props.has_success_message and props.is_terminal)
            elif flag_type == "rejected_true":
                result[col].append(props.has_rejection_reason)
            elif flag_type == "pending_true":
                result[col].append(not props.is_terminal and props.is_active)
            else:
                result[col].append(False)

        # Set reason/message columns — only filled when appropriate
        for col, reason_type in mapping.reason_cols.items():
            if reason_type == "rejection_reason":
                if props.has_rejection_reason:
                    result[col].append(random.choice(rejection_pool))
                else:
                    result[col].append(None)
            elif reason_type == "success_message":
                if props.has_success_message:
                    result[col].append(random.choice(success_pool))
                else:
                    result[col].append(None)
            elif reason_type == "error_message":
                if props.has_error_message:
                    result[col].append(random.choice(error_pool))
                else:
                    result[col].append(None)
            elif reason_type == "cancellation_reason":
                if props.notes_category == "cancellation":
                    result[col].append(random.choice(cancel_pool))
                else:
                    result[col].append(None)
            elif reason_type == "generic_reason":
                # Generic "reason" column: fill for terminal states
                if props.has_rejection_reason:
                    result[col].append(random.choice(rejection_pool))
                elif props.notes_category == "cancellation":
                    result[col].append(random.choice(cancel_pool))
                elif props.has_success_message:
                    result[col].append(random.choice(success_pool))
                else:
                    result[col].append(None)
            elif reason_type == "notes":
                # Notes: always filled with rich, context-aware content
                from app.generators.contextual_comments import (
                    generate_contextual_comment, detect_comment_purpose,
                )
                col_purpose = detect_comment_purpose(col)
                comment = generate_contextual_comment(
                    state_category=props.notes_category,
                    domain=effective_domain,
                    column_purpose=col_purpose,
                    status_value=status,
                )
                result[col].append(comment)
            else:
                result[col].append(None)

        # Set date columns — only set when state warrants it
        for col, date_type in mapping.date_cols.items():
            if date_type == "completion_date":
                result[col].append(_generate_date_value(props.has_completion_date))
            elif date_type == "start_date":
                # Start date is always set (record was started/submitted)
                result[col].append(_generate_date_value(True))
            else:
                result[col].append(_generate_date_value(props.has_completion_date))

    return result
