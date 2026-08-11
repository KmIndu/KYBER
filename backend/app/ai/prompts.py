"""Prompt templates for AI reasoning.

Each template is a function that accepts structured metadata and returns
a prompt string.  Templates are pure functions — no I/O, no side effects.
"""

from __future__ import annotations

from typing import Any


# ── System prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a test-data reasoning engine for an insurance domain.\n"
    "Your job is to analyze database schemas, API specs, and BDD rules\n"
    "to infer HIDDEN constraints, business rules, and edge cases.\n\n"
    "IMPORTANT:\n"
    "- Do NOT generate data rows. Only produce reasoning instructions.\n"
    "- Output ONLY valid JSON — no markdown, no commentary.\n"
    "- Use the exact JSON structure specified in each prompt.\n"
)


# ── Schema analysis prompt ────────────────────────────────────

_SCHEMA_TEMPLATE = """\
Analyze this SQL schema and infer hidden constraints, business rules, \
and edge cases that are NOT explicitly declared in the DDL.

Schema:
{schema_text}

Return JSON:
{{
  "hidden_constraints": [
    {{"table": "...", "column": "...", "constraint_type": "...", "description": "...", "suggestion": {{}}}}
  ],
  "business_rules": [
    {{"table": "...", "column": "...", "constraint_type": "business_rule", "description": "...", "suggestion": {{}}}}
  ],
  "edge_cases": [
    {{"table": "...", "column": "...", "scenario": "...", "test_value": ...}}
  ]
}}

constraint_type must be one of: range, format, dependency, business_rule, edge_case.
Focus on the insurance domain. Think about:
- date ordering (start_date < end_date)
- age ranges for policyholders
- claim amount vs coverage amount
- payment totals vs claim amounts
- email/phone format expectations
- status transition rules
"""


def build_schema_prompt(schema_text: str) -> str:
    return _SCHEMA_TEMPLATE.format(schema_text=schema_text)


# ── BDD analysis prompt ──────────────────────────────────────

_BDD_TEMPLATE = """\
Analyze these BDD/Gherkin scenarios and infer additional business rules, \
hidden constraints, and edge cases for data generation.

BDD Scenarios:
{bdd_text}

{schema_context}

Return JSON:
{{
  "hidden_constraints": [
    {{"table": "...", "column": "...", "constraint_type": "...", "description": "...", "suggestion": {{}}}}
  ],
  "business_rules": [
    {{"table": "...", "column": "...", "constraint_type": "business_rule", "description": "...", "suggestion": {{}}}}
  ],
  "edge_cases": [
    {{"table": "...", "column": "...", "scenario": "...", "test_value": ...}}
  ]
}}

constraint_type must be one of: range, format, dependency, business_rule, edge_case.
Infer what the BDD scenarios imply about data constraints beyond what is stated.
"""


def build_bdd_prompt(bdd_text: str, schema_text: str = "") -> str:
    ctx = f"Related schema:\n{schema_text}" if schema_text else ""
    return _BDD_TEMPLATE.format(bdd_text=bdd_text, schema_context=ctx)


# ── OpenAPI analysis prompt ───────────────────────────────────

_OPENAPI_TEMPLATE = """\
Analyze this OpenAPI specification and infer hidden constraints, \
business rules, and edge cases for test data generation.

OpenAPI spec:
{openapi_text}

Return JSON:
{{
  "hidden_constraints": [
    {{"table": "...", "column": "...", "constraint_type": "...", "description": "...", "suggestion": {{}}}}
  ],
  "business_rules": [
    {{"table": "...", "column": "...", "constraint_type": "business_rule", "description": "...", "suggestion": {{}}}}
  ],
  "edge_cases": [
    {{"table": "...", "column": "...", "scenario": "...", "test_value": ...}}
  ]
}}

constraint_type must be one of: range, format, dependency, business_rule, edge_case.
"""


def build_openapi_prompt(openapi_text: str) -> str:
    return _OPENAPI_TEMPLATE.format(openapi_text=openapi_text)


# ── Combined analysis prompt ─────────────────────────────────

_COMBINED_TEMPLATE = """\
Analyze ALL of the following inputs together and produce a unified set of \
hidden constraints, business rules, and edge cases.

{sections}

Return JSON:
{{
  "hidden_constraints": [
    {{"table": "...", "column": "...", "constraint_type": "...", "description": "...", "suggestion": {{}}}}
  ],
  "business_rules": [
    {{"table": "...", "column": "...", "constraint_type": "business_rule", "description": "...", "suggestion": {{}}}}
  ],
  "edge_cases": [
    {{"table": "...", "column": "...", "scenario": "...", "test_value": ...}}
  ]
}}

constraint_type must be one of: range, format, dependency, business_rule, edge_case.
Cross-reference the schema, API spec, and BDD rules to find constraints \
implied by the combination that no single source reveals alone.
"""


def build_combined_prompt(
    schema_text: str = "",
    bdd_text: str = "",
    openapi_text: str = "",
) -> str:
    parts: list[str] = []
    if schema_text:
        parts.append(f"SQL Schema:\n{schema_text}")
    if bdd_text:
        parts.append(f"BDD Scenarios:\n{bdd_text}")
    if openapi_text:
        parts.append(f"OpenAPI Spec:\n{openapi_text}")
    return _COMBINED_TEMPLATE.format(sections="\n\n---\n\n".join(parts))


# ── Natural-language → schema inference prompt ────────────────

NL_SYSTEM_PROMPT = (
    "You are a database schema architect.\n"
    "Your job is to analyze a natural-language description and produce\n"
    "a complete relational database schema — entities, columns, types,\n"
    "keys, relationships, and constraints.\n\n"
    "IMPORTANT:\n"
    "- Do NOT generate data rows.\n"
    "- Output ONLY valid JSON — no markdown, no commentary.\n"
    "- Use the exact JSON structure specified in the prompt.\n"
    "- Infer realistic column types, constraints, and relationships.\n"
    "- Include domain-specific edge cases.\n"
)

_NL_SCHEMA_TEMPLATE = """\
A user wants to generate synthetic test data. They described their needs as:

"{user_prompt}"

From this description, infer:
1. The business domain
2. All relevant entities (database tables)
3. Columns for each entity with appropriate SQL data types
4. Primary keys, foreign keys, and unique constraints
5. CHECK constraints (e.g. enums, value ranges)
6. Relationships between entities
7. Domain-specific constraints and business rules

Return JSON:
{{
  "domain": "the inferred business domain",
  "entities": [
    {{
      "name": "table_name",
      "description": "what this table represents",
      "columns": [
        {{
          "name": "column_name",
          "data_type": "SQL type (e.g. INTEGER, VARCHAR(255), DATE, BOOLEAN, DECIMAL(10,2))",
          "nullable": true,
          "is_primary_key": false,
          "is_unique": false,
          "check_constraint": "optional CHECK expression or null",
          "description": "what this column represents"
        }}
      ]
    }}
  ],
  "relationships": [
    {{
      "from_table": "child_table",
      "from_column": "fk_column",
      "to_table": "parent_table",
      "to_column": "pk_column"
    }}
  ],
  "constraints": [
    {{
      "table": "table_name",
      "column": "column_name",
      "rule": "business rule description",
      "description": "why this constraint exists"
    }}
  ]
}}

Rules:
- Every table MUST have a primary key (usually an INTEGER id column).
- Use realistic SQL types: INTEGER, VARCHAR(n), TEXT, DATE, TIMESTAMP, BOOLEAN, DECIMAL(p,s).
- Include status/type columns with CHECK IN constraints where appropriate.
- Add NOT NULL (nullable=false) for required fields.
- Make foreign keys reference the parent table's primary key.
- Include 3-8 tables with 4-10 columns each — enough for a realistic domain.
- Think about edge cases mentioned in the prompt (e.g. "failed KYC", "fraud").
"""


def build_nl_schema_prompt(user_prompt: str) -> str:
    """Build a prompt that asks the AI to infer a database schema from natural language."""
    return _NL_SCHEMA_TEMPLATE.format(user_prompt=user_prompt)


# ── Reference-document enrichment prompt ──────────────────────

REFERENCE_DOC_SYSTEM_PROMPT = (
    "You are a database schema extraction expert.\n"
    "Your job is to analyze text extracted from screenshots, schema images,\n"
    "BRD documents, or API documentation and produce a complete relational\n"
    "database schema — entities, columns, types, keys, relationships,\n"
    "and constraints.\n\n"
    "IMPORTANT:\n"
    "- Do NOT generate data rows.\n"
    "- Output ONLY valid JSON — no markdown, no commentary.\n"
    "- Use the exact JSON structure specified in the prompt.\n"
    "- When OCR text is noisy, use your best judgement to correct typos.\n"
    "- Assign a confidence score (0.0–1.0) to each extracted element.\n"
)

_REFERENCE_DOC_TEMPLATE = """\
The following text was extracted via OCR from a {doc_type} image.
The OCR average confidence was {ocr_confidence:.1%}.

--- BEGIN OCR TEXT ---
{ocr_text}
--- END OCR TEXT ---

Analyze this text and extract:
1. All database entities (tables) mentioned or implied
2. Columns for each entity with appropriate SQL data types
3. Primary keys, foreign keys, and unique constraints
4. CHECK constraints (enums, value ranges)
5. Relationships between entities
6. Business rules and domain constraints

For each extracted item, provide a confidence score (0.0 to 1.0) \
based on how clearly it appeared in the source text.

Return JSON:
{{
  "domain": "the inferred business domain",
  "entities": [
    {{
      "name": "table_name",
      "description": "what this table represents",
      "confidence": 0.8,
      "columns": [
        {{
          "name": "column_name",
          "data_type": "SQL type",
          "nullable": true,
          "is_primary_key": false,
          "is_unique": false,
          "check_constraint": null,
          "description": "column description",
          "confidence": 0.8
        }}
      ]
    }}
  ],
  "relationships": [
    {{
      "from_entity": "child_table",
      "from_field": "fk_column",
      "to_entity": "parent_table",
      "to_field": "pk_column",
      "confidence": 0.7
    }}
  ],
  "constraints": [
    {{
      "entity": "table_name",
      "field": "column_name",
      "rule": "constraint description",
      "description": "why this constraint exists",
      "confidence": 0.6
    }}
  ]
}}

Rules:
- Correct obvious OCR errors in identifiers (e.g. "cust0mer_ld" → "customer_id").
- Every table MUST have a primary key.
- Use realistic SQL types: INTEGER, VARCHAR(n), TEXT, DATE, TIMESTAMP, BOOLEAN, DECIMAL(p,s).
- Low-confidence items should still be included but marked accordingly.
- If the text looks like SQL DDL, extract the schema precisely.
- If the text looks like an API spec, infer entities from endpoints and payloads.
- If the text looks like a BRD, infer entities from business requirements.
"""


def build_reference_doc_prompt(
    ocr_text: str,
    doc_type: str,
    ocr_confidence: float,
) -> str:
    """Build a prompt for AI enrichment of OCR-extracted reference documents."""
    return _REFERENCE_DOC_TEMPLATE.format(
        ocr_text=ocr_text,
        doc_type=doc_type,
        ocr_confidence=ocr_confidence,
    )


# ── Integration guide prompt ─────────────────────────────────

INTEGRATION_GUIDE_SYSTEM_PROMPT = (
    "You are a test-data integration expert.\n"
    "Your job is to produce step-by-step integration guides that help\n"
    "engineers use synthetic datasets in real environments.\n\n"
    "IMPORTANT:\n"
    "- Output ONLY valid JSON — no markdown, no commentary.\n"
    "- Use the exact JSON structure specified in the prompt.\n"
    "- Include concrete, copy-pasteable code snippets.\n"
    "- Keep instructions concise and actionable.\n"
)

_INTEGRATION_GUIDE_TEMPLATE = """\
A user generated synthetic test data with the following characteristics:

Tables: {table_names}
Total rows: {total_rows}
Available export formats: {formats}
Columns per table:
{columns_summary}

{artifacts_context}

Generate a comprehensive integration guide with step-by-step instructions \
for using this dataset in real test environments.

Cover these scenarios:
1. Importing CSV files into PostgreSQL (psql \\copy and pgAdmin)
2. Importing CSV files into MySQL (LOAD DATA and MySQL Workbench)
3. Using the Postman collection for API testing
4. Executing the SQL INSERT scripts against a database
5. Using API JSON payloads with curl / fetch / Python requests
6. Loading data into a Python test suite (pytest fixtures)

Return JSON:
{{
  "overview": "A 2-3 sentence overview of the generated dataset and what it can be used for.",
  "sections": [
    {{
      "scenario": "Short title, e.g. Import CSV into PostgreSQL",
      "summary": "One-sentence summary of this scenario",
      "prerequisites": ["list", "of", "requirements"],
      "steps": [
        {{
          "step_number": 1,
          "title": "Short step title",
          "description": "What this step does and why",
          "code_snippet": "copy-pasteable code or command",
          "language": "sql or bash or python or json or yaml"
        }}
      ],
      "tips": ["optional pro tips or gotchas"]
    }}
  ]
}}

Rules:
- Every scenario MUST have at least 2 steps with code snippets.
- Use the actual table names and column names from the dataset.
- Code snippets must be syntactically correct and ready to execute.
- Include connection strings with placeholder credentials.
- For SQL imports, respect the generation order (parent tables first).
- For API payloads, show both curl and Python requests examples.
- Include setup/teardown guidance where relevant.
"""


def build_integration_guide_prompt(
    table_names: list[str],
    total_rows: int,
    formats: list[str],
    columns_summary: str,
    artifacts_context: str = "",
) -> str:
    """Build a prompt for AI-generated integration guidance."""
    return _INTEGRATION_GUIDE_TEMPLATE.format(
        table_names=", ".join(table_names),
        total_rows=total_rows,
        formats=", ".join(formats),
        columns_summary=columns_summary,
        artifacts_context=artifacts_context,
    )
