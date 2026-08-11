"""Structured logging configuration.

Provides JSON-formatted log output with consistent fields for
pipeline stage tracking, request context, and error diagnostics.
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

from app.utils.config import settings


class StructuredFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach structured extras injected via `logger.info("msg", extra={...})`
        for key in ("stage", "session_id", "event", "detail",
                     "file_type", "file_name", "table", "row_count",
                     "duration_ms", "error_type", "status_code"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(entry, default=str)


def setup_logging() -> logging.Logger:
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    logging.basicConfig(
        level=log_level,
        handlers=[handler],
        force=True,
    )

    logger = logging.getLogger(settings.APP_NAME)
    logger.setLevel(log_level)
    return logger


logger = setup_logging()
