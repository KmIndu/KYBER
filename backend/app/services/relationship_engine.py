"""Foreign-key relationship graph builder.

Constructs a directed dependency graph from foreign-key constraints so
that tables can be populated in topological (parent-first) order.
"""

from __future__ import annotations

import logging

import networkx as nx

from app.models.schema import SchemaMetadata

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when the schema contains circular foreign key dependencies."""


class RelationshipGraphError(Exception):
    """Raised when graph construction fails."""


class RelationshipGraph:
    """Builds and queries a dependency graph from parsed schema metadata."""

    def __init__(self, schema: SchemaMetadata) -> None:
        self._schema = schema
        self._graph = nx.DiGraph()
        self._build()

    # ── Construction ──────────────────────────────────────────

    def _build(self) -> None:
        table_names = {t.name for t in self._schema.tables}

        # Add every table as a node
        for table in self._schema.tables:
            self._graph.add_node(table.name)

        # Add FK edges: child → parent  (child depends on parent)
        for table in self._schema.tables:
            for fk in table.foreign_keys:
                parent = fk.references_table
                if parent not in table_names:
                    logger.warning(
                        "FK in %s references unknown table %s — skipping edge",
                        table.name,
                        parent,
                    )
                    continue
                # Edge direction: child → parent means "child depends on parent"
                self._graph.add_edge(
                    table.name,
                    parent,
                    column=fk.column,
                    references_column=fk.references_column,
                )

    # ── Queries ───────────────────────────────────────────────

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    def has_circular_dependencies(self) -> bool:
        try:
            nx.find_cycle(self._graph)
            return True
        except nx.NetworkXNoCycle:
            return False

    def get_circular_dependencies(self) -> list[list[str]]:
        """Return all simple cycles in the graph."""
        return list(nx.simple_cycles(self._graph))

    def get_generation_order(self) -> list[str]:
        """Return tables in safe generation order (parents before children).

        Since edges point child → parent, a topological sort gives
        children first. We reverse to get parents first.
        """
        if self.has_circular_dependencies():
            cycles = self.get_circular_dependencies()
            raise CircularDependencyError(
                f"Cannot determine generation order — circular dependencies detected: {cycles}"
            )
        return list(reversed(list(nx.topological_sort(self._graph))))

    def get_parent_tables(self, table_name: str) -> list[str]:
        """Return tables that the given table depends on (FK targets)."""
        if table_name not in self._graph:
            return []
        return list(self._graph.successors(table_name))

    def get_child_tables(self, table_name: str) -> list[str]:
        """Return tables that depend on the given table."""
        if table_name not in self._graph:
            return []
        return list(self._graph.predecessors(table_name))

    def get_root_tables(self) -> list[str]:
        """Return tables with no foreign key dependencies (no outgoing edges)."""
        return [n for n in self._graph.nodes if self._graph.out_degree(n) == 0]

    def get_leaf_tables(self) -> list[str]:
        """Return tables that no other table depends on (no incoming edges)."""
        return [n for n in self._graph.nodes if self._graph.in_degree(n) == 0]

    def get_edge_details(self) -> list[dict[str, str]]:
        """Return all FK relationships as a list of dicts."""
        edges = []
        for child, parent, data in self._graph.edges(data=True):
            edges.append({
                "child_table": child,
                "parent_table": parent,
                "child_column": data.get("column", ""),
                "parent_column": data.get("references_column", ""),
            })
        return edges

    # ── Validation ────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Run validation checks and return a list of issues (empty = valid)."""
        issues: list[str] = []

        # Check for circular deps
        cycles = self.get_circular_dependencies()
        for cycle in cycles:
            issues.append(f"Circular dependency: {' → '.join(cycle + [cycle[0]])}")

        # Check for self-referencing tables
        for node in self._graph.nodes:
            if self._graph.has_edge(node, node):
                issues.append(f"Self-referencing FK in table: {node}")

        # Check for isolated tables (no relationships at all)
        for node in self._graph.nodes:
            if self._graph.degree(node) == 0:
                issues.append(f"Isolated table (no relationships): {node}")

        return issues

    # ── Visualization ─────────────────────────────────────────

    def to_ascii(self) -> str:
        """Return a simple ASCII representation of the dependency graph."""
        if not self._graph.nodes:
            return "(empty graph)"

        try:
            order = self.get_generation_order()
        except CircularDependencyError:
            order = list(self._graph.nodes)

        lines: list[str] = []
        for table in order:
            children = self.get_child_tables(table)
            parents = self.get_parent_tables(table)
            parts = [table]
            if parents:
                parts.append(f"→ depends on: {', '.join(parents)}")
            if children:
                parts.append(f"← depended by: {', '.join(children)}")
            lines.append("  ".join(parts))

        return "\n".join(lines)

    def to_adjacency_dict(self) -> dict[str, list[str]]:
        """Return {table: [parent_tables]} dict for JSON serialization."""
        return {
            node: list(self._graph.successors(node))
            for node in self._graph.nodes
        }
