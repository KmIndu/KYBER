"""Tests for semantic type detection and realistic data generation."""

import re

import pytest

from app.generators.realistic_provider import RealisticProvider
from app.generators.semantic_types import SemanticType, detect_semantic_type


# ── Semantic Type Detection Tests ──────────────────────────────


class TestSemanticTypeDetection:
    """Test detect_semantic_type for all categories."""

    # Person
    @pytest.mark.parametrize("col,expected", [
        ("first_name", SemanticType.FIRST_NAME),
        ("firstName", SemanticType.FIRST_NAME),
        ("given_name", SemanticType.FIRST_NAME),
        ("last_name", SemanticType.LAST_NAME),
        ("surname", SemanticType.LAST_NAME),
        ("family_name", SemanticType.LAST_NAME),
        ("full_name", SemanticType.FULL_NAME),
        ("name", SemanticType.FULL_NAME),
        ("customer_name", SemanticType.FULL_NAME),
        ("patient_name", SemanticType.FULL_NAME),
        ("gender", SemanticType.GENDER),
        ("date_of_birth", SemanticType.DATE_OF_BIRTH),
        ("dob", SemanticType.DATE_OF_BIRTH),
        ("age", SemanticType.AGE),
    ])
    def test_person_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Contact
    @pytest.mark.parametrize("col,expected", [
        ("email", SemanticType.EMAIL),
        ("email_address", SemanticType.EMAIL),
        ("phone", SemanticType.PHONE),
        ("telephone", SemanticType.PHONE),
        ("mobile", SemanticType.MOBILE),
        ("mobile_number", SemanticType.MOBILE),
    ])
    def test_contact_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Address
    @pytest.mark.parametrize("col,expected", [
        ("street_address", SemanticType.STREET_ADDRESS),
        ("address_line", SemanticType.STREET_ADDRESS),
        ("city", SemanticType.CITY),
        ("state", SemanticType.STATE),
        ("province", SemanticType.STATE),
        ("country", SemanticType.COUNTRY),
        ("zip_code", SemanticType.POSTAL_CODE),
        ("postal_code", SemanticType.POSTAL_CODE),
        ("pincode", SemanticType.POSTAL_CODE),
        ("address", SemanticType.FULL_ADDRESS),
    ])
    def test_address_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Financial
    @pytest.mark.parametrize("col,expected", [
        ("account_number", SemanticType.ACCOUNT_NUMBER),
        ("account_no", SemanticType.ACCOUNT_NUMBER),
        ("iban", SemanticType.IBAN),
        ("swift_code", SemanticType.SWIFT_CODE),
        ("routing_number", SemanticType.ROUTING_NUMBER),
        ("amount", SemanticType.AMOUNT),
        ("balance", SemanticType.AMOUNT),
        ("total", SemanticType.AMOUNT),
        ("currency", SemanticType.CURRENCY),
        ("credit_card", SemanticType.CREDIT_CARD),
    ])
    def test_financial_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Insurance
    @pytest.mark.parametrize("col,expected", [
        ("policy_id", SemanticType.POLICY_ID),
        ("policy_number", SemanticType.POLICY_ID),
        ("claim_number", SemanticType.CLAIM_NUMBER),
        ("claim_id", SemanticType.CLAIM_NUMBER),
        ("premium", SemanticType.PREMIUM_AMOUNT),
        ("premium_amount", SemanticType.PREMIUM_AMOUNT),
        ("coverage", SemanticType.COVERAGE_AMOUNT),
        ("coverage_amount", SemanticType.COVERAGE_AMOUNT),
    ])
    def test_insurance_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Healthcare
    @pytest.mark.parametrize("col,expected", [
        ("patient_id", SemanticType.PATIENT_ID),
        ("diagnosis_code", SemanticType.DIAGNOSIS_CODE),
        ("icd_code", SemanticType.DIAGNOSIS_CODE),
        ("medication", SemanticType.MEDICATION_NAME),
        ("medication_name", SemanticType.MEDICATION_NAME),
        ("dosage", SemanticType.DOSAGE),
    ])
    def test_healthcare_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Retail
    @pytest.mark.parametrize("col,expected", [
        ("sku", SemanticType.SKU),
        ("sku_code", SemanticType.SKU),
        ("barcode", SemanticType.BARCODE),
        ("upc", SemanticType.BARCODE),
        ("product_name", SemanticType.PRODUCT_NAME),
    ])
    def test_retail_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Identity
    @pytest.mark.parametrize("col,expected", [
        ("pan_number", SemanticType.PAN),
        ("pan", SemanticType.PAN),
        ("ssn", SemanticType.SSN),
        ("social_security", SemanticType.SSN),
        ("passport_number", SemanticType.PASSPORT),
        ("national_id", SemanticType.NATIONAL_ID),
        ("aadhaar", SemanticType.NATIONAL_ID),
    ])
    def test_identity_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Timestamps
    @pytest.mark.parametrize("col,expected", [
        ("created_at", SemanticType.CREATED_AT),
        ("updated_at", SemanticType.UPDATED_AT),
        ("timestamp", SemanticType.TIMESTAMP),
    ])
    def test_timestamp_types(self, col, expected):
        assert detect_semantic_type(col) == expected

    # Domain-aware fallback
    def test_domain_aware_banking(self):
        assert detect_semantic_type("account", domain="banking") == SemanticType.ACCOUNT_NUMBER

    def test_domain_aware_insurance(self):
        assert detect_semantic_type("policy", domain="insurance") == SemanticType.POLICY_ID
        assert detect_semantic_type("claim", domain="insurance") == SemanticType.CLAIM_NUMBER

    def test_domain_aware_healthcare(self):
        assert detect_semantic_type("patient", domain="healthcare") == SemanticType.PATIENT_ID

    # Unknown
    def test_unknown_column(self):
        assert detect_semantic_type("xyz_foobar") == SemanticType.UNKNOWN


# ── Realistic Provider Tests ───────────────────────────────────


class TestRealisticProvider:
    """Test RealisticProvider generates valid values."""

    def test_default_locale(self):
        p = RealisticProvider()
        assert p.locale == "en_US"

    def test_india_locale(self):
        p = RealisticProvider(country="india")
        assert p.locale == "en_IN"

    def test_uk_locale(self):
        p = RealisticProvider(country="uk")
        assert p.locale == "en_GB"

    # ── Name generation ────────────────────────────────────────

    def test_first_name(self):
        p = RealisticProvider()
        name = p.generate(SemanticType.FIRST_NAME)
        assert isinstance(name, str) and len(name) > 0

    def test_last_name(self):
        p = RealisticProvider()
        name = p.generate(SemanticType.LAST_NAME)
        assert isinstance(name, str) and len(name) > 0

    def test_full_name(self):
        p = RealisticProvider()
        name = p.generate(SemanticType.FULL_NAME)
        assert isinstance(name, str) and " " in name

    # ── Email generation ───────────────────────────────────────

    def test_email_format(self):
        p = RealisticProvider()
        email = p.generate(SemanticType.EMAIL)
        assert "@" in email
        assert "." in email.split("@")[1]

    # ── Phone generation ───────────────────────────────────────

    def test_phone_us(self):
        p = RealisticProvider(country="us")
        phone = p.generate(SemanticType.PHONE)
        assert phone.startswith("+1")

    def test_phone_india(self):
        p = RealisticProvider(country="india")
        phone = p.generate(SemanticType.PHONE)
        assert phone.startswith("+91")

    def test_phone_uk(self):
        p = RealisticProvider(country="uk")
        phone = p.generate(SemanticType.PHONE)
        assert phone.startswith("+44")

    # ── Address generation ─────────────────────────────────────

    def test_city(self):
        p = RealisticProvider()
        city = p.generate(SemanticType.CITY)
        assert isinstance(city, str) and len(city) > 0

    def test_postal_code_india(self):
        p = RealisticProvider(country="india")
        code = p.generate(SemanticType.POSTAL_CODE)
        assert len(code) == 6 and code.isdigit()

    def test_postal_code_us(self):
        p = RealisticProvider(country="us")
        code = p.generate(SemanticType.POSTAL_CODE)
        assert len(code) == 5 and code.isdigit()

    # ── Account Number generation ──────────────────────────────

    def test_account_number_india(self):
        p = RealisticProvider(country="india")
        acct = p.generate(SemanticType.ACCOUNT_NUMBER)
        assert acct.isdigit()
        assert 11 <= len(acct) <= 16

    def test_account_number_us(self):
        p = RealisticProvider(country="us")
        acct = p.generate(SemanticType.ACCOUNT_NUMBER)
        assert acct.isdigit()
        assert 10 <= len(acct) <= 12

    def test_account_number_uk(self):
        p = RealisticProvider(country="uk")
        acct = p.generate(SemanticType.ACCOUNT_NUMBER)
        assert acct.isdigit()
        assert len(acct) == 8

    # ── Policy ID generation ───────────────────────────────────

    def test_policy_id_format(self):
        p = RealisticProvider(domain="insurance")
        policy = p.generate(SemanticType.POLICY_ID)
        # Format: PREFIX-YEAR-NNNNNN
        parts = policy.split("-")
        assert len(parts) == 3
        assert parts[0].isalpha() and len(parts[0]) == 3
        assert parts[1].isdigit() and len(parts[1]) == 4
        assert parts[2].isdigit() and len(parts[2]) == 6

    # ── Claim Number generation ────────────────────────────────

    def test_claim_number_format(self):
        p = RealisticProvider(domain="insurance")
        claim = p.generate(SemanticType.CLAIM_NUMBER)
        assert claim.startswith("CLM")
        assert len(claim) == 12  # CLM + 4 year + 5 seq

    # ── PAN generation ─────────────────────────────────────────

    def test_pan_format(self):
        p = RealisticProvider(country="india")
        pan = p.generate(SemanticType.PAN)
        assert len(pan) == 10
        # AAAPL1234C pattern
        assert pan[:5].isalpha()
        assert pan[5:9].isdigit()
        assert pan[9].isalpha()

    # ── Timestamp generation ───────────────────────────────────

    def test_timestamp_format(self):
        p = RealisticProvider()
        ts = p.generate(SemanticType.TIMESTAMP)
        assert "T" in ts  # ISO format
        assert len(ts) >= 19

    def test_date_format(self):
        p = RealisticProvider()
        d = p.generate(SemanticType.DATE)
        # YYYY-MM-DD
        assert re.match(r"\d{4}-\d{2}-\d{2}$", d)

    # ── Domain-aware amount ────────────────────────────────────

    def test_amount_insurance_range(self):
        p = RealisticProvider(domain="insurance")
        for _ in range(20):
            amt = p.generate(SemanticType.AMOUNT)
            assert 100.0 <= amt <= 500000.0

    def test_amount_retail_range(self):
        p = RealisticProvider(domain="retail")
        for _ in range(20):
            amt = p.generate(SemanticType.AMOUNT)
            assert 0.99 <= amt <= 9999.99

    # ── Currency country-aware ─────────────────────────────────

    def test_currency_india(self):
        p = RealisticProvider(country="india")
        assert p.generate(SemanticType.CURRENCY) == "INR"

    def test_currency_us(self):
        p = RealisticProvider(country="us")
        assert p.generate(SemanticType.CURRENCY) == "USD"

    def test_currency_uk(self):
        p = RealisticProvider(country="uk")
        assert p.generate(SemanticType.CURRENCY) == "GBP"

    # ── Healthcare-specific ────────────────────────────────────

    def test_diagnosis_code(self):
        p = RealisticProvider(domain="healthcare")
        code = p.generate(SemanticType.DIAGNOSIS_CODE)
        # ICD format: letter + digits + dot + digits
        assert re.match(r"[A-Z]\d+\.?\d*", code)

    def test_medication_name(self):
        p = RealisticProvider(domain="healthcare")
        med = p.generate(SemanticType.MEDICATION_NAME)
        assert isinstance(med, str) and len(med) > 5

    # ── Retail-specific ────────────────────────────────────────

    def test_sku_format(self):
        p = RealisticProvider(domain="retail")
        sku = p.generate(SemanticType.SKU)
        # AAA-NNNNNN
        assert re.match(r"[A-Z]{3}-\d{6}$", sku)

    def test_barcode_ean13(self):
        p = RealisticProvider(domain="retail")
        barcode = p.generate(SemanticType.BARCODE)
        assert len(barcode) == 13 and barcode.isdigit()

    # ── General ────────────────────────────────────────────────

    def test_uuid_format(self):
        p = RealisticProvider()
        val = p.generate(SemanticType.UUID)
        assert re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", val)

    def test_ssn_us_format(self):
        p = RealisticProvider(country="us")
        ssn = p.generate(SemanticType.SSN)
        assert re.match(r"\d{3}-\d{2}-\d{4}$", ssn)

    def test_unknown_type_returns_value(self):
        p = RealisticProvider()
        val = p.generate(SemanticType.UNKNOWN)
        assert isinstance(val, str) and len(val) > 0


# ── Integration with Generator ─────────────────────────────────


class TestGeneratorIntegration:
    """Test that SyntheticDataGenerator uses realistic values."""

    def test_generates_realistic_emails(self):
        from app.generators.synthetic_generator import SyntheticDataGenerator
        from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="users",
                columns=[
                    ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                    ColumnMetadata(name="email", data_type="varchar(100)", nullable=False),
                    ColumnMetadata(name="phone", data_type="varchar(20)", nullable=False),
                    ColumnMetadata(name="first_name", data_type="varchar(50)", nullable=False),
                    ColumnMetadata(name="pan_number", data_type="varchar(10)", nullable=False),
                ],
            ),
        ])
        gen = SyntheticDataGenerator(schema, row_count=5, country="india", domain="banking")
        data = gen.generate()
        rows = data["users"]
        assert len(rows) == 5

        for row in rows:
            assert "@" in row["email"]
            assert row["phone"].startswith("+91")
            assert isinstance(row["first_name"], str) and len(row["first_name"]) > 0
            pan = row["pan_number"]
            assert len(pan) == 10
            assert pan[:5].isalpha()
            assert pan[5:9].isdigit()

    def test_generates_insurance_data(self):
        from app.generators.synthetic_generator import SyntheticDataGenerator
        from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="policies",
                columns=[
                    ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                    ColumnMetadata(name="policy_number", data_type="varchar(20)", nullable=False),
                    ColumnMetadata(name="premium_amount", data_type="decimal(10,2)", nullable=False),
                    ColumnMetadata(name="claim_id", data_type="varchar(15)", nullable=False),
                ],
            ),
        ])
        gen = SyntheticDataGenerator(schema, row_count=5, country="us", domain="insurance")
        data = gen.generate()
        rows = data["policies"]

        for row in rows:
            assert row["policy_number"].count("-") == 2  # PREFIX-YEAR-SEQ
            assert 500.0 <= row["premium_amount"] <= 50000.0
            assert row["claim_id"].startswith("CLM")

    def test_generates_country_aware_accounts(self):
        from app.generators.synthetic_generator import SyntheticDataGenerator
        from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata

        schema = SchemaMetadata(tables=[
            TableMetadata(
                name="accounts",
                columns=[
                    ColumnMetadata(name="id", data_type="integer", is_primary_key=True),
                    ColumnMetadata(name="account_number", data_type="varchar(20)", nullable=False),
                    ColumnMetadata(name="currency", data_type="varchar(3)", nullable=False),
                ],
            ),
        ])

        # India
        gen_in = SyntheticDataGenerator(schema, row_count=3, country="india", domain="banking")
        data_in = gen_in.generate()
        for row in data_in["accounts"]:
            assert row["account_number"].isdigit()
            assert 11 <= len(row["account_number"]) <= 16
            assert row["currency"] == "INR"

        # UK
        gen_uk = SyntheticDataGenerator(schema, row_count=3, country="uk", domain="banking")
        data_uk = gen_uk.generate()
        for row in data_uk["accounts"]:
            assert row["account_number"].isdigit()
            assert len(row["account_number"]) == 8
            assert row["currency"] == "GBP"
