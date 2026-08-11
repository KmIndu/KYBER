"""Pydantic models for natural-language dataset generation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.schema import SchemaMetadata
from app.models.validation import ValidationReport


class NLRequest(BaseModel):
    """User's natural-language prompt describing desired data."""

    prompt: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Natural-language description, e.g. 'Generate banking customer data with failed KYC cases'",
    )
    row_count: int = Field(default=10, ge=1, le=1000000, description="Rows per table")
    include_invalid: bool = Field(default=False, description="Include negative/edge cases")


class InferredEntity(BaseModel):
    """A single entity (table) inferred from the prompt."""

    name: str
    description: str = ""
    columns: list[InferredColumn] = Field(default_factory=list)


class InferredColumn(BaseModel):
    """A single column inferred for an entity."""

    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    check_constraint: str | None = None
    description: str = ""


class InferredRelationship(BaseModel):
    """A foreign-key relationship inferred between entities."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str


class InferredConstraint(BaseModel):
    """A domain constraint inferred from the prompt."""

    table: str
    column: str
    rule: str
    description: str = ""


class NLSchemaResult(BaseModel):
    """Full result of NL → schema inference."""

    model_config = ConfigDict(protected_namespaces=())

    domain: str = Field(default="", description="Inferred business domain")
    entities: list[InferredEntity] = Field(default_factory=list)
    relationships: list[InferredRelationship] = Field(default_factory=list)
    constraints: list[InferredConstraint] = Field(default_factory=list)
    schema: SchemaMetadata = Field(default_factory=SchemaMetadata)
    generation_order: list[str] = Field(default_factory=list)
    generated_sql: str = Field(default="", description="Equivalent DDL for the inferred schema")


class NLGenerateResponse(BaseModel):
    """Response from the NL generate endpoint."""

    session_id: str
    prompt: str
    domain: str = ""
    tables: list[NLGenerateTableInfo] = Field(default_factory=list)
    total_rows: int = 0
    negative_cases: int = 0
    validation: ValidationReport | None = None
    generation_order: list[str] = Field(default_factory=list)
    generated_sql: str = ""
    message: str = "Generation complete"


class NLGenerateTableInfo(BaseModel):
    """Per-table row count in NL generation response."""

    table_name: str
    row_count: int


# Rebuild forward refs for nested models
InferredEntity.model_rebuild()
