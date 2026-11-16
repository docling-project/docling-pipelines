# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
NodeOrderResolver - topological node order for a job run, from its flow snapshot

Used by JobTrackerService to order node_stats in status responses and exported
job logs. Owns the per-job-run cache of the snapshot order.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from logging import Logger
from typing import Any

from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.node_ordering import map_node_order_to_stats

logger: Logger = get_logger()

# Default max job runs whose snapshot node order is kept in memory per resolver
NODE_ORDER_CACHE_SIZE = 256

FlowDefinitionLoader = Callable[[str], dict[str, Any] | None]


class NodeOrderResolver:
    """
    Resolve the topological node order of a job run from its flow snapshot.

    A job run's flow snapshot is written once and never changes, so the order
    derived from it is cached per job_run_id (LRU-bounded). The cached order is
    unfiltered and mapped onto the current node_stats on every call, because
    node_stats grows as nodes start. A missing snapshot is not cached (it is
    saved after flow validation, so early polls of a run see None), and storage
    errors are not cached either.
    """

    def __init__(self, *, load_flow_definition: FlowDefinitionLoader, cache_size: int = NODE_ORDER_CACHE_SIZE):
        """
        Initialize NodeOrderResolver.

        Args:
            load_flow_definition: Returns the flow snapshot for a job_run_id, or None if not saved yet
            cache_size: Max job runs whose snapshot order is kept in memory
        """
        self._load_flow_definition = load_flow_definition
        self._cache_size = cache_size
        self._cache: OrderedDict[str, list[str]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def resolve(
        self,
        *,
        job_run_id: str | None,
        node_stats: dict[str, Any] | None = None,
        flow_id: str | None = None,
        flow_name: str | None = None,
    ) -> list[str] | None:
        """
        Return node_stats keys in topological order, or None to fall back to chronological order.

        Args:
            job_run_id: Job run whose flow snapshot defines the order
            node_stats: Current node stats keyed by node_id; None returns the unmapped snapshot order
            flow_id: Flow identifier, used only for logging
            flow_name: Flow name, used only for logging
        """
        if not job_run_id:
            return None
        try:
            snapshot_order = self._get_snapshot_order(job_run_id=job_run_id, flow_id=flow_id, flow_name=flow_name)
            if snapshot_order is None:
                return None
            if node_stats is None:
                return snapshot_order
            return map_node_order_to_stats(node_order=snapshot_order, node_stats=node_stats)
        except Exception as e:
            logger.warning(
                "Failed to determine topological node order for job_run_id %s: %s",
                job_run_id,
                e,
                exc_info=True,
            )
        return None

    def _get_snapshot_order(self, *, job_run_id: str, flow_id: str | None, flow_name: str | None) -> list[str] | None:
        """Return the unfiltered snapshot node order for a job run, sorting it on a cache miss."""
        with self._cache_lock:
            cached = self._cache.get(job_run_id)
            if cached is not None:
                self._cache.move_to_end(job_run_id)
                return cached

        flow_def = self._load_flow_definition(job_run_id)
        if not flow_def:
            return None

        # Local import to prevent circular import: dag_utils -> elyra_converter -> abstract_operator
        # -> operator_utils -> job_management. The node_stats-only helpers live in node_ordering instead.
        from docpipe.utils.orchestration.dag_utils import get_topologically_sorted_node_ids

        snapshot_order = get_topologically_sorted_node_ids(flow_definition=flow_def)
        with self._cache_lock:
            self._cache[job_run_id] = snapshot_order
            self._cache.move_to_end(job_run_id)
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            cached_runs = len(self._cache)

        # One line per sort: repeated lines for the same job_run_id mean the cache is too small
        logger.info(
            "Sorted flow snapshot node order for job_run_id=%s flow_id=%s flow_name=%s nodes=%d cached_runs=%d/%d",
            job_run_id,
            flow_id,
            flow_name,
            len(snapshot_order),
            cached_runs,
            self._cache_size,
        )
        return snapshot_order
