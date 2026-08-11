"""Derivation Rule Engine — derives dependent field values from source business context.

Implements deterministic derivation rules with dependency chaining, conflict
prevention, rule priority handling, and validation hooks.

Examples:
  full_name → email (identity derivation)
  country → phone_code (geographic mapping)
  status → comments (state-driven explanation)
  claim_status → rejection_reason (conditional presence)

Architecture:
  - DerivationRule: single rule with source→target derivation function
  - DerivationChain: ordered chain of rules respecting dependencies
  - DerivationEngine: orchestrator with conflict resolution and validation
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from faker import Faker

fake = Faker()


# ── Rule Definition ───────────────────────────────────────────

@dataclass
class DerivationRule:
    """A single derivation rule mapping source column(s) → target column."""

    name: str
    # Regex patterns that match source column names
    source_patterns: list[re.Pattern]
    # Regex pattern that matches the target (derived) column name
    target_pattern: re.Pattern
    # Derivation function: (source_values: dict[str, Any], row_index: int, context: dict) → derived_value
    derive_fn: Callable[[dict[str, Any], int, dict[str, Any]], Any]
    # Higher priority rules win conflicts (higher number = higher priority)
    priority: int = 50
    # Domain applicability (None = all domains)
    domains: list[str] | None = None
    # Optional validation function: (derived_value, source_values, context) → bool
    validate_fn: Callable[[Any, dict[str, Any], dict[str, Any]], bool] | None = None
    # Human-readable description
    description: str = ""

    def applies_to_domain(self, domain: str | None) -> bool:
        """Check if this rule applies to the given domain."""
        if self.domains is None:
            return True
        if domain is None:
            return True
        return domain.lower() in [d.lower() for d in self.domains]


@dataclass
class DerivationResult:
    """Result of applying derivation rules to a table."""

    # column_name → list[values] for each derived column
    derived_columns: dict[str, list[Any]]
    # Provenance: column_name → rule_name that produced it
    provenance: dict[str, str]
    # Conflicts that were resolved: target_col → list of (rule_name, priority) that lost
    conflicts_resolved: dict[str, list[tuple[str, int]]]
    # Validation failures: (rule_name, row_index, reason)
    validation_failures: list[tuple[str, int, str]]
    # Execution order of rules (after topological sort)
    execution_order: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_column_count": len(self.derived_columns),
            "columns": list(self.derived_columns.keys()),
            "provenance": self.provenance,
            "conflicts_resolved": {
                k: [{"rule": r, "priority": p} for r, p in v]
                for k, v in self.conflicts_resolved.items()
            },
            "validation_failures": [
                {"rule": r, "row": i, "reason": reason}
                for r, i, reason in self.validation_failures
            ],
            "execution_order": self.execution_order,
        }


# ── Dependency Graph & Topological Sort ───────────────────────

class CyclicDependencyError(Exception):
    """Raised when derivation rules form a circular dependency."""


def _topological_sort(rules: list[_ResolvedRule]) -> list[_ResolvedRule]:
    """Sort rules respecting dependencies (source columns of rule B may be
    targets of rule A → A must run first).

    Uses Kahn's algorithm for cycle detection.
    """
    # Build adjacency: if rule A produces a column that rule B needs as source,
    # then B depends on A
    target_to_rule: dict[str, _ResolvedRule] = {}
    for r in rules:
        target_to_rule[r.target_col] = r

    # Build edges: rule → set of rules it depends on
    in_degree: dict[str, int] = {r.rule.name: 0 for r in rules}
    dependents: dict[str, list[_ResolvedRule]] = {r.rule.name: [] for r in rules}

    for r in rules:
        for src_col in r.source_cols:
            if src_col in target_to_rule:
                provider = target_to_rule[src_col]
                if provider.rule.name != r.rule.name:
                    in_degree[r.rule.name] += 1
                    dependents[provider.rule.name].append(r)

    # Kahn's algorithm
    queue = [r for r in rules if in_degree[r.rule.name] == 0]
    # Sort by priority descending within same level for determinism
    queue.sort(key=lambda r: -r.rule.priority)
    result: list[_ResolvedRule] = []

    while queue:
        current = queue.pop(0)
        result.append(current)
        for dep in dependents[current.rule.name]:
            in_degree[dep.rule.name] -= 1
            if in_degree[dep.rule.name] == 0:
                queue.append(dep)
        queue.sort(key=lambda r: -r.rule.priority)

    if len(result) != len(rules):
        cycle_members = [r.rule.name for r in rules if in_degree[r.rule.name] > 0]
        raise CyclicDependencyError(
            f"Cyclic dependency among rules: {cycle_members}"
        )

    return result


@dataclass
class _ResolvedRule:
    """A rule bound to specific source/target columns in a table."""

    rule: DerivationRule
    source_cols: list[str]
    target_col: str


# ── Built-in Derivation Functions ─────────────────────────────

def _derive_email_from_name(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive email address from name fields."""
    # Try full_name first, then first_name + last_name
    full_name = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            key_lower = key.lower()
            if "full" in key_lower or key_lower == "name":
                full_name = val
                break
    if not full_name:
        first = ""
        last = ""
        for key, val in sources.items():
            if val and isinstance(val, str):
                key_lower = key.lower()
                if "first" in key_lower:
                    first = val
                elif "last" in key_lower or "surname" in key_lower:
                    last = val
        if first or last:
            full_name = f"{first} {last}".strip()

    if not full_name:
        return None

    # Deterministic email derivation
    parts = full_name.lower().split()
    parts = [re.sub(r"[^a-z]", "", p) for p in parts if p]
    if not parts:
        return None

    domain = ctx.get("domain", "general")
    domains_map = {
        "insurance": ["sunlife.com", "manulife.com", "aetna.com", "cigna.com"],
        "banking": ["bank.com", "finance.net", "capital.io", "invest.com"],
        "healthcare": ["hospital.org", "medcenter.com", "clinic.net", "health.io"],
        "hr": ["company.com", "corp.net", "internal.org", "enterprise.io"],
        "ecommerce": ["shop.com", "store.net", "market.io", "retail.com"],
    }
    email_domains = domains_map.get(domain, ["example.com", "company.com", "corp.net"])

    # Deterministic domain selection based on row index
    email_domain = email_domains[row_idx % len(email_domains)]

    if len(parts) >= 2:
        local = f"{parts[0]}.{parts[-1]}"
    else:
        local = parts[0]

    # Add numeric suffix for uniqueness based on row_idx
    if row_idx > 0:
        # Use hash for determinism without sequential patterns
        h = int(hashlib.md5(f"{full_name}:{row_idx}".encode()).hexdigest()[:4], 16) % 100
        if h > 50:
            local = f"{local}{row_idx}"

    return f"{local}@{email_domain}"


def _derive_phone_code_from_country(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive phone country code from country field."""
    country = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            country = val.strip().lower()
            break

    if not country:
        return None

    code = _COUNTRY_PHONE_CODES.get(country)
    if code:
        return code

    # Try partial match
    for c, code in _COUNTRY_PHONE_CODES.items():
        if c in country or country in c:
            return code

    return "+1"  # Default fallback


def _derive_rejection_reason_from_status(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive rejection_reason based on claim/application status."""
    status = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            status = val.strip().lower()
            break

    if not status:
        return None

    # Only provide rejection reason for negative statuses
    negative_statuses = {"rejected", "denied", "declined", "refused", "cancelled", "failed", "closed_denied"}
    if status not in negative_statuses:
        return None

    domain = ctx.get("domain", "general")
    reasons = _REJECTION_REASONS.get(domain, _REJECTION_REASONS["general"])
    # Deterministic selection based on row index
    return reasons[row_idx % len(reasons)]


def _derive_comments_from_status(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive contextual comments based on workflow status."""
    status = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            status = val.strip().lower()
            break

    if not status:
        return None

    category = _classify_status(status)
    domain = ctx.get("domain", "general")
    templates = _COMMENT_TEMPLATES.get(category, _COMMENT_TEMPLATES["neutral"])
    domain_templates = _DOMAIN_COMMENT_TEMPLATES.get(domain, {}).get(category, [])

    pool = templates + domain_templates if domain_templates else templates
    return pool[row_idx % len(pool)]


def _derive_approval_date_from_status(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive approval/completion date — only set for terminal positive states."""
    status = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            status = val.strip().lower()
            break

    if not status:
        return None

    positive_terminal = {"approved", "completed", "resolved", "paid", "settled", "closed_approved", "accepted"}
    if status not in positive_terminal:
        return None

    from datetime import date, timedelta
    base = date(2024, 1, 1)
    offset = (row_idx * 7 + 3) % 365
    return (base + timedelta(days=offset)).isoformat()


def _derive_active_flag_from_status(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive is_active boolean from status."""
    status = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            status = val.strip().lower()
            break

    if not status:
        return None

    terminal_states = {
        "closed", "completed", "resolved", "cancelled", "rejected",
        "denied", "expired", "archived", "terminated", "settled",
    }
    return status not in terminal_states


def _derive_currency_from_country(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive currency code from country."""
    country = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            country = val.strip().lower()
            break

    if not country:
        return None

    currency = _COUNTRY_CURRENCIES.get(country)
    if currency:
        return currency

    for c, cur in _COUNTRY_CURRENCIES.items():
        if c in country or country in c:
            return cur

    return "USD"


def _derive_username_from_name(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive username from name fields."""
    full_name = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            key_lower = key.lower()
            if "full" in key_lower or key_lower == "name" or "first" in key_lower:
                full_name = val
                break

    if not full_name:
        return None

    parts = full_name.lower().split()
    parts = [re.sub(r"[^a-z]", "", p) for p in parts if p]
    if not parts:
        return None

    if len(parts) >= 2:
        username = f"{parts[0][0]}{parts[-1]}"
    else:
        username = parts[0]

    # Deterministic suffix
    if row_idx > 0:
        h = int(hashlib.md5(f"{full_name}:{row_idx}".encode()).hexdigest()[:3], 16) % 99
        if h > 30:
            username = f"{username}{h}"

    return username


def _derive_display_name_from_name(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive display_name from first/last name."""
    first = ""
    last = ""
    full = ""
    for key, val in sources.items():
        if val and isinstance(val, str):
            key_lower = key.lower()
            if "first" in key_lower:
                first = val
            elif "last" in key_lower or "surname" in key_lower:
                last = val
            elif "full" in key_lower or key_lower == "name":
                full = val

    if full:
        return full
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    return None


def _derive_state_from_country(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive state/province from country."""
    country = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            country = val.strip().lower()
            break

    if not country:
        return None

    states = _COUNTRY_STATES.get(country)
    if not states:
        for c, s in _COUNTRY_STATES.items():
            if c in country or country in c:
                states = s
                break

    if not states:
        return None

    return states[row_idx % len(states)]


def _derive_postal_format_from_country(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive postal/zip code format from country."""
    country = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            country = val.strip().lower()
            break

    if not country:
        return None

    fmt = _COUNTRY_POSTAL_FORMATS.get(country)
    if not fmt:
        for c, f in _COUNTRY_POSTAL_FORMATS.items():
            if c in country or country in c:
                fmt = f
                break

    if not fmt:
        fmt = "zip_us"

    return _generate_postal_code(fmt, row_idx)


def _derive_error_message_from_status(sources: dict[str, Any], row_idx: int, ctx: dict) -> Any:
    """Derive error/failure message from error status."""
    status = None
    for key, val in sources.items():
        if val and isinstance(val, str):
            status = val.strip().lower()
            break

    if not status:
        return None

    error_statuses = {"failed", "error", "timeout", "crashed", "aborted", "exception"}
    if status not in error_statuses:
        return None

    messages = [
        "Connection timeout after 30s",
        "Invalid input parameters",
        "Service unavailable - retry later",
        "Authentication token expired",
        "Resource not found",
        "Rate limit exceeded",
        "Internal server error",
        "Database connection pool exhausted",
        "Payload too large",
        "Validation failed: missing required fields",
    ]
    return messages[row_idx % len(messages)]


# ── Validation Functions ──────────────────────────────────────

def _validate_email(value: Any, sources: dict[str, Any], ctx: dict) -> bool:
    """Validate derived email has proper format."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return "@" in value and "." in value.split("@")[-1]


def _validate_phone_code(value: Any, sources: dict[str, Any], ctx: dict) -> bool:
    """Validate phone code starts with +."""
    if value is None:
        return True
    return isinstance(value, str) and value.startswith("+")


def _validate_not_empty_string(value: Any, sources: dict[str, Any], ctx: dict) -> bool:
    """Validate value is None or a non-empty string."""
    if value is None:
        return True
    return isinstance(value, str) and len(value.strip()) > 0


def _validate_iso_date(value: Any, sources: dict[str, Any], ctx: dict) -> bool:
    """Validate ISO date format."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        from datetime import date as d
        d.fromisoformat(value)
        return True
    except ValueError:
        return False


def _validate_boolean(value: Any, sources: dict[str, Any], ctx: dict) -> bool:
    """Validate boolean value."""
    if value is None:
        return True
    return isinstance(value, bool)


# ── Lookup Tables ─────────────────────────────────────────────

_COUNTRY_PHONE_CODES: dict[str, str] = {
    "united states": "+1", "usa": "+1", "us": "+1",
    "canada": "+1", "ca": "+1",
    "united kingdom": "+44", "uk": "+44",
    "india": "+91", "in": "+91",
    "australia": "+61", "au": "+61",
    "germany": "+49", "de": "+49",
    "france": "+33", "fr": "+33",
    "japan": "+81", "jp": "+81",
    "china": "+86", "cn": "+86",
    "brazil": "+55", "br": "+55",
    "mexico": "+52", "mx": "+52",
    "singapore": "+65", "sg": "+65",
    "south korea": "+82", "kr": "+82",
    "italy": "+39", "it": "+39",
    "spain": "+34", "es": "+34",
    "netherlands": "+31", "nl": "+31",
    "sweden": "+46", "se": "+46",
    "switzerland": "+41", "ch": "+41",
    "ireland": "+353", "ie": "+353",
    "new zealand": "+64", "nz": "+64",
    "south africa": "+27", "za": "+27",
    "uae": "+971", "united arab emirates": "+971",
    "saudi arabia": "+966", "sa": "+966",
    "philippines": "+63", "ph": "+63",
    "indonesia": "+62", "id": "+62",
    "thailand": "+66", "th": "+66",
    "malaysia": "+60", "my": "+60",
    "pakistan": "+92", "pk": "+92",
    "nigeria": "+234", "ng": "+234",
    "egypt": "+20", "eg": "+20",
    "argentina": "+54", "ar": "+54",
    "colombia": "+57", "co": "+57",
    "poland": "+48", "pl": "+48",
    "turkey": "+90", "tr": "+90",
    "israel": "+972", "il": "+972",
    "portugal": "+351", "pt": "+351",
    "hong kong": "+852", "hk": "+852",
}

_COUNTRY_CURRENCIES: dict[str, str] = {
    "united states": "USD", "usa": "USD", "us": "USD",
    "canada": "CAD", "ca": "CAD",
    "united kingdom": "GBP", "uk": "GBP",
    "india": "INR", "in": "INR",
    "australia": "AUD", "au": "AUD",
    "germany": "EUR", "de": "EUR",
    "france": "EUR", "fr": "EUR",
    "japan": "JPY", "jp": "JPY",
    "china": "CNY", "cn": "CNY",
    "brazil": "BRL", "br": "BRL",
    "mexico": "MXN", "mx": "MXN",
    "singapore": "SGD", "sg": "SGD",
    "south korea": "KRW", "kr": "KRW",
    "italy": "EUR", "it": "EUR",
    "spain": "EUR", "es": "EUR",
    "netherlands": "EUR", "nl": "EUR",
    "sweden": "SEK", "se": "SEK",
    "switzerland": "CHF", "ch": "CHF",
    "ireland": "EUR", "ie": "EUR",
    "new zealand": "NZD", "nz": "NZD",
    "south africa": "ZAR", "za": "ZAR",
    "uae": "AED", "united arab emirates": "AED",
    "saudi arabia": "SAR", "sa": "SAR",
    "philippines": "PHP", "ph": "PHP",
    "indonesia": "IDR", "id": "IDR",
    "thailand": "THB", "th": "THB",
    "malaysia": "MYR", "my": "MYR",
    "pakistan": "PKR", "pk": "PKR",
    "nigeria": "NGN", "ng": "NGN",
    "egypt": "EGP", "eg": "EGP",
    "hong kong": "HKD", "hk": "HKD",
    "poland": "PLN", "pl": "PLN",
    "turkey": "TRY", "tr": "TRY",
    "israel": "ILS", "il": "ILS",
    "portugal": "EUR", "pt": "EUR",
}

_COUNTRY_STATES: dict[str, list[str]] = {
    "united states": ["California", "Texas", "New York", "Florida", "Illinois", "Pennsylvania", "Ohio", "Georgia", "Washington", "Massachusetts"],
    "usa": ["California", "Texas", "New York", "Florida", "Illinois", "Pennsylvania", "Ohio", "Georgia", "Washington", "Massachusetts"],
    "canada": ["Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba", "Saskatchewan", "Nova Scotia", "New Brunswick"],
    "india": ["Maharashtra", "Karnataka", "Tamil Nadu", "Delhi", "Uttar Pradesh", "Telangana", "Gujarat", "West Bengal"],
    "united kingdom": ["England", "Scotland", "Wales", "Northern Ireland"],
    "australia": ["New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia", "Tasmania"],
    "germany": ["Bavaria", "North Rhine-Westphalia", "Baden-Württemberg", "Lower Saxony", "Hesse", "Saxony"],
}

_COUNTRY_POSTAL_FORMATS: dict[str, str] = {
    "united states": "zip_us", "usa": "zip_us", "us": "zip_us",
    "canada": "postal_ca", "ca": "postal_ca",
    "united kingdom": "postcode_uk", "uk": "postcode_uk",
    "india": "pincode_in", "in": "pincode_in",
    "australia": "postcode_au", "au": "postcode_au",
    "germany": "plz_de", "de": "plz_de",
    "japan": "postal_jp", "jp": "postal_jp",
}

_REJECTION_REASONS: dict[str, list[str]] = {
    "insurance": [
        "Insufficient documentation provided",
        "Pre-existing condition not covered under current policy",
        "Claim amount exceeds policy coverage limits",
        "Policy was not active at time of incident",
        "Duplicate claim submission detected",
        "Incident occurred outside coverage territory",
        "Waiting period has not been satisfied",
        "Required medical examination not completed",
        "Fraudulent activity suspected — referred to investigation",
        "Service provider not within approved network",
    ],
    "banking": [
        "Insufficient funds in account",
        "Credit score below minimum threshold",
        "Employment verification failed",
        "Income below required minimum",
        "Excessive existing debt obligations",
        "Identity verification documents expired",
        "Account in default status",
        "Collateral valuation insufficient",
        "Application incomplete — missing required fields",
        "Risk assessment flag — unusual activity pattern",
    ],
    "healthcare": [
        "Treatment not medically necessary per guidelines",
        "Prior authorization not obtained",
        "Provider not in network",
        "Service not covered under current plan",
        "Maximum benefit limit reached",
        "Incorrect procedure code submitted",
        "Patient eligibility expired",
        "Duplicate claim for same service date",
    ],
    "general": [
        "Request does not meet eligibility criteria",
        "Required documentation incomplete",
        "Submission deadline has passed",
        "Duplicate request detected",
        "Does not comply with current policy terms",
        "Verification process failed",
        "Budget allocation exhausted for this period",
        "Approval authority threshold exceeded",
    ],
}

_COMMENT_TEMPLATES: dict[str, list[str]] = {
    "positive": [
        "Request processed successfully. All criteria met.",
        "Approved after thorough review. Documentation complete.",
        "All validations passed. Forwarded for final processing.",
        "Meets all requirements. Expedited for completion.",
        "Review complete. No issues identified.",
    ],
    "negative": [
        "Unable to process due to incomplete information.",
        "Declined per policy guidelines. See rejection reason.",
        "Does not meet minimum eligibility requirements.",
        "Review identified discrepancies. Request returned.",
        "Cannot proceed — blocking issues identified.",
    ],
    "waiting": [
        "Awaiting additional documentation from applicant.",
        "Pending supervisor review and approval.",
        "On hold — waiting for third-party verification.",
        "Queued for processing. Current wait time: 3-5 business days.",
        "Under review — additional information requested.",
    ],
    "neutral": [
        "Standard processing applied.",
        "Routed to appropriate department.",
        "Logged for audit trail.",
        "No action required at this time.",
        "Routine update recorded.",
    ],
}

_DOMAIN_COMMENT_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "insurance": {
        "positive": [
            "Claim approved. Payment will be issued within 5 business days.",
            "Coverage confirmed. Benefit amount calculated per schedule.",
            "Adjudication complete. Claimant notified of approval.",
        ],
        "negative": [
            "Claim denied. Insured may appeal within 60 days.",
            "Coverage determination: not eligible under current terms.",
            "Adjudication result: insufficient evidence of covered loss.",
        ],
        "waiting": [
            "Awaiting loss adjuster report.",
            "Pending medical records from attending physician.",
            "Under investigation — special investigations unit involved.",
        ],
    },
    "banking": {
        "positive": [
            "Transaction approved. Funds available immediately.",
            "Loan application approved. Disbursement scheduled.",
            "Account verification successful. Access granted.",
        ],
        "negative": [
            "Transaction declined. Insufficient balance.",
            "Application rejected due to credit assessment.",
            "Security flag raised — account temporarily restricted.",
        ],
        "waiting": [
            "Pending compliance review.",
            "Awaiting signoff from credit committee.",
            "Document verification in progress.",
        ],
    },
    "healthcare": {
        "positive": [
            "Authorization granted. Proceed with scheduled treatment.",
            "Claim processed. Patient responsibility: co-pay only.",
            "Referral approved. Specialist visit authorized.",
        ],
        "negative": [
            "Pre-authorization denied. Alternative treatment recommended.",
            "Claim rejected: service not covered under plan.",
            "Referral denied: does not meet clinical criteria.",
        ],
        "waiting": [
            "Pending clinical review by medical director.",
            "Awaiting lab results for determination.",
            "Under utilization review.",
        ],
    },
}


def _classify_status(status: str) -> str:
    """Classify a status string into a sentiment category."""
    status_lower = status.lower().strip()
    positive = {"approved", "completed", "resolved", "paid", "settled", "accepted", "active", "passed", "success", "done"}
    negative = {"rejected", "denied", "declined", "failed", "cancelled", "refused", "closed_denied", "error", "aborted"}
    waiting = {"pending", "in_review", "under_review", "processing", "queued", "submitted", "waiting", "on_hold", "open"}

    if status_lower in positive:
        return "positive"
    if status_lower in negative:
        return "negative"
    if status_lower in waiting:
        return "waiting"
    return "neutral"


def _generate_postal_code(fmt: str, row_idx: int) -> str:
    """Generate a deterministic postal code in the given format."""
    seed = row_idx * 31 + 7
    if fmt == "zip_us":
        return f"{(seed % 90000) + 10000}"
    elif fmt == "postal_ca":
        letters = "ABCEGHJKLMNPRSTVXY"
        l1 = letters[seed % len(letters)]
        l2 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(seed * 3) % 26]
        l3 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(seed * 7) % 26]
        d1 = (seed * 2) % 10
        d2 = (seed * 5) % 10
        d3 = (seed * 11) % 10
        return f"{l1}{d1}{l2} {d2}{l3}{d3}"
    elif fmt == "postcode_uk":
        area = "ABCDEFGHIJKLMNOPRSTUWYZ"[seed % 23]
        district = (seed * 3) % 30 + 1
        sector = seed % 10
        unit = "ABDEFGHJLNPQRSTUWXYZ"[(seed * 7) % 20] + "ABDEFGHJLNPQRSTUWXYZ"[(seed * 13) % 20]
        return f"{area}{district} {sector}{unit}"
    elif fmt == "pincode_in":
        return f"{(seed % 800000) + 100000}"
    elif fmt == "postcode_au":
        return f"{(seed % 9000) + 1000}"
    elif fmt == "plz_de":
        return f"{(seed % 90000) + 10000:05d}"
    elif fmt == "postal_jp":
        return f"{(seed % 900) + 100}-{(seed * 7) % 9000 + 1000}"
    return f"{(seed % 90000) + 10000}"


# ── Built-in Rule Registry ────────────────────────────────────

_BUILTIN_RULES: list[DerivationRule] = [
    # Name → Email
    DerivationRule(
        name="name_to_email",
        source_patterns=[re.compile(r"full_name|^name$|first_name|last_name", re.I)],
        target_pattern=re.compile(r"^email$|^e_mail$|email_address", re.I),
        derive_fn=_derive_email_from_name,
        priority=80,
        validate_fn=_validate_email,
        description="Derives email address from person name fields",
    ),
    # Name → Username
    DerivationRule(
        name="name_to_username",
        source_patterns=[re.compile(r"full_name|^name$|first_name", re.I)],
        target_pattern=re.compile(r"username|user_name|login_name|login_id", re.I),
        derive_fn=_derive_username_from_name,
        priority=75,
        validate_fn=_validate_not_empty_string,
        description="Derives username from person name",
    ),
    # First/Last Name → Display Name
    DerivationRule(
        name="name_to_display_name",
        source_patterns=[re.compile(r"first_name|last_name|full_name|^name$", re.I)],
        target_pattern=re.compile(r"display_name|displayname|screen_name", re.I),
        derive_fn=_derive_display_name_from_name,
        priority=70,
        validate_fn=_validate_not_empty_string,
        description="Derives display name from name components",
    ),
    # Country → Phone Code
    DerivationRule(
        name="country_to_phone_code",
        source_patterns=[re.compile(r"country|nation", re.I)],
        target_pattern=re.compile(r"phone_code|country_code|dial_code|calling_code", re.I),
        derive_fn=_derive_phone_code_from_country,
        priority=85,
        validate_fn=_validate_phone_code,
        description="Derives phone country code from country name",
    ),
    # Country → Currency
    DerivationRule(
        name="country_to_currency",
        source_patterns=[re.compile(r"country|nation", re.I)],
        target_pattern=re.compile(r"^currency$|currency_code|^ccy$", re.I),
        derive_fn=_derive_currency_from_country,
        priority=82,
        validate_fn=_validate_not_empty_string,
        description="Derives currency code from country",
    ),
    # Country → State/Province
    DerivationRule(
        name="country_to_state",
        source_patterns=[re.compile(r"country|nation", re.I)],
        target_pattern=re.compile(r"^state$|province|^region$", re.I),
        derive_fn=_derive_state_from_country,
        priority=78,
        description="Derives state/province from country",
    ),
    # Country → Postal Code Format
    DerivationRule(
        name="country_to_postal",
        source_patterns=[re.compile(r"country|nation", re.I)],
        target_pattern=re.compile(r"postal_code|zip_code|zip|postcode|pincode", re.I),
        derive_fn=_derive_postal_format_from_country,
        priority=76,
        description="Derives postal/zip code in country-appropriate format",
    ),
    # Status → Rejection Reason
    DerivationRule(
        name="status_to_rejection_reason",
        source_patterns=[re.compile(r"status|decision|verdict|outcome|claim_status", re.I)],
        target_pattern=re.compile(r"rejection_reason|deny_reason|decline_reason|denial_reason|reject_reason", re.I),
        derive_fn=_derive_rejection_reason_from_status,
        priority=90,
        validate_fn=_validate_not_empty_string,
        description="Derives rejection reason from negative status values",
    ),
    # Status → Comments
    DerivationRule(
        name="status_to_comments",
        source_patterns=[re.compile(r"status|decision|state|outcome", re.I)],
        target_pattern=re.compile(r"^comments?$|^notes?$|^remarks?$|observation", re.I),
        derive_fn=_derive_comments_from_status,
        priority=60,
        validate_fn=_validate_not_empty_string,
        description="Derives contextual comments from workflow status",
    ),
    # Status → Approval Date
    DerivationRule(
        name="status_to_approval_date",
        source_patterns=[re.compile(r"status|decision|outcome", re.I)],
        target_pattern=re.compile(r"approval_date|approved_at|completion_date|resolved_date", re.I),
        derive_fn=_derive_approval_date_from_status,
        priority=72,
        validate_fn=_validate_iso_date,
        description="Derives approval/completion date only for positive terminal statuses",
    ),
    # Status → Active Flag
    DerivationRule(
        name="status_to_active_flag",
        source_patterns=[re.compile(r"status|state|decision", re.I)],
        target_pattern=re.compile(r"is_active|active_flag|^active$", re.I),
        derive_fn=_derive_active_flag_from_status,
        priority=88,
        validate_fn=_validate_boolean,
        description="Derives is_active flag from status (false for terminal states)",
    ),
    # Status → Error Message
    DerivationRule(
        name="status_to_error_message",
        source_patterns=[re.compile(r"status|state|outcome", re.I)],
        target_pattern=re.compile(r"error_message|failure_reason|error_detail|fail_reason", re.I),
        derive_fn=_derive_error_message_from_status,
        priority=85,
        validate_fn=_validate_not_empty_string,
        description="Derives error/failure message for error statuses",
        domains=["devops", "ecommerce", "general"],
    ),
]


# ── Derivation Engine ─────────────────────────────────────────

class DerivationEngine:
    """Orchestrates derivation rule execution with conflict resolution."""

    def __init__(self, rules: list[DerivationRule] | None = None):
        self._rules = rules if rules is not None else list(_BUILTIN_RULES)
        self._custom_rules: list[DerivationRule] = []

    @property
    def rules(self) -> list[DerivationRule]:
        return self._rules + self._custom_rules

    def register_rule(self, rule: DerivationRule) -> None:
        """Register a custom derivation rule."""
        self._custom_rules.append(rule)

    def deregister_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found and removed."""
        for i, r in enumerate(self._custom_rules):
            if r.name == name:
                self._custom_rules.pop(i)
                return True
        for i, r in enumerate(self._rules):
            if r.name == name:
                self._rules.pop(i)
                return True
        return False

    def list_rules(self, domain: str | None = None) -> list[dict[str, Any]]:
        """List all registered rules, optionally filtered by domain."""
        result = []
        for r in self.rules:
            if domain and not r.applies_to_domain(domain):
                continue
            result.append({
                "name": r.name,
                "description": r.description,
                "priority": r.priority,
                "domains": r.domains,
                "source_patterns": [p.pattern for p in r.source_patterns],
                "target_pattern": r.target_pattern.pattern,
            })
        return sorted(result, key=lambda x: -x["priority"])

    def resolve_columns(
        self,
        table_name: str,
        column_names: list[str],
        n: int,
        *,
        domain: str | None = None,
        existing_values: dict[str, list[Any]] | None = None,
        check_constraints: dict[str, str] | None = None,
    ) -> DerivationResult:
        """Resolve derived columns for a table.

        Args:
            table_name: Name of the table being generated
            column_names: All column names in the table
            n: Number of rows to generate
            domain: Business domain for rule filtering
            existing_values: Pre-generated column values (from higher-priority engines)
            check_constraints: CHECK constraint expressions per column

        Returns:
            DerivationResult with derived column values and metadata
        """
        # Use a local copy so callers' dicts are not mutated by chaining
        existing = dict(existing_values) if existing_values else {}
        constraints = check_constraints or {}

        # Phase 1: Match rules to actual columns
        resolved_rules = self._match_rules_to_columns(column_names, domain)

        # Phase 2: Conflict resolution — if multiple rules target the same column,
        # highest priority wins
        resolved_rules, conflicts = self._resolve_conflicts(resolved_rules)

        # Phase 3: Filter out columns already provided by higher-priority engines
        resolved_rules = [
            r for r in resolved_rules if r.target_col not in existing
        ]

        # Phase 4: Topological sort for dependency chaining
        try:
            sorted_rules = _topological_sort(resolved_rules)
        except CyclicDependencyError:
            # Fall back to priority-based ordering if cycles exist
            sorted_rules = sorted(resolved_rules, key=lambda r: -r.rule.priority)

        # Phase 5: Execute rules in order
        derived: dict[str, list[Any]] = {}
        provenance: dict[str, str] = {}
        validation_failures: list[tuple[str, int, str]] = []
        execution_order: list[str] = []

        # Context available to all rules
        ctx: dict[str, Any] = {
            "domain": domain,
            "table_name": table_name,
            "column_names": column_names,
            "check_constraints": constraints,
        }

        for resolved in sorted_rules:
            rule = resolved.rule
            execution_order.append(rule.name)

            values: list[Any] = []
            for row_idx in range(n):
                # Gather source values for this row
                source_vals: dict[str, Any] = {}
                for src_col in resolved.source_cols:
                    if src_col in existing:
                        source_vals[src_col] = existing[src_col][row_idx]
                    elif src_col in derived:
                        source_vals[src_col] = derived[src_col][row_idx]
                    else:
                        source_vals[src_col] = None

                # Skip if all sources are None (nothing to derive from)
                if all(v is None for v in source_vals.values()):
                    values.append(None)
                    continue

                # Execute derivation
                value = rule.derive_fn(source_vals, row_idx, ctx)

                # Apply CHECK constraint validation
                if value is not None and resolved.target_col in constraints:
                    if not _check_constraint_allows(value, resolved.target_col, constraints[resolved.target_col]):
                        value = None

                # Validation hook
                if value is not None and rule.validate_fn:
                    if not rule.validate_fn(value, source_vals, ctx):
                        validation_failures.append((
                            rule.name, row_idx,
                            f"Validation failed for value '{value}'"
                        ))
                        value = None

                values.append(value)

            # Only include if at least some values were derived
            non_none_count = sum(1 for v in values if v is not None)
            if non_none_count > 0:
                derived[resolved.target_col] = values
                provenance[resolved.target_col] = rule.name
                # Make available for downstream chaining
                existing[resolved.target_col] = values

        return DerivationResult(
            derived_columns=derived,
            provenance=provenance,
            conflicts_resolved=conflicts,
            validation_failures=validation_failures,
            execution_order=execution_order,
        )

    def _match_rules_to_columns(
        self, column_names: list[str], domain: str | None
    ) -> list[_ResolvedRule]:
        """Match rules to actual columns present in the table."""
        resolved: list[_ResolvedRule] = []

        for rule in self.rules:
            if not rule.applies_to_domain(domain):
                continue

            # Find target column
            target_col: str | None = None
            for col in column_names:
                if rule.target_pattern.search(col):
                    target_col = col
                    break

            if not target_col:
                continue

            # Find source columns
            source_cols: list[str] = []
            for col in column_names:
                if col == target_col:
                    continue
                for src_pat in rule.source_patterns:
                    if src_pat.search(col):
                        source_cols.append(col)
                        break

            if not source_cols:
                continue

            resolved.append(_ResolvedRule(
                rule=rule,
                source_cols=source_cols,
                target_col=target_col,
            ))

        return resolved

    def _resolve_conflicts(
        self, rules: list[_ResolvedRule]
    ) -> tuple[list[_ResolvedRule], dict[str, list[tuple[str, int]]]]:
        """Resolve conflicts when multiple rules target the same column.

        Highest priority wins. Returns (winners, conflicts_dict).
        """
        # Group by target column
        by_target: dict[str, list[_ResolvedRule]] = {}
        for r in rules:
            by_target.setdefault(r.target_col, []).append(r)

        winners: list[_ResolvedRule] = []
        conflicts: dict[str, list[tuple[str, int]]] = {}

        for target_col, candidates in by_target.items():
            if len(candidates) == 1:
                winners.append(candidates[0])
            else:
                # Sort by priority descending
                candidates.sort(key=lambda r: -r.rule.priority)
                winners.append(candidates[0])
                # Record losers
                conflicts[target_col] = [
                    (c.rule.name, c.rule.priority) for c in candidates[1:]
                ]

        return winners, conflicts


def _check_constraint_allows(value: Any, col_name: str, constraint: str) -> bool:
    """Check if a derived value satisfies a CHECK constraint.

    Handles simple IN (...) constraints. Complex expressions pass through.
    """
    # Extract enum values from CHECK constraint
    match = re.search(
        r"(?:CHECK\s*\()?\s*\w+\s+IN\s*\(\s*(.+?)\s*\)",
        constraint,
        re.IGNORECASE,
    )
    if match:
        raw = match.group(1)
        allowed = [v.strip().strip("'\"") for v in raw.split(",")]
        return str(value) in allowed or value in allowed

    return True  # Allow if we can't parse the constraint


# ── Module-level singleton ────────────────────────────────────

_default_engine: DerivationEngine | None = None


def get_default_engine() -> DerivationEngine:
    """Get or create the default derivation engine instance."""
    global _default_engine
    if _default_engine is None:
        _default_engine = DerivationEngine()
    return _default_engine


# ── Public API ────────────────────────────────────────────────

def resolve_derived_columns(
    table_name: str,
    column_names: list[str],
    n: int,
    *,
    domain: str | None = None,
    existing_values: dict[str, list[Any]] | None = None,
    check_constraints: dict[str, str] | None = None,
) -> dict[str, list[Any]] | None:
    """Resolve derived columns for integration into the generation pipeline.

    Returns dict of column_name → list[values], or None if no derivations apply.
    This is the main entry point for the synthetic generator.
    """
    engine = get_default_engine()
    result = engine.resolve_columns(
        table_name=table_name,
        column_names=column_names,
        n=n,
        domain=domain,
        existing_values=existing_values,
        check_constraints=check_constraints,
    )

    if not result.derived_columns:
        return None

    return result.derived_columns


def get_derivation_report(
    table_name: str,
    column_names: list[str],
    n: int,
    *,
    domain: str | None = None,
    existing_values: dict[str, list[Any]] | None = None,
    check_constraints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Get full derivation report including provenance and conflicts.

    Used by the API endpoint for transparency.
    """
    engine = get_default_engine()
    result = engine.resolve_columns(
        table_name=table_name,
        column_names=column_names,
        n=n,
        domain=domain,
        existing_values=existing_values,
        check_constraints=check_constraints,
    )
    return result.to_dict()


def list_derivation_rules(domain: str | None = None) -> list[dict[str, Any]]:
    """List all available derivation rules."""
    engine = get_default_engine()
    return engine.list_rules(domain=domain)


def register_custom_derivation_rule(
    name: str,
    source_patterns: list[str],
    target_pattern: str,
    derive_fn: Callable[[dict[str, Any], int, dict[str, Any]], Any],
    *,
    priority: int = 50,
    domains: list[str] | None = None,
    validate_fn: Callable[[Any, dict[str, Any], dict[str, Any]], bool] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Register a custom derivation rule at runtime."""
    rule = DerivationRule(
        name=name,
        source_patterns=[re.compile(p, re.I) for p in source_patterns],
        target_pattern=re.compile(target_pattern, re.I),
        derive_fn=derive_fn,
        priority=priority,
        domains=domains,
        validate_fn=validate_fn,
        description=description,
    )
    engine = get_default_engine()
    engine.register_rule(rule)
    return {"name": name, "priority": priority, "description": description}
