"""Tests for the realistic identity derivation engine.

Covers:
- Email derivation from names
- Username derivation from names
- Company email patterns
- Locale-aware formatting
- Eastern name ordering (Japanese, Chinese, Korean)
- Transliteration of accented characters
- Batch derivation with uniqueness
- Edge cases (empty names, single names)
- Router integration
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.generators.identity_derivation_engine import (
    DerivedIdentity,
    IdentityDerivationEngine,
    IdentityDerivationResult,
)
from app.main import app

client = TestClient(app)


# ── Basic Derivation Tests ────────────────────────────────────


class TestBasicDerivation:
    def test_derive_from_first_last(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="John", last_name="Doe")

        assert result.first_name == "John"
        assert result.last_name == "Doe"
        assert result.full_name == "John Doe"
        assert result.initials == "JD"
        assert len(result.emails) == 3
        assert len(result.usernames) == 3

    def test_derive_from_full_name(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(full_name="Jane Smith")

        assert result.first_name == "Jane"
        assert result.last_name == "Smith"
        assert result.full_name == "Jane Smith"

    def test_derive_from_multi_word_last_name(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(full_name="Mary Van Der Berg")

        assert result.first_name == "Mary"
        assert result.last_name == "Van Der Berg"


# ── Email Derivation Tests ────────────────────────────────────


class TestEmailDerivation:
    def test_emails_contain_name_components(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="John", last_name="Doe")

        all_emails = [e["email"] for e in result.emails]
        # At least one email should contain "john" and "doe"
        has_name_based = any(
            "john" in email.split("@")[0] or "doe" in email.split("@")[0]
            for email in all_emails
        )
        assert has_name_based, f"No name-based emails found in {all_emails}"

    def test_emails_have_valid_format(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Alice", last_name="Johnson")

        for entry in result.emails:
            email = entry["email"]
            assert "@" in email
            local, domain = email.split("@")
            assert "." in domain
            assert len(local) > 0

    def test_emails_have_type_field(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Bob", last_name="Smith")

        for entry in result.emails:
            assert entry["type"] in ("corporate", "personal")
            assert "pattern" in entry

    def test_email_count_configurable(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Test", last_name="User", num_emails=5)
        assert len(result.emails) == 5

        result2 = engine.derive(first_name="Test2", last_name="User2", num_emails=1)
        assert len(result2.emails) == 1


# ── Company Email Pattern Tests ───────────────────────────────


class TestCompanyEmailPatterns:
    def test_company_domain_used(self):
        engine = IdentityDerivationEngine(company_domain="sunlife.com", seed=42)
        result = engine.derive(first_name="John", last_name="Doe")

        corporate_emails = [e for e in result.emails if e["type"] == "corporate"]
        assert len(corporate_emails) >= 1
        assert all("sunlife.com" in e["email"] for e in corporate_emails)

    def test_forced_pattern_first_dot_last(self):
        engine = IdentityDerivationEngine(
            company_domain="company.com", company_pattern="first.last", seed=42,
        )
        result = engine.derive(first_name="John", last_name="Doe")

        corporate_emails = [e for e in result.emails if e["type"] == "corporate"]
        assert len(corporate_emails) >= 1
        assert corporate_emails[0]["email"] == "john.doe@company.com"

    def test_forced_pattern_flast(self):
        engine = IdentityDerivationEngine(
            company_domain="corp.net", company_pattern="flast", seed=42,
        )
        result = engine.derive(first_name="John", last_name="Doe")

        corporate_emails = [e for e in result.emails if e["type"] == "corporate"]
        assert len(corporate_emails) >= 1
        assert corporate_emails[0]["email"] == "jdoe@corp.net"

    def test_company_email_comes_first(self):
        engine = IdentityDerivationEngine(company_domain="acme.com", seed=42)
        result = engine.derive(first_name="Alice", last_name="Wonder")

        assert result.emails[0]["type"] == "corporate"
        assert "acme.com" in result.emails[0]["email"]


# ── Username Derivation Tests ─────────────────────────────────


class TestUsernamDerivation:
    def test_usernames_derived_from_name(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="John", last_name="Doe")

        all_usernames = [u["username"] for u in result.usernames]
        # At least one should contain part of the name
        has_name = any(
            "john" in u or "doe" in u or "jdoe" in u or "johnd" in u
            for u in all_usernames
        )
        assert has_name, f"No name-derived usernames in {all_usernames}"

    def test_usernames_have_style(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Bob", last_name="Builder")

        for entry in result.usernames:
            assert entry["style"] in ("enterprise", "social", "shorthand")
            assert "pattern" in entry

    def test_username_count_configurable(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Test", last_name="User", num_usernames=5)
        assert len(result.usernames) == 5

    def test_usernames_are_lowercase(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="UPPER", last_name="CASE")

        for entry in result.usernames:
            assert entry["username"] == entry["username"].lower()


# ── Locale Awareness Tests ────────────────────────────────────


class TestLocaleAwareness:
    def test_japanese_name_order(self):
        """Japanese locale should use eastern name order (family first)."""
        engine = IdentityDerivationEngine(locale="ja_JP", seed=42)
        result = engine.derive(full_name="Tanaka Yuki")

        # Eastern order: "Tanaka Yuki" → last=Tanaka, first=Yuki
        assert result.first_name == "Yuki"
        assert result.last_name == "Tanaka"
        assert result.full_name == "Tanaka Yuki"  # Eastern order preserved

    def test_chinese_name_order(self):
        engine = IdentityDerivationEngine(locale="zh_CN", seed=42)
        result = engine.derive(full_name="Wang Wei")

        assert result.first_name == "Wei"
        assert result.last_name == "Wang"

    def test_german_transliteration(self):
        """German locale should transliterate umlauts."""
        engine = IdentityDerivationEngine(locale="de_DE", seed=42)
        result = engine.derive(first_name="Müller", last_name="Schröder")

        # Emails should use transliterated versions
        all_emails = [e["email"] for e in result.emails]
        for email in all_emails:
            local = email.split("@")[0]
            # Should not contain umlauts
            assert "ü" not in local
            assert "ö" not in local

    def test_french_accents_handled(self):
        engine = IdentityDerivationEngine(locale="fr_FR", seed=42)
        result = engine.derive(first_name="René", last_name="Léger")

        all_emails = [e["email"] for e in result.emails]
        for email in all_emails:
            local = email.split("@")[0]
            assert "é" not in local

    def test_locale_alias_resolution(self):
        """Short locale aliases should work."""
        engine = IdentityDerivationEngine(locale="us", seed=42)
        assert engine._locale_code == "en_US"

        engine2 = IdentityDerivationEngine(locale="japan", seed=42)
        assert engine2._locale_code == "ja_JP"

    def test_locale_specific_email_domains(self):
        """German locale should use German consumer domains from config."""
        engine = IdentityDerivationEngine(locale="de_DE", seed=42)
        result = engine.derive(first_name="Hans", last_name="Schmidt", num_emails=10)

        domains = [e["email"].split("@")[1] for e in result.emails]
        # German locale config includes: gmail.com, web.de, gmx.de, t-online.de, outlook.de
        german_domains = {"web.de", "gmx.de", "t-online.de", "outlook.de"}
        has_german = any(d in german_domains for d in domains)
        assert has_german, f"No German domains in {domains}"


# ── Batch Derivation Tests ────────────────────────────────────


class TestBatchDerivation:
    def test_batch_derives_multiple(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive_batch(
            names=[
                {"first_name": "John", "last_name": "Doe"},
                {"first_name": "Jane", "last_name": "Smith"},
                {"full_name": "Bob Builder"},
            ],
        )

        assert result.total_derived == 3
        assert len(result.identities) == 3
        assert result.identities[0].first_name == "John"
        assert result.identities[1].first_name == "Jane"
        assert result.identities[2].first_name == "Bob"

    def test_batch_email_uniqueness(self):
        engine = IdentityDerivationEngine(company_domain="company.com", seed=42)
        result = engine.derive_batch(
            names=[
                {"first_name": "John", "last_name": "Doe"},
                {"first_name": "John", "last_name": "Doe"},  # Same name!
            ],
        )

        # Even with same name, emails should differ (uniqueness guarantee)
        emails_1 = {e["email"] for e in result.identities[0].emails}
        emails_2 = {e["email"] for e in result.identities[1].emails}
        # At least the corporate emails should be unique
        corp_1 = [e["email"] for e in result.identities[0].emails if e["type"] == "corporate"]
        corp_2 = [e["email"] for e in result.identities[1].emails if e["type"] == "corporate"]
        if corp_1 and corp_2:
            assert corp_1[0] != corp_2[0]

    def test_batch_tracks_patterns_used(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive_batch(
            names=[{"first_name": "A", "last_name": "B"} for _ in range(10)],
        )
        assert len(result.patterns_used) > 0


# ── Edge Cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_name_only(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(full_name="Madonna")

        assert result.first_name == "Madonna"
        assert result.last_name == ""
        assert len(result.emails) > 0
        assert len(result.usernames) > 0

    def test_empty_first_name(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="", last_name="Doe")

        assert len(result.emails) > 0

    def test_very_long_name(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="A" * 50, last_name="B" * 50)

        # Should not crash, emails should still be valid
        for entry in result.emails:
            assert "@" in entry["email"]

    def test_deterministic_with_seed(self):
        """Same seed + same input → same structural output (pattern types match)."""
        engine1 = IdentityDerivationEngine(seed=123)
        result1 = engine1.derive(first_name="John", last_name="Doe")

        engine2 = IdentityDerivationEngine(seed=123)
        result2 = engine2.derive(first_name="John", last_name="Doe")

        # Pattern selection is deterministic even if embedded random digits differ
        patterns1 = [e["pattern"] for e in result1.emails]
        patterns2 = [e["pattern"] for e in result2.emails]
        assert patterns1 == patterns2

        upatterns1 = [u["pattern"] for u in result1.usernames]
        upatterns2 = [u["pattern"] for u in result2.usernames]
        assert upatterns1 == upatterns2

    def test_to_dict_serializable(self):
        engine = IdentityDerivationEngine(seed=42)
        result = engine.derive(first_name="Test", last_name="User")
        d = result.to_dict()

        assert "first_name" in d
        assert "emails" in d
        assert "usernames" in d
        assert isinstance(d["emails"], list)


# ── Router Integration Tests ──────────────────────────────────


class TestIdentityRouter:
    def test_derive_endpoint(self):
        response = client.post("/identity/derive", json={
            "first_name": "John",
            "last_name": "Doe",
            "locale": "en_US",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"
        assert len(data["emails"]) == 3
        assert len(data["usernames"]) == 3

    def test_derive_with_company_domain(self):
        response = client.post("/identity/derive", json={
            "first_name": "Jane",
            "last_name": "Smith",
            "company_domain": "sunlife.com",
            "company_pattern": "first.last",
        })
        assert response.status_code == 200
        data = response.json()
        corporate = [e for e in data["emails"] if e["type"] == "corporate"]
        assert len(corporate) >= 1
        assert "sunlife.com" in corporate[0]["email"]
        assert corporate[0]["email"] == "jane.smith@sunlife.com"

    def test_derive_with_full_name(self):
        response = client.post("/identity/derive", json={
            "full_name": "Bob Builder",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Bob"
        assert data["last_name"] == "Builder"

    def test_derive_batch_endpoint(self):
        response = client.post("/identity/derive-batch", json={
            "names": [
                {"first_name": "John", "last_name": "Doe"},
                {"first_name": "Jane", "last_name": "Smith"},
                {"full_name": "Alice Wonderland"},
            ],
            "company_domain": "acme.com",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total_derived"] == 3
        assert len(data["identities"]) == 3

    def test_derive_locale_parameter(self):
        response = client.post("/identity/derive", json={
            "full_name": "Tanaka Yuki",
            "locale": "ja_JP",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Yuki"
        assert data["last_name"] == "Tanaka"
        assert data["locale"] == "ja_JP"

    def test_derive_batch_empty_names_rejected(self):
        response = client.post("/identity/derive-batch", json={
            "names": [],
        })
        assert response.status_code == 422  # Validation error
