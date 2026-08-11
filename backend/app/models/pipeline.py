"""Pydantic models for the unified pipeline API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.export import ExportFormat, ExportSummary
from app.models.validation import ValidationReport


# ── Upload response ───────────────────────────────────────────


class UploadedFileInfo(BaseModel):
    filename: str
    file_type: str  # "sql", "openapi", "bdd"
    size_bytes: int


class UploadResponse(BaseModel):
    session_id: str
    files: list[UploadedFileInfo] = Field(default_factory=list)
    message: str = "Files uploaded successfully"


# ── Parse response ────────────────────────────────────────────


class ParsedTableInfo(BaseModel):
    name: str
    column_count: int
    primary_keys: list[str] = Field(default_factory=list)
    foreign_keys: int = 0
    has_check_constraints: bool = False


class ParseResponse(BaseModel):
    session_id: str
    tables: list[ParsedTableInfo] = Field(default_factory=list)
    generation_order: list[str] = Field(default_factory=list)
    openapi_schemas: int = 0
    bdd_scenarios: int = 0
    message: str = "Parsing complete"


# ── Generate response ─────────────────────────────────────────


class GenerateTableInfo(BaseModel):
    table_name: str
    row_count: int


class GenerateResponse(BaseModel):
    session_id: str
    row_count: int
    tables: list[GenerateTableInfo] = Field(default_factory=list)
    total_rows: int = 0
    negative_cases: int = 0
    validation: ValidationReport | None = None
    ai_enhanced: bool = False
    message: str = "Generation complete"


# ── Summary response ──────────────────────────────────────────


class DownloadLink(BaseModel):
    format: str
    url: str


class SummaryResponse(BaseModel):
    session_id: str
    uploaded_files: list[UploadedFileInfo] = Field(default_factory=list)
    tables_parsed: int = 0
    generation_order: list[str] = Field(default_factory=list)
    row_count: int = 0
    total_rows: int = 0
    negative_cases: int = 0
    validation: ValidationReport | None = None
    coherence: dict[str, Any] | None = None
    business_context: dict[str, Any] | None = None
    exports: list[DownloadLink] = Field(default_factory=list)
    generated_at: datetime | None = None
    ai_enhanced: bool = False
