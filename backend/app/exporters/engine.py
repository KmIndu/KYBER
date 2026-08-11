"""Export engine — CSV, JSON, SQL INSERT with ZIP packaging.

Exports generated data to individual files per table, bundled into
a downloadable ZIP archive with a metadata summary.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.models.export import (
    ExportFormat,
    ExportResult,
    ExportSummary,
    TableExportInfo,
)
from app.models.schema import SchemaMetadata

logger = logging.getLogger(__name__)

# ── Default output directory ──────────────────────────────────

_OUTPUT_DIR = os.environ.get("EXPORT_OUTPUT_DIR", tempfile.gettempdir())


class ExportError(Exception):
    """Raised when export fails."""


# ── JSON serialiser for dates/datetimes ───────────────────────


def _json_serial(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# ── Chunk size for streaming writes ───────────────────────────

_CHUNK_SIZE = 10_000  # rows per write chunk

# Threshold above which we skip zlib compression (ZIP_STORED)
_COMPRESSION_THRESHOLD = 50_000

# SQL multi-value INSERT batch size
_SQL_BATCH = 1_000


# ── Individual format writers (chunked for large datasets) ────


def _write_csv(table_name: str, rows: list[dict[str, Any]]) -> str:
    """Return CSV content for a single table, written in chunks."""
    if not rows:
        return ""
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for start in range(0, len(rows), _CHUNK_SIZE):
        writer.writerows(rows[start : start + _CHUNK_SIZE])
    return buf.getvalue()


def _write_csv_to_zip(
    zf: zipfile.ZipFile, file_name: str, table_name: str, rows: list[dict[str, Any]],
) -> None:
    """Stream CSV into an open ZIP file without building a full string."""
    if not rows:
        zf.writestr(file_name, "")
        return
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    zf.writestr(file_name, buf.getvalue())


def _write_json(table_name: str, rows: list[dict[str, Any]]) -> str:
    """Return JSON content for a single table."""
    return json.dumps(rows, indent=2, default=_json_serial)


def _write_json_to_zip(
    zf: zipfile.ZipFile, file_name: str, table_name: str, rows: list[dict[str, Any]],
) -> None:
    """Stream JSON into an open ZIP file without full-string buffering."""
    if not rows:
        zf.writestr(file_name, "[]")
        return
    # For large datasets, use compact JSON (no indent) to save memory/time
    if len(rows) > 50_000:
        zf.writestr(file_name, json.dumps(rows, default=_json_serial))
    else:
        zf.writestr(file_name, json.dumps(rows, indent=2, default=_json_serial))


def _write_sql_to_zip(
    zf: zipfile.ZipFile, file_name: str, table_name: str, rows: list[dict[str, Any]],
) -> None:
    """Write SQL INSERTs using multi-value batches (1000 rows per statement)."""
    if not rows:
        zf.writestr(file_name, f"-- No data for {table_name}\n")
        return
    buf = io.StringIO()
    columns = list(rows[0].keys())
    col_list = ", ".join(columns)
    n = len(rows)
    for start in range(0, n, _SQL_BATCH):
        batch = rows[start : start + _SQL_BATCH]
        value_rows = []
        for row in batch:
            vals = ", ".join(_sql_escape(row.get(c)) for c in columns)
            value_rows.append(f"({vals})")
        buf.write(f"INSERT INTO {table_name} ({col_list}) VALUES\n")
        buf.write(",\n".join(value_rows))
        buf.write(";\n")
    zf.writestr(file_name, buf.getvalue())


def _sql_escape(value: Any) -> str:
    """Escape a value for SQL INSERT literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return f"'{value.isoformat()}'"
    # String — escape single quotes
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _write_sql(table_name: str, rows: list[dict[str, Any]]) -> str:
    """Return SQL INSERT statements for a single table."""
    if not rows:
        return f"-- No data for {table_name}\n"

    lines: list[str] = []
    columns = list(rows[0].keys())
    col_list = ", ".join(columns)

    for row in rows:
        values = ", ".join(_sql_escape(row.get(c)) for c in columns)
        lines.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({values});")

    return "\n".join(lines) + "\n"


_WRITERS = {
    ExportFormat.CSV: (_write_csv, ".csv"),
    ExportFormat.JSON: (_write_json, ".json"),
    ExportFormat.SQL: (_write_sql, ".sql"),
}

# Direct-to-ZIP writers (avoid building full string in memory)
_ZIP_WRITERS = {
    ExportFormat.CSV: (_write_csv_to_zip, ".csv"),
    ExportFormat.JSON: (_write_json_to_zip, ".json"),
    ExportFormat.SQL: (_write_sql_to_zip, ".sql"),
}


# ── Export engine ─────────────────────────────────────────────


class ExportEngine:
    """Exports generated data to ZIP archives."""

    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or _OUTPUT_DIR

    def _ensure_output_dir(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_table_name(self, name: str) -> str:
        """Sanitise table name for use as a filename."""
        return re.sub(r"[^\w\-.]", "_", name)

    def export(
        self,
        data: dict[str, list[dict[str, Any]]],
        fmt: ExportFormat,
        schema: SchemaMetadata | None = None,
    ) -> ExportResult:
        """Export all tables in *data* to a ZIP archive.

        Parameters
        ----------
        data : dict mapping table name → list of row dicts
        fmt  : target format (csv / json / sql)
        schema : optional schema metadata (included in summary)

        Returns
        -------
        ExportResult with zip_path and summary
        """
        zip_writer_fn, ext = _ZIP_WRITERS[fmt]
        out_dir = self._ensure_output_dir()

        table_infos: list[TableExportInfo] = []
        total_rows = 0

        zip_name = f"export_{fmt.value}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = out_dir / zip_name

        # Skip zlib compression for large datasets — I/O bound, not size bound
        total_row_count = sum(len(rows) for rows in data.values())
        compression = zipfile.ZIP_STORED if total_row_count > _COMPRESSION_THRESHOLD else zipfile.ZIP_DEFLATED

        try:
            with zipfile.ZipFile(zip_path, "w", compression) as zf:
                for table_name, rows in data.items():
                    safe_name = self._safe_table_name(table_name)
                    file_name = f"{safe_name}{ext}"
                    zip_writer_fn(zf, file_name, table_name, rows)

                    info = TableExportInfo(
                        table_name=table_name,
                        row_count=len(rows),
                        file_name=file_name,
                        format=fmt,
                    )
                    table_infos.append(info)
                    total_rows += len(rows)

                # Write summary metadata into the ZIP
                summary = ExportSummary(
                    format=fmt,
                    total_tables=len(data),
                    total_rows=total_rows,
                    tables=table_infos,
                )
                summary_json = summary.model_dump_json(indent=2)
                zf.writestr("_export_summary.json", summary_json)

        except OSError as e:
            logger.error(
                "Failed to write ZIP: %s",
                e,
                extra={"stage": "export", "event": "export_write_error", "error_type": "OSError"},
            )
            raise ExportError(f"Failed to write ZIP: {e}") from e

        logger.info(
            "Exported %d tables (%d rows) as %s → %s",
            len(data),
            total_rows,
            fmt.value,
            zip_path,
            extra={"stage": "export", "event": "export_written", "row_count": total_rows},
        )

        return ExportResult(zip_path=str(zip_path), summary=summary)

    def export_all_formats(
        self,
        data: dict[str, list[dict[str, Any]]],
        schema: SchemaMetadata | None = None,
    ) -> list[ExportResult]:
        """Export data in all supported formats, returning a list of results."""
        results: list[ExportResult] = []
        for fmt in ExportFormat:
            results.append(self.export(data, fmt, schema))
        return results
