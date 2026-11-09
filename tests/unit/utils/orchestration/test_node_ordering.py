# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for node ordering utility functions.

Tests cover:
- Mapping a snapshot node order onto node_stats keys
- Topological ordering of node_stats with chronological fallback
"""

from types import SimpleNamespace

from docpipe.utils.orchestration.node_ordering import map_node_order_to_stats, order_node_items


class TestMapNodeOrderToStats:
    """Test map_node_order_to_stats helper."""

    def test_keeps_ids_maps_names_and_drops_unknown(self):
        """IDs present in node_stats pass through, operator names map to UUIDs, others are dropped."""
        node_stats = {
            "uuid-ingest": SimpleNamespace(name="Ingest"),
            "uuid-extract": {"name": "Extract"},
        }

        result = map_node_order_to_stats(node_order=["Ingest", "uuid-extract", "Missing"], node_stats=node_stats)

        assert result == ["uuid-ingest", "uuid-extract"]


class TestOrderNodeItems:
    """Test order_node_items helper."""

    def test_order_node_items_appends_unmatched_nodes_chronologically(self):
        """Unmatched extra nodes not in node_order are sorted chronologically and placed after matched nodes."""
        node_stats = {
            "extra-2": {"name": "ExtraLate", "start_time": 500, "end_time": 600},
            "node-1": {"name": "Node1", "start_time": 100, "end_time": 200},
            "extra-1": {"name": "ExtraEarly", "start_time": 300, "end_time": 400},
            "node-2": {"name": "Node2", "start_time": 200, "end_time": 300},
        }
        node_order = ["node-2", "node-1"]

        result = order_node_items(node_stats=node_stats, node_order=node_order)
        ordered_keys = [k for k, _ in result]
        assert ordered_keys == ["node-2", "node-1", "extra-1", "extra-2"]

    def test_order_node_items_empty_returns_empty(self):
        """Empty node_stats returns empty list."""
        assert order_node_items(node_stats={}) == []

    def test_order_node_items_no_node_order_falls_back_to_chronological(self):
        """When node_order is None, sorts all nodes chronologically."""
        node_stats = {
            "node-b": {"name": "NodeB", "start_time": 200, "end_time": 300},
            "node-a": {"name": "NodeA", "start_time": 100, "end_time": 200},
        }
        result = order_node_items(node_stats=node_stats, node_order=None)
        assert [k for k, _ in result] == ["node-a", "node-b"]

    def test_order_node_items_fallback_places_completed_before_running_before_pending(self):
        """When node_order is None, sorts completed -> running -> pending chronologically."""
        node_stats = {
            "pending-node": {"name": "Pending", "start_time": 0, "end_time": 0},
            "running-node": {"name": "Running", "start_time": 150, "end_time": 0},
            "completed-node": {"name": "Completed", "start_time": 100, "end_time": 200},
        }
        result = order_node_items(node_stats=node_stats, node_order=None)
        assert [k for k, _ in result] == ["completed-node", "running-node", "pending-node"]

    def test_order_node_items_fallback_with_objects(self):
        """Objects with start_time=0 sort after executed nodes."""
        node_stats = {
            "pending": SimpleNamespace(name="Pending", start_time=0, end_time=0),
            "completed": SimpleNamespace(name="Completed", start_time=100, end_time=120),
        }
        result = order_node_items(node_stats=node_stats, node_order=None)
        assert [k for k, _ in result] == ["completed", "pending"]
