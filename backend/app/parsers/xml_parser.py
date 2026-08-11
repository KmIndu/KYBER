"""XML parser — infers schema metadata from XML documents.

Treats each unique element name (that has children or appears
multiple times) as a table.  Attributes and text children become
columns.  Nested element names that match other "tables" are
treated as foreign-key relationships.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)

logger = logging.getLogger(__name__)


class XMLParserError(Exception):
    """Raised when XML parsing fails."""


def parse_xml_schema(
    text: str,
    default_table_name: str = "imported_table",
) -> SchemaMetadata:
    """Infer SQL schema from XML content.

    Strategy:
      1. Walk the tree and collect every element tag.
      2. Elements that appear as repeated children under a parent
         become "row" elements → each one is a table.
      3. Their attributes + direct-text children become columns.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise XMLParserError(f"Invalid XML: {exc}") from exc

    # Collect info about every element
    element_info: dict[str, _ElemInfo] = defaultdict(lambda: _ElemInfo())

    _walk(root, element_info)

    # Determine which tags become tables: those that appear > 1 time
    # AND have child elements or attributes (not pure text-only leaves).
    table_tags: set[str] = set()
    for tag, info in element_info.items():
        if info.has_children or info.attributes:
            if info.count > 1 or info.has_children:
                table_tags.add(tag)

    # If nothing qualifies, treat the root's direct children as one table
    if not table_tags:
        table_tags.add(root.tag)

    tables: list[TableMetadata] = []
    seen_names: set[str] = set()

    for tag in sorted(table_tags):
        info = element_info[tag]
        columns: list[ColumnMetadata] = []
        primary_keys: list[str] = []
        fks: list[ForeignKeyMetadata] = []

        # Attributes → columns
        for attr_name, values in sorted(info.attributes.items()):
            col_name = _clean_name(attr_name)
            if not col_name:
                continue

            data_type = _infer_type(values)
            unique_vals = set(values)
            is_unique = len(unique_vals) == info.count and info.count > 1
            is_pk = is_unique and _looks_like_id(col_name)

            columns.append(
                ColumnMetadata(
                    name=col_name,
                    data_type=data_type,
                    nullable=len(values) < info.count,
                    is_primary_key=is_pk,
                    is_unique=is_unique and not is_pk,
                )
            )
            if is_pk:
                primary_keys.append(col_name)

        # Child text elements → columns
        for child_tag, values in sorted(info.child_texts.items()):
            col_name = _clean_name(child_tag)
            if not col_name:
                continue

            # If this child tag is itself a table, treat as FK
            if child_tag in table_tags and child_tag != tag:
                fks.append(
                    ForeignKeyMetadata(
                        column=f"{col_name}_id",
                        references_table=_clean_name(child_tag),
                        references_column="id",
                    )
                )
                columns.append(
                    ColumnMetadata(
                        name=f"{col_name}_id",
                        data_type="INTEGER",
                        nullable=True,
                    )
                )
                continue

            data_type = _infer_type(values)
            nullable = len(values) < info.count
            is_unique = (
                len(set(values)) == len(values)
                and len(values) == info.count
                and info.count > 1
            )
            is_pk = is_unique and _looks_like_id(col_name)

            columns.append(
                ColumnMetadata(
                    name=col_name,
                    data_type=data_type,
                    nullable=nullable,
                    is_primary_key=is_pk,
                    is_unique=is_unique and not is_pk,
                )
            )
            if is_pk:
                primary_keys.append(col_name)

        # Direct text content of the element itself
        if info.text_values:
            columns.append(
                ColumnMetadata(
                    name="value",
                    data_type=_infer_type(info.text_values),
                    nullable=len(info.text_values) < info.count,
                )
            )

        if not columns:
            continue

        tbl_name = _clean_name(tag) or default_table_name
        if tbl_name in seen_names:
            tbl_name = f"{tbl_name}_{len(seen_names)}"
        seen_names.add(tbl_name)

        tables.append(
            TableMetadata(
                name=tbl_name,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=fks,
            )
        )

    if not tables:
        raise XMLParserError("Could not extract any table structure from XML")

    logger.info(
        "XML parsed — %d table(s) extracted",
        len(tables),
        extra={"stage": "parsing", "event": "xml_parsed"},
    )

    return SchemaMetadata(tables=tables)


# ── Internal data structures ──────────────────────────────────


class _ElemInfo:
    """Accumulates info about elements with the same tag."""

    __slots__ = ("count", "attributes", "child_texts", "text_values", "has_children")

    def __init__(self):
        self.count: int = 0
        self.attributes: dict[str, list[str]] = defaultdict(list)
        self.child_texts: dict[str, list[str]] = defaultdict(list)
        self.text_values: list[str] = []
        self.has_children: bool = False


def _walk(elem: ET.Element, info: dict[str, _ElemInfo]) -> None:
    """Recursively walk XML tree and accumulate element info."""
    ei = info[elem.tag]
    ei.count += 1

    for attr, val in elem.attrib.items():
        ei.attributes[attr].append(val)

    if elem.text and elem.text.strip():
        ei.text_values.append(elem.text.strip())

    children = list(elem)
    if children:
        ei.has_children = True

    for child in children:
        # Child with text and no grandchildren → treat as column
        has_grandchildren = len(list(child)) > 0
        if child.text and child.text.strip() and not has_grandchildren:
            ei.child_texts[child.tag].append(child.text.strip())
        _walk(child, info)


# ── Helpers ───────────────────────────────────────────────────

_CLEAN_RE = re.compile(r"[^\w]+")

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_BOOL_RE = re.compile(r"^(?:true|false|yes|no)$", re.IGNORECASE)
_DATE_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$"
)

_ID_PATTERNS = re.compile(r"(?:^id$|^pk$|^key$|^uuid$)", re.IGNORECASE)


def _clean_name(raw: str) -> str:
    # Strip namespace prefix
    if "}" in raw:
        raw = raw.split("}", 1)[1]
    cleaned = _CLEAN_RE.sub("_", raw).strip("_").lower()
    return cleaned


def _infer_type(values: list[str]) -> str:
    if not values:
        return "VARCHAR"

    type_counts: Counter[str] = Counter()
    for v in values:
        if _INT_RE.match(v):
            type_counts["INTEGER"] += 1
        elif _FLOAT_RE.match(v):
            type_counts["DECIMAL"] += 1
        elif _BOOL_RE.match(v):
            type_counts["BOOLEAN"] += 1
        elif _DATE_RE.match(v):
            type_counts["TIMESTAMP" if ("T" in v or " " in v) else "DATE"] += 1
        else:
            type_counts["VARCHAR"] += 1

    if not type_counts:
        return "VARCHAR"

    dominant, count = type_counts.most_common(1)[0]
    if count / len(values) >= 0.8:
        return dominant
    return "VARCHAR"


def _looks_like_id(col_name: str) -> bool:
    return bool(_ID_PATTERNS.search(col_name))
