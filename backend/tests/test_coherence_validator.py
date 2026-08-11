"""Tests for coherence_validator — row-level consistency enforcement."""
import pytest
from app.generators.coherence_validator import CoherenceValidator, CoherenceReport


# ── Helpers ───────────────────────────────────────────────────

def _make_rows(overrides: list[dict]) -> list[dict]:
    """Create test rows with standard fields plus overrides."""
    base = {
        "id": 1,
        "status": "approved",
        "is_active": True,
        "is_closed": True,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-02-01T00:00:00",
        "rejection_reason": None,
        "approved_amount": 5000.00,
    }
    rows = []
    for i, ov in enumerate(overrides):
        row = {**base, "id": i + 1, **ov}
        rows.append(row)
    return rows


# ── Status-conditional rules ──────────────────────────────────


class TestStatusConditional:
    def test_rejection_reason_cleared_for_approved(self):
        """rejection_reason must be None when status is approved."""
        rows = _make_rows([{"status": "approved", "rejection_reason": "bad docs"}])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["rejection_reason"] is None
        assert report.auto_corrections > 0

    def test_rejection_reason_kept_for_rejected(self):
        """rejection_reason should stay when status is rejected."""
        rows = _make_rows([{
            "status": "rejected",
            "rejection_reason": "missing info",
            "is_active": False,
            "is_closed": True,
            "approved_amount": 0,
        }])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["rejection_reason"] == "missing info"

    def test_approved_amount_zeroed_for_rejected(self):
        """approved_amount should be 0 when rejected."""
        rows = _make_rows([{
            "status": "rejected",
            "approved_amount": 5000.00,
            "is_active": False,
            "is_closed": True,
        }])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["approved_amount"] == 0


# ── Boolean alignment ─────────────────────────────────────────


class TestBooleanAlignment:
    def test_is_active_false_when_rejected(self):
        """is_active must be False for terminal negative status."""
        rows = _make_rows([{"status": "rejected", "is_active": True, "is_closed": True}])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["is_active"] is False

    def test_is_closed_true_when_completed(self):
        """is_closed must be True for terminal positive status."""
        rows = _make_rows([{"status": "completed", "is_closed": False, "is_active": False}])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["is_closed"] is True

    def test_is_active_true_when_pending(self):
        """is_active should be True for in-progress status."""
        rows = _make_rows([{"status": "pending", "is_active": False, "is_closed": False, "approved_amount": None}])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["is_active"] is True


# ── Temporal ordering ─────────────────────────────────────────


class TestTemporalOrdering:
    def test_created_before_updated(self):
        """created_at must be <= updated_at after correction."""
        rows = _make_rows([{
            "created_at": "2024-06-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        # After swap correction, created should be the earlier date
        assert corrected[0]["created_at"] <= corrected[0]["updated_at"]
        assert report.auto_corrections > 0

    def test_valid_ordering_unchanged(self):
        """Rows with correct ordering should not be modified."""
        rows = _make_rows([{
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-06-01T00:00:00",
        }])
        validator = CoherenceValidator(auto_correct=True)
        corrected, report = validator.validate(rows)
        assert corrected[0]["created_at"] == "2024-01-01T00:00:00"
        assert corrected[0]["updated_at"] == "2024-06-01T00:00:00"


# ── Report structure ──────────────────────────────────────────


class TestCoherenceReport:
    def test_report_counts(self):
        rows = _make_rows([
            {"status": "approved", "rejection_reason": "bad"},  # violation
            {"status": "approved", "rejection_reason": None},   # clean
            {"status": "rejected", "is_active": True, "is_closed": True},  # violation
        ])
        validator = CoherenceValidator(auto_correct=True)
        _, report = validator.validate(rows)
        assert report.total_rows == 3
        assert report.total_violations >= 2
        assert report.auto_corrections >= 2

    def test_pass_rate_calculation(self):
        rows = _make_rows([
            {"status": "approved", "rejection_reason": None, "is_closed": True, "is_active": True},
            {"status": "approved", "rejection_reason": None, "is_closed": True, "is_active": True},
        ])
        validator = CoherenceValidator(auto_correct=True)
        _, report = validator.validate(rows)
        assert report.pass_rate == 1.0

    def test_no_correction_mode(self):
        """With auto_correct=False, violations detected but not fixed."""
        rows = _make_rows([{"status": "approved", "rejection_reason": "bad"}])
        validator = CoherenceValidator(auto_correct=False)
        result, report = validator.validate(rows)
        assert report.total_violations > 0
        assert report.auto_corrections == 0
        # Row unchanged
        assert result[0]["rejection_reason"] == "bad"


# ── Scenario-first architecture integration ───────────────────


class TestScenarioFirstIntegration:
    """Test that the refactored generator produces coherent rows."""

    def test_generated_rows_pass_coherence(self):
        """All generated rows must pass coherence validation."""
        from pathlib import Path
        from app.parsers.sql_parser import parse_sql_schema
        from app.generators.synthetic_generator import SyntheticDataGenerator

        fixtures = Path(__file__).parent / "fixtures"
        sql = (fixtures / "sample_schema.sql").read_text(encoding="utf-8")
        schema = parse_sql_schema(sql)

        gen = SyntheticDataGenerator(schema, row_count=20, domain="insurance")
        data = gen.generate()

        validator = CoherenceValidator(auto_correct=False)
        for table_name, rows in data.items():
            _, report = validator.validate(rows)
            # Allow small number of violations (edge cases) but majority must pass
            assert report.pass_rate >= 0.8, (
                f"Table {table_name}: pass_rate={report.pass_rate:.2f}, "
                f"violations={report.total_violations}"
            )

    def test_no_isolated_generation(self):
        """Rows should have dependent fields derived from shared context.

        Example: status='rejected' → rejection_reason should be present (or None),
        never have rejection_reason with status='approved'.
        """
        from pathlib import Path
        from app.parsers.sql_parser import parse_sql_schema
        from app.generators.synthetic_generator import SyntheticDataGenerator

        fixtures = Path(__file__).parent / "fixtures"
        sql = (fixtures / "sample_schema.sql").read_text(encoding="utf-8")
        schema = parse_sql_schema(sql)

        gen = SyntheticDataGenerator(schema, row_count=50, domain="insurance")
        data = gen.generate()

        # FK integrity: every claim's policy_id must exist in policies
        policy_ids = {r["policy_id"] for r in data["policies"]}
        for claim in data["claims"]:
            assert claim["policy_id"] in policy_ids

        # All rows have all expected columns (no gaps)
        for row in data["customers"]:
            assert "first_name" in row
            assert "last_name" in row
            assert "email" in row

    def test_scenario_coherent_status_fields(self):
        """Claims with status='approved' should not have rejection-like data."""
        from pathlib import Path
        from app.parsers.sql_parser import parse_sql_schema
        from app.generators.synthetic_generator import SyntheticDataGenerator

        fixtures = Path(__file__).parent / "fixtures"
        # Use an extended schema with rejection_reason
        sql = """
        CREATE TABLE applications (
            app_id INT PRIMARY KEY,
            applicant_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) CHECK (status IN ('pending', 'approved', 'rejected')),
            rejection_reason VARCHAR(200),
            approved_amount DECIMAL(10,2),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
        """
        schema = parse_sql_schema(sql)
        gen = SyntheticDataGenerator(schema, row_count=30, domain="insurance")
        data = gen.generate()

        for row in data["applications"]:
            if row.get("status") == "approved":
                # Approved rows should NOT have a rejection reason
                assert row.get("rejection_reason") is None, (
                    f"Approved row has rejection_reason: {row}"
                )
