"""Persistent per-user history of generated datasets.

Stores generation records as JSON files on disk so they survive
server restarts.  Each user (identified by email) has their own
folder under ``DATA_DIR/history/<email_hash>/``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Root directory for history storage
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "history",
)


def _user_dir(email: str) -> str:
    """Return the directory for a given user (hashed email)."""
    safe = hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]
    return os.path.join(_DATA_DIR, safe)


@dataclass
class HistoryRecord:
    """A single historical generation record."""
    id: str
    email: str
    created_at: str  # ISO format
    source_files: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    row_count: int
    total_rows: int
    negative_cases: int
    generation_order: list[str]
    data: dict[str, list[dict[str, Any]]] | None = None
    validation_passed: int = 0
    validation_failed: int = 0
    label: str = ""
    schema: dict[str, Any] | None = None
    negative_data: dict[str, Any] | None = None
    edge_cases: dict[str, Any] | None = None
    partitions: dict[str, Any] | None = None
    integration_bundle: dict[str, Any] | None = None
    integration_guide: dict[str, Any] | None = None


class HistoryStore:
    """File-backed per-user history store."""

    def __init__(self, data_dir: str = _DATA_DIR) -> None:
        self._data_dir = data_dir
        os.makedirs(self._data_dir, exist_ok=True)

    # ── Write ──────────────────────────────────────────────

    def save(self, record: HistoryRecord) -> None:
        """Persist a history record to disk."""
        user_dir = _user_dir(record.email)
        os.makedirs(user_dir, exist_ok=True)
        path = os.path.join(user_dir, f"{record.id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(record), f, default=str, indent=2)
        logger.info("History saved: %s for %s", record.id, record.email)

    # ── Read ───────────────────────────────────────────────

    def list_for_user(self, email: str) -> list[dict]:
        """Return metadata (no row data) for all records belonging to *email*,
        sorted newest first."""
        user_dir = _user_dir(email)
        if not os.path.isdir(user_dir):
            return []
        records: list[dict] = []
        MAX_FILE_SIZE = 50 * 1024 * 1024  # skip files > 50 MB for listing
        for fname in os.listdir(user_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(user_dir, fname)
            try:
                if os.path.getsize(path) > MAX_FILE_SIZE:
                    logger.warning("Skipping oversized history file: %s", path)
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                # Strip heavy payload for listing
                rec.pop("data", None)
                rec.pop("schema", None)
                rec.pop("negative_data", None)
                rec.pop("edge_cases", None)
                rec.pop("partitions", None)
                rec.pop("integration_bundle", None)
                rec.pop("integration_guide", None)
                records.append(rec)
            except Exception:
                logger.warning("Corrupt history file: %s", path)
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return records

    def get(self, email: str, record_id: str) -> dict | None:
        """Load a full record (including data) by ID."""
        user_dir = _user_dir(email)
        path = os.path.join(user_dir, f"{record_id}.json")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def update(self, email: str, record_id: str, updates: dict[str, Any]) -> bool:
        """Merge *updates* into an existing record and re-save."""
        user_dir = _user_dir(email)
        path = os.path.join(user_dir, f"{record_id}.json")
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            rec = json.load(f)
        rec.update(updates)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, default=str, indent=2)
        logger.info("History updated: %s for %s (fields: %s)", record_id, email, list(updates.keys()))
        return True

    def delete(self, email: str, record_id: str) -> bool:
        """Delete a single record.  Returns True if it existed."""
        user_dir = _user_dir(email)
        path = os.path.join(user_dir, f"{record_id}.json")
        if os.path.isfile(path):
            os.remove(path)
            logger.info("History deleted: %s for %s", record_id, email)
            return True
        return False

    def delete_all(self, email: str) -> int:
        """Delete all records for a user.  Returns count deleted."""
        user_dir = _user_dir(email)
        if not os.path.isdir(user_dir):
            return 0
        count = len([f for f in os.listdir(user_dir) if f.endswith(".json")])
        shutil.rmtree(user_dir, ignore_errors=True)
        logger.info("History cleared: %d records for %s", count, email)
        return count

    def count_for_user(self, email: str) -> int:
        user_dir = _user_dir(email)
        if not os.path.isdir(user_dir):
            return 0
        return len([f for f in os.listdir(user_dir) if f.endswith(".json")])


# Singleton
history_store = HistoryStore()
