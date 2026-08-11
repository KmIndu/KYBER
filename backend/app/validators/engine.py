"""Validation engine — orchestrates all validators across a dataset.

Takes a SchemaMetadata and generated data, runs every validator,
and produces a comprehensive ValidationReport.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.schema import SchemaMetadata
from app.models.validation import TableValidationReport, ValidationReport
from app.validators.validators import (
    EnumValidator,
    FKValidator,
    NullableValidator,
    PKValidator,
    RegexValidator,
    TypeValidator,
    UniqueValidator,
)

logger = logging.getLogger(__name__)


class ValidationEngine:
    """Run all validators against generated data and produce a report."""

    # Sample size for large-dataset validation — validates a random subset
    # rather than all rows to keep the pipeline fast at scale.
    SAMPLE_THRESHOLD = 100_000
    SAMPLE_SIZE = 10_000

    def __init__(self, schema: SchemaMetadata) -> None:
        self._schema = schema
        self._table_map = {t.name: t for t in schema.tables}
        # Reusable validator instances
        self._pk = PKValidator()
        self._fk = FKValidator()
        self._unique = UniqueValidator()
        self._type = TypeValidator()
        self._enum = EnumValidator()
        self._nullable = NullableValidator()
        self._regex = RegexValidator()

    def validate(
        self, data: dict[str, list[dict[str, Any]]]
    ) -> ValidationReport:
        """Validate all tables and return a full report.

        For tables with more than SAMPLE_THRESHOLD rows, a random sample
        is validated and results are extrapolated to the full table size.
        """
        import random as _rand

        all_errors = []
        table_reports = []
        total_rows = 0

        for table_name, rows in data.items():
            table = self._table_map.get(table_name)
            if not table:
                logger.warning(
                    "Table '%s' not found in schema, skipping",
                    table_name,
                    extra={"stage": "validation", "event": "table_not_in_schema", "table": table_name},
                )
                continue

            actual_count = len(rows)
            sampled = False

            # Sample for large datasets
            if actual_count > self.SAMPLE_THRESHOLD:
                sample_rows = _rand.sample(rows, self.SAMPLE_SIZE)
                sampled = True
                logger.info(
                    "Sampling %d of %d rows for validation on %s",
                    self.SAMPLE_SIZE,
                    actual_count,
                    table_name,
                    extra={"stage": "validation", "event": "sampling", "table": table_name},
                )
            else:
                sample_rows = rows

            table_errors = []
            table_errors.extend(self._pk.validate(table, sample_rows))
            table_errors.extend(self._fk.validate(table, sample_rows, data))
            table_errors.extend(self._unique.validate(table, sample_rows))
            table_errors.extend(self._type.validate(table, sample_rows))
            table_errors.extend(self._enum.validate(table, sample_rows))
            table_errors.extend(self._nullable.validate(table, sample_rows))
            table_errors.extend(self._regex.validate(table, sample_rows))

            # Count unique failing rows
            failing_rows = {e.row_index for e in table_errors}

            if sampled:
                # Extrapolate sample results to full table
                sample_pass_rate = (len(sample_rows) - len(failing_rows)) / max(len(sample_rows), 1)
                passed = int(actual_count * sample_pass_rate)
                failed = actual_count - passed
            else:
                passed = actual_count - len(failing_rows)
                failed = len(failing_rows)

            table_report = TableValidationReport(
                table=table_name,
                total_rows=actual_count,
                passed=passed,
                failed=failed,
                errors=table_errors,
            )
            table_reports.append(table_report)
            all_errors.extend(table_errors)
            total_rows += actual_count

            logger.info(
                "Validated %s: %d passed, %d failed (%d errors)%s",
                table_name,
                passed,
                failed,
                len(table_errors),
                " (sampled)" if sampled else "",
                extra={"stage": "validation", "event": "table_validated", "table": table_name},
            )

        total_passed = sum(t.passed for t in table_reports)
        total_failed = sum(t.failed for t in table_reports)

        return ValidationReport(
            total_rows=total_rows,
            passed=total_passed,
            failed=total_failed,
            tables=table_reports,
            errors=all_errors,
        )
