"""BDD / Gherkin metadata models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BDDRule(BaseModel):
    field: str
    condition: str
    result: str


class BDDScenario(BaseModel):
    name: str = ""
    rules: list[BDDRule] = Field(default_factory=list)
    raw_steps: list[str] = Field(default_factory=list)


class BDDMetadata(BaseModel):
    feature: str = ""
    scenarios: list[BDDScenario] = Field(default_factory=list)
