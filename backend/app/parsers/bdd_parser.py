"""BDD / Gherkin parser — extracts structured rules from .feature files.

Recognises Given/When/Then steps and maps them to condition–outcome
pairs using regex-based pattern matching.  Supports natural-language
expressions for comparisons, null checks, duplicates, format
validation, and range checks.
"""

from __future__ import annotations

import logging
import re

from app.models.bdd import BDDMetadata, BDDRule, BDDScenario

logger = logging.getLogger(__name__)


class BDDParserError(Exception):
    """Raised when BDD/Gherkin parsing fails."""


# ── Condition patterns ────────────────────────────────────────
# Each tuple: (compiled regex, field_group, condition_builder)
# The regex matches a Given/When/And step line and extracts field + value.

_CONDITION_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
    # "password length is less than 8" — must be before generic < pattern
    (re.compile(
        r"(\w[\w\s]*?)\s+length\s+(?:is\s+)?(?:below|less\s+than|under|<)\s+(\S+)",
        re.IGNORECASE,
    ), 1, "length<{value}"),

    # "password length is greater than 128" — must be before generic > pattern
    (re.compile(
        r"(\w[\w\s]*?)\s+length\s+(?:is\s+)?(?:above|greater\s+than|over|>)\s+(\S+)",
        re.IGNORECASE,
    ), 1, "length>{value}"),

    # "age is below 18", "age is less than 18", "age < 18"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+)?(?:below|less\s+than|under|<)\s+(\S+)",
        re.IGNORECASE,
    ), 1, "<{value}"),

    # "age is above 65", "age is greater than 65", "age > 65"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+)?(?:above|greater\s+than|over|exceeds|>)\s+(\S+)",
        re.IGNORECASE,
    ), 1, ">{value}"),

    # "age is equal to 18", "age equals 18", "age = 18", "age is 18"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+equal\s+to|equals|==?)\s+(\S+)",
        re.IGNORECASE,
    ), 1, "=={value}"),

    # "email is null", "phone is empty", "name is blank"
    (re.compile(
        r"(\w[\w\s]*?)\s+is\s+(?:null|empty|blank|missing|not\s+provided)",
        re.IGNORECASE,
    ), 1, "null"),

    # "email is not null", "name is present", "name is provided"
    (re.compile(
        r"(\w[\w\s]*?)\s+is\s+(?:not\s+null|not\s+empty|present|provided)",
        re.IGNORECASE,
    ), 1, "not_null"),

    # "email is duplicate", "username is duplicated", "email already exists"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+)?(?:duplicate[d]?|already\s+exists)",
        re.IGNORECASE,
    ), 1, "duplicate"),

    # "email is invalid", "email has invalid format", "email format is invalid"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+invalid|has\s+invalid\s+format|format\s+is\s+invalid)",
        re.IGNORECASE,
    ), 1, "invalid_format"),

    # "email is valid", "email has valid format"
    (re.compile(
        r"(\w[\w\s]*?)\s+(?:is\s+valid|has\s+valid\s+format)",
        re.IGNORECASE,
    ), 1, "valid_format"),

    # "amount is between 100 and 500"
    (re.compile(
        r"(\w[\w\s]*?)\s+is\s+between\s+(\S+)\s+and\s+(\S+)",
        re.IGNORECASE,
    ), 1, "between({value},{value2})"),
]

# ── Outcome patterns ─────────────────────────────────────────

_OUTCOME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"should\s+fail|fails|rejected|denied|not\s+allowed|error", re.IGNORECASE), "fail"),
    (re.compile(r"should\s+succeed|succeeds|accepted|approved|allowed|passes", re.IGNORECASE), "pass"),
    (re.compile(r"requires?\s+.*approval|approval\s+required", re.IGNORECASE), "requires_approval"),
    (re.compile(r"warning|flagged", re.IGNORECASE), "warning"),
]

_STEP_PREFIX = re.compile(r"^\s*(Given|When|Then|And|But)\s+", re.IGNORECASE)
_FEATURE_LINE = re.compile(r"^\s*Feature:\s*(.+)", re.IGNORECASE)
_SCENARIO_LINE = re.compile(r"^\s*Scenario(?:\s+Outline)?:\s*(.+)", re.IGNORECASE)


def parse_bdd_feature(content: str) -> BDDMetadata:
    """Parse a Gherkin .feature file and extract structured rules."""
    lines = content.splitlines()

    feature_name = ""
    scenarios: list[BDDScenario] = []
    current_scenario: BDDScenario | None = None
    pending_conditions: list[tuple[str, str]] = []  # (field, condition)

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue

        # Feature line
        feat_match = _FEATURE_LINE.match(line)
        if feat_match:
            feature_name = feat_match.group(1).strip()
            continue

        # Scenario line
        scen_match = _SCENARIO_LINE.match(line)
        if scen_match:
            if current_scenario is not None:
                _flush_pending(current_scenario, pending_conditions, "unknown")
                scenarios.append(current_scenario)
            current_scenario = BDDScenario(name=scen_match.group(1).strip())
            pending_conditions = []
            continue

        # Step line
        step_match = _STEP_PREFIX.match(line)
        if not step_match:
            continue

        keyword = step_match.group(1).lower()
        step_text = _STEP_PREFIX.sub("", line).strip()

        if current_scenario is None:
            current_scenario = BDDScenario()

        current_scenario.raw_steps.append(line)

        # Given / When / And → condition
        if keyword in ("given", "when", "and", "but"):
            cond = _extract_condition(step_text)
            if cond:
                pending_conditions.append(cond)

        # Then → outcome
        if keyword == "then":
            outcome = _extract_outcome(step_text)
            # Also check if Then line itself has a condition
            cond = _extract_condition(step_text)
            if cond:
                pending_conditions.append(cond)

            _flush_pending(current_scenario, pending_conditions, outcome)
            pending_conditions = []

    # Flush last scenario
    if current_scenario is not None:
        _flush_pending(current_scenario, pending_conditions, "unknown")
        scenarios.append(current_scenario)

    if not scenarios:
        logger.warning("No scenarios found in BDD feature file")

    return BDDMetadata(feature=feature_name, scenarios=scenarios)


def _flush_pending(
    scenario: BDDScenario,
    conditions: list[tuple[str, str]],
    outcome: str,
) -> None:
    """Convert accumulated conditions into rules with the given outcome."""
    for field, condition in conditions:
        scenario.rules.append(
            BDDRule(field=field, condition=condition, result=outcome)
        )
    conditions.clear()


def _extract_condition(text: str) -> tuple[str, str] | None:
    """Try to match a step line against known condition patterns."""
    for pattern, field_group, condition_template in _CONDITION_PATTERNS:
        m = pattern.search(text)
        if m:
            field = _normalize_field(m.group(field_group))
            if "{value2}" in condition_template:
                condition = condition_template.format(
                    value=m.group(2), value2=m.group(3)
                )
            elif "{value}" in condition_template:
                condition = condition_template.format(value=m.group(2))
            else:
                condition = condition_template
            return field, condition
    return None


def _extract_outcome(text: str) -> str:
    """Try to match a step line against known outcome patterns."""
    for pattern, outcome in _OUTCOME_PATTERNS:
        if pattern.search(text):
            return outcome
    return "unknown"


def _normalize_field(raw: str) -> str:
    """Normalize a field name: lowercase, strip articles, underscorize."""
    raw = raw.strip().lower()
    # Remove leading articles / noise words
    raw = re.sub(r"^(the|a|an|user|user\'?s?|customer|customer\'?s?)\s+", "", raw)
    # Replace spaces with underscores
    raw = re.sub(r"\s+", "_", raw)
    return raw
