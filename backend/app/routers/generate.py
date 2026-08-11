"""Standalone generation endpoints — generate data from a single SQL file.

These endpoints are provided for direct generation without the
session-based pipeline workflow.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.generators.synthetic_generator import SyntheticDataGenerator, GeneratorError
from app.generators.negative_generator import NegativeCaseGenerator
from app.models.negative import NegativeToggles
from app.services.relationship_engine import CircularDependencyError

router = APIRouter(prefix="/generate", tags=["Generation"])


@router.post("/sql")
async def generate_from_sql(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=1000000),
    country: str = Query(default="us", description="Country for locale-aware generation"),
    domain: str = Query(default="unknown", description="Business domain (banking, insurance, healthcare, retail)"),
):
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    try:
        schema = parse_sql_schema(sql_text)
    except SQLParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        generator = SyntheticDataGenerator(schema, row_count=row_count, country=country, domain=domain)
        data = generator.generate()
    except CircularDependencyError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except GeneratorError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return data


@router.post("/sql/negative")
async def generate_negative_from_sql(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=1000000),
    invalid_emails: bool = Query(default=True),
    null_required_fields: bool = Query(default=True),
    duplicate_values: bool = Query(default=True),
    broken_foreign_keys: bool = Query(default=True),
    boundary_values: bool = Query(default=True),
    invalid_enums: bool = Query(default=True),
    invalid_regex_patterns: bool = Query(default=True),
):
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    try:
        schema = parse_sql_schema(sql_text)
    except SQLParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    toggles = NegativeToggles(
        invalid_emails=invalid_emails,
        null_required_fields=null_required_fields,
        duplicate_values=duplicate_values,
        broken_foreign_keys=broken_foreign_keys,
        boundary_values=boundary_values,
        invalid_enums=invalid_enums,
        invalid_regex_patterns=invalid_regex_patterns,
    )

    try:
        generator = NegativeCaseGenerator(schema, row_count=row_count, toggles=toggles)
        result = generator.generate()
    except CircularDependencyError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    return result.model_dump()
