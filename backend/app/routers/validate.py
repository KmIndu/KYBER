"""Standalone validation endpoint — generate and validate from a single SQL file."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Query

from app.generators.synthetic_generator import SyntheticDataGenerator, GeneratorError
from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.services.relationship_engine import CircularDependencyError
from app.validators.engine import ValidationEngine
from app.validators.coherence_validator import validate_coherence

router = APIRouter(prefix="/validate", tags=["Validation"])


@router.post("/sql")
async def validate_generated_sql(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=10000),
):
    """Generate data from a SQL schema and validate it against constraints."""
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
        generator = SyntheticDataGenerator(schema, row_count=row_count)
        data = generator.generate()
    except (CircularDependencyError, GeneratorError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    engine = ValidationEngine(schema)
    report = engine.validate(data)

    return report.model_dump()


@router.post("/coherence")
async def validate_coherence_sql(
    file: UploadFile = File(...),
    row_count: int = Query(default=10, ge=1, le=10000),
):
    """Generate data from a SQL schema and run coherence validation.

    Detects semantic contradictions such as:
    - approved status + rejection comment
    - invalid email + verified=true
    - country=India + phone_code=+1
    """
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
        generator = SyntheticDataGenerator(schema, row_count=row_count)
        data = generator.generate()
    except (CircularDependencyError, GeneratorError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    coherence_report = validate_coherence(data)
    return coherence_report.to_dict()
