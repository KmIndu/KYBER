"""AI-powered row correlation engine.

Generates coherent "row profiles" that define how column values should
relate to each other within a single row. For example:
  - A "young_new_customer" profile → age 22-30, recent join_date, starter policy, low premium
  - An "elderly_high_value" profile → age 60-75, old join_date, comprehensive policy, high premium

Strategy:
  1. Call LLM once per table to generate 30-50 row profiles
  2. Each profile defines value constraints/ranges for correlated columns
  3. Rows are assigned to profiles by weight
  4. Vectorized generation uses profile-scoped constraints

Falls back to heuristic-based correlation when AI gateway is unavailable.
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

from app.models.schema import SchemaMetadata, TableMetadata
from app.utils.sql_types import base_type as _base_type

logger = logging.getLogger(__name__)


# ── Data Structures ───────────────────────────────────────────

@dataclass
class ColumnConstraint:
    """Value constraint for a column within a profile."""
    values: list[Any] | None = None      # Pick from these (enum-style)
    min_val: float | None = None          # Numeric min
    max_val: float | None = None          # Numeric max
    null_probability: float = 0.0         # Chance of None
    pattern: str | None = None            # String format hint


@dataclass
class RowProfile:
    """A coherent row archetype with correlated column constraints."""
    name: str
    description: str
    weight: float = 1.0  # Relative probability of this profile
    constraints: dict[str, ColumnConstraint] = field(default_factory=dict)


@dataclass
class TableProfiles:
    """All row profiles for a single table."""
    table_name: str
    profiles: list[RowProfile]

    def assign_rows(self, n: int) -> list[int]:
        """Assign n rows to profiles by weight, return profile indices."""
        if not self.profiles:
            return [0] * n
        weights = [p.weight for p in self.profiles]
        total = sum(weights)
        normalized = [w / total for w in weights]
        import numpy as np
        rng = np.random.default_rng()
        return rng.choice(len(self.profiles), size=n, p=normalized).tolist()


# ── AI-Powered Profile Generation ────────────────────────────

_PROFILE_SYSTEM = (
    "You are a synthetic data expert. Given a database table schema, generate "
    "realistic ROW PROFILES — coherent archetypes where column values make sense "
    "together. Each profile represents a realistic 'type' of row that could exist.\n\n"
    "RULES:\n"
    "- Each profile must define correlated values that make business sense together\n"
    "- Include 20-40 profiles with varying weights (common scenarios get higher weights)\n"
    "- For enum/status columns: provide exact values\n"
    "- For numeric columns: provide realistic min/max ranges\n"
    "- For date columns: provide relative ranges (e.g., 'recent', 'old')\n"
    "- Ensure logical consistency (e.g., 'cancelled' status → null approval_date)\n"
    "- Output ONLY valid JSON\n"
)

_PROFILE_TEMPLATE = """\
Generate row profiles for this table:

TABLE: {table_name}
COLUMNS: {columns_desc}
FOREIGN KEYS: {fk_desc}
DOMAIN: {domain}

Return JSON with this structure:
{{
  "profiles": [
    {{
      "name": "profile_name",
      "description": "Brief description of this row archetype",
      "weight": 2.0,
      "constraints": {{
        "column_name": {{
          "values": ["val1", "val2"],
          "min_val": null,
          "max_val": null,
          "null_probability": 0.0
        }}
      }}
    }}
  ]
}}

IMPORTANT:
- Skip primary key columns and foreign key columns (they are auto-managed)
- Focus on columns where cross-column correlation matters
- weights should sum to roughly 20 (common profiles get 2-3, rare ones get 0.5-1)
- For string enum columns, provide the exact allowed values in "values"
- For numeric columns, provide min_val/max_val ranges
- null_probability should be 0.0 for required columns, 0.0-0.3 for optional ones
- Make profiles business-realistic (e.g., a denied claim shouldn't have a payout amount > 0)
"""


def generate_profiles_with_ai(
    table: TableMetadata,
    domain: str = "unknown",
) -> TableProfiles | None:
    """Call LLM to generate row correlation profiles for a table.

    Returns None if gateway unavailable — falls back to heuristic profiles.
    """
    from app.utils.config import settings
    from app.models.ai import AIProviderConfig

    config = AIProviderConfig(
        gateway_url=settings.AI_GATEWAY_URL,
        api_token=settings.AI_GATEWAY_TOKEN,
        model=settings.AI_MODEL,
        api_format=settings.AI_API_FORMAT,
        timeout=settings.AI_TIMEOUT,
        max_retries=settings.AI_MAX_RETRIES,
    )

    if not config.gateway_url or not config.api_token:
        logger.info("AI gateway not configured — using heuristic profiles")
        return None

    # Build column description
    fk_cols = {fk.column for fk in table.foreign_keys}
    pk_cols = {c.name for c in table.columns if c.is_primary_key}
    skip_cols = fk_cols | pk_cols

    columns_desc = ", ".join(
        f"{c.name} {c.data_type}"
        + (f" CHECK({c.check_constraint})" if c.check_constraint else "")
        + (" NULLABLE" if c.nullable else " NOT NULL")
        for c in table.columns if c.name not in skip_cols
    )
    fk_desc = ", ".join(
        f"{fk.column} → {fk.references_table}.{fk.references_column}"
        for fk in table.foreign_keys
    ) or "none"

    prompt = _PROFILE_TEMPLATE.format(
        table_name=table.name,
        columns_desc=columns_desc,
        fk_desc=fk_desc,
        domain=domain,
    )

    try:
        raw = _call_profile_inference(prompt, config)
        profiles = _parse_profiles(raw, table.name)
        if profiles:
            logger.info(
                "AI generated %d row profiles for table %s",
                len(profiles.profiles), table.name,
            )
            return profiles
    except Exception as e:
        logger.warning("AI profile generation failed for %s: %s", table.name, e)

    return None


def _call_profile_inference(prompt: str, config) -> str:
    """Send profile generation prompt to AI gateway."""
    import requests

    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    if config.api_format == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        payload = {
            "model": config.model,
            "system": _PROFILE_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 4096,
        }
        url = config.gateway_url.rstrip("/")
        if not url.endswith("/messages"):
            url = f"{url}/messages"
        resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    else:
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": _PROFILE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": 4096,
        }
        url = config.gateway_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _parse_profiles(raw: str, table_name: str) -> TableProfiles | None:
    """Parse LLM JSON response into TableProfiles."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("AI row profiles returned invalid JSON")
        return None

    profiles_data = data.get("profiles", [])
    if not profiles_data:
        return None

    profiles: list[RowProfile] = []
    for p in profiles_data:
        constraints: dict[str, ColumnConstraint] = {}
        for col_name, spec in (p.get("constraints") or {}).items():
            constraints[col_name] = ColumnConstraint(
                values=spec.get("values"),
                min_val=spec.get("min_val"),
                max_val=spec.get("max_val"),
                null_probability=spec.get("null_probability", 0.0),
                pattern=spec.get("pattern"),
            )
        profiles.append(RowProfile(
            name=p.get("name", "unknown"),
            description=p.get("description", ""),
            weight=p.get("weight", 1.0),
            constraints=constraints,
        ))

    return TableProfiles(table_name=table_name, profiles=profiles)


# ── Heuristic Fallback Profiles ───────────────────────────────

def generate_profiles_heuristic(
    table: TableMetadata,
    domain: str = "unknown",
) -> TableProfiles:
    """Generate correlation profiles using heuristic rules.

    Detects column roles (status, amount, date, etc.) and builds
    coherent profiles that correlate them realistically.
    """
    fk_cols = {fk.column for fk in table.foreign_keys}
    pk_cols = {c.name for c in table.columns if c.is_primary_key}

    # Classify columns by role
    status_cols: list[str] = []
    amount_cols: list[str] = []
    date_cols: list[str] = []
    bool_cols: list[str] = []
    text_cols: list[str] = []
    other_cols: list[str] = []

    _STATUS_PAT = re.compile(r"status|state|phase|stage|decision|outcome|type", re.I)
    _AMOUNT_PAT = re.compile(r"amount|total|price|cost|fee|balance|premium|payment|salary|rate", re.I)
    _DATE_PAT = re.compile(r"_at$|_on$|_date$|_time$|created|updated|submitted|closed|completed|start|end|birth|expir", re.I)
    _BOOL_PAT = re.compile(r"^is_|^has_|^can_|_flag$|active|enabled|verified", re.I)

    for col in table.columns:
        if col.name in fk_cols or col.name in pk_cols:
            continue
        base = _base_type(col.data_type)
        if _STATUS_PAT.search(col.name):
            status_cols.append(col.name)
        elif _AMOUNT_PAT.search(col.name):
            amount_cols.append(col.name)
        elif _DATE_PAT.search(col.name) or base in ("date", "datetime"):
            date_cols.append(col.name)
        elif base == "boolean" or _BOOL_PAT.search(col.name):
            bool_cols.append(col.name)
        elif base in ("integer", "float"):
            amount_cols.append(col.name)
        else:
            text_cols.append(col.name)

    # Detect CHECK constraint enums for status columns
    status_values: dict[str, list[str]] = {}
    for col in table.columns:
        if col.name in status_cols and col.check_constraint:
            from app.utils.sql_types import extract_enum_from_check
            vals = extract_enum_from_check(col.check_constraint)
            if vals:
                status_values[col.name] = vals

    profiles = _build_correlated_profiles(
        table.name, domain,
        status_cols, status_values,
        amount_cols, date_cols, bool_cols, text_cols,
        table.columns,
    )

    return TableProfiles(table_name=table.name, profiles=profiles)


def _build_correlated_profiles(
    table_name: str,
    domain: str,
    status_cols: list[str],
    status_values: dict[str, list[str]],
    amount_cols: list[str],
    date_cols: list[str],
    bool_cols: list[str],
    text_cols: list[str],
    all_columns: list,
) -> list[RowProfile]:
    """Build correlated profiles based on detected column roles."""
    profiles: list[RowProfile] = []

    # If we have status columns with known values, build status-driven profiles
    if status_cols and status_values:
        primary_status = status_cols[0]
        values = status_values[primary_status]
        profiles.extend(_status_driven_profiles(
            primary_status, values, amount_cols, date_cols, bool_cols, domain
        ))
    else:
        # No explicit status — build amount-range profiles
        profiles.extend(_amount_driven_profiles(amount_cols, date_cols, bool_cols, domain))

    # Add edge cases
    profiles.extend(_edge_case_profiles(status_cols, amount_cols, date_cols, bool_cols))

    # If no profiles could be built, create a generic one
    if not profiles:
        profiles.append(RowProfile(
            name="default",
            description="Default row with no special correlation",
            weight=1.0,
            constraints={},
        ))

    return profiles


def _status_driven_profiles(
    status_col: str,
    status_values: list[str],
    amount_cols: list[str],
    date_cols: list[str],
    bool_cols: list[str],
    domain: str,
) -> list[RowProfile]:
    """Create profiles where status drives other column values."""
    profiles: list[RowProfile] = []

    # Classify status values into categories
    _POSITIVE = {"approved", "completed", "resolved", "paid", "settled", "accepted", "active", "success", "processed"}
    _NEGATIVE = {"rejected", "denied", "declined", "failed", "cancelled", "refused", "closed", "expired", "terminated"}
    _PENDING = {"pending", "submitted", "in_review", "under_review", "processing", "queued", "open", "new", "draft"}

    for status_val in status_values:
        val_lower = status_val.lower().replace("-", "_").replace(" ", "_")
        constraints: dict[str, ColumnConstraint] = {
            status_col: ColumnConstraint(values=[status_val])
        }

        if val_lower in _POSITIVE or any(p in val_lower for p in ("approv", "complet", "paid", "settl")):
            # Positive status → higher amounts, completion dates present, active flags True
            for ac in amount_cols:
                if re.search(r"amount|total|payment|payout", ac, re.I):
                    constraints[ac] = ColumnConstraint(min_val=100, max_val=50000)
                elif re.search(r"premium|fee|rate", ac, re.I):
                    constraints[ac] = ColumnConstraint(min_val=50, max_val=5000)
            for dc in date_cols:
                if re.search(r"complet|approv|paid|settl|closed", dc, re.I):
                    constraints[dc] = ColumnConstraint(null_probability=0.0)
                elif re.search(r"cancel|reject|deny", dc, re.I):
                    constraints[dc] = ColumnConstraint(null_probability=1.0)
            for bc in bool_cols:
                if re.search(r"active|enabled|verified|valid", bc, re.I):
                    constraints[bc] = ColumnConstraint(values=[True])
                elif re.search(r"cancelled|rejected|deleted", bc, re.I):
                    constraints[bc] = ColumnConstraint(values=[False])

            profiles.append(RowProfile(
                name=f"status_{val_lower}",
                description=f"Row with {status_val} status — positive outcome",
                weight=2.5,
                constraints=constraints,
            ))

        elif val_lower in _NEGATIVE or any(p in val_lower for p in ("reject", "deny", "declin", "cancel", "fail")):
            # Negative status → zero/null payout, rejection dates present, active=False
            for ac in amount_cols:
                if re.search(r"payout|payment|settlement|disbursement", ac, re.I):
                    constraints[ac] = ColumnConstraint(values=[0], min_val=0, max_val=0)
                elif re.search(r"amount|total", ac, re.I):
                    constraints[ac] = ColumnConstraint(min_val=10, max_val=25000)
            for dc in date_cols:
                if re.search(r"complet|approv|paid|settl", dc, re.I):
                    constraints[dc] = ColumnConstraint(null_probability=1.0)
                elif re.search(r"cancel|reject|deny|closed", dc, re.I):
                    constraints[dc] = ColumnConstraint(null_probability=0.0)
            for bc in bool_cols:
                if re.search(r"active|enabled|valid", bc, re.I):
                    constraints[bc] = ColumnConstraint(values=[False])
                elif re.search(r"cancelled|rejected|deleted", bc, re.I):
                    constraints[bc] = ColumnConstraint(values=[True])

            profiles.append(RowProfile(
                name=f"status_{val_lower}",
                description=f"Row with {status_val} status — negative outcome",
                weight=1.5,
                constraints=constraints,
            ))

        elif val_lower in _PENDING or any(p in val_lower for p in ("pending", "submit", "review", "process", "open")):
            # Pending status → moderate amounts, no completion dates, active=True
            for ac in amount_cols:
                if re.search(r"payout|payment|settlement", ac, re.I):
                    constraints[ac] = ColumnConstraint(null_probability=0.8)
                elif re.search(r"amount|total", ac, re.I):
                    constraints[ac] = ColumnConstraint(min_val=50, max_val=30000)
            for dc in date_cols:
                if re.search(r"complet|approv|paid|settl|closed|cancel|reject", dc, re.I):
                    constraints[dc] = ColumnConstraint(null_probability=1.0)
            for bc in bool_cols:
                if re.search(r"active|enabled", bc, re.I):
                    constraints[bc] = ColumnConstraint(values=[True])

            profiles.append(RowProfile(
                name=f"status_{val_lower}",
                description=f"Row with {status_val} status — in progress",
                weight=2.0,
                constraints=constraints,
            ))
        else:
            # Unknown category — just set the status value
            profiles.append(RowProfile(
                name=f"status_{val_lower}",
                description=f"Row with {status_val} status",
                weight=1.0,
                constraints=constraints,
            ))

    return profiles


def _amount_driven_profiles(
    amount_cols: list[str],
    date_cols: list[str],
    bool_cols: list[str],
    domain: str,
) -> list[RowProfile]:
    """Create profiles based on amount ranges when no status column exists."""
    profiles: list[RowProfile] = []

    if not amount_cols:
        return profiles

    # Low value
    constraints_low: dict[str, ColumnConstraint] = {}
    for ac in amount_cols:
        constraints_low[ac] = ColumnConstraint(min_val=1, max_val=500)
    profiles.append(RowProfile(
        name="low_value",
        description="Low-value transaction/entity",
        weight=3.0,
        constraints=constraints_low,
    ))

    # Medium value
    constraints_med: dict[str, ColumnConstraint] = {}
    for ac in amount_cols:
        constraints_med[ac] = ColumnConstraint(min_val=500, max_val=10000)
    profiles.append(RowProfile(
        name="medium_value",
        description="Medium-value transaction/entity",
        weight=4.0,
        constraints=constraints_med,
    ))

    # High value
    constraints_high: dict[str, ColumnConstraint] = {}
    for ac in amount_cols:
        constraints_high[ac] = ColumnConstraint(min_val=10000, max_val=100000)
    profiles.append(RowProfile(
        name="high_value",
        description="High-value transaction/entity",
        weight=2.0,
        constraints=constraints_high,
    ))

    # Premium/VIP
    constraints_vip: dict[str, ColumnConstraint] = {}
    for ac in amount_cols:
        constraints_vip[ac] = ColumnConstraint(min_val=100000, max_val=1000000)
    profiles.append(RowProfile(
        name="premium_vip",
        description="Premium/VIP high-value case",
        weight=0.5,
        constraints=constraints_vip,
    ))

    return profiles


def _edge_case_profiles(
    status_cols: list[str],
    amount_cols: list[str],
    date_cols: list[str],
    bool_cols: list[str],
) -> list[RowProfile]:
    """Create edge-case profiles for testing boundary conditions."""
    profiles: list[RowProfile] = []

    # Zero-amount edge case
    if amount_cols:
        constraints: dict[str, ColumnConstraint] = {}
        for ac in amount_cols:
            constraints[ac] = ColumnConstraint(values=[0])
        profiles.append(RowProfile(
            name="zero_amount",
            description="Edge case: all amounts are zero",
            weight=0.3,
            constraints=constraints,
        ))

    # All nullable columns are null
    if bool_cols:
        constraints = {}
        for bc in bool_cols:
            constraints[bc] = ColumnConstraint(null_probability=0.5)
        profiles.append(RowProfile(
            name="sparse_data",
            description="Edge case: many nullable fields are null",
            weight=0.5,
            constraints=constraints,
        ))

    return profiles


# ── Public API ────────────────────────────────────────────────

def get_table_profiles(
    table: TableMetadata,
    domain: str = "unknown",
    use_ai: bool = True,
) -> TableProfiles:
    """Get row correlation profiles for a table.

    Tries AI first (if configured), falls back to heuristic profiles.
    """
    if use_ai:
        ai_profiles = generate_profiles_with_ai(table, domain)
        if ai_profiles:
            return ai_profiles

    return generate_profiles_heuristic(table, domain)
