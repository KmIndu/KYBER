"""Business rule reasoning models — inferred rules, validation logic, edge-case scenarios."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RuleCategory(str, Enum):
    """Categories of business rules."""

    AGE_RESTRICTION = "age_restriction"
    ELIGIBILITY = "eligibility"
    KYC = "kyc"
    APPROVAL = "approval"
    FINANCIAL = "financial"
    TEMPORAL = "temporal"
    STATUS_TRANSITION = "status_transition"
    THRESHOLD = "threshold"
    DEPENDENCY = "dependency"
    FORMAT = "format"


class RuleSource(str, Enum):
    """Origin of the inferred rule."""

    BDD = "bdd"
    SCHEMA = "schema"
    OPENAPI = "openapi"
    INFERRED = "inferred"


class RuleSeverity(str, Enum):
    """Impact level of rule violation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BusinessRule(BaseModel):
    """A single inferred business rule."""

    rule_id: str
    name: str
    category: RuleCategory
    source: RuleSource
    severity: RuleSeverity
    description: str
    condition: str
    fields: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)


class ValidationRule(BaseModel):
    """A validation rule derived from a business rule, ready for enforcement."""

    rule_id: str
    field: str
    operator: str  # eq, ne, gt, gte, lt, lte, in, not_in, matches, between, required, depends_on
    value: Any = None
    value_max: Any = None  # For 'between' operator
    error_message: str = ""


class EdgeCaseScenario(BaseModel):
    """An edge-case test scenario derived from a business rule."""

    rule_id: str
    scenario_name: str
    description: str
    test_inputs: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str  # "pass", "fail", "error"
    boundary_type: str = ""  # "below_min", "at_min", "above_max", "at_max", "null", "invalid"


class BusinessRuleMetadata(BaseModel):
    """Metadata about a business rule for documentation/tracing."""

    rule_id: str
    source_text: str = ""
    confidence: float = 1.0
    inferred_from: str = ""
    related_rules: list[str] = Field(default_factory=list)


class BusinessRuleResult(BaseModel):
    """Full result of business rule reasoning."""

    total_rules: int = 0
    total_validation_rules: int = 0
    total_edge_cases: int = 0
    rules: list[BusinessRule] = Field(default_factory=list)
    validation_rules: list[ValidationRule] = Field(default_factory=list)
    edge_cases: list[EdgeCaseScenario] = Field(default_factory=list)
    metadata: list[BusinessRuleMetadata] = Field(default_factory=list)
    rules_by_category: dict[str, int] = Field(default_factory=dict)
    rules_by_source: dict[str, int] = Field(default_factory=dict)
