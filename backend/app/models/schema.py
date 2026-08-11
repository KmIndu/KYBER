"""Core schema models — normalised representation of SQL DDL metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ColumnMetadata(BaseModel):
    """Metadata for a single column in a table."""

    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False
    is_unique: bool = False
    check_constraint: str | None = None


class ForeignKeyMetadata(BaseModel):
    """A single foreign-key relationship."""

    column: str
    references_table: str
    references_column: str


class TableMetadata(BaseModel):
    """Full metadata for a table including columns, keys, and constraints."""

    name: str
    columns: list[ColumnMetadata] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyMetadata] = Field(default_factory=list)
    unique_constraints: list[list[str]] = Field(default_factory=list)
    check_constraints: list[str] = Field(default_factory=list)


class SchemaMetadata(BaseModel):
    """Top-level container for all tables in a parsed schema."""

    tables: list[TableMetadata] = Field(default_factory=list)
