"""Referential integrity engine.

Comprehensive analysis of FK relationships in both schema definitions
and generated data. Detects:
- Circular dependencies
- Broken FK references (table/column doesn't exist)
- Orphan rows (child rows referencing non-existent parent values)
- Dangling references (parent rows with no children where expected)
- Self-referencing tables
- Isolated tables
- Graph validation issues

Also provides:
- Dependency-safe generation order
- Parent-child ordering
- Orphan prevention guidance
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from app.models.integrity import (
    IntegrityIssue,
    IntegrityIssueType,
    IntegrityReport,
)
from app.models.schema import SchemaMetadata
from app.services.relationship_engine import RelationshipGraph

logger = logging.getLogger(__name__)


class ReferentialIntegrityEngine:
    """Analyze and enforce referential integrity across schema and generated data."""

    def __init__(self, schema: SchemaMetadata) -> None:
        self._schema = schema
        self._table_map = {t.name: t for t in schema.tables}
        self._graph = RelationshipGraph(schema)

    # ── Public API ─────────────────────────────────────────────

    def validate_schema(self) -> IntegrityReport:
        """Validate schema-level referential integrity (no data needed)."""
        issues: list[IntegrityIssue] = []

        issues.extend(self._check_circular_dependencies())
        issues.extend(self._check_broken_fk_references())
        issues.extend(self._check_self_references())
        issues.extend(self._check_isolated_tables())

        return self._build_report(issues)

    def validate_data(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> IntegrityReport:
        """Validate both schema and generated data for integrity issues."""
        issues: list[IntegrityIssue] = []

        # Schema-level checks
        issues.extend(self._check_circular_dependencies())
        issues.extend(self._check_broken_fk_references())
        issues.extend(self._check_self_references())
        issues.extend(self._check_isolated_tables())

        # Data-level checks
        issues.extend(self._check_orphan_rows(data))
        issues.extend(self._check_dangling_references(data))

        return self._build_report(issues)

    def get_generation_order(self) -> list[str]:
        """Return dependency-safe generation order (parents first)."""
        return self._graph.get_generation_order()

    def get_parent_child_map(self) -> dict[str, list[str]]:
        """Return mapping of each table to its child tables."""
        result: dict[str, list[str]] = {}
        for table_name in self._table_map:
            children = self._graph.get_child_tables(table_name)
            if children:
                result[table_name] = children
        return result

    # ── Schema-level checks ────────────────────────────────────

    def _check_circular_dependencies(self) -> list[IntegrityIssue]:
        """Detect circular FK dependencies in the schema."""
        issues: list[IntegrityIssue] = []
        cycles = self._graph.get_circular_dependencies()

        for cycle in cycles:
            cycle_str = " → ".join(cycle + [cycle[0]])
            issues.append(IntegrityIssue(
                issue_type=IntegrityIssueType.CIRCULAR_DEPENDENCY,
                severity="error",
                table=cycle[0],
                related_table=cycle[-1] if len(cycle) > 1 else cycle[0],
                message=f"Circular dependency detected: {cycle_str}",
            ))

        return issues

    def _check_broken_fk_references(self) -> list[IntegrityIssue]:
        """Detect FK references to non-existent tables or columns."""
        issues: list[IntegrityIssue] = []

        for table in self._schema.tables:
            for fk in table.foreign_keys:
                # Check if parent table exists
                if fk.references_table not in self._table_map:
                    issues.append(IntegrityIssue(
                        issue_type=IntegrityIssueType.MISSING_PARENT_TABLE,
                        severity="error",
                        table=table.name,
                        column=fk.column,
                        related_table=fk.references_table,
                        related_column=fk.references_column,
                        message=(
                            f"FK '{fk.column}' in '{table.name}' references "
                            f"non-existent table '{fk.references_table}'"
                        ),
                    ))
                    continue

                # Check if parent column exists
                parent_table = self._table_map[fk.references_table]
                parent_col_names = {c.name for c in parent_table.columns}
                if fk.references_column not in parent_col_names:
                    issues.append(IntegrityIssue(
                        issue_type=IntegrityIssueType.MISSING_PARENT_COLUMN,
                        severity="error",
                        table=table.name,
                        column=fk.column,
                        related_table=fk.references_table,
                        related_column=fk.references_column,
                        message=(
                            f"FK '{fk.column}' in '{table.name}' references "
                            f"non-existent column '{fk.references_table}.{fk.references_column}'"
                        ),
                    ))

                # Check if child column exists in the child table
                child_col_names = {c.name for c in table.columns}
                if fk.column not in child_col_names:
                    issues.append(IntegrityIssue(
                        issue_type=IntegrityIssueType.BROKEN_FK_REFERENCE,
                        severity="error",
                        table=table.name,
                        column=fk.column,
                        related_table=fk.references_table,
                        related_column=fk.references_column,
                        message=(
                            f"FK references column '{fk.column}' which does not exist "
                            f"in table '{table.name}'"
                        ),
                    ))

        return issues

    def _check_self_references(self) -> list[IntegrityIssue]:
        """Detect self-referencing FK constraints."""
        issues: list[IntegrityIssue] = []

        for table in self._schema.tables:
            for fk in table.foreign_keys:
                if fk.references_table == table.name:
                    issues.append(IntegrityIssue(
                        issue_type=IntegrityIssueType.SELF_REFERENCE,
                        severity="warning",
                        table=table.name,
                        column=fk.column,
                        related_table=table.name,
                        related_column=fk.references_column,
                        message=(
                            f"Self-referencing FK: '{table.name}.{fk.column}' → "
                            f"'{table.name}.{fk.references_column}'"
                        ),
                    ))

        return issues

    def _check_isolated_tables(self) -> list[IntegrityIssue]:
        """Detect tables with no FK relationships (neither parent nor child)."""
        issues: list[IntegrityIssue] = []

        if len(self._table_map) <= 1:
            return issues  # Single-table schemas are fine

        for table_name in self._table_map:
            parents = self._graph.get_parent_tables(table_name)
            children = self._graph.get_child_tables(table_name)
            if not parents and not children:
                issues.append(IntegrityIssue(
                    issue_type=IntegrityIssueType.ISOLATED_TABLE,
                    severity="info",
                    table=table_name,
                    message=f"Table '{table_name}' has no FK relationships (isolated)",
                ))

        return issues

    # ── Data-level checks ──────────────────────────────────────

    def _check_orphan_rows(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> list[IntegrityIssue]:
        """Detect child rows that reference non-existent parent values (orphans)."""
        issues: list[IntegrityIssue] = []

        for table in self._schema.tables:
            table_rows = data.get(table.name, [])
            if not table_rows:
                continue

            for fk in table.foreign_keys:
                if fk.references_table not in self._table_map:
                    continue  # Already reported as MISSING_PARENT_TABLE

                parent_rows = data.get(fk.references_table, [])
                parent_values = {r.get(fk.references_column) for r in parent_rows}

                for i, row in enumerate(table_rows):
                    val = row.get(fk.column)
                    if val is None:
                        continue  # Nullable FK, skip
                    if val not in parent_values:
                        issues.append(IntegrityIssue(
                            issue_type=IntegrityIssueType.ORPHAN_ROW,
                            severity="error",
                            table=table.name,
                            column=fk.column,
                            related_table=fk.references_table,
                            related_column=fk.references_column,
                            row_index=i,
                            value=str(val),
                            message=(
                                f"Orphan row: '{table.name}' row {i} has "
                                f"'{fk.column}' = {val} which does not exist in "
                                f"'{fk.references_table}.{fk.references_column}'"
                            ),
                        ))

        return issues

    def _check_dangling_references(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> list[IntegrityIssue]:
        """Detect parent rows that are not referenced by any child (informational)."""
        issues: list[IntegrityIssue] = []

        for table in self._schema.tables:
            for fk in table.foreign_keys:
                if fk.references_table not in self._table_map:
                    continue

                parent_rows = data.get(fk.references_table, [])
                child_rows = data.get(table.name, [])

                if not parent_rows or not child_rows:
                    continue

                child_values = {r.get(fk.column) for r in child_rows if r.get(fk.column) is not None}

                for i, parent_row in enumerate(parent_rows):
                    parent_val = parent_row.get(fk.references_column)
                    if parent_val is not None and parent_val not in child_values:
                        issues.append(IntegrityIssue(
                            issue_type=IntegrityIssueType.DANGLING_REFERENCE,
                            severity="info",
                            table=fk.references_table,
                            column=fk.references_column,
                            related_table=table.name,
                            related_column=fk.column,
                            row_index=i,
                            value=str(parent_val),
                            message=(
                                f"Unreferenced parent: '{fk.references_table}' row {i} "
                                f"'{fk.references_column}' = {parent_val} has no matching "
                                f"child in '{table.name}.{fk.column}'"
                            ),
                        ))

        return issues

    # ── Report builder ─────────────────────────────────────────

    def _build_report(self, issues: list[IntegrityIssue]) -> IntegrityReport:
        """Assemble the final integrity report."""
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        info = sum(1 for i in issues if i.severity == "info")

        # Generation order (only if no circular deps)
        try:
            generation_order = self._graph.get_generation_order()
        except Exception:
            generation_order = []

        return IntegrityReport(
            valid=errors == 0,
            total_issues=len(issues),
            errors=errors,
            warnings=warnings,
            info=info,
            issues=issues,
            generation_order=generation_order,
            dependency_edges=self._graph.get_edge_details(),
            root_tables=self._graph.get_root_tables(),
            leaf_tables=self._graph.get_leaf_tables(),
            cycles=self._graph.get_circular_dependencies(),
        )
