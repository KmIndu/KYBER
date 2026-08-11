"""SQL DDL parser — extracts normalized schema metadata from CREATE TABLE statements.

Uses ``sqlglot`` for AST-based parsing.  Handles inline and table-level
constraints: PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, NOT NULL, DEFAULT.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

from app.models.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaMetadata,
    TableMetadata,
)

logger = logging.getLogger(__name__)


class SQLParserError(Exception):
    """Raised when SQL parsing fails."""


def parse_sql_schema(sql: str) -> SchemaMetadata:
    """Parse SQL DDL and return normalized schema metadata.

    Supports CREATE TABLE statements with:
    - column definitions (name, type, nullable, default)
    - inline PRIMARY KEY / UNIQUE / CHECK / NOT NULL
    - table-level PRIMARY KEY, UNIQUE, FOREIGN KEY, CHECK constraints
    """
    try:
        statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.WARN)
    except sqlglot.errors.ParseError as e:
        logger.error(
            "Malformed SQL — parse failed: %s",
            e,
            extra={"stage": "parsing", "event": "sql_parse_error", "error_type": "SQLParserError"},
        )
        raise SQLParserError(f"Failed to parse SQL: {e}") from e

    tables: list[TableMetadata] = []

    for statement in statements:
        if statement is None:
            continue
        if not isinstance(statement, exp.Create):
            continue

        table_expr = statement.find(exp.Table)
        if table_expr is None:
            continue

        table_name = table_expr.name
        columns: list[ColumnMetadata] = []
        primary_keys: list[str] = []
        foreign_keys: list[ForeignKeyMetadata] = []
        unique_constraints: list[list[str]] = []
        check_constraints: list[str] = []

        schema_node = statement.find(exp.Schema)
        if schema_node is None:
            continue

        # --- Process column definitions ---
        for col_def in schema_node.find_all(exp.ColumnDef):
            col_name = col_def.name
            col_type = _extract_column_type(col_def)
            nullable = True
            default_value: str | None = None
            is_pk = False
            is_unique = False
            col_check: str | None = None

            for constraint in col_def.find_all(exp.ColumnConstraint):
                kind = constraint.find(exp.ColumnConstraintKind)
                if kind is None:
                    # Check direct children for constraint kinds
                    for child in constraint.args.values():
                        if isinstance(child, exp.ColumnConstraintKind):
                            kind = child
                            break

                if kind is None:
                    continue

                if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                    is_pk = True
                    if col_name not in primary_keys:
                        primary_keys.append(col_name)
                elif isinstance(kind, exp.NotNullColumnConstraint):
                    nullable = False
                elif isinstance(kind, exp.UniqueColumnConstraint):
                    is_unique = True
                elif isinstance(kind, exp.DefaultColumnConstraint):
                    default_value = _expression_to_str(kind.this)
                elif isinstance(kind, exp.CheckColumnConstraint):
                    col_check = _expression_to_str(kind.this)
                    check_constraints.append(f"{col_name}: {col_check}")

            columns.append(
                ColumnMetadata(
                    name=col_name,
                    data_type=col_type,
                    nullable=nullable,
                    default=default_value,
                    is_primary_key=is_pk,
                    is_unique=is_unique,
                    check_constraint=col_check,
                )
            )

        # --- Process table-level constraints ---
        for pk in schema_node.find_all(exp.PrimaryKey):
            pk_cols = _extract_identifier_names(pk)
            for col_name in pk_cols:
                if col_name not in primary_keys:
                    primary_keys.append(col_name)
            # Mark columns
            for col in columns:
                if col.name in primary_keys:
                    col.is_primary_key = True

        for fk in schema_node.find_all(exp.ForeignKey):
            fk_cols = _extract_identifier_names(fk)
            ref = fk.find(exp.Reference)
            if ref is not None:
                ref_schema = ref.find(exp.Schema)
                ref_table_expr = ref.find(exp.Table)
                if ref_table_expr:
                    ref_table_name = ref_table_expr.name
                    ref_cols = (
                        _extract_identifier_names(ref_schema)
                        if ref_schema
                        else []
                    )
                    for src_col, ref_col in zip(fk_cols, ref_cols):
                        foreign_keys.append(
                            ForeignKeyMetadata(
                                column=src_col,
                                references_table=ref_table_name,
                                references_column=ref_col,
                            )
                        )

        for unique in schema_node.find_all(exp.UniqueColumnConstraint):
            parent = unique.parent
            if isinstance(parent, exp.ColumnConstraint) and isinstance(
                parent.parent, exp.ColumnDef
            ):
                continue  # Already handled inline
            unique_cols = _extract_identifier_names(unique)
            if unique_cols:
                unique_constraints.append(unique_cols)
                for col in columns:
                    if col.name in unique_cols and len(unique_cols) == 1:
                        col.is_unique = True

        for check in schema_node.find_all(exp.CheckColumnConstraint):
            parent = check.parent
            if isinstance(parent, exp.ColumnConstraint) and isinstance(
                parent.parent, exp.ColumnDef
            ):
                continue  # Already handled inline
            check_sql = _expression_to_str(check.this)
            check_constraints.append(check_sql)

        tables.append(
            TableMetadata(
                name=table_name,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=foreign_keys,
                unique_constraints=unique_constraints,
                check_constraints=check_constraints,
            )
        )

    if not tables:
        logger.warning(
            "No CREATE TABLE statements found in input SQL",
            extra={"stage": "parsing", "event": "sql_no_tables"},
        )
    else:
        logger.info(
            "SQL parser extracted %d tables",
            len(tables),
            extra={"stage": "parsing", "event": "sql_tables_extracted"},
        )

    return SchemaMetadata(tables=tables)


def _extract_column_type(col_def: exp.ColumnDef) -> str:
    """Extract the data type string from a column definition."""
    dtype = col_def.find(exp.DataType)
    if dtype is None:
        return "UNKNOWN"
    return dtype.sql()


def _expression_to_str(node: exp.Expression | None) -> str:
    """Safely convert an AST node to its SQL string."""
    if node is None:
        return ""
    return node.sql()


def _extract_identifier_names(node: exp.Expression) -> list[str]:
    """Extract direct Identifier children names from a constraint node."""
    names: list[str] = []
    for ident in node.find_all(exp.Identifier):
        # Skip identifiers that belong to tables or nested schemas
        parent = ident.parent
        if isinstance(parent, exp.Table):
            continue
        if isinstance(parent, exp.Column):
            names.append(ident.name)
            continue
        # Direct identifiers in PK/FK/UNIQUE expressions
        names.append(ident.name)
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result
