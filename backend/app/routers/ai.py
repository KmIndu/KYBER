"""AI reasoning endpoints — analyse SQL schemas and BDD features for hidden rules."""

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.ai.service import analyze_schema, analyze_bdd, analyze_combined
from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.parsers.bdd_parser import parse_bdd_feature, BDDParserError

router = APIRouter(prefix="/ai", tags=["AI Reasoning"])


@router.post("/analyze/sql")
async def ai_analyze_sql(file: UploadFile = File(...)):
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

    result = analyze_schema(schema, schema_text=sql_text)
    return result.model_dump()


@router.post("/analyze/bdd")
async def ai_analyze_bdd(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith((".feature", ".txt")):
        raise HTTPException(status_code=400, detail="Only .feature or .txt files are accepted")

    content = await file.read()
    try:
        bdd_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    try:
        bdd = parse_bdd_feature(bdd_text)
    except BDDParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = analyze_bdd(bdd, bdd_text=bdd_text)
    return result.model_dump()


@router.post("/analyze/combined")
async def ai_analyze_combined(
    sql_file: UploadFile | None = File(default=None),
    bdd_file: UploadFile | None = File(default=None),
):
    schema = None
    bdd = None
    sql_text = ""
    bdd_text = ""

    if sql_file and sql_file.filename:
        raw = await sql_file.read()
        try:
            sql_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="SQL file must be UTF-8 encoded")
        try:
            schema = parse_sql_schema(sql_text)
        except SQLParserError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if bdd_file and bdd_file.filename:
        raw = await bdd_file.read()
        try:
            bdd_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="BDD file must be UTF-8 encoded")
        try:
            bdd = parse_bdd_feature(bdd_text)
        except BDDParserError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if not schema and not bdd:
        raise HTTPException(status_code=400, detail="At least one file must be provided")

    result = analyze_combined(
        schema=schema,
        bdd=bdd,
        schema_text=sql_text,
        bdd_text=bdd_text,
    )
    return result.model_dump()
