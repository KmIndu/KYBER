"""Negative / edge-case dataset models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NegativeToggles(BaseModel):
    """Configurable toggles for which negative cases to generate."""

    invalid_emails: bool = True
    null_required_fields: bool = True
    duplicate_values: bool = True
    broken_foreign_keys: bool = True
    boundary_values: bool = True
    invalid_enums: bool = True
    invalid_regex_patterns: bool = True


class NegativeRow(BaseModel):
    """A single invalid row with metadata about what was violated."""

    table: str
    violation: str  # e.g. "invalid_email", "null_required", ...
    column: str
    description: str
    row: dict


class NegativeDataset(BaseModel):
    """Holds both valid and invalid datasets separately."""

    valid: dict[str, list[dict]] = Field(default_factory=dict)
    invalid: list[NegativeRow] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
