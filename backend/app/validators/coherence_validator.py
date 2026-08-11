"""Synthetic Data Coherence Validator.

Detects contradictory or semantically inconsistent rows in generated data.
Works at three levels:

1. Rule-based validation — hard-coded logic for common contradictions
   (e.g., status=approved + rejection_reason filled)
2. Semantic validation — detects mismatches using column meaning awareness
   (e.g., country=India + phone_code=+1)
3. Dependency-aware validation — leverages the dependency graph to validate
   cross-column coherence (e.g., email should contain name components)

Returns a CoherenceReport with issues, severity levels, and correction
suggestions for each detected contradiction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Severity levels ──────────────────────────────────────────


class Severity(str, Enum):
    """Issue severity."""
    CRITICAL = "critical"     # Definitely wrong, breaks business logic
    HIGH = "high"             # Very likely contradictory
    MEDIUM = "medium"         # Probably inconsistent, context-dependent
    LOW = "low"               # Minor inconsistency, cosmetic


# ── Data models ──────────────────────────────────────────────


@dataclass
class CoherenceIssue:
    """A single coherence issue in a row."""
    table: str
    row_index: int
    rule: str
    severity: Severity
    columns_involved: list[str]
    values: dict[str, Any]
    message: str
    suggestion: str


@dataclass
class TableCoherenceReport:
    """Coherence report for a single table."""
    table: str
    total_rows: int = 0
    issues_found: int = 0
    issues: list[CoherenceIssue] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)

    @property
    def coherence_score(self) -> float:
        """0.0–1.0 score; 1.0 = fully coherent."""
        if self.total_rows == 0:
            return 1.0
        failing_rows = len({i.row_index for i in self.issues})
        return 1.0 - (failing_rows / self.total_rows)


@dataclass
class CoherenceReport:
    """Full coherence report across all tables."""
    tables: list[TableCoherenceReport] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return sum(t.issues_found for t in self.tables)

    @property
    def total_rows(self) -> int:
        return sum(t.total_rows for t in self.tables)

    @property
    def overall_coherence_score(self) -> float:
        if self.total_rows == 0:
            return 1.0
        failing = sum(len({i.row_index for i in t.issues}) for t in self.tables)
        return 1.0 - (failing / self.total_rows)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        return {
            "total_issues": self.total_issues,
            "total_rows": self.total_rows,
            "overall_coherence_score": round(self.overall_coherence_score, 4),
            "tables": [
                {
                    "table": t.table,
                    "total_rows": t.total_rows,
                    "issues_found": t.issues_found,
                    "coherence_score": round(t.coherence_score, 4),
                    "issues": [
                        {
                            "row_index": issue.row_index,
                            "rule": issue.rule,
                            "severity": issue.severity.value,
                            "columns_involved": issue.columns_involved,
                            "values": {k: _safe_str(v) for k, v in issue.values.items()},
                            "message": issue.message,
                            "suggestion": issue.suggestion,
                        }
                        for issue in t.issues
                    ],
                }
                for t in self.tables
            ],
        }


def _safe_str(val: Any) -> str:
    """Safe string representation for values."""
    if val is None:
        return "NULL"
    return str(val)[:200]


# ═══════════════════════════════════════════════════════════════
# STATUS → CATEGORY MAPPING (reused from contextual_comments)
# ═══════════════════════════════════════════════════════════════

_POSITIVE_STATUSES = frozenset({
    "approved", "completed", "success", "active", "resolved", "paid",
    "accepted", "confirmed", "delivered", "fulfilled", "passed", "verified",
    "hired", "onboarded", "shipped", "deployed", "released", "merged",
    "closed", "done", "finished",
})

_NEGATIVE_STATUSES = frozenset({
    "rejected", "failed", "denied", "cancelled", "error", "expired",
    "terminated", "declined", "revoked", "suspended", "blocked", "voided",
    "returned", "refunded", "fired", "aborted", "rollback",
})

_WAITING_STATUSES = frozenset({
    "pending", "submitted", "awaiting", "queued", "scheduled", "on_hold",
    "waiting", "deferred", "paused", "backlog",
})

_IN_PROGRESS_STATUSES = frozenset({
    "in_progress", "processing", "running", "in_review", "reviewing",
    "investigating", "building", "deploying", "testing", "analyzing",
})


def _classify_status(value: Any) -> str | None:
    """Classify a status value into a category. Returns None if unrecognizable."""
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _POSITIVE_STATUSES:
        return "positive"
    if normalized in _NEGATIVE_STATUSES:
        return "negative"
    if normalized in _WAITING_STATUSES:
        return "waiting"
    if normalized in _IN_PROGRESS_STATUSES:
        return "in_progress"
    # Substring fallback
    for s in _POSITIVE_STATUSES:
        if s in normalized:
            return "positive"
    for s in _NEGATIVE_STATUSES:
        if s in normalized:
            return "negative"
    for s in _WAITING_STATUSES:
        if s in normalized:
            return "waiting"
    for s in _IN_PROGRESS_STATUSES:
        if s in normalized:
            return "in_progress"
    return None


# ═══════════════════════════════════════════════════════════════
# COLUMN DETECTION PATTERNS
# ═══════════════════════════════════════════════════════════════

_STATUS_COL = re.compile(r"^status$|_status$|^state$|_state$|^decision$|^outcome$", re.I)
_REJECTION_COL = re.compile(r"reject|denial|decline|refus", re.I)
_APPROVAL_COL = re.compile(r"approv|accept|confirm", re.I)
_COMMENT_COL = re.compile(r"comment|note|remark|explanation|description|reason|message", re.I)
_EMAIL_COL = re.compile(r"email|e_mail", re.I)
_PHONE_COL = re.compile(r"phone|mobile|telephone|cell|contact_number", re.I)
_COUNTRY_COL = re.compile(r"^country$|^nation$|^country_code$|^country_name$", re.I)
_PHONE_CODE_COL = re.compile(r"phone_code|country_code|dial_code|calling_code|intl_code", re.I)
_BOOL_COL = re.compile(r"^is_|^has_|^can_|^allow|^flag_|_flag$|^enabled$|^verified$|^valid$", re.I)
_ACTIVE_COL = re.compile(r"is_active|active_flag|is_enabled|is_open", re.I)
_CLOSED_COL = re.compile(r"is_closed|is_completed|is_done|is_resolved|is_terminated", re.I)
_DATE_START_COL = re.compile(r"created_(?:at|date|on)|start_date|opened_(?:at|date|on)|submitted_(?:at|date|on)|filed_(?:at|date|on)|begin_date", re.I)
_DATE_END_COL = re.compile(r"closed_(?:at|date|on)|completed_(?:at|date|on)|end_date|resolved_(?:at|date|on)|finished_(?:at|date|on)|terminated_(?:at|date|on)", re.I)
_AMOUNT_COL = re.compile(r"amount|total|price|cost|fee|balance|premium|payment", re.I)
_CURRENCY_COL = re.compile(r"currency|currency_code", re.I)
_NAME_COL = re.compile(r"first_name|last_name|full_name|^name$", re.I)
_FIRST_NAME_COL = re.compile(r"first_name|given_name|fname", re.I)
_LAST_NAME_COL = re.compile(r"last_name|surname|family_name|lname", re.I)
_VERIFIED_COL = re.compile(r"verified|is_verified|is_valid|validated|is_confirmed", re.I)


# ═══════════════════════════════════════════════════════════════
# COUNTRY → PHONE CODE MAPPING
# ═══════════════════════════════════════════════════════════════

_COUNTRY_PHONE_CODES: dict[str, str] = {
    "united states": "+1", "usa": "+1", "us": "+1",
    "canada": "+1", "ca": "+1",
    "united kingdom": "+44", "uk": "+44", "gb": "+44",
    "india": "+91", "in": "+91",
    "australia": "+61", "au": "+61",
    "germany": "+49", "de": "+49",
    "france": "+33", "fr": "+33",
    "japan": "+81", "jp": "+81",
    "china": "+86", "cn": "+86",
    "brazil": "+55", "br": "+55",
    "mexico": "+52", "mx": "+52",
    "south korea": "+82", "kr": "+82",
    "italy": "+39", "it": "+39",
    "spain": "+34", "es": "+34",
    "netherlands": "+31", "nl": "+31",
    "singapore": "+65", "sg": "+65",
    "ireland": "+353", "ie": "+353",
    "new zealand": "+64", "nz": "+64",
    "south africa": "+27", "za": "+27",
    "sweden": "+46", "se": "+46",
    "norway": "+47", "no": "+47",
    "denmark": "+45", "dk": "+45",
    "switzerland": "+41", "ch": "+41",
    "austria": "+43", "at": "+43",
    "belgium": "+32", "be": "+32",
    "portugal": "+351", "pt": "+351",
    "russia": "+7", "ru": "+7",
    "poland": "+48", "pl": "+48",
    "turkey": "+90", "tr": "+90",
    "israel": "+972", "il": "+972",
    "uae": "+971", "ae": "+971",
    "saudi arabia": "+966", "sa": "+966",
    "malaysia": "+60", "my": "+60",
    "indonesia": "+62", "id": "+62",
    "philippines": "+63", "ph": "+63",
    "thailand": "+66", "th": "+66",
    "vietnam": "+84", "vn": "+84",
    "pakistan": "+92", "pk": "+92",
    "bangladesh": "+880", "bd": "+880",
    "nigeria": "+234", "ng": "+234",
    "egypt": "+20", "eg": "+20",
    "argentina": "+54", "ar": "+54",
    "colombia": "+57", "co": "+57",
    "chile": "+56", "cl": "+56",
    "peru": "+51", "pe": "+51",
}


# ═══════════════════════════════════════════════════════════════
# NEGATIVE SENTIMENT PATTERNS (for comment analysis)
# ═══════════════════════════════════════════════════════════════

_NEGATIVE_COMMENT_PATTERNS = [
    re.compile(r"reject|denied|declined|unable to approv|cannot approv|not approv", re.I),
    re.compile(r"fail|error|invalid|violation|non.?complian", re.I),
    re.compile(r"cancel|terminat|revok|suspend|block", re.I),
    re.compile(r"insufficien|ineligib|disqualif|exceed.?limit", re.I),
    re.compile(r"not.?meet|does.?not.?satisfy|missing.?requir", re.I),
]

_POSITIVE_COMMENT_PATTERNS = [
    re.compile(r"approv|accept|confirm|granted|success", re.I),
    re.compile(r"complet|resolved|fulfill|satisf|pass", re.I),
    re.compile(r"verified|validated|cleared|eligible", re.I),
    re.compile(r"all.?requirements?.?met|criteria.?satisf", re.I),
    re.compile(r"in.?good.?standing|no.?issues", re.I),
]

_WAITING_COMMENT_PATTERNS = [
    re.compile(r"pending|await|waiting|under.?review", re.I),
    re.compile(r"in.?progress|processing|investigating", re.I),
    re.compile(r"additional.?info|further.?review|more.?documents", re.I),
]


def _detect_comment_sentiment(text: str | None) -> str | None:
    """Detect the sentiment/category of a comment text."""
    if not text or not isinstance(text, str):
        return None
    for pattern in _NEGATIVE_COMMENT_PATTERNS:
        if pattern.search(text):
            return "negative"
    for pattern in _POSITIVE_COMMENT_PATTERNS:
        if pattern.search(text):
            return "positive"
    for pattern in _WAITING_COMMENT_PATTERNS:
        if pattern.search(text):
            return "waiting"
    return None


# ═══════════════════════════════════════════════════════════════
# EMAIL VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════

_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


def _is_valid_email(val: Any) -> bool | None:
    """Check if a value looks like a valid email. Returns None if not a string."""
    if not isinstance(val, str):
        return None
    return bool(_EMAIL_PATTERN.match(val.strip()))


def _is_truthy(val: Any) -> bool | None:
    """Check if a value is truthy (True, 1, 'yes', 'true', etc.)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "t", "active", "enabled"):
        return True
    if s in ("false", "0", "no", "n", "f", "inactive", "disabled"):
        return False
    return None


def _is_falsy(val: Any) -> bool | None:
    """Check if a value is explicitly falsy."""
    result = _is_truthy(val)
    if result is None:
        return None
    return not result


# ═══════════════════════════════════════════════════════════════
# COHERENCE VALIDATOR
# ═══════════════════════════════════════════════════════════════


class CoherenceValidator:
    """Validates semantic coherence of generated synthetic data.

    Three validation layers:
    1. Rule-based — hard-coded cross-column logic
    2. Semantic — meaning-aware content analysis
    3. Dependency-aware — leverages column relationship graph
    """

    def __init__(self) -> None:
        self._rules = self._build_rules()

    def validate(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
        column_names: list[str] | None = None,
    ) -> TableCoherenceReport:
        """Validate a single table's rows for coherence issues."""
        if not rows:
            return TableCoherenceReport(table=table_name)

        if column_names is None:
            column_names = list(rows[0].keys())

        # Pre-detect column roles for this table
        ctx = self._build_table_context(column_names)
        issues: list[CoherenceIssue] = []

        for row_idx, row in enumerate(rows):
            row_issues = self._validate_row(table_name, row_idx, row, ctx)
            issues.extend(row_issues)

        report = TableCoherenceReport(
            table=table_name,
            total_rows=len(rows),
            issues_found=len(issues),
            issues=issues,
        )
        return report

    def validate_all(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> CoherenceReport:
        """Validate all tables and return a full coherence report."""
        reports: list[TableCoherenceReport] = []
        for table_name, rows in data.items():
            report = self.validate(table_name, rows)
            reports.append(report)
        return CoherenceReport(tables=reports)

    # ── Internal: Table context detection ────────────────────

    def _build_table_context(self, columns: list[str]) -> dict[str, Any]:
        """Detect column roles for a table."""
        ctx: dict[str, Any] = {
            "status_cols": [],
            "rejection_cols": [],
            "approval_cols": [],
            "comment_cols": [],
            "email_cols": [],
            "phone_cols": [],
            "country_cols": [],
            "phone_code_cols": [],
            "bool_cols": [],
            "active_cols": [],
            "closed_cols": [],
            "date_start_cols": [],
            "date_end_cols": [],
            "amount_cols": [],
            "currency_cols": [],
            "first_name_cols": [],
            "last_name_cols": [],
            "name_cols": [],
            "verified_cols": [],
        }

        for col in columns:
            if _STATUS_COL.search(col):
                ctx["status_cols"].append(col)
            if _REJECTION_COL.search(col):
                ctx["rejection_cols"].append(col)
            if _APPROVAL_COL.search(col):
                ctx["approval_cols"].append(col)
            if _COMMENT_COL.search(col):
                ctx["comment_cols"].append(col)
            if _EMAIL_COL.search(col):
                ctx["email_cols"].append(col)
            # phone_code columns should NOT also be phone columns
            is_phone_code = bool(_PHONE_CODE_COL.search(col))
            if is_phone_code:
                ctx["phone_code_cols"].append(col)
            elif _PHONE_COL.search(col):
                ctx["phone_cols"].append(col)
            if _COUNTRY_COL.search(col):
                ctx["country_cols"].append(col)
            if _BOOL_COL.search(col):
                ctx["bool_cols"].append(col)
            if _ACTIVE_COL.search(col):
                ctx["active_cols"].append(col)
            if _CLOSED_COL.search(col):
                ctx["closed_cols"].append(col)
            if _DATE_START_COL.search(col):
                ctx["date_start_cols"].append(col)
            if _DATE_END_COL.search(col):
                ctx["date_end_cols"].append(col)
            if _AMOUNT_COL.search(col):
                ctx["amount_cols"].append(col)
            if _CURRENCY_COL.search(col):
                ctx["currency_cols"].append(col)
            if _FIRST_NAME_COL.search(col):
                ctx["first_name_cols"].append(col)
            if _LAST_NAME_COL.search(col):
                ctx["last_name_cols"].append(col)
            if _NAME_COL.search(col):
                ctx["name_cols"].append(col)
            if _VERIFIED_COL.search(col):
                ctx["verified_cols"].append(col)

        return ctx

    # ── Internal: Per-row validation ─────────────────────────

    def _validate_row(
        self,
        table: str,
        row_idx: int,
        row: dict[str, Any],
        ctx: dict[str, Any],
    ) -> list[CoherenceIssue]:
        """Run all coherence rules on a single row."""
        issues: list[CoherenceIssue] = []

        # Rule 1: Status vs rejection/approval columns
        issues.extend(self._check_status_vs_reason(table, row_idx, row, ctx))

        # Rule 2: Status vs comment sentiment
        issues.extend(self._check_status_vs_comment(table, row_idx, row, ctx))

        # Rule 3: Status vs boolean flags (is_active, is_closed)
        issues.extend(self._check_status_vs_booleans(table, row_idx, row, ctx))

        # Rule 4: Country vs phone code
        issues.extend(self._check_country_vs_phone_code(table, row_idx, row, ctx))

        # Rule 5: Email format vs verified flag
        issues.extend(self._check_email_vs_verified(table, row_idx, row, ctx))

        # Rule 6: Temporal ordering (start_date < end_date)
        issues.extend(self._check_temporal_ordering(table, row_idx, row, ctx))

        # Rule 7: Status vs completion dates
        issues.extend(self._check_status_vs_dates(table, row_idx, row, ctx))

        # Rule 8: Amount vs currency presence
        issues.extend(self._check_amount_vs_currency(table, row_idx, row, ctx))

        # Rule 9: Name in email coherence
        issues.extend(self._check_name_in_email(table, row_idx, row, ctx))

        return issues

    # ── Rule implementations ─────────────────────────────────

    def _check_status_vs_reason(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Status=approved should not have rejection_reason filled; 
        status=rejected should have rejection_reason."""
        issues: list[CoherenceIssue] = []

        for status_col in ctx["status_cols"]:
            status_val = row.get(status_col)
            category = _classify_status(status_val)
            if category is None:
                continue

            # Positive status + rejection reason filled
            for rej_col in ctx["rejection_cols"]:
                rej_val = row.get(rej_col)
                if category == "positive" and rej_val and str(rej_val).strip():
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_rejection_reason",
                        severity=Severity.CRITICAL,
                        columns_involved=[status_col, rej_col],
                        values={status_col: status_val, rej_col: rej_val},
                        message=f"Status is '{status_val}' (positive) but rejection reason is filled: '{_safe_str(rej_val)}'",
                        suggestion=f"Clear '{rej_col}' when status is positive, or change status to a negative value",
                    ))

                # Negative status + rejection reason empty
                if category == "negative" and (rej_val is None or not str(rej_val).strip()):
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_rejection_reason",
                        severity=Severity.MEDIUM,
                        columns_involved=[status_col, rej_col],
                        values={status_col: status_val, rej_col: rej_val},
                        message=f"Status is '{status_val}' (negative) but rejection reason is empty",
                        suggestion=f"Provide a rejection reason in '{rej_col}' when status is negative",
                    ))

            # Negative status + approval message filled
            for appr_col in ctx["approval_cols"]:
                appr_val = row.get(appr_col)
                if category == "negative" and appr_val and str(appr_val).strip():
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_approval_message",
                        severity=Severity.HIGH,
                        columns_involved=[status_col, appr_col],
                        values={status_col: status_val, appr_col: appr_val},
                        message=f"Status is '{status_val}' (negative) but approval field is filled: '{_safe_str(appr_val)}'",
                        suggestion=f"Clear '{appr_col}' when status is negative",
                    ))

        return issues

    def _check_status_vs_comment(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Comment sentiment should align with status category."""
        issues: list[CoherenceIssue] = []

        for status_col in ctx["status_cols"]:
            status_val = row.get(status_col)
            category = _classify_status(status_val)
            if category is None:
                continue

            for comment_col in ctx["comment_cols"]:
                comment_val = row.get(comment_col)
                comment_sentiment = _detect_comment_sentiment(comment_val)
                if comment_sentiment is None:
                    continue

                # Contradiction: positive status + negative comment
                if category == "positive" and comment_sentiment == "negative":
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_comment_sentiment",
                        severity=Severity.HIGH,
                        columns_involved=[status_col, comment_col],
                        values={status_col: status_val, comment_col: comment_val},
                        message=f"Status is '{status_val}' (positive) but comment has negative sentiment",
                        suggestion=f"Regenerate '{comment_col}' with positive/neutral language aligned with '{status_val}' status",
                    ))

                # Contradiction: negative status + positive comment
                if category == "negative" and comment_sentiment == "positive":
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_comment_sentiment",
                        severity=Severity.HIGH,
                        columns_involved=[status_col, comment_col],
                        values={status_col: status_val, comment_col: comment_val},
                        message=f"Status is '{status_val}' (negative) but comment has positive sentiment",
                        suggestion=f"Regenerate '{comment_col}' with negative/explanatory language aligned with '{status_val}' status",
                    ))

        return issues

    def _check_status_vs_booleans(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Status implies certain boolean states (active/closed flags)."""
        issues: list[CoherenceIssue] = []

        for status_col in ctx["status_cols"]:
            status_val = row.get(status_col)
            category = _classify_status(status_val)
            if category is None:
                continue

            # Closed/completed status but is_active=true
            for active_col in ctx["active_cols"]:
                active_val = _is_truthy(row.get(active_col))
                if active_val is None:
                    continue
                # Terminal positive (completed/closed/done) → should be inactive
                norm_status = str(status_val).strip().lower().replace("-", "_").replace(" ", "_")
                if norm_status in ("completed", "closed", "done", "finished", "terminated",
                                   "resolved", "cancelled", "expired"):
                    if active_val is True:
                        issues.append(CoherenceIssue(
                            table=table, row_index=idx,
                            rule="status_vs_active_flag",
                            severity=Severity.CRITICAL,
                            columns_involved=[status_col, active_col],
                            values={status_col: status_val, active_col: row.get(active_col)},
                            message=f"Status is '{status_val}' (terminal) but '{active_col}' is true",
                            suggestion=f"Set '{active_col}' to false when status is terminal ('{status_val}')",
                        ))

            # is_closed should be true when status is terminal
            for closed_col in ctx["closed_cols"]:
                closed_val = _is_truthy(row.get(closed_col))
                if closed_val is None:
                    continue
                norm_status = str(status_val).strip().lower().replace("-", "_").replace(" ", "_")
                if norm_status in ("completed", "closed", "done", "finished", "resolved"):
                    if closed_val is False:
                        issues.append(CoherenceIssue(
                            table=table, row_index=idx,
                            rule="status_vs_closed_flag",
                            severity=Severity.HIGH,
                            columns_involved=[status_col, closed_col],
                            values={status_col: status_val, closed_col: row.get(closed_col)},
                            message=f"Status is '{status_val}' but '{closed_col}' is false",
                            suggestion=f"Set '{closed_col}' to true when status is '{status_val}'",
                        ))
                # Active/pending status should have is_closed=false
                if norm_status in ("pending", "in_progress", "active", "open", "new"):
                    if closed_val is True:
                        issues.append(CoherenceIssue(
                            table=table, row_index=idx,
                            rule="status_vs_closed_flag",
                            severity=Severity.CRITICAL,
                            columns_involved=[status_col, closed_col],
                            values={status_col: status_val, closed_col: row.get(closed_col)},
                            message=f"Status is '{status_val}' (active) but '{closed_col}' is true",
                            suggestion=f"Set '{closed_col}' to false when status is '{status_val}'",
                        ))

        return issues

    def _check_country_vs_phone_code(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Country and phone code must be geographically consistent."""
        issues: list[CoherenceIssue] = []

        for country_col in ctx["country_cols"]:
            country_val = row.get(country_col)
            if not country_val or not isinstance(country_val, str):
                continue
            country_lower = country_val.strip().lower()
            expected_code = _COUNTRY_PHONE_CODES.get(country_lower)
            if expected_code is None:
                continue

            for phone_code_col in ctx["phone_code_cols"]:
                phone_code_val = row.get(phone_code_col)
                if not phone_code_val:
                    continue
                code_str = str(phone_code_val).strip()
                if not code_str.startswith("+"):
                    code_str = "+" + code_str
                if code_str != expected_code:
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="country_vs_phone_code",
                        severity=Severity.HIGH,
                        columns_involved=[country_col, phone_code_col],
                        values={country_col: country_val, phone_code_col: phone_code_val},
                        message=f"Country is '{country_val}' but phone code is '{phone_code_val}' (expected '{expected_code}')",
                        suggestion=f"Set '{phone_code_col}' to '{expected_code}' for country '{country_val}'",
                    ))

            # Also check phone numbers starting with wrong country code
            for phone_col in ctx["phone_cols"]:
                phone_val = row.get(phone_col)
                if not phone_val or not isinstance(phone_val, str):
                    continue
                phone_str = phone_val.strip()
                if phone_str.startswith("+"):
                    # Extract the country code from the phone number
                    # Try matching longest codes first
                    phone_matches_country = False
                    for code_len in (4, 3, 2):  # +880, +91, +1
                        prefix = phone_str[:code_len + 1]  # include the +
                        if prefix == expected_code:
                            phone_matches_country = True
                            break
                    if not phone_matches_country and phone_str[:len(expected_code)] != expected_code:
                        issues.append(CoherenceIssue(
                            table=table, row_index=idx,
                            rule="country_vs_phone_number",
                            severity=Severity.MEDIUM,
                            columns_involved=[country_col, phone_col],
                            values={country_col: country_val, phone_col: phone_val},
                            message=f"Country is '{country_val}' (code {expected_code}) but phone number starts with different code: '{phone_str[:5]}...'",
                            suggestion=f"Phone number should start with '{expected_code}' for country '{country_val}'",
                        ))

        return issues

    def _check_email_vs_verified(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Invalid email should not have verified=true."""
        issues: list[CoherenceIssue] = []

        for email_col in ctx["email_cols"]:
            email_val = row.get(email_col)
            is_valid = _is_valid_email(email_val)
            if is_valid is None:
                continue

            for verified_col in ctx["verified_cols"]:
                verified_val = _is_truthy(row.get(verified_col))
                if verified_val is None:
                    continue

                # Invalid email + verified=true
                if not is_valid and verified_val is True:
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="email_format_vs_verified",
                        severity=Severity.CRITICAL,
                        columns_involved=[email_col, verified_col],
                        values={email_col: email_val, verified_col: row.get(verified_col)},
                        message=f"Email '{email_val}' has invalid format but '{verified_col}' is true",
                        suggestion=f"Set '{verified_col}' to false for invalid emails, or fix the email format",
                    ))

        return issues

    def _check_temporal_ordering(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Start dates should precede end dates."""
        issues: list[CoherenceIssue] = []

        for start_col in ctx["date_start_cols"]:
            start_val = row.get(start_col)
            if start_val is None:
                continue
            start_dt = self._parse_date(start_val)
            if start_dt is None:
                continue

            for end_col in ctx["date_end_cols"]:
                end_val = row.get(end_col)
                if end_val is None:
                    continue
                end_dt = self._parse_date(end_val)
                if end_dt is None:
                    continue

                if start_dt > end_dt:
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="temporal_ordering",
                        severity=Severity.CRITICAL,
                        columns_involved=[start_col, end_col],
                        values={start_col: str(start_val), end_col: str(end_val)},
                        message=f"Start date '{start_col}' ({start_val}) is after end date '{end_col}' ({end_val})",
                        suggestion=f"Ensure '{start_col}' <= '{end_col}'; swap values or regenerate",
                    ))

        return issues

    def _check_status_vs_dates(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Pending/in-progress status should not have completion date set."""
        issues: list[CoherenceIssue] = []

        for status_col in ctx["status_cols"]:
            status_val = row.get(status_col)
            category = _classify_status(status_val)
            if category is None:
                continue

            for end_col in ctx["date_end_cols"]:
                end_val = row.get(end_col)

                # Pending/in-progress with completion date
                if category in ("waiting", "in_progress") and end_val is not None:
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_completion_date",
                        severity=Severity.HIGH,
                        columns_involved=[status_col, end_col],
                        values={status_col: status_val, end_col: end_val},
                        message=f"Status is '{status_val}' ({category}) but completion date '{end_col}' is set",
                        suggestion=f"Clear '{end_col}' when status is '{status_val}', or update status to a terminal state",
                    ))

                # Completed/closed without completion date
                norm_status = str(status_val).strip().lower().replace("-", "_").replace(" ", "_")
                if norm_status in ("completed", "closed", "done", "finished", "resolved") and end_val is None:
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="status_vs_completion_date",
                        severity=Severity.MEDIUM,
                        columns_involved=[status_col, end_col],
                        values={status_col: status_val, end_col: None},
                        message=f"Status is '{status_val}' (terminal) but completion date '{end_col}' is not set",
                        suggestion=f"Set '{end_col}' to a valid date when status is '{status_val}'",
                    ))

        return issues

    def _check_amount_vs_currency(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """Non-zero amount should have a currency; zero/null amount with currency is odd."""
        issues: list[CoherenceIssue] = []

        if not ctx["amount_cols"] or not ctx["currency_cols"]:
            return issues

        for amount_col in ctx["amount_cols"]:
            amount_val = row.get(amount_col)
            if amount_val is None:
                continue

            try:
                amount_num = float(amount_val)
            except (ValueError, TypeError):
                continue

            for currency_col in ctx["currency_cols"]:
                currency_val = row.get(currency_col)

                # Positive amount without currency
                if amount_num > 0 and (currency_val is None or not str(currency_val).strip()):
                    issues.append(CoherenceIssue(
                        table=table, row_index=idx,
                        rule="amount_without_currency",
                        severity=Severity.LOW,
                        columns_involved=[amount_col, currency_col],
                        values={amount_col: amount_val, currency_col: currency_val},
                        message=f"Amount '{amount_col}' is {amount_val} but currency is missing",
                        suggestion=f"Provide a currency code in '{currency_col}' when amount is non-zero",
                    ))

        return issues

    def _check_name_in_email(
        self, table: str, idx: int, row: dict[str, Any], ctx: dict[str, Any]
    ) -> list[CoherenceIssue]:
        """If identity-consistent generation is active, email should reference name components."""
        issues: list[CoherenceIssue] = []

        if not ctx["email_cols"] or not (ctx["first_name_cols"] or ctx["last_name_cols"]):
            return issues

        for email_col in ctx["email_cols"]:
            email_val = row.get(email_col)
            if not email_val or not isinstance(email_val, str) or "@" not in email_val:
                continue

            local_part = email_val.split("@")[0].lower()

            # Collect name components
            name_parts: list[str] = []
            for fn_col in ctx["first_name_cols"]:
                fn = row.get(fn_col)
                if fn and isinstance(fn, str) and len(fn.strip()) > 1:
                    name_parts.append(fn.strip().lower())
            for ln_col in ctx["last_name_cols"]:
                ln = row.get(ln_col)
                if ln and isinstance(ln, str) and len(ln.strip()) > 1:
                    name_parts.append(ln.strip().lower())

            if not name_parts:
                continue

            # Check if at least one name part appears in the email local part
            has_match = any(
                part in local_part or part[:3] in local_part
                for part in name_parts
                if len(part) >= 3
            )

            if not has_match:
                issues.append(CoherenceIssue(
                    table=table, row_index=idx,
                    rule="name_email_coherence",
                    severity=Severity.LOW,
                    columns_involved=[email_col] + ctx["first_name_cols"] + ctx["last_name_cols"],
                    values={
                        email_col: email_val,
                        **{c: row.get(c) for c in ctx["first_name_cols"] + ctx["last_name_cols"]},
                    },
                    message=f"Email '{email_val}' does not reference name components ({', '.join(name_parts)})",
                    suggestion=f"Generate email using name-based pattern (e.g., firstname.lastname@domain.com)",
                ))

        return issues

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _parse_date(val: Any):
        """Try to parse a date value into a comparable form."""
        from datetime import date, datetime

        if isinstance(val, datetime):
            return val
        if isinstance(val, date):
            return datetime(val.year, val.month, val.day)
        if isinstance(val, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                        "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
                try:
                    return datetime.strptime(val.strip(), fmt)
                except ValueError:
                    continue
        return None

    def _build_rules(self) -> list[str]:
        """Return list of active rule names for documentation."""
        return [
            "status_vs_rejection_reason",
            "status_vs_approval_message",
            "status_vs_comment_sentiment",
            "status_vs_active_flag",
            "status_vs_closed_flag",
            "country_vs_phone_code",
            "country_vs_phone_number",
            "email_format_vs_verified",
            "temporal_ordering",
            "status_vs_completion_date",
            "amount_without_currency",
            "name_email_coherence",
        ]


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════


def validate_coherence(
    data: dict[str, list[dict[str, Any]]],
) -> CoherenceReport:
    """Validate all tables for semantic coherence.

    Args:
        data: Dict mapping table_name → list of row dicts.

    Returns:
        CoherenceReport with all detected issues.
    """
    validator = CoherenceValidator()
    return validator.validate_all(data)


def validate_table_coherence(
    table_name: str,
    rows: list[dict[str, Any]],
    column_names: list[str] | None = None,
) -> TableCoherenceReport:
    """Validate a single table for semantic coherence.

    Args:
        table_name: Name of the table.
        rows: List of row dicts.
        column_names: Optional explicit column list.

    Returns:
        TableCoherenceReport with detected issues.
    """
    validator = CoherenceValidator()
    return validator.validate(table_name, rows, column_names)
