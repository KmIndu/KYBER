"""AI-powered column inference — uses an LLM to determine realistic value
generation strategies for each column in the schema.

The AI analyzes column names, types, relationships, and table context to
produce generation hints that tell the synthetic generator HOW to produce
realistic values (e.g., value ranges, formats, enum lists, realistic patterns).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.ai.prompts import SYSTEM_PROMPT
from app.models.ai import AIProviderConfig
from app.models.schema import SchemaMetadata
from app.utils.config import settings

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────

class ColumnHint:
    """AI-inferred generation hint for a single column."""

    __slots__ = ("strategy", "values", "min_val", "max_val", "pattern", "prefix", "format_hint")

    def __init__(
        self,
        strategy: str = "default",
        values: list[Any] | None = None,
        min_val: float | int | None = None,
        max_val: float | int | None = None,
        pattern: str | None = None,
        prefix: str | None = None,
        format_hint: str | None = None,
    ) -> None:
        self.strategy = strategy  # "enum", "range", "pattern", "prefix_seq", "faker", "default"
        self.values = values      # For enum strategy: list of realistic values
        self.min_val = min_val    # For range strategy
        self.max_val = max_val    # For range strategy
        self.pattern = pattern    # For pattern strategy (regex-like hint)
        self.prefix = prefix      # For prefix_seq strategy (e.g., "AGT-")
        self.format_hint = format_hint  # Human-readable hint


# Type alias
ColumnHints = dict[str, dict[str, ColumnHint]]  # table_name -> col_name -> ColumnHint


# ── Prompt ────────────────────────────────────────────────────

_INFERENCE_SYSTEM = (
    "You are a data-generation expert. Given a database schema, you infer "
    "the BEST strategy to generate realistic synthetic values for each column.\n\n"
    "For each column, decide one strategy:\n"
    "- \"enum\": column has a small set of realistic values (provide them in \"values\")\n"
    "- \"range\": numeric column with a realistic min/max (provide min_val, max_val)\n"
    "- \"pattern\": string column with a recognizable format (provide pattern description)\n"
    "- \"prefix_seq\": ID-like column with a prefix + sequence (provide prefix)\n"
    "- \"faker\": column best handled by Faker (provide format_hint like \"email\", \"name\", etc.)\n"
    "- \"default\": no special handling needed (FK columns, PKs, etc.)\n\n"
    "IMPORTANT:\n"
    "- Skip primary key columns (set strategy to \"default\")\n"
    "- Skip foreign key columns (set strategy to \"default\")\n"
    "- Focus on columns that would benefit from realistic values\n"
    "- For enum columns, provide 5-15 realistic domain-appropriate values\n"
    "- For range columns used as IDs referencing other tables, use \"default\"\n"
    "- Output ONLY valid JSON — no markdown, no commentary\n"
)

_INFERENCE_TEMPLATE = """\
Analyze this schema and provide generation hints for each column.

Schema:
{schema_text}

Domain context: {domain}

Return JSON with this exact structure:
{{
  "hints": {{
    "<table_name>": {{
      "<column_name>": {{
        "strategy": "enum|range|pattern|prefix_seq|faker|default",
        "values": ["val1", "val2"],
        "min_val": 0,
        "max_val": 100,
        "pattern": "XXX-####",
        "prefix": "AGT-",
        "format_hint": "email"
      }}
    }}
  }}
}}

Only include fields relevant to the chosen strategy. Use null for irrelevant fields.
For enum strategy, ensure values match the column's data type (integers for INT columns, strings for VARCHAR).
"""


# ── Public API ────────────────────────────────────────────────


def infer_column_hints(
    schema: SchemaMetadata,
    domain: str = "unknown",
) -> ColumnHints | None:
    """Call the AI gateway to infer column generation hints.

    Returns None if the gateway is unavailable or the call fails.
    Falls through gracefully — the generator uses its existing logic as fallback.
    """
    config = _get_config()
    if not config.gateway_url or not config.api_token:
        logger.info("AI gateway not configured — skipping column inference")
        return None

    schema_text = _schema_to_prompt(schema)
    prompt = _INFERENCE_TEMPLATE.format(schema_text=schema_text, domain=domain)

    try:
        raw = _call_inference(prompt, config)
        return _parse_response(raw)
    except Exception as e:
        logger.warning(
            "AI column inference failed, falling back to default generation: %s",
            e,
            extra={"stage": "ai_inference", "event": "inference_failed", "error_type": type(e).__name__},
        )
        return None


# ── Internal helpers ──────────────────────────────────────────


def _get_config() -> AIProviderConfig:
    return AIProviderConfig(
        gateway_url=settings.AI_GATEWAY_URL,
        api_token=settings.AI_GATEWAY_TOKEN,
        model=settings.AI_MODEL,
        api_format=settings.AI_API_FORMAT,
        timeout=settings.AI_TIMEOUT,
        max_retries=settings.AI_MAX_RETRIES,
    )


def _schema_to_prompt(schema: SchemaMetadata) -> str:
    """Convert schema to a concise text representation for the prompt."""
    lines: list[str] = []
    for t in schema.tables:
        cols = ", ".join(
            f"{c.name} {c.data_type}"
            + (" PK" if c.is_primary_key else "")
            + (" NOT NULL" if not c.nullable else "")
            + (f" CHECK({c.check_constraint})" if c.check_constraint else "")
            for c in t.columns
        )
        fks = ", ".join(
            f"FK {fk.column} → {fk.references_table}.{fk.references_column}"
            for fk in t.foreign_keys
        )
        line = f"TABLE {t.name} ({cols})"
        if fks:
            line += f" [{fks}]"
        lines.append(line)
    return "\n".join(lines)


def _call_inference(prompt: str, config: AIProviderConfig) -> str:
    """Send the inference prompt to the AI gateway."""
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    if config.api_format == "anthropic":
        return _send_anthropic(prompt, config, headers)
    return _send_openai(prompt, config, headers)


def _send_openai(prompt: str, config: AIProviderConfig, headers: dict) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": _INFERENCE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    url = config.gateway_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"

    resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _send_anthropic(prompt: str, config: AIProviderConfig, headers: dict) -> str:
    headers["anthropic-version"] = "2023-06-01"
    payload = {
        "model": config.model,
        "system": _INFERENCE_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    url = config.gateway_url.rstrip("/")
    if not url.endswith("/messages"):
        url = f"{url}/messages"

    resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


def _parse_response(raw: str) -> ColumnHints | None:
    """Parse the AI JSON response into ColumnHints dict."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("AI column inference returned invalid JSON")
        return None

    hints_data = data.get("hints", data)  # Allow top-level or nested
    if not isinstance(hints_data, dict):
        return None

    result: ColumnHints = {}
    for table_name, columns in hints_data.items():
        if not isinstance(columns, dict):
            continue
        table_hints: dict[str, ColumnHint] = {}
        for col_name, hint_data in columns.items():
            if not isinstance(hint_data, dict):
                continue
            strategy = hint_data.get("strategy", "default")
            if strategy == "default":
                continue  # No hint needed for default
            table_hints[col_name] = ColumnHint(
                strategy=strategy,
                values=hint_data.get("values"),
                min_val=hint_data.get("min_val"),
                max_val=hint_data.get("max_val"),
                pattern=hint_data.get("pattern"),
                prefix=hint_data.get("prefix"),
                format_hint=hint_data.get("format_hint"),
            )
        if table_hints:
            result[table_name] = table_hints

    return result if result else None
