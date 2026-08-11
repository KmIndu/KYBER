"""Contextual explanation and comment generation engine.

Generates comments, descriptions, and explanations that semantically align
with the workflow state of the row. Instead of random text, comments are
composed from domain-specific templates that reference the current state.

Features:
- Context-aware explanation generation (aligned with status/state)
- Deterministic composable templates
- Column-purpose awareness (internal_notes vs customer_comment vs audit_trail)
- Business-domain-specific language
- Semantic consistency enforcement
- Support for multiple comment columns with different tones/purposes

Integration:
- Called by the workflow engine to generate richer notes content
- Can also work standalone for tables with comment columns but no explicit status
"""

from __future__ import annotations

import random
import re
from typing import Any


# ── Comment Column Purpose Detection ─────────────────────────

_COMMENT_COLUMN_PURPOSES: list[tuple[re.Pattern[str], str]] = [
    # Internal/system notes
    (re.compile(r"internal[_\s]?note|system[_\s]?note|admin[_\s]?note|"
                r"private[_\s]?note|staff[_\s]?note", re.I), "internal"),
    # Audit trail entries
    (re.compile(r"audit[_\s]?(trail|log|entry|note)|change[_\s]?log|"
                r"history[_\s]?note|tracking[_\s]?note", re.I), "audit"),
    # Customer-facing remarks
    (re.compile(r"customer[_\s]?(comment|note|message|response)|"
                r"client[_\s]?(note|comment)|external[_\s]?note|"
                r"public[_\s]?note|user[_\s]?message", re.I), "customer_facing"),
    # Resolution/outcome summary
    (re.compile(r"resolution[_\s]?(note|summary|detail)|outcome[_\s]?note|"
                r"final[_\s]?note|closing[_\s]?note|conclusion", re.I), "resolution"),
    # Explanation/justification
    (re.compile(r"explanation|justification|rationale|reasoning", re.I), "explanation"),
    # Processing/action notes
    (re.compile(r"processing[_\s]?note|action[_\s]?note|handler[_\s]?note|"
                r"adjuster[_\s]?note|reviewer[_\s]?note", re.I), "processing"),
    # Description (more generic context about the record)
    (re.compile(r"^description$|^detail[s]?$|^summary$|^overview$", re.I), "description"),
    # Generic notes/comments/remarks (fallback)
    (re.compile(r"note[s]?$|comment[s]?$|remark[s]?$|observation[s]?$|"
                r"feedback$|memo$", re.I), "general"),
]


# ── Template Fragments ───────────────────────────────────────
# Templates are composable: {opener} + {detail} + {closer}
# Each varies by (domain, state_category, column_purpose)

# State categories (from workflow_engine.StateProperties.notes_category):
# positive, negative, waiting, progress, neutral, cancellation, resolution, expiry

_OPENERS: dict[str, dict[str, list[str]]] = {
    # domain → state_category → list of openers
    "insurance": {
        "positive": [
            "Claim has been approved.",
            "Coverage verified and approved.",
            "Adjuster completed review — approved.",
            "All requirements satisfied.",
            "Approval granted after review.",
        ],
        "negative": [
            "Claim has been denied.",
            "Unable to approve this claim.",
            "Review completed — denial issued.",
            "Coverage verification failed.",
            "Claim does not meet approval criteria.",
        ],
        "waiting": [
            "Claim is pending further review.",
            "Awaiting additional documentation.",
            "Currently in the review queue.",
            "On hold pending verification.",
            "Assigned to adjuster — awaiting assessment.",
        ],
        "progress": [
            "Claim is being actively reviewed.",
            "Assessment currently in progress.",
            "Adjuster is reviewing submitted documents.",
            "Evaluation underway.",
            "Processing through standard review workflow.",
        ],
        "cancellation": [
            "Claim has been cancelled.",
            "Processing discontinued at requestor's instruction.",
            "Withdrawal request acknowledged.",
            "Claim cancelled — no further action.",
            "Case closed per policyholder request.",
        ],
        "resolution": [
            "Case has been resolved and closed.",
            "Final determination has been made.",
            "All outstanding items addressed.",
            "Settlement finalized.",
            "Matter concluded — archived.",
        ],
        "expiry": [
            "Claim period has expired.",
            "Filing deadline has passed.",
            "Coverage period no longer active.",
            "Statute of limitations reached.",
            "Time-limit for submission exceeded.",
        ],
    },
    "banking": {
        "positive": [
            "Transaction approved and processed.",
            "Request has been approved.",
            "Compliance review passed successfully.",
            "Funds transfer completed.",
            "Authorization confirmed.",
        ],
        "negative": [
            "Transaction could not be completed.",
            "Request has been declined.",
            "Compliance review identified issues.",
            "Authorization denied.",
            "Transaction blocked by security controls.",
        ],
        "waiting": [
            "Transaction is pending processing.",
            "Awaiting compliance review.",
            "In queue for next business day processing.",
            "Pending additional verification.",
            "Waiting for authorization from account holder.",
        ],
        "progress": [
            "Transaction is being processed.",
            "Currently under compliance review.",
            "Verification steps in progress.",
            "Processing through standard workflow.",
            "Being reviewed by operations team.",
        ],
        "cancellation": [
            "Transaction has been cancelled.",
            "Transfer recalled before settlement.",
            "Account holder requested cancellation.",
            "Transaction voided.",
            "Processing stopped — cancelled by user.",
        ],
        "resolution": [
            "Matter resolved — no further action needed.",
            "Dispute settled — case closed.",
            "Reconciliation completed.",
            "All discrepancies resolved.",
            "Final settlement processed.",
        ],
    },
    "healthcare": {
        "positive": [
            "Treatment completed successfully.",
            "Patient responding well to treatment.",
            "Procedure performed without complications.",
            "Discharge criteria met.",
            "Clinical goals achieved.",
        ],
        "negative": [
            "Treatment not producing expected results.",
            "Appointment cancelled due to scheduling conflict.",
            "Pre-authorization was not approved.",
            "Patient did not meet eligibility criteria.",
            "Referral requirement not satisfied.",
        ],
        "waiting": [
            "Awaiting test results.",
            "Patient scheduled for follow-up.",
            "Pending specialist consultation.",
            "Lab work ordered — awaiting results.",
            "Referral pending approval.",
        ],
        "progress": [
            "Treatment plan in progress.",
            "Patient currently under observation.",
            "Therapy sessions ongoing.",
            "Medication regimen being followed.",
            "Recovery progressing as expected.",
        ],
        "cancellation": [
            "Appointment cancelled.",
            "Procedure cancelled — patient decision.",
            "Treatment plan discontinued.",
            "Scheduling conflict — needs rescheduling.",
            "Service cancelled per patient request.",
        ],
        "resolution": [
            "Patient discharged — recovery complete.",
            "Treatment goals achieved.",
            "Case closed — no further follow-up needed.",
            "Final assessment completed.",
            "Patient cleared for discharge.",
        ],
    },
    "devops": {
        "positive": [
            "Pipeline completed successfully.",
            "All checks passed.",
            "Deployment verified and healthy.",
            "Build and tests completed without issues.",
            "Release deployed to production.",
        ],
        "negative": [
            "Pipeline execution failed.",
            "Build errors detected.",
            "Deployment health check failed.",
            "Security scan identified critical issues.",
            "Test suite reported failures.",
        ],
        "waiting": [
            "Job queued for execution.",
            "Awaiting dependent pipeline completion.",
            "In deployment queue.",
            "Waiting for approval gate.",
            "Pending resource availability.",
        ],
        "progress": [
            "Pipeline currently executing.",
            "Build in progress.",
            "Running test suite.",
            "Deploying to target environment.",
            "Security scan in progress.",
        ],
        "cancellation": [
            "Pipeline execution cancelled.",
            "Deployment rolled back.",
            "Job manually cancelled by operator.",
            "Build aborted — superseded by newer commit.",
            "Execution terminated.",
        ],
        "resolution": [
            "Issue resolved — pipeline unblocked.",
            "Hotfix deployed — incident closed.",
            "Configuration corrected.",
            "Dependencies updated — build restored.",
            "Rollback successful — service stable.",
        ],
    },
    "hr": {
        "positive": [
            "Application approved.",
            "Request has been granted.",
            "Candidate meets all requirements.",
            "Evaluation completed — positive outcome.",
            "Approved by hiring committee.",
        ],
        "negative": [
            "Application not selected for advancement.",
            "Request has been denied.",
            "Candidate does not meet requirements.",
            "Evaluation identified disqualifying factors.",
            "Position requirements not met.",
        ],
        "waiting": [
            "Under review by hiring manager.",
            "Pending background check results.",
            "Awaiting committee decision.",
            "In review queue.",
            "Waiting for supporting documentation.",
        ],
        "progress": [
            "Currently in evaluation process.",
            "Interview round in progress.",
            "Background verification underway.",
            "Assessment being conducted.",
            "Processing through review stages.",
        ],
        "cancellation": [
            "Application withdrawn.",
            "Candidate withdrew from process.",
            "Position cancelled — restructuring.",
            "Request no longer needed.",
            "Process discontinued.",
        ],
        "resolution": [
            "Process completed — decision final.",
            "Onboarding finalized.",
            "All steps completed successfully.",
            "Case resolved and documented.",
            "Final status recorded.",
        ],
    },
    "ecommerce": {
        "positive": [
            "Order delivered successfully.",
            "Shipment confirmed.",
            "Payment processed and verified.",
            "Delivery confirmed by customer.",
            "Order fulfilled.",
        ],
        "negative": [
            "Order could not be fulfilled.",
            "Delivery attempt failed.",
            "Payment was declined.",
            "Item out of stock.",
            "Shipping address could not be verified.",
        ],
        "waiting": [
            "Order awaiting shipment.",
            "Pending payment confirmation.",
            "In packing queue.",
            "Awaiting inventory restock.",
            "Order received — processing.",
        ],
        "progress": [
            "Order being prepared for shipment.",
            "Currently in transit.",
            "Payment verification in progress.",
            "Package at sorting facility.",
            "Out for delivery.",
        ],
        "cancellation": [
            "Order cancelled by customer.",
            "Seller cancelled — item unavailable.",
            "Auto-cancelled — payment timeout.",
            "Cancellation confirmed — refund initiated.",
            "Order removed at buyer's request.",
        ],
        "resolution": [
            "Return processed — refund issued.",
            "Dispute resolved in customer's favor.",
            "Replacement item shipped.",
            "Issue resolved — credit applied.",
            "Exchange completed.",
        ],
    },
}

# Fallback general openers
_GENERAL_OPENERS: dict[str, list[str]] = {
    "positive": [
        "Request has been approved.",
        "Processing completed successfully.",
        "All requirements met.",
        "Approved as submitted.",
        "Verification passed.",
    ],
    "negative": [
        "Request could not be approved.",
        "Processing encountered issues.",
        "Requirements not met.",
        "Unable to proceed as submitted.",
        "Verification did not pass.",
    ],
    "waiting": [
        "Currently pending review.",
        "Awaiting further input.",
        "In processing queue.",
        "On hold pending information.",
        "Assigned for review.",
    ],
    "progress": [
        "Currently being processed.",
        "Under active review.",
        "In progress.",
        "Being handled by assigned team.",
        "Processing underway.",
    ],
    "cancellation": [
        "Has been cancelled.",
        "Processing discontinued.",
        "Withdrawn from workflow.",
        "No longer being processed.",
        "Cancelled per request.",
    ],
    "resolution": [
        "Resolved and closed.",
        "Final determination made.",
        "No further action required.",
        "Matter concluded.",
        "Closed with resolution.",
    ],
    "neutral": [
        "Record created.",
        "Entry documented.",
        "Standard processing applies.",
        "In normal workflow state.",
        "No special conditions noted.",
    ],
    "expiry": [
        "Deadline has passed.",
        "Time limit exceeded.",
        "No longer within valid period.",
        "Expired per policy rules.",
        "Period has elapsed.",
    ],
}


# ── Detail Fragments (compose with openers for richer comments) ──

_DETAILS: dict[str, dict[str, list[str]]] = {
    "insurance": {
        "positive": [
            "All supporting documentation has been verified against policy terms.",
            "Coverage limits confirmed — within allowable range.",
            "Medical necessity review completed by senior adjuster.",
            "Policy was active at time of incident — no exclusions apply.",
            "Third-party verification confirmed all claim details.",
            "Automated approval triggered — falls within pre-approved criteria.",
        ],
        "negative": [
            "Documentation submitted does not support the claimed amount.",
            "Policy exclusion clause 4.2(b) applies to this type of loss.",
            "The incident occurred outside the coverage period.",
            "Prior condition exclusion renders this claim ineligible.",
            "The claim amount exceeds the maximum per-incident limit.",
            "Required evidence was not provided within the 30-day window.",
        ],
        "waiting": [
            "Adjuster has requested itemized receipts for verification.",
            "Waiting for police report to corroborate claim details.",
            "Medical records have been requested from the treating provider.",
            "Third-party liability assessment is still in progress.",
            "Policyholder has been contacted for additional information.",
        ],
        "progress": [
            "Currently cross-referencing claim details against policy schedule.",
            "Fraud detection algorithms flagged for manual review — in process.",
            "Reviewing supplementary documentation submitted on prior date.",
            "Coordinating with reinsurance team for high-value assessment.",
            "Field investigator report being incorporated into analysis.",
        ],
    },
    "banking": {
        "positive": [
            "Identity verification completed via multi-factor authentication.",
            "AML screening cleared — no adverse findings.",
            "Credit assessment score exceeds minimum threshold.",
            "Dual-authorization obtained for this transaction amount.",
            "Funds availability confirmed in source account.",
        ],
        "negative": [
            "Account balance insufficient to cover requested amount.",
            "Beneficiary account failed validation checks.",
            "Transaction flagged by fraud detection model (score: 0.87).",
            "Regulatory hold placed — suspicious activity pattern detected.",
            "Customer identity could not be verified with provided documents.",
        ],
        "waiting": [
            "Compliance team review scheduled for next business day.",
            "Waiting for correspondent bank confirmation.",
            "Additional document verification required per policy.",
            "Manager approval needed for amounts above threshold.",
            "Customer callback scheduled to verify transaction intent.",
        ],
        "progress": [
            "Currently in the settlement processing queue.",
            "Undergoing enhanced due diligence review.",
            "Multi-currency conversion being calculated.",
            "Routing through ACH network — estimated 1-2 business days.",
            "Cross-border compliance checks in progress.",
        ],
    },
    "healthcare": {
        "positive": [
            "Patient vitals within normal range at discharge.",
            "Treatment objectives achieved per clinical protocol.",
            "Imaging results confirm successful intervention.",
            "Lab values normalized following treatment course.",
            "Patient reported significant improvement in symptoms.",
        ],
        "negative": [
            "Clinical indicators suggest alternative treatment needed.",
            "Insurance authorization was not obtained in advance.",
            "Patient does not meet clinical criteria for this procedure.",
            "Specialist referral from PCP was not documented.",
            "Treatment plan inconsistent with evidence-based guidelines.",
        ],
        "waiting": [
            "Lab results expected within 48 hours.",
            "Specialist consultation scheduled for next week.",
            "Imaging appointment confirmed — awaiting results.",
            "Pre-operative clearance pending cardiology review.",
            "Insurance pre-authorization request submitted.",
        ],
        "progress": [
            "Patient currently on day 3 of treatment protocol.",
            "Medication titration in progress — monitoring response.",
            "Physical therapy sessions ongoing — improvement noted.",
            "Post-operative recovery progressing within normal parameters.",
            "Wound care protocol being followed — healing well.",
        ],
    },
    "devops": {
        "positive": [
            "All 1,247 unit tests passed in 42 seconds.",
            "Zero critical or high vulnerabilities detected.",
            "Rolling deployment completed — all pods healthy.",
            "Performance benchmarks within acceptable thresholds.",
            "Code coverage at 94% — above minimum requirement.",
        ],
        "negative": [
            "Compilation failed at module: src/services/auth.ts (line 287).",
            "Integration test timeout — database connection pool exhausted.",
            "Container health check failed after 3 consecutive attempts.",
            "SAST scan detected 2 critical CVEs in dependency tree.",
            "Memory usage exceeded limit: 4.2GB / 4.0GB max.",
        ],
        "waiting": [
            "Dependent service 'auth-service' pipeline still running.",
            "Queued behind 3 other builds in shared runner pool.",
            "Manual approval gate — waiting for team lead sign-off.",
            "Artifact registry rate limit — retrying in 60 seconds.",
            "Waiting for staging environment to become available.",
        ],
        "progress": [
            "Currently executing integration test suite (47% complete).",
            "Docker image build: layer 5/8 — installing dependencies.",
            "Running SAST scan across 342 source files.",
            "Deploying canary instance — monitoring error rates.",
            "Database migration running — 3 of 5 scripts applied.",
        ],
    },
    "hr": {
        "positive": [
            "Candidate demonstrated strong fit during all interview rounds.",
            "Background check returned clean — no adverse findings.",
            "All required qualifications and certifications verified.",
            "Compensation package within approved band — ready to extend.",
            "Reference checks returned positive feedback from all contacts.",
        ],
        "negative": [
            "Technical assessment score below minimum threshold (62/100).",
            "Background verification revealed discrepancy in employment history.",
            "Required certification not current — expired 6 months ago.",
            "Salary expectations 28% above approved budget for this level.",
            "Multiple scheduling conflicts — unable to complete process.",
        ],
        "waiting": [
            "Awaiting hiring manager's availability for final interview.",
            "Reference check in progress — 2 of 3 contacts reached.",
            "Pending completion of mandatory compliance training.",
            "Document submission package received — under review.",
            "Benefits enrollment window opens next week.",
        ],
        "progress": [
            "Currently in interview round 3 of 4.",
            "Skills assessment being evaluated by technical panel.",
            "Onboarding documents being prepared.",
            "New hire orientation scheduled for upcoming Monday.",
            "System access provisioning in progress.",
        ],
    },
    "ecommerce": {
        "positive": [
            "Delivery confirmed via signature — photo proof available.",
            "Payment cleared through payment processor.",
            "All items verified and packed per quality checklist.",
            "Tracking shows delivered to mailbox at destination.",
            "Return processed — item inspected and accepted.",
        ],
        "negative": [
            "Delivery attempt failed — recipient not available.",
            "Payment declined by card issuer (insufficient funds).",
            "Warehouse inventory count shows item out of stock.",
            "Address validation service returned error for destination.",
            "Item damaged during transit — reported by carrier.",
        ],
        "waiting": [
            "Awaiting carrier pickup — scheduled for tomorrow.",
            "Payment hold pending fraud review (standard for high-value).",
            "In queue for next batch picking cycle.",
            "Awaiting supplier confirmation for back-ordered item.",
            "Pending customer response to shipping options.",
        ],
        "progress": [
            "Package in transit — currently at regional sorting facility.",
            "Order being picked and packed at fulfillment center.",
            "Carrier has scanned package — out for delivery.",
            "Return shipment in transit back to warehouse.",
            "Refund being processed — typically 3-5 business days.",
        ],
    },
}

_GENERAL_DETAILS: dict[str, list[str]] = {
    "positive": [
        "All required criteria have been satisfied.",
        "Verification completed without issues.",
        "Standard approval path followed.",
        "Review completed by authorized personnel.",
        "No outstanding issues or blockers identified.",
    ],
    "negative": [
        "One or more requirements were not satisfied.",
        "Issues identified during review process.",
        "Does not conform to established criteria.",
        "Discrepancy found between submitted and required information.",
        "Compliance check returned negative result.",
    ],
    "waiting": [
        "Additional information has been requested.",
        "Scheduled for review in next processing cycle.",
        "Dependent on external input before proceeding.",
        "Queued for assigned handler.",
        "Standard processing timeline applies.",
    ],
    "progress": [
        "Being reviewed against established criteria.",
        "Standard workflow steps being executed.",
        "Handler is actively working on this item.",
        "Processing through normal validation steps.",
        "Review in progress by assigned team member.",
    ],
    "cancellation": [
        "Requestor indicated this is no longer needed.",
        "Superseded by a newer submission.",
        "External factors made this irrelevant.",
        "Withdrawn before completion of processing.",
        "No longer applicable per requestor.",
    ],
    "resolution": [
        "All parties have confirmed satisfactory outcome.",
        "Final status documented and archived.",
        "No further action items remain.",
        "Audit trail complete — case closed.",
        "Resolution accepted by all stakeholders.",
    ],
    "neutral": [
        "Standard processing applies.",
        "No special conditions at this time.",
        "Routine entry in normal workflow.",
        "Record created per standard procedure.",
        "No exceptions noted.",
    ],
    "expiry": [
        "Allowable time period has elapsed.",
        "No action taken within required timeframe.",
        "Automatic expiration per policy rules.",
        "Deadline passed without required submission.",
        "Auto-archived due to inactivity.",
    ],
}


# ── Purpose-specific tone modifiers ─────────────────────────

_PURPOSE_CLOSERS: dict[str, list[str]] = {
    "internal": [
        "For internal use only.",
        "Do not share with external parties.",
        "Internal reference #{}.",
        "Logged for audit purposes.",
        "Handler: see workflow history for details.",
    ],
    "audit": [
        "Logged at {} by system.",
        "Audit entry — no manual override.",
        "Change tracked for compliance.",
        "Recorded per regulatory requirement.",
        "Timestamp and actor verified.",
    ],
    "customer_facing": [
        "Please contact us if you have questions.",
        "You will receive further updates by email.",
        "Thank you for your patience.",
        "We appreciate your understanding.",
        "For assistance, reach out to our support team.",
    ],
    "resolution": [
        "This matter is now fully resolved.",
        "No further follow-up required.",
        "Case considered closed.",
        "Final determination — no appeal filed.",
        "Resolution documented for reference.",
    ],
    "explanation": [
        "This determination is based on current policy guidelines.",
        "Decision made per established criteria.",
        "See referenced documentation for full details.",
        "This assessment follows standard protocols.",
        "Based on information available at time of review.",
    ],
    "processing": [
        "Next step: see assigned handler.",
        "Follow standard escalation if unresolved.",
        "Regular updates will be provided.",
        "SLA clock started at submission time.",
        "Auto-escalation in 48 hours if no action.",
    ],
    "description": [
        "",  # descriptions don't need a closer
    ],
    "general": [
        "",  # general notes don't need a closer
    ],
}


# ── Core Engine ──────────────────────────────────────────────

def detect_comment_purpose(column_name: str) -> str:
    """Detect the purpose/audience of a comment column.

    Returns one of: internal, audit, customer_facing, resolution,
    explanation, processing, description, general
    """
    for pattern, purpose in _COMMENT_COLUMN_PURPOSES:
        if pattern.search(column_name):
            return purpose
    return "general"


def generate_contextual_comment(
    state_category: str,
    domain: str = "general",
    column_purpose: str = "general",
    status_value: str | None = None,
) -> str:
    """Generate a single contextual comment aligned with the given state.

    Args:
        state_category: The notes_category from StateProperties
                       (positive, negative, waiting, progress, cancellation, resolution, expiry, neutral)
        domain: Business domain (insurance, banking, healthcare, devops, hr, ecommerce)
        column_purpose: Purpose of the column (internal, audit, customer_facing, etc.)
        status_value: The actual status value (for reference in the comment)

    Returns:
        A coherent, context-appropriate comment string.
    """
    # Get opener
    domain_openers = _OPENERS.get(domain, {})
    openers = domain_openers.get(state_category, _GENERAL_OPENERS.get(state_category, _GENERAL_OPENERS["neutral"]))
    opener = random.choice(openers)

    # Get detail (50% chance to add a detail for richer content)
    detail = ""
    if random.random() < 0.6:
        domain_details = _DETAILS.get(domain, {})
        details_list = domain_details.get(state_category, _GENERAL_DETAILS.get(state_category, _GENERAL_DETAILS["neutral"]))
        detail = " " + random.choice(details_list)

    # Get closer based on column purpose (30% chance)
    closer = ""
    if random.random() < 0.3 and column_purpose != "general" and column_purpose != "description":
        closers = _PURPOSE_CLOSERS.get(column_purpose, [])
        closers = [c for c in closers if c]  # filter empty strings
        if closers:
            c = random.choice(closers)
            # Replace {} with a pseudo-reference if present
            if "{}" in c:
                c = c.format(f"{random.randint(1000, 9999)}")
            closer = " " + c

    return f"{opener}{detail}{closer}".strip()


def generate_contextual_comments_batch(
    state_categories: list[str],
    n: int,
    domain: str = "general",
    column_purpose: str = "general",
    status_values: list[str] | None = None,
) -> list[str]:
    """Generate n contextual comments for a batch of rows.

    Args:
        state_categories: List of state categories, one per row.
        n: Number of comments to generate.
        domain: Business domain.
        column_purpose: Column purpose type.
        status_values: Optional list of actual status values per row.

    Returns:
        List of n comment strings.
    """
    comments: list[str] = []
    for i in range(n):
        cat = state_categories[i] if i < len(state_categories) else "neutral"
        sv = status_values[i] if status_values and i < len(status_values) else None
        comments.append(generate_contextual_comment(cat, domain, column_purpose, sv))
    return comments


# ── Standalone Resolution (no explicit status column) ────────

# When a table has comment/notes columns but no status column,
# infer the state distribution from the table context.

_TABLE_STATE_DISTRIBUTIONS: dict[str, list[tuple[str, float]]] = {
    "insurance": [
        ("positive", 0.30), ("negative", 0.15), ("waiting", 0.20),
        ("progress", 0.20), ("cancellation", 0.05), ("resolution", 0.10),
    ],
    "banking": [
        ("positive", 0.35), ("negative", 0.10), ("waiting", 0.20),
        ("progress", 0.20), ("cancellation", 0.05), ("resolution", 0.10),
    ],
    "healthcare": [
        ("positive", 0.30), ("negative", 0.10), ("waiting", 0.20),
        ("progress", 0.25), ("cancellation", 0.05), ("resolution", 0.10),
    ],
    "devops": [
        ("positive", 0.35), ("negative", 0.20), ("waiting", 0.15),
        ("progress", 0.20), ("cancellation", 0.05), ("resolution", 0.05),
    ],
    "hr": [
        ("positive", 0.25), ("negative", 0.15), ("waiting", 0.25),
        ("progress", 0.20), ("cancellation", 0.05), ("resolution", 0.10),
    ],
    "ecommerce": [
        ("positive", 0.40), ("negative", 0.10), ("waiting", 0.15),
        ("progress", 0.20), ("cancellation", 0.10), ("resolution", 0.05),
    ],
    "general": [
        ("positive", 0.25), ("negative", 0.10), ("waiting", 0.20),
        ("progress", 0.25), ("neutral", 0.10), ("resolution", 0.10),
    ],
}


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


def detect_comment_columns(column_names: list[str]) -> dict[str, str]:
    """Detect comment/explanation columns and their purposes.

    Returns dict mapping col_name → purpose.
    """
    result: dict[str, str] = {}
    for col_name in column_names:
        for pattern, purpose in _COMMENT_COLUMN_PURPOSES:
            if pattern.search(col_name):
                result[col_name] = purpose
                break
    return result


# ---------------------------------------------------------------------------
# Status → State Category mapping
# ---------------------------------------------------------------------------

_STATUS_CATEGORY_MAP: dict[str, str] = {
    # Positive
    "approved": "positive", "completed": "positive", "success": "positive",
    "active": "positive", "resolved": "positive", "paid": "positive",
    "accepted": "positive", "confirmed": "positive", "delivered": "positive",
    "fulfilled": "positive", "passed": "positive", "verified": "positive",
    "hired": "positive", "onboarded": "positive", "shipped": "positive",
    "deployed": "positive", "released": "positive", "merged": "positive",
    "closed": "positive", "done": "positive", "finished": "positive",
    # Negative
    "rejected": "negative", "failed": "negative", "denied": "negative",
    "cancelled": "negative", "error": "negative", "expired": "negative",
    "terminated": "negative", "declined": "negative", "revoked": "negative",
    "suspended": "negative", "blocked": "negative", "voided": "negative",
    "returned": "negative", "refunded": "negative", "fired": "negative",
    "aborted": "negative", "rollback": "negative",
    # Waiting
    "pending": "waiting", "submitted": "waiting", "awaiting": "waiting",
    "queued": "waiting", "scheduled": "waiting", "on_hold": "waiting",
    "on hold": "waiting", "waiting": "waiting", "deferred": "waiting",
    "paused": "waiting", "backlog": "waiting",
    # In-progress
    "in_progress": "in_progress", "in progress": "in_progress",
    "processing": "in_progress", "running": "in_progress",
    "in_review": "in_progress", "in review": "in_progress",
    "reviewing": "in_progress", "investigating": "in_progress",
    "building": "in_progress", "deploying": "in_progress",
    "testing": "in_progress", "analyzing": "in_progress",
    # Neutral
    "draft": "neutral", "new": "neutral", "open": "neutral",
    "created": "neutral", "initialized": "neutral", "unknown": "neutral",
    "na": "neutral", "n/a": "neutral", "other": "neutral",
    "inactive": "neutral", "archived": "neutral",
}


def _map_status_to_category(status: str) -> str:
    """Map a status string value to a state category."""
    normalized = status.strip().lower().replace("-", "_")
    # Direct lookup
    if normalized in _STATUS_CATEGORY_MAP:
        return _STATUS_CATEGORY_MAP[normalized]
    # Substring match for composite statuses like "claim_approved" or "payment_failed"
    for key, category in _STATUS_CATEGORY_MAP.items():
        if key in normalized:
            return category
    # Default to neutral if truly unrecognizable
    return "neutral"


def resolve_contextual_comments(
    table_name: str,
    column_names: list[str],
    n: int,
    domain: str = "unknown",
    status_values: list[str] | None = None,
    state_categories: list[str] | None = None,
) -> dict[str, list[str]] | None:
    """Generate contextual comments for detected comment columns.

    Can work in two modes:
    1. With state_categories provided (from workflow engine) — generates aligned
    2. Standalone (no status) — infers state distribution from domain

    Args:
        table_name: Name of the table.
        column_names: All column names.
        n: Number of rows.
        domain: Business domain.
        status_values: Optional list of status values per row (for alignment reference).
        state_categories: Optional list of state categories per row (from workflow engine).

    Returns:
        Dict mapping comment column_name → list of n comment strings,
        or None if no comment columns detected.
    """
    comment_cols = detect_comment_columns(column_names)

    if not comment_cols:
        return None

    effective_domain = domain if domain != "unknown" else _infer_domain_from_table(table_name)

    # If no state categories provided, derive from status_values or domain distribution
    if not state_categories:
        if status_values:
            # Map status values to state categories
            state_categories = [_map_status_to_category(s) for s in status_values]
        else:
            dist = _TABLE_STATE_DISTRIBUTIONS.get(effective_domain, _TABLE_STATE_DISTRIBUTIONS["general"])
            categories = [cat for cat, _ in dist]
            weights = [w for _, w in dist]
            state_categories = random.choices(categories, weights=weights, k=n)

    result: dict[str, list[str]] = {}
    for col_name, purpose in comment_cols.items():
        result[col_name] = generate_contextual_comments_batch(
            state_categories, n,
            domain=effective_domain,
            column_purpose=purpose,
            status_values=status_values,
        )

    return result
