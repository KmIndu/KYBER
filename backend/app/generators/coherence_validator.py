"""Row-level coherence validator with auto-correction for generated data.

Enforces logical consistency rules during generation:
- Status-conditional fields (rejection_reason cleared for approved, etc.)
- Boolean alignment (is_active/is_closed match terminal states)
- Temporal ordering (created_at <= updated_at)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Terminal status categories ────────────────────────────────

_TERMINAL_NEGATIVE = {"rejected", "cancelled", "denied", "failed", "terminated", "closed"}
_TERMINAL_POSITIVE = {"approved", "completed", "fulfilled", "resolved", "paid"}
_IN_PROGRESS = {"pending", "in_progress", "processing", "submitted", "open", "active", "under_review"}


# ── Report model ─────────────────────────────────────────────


@dataclass
class CoherenceReport:
    """Summary of coherence validation results."""
    total_rows: int = 0
    total_violations: int = 0
    auto_corrections: int = 0
    violations_by_rule: dict[str, int] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        if self.total_rows == 0:
            return 1.0
        violating_rows = min(self.total_violations, self.total_rows)
        return (self.total_rows - violating_rows) / self.total_rows


# ── Validator ─────────────────────────────────────────────────


class CoherenceValidator:
    """Validates and optionally auto-corrects row-level coherence."""

    def __init__(self, auto_correct: bool = True):
        self._auto_correct = auto_correct

    def validate(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], CoherenceReport]:
        """Validate rows and return (corrected_rows, report)."""
        report = CoherenceReport(total_rows=len(rows))
        result = []

        for row in rows:
            corrected = dict(row)
            violations = 0
            corrections = 0

            # Rule 1: Status-conditional fields
            v, c = self._check_status_conditional(corrected)
            violations += v
            corrections += c

            # Rule 2: Boolean alignment
            v, c = self._check_boolean_alignment(corrected)
            violations += v
            corrections += c

            # Rule 3: Temporal ordering
            v, c = self._check_temporal_ordering(corrected)
            violations += v
            corrections += c

            report.total_violations += violations
            report.auto_corrections += corrections
            result.append(corrected)

        return result, report

    def _check_status_conditional(self, row: dict[str, Any]) -> tuple[int, int]:
        """Check status-dependent field rules."""
        violations = 0
        corrections = 0
        status = str(row.get("status", "")).lower()

        if not status:
            return 0, 0

        # Approved/positive terminal: rejection_reason must be None
        if status in _TERMINAL_POSITIVE:
            if row.get("rejection_reason") is not None:
                violations += 1
                if self._auto_correct:
                    row["rejection_reason"] = None
                    corrections += 1

        # Rejected/negative terminal: approved_amount should be 0
        if status in _TERMINAL_NEGATIVE:
            if "approved_amount" in row and row["approved_amount"] not in (0, 0.0, None):
                violations += 1
                if self._auto_correct:
                    row["approved_amount"] = 0
                    corrections += 1

        return violations, corrections

    def _check_boolean_alignment(self, row: dict[str, Any]) -> tuple[int, int]:
        """Check boolean flags align with status."""
        violations = 0
        corrections = 0
        status = str(row.get("status", "")).lower()

        if not status:
            return 0, 0

        # Terminal negative: is_active must be False
        if status in _TERMINAL_NEGATIVE:
            if "is_active" in row and row["is_active"] is True:
                violations += 1
                if self._auto_correct:
                    row["is_active"] = False
                    corrections += 1

        # Terminal positive: is_closed must be True
        if status in _TERMINAL_POSITIVE:
            if "is_closed" in row and row["is_closed"] is False:
                violations += 1
                if self._auto_correct:
                    row["is_closed"] = True
                    corrections += 1

        # In-progress: is_active should be True
        if status in _IN_PROGRESS:
            if "is_active" in row and row["is_active"] is False:
                violations += 1
                if self._auto_correct:
                    row["is_active"] = True
                    corrections += 1

        return violations, corrections

    def _check_temporal_ordering(self, row: dict[str, Any]) -> tuple[int, int]:
        """Check timestamp ordering (created <= updated)."""
        violations = 0
        corrections = 0

        created = row.get("created_at")
        updated = row.get("updated_at")

        if created is not None and updated is not None:
            # Compare as strings (ISO format) or datetime objects
            try:
                if str(created) > str(updated):
                    violations += 1
                    if self._auto_correct:
                        row["created_at"] = updated
                        row["updated_at"] = created
                        corrections += 1
            except (TypeError, ValueError):
                pass

        return violations, corrections
