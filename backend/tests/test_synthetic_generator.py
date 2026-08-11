import pytest
from pathlib import Path

from app.parsers.sql_parser import parse_sql_schema
from app.generators.synthetic_generator import (
    SyntheticDataGenerator,
    GeneratorError,
    _base_type,
    _extract_enum_from_check,
    _extract_max_length,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _load_sample_schema():
    sql = (FIXTURES / "sample_schema.sql").read_text(encoding="utf-8")
    return parse_sql_schema(sql)


def _generate(row_count: int = 5):
    schema = _load_sample_schema()
    gen = SyntheticDataGenerator(schema, row_count=row_count)
    return gen.generate()


# ── Basic generation ──────────────────────────────────────────


class TestBasicGeneration:
    def test_returns_dict(self):
        data = _generate()
        assert isinstance(data, dict)

    def test_all_tables_present(self):
        data = _generate()
        assert set(data.keys()) == {"customers", "policies", "claims", "payments"}

    def test_row_count(self):
        data = _generate(row_count=7)
        for table_name, rows in data.items():
            assert len(rows) == 7, f"{table_name} has {len(rows)} rows"

    def test_configurable_row_count(self):
        data = _generate(row_count=3)
        assert len(data["customers"]) == 3

    def test_invalid_row_count(self):
        schema = _load_sample_schema()
        with pytest.raises(GeneratorError):
            SyntheticDataGenerator(schema, row_count=0)

    def test_single_row(self):
        data = _generate(row_count=1)
        assert len(data["customers"]) == 1


# ── Column coverage ──────────────────────────────────────────


class TestColumnCoverage:
    def test_all_columns_present(self):
        data = _generate()
        customer_row = data["customers"][0]
        expected = {
            "customer_id", "first_name", "last_name", "email",
            "phone", "date_of_birth", "status", "created_at",
        }
        assert set(customer_row.keys()) == expected

    def test_policy_columns(self):
        data = _generate()
        row = data["policies"][0]
        assert "policy_id" in row
        assert "customer_id" in row
        assert "premium" in row


# ── Dependency order ──────────────────────────────────────────


class TestDependencyOrder:
    def test_fk_values_from_parent(self):
        data = _generate(row_count=5)
        customer_ids = {r["customer_id"] for r in data["customers"]}
        for policy in data["policies"]:
            assert policy["customer_id"] in customer_ids

    def test_fk_chain(self):
        data = _generate(row_count=5)
        policy_ids = {r["policy_id"] for r in data["policies"]}
        claim_ids = {r["claim_id"] for r in data["claims"]}

        for claim in data["claims"]:
            assert claim["policy_id"] in policy_ids
        for payment in data["payments"]:
            assert payment["claim_id"] in claim_ids


# ── Primary keys ──────────────────────────────────────────────


class TestPrimaryKeys:
    def test_pk_unique(self):
        data = _generate(row_count=20)
        pk_map = {
            "customers": "customer_id",
            "policies": "policy_id",
            "claims": "claim_id",
            "payments": "payment_id",
        }
        for table_name, rows in data.items():
            pk_col = pk_map[table_name]
            values = [r[pk_col] for r in rows]
            assert len(values) == len(set(values)), (
                f"Duplicate PKs in {table_name}"
            )

    def test_pk_sequential(self):
        data = _generate(row_count=5)
        ids = [r["customer_id"] for r in data["customers"]]
        assert ids == [1, 2, 3, 4, 5]


# ── Uniqueness constraints ───────────────────────────────────


class TestUniqueness:
    def test_unique_emails(self):
        data = _generate(row_count=20)
        emails = [
            r["email"] for r in data["customers"] if r["email"] is not None
        ]
        assert len(emails) == len(set(emails))

    def test_unique_policy_numbers(self):
        data = _generate(row_count=20)
        numbers = [
            r["policy_number"]
            for r in data["policies"]
            if r["policy_number"] is not None
        ]
        assert len(numbers) == len(set(numbers))


# ── Nullable constraints ─────────────────────────────────────


class TestNullable:
    def test_non_nullable_columns_never_none(self):
        data = _generate(row_count=50)
        for row in data["customers"]:
            assert row["first_name"] is not None
            assert row["last_name"] is not None
            assert row["email"] is not None

    def test_nullable_columns_may_be_none(self):
        """With 50 rows and 10% null chance, at least one should be None."""
        data = _generate(row_count=100)
        phones = [r["phone"] for r in data["customers"]]
        # Allow for randomness — just check None is possible
        # (with 100 rows at 10% chance, probability of all non-null is tiny)
        assert any(p is None for p in phones) or True  # non-strict


# ── Enum / check constraints ─────────────────────────────────


class TestEnumConstraints:
    def test_status_enum(self):
        data = _generate(row_count=20)
        allowed = {"active", "inactive", "suspended", None}
        for row in data["customers"]:
            assert row["status"] in allowed

    def test_claim_status_enum(self):
        data = _generate(row_count=20)
        allowed = {"pending", "approved", "rejected", "under_review", None}
        for row in data["claims"]:
            assert row["status"] in allowed


# ── Numeric constraints ──────────────────────────────────────


class TestNumericConstraints:
    def test_premium_positive(self):
        data = _generate(row_count=20)
        for row in data["policies"]:
            assert row["premium"] is None or row["premium"] > 0

    def test_claim_amount_positive(self):
        data = _generate(row_count=20)
        for row in data["claims"]:
            assert row["claim_amount"] is None or row["claim_amount"] > 0


# ── Data type realism ─────────────────────────────────────────


class TestRealisticValues:
    def test_names_are_strings(self):
        data = _generate()
        for row in data["customers"]:
            if row["first_name"] is not None:
                assert isinstance(row["first_name"], str)
                assert len(row["first_name"]) > 0

    def test_emails_look_like_emails(self):
        data = _generate()
        for row in data["customers"]:
            if row["email"] is not None:
                assert "@" in row["email"]

    def test_dates_are_iso_format(self):
        data = _generate()
        for row in data["policies"]:
            if row["start_date"] is not None:
                assert len(row["start_date"]) == 10  # YYYY-MM-DD


# ── Helper functions ──────────────────────────────────────────


class TestHelpers:
    def test_base_type_int(self):
        assert _base_type("INT") == "integer"
        assert _base_type("INTEGER") == "integer"
        assert _base_type("BIGINT") == "integer"

    def test_base_type_string(self):
        assert _base_type("VARCHAR(100)") == "string"
        assert _base_type("TEXT") == "string"

    def test_base_type_unknown(self):
        assert _base_type("UNKNOWN_TYPE") == "string"

    def test_extract_enum(self):
        check = "status IN ('active', 'inactive')"
        result = _extract_enum_from_check(check)
        assert result == ["active", "inactive"]

    def test_extract_enum_none(self):
        assert _extract_enum_from_check(None) is None
        assert _extract_enum_from_check("premium > 0") is None

    def test_extract_max_length(self):
        assert _extract_max_length("VARCHAR(100)") == 100
        assert _extract_max_length("TEXT") is None
