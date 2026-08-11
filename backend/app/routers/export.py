"""Export router — download generated data as CSV, JSON, SQL, or all formats."""

from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.exporters.engine import ExportEngine, ExportError
from app.generators.synthetic_generator import SyntheticDataGenerator, GeneratorError
from app.models.export import ExportFormat
from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.services.relationship_engine import CircularDependencyError

router = APIRouter(prefix="/export", tags=["Export"])


def _generate_data(sql_text: str, row_count: int) -> dict:
    """Parse schema + generate data, returning (schema, data)."""
    try:
        schema = parse_sql_schema(sql_text)
    except SQLParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        gen = SyntheticDataGenerator(schema, row_count=row_count)
        data = gen.generate()
    except CircularDependencyError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except GeneratorError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return schema, data


@router.post("/csv")
async def export_csv(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=1000000),
):
    """Generate synthetic data and download as CSV ZIP."""
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    schema, data = _generate_data(sql_text, row_count)

    try:
        engine = ExportEngine()
        result = engine.export(data, ExportFormat.CSV, schema)
    except ExportError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(
        path=result.zip_path,
        media_type="application/zip",
        filename=os.path.basename(result.zip_path),
    )


@router.post("/json")
async def export_json(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=10000),
):
    """Generate synthetic data and download as JSON ZIP."""
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    schema, data = _generate_data(sql_text, row_count)

    try:
        engine = ExportEngine()
        result = engine.export(data, ExportFormat.JSON, schema)
    except ExportError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(
        path=result.zip_path,
        media_type="application/zip",
        filename=os.path.basename(result.zip_path),
    )


@router.post("/sql")
async def export_sql(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=10000),
):
    """Generate synthetic data and download as SQL INSERT ZIP."""
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    schema, data = _generate_data(sql_text, row_count)

    try:
        engine = ExportEngine()
        result = engine.export(data, ExportFormat.SQL, schema)
    except ExportError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(
        path=result.zip_path,
        media_type="application/zip",
        filename=os.path.basename(result.zip_path),
    )


@router.post("/all")
async def export_all(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=10000),
):
    """Generate synthetic data and return summary with paths for all formats."""
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    schema, data = _generate_data(sql_text, row_count)

    try:
        engine = ExportEngine()
        results = engine.export_all_formats(data, schema)
    except ExportError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "formats": [
            {
                "format": r.summary.format.value,
                "zip_path": r.zip_path,
                "total_tables": r.summary.total_tables,
                "total_rows": r.summary.total_rows,
                "tables": [t.model_dump() for t in r.summary.tables],
            }
            for r in results
        ]
    }
