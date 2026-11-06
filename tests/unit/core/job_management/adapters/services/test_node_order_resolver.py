# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for NodeOrderResolver.

Covers:
- Per-job-run caching of the snapshot node order
- Mapping the cached order onto node_stats that grow over a run
- Which outcomes are cached (missing snapshot and storage errors are not)
- LRU eviction and the INFO line logged on each sort
"""

from unittest.mock import Mock, patch

from docpipe.core.job_management.adapters.services import node_order_resolver as resolver_module
from docpipe.core.job_management.adapters.services.node_order_resolver import NodeOrderResolver
from docpipe.core.job_management.domain.models.node_stats import NodeStats

JOB_RUN_ID = "87654321-4321-4321-4321-210987654321"

LINEAR_FLOW_DEF = {
    "dag": [
        {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
        {"id": "b", "output_edges": [{"node_id_ref": "c"}]},
        {"id": "c", "output_edges": []},
    ]
}


class TestNodeOrderResolverCache:
    """Caching behavior of NodeOrderResolver.resolve."""

    def test_snapshot_read_once_per_job_run(self):
        """Repeated calls for the same job run load the snapshot only once."""
        loader = Mock(return_value=LINEAR_FLOW_DEF)
        resolver = NodeOrderResolver(load_flow_definition=loader)

        first = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}, "b": {}})
        second = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}, "b": {}})

        assert first == second == ["a", "b"]
        loader.assert_called_once_with(JOB_RUN_ID)

    def test_nodes_starting_after_first_call_keep_dag_order(self):
        """The unfiltered order is cached, so nodes that gain stats later are still placed by the DAG."""
        resolver = NodeOrderResolver(load_flow_definition=Mock(return_value=LINEAR_FLOW_DEF))

        early = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})
        later = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"c": {}, "a": {}, "b": {}})

        assert early == ["a"]
        assert later == ["a", "b", "c"]

    def test_missing_snapshot_is_not_cached(self):
        """A snapshot not yet saved (None) is retried on the next call."""
        loader = Mock(side_effect=[None, LINEAR_FLOW_DEF])
        resolver = NodeOrderResolver(load_flow_definition=loader)

        first = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})
        second = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})

        assert first is None
        assert second == ["a"]
        assert loader.call_count == 2

    def test_storage_error_is_not_cached(self):
        """A failing snapshot read returns None and is retried on the next call."""
        loader = Mock(side_effect=[RuntimeError("Store connection failed"), LINEAR_FLOW_DEF])
        resolver = NodeOrderResolver(load_flow_definition=loader)

        first = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})
        second = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})

        assert first is None
        assert second == ["a"]
        assert loader.call_count == 2

    def test_unparseable_snapshot_is_cached_as_empty_order(self):
        """A snapshot that yields no order is cached, so it is not re-read and re-warned every call."""
        loader = Mock(return_value={"unknown": "shape"})
        resolver = NodeOrderResolver(load_flow_definition=loader)

        first = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})
        second = resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}})

        assert first == second == []
        loader.assert_called_once()

    def test_cache_evicts_least_recently_used_job_run(self):
        """The cache is bounded; the least recently used job run is evicted and reloaded on demand."""
        loader = Mock(return_value=LINEAR_FLOW_DEF)
        resolver = NodeOrderResolver(load_flow_definition=loader, cache_size=2)

        for run_id in ("run-1", "run-2", "run-1", "run-3", "run-1", "run-2"):
            resolver.resolve(job_run_id=run_id, node_stats={"a": {}})

        # run-1 stays hot; run-2 is evicted by run-3 and loaded again
        assert [c.args[0] for c in loader.call_args_list] == ["run-1", "run-2", "run-3", "run-2"]


class TestNodeOrderResolverMapping:
    """Mapping and input handling of NodeOrderResolver.resolve."""

    def test_no_job_run_id_returns_none_without_loading(self):
        """Without a job_run_id there is no snapshot to load."""
        loader = Mock()
        resolver = NodeOrderResolver(load_flow_definition=loader)

        assert resolver.resolve(job_run_id=None, node_stats={"a": {}}) is None
        loader.assert_not_called()

    def test_authoring_names_mapped_to_current_node_stats(self):
        """Authoring snapshots cache operator names and map them to node UUIDs on each call."""
        flow_def = {
            "flow": [
                {"name": "Ingest", "depends_on": []},
                {"name": "Extract", "depends_on": ["Ingest"]},
            ]
        }
        node_stats = {
            "uuid-extract": NodeStats(id="uuid-extract", name="Extract", start_time=101),
            "uuid-ingest": NodeStats(id="uuid-ingest", name="Ingest", start_time=101),
        }
        resolver = NodeOrderResolver(load_flow_definition=Mock(return_value=flow_def))

        assert resolver.resolve(job_run_id=JOB_RUN_ID, node_stats=node_stats) == ["uuid-ingest", "uuid-extract"]


class TestNodeOrderResolverLogging:
    """The INFO line logged when a snapshot is sorted."""

    def test_logs_once_per_sort_with_run_and_flow_context(self):
        """A sort logs job run, flow and cache occupancy; a cache hit logs nothing."""
        resolver = NodeOrderResolver(load_flow_definition=Mock(return_value=LINEAR_FLOW_DEF), cache_size=8)

        with patch.object(resolver_module.logger, "info") as info:
            for _ in range(2):
                resolver.resolve(job_run_id=JOB_RUN_ID, node_stats={"a": {}}, flow_id="flow-1", flow_name="my-flow")

        info.assert_called_once()
        assert info.call_args.args[1:] == (JOB_RUN_ID, "flow-1", "my-flow", 3, 1, 8)
