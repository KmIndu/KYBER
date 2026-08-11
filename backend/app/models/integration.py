"""Pydantic models for test-environment integration artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntegrationFormat(str, Enum):
    POSTMAN = "postman"
    MOCK_PAYLOAD = "mock_payload"
    SQL_INSERT = "sql_insert"
    API_JSON = "api_json"
    SWAGGER_TEST = "swagger_test"
    CI_BUNDLE = "ci_bundle"


class PostmanRequest(BaseModel):
    """A single request item inside a Postman collection."""

    name: str
    method: str = "POST"
    url: str
    headers: list[dict[str, str]] = Field(default_factory=list)
    body: dict[str, Any] | None = None


class PostmanCollection(BaseModel):
    """Postman Collection v2.1 structure."""

    info: dict[str, str]
    item: list[dict[str, Any]] = Field(default_factory=list)


class MockPayload(BaseModel):
    """A mock payload for a single table/entity."""

    entity: str
    valid: list[dict[str, Any]] = Field(default_factory=list)
    invalid: list[dict[str, Any]] = Field(default_factory=list)
    boundary: list[dict[str, Any]] = Field(default_factory=list)


class APIPayload(BaseModel):
    """API-ready JSON payload for a single entity."""

    entity: str
    endpoint: str
    method: str = "POST"
    content_type: str = "application/json"
    payloads: list[dict[str, Any]] = Field(default_factory=list)


class SwaggerTestCase(BaseModel):
    """A single Swagger test case definition."""

    operation_id: str
    method: str
    path: str
    request_body: dict[str, Any] | None = None
    expected_status: int = 200
    description: str = ""


class SwaggerTestSuite(BaseModel):
    """Collection of Swagger test cases for API validation."""

    title: str
    base_url: str = "http://localhost:8080"
    tests: list[SwaggerTestCase] = Field(default_factory=list)


class CIConfig(BaseModel):
    """CI/CD pipeline configuration fragment."""

    pipeline_name: str
    stages: list[dict[str, Any]] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)


class IntegrationArtifact(BaseModel):
    """Result of generating a single integration artifact."""

    format: IntegrationFormat
    filename: str
    content_type: str
    size_bytes: int


class IntegrationBundle(BaseModel):
    """Result of generating the full integration bundle."""

    session_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    zip_path: str
    artifacts: list[IntegrationArtifact] = Field(default_factory=list)
    total_tables: int = 0
    total_rows: int = 0


# ── AI Integration Assistant models ──────────────────────────


class GuideStep(BaseModel):
    """A single step within an integration guide."""

    step_number: int
    title: str
    description: str
    code_snippet: str = ""
    language: str = ""  # e.g. "sql", "bash", "python", "json"


class IntegrationGuideSection(BaseModel):
    """A guide section for one integration scenario."""

    scenario: str  # e.g. "Import CSV into PostgreSQL"
    summary: str
    prerequisites: list[str] = Field(default_factory=list)
    steps: list[GuideStep] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class IntegrationGuide(BaseModel):
    """Full AI-generated integration guide for using generated datasets."""

    session_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    overview: str = ""
    sections: list[IntegrationGuideSection] = Field(default_factory=list)
    provider: str = ""  # "gateway" or "offline"
