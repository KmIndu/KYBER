"""Constraint enforcement models — detailed reports on constraint compliance."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ConstraintType(str, Enum):
    """Types of constraints the engine can enforce."""

    NULLABLE = "nullable"
    REGEX = "regex"
    ENUM = "enum"
    UNIQUE = "unique"
    RANGE = "range"
    COMPOSITE_KEY = "composite_key"


class ConstraintViolation(BaseModel):
    """A single constraint violation detected during enforcement."""

    table: str
    row_index: int
    columns: list[str]
    constraint_type: ConstraintType
    constraint_definition: str
    value: str
    expected: str
    message: str


class ConstraintSummary(BaseModel):
    """Summary statistics for a single constraint type."""

    constraint_type: ConstraintType
    total_checks: int = 0
    passed: int = 0
    failed: int = 0


class TableEnforcementReport(BaseModel):
    """Enforcement report for a single table."""

    table: str
    total_rows: int = 0
    total_checks: int = 0
    violations: list[ConstraintViolation] = Field(default_factory=list)
    constraints_summary: list[ConstraintSummary] = Field(default_factory=list)


class EnforcementReport(BaseModel):
    """Full constraint enforcement report across all tables."""

    total_rows: int = 0
    total_constraints_checked: int = 0
    total_violations: int = 0
    compliance_rate: float = 1.0
    tables: list[TableEnforcementReport] = Field(default_factory=list)
    violations: list[ConstraintViolation] = Field(default_factory=list)
    summary_by_type: list[ConstraintSummary] = Field(default_factory=list)
