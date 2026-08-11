"""Pydantic models for the export engine."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    SQL = "sql"


class TableExportInfo(BaseModel):
    """Metadata about a single exported table file."""

    table_name: str
    row_count: int
    file_name: str
    format: ExportFormat


class ExportSummary(BaseModel):
    """Summary metadata included in every export archive."""

    exported_at: datetime = Field(default_factory=datetime.utcnow)
    format: ExportFormat
    total_tables: int
    total_rows: int
    tables: list[TableExportInfo] = Field(default_factory=list)


class ExportResult(BaseModel):
    """Result returned by the export engine."""

    zip_path: str
    summary: ExportSummary
