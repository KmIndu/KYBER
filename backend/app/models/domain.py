"""Domain detection models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DomainSignal(BaseModel):
    """A single signal that contributed to domain detection."""

    source: str  # "field_name", "table_name", "endpoint_name", "bdd_keyword"
    value: str  # the actual term that matched
    domain: str  # which domain it signals
    weight: float = 1.0


class DomainResult(BaseModel):
    """Result of domain detection analysis."""

    domain: str  # "banking", "insurance", "healthcare", "retail", "unknown"
    confidence: float  # 0.0 - 1.0
    signals: list[DomainSignal] = Field(default_factory=list)
    all_scores: dict[str, float] = Field(default_factory=dict)  # domain → score
