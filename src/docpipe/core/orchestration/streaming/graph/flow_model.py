# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Data model for a flow graph: nodes, edges and adjacency lookups."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class Edge:
    """Directed connection from one operator to the next."""

    source_id: UUID
    target_id: UUID
    branch_id: str | None = None


@dataclass
class Node:
    """Graph node representing a single operator invocation and its configuration."""

    id: UUID
    name: str
    operator_name: str
    operator_config: dict[str, Any]


@dataclass
class FlowGraph:
    """Graph whose nodes may have multiple incoming and outgoing edges."""

    nodes: dict[UUID, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _in_edges: dict[UUID, list[Edge]] = field(default_factory=dict, init=False, repr=False)
    _out_edges: dict[UUID, list[Edge]] = field(default_factory=dict, init=False, repr=False)

    def add_node(self, node: Node) -> None:
        """Register a node and initialize its adjacency lists."""
        self.nodes[node.id] = node
        self._in_edges.setdefault(node.id, [])
        self._out_edges.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        """Connect two existing nodes."""
        self.edges.append(edge)
        self._out_edges.setdefault(edge.source_id, []).append(edge)
        self._in_edges.setdefault(edge.target_id, []).append(edge)

    def get_input_edges(self, node_id: UUID) -> list[Edge]:
        """Return the edges flowing into ``node_id``."""
        return self._in_edges[node_id]

    def get_output_edges(self, node_id: UUID) -> list[Edge]:
        """Return the edges flowing out of ``node_id``."""
        return self._out_edges[node_id]
