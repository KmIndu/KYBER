"""Parse and validate structured JSON responses from the AI provider."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.models.ai import AIConstraint, AIEdgeCase, AIReasoningResult
from app.models.integration import (
    GuideStep,
    IntegrationGuide,
    IntegrationGuideSection,
)

logger = logging.getLogger(__name__)


class OutputParserError(Exception):
    """Raised when the AI response cannot be parsed into structured output."""


def parse_ai_response(raw: str, provider: str = "") -> AIReasoningResult:
    """Parse a raw AI response string into a validated AIReasoningResult.

    Handles:
    - pure JSON
    - JSON wrapped in markdown code fences
    - partial / truncated JSON (best-effort)
    """
    cleaned = _extract_json(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse AI JSON: %s", e)
        raise OutputParserError(f"Invalid JSON from AI: {e}") from e

    if not isinstance(data, dict):
        raise OutputParserError(f"Expected JSON object, got {type(data).__name__}")

    return _build_result(data, raw, provider)


def _extract_json(raw: str) -> str:
    """Extract JSON from raw text, stripping markdown fences if present."""
    raw = raw.strip()

    # Strip ```json ... ``` wrappers
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Already starts with { or [
    if raw.startswith(("{", "[")):
        return raw

    # Try to find the first { ... } block
    start = raw.find("{")
    if start != -1:
        return raw[start:]

    return raw


def _build_result(
    data: dict[str, Any], raw: str, provider: str
) -> AIReasoningResult:
    """Build and validate an AIReasoningResult from parsed JSON dict."""
    hidden = _parse_constraints(data.get("hidden_constraints", []))
    rules = _parse_constraints(data.get("business_rules", []))
    edges = _parse_edge_cases(data.get("edge_cases", []))

    return AIReasoningResult(
        hidden_constraints=hidden,
        business_rules=rules,
        edge_cases=edges,
        provider=provider,
        raw_response=raw,
    )


def _parse_constraints(items: list[dict[str, Any]]) -> list[AIConstraint]:
    """Parse a list of constraint dicts, skipping invalid entries."""
    result: list[AIConstraint] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            result.append(
                AIConstraint(
                    table=item.get("table", ""),
                    column=item.get("column", ""),
                    constraint_type=item.get("constraint_type", "unknown"),
                    description=item.get("description", ""),
                    suggestion=item.get("suggestion", {}),
                )
            )
        except Exception:
            logger.debug("Skipping malformed constraint: %s", item)
    return result


def _parse_edge_cases(items: list[dict[str, Any]]) -> list[AIEdgeCase]:
    """Parse a list of edge-case dicts, skipping invalid entries."""
    result: list[AIEdgeCase] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            result.append(
                AIEdgeCase(
                    table=item.get("table", ""),
                    column=item.get("column", ""),
                    scenario=item.get("scenario", ""),
                    test_value=item.get("test_value"),
                )
            )
        except Exception:
            logger.debug("Skipping malformed edge case: %s", item)
    return result


def parse_guide_response(
    raw: str, session_id: str, provider: str = ""
) -> IntegrationGuide:
    """Parse a raw AI response into an IntegrationGuide."""
    cleaned = _extract_json(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OutputParserError(f"Invalid JSON from AI (guide): {e}") from e

    if not isinstance(data, dict):
        raise OutputParserError(f"Expected JSON object, got {type(data).__name__}")

    sections: list[IntegrationGuideSection] = []
    for sec in data.get("sections", []):
        if not isinstance(sec, dict):
            continue
        steps: list[GuideStep] = []
        for s in sec.get("steps", []):
            if not isinstance(s, dict):
                continue
            try:
                steps.append(
                    GuideStep(
                        step_number=s.get("step_number", 0),
                        title=s.get("title", ""),
                        description=s.get("description", ""),
                        code_snippet=s.get("code_snippet", ""),
                        language=s.get("language", ""),
                    )
                )
            except Exception:
                logger.debug("Skipping malformed guide step: %s", s)
        try:
            sections.append(
                IntegrationGuideSection(
                    scenario=sec.get("scenario", ""),
                    summary=sec.get("summary", ""),
                    prerequisites=sec.get("prerequisites", []),
                    steps=steps,
                    tips=sec.get("tips", []),
                )
            )
        except Exception:
            logger.debug("Skipping malformed guide section: %s", sec)

    return IntegrationGuide(
        session_id=session_id,
        overview=data.get("overview", ""),
        sections=sections,
        provider=provider,
    )
