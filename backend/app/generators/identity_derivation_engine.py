"""Identity Derivation Engine — derives coherent emails, usernames from names.

Given a person's name, produces realistic:
- Email addresses (corporate + personal) with configurable patterns
- Usernames (enterprise, social, shorthand styles)
- Locale-aware name handling (eastern order, transliteration)
- Batch mode with uniqueness guarantees
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


# ── Locale Configuration ──────────────────────────────────────

_LOCALE_ALIASES: dict[str, str] = {
    "us": "en_US", "usa": "en_US", "united states": "en_US",
    "uk": "en_GB", "united kingdom": "en_GB",
    "japan": "ja_JP", "jp": "ja_JP",
    "china": "zh_CN", "cn": "zh_CN",
    "korea": "ko_KR", "kr": "ko_KR",
    "germany": "de_DE", "de": "de_DE",
    "france": "fr_FR", "fr": "fr_FR",
    "india": "en_IN", "in": "en_IN",
}

_EASTERN_ORDER_LOCALES = {"ja_JP", "zh_CN", "ko_KR"}

_LOCALE_EMAIL_DOMAINS: dict[str, list[str]] = {
    "en_US": ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"],
    "en_GB": ["gmail.com", "yahoo.co.uk", "outlook.com", "btinternet.com"],
    "de_DE": ["gmail.com", "web.de", "gmx.de", "t-online.de", "outlook.de"],
    "fr_FR": ["gmail.com", "yahoo.fr", "outlook.fr", "orange.fr", "free.fr"],
    "ja_JP": ["gmail.com", "yahoo.co.jp", "outlook.jp", "docomo.ne.jp"],
    "zh_CN": ["gmail.com", "qq.com", "163.com", "126.com"],
    "ko_KR": ["gmail.com", "naver.com", "daum.net", "kakao.com"],
    "en_IN": ["gmail.com", "yahoo.co.in", "outlook.com", "rediffmail.com"],
}

_DEFAULT_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "protonmail.com"]

# ── Email/Username Patterns ───────────────────────────────────

_EMAIL_PATTERNS: list[dict[str, Any]] = [
    {"pattern": "first.last", "type": "corporate", "fn": lambda f, l, _: f"{f}.{l}"},
    {"pattern": "flast", "type": "corporate", "fn": lambda f, l, _: f"{f[0]}{l}"},
    {"pattern": "firstl", "type": "corporate", "fn": lambda f, l, _: f"{f}{l[0]}"},
    {"pattern": "first_last", "type": "corporate", "fn": lambda f, l, _: f"{f}_{l}"},
    {"pattern": "last.first", "type": "corporate", "fn": lambda f, l, _: f"{l}.{f}"},
    {"pattern": "first", "type": "personal", "fn": lambda f, l, r: f"{f}{r.randint(10, 99)}"},
    {"pattern": "first.last+digits", "type": "personal", "fn": lambda f, l, r: f"{f}.{l}{r.randint(1, 999)}"},
    {"pattern": "nickname", "type": "personal", "fn": lambda f, l, r: f"{f}{l[0]}{r.randint(100, 9999)}"},
]

_COMPANY_PATTERNS: dict[str, Any] = {
    "first.last": lambda f, l: f"{f}.{l}",
    "flast": lambda f, l: f"{f[0]}{l}",
    "firstl": lambda f, l: f"{f}{l[0]}",
    "first_last": lambda f, l: f"{f}_{l}",
    "last.first": lambda f, l: f"{l}.{f}",
    "lastf": lambda f, l: f"{l}{f[0]}",
}

_USERNAME_PATTERNS: list[dict[str, Any]] = [
    {"pattern": "first.last", "style": "enterprise", "fn": lambda f, l, _: f"{f}.{l}"},
    {"pattern": "flast", "style": "enterprise", "fn": lambda f, l, _: f"{f[0]}{l}"},
    {"pattern": "firstl", "style": "shorthand", "fn": lambda f, l, _: f"{f}{l[0]}"},
    {"pattern": "first_last", "style": "enterprise", "fn": lambda f, l, _: f"{f}_{l}"},
    {"pattern": "first+digits", "style": "social", "fn": lambda f, l, r: f"{f}{r.randint(10, 9999)}"},
    {"pattern": "f.last+digits", "style": "social", "fn": lambda f, l, r: f"{f[0]}.{l}{r.randint(1, 99)}"},
    {"pattern": "nickname", "style": "social", "fn": lambda f, l, r: f"{f}{l[:3]}{r.randint(1, 99)}"},
]


# ── Result Models ─────────────────────────────────────────────


@dataclass
class DerivedIdentity:
    """A single derived identity with emails and usernames."""
    first_name: str
    last_name: str
    full_name: str
    initials: str
    locale: str
    emails: list[dict[str, str]]
    usernames: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "initials": self.initials,
            "locale": self.locale,
            "emails": self.emails,
            "usernames": self.usernames,
        }


@dataclass
class IdentityDerivationResult:
    """Result from batch identity derivation."""
    total_derived: int
    identities: list[DerivedIdentity]
    patterns_used: list[str] = field(default_factory=list)
    company_domain: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_derived": self.total_derived,
            "identities": [i.to_dict() for i in self.identities],
            "patterns_used": self.patterns_used,
            "company_domain": self.company_domain,
        }


# ── Helpers ───────────────────────────────────────────────────

def _transliterate(text: str) -> str:
    """Remove accents/diacritics and transliterate to ASCII."""
    # Manual common substitutions first
    subs = {"ü": "ue", "ö": "oe", "ä": "ae", "ß": "ss", "ñ": "n"}
    for char, repl in subs.items():
        text = text.replace(char, repl)
        text = text.replace(char.upper(), repl.capitalize())
    # NFD decomposition to strip remaining combining marks
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _resolve_locale(locale: str | None) -> str:
    """Resolve a locale string to a standard code."""
    if not locale:
        return "en_US"
    locale = locale.strip().lower()
    if locale in _LOCALE_ALIASES:
        return _LOCALE_ALIASES[locale]
    # Already a full code
    if "_" in locale and len(locale) >= 4:
        return locale
    return "en_US"


def _parse_name(full_name: str | None, first_name: str | None, last_name: str | None, locale: str) -> tuple[str, str]:
    """Parse name into (first, last) respecting locale conventions."""
    if first_name is not None and last_name is not None:
        return first_name.strip(), last_name.strip()

    if full_name:
        parts = full_name.strip().split()
        if len(parts) == 1:
            return parts[0], ""
        if locale in _EASTERN_ORDER_LOCALES:
            # Eastern order: first token is family name
            return parts[-1], parts[0] if len(parts) == 2 else " ".join(parts[:-1])
        # Western order: last token is family name
        return parts[0], " ".join(parts[1:])

    return first_name or "", last_name or ""


# ── Engine ────────────────────────────────────────────────────


class IdentityDerivationEngine:
    """Derives emails and usernames from person names."""

    def __init__(
        self,
        locale: str | None = None,
        company_domain: str | None = None,
        company_pattern: str | None = None,
        seed: int | None = None,
    ) -> None:
        self._locale_code = _resolve_locale(locale)
        self._company_domain = company_domain
        self._company_pattern = company_pattern
        self._rng = random.Random(seed)
        self._used_emails: set[str] = set()
        self._used_usernames: set[str] = set()
        self._patterns_used: set[str] = set()

    def derive(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        full_name: str | None = None,
        num_emails: int = 3,
        num_usernames: int = 3,
    ) -> DerivedIdentity:
        """Derive a complete identity from name components."""
        first, last = _parse_name(full_name, first_name, last_name, self._locale_code)

        # Build full name respecting locale order
        if self._locale_code in _EASTERN_ORDER_LOCALES and first and last:
            display_full = f"{last} {first}"
        else:
            display_full = f"{first} {last}".strip()

        initials = ""
        if first:
            initials += first[0].upper()
        if last:
            initials += last[0].upper()

        # Transliterate for email/username generation
        first_ascii = _transliterate(first).lower().replace(" ", "")
        last_ascii = _transliterate(last).lower().replace(" ", "")

        # Guard against empty
        if not first_ascii:
            first_ascii = "user"
        if not last_ascii:
            last_ascii = first_ascii

        emails = self._generate_emails(first_ascii, last_ascii, num_emails)
        usernames = self._generate_usernames(first_ascii, last_ascii, num_usernames)

        return DerivedIdentity(
            first_name=first,
            last_name=last,
            full_name=display_full,
            initials=initials,
            locale=self._locale_code,
            emails=emails,
            usernames=usernames,
        )

    def derive_batch(
        self,
        names: list[dict[str, str]],
        num_emails: int = 3,
        num_usernames: int = 3,
    ) -> IdentityDerivationResult:
        """Derive identities for multiple names with uniqueness guarantees."""
        identities: list[DerivedIdentity] = []

        for name_entry in names:
            identity = self.derive(
                first_name=name_entry.get("first_name"),
                last_name=name_entry.get("last_name"),
                full_name=name_entry.get("full_name"),
                num_emails=num_emails,
                num_usernames=num_usernames,
            )
            identities.append(identity)

        return IdentityDerivationResult(
            total_derived=len(identities),
            identities=identities,
            patterns_used=sorted(self._patterns_used),
            company_domain=self._company_domain,
        )

    def _generate_emails(self, first: str, last: str, count: int) -> list[dict[str, str]]:
        """Generate email addresses."""
        emails: list[dict[str, str]] = []

        # Corporate email first if company_domain is set
        if self._company_domain:
            if self._company_pattern and self._company_pattern in _COMPANY_PATTERNS:
                local = _COMPANY_PATTERNS[self._company_pattern](first, last)
            else:
                local = f"{first}.{last}"
            email = f"{local}@{self._company_domain}"
            email = self._ensure_unique_email(email)
            emails.append({"email": email, "type": "corporate", "pattern": self._company_pattern or "first.last"})
            self._patterns_used.add(self._company_pattern or "first.last")

        # Fill remaining with patterns
        available_patterns = list(_EMAIL_PATTERNS)
        self._rng.shuffle(available_patterns)

        domains = _LOCALE_EMAIL_DOMAINS.get(self._locale_code, _DEFAULT_DOMAINS)

        for pat in available_patterns:
            if len(emails) >= count:
                break
            # Skip corporate patterns if we already have corporate
            if pat["type"] == "corporate" and any(e["type"] == "corporate" for e in emails):
                # Use as personal with personal domain
                local = pat["fn"](first, last, self._rng)
                domain = self._rng.choice(domains)
                email = f"{local}@{domain}"
                email = self._ensure_unique_email(email)
                emails.append({"email": email, "type": "personal", "pattern": pat["pattern"]})
            else:
                local = pat["fn"](first, last, self._rng)
                if pat["type"] == "corporate" and self._company_domain:
                    domain = self._company_domain
                else:
                    domain = self._rng.choice(domains)
                email = f"{local}@{domain}"
                email = self._ensure_unique_email(email)
                emails.append({"email": email, "type": pat["type"], "pattern": pat["pattern"]})
            self._patterns_used.add(pat["pattern"])

        return emails[:count]

    def _generate_usernames(self, first: str, last: str, count: int) -> list[dict[str, str]]:
        """Generate usernames."""
        usernames: list[dict[str, str]] = []

        available = list(_USERNAME_PATTERNS)
        self._rng.shuffle(available)

        for pat in available:
            if len(usernames) >= count:
                break
            username = pat["fn"](first, last, self._rng)
            username = self._ensure_unique_username(username)
            usernames.append({"username": username, "style": pat["style"], "pattern": pat["pattern"]})
            self._patterns_used.add(pat["pattern"])

        return usernames[:count]

    def _ensure_unique_email(self, email: str) -> str:
        """Ensure email is unique across this engine's lifetime."""
        base_email = email
        counter = 1
        while email in self._used_emails:
            local, domain = base_email.rsplit("@", 1)
            email = f"{local}{counter}@{domain}"
            counter += 1
        self._used_emails.add(email)
        return email

    def _ensure_unique_username(self, username: str) -> str:
        """Ensure username is unique."""
        base = username
        counter = 1
        while username in self._used_usernames:
            username = f"{base}{counter}"
            counter += 1
        self._used_usernames.add(username)
        return username
