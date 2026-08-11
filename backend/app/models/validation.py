"""Validation result models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationError(BaseModel):
    """A single validation failure."""

    table: str
    row_index: int
    column: str
    rule: str  # "pk_unique", "fk_valid", "unique", "type", "enum", "regex", "nullable"
    expected: str
    actual: str
    message: str


class TableValidationReport(BaseModel):
    """Validation report for a single table."""

    table: str
    total_rows: int = 0
    passed: int = 0
    failed: int = 0
    errors: list[ValidationError] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Full validation report across all tables."""

    total_rows: int = 0
    passed: int = 0
    failed: int = 0
    tables: list[TableValidationReport] = Field(default_factory=list)
    errors: list[ValidationError] = Field(default_factory=list)
