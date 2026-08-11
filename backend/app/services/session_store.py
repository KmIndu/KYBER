"""In-memory session store for the pipeline workflow.

Each session holds uploaded files, parsed metadata, generated data,
and export results between API calls. Sessions are keyed by UUID
and cleaned up on shutdown or after expiry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.export import ExportResult
from app.models.negative import NegativeDataset
from app.models.schema import SchemaMetadata
from app.models.openapi import OpenAPIMetadata
from app.models.bdd import BDDMetadata
from app.models.validation import ValidationReport
from app.models.pipeline import UploadedFileInfo
from app.models.integration import IntegrationBundle


@dataclass
class Session:
    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Upload stage
    uploaded_files: list[UploadedFileInfo] = field(default_factory=list)
    raw_sql: str | None = None
    raw_openapi: str | None = None
    raw_openapi_is_json: bool = False
    raw_bdd: str | None = None
    raw_csv: str | None = None
    raw_xlsx: bytes | None = None
    raw_xml: str | None = None

    # Multi-file support: lists of all uploaded contents per type
    raw_sql_files: list[str] = field(default_factory=list)
    raw_openapi_files: list[tuple[str, bool]] = field(default_factory=list)  # (content, is_json)
    raw_csv_files: list[str] = field(default_factory=list)
    raw_xlsx_files: list[bytes] = field(default_factory=list)
    raw_xml_files: list[str] = field(default_factory=list)
    raw_bdd_files: list[str] = field(default_factory=list)

    # Parse stage
    schema: SchemaMetadata | None = None
    openapi: OpenAPIMetadata | None = None
    bdd: BDDMetadata | None = None
    generation_order: list[str] = field(default_factory=list)

    # Generate stage
    row_count: int = 0
    data: dict[str, list[dict[str, Any]]] | None = None
    negative: NegativeDataset | None = None
    validation: ValidationReport | None = None
    coherence: dict[str, Any] | None = None
    business_context: dict[str, Any] | None = None
    generated_at: datetime | None = None
    ai_enhanced: bool = False

    # Export stage
    exports: dict[str, ExportResult] = field(default_factory=dict)

    # Integration stage
    integration_bundle: IntegrationBundle | None = None


class SessionStore:
    """Thread-safe (GIL) in-memory store."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex[:16]
        session = Session(session_id=sid)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()

    @property
    def count(self) -> int:
        return len(self._sessions)


# Singleton instance used by the app
store = SessionStore()
