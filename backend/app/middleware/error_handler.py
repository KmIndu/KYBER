"""Centralized exception handling for the FastAPI application.

Catches unhandled exceptions and domain-specific errors, returning
consistent JSON error responses with structured logging.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exporters.engine import ExportError
from app.generators.synthetic_generator import GeneratorError
from app.parsers.openapi_parser import OpenAPIParserError
from app.parsers.sql_parser import SQLParserError
from app.services.relationship_engine import CircularDependencyError

logger = logging.getLogger(__name__)


# ── Request logging middleware ────────────────────────────────


async def request_logging_middleware(request: Request, call_next):
    """Log every request with duration and status code."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={
            "event": "request_completed",
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# ── Exception handlers ────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Only log 5xx as errors; 4xx are warnings
        if exc.status_code >= 500:
            logger.error(
                "HTTP %d: %s",
                exc.status_code,
                exc.detail,
                extra={
                    "event": "http_error",
                    "error_type": "HTTPException",
                    "status_code": exc.status_code,
                },
            )
        else:
            logger.warning(
                "HTTP %d: %s",
                exc.status_code,
                exc.detail,
                extra={
                    "event": "client_error",
                    "error_type": "HTTPException",
                    "status_code": exc.status_code,
                },
            )
        # Preserve FastAPI's default {"detail": "..."} shape
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        logger.warning(
            "Validation error: %d issues",
            len(errors),
            extra={
                "event": "validation_error",
                "error_type": "RequestValidationError",
                "detail": errors,
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    @app.exception_handler(SQLParserError)
    async def sql_parser_error_handler(request: Request, exc: SQLParserError):
        logger.error(
            "Malformed SQL: %s",
            exc,
            extra={
                "event": "parse_error",
                "error_type": "SQLParserError",
                "stage": "parsing",
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": f"Malformed SQL: {exc}"},
        )

    @app.exception_handler(OpenAPIParserError)
    async def openapi_parser_error_handler(request: Request, exc: OpenAPIParserError):
        logger.error(
            "Invalid YAML/JSON: %s",
            exc,
            extra={
                "event": "parse_error",
                "error_type": "OpenAPIParserError",
                "stage": "parsing",
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": f"Invalid OpenAPI spec: {exc}"},
        )

    @app.exception_handler(CircularDependencyError)
    async def circular_dep_handler(request: Request, exc: CircularDependencyError):
        logger.error(
            "Circular dependency: %s",
            exc,
            extra={
                "event": "dependency_error",
                "error_type": "CircularDependencyError",
                "stage": "parsing",
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )

    @app.exception_handler(GeneratorError)
    async def generator_error_handler(request: Request, exc: GeneratorError):
        logger.error(
            "Generation failed: %s",
            exc,
            extra={
                "event": "generation_error",
                "error_type": "GeneratorError",
                "stage": "generation",
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": f"Data generation failed: {exc}"},
        )

    @app.exception_handler(ExportError)
    async def export_error_handler(request: Request, exc: ExportError):
        logger.error(
            "Export failed: %s",
            exc,
            extra={
                "event": "export_error",
                "error_type": "ExportError",
                "stage": "export",
            },
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"Export failed: {exc}"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        error_id = uuid.uuid4().hex[:12]
        logger.critical(
            "Unhandled exception [%s]: %s",
            error_id,
            exc,
            exc_info=True,
            extra={
                "event": "unhandled_error",
                "error_type": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected error occurred. Please try again.",
                "error_id": error_id,
            },
        )
