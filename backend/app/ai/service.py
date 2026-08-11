"""AI reasoning service — facade for the AI layer.

Routes to the gateway provider when configured, otherwise falls back
to offline rule-based reasoning.  This is the single entry point that
routers and other services should use.
"""

from __future__ import annotations

import logging

from app.ai.gateway_provider import GatewayError, call_gateway
from app.ai.offline_provider import reason_offline
from app.ai.output_parser import parse_ai_response, parse_guide_response
from app.ai.prompts import (
    INTEGRATION_GUIDE_SYSTEM_PROMPT,
    NL_SYSTEM_PROMPT,
    REFERENCE_DOC_SYSTEM_PROMPT,
    build_bdd_prompt,
    build_combined_prompt,
    build_integration_guide_prompt,
    build_nl_schema_prompt,
    build_openapi_prompt,
    build_reference_doc_prompt,
    build_schema_prompt,
)
from app.models.ai import AIProviderConfig, AIReasoningResult
from app.models.bdd import BDDMetadata
from app.models.integration import (
    GuideStep,
    IntegrationGuide,
    IntegrationGuideSection,
)
from app.models.nl import NLSchemaResult
from app.models.openapi import OpenAPIMetadata
from app.models.schema import SchemaMetadata
from app.parsers.nl_schema_parser import NLParserError, infer_schema_offline, parse_nl_response
from app.utils.config import settings

logger = logging.getLogger(__name__)


def _get_config() -> AIProviderConfig:
    """Build provider config from application settings."""
    return AIProviderConfig(
        gateway_url=settings.AI_GATEWAY_URL,
        api_token=settings.AI_GATEWAY_TOKEN,
        model=settings.AI_MODEL,
        api_format=settings.AI_API_FORMAT,
        timeout=settings.AI_TIMEOUT,
        max_retries=settings.AI_MAX_RETRIES,
    )


def _gateway_available(config: AIProviderConfig) -> bool:
    return bool(config.gateway_url and config.api_token)


# ── Public API ────────────────────────────────────────────────


def analyze_schema(
    schema: SchemaMetadata,
    schema_text: str = "",
) -> AIReasoningResult:
    """Analyze a SQL schema for hidden constraints, business rules, edge cases."""
    config = _get_config()

    if _gateway_available(config):
        prompt = build_schema_prompt(schema_text or _schema_to_text(schema))
        try:
            return call_gateway(prompt, config)
        except GatewayError as e:
            logger.warning(
                "Gateway failed for schema analysis, falling back to offline: %s",
                e,
                extra={"stage": "ai_reasoning", "event": "gateway_fallback", "error_type": "GatewayError"},
            )

    return reason_offline(schema=schema)


def analyze_bdd(
    bdd: BDDMetadata,
    schema: SchemaMetadata | None = None,
    schema_text: str = "",
    bdd_text: str = "",
) -> AIReasoningResult:
    """Analyze BDD scenarios for business rules and edge cases."""
    config = _get_config()

    if _gateway_available(config):
        prompt = build_bdd_prompt(
            bdd_text or _bdd_to_text(bdd),
            schema_text,
        )
        try:
            return call_gateway(prompt, config)
        except GatewayError as e:
            logger.warning(
                "Gateway failed for BDD analysis, falling back to offline: %s",
                e,
                extra={"stage": "ai_reasoning", "event": "gateway_fallback", "error_type": "GatewayError"},
            )

    return reason_offline(schema=schema, bdd=bdd)


def analyze_openapi(
    openapi: OpenAPIMetadata,
    openapi_text: str = "",
) -> AIReasoningResult:
    """Analyze an OpenAPI spec for hidden constraints and edge cases."""
    config = _get_config()

    if _gateway_available(config):
        prompt = build_openapi_prompt(openapi_text or _openapi_to_text(openapi))
        try:
            return call_gateway(prompt, config)
        except GatewayError as e:
            logger.warning(
                "Gateway failed for OpenAPI analysis, falling back to offline: %s",
                e,
                extra={"stage": "ai_reasoning", "event": "gateway_fallback", "error_type": "GatewayError"},
            )

    return reason_offline(openapi=openapi)


def analyze_combined(
    schema: SchemaMetadata | None = None,
    bdd: BDDMetadata | None = None,
    openapi: OpenAPIMetadata | None = None,
    schema_text: str = "",
    bdd_text: str = "",
    openapi_text: str = "",
) -> AIReasoningResult:
    """Analyze all inputs together for cross-cutting insights."""
    config = _get_config()

    if _gateway_available(config):
        prompt = build_combined_prompt(
            schema_text=schema_text or (_schema_to_text(schema) if schema else ""),
            bdd_text=bdd_text or (_bdd_to_text(bdd) if bdd else ""),
            openapi_text=openapi_text or (_openapi_to_text(openapi) if openapi else ""),
        )
        try:
            return call_gateway(prompt, config)
        except GatewayError as e:
            logger.warning(
                "Gateway failed for combined analysis, falling back to offline: %s",
                e,
                extra={"stage": "ai_reasoning", "event": "gateway_fallback", "error_type": "GatewayError"},
            )

    return reason_offline(schema=schema, bdd=bdd, openapi=openapi)


# ── Text converters (metadata → prompt-friendly text) ─────────


def _schema_to_text(schema: SchemaMetadata) -> str:
    lines: list[str] = []
    for t in schema.tables:
        cols = ", ".join(
            f"{c.name} {c.data_type}"
            + (" PK" if c.is_primary_key else "")
            + (" NOT NULL" if not c.nullable else "")
            + (f" CHECK({c.check_constraint})" if c.check_constraint else "")
            for c in t.columns
        )
        fks = ", ".join(
            f"FK {fk.column} → {fk.references_table}.{fk.references_column}"
            for fk in t.foreign_keys
        )
        line = f"TABLE {t.name} ({cols})"
        if fks:
            line += f" [{fks}]"
        lines.append(line)
    return "\n".join(lines)


def _bdd_to_text(bdd: BDDMetadata) -> str:
    lines = [f"Feature: {bdd.feature}"]
    for s in bdd.scenarios:
        lines.append(f"\n  Scenario: {s.name}")
        for step in s.raw_steps:
            lines.append(f"    {step}")
    return "\n".join(lines)


def _openapi_to_text(openapi: OpenAPIMetadata) -> str:
    lines = [f"OpenAPI {openapi.openapi_version} — {openapi.title}"]
    for s in openapi.schemas:
        fields = ", ".join(
            f"{f.name}: {f.data_type}"
            + (f" (required)" if f.required else "")
            + (f" enum={f.validation.enum}" if f.validation.enum else "")
            for f in s.fields
        )
        lines.append(f"Schema {s.name}: {fields}")
    return "\n".join(lines)


# ── Natural-language → schema inference ───────────────────────


def infer_schema_from_prompt(prompt: str) -> NLSchemaResult:
    """Infer a database schema from a natural-language description.

    Uses the AI gateway when available; falls back to keyword-based
    offline heuristics otherwise.
    """
    config = _get_config()

    if _gateway_available(config):
        nl_prompt = build_nl_schema_prompt(prompt)
        try:
            raw = _send_nl_request(nl_prompt, config)
            return parse_nl_response(raw)
        except (GatewayError, NLParserError) as e:
            logger.warning(
                "AI schema inference failed, falling back to offline: %s",
                e,
                extra={"stage": "nl_inference", "event": "gateway_fallback"},
            )

    return infer_schema_offline(prompt)


def _send_nl_request(prompt: str, config: AIProviderConfig) -> str:
    """Send NL prompt to the gateway with the NL-specific system prompt."""
    import time

    import requests

    from app.ai.gateway_provider import GatewayError

    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(1, config.max_retries + 1):
        try:
            if config.api_format == "anthropic":
                payload = {
                    "model": config.model,
                    "system": NL_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/messages"):
                    url = f"{url}/messages"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
            else:
                payload = {
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": NL_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/chat/completions"):
                    url = f"{url}/chat/completions"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = GatewayError(f"NL gateway error (attempt {attempt}): {e}")
            logger.warning("NL gateway error (attempt %d/%d): %s", attempt, config.max_retries, e)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500:
                last_error = GatewayError(f"NL gateway {status} (attempt {attempt})")
            else:
                raise GatewayError(f"NL gateway client error {status}: {e}") from e

        if attempt < config.max_retries:
            time.sleep(2 ** (attempt - 1))

    raise last_error or GatewayError("NL gateway call failed")


# ── Reference-document enrichment ─────────────────────────────


def enrich_reference_doc(
    ocr_text: str,
    doc_type: str,
    ocr_confidence: float,
) -> dict | None:
    """Send OCR text to the AI gateway for entity/schema enrichment.

    Returns parsed JSON dict on success, or ``None`` if the gateway
    is unavailable or fails.
    """
    config = _get_config()

    if not _gateway_available(config):
        logger.info("AI gateway unavailable — skipping reference doc enrichment")
        return None

    prompt = build_reference_doc_prompt(ocr_text, doc_type, ocr_confidence)
    try:
        raw = _send_reference_doc_request(prompt, config)
        return _parse_reference_json(raw)
    except (GatewayError, Exception) as e:
        logger.warning(
            "Reference doc enrichment failed: %s",
            e,
            extra={"stage": "reference_enrichment", "event": "gateway_fallback"},
        )
        return None


def _send_reference_doc_request(prompt: str, config: AIProviderConfig) -> str:
    """Send reference-doc prompt to the gateway."""
    import time as _time

    import requests

    from app.ai.gateway_provider import GatewayError

    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(1, config.max_retries + 1):
        try:
            if config.api_format == "anthropic":
                payload = {
                    "model": config.model,
                    "system": REFERENCE_DOC_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/messages"):
                    url = f"{url}/messages"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
            else:
                payload = {
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": REFERENCE_DOC_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/chat/completions"):
                    url = f"{url}/chat/completions"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = GatewayError(f"Reference doc gateway error (attempt {attempt}): {e}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500:
                last_error = GatewayError(f"Reference doc gateway {status} (attempt {attempt})")
            else:
                raise GatewayError(f"Reference doc gateway client error {status}: {e}") from e

        if attempt < config.max_retries:
            _time.sleep(2 ** (attempt - 1))

    raise last_error or GatewayError("Reference doc gateway call failed")


def _parse_reference_json(raw: str) -> dict:
    """Extract JSON from AI response for reference doc enrichment."""
    import json
    import re

    # Strip code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.strip().rstrip("`")

    # Find the JSON object
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in AI response")

    return json.loads(cleaned[start:end])


# ── Integration guide ─────────────────────────────────────────


def generate_integration_guide(
    session_id: str,
    schema: SchemaMetadata,
    data: dict[str, list[dict]],
    generation_order: list[str],
    has_integration_bundle: bool = False,
) -> IntegrationGuide:
    """Generate an AI-powered integration guide for the dataset.

    Uses the gateway when configured; falls back to a deterministic
    offline guide otherwise.
    """
    table_names = generation_order or list(data.keys())
    total_rows = sum(len(rows) for rows in data.values())
    formats = ["CSV", "JSON", "SQL INSERT"]
    if has_integration_bundle:
        formats.extend(["Postman Collection", "Swagger Tests", "CI/CD Config"])

    columns_summary = _build_columns_summary(schema, table_names)
    artifacts_ctx = ""
    if has_integration_bundle:
        artifacts_ctx = (
            "The user also generated integration artifacts including:\n"
            "- Postman Collection (JSON)\n"
            "- Mock Payloads (valid / invalid / boundary)\n"
            "- SQL INSERT scripts (FK-ordered, transaction-wrapped)\n"
            "- API-ready JSON payloads (PKs stripped)\n"
            "- Swagger test suite (status-code assertions)\n"
            "- CI/CD pipeline config (GitHub Actions)\n"
        )

    config = _get_config()

    if _gateway_available(config):
        prompt = build_integration_guide_prompt(
            table_names=table_names,
            total_rows=total_rows,
            formats=formats,
            columns_summary=columns_summary,
            artifacts_context=artifacts_ctx,
        )
        try:
            raw = _send_guide_request(prompt, config)
            return parse_guide_response(raw, session_id, provider="gateway")
        except (GatewayError, Exception) as e:
            logger.warning(
                "AI guide generation failed, falling back to offline: %s",
                e,
                extra={"stage": "integration_guide", "event": "gateway_fallback"},
            )

    return _build_offline_guide(
        session_id=session_id,
        table_names=table_names,
        total_rows=total_rows,
        generation_order=generation_order,
        schema=schema,
        has_integration_bundle=has_integration_bundle,
    )


def _build_columns_summary(
    schema: SchemaMetadata, table_names: list[str]
) -> str:
    """Build a compact columns summary for prompt context."""
    lines: list[str] = []
    for t in schema.tables:
        if t.name not in table_names:
            continue
        cols = ", ".join(
            f"{c.name} ({c.data_type}{'  PK' if c.is_primary_key else ''}{'  NOT NULL' if not c.nullable else ''})"
            for c in t.columns
        )
        lines.append(f"  {t.name}: {cols}")
    return "\n".join(lines) or "  (no column details available)"


def _send_guide_request(prompt: str, config: AIProviderConfig) -> str:
    """Send the integration guide prompt to the gateway."""
    import time as _time

    import requests

    from app.ai.gateway_provider import GatewayError

    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(1, config.max_retries + 1):
        try:
            if config.api_format == "anthropic":
                payload = {
                    "model": config.model,
                    "system": INTEGRATION_GUIDE_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 8192,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/messages"):
                    url = f"{url}/messages"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
            else:
                payload = {
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": INTEGRATION_GUIDE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 8192,
                }
                url = config.gateway_url.rstrip("/")
                if not url.endswith("/chat/completions"):
                    url = f"{url}/chat/completions"
                resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = GatewayError(f"Guide gateway error (attempt {attempt}): {e}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500:
                last_error = GatewayError(f"Guide gateway {status} (attempt {attempt})")
            else:
                raise GatewayError(f"Guide gateway client error {status}: {e}") from e

        if attempt < config.max_retries:
            _time.sleep(2 ** (attempt - 1))

    raise last_error or GatewayError("Guide gateway call failed")


def _build_offline_guide(
    session_id: str,
    table_names: list[str],
    total_rows: int,
    generation_order: list[str],
    schema: SchemaMetadata,
    has_integration_bundle: bool,
) -> IntegrationGuide:
    """Build a deterministic integration guide without AI."""
    order_str = " → ".join(generation_order) if generation_order else ", ".join(table_names)
    tables_csv = ", ".join(table_names)

    sections: list[IntegrationGuideSection] = []

    # ── 1. CSV → PostgreSQL ──────────────────────────────────
    pg_steps: list[GuideStep] = [
        GuideStep(
            step_number=1,
            title="Create tables",
            description="Run the SQL DDL or use the generated SQL INSERT file which includes CREATE TABLE statements.",
            code_snippet=f"psql -h localhost -U postgres -d testdb -f sql_inserts.sql",
            language="bash",
        ),
        GuideStep(
            step_number=2,
            title="Import CSV files",
            description=f"Import each CSV file in dependency order: {order_str}",
            code_snippet="\n".join(
                f"\\copy {t} FROM '{t}.csv' WITH (FORMAT csv, HEADER true);"
                for t in table_names
            ),
            language="sql",
        ),
        GuideStep(
            step_number=3,
            title="Verify row counts",
            description="Confirm all rows were imported correctly.",
            code_snippet="\n".join(
                f"SELECT COUNT(*) AS {t}_count FROM {t};" for t in table_names
            ),
            language="sql",
        ),
    ]
    sections.append(IntegrationGuideSection(
        scenario="Import CSV into PostgreSQL",
        summary="Load generated CSV files into PostgreSQL using psql \\copy commands.",
        prerequisites=[
            "PostgreSQL 13+ installed",
            "psql CLI or pgAdmin available",
            f"Database 'testdb' created with tables: {tables_csv}",
        ],
        steps=pg_steps,
        tips=[
            f"Import tables in FK order: {order_str}",
            "Use BEGIN/COMMIT for transactional imports.",
            "Run ANALYZE after bulk imports for query planner accuracy.",
        ],
    ))

    # ── 2. CSV → MySQL ───────────────────────────────────────
    mysql_steps: list[GuideStep] = [
        GuideStep(
            step_number=1,
            title="Enable local file loading",
            description="MySQL requires explicit permission for LOAD DATA LOCAL.",
            code_snippet="SET GLOBAL local_infile = 1;\nmysql --local-infile=1 -u root -p testdb",
            language="bash",
        ),
        GuideStep(
            step_number=2,
            title="Load CSV files",
            description=f"Import each CSV in order: {order_str}",
            code_snippet="\n".join(
                f"LOAD DATA LOCAL INFILE '{t}.csv'\n"
                f"  INTO TABLE {t}\n"
                f"  FIELDS TERMINATED BY ','\n"
                f"  ENCLOSED BY '\"'\n"
                f"  LINES TERMINATED BY '\\n'\n"
                f"  IGNORE 1 ROWS;"
                for t in table_names
            ),
            language="sql",
        ),
    ]
    sections.append(IntegrationGuideSection(
        scenario="Import CSV into MySQL",
        summary="Load CSV files into MySQL using LOAD DATA LOCAL INFILE.",
        prerequisites=[
            "MySQL 8.0+ installed",
            "local_infile enabled",
            f"Database 'testdb' with tables: {tables_csv}",
        ],
        steps=mysql_steps,
        tips=[
            "Use --local-infile=1 when connecting via CLI.",
            "For MySQL Workbench, enable local infile in connection settings.",
        ],
    ))

    # ── 3. SQL INSERT Scripts ────────────────────────────────
    sql_steps: list[GuideStep] = [
        GuideStep(
            step_number=1,
            title="Download SQL inserts",
            description="The SQL INSERT file is transaction-wrapped and FK-ordered.",
            code_snippet=f"# Download from the Export section or Integration bundle\n"
                         f"# File: sql_inserts.sql ({total_rows} rows across {len(table_names)} tables)",
            language="bash",
        ),
        GuideStep(
            step_number=2,
            title="Execute against database",
            description="Run the script against PostgreSQL or MySQL.",
            code_snippet="# PostgreSQL\n"
                         "psql -h localhost -U postgres -d testdb -f sql_inserts.sql\n\n"
                         "# MySQL\n"
                         "mysql -u root -p testdb < sql_inserts.sql",
            language="bash",
        ),
    ]
    sections.append(IntegrationGuideSection(
        scenario="Execute SQL INSERT Scripts",
        summary="Run generated SQL INSERT statements directly against your database.",
        prerequisites=[
            "Target database server running",
            "Tables already created (or use included CREATE TABLE statements)",
        ],
        steps=sql_steps,
        tips=[
            "The script uses transactions — all rows are committed or none.",
            f"Tables are inserted in dependency order: {order_str}",
        ],
    ))

    # ── 4. API JSON Payloads ─────────────────────────────────
    first_table = table_names[0] if table_names else "entity"
    api_steps: list[GuideStep] = [
        GuideStep(
            step_number=1,
            title="Using curl",
            description=f"Send generated payloads to your API endpoint for {first_table}.",
            code_snippet=f'curl -X POST http://localhost:8080/api/{first_table} \\\n'
                         f'  -H "Content-Type: application/json" \\\n'
                         f'  -d @api_payloads/{first_table}.json',
            language="bash",
        ),
        GuideStep(
            step_number=2,
            title="Using Python requests",
            description="Load and send payloads programmatically.",
            code_snippet=f'import json\n'
                         f'import requests\n\n'
                         f'with open("api_payloads.json") as f:\n'
                         f'    payloads = json.load(f)\n\n'
                         f'for entity, items in payloads.items():\n'
                         f'    for payload in items:\n'
                         f'        resp = requests.post(\n'
                         f'            f"http://localhost:8080/api/{{entity}}",\n'
                         f'            json=payload,\n'
                         f'            timeout=10,\n'
                         f'        )\n'
                         f'        print(f"{{entity}}: {{resp.status_code}}")',
            language="python",
        ),
        GuideStep(
            step_number=3,
            title="Using JavaScript fetch",
            description="Send payloads from a Node.js or browser environment.",
            code_snippet=f'const payloads = require("./api_payloads.json");\n\n'
                         f'for (const [entity, items] of Object.entries(payloads)) {{\n'
                         f'  for (const payload of items) {{\n'
                         f'    const resp = await fetch(`http://localhost:8080/api/${{entity}}`, {{\n'
                         f'      method: "POST",\n'
                         f'      headers: {{ "Content-Type": "application/json" }},\n'
                         f'      body: JSON.stringify(payload),\n'
                         f'    }});\n'
                         f'    console.log(`${{entity}}: ${{resp.status}}`);\n'
                         f'  }}\n'
                         f'}}',
            language="javascript",
        ),
    ]
    sections.append(IntegrationGuideSection(
        scenario="Use API JSON Payloads",
        summary="Send generated JSON payloads to your REST API using curl, Python, or JavaScript.",
        prerequisites=[
            "Target API server running on http://localhost:8080",
            "API endpoints matching entity names",
        ],
        steps=api_steps,
        tips=[
            "API payloads have primary keys removed — let your API assign them.",
            "Use the mock payloads for negative testing (invalid/boundary values).",
        ],
    ))

    # ── 5. Postman Collection ────────────────────────────────
    if has_integration_bundle:
        postman_steps: list[GuideStep] = [
            GuideStep(
                step_number=1,
                title="Import collection",
                description="Import the Postman collection JSON into Postman.",
                code_snippet='1. Open Postman → Import → Upload Files\n'
                             '2. Select "postman_collection.json" from the ZIP\n'
                             '3. Click Import',
                language="bash",
            ),
            GuideStep(
                step_number=2,
                title="Configure environment",
                description="Set the base URL variable in Postman.",
                code_snippet='{\n'
                             '  "variable": [\n'
                             '    { "key": "baseUrl", "value": "http://localhost:8080" }\n'
                             '  ]\n'
                             '}',
                language="json",
            ),
            GuideStep(
                step_number=3,
                title="Run collection",
                description="Use the Collection Runner or Newman CLI to execute all requests.",
                code_snippet="# CLI with Newman\n"
                             "npm install -g newman\n"
                             "newman run postman_collection.json --env-var baseUrl=http://localhost:8080",
                language="bash",
            ),
        ]
        sections.append(IntegrationGuideSection(
            scenario="Use Postman Collection for API Testing",
            summary="Import the generated Postman collection and run automated API tests.",
            prerequisites=[
                "Postman desktop app or Newman CLI installed",
                "Target API server running",
            ],
            steps=postman_steps,
            tips=[
                "Use Newman for CI/CD integration: newman run collection.json --reporters cli,junit",
                "The collection includes CRUD operations for all entities.",
            ],
        ))

    # ── 6. Python pytest Fixtures ────────────────────────────
    pytest_steps: list[GuideStep] = [
        GuideStep(
            step_number=1,
            title="Create a test fixture",
            description="Load generated JSON data as pytest fixtures.",
            code_snippet=f'import json\nimport pytest\n\n\n'
                         f'@pytest.fixture\n'
                         f'def test_data():\n'
                         f'    """Load generated synthetic test data."""\n'
                         f'    with open("generated_data.json") as f:\n'
                         f'        return json.load(f)\n\n\n'
                         f'@pytest.fixture\n'
                         f'def {first_table}_records(test_data):\n'
                         f'    """Get {first_table} records."""\n'
                         f'    return test_data["{first_table}"]',
            language="python",
        ),
        GuideStep(
            step_number=2,
            title="Write test cases",
            description="Use the fixtures in your test functions.",
            code_snippet=f'def test_{first_table}_has_records({first_table}_records):\n'
                         f'    assert len({first_table}_records) > 0\n\n\n'
                         f'def test_{first_table}_has_required_fields({first_table}_records):\n'
                         f'    for record in {first_table}_records:\n'
                         f'        assert "id" in record\n',
            language="python",
        ),
    ]
    sections.append(IntegrationGuideSection(
        scenario="Load Data into Python Test Suite",
        summary="Use generated JSON data as pytest fixtures for automated testing.",
        prerequisites=[
            "Python 3.9+",
            "pytest installed (pip install pytest)",
            "Generated JSON data file downloaded",
        ],
        steps=pytest_steps,
        tips=[
            "Use @pytest.fixture(scope='session') to load data once for all tests.",
            "Combine with mock payloads for negative test scenarios.",
        ],
    ))

    overview = (
        f"This dataset contains {total_rows} rows across {len(table_names)} tables "
        f"({tables_csv}). The data preserves referential integrity and follows the "
        f"generation order: {order_str}. Use the guides below to integrate this data "
        f"into your test environment."
    )

    return IntegrationGuide(
        session_id=session_id,
        overview=overview,
        sections=sections,
        provider="offline",
    )
