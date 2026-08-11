"""Business Rule Reasoning Engine — infers rules from BDD, schema, and OpenAPI sources.

Capabilities:
- Infers age restrictions from column names, BDD steps, and OpenAPI constraints
- Detects policy eligibility rules from schema patterns and BDD conditions
- Identifies KYC rules from identity/verification-related fields
- Extracts approval logic from status columns and workflow patterns
- Generates validation rules for each inferred business rule
- Produces edge-case scenarios for boundary/negative testing
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.models.bdd import BDDMetadata, BDDRule, BDDScenario
from app.models.business_rule import (
    BusinessRule,
    BusinessRuleMetadata,
    BusinessRuleResult,
    EdgeCaseScenario,
    RuleCategory,
    RuleSeverity,
    RuleSource,
    ValidationRule,
)
from app.models.openapi import OpenAPIMetadata, OpenAPISchemaMetadata
from app.models.schema import SchemaMetadata, TableMetadata


class BusinessRuleEngine:
    """Infers business rules from BDD scenarios, SQL schemas, and OpenAPI specs."""

    def __init__(
        self,
        schema: SchemaMetadata | None = None,
        bdd: BDDMetadata | None = None,
        openapi: OpenAPIMetadata | None = None,
    ) -> None:
        self._schema = schema
        self._bdd = bdd
        self._openapi = openapi
        self._rule_counter = 0

    def analyze(self) -> BusinessRuleResult:
        """Run full analysis and return inferred rules, validations, and edge cases."""
        rules: list[BusinessRule] = []
        validation_rules: list[ValidationRule] = []
        edge_cases: list[EdgeCaseScenario] = []
        metadata: list[BusinessRuleMetadata] = []

        # Infer from BDD
        if self._bdd:
            bdd_results = self._infer_from_bdd()
            rules.extend(bdd_results[0])
            validation_rules.extend(bdd_results[1])
            edge_cases.extend(bdd_results[2])
            metadata.extend(bdd_results[3])

        # Infer from schema
        if self._schema:
            schema_results = self._infer_from_schema()
            rules.extend(schema_results[0])
            validation_rules.extend(schema_results[1])
            edge_cases.extend(schema_results[2])
            metadata.extend(schema_results[3])

        # Infer from OpenAPI
        if self._openapi:
            api_results = self._infer_from_openapi()
            rules.extend(api_results[0])
            validation_rules.extend(api_results[1])
            edge_cases.extend(api_results[2])
            metadata.extend(api_results[3])

        # Build summary
        by_category: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)
        for r in rules:
            by_category[r.category.value] += 1
            by_source[r.source.value] += 1

        return BusinessRuleResult(
            total_rules=len(rules),
            total_validation_rules=len(validation_rules),
            total_edge_cases=len(edge_cases),
            rules=rules,
            validation_rules=validation_rules,
            edge_cases=edge_cases,
            metadata=metadata,
            rules_by_category=dict(by_category),
            rules_by_source=dict(by_source),
        )

    # ── BDD Inference ─────────────────────────────────────────

    def _infer_from_bdd(self) -> tuple[list, list, list, list]:
        rules: list[BusinessRule] = []
        validations: list[ValidationRule] = []
        edges: list[EdgeCaseScenario] = []
        meta: list[BusinessRuleMetadata] = []

        for scenario in self._bdd.scenarios:
            for bdd_rule in scenario.rules:
                inferred = self._classify_bdd_rule(bdd_rule, scenario)
                if inferred:
                    rule, vals, edgs, m = inferred
                    rules.append(rule)
                    validations.extend(vals)
                    edges.extend(edgs)
                    meta.append(m)

        return rules, validations, edges, meta

    def _classify_bdd_rule(
        self, bdd_rule: BDDRule, scenario: BDDScenario
    ) -> tuple[BusinessRule, list[ValidationRule], list[EdgeCaseScenario], BusinessRuleMetadata] | None:
        """Classify a BDD rule into a business rule category."""
        field = bdd_rule.field.lower()
        condition = bdd_rule.condition.lower()
        result = bdd_rule.result.lower()

        category = self._detect_bdd_category(field, condition, result)
        severity = self._determine_severity(category, result)
        rule_id = self._next_id()

        rule = BusinessRule(
            rule_id=rule_id,
            name=f"{scenario.name or 'Rule'}: {bdd_rule.field} {bdd_rule.condition}",
            category=category,
            source=RuleSource.BDD,
            severity=severity,
            description=f"When {bdd_rule.field} {bdd_rule.condition}, then {bdd_rule.result}",
            condition=f"{bdd_rule.field} {bdd_rule.condition}",
            fields=[bdd_rule.field],
        )

        validations = self._generate_bdd_validations(rule_id, bdd_rule)
        edges = self._generate_bdd_edge_cases(rule_id, bdd_rule)
        meta = BusinessRuleMetadata(
            rule_id=rule_id,
            source_text=f"Given {bdd_rule.field} {bdd_rule.condition} Then {bdd_rule.result}",
            confidence=0.95,
            inferred_from=f"BDD scenario: {scenario.name}",
        )

        return rule, validations, edges, meta

    def _detect_bdd_category(self, field: str, condition: str, result: str) -> RuleCategory:
        """Detect rule category from BDD field/condition/result."""
        # Age restrictions (field must relate to age)
        if re.search(r"age|birth|dob|date.of.birth|minor|adult", field):
            return RuleCategory.AGE_RESTRICTION

        # KYC
        if re.search(r"kyc|identity|verif|document|passport|id.proof|address.proof", field):
            return RuleCategory.KYC
        if re.search(r"verify|verified|validate|kyc", condition + result):
            return RuleCategory.KYC

        # Eligibility
        if re.search(r"eligible|eligibility|qualify|qualification|policy|coverage|premium", field + condition + result):
            return RuleCategory.ELIGIBILITY

        # Approval
        if re.search(r"approv|reject|pending|status|workflow", field + condition + result):
            return RuleCategory.APPROVAL

        # Financial
        if re.search(r"amount|balance|credit|debit|salary|income|limit|transaction", field):
            return RuleCategory.FINANCIAL

        # Temporal
        if re.search(r"date|time|expir|duration|period|deadline", field):
            return RuleCategory.TEMPORAL

        # Threshold
        if re.search(r"greater|less|above|below|between|minimum|maximum|exceed", condition):
            return RuleCategory.THRESHOLD

        return RuleCategory.DEPENDENCY

    def _generate_bdd_validations(self, rule_id: str, bdd_rule: BDDRule) -> list[ValidationRule]:
        """Generate validation rules from a BDD rule."""
        validations: list[ValidationRule] = []
        condition = bdd_rule.condition.lower()

        # Parse numeric comparisons
        num_match = re.search(r"(below|under|less than|<)\s+(\d+\.?\d*)", condition)
        if num_match:
            val = float(num_match.group(2))
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="lt",
                value=val,
                error_message=f"{bdd_rule.field} must be less than {val}",
            ))

        num_match = re.search(r"(above|over|greater than|more than|>)\s+(\d+\.?\d*)", condition)
        if num_match:
            val = float(num_match.group(2))
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="gt",
                value=val,
                error_message=f"{bdd_rule.field} must be greater than {val}",
            ))

        num_match = re.search(r"(at least|>=|minimum)\s+(\d+\.?\d*)", condition)
        if num_match:
            val = float(num_match.group(2))
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="gte",
                value=val,
                error_message=f"{bdd_rule.field} must be at least {val}",
            ))

        num_match = re.search(r"(at most|<=|maximum)\s+(\d+\.?\d*)", condition)
        if num_match:
            val = float(num_match.group(2))
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="lte",
                value=val,
                error_message=f"{bdd_rule.field} must be at most {val}",
            ))

        # Between range
        between_match = re.search(r"between\s+(\d+\.?\d*)\s+and\s+(\d+\.?\d*)", condition)
        if between_match:
            low = float(between_match.group(1))
            high = float(between_match.group(2))
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="between",
                value=low,
                value_max=high,
                error_message=f"{bdd_rule.field} must be between {low} and {high}",
            ))

        # Equality
        eq_match = re.search(r"(is|equals?|==)\s+['\"]?([^'\"]+)['\"]?\s*$", condition)
        if eq_match and not num_match and not between_match:
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="eq",
                value=eq_match.group(2).strip(),
                error_message=f"{bdd_rule.field} must equal '{eq_match.group(2).strip()}'",
            ))

        # Not empty / required
        if re.search(r"not empty|not blank|required|provided|present|exists", condition):
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="required",
                error_message=f"{bdd_rule.field} is required",
            ))

        # If no specific pattern matched, create a generic validation
        if not validations:
            validations.append(ValidationRule(
                rule_id=rule_id,
                field=bdd_rule.field,
                operator="ne",
                value=None,
                error_message=f"{bdd_rule.field}: {bdd_rule.condition} → {bdd_rule.result}",
            ))

        return validations

    def _generate_bdd_edge_cases(self, rule_id: str, bdd_rule: BDDRule) -> list[EdgeCaseScenario]:
        """Generate edge-case scenarios from a BDD rule."""
        edges: list[EdgeCaseScenario] = []
        condition = bdd_rule.condition.lower()

        # Extract numeric threshold
        num_match = re.search(r"(\d+\.?\d*)", condition)
        if num_match:
            threshold = float(num_match.group(1))
            is_int = threshold == int(threshold)
            t_val = int(threshold) if is_int else threshold

            edges.append(EdgeCaseScenario(
                rule_id=rule_id,
                scenario_name=f"{bdd_rule.field} at boundary ({t_val})",
                description=f"Test with {bdd_rule.field} exactly at {t_val}",
                test_inputs={bdd_rule.field: t_val},
                expected_outcome="boundary",
                boundary_type="at_boundary",
            ))
            edges.append(EdgeCaseScenario(
                rule_id=rule_id,
                scenario_name=f"{bdd_rule.field} just below boundary",
                description=f"Test with {bdd_rule.field} at {t_val - 1}",
                test_inputs={bdd_rule.field: t_val - 1 if is_int else t_val - 0.01},
                expected_outcome="fail" if "above" in condition or "greater" in condition or "at least" in condition else "pass",
                boundary_type="below_min",
            ))
            edges.append(EdgeCaseScenario(
                rule_id=rule_id,
                scenario_name=f"{bdd_rule.field} just above boundary",
                description=f"Test with {bdd_rule.field} at {t_val + 1}",
                test_inputs={bdd_rule.field: t_val + 1 if is_int else t_val + 0.01},
                expected_outcome="fail" if "below" in condition or "less" in condition or "under" in condition or "at most" in condition else "pass",
                boundary_type="above_max",
            ))

        # Null/empty case
        edges.append(EdgeCaseScenario(
            rule_id=rule_id,
            scenario_name=f"{bdd_rule.field} is null",
            description=f"Test with {bdd_rule.field} as null/empty",
            test_inputs={bdd_rule.field: None},
            expected_outcome="fail",
            boundary_type="null",
        ))

        return edges

    # ── Schema Inference ──────────────────────────────────────

    def _infer_from_schema(self) -> tuple[list, list, list, list]:
        rules: list[BusinessRule] = []
        validations: list[ValidationRule] = []
        edges: list[EdgeCaseScenario] = []
        meta: list[BusinessRuleMetadata] = []

        for table in self._schema.tables:
            results = self._analyze_table(table)
            rules.extend(results[0])
            validations.extend(results[1])
            edges.extend(results[2])
            meta.extend(results[3])

        return rules, validations, edges, meta

    def _analyze_table(self, table: TableMetadata) -> tuple[list, list, list, list]:
        """Analyze a table for business rule patterns."""
        rules: list[BusinessRule] = []
        validations: list[ValidationRule] = []
        edges: list[EdgeCaseScenario] = []
        meta: list[BusinessRuleMetadata] = []

        for col in table.columns:
            col_rules = self._infer_column_rules(table, col)
            for rule, vals, edgs, m in col_rules:
                rules.append(rule)
                validations.extend(vals)
                edges.extend(edgs)
                meta.append(m)

        # Check constraints as business rules
        for check in table.check_constraints:
            result = self._infer_from_check_constraint(table, check)
            if result:
                rules.append(result[0])
                validations.extend(result[1])
                edges.extend(result[2])
                meta.append(result[3])

        # Status transition rules
        status_cols = [c for c in table.columns if re.search(r"status|state|phase|stage", c.name, re.I)]
        for col in status_cols:
            result = self._infer_status_transition(table, col)
            if result:
                rules.append(result[0])
                validations.extend(result[1])
                edges.extend(result[2])
                meta.append(result[3])

        return rules, validations, edges, meta

    def _infer_column_rules(self, table: TableMetadata, col) -> list[tuple]:
        """Infer business rules from column name patterns."""
        results: list[tuple] = []
        col_name = col.name.lower()

        # Age-related columns
        if re.search(r"^age$|_age$|^date.of.birth$|^dob$|^birth.date$", col_name):
            rule_id = self._next_id()
            category = RuleCategory.AGE_RESTRICTION
            rules_list = []
            edges_list = []

            if "age" in col_name:
                rules_list.append(ValidationRule(
                    rule_id=rule_id, field=col.name, operator="gte", value=0,
                    error_message=f"{col.name} must be non-negative",
                ))
                rules_list.append(ValidationRule(
                    rule_id=rule_id, field=col.name, operator="lte", value=150,
                    error_message=f"{col.name} must not exceed 150",
                ))
                edges_list.extend([
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = 0 (newborn)", description="Minimum valid age", test_inputs={col.name: 0}, expected_outcome="pass", boundary_type="at_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = 17 (minor)", description="Below legal age threshold", test_inputs={col.name: 17}, expected_outcome="conditional", boundary_type="below_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = 18 (adult)", description="At legal age threshold", test_inputs={col.name: 18}, expected_outcome="pass", boundary_type="at_boundary"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = -1 (invalid)", description="Negative age", test_inputs={col.name: -1}, expected_outcome="fail", boundary_type="below_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = 151 (impossible)", description="Exceeds maximum human age", test_inputs={col.name: 151}, expected_outcome="fail", boundary_type="above_max"),
                ])

            rule = BusinessRule(
                rule_id=rule_id, name=f"Age restriction on {table.name}.{col.name}",
                category=category, source=RuleSource.SCHEMA, severity=RuleSeverity.HIGH,
                description=f"Column {col.name} in {table.name} implies age-based restrictions",
                condition=f"{col.name} >= 0 AND {col.name} <= 150",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(
                rule_id=rule_id, confidence=0.9,
                inferred_from=f"Column name pattern: {table.name}.{col.name}",
            )
            results.append((rule, rules_list, edges_list, meta))

        # KYC-related columns
        if re.search(r"kyc|passport|national.id|ssn|sin|tax.id|identity|id.proof|pan|aadhar|aadhaar|document.type|verification", col_name):
            rule_id = self._next_id()
            vals = [ValidationRule(
                rule_id=rule_id, field=col.name, operator="required",
                error_message=f"{col.name} is required for KYC compliance",
            )]
            edgs = [
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} missing (KYC fail)", description="KYC document not provided", test_inputs={col.name: None}, expected_outcome="fail", boundary_type="null"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} empty string", description="Empty KYC field", test_inputs={col.name: ""}, expected_outcome="fail", boundary_type="null"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} invalid format", description="Invalid document format", test_inputs={col.name: "INVALID-XXX"}, expected_outcome="fail", boundary_type="invalid"),
            ]
            rule = BusinessRule(
                rule_id=rule_id, name=f"KYC requirement: {table.name}.{col.name}",
                category=RuleCategory.KYC, source=RuleSource.SCHEMA, severity=RuleSeverity.CRITICAL,
                description=f"Column {col.name} is a KYC-critical field requiring valid identity documentation",
                condition=f"{col.name} IS NOT NULL AND {col.name} != ''",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(rule_id=rule_id, confidence=0.85, inferred_from=f"KYC column pattern: {table.name}.{col.name}")
            results.append((rule, vals, edgs, meta))

        # Financial columns
        if re.search(r"amount|balance|salary|income|premium|coverage|credit.?limit|debit|transaction.?amount|price|cost|fee", col_name):
            rule_id = self._next_id()
            vals = [
                ValidationRule(rule_id=rule_id, field=col.name, operator="gte", value=0, error_message=f"{col.name} must be non-negative"),
            ]
            edgs = [
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = 0 (zero amount)", description="Zero financial value", test_inputs={col.name: 0}, expected_outcome="conditional", boundary_type="at_min"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} negative", description="Negative financial value", test_inputs={col.name: -100}, expected_outcome="fail", boundary_type="below_min"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} very large", description="Extremely large financial value", test_inputs={col.name: 99999999.99}, expected_outcome="conditional", boundary_type="above_max"),
            ]
            rule = BusinessRule(
                rule_id=rule_id, name=f"Financial constraint: {table.name}.{col.name}",
                category=RuleCategory.FINANCIAL, source=RuleSource.SCHEMA, severity=RuleSeverity.HIGH,
                description=f"Financial column {col.name} should be non-negative",
                condition=f"{col.name} >= 0",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(rule_id=rule_id, confidence=0.9, inferred_from=f"Financial column: {table.name}.{col.name}")
            results.append((rule, vals, edgs, meta))

        # Approval/status columns
        if re.search(r"approved|approval|approved.by|approved.at|approval.status", col_name):
            rule_id = self._next_id()
            vals = [ValidationRule(rule_id=rule_id, field=col.name, operator="required", error_message=f"{col.name} must be present for approved records")]
            edgs = [
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} without approver", description="Record approved without approver info", test_inputs={col.name: None}, expected_outcome="fail", boundary_type="null"),
            ]
            rule = BusinessRule(
                rule_id=rule_id, name=f"Approval logic: {table.name}.{col.name}",
                category=RuleCategory.APPROVAL, source=RuleSource.SCHEMA, severity=RuleSeverity.HIGH,
                description=f"Approval field {col.name} implies workflow authorization requirements",
                condition=f"{col.name} IS NOT NULL when record is approved",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(rule_id=rule_id, confidence=0.8, inferred_from=f"Approval column: {table.name}.{col.name}")
            results.append((rule, vals, edgs, meta))

        # Eligibility columns
        if re.search(r"eligible|eligibility|qualify|qualified|active|is.active|is.eligible", col_name):
            rule_id = self._next_id()
            vals = [ValidationRule(rule_id=rule_id, field=col.name, operator="in", value=["true", "false", "1", "0", "yes", "no"], error_message=f"{col.name} must be a valid eligibility flag")]
            edgs = [
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} = null", description="Eligibility not determined", test_inputs={col.name: None}, expected_outcome="conditional", boundary_type="null"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} invalid value", description="Non-boolean eligibility", test_inputs={col.name: "maybe"}, expected_outcome="fail", boundary_type="invalid"),
            ]
            rule = BusinessRule(
                rule_id=rule_id, name=f"Eligibility check: {table.name}.{col.name}",
                category=RuleCategory.ELIGIBILITY, source=RuleSource.SCHEMA, severity=RuleSeverity.MEDIUM,
                description=f"Column {col.name} represents a binary eligibility decision",
                condition=f"{col.name} IN (true, false)",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(rule_id=rule_id, confidence=0.85, inferred_from=f"Eligibility column: {table.name}.{col.name}")
            results.append((rule, vals, edgs, meta))

        # Temporal columns with business meaning
        if re.search(r"expir|expire.date|valid.until|deadline|due.date|maturity.date|start.date|end.date", col_name):
            rule_id = self._next_id()
            vals = [ValidationRule(rule_id=rule_id, field=col.name, operator="required", error_message=f"{col.name} temporal constraint required")]
            edgs = [
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} in the past", description="Expired temporal value", test_inputs={col.name: "2020-01-01"}, expected_outcome="conditional", boundary_type="below_min"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} far future", description="Very distant future date", test_inputs={col.name: "2099-12-31"}, expected_outcome="conditional", boundary_type="above_max"),
                EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} null", description="Missing temporal value", test_inputs={col.name: None}, expected_outcome="fail", boundary_type="null"),
            ]
            rule = BusinessRule(
                rule_id=rule_id, name=f"Temporal constraint: {table.name}.{col.name}",
                category=RuleCategory.TEMPORAL, source=RuleSource.SCHEMA, severity=RuleSeverity.MEDIUM,
                description=f"Column {col.name} implies temporal business rules (expiration/deadline)",
                condition=f"{col.name} must be a valid date",
                fields=[col.name], tables=[table.name],
            )
            meta = BusinessRuleMetadata(rule_id=rule_id, confidence=0.8, inferred_from=f"Temporal column: {table.name}.{col.name}")
            results.append((rule, vals, edgs, meta))

        return results

    def _infer_from_check_constraint(self, table: TableMetadata, check: str) -> tuple | None:
        """Infer a business rule from a CHECK constraint."""
        rule_id = self._next_id()

        # Try to extract the column name from the constraint
        col_match = re.search(r"(\w+)\s*(>=?|<=?|BETWEEN|IN)", check, re.I)
        field = col_match.group(1) if col_match else "unknown"

        category = self._classify_check_constraint(check, field)
        vals: list[ValidationRule] = []
        edgs: list[EdgeCaseScenario] = []

        # Extract numeric range
        range_match = re.findall(r"(\d+\.?\d*)", check)
        if range_match:
            values = [float(v) for v in range_match]
            if len(values) >= 2:
                vals.append(ValidationRule(
                    rule_id=rule_id, field=field, operator="between",
                    value=min(values), value_max=max(values),
                    error_message=f"{field} must be between {min(values)} and {max(values)}",
                ))
                edgs.extend([
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field} below range", description=f"Below {min(values)}", test_inputs={field: min(values) - 1}, expected_outcome="fail", boundary_type="below_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field} above range", description=f"Above {max(values)}", test_inputs={field: max(values) + 1}, expected_outcome="fail", boundary_type="above_max"),
                ])
            elif len(values) == 1:
                vals.append(ValidationRule(
                    rule_id=rule_id, field=field, operator="gte", value=values[0],
                    error_message=f"{field} must satisfy: {check}",
                ))

        rule = BusinessRule(
            rule_id=rule_id,
            name=f"Check constraint: {table.name}.{field}",
            category=category, source=RuleSource.SCHEMA, severity=RuleSeverity.MEDIUM,
            description=f"CHECK constraint on {table.name}: {check}",
            condition=check,
            fields=[field], tables=[table.name],
        )
        meta = BusinessRuleMetadata(
            rule_id=rule_id, source_text=check, confidence=1.0,
            inferred_from=f"CHECK constraint: {table.name}",
        )
        return rule, vals, edgs, meta

    def _infer_status_transition(self, table: TableMetadata, col) -> tuple | None:
        """Infer status transition rules from status-like columns."""
        rule_id = self._next_id()

        # Extract enum values if present
        from app.utils.sql_types import extract_enum_from_check
        enum_values = extract_enum_from_check(col.check_constraint) if col.check_constraint else None

        if not enum_values:
            # Infer common status values from column name
            if re.search(r"status", col.name, re.I):
                enum_values = ["pending", "active", "inactive", "suspended", "closed"]
            elif re.search(r"state|phase", col.name, re.I):
                enum_values = ["draft", "submitted", "in_review", "approved", "rejected"]
            else:
                return None

        vals = [ValidationRule(
            rule_id=rule_id, field=col.name, operator="in", value=enum_values,
            error_message=f"{col.name} must be one of: {enum_values}",
        )]
        edgs = [
            EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} invalid transition", description=f"Invalid status value", test_inputs={col.name: "INVALID_STATUS"}, expected_outcome="fail", boundary_type="invalid"),
            EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{col.name} null status", description="Null status field", test_inputs={col.name: None}, expected_outcome="fail", boundary_type="null"),
        ]

        rule = BusinessRule(
            rule_id=rule_id,
            name=f"Status transition: {table.name}.{col.name}",
            category=RuleCategory.STATUS_TRANSITION, source=RuleSource.SCHEMA,
            severity=RuleSeverity.HIGH,
            description=f"Column {col.name} represents a state machine with allowed values: {enum_values}",
            condition=f"{col.name} IN {enum_values}",
            fields=[col.name], tables=[table.name],
        )
        meta = BusinessRuleMetadata(
            rule_id=rule_id, confidence=0.75 if not col.check_constraint else 1.0,
            inferred_from=f"Status column: {table.name}.{col.name}",
        )
        return rule, vals, edgs, meta

    def _classify_check_constraint(self, check: str, field: str) -> RuleCategory:
        """Classify a CHECK constraint into a rule category."""
        combined = (check + " " + field).lower()
        if re.search(r"age|birth|minor", combined):
            return RuleCategory.AGE_RESTRICTION
        if re.search(r"amount|balance|salary|price|cost|fee|premium", combined):
            return RuleCategory.FINANCIAL
        if re.search(r"status|state|phase", combined):
            return RuleCategory.STATUS_TRANSITION
        return RuleCategory.THRESHOLD

    # ── OpenAPI Inference ─────────────────────────────────────

    def _infer_from_openapi(self) -> tuple[list, list, list, list]:
        rules: list[BusinessRule] = []
        validations: list[ValidationRule] = []
        edges: list[EdgeCaseScenario] = []
        meta: list[BusinessRuleMetadata] = []

        for schema in self._openapi.schemas:
            results = self._analyze_api_schema(schema)
            rules.extend(results[0])
            validations.extend(results[1])
            edges.extend(results[2])
            meta.extend(results[3])

        return rules, validations, edges, meta

    def _analyze_api_schema(self, schema: OpenAPISchemaMetadata) -> tuple[list, list, list, list]:
        """Analyze an OpenAPI schema for business rules."""
        rules: list[BusinessRule] = []
        validations: list[ValidationRule] = []
        edges: list[EdgeCaseScenario] = []
        meta: list[BusinessRuleMetadata] = []

        for field in schema.fields:
            field_name = field.name.lower()

            # Age-related API fields
            if re.search(r"^age$|_age$|^date.of.birth$|^dob$|^birth.date$", field_name):
                rule_id = self._next_id()
                min_val = field.validation.minimum if field.validation.minimum is not None else 0
                max_val = field.validation.maximum if field.validation.maximum is not None else 150

                vals = [
                    ValidationRule(rule_id=rule_id, field=field.name, operator="gte", value=min_val, error_message=f"{field.name} >= {min_val}"),
                    ValidationRule(rule_id=rule_id, field=field.name, operator="lte", value=max_val, error_message=f"{field.name} <= {max_val}"),
                ]
                edgs = [
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} at min ({min_val})", description="At minimum age", test_inputs={field.name: min_val}, expected_outcome="pass", boundary_type="at_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} at max ({max_val})", description="At maximum age", test_inputs={field.name: max_val}, expected_outcome="pass", boundary_type="at_max"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} below min", description="Below minimum", test_inputs={field.name: min_val - 1}, expected_outcome="fail", boundary_type="below_min"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} above max", description="Above maximum", test_inputs={field.name: max_val + 1}, expected_outcome="fail", boundary_type="above_max"),
                ]
                rule = BusinessRule(
                    rule_id=rule_id, name=f"Age restriction: {schema.name}.{field.name}",
                    category=RuleCategory.AGE_RESTRICTION, source=RuleSource.OPENAPI,
                    severity=RuleSeverity.HIGH,
                    description=f"API field {field.name} has age restriction [{min_val}, {max_val}]",
                    condition=f"{min_val} <= {field.name} <= {max_val}",
                    fields=[field.name], schemas=[schema.name],
                )
                m = BusinessRuleMetadata(rule_id=rule_id, confidence=0.9, inferred_from=f"OpenAPI schema: {schema.name}.{field.name}")
                rules.append(rule)
                validations.extend(vals)
                edges.extend(edgs)
                meta.append(m)
                continue

            # Enum fields = business state rules
            if field.validation.enum:
                rule_id = self._next_id()
                category = self._classify_api_field(field_name, field.validation.enum)
                vals = [ValidationRule(rule_id=rule_id, field=field.name, operator="in", value=field.validation.enum, error_message=f"{field.name} must be one of: {field.validation.enum}")]
                edgs = [
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} invalid enum", description="Value not in allowed set", test_inputs={field.name: "INVALID_VALUE"}, expected_outcome="fail", boundary_type="invalid"),
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} null", description="Null enum field", test_inputs={field.name: None}, expected_outcome="fail" if field.required else "conditional", boundary_type="null"),
                ]
                rule = BusinessRule(
                    rule_id=rule_id, name=f"Allowed values: {schema.name}.{field.name}",
                    category=category, source=RuleSource.OPENAPI, severity=RuleSeverity.MEDIUM,
                    description=f"Field {field.name} restricted to: {field.validation.enum}",
                    condition=f"{field.name} IN {field.validation.enum}",
                    fields=[field.name], schemas=[schema.name],
                )
                m = BusinessRuleMetadata(rule_id=rule_id, confidence=1.0, inferred_from=f"OpenAPI enum: {schema.name}.{field.name}")
                rules.append(rule)
                validations.extend(vals)
                edges.extend(edgs)
                meta.append(m)
                continue

            # Required fields with validation constraints
            if field.required and (field.validation.minimum is not None or field.validation.maximum is not None):
                rule_id = self._next_id()
                category = self._classify_api_field(field_name, [])
                vals_list: list[ValidationRule] = []
                edgs_list: list[EdgeCaseScenario] = []

                if field.validation.minimum is not None:
                    vals_list.append(ValidationRule(rule_id=rule_id, field=field.name, operator="gte", value=field.validation.minimum, error_message=f"{field.name} >= {field.validation.minimum}"))
                    edgs_list.append(EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} below min", description=f"Below {field.validation.minimum}", test_inputs={field.name: field.validation.minimum - 1}, expected_outcome="fail", boundary_type="below_min"))

                if field.validation.maximum is not None:
                    vals_list.append(ValidationRule(rule_id=rule_id, field=field.name, operator="lte", value=field.validation.maximum, error_message=f"{field.name} <= {field.validation.maximum}"))
                    edgs_list.append(EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} above max", description=f"Above {field.validation.maximum}", test_inputs={field.name: field.validation.maximum + 1}, expected_outcome="fail", boundary_type="above_max"))

                condition_parts = []
                if field.validation.minimum is not None:
                    condition_parts.append(f"{field.name} >= {field.validation.minimum}")
                if field.validation.maximum is not None:
                    condition_parts.append(f"{field.name} <= {field.validation.maximum}")

                rule = BusinessRule(
                    rule_id=rule_id, name=f"Range constraint: {schema.name}.{field.name}",
                    category=category, source=RuleSource.OPENAPI, severity=RuleSeverity.MEDIUM,
                    description=f"API field {field.name} has range constraints",
                    condition=" AND ".join(condition_parts),
                    fields=[field.name], schemas=[schema.name],
                )
                m = BusinessRuleMetadata(rule_id=rule_id, confidence=1.0, inferred_from=f"OpenAPI validation: {schema.name}.{field.name}")
                rules.append(rule)
                validations.extend(vals_list)
                edges.extend(edgs_list)
                meta.append(m)
                continue

            # Pattern-based rules
            if field.validation.pattern:
                rule_id = self._next_id()
                category = self._classify_api_field(field_name, [])
                vals = [ValidationRule(rule_id=rule_id, field=field.name, operator="matches", value=field.validation.pattern, error_message=f"{field.name} must match pattern: {field.validation.pattern}")]
                edgs = [
                    EdgeCaseScenario(rule_id=rule_id, scenario_name=f"{field.name} invalid pattern", description="Value not matching regex", test_inputs={field.name: "!!INVALID!!"}, expected_outcome="fail", boundary_type="invalid"),
                ]
                rule = BusinessRule(
                    rule_id=rule_id, name=f"Format rule: {schema.name}.{field.name}",
                    category=RuleCategory.FORMAT, source=RuleSource.OPENAPI, severity=RuleSeverity.MEDIUM,
                    description=f"Field {field.name} must match pattern: {field.validation.pattern}",
                    condition=f"{field.name} ~ /{field.validation.pattern}/",
                    fields=[field.name], schemas=[schema.name],
                )
                m = BusinessRuleMetadata(rule_id=rule_id, confidence=1.0, inferred_from=f"OpenAPI pattern: {schema.name}.{field.name}")
                rules.append(rule)
                validations.extend(vals)
                edges.extend(edgs)
                meta.append(m)

        return rules, validations, edges, meta

    def _classify_api_field(self, field_name: str, enum_values: list[str]) -> RuleCategory:
        """Classify an API field into a business rule category."""
        combined = field_name + " " + " ".join(enum_values).lower()

        if re.search(r"age|birth|dob|minor", field_name):
            return RuleCategory.AGE_RESTRICTION
        if re.search(r"status|state|phase|stage", field_name):
            return RuleCategory.STATUS_TRANSITION
        if re.search(r"approv|reject", combined):
            return RuleCategory.APPROVAL
        if re.search(r"eligible|qualify", combined):
            return RuleCategory.ELIGIBILITY
        if re.search(r"kyc|identity|verif|passport|document", field_name):
            return RuleCategory.KYC
        if re.search(r"amount|balance|salary|price|premium|cost|fee", field_name):
            return RuleCategory.FINANCIAL
        if re.search(r"date|time|expir|deadline|due", field_name):
            return RuleCategory.TEMPORAL
        return RuleCategory.THRESHOLD

    # ── Utilities ─────────────────────────────────────────────

    def _next_id(self) -> str:
        self._rule_counter += 1
        return f"BR-{self._rule_counter:04d}"

    @staticmethod
    def _determine_severity(category: RuleCategory, result: str) -> RuleSeverity:
        """Determine rule severity based on category and outcome."""
        if re.search(r"fail|reject|block|deny|error", result):
            return RuleSeverity.CRITICAL
        if category in (RuleCategory.KYC, RuleCategory.AGE_RESTRICTION, RuleCategory.FINANCIAL):
            return RuleSeverity.HIGH
        if category in (RuleCategory.APPROVAL, RuleCategory.ELIGIBILITY):
            return RuleSeverity.MEDIUM
        return RuleSeverity.LOW
