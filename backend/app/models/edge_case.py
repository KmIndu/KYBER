"""Edge-case analysis models.

Structured representation of edge-case rules, categories, and the
full analysis result for a schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EdgeCaseCategory(str, Enum):
    """Categories of edge-case values."""

    NULL = "null"
    BOUNDARY = "boundary"
    NEGATIVE = "negative"
    OVERFLOW = "overflow"
    INVALID_FORMAT = "invalid_format"
    DUPLICATE = "duplicate"
    TYPE_MISMATCH = "type_mismatch"
    EMPTY = "empty"
    SPECIAL_CHARS = "special_chars"


class EdgeCaseToggles(BaseModel):
    """Configurable toggles for which edge-case categories to generate."""

    null_values: bool = True
    boundary_values: bool = True
    negative_values: bool = True
    overflow_values: bool = True
    invalid_formats: bool = True
    duplicate_values: bool = True
    type_mismatch: bool = True
    empty_values: bool = True
    special_chars: bool = True


class EdgeCaseRule(BaseModel):
    """A single edge-case rule for a column."""

    table: str
    column: str
    category: EdgeCaseCategory
    description: str
    test_value: Any = None
    expected_behavior: str = "should be rejected"
    data_type: str = ""
    source: str = "engine"  # "engine", "ai", "bdd"


class EdgeCaseColumnSummary(BaseModel):
    """Summary of edge cases for a single column."""

    table: str
    column: str
    data_type: str
    rule_count: int = 0
    categories: list[str] = Field(default_factory=list)


class EdgeCaseAnalysis(BaseModel):
    """Full edge-case analysis result for a schema."""

    session_id: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    rules: list[EdgeCaseRule] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)  # category → count
    column_summaries: list[EdgeCaseColumnSummary] = Field(default_factory=list)
    total_rules: int = 0
    tables_analyzed: int = 0
    columns_analyzed: int = 0
