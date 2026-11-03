# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for JobStatsMapper — chronological sorting of node_stats.

Covers:
- to_dto(): node_stats dict keys are in start_time order
- to_dto(): tie-breaking by end_time then name
- to_dto(): single-node and empty node_stats cases
- to_status_response(): node_sequence list matches chronological order
- to_status_response(): node_metadata array order matches node_sequence
"""

from docpipe.api.dto.mappers.job_stats_mapper import JobStatsMapper
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats

JOB_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
JOB_RUN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# 36-char node IDs — must match ^[0-9a-f]{8}-...-[0-9a-f]{12}$
NODE_A = "aaaaaaaa-0000-0000-0000-000000000001"
NODE_B = "bbbbbbbb-0000-0000-0000-000000000001"
NODE_C = "cccccccc-0000-0000-0000-000000000001"
NODE_X = "dddddddd-0000-0000-0000-000000000001"
NODE_Z = "eeeeeeee-0000-0000-0000-000000000001"
NODE_1 = "11111111-0000-0000-0000-000000000001"
NODE_2 = "22222222-0000-0000-0000-000000000001"


def _make_node(node_id: str, name: str, start_time: int, end_time: int = 0) -> NodeStats:
    return NodeStats(id=node_id, name=name, start_time=start_time, end_time=end_time)


def _make_job_stats(node_stats: dict[str, NodeStats]) -> JobStats:
    return JobStats(
        job_id=JOB_ID,
        job_run_id=JOB_RUN_ID,
        status=ExecutionStatus.COMPLETED,
        node_stats=node_stats,
    )


class TestJobStatsMapperToDto:
    """Tests for JobStatsMapper.to_dto() chronological ordering."""

    def test_node_stats_sorted_by_start_time(self):
        """to_dto() returns node_stats keys in ascending start_time order."""
        # nodes intentionally inserted in reverse order
        node_stats = {
            NODE_C: _make_node(NODE_C, "NodeC", start_time=300),
            NODE_A: _make_node(NODE_A, "NodeA", start_time=100),
            NODE_B: _make_node(NODE_B, "NodeB", start_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        assert list(dto.node_stats.keys()) == [NODE_A, NODE_B, NODE_C]

    def test_node_stats_sorted_tiebreak_by_end_time(self):
        """When start_times are equal, nodes are sorted by end_time."""
        node_stats = {
            NODE_B: _make_node(NODE_B, "NodeB", start_time=100, end_time=300),
            NODE_A: _make_node(NODE_A, "NodeA", start_time=100, end_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        assert list(dto.node_stats.keys()) == [NODE_A, NODE_B]

    def test_node_stats_sorted_tiebreak_by_name(self):
        """When start_time and end_time are equal, nodes are sorted alphabetically by name."""
        # "Apple" < "Zebra" so Apple-node must appear first regardless of dict insertion order
        node_stats = {
            NODE_Z: _make_node(NODE_Z, "Zebra", start_time=100, end_time=200),
            NODE_A: _make_node(NODE_A, "Apple", start_time=100, end_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        keys = list(dto.node_stats.keys())
        apple_idx = keys.index(NODE_A)
        zebra_idx = keys.index(NODE_Z)
        assert apple_idx < zebra_idx

    def test_node_stats_sorted_completed_running_pending(self):
        """Completed nodes come first, running nodes second, pending nodes (start_time=0) last."""
        node_stats = {
            NODE_C: _make_node(NODE_C, "PendingNode", start_time=0, end_time=0),
            NODE_B: _make_node(NODE_B, "RunningNode", start_time=150, end_time=0),
            NODE_A: _make_node(NODE_A, "CompletedNode", start_time=100, end_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        assert list(dto.node_stats.keys()) == [NODE_A, NODE_B, NODE_C]

    def test_single_node_returns_unchanged(self):
        """to_dto() with a single node returns that single entry."""
        node_stats = {NODE_X: _make_node(NODE_X, "OnlyNode", start_time=500)}
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        assert NODE_X in dto.node_stats
        assert len(dto.node_stats) == 1

    def test_empty_node_stats_returns_empty(self):
        """to_dto() with no nodes returns an empty node_stats dict."""
        job_stats = _make_job_stats({})

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.node_stats == {}

    def test_scalar_fields_preserved(self):
        """to_dto() does not alter top-level scalar fields."""
        job_stats = _make_job_stats({})
        job_stats.total_docs = 42
        job_stats.completed_docs = 40
        job_stats.failed_docs = 2
        job_stats.heartbeat_timestamp = 1704067260
        job_stats.progress_timestamp = 1704067200

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.job_id == JOB_ID
        assert dto.job_run_id == JOB_RUN_ID
        assert dto.total_docs == 42
        assert dto.completed_docs == 40
        assert dto.failed_docs == 2
        assert dto.heartbeat_timestamp == 1704067260
        assert dto.progress_timestamp == 1704067200

    def test_node_stats_values_mapped_correctly(self):
        """Each mapped NodeStatsDto retains the correct node_id and name."""
        node_stats = {
            NODE_2: _make_node(NODE_2, "Second", start_time=200),
            NODE_1: _make_node(NODE_1, "First", start_time=100),
        }
        job_stats = _make_job_stats(node_stats)

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.node_stats[NODE_1].id == NODE_1
        assert dto.node_stats[NODE_1].name == "First"
        assert dto.node_stats[NODE_2].id == NODE_2
        assert dto.node_stats[NODE_2].name == "Second"


class TestJobStatsMapperToStatusResponse:
    """Tests for JobStatsMapper.to_status_response() ordering."""

    def test_node_sequence_is_chronological(self):
        """to_status_response() returns node_sequence in ascending start_time order."""
        node_stats = {
            NODE_C: _make_node(NODE_C, "NodeC", start_time=300),
            NODE_A: _make_node(NODE_A, "NodeA", start_time=100),
            NODE_B: _make_node(NODE_B, "NodeB", start_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        response = JobStatsMapper.to_status_response(job_stats)

        assert response.node_sequence == [NODE_A, NODE_B, NODE_C]

    def test_node_sequence_fallback_places_completed_before_running_before_pending(self):
        """to_status_response() with no node_order fallback places completed -> running -> pending."""
        node_stats = {
            NODE_C: _make_node(NODE_C, "PendingNode", start_time=0, end_time=0),
            NODE_B: _make_node(NODE_B, "RunningNode", start_time=150, end_time=0),
            NODE_A: _make_node(NODE_A, "CompletedNode", start_time=100, end_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        response = JobStatsMapper.to_status_response(job_stats)

        assert response.node_sequence == [NODE_A, NODE_B, NODE_C]

    def test_node_metadata_order_matches_node_sequence(self):
        """node_metadata array is in the same order as node_sequence."""
        node_stats = {
            NODE_C: _make_node(NODE_C, "NodeC", start_time=300),
            NODE_A: _make_node(NODE_A, "NodeA", start_time=100),
            NODE_B: _make_node(NODE_B, "NodeB", start_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        response = JobStatsMapper.to_status_response(job_stats)

        metadata_ids = [item.id for item in response.node_metadata]
        assert metadata_ids == response.node_sequence

    def test_node_metadata_operator_names_match_node_names(self):
        """Each node_metadata item carries the correct operator name."""
        node_stats = {
            NODE_B: _make_node(NODE_B, "Chunker", start_time=200),
            NODE_A: _make_node(NODE_A, "Ingest", start_time=100),
        }
        job_stats = _make_job_stats(node_stats)

        response = JobStatsMapper.to_status_response(job_stats)

        assert response.node_metadata[0].operator == "Ingest"
        assert response.node_metadata[1].operator == "Chunker"

    def test_node_sequence_empty_when_no_nodes(self):
        """to_status_response() returns empty node_sequence for no nodes."""
        job_stats = _make_job_stats({})

        response = JobStatsMapper.to_status_response(job_stats)

        assert response.node_sequence == []
        assert response.node_metadata == []

    def test_job_stats_dto_inside_response_also_sorted(self):
        """The embedded job_stats DTO inside the response has sorted node_stats."""
        node_stats = {
            NODE_C: _make_node(NODE_C, "NodeC", start_time=300),
            NODE_A: _make_node(NODE_A, "NodeA", start_time=100),
            NODE_B: _make_node(NODE_B, "NodeB", start_time=200),
        }
        job_stats = _make_job_stats(node_stats)

        response = JobStatsMapper.to_status_response(job_stats)

        assert list(response.job_stats.node_stats.keys()) == [NODE_A, NODE_B, NODE_C]

    def test_node_sequence_respects_topological_node_order(self):
        """to_status_response() uses node_order when provided, overriding same-second timestamps."""
        # Reproducing issue #527: downstream nodes skipped at the same second
        # Alphabetical sort would place Extract Content ('Ex') after Embeddings ('Em')
        node_ingest = "11111111-0000-0000-0000-000000000001"
        node_extract = "22222222-0000-0000-0000-000000000002"
        node_quality = "33333333-0000-0000-0000-000000000003"
        node_chunk = "44444444-0000-0000-0000-000000000004"
        node_embed = "55555555-0000-0000-0000-000000000005"

        node_stats = {
            node_ingest: _make_node(node_ingest, "Ingest data", start_time=100, end_time=101),
            node_chunk: _make_node(node_chunk, "Chunking", start_time=101, end_time=101),
            node_quality: _make_node(node_quality, "Document Quality", start_time=101, end_time=101),
            node_embed: _make_node(node_embed, "Embeddings", start_time=101, end_time=101),
            node_extract: _make_node(node_extract, "Extract Content", start_time=101, end_time=101),
        }
        job_stats = _make_job_stats(node_stats)
        topological_order = [node_ingest, node_extract, node_quality, node_chunk, node_embed]

        response = JobStatsMapper.to_status_response(job_stats, node_order=topological_order)

        assert response.node_sequence == topological_order
        assert [m.id for m in response.node_metadata] == topological_order
        assert list(response.job_stats.node_stats.keys()) == topological_order

    def test_node_sequence_appends_unmapped_nodes_at_end(self):
        """Nodes not present in topological node_order are appended at the end sorted chronologically."""
        node_1 = "11111111-0000-0000-0000-000000000001"
        node_2 = "22222222-0000-0000-0000-000000000002"
        node_extra = "33333333-0000-0000-0000-000000000003"

        node_stats = {
            node_1: _make_node(node_1, "Node1", start_time=100),
            node_2: _make_node(node_2, "Node2", start_time=100),
            node_extra: _make_node(node_extra, "ExtraNode", start_time=105),
        }
        job_stats = _make_job_stats(node_stats)
        topological_order = [node_1, node_2]

        response = JobStatsMapper.to_status_response(job_stats, node_order=topological_order)

        assert response.node_sequence == [node_1, node_2, node_extra]


class TestJobStatsMapperReportFields:
    """Report status fields are passed through to_dto()."""

    def test_report_fields_are_none_by_default(self):
        """When domain model has no report fields set, DTO fields are None."""
        job_stats = _make_job_stats({})

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.report_status is None
        assert dto.report_generation_started_at is None
        assert dto.report_generation_completed_at is None

    def test_report_status_generating_mapped(self):
        """GENERATING status and started_at timestamp are preserved in the DTO."""
        job_stats = _make_job_stats({})
        job_stats.report_status = "GENERATING"
        job_stats.report_generation_started_at = 1704067200

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.report_status == "GENERATING"
        assert dto.report_generation_started_at == 1704067200
        assert dto.report_generation_completed_at is None

    def test_report_status_completed_mapped(self):
        """COMPLETED status with both timestamps is preserved."""
        job_stats = _make_job_stats({})
        job_stats.report_status = "COMPLETED"
        job_stats.report_generation_started_at = 1704067200
        job_stats.report_generation_completed_at = 1704067260

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.report_status == "COMPLETED"
        assert dto.report_generation_started_at == 1704067200
        assert dto.report_generation_completed_at == 1704067260

    def test_report_status_failed_mapped(self):
        """FAILED status and completed_at timestamp are preserved."""
        job_stats = _make_job_stats({})
        job_stats.report_status = "FAILED"
        job_stats.report_generation_completed_at = 1704067260

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.report_status == "FAILED"
        assert dto.report_generation_completed_at == 1704067260

    def test_report_status_not_available_mapped(self):
        """NOT_AVAILABLE status is preserved (set when parquet is absent)."""
        job_stats = _make_job_stats({})
        job_stats.report_status = "NOT_AVAILABLE"

        dto = JobStatsMapper.to_dto(job_stats)

        assert dto.report_status == "NOT_AVAILABLE"
