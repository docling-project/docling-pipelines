# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Node Ordering Utilities

Order node stats entries for job stats responses and exported job logs.

These helpers depend only on node_stats and constants. Keep it that way: unlike
``dag_utils`` (which imports the Elyra converter and, through it, the operator
and job management packages), this module can be imported at module level from
``job_management`` without creating an import cycle.
"""

from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants


def _resolve_node_name(ns: Any) -> str | None:
    """Return the operator name from a node-stats entry (object or dict)."""
    if hasattr(ns, OperatorConstants.Misc.NAME):
        return ns.name
    if isinstance(ns, dict):
        return ns.get(OperatorConstants.Misc.NAME)
    return None


def build_name_to_uuid(node_stats: dict[str, Any]) -> dict[str, str]:
    """Map operator name -> UUID from node_stats."""
    name_to_uuid: dict[str, str] = {}
    for node_id, ns in node_stats.items():
        name = _resolve_node_name(ns)
        if name:
            name_to_uuid[name] = node_id
    return name_to_uuid


def map_node_order_to_stats(*, node_order: list[str], node_stats: dict[str, Any]) -> list[str]:
    """Map a snapshot node order onto node_stats keys.

    Node IDs present in node_stats are kept as-is; authoring operator names are
    translated to their node UUIDs. Entries matching neither are dropped.
    """
    name_to_uuid = build_name_to_uuid(node_stats)
    mapped: list[str] = []
    for key in node_order:
        if key in node_stats:
            mapped.append(key)
        elif key in name_to_uuid:
            mapped.append(name_to_uuid[key])
    return mapped


def get_node_sort_key(node_item: tuple[str, Any]) -> tuple[int, int, int, int, str]:
    """Generate a sort key to order nodes chronologically, placing completed/running first and pending last."""
    _, stats = node_item
    start_time = (stats.get("start_time") or 0) if isinstance(stats, dict) else (getattr(stats, "start_time", 0) or 0)
    end_time = (stats.get("end_time") or 0) if isinstance(stats, dict) else (getattr(stats, "end_time", 0) or 0)
    name = (stats.get("name") or "") if isinstance(stats, dict) else (getattr(stats, "name", "") or "")
    is_pending = 1 if start_time == 0 else 0
    is_running = 1 if end_time == 0 else 0
    return (is_pending, int(start_time), is_running, int(end_time), str(name))


def order_node_items(
    *,
    node_stats: dict[str, Any],
    node_order: list[str] | None = None,
) -> list[tuple[str, Any]]:
    """Order node items by provided topological node_order, falling back to chronological sort.

    Unmatched/extra nodes not in node_order are sorted chronologically and appended to the end.
    """
    if not node_stats:
        return []

    if node_order:
        ordered_items: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for node_id in node_order:
            if node_id in node_stats and node_id not in seen:
                ordered_items.append((node_id, node_stats[node_id]))
                seen.add(node_id)
        # Append any node_stats entries not present in node_order sorted chronologically
        remaining_items = [(node_id, stats) for node_id, stats in node_stats.items() if node_id not in seen]
        if remaining_items:
            remaining_items.sort(key=get_node_sort_key)
            ordered_items.extend(remaining_items)
        return ordered_items

    return sorted(node_stats.items(), key=get_node_sort_key)
