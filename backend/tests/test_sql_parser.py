import json
import pytest
from pathlib import Path

from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.models.schema import SchemaMetadata


FIXTURES = Path(__file__).parent / "fixtures"


def _load_sample_sql() -> str:
    return (FIXTURES / "sample_schema.sql").read_text(encoding="utf-8")


# ── Basic parsing ──────────────────────────────────────────────


class TestSQLParserBasic:
    def test_parses_all_tables(self):
        result = parse_sql_schema(_load_sample_sql())
        table_names = [t.name for t in result.tables]
        assert table_names == ["customers", "policies", "claims", "payments"]

    def test_returns_schema_metadata_type(self):
        result = parse_sql_schema(_load_sample_sql())
        assert isinstance(result, SchemaMetadata)

    def test_empty_sql_returns_empty_tables(self):
        result = parse_sql_schema("")
        assert result.tables == []

    def test_non_create_statements_ignored(self):
        result = parse_sql_schema("SELECT 1; INSERT INTO foo VALUES (1);")
        assert result.tables == []

    def test_invalid_sql_does_not_crash(self):
        result = parse_sql_schema("THIS IS NOT SQL AT ALL;;;")
        assert isinstance(result, SchemaMetadata)


# ── Column extraction ──────────────────────────────────────────


class TestColumnExtraction:
    def test_customers_column_count(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        assert len(customers.columns) == 8

    def test_column_names(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        names = [c.name for c in customers.columns]
        assert names == [
            "customer_id", "first_name", "last_name", "email",
            "phone", "date_of_birth", "status", "created_at",
        ]

    def test_column_types(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        types = {c.name: c.data_type for c in customers.columns}
        assert "INT" in types["customer_id"]
        assert "VARCHAR" in types["first_name"]
        assert "DATE" in types["date_of_birth"]


# ── Primary keys ───────────────────────────────────────────────


class TestPrimaryKeys:
    def test_inline_pk(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        assert "customer_id" in customers.primary_keys

    def test_all_tables_have_pk(self):
        result = parse_sql_schema(_load_sample_sql())
        for table in result.tables:
            assert len(table.primary_keys) >= 1, f"{table.name} has no PK"

    def test_pk_column_flagged(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        pk_col = next(c for c in customers.columns if c.name == "customer_id")
        assert pk_col.is_primary_key is True

    def test_composite_pk(self):
        sql = """
        CREATE TABLE enrollment (
            student_id INT,
            course_id INT,
            PRIMARY KEY (student_id, course_id)
        );
        """
        result = parse_sql_schema(sql)
        assert sorted(result.tables[0].primary_keys) == ["course_id", "student_id"]


# ── Foreign keys ───────────────────────────────────────────────


class TestForeignKeys:
    def test_policies_fk(self):
        result = parse_sql_schema(_load_sample_sql())
        policies = result.tables[1]
        assert len(policies.foreign_keys) == 1
        fk = policies.foreign_keys[0]
        assert fk.column == "customer_id"
        assert fk.references_table == "customers"
        assert fk.references_column == "customer_id"

    def test_fk_chain(self):
        result = parse_sql_schema(_load_sample_sql())
        payments = result.tables[3]
        assert len(payments.foreign_keys) == 1
        fk = payments.foreign_keys[0]
        assert fk.column == "claim_id"
        assert fk.references_table == "claims"

    def test_total_fk_count(self):
        result = parse_sql_schema(_load_sample_sql())
        total_fks = sum(len(t.foreign_keys) for t in result.tables)
        assert total_fks == 3


# ── Unique constraints ────────────────────────────────────────


class TestUniqueConstraints:
    def test_inline_unique(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        email_col = next(c for c in customers.columns if c.name == "email")
        assert email_col.is_unique is True

    def test_table_level_unique(self):
        sql = """
        CREATE TABLE products (
            id INT PRIMARY KEY,
            sku VARCHAR(50),
            name VARCHAR(100),
            UNIQUE (sku)
        );
        """
        result = parse_sql_schema(sql)
        assert ["sku"] in result.tables[0].unique_constraints


# ── Nullable constraints ──────────────────────────────────────


class TestNullableConstraints:
    def test_not_null_columns(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        not_null_cols = [c.name for c in customers.columns if not c.nullable]
        assert "first_name" in not_null_cols
        assert "last_name" in not_null_cols
        assert "email" in not_null_cols

    def test_nullable_columns(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        nullable_cols = [c.name for c in customers.columns if c.nullable]
        assert "phone" in nullable_cols
        assert "date_of_birth" in nullable_cols


# ── Check constraints ─────────────────────────────────────────


class TestCheckConstraints:
    def test_check_constraints_extracted(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        assert len(customers.check_constraints) >= 1

    def test_check_on_premium(self):
        result = parse_sql_schema(_load_sample_sql())
        policies = result.tables[1]
        assert any("premium" in c for c in policies.check_constraints)


# ── Default values ─────────────────────────────────────────────


class TestDefaults:
    def test_default_value_extracted(self):
        result = parse_sql_schema(_load_sample_sql())
        customers = result.tables[0]
        status_col = next(c for c in customers.columns if c.name == "status")
        assert status_col.default is not None
        assert "active" in status_col.default.lower()


# ── JSON serialization ────────────────────────────────────────


class TestSerialization:
    def test_model_dump_is_serializable(self):
        result = parse_sql_schema(_load_sample_sql())
        data = result.model_dump()
        output = json.dumps(data, indent=2)
        assert '"tables"' in output
        assert '"customers"' in output

    def test_round_trip(self):
        result = parse_sql_schema(_load_sample_sql())
        data = result.model_dump()
        restored = SchemaMetadata(**data)
        assert len(restored.tables) == len(result.tables)
