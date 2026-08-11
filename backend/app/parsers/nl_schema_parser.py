"""Natural-language schema parser — converts AI-inferred JSON into SchemaMetadata.

Also provides a deterministic offline fallback that uses keyword heuristics
to build a schema when no AI gateway is available.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.models.nl import (
    InferredColumn,
    InferredConstraint,
    InferredEntity,
    InferredRelationship,
    NLSchemaResult,
)
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.relationship_engine import RelationshipGraph

logger = logging.getLogger(__name__)


class NLParserError(Exception):
    """Raised when NL schema parsing fails."""


# ── Public API ────────────────────────────────────────────────


def parse_nl_response(raw_json: str) -> NLSchemaResult:
    """Parse AI JSON response into a validated NLSchemaResult with SchemaMetadata."""
    cleaned = _extract_json(raw_json)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise NLParserError(f"Invalid JSON from AI: {e}") from e

    if not isinstance(data, dict):
        raise NLParserError(f"Expected JSON object, got {type(data).__name__}")

    domain = data.get("domain", "")
    entities = _parse_entities(data.get("entities", []))
    relationships = _parse_relationships(data.get("relationships", []))
    constraints = _parse_constraints(data.get("constraints", []))

    schema = _build_schema(entities, relationships)

    try:
        graph = RelationshipGraph(schema)
        generation_order = graph.get_generation_order()
    except Exception:
        generation_order = [t.name for t in schema.tables]

    generated_sql = _schema_to_ddl(schema)

    return NLSchemaResult(
        domain=domain,
        entities=entities,
        relationships=relationships,
        constraints=constraints,
        schema=schema,
        generation_order=generation_order,
        generated_sql=generated_sql,
    )


def infer_schema_offline(prompt: str) -> NLSchemaResult:
    """Build a schema from a user prompt using keyword heuristics (no AI).

    If the user explicitly specifies columns or table/entity names, those are
    used directly.  Otherwise falls back to domain-template detection.
    """
    lower = prompt.lower()

    # Try to extract explicit column/table specification from the prompt
    custom = _extract_custom_schema(prompt)
    if custom:
        domain, entities, relationships = custom
    else:
        domain, entities, relationships = _detect_domain(lower)

    schema = _build_schema(entities, relationships)
    try:
        graph = RelationshipGraph(schema)
        generation_order = graph.get_generation_order()
    except Exception:
        generation_order = [t.name for t in schema.tables]

    generated_sql = _schema_to_ddl(schema)

    return NLSchemaResult(
        domain=domain,
        entities=entities,
        relationships=relationships,
        constraints=[],
        schema=schema,
        generation_order=generation_order,
        generated_sql=generated_sql,
    )


# ── JSON extraction ───────────────────────────────────────────


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    if raw.startswith(("{", "[")):
        return raw
    start = raw.find("{")
    if start != -1:
        return raw[start:]
    return raw


# ── Parse helpers ─────────────────────────────────────────────


def _parse_entities(items: list[dict[str, Any]]) -> list[InferredEntity]:
    result: list[InferredEntity] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        columns = []
        for col in item.get("columns", []):
            if not isinstance(col, dict):
                continue
            columns.append(
                InferredColumn(
                    name=col.get("name", ""),
                    data_type=col.get("data_type", "VARCHAR(255)"),
                    nullable=col.get("nullable", True),
                    is_primary_key=col.get("is_primary_key", False),
                    is_unique=col.get("is_unique", False),
                    check_constraint=col.get("check_constraint"),
                    description=col.get("description", ""),
                )
            )
        result.append(
            InferredEntity(
                name=item.get("name", ""),
                description=item.get("description", ""),
                columns=columns,
            )
        )
    return result


def _parse_relationships(items: list[dict[str, Any]]) -> list[InferredRelationship]:
    result: list[InferredRelationship] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(
            InferredRelationship(
                from_table=item.get("from_table", ""),
                from_column=item.get("from_column", ""),
                to_table=item.get("to_table", ""),
                to_column=item.get("to_column", ""),
            )
        )
    return result


def _parse_constraints(items: list[dict[str, Any]]) -> list[InferredConstraint]:
    result: list[InferredConstraint] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(
            InferredConstraint(
                table=item.get("table", ""),
                column=item.get("column", ""),
                rule=item.get("rule", ""),
                description=item.get("description", ""),
            )
        )
    return result


# ── Schema builder ────────────────────────────────────────────


def _build_schema(
    entities: list[InferredEntity],
    relationships: list[InferredRelationship],
) -> SchemaMetadata:
    """Convert inferred entities + relationships into SchemaMetadata."""
    fk_map: dict[tuple[str, str], InferredRelationship] = {
        (r.from_table, r.from_column): r for r in relationships
    }

    tables: list[TableMetadata] = []
    for entity in entities:
        columns: list[ColumnMetadata] = []
        pks: list[str] = []
        checks: list[str] = []

        for col in entity.columns:
            columns.append(
                ColumnMetadata(
                    name=col.name,
                    data_type=col.data_type,
                    nullable=col.nullable,
                    is_primary_key=col.is_primary_key,
                    is_unique=col.is_unique,
                    check_constraint=col.check_constraint,
                )
            )
            if col.is_primary_key:
                pks.append(col.name)
            if col.check_constraint:
                checks.append(col.check_constraint)

        fks: list[ForeignKeyMetadata] = []
        for col in entity.columns:
            key = (entity.name, col.name)
            if key in fk_map:
                rel = fk_map[key]
                fks.append(
                    ForeignKeyMetadata(
                        column=rel.from_column,
                        references_table=rel.to_table,
                        references_column=rel.to_column,
                    )
                )

        tables.append(
            TableMetadata(
                name=entity.name,
                columns=columns,
                primary_keys=pks,
                foreign_keys=fks,
                check_constraints=checks,
            )
        )

    return SchemaMetadata(tables=tables)


# ── DDL generator ─────────────────────────────────────────────


def _schema_to_ddl(schema: SchemaMetadata) -> str:
    """Generate SQL DDL from SchemaMetadata."""
    statements: list[str] = []
    for table in schema.tables:
        lines: list[str] = []
        for col in table.columns:
            parts = [f"    {col.name} {col.data_type}"]
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if col.is_unique and not col.is_primary_key:
                parts.append("UNIQUE")
            if not col.nullable and not col.is_primary_key:
                parts.append("NOT NULL")
            if col.check_constraint:
                parts.append(f"CHECK ({col.check_constraint})")
            lines.append(" ".join(parts))

        for fk in table.foreign_keys:
            lines.append(
                f"    FOREIGN KEY ({fk.column}) REFERENCES {fk.references_table}({fk.references_column})"
            )

        body = ",\n".join(lines)
        statements.append(f"CREATE TABLE {table.name} (\n{body}\n);")

    return "\n\n".join(statements)


# ── Custom schema extraction from prompt ─────────────────────


def _extract_custom_schema(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]] | None:
    """Try to extract explicit table/column specifications from the user prompt.

    Detects patterns like:
      - "columns: col1, col2, col3"
      - "fields: col1, col2, col3"
      - "with columns col1, col2, col3"
      - "table X with columns: col1, col2"
      - Bullet-point or numbered lists of columns
      - "dataset with: col1, col2, col3"

    Returns None if no explicit columns are found in the prompt.
    """
    lower = prompt.lower()

    # ── Extract table name ────────────────────────────────────
    table_name = "data"
    table_patterns = [
        # "Sponsor Details dataset" / "Sponsor Details data" / "Sponsor Details table"
        # Uses word boundaries to avoid matching from inside words like "inSURANCE"
        r"(?:^|\s)((?:[a-z][a-z0-9_]*\s+){0,3}[a-z][a-z0-9_]*)\s+(?:dataset|data|table)\b",
        # "table/dataset named/called X"
        r"(?:table|entity|dataset)\s+(?:named?|called?)\s*[:\-]?\s*[\"']?([a-z][a-z0-9_ ]{1,30})[\"']?",
        # "'s Sponsor Details" (possessive pattern)
        r"'s\s+([a-z][a-z0-9_ ]{1,30}?)\s+(?:dat|table|info)",
    ]
    for pat in table_patterns:
        matches = re.findall(pat, lower)
        # Use last match (closest to "dataset"/"table" keyword)
        for candidate in reversed(matches):
            candidate = candidate.strip() if isinstance(candidate, str) else candidate
            if not candidate:
                continue
            # Reject if it's just a domain keyword or too generic
            skip_words = {"insurance", "bank", "banking", "e-commerce", "ecommerce",
                          "health", "healthcare", "education", "generic", "realistic",
                          "synthetic", "generate", "company", "an", "the", "some",
                          "realistic synthetic", "generate realistic synthetic",
                          "generate realistic"}
            if candidate in skip_words:
                continue
            # Take only the last 1-3 meaningful words as the table name
            words = candidate.split()
            # Skip filler words
            filler = {"a", "an", "the", "for", "of", "my", "our", "your",
                      "realistic", "synthetic", "generate", "sample", "test",
                      "insurance", "banking", "company", "companies",
                      "create", "need", "want", "make", "build", "data",
                      "i", "we", "some", "new", "this", "that"}
            meaningful = [w for w in words if w not in filler and len(w) > 2]
            if meaningful:
                table_name = re.sub(r"\s+", "_", "_".join(meaningful[-3:]))
                break
        else:
            continue
        break

    # ── Extract columns ────────────────────────────────────────
    columns: list[str] = []

    # Pattern 1: "columns:" or "fields:" or "with columns" followed by a list
    col_section = re.search(
        r"(?:columns?|fields?|attributes?|with\s+(?:the\s+)?(?:following\s+)?(?:columns?|fields?))\s*[:\-]\s*(.+)",
        lower,
        re.IGNORECASE,
    )
    if col_section:
        col_text = col_section.group(1)
        # Split on commas, newlines, bullet chars, or "and"
        raw_cols = re.split(r"[,\n•\-\|]|\band\b", col_text)
        for c in raw_cols:
            cleaned = c.strip().strip("\"'`").strip()
            # Stop at sentence boundaries
            if re.search(r"[.!?]$", cleaned):
                cleaned = re.sub(r"[.!?]+$", "", cleaned).strip()
                if cleaned:
                    columns.append(cleaned)
                break
            if cleaned and len(cleaned) < 60:
                columns.append(cleaned)

    # Pattern 2: Numbered or bullet list (e.g., "1. col_name\n2. col_name")
    if not columns:
        list_items = re.findall(r"(?:^|\n)\s*(?:\d+[.)]\s*|[-•*]\s+)([^\n,]{2,50})", prompt)
        if len(list_items) >= 2:
            columns = [item.strip().strip("\"'`") for item in list_items]

    # Pattern 3: Inline parenthetical list "(..., ..., ...)"
    if not columns:
        paren = re.search(r"\(([^)]{10,500})\)", prompt)
        if paren:
            items = [x.strip().strip("\"'`") for x in paren.group(1).split(",")]
            if len(items) >= 2 and all(len(x) < 60 for x in items):
                columns = items

    if not columns:
        return None

    # ── Normalize column names ────────────────────────────────
    normalized: list[str] = []
    for col in columns:
        # Extract just the column name (strip descriptions like "name - the user's name")
        col_name = re.split(r"\s*[-:–—]\s+", col)[0].strip()
        # Convert to snake_case
        col_name = re.sub(r"[^a-zA-Z0-9]+", "_", col_name).strip("_").lower()
        if col_name and col_name not in normalized and len(col_name) < 50:
            normalized.append(col_name)

    if len(normalized) < 1:
        return None

    # ── Infer data types from column names ────────────────────
    def _guess_type(name: str) -> str:
        n = name.lower()
        if n in ("id",) or n.endswith("_id"):
            return "INTEGER"
        if "date" in n or "time" in n or n.endswith("_at") or n.startswith("created") or n.startswith("updated"):
            return "TIMESTAMP" if "time" in n or n.endswith("_at") else "DATE"
        if "email" in n:
            return "VARCHAR(255)"
        if "phone" in n or "mobile" in n or "fax" in n:
            return "VARCHAR(20)"
        if "amount" in n or "price" in n or "cost" in n or "salary" in n or "balance" in n or "premium" in n:
            return "DECIMAL(15,2)"
        if "count" in n or "quantity" in n or "age" in n or "number" in n or "num" in n:
            return "INTEGER"
        if n.startswith("is_") or n.startswith("has_") or n == "active" or n == "enabled":
            return "BOOLEAN"
        if "description" in n or "notes" in n or "comment" in n or "address" in n or "bio" in n:
            return "TEXT"
        if "percent" in n or "ratio" in n or "rate" in n:
            return "DECIMAL(5,2)"
        return "VARCHAR(255)"

    # Build columns — add "id" as PK if not already in the list
    inferred_columns: list[InferredColumn] = []
    has_id = any(c == "id" or c.endswith("_id") and normalized.index(c) == 0 for c in normalized)
    if not has_id:
        inferred_columns.append(
            InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True)
        )

    for col_name in normalized:
        dtype = _guess_type(col_name)
        is_pk = col_name == "id" and not has_id  # already added
        if col_name == "id" and not has_id:
            continue  # skip, already added
        inferred_columns.append(
            InferredColumn(
                name=col_name,
                data_type=dtype,
                nullable=col_name != "id",
                is_primary_key=(col_name == "id"),
                is_unique=(col_name == "email" or col_name.endswith("_number")),
            )
        )

    entity = InferredEntity(
        name=table_name,
        description=f"Custom entity from prompt",
        columns=inferred_columns,
    )

    logger.info(
        "Extracted custom schema from prompt: table=%s, columns=%s",
        table_name,
        [c.name for c in inferred_columns],
    )

    return "custom", [entity], []


# ── Offline domain detection ─────────────────────────────────


def _detect_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    """Detect domain from prompt keywords and return appropriate entities."""
    if re.search(r"bank|account|transaction|transfer|kyc|deposit|withdraw", prompt):
        return _banking_domain(prompt)
    if re.search(r"insurance|policy|claim|premium|coverage|underwriting", prompt):
        return _insurance_domain(prompt)
    if re.search(r"e-?commerce|product|order|cart|shop|store|catalog", prompt):
        return _ecommerce_domain(prompt)
    if re.search(r"hospital|patient|doctor|medical|diagnosis|prescription|health", prompt):
        return _healthcare_domain(prompt)
    if re.search(r"school|student|course|teacher|enrollment|grade|university", prompt):
        return _education_domain(prompt)
    # Default: generic business domain
    return _generic_domain(prompt)


def _banking_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    kyc_status = "IN ('pending', 'approved', 'failed', 'expired')"
    acct_type = "IN ('checking', 'savings', 'business', 'joint')"
    txn_type = "IN ('deposit', 'withdrawal', 'transfer', 'payment', 'fee')"
    txn_status = "IN ('completed', 'pending', 'failed', 'reversed')"

    entities = [
        InferredEntity(
            name="customers",
            description="Bank customers",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="first_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="last_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True),
                InferredColumn(name="phone", data_type="VARCHAR(20)", nullable=True),
                InferredColumn(name="date_of_birth", data_type="DATE", nullable=False),
                InferredColumn(name="kyc_status", data_type="VARCHAR(20)", nullable=False, check_constraint=kyc_status),
                InferredColumn(name="kyc_verified_at", data_type="TIMESTAMP", nullable=True),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
        InferredEntity(
            name="accounts",
            description="Bank accounts",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="customer_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="account_number", data_type="VARCHAR(20)", nullable=False, is_unique=True),
                InferredColumn(name="account_type", data_type="VARCHAR(20)", nullable=False, check_constraint=acct_type),
                InferredColumn(name="balance", data_type="DECIMAL(15,2)", nullable=False),
                InferredColumn(name="currency", data_type="VARCHAR(3)", nullable=False),
                InferredColumn(name="is_active", data_type="BOOLEAN", nullable=False),
                InferredColumn(name="opened_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
        InferredEntity(
            name="transactions",
            description="Financial transactions",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="account_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="transaction_type", data_type="VARCHAR(20)", nullable=False, check_constraint=txn_type),
                InferredColumn(name="amount", data_type="DECIMAL(15,2)", nullable=False),
                InferredColumn(name="currency", data_type="VARCHAR(3)", nullable=False),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint=txn_status),
                InferredColumn(name="description", data_type="VARCHAR(500)", nullable=True),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="accounts", from_column="customer_id", to_table="customers", to_column="id"),
        InferredRelationship(from_table="transactions", from_column="account_id", to_table="accounts", to_column="id"),
    ]

    return "banking", entities, relationships


def _insurance_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    policy_status = "IN ('active', 'expired', 'cancelled', 'pending')"
    claim_status = "IN ('filed', 'under_review', 'approved', 'denied', 'paid')"
    policy_type = "IN ('life', 'health', 'auto', 'property', 'travel')"

    entities = [
        InferredEntity(
            name="policyholders",
            description="Insurance policyholders",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="first_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="last_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True),
                InferredColumn(name="phone", data_type="VARCHAR(20)", nullable=True),
                InferredColumn(name="date_of_birth", data_type="DATE", nullable=False),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
        InferredEntity(
            name="policies",
            description="Insurance policies",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="policyholder_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="policy_number", data_type="VARCHAR(20)", nullable=False, is_unique=True),
                InferredColumn(name="policy_type", data_type="VARCHAR(20)", nullable=False, check_constraint=policy_type),
                InferredColumn(name="coverage_amount", data_type="DECIMAL(15,2)", nullable=False),
                InferredColumn(name="premium", data_type="DECIMAL(10,2)", nullable=False),
                InferredColumn(name="start_date", data_type="DATE", nullable=False),
                InferredColumn(name="end_date", data_type="DATE", nullable=False),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint=policy_status),
            ],
        ),
        InferredEntity(
            name="claims",
            description="Insurance claims",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="policy_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="claim_amount", data_type="DECIMAL(15,2)", nullable=False),
                InferredColumn(name="claim_date", data_type="DATE", nullable=False),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint=claim_status),
                InferredColumn(name="description", data_type="TEXT", nullable=True),
                InferredColumn(name="approved_amount", data_type="DECIMAL(15,2)", nullable=True),
            ],
        ),
        InferredEntity(
            name="payments",
            description="Claim payments",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="claim_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="amount", data_type="DECIMAL(15,2)", nullable=False),
                InferredColumn(name="payment_date", data_type="DATE", nullable=False),
                InferredColumn(name="payment_method", data_type="VARCHAR(50)", nullable=False),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="policies", from_column="policyholder_id", to_table="policyholders", to_column="id"),
        InferredRelationship(from_table="claims", from_column="policy_id", to_table="policies", to_column="id"),
        InferredRelationship(from_table="payments", from_column="claim_id", to_table="claims", to_column="id"),
    ]

    return "insurance", entities, relationships


def _ecommerce_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    order_status = "IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled', 'returned')"

    entities = [
        InferredEntity(
            name="customers",
            description="E-commerce customers",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="name", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True),
                InferredColumn(name="phone", data_type="VARCHAR(20)", nullable=True),
                InferredColumn(name="address", data_type="TEXT", nullable=True),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
        InferredEntity(
            name="products",
            description="Product catalog",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="name", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="description", data_type="TEXT", nullable=True),
                InferredColumn(name="price", data_type="DECIMAL(10,2)", nullable=False),
                InferredColumn(name="stock_quantity", data_type="INTEGER", nullable=False),
                InferredColumn(name="category", data_type="VARCHAR(100)", nullable=True),
                InferredColumn(name="is_active", data_type="BOOLEAN", nullable=False),
            ],
        ),
        InferredEntity(
            name="orders",
            description="Customer orders",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="customer_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="order_date", data_type="TIMESTAMP", nullable=False),
                InferredColumn(name="total_amount", data_type="DECIMAL(12,2)", nullable=False),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint=order_status),
                InferredColumn(name="shipping_address", data_type="TEXT", nullable=False),
            ],
        ),
        InferredEntity(
            name="order_items",
            description="Line items in an order",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="order_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="product_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="quantity", data_type="INTEGER", nullable=False),
                InferredColumn(name="unit_price", data_type="DECIMAL(10,2)", nullable=False),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="orders", from_column="customer_id", to_table="customers", to_column="id"),
        InferredRelationship(from_table="order_items", from_column="order_id", to_table="orders", to_column="id"),
        InferredRelationship(from_table="order_items", from_column="product_id", to_table="products", to_column="id"),
    ]

    return "e-commerce", entities, relationships


def _healthcare_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    entities = [
        InferredEntity(
            name="patients",
            description="Registered patients",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="first_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="last_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="date_of_birth", data_type="DATE", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=True, is_unique=True),
                InferredColumn(name="phone", data_type="VARCHAR(20)", nullable=True),
                InferredColumn(name="blood_type", data_type="VARCHAR(5)", nullable=True, check_constraint="IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')"),
            ],
        ),
        InferredEntity(
            name="doctors",
            description="Medical practitioners",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="first_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="last_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="specialization", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="license_number", data_type="VARCHAR(50)", nullable=False, is_unique=True),
            ],
        ),
        InferredEntity(
            name="appointments",
            description="Patient appointments",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="patient_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="doctor_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="appointment_date", data_type="TIMESTAMP", nullable=False),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint="IN ('scheduled', 'completed', 'cancelled', 'no_show')"),
                InferredColumn(name="notes", data_type="TEXT", nullable=True),
            ],
        ),
        InferredEntity(
            name="prescriptions",
            description="Medical prescriptions",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="appointment_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="medication", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="dosage", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="duration_days", data_type="INTEGER", nullable=False),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="appointments", from_column="patient_id", to_table="patients", to_column="id"),
        InferredRelationship(from_table="appointments", from_column="doctor_id", to_table="doctors", to_column="id"),
        InferredRelationship(from_table="prescriptions", from_column="appointment_id", to_table="appointments", to_column="id"),
    ]

    return "healthcare", entities, relationships


def _education_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    entities = [
        InferredEntity(
            name="students",
            description="Enrolled students",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="first_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="last_name", data_type="VARCHAR(100)", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True),
                InferredColumn(name="enrollment_date", data_type="DATE", nullable=False),
                InferredColumn(name="gpa", data_type="DECIMAL(3,2)", nullable=True),
            ],
        ),
        InferredEntity(
            name="courses",
            description="Available courses",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="course_code", data_type="VARCHAR(20)", nullable=False, is_unique=True),
                InferredColumn(name="title", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="credits", data_type="INTEGER", nullable=False),
                InferredColumn(name="department", data_type="VARCHAR(100)", nullable=False),
            ],
        ),
        InferredEntity(
            name="enrollments",
            description="Student-course enrollments",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="student_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="course_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="semester", data_type="VARCHAR(20)", nullable=False),
                InferredColumn(name="grade", data_type="VARCHAR(2)", nullable=True, check_constraint="IN ('A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D', 'F')"),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="enrollments", from_column="student_id", to_table="students", to_column="id"),
        InferredRelationship(from_table="enrollments", from_column="course_id", to_table="courses", to_column="id"),
    ]

    return "education", entities, relationships


def _generic_domain(
    prompt: str,
) -> tuple[str, list[InferredEntity], list[InferredRelationship]]:
    """Fallback: create a simple users + records schema."""
    entities = [
        InferredEntity(
            name="users",
            description="Application users",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="name", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="email", data_type="VARCHAR(255)", nullable=False, is_unique=True),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
                InferredColumn(name="is_active", data_type="BOOLEAN", nullable=False),
            ],
        ),
        InferredEntity(
            name="records",
            description="User records",
            columns=[
                InferredColumn(name="id", data_type="INTEGER", nullable=False, is_primary_key=True),
                InferredColumn(name="user_id", data_type="INTEGER", nullable=False),
                InferredColumn(name="title", data_type="VARCHAR(200)", nullable=False),
                InferredColumn(name="description", data_type="TEXT", nullable=True),
                InferredColumn(name="status", data_type="VARCHAR(20)", nullable=False, check_constraint="IN ('active', 'archived', 'deleted')"),
                InferredColumn(name="created_at", data_type="TIMESTAMP", nullable=False),
            ],
        ),
    ]

    relationships = [
        InferredRelationship(from_table="records", from_column="user_id", to_table="users", to_column="id"),
    ]

    return "general", entities, relationships
