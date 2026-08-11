"""Standalone parser endpoints — parse individual SQL / OpenAPI / BDD files.

These endpoints are provided for direct file parsing without the
session-based pipeline workflow.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from app.models.schema import SchemaMetadata
from app.models.openapi import OpenAPIMetadata
from app.models.bdd import BDDMetadata
from app.parsers.sql_parser import parse_sql_schema, SQLParserError
from app.parsers.openapi_parser import parse_openapi_spec, OpenAPIParserError
from app.parsers.bdd_parser import parse_bdd_feature
from app.services.relationship_engine import (
    RelationshipGraph,
    CircularDependencyError,
)

router = APIRouter(prefix="/parse", tags=["Parsers"])

OPENAPI_EXTENSIONS = (".yaml", ".yml", ".json")
BDD_EXTENSIONS = (".feature", ".txt")


@router.post("/sql", response_model=SchemaMetadata)
async def parse_sql(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Only .sql files are accepted")

    content = await file.read()
    try:
        sql_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    try:
        result = parse_sql_schema(sql_text)
    except SQLParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return result


@router.post("/openapi", response_model=OpenAPIMetadata)
async def parse_openapi(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(OPENAPI_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail="Only .yaml, .yml, or .json files are accepted",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    is_json = file.filename.endswith(".json")
    try:
        result = parse_openapi_spec(text, is_json=is_json)
    except OpenAPIParserError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return result


@router.post("/bdd", response_model=BDDMetadata)
async def parse_bdd(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(BDD_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail="Only .feature or .txt files are accepted",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    result = parse_bdd_feature(text)
    return result


@router.post("/sql/graph")
async def parse_sql_graph(file: UploadFile = File(...)):
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

    graph = RelationshipGraph(schema)
    issues = graph.validate()

    try:
        generation_order = graph.get_generation_order()
    except CircularDependencyError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "generation_order": generation_order,
        "relationships": graph.get_edge_details(),
        "root_tables": graph.get_root_tables(),
        "leaf_tables": graph.get_leaf_tables(),
        "adjacency": graph.to_adjacency_dict(),
        "validation_issues": issues,
        "ascii_graph": graph.to_ascii(),
    }
