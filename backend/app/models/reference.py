"""Pydantic models for the reference-document ingestion system.

Covers OCR extraction, entity/field/relationship extraction,
confidence scoring, and schema generation from images and BRD snippets.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ─────────────────────────────────────────────────────


class ReferenceDocType(str, Enum):
    """Supported reference-document categories."""

    SCREENSHOT = "screenshot"
    SCHEMA_IMAGE = "schema_image"
    BRD_SNIPPET = "brd_snippet"
    API_SCREENSHOT = "api_screenshot"


class ExtractionSource(str, Enum):
    """How a piece of metadata was extracted."""

    OCR = "ocr"
    AI = "ai"
    HEURISTIC = "heuristic"


# ── OCR result ────────────────────────────────────────────────


class OCRBlock(BaseModel):
    """A single block of text recognised by the OCR engine."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0, description="OCR confidence 0–1")
    bbox: list[int] = Field(
        default_factory=list,
        description="Bounding box [x, y, w, h] in pixels",
    )


class OCRResult(BaseModel):
    """Full OCR output for one image."""

    raw_text: str = ""
    blocks: list[OCRBlock] = Field(default_factory=list)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    image_width: int = 0
    image_height: int = 0


# ── Extracted entities / fields ───────────────────────────────


class ExtractedField(BaseModel):
    """A column / field extracted from a reference document."""

    name: str
    data_type: str = "VARCHAR"
    nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    check_constraint: str | None = None
    description: str = ""
    source: ExtractionSource = ExtractionSource.HEURISTIC
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExtractedEntity(BaseModel):
    """A table / entity extracted from a reference document."""

    name: str
    description: str = ""
    fields: list[ExtractedField] = Field(default_factory=list)
    source: ExtractionSource = ExtractionSource.HEURISTIC
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExtractedRelationship(BaseModel):
    """A foreign-key relationship inferred between entities."""

    from_entity: str
    from_field: str
    to_entity: str
    to_field: str
    source: ExtractionSource = ExtractionSource.HEURISTIC
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExtractedConstraint(BaseModel):
    """A business constraint extracted from the document."""

    entity: str
    field: str
    rule: str
    description: str = ""
    source: ExtractionSource = ExtractionSource.HEURISTIC
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ── Ingestion result ─────────────────────────────────────────


class ReferenceIngestionResult(BaseModel):
    """Complete result from ingesting one or more reference documents."""

    model_config = ConfigDict(protected_namespaces=())

    doc_type: ReferenceDocType
    filename: str = ""
    ocr: OCRResult = Field(default_factory=OCRResult)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    constraints: list[ExtractedConstraint] = Field(default_factory=list)
    domain: str = ""
    schema_sql: str = ""
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


# ── Generate response ────────────────────────────────────────


class ReferenceGenerateResponse(BaseModel):
    """Response from the reference-doc generate endpoint."""

    session_id: str
    filename: str = ""
    doc_type: str = ""
    domain: str = ""
    tables: list[ReferenceTableInfo] = Field(default_factory=list)
    total_rows: int = 0
    negative_cases: int = 0
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    generation_order: list[str] = Field(default_factory=list)
    schema_sql: str = ""
    message: str = "Generation complete"


class ReferenceTableInfo(BaseModel):
    """Per-table row count in the reference-doc generation response."""

    table_name: str
    row_count: int
