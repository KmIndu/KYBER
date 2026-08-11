"""Natural-language dataset generation router.

Endpoints:
  POST /nl/infer-schema  — infer schema from a prompt (returns metadata only)
  POST /nl/generate      — infer schema + generate data + validate + export
  POST /nl/generate-with-ref — same as generate but with an optional reference document
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.ai.service import infer_schema_from_prompt
from app.exporters.engine import ExportEngine, ExportError
from app.generators.negative_generator import NegativeCaseGenerator
from app.generators.synthetic_generator import GeneratorError, SyntheticDataGenerator
from app.models.export import ExportFormat
from app.models.negative import NegativeToggles
from app.models.nl import (
    NLGenerateResponse,
    NLGenerateTableInfo,
    NLRequest,
    NLSchemaResult,
)
from app.models.pipeline import DownloadLink, UploadedFileInfo
from app.services.relationship_engine import CircularDependencyError
from app.services.session_store import store
from app.validators.engine import ValidationEngine

router = APIRouter(prefix="/nl", tags=["Natural Language"])
logger = logging.getLogger(__name__)


# ── POST /nl/infer-schema ─────────────────────────────────────


@router.post("/infer-schema", response_model=NLSchemaResult)
async def infer_schema(body: NLRequest):
    """Infer a database schema from a natural-language description.

    Returns the inferred domain, entities, relationships, constraints,
    generation order, and equivalent SQL DDL — without generating data.
    """
    logger.info(
        "NL schema inference — prompt: %.80s...",
        body.prompt,
        extra={"stage": "nl_inference", "event": "infer_started"},
    )
    start = time.perf_counter()

    try:
        result = infer_schema_from_prompt(body.prompt)
    except Exception as e:
        logger.error(
            "NL schema inference failed: %s",
            e,
            extra={"stage": "nl_inference", "event": "infer_error", "error_type": type(e).__name__},
        )
        raise HTTPException(status_code=422, detail=f"Schema inference failed: {e}")

    if not result.schema.tables:
        raise HTTPException(status_code=422, detail="Could not infer any entities from the prompt")

    duration = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "NL schema inferred — domain=%s, %d tables (%.1fms)",
        result.domain,
        len(result.schema.tables),
        duration,
        extra={"stage": "nl_inference", "event": "infer_completed", "duration_ms": duration},
    )

    return result


# ── POST /nl/generate ─────────────────────────────────────────


@router.post("/generate", response_model=NLGenerateResponse)
async def generate_from_prompt(body: NLRequest):
    """Infer schema from prompt, generate synthetic data, validate, and export.

    This is a one-shot endpoint: prompt in → data out with download links.
    """
    logger.info(
        "NL generate — prompt: %.80s..., rows=%d",
        body.prompt,
        body.row_count,
        extra={"stage": "nl_generate", "event": "generate_started"},
    )
    gen_start = time.perf_counter()

    # 1. Infer schema
    try:
        nl_result = infer_schema_from_prompt(body.prompt)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Schema inference failed: {e}")

    if not nl_result.schema.tables:
        raise HTTPException(status_code=422, detail="Could not infer any entities from the prompt")

    schema = nl_result.schema

    # 2. Create session
    session = store.create()
    session.schema = schema
    session.generation_order = nl_result.generation_order
    session.row_count = body.row_count
    session.uploaded_files = [
        UploadedFileInfo(filename="(natural language prompt)", file_type="nl", size_bytes=len(body.prompt)),
    ]

    # 3. Generate valid data
    data: dict[str, list[dict]] = {}
    try:
        gen = SyntheticDataGenerator(schema, row_count=body.row_count)
        data = gen.generate()
    except (CircularDependencyError, GeneratorError) as e:
        logger.error(
            "NL generation failed: %s",
            e,
            extra={"stage": "nl_generate", "session_id": session.session_id, "event": "generation_error"},
        )
        raise HTTPException(status_code=422, detail=str(e))

    # 4. Generate negative cases if requested
    negative_count = 0
    if body.include_invalid:
        toggles = NegativeToggles(
            invalid_emails=True,
            null_required_fields=True,
            broken_foreign_keys=True,
            invalid_enums=True,
            invalid_regex_patterns=True,
            boundary_values=True,
            duplicate_values=True,
        )
        try:
            neg_gen = NegativeCaseGenerator(schema, toggles=toggles)
            negative_dataset = neg_gen.generate()
            session.negative = negative_dataset
            negative_count = len(negative_dataset.invalid)
            for neg_row in negative_dataset.invalid:
                data.setdefault(neg_row.table, []).append(neg_row.row)
        except Exception as e:
            logger.warning("NL negative generation failed: %s", e)

    # 5. Validate
    engine = ValidationEngine(schema)
    report = engine.validate(data)
    session.validation = report
    session.data = data

    # 6. Export
    try:
        exporter = ExportEngine()
        for fmt in ExportFormat:
            result = exporter.export(data, fmt, schema)
            session.exports[fmt.value] = result
    except ExportError as e:
        logger.error("NL export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    session.generated_at = datetime.utcnow()

    table_infos = [
        NLGenerateTableInfo(table_name=name, row_count=len(rows))
        for name, rows in data.items()
    ]
    total = sum(len(rows) for rows in data.values())

    duration = round((time.perf_counter() - gen_start) * 1000, 1)
    logger.info(
        "NL generate complete — domain=%s, %d tables, %d rows, %d negative (%.1fms)",
        nl_result.domain,
        len(data),
        total,
        negative_count,
        duration,
        extra={
            "stage": "nl_generate",
            "session_id": session.session_id,
            "event": "generate_completed",
            "duration_ms": duration,
        },
    )

    return NLGenerateResponse(
        session_id=session.session_id,
        prompt=body.prompt,
        domain=nl_result.domain,
        tables=table_infos,
        total_rows=total,
        negative_cases=negative_count,
        validation=report,
        generation_order=nl_result.generation_order,
        generated_sql=nl_result.generated_sql,
    )


# ── POST /nl/generate-with-ref ────────────────────────────────


@router.post("/generate-with-ref", response_model=NLGenerateResponse)
async def generate_from_prompt_with_reference(
    prompt: str = Form(..., min_length=5, max_length=2000),
    row_count: int = Form(default=100, ge=1, le=1000000),
    include_invalid: bool = Form(default=False),
    file: UploadFile = File(...),
    doc_type: str = Form(default=None),
):
    """Generate synthetic data from a NL prompt enriched with a reference document.

    The reference document (screenshot, ERD, BRD, etc.) is processed via OCR
    to extract additional schema context, which is merged with the prompt-inferred schema.
    """
    from app.parsers.ocr_pipeline import extract_text_from_image
    from app.parsers.reference_extractor import extract_entities_from_ocr, _build_schema

    logger.info(
        "NL generate-with-ref — prompt: %.80s..., file=%s, rows=%d",
        prompt,
        file.filename,
        row_count,
        extra={"stage": "nl_generate_ref", "event": "generate_started"},
    )
    gen_start = time.perf_counter()

    # 1. Infer schema from prompt
    try:
        nl_result = infer_schema_from_prompt(prompt)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Schema inference failed: {e}")

    # 2. Process reference document (OCR + extraction)
    ref_entities = []
    content = b""
    try:
        content = await file.read()
        ct = (file.content_type or "").lower()
        is_image = ct.startswith("image/") or (file.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")
        )

        if is_image:
            ocr_result = extract_text_from_image(content)
            from app.models.reference import ReferenceDocType
            classified = ReferenceDocType.SCREENSHOT
            if doc_type:
                try:
                    classified = ReferenceDocType(doc_type)
                except ValueError:
                    pass
            ingestion = extract_entities_from_ocr(ocr_result, classified, file.filename or "reference")
            ref_entities = ingestion.entities if ingestion.entities else []
        else:
            # Text-based docs: decode and treat as additional prompt context
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                text_content = content.decode("latin-1")
            # Re-infer with combined prompt + document content
            combined_prompt = f"{prompt}\n\nAdditional context from uploaded document:\n{text_content[:4000]}"
            try:
                nl_result = infer_schema_from_prompt(combined_prompt)
            except Exception:
                pass  # Keep original inference if combined fails

        logger.info(
            "Reference doc processed — %d entities extracted from file",
            len(ref_entities),
            extra={"stage": "nl_generate_ref", "event": "reference_processed"},
        )
    except Exception as e:
        logger.warning("Reference doc processing failed (continuing with prompt only): %s", e)

    # 3. Merge reference entities into prompt-inferred schema if applicable
    schema = nl_result.schema
    if ref_entities and not schema.tables:
        # Prompt didn't yield tables but reference did — use reference schema
        relationships = []
        schema = _build_schema(ref_entities, relationships)

    if not schema.tables:
        raise HTTPException(status_code=422, detail="Could not infer any entities from prompt or reference document")

    # 4. Create session
    session = store.create()
    session.schema = schema
    session.generation_order = nl_result.generation_order if nl_result.generation_order else [t.name for t in schema.tables]
    session.row_count = row_count
    session.uploaded_files = [
        UploadedFileInfo(filename="(natural language prompt)", file_type="nl", size_bytes=len(prompt)),
        UploadedFileInfo(filename=file.filename or "reference", file_type="reference", size_bytes=len(content)),
    ]

    # 5. Generate valid data
    data: dict[str, list[dict]] = {}
    try:
        gen = SyntheticDataGenerator(schema, row_count=row_count)
        data = gen.generate()
    except (CircularDependencyError, GeneratorError) as e:
        logger.error("NL+ref generation failed: %s", e)
        raise HTTPException(status_code=422, detail=str(e))

    # 6. Generate negative cases if requested
    negative_count = 0
    if include_invalid:
        toggles = NegativeToggles(
            invalid_emails=True,
            null_required_fields=True,
            broken_foreign_keys=True,
            invalid_enums=True,
            invalid_regex_patterns=True,
            boundary_values=True,
            duplicate_values=True,
        )
        try:
            neg_gen = NegativeCaseGenerator(schema, toggles=toggles)
            negative_dataset = neg_gen.generate()
            session.negative = negative_dataset
            negative_count = len(negative_dataset.invalid)
            for neg_row in negative_dataset.invalid:
                data.setdefault(neg_row.table, []).append(neg_row.row)
        except Exception as e:
            logger.warning("NL+ref negative generation failed: %s", e)

    # 7. Validate
    engine = ValidationEngine(schema)
    report = engine.validate(data)
    session.validation = report
    session.data = data

    # 8. Export
    try:
        exporter = ExportEngine()
        for fmt in ExportFormat:
            result = exporter.export(data, fmt, schema)
            session.exports[fmt.value] = result
    except ExportError as e:
        logger.error("NL+ref export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    session.generated_at = datetime.utcnow()

    table_infos = [
        NLGenerateTableInfo(table_name=name, row_count=len(rows))
        for name, rows in data.items()
    ]
    total = sum(len(rows) for rows in data.values())

    duration = round((time.perf_counter() - gen_start) * 1000, 1)
    logger.info(
        "NL+ref generate complete — domain=%s, %d tables, %d rows, %d negative (%.1fms)",
        nl_result.domain,
        len(data),
        total,
        negative_count,
        duration,
        extra={"stage": "nl_generate_ref", "session_id": session.session_id, "event": "generate_completed"},
    )

    return NLGenerateResponse(
        session_id=session.session_id,
        prompt=prompt,
        domain=nl_result.domain,
        tables=table_infos,
        total_rows=total,
        negative_cases=negative_count,
        validation=report,
        generation_order=session.generation_order,
        generated_sql=nl_result.generated_sql,
    )
