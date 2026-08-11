"""Equivalence partitioning engine.

Analyzes a schema and automatically divides each column's input space
into valid, invalid, and boundary equivalence partitions.  Generates
proportional sample datasets from each partition and produces
visualization-ready outputs.

Partition derivation sources:
  - CHECK constraints (numeric ranges, enum sets)
  - Data-type boundaries (INT ranges, VARCHAR lengths)
  - Nullability (nullable vs NOT NULL)
  - Column-name heuristics (age, email, phone, date, etc.)
  - PK / UNIQUE constraints
"""

from __future__ import annotations

import logging
import random
import re
import string
from datetime import date, timedelta
from typing import Any

from faker import Faker

from app.models.partition import (
    DatasetSplitConfig,
    Partition,
    PartitionAnalysis,
    PartitionColumnSummary,
    PartitionDataset,
    PartitionDatasetRow,
    PartitionType,
    PartitionVisualization,
)
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.utils.sql_types import (
    base_type as _base_type,
    extract_enum_from_check as _extract_enum_from_check,
    extract_max_length as _extract_max_length,
)

logger = logging.getLogger(__name__)
fake = Faker()

# ── Type-specific ranges ──────────────────────────────────────

_INT_RANGES: dict[str, tuple[int, int]] = {
    "TINYINT": (-128, 255),
    "SMALLINT": (-32768, 32767),
    "INT": (-2147483648, 2147483647),
    "INTEGER": (-2147483648, 2147483647),
    "BIGINT": (-9223372036854775808, 9223372036854775807),
}

# ── Heuristic age-like columns ────────────────────────────────

_AGE_PATTERN = re.compile(r"\bage\b", re.I)
_PRICE_PATTERN = re.compile(r"price|amount|cost|salary|income|balance|fee|total", re.I)
_PERCENTAGE_PATTERN = re.compile(r"percent|rate|ratio|score", re.I)
_QUANTITY_PATTERN = re.compile(r"quantity|qty|count|stock", re.I)

# ── Visualization colors by type ─────────────────────────────

_COLORS: dict[str, str] = {
    "valid": "#22c55e",       # green-500
    "invalid": "#ef4444",     # red-500
    "boundary": "#f59e0b",    # amber-500
}

_SAMPLES_PER_PARTITION = 5  # how many sample values to generate


class EquivalencePartitioningEngine:
    """Analyze a schema and produce equivalence partitions per column."""

    def __init__(
        self,
        schema: SchemaMetadata,
        rows_per_partition: int = 3,
        split_config: DatasetSplitConfig | None = None,
        total_rows: int | None = None,
    ) -> None:
        self._schema = schema
        self._rows_per_partition = max(1, rows_per_partition)
        self._split_config = split_config
        self._total_rows = total_rows
        self._partitions: list[Partition] = []

    # ── Public API ────────────────────────────────────────────

    def analyze(self, session_id: str = "") -> PartitionAnalysis:
        """Run the full partitioning analysis."""
        self._partitions = []

        for table in self._schema.tables:
            for col in table.columns:
                self._partition_column(table, col)

        # Build aggregates
        summary = self._build_summary()
        col_summaries = self._build_column_summaries()
        datasets = self._generate_datasets()
        visualizations = self._build_visualizations()

        analyzed_cols = len({(p.table, p.column) for p in self._partitions})
        analyzed_tables = len({p.table for p in self._partitions})
        total_rows = sum(ds.total_rows for ds in datasets)

        return PartitionAnalysis(
            session_id=session_id,
            partitions=self._partitions,
            column_summaries=col_summaries,
            datasets=datasets,
            visualizations=visualizations,
            summary=summary,
            total_partitions=len(self._partitions),
            tables_analyzed=analyzed_tables,
            columns_analyzed=analyzed_cols,
            total_generated_rows=total_rows,
            split_config=self._split_config,
        )

    # ── Column-level dispatch ─────────────────────────────────

    def _partition_column(self, table: TableMetadata, col: ColumnMetadata) -> None:
        base = _base_type(col.data_type)
        enums = _extract_enum_from_check(col.check_constraint)

        if enums:
            self._partition_enum(table, col, enums)
        elif base in ("integer", "float"):
            self._partition_numeric(table, col, base)
        elif base == "string":
            self._partition_string(table, col)
        elif base in ("date", "datetime"):
            self._partition_date(table, col)
        elif base == "boolean":
            self._partition_boolean(table, col)

        # Nullable partition (applies to all types)
        self._partition_nullable(table, col)

    # ── Numeric partitioning ──────────────────────────────────

    def _partition_numeric(
        self, table: TableMetadata, col: ColumnMetadata, base: str
    ) -> None:
        check = col.check_constraint or ""
        is_int = base == "integer"
        cast = int if is_int else float

        # Extract explicit bounds from CHECK
        lo, hi = self._extract_check_bounds(check, is_int)

        # Heuristic bounds from column name
        if lo is None and hi is None:
            lo, hi = self._infer_heuristic_bounds(col.name, is_int)

        # Type-based bounds fallback
        if lo is None and hi is None and is_int:
            type_upper = col.data_type.upper().split("(")[0].strip()
            type_range = _INT_RANGES.get(type_upper)
            if type_range:
                lo, hi = cast(type_range[0]), cast(type_range[1])

        # Default numeric range
        if lo is None:
            lo = cast(0)
        if hi is None:
            hi = cast(1000)

        # ── Valid partition ──
        valid_lo = lo
        valid_hi = hi
        step = 1 if is_int else 0.01
        valid_samples = self._sample_range(valid_lo, valid_hi, is_int, _SAMPLES_PER_PARTITION)
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name} ∈ [{valid_lo}, {valid_hi}]",
            description=f"Valid range: {valid_lo} to {valid_hi}",
            range_low=valid_lo,
            range_high=valid_hi,
            sample_values=valid_samples,
            data_type=col.data_type,
            constraint_source=self._constraint_source(col),
        ))

        # ── Invalid partition: below lower bound ──
        below_lo = cast(lo - 1000) if is_int else lo - 1000.0
        below_hi = cast(lo - step)
        invalid_below = self._sample_range(below_lo, below_hi, is_int, _SAMPLES_PER_PARTITION)
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name} < {lo}",
            description=f"Below minimum: values less than {lo}",
            range_low=below_lo,
            range_high=below_hi,
            sample_values=invalid_below,
            data_type=col.data_type,
            constraint_source=self._constraint_source(col),
        ))

        # ── Invalid partition: above upper bound ──
        above_lo = cast(hi + step)
        above_hi = cast(hi + 1000) if is_int else hi + 1000.0
        invalid_above = self._sample_range(above_lo, above_hi, is_int, _SAMPLES_PER_PARTITION)
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name} > {hi}",
            description=f"Above maximum: values greater than {hi}",
            range_low=above_lo,
            range_high=above_hi,
            sample_values=invalid_above,
            data_type=col.data_type,
            constraint_source=self._constraint_source(col),
        ))

        # ── Boundary partitions ──
        boundaries = self._compute_boundaries(lo, hi, is_int)
        for val, desc in boundaries:
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.BOUNDARY,
                label=f"{col.name} = {val}",
                description=desc,
                range_low=val,
                range_high=val,
                sample_values=[val],
                data_type=col.data_type,
                constraint_source=self._constraint_source(col),
            ))

    def _extract_check_bounds(
        self, check: str, is_int: bool
    ) -> tuple[int | float | None, int | float | None]:
        """Extract lower/upper bounds from CHECK constraint text."""
        lo: int | float | None = None
        hi: int | float | None = None
        cast = int if is_int else float

        # >=
        m = re.search(r">=\s*([\d.]+)", check)
        if m:
            lo = cast(float(m.group(1)))
        else:
            m = re.search(r">\s*([\d.]+)", check)
            if m:
                lo = cast(float(m.group(1))) + (1 if is_int else 0.01)

        # <=
        m = re.search(r"<=\s*([\d.]+)", check)
        if m:
            hi = cast(float(m.group(1)))
        else:
            m = re.search(r"<\s*([\d.]+)", check)
            if m:
                hi = cast(float(m.group(1))) - (1 if is_int else 0.01)

        return lo, hi

    def _infer_heuristic_bounds(
        self, col_name: str, is_int: bool
    ) -> tuple[int | float | None, int | float | None]:
        """Infer bounds from column name heuristics."""
        cast = int if is_int else float
        if _AGE_PATTERN.search(col_name):
            return cast(0), cast(150)
        if _PRICE_PATTERN.search(col_name):
            return cast(0), cast(999999)
        if _PERCENTAGE_PATTERN.search(col_name):
            return cast(0), cast(100)
        if _QUANTITY_PATTERN.search(col_name):
            return cast(0), cast(100000)
        return None, None

    def _compute_boundaries(
        self, lo: int | float, hi: int | float, is_int: bool
    ) -> list[tuple[int | float, str]]:
        """Compute boundary values for a numeric range."""
        step = 1 if is_int else 0.01
        cast = int if is_int else float
        boundaries: list[tuple[int | float, str]] = [
            (cast(lo), f"At lower bound ({lo})"),
            (cast(lo - step), f"Just below lower bound ({lo - step})"),
            (cast(lo + step), f"Just above lower bound ({lo + step})"),
            (cast(hi), f"At upper bound ({hi})"),
            (cast(hi - step), f"Just below upper bound ({hi - step})"),
            (cast(hi + step), f"Just above upper bound ({hi + step})"),
        ]
        # Add midpoint
        mid = cast((lo + hi) / 2) if is_int else round((lo + hi) / 2, 2)
        boundaries.append((mid, f"Midpoint ({mid})"))
        return boundaries

    def _sample_range(
        self, lo: int | float, hi: int | float, is_int: bool, count: int
    ) -> list[int | float]:
        """Generate sample values within a range."""
        if lo > hi:
            lo, hi = hi, lo
        samples: list[int | float] = []
        for _ in range(count):
            if is_int:
                samples.append(random.randint(int(lo), int(hi)))
            else:
                samples.append(round(random.uniform(float(lo), float(hi)), 2))
        return samples

    # ── Enum partitioning ─────────────────────────────────────

    def _partition_enum(
        self, table: TableMetadata, col: ColumnMetadata, enums: list[str]
    ) -> None:
        # Valid: each enum value is a valid partition
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name} ∈ {{{', '.join(enums)}}}",
            description=f"Valid enum values: {', '.join(enums)}",
            sample_values=list(enums),
            data_type=col.data_type,
            constraint_source="enum",
        ))

        # Invalid: values not in enum
        invalid_values = ["__INVALID__", "UNKNOWN", ""]
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name} ∉ {{{', '.join(enums)}}}",
            description=f"Values outside allowed set",
            sample_values=invalid_values,
            data_type=col.data_type,
            constraint_source="enum",
        ))

        # Boundary: first and last enum values
        if len(enums) >= 2:
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.BOUNDARY,
                label=f"{col.name} = '{enums[0]}' (first enum)",
                description=f"First enumerated value",
                sample_values=[enums[0]],
                data_type=col.data_type,
                constraint_source="enum",
            ))
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.BOUNDARY,
                label=f"{col.name} = '{enums[-1]}' (last enum)",
                description=f"Last enumerated value",
                sample_values=[enums[-1]],
                data_type=col.data_type,
                constraint_source="enum",
            ))

    # ── String partitioning ───────────────────────────────────

    def _partition_string(
        self, table: TableMetadata, col: ColumnMetadata
    ) -> None:
        max_len = _extract_max_length(col.data_type)
        name_lower = col.name.lower()

        # Email heuristic
        if re.search(r"email", name_lower):
            self._partition_email(table, col)
            return

        # Phone heuristic
        if re.search(r"phone|mobile|cell", name_lower):
            self._partition_phone(table, col)
            return

        # Generic string with length constraint
        if max_len:
            # Valid: strings within max_len
            valid_samples = [
                fake.pystr(min_chars=1, max_chars=min(max_len, 20))
                for _ in range(_SAMPLES_PER_PARTITION)
            ]
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.VALID,
                label=f"{col.name}: 1 to {max_len} chars",
                description=f"String within max length ({max_len})",
                range_low=1,
                range_high=max_len,
                sample_values=valid_samples,
                data_type=col.data_type,
                constraint_source="type",
            ))

            # Invalid: empty string and over-length
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.INVALID,
                label=f"{col.name}: > {max_len} chars",
                description=f"String exceeding max length",
                range_low=max_len + 1,
                sample_values=["x" * (max_len + 10)],
                data_type=col.data_type,
                constraint_source="type",
            ))
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.INVALID,
                label=f"{col.name}: empty string",
                description=f"Empty string value",
                sample_values=[""],
                data_type=col.data_type,
                constraint_source="type",
            ))

            # Boundary
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.BOUNDARY,
                label=f"{col.name}: exactly {max_len} chars",
                description=f"String at exact max length",
                range_low=max_len,
                range_high=max_len,
                sample_values=["x" * max_len],
                data_type=col.data_type,
                constraint_source="type",
            ))
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.BOUNDARY,
                label=f"{col.name}: 1 char",
                description=f"Single character string",
                range_low=1,
                range_high=1,
                sample_values=["a"],
                data_type=col.data_type,
                constraint_source="type",
            ))
        else:
            # No length constraint — simple valid/invalid
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.VALID,
                label=f"{col.name}: non-empty string",
                description=f"Any non-empty string",
                sample_values=[fake.word() for _ in range(_SAMPLES_PER_PARTITION)],
                data_type=col.data_type,
                constraint_source="type",
            ))
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.INVALID,
                label=f"{col.name}: empty string",
                description=f"Empty string value",
                sample_values=[""],
                data_type=col.data_type,
                constraint_source="type",
            ))

    def _partition_email(self, table: TableMetadata, col: ColumnMetadata) -> None:
        valid = [fake.email() for _ in range(_SAMPLES_PER_PARTITION)]
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name}: valid email format",
            description="Emails matching user@domain.tld pattern",
            sample_values=valid,
            data_type=col.data_type,
            constraint_source="heuristic",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name}: invalid email format",
            description="Strings that are not valid emails",
            sample_values=["plainaddress", "@missing.com", "user@", "a b@c.com"],
            data_type=col.data_type,
            constraint_source="heuristic",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.BOUNDARY,
            label=f"{col.name}: edge-case emails",
            description="Minimum valid / maximum length emails",
            sample_values=["a@b.co", "x" * 64 + "@example.com"],
            data_type=col.data_type,
            constraint_source="heuristic",
        ))

    def _partition_phone(self, table: TableMetadata, col: ColumnMetadata) -> None:
        valid = [fake.phone_number() for _ in range(_SAMPLES_PER_PARTITION)]
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name}: valid phone numbers",
            description="Phone numbers in acceptable formats",
            sample_values=valid,
            data_type=col.data_type,
            constraint_source="heuristic",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name}: invalid phone numbers",
            description="Strings that are not valid phone numbers",
            sample_values=["abc", "!@#", "12"],
            data_type=col.data_type,
            constraint_source="heuristic",
        ))

    # ── Date partitioning ─────────────────────────────────────

    def _partition_date(self, table: TableMetadata, col: ColumnMetadata) -> None:
        d_start = date(2000, 1, 1)
        d_end = date(2030, 12, 31)
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name}: reasonable dates",
            description="Dates in 2000–2030 range",
            range_low="2000-01-01",
            range_high="2030-12-31",
            sample_values=[str(fake.date_between_dates(
                date_start=d_start, date_end=d_end,
            )) for _ in range(_SAMPLES_PER_PARTITION)],
            data_type=col.data_type,
            constraint_source="type",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name}: invalid dates",
            description="Non-date strings and impossible dates",
            sample_values=["not-a-date", "2025-13-45", "0000-00-00"],
            data_type=col.data_type,
            constraint_source="type",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.BOUNDARY,
            label=f"{col.name}: boundary dates",
            description="Epoch, far-future, and year-2000 dates",
            sample_values=["1970-01-01", "2099-12-31", "2000-01-01"],
            data_type=col.data_type,
            constraint_source="type",
        ))

    # ── Boolean partitioning ──────────────────────────────────

    def _partition_boolean(self, table: TableMetadata, col: ColumnMetadata) -> None:
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.VALID,
            label=f"{col.name}: true/false",
            description="Valid boolean values",
            sample_values=[True, False],
            data_type=col.data_type,
            constraint_source="type",
        ))
        self._partitions.append(Partition(
            table=table.name,
            column=col.name,
            partition_type=PartitionType.INVALID,
            label=f"{col.name}: non-boolean",
            description="Values that are not boolean",
            sample_values=["maybe", 42, ""],
            data_type=col.data_type,
            constraint_source="type",
        ))

    # ── Nullable partitioning ─────────────────────────────────

    def _partition_nullable(self, table: TableMetadata, col: ColumnMetadata) -> None:
        if col.nullable:
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.VALID,
                label=f"{col.name}: NULL (allowed)",
                description="NULL is valid — column is nullable",
                sample_values=[None],
                data_type=col.data_type,
                constraint_source="nullable",
            ))
        elif not col.is_primary_key:
            self._partitions.append(Partition(
                table=table.name,
                column=col.name,
                partition_type=PartitionType.INVALID,
                label=f"{col.name}: NULL (disallowed)",
                description="NULL is invalid — column is NOT NULL",
                sample_values=[None],
                data_type=col.data_type,
                constraint_source="nullable",
            ))

    # ── Dataset generation ────────────────────────────────────

    def _generate_datasets(self) -> list[PartitionDataset]:
        """Generate proportional datasets from partitions, grouped by table."""
        table_map: dict[str, list[Partition]] = {}
        for p in self._partitions:
            table_map.setdefault(p.table, []).append(p)

        datasets: list[PartitionDataset] = []
        for table_name, parts in table_map.items():
            table_meta = self._find_table(table_name)
            if not table_meta:
                continue

            rows: list[PartitionDatasetRow] = []

            if self._split_config and self._total_rows:
                # Proportional allocation by partition type
                rows = self._generate_split_rows(table_name, parts, table_meta)
            else:
                # Legacy: equal rows per partition
                for p in parts:
                    n = self._rows_per_partition
                    for i in range(n):
                        val = p.sample_values[i % len(p.sample_values)] if p.sample_values else None
                        row_data = self._build_row_from_partition(table_meta, p, val)
                        rows.append(PartitionDatasetRow(
                            table=table_name,
                            partition_label=p.label,
                            partition_type=p.partition_type,
                            row=row_data,
                        ))

            datasets.append(PartitionDataset(
                table=table_name,
                rows=rows,
                total_rows=len(rows),
            ))

        return datasets

    def _generate_split_rows(
        self,
        table_name: str,
        parts: list[Partition],
        table_meta: TableMetadata,
    ) -> list[PartitionDatasetRow]:
        """Generate rows distributed according to split_config percentages."""
        assert self._split_config is not None  # noqa: S101
        assert self._total_rows is not None  # noqa: S101

        # Group partitions by type
        type_groups: dict[PartitionType, list[Partition]] = {
            PartitionType.VALID: [],
            PartitionType.INVALID: [],
            PartitionType.BOUNDARY: [],
            PartitionType.DUPLICATE: [],
        }
        for p in parts:
            type_groups[p.partition_type].append(p)

        # Compute row allocation per type
        pct_map = {
            PartitionType.VALID: self._split_config.valid_pct,
            PartitionType.INVALID: self._split_config.invalid_pct,
            PartitionType.BOUNDARY: self._split_config.boundary_pct,
            PartitionType.DUPLICATE: self._split_config.duplicate_pct,
        }

        rows: list[PartitionDatasetRow] = []
        for ptype, pct in pct_map.items():
            group = type_groups[ptype]
            if not group:
                continue
            type_rows = max(1, int(round(self._total_rows * pct / 100.0)))
            # Distribute evenly among partitions of this type
            per_partition = max(1, type_rows // len(group))
            remainder = type_rows - (per_partition * len(group))

            for idx, p in enumerate(group):
                n = per_partition + (1 if idx < remainder else 0)
                for i in range(n):
                    val = p.sample_values[i % len(p.sample_values)] if p.sample_values else None
                    row_data = self._build_row_from_partition(table_meta, p, val)
                    rows.append(PartitionDatasetRow(
                        table=table_name,
                        partition_label=p.label,
                        partition_type=p.partition_type,
                        row=row_data,
                    ))

        return rows

    def _build_row_from_partition(
        self, table: TableMetadata, partition: Partition, target_value: Any,
    ) -> dict[str, Any]:
        """Build a full row for a table, using target_value for the partitioned column."""
        row: dict[str, Any] = {}
        for col in table.columns:
            if col.name == partition.column:
                row[col.name] = target_value
            else:
                row[col.name] = self._default_value(col)
        return row

    def _default_value(self, col: ColumnMetadata) -> Any:
        """Generate a simple default value for a non-target column."""
        base = _base_type(col.data_type)
        if col.is_primary_key and base == "integer":
            return random.randint(1, 999999)
        if base == "integer":
            return random.randint(1, 100)
        if base == "float":
            return round(random.uniform(1.0, 100.0), 2)
        if base == "boolean":
            return random.choice([True, False])
        if base in ("date", "datetime"):
            return str(fake.date_between_dates(date_start=date(2020, 1, 1), date_end=date(2025, 12, 31)))
        enums = _extract_enum_from_check(col.check_constraint)
        if enums:
            return random.choice(enums)
        return fake.word()

    # ── Visualization outputs ─────────────────────────────────

    def _build_visualizations(self) -> list[PartitionVisualization]:
        """Build visualization-ready data grouped by column."""
        col_map: dict[tuple[str, str], list[Partition]] = {}
        for p in self._partitions:
            col_map.setdefault((p.table, p.column), []).append(p)

        visualizations: list[PartitionVisualization] = []
        for (table, column), parts in col_map.items():
            viz_parts: list[dict[str, Any]] = []
            for p in parts:
                viz_parts.append({
                    "label": p.label,
                    "type": p.partition_type.value,
                    "low": p.range_low,
                    "high": p.range_high,
                    "sample_count": len(p.sample_values),
                    "color": _COLORS.get(p.partition_type.value, "#6b7280"),
                })
            visualizations.append(PartitionVisualization(
                table=table,
                column=column,
                data_type=parts[0].data_type if parts else "",
                partitions=viz_parts,
            ))

        return visualizations

    # ── Summary helpers ───────────────────────────────────────

    def _build_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for p in self._partitions:
            summary[p.partition_type.value] = summary.get(p.partition_type.value, 0) + 1
        return summary

    def _build_column_summaries(self) -> list[PartitionColumnSummary]:
        col_map: dict[tuple[str, str], PartitionColumnSummary] = {}
        for p in self._partitions:
            key = (p.table, p.column)
            if key not in col_map:
                col_map[key] = PartitionColumnSummary(
                    table=p.table,
                    column=p.column,
                    data_type=p.data_type,
                )
            s = col_map[key]
            s.total_partitions += 1
            if p.partition_type == PartitionType.VALID:
                s.valid_count += 1
            elif p.partition_type == PartitionType.INVALID:
                s.invalid_count += 1
            elif p.partition_type == PartitionType.BOUNDARY:
                s.boundary_count += 1
        return list(col_map.values())

    def _find_table(self, name: str) -> TableMetadata | None:
        for t in self._schema.tables:
            if t.name == name:
                return t
        return None

    def _constraint_source(self, col: ColumnMetadata) -> str:
        if col.check_constraint:
            return "check"
        if _extract_enum_from_check(col.check_constraint):
            return "enum"
        return "type"
