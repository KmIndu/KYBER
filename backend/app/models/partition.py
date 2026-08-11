"""Equivalence partitioning models.

Structured representation of partitions (valid / invalid / boundary),
partition summaries, metadata, and generated sample datasets.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class PartitionType(str, Enum):
    """Classification of a partition."""

    VALID = "valid"
    INVALID = "invalid"
    BOUNDARY = "boundary"
    DUPLICATE = "duplicate"


class DatasetSplitConfig(BaseModel):
    """User-defined distribution for dataset generation.

    Percentages must be >= 0 and sum to 100.
    """

    valid_pct: float = 80.0
    invalid_pct: float = 10.0
    boundary_pct: float = 10.0
    duplicate_pct: float = 0.0

    @model_validator(mode="after")
    def _validate_percentages(self) -> "DatasetSplitConfig":
        for field in ("valid_pct", "invalid_pct", "boundary_pct", "duplicate_pct"):
            if getattr(self, field) < 0:
                raise ValueError("Percentages must be >= 0")
        total = round(
            self.valid_pct + self.invalid_pct + self.boundary_pct + self.duplicate_pct, 2
        )
        if total != 100.0:
            raise ValueError(
                f"valid_pct + invalid_pct + boundary_pct + duplicate_pct must equal 100 (got {total})"
            )
        return self


class Partition(BaseModel):
    """A single equivalence partition for a column."""

    table: str
    column: str
    partition_type: PartitionType
    label: str
    description: str
    range_low: float | int | str | None = None
    range_high: float | int | str | None = None
    sample_values: list[Any] = Field(default_factory=list)
    data_type: str = ""
    constraint_source: str = ""  # "check", "type", "nullable", "enum", "heuristic"


class PartitionColumnSummary(BaseModel):
    """Summary of partitions for a single column."""

    table: str
    column: str
    data_type: str
    total_partitions: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    boundary_count: int = 0


class PartitionDatasetRow(BaseModel):
    """A single generated row from a partition."""

    table: str
    partition_label: str
    partition_type: PartitionType
    row: dict[str, Any] = Field(default_factory=dict)


class PartitionDataset(BaseModel):
    """Generated dataset from partitions for a table."""

    table: str
    rows: list[PartitionDatasetRow] = Field(default_factory=list)
    total_rows: int = 0


class PartitionVisualization(BaseModel):
    """Visualization-ready output for a column's partitions."""

    table: str
    column: str
    data_type: str
    partitions: list[dict[str, Any]] = Field(default_factory=list)
    # Each dict: { "label", "type", "low", "high", "sample_count", "color" }


class PartitionAnalysis(BaseModel):
    """Full equivalence partitioning analysis result."""

    session_id: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    partitions: list[Partition] = Field(default_factory=list)
    column_summaries: list[PartitionColumnSummary] = Field(default_factory=list)
    datasets: list[PartitionDataset] = Field(default_factory=list)
    visualizations: list[PartitionVisualization] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)  # partition_type → count
    total_partitions: int = 0
    tables_analyzed: int = 0
    columns_analyzed: int = 0
    total_generated_rows: int = 0
    split_config: DatasetSplitConfig | None = None
