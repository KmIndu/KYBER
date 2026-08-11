"""Offline rule-based AI reasoning provider.

Produces deterministic hidden constraints, business rules, and edge cases
by analyzing schema structure, BDD rules, and OpenAPI specs using
heuristics — no external API calls required.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.ai import AIConstraint, AIEdgeCase, AIReasoningResult
from app.models.bdd import BDDMetadata
from app.models.openapi import OpenAPIMetadata
from app.models.schema import SchemaMetadata


def reason_offline(
    schema: SchemaMetadata | None = None,
    bdd: BDDMetadata | None = None,
    openapi: OpenAPIMetadata | None = None,
) -> AIReasoningResult:
    """Run offline rule-based reasoning across all provided metadata."""
    hidden: list[AIConstraint] = []
    rules: list[AIConstraint] = []
    edges: list[AIEdgeCase] = []

    if schema:
        h, r, e = _analyze_schema(schema)
        hidden.extend(h)
        rules.extend(r)
        edges.extend(e)

    if bdd:
        h, r, e = _analyze_bdd(bdd)
        hidden.extend(h)
        rules.extend(r)
        edges.extend(e)

    if openapi:
        h, r, e = _analyze_openapi(openapi)
        hidden.extend(h)
        rules.extend(r)
        edges.extend(e)

    return AIReasoningResult(
        hidden_constraints=hidden,
        business_rules=rules,
        edge_cases=edges,
        provider="offline",
        raw_response="",
    )


# ── Schema heuristics ────────────────────────────────────────


def _analyze_schema(
    schema: SchemaMetadata,
) -> tuple[list[AIConstraint], list[AIConstraint], list[AIEdgeCase]]:
    hidden: list[AIConstraint] = []
    rules: list[AIConstraint] = []
    edges: list[AIEdgeCase] = []

    for table in schema.tables:
        col_map = {c.name: c for c in table.columns}

        # Date ordering: start_date < end_date
        if "start_date" in col_map and "end_date" in col_map:
            hidden.append(
                AIConstraint(
                    table=table.name,
                    column="start_date",
                    constraint_type="range",
                    description="start_date should be before end_date",
                    suggestion={"rule": "start_date < end_date"},
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column="start_date",
                    scenario="start_date equals end_date",
                    test_value=None,
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column="start_date",
                    scenario="start_date after end_date",
                    test_value=None,
                )
            )

        # Email format
        email_cols = [c for c in table.columns if re.search(r"email", c.name, re.I)]
        for ec in email_cols:
            hidden.append(
                AIConstraint(
                    table=table.name,
                    column=ec.name,
                    constraint_type="format",
                    description="Email should match RFC 5322 format",
                    suggestion={"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
                )
            )

        # Phone format
        phone_cols = [
            c for c in table.columns if re.search(r"phone|mobile|cell", c.name, re.I)
        ]
        for pc in phone_cols:
            hidden.append(
                AIConstraint(
                    table=table.name,
                    column=pc.name,
                    constraint_type="format",
                    description="Phone number should contain only digits, spaces, dashes, or parentheses",
                    suggestion={"pattern": r"^[\d\s\-\(\)\+]+$"},
                )
            )

        # Date of birth → age constraints
        dob_cols = [
            c
            for c in table.columns
            if re.search(r"date.?of.?birth|dob|birth.?date", c.name, re.I)
        ]
        for dc in dob_cols:
            rules.append(
                AIConstraint(
                    table=table.name,
                    column=dc.name,
                    constraint_type="business_rule",
                    description="Policyholder must be at least 18 years old",
                    suggestion={"min_age": 18, "max_age": 120},
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column=dc.name,
                    scenario="User is exactly 18 years old",
                    test_value=None,
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column=dc.name,
                    scenario="User is 17 years old (underage)",
                    test_value=None,
                )
            )

        # Claim amount vs coverage amount cross-table rules
        claim_amt = col_map.get("claim_amount")
        if claim_amt:
            rules.append(
                AIConstraint(
                    table=table.name,
                    column="claim_amount",
                    constraint_type="business_rule",
                    description="Claim amount should not exceed policy coverage amount",
                    suggestion={"rule": "claim_amount <= policy.coverage_amount"},
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column="claim_amount",
                    scenario="Claim amount equals coverage amount",
                    test_value=None,
                )
            )
            edges.append(
                AIEdgeCase(
                    table=table.name,
                    column="claim_amount",
                    scenario="Claim amount exceeds coverage amount",
                    test_value=None,
                )
            )

        # Status columns → transition rules
        for col in table.columns:
            check = col.check_constraint or ""
            m = re.search(r"IN\s*\(([^)]+)\)", check, re.I)
            if m and re.search(r"status", col.name, re.I):
                vals = [v.strip().strip("'\"") for v in m.group(1).split(",")]
                rules.append(
                    AIConstraint(
                        table=table.name,
                        column=col.name,
                        constraint_type="business_rule",
                        description=f"Status transitions should follow a valid workflow: {' → '.join(vals)}",
                        suggestion={"valid_statuses": vals},
                    )
                )

        # Payment amounts → should not exceed claim amount
        if "amount" in col_map and table.name == "payments":
            rules.append(
                AIConstraint(
                    table=table.name,
                    column="amount",
                    constraint_type="business_rule",
                    description="Payment amount should not exceed the associated claim amount",
                    suggestion={"rule": "payment.amount <= claim.claim_amount"},
                )
            )

    return hidden, rules, edges


# ── BDD heuristics ────────────────────────────────────────────


def _analyze_bdd(
    bdd: BDDMetadata,
) -> tuple[list[AIConstraint], list[AIConstraint], list[AIEdgeCase]]:
    hidden: list[AIConstraint] = []
    rules: list[AIConstraint] = []
    edges: list[AIEdgeCase] = []

    for scenario in bdd.scenarios:
        for rule in scenario.rules:
            # Age rules
            if re.search(r"age", rule.field, re.I):
                if "below" in rule.condition or "<" in rule.condition:
                    m = re.search(r"(\d+)", rule.condition)
                    threshold = int(m.group(1)) if m else 18
                    rules.append(
                        AIConstraint(
                            table="",
                            column=rule.field,
                            constraint_type="business_rule",
                            description=f"BDD: {rule.field} below {threshold} → {rule.result}",
                            suggestion={"threshold": threshold, "direction": "below"},
                        )
                    )
                    edges.append(
                        AIEdgeCase(
                            column=rule.field,
                            scenario=f"{rule.field} at boundary {threshold}",
                            test_value=threshold,
                        )
                    )
                    edges.append(
                        AIEdgeCase(
                            column=rule.field,
                            scenario=f"{rule.field} just below boundary",
                            test_value=threshold - 1,
                        )
                    )

            # Amount rules with thresholds
            if re.search(r"amount|premium", rule.field, re.I):
                m = re.search(r"(\d+)", rule.condition)
                if m:
                    threshold = int(m.group(1))
                    rules.append(
                        AIConstraint(
                            table="",
                            column=rule.field,
                            constraint_type="business_rule",
                            description=f"BDD: {rule.field} {rule.condition} → {rule.result}",
                            suggestion={"threshold": threshold},
                        )
                    )
                    edges.append(
                        AIEdgeCase(
                            column=rule.field,
                            scenario=f"{rule.field} at threshold {threshold}",
                            test_value=threshold,
                        )
                    )

            # Null / empty checks
            if "null" in rule.condition.lower() or "empty" in rule.condition.lower():
                hidden.append(
                    AIConstraint(
                        table="",
                        column=rule.field,
                        constraint_type="dependency",
                        description=f"BDD implies {rule.field} null/empty handling: {rule.result}",
                        suggestion={"nullable_behavior": rule.result},
                    )
                )

            # Format checks
            if "invalid" in rule.condition.lower() or "valid" in rule.condition.lower():
                hidden.append(
                    AIConstraint(
                        table="",
                        column=rule.field,
                        constraint_type="format",
                        description=f"BDD implies format validation on {rule.field}",
                        suggestion={"format_rule": rule.condition},
                    )
                )

    return hidden, rules, edges


# ── OpenAPI heuristics ────────────────────────────────────────


def _analyze_openapi(
    openapi: OpenAPIMetadata,
) -> tuple[list[AIConstraint], list[AIConstraint], list[AIEdgeCase]]:
    hidden: list[AIConstraint] = []
    rules: list[AIConstraint] = []
    edges: list[AIEdgeCase] = []

    for schema_def in openapi.schemas:
        for field in schema_def.fields:
            v = field.validation

            # Pattern → format constraint
            if v.pattern:
                hidden.append(
                    AIConstraint(
                        table=schema_def.name,
                        column=field.name,
                        constraint_type="format",
                        description=f"Regex pattern on {field.name}: {v.pattern}",
                        suggestion={"pattern": v.pattern},
                    )
                )
                edges.append(
                    AIEdgeCase(
                        table=schema_def.name,
                        column=field.name,
                        scenario=f"Value violating pattern {v.pattern}",
                        test_value="INVALID",
                    )
                )

            # min/max → range constraint
            if v.minimum is not None or v.maximum is not None:
                hidden.append(
                    AIConstraint(
                        table=schema_def.name,
                        column=field.name,
                        constraint_type="range",
                        description=f"Range on {field.name}: min={v.minimum}, max={v.maximum}",
                        suggestion={"min": v.minimum, "max": v.maximum},
                    )
                )
                if v.minimum is not None:
                    edges.append(
                        AIEdgeCase(
                            table=schema_def.name,
                            column=field.name,
                            scenario=f"Value at minimum ({v.minimum})",
                            test_value=v.minimum,
                        )
                    )
                    edges.append(
                        AIEdgeCase(
                            table=schema_def.name,
                            column=field.name,
                            scenario=f"Value below minimum ({v.minimum - 1})",
                            test_value=v.minimum - 1,
                        )
                    )

            # min_length / max_length
            if v.min_length is not None or v.max_length is not None:
                hidden.append(
                    AIConstraint(
                        table=schema_def.name,
                        column=field.name,
                        constraint_type="range",
                        description=f"Length on {field.name}: min_len={v.min_length}, max_len={v.max_length}",
                        suggestion={"min_length": v.min_length, "max_length": v.max_length},
                    )
                )

            # Enum → business rule
            if v.enum:
                rules.append(
                    AIConstraint(
                        table=schema_def.name,
                        column=field.name,
                        constraint_type="business_rule",
                        description=f"Allowed values for {field.name}: {v.enum}",
                        suggestion={"enum": v.enum},
                    )
                )
                edges.append(
                    AIEdgeCase(
                        table=schema_def.name,
                        column=field.name,
                        scenario="Value not in enum",
                        test_value="INVALID_ENUM_VALUE",
                    )
                )

    return hidden, rules, edges
