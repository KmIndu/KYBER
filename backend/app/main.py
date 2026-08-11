"""FastAPI application entry point.

Configures CORS, request logging, exception handlers, and mounts all
routers under the app instance.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware.error_handler import (
    register_exception_handlers,
    request_logging_middleware,
)
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.parse import router as parse_router
from app.routers.generate import router as generate_router
from app.routers.ai import router as ai_router
from app.routers.validate import router as validate_router
from app.routers.export import router as export_router
from app.routers.nl import router as nl_router
from app.routers.reference import router as reference_router
from app.routers.pipeline import router as pipeline_router
from app.routers.integration import router as integration_router
from app.routers.edge_cases import router as edge_cases_router
from app.routers.partitions import router as partitions_router
from app.routers.domain import router as domain_router
from app.routers.integrity_check import router as integrity_router
from app.routers.payloads import router as payloads_router
from app.routers.constraints import router as constraints_router
from app.routers.business_rules import router as business_rules_router
from app.routers.semantics import router as semantics_router
from app.routers.history import router as history_router
from app.routers.identity import router as identity_router
from app.routers.chat import router as chat_router
from app.services.session_store import store as session_store
from app.utils.config import settings
from app.utils.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    yield
    logger.info("Shutting down %s — clearing %d sessions", settings.APP_NAME, session_store.count)
    session_store.clear()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

_original_openapi = app.openapi


def _patched_openapi():
    """Patch OpenAPI schema so Swagger UI shows file pickers instead of text boxes."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = _original_openapi()
    for schema_def in schema.get("components", {}).get("schemas", {}).values():
        for prop in schema_def.get("properties", {}).values():
            if prop.get("type") == "array":
                items = prop.get("items", {})
                if "contentMediaType" in items:
                    del items["contentMediaType"]
                    items["type"] = "string"
                    items["format"] = "binary"
            elif "contentMediaType" in prop:
                del prop["contentMediaType"]
                prop["type"] = "string"
                prop["format"] = "binary"
    app.openapi_schema = schema
    return schema


app.openapi = _patched_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request logging middleware ---
app.middleware("http")(request_logging_middleware)

# --- Centralized exception handlers ---
register_exception_handlers(app)

# --- Routers ---
app.include_router(auth_router)
app.include_router(health_router, tags=["Health"])
app.include_router(parse_router)
app.include_router(generate_router)
app.include_router(ai_router)
app.include_router(validate_router)
app.include_router(export_router)
app.include_router(nl_router)
app.include_router(reference_router)
app.include_router(pipeline_router)
app.include_router(integration_router)
app.include_router(edge_cases_router)
app.include_router(partitions_router)
app.include_router(domain_router)
app.include_router(integrity_router)
app.include_router(payloads_router)
app.include_router(constraints_router)
app.include_router(business_rules_router)
app.include_router(semantics_router)
app.include_router(history_router)
app.include_router(identity_router)
app.include_router(chat_router)
