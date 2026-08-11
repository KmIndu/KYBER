"""Reference-document entity extractor.

Takes OCR text (and optionally the raw image bytes) and extracts:
  - Entities (tables)
  - Fields (columns) with data types and constraints
  - Relationships (foreign keys)
  - Domain-level constraints

Two extraction modes:
  1. AI-enriched — sends text + context to the AI gateway
  2. Heuristic — regex / keyword-based offline extraction

Confidence scoring is applied at every level.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models.reference import (
    ExtractionSource,
    ExtractedConstraint,
    ExtractedEntity,
    ExtractedField,
    ExtractedRelationship,
    OCRResult,
    ReferenceDocType,
    ReferenceIngestionResult,
)
from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when entity extraction fails."""


# ── OCR text normalization ────────────────────────────────────

# Common OCR mis-reads in SQL/schema context
_OCR_REPLACEMENTS = [
    (r"(?<=\d)@(?=[\s,)\]}])", "0"),  # @ → 0 when after digits
    (r"(?<=\w)\s+(?=_\w)", ""),       # close gaps around underscores: "policy _type" → "policy_type"
    (r"(?<=\w_)\s+(?=\w)", ""),       # "customer_ id" → "customer_id"
    (r"\}(?=\s)", ")"),               # } → ) at end of tokens
    (r"\{(?=\s)", "("),               # { → ( at end of tokens
    (r"(?i)\bUNTQUE\b", "UNIQUE"),    # common OCR misread
    (r"(?i)\bNOTNULL\b", "NOT NULL"), # joined words
    (r"(?i)\bINTPRIMARY\b", "INT PRIMARY"),  # joined words
    (r"(?i)\bPRlMARY\b", "PRIMARY"),  # l → I
    (r"(?i)\bVARCHAR\s*\((\d+)[})\]@]\s*\)", r"VARCHAR(\1)"),  # fix garbled type suffixes
]

_OCR_COMPILED = [(re.compile(p), r) for p, r in _OCR_REPLACEMENTS]


def _normalise_ocr_text(text: str) -> str:
    """Clean common OCR artefacts from text to improve extraction accuracy."""
    if not text:
        return text
    for pattern, replacement in _OCR_COMPILED:
        text = pattern.sub(replacement, text)
    return text


# ── Public API ────────────────────────────────────────────────


def extract_entities_from_ocr(
    ocr: OCRResult,
    doc_type: ReferenceDocType,
    filename: str = "",
) -> ReferenceIngestionResult:
    """Extract structured entities from OCR output using heuristics.

    This is the offline / fallback path. The AI-enriched path is
    handled by the AI service layer and merges on top of this.
    """
    text = _normalise_ocr_text(ocr.raw_text)

    # Detect domain
    domain = _detect_domain(text)

    # Classify document and extract accordingly
    if doc_type == ReferenceDocType.SCHEMA_IMAGE:
        entities, relationships, constraints = _extract_schema_image(text)
    elif doc_type == ReferenceDocType.API_SCREENSHOT:
        entities, relationships, constraints = _extract_api_screenshot(text)
    elif doc_type == ReferenceDocType.BRD_SNIPPET:
        entities, relationships, constraints = _extract_brd_snippet(text)
    else:
        entities, relationships, constraints = _extract_generic_screenshot(text)

    # Compute overall confidence
    all_confs = [e.confidence for e in entities]
    all_confs += [f.confidence for e in entities for f in e.fields]
    all_confs += [r.confidence for r in relationships]
    avg_conf = round(sum(all_confs) / len(all_confs), 3) if all_confs else 0.0

    # Generate SQL DDL
    schema = _build_schema(entities, relationships)
    ddl = _schema_to_ddl(schema)
    gen_order = _generation_order(entities, relationships)

    warnings: list[str] = []
    if not text.strip():
        warnings.append("OCR returned no text — results based on AI or fallback heuristics only")
    if avg_conf < 0.3:
        warnings.append("Low overall confidence — review extracted entities carefully")

    return ReferenceIngestionResult(
        doc_type=doc_type,
        filename=filename,
        ocr=ocr,
        entities=entities,
        relationships=relationships,
        constraints=constraints,
        domain=domain,
        schema_sql=ddl,
        avg_confidence=avg_conf,
        warnings=warnings,
    )


# ── Domain detection ──────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "banking": [
        "account", "transaction", "balance", "deposit", "withdrawal",
        "transfer", "bank", "ledger", "kyc", "loan", "mortgage",
    ],
    "insurance": [
        "policy", "claim", "premium", "coverage", "underwriting",
        "beneficiary", "insured", "deductible", "endorsement",
    ],
    "ecommerce": [
        "product", "order", "cart", "payment", "shipping",
        "inventory", "catalog", "sku", "checkout", "refund",
    ],
    "healthcare": [
        "patient", "doctor", "diagnosis", "prescription", "appointment",
        "medical", "treatment", "medication", "hospital", "clinical",
    ],
    "education": [
        "student", "course", "enrollment", "grade", "instructor",
        "semester", "curriculum", "faculty", "transcript", "gpa",
    ],
}


def _detect_domain(text: str) -> str:
    lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in lower)
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] >= 2 else "generic"


# ── Schema image extraction ──────────────────────────────────

# Patterns for CREATE TABLE, column definitions, etc.
_CREATE_TABLE_RE = re.compile(
    r"(?:CREATE\s+TABLE\s+)([`\"\']?\w+[`\"\']?)",
    re.IGNORECASE,
)
_COLUMN_DEF_RE = re.compile(
    r"(?:^|[,(])\s*([`\"\']?\w+[`\"\']?)\s+((?:VAR)?CHAR|INT(?:EGER)?|TEXT|BOOL(?:EAN)?|DATE(?:TIME)?|TIME(?:STAMP)?|FLOAT|DOUBLE|DECIMAL|NUMERIC|BIGINT|SMALLINT|UUID|SERIAL|MONEY|BLOB|CLOB)\b",
    re.IGNORECASE | re.MULTILINE,
)
_PK_RE = re.compile(r"PRIMARY\s+KEY", re.IGNORECASE)
_FK_RE = re.compile(
    r"(?:FOREIGN\s+KEY\s*\(\s*(\w+)\s*\)\s*REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\))",
    re.IGNORECASE,
)
_NOT_NULL_RE = re.compile(r"NOT\s+NULL", re.IGNORECASE)
_UNIQUE_RE = re.compile(r"\bUNIQUE\b", re.IGNORECASE)
_CHECK_RE = re.compile(r"CHECK\s*\(([^)]+)\)", re.IGNORECASE)

# Patterns for tabular data (field | type | description)
_TABLE_HEADER_RE = re.compile(
    r"(?:field|column|attribute|name)\s*[\|:]\s*(?:type|data\s*type)\b",
    re.IGNORECASE,
)
_TABLE_ROW_RE = re.compile(
    r"(\w[\w_]*)\s*[\|:]\s*((?:VAR)?CHAR|INT(?:EGER)?|TEXT|BOOL(?:EAN)?|DATE(?:TIME)?|FLOAT|DOUBLE|DECIMAL|NUMERIC|BIGINT|UUID|SERIAL|STRING|NUMBER)\b",
    re.IGNORECASE,
)

# Entity name patterns (headings like "Table: customers" or "Entity: Account")
_ENTITY_HEADING_RE = re.compile(
    r"(?:table|entity|model|object|resource)\s*[:=\-]\s*([A-Z]\w+)",
    re.IGNORECASE,
)


def _extract_schema_image(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Extract entities from text that looks like SQL DDL or schema diagrams."""
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []
    constraints: list[ExtractedConstraint] = []

    # Try CREATE TABLE statements first
    create_matches = list(_CREATE_TABLE_RE.finditer(text))
    if create_matches:
        return _parse_ddl_text(text, create_matches)

    # Try tabular format (field | type)
    if _TABLE_HEADER_RE.search(text):
        return _parse_tabular_schema(text)

    # Try entity headings
    heading_matches = list(_ENTITY_HEADING_RE.finditer(text))
    if heading_matches:
        return _parse_entity_headings(text, heading_matches)

    # Last resort: extract any identifiable field patterns
    return _extract_field_patterns(text)


def _parse_ddl_text(
    text: str,
    create_matches: list[re.Match],
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Parse CREATE TABLE statements from OCR text."""
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []
    constraints: list[ExtractedConstraint] = []

    # SQL keywords that should never be treated as column names
    _SQL_KEYWORDS = {
        "foreign", "primary", "key", "references", "constraint", "check",
        "unique", "index", "not", "null", "default", "create", "table",
        "alter", "drop", "insert", "select", "from", "where", "and", "or",
    }

    for i, match in enumerate(create_matches):
        table_name = match.group(1).strip("`\"'")
        # Get text until next CREATE TABLE or end
        start = match.end()
        end = create_matches[i + 1].start() if i + 1 < len(create_matches) else len(text)
        block = text[start:end]

        fields: list[ExtractedField] = []
        for col_match in _COLUMN_DEF_RE.finditer(block):
            col_name = col_match.group(1).strip("`\"'")
            col_type = col_match.group(2).upper()

            # Skip SQL keywords mistakenly matched as column names
            if col_name.lower() in _SQL_KEYWORDS:
                continue

            # Get trailing context for constraint detection
            line_end = min(col_match.end() + 200, len(block))
            # Find next column or end of statement
            next_col = _COLUMN_DEF_RE.search(block, col_match.end())
            if next_col:
                line_end = next_col.start()
            line = block[col_match.start():line_end]

            is_pk = bool(_PK_RE.search(line))
            is_nullable = not bool(_NOT_NULL_RE.search(line))
            is_unique = bool(_UNIQUE_RE.search(line))
            check = None
            check_match = _CHECK_RE.search(line)
            if check_match:
                check = check_match.group(1).strip()

            fields.append(
                ExtractedField(
                    name=col_name,
                    data_type=col_type,
                    nullable=is_nullable,
                    is_primary_key=is_pk,
                    is_unique=is_unique,
                    check_constraint=check,
                    source=ExtractionSource.OCR,
                    confidence=0.8,
                )
            )

        # FK detection
        for fk_match in _FK_RE.finditer(block):
            relationships.append(
                ExtractedRelationship(
                    from_entity=table_name,
                    from_field=fk_match.group(1),
                    to_entity=fk_match.group(2),
                    to_field=fk_match.group(3),
                    source=ExtractionSource.OCR,
                    confidence=0.8,
                )
            )

        # CHECK constraints
        for ck_match in _CHECK_RE.finditer(block):
            constraints.append(
                ExtractedConstraint(
                    entity=table_name,
                    field="",
                    rule=ck_match.group(1).strip(),
                    source=ExtractionSource.OCR,
                    confidence=0.7,
                )
            )

        entities.append(
            ExtractedEntity(
                name=table_name,
                fields=fields,
                source=ExtractionSource.OCR,
                confidence=0.8 if fields else 0.4,
            )
        )

    return entities, relationships, constraints


def _parse_tabular_schema(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Parse tabular field|type layouts."""
    fields: list[ExtractedField] = []
    for row_match in _TABLE_ROW_RE.finditer(text):
        fields.append(
            ExtractedField(
                name=row_match.group(1),
                data_type=row_match.group(2).upper(),
                source=ExtractionSource.OCR,
                confidence=0.7,
            )
        )

    # Try to find a table name
    heading = _ENTITY_HEADING_RE.search(text)
    name = heading.group(1) if heading else "extracted_table"

    entities = [
        ExtractedEntity(
            name=name, fields=fields, source=ExtractionSource.OCR, confidence=0.7
        )
    ] if fields else []

    return entities, [], []


def _parse_entity_headings(
    text: str,
    heading_matches: list[re.Match],
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Parse entity names from headings and attempt to find their fields."""
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []

    for i, match in enumerate(heading_matches):
        entity_name = match.group(1)
        start = match.end()
        end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)
        block = text[start:end]

        fields: list[ExtractedField] = []
        for col_match in _COLUMN_DEF_RE.finditer(block):
            fields.append(
                ExtractedField(
                    name=col_match.group(1).strip("`\"'"),
                    data_type=col_match.group(2).upper(),
                    source=ExtractionSource.OCR,
                    confidence=0.6,
                )
            )

        # Also try row-style parsing
        if not fields:
            for row_match in _TABLE_ROW_RE.finditer(block):
                fields.append(
                    ExtractedField(
                        name=row_match.group(1),
                        data_type=row_match.group(2).upper(),
                        source=ExtractionSource.OCR,
                        confidence=0.6,
                    )
                )

        entities.append(
            ExtractedEntity(
                name=entity_name,
                fields=fields,
                source=ExtractionSource.OCR,
                confidence=0.6 if fields else 0.3,
            )
        )

    return entities, relationships, []


def _extract_field_patterns(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Last-resort: find anything that looks like field definitions."""
    fields: list[ExtractedField] = []
    for col_match in _COLUMN_DEF_RE.finditer(text):
        fields.append(
            ExtractedField(
                name=col_match.group(1).strip("`\"'"),
                data_type=col_match.group(2).upper(),
                source=ExtractionSource.OCR,
                confidence=0.4,
            )
        )

    for row_match in _TABLE_ROW_RE.finditer(text):
        name = row_match.group(1)
        if not any(f.name == name for f in fields):
            fields.append(
                ExtractedField(
                    name=name,
                    data_type=row_match.group(2).upper(),
                    source=ExtractionSource.OCR,
                    confidence=0.4,
                )
            )

    entities = [
        ExtractedEntity(
            name="extracted_table",
            fields=fields,
            source=ExtractionSource.OCR,
            confidence=0.3,
        )
    ] if fields else []

    return entities, [], []


# ── API screenshot extraction ─────────────────────────────────

_ENDPOINT_RE = re.compile(
    r"(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}:\-]+)",
    re.IGNORECASE,
)
_JSON_FIELD_RE = re.compile(
    r'["\'](\w+)["\']\s*:\s*(?:["\']([^"\']+)["\']|(\d+(?:\.\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|\[|\{)',
    re.IGNORECASE,
)
_TYPE_MAP = {
    "string": "VARCHAR",
    "integer": "INTEGER",
    "number": "DECIMAL",
    "boolean": "BOOLEAN",
    "array": "TEXT",
    "object": "TEXT",
}


def _extract_api_screenshot(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Extract entities from API documentation / Swagger screenshots."""
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []

    # Find endpoints to infer entity names
    endpoints = _ENDPOINT_RE.findall(text)
    entity_names: list[str] = []
    for _, path in endpoints:
        parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
        if parts:
            name = parts[-1].rstrip("s")  # crude singularisation
            if name not in entity_names:
                entity_names.append(name)

    # Find JSON fields
    json_fields: list[ExtractedField] = []
    for match in _JSON_FIELD_RE.finditer(text):
        field_name = match.group(1)
        if match.group(2) is not None:
            dtype = "VARCHAR"
        elif match.group(3) is not None:
            dtype = "DECIMAL" if "." in match.group(3) else "INTEGER"
        elif match.group(4) is not None:
            val = match.group(4).lower()
            dtype = "BOOLEAN" if val in ("true", "false") else "VARCHAR"
        else:
            dtype = "TEXT"

        if not any(f.name == field_name for f in json_fields):
            json_fields.append(
                ExtractedField(
                    name=field_name,
                    data_type=dtype,
                    source=ExtractionSource.OCR,
                    confidence=0.6,
                )
            )

    # Build entities
    if entity_names:
        for name in entity_names:
            entities.append(
                ExtractedEntity(
                    name=name,
                    fields=json_fields.copy(),
                    source=ExtractionSource.OCR,
                    confidence=0.5,
                )
            )
    elif json_fields:
        entities.append(
            ExtractedEntity(
                name="api_entity",
                fields=json_fields,
                source=ExtractionSource.OCR,
                confidence=0.4,
            )
        )

    # Infer relationships from _id fields
    for entity in entities:
        for field in entity.fields:
            if field.name.endswith("_id") and field.name != "id":
                ref_name = field.name[:-3]
                if any(e.name == ref_name for e in entities):
                    relationships.append(
                        ExtractedRelationship(
                            from_entity=entity.name,
                            from_field=field.name,
                            to_entity=ref_name,
                            to_field="id",
                            source=ExtractionSource.HEURISTIC,
                            confidence=0.5,
                        )
                    )

    return entities, relationships, []


# ── BRD snippet extraction ────────────────────────────────────

_BRD_ENTITY_RE = re.compile(
    r"\b(?:the\s+)?(\w+)\s+(?:table|entity|object|record|document)\b",
    re.IGNORECASE,
)
_BRD_FIELD_RE = re.compile(
    r"\b(\w+(?:\s+\w+)?)\s+(?:field|column|attribute|property)\b",
    re.IGNORECASE,
)
_BRD_RULE_RE = re.compile(
    r"(?:must|should|shall|requires?|mandatory|required)\s+(.{10,80})",
    re.IGNORECASE,
)
_BRD_RELATIONSHIP_RE = re.compile(
    r"(\w+)\s+(?:has many|has one|belongs to|references|links? to)\s+(\w+)",
    re.IGNORECASE,
)


def _extract_brd_snippet(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Extract entities from Business Requirements Documents (BRDs)."""
    entities_map: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []
    constraints: list[ExtractedConstraint] = []

    # Find entity mentions
    for match in _BRD_ENTITY_RE.finditer(text):
        name = match.group(1).lower()
        if name not in entities_map and len(name) > 2:
            entities_map[name] = ExtractedEntity(
                name=name,
                source=ExtractionSource.OCR,
                confidence=0.5,
            )

    # Find field mentions  
    for match in _BRD_FIELD_RE.finditer(text):
        field_text = match.group(1).strip()
        field_name = field_text.lower().replace(" ", "_")
        # Try to associate with nearest entity
        for entity in entities_map.values():
            if not any(f.name == field_name for f in entity.fields):
                entity.fields.append(
                    ExtractedField(
                        name=field_name,
                        data_type="VARCHAR",
                        source=ExtractionSource.OCR,
                        confidence=0.4,
                    )
                )
                break

    # Find relationships
    for match in _BRD_RELATIONSHIP_RE.finditer(text):
        from_entity = match.group(1).lower()
        to_entity = match.group(2).lower()
        # Auto-create entities discovered via relationship mentions
        for ename in (from_entity, to_entity):
            if ename not in entities_map and len(ename) > 2:
                entities_map[ename] = ExtractedEntity(
                    name=ename,
                    source=ExtractionSource.OCR,
                    confidence=0.4,
                )
        relationships.append(
            ExtractedRelationship(
                from_entity=from_entity,
                from_field=f"{to_entity}_id",
                to_entity=to_entity,
                to_field="id",
                source=ExtractionSource.OCR,
                confidence=0.4,
            )
        )

    # Find constraints / rules
    for match in _BRD_RULE_RE.finditer(text):
        rule_text = match.group(1).strip().rstrip(".")
        entity_name = ""
        for name in entities_map:
            if name in rule_text.lower():
                entity_name = name
                break
        constraints.append(
            ExtractedConstraint(
                entity=entity_name,
                field="",
                rule=rule_text,
                source=ExtractionSource.OCR,
                confidence=0.4,
            )
        )

    entities = list(entities_map.values())
    return entities, relationships, constraints


# ── Generic screenshot extraction ─────────────────────────────


def _extract_generic_screenshot(
    text: str,
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship], list[ExtractedConstraint]]:
    """Attempt extraction from any screenshot — tries all strategies."""
    # Try schema patterns first
    entities, rels, cons = _extract_schema_image(text)
    if entities:
        return entities, rels, cons

    # Try API patterns
    entities, rels, cons = _extract_api_screenshot(text)
    if entities:
        return entities, rels, cons

    # Try BRD patterns
    return _extract_brd_snippet(text)


# ── Schema builder ────────────────────────────────────────────


def _build_schema(
    entities: list[ExtractedEntity],
    relationships: list[ExtractedRelationship],
) -> SchemaMetadata:
    """Convert extracted entities into a normalised SchemaMetadata."""
    tables: list[TableMetadata] = []

    for entity in entities:
        columns: list[ColumnMetadata] = []
        primary_keys: list[str] = []
        has_pk = any(f.is_primary_key for f in entity.fields)

        # Add auto PK if none found
        if not has_pk and entity.fields:
            columns.append(
                ColumnMetadata(
                    name="id",
                    data_type="INTEGER",
                    nullable=False,
                    is_primary_key=True,
                    is_unique=True,
                )
            )
            primary_keys.append("id")

        for field in entity.fields:
            columns.append(
                ColumnMetadata(
                    name=field.name,
                    data_type=field.data_type,
                    nullable=field.nullable,
                    is_primary_key=field.is_primary_key,
                    is_unique=field.is_unique,
                    check_constraint=field.check_constraint,
                )
            )
            if field.is_primary_key:
                primary_keys.append(field.name)

        # Build FK list for this table
        foreign_keys: list[ForeignKeyMetadata] = []
        for rel in relationships:
            if rel.from_entity == entity.name:
                foreign_keys.append(
                    ForeignKeyMetadata(
                        column=rel.from_field,
                        references_table=rel.to_entity,
                        references_column=rel.to_field,
                    )
                )
                # Ensure the FK column exists
                if not any(c.name == rel.from_field for c in columns):
                    columns.append(
                        ColumnMetadata(
                            name=rel.from_field,
                            data_type="INTEGER",
                            nullable=True,
                        )
                    )

        tables.append(
            TableMetadata(
                name=entity.name,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=foreign_keys,
            )
        )

    return SchemaMetadata(tables=tables)


def _schema_to_ddl(schema: SchemaMetadata) -> str:
    """Generate SQL DDL from normalised schema metadata."""
    statements: list[str] = []

    for table in schema.tables:
        lines: list[str] = []
        for col in table.columns:
            parts = [f"  {col.name} {col.data_type}"]
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if not col.nullable and not col.is_primary_key:
                parts.append("NOT NULL")
            if col.is_unique and not col.is_primary_key:
                parts.append("UNIQUE")
            if col.check_constraint:
                parts.append(f"CHECK ({col.check_constraint})")
            lines.append(" ".join(parts))

        for fk in table.foreign_keys:
            lines.append(
                f"  FOREIGN KEY ({fk.column}) REFERENCES {fk.references_table}({fk.references_column})"
            )

        body = ",\n".join(lines)
        statements.append(f"CREATE TABLE {table.name} (\n{body}\n);")

    return "\n\n".join(statements)


def _generation_order(
    entities: list[ExtractedEntity],
    relationships: list[ExtractedRelationship],
) -> list[str]:
    """Determine generation order respecting FK dependencies."""
    names = [e.name for e in entities]
    deps: dict[str, set[str]] = {n: set() for n in names}
    for rel in relationships:
        if rel.from_entity in deps and rel.to_entity in names:
            deps[rel.from_entity].add(rel.to_entity)

    ordered: list[str] = []
    remaining = set(names)
    max_iter = len(names) * 2
    i = 0
    while remaining and i < max_iter:
        for name in list(remaining):
            if deps[name] <= set(ordered):
                ordered.append(name)
                remaining.discard(name)
        i += 1

    # Add any remaining (circular deps) at the end
    for name in names:
        if name not in ordered:
            ordered.append(name)

    return ordered
