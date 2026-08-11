"""Referential integrity models — results of integrity analysis."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IntegrityIssueType(str, Enum):
    """Categories of referential integrity issues."""

    CIRCULAR_DEPENDENCY = "circular_dependency"
    ORPHAN_ROW = "orphan_row"
    BROKEN_FK_REFERENCE = "broken_fk_reference"
    MISSING_PARENT_TABLE = "missing_parent_table"
    MISSING_PARENT_COLUMN = "missing_parent_column"
    SELF_REFERENCE = "self_reference"
    DANGLING_REFERENCE = "dangling_reference"
    ISOLATED_TABLE = "isolated_table"


class IntegrityIssue(BaseModel):
    """A single integrity issue found in the schema or data."""

    issue_type: IntegrityIssueType
    severity: str = "error"  # "error", "warning", "info"
    table: str = ""
    column: str = ""
    related_table: str = ""
    related_column: str = ""
    row_index: int | None = None
    value: str | None = None
    message: str = ""


class IntegrityReport(BaseModel):
    """Complete referential integrity analysis report."""

    valid: bool = True
    total_issues: int = 0
    errors: int = 0
    warnings: int = 0
    info: int = 0
    issues: list[IntegrityIssue] = Field(default_factory=list)
    generation_order: list[str] = Field(default_factory=list)
    dependency_edges: list[dict[str, str]] = Field(default_factory=list)
    root_tables: list[str] = Field(default_factory=list)
    leaf_tables: list[str] = Field(default_factory=list)
    cycles: list[list[str]] = Field(default_factory=list)
