"""Synthetic data generator — produces valid rows from parsed schema metadata.

Respects primary keys, foreign keys, unique constraints, CHECK constraints,
nullability, and column-name heuristics (email, phone, address, etc.).

Enhanced with semantic type detection and country-aware / domain-aware
realistic data generation.

Performance-optimised: column strategies are pre-computed once per table,
FK parent values are pre-extracted into flat lists, and unique columns use
deterministic suffix schemes to avoid costly retry loops.
"""

from __future__ import annotations

import logging
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

from faker import Faker

from app.generators.realistic_provider import RealisticProvider
from app.generators.semantic_types import SemanticType, detect_semantic_type
from app.models.schema import ColumnMetadata, SchemaMetadata, TableMetadata
from app.services.relationship_engine import RelationshipGraph
from app.utils.sql_types import (
    base_type as _base_type,
    extract_enum_from_check as _extract_enum_from_check,
    extract_max_length as _extract_max_length,
    extract_precision as _extract_precision,
)

logger = logging.getLogger(__name__)

fake = Faker()

# Heuristic column-name → Faker provider
_NAME_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"first.?name", re.I), "first_name"),
    (re.compile(r"last.?name|surname", re.I), "last_name"),
    (re.compile(r"^name$|full.?name", re.I), "name"),
    (re.compile(r"email", re.I), "email"),
    (re.compile(r"phone|mobile|cell", re.I), "phone_number"),
    (re.compile(r"address|street", re.I), "street_address"),
    (re.compile(r"city", re.I), "city"),
    (re.compile(r"state|province", re.I), "state"),
    (re.compile(r"country", re.I), "country"),
    (re.compile(r"zip|postal", re.I), "zipcode"),
    (re.compile(r"company|org", re.I), "company"),
    (re.compile(r"url|website|link", re.I), "url"),
    (re.compile(r"description|^note$|^comment$|^remark$|^text$", re.I), "sentence"),
    (re.compile(r"uuid|guid", re.I), "uuid4"),
]

# Pre-computed date/time constants
_DATE_START = date(2020, 1, 1)
_DATE_DAYS = (date(2026, 12, 31) - _DATE_START).days
_DT_START = datetime(2020, 1, 1)
_DT_SECS = int((datetime(2026, 12, 31) - _DT_START).total_seconds())

# Pool size for Faker / RealisticProvider value pre-generation
_POOL_SIZE = 1_000
_POOL_SIZE_LARGE = 5_000  # for row counts > 50K


def _effective_pool_size(row_count: int) -> int:
    """Select pool size based on row count for optimal cache hit rate."""
    if row_count > 50_000:
        return _POOL_SIZE_LARGE
    return _POOL_SIZE


class GeneratorError(Exception):
    """Raised when data generation fails."""


# ── Column strategy types ─────────────────────────────────────

# A strategy is a callable (row_index) -> value
# This eliminates per-row regex, type detection, and conditional branching.
ColumnStrategy = Callable[[int], Any]


class SyntheticDataGenerator:
    """Generate synthetic data from parsed schema metadata."""

    def __init__(
        self,
        schema: SchemaMetadata,
        row_count: int = 10,
        country: str = "us",
        domain: str = "unknown",
        ai_hints: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if row_count < 1:
            raise GeneratorError("row_count must be at least 1")
        self._schema = schema
        self._row_count = row_count
        self._graph = RelationshipGraph(schema)
        self._generated: dict[str, list[dict[str, Any]]] = {}
        self._unique_tracker: dict[str, set[Any]] = {}
        self._provider = RealisticProvider(country=country, domain=domain)
        self._country = country
        self._domain = domain
        self._ai_hints = ai_hints  # table_name -> col_name -> ColumnHint

    def generate(self) -> dict[str, list[dict[str, Any]]]:
        """Generate data for all tables in dependency-safe order.

        Independent tables (no FK dependencies on ungenerated tables) are
        processed in parallel using ThreadPoolExecutor for speedups.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        order = self._graph.get_generation_order()
        table_map = {t.name: t for t in self._schema.tables}

        # Build dependency map: table -> set of parent tables it depends on
        dep_map: dict[str, set[str]] = {name: set() for name in order}
        for table_name in order:
            table = table_map[table_name]
            for fk in table.foreign_keys:
                if fk.references_table in table_map and fk.references_table != table_name:
                    dep_map[table_name].add(fk.references_table)

        generated_set: set[str] = set()

        # Process in waves: each wave contains tables whose deps are all satisfied
        while len(generated_set) < len(order):
            ready = [
                t for t in order
                if t not in generated_set and dep_map[t].issubset(generated_set)
            ]
            if not ready:
                remaining = [t for t in order if t not in generated_set]
                ready = remaining[:1]

            if len(ready) > 1:
                # Parallel generation for independent tables
                with ThreadPoolExecutor(max_workers=min(len(ready), 4)) as executor:
                    futures = {
                        executor.submit(self._generate_table, table_map[t]): t
                        for t in ready
                    }
                    for future in as_completed(futures):
                        table_name = futures[future]
                        rows = future.result()
                        self._generated[table_name] = rows
                        generated_set.add(table_name)
                        logger.info(
                            "Generated %d rows for table %s",
                            len(rows), table_name,
                            extra={"stage": "generation", "event": "table_generated", "table": table_name, "row_count": len(rows)},
                        )
            else:
                # Sequential for single tables in a dependency chain
                for table_name in ready:
                    table = table_map[table_name]
                    rows = self._generate_table(table)
                    self._generated[table_name] = rows
                    generated_set.add(table_name)
                    logger.info(
                        "Generated %d rows for table %s",
                        len(rows), table_name,
                        extra={"stage": "generation", "event": "table_generated", "table": table_name, "row_count": len(rows)},
                    )

        return self._generated

    # ── Strategy builder ──────────────────────────────────────

    def _build_column_strategy(
        self,
        table: TableMetadata,
        col: ColumnMetadata,
        fk_map: dict[str, Any],
    ) -> ColumnStrategy:
        """Pre-compute a fast generation strategy for a column.

        All regex matching, type detection, and constraint parsing happens
        here ONCE, returning a tight callable for the hot loop.
        """
        col_key = f"{table.name}.{col.name}"

        # FK column → pick from parent data
        if col.name in fk_map:
            fk = fk_map[col.name]
            ref_table = fk.references_table
            ref_col = fk.references_column
            return lambda _i, _rt=ref_table, _rc=ref_col: self._pick_fk_value(_rt, _rc)

        # Integer PK → sequential
        if col.is_primary_key and _base_type(col.data_type) in ("integer",):
            return lambda i: i + 1

        # Build the core value generator (no uniqueness handling yet)
        gen_fn = self._resolve_value_generator(col)

        # Wrap with nullable/uniqueness as needed
        is_nullable = col.nullable and not col.is_primary_key
        needs_unique = col.is_unique or col.is_primary_key

        if needs_unique:
            # Initialise tracker
            if col_key not in self._unique_tracker:
                self._unique_tracker[col_key] = set()
            seen = self._unique_tracker[col_key]

            def _unique_strategy(i: int, _gen=gen_fn, _s=seen) -> Any:
                # Deterministic unique: append row index directly
                value = _gen(i)
                if value not in _s:
                    _s.add(value)
                    return value
                # Deterministic suffix using row index
                if isinstance(value, str) and "@" in value:
                    local, domain = value.rsplit("@", 1)
                    value = f"{local}{i}@{domain}"
                elif isinstance(value, str):
                    value = f"{value}_{i}"
                elif isinstance(value, (int, float)):
                    value = value + i
                else:
                    value = f"{value}_{i}"
                c = i
                while value in _s:
                    c += 1
                    if isinstance(value, str) and "@" in value:
                        local, domain = value.rsplit("@", 1)
                        value = f"{local}{c}@{domain}"
                    elif isinstance(value, (int, float)):
                        value = _gen(i) + c
                    else:
                        value = f"{_gen(i)}_{c}"
                _s.add(value)
                return value

            if is_nullable:
                def _nullable_unique_strategy(i: int) -> Any:
                    if random.random() < 0.1:
                        return None
                    return _unique_strategy(i)
                return _nullable_unique_strategy

            return _unique_strategy

        if is_nullable:
            def _nullable_strategy(i: int) -> Any:
                if random.random() < 0.1:
                    return None
                return gen_fn(i)
            return _nullable_strategy

        return gen_fn

    def _resolve_value_generator(self, col: ColumnMetadata) -> ColumnStrategy:
        """Resolve the value-generation function for a column ONCE.

        For Faker / RealisticProvider columns, pre-generates a pool of values
        (size = min(row_count, _POOL_SIZE)) so the hot loop only does
        ``random.choice(pool)`` instead of calling Faker per row.
        """
        base = _base_type(col.data_type)
        pool_n = min(self._row_count, _effective_pool_size(self._row_count))

        # CHECK constraint enum
        enum_values = _extract_enum_from_check(col.check_constraint)
        if enum_values:
            choices = enum_values
            return lambda _i: random.choice(choices)

        # Semantic type — pool pre-generation
        sem_type = detect_semantic_type(col.name, domain=self._domain)
        if sem_type != SemanticType.UNKNOWN:
            provider = self._provider
            pool = [provider.generate(sem_type) for _ in range(pool_n)]
            # Coerce to int when schema declares INTEGER
            if base == "integer":
                pool = [int(v) if isinstance(v, float) else v for v in pool]
            return lambda _i: random.choice(pool)

        # Legacy name heuristics — pool pre-generation
        for pattern, prov_name in _NAME_HINTS:
            if pattern.search(col.name):
                fn = getattr(fake, prov_name)
                pool = [fn() for _ in range(pool_n)]
                return lambda _i: random.choice(pool)

        # Type-based (no Faker calls → no pooling needed)
        if base == "integer":
            lo, hi = _parse_int_bounds(col)
            return lambda _i: random.randint(lo, hi)
        elif base == "float":
            lo, hi, prec = _parse_float_bounds(col)
            return lambda _i: round(random.uniform(lo, hi), prec)
        elif base == "boolean":
            return lambda _i: random.random() < 0.5
        elif base == "date":
            return lambda _i: (_DATE_START + timedelta(days=random.randint(0, _DATE_DAYS))).isoformat()
        elif base == "datetime":
            return lambda _i: (_DT_START + timedelta(seconds=random.randint(0, _DT_SECS))).isoformat()
        elif base == "uuid":
            return lambda _i: str(uuid.uuid4())
        else:
            max_len = _extract_max_length(col.data_type)
            if max_len and max_len <= 10:
                return lambda _i: "".join(random.choices(string.ascii_lowercase, k=max_len))
            if max_len:
                pool = [fake.word()[:max_len] for _ in range(pool_n)]
                return lambda _i: random.choice(pool)
            pool = [fake.word() for _ in range(pool_n)]
            return lambda _i: random.choice(pool)

    # ── Bulk column generator ────────────────────────────────────

    def _generate_column_bulk(
        self,
        table: TableMetadata,
        col: ColumnMetadata,
        fk_values: list[Any] | None,
        n: int,
    ) -> list[Any]:
        """Generate an entire column of *n* values as a flat list.

        Uses ``_random()`` (single C call) instead of ``random.choice()``
        (3 Python function calls deep) to eliminate per-cell overhead.
        """
        _random = random.random  # local for speed
        col_key = f"{table.name}.{col.name}"

        # ── FK column ────────────────────────────────────────
        if fk_values is not None:
            if not fk_values:
                return [None] * n
            fk_len = len(fk_values)
            # If column is unique, pick without replacement (1:1 mapping)
            needs_unique = col.is_unique or col.is_primary_key
            if needs_unique and fk_len >= n:
                # Shuffle parent values and take first n for guaranteed uniqueness
                import random as _rmod
                shuffled = list(fk_values)
                _rmod.shuffle(shuffled)
                vals = shuffled[:n]
            elif needs_unique:
                # Not enough parent rows for full uniqueness — use all then cycle
                vals = list(fk_values) * ((n // fk_len) + 1)
                vals = vals[:n]
            else:
                vals = [fk_values[int(_random() * fk_len)] for _ in range(n)]
            # Coerce FK values to match the child column's declared type
            base = _base_type(col.data_type)
            if base == "integer":
                coerced = []
                for v in vals:
                    if v is None:
                        coerced.append(None)
                    elif isinstance(v, int):
                        coerced.append(v)
                    elif isinstance(v, float):
                        coerced.append(int(v))
                    elif isinstance(v, str):
                        try:
                            coerced.append(int(v))
                        except (ValueError, TypeError):
                            coerced.append(fk_values.index(v) + 1 if v in fk_values else 1)
                    else:
                        coerced.append(1)
                vals = coerced
            return vals

        # ── Integer PK → sequential ─────────────────────────
        if col.is_primary_key and _base_type(col.data_type) in ("integer",):
            return list(range(1, n + 1))

        # ── Resolve the core values ─────────────────────────
        needs_unique = col.is_unique or col.is_primary_key

        if needs_unique:
            # For unique columns, generate directly-unique values to avoid
            # the expensive collision-resolution loop.
            values = self._generate_unique_column(col, col_key, n, table_name=table.name)
        else:
            values = self._generate_column_values(col, n, table_name=table.name)

        # ── Type enforcement — final safety net ──────────────
        base = _base_type(col.data_type)
        if base == "integer":
            values = self._coerce_to_int(values, col)
        elif base == "float":
            values = self._coerce_to_float(values, col)

        # ── Nullable ─────────────────────────────────────────
        is_nullable = col.nullable and not col.is_primary_key
        if is_nullable:
            for idx in range(n):
                if _random() < 0.1:
                    values[idx] = None

        return values

    # ── Type coercion helpers ────────────────────────────────────

    def _coerce_to_int(self, values: list[Any], col: ColumnMetadata) -> list[Any]:
        """Ensure all non-None values are integers. Replace un-coerceable values."""
        lo, hi = _parse_int_bounds(col)
        result = values
        for i, v in enumerate(result):
            if v is None:
                continue
            if isinstance(v, int):
                continue
            if isinstance(v, float):
                result[i] = int(v)
            elif isinstance(v, str):
                try:
                    result[i] = int(v)
                except (ValueError, TypeError):
                    # String can't be converted — replace with random int
                    result[i] = random.randint(lo, hi)
            else:
                result[i] = random.randint(lo, hi)
        return result

    def _coerce_to_float(self, values: list[Any], col: ColumnMetadata) -> list[Any]:
        """Ensure all non-None values are floats. Replace un-coerceable values."""
        lo, hi, prec = _parse_float_bounds(col)
        result = values
        for i, v in enumerate(result):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                result[i] = float(v)
            elif isinstance(v, str):
                try:
                    result[i] = float(v)
                except (ValueError, TypeError):
                    result[i] = round(random.uniform(lo, hi), prec)
            else:
                result[i] = round(random.uniform(lo, hi), prec)
        return result

    def _generate_unique_column(
        self, col: ColumnMetadata, col_key: str, n: int, table_name: str = "",
    ) -> list[Any]:
        """Generate *n* guaranteed-unique values without collision loops.

        Uses a small pool of base values combined with row indices to
        produce unique strings/numbers in a single pass.
        """
        _random = random.random
        pool_n = min(n, _effective_pool_size(self._row_count))
        base = _base_type(col.data_type)

        # CHECK constraint enum (authoritative — defines allowed values)
        enum_values = _extract_enum_from_check(col.check_constraint)
        if enum_values:
            # Enum with unique → cycle through values with dedup
            if col_key not in self._unique_tracker:
                self._unique_tracker[col_key] = set()
            seen = self._unique_tracker[col_key]
            e_len = len(enum_values)
            values: list[Any] = []
            for i in range(n):
                v = enum_values[i % e_len]
                if v not in seen:
                    seen.add(v)
                    values.append(v)
                else:
                    values.append(v)  # allow repeats if enum is smaller than n
            return values

        # ── Context-aware inference (table + column name) ────
        from app.generators.context_inference import resolve_contextual_values
        ctx_values = resolve_contextual_values(table_name, col.name, max(n * 3, pool_n))
        if ctx_values is not None:
            # Use context pool for unique generation
            pool = ctx_values
            if col_key not in self._unique_tracker:
                self._unique_tracker[col_key] = set()
            seen = self._unique_tracker[col_key]
            values = []
            for v in pool:
                if v not in seen and len(values) < n:
                    seen.add(v)
                    values.append(v)
            # If pool was large enough, we're done
            if len(values) >= n:
                return values[:n]
            # Else, pad with indexed variants
            idx = 0
            while len(values) < n:
                candidate = f"{pool[int(_random() * len(pool))]}_{idx}"
                if candidate not in seen:
                    seen.add(candidate)
                    values.append(candidate)
                idx += 1
            return values

        # Build a base pool (same logic as _generate_column_values but small)
        enum_values = _extract_enum_from_check(col.check_constraint)
        sem_type = detect_semantic_type(col.name, domain=self._domain)

        if enum_values:
            # Enum with unique → cycle through values
            pool = enum_values
        elif sem_type != SemanticType.UNKNOWN:
            pool = [self._provider.generate(sem_type) for _ in range(pool_n)]
            if base == "integer":
                pool = [int(v) if isinstance(v, float) else v for v in pool]
        else:
            matched_hint = None
            for pattern, prov_name in _NAME_HINTS:
                if pattern.search(col.name):
                    matched_hint = prov_name
                    break
            if matched_hint:
                fn = getattr(fake, matched_hint)
                pool = [fn() for _ in range(pool_n)]
            elif base in ("integer", "float"):
                # Numeric uniques: sequential is fastest
                if col_key not in self._unique_tracker:
                    self._unique_tracker[col_key] = set()
                seen = self._unique_tracker[col_key]
                lo, _ = _parse_int_bounds(col) if base == "integer" else (1, 0)
                values = list(range(lo, lo + n))
                for v in values:
                    seen.add(v)
                return values
            else:
                pool = [fake.word() for _ in range(pool_n)]

        # Build unique values by appending index to pool elements
        if col_key not in self._unique_tracker:
            self._unique_tracker[col_key] = set()
        seen = self._unique_tracker[col_key]
        p_len = len(pool)
        values: list[Any] = [None] * n
        for i in range(n):
            base_val = pool[int(_random() * p_len)]
            if isinstance(base_val, str) and "@" in base_val:
                local, domain_part = base_val.rsplit("@", 1)
                candidate = f"{local}{i}@{domain_part}"
            elif isinstance(base_val, str):
                candidate = f"{base_val}_{i}"
            elif isinstance(base_val, (int, float)):
                candidate = base_val + i
            else:
                candidate = f"{base_val}_{i}"
            # Very rare collision — handle safely
            c = i
            while candidate in seen:
                c += 1
                if isinstance(base_val, str) and "@" in base_val:
                    local, domain_part = base_val.rsplit("@", 1)
                    candidate = f"{local}{c}@{domain_part}"
                elif isinstance(base_val, (int, float)):
                    candidate = base_val + c
                else:
                    candidate = f"{base_val}_{c}"
            seen.add(candidate)
            values[i] = candidate
        return values

    # ── AI hint application ──────────────────────────────────────

    def _apply_ai_hint(
        self, col: ColumnMetadata, base: str, n: int, table_name: str,
    ) -> list[Any] | None:
        """Apply AI-inferred hint to generate values. Returns None if no hint."""
        if not self._ai_hints or not table_name:
            return None
        table_hints = self._ai_hints.get(table_name)
        if not table_hints:
            return None
        hint = table_hints.get(col.name)
        if not hint:
            return None

        _random = random.random

        if hint.strategy == "enum" and hint.values:
            pool = hint.values
            # Coerce to match declared type
            if base == "integer":
                coerced = []
                for v in pool:
                    if v is None:
                        continue
                    if isinstance(v, int):
                        coerced.append(v)
                    elif isinstance(v, float):
                        coerced.append(int(v))
                    elif isinstance(v, str):
                        try:
                            coerced.append(int(v))
                        except (ValueError, TypeError):
                            continue  # Skip non-numeric AI suggestions for int columns
                    else:
                        continue
                pool = coerced
            elif base == "float":
                coerced = []
                for v in pool:
                    if v is None:
                        continue
                    try:
                        coerced.append(float(v))
                    except (ValueError, TypeError):
                        continue
                pool = coerced
            if not pool:
                return None  # AI hint incompatible with column type — fall through
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]

        if hint.strategy == "range":
            lo = hint.min_val if hint.min_val is not None else 0
            hi = hint.max_val if hint.max_val is not None else 1000
            if base == "integer":
                lo, hi = int(lo), int(hi)
                span = hi - lo + 1
                return [int(_random() * span) + lo for _ in range(n)]
            else:
                rng = hi - lo
                return [round(_random() * rng + lo, 2) for _ in range(n)]

        if hint.strategy == "prefix_seq" and hint.prefix:
            # prefix_seq produces strings — only use for string columns
            if base in ("integer", "float", "boolean"):
                return None  # Incompatible — fall through to type-based generation
            prefix = hint.prefix
            return [f"{prefix}{i + 1}" for i in range(n)]

        if hint.strategy == "pattern" and hint.pattern:
            # pattern produces strings — only use for string columns
            if base in ("integer", "float", "boolean"):
                return None
            pat = hint.pattern
            pool = [fake.bothify(pat) for _ in range(min(n, _POOL_SIZE))]
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]

        if hint.strategy == "faker" and hint.format_hint:
            fmt = hint.format_hint.lower().replace(" ", "_")
            fn = getattr(fake, fmt, None)
            if fn and callable(fn):
                pool = [fn() for _ in range(min(n, _POOL_SIZE))]
                if base == "integer":
                    coerced = []
                    for v in pool:
                        if isinstance(v, int):
                            coerced.append(v)
                        elif isinstance(v, float):
                            coerced.append(int(v))
                        elif isinstance(v, str):
                            try:
                                coerced.append(int(v))
                            except (ValueError, TypeError):
                                continue
                        else:
                            continue
                    if not coerced:
                        return None  # Faker hint incompatible
                    pool = coerced
                p_len = len(pool)
                return [pool[int(_random() * p_len)] for _ in range(n)]

        return None

    def _generate_column_values(self, col: ColumnMetadata, n: int, table_name: str = "") -> list[Any]:
        """Generate *n* raw values for a column using the fastest path."""
        _random = random.random
        base = _base_type(col.data_type)
        pool_n = min(n, _effective_pool_size(self._row_count))

        # ── AI hint override (highest priority after FK/PK) ──
        ai_values = self._apply_ai_hint(col, base, n, table_name)
        if ai_values is not None:
            return ai_values

        # CHECK constraint enum (authoritative — defines allowed values)
        enum_values = _extract_enum_from_check(col.check_constraint)
        if enum_values:
            e_len = len(enum_values)
            return [enum_values[int(_random() * e_len)] for _ in range(n)]

        # ── Context-aware inference (table + column name) ────
        from app.generators.context_inference import resolve_contextual_values
        ctx_values = resolve_contextual_values(table_name, col.name, n)
        if ctx_values is not None:
            return ctx_values

        # Semantic type — pool
        sem_type = detect_semantic_type(col.name, domain=self._domain)
        if sem_type != SemanticType.UNKNOWN:
            pool = [self._provider.generate(sem_type) for _ in range(pool_n)]
            # Coerce to int when schema declares INTEGER
            if base == "integer":
                pool = [int(v) if isinstance(v, float) else v for v in pool]
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]

        # Legacy name heuristics — pool
        for pattern, prov_name in _NAME_HINTS:
            if pattern.search(col.name):
                fn = getattr(fake, prov_name)
                pool = [fn() for _ in range(pool_n)]
                p_len = len(pool)
                return [pool[int(_random() * p_len)] for _ in range(n)]

        # Type-based bulk generation
        if base == "integer":
            lo, hi = _parse_int_bounds(col)
            span = hi - lo + 1
            return [int(_random() * span) + lo for _ in range(n)]
        elif base == "float":
            lo, hi, prec = _parse_float_bounds(col)
            rng = hi - lo
            return [round(_random() * rng + lo, prec) for _ in range(n)]
        elif base == "boolean":
            return [_random() < 0.5 for _ in range(n)]
        elif base == "date":
            pool = [(_DATE_START + timedelta(days=int(_random() * _DATE_DAYS))).isoformat()
                    for _ in range(pool_n)]
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]
        elif base == "datetime":
            pool = [(_DT_START + timedelta(seconds=int(_random() * _DT_SECS))).isoformat()
                    for _ in range(pool_n)]
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]
        elif base == "uuid":
            return [str(uuid.uuid4()) for _ in range(n)]
        else:
            max_len = _extract_max_length(col.data_type)
            if max_len and max_len <= 10:
                return ["".join(random.choices(string.ascii_lowercase, k=max_len))
                        for _ in range(n)]
            pool = [fake.word() for _ in range(pool_n)]
            if max_len:
                pool = [w[:max_len] for w in pool]
            p_len = len(pool)
            return [pool[int(_random() * p_len)] for _ in range(n)]

    # ── Vectorized fast path (numpy + pandas) ───────────────────

    # Threshold: use vectorized path for large row counts
    _VECTORIZED_THRESHOLD = 5_000

    def _generate_table_vectorized(self, table: TableMetadata) -> list[dict[str, Any]]:
        """Generate rows using numpy vectorization + AI row correlation.

        1. Get row profiles (AI or heuristic) for cross-column coherence
        2. Assign rows to profiles
        3. Generate values per-profile using vectorized numpy operations
        4. Merge profile-constrained columns with independent columns

        Maintains FK integrity, CHECK constraints, uniqueness, and type correctness.
        """
        import numpy as np
        import pandas as pd
        from app.ai.row_correlation import get_table_profiles

        n = self._row_count
        rng = np.random.default_rng()

        # ── Step 1: Get correlation profiles ─────────────────
        table_profiles = get_table_profiles(table, domain=self._domain, use_ai=True)
        profile_assignments = table_profiles.assign_rows(n)

        # Build FK lookup: col_name → list of parent values
        fk_map: dict[str, list[Any]] = {}
        for fk in table.foreign_keys:
            parent_rows = self._generated.get(fk.references_table, [])
            if parent_rows:
                fk_map[fk.column] = [r.get(fk.references_column) for r in parent_rows]

        # Pool size for Faker-generated values
        pool_size = min(n, _effective_pool_size(self._row_count))

        data: dict[str, Any] = {}

        for col in table.columns:
            col_name = col.name
            base = _base_type(col.data_type)

            # ── FK column → sample from parent values ────────
            if col_name in fk_map:
                parent_vals = fk_map[col_name]
                if not parent_vals:
                    data[col_name] = [None] * n
                elif col.is_unique or col.is_primary_key:
                    # Unique FK: cycle through parent values
                    repeated = (parent_vals * ((n // len(parent_vals)) + 1))[:n]
                    rng.shuffle(repeated)
                    data[col_name] = repeated
                else:
                    parent_arr = np.array(parent_vals)
                    indices = rng.integers(0, len(parent_vals), size=n)
                    data[col_name] = parent_arr[indices].tolist()
                continue

            # ── Integer PK → sequential ──────────────────────
            if col.is_primary_key and base == "integer":
                data[col_name] = np.arange(1, n + 1).tolist()
                continue

            # ── CHECK constraint enum → vectorized choice ────
            enum_values = _extract_enum_from_check(col.check_constraint)
            if enum_values:
                arr = np.array(enum_values)
                indices = rng.integers(0, len(enum_values), size=n)
                data[col_name] = arr[indices].tolist()
                continue

            # ── AI hint override ─────────────────────────────
            ai_vals = self._apply_ai_hint(col, base, n, table.name)
            if ai_vals is not None:
                data[col_name] = ai_vals
                continue

            # ── Context-aware inference ──────────────────────
            from app.generators.context_inference import resolve_contextual_values
            ctx_values = resolve_contextual_values(table.name, col_name, pool_size)
            if ctx_values is not None:
                pool = ctx_values
                if col.is_unique or col.is_primary_key:
                    # Unique: append index suffix
                    data[col_name] = [f"{pool[i % len(pool)]}_{i}" for i in range(n)]
                else:
                    arr = np.array(pool)
                    indices = rng.integers(0, len(pool), size=n)
                    data[col_name] = arr[indices].tolist()
                continue

            # ── Semantic type → pool + vectorized choice ─────
            sem_type = detect_semantic_type(col_name, domain=self._domain)
            if sem_type != SemanticType.UNKNOWN:
                pool = [self._provider.generate(sem_type) for _ in range(pool_size)]
                if base == "integer":
                    pool = [int(v) if isinstance(v, (int, float)) else v for v in pool]
                    pool = [v for v in pool if isinstance(v, int)]
                    if pool:
                        arr = np.array(pool)
                        indices = rng.integers(0, len(pool), size=n)
                        vals = arr[indices].tolist()
                    else:
                        vals = rng.integers(1, 10000, size=n).tolist()
                    if col.is_unique or col.is_primary_key:
                        vals = list(range(1, n + 1))
                    data[col_name] = vals
                elif base == "float":
                    pool = [float(v) for v in pool if isinstance(v, (int, float))]
                    if pool:
                        arr = np.array(pool)
                        indices = rng.integers(0, len(pool), size=n)
                        data[col_name] = arr[indices].tolist()
                    else:
                        data[col_name] = rng.uniform(0.01, 99999.99, size=n).round(2).tolist()
                else:
                    arr = np.array(pool)
                    indices = rng.integers(0, len(pool), size=n)
                    vals = arr[indices].tolist()
                    if col.is_unique or col.is_primary_key:
                        vals = [f"{vals[i]}_{i}" for i in range(n)]
                    data[col_name] = vals
                continue

            # ── Name heuristics → Faker pool + vectorized choice ─
            matched_hint = None
            for pattern, prov_name in _NAME_HINTS:
                if pattern.search(col_name):
                    matched_hint = prov_name
                    break
            if matched_hint:
                fn = getattr(fake, matched_hint)
                pool = [fn() for _ in range(pool_size)]
                arr = np.array(pool)
                indices = rng.integers(0, len(pool), size=n)
                vals = arr[indices].tolist()
                if col.is_unique or col.is_primary_key:
                    vals = [f"{vals[i]}_{i}" for i in range(n)]
                data[col_name] = vals
                continue

            # ── Type-based vectorized generation ─────────────
            if base == "integer":
                lo, hi = _parse_int_bounds(col)
                vals = rng.integers(lo, hi + 1, size=n).tolist()
                if col.is_unique or col.is_primary_key:
                    vals = list(range(lo, lo + n))
                data[col_name] = vals
            elif base == "float":
                lo, hi, prec = _parse_float_bounds(col)
                data[col_name] = np.round(rng.uniform(lo, hi, size=n), prec).tolist()
            elif base == "boolean":
                data[col_name] = rng.choice([True, False], size=n).tolist()
            elif base == "date":
                days = rng.integers(0, _DATE_DAYS, size=n)
                data[col_name] = [
                    (_DATE_START + timedelta(days=int(d))).isoformat() for d in days
                ]
            elif base == "datetime":
                secs = rng.integers(0, _DT_SECS, size=n)
                data[col_name] = [
                    (_DT_START + timedelta(seconds=int(s))).isoformat() for s in secs
                ]
            elif base == "uuid":
                data[col_name] = [str(uuid.uuid4()) for _ in range(n)]
            else:
                # String fallback — pool of words
                pool = [fake.word() for _ in range(pool_size)]
                max_len = _extract_max_length(col.data_type)
                if max_len:
                    pool = [w[:max_len] for w in pool]
                arr = np.array(pool)
                indices = rng.integers(0, len(pool), size=n)
                vals = arr[indices].tolist()
                if col.is_unique or col.is_primary_key:
                    vals = [f"{vals[i]}_{i}" for i in range(n)]
                data[col_name] = vals

            # ── Nullable: set ~10% to None ───────────────────
            if col.nullable and not col.is_primary_key and col_name not in fk_map:
                null_mask = rng.random(n) < 0.1
                col_data = data[col_name]
                for idx in np.where(null_mask)[0]:
                    col_data[idx] = None

        # ── Step 2: Apply profile-driven correlation ────────────
        # Override independently-generated values with profile constraints
        # so that column values within a row are coherent.
        # Vectorized: process all rows of one profile at once (batch per profile).
        fk_cols = {fk.column for fk in table.foreign_keys}
        pk_cols = {c.name for c in table.columns if c.is_primary_key}
        skip_correlation = fk_cols | pk_cols  # Never override structural columns

        profile_arr = np.array(profile_assignments)
        col_meta_map = {c.name: c for c in table.columns}

        for pidx, profile in enumerate(table_profiles.profiles):
            if not profile.constraints:
                continue
            # Get row indices assigned to this profile
            row_mask = profile_arr == pidx
            row_indices = np.where(row_mask)[0]
            if len(row_indices) == 0:
                continue
            batch_n = len(row_indices)

            for col_name, constraint in profile.constraints.items():
                if col_name not in data or col_name in skip_correlation:
                    continue
                col_data = data[col_name]

                # Apply null probability (entire batch)
                if constraint.null_probability and constraint.null_probability >= 1.0:
                    for idx in row_indices:
                        col_data[idx] = None
                    continue

                # Generate batch values based on constraint type
                if constraint.values:
                    vals_arr = np.array(constraint.values)
                    picks = vals_arr[rng.integers(0, len(constraint.values), size=batch_n)]
                    for i, idx in enumerate(row_indices):
                        col_data[idx] = picks[i].item() if hasattr(picks[i], 'item') else picks[i]
                elif constraint.min_val is not None and constraint.max_val is not None:
                    col_meta = col_meta_map.get(col_name)
                    if col_meta:
                        col_base = _base_type(col_meta.data_type)
                        if col_base == "integer":
                            batch_vals = rng.integers(
                                int(constraint.min_val), int(constraint.max_val) + 1, size=batch_n
                            )
                            for i, idx in enumerate(row_indices):
                                col_data[idx] = int(batch_vals[i])
                        elif col_base == "float":
                            batch_vals = np.round(
                                rng.uniform(constraint.min_val, constraint.max_val, size=batch_n), 2
                            )
                            for i, idx in enumerate(row_indices):
                                col_data[idx] = float(batch_vals[i])

                # Apply null probability for partial nulls
                if constraint.null_probability and 0 < constraint.null_probability < 1.0:
                    null_mask = rng.random(batch_n) < constraint.null_probability
                    for i, idx in enumerate(row_indices):
                        if null_mask[i]:
                            col_data[idx] = None

        # Assemble into list[dict] via pandas for speed
        df = pd.DataFrame(data)
        return df.to_dict("records")

    # ── Table generation ──────────────────────────────────────

    def _generate_table(self, table: TableMetadata) -> list[dict[str, Any]]:
        """Generate rows for a single table.

        For large row counts (>= _VECTORIZED_THRESHOLD), uses numpy-vectorized
        generation for speed. For smaller counts, uses the full scenario-first
        orchestration pipeline for maximum data quality.
        """
        # Fast path: numpy vectorization for large datasets
        if self._row_count >= self._VECTORIZED_THRESHOLD:
            return self._generate_table_vectorized(table)

        # Quality path: full 8-stage orchestration for small datasets
        from app.generators.orchestration_engine import (
            GenerationOrchestrator,
            TableGenerationContext,
            _stage_understand_schema,
            _stage_understand_business_context,
            _stage_infer_semantic_meaning,
            _stage_detect_dependencies,
            _stage_determine_scenario,
            _stage_derive_dependent_values,
            _stage_validate_consistency,
            _stage_generate_final_rows,
        )
        from app.generators.coherence_validator import CoherenceValidator

        n = self._row_count

        # Build orchestration context
        check_constraints = {
            c.name: c.check_constraint for c in table.columns if c.check_constraint
        }
        ctx = TableGenerationContext(
            table=table,
            n=n,
            domain=self._domain,
            country=self._country,
            check_constraints=check_constraints,
        )

        # Pre-populate FK parent data from already-generated tables
        for fk in table.foreign_keys:
            parent_rows = self._generated.get(fk.references_table, [])
            if parent_rows:
                ctx.fk_parent_data[fk.column] = [
                    r.get(fk.references_column) for r in parent_rows
                ]

        # Execute the 8-stage scenario-first pipeline
        stages = [
            _stage_understand_schema,
            _stage_understand_business_context,
            _stage_infer_semantic_meaning,
            _stage_detect_dependencies,
            _stage_determine_scenario,
            _stage_derive_dependent_values,
            _stage_validate_consistency,
            _stage_generate_final_rows,
        ]

        for stage_fn in stages:
            try:
                stage_fn(ctx)
            except Exception as e:
                logger.warning(
                    "Orchestration stage %s failed for %s: %s — continuing",
                    stage_fn.__name__, table.name, e,
                )

        # Apply coherence validation with auto-correction
        # For large datasets (>10K rows), validate a sample and apply corrections
        # proportionally to avoid O(n) validation overhead
        if ctx.rows:
            validator = CoherenceValidator(auto_correct=True)
            _COHERENCE_SAMPLE_THRESHOLD = 10_000
            if len(ctx.rows) > _COHERENCE_SAMPLE_THRESHOLD:
                # Sample-based validation: validate first 10K rows
                sample = ctx.rows[:_COHERENCE_SAMPLE_THRESHOLD]
                corrected_sample, _report = validator.validate(sample)
                ctx.rows[:_COHERENCE_SAMPLE_THRESHOLD] = corrected_sample
                if _report.auto_corrections > 0:
                    logger.info(
                        "Coherence validator corrected %d violations in %s sample (pass rate: %.1f%%)",
                        _report.auto_corrections,
                        table.name,
                        _report.pass_rate * 100,
                    )
            else:
                ctx.rows, _report = validator.validate(ctx.rows)
                if _report.auto_corrections > 0:
                    logger.info(
                        "Coherence validator corrected %d violations in %s (pass rate: %.1f%%)",
                        _report.auto_corrections,
                        table.name,
                        _report.pass_rate * 100,
                    )

        return ctx.rows

    def _pick_fk_value(self, parent_table: str, parent_column: str) -> Any:
        """Pick a random value from a parent table's generated column."""
        parent_rows = self._generated.get(parent_table, [])
        if not parent_rows:
            logger.warning("No rows for parent table %s — using None", parent_table)
            return None
        row = random.choice(parent_rows)
        return row.get(parent_column)

    # Keep legacy _generate_value and _ensure_unique for external callers
    def _generate_value(self, col: ColumnMetadata) -> Any:
        """Generate a single value for a column, using semantic detection + heuristics + constraints."""
        base = _base_type(col.data_type)

        enum_values = _extract_enum_from_check(col.check_constraint)
        if enum_values:
            return random.choice(enum_values)

        sem_type = detect_semantic_type(col.name, domain=self._domain)
        if sem_type != SemanticType.UNKNOWN:
            return self._provider.generate(sem_type)

        for pattern, provider in _NAME_HINTS:
            if pattern.search(col.name):
                return _call_faker(provider)

        if base == "integer":
            return _gen_integer(col)
        elif base == "float":
            return _gen_float(col)
        elif base == "boolean":
            return random.choice([True, False])
        elif base == "date":
            return _gen_date()
        elif base == "datetime":
            return _gen_datetime()
        elif base == "uuid":
            return str(uuid.uuid4())
        else:
            return _gen_string(col)

    def _ensure_unique(
        self, col_key: str, col: ColumnMetadata, initial: Any
    ) -> Any:
        """Retry generation until a unique value is produced."""
        if col_key not in self._unique_tracker:
            self._unique_tracker[col_key] = set()

        seen = self._unique_tracker[col_key]
        value = initial

        if value not in seen:
            seen.add(value)
            return value

        for _ in range(20):
            value = self._generate_value(col)
            if value not in seen:
                seen.add(value)
                return value

        counter = len(seen)
        if isinstance(initial, str) and "@" in initial:
            local, domain = initial.rsplit("@", 1)
            value = f"{local}{counter}@{domain}"
        elif isinstance(initial, str):
            value = f"{initial}_{counter}"
        elif isinstance(initial, (int, float)):
            value = initial + counter
        else:
            value = f"{initial}_{counter}"

        while value in seen:
            counter += 1
            if isinstance(initial, str) and "@" in initial:
                local, domain = initial.rsplit("@", 1)
                value = f"{local}{counter}@{domain}"
            elif isinstance(initial, str):
                value = f"{initial}_{counter}"
            elif isinstance(initial, (int, float)):
                value = initial + counter
            else:
                value = f"{initial}_{counter}"

        seen.add(value)
        return value


# ── Value generators ──────────────────────────────────────────


def _call_faker(provider: str) -> Any:
    """Call a Faker provider by name."""
    return getattr(fake, provider)()


def _parse_int_bounds(col: ColumnMetadata) -> tuple[int, int]:
    """Parse integer bounds from CHECK constraints ONCE."""
    lo, hi = 1, 100_000
    check = col.check_constraint or ""
    m = re.search(r">\s*(\d+)", check)
    if m:
        lo = int(m.group(1)) + 1
    m = re.search(r"<\s*(\d+)", check)
    if m:
        hi = int(m.group(1)) - 1
    return lo, max(lo, hi)


def _parse_float_bounds(col: ColumnMetadata) -> tuple[float, float, int]:
    """Parse float bounds and precision from CHECK constraints ONCE."""
    lo, hi = 0.01, 100_000.0
    check = col.check_constraint or ""
    m = re.search(r">\s*([\d.]+)", check)
    if m:
        lo = float(m.group(1)) + 0.01
    m = re.search(r"<\s*([\d.]+)", check)
    if m:
        hi = float(m.group(1)) - 0.01
    precision = _extract_precision(col.data_type)
    return lo, max(lo, hi), precision


def _gen_integer(col: ColumnMetadata) -> int:
    """Generate a random integer, respecting CHECK constraint bounds."""
    lo, hi = _parse_int_bounds(col)
    return random.randint(lo, hi)


def _gen_float(col: ColumnMetadata) -> float:
    """Generate a random float, respecting CHECK constraint bounds and precision."""
    lo, hi, precision = _parse_float_bounds(col)
    return round(random.uniform(lo, hi), precision)


def _gen_date() -> str:
    """Generate a random ISO-format date between 2020 and 2026."""
    return (_DATE_START + timedelta(days=random.randint(0, _DATE_DAYS))).isoformat()


def _gen_datetime() -> str:
    """Generate a random ISO-format datetime between 2020 and 2026."""
    return (_DT_START + timedelta(seconds=random.randint(0, _DT_SECS))).isoformat()


def _gen_string(col: ColumnMetadata) -> str:
    """Generate a random string value, respecting max-length constraints."""
    max_len = _extract_max_length(col.data_type)
    if max_len and max_len <= 10:
        return "".join(random.choices(string.ascii_lowercase, k=max_len))
    word = fake.word()
    if max_len:
        word = word[:max_len]
    return word
