"""Reference-document ingestion router.

Endpoints:
  POST /reference/ingest   — upload image/BRD, run OCR + extraction
  POST /reference/generate — ingest + generate synthetic data + validate + export
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.ai.service import enrich_reference_doc
from app.exporters.engine import ExportEngine, ExportError
from app.generators.negative_generator import NegativeCaseGenerator
from app.generators.synthetic_generator import GeneratorError, SyntheticDataGenerator
from app.models.export import ExportFormat
from app.models.negative import NegativeToggles
from app.models.pipeline import UploadedFileInfo
from app.models.reference import (
    ExtractionSource,
    ExtractedConstraint,
    ExtractedEntity,
    ExtractedField,
    ExtractedRelationship,
    ReferenceDocType,
    ReferenceGenerateResponse,
    ReferenceIngestionResult,
    ReferenceTableInfo,
)
from app.parsers.ocr_pipeline import OCRError, extract_text_from_image
from app.parsers.reference_extractor import (
    ExtractionError,
    _build_schema,
    _generation_order,
    _schema_to_ddl,
    extract_entities_from_ocr,
)
from app.services.relationship_engine import CircularDependencyError
from app.services.session_store import store
from app.validators.engine import ValidationEngine

router = APIRouter(prefix="/reference", tags=["Reference Documents"])
logger = logging.getLogger(__name__)

# Supported image MIME types
_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

# Text MIME types for BRD snippets
_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "application/pdf",
}

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _classify_upload(file: UploadFile) -> ReferenceDocType:
    """Classify the uploaded file into a reference-document type."""
    ct = (file.content_type or "").lower()
    name = (file.filename or "").lower()

    if ct in _IMAGE_TYPES or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")):
        # Try to distinguish schema images from generic screenshots
        if any(kw in name for kw in ("schema", "erd", "diagram", "model", "db")):
            return ReferenceDocType.SCHEMA_IMAGE
        if any(kw in name for kw in ("api", "swagger", "endpoint", "postman")):
            return ReferenceDocType.API_SCREENSHOT
        return ReferenceDocType.SCREENSHOT

    if any(kw in name for kw in ("brd", "requirement", "spec", "business")):
        return ReferenceDocType.BRD_SNIPPET

    return ReferenceDocType.SCREENSHOT


# ── POST /reference/ingest ────────────────────────────────────


@router.post("/ingest", response_model=ReferenceIngestionResult)
async def ingest_reference(
    file: UploadFile = File(...),
    doc_type: str | None = Query(
        default=None,
        description="Override auto-detection: screenshot, schema_image, brd_snippet, api_screenshot",
    ),
):
    """Upload a reference document (image or text), run OCR, extract entities.

    Returns the inferred schema with confidence scores but does not generate data.
    """
    start = time.perf_counter()

    # Read file bytes
    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # Classify
    if doc_type:
        try:
            classified = ReferenceDocType(doc_type)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid doc_type: {doc_type}. Must be one of: {', '.join(t.value for t in ReferenceDocType)}",
            )
    else:
        classified = _classify_upload(file)

    filename = file.filename or "unknown"
    logger.info(
        "Reference ingest — file=%s, type=%s, size=%d",
        filename,
        classified.value,
        len(raw_bytes),
        extra={"stage": "reference_ingest", "event": "ingest_started"},
    )

    # Step 1: OCR (for images) or direct text extraction
    ct = (file.content_type or "").lower()
    is_image = ct in _IMAGE_TYPES or filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")
    )

    if is_image:
        try:
            ocr_result = extract_text_from_image(raw_bytes)
        except OCRError as e:
            raise HTTPException(status_code=422, detail=f"OCR failed: {e}")
    else:
        # Text file — use raw content as OCR result
        try:
            text_content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text_content = raw_bytes.decode("latin-1", errors="replace")
        from app.models.reference import OCRBlock, OCRResult

        ocr_result = OCRResult(
            raw_text=text_content,
            blocks=[OCRBlock(text=text_content, confidence=1.0)],
            avg_confidence=1.0,
        )

    # Step 2: Heuristic extraction
    result = extract_entities_from_ocr(ocr_result, classified, filename)

    # Step 3: AI enrichment (if available)
    ai_data = enrich_reference_doc(
        ocr_text=ocr_result.raw_text,
        doc_type=classified.value,
        ocr_confidence=ocr_result.avg_confidence,
    )
    if ai_data:
        result = _merge_ai_enrichment(result, ai_data)

    duration = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "Reference ingest complete — %d entities, confidence=%.2f (%.1fms)",
        len(result.entities),
        result.avg_confidence,
        duration,
        extra={
            "stage": "reference_ingest",
            "event": "ingest_completed",
            "duration_ms": duration,
        },
    )

    return result


# ── POST /reference/generate ──────────────────────────────────


@router.post("/generate", response_model=ReferenceGenerateResponse)
async def generate_from_reference(
    file: UploadFile = File(...),
    doc_type: str | None = Query(default=None),
    row_count: int = Query(default=100, ge=1, le=10000),
    include_invalid: bool = Query(default=False),
):
    """Ingest reference doc, infer schema, generate synthetic data, validate, export.

    One-shot: image in → data out with download links.
    """
    start = time.perf_counter()

    # Read file
    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # Classify
    if doc_type:
        try:
            classified = ReferenceDocType(doc_type)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid doc_type: {doc_type}")
    else:
        classified = _classify_upload(file)

    filename = file.filename or "unknown"
    logger.info(
        "Reference generate — file=%s, type=%s, rows=%d",
        filename,
        classified.value,
        row_count,
        extra={"stage": "reference_generate", "event": "generate_started"},
    )

    # 1. OCR
    ct = (file.content_type or "").lower()
    is_image = ct in _IMAGE_TYPES or filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")
    )

    if is_image:
        try:
            ocr_result = extract_text_from_image(raw_bytes)
        except OCRError as e:
            raise HTTPException(status_code=422, detail=f"OCR failed: {e}")
    else:
        try:
            text_content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text_content = raw_bytes.decode("latin-1", errors="replace")
        from app.models.reference import OCRResult, OCRBlock

        ocr_result = OCRResult(
            raw_text=text_content,
            blocks=[OCRBlock(text=text_content, confidence=1.0)],
            avg_confidence=1.0,
        )

    # 2. Extract entities
    ingestion = extract_entities_from_ocr(ocr_result, classified, filename)

    # 3. AI enrichment
    ai_data = enrich_reference_doc(
        ocr_text=ocr_result.raw_text,
        doc_type=classified.value,
        ocr_confidence=ocr_result.avg_confidence,
    )
    if ai_data:
        ingestion = _merge_ai_enrichment(ingestion, ai_data)

    if not ingestion.entities:
        raise HTTPException(
            status_code=422,
            detail="Could not extract any entities from the document",
        )

    # 4. Build schema
    schema = _build_schema(ingestion.entities, ingestion.relationships)
    if not schema.tables:
        raise HTTPException(status_code=422, detail="No tables could be generated")

    gen_order = _generation_order(ingestion.entities, ingestion.relationships)

    # 5. Create session
    session = store.create()
    session.schema = schema
    session.generation_order = gen_order
    session.row_count = row_count
    session.uploaded_files = [
        UploadedFileInfo(
            filename=filename,
            file_type=classified.value,
            size_bytes=len(raw_bytes),
        ),
    ]

    # 6. Generate valid data
    data: dict[str, list[dict]] = {}
    try:
        gen = SyntheticDataGenerator(schema, row_count=row_count)
        data = gen.generate()
    except (CircularDependencyError, GeneratorError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 7. Negative cases
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
            logger.warning("Reference negative generation failed: %s", e)

    # 8. Validate
    engine = ValidationEngine(schema)
    report = engine.validate(data)
    session.validation = report
    session.data = data

    # 9. Export
    try:
        exporter = ExportEngine()
        for fmt in ExportFormat:
            result = exporter.export(data, fmt, schema)
            session.exports[fmt.value] = result
    except ExportError as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    session.generated_at = datetime.utcnow()

    table_infos = [
        ReferenceTableInfo(table_name=name, row_count=len(rows))
        for name, rows in data.items()
    ]
    total = sum(len(rows) for rows in data.values())

    duration = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "Reference generate complete — domain=%s, %d tables, %d rows (%.1fms)",
        ingestion.domain,
        len(data),
        total,
        duration,
        extra={
            "stage": "reference_generate",
            "session_id": session.session_id,
            "event": "generate_completed",
            "duration_ms": duration,
        },
    )

    return ReferenceGenerateResponse(
        session_id=session.session_id,
        filename=filename,
        doc_type=classified.value,
        domain=ingestion.domain,
        tables=table_infos,
        total_rows=total,
        negative_cases=negative_count,
        avg_confidence=ingestion.avg_confidence,
        generation_order=gen_order,
        schema_sql=ingestion.schema_sql,
        message="Generation complete",
    )


# ── AI enrichment merge ────────────────────────────────────────


def _merge_ai_enrichment(
    result: ReferenceIngestionResult,
    ai_data: dict,
) -> ReferenceIngestionResult:
    """Merge AI-enriched entities/relationships into the heuristic result.

    AI entities supplement or replace heuristic ones with higher confidence.
    """
    if "domain" in ai_data and ai_data["domain"]:
        result.domain = ai_data["domain"]

    existing_names = {e.name.lower() for e in result.entities}

    # Merge entities
    for ai_entity in ai_data.get("entities", []):
        name = ai_entity.get("name", "")
        if not name:
            continue
        conf = ai_entity.get("confidence", 0.7)

        fields: list[ExtractedField] = []
        for col in ai_entity.get("columns", []):
            fields.append(
                ExtractedField(
                    name=col.get("name", ""),
                    data_type=col.get("data_type", "VARCHAR"),
                    nullable=col.get("nullable", True),
                    is_primary_key=col.get("is_primary_key", False),
                    is_unique=col.get("is_unique", False),
                    check_constraint=col.get("check_constraint"),
                    description=col.get("description", ""),
                    source=ExtractionSource.AI,
                    confidence=col.get("confidence", conf),
                )
            )

        if name.lower() in existing_names:
            # Replace heuristic entity with higher-confidence AI version
            for i, existing in enumerate(result.entities):
                if existing.name.lower() == name.lower() and conf > existing.confidence:
                    result.entities[i] = ExtractedEntity(
                        name=name,
                        description=ai_entity.get("description", ""),
                        fields=fields,
                        source=ExtractionSource.AI,
                        confidence=conf,
                    )
                    break
        else:
            result.entities.append(
                ExtractedEntity(
                    name=name,
                    description=ai_entity.get("description", ""),
                    fields=fields,
                    source=ExtractionSource.AI,
                    confidence=conf,
                )
            )
            existing_names.add(name.lower())

    # Merge relationships
    existing_rels = {
        (r.from_entity.lower(), r.to_entity.lower()) for r in result.relationships
    }
    for ai_rel in ai_data.get("relationships", []):
        key = (
            ai_rel.get("from_entity", "").lower(),
            ai_rel.get("to_entity", "").lower(),
        )
        if key not in existing_rels:
            result.relationships.append(
                ExtractedRelationship(
                    from_entity=ai_rel.get("from_entity", ""),
                    from_field=ai_rel.get("from_field", ""),
                    to_entity=ai_rel.get("to_entity", ""),
                    to_field=ai_rel.get("to_field", ""),
                    source=ExtractionSource.AI,
                    confidence=ai_rel.get("confidence", 0.7),
                )
            )
            existing_rels.add(key)

    # Merge constraints
    for ai_con in ai_data.get("constraints", []):
        result.constraints.append(
            ExtractedConstraint(
                entity=ai_con.get("entity", ""),
                field=ai_con.get("field", ""),
                rule=ai_con.get("rule", ""),
                description=ai_con.get("description", ""),
                source=ExtractionSource.AI,
                confidence=ai_con.get("confidence", 0.6),
            )
        )

    # Recompute confidence
    all_confs = [e.confidence for e in result.entities]
    all_confs += [f.confidence for e in result.entities for f in e.fields]
    all_confs += [r.confidence for r in result.relationships]
    result.avg_confidence = round(sum(all_confs) / len(all_confs), 3) if all_confs else 0.0

    # Regenerate DDL
    schema = _build_schema(result.entities, result.relationships)
    result.schema_sql = _schema_to_ddl(schema)

    return result
