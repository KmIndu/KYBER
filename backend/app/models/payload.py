"""OpenAPI payload generation models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PayloadType(str, Enum):
    """Types of generated payloads."""

    REQUEST = "request"
    RESPONSE = "response"
    MOCK = "mock"
    INVALID = "invalid"


class GeneratedPayload(BaseModel):
    """A single generated API payload."""

    schema_name: str
    payload_type: PayloadType
    body: dict | list = Field(default_factory=dict)
    description: str = ""


class PayloadGenerationResult(BaseModel):
    """Complete payload generation result for an OpenAPI spec."""

    total_schemas: int = 0
    total_payloads: int = 0
    payloads: list[GeneratedPayload] = Field(default_factory=list)
