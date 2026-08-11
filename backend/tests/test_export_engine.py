"""Tests for the export engine — CSV, JSON, SQL INSERT, ZIP packaging."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from datetime import date, datetime

import pytest

from app.exporters.engine import (
    ExportEngine,
    ExportError,
    _json_serial,
    _sql_escape,
    _write_csv,
    _write_json,
    _write_sql,
)
from app.models.export import ExportFormat, ExportResult, ExportSummary, TableExportInfo
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.generators.synthetic_generator import SyntheticDataGenerator


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def sample_data():
    return {
        "customers": [
            {"id": 1, "name": "Alice", "email": "alice@test.com"},
            {"id": 2, "name": "Bob", "email": "bob@test.com"},
            {"id": 3, "name": "Charlie", "email": "charlie@test.com"},
        ],
        "orders": [
            {"id": 101, "customer_id": 1, "amount": 99.99},
            {"id": 102, "customer_id": 2, "amount": 150.00},
        ],
    }


@pytest.fixture
def empty_data():
    return {"empty_table": []}


@pytest.fixture
def data_with_special_values():
    return {
        "test_table": [
            {
                "id": 1,
                "name": "O'Brien",
                "active": True,
                "score": None,
                "created": date(2025, 1, 15),
                "updated": datetime(2025, 6, 1, 12, 30, 0),
            },
        ],
    }


@pytest.fixture
def export_dir():
    d = tempfile.mkdtemp(prefix="export_test_")
    yield d
    # Cleanup after test
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)


@pytest.fixture
def sample_schema():
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="id", data_type="INT", is_primary_key=True, nullable=False),
                    ColumnMetadata(name="name", data_type="VARCHAR(100)", nullable=False),
                    ColumnMetadata(name="email", data_type="VARCHAR(255)", is_unique=True, nullable=False),
                ],
                primary_keys=["id"],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="INT", is_primary_key=True, nullable=False),
                    ColumnMetadata(name="customer_id", data_type="INT", nullable=False),
                    ColumnMetadata(name="amount", data_type="DECIMAL(10,2)", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[
                    ForeignKeyMetadata(column="customer_id", references_table="customers", references_column="id"),
                ],
            ),
        ]
    )


# ── Test _json_serial ─────────────────────────────────────────


class TestJsonSerial:
    def test_date(self):
        assert _json_serial(date(2025, 3, 15)) == "2025-03-15"

    def test_datetime(self):
        result = _json_serial(datetime(2025, 3, 15, 10, 30, 0))
        assert result == "2025-03-15T10:30:00"

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            _json_serial(set())


# ── Test _sql_escape ──────────────────────────────────────────


class TestSqlEscape:
    def test_none(self):
        assert _sql_escape(None) == "NULL"

    def test_bool_true(self):
        assert _sql_escape(True) == "TRUE"

    def test_bool_false(self):
        assert _sql_escape(False) == "FALSE"

    def test_integer(self):
        assert _sql_escape(42) == "42"

    def test_float(self):
        assert _sql_escape(3.14) == "3.14"

    def test_string(self):
        assert _sql_escape("hello") == "'hello'"

    def test_string_with_quotes(self):
        assert _sql_escape("O'Brien") == "'O''Brien'"

    def test_date(self):
        assert _sql_escape(date(2025, 1, 1)) == "'2025-01-01'"

    def test_datetime(self):
        result = _sql_escape(datetime(2025, 6, 15, 12, 0, 0))
        assert result == "'2025-06-15T12:00:00'"


# ── Test CSV writer ───────────────────────────────────────────


class TestWriteCSV:
    def test_basic_csv(self, sample_data):
        content = _write_csv("customers", sample_data["customers"])
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 3
        assert rows[0]["name"] == "Alice"
        assert rows[2]["email"] == "charlie@test.com"

    def test_empty_rows(self):
        assert _write_csv("empty", []) == ""

    def test_csv_headers(self, sample_data):
        content = _write_csv("customers", sample_data["customers"])
        first_line = content.split("\n")[0]
        assert "id" in first_line
        assert "name" in first_line
        assert "email" in first_line


# ── Test JSON writer ─────────────────────────────────────────


class TestWriteJSON:
    def test_basic_json(self, sample_data):
        content = _write_json("orders", sample_data["orders"])
        parsed = json.loads(content)
        assert len(parsed) == 2
        assert parsed[0]["amount"] == 99.99

    def test_empty_rows(self):
        content = _write_json("empty", [])
        assert json.loads(content) == []

    def test_dates_serialised(self, data_with_special_values):
        content = _write_json("test_table", data_with_special_values["test_table"])
        parsed = json.loads(content)
        assert parsed[0]["created"] == "2025-01-15"
        assert parsed[0]["updated"] == "2025-06-01T12:30:00"

    def test_null_values(self, data_with_special_values):
        content = _write_json("test_table", data_with_special_values["test_table"])
        parsed = json.loads(content)
        assert parsed[0]["score"] is None


# ── Test SQL writer ───────────────────────────────────────────


class TestWriteSQL:
    def test_basic_inserts(self, sample_data):
        content = _write_sql("customers", sample_data["customers"])
        lines = content.strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("INSERT INTO customers")
        assert "VALUES" in lines[0]
        assert "'Alice'" in lines[0]

    def test_empty_rows(self):
        content = _write_sql("empty", [])
        assert "No data" in content

    def test_null_handling(self, data_with_special_values):
        content = _write_sql("test_table", data_with_special_values["test_table"])
        assert "NULL" in content

    def test_bool_handling(self, data_with_special_values):
        content = _write_sql("test_table", data_with_special_values["test_table"])
        assert "TRUE" in content

    def test_quote_escape(self, data_with_special_values):
        content = _write_sql("test_table", data_with_special_values["test_table"])
        assert "O''Brien" in content

    def test_column_list_present(self, sample_data):
        content = _write_sql("orders", sample_data["orders"])
        assert "(id, customer_id, amount)" in content


# ── Test ExportEngine — CSV ───────────────────────────────────


class TestExportCSV:
    def test_creates_zip(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        assert os.path.exists(result.zip_path)
        assert result.zip_path.endswith(".zip")

    def test_zip_contains_files(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            assert "customers.csv" in names
            assert "orders.csv" in names
            assert "_export_summary.json" in names

    def test_csv_content_valid(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("customers.csv").decode()
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            assert len(rows) == 3

    def test_summary_metadata(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        assert result.summary.format == ExportFormat.CSV
        assert result.summary.total_tables == 2
        assert result.summary.total_rows == 5


# ── Test ExportEngine — JSON ─────────────────────────────────


class TestExportJSON:
    def test_creates_zip(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.JSON)
        assert os.path.exists(result.zip_path)

    def test_zip_contains_json_files(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.JSON)
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            assert "customers.json" in names
            assert "orders.json" in names

    def test_json_content_valid(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.JSON)
        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("orders.json").decode()
            parsed = json.loads(content)
            assert len(parsed) == 2
            assert parsed[0]["id"] == 101


# ── Test ExportEngine — SQL ───────────────────────────────────


class TestExportSQL:
    def test_creates_zip(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.SQL)
        assert os.path.exists(result.zip_path)

    def test_zip_contains_sql_files(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.SQL)
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            assert "customers.sql" in names
            assert "orders.sql" in names

    def test_sql_content_valid(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.SQL)
        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("customers.sql").decode()
            # Multi-value INSERT batches: at least 1 INSERT statement
            assert "INSERT INTO customers" in content
            assert content.count("INSERT INTO customers") >= 1


# ── Test export_all_formats ──────────────────────────────────


class TestExportAllFormats:
    def test_returns_three_results(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        results = engine.export_all_formats(sample_data)
        assert len(results) == 3
        formats = {r.summary.format for r in results}
        assert formats == {ExportFormat.CSV, ExportFormat.JSON, ExportFormat.SQL}

    def test_all_zips_exist(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        results = engine.export_all_formats(sample_data)
        for r in results:
            assert os.path.exists(r.zip_path)


# ── Test summary in ZIP ──────────────────────────────────────


class TestExportSummary:
    def test_summary_in_zip(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        with zipfile.ZipFile(result.zip_path) as zf:
            summary_raw = zf.read("_export_summary.json").decode()
            summary = json.loads(summary_raw)
            assert summary["total_tables"] == 2
            assert summary["total_rows"] == 5
            assert summary["format"] == "csv"
            assert len(summary["tables"]) == 2

    def test_summary_table_info(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.JSON)
        table_info = {t.table_name: t for t in result.summary.tables}
        assert table_info["customers"].row_count == 3
        assert table_info["orders"].row_count == 2
        assert table_info["customers"].file_name == "customers.json"

    def test_summary_exported_at(self, sample_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(sample_data, ExportFormat.CSV)
        assert result.summary.exported_at is not None


# ── Test edge cases ──────────────────────────────────────────


class TestExportEdgeCases:
    def test_empty_table(self, empty_data, export_dir):
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(empty_data, ExportFormat.CSV)
        assert result.summary.total_rows == 0
        assert result.summary.total_tables == 1

    def test_special_characters_in_table_name(self, export_dir):
        data = {"my table!@#": [{"col": 1}]}
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(data, ExportFormat.CSV)
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            # Table name sanitised — no special characters
            csv_files = [n for n in names if n.endswith(".csv")]
            assert len(csv_files) == 1
            assert "!" not in csv_files[0]
            assert "@" not in csv_files[0]

    def test_output_dir_created(self):
        d = os.path.join(tempfile.gettempdir(), "export_test_nested", "sub")
        try:
            engine = ExportEngine(output_dir=d)
            result = engine.export({"t": [{"a": 1}]}, ExportFormat.JSON)
            assert os.path.exists(result.zip_path)
        finally:
            # Cleanup
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
            os.rmdir(d)
            os.rmdir(os.path.dirname(d))

    def test_single_row(self, export_dir):
        data = {"one": [{"x": 42}]}
        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(data, ExportFormat.SQL)
        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("one.sql").decode()
            assert "INSERT INTO one" in content
            assert "42" in content


# ── Integration: generate → export ───────────────────────────


class TestGenerateAndExport:
    def test_generated_data_export_csv(self, sample_schema, export_dir):
        gen = SyntheticDataGenerator(sample_schema, row_count=5)
        data = gen.generate()

        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(data, ExportFormat.CSV, sample_schema)

        assert result.summary.total_tables == 2
        assert result.summary.total_rows == 10  # 5 per table

        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("customers.csv").decode()
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            assert len(rows) == 5

    def test_generated_data_export_json(self, sample_schema, export_dir):
        gen = SyntheticDataGenerator(sample_schema, row_count=5)
        data = gen.generate()

        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(data, ExportFormat.JSON, sample_schema)

        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("orders.json").decode()
            parsed = json.loads(content)
            assert len(parsed) == 5
            # FK integrity — customer_id should exist
            customer_ids = {r["id"] for r in data["customers"]}
            for row in parsed:
                assert row["customer_id"] in customer_ids

    def test_generated_data_export_sql(self, sample_schema, export_dir):
        gen = SyntheticDataGenerator(sample_schema, row_count=5)
        data = gen.generate()

        engine = ExportEngine(output_dir=export_dir)
        result = engine.export(data, ExportFormat.SQL, sample_schema)

        with zipfile.ZipFile(result.zip_path) as zf:
            content = zf.read("customers.sql").decode()
            # Multi-value INSERT: 5 rows batched into 1 statement
            assert "INSERT INTO customers" in content
            assert content.count("INSERT INTO customers") >= 1

    def test_generated_data_all_formats(self, sample_schema, export_dir):
        gen = SyntheticDataGenerator(sample_schema, row_count=3)
        data = gen.generate()

        engine = ExportEngine(output_dir=export_dir)
        results = engine.export_all_formats(data, sample_schema)

        assert len(results) == 3
        for r in results:
            assert os.path.exists(r.zip_path)
            assert r.summary.total_rows == 6  # 3 per table


# ── Test ExportResult / models ────────────────────────────────


class TestExportModels:
    def test_export_format_values(self):
        assert ExportFormat.CSV.value == "csv"
        assert ExportFormat.JSON.value == "json"
        assert ExportFormat.SQL.value == "sql"

    def test_table_export_info(self):
        info = TableExportInfo(
            table_name="users",
            row_count=100,
            file_name="users.csv",
            format=ExportFormat.CSV,
        )
        assert info.table_name == "users"
        assert info.row_count == 100

    def test_export_summary_defaults(self):
        s = ExportSummary(format=ExportFormat.JSON, total_tables=0, total_rows=0)
        assert s.exported_at is not None
        assert s.tables == []

    def test_export_result(self):
        s = ExportSummary(format=ExportFormat.SQL, total_tables=1, total_rows=10)
        r = ExportResult(zip_path="/tmp/test.zip", summary=s)
        assert r.zip_path == "/tmp/test.zip"
