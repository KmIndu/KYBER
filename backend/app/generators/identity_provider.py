"""Identity-consistent synthetic data generation.

Ensures that identity fields within the same row remain semantically linked:
- name = "John Doe" → email = "john.doe@gmail.com"
- username = "jdoe" → display_name = "John Doe"
- employee_id follows deterministic derivation from the identity

Supports:
- Name-aware email generation
- Username consistency (derived from name)
- Locale-aware formatting
- Deterministic derivation rules
- Domain-aware identity generation (corporate, consumer, healthcare, etc.)
"""

from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass, field
from typing import Any

from faker import Faker


# ── Locale configurations ────────────────────────────────────

_LOCALE_MAP: dict[str, str] = {
    "us": "en_US", "usa": "en_US", "united states": "en_US",
    "uk": "en_GB", "united kingdom": "en_GB",
    "in": "en_IN", "india": "en_IN",
    "ca": "en_CA", "canada": "en_CA",
    "au": "en_AU", "australia": "en_AU",
    "de": "de_DE", "germany": "de_DE",
    "fr": "fr_FR", "france": "fr_FR",
    "jp": "ja_JP", "japan": "ja_JP",
    "sg": "en_SG", "singapore": "en_SG",
}

# ── Email domain pools (by domain context) ───────────────────

_EMAIL_DOMAINS_CORPORATE = [
    "company.com", "corp.net", "enterprise.io", "internal.org",
    "acme.com", "globex.com", "initech.com", "hooli.net",
    "piedpiper.com", "wayneenterprises.com", "oscorp.net",
    "starkindustries.com", "umbrellagroup.com", "cyberdyne.io",
]

_EMAIL_DOMAINS_CONSUMER = [
    "gmail.com", "outlook.com", "yahoo.com", "hotmail.com",
    "protonmail.com", "icloud.com", "mail.com", "aol.com",
]

_EMAIL_DOMAINS_HEALTHCARE = [
    "hospital.org", "medcenter.com", "healthsys.net",
    "clinic.org", "medgroup.com", "healthcare.io",
]

_EMAIL_DOMAINS_INSURANCE = [
    "sunlife.com", "manulife.com", "insure.co", "protectlife.com",
    "lifeins.net", "coverageplus.com", "safetynet.io",
]

_DOMAIN_EMAIL_MAP: dict[str, list[str]] = {
    "insurance": _EMAIL_DOMAINS_INSURANCE + _EMAIL_DOMAINS_CORPORATE,
    "banking": _EMAIL_DOMAINS_CORPORATE,
    "healthcare": _EMAIL_DOMAINS_HEALTHCARE,
    "hr": _EMAIL_DOMAINS_CORPORATE,
    "retail": _EMAIL_DOMAINS_CONSUMER,
    "ecommerce": _EMAIL_DOMAINS_CONSUMER,
    "devops": _EMAIL_DOMAINS_CORPORATE,
}

# ── Username generation strategies ───────────────────────────

_USERNAME_STRATEGIES = [
    # first initial + last name: jdoe
    lambda f, l: f"{f[0]}{l}".lower(),
    # first.last: john.doe
    lambda f, l: f"{f}.{l}".lower(),
    # first + last initial: johnd
    lambda f, l: f"{f}{l[0]}".lower(),
    # first_last: john_doe
    lambda f, l: f"{f}_{l}".lower(),
    # first initial + last + digits: jdoe42
    lambda f, l: f"{f[0]}{l}{random.randint(1, 99)}".lower(),
]

# ── Employee ID patterns ─────────────────────────────────────

_EMPLOYEE_ID_PATTERNS: dict[str, str] = {
    "insurance": "EMP{:06d}",
    "banking": "BNK{:06d}",
    "healthcare": "HC{:06d}",
    "hr": "HR{:06d}",
    "devops": "DEV{:05d}",
    "retail": "RTL{:06d}",
    "unknown": "EMP{:06d}",
}

# ── Account ID patterns ──────────────────────────────────────

_ACCOUNT_ID_PATTERNS: dict[str, str] = {
    "insurance": "ACC-{:08d}",
    "banking": "ACT{:010d}",
    "healthcare": "PAT-{:07d}",
    "hr": "USR-{:06d}",
    "retail": "CUS{:09d}",
    "ecommerce": "UID-{:08d}",
    "unknown": "ACC-{:08d}",
}


@dataclass
class IdentityRecord:
    """A single coherent identity with all derived fields."""

    first_name: str
    last_name: str
    full_name: str
    email: str
    username: str
    display_name: str
    employee_id: str
    account_id: str
    alias: str
    initials: str


@dataclass
class IdentityPool:
    """Pre-generated pool of identity records for a table."""

    records: list[IdentityRecord] = field(default_factory=list)

    def get(self, index: int) -> IdentityRecord:
        """Get an identity record by index (wraps around)."""
        return self.records[index % len(self.records)]


class IdentityProvider:
    """Generates coherent identity records where all fields are semantically linked.

    Usage:
        provider = IdentityProvider(country="us", domain="insurance")
        pool = provider.generate_pool(100)
        # All fields in pool.get(0) are linked to same person
    """

    def __init__(
        self,
        country: str = "us",
        domain: str = "unknown",
    ) -> None:
        self._country = country.lower().strip()
        self._domain = domain.lower().strip()
        locale = _LOCALE_MAP.get(self._country, "en_US")
        self._faker = Faker(locale)
        self._email_domains = _DOMAIN_EMAIL_MAP.get(self._domain, _EMAIL_DOMAINS_CONSUMER)
        self._emp_pattern = _EMPLOYEE_ID_PATTERNS.get(self._domain, _EMPLOYEE_ID_PATTERNS["unknown"])
        self._acct_pattern = _ACCOUNT_ID_PATTERNS.get(self._domain, _ACCOUNT_ID_PATTERNS["unknown"])
        self._used_usernames: set[str] = set()
        self._used_emails: set[str] = set()
        self._used_emp_ids: set[str] = set()
        self._used_acct_ids: set[str] = set()

    def generate_pool(self, n: int) -> IdentityPool:
        """Generate n coherent identity records."""
        records: list[IdentityRecord] = []
        for i in range(n):
            records.append(self._generate_one(i))
        return IdentityPool(records=records)

    def _generate_one(self, index: int) -> IdentityRecord:
        """Generate a single coherent identity record."""
        # Generate the base name (source of truth)
        first_name = self._faker.first_name()
        last_name = self._faker.last_name()

        # Clean for email/username safety
        first_clean = self._sanitize(first_name)
        last_clean = self._sanitize(last_name)

        # Full name
        full_name = f"{first_name} {last_name}"

        # Display name (may include title for corporate domains)
        display_name = self._derive_display_name(first_name, last_name)

        # Email — deterministically derived from name
        email = self._derive_email(first_clean, last_clean, index)

        # Username — deterministically derived from name
        username = self._derive_username(first_clean, last_clean, index)

        # Employee ID — deterministic from index
        employee_id = self._derive_employee_id(index)

        # Account ID — deterministic from index
        account_id = self._derive_account_id(index)

        # Alias — short form derived from name
        alias = self._derive_alias(first_clean, last_clean, index)

        # Initials
        initials = f"{first_name[0]}{last_name[0]}".upper()

        return IdentityRecord(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            email=email,
            username=username,
            display_name=display_name,
            employee_id=employee_id,
            account_id=account_id,
            alias=alias,
            initials=initials,
        )

    def _sanitize(self, name: str) -> str:
        """Remove non-ascii and special characters for email/username use."""
        return re.sub(r"[^a-zA-Z]", "", name).lower()

    def _derive_email(self, first: str, last: str, index: int) -> str:
        """Generate a name-consistent email address."""
        if not first or not last:
            first = first or "user"
            last = last or str(index)

        # Pick a deterministic strategy based on index
        strategies = [
            f"{first}.{last}",          # john.doe
            f"{first}{last}",           # johndoe
            f"{first[0]}{last}",        # jdoe
            f"{first}_{last}",          # john_doe
            f"{first}.{last[0]}",       # john.d
            f"{last}.{first}",          # doe.john
        ]

        base_email = strategies[index % len(strategies)]
        domain = self._email_domains[index % len(self._email_domains)]

        email = f"{base_email}@{domain}"

        # Ensure uniqueness
        if email in self._used_emails:
            email = f"{base_email}{index}@{domain}"
        attempts = 0
        while email in self._used_emails and attempts < 100:
            attempts += 1
            email = f"{base_email}{index + attempts}@{domain}"

        self._used_emails.add(email)
        return email

    def _derive_username(self, first: str, last: str, index: int) -> str:
        """Generate a name-consistent username."""
        if not first or not last:
            first = first or "user"
            last = last or str(index)

        strategy = _USERNAME_STRATEGIES[index % len(_USERNAME_STRATEGIES)]
        username = strategy(first, last)

        # Ensure uniqueness
        if username in self._used_usernames:
            username = f"{username}{index}"
        attempts = 0
        while username in self._used_usernames and attempts < 100:
            attempts += 1
            username = f"{strategy(first, last)}{index + attempts}"

        self._used_usernames.add(username)
        return username

    def _derive_display_name(self, first: str, last: str) -> str:
        """Generate a display name appropriate for the domain."""
        if self._domain in ("insurance", "banking", "healthcare"):
            # Formal: may include title
            titles = ["", "", "", "Dr. ", "Mr. ", "Ms. "]
            title = random.choice(titles)
            return f"{title}{first} {last}".strip()
        return f"{first} {last}"

    def _derive_employee_id(self, index: int) -> str:
        """Generate a deterministic employee ID from index."""
        emp_id = self._emp_pattern.format(index + 1001)
        self._used_emp_ids.add(emp_id)
        return emp_id

    def _derive_account_id(self, index: int) -> str:
        """Generate a deterministic account ID from index."""
        acct_id = self._acct_pattern.format(index + 10001)
        self._used_acct_ids.add(acct_id)
        return acct_id

    def _derive_alias(self, first: str, last: str, index: int) -> str:
        """Generate a short alias from name."""
        if not first or not last:
            return f"user{index}"
        patterns = [
            f"{first[0]}{last}",        # jdoe
            f"{first}{last[0]}",        # johnd
            f"{first[:3]}{last[:3]}",   # johdoe
            f"{first[0]}{last[0]}{index:02d}",  # jd01
        ]
        return patterns[index % len(patterns)]


# ── Column pattern matching ──────────────────────────────────
# Maps column name patterns to (identity_field, role)
# role: "primary" = the main subject, "secondary" = a different actor (reviewer, approver, etc.)

_IDENTITY_COLUMN_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # First/last name → primary identity
    (re.compile(r"first[_\s]?name|given[_\s]?name|fname", re.I), "first_name", "primary"),
    (re.compile(r"last[_\s]?name|surname|family[_\s]?name|lname", re.I), "last_name", "primary"),

    # Full name variants → primary identity
    (re.compile(r"full[_\s]?name|^name$|display[_\s]?name|customer[_\s]?name|patient[_\s]?name|"
                r"policyholder[_\s]?name|employee[_\s]?name|insured[_\s]?name|"
                r"payee[_\s]?name|beneficiary[_\s]?name|claimant[_\s]?name|"
                r"provider[_\s]?name|advisor[_\s]?name|adjuster[_\s]?name|"
                r"applicant[_\s]?name|recipient[_\s]?name|member[_\s]?name|"
                r"contact[_\s]?name|agent[_\s]?name|owner[_\s]?name|"
                r"requester[_\s]?name|assignee[_\s]?name", re.I), "full_name", "primary"),

    # Email → primary identity
    (re.compile(r"email|e[_\s]?mail|email[_\s]?address", re.I), "email", "primary"),

    # Username/login → primary identity
    (re.compile(r"user[_\s]?name|username|login[_\s]?name|login[_\s]?id|"
                r"user[_\s]?id$|login$", re.I), "username", "primary"),

    # *_by columns → secondary actors (different people)
    (re.compile(r"(created|updated|modified|requested|approved|reviewed|"
                r"assigned|processed|handled|verified|adjudicated)[_\s]?by$", re.I), "username", "secondary"),
    (re.compile(r"author|reviewer|approver", re.I), "username", "secondary"),

    # Assignee/reporter → secondary actors
    (re.compile(r"assignee|reporter|owner", re.I), "username", "secondary"),

    # Display name
    (re.compile(r"display[_\s]?name|screen[_\s]?name|preferred[_\s]?name|"
                r"nick[_\s]?name|alias[_\s]?name", re.I), "display_name", "primary"),

    # Employee ID
    (re.compile(r"employee[_\s]?(id|number|no|num|code)|emp[_\s]?(id|no|num|code)|"
                r"staff[_\s]?(id|number|no|num)", re.I), "employee_id", "primary"),

    # Account ID
    (re.compile(r"account[_\s]?id|acct[_\s]?id|user[_\s]?account[_\s]?id|"
                r"member[_\s]?id|customer[_\s]?id", re.I), "account_id", "primary"),

    # Alias
    (re.compile(r"^alias$|nick[_\s]?name|handle$|screen[_\s]?name", re.I), "alias", "primary"),

    # Initials
    (re.compile(r"initials$", re.I), "initials", "primary"),
]


def detect_identity_columns(column_names: list[str]) -> dict[str, tuple[str, str]]:
    """Detect which columns are identity-related and what field/role they map to.

    Args:
        column_names: List of column names in a table.

    Returns:
        Dict mapping column_name → (identity_field, role)
        where role is "primary" or "secondary"
    """
    matches: dict[str, tuple[str, str]] = {}
    for col_name in column_names:
        col_lower = col_name.lower().strip()
        for pattern, identity_field, role in _IDENTITY_COLUMN_PATTERNS:
            if pattern.search(col_lower):
                matches[col_name] = (identity_field, role)
                break
    return matches


def resolve_identity_columns(
    table_name: str,
    column_names: list[str],
    n: int,
    country: str = "us",
    domain: str = "unknown",
) -> dict[str, list[Any]] | None:
    """Resolve identity-linked column values for a table.

    Detects identity columns, generates a coherent pool of identities,
    and returns synchronized column values. Primary identity columns share
    one identity per row; secondary actors (reviewed_by, approver, etc.)
    get a separate identity pool to avoid the policyholder being their own reviewer.

    Args:
        table_name: Name of the table being generated.
        column_names: All column names in the table.
        n: Number of rows to generate.
        country: Country/locale for name formatting.
        domain: Business domain (insurance, banking, etc.)

    Returns:
        Dict mapping matched column_name → list of n values,
        or None if fewer than 2 identity columns detected
        (no cross-column consistency needed for a single column).
    """
    identity_cols = detect_identity_columns(column_names)

    # Need at least 2 identity columns to warrant consistency
    if len(identity_cols) < 2:
        return None

    # Split into primary and secondary groups
    primary_cols: dict[str, str] = {}
    secondary_cols: dict[str, str] = {}
    for col_name, (field_name, role) in identity_cols.items():
        if role == "primary":
            primary_cols[col_name] = field_name
        else:
            secondary_cols[col_name] = field_name

    # If only secondary columns (no primary subject), treat them all as primary
    if not primary_cols and secondary_cols:
        primary_cols = secondary_cols
        secondary_cols = {}

    # Generate the primary identity pool
    provider = IdentityProvider(country=country, domain=domain)
    primary_pool = provider.generate_pool(n)

    # Generate a SEPARATE pool for secondary actors
    secondary_pool: IdentityPool | None = None
    if secondary_cols:
        secondary_provider = IdentityProvider(country=country, domain=domain)
        secondary_pool = secondary_provider.generate_pool(n)

    # Map each detected column to its identity field values
    result: dict[str, list[Any]] = {}

    for col_name, field_name in primary_cols.items():
        values: list[Any] = []
        for i in range(n):
            record = primary_pool.get(i)
            values.append(getattr(record, field_name))
        result[col_name] = values

    if secondary_pool:
        # Each secondary column gets a different shuffle offset so
        # reviewed_by and approved_by aren't always the same person
        offset = 0
        for col_name, field_name in secondary_cols.items():
            values = []
            for i in range(n):
                # Offset index so different secondary columns get different people
                record = secondary_pool.get(i + offset)
                values.append(getattr(record, field_name))
            result[col_name] = values
            offset += max(n // 3, 1)  # shift by ~1/3 of pool per column

    return result
