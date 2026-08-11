"""Unified pipeline router — the primary API surface.

Endpoints:
  POST /upload      — accept SQL / OpenAPI / BDD files, create session
  POST /parse       — parse uploaded files, extract metadata
  POST /generate    — generate synthetic data + validate + export
  GET  /download/csv   — download CSV ZIP
  GET  /download/json  — download JSON ZIP
  GET  /download/sql   — download SQL INSERT ZIP
  GET  /summary        — full session summary
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.converters.bdd_to_schema import bdd_to_schema
from app.converters.openapi_to_schema import openapi_to_schema
from app.exporters.engine import ExportEngine, ExportError
from app.generators.negative_generator import NegativeCaseGenerator
from app.generators.synthetic_generator import SyntheticDataGenerator, GeneratorError
from app.models.export import ExportFormat
from app.models.negative import NegativeToggles
from app.models.pipeline import (
    DownloadLink,
    GenerateResponse,
    GenerateTableInfo,
    ParsedTableInfo,
    ParseResponse,
    SummaryResponse,
    UploadedFileInfo,
    UploadResponse,
)
from app.models.schema import SchemaMetadata, TableMetadata
from app.parsers.bdd_parser import parse_bdd_feature
from app.parsers.csv_parser import CSVParserError, parse_csv_schema
from app.parsers.format_dispatcher import FormatDetectionError, classify_format
from app.parsers.jsonschema_parser import JSONSchemaParserError, parse_jsonschema
from app.parsers.openapi_parser import OpenAPIParserError, parse_openapi_spec
from app.parsers.sql_parser import SQLParserError, parse_sql_schema
from app.parsers.xlsx_parser import XLSXParserError, parse_xlsx_schema
from app.parsers.xml_parser import XMLParserError, parse_xml_schema
from app.services.relationship_engine import CircularDependencyError, RelationshipGraph
from app.services.history_store import HistoryRecord, history_store
from app.services.session_store import store
from app.validators.engine import ValidationEngine

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger(__name__)

# ── File classification ───────────────────────────────────────

_SQL_EXTS = (".sql",)
_OPENAPI_EXTS = (".yaml", ".yml", ".json")
_BDD_EXTS = (".feature", ".txt")
_CSV_EXTS = (".csv",)
_XLSX_EXTS = (".xlsx",)
_XML_EXTS = (".xml",)

_ALL_EXTS = _SQL_EXTS + _OPENAPI_EXTS + _BDD_EXTS + _CSV_EXTS + _XLSX_EXTS + _XML_EXTS
_ACCEPTED_LIST = ", ".join(_ALL_EXTS)


def _classify_file(filename: str) -> str | None:
    """Return the file category or ``None``."""
    lower = filename.lower()
    if lower.endswith(_SQL_EXTS):
        return "sql"
    if lower.endswith(_OPENAPI_EXTS):
        return "openapi"
    if lower.endswith(_BDD_EXTS):
        return "bdd"
    if lower.endswith(_CSV_EXTS):
        return "csv"
    if lower.endswith(_XLSX_EXTS):
        return "xlsx"
    if lower.endswith(_XML_EXTS):
        return "xml"
    return None


def _get_session(session_id: str):
    """Retrieve a session by ID, raising 404 if not found."""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


def _build_table_info(table: TableMetadata) -> ParsedTableInfo:
    """Build a ``ParsedTableInfo`` summary from a ``TableMetadata``."""
    return ParsedTableInfo(
        name=table.name,
        column_count=len(table.columns),
        primary_keys=table.primary_keys,
        foreign_keys=len(table.foreign_keys),
        has_check_constraints=(
            len(table.check_constraints) > 0
            or any(c.check_constraint for c in table.columns)
        ),
    )


# ── POST /upload ──────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_files(files: list[UploadFile] = File(..., description="SQL, OpenAPI, BDD, CSV, XLSX, or XML files")):
    """Accept one or more files and create a session.

    Upload your schema files here. Supported types:
    - **SQL**: `.sql` files with CREATE TABLE statements
    - **OpenAPI**: `.yaml`, `.yml`, or `.json` Swagger/OpenAPI specs
    - **BDD**: `.feature` or `.txt` Gherkin files
    - **CSV**: `.csv` tabular data with headers
    - **XLSX**: `.xlsx` Excel workbooks
    - **XML**: `.xml` structured data
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    session = store.create()
    logger.info(
        "Upload started — session %s",
        session.session_id,
        extra={"stage": "upload", "session_id": session.session_id, "event": "upload_started"},
    )
    accepted: list[UploadedFileInfo] = []

    for f in files:
        if not f.filename:
            continue
        ftype = _classify_file(f.filename)
        if ftype is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {f.filename}. Accepted: {_ACCEPTED_LIST}",
            )

        content = await f.read()

        # XLSX is binary — skip UTF-8 decode
        if ftype == "xlsx":
            session.raw_xlsx = content
            session.raw_xlsx_files.append(content)
        else:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400, detail=f"File '{f.filename}' is not valid UTF-8"
                )

            if ftype == "sql":
                session.raw_sql = text
                session.raw_sql_files.append(text)
            elif ftype == "openapi":
                session.raw_openapi = text
                session.raw_openapi_is_json = f.filename.lower().endswith(".json")
                session.raw_openapi_files.append((text, f.filename.lower().endswith(".json")))
            elif ftype == "bdd":
                session.raw_bdd = text
                session.raw_bdd_files.append(text)
            elif ftype == "csv":
                session.raw_csv = text
                session.raw_csv_files.append(text)
            elif ftype == "xml":
                session.raw_xml = text
                session.raw_xml_files.append(text)

        info = UploadedFileInfo(
            filename=f.filename,
            file_type=ftype,
            size_bytes=len(content),
        )
        accepted.append(info)
        logger.info(
            "File accepted: %s (%s, %d bytes)",
            f.filename,
            ftype,
            len(content),
            extra={
                "stage": "upload",
                "session_id": session.session_id,
                "event": "file_accepted",
                "file_name": f.filename,
                "file_type": ftype,
            },
        )

    if not accepted:
        store.delete(session.session_id)
        raise HTTPException(status_code=400, detail="No valid files provided")

    session.uploaded_files = accepted

    logger.info(
        "Upload complete — %d files accepted",
        len(accepted),
        extra={
            "stage": "upload",
            "session_id": session.session_id,
            "event": "upload_completed",
        },
    )

    return UploadResponse(
        session_id=session.session_id,
        files=accepted,
    )


# ── POST /parse ───────────────────────────────────────────────


@router.post("/parse", response_model=ParseResponse)
async def parse_uploaded(
    session_id: str = Query(..., description="Session ID from /upload"),
    merge_schemas: bool = Query(default=True, description="Merge tables from all uploaded files into one unified schema"),
):
    """Parse all uploaded files in the session.

    When ``merge_schemas=True`` (default), tables from ALL uploaded files are
    combined into a single unified schema. When ``False``, the legacy priority
    behaviour is used (SQL > OpenAPI > CSV > XLSX > XML > BDD).
    """
    session = _get_session(session_id)

    if not any([session.raw_sql, session.raw_openapi, session.raw_bdd,
                session.raw_csv, session.raw_xlsx, session.raw_xml]):
        raise HTTPException(status_code=400, detail="No files uploaded in this session")

    logger.info(
        "Parse started — session %s (merge=%s)",
        session_id,
        merge_schemas,
        extra={"stage": "parsing", "session_id": session_id, "event": "parse_started"},
    )
    parse_start = time.perf_counter()

    tables_info: list[ParsedTableInfo] = []
    generation_order: list[str] = []
    openapi_count = 0
    bdd_count = 0
    all_tables: list[TableMetadata] = []

    # ── Helper: deduplicate table names when merging ──────────
    def _unique_table_name(name: str, existing: set[str]) -> str:
        if name not in existing:
            return name
        i = 2
        while f"{name}_{i}" in existing:
            i += 1
        return f"{name}_{i}"

    existing_names: set[str] = set()

    # ── Parse SQL files ───────────────────────────────────────
    sql_sources = session.raw_sql_files if merge_schemas else ([session.raw_sql] if session.raw_sql else [])
    for sql_text in sql_sources:
        try:
            schema = parse_sql_schema(sql_text)
        except SQLParserError as e:
            logger.error("SQL parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "sql_parse_error", "error_type": "SQLParserError"})
            raise HTTPException(status_code=422, detail=f"SQL parse error: {e}")
        for t in schema.tables:
            t.name = _unique_table_name(t.name, existing_names)
            existing_names.add(t.name)
            all_tables.append(t)
        logger.info("SQL parsed — %d tables", len(schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "sql_parsed"})

    # ── Parse OpenAPI / JSON Schema files ─────────────────────
    openapi_sources = session.raw_openapi_files if merge_schemas else ([(session.raw_openapi, session.raw_openapi_is_json)] if session.raw_openapi else [])
    for openapi_text, is_json in openapi_sources:
        detected_format = "openapi"
        if is_json:
            detected_format = classify_format("test.json", openapi_text)

        if detected_format == "jsonschema":
            try:
                js_schema = parse_jsonschema(openapi_text, table_name="json_schema_import")
            except JSONSchemaParserError as e:
                logger.error("JSON Schema parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "jsonschema_parse_error", "error_type": "JSONSchemaParserError"})
                raise HTTPException(status_code=422, detail=f"JSON Schema parse error: {e}")
            for t in js_schema.tables:
                t.name = _unique_table_name(t.name, existing_names)
                existing_names.add(t.name)
                all_tables.append(t)
            logger.info("JSON Schema parsed — %d tables", len(js_schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "jsonschema_parsed"})
        else:
            try:
                openapi_meta = parse_openapi_spec(openapi_text, is_json=is_json)
            except OpenAPIParserError as e:
                logger.error("OpenAPI parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "openapi_parse_error", "error_type": "OpenAPIParserError"})
                raise HTTPException(status_code=422, detail=f"OpenAPI parse error: {e}")
            session.openapi = openapi_meta
            openapi_count += len(openapi_meta.schemas)
            # Convert OpenAPI schemas to tables
            oa_schema = openapi_to_schema(openapi_meta)
            for t in oa_schema.tables:
                t.name = _unique_table_name(t.name, existing_names)
                existing_names.add(t.name)
                all_tables.append(t)
            logger.info("OpenAPI parsed — %d schemas → %d tables", len(openapi_meta.schemas), len(oa_schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "openapi_parsed"})

    # ── Parse CSV files ───────────────────────────────────────
    csv_sources = session.raw_csv_files if merge_schemas else ([session.raw_csv] if session.raw_csv and not all_tables else [])
    for idx, csv_text in enumerate(csv_sources):
        tname = f"csv_import_{idx + 1}" if len(csv_sources) > 1 else "csv_import"
        try:
            csv_schema = parse_csv_schema(csv_text, table_name=tname)
        except CSVParserError as e:
            logger.error("CSV parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "csv_parse_error"})
            raise HTTPException(status_code=422, detail=f"CSV parse error: {e}")
        for t in csv_schema.tables:
            t.name = _unique_table_name(t.name, existing_names)
            existing_names.add(t.name)
            all_tables.append(t)
        logger.info("CSV parsed — %d tables", len(csv_schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "csv_parsed"})

    # ── Parse XLSX files ──────────────────────────────────────
    xlsx_sources = session.raw_xlsx_files if merge_schemas else ([session.raw_xlsx] if session.raw_xlsx and not all_tables else [])
    for idx, xlsx_bytes in enumerate(xlsx_sources):
        tname = f"xlsx_import_{idx + 1}" if len(xlsx_sources) > 1 else "xlsx_import"
        try:
            xlsx_schema = parse_xlsx_schema(xlsx_bytes, default_table_name=tname)
        except XLSXParserError as e:
            logger.error("XLSX parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "xlsx_parse_error"})
            raise HTTPException(status_code=422, detail=f"XLSX parse error: {e}")
        for t in xlsx_schema.tables:
            t.name = _unique_table_name(t.name, existing_names)
            existing_names.add(t.name)
            all_tables.append(t)
        logger.info("XLSX parsed — %d tables", len(xlsx_schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "xlsx_parsed"})

    # ── Parse XML files ───────────────────────────────────────
    xml_sources = session.raw_xml_files if merge_schemas else ([session.raw_xml] if session.raw_xml and not all_tables else [])
    for idx, xml_text in enumerate(xml_sources):
        tname = f"xml_import_{idx + 1}" if len(xml_sources) > 1 else "xml_import"
        try:
            xml_schema = parse_xml_schema(xml_text, default_table_name=tname)
        except XMLParserError as e:
            logger.error("XML parse failed: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "xml_parse_error"})
            raise HTTPException(status_code=422, detail=f"XML parse error: {e}")
        for t in xml_schema.tables:
            t.name = _unique_table_name(t.name, existing_names)
            existing_names.add(t.name)
            all_tables.append(t)
        logger.info("XML parsed — %d tables", len(xml_schema.tables), extra={"stage": "parsing", "session_id": session_id, "event": "xml_parsed"})

    # ── Parse BDD files ───────────────────────────────────────
    bdd_sources = session.raw_bdd_files if merge_schemas else ([session.raw_bdd] if session.raw_bdd else [])
    for bdd_text in bdd_sources:
        bdd = parse_bdd_feature(bdd_text)
        session.bdd = bdd
        bdd_count += len(bdd.scenarios)
        logger.info("BDD parsed — %d scenarios", len(bdd.scenarios), extra={"stage": "parsing", "session_id": session_id, "event": "bdd_parsed"})
        # If merge mode and we have no other tables, convert BDD to schema tables
        if merge_schemas:
            bdd_schema = bdd_to_schema(bdd)
            for t in bdd_schema.tables:
                t.name = _unique_table_name(t.name, existing_names)
                existing_names.add(t.name)
                all_tables.append(t)

    # ── Fallback: BDD-derived tables in non-merge mode ────────
    if not merge_schemas and not all_tables:
        if session.bdd and session.bdd.scenarios:
            bdd_schema = bdd_to_schema(session.bdd)
            for t in bdd_schema.tables:
                all_tables.append(t)
                existing_names.add(t.name)

    # ── Build unified schema ──────────────────────────────────
    if all_tables:
        unified = SchemaMetadata(tables=all_tables)
        session.schema = unified
        graph = RelationshipGraph(unified)
        try:
            generation_order = graph.get_generation_order()
        except CircularDependencyError as e:
            logger.error("Circular dependency detected: %s", e, extra={"stage": "parsing", "session_id": session_id, "event": "circular_dependency", "error_type": "CircularDependencyError"})
            raise HTTPException(status_code=422, detail=str(e))
        session.generation_order = generation_order
        for t in all_tables:
            tables_info.append(_build_table_info(t))

    parse_duration = round((time.perf_counter() - parse_start) * 1000, 1)
    logger.info(
        "Parse complete — %d tables, %d openapi schemas, %d bdd scenarios (%.1fms)",
        len(tables_info),
        openapi_count,
        bdd_count,
        parse_duration,
        extra={
            "stage": "parsing",
            "session_id": session_id,
            "event": "parse_completed",
            "duration_ms": parse_duration,
        },
    )

    return ParseResponse(
        session_id=session.session_id,
        tables=tables_info,
        generation_order=generation_order,
        openapi_schemas=openapi_count,
        bdd_scenarios=bdd_count,
    )


# ── POST /generate ────────────────────────────────────────────


@router.post("/generate", response_model=GenerateResponse)
async def generate_data(
    session_id: str = Query(..., description="Session ID from /upload"),
    row_count: int = Query(default=10, ge=1, le=1000000),
    include_valid: bool = Query(default=True, description="Generate valid rows"),
    include_invalid: bool = Query(default=False, description="Generate invalid / negative cases"),
    include_boundary: bool = Query(default=False, description="Generate boundary-value cases"),
    include_duplicates: bool = Query(default=False, description="Generate duplicate-value cases"),
    country: str = Query(default="us", description="Country for locale-aware generation"),
    domain: str = Query(default="unknown", description="Business domain (banking, insurance, healthcare, retail)"),
    authorization: str | None = Header(default=None),
):
    """Generate synthetic data, validate, and prepare exports."""
    session = _get_session(session_id)

    if not session.schema:
        raise HTTPException(
            status_code=400,
            detail="No schema available. Upload SQL, OpenAPI, or BDD files and call POST /parse first.",
        )

    logger.info(
        "Generation started — session %s, rows=%d, valid=%s, invalid=%s, boundary=%s, duplicates=%s",
        session_id,
        row_count,
        include_valid,
        include_invalid,
        include_boundary,
        include_duplicates,
        extra={
            "stage": "generation",
            "session_id": session_id,
            "event": "generation_started",
            "row_count": row_count,
        },
    )
    gen_start = time.perf_counter()

    # Business context inference — auto-detect domain if not specified
    if domain == "unknown" and session.schema:
        try:
            from app.generators.business_context_engine import analyze_schema_context, infer_schema_domain
            business_ctx = analyze_schema_context(session.schema)
            session.business_context = business_ctx
            inferred = business_ctx.get("primary_domain", "unknown")
            if inferred and inferred != "general":
                domain = inferred
                logger.info(
                    "Business context inferred domain: %s (confidence %.2f)",
                    domain,
                    business_ctx.get("domain_confidence", 0),
                    extra={"stage": "generation", "session_id": session_id, "event": "domain_inferred"},
                )
        except Exception as e:
            logger.warning(
                "Business context inference skipped: %s",
                e,
                extra={"stage": "generation", "session_id": session_id, "event": "context_inference_skipped"},
            )

    # AI column inference — enriches the generator with realistic value hints
    ai_hints = None
    if include_valid:
        try:
            from app.ai.column_inference import infer_column_hints
            ai_hints = infer_column_hints(session.schema, domain=domain)
            if ai_hints:
                logger.info(
                    "AI column inference complete — hints for %d tables",
                    len(ai_hints),
                    extra={"stage": "generation", "session_id": session_id, "event": "ai_hints_ready"},
                )
        except Exception as e:
            logger.warning(
                "AI column inference skipped: %s",
                e,
                extra={"stage": "generation", "session_id": session_id, "event": "ai_hints_skipped"},
            )

    # Generate valid data
    data: dict[str, list[dict]] = {}
    if include_valid:
        try:
            gen = SyntheticDataGenerator(session.schema, row_count=row_count, country=country, domain=domain, ai_hints=ai_hints)
            data = gen.generate()
        except (CircularDependencyError, GeneratorError) as e:
            logger.error(
                "Generation failed: %s",
                e,
                extra={"stage": "generation", "session_id": session_id, "event": "generation_error", "error_type": type(e).__name__},
            )
            raise HTTPException(status_code=422, detail=str(e))
        logger.info(
            "Valid data generated — %d tables, %d total rows",
            len(data),
            sum(len(r) for r in data.values()),
            extra={"stage": "generation", "session_id": session_id, "event": "valid_data_generated"},
        )

    session.row_count = row_count

    # Generate negative / edge cases
    negative_dataset = None
    if include_invalid or include_boundary or include_duplicates:
        toggles = NegativeToggles(
            invalid_emails=include_invalid,
            null_required_fields=include_invalid,
            broken_foreign_keys=include_invalid,
            invalid_enums=include_invalid,
            invalid_regex_patterns=include_invalid,
            boundary_values=include_boundary,
            duplicate_values=include_duplicates,
        )
        try:
            neg_gen = NegativeCaseGenerator(session.schema, row_count=row_count, toggles=toggles)
            negative_dataset = neg_gen.generate()
        except Exception as e:
            logger.error(
                "Negative generation failed: %s",
                e,
                exc_info=True,
                extra={"stage": "generation", "session_id": session_id, "event": "negative_generation_error", "error_type": type(e).__name__},
            )
            raise HTTPException(status_code=422, detail=f"Negative generation error: {e}")
        session.negative = negative_dataset
        logger.info(
            "Negative cases generated — %d invalid rows",
            len(negative_dataset.invalid),
            extra={"stage": "generation", "session_id": session_id, "event": "negative_data_generated"},
        )

    # Validate valid data only (before merging negative rows)
    engine = ValidationEngine(session.schema)
    report = engine.validate(data)
    session.validation = report
    logger.info(
        "Validation complete — %d passed, %d failed",
        report.passed,
        report.failed,
        extra={"stage": "validation", "session_id": session_id, "event": "validation_completed"},
    )

    # Coherence validation — detect semantic contradictions
    from app.validators.coherence_validator import validate_coherence

    coherence_report = validate_coherence(data)
    session.coherence = coherence_report.to_dict()
    logger.info(
        "Coherence validation complete — %d issues, score %.2f",
        coherence_report.total_issues,
        coherence_report.overall_coherence_score,
        extra={"stage": "validation", "session_id": session_id, "event": "coherence_validated"},
    )

    # Merge negative rows into data so they appear in preview/export/download
    if negative_dataset:
        for neg_row in negative_dataset.invalid:
            data.setdefault(neg_row.table, []).append(neg_row.row)

    session.data = data

    # Exports are now lazy — generated on first download request
    # Clear any stale exports from a previous generation
    session.exports.clear()

    session.generated_at = datetime.utcnow()
    session.ai_enhanced = ai_hints is not None

    table_infos = [
        GenerateTableInfo(table_name=name, row_count=len(rows))
        for name, rows in data.items()
    ]
    total = sum(len(rows) for rows in data.values())
    negative_count = len(negative_dataset.invalid) if negative_dataset else 0

    gen_duration = round((time.perf_counter() - gen_start) * 1000, 1)
    logger.info(
        "Generation pipeline complete — %d total rows, %d negative cases (%.1fms)",
        total,
        negative_count,
        gen_duration,
        extra={
            "stage": "generation",
            "session_id": session_id,
            "event": "generation_completed",
            "row_count": total,
            "duration_ms": gen_duration,
        },
    )

    # ── Save to per-user history ──────────────────────────────
    try:
        from app.auth.jwt_handler import decode_access_token
        _user_email = "anonymous@local"
        if authorization and authorization.startswith("Bearer "):
            _claims = decode_access_token(authorization[7:])
            if _claims:
                _user_email = (_claims.get("email") or _claims.get("sub") or "anonymous@local").lower().strip()

        _hist_record = HistoryRecord(
            id=session.session_id,
            email=_user_email,
            created_at=session.generated_at.isoformat() if session.generated_at else datetime.utcnow().isoformat(),
            source_files=[{"filename": f.filename, "file_type": f.file_type, "size_bytes": f.size_bytes} for f in session.uploaded_files],
            tables=[{"table_name": t.table_name, "row_count": t.row_count} for t in table_infos],
            row_count=row_count,
            total_rows=total,
            negative_cases=negative_count,
            generation_order=session.generation_order,
            data=data,
            validation_passed=report.passed,
            validation_failed=report.failed,
            schema=session.schema.model_dump() if session.schema else None,
            negative_data=session.negative.model_dump() if session.negative else None,
        )
        history_store.save(_hist_record)
    except Exception as exc:
        logger.warning("Failed to save history: %s", exc)

    return GenerateResponse(
        session_id=session.session_id,
        row_count=row_count,
        tables=table_infos,
        total_rows=total,
        negative_cases=negative_count,
        validation=report,
        ai_enhanced=ai_hints is not None,
    )


# ── GET /download/* ───────────────────────────────────────────


def _download(session_id: str, fmt: str) -> FileResponse:
    session = _get_session(session_id)
    export_result = session.exports.get(fmt)
    if not export_result:
        # Lazy export: generate on first download request
        if not session.data:
            raise HTTPException(
                status_code=400,
                detail=f"No data available. Call POST /generate first.",
            )
        exporter = ExportEngine()
        export_result = exporter.export(session.data, ExportFormat(fmt), session.schema)
        session.exports[fmt] = export_result
    if not os.path.exists(export_result.zip_path):
        # Re-generate if file was cleaned up
        if not session.data:
            raise HTTPException(status_code=410, detail="Export file no longer available")
        exporter = ExportEngine()
        export_result = exporter.export(session.data, ExportFormat(fmt), session.schema)
        session.exports[fmt] = export_result

    logger.info(
        "Download served — %s format, session %s",
        fmt,
        session_id,
        extra={"stage": "export", "session_id": session_id, "event": "download_served"},
    )
    return FileResponse(
        path=export_result.zip_path,
        media_type="application/zip",
        filename=os.path.basename(export_result.zip_path),
    )


@router.get("/download/csv")
async def download_csv(
    session_id: str = Query(..., description="Session ID"),
):
    """Download generated data as CSV ZIP."""
    return _download(session_id, "csv")


@router.get("/download/json")
async def download_json(
    session_id: str = Query(..., description="Session ID"),
):
    """Download generated data as JSON ZIP."""
    return _download(session_id, "json")


@router.get("/download/sql")
async def download_sql(
    session_id: str = Query(..., description="Session ID"),
):
    """Download generated data as SQL INSERT ZIP."""
    return _download(session_id, "sql")


# ── GET /summary ──────────────────────────────────────────────


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    session_id: str = Query(..., description="Session ID"),
):
    """Return full session summary — files, schema, validation, download links."""
    session = _get_session(session_id)

    downloads: list[DownloadLink] = []
    if session.data:
        # Exports are lazy — always show links when data exists
        for fmt_key in ("csv", "json", "sql"):
            downloads.append(
                DownloadLink(
                    format=fmt_key,
                    url=f"/download/{fmt_key}?session_id={session.session_id}",
                )
            )

    negative_count = len(session.negative.invalid) if session.negative else 0

    return SummaryResponse(
        session_id=session.session_id,
        uploaded_files=session.uploaded_files,
        tables_parsed=len(session.schema.tables) if session.schema else 0,
        generation_order=session.generation_order,
        row_count=session.row_count,
        total_rows=sum(len(rows) for rows in session.data.values())
        if session.data
        else 0,
        negative_cases=negative_count,
        validation=session.validation,
        coherence=session.coherence,
        business_context=session.business_context,
        exports=downloads,
        generated_at=session.generated_at,
        ai_enhanced=session.ai_enhanced,
    )


# ── GET /preview/{table} ──────────────────────────────────────


@router.get("/preview/{table_name}")
async def preview_table(
    table_name: str,
    session_id: str = Query(..., description="Session ID"),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Return a paginated preview of generated rows for a specific table."""
    session = _get_session(session_id)
    if not session.data:
        raise HTTPException(status_code=400, detail="No generated data")
    rows = session.data.get(table_name)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    preview_rows = rows[offset:offset + limit]
    columns = list(preview_rows[0].keys()) if preview_rows else (list(rows[0].keys()) if rows else [])
    return {
        "table_name": table_name,
        "total_rows": len(rows),
        "preview_count": len(preview_rows),
        "offset": offset,
        "limit": limit,
        "columns": columns,
        "rows": preview_rows,
    }
