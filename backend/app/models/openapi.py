"""OpenAPI / Swagger metadata models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FieldValidation(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    enum: list[str] = Field(default_factory=list)


class OpenAPIFieldMetadata(BaseModel):
    name: str
    data_type: str
    format: str | None = None
    required: bool = False
    nullable: bool = True
    default: str | None = None
    validation: FieldValidation = Field(default_factory=FieldValidation)


class OpenAPISchemaMetadata(BaseModel):
    name: str
    fields: list[OpenAPIFieldMetadata] = Field(default_factory=list)


class OpenAPIMetadata(BaseModel):
    openapi_version: str = ""
    title: str = ""
    schemas: list[OpenAPISchemaMetadata] = Field(default_factory=list)
