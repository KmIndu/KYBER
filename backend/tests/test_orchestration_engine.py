"""Tests for the Generation Flow Orchestration Engine."""

import pytest

from app.models.schema import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata
from app.generators.orchestration_engine import (
    GenerationOrchestrator,
    get_generation_flow_stages,
    orchestrate_generation,
    orchestrate_table_generation,
)


def _claims_table() -> TableMetadata:
    return TableMetadata(
        name="claims",
        columns=[
            ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
            ColumnMetadata(
                name="status",
                data_type="VARCHAR(20)",
                check_constraint="status IN ('pending','approved','rejected','closed')",
            ),
            ColumnMetadata(name="amount", data_type="DECIMAL(10,2)"),
            ColumnMetadata(name="submitted_at", data_type="TIMESTAMP"),
            ColumnMetadata(name="rejection_reason", data_type="VARCHAR(200)", nullable=True),
            ColumnMetadata(name="claimant_name", data_type="VARCHAR(100)"),
            ColumnMetadata(name="email", data_type="VARCHAR(100)"),
        ],
        foreign_keys=[],
    )


def _multi_table_schema() -> SchemaMetadata:
    customers = TableMetadata(
        name="customers",
        columns=[
            ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
            ColumnMetadata(name="full_name", data_type="VARCHAR(100)"),
            ColumnMetadata(name="email", data_type="VARCHAR(100)"),
            ColumnMetadata(name="country", data_type="VARCHAR(50)"),
        ],
        foreign_keys=[],
    )
    orders = TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
            ColumnMetadata(name="customer_id", data_type="INTEGER"),
            ColumnMetadata(
                name="status",
                data_type="VARCHAR(20)",
                check_constraint="status IN ('pending','shipped','delivered','cancelled')",
            ),
            ColumnMetadata(name="total_amount", data_type="DECIMAL(10,2)"),
            ColumnMetadata(name="created_at", data_type="TIMESTAMP"),
        ],
        foreign_keys=[
            ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
        ],
    )
    return SchemaMetadata(tables=[customers, orders])


class TestOrchestrationStages:
    """Test the 8-stage pipeline definition."""

    def test_stages_are_eight(self):
        stages = get_generation_flow_stages()
        assert len(stages) == 8

    def test_stages_ordered(self):
        stages = get_generation_flow_stages()
        assert stages[0]["name"] == "understand_schema"
        assert stages[4]["name"] == "determine_scenario"
        assert stages[7]["name"] == "generate_final_rows"

    def test_stages_have_descriptions(self):
        stages = get_generation_flow_stages()
        for s in stages:
            assert "description" in s
            assert len(s["description"]) > 10


class TestSingleTableOrchestration:
    """Test orchestrated generation for a single table."""

    def test_produces_correct_row_count(self):
        table = _claims_table()
        rows, report = orchestrate_table_generation(table, row_count=10, domain="insurance")
        assert len(rows) == 10

    def test_rows_have_all_columns(self):
        table = _claims_table()
        rows, _ = orchestrate_table_generation(table, row_count=5, domain="insurance")
        expected_cols = {"id", "status", "amount", "submitted_at", "rejection_reason", "claimant_name", "email"}
        for row in rows:
            # rejection_reason can be None (nullable)
            assert set(row.keys()) == expected_cols

    def test_pk_is_sequential(self):
        table = _claims_table()
        rows, _ = orchestrate_table_generation(table, row_count=5)
        ids = [r["id"] for r in rows]
        assert ids == [1, 2, 3, 4, 5]

    def test_status_values_from_constraint(self):
        table = _claims_table()
        rows, _ = orchestrate_table_generation(table, row_count=20, domain="insurance")
        valid_statuses = {"pending", "approved", "rejected", "closed"}
        for row in rows:
            if row["status"] is not None:
                assert row["status"] in valid_statuses, f"Invalid status: {row['status']}"

    def test_report_has_stages(self):
        table = _claims_table()
        _, report = orchestrate_table_generation(table, row_count=5)
        assert "stages" in report
        assert len(report["stages"]) == 8
        assert report["stages"][0]["stage"] == "understand_schema"
        assert report["rows_generated"] == 5

    def test_coherence_corrections_tracked(self):
        table = _claims_table()
        _, report = orchestrate_table_generation(table, row_count=20, domain="insurance")
        # corrections_applied can be 0 or more — just check it's tracked
        assert "rows_corrected" in report
        assert isinstance(report["rows_corrected"], int)


class TestMultiTableOrchestration:
    """Test orchestrated generation with FK relationships."""

    def test_multi_table_generation(self):
        schema = _multi_table_schema()
        data, reports = orchestrate_generation(schema, row_count=5, domain="ecommerce")
        assert "customers" in data
        assert "orders" in data
        assert len(data["customers"]) == 5
        assert len(data["orders"]) == 5

    def test_fk_integrity(self):
        schema = _multi_table_schema()
        data, _ = orchestrate_generation(schema, row_count=10, domain="ecommerce")
        customer_ids = {r["id"] for r in data["customers"]}
        for order in data["orders"]:
            assert order["customer_id"] in customer_ids

    def test_reports_for_all_tables(self):
        schema = _multi_table_schema()
        _, reports = orchestrate_generation(schema, row_count=5)
        assert "customers" in reports
        assert "orders" in reports
        for name, report in reports.items():
            assert report["rows_generated"] == 5


class TestScenarioFirstBehavior:
    """Verify that generation is truly scenario-first."""

    def test_scenario_stage_runs_before_derivation(self):
        table = _claims_table()
        _, report = orchestrate_table_generation(table, row_count=5, domain="insurance")
        stage_names = [s["stage"] for s in report["stages"]]
        scenario_idx = stage_names.index("determine_scenario")
        derivation_idx = stage_names.index("derive_dependent_values")
        assert scenario_idx < derivation_idx

    def test_validation_runs_after_derivation(self):
        table = _claims_table()
        _, report = orchestrate_table_generation(table, row_count=5, domain="insurance")
        stage_names = [s["stage"] for s in report["stages"]]
        validation_idx = stage_names.index("validate_consistency")
        derivation_idx = stage_names.index("derive_dependent_values")
        assert validation_idx > derivation_idx

    def test_rejected_rows_no_approval_artifacts(self):
        """Rejected rows should not have approval-related data after correction."""
        table = TableMetadata(
            name="applications",
            columns=[
                ColumnMetadata(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnMetadata(
                    name="status",
                    data_type="VARCHAR(20)",
                    check_constraint="status IN ('pending','approved','rejected')",
                ),
                ColumnMetadata(name="approval_date", data_type="DATE", nullable=True),
                ColumnMetadata(name="rejection_reason", data_type="VARCHAR(200)", nullable=True),
            ],
            foreign_keys=[],
        )
        rows, _ = orchestrate_table_generation(table, row_count=50, domain="insurance")
        for row in rows:
            if row["status"] == "rejected":
                assert row["approval_date"] is None, (
                    f"Rejected row should not have approval_date: {row}"
                )
            if row["status"] == "approved":
                assert row["rejection_reason"] is None, (
                    f"Approved row should not have rejection_reason: {row}"
                )


class TestRetryMechanism:
    """Test the retry mechanism in the orchestrator."""

    def test_orchestrator_max_retries(self):
        schema = SchemaMetadata(tables=[_claims_table()])
        orch = GenerationOrchestrator(schema=schema, row_count=5, max_retries=3)
        assert orch._max_retries == 3

    def test_all_stages_succeed(self):
        table = _claims_table()
        _, report = orchestrate_table_generation(table, row_count=5)
        for stage in report["stages"]:
            assert stage["success"] is True, f"Stage {stage['stage']} failed"
