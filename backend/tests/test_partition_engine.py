"""Tests for the equivalence partitioning engine and router.

Covers:
- Numeric partitioning (CHECK bounds, heuristic bounds, type bounds)
- Enum partitioning
- String partitioning (with/without max length, email, phone)
- Date & boolean partitioning
- Nullable partitioning
- Dataset generation (proportional rows)
- Visualization outputs
- Column summaries
- Empty schema handling
- Router endpoint (success, 404, 400, rows_per_partition param)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.generators.partition_engine import EquivalencePartitioningEngine
from app.main import app
from app.models.partition import (
    Partition,
    PartitionAnalysis,
    PartitionColumnSummary,
    PartitionDataset,
    PartitionType,
    PartitionVisualization,
)
from app.models.schema import (
    ColumnMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.session_store import store

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def int_col_checked() -> ColumnMetadata:
    return ColumnMetadata(
        name="age", data_type="INTEGER", nullable=False,
        check_constraint="age >= 18 AND age <= 60",
    )


@pytest.fixture
def int_col_plain() -> ColumnMetadata:
    return ColumnMetadata(name="count", data_type="INTEGER", nullable=True)


@pytest.fixture
def float_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="price", data_type="DECIMAL(10,2)", nullable=False,
        check_constraint="price >= 0 AND price <= 99999",
    )


@pytest.fixture
def varchar_col() -> ColumnMetadata:
    return ColumnMetadata(name="name", data_type="VARCHAR(100)", nullable=True)


@pytest.fixture
def text_col() -> ColumnMetadata:
    return ColumnMetadata(name="bio", data_type="TEXT", nullable=True)


@pytest.fixture
def email_col() -> ColumnMetadata:
    return ColumnMetadata(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True)


@pytest.fixture
def phone_col() -> ColumnMetadata:
    return ColumnMetadata(name="phone", data_type="VARCHAR(20)", nullable=True)


@pytest.fixture
def date_col() -> ColumnMetadata:
    return ColumnMetadata(name="created_at", data_type="DATE", nullable=True)


@pytest.fixture
def bool_col() -> ColumnMetadata:
    return ColumnMetadata(name="active", data_type="BOOLEAN", nullable=False)


@pytest.fixture
def pk_col() -> ColumnMetadata:
    return ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True)


@pytest.fixture
def enum_col() -> ColumnMetadata:
    return ColumnMetadata(
        name="status", data_type="VARCHAR(20)", nullable=False,
        check_constraint="status IN ('active','inactive','pending')",
    )


@pytest.fixture
def percentage_col() -> ColumnMetadata:
    return ColumnMetadata(name="score", data_type="INTEGER", nullable=False)


@pytest.fixture
def simple_table(pk_col, int_col_checked, varchar_col, email_col) -> TableMetadata:
    return TableMetadata(
        name="users",
        columns=[pk_col, int_col_checked, varchar_col, email_col],
        primary_keys=["id"],
    )


@pytest.fixture
def simple_schema(simple_table) -> SchemaMetadata:
    return SchemaMetadata(tables=[simple_table])


@pytest.fixture
def multi_table_schema(
    int_col_checked, varchar_col, email_col, pk_col, date_col, float_col, bool_col,
) -> SchemaMetadata:
    return SchemaMetadata(
        tables=[
            TableMetadata(
                name="users",
                columns=[pk_col, int_col_checked, varchar_col, email_col],
                primary_keys=["id"],
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                    float_col,
                    date_col,
                    bool_col,
                ],
                primary_keys=["id"],
            ),
        ]
    )


def _parts_of(result: PartitionAnalysis, pt: PartitionType) -> list[Partition]:
    return [p for p in result.partitions if p.partition_type == pt]


def _col_parts(result: PartitionAnalysis, col_name: str) -> list[Partition]:
    return [p for p in result.partitions if p.column == col_name]


# ── Basic structure ───────────────────────────────────────────


class TestBasicAnalysis:
    def test_returns_analysis(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze(session_id="test-1")
        assert isinstance(result, PartitionAnalysis)

    def test_session_id(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze(session_id="abc")
        assert result.session_id == "abc"

    def test_total_partitions_matches(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        assert result.total_partitions == len(result.partitions)

    def test_summary_counts(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        total = sum(result.summary.values())
        assert total == result.total_partitions

    def test_tables_analyzed(self, multi_table_schema):
        engine = EquivalencePartitioningEngine(multi_table_schema)
        result = engine.analyze()
        assert result.tables_analyzed == 2

    def test_columns_analyzed(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        assert result.columns_analyzed > 0

    def test_empty_schema(self):
        schema = SchemaMetadata(tables=[])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        assert result.total_partitions == 0
        assert result.tables_analyzed == 0
        assert result.columns_analyzed == 0


# ── Numeric partitioning (CHECK constraint) ───────────────────


class TestNumericCheckPartitions:
    def test_has_valid_partition(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        age_valid = [p for p in _col_parts(result, "age") if p.partition_type == PartitionType.VALID]
        assert len(age_valid) >= 1
        # The valid range should be 18–60
        v = age_valid[0]
        assert v.range_low == 18
        assert v.range_high == 60

    def test_has_invalid_below(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        age_inv = [
            p for p in _col_parts(result, "age")
            if p.partition_type == PartitionType.INVALID and "< 18" in p.label
        ]
        assert len(age_inv) == 1

    def test_has_invalid_above(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        age_inv = [
            p for p in _col_parts(result, "age")
            if p.partition_type == PartitionType.INVALID and "> 60" in p.label
        ]
        assert len(age_inv) == 1

    def test_has_boundary_at_bounds(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        age_boundary = [p for p in _col_parts(result, "age") if p.partition_type == PartitionType.BOUNDARY]
        # Should have at lower, below lower, above lower, at upper, below upper, above upper, midpoint
        assert len(age_boundary) >= 7
        values = [p.sample_values[0] for p in age_boundary]
        assert 18 in values   # at lower
        assert 17 in values   # below lower
        assert 19 in values   # above lower
        assert 60 in values   # at upper
        assert 59 in values   # below upper
        assert 61 in values   # above upper

    def test_valid_samples_in_range(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        age_valid = [p for p in _col_parts(result, "age") if p.partition_type == PartitionType.VALID][0]
        for v in age_valid.sample_values:
            assert 18 <= v <= 60

    def test_invalid_below_samples(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        inv = [p for p in _col_parts(result, "age") if p.partition_type == PartitionType.INVALID and "< 18" in p.label][0]
        for v in inv.sample_values:
            assert v < 18


class TestNumericFloat:
    def test_float_check_partitions(self, float_col):
        table = TableMetadata(name="t", columns=[float_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        price_parts = _col_parts(result, "price")
        types = {p.partition_type for p in price_parts}
        assert PartitionType.VALID in types
        assert PartitionType.INVALID in types
        assert PartitionType.BOUNDARY in types


class TestNumericHeuristic:
    def test_age_heuristic_no_check(self):
        col = ColumnMetadata(name="age", data_type="INTEGER", nullable=False)
        table = TableMetadata(name="t", columns=[col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        age_parts = _col_parts(result, "age")
        valid = [p for p in age_parts if p.partition_type == PartitionType.VALID]
        assert len(valid) >= 1
        # Heuristic: 0–150
        assert valid[0].range_low == 0
        assert valid[0].range_high == 150

    def test_percentage_heuristic(self, percentage_col):
        table = TableMetadata(name="t", columns=[percentage_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        score_parts = _col_parts(result, "score")
        valid = [p for p in score_parts if p.partition_type == PartitionType.VALID]
        assert valid[0].range_low == 0
        assert valid[0].range_high == 100


# ── Enum partitioning ─────────────────────────────────────────


class TestEnumPartitions:
    def test_valid_enum(self, enum_col):
        table = TableMetadata(name="t", columns=[enum_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        status_parts = _col_parts(result, "status")
        valid = [p for p in status_parts if p.partition_type == PartitionType.VALID]
        assert len(valid) >= 1
        assert set(valid[0].sample_values) == {"active", "inactive", "pending"}

    def test_invalid_enum(self, enum_col):
        table = TableMetadata(name="t", columns=[enum_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        status_parts = _col_parts(result, "status")
        invalid = [p for p in status_parts if p.partition_type == PartitionType.INVALID]
        assert len(invalid) >= 1

    def test_boundary_enum(self, enum_col):
        table = TableMetadata(name="t", columns=[enum_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        status_parts = _col_parts(result, "status")
        boundary = [p for p in status_parts if p.partition_type == PartitionType.BOUNDARY]
        assert len(boundary) >= 2  # first and last
        labels = [p.sample_values[0] for p in boundary]
        assert "active" in labels
        assert "pending" in labels


# ── String partitioning ──────────────────────────────────────


class TestStringPartitions:
    def test_varchar_with_length(self, varchar_col):
        table = TableMetadata(name="t", columns=[varchar_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        name_parts = _col_parts(result, "name")
        types = {p.partition_type for p in name_parts}
        assert PartitionType.VALID in types
        assert PartitionType.INVALID in types
        assert PartitionType.BOUNDARY in types

    def test_text_no_length(self, text_col):
        table = TableMetadata(name="t", columns=[text_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        bio_parts = _col_parts(result, "bio")
        valid = [p for p in bio_parts if p.partition_type == PartitionType.VALID]
        assert len(valid) >= 1

    def test_email_heuristic(self, email_col):
        table = TableMetadata(name="t", columns=[email_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        email_parts = _col_parts(result, "email")
        types = {p.partition_type for p in email_parts}
        assert PartitionType.VALID in types
        assert PartitionType.INVALID in types
        assert PartitionType.BOUNDARY in types

    def test_phone_heuristic(self, phone_col):
        table = TableMetadata(name="t", columns=[phone_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        phone_parts = _col_parts(result, "phone")
        types = {p.partition_type for p in phone_parts}
        assert PartitionType.VALID in types
        assert PartitionType.INVALID in types

    def test_boundary_at_max_length(self, varchar_col):
        table = TableMetadata(name="t", columns=[varchar_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        name_boundary = [p for p in _col_parts(result, "name") if p.partition_type == PartitionType.BOUNDARY]
        sample_lens = [len(str(p.sample_values[0])) for p in name_boundary if p.sample_values]
        assert 100 in sample_lens  # exactly at max
        assert 1 in sample_lens    # single char


# ── Date & boolean partitioning ──────────────────────────────


class TestDatePartitions:
    def test_date_partitions(self, date_col):
        table = TableMetadata(name="t", columns=[date_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        date_parts = _col_parts(result, "created_at")
        types = {p.partition_type for p in date_parts}
        assert PartitionType.VALID in types
        assert PartitionType.INVALID in types
        assert PartitionType.BOUNDARY in types


class TestBooleanPartitions:
    def test_boolean_partitions(self, bool_col):
        table = TableMetadata(name="t", columns=[bool_col])
        schema = SchemaMetadata(tables=[table])
        engine = EquivalencePartitioningEngine(schema)
        result = engine.analyze()
        active_parts = _col_parts(result, "active")
        valid = [p for p in active_parts if p.partition_type == PartitionType.VALID]
        invalid = [p for p in active_parts if p.partition_type == PartitionType.INVALID]
        assert len(valid) >= 1
        assert len(invalid) >= 1
        assert True in valid[0].sample_values
        assert False in valid[0].sample_values


# ── Nullable partitioning ─────────────────────────────────────


class TestNullablePartitions:
    def test_nullable_column_valid_null(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        # "name" is nullable
        name_parts = _col_parts(result, "name")
        null_valid = [p for p in name_parts if p.partition_type == PartitionType.VALID and "NULL" in p.label]
        assert len(null_valid) == 1

    def test_not_null_column_invalid_null(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        # "age" is NOT NULL
        age_parts = _col_parts(result, "age")
        null_inv = [p for p in age_parts if p.partition_type == PartitionType.INVALID and "NULL" in p.label]
        assert len(null_inv) == 1

    def test_pk_no_null_partition(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        id_parts = _col_parts(result, "id")
        null_parts = [p for p in id_parts if "NULL" in p.label]
        assert len(null_parts) == 0


# ── Dataset generation ────────────────────────────────────────


class TestDatasetGeneration:
    def test_datasets_generated(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema, rows_per_partition=2)
        result = engine.analyze()
        assert len(result.datasets) >= 1
        assert result.total_generated_rows > 0

    def test_row_count_proportional(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema, rows_per_partition=2)
        result = engine.analyze()
        user_ds = [ds for ds in result.datasets if ds.table == "users"]
        assert len(user_ds) == 1
        user_parts = [p for p in result.partitions if p.table == "users"]
        expected_rows = len(user_parts) * 2
        assert user_ds[0].total_rows == expected_rows

    def test_rows_have_partition_metadata(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema, rows_per_partition=1)
        result = engine.analyze()
        for ds in result.datasets:
            for row in ds.rows:
                assert row.partition_label
                assert row.partition_type in (PartitionType.VALID, PartitionType.INVALID, PartitionType.BOUNDARY)
                assert isinstance(row.row, dict)

    def test_rows_have_all_columns(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema, rows_per_partition=1)
        result = engine.analyze()
        user_ds = [ds for ds in result.datasets if ds.table == "users"][0]
        for row in user_ds.rows:
            assert "id" in row.row
            assert "age" in row.row
            assert "name" in row.row
            assert "email" in row.row


# ── Visualization outputs ────────────────────────────────────


class TestVisualizations:
    def test_visualizations_generated(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        assert len(result.visualizations) > 0

    def test_visualization_structure(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        for viz in result.visualizations:
            assert isinstance(viz, PartitionVisualization)
            assert viz.table
            assert viz.column
            assert len(viz.partitions) > 0
            for vp in viz.partitions:
                assert "label" in vp
                assert "type" in vp
                assert "color" in vp
                assert "sample_count" in vp

    def test_viz_colors(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        colors_seen = set()
        for viz in result.visualizations:
            for vp in viz.partitions:
                colors_seen.add(vp["color"])
        assert "#22c55e" in colors_seen  # valid (green)
        assert "#ef4444" in colors_seen  # invalid (red)
        assert "#f59e0b" in colors_seen  # boundary (amber)


# ── Column summaries ─────────────────────────────────────────


class TestColumnSummaries:
    def test_summaries_exist(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        assert len(result.column_summaries) > 0

    def test_summary_counts(self, simple_schema):
        engine = EquivalencePartitioningEngine(simple_schema)
        result = engine.analyze()
        for cs in result.column_summaries:
            assert isinstance(cs, PartitionColumnSummary)
            assert cs.total_partitions == cs.valid_count + cs.invalid_count + cs.boundary_count
            col_parts = [p for p in result.partitions if p.table == cs.table and p.column == cs.column]
            assert cs.total_partitions == len(col_parts)


# ── Router endpoint ──────────────────────────────────────────


class TestPartitionRouter:
    @pytest.fixture(autouse=True)
    def _clean(self):
        yield
        store.clear()

    def _create_session(self, schema: SchemaMetadata) -> str:
        sess = store.create()
        sess.schema = schema
        return sess.session_id

    def test_analyze_success(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/partitions/analyze?session_id={sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_partitions"] > 0
        assert "partitions" in data
        assert "datasets" in data
        assert "visualizations" in data
        assert "summary" in data

    def test_session_not_found(self):
        resp = client.post("/partitions/analyze?session_id=nonexistent")
        assert resp.status_code == 404

    def test_no_schema(self):
        sess = store.create()
        resp = client.post(f"/partitions/analyze?session_id={sess.session_id}")
        assert resp.status_code == 400

    def test_custom_rows_per_partition(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/partitions/analyze?session_id={sid}&rows_per_partition=5")
        assert resp.status_code == 200
        data = resp.json()
        # Verify more rows generated
        assert data["total_generated_rows"] > 0

    def test_response_matches_model(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/partitions/analyze?session_id={sid}")
        data = resp.json()
        analysis = PartitionAnalysis(**data)
        assert analysis.total_partitions == data["total_partitions"]
        assert len(analysis.partitions) == len(data["partitions"])

    def test_all_three_partition_types_present(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/partitions/analyze?session_id={sid}")
        data = resp.json()
        types = set(p["partition_type"] for p in data["partitions"])
        assert "valid" in types
        assert "invalid" in types
        assert "boundary" in types


# ── Dataset Split Config Tests ────────────────────────────────


class TestDatasetSplitConfig:
    """Tests for the DatasetSplitConfig model validation."""

    def test_valid_three_way_split(self):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=70, invalid_pct=20, boundary_pct=10)
        assert cfg.valid_pct == 70
        assert cfg.invalid_pct == 20
        assert cfg.boundary_pct == 10

    def test_default_split_is_valid(self):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig()
        assert cfg.valid_pct == 80
        assert cfg.invalid_pct == 10
        assert cfg.boundary_pct == 10

    def test_invalid_sum_raises(self):
        from app.models.partition import DatasetSplitConfig
        with pytest.raises(Exception):
            DatasetSplitConfig(valid_pct=50, invalid_pct=20, boundary_pct=10)

    def test_negative_pct_raises(self):
        from app.models.partition import DatasetSplitConfig
        with pytest.raises(Exception):
            DatasetSplitConfig(valid_pct=-10, invalid_pct=60, boundary_pct=50)

    def test_four_way_split(self):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=60, invalid_pct=15, boundary_pct=15, duplicate_pct=10)
        assert cfg.valid_pct == 60
        assert cfg.invalid_pct == 15
        assert cfg.duplicate_pct == 10

    def test_four_way_invalid_sum(self):
        from app.models.partition import DatasetSplitConfig
        with pytest.raises(Exception):
            DatasetSplitConfig(valid_pct=60, invalid_pct=20, boundary_pct=20, duplicate_pct=10)

    def test_all_valid_split(self):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=100, invalid_pct=0, boundary_pct=0)
        assert cfg.valid_pct == 100


class TestSplitDatasetGeneration:
    """Tests for proportional dataset generation using split config."""

    @pytest.fixture
    def schema_with_types(self):
        """Schema that generates all 3 partition types."""
        return SchemaMetadata(tables=[
            TableMetadata(name="users", columns=[
                ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                ColumnMetadata(
                    name="age", data_type="INTEGER", nullable=False,
                    check_constraint="age >= 18 AND age <= 65",
                ),
            ]),
        ])

    def test_split_produces_proportional_rows(self, schema_with_types):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=80, invalid_pct=10, boundary_pct=10)
        engine = EquivalencePartitioningEngine(
            schema=schema_with_types,
            split_config=cfg,
            total_rows=100,
        )
        analysis = engine.analyze(session_id="test")
        assert analysis.total_generated_rows > 0
        assert analysis.split_config is not None
        assert analysis.split_config.valid_pct == 80

    def test_split_rows_distribution(self, schema_with_types):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=60, invalid_pct=20, boundary_pct=20)
        engine = EquivalencePartitioningEngine(
            schema=schema_with_types,
            split_config=cfg,
            total_rows=100,
        )
        analysis = engine.analyze(session_id="test")
        # Count rows by type
        for ds in analysis.datasets:
            valid_rows = [r for r in ds.rows if r.partition_type == PartitionType.VALID]
            invalid_rows = [r for r in ds.rows if r.partition_type == PartitionType.INVALID]
            boundary_rows = [r for r in ds.rows if r.partition_type == PartitionType.BOUNDARY]
            # Valid should have the most rows
            if valid_rows and invalid_rows:
                assert len(valid_rows) >= len(invalid_rows)

    def test_no_split_uses_legacy(self, schema_with_types):
        engine = EquivalencePartitioningEngine(
            schema=schema_with_types,
            rows_per_partition=5,
        )
        analysis = engine.analyze(session_id="test")
        assert analysis.split_config is None
        assert analysis.total_generated_rows > 0

    def test_split_with_total_rows_1(self, schema_with_types):
        from app.models.partition import DatasetSplitConfig
        cfg = DatasetSplitConfig(valid_pct=100, invalid_pct=0, boundary_pct=0)
        engine = EquivalencePartitioningEngine(
            schema=schema_with_types,
            split_config=cfg,
            total_rows=1,
        )
        analysis = engine.analyze(session_id="test")
        assert analysis.total_generated_rows >= 1


class TestSplitRouter:
    """Tests for the router with split query params."""

    def _create_session(self, schema):
        sess = store.create()
        sess.schema = schema
        return sess.session_id

    @pytest.fixture
    def simple_schema(self):
        return SchemaMetadata(tables=[
            TableMetadata(name="products", columns=[
                ColumnMetadata(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                ColumnMetadata(
                    name="price", data_type="DECIMAL(10,2)", nullable=False,
                    check_constraint="price >= 0 AND price <= 9999",
                ),
            ]),
        ])

    def test_split_params_accepted(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(
            f"/partitions/analyze?session_id={sid}&total_rows=50&valid_pct=60&invalid_pct=20&boundary_pct=20"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["split_config"] is not None
        assert data["split_config"]["valid_pct"] == 60

    def test_invalid_split_sum_returns_422(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(
            f"/partitions/analyze?session_id={sid}&total_rows=50&valid_pct=60&invalid_pct=20&boundary_pct=30"
        )
        assert resp.status_code == 422

    def test_no_total_rows_uses_legacy(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(f"/partitions/analyze?session_id={sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["split_config"] is None

    def test_split_total_rows_reflected(self, simple_schema):
        sid = self._create_session(simple_schema)
        resp = client.post(
            f"/partitions/analyze?session_id={sid}&total_rows=200&valid_pct=80&invalid_pct=10&boundary_pct=10"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_generated_rows"] > 0
