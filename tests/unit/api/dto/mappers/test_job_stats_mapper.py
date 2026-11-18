# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for JobStatsMapper.

Tests cover:
- Conversion from JobStats domain model to JobStatsDto
- Conversion to JobRunStatusResponse
- Nested node_stats and batch_node_stats mapping
- Node sequence calculation
- Log inclusion in status response
"""

import pytest

from docpipe.api.dto.mappers.job_stats_mapper import JobStatsMapper
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models import JobStats, NodeStats


@pytest.fixture
def sample_node_stats():
    """Sample node stats for testing."""
    return NodeStats(
        id="12345678-1234-1234-1234-123456789abc",
        name="TestNode",
        node_status=ExecutionStatus.COMPLETED.value,
        start_time=1704067200,
        end_time=1704067260,
        time_taken=60,
        col_names=["col1", "col2"],
        total_docs=["doc1", "doc2"],
        docs_completed=["doc1", "doc2"],
        docs_completed_count=2,
        failed_docs=[],
        skipped_docs=[],
        node_metadata={
            "id": "12345678-1234-1234-1234-123456789abc",
            "operator": "TestNode",
            "node_metadata": {"key": "value"},
        },
    )


@pytest.fixture
def sample_job_stats(sample_node_stats):
    """Sample job stats with node stats."""
    return JobStats(
        job_id="12345678-1234-1234-1234-123456789abc",
        job_run_id="87654321-4321-4321-4321-cba987654321",
        status=ExecutionStatus.COMPLETED,
        message="Test job completed",
        start_time=1704067200,
        end_time=1704067300,
        duration=100,
        heartbeat_timestamp=1704067300,
        progress_timestamp=1704067250,
        total_docs=10,
        processed_docs=10,
        completed_docs=10,
        failed_docs=0,
        skipped_docs=0,
        deleted_doc_count=0,
        total_pages_processed=20,
        page_type_stats={"pdf": 5, "docx": 5},
        execution_time=100,
        orchestrator="prefect",
        container_kind="docker",
        container_id="container-123",
        flow_id="flow-789",
        user_id="user-001",
        account_id="account-001",
        user_entitlements={"role": "admin"},
        node_stats={"12345678-1234-1234-1234-123456789abc": sample_node_stats},
        batch_node_stats={},
    )


class TestToDtoConversion:
    """Test conversion from JobStats to JobStatsDto."""

    def test_to_dto_basic_fields(self, sample_job_stats):
        """Should convert all basic fields correctly."""
        dto = JobStatsMapper.to_dto(job_stats=sample_job_stats)

        assert dto.job_id == "12345678-1234-1234-1234-123456789abc"
        assert dto.job_run_id == "87654321-4321-4321-4321-cba987654321"
        assert dto.status == ExecutionStatus.COMPLETED
        assert dto.message == "Test job completed"
        assert dto.start_time == 1704067200
        assert dto.end_time == 1704067300
        assert dto.duration == 100
        assert dto.heartbeat_timestamp == 1704067300
        assert dto.progress_timestamp == 1704067250

    def test_to_dto_document_counts(self, sample_job_stats):
        """Should convert document count fields correctly."""
        dto = JobStatsMapper.to_dto(job_stats=sample_job_stats)

        assert dto.total_docs == 10
        assert dto.processed_docs == 10
        assert dto.completed_docs == 10
        assert dto.failed_docs == 0
        assert dto.skipped_docs == 0
        assert dto.deleted_doc_count == 0

    def test_to_dto_metadata_fields(self, sample_job_stats):
        """Should convert metadata fields correctly."""
        dto = JobStatsMapper.to_dto(job_stats=sample_job_stats)

        assert dto.orchestrator == "prefect"
        assert dto.container_kind == "docker"
        assert dto.container_id == "container-123"
        assert dto.flow_id == "flow-789"
        assert dto.flow_name is None  # sample_job_stats has no flow_name set
        assert dto.user_id == "user-001"
        assert dto.account_id == "account-001"

    def test_to_dto_flow_name_mapped(self):
        """flow_name is passed through from domain model to DTO."""
        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.COMPLETED,
            start_time=1704067200,
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_name="flow_06_oct_2026_11_16_PM-jyoti",
            node_stats={},
            batch_node_stats={},
        )

        dto = JobStatsMapper.to_dto(job_stats=job_stats)

        assert dto.flow_id == "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        assert dto.flow_name == "flow_06_oct_2026_11_16_PM-jyoti"

    def test_to_dto_flow_name_none_when_not_set(self):
        """flow_name defaults to None when the domain model has no flow_name."""
        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.RUNNING,
            start_time=1704067200,
            node_stats={},
            batch_node_stats={},
        )

        dto = JobStatsMapper.to_dto(job_stats=job_stats)

        assert dto.flow_name is None

    def test_to_dto_json_fields(self, sample_job_stats):
        """Should convert JSON fields correctly."""
        dto = JobStatsMapper.to_dto(job_stats=sample_job_stats)

        assert dto.page_type_stats == {"pdf": 5, "docx": 5}
        assert dto.user_entitlements == {"role": "admin"}

    def test_to_dto_node_stats_mapping(self, sample_job_stats):
        """Should map nested node_stats correctly."""
        dto = JobStatsMapper.to_dto(job_stats=sample_job_stats)

        assert "12345678-1234-1234-1234-123456789abc" in dto.node_stats
        node_dto = dto.node_stats["12345678-1234-1234-1234-123456789abc"]
        assert node_dto.id == "12345678-1234-1234-1234-123456789abc"
        assert node_dto.name == "TestNode"
        assert node_dto.node_status == ExecutionStatus.COMPLETED.value

    def test_to_dto_empty_node_stats(self):
        """Should handle empty node_stats."""
        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.RUNNING,
            start_time=1704067200,
            node_stats={},
            batch_node_stats={},
        )

        dto = JobStatsMapper.to_dto(job_stats=job_stats)
        assert dto.node_stats == {}
        assert dto.batch_node_stats == {}

    def test_to_dto_batch_node_stats_mapping(self, sample_node_stats):
        """Should map nested batch_node_stats correctly."""
        batch_node = NodeStats(
            id="22345678-1234-1234-1234-123456789abc",
            name="BatchNode",
            node_status=ExecutionStatus.COMPLETED.value,
            batch_id="b2345678-1234-1234-1234-123456789abc",
            batch_num=0,
            start_time=1704067200,
            end_time=1704067260,
            time_taken=60,
        )

        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.RUNNING,
            start_time=1704067200,
            node_stats={},
            batch_node_stats={
                "22345678-1234-1234-1234-123456789abc": {"b2345678-1234-1234-1234-123456789abc": batch_node}
            },
        )

        dto = JobStatsMapper.to_dto(job_stats=job_stats)
        assert "22345678-1234-1234-1234-123456789abc" in dto.batch_node_stats
        assert "b2345678-1234-1234-1234-123456789abc" in dto.batch_node_stats["22345678-1234-1234-1234-123456789abc"]
        batch_dto = dto.batch_node_stats["22345678-1234-1234-1234-123456789abc"]["b2345678-1234-1234-1234-123456789abc"]
        assert batch_dto.id == "22345678-1234-1234-1234-123456789abc"
        assert batch_dto.batch_id == "b2345678-1234-1234-1234-123456789abc"


class TestToStatusResponse:
    """Test conversion to JobRunStatusResponse."""

    def test_to_status_response_basic(self, sample_job_stats):
        """Should create status response with basic fields."""
        response = JobStatsMapper.to_status_response(job_stats=sample_job_stats)

        assert response.job_stats.job_id == "12345678-1234-1234-1234-123456789abc"
        assert response.job_stats.job_run_id == "87654321-4321-4321-4321-cba987654321"
        assert len(response.node_sequence) == 1
        assert response.node_sequence[0] == "12345678-1234-1234-1234-123456789abc"

    def test_to_status_response_node_sequence_ordering(self):
        """Should order node_sequence by start_time."""
        node1 = NodeStats(
            id="11111111-1111-1111-1111-111111111111",
            name="FirstNode",
            node_status=ExecutionStatus.COMPLETED.value,
            start_time=1704067200,
            end_time=1704067260,
        )
        node2 = NodeStats(
            id="22222222-2222-2222-2222-222222222222",
            name="SecondNode",
            node_status=ExecutionStatus.COMPLETED.value,
            start_time=1704067100,  # Earlier start time
            end_time=1704067150,
        )
        node3 = NodeStats(
            id="33333333-3333-3333-3333-333333333333",
            name="ThirdNode",
            node_status=ExecutionStatus.COMPLETED.value,
            start_time=1704067300,  # Latest start time
            end_time=1704067350,
        )

        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.COMPLETED,
            start_time=1704067100,
            node_stats={
                "11111111-1111-1111-1111-111111111111": node1,
                "22222222-2222-2222-2222-222222222222": node2,
                "33333333-3333-3333-3333-333333333333": node3,
            },
            batch_node_stats={},
        )

        response = JobStatsMapper.to_status_response(job_stats=job_stats)

        # Should be ordered by start_time
        assert response.node_sequence == [
            "22222222-2222-2222-2222-222222222222",
            "11111111-1111-1111-1111-111111111111",
            "33333333-3333-3333-3333-333333333333",
        ]

    def test_to_status_response_node_metadata(self, sample_job_stats):
        """Should include node_metadata array."""
        response = JobStatsMapper.to_status_response(job_stats=sample_job_stats)

        assert len(response.node_metadata) == 1
        metadata_item = response.node_metadata[0]
        assert metadata_item.id == "12345678-1234-1234-1234-123456789abc"
        assert metadata_item.operator == "TestNode"

    def test_to_status_response_without_logs(self, sample_job_stats):
        """Should not include log strings by default."""
        response = JobStatsMapper.to_status_response(job_stats=sample_job_stats, include_logs=False)

        # Should not have dynamic node_id attributes
        assert not hasattr(response, "12345678-1234-1234-1234-123456789abc")

    def test_to_status_response_with_logs(self, sample_job_stats):
        """Should include log strings when requested."""
        response = JobStatsMapper.to_status_response(job_stats=sample_job_stats, include_logs=True)

        # Should have dynamic node_id attribute with log string
        assert hasattr(response, "12345678-1234-1234-1234-123456789abc")
        log_str = getattr(response, "12345678-1234-1234-1234-123456789abc")
        assert "Starting execution: Step Name: TestNode" in log_str
        assert "Completed execution: TestNode" in log_str

    def test_to_status_response_empty_node_stats(self):
        """Should handle empty node_stats."""
        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.RUNNING,
            start_time=1704067200,
            node_stats={},
            batch_node_stats={},
        )

        response = JobStatsMapper.to_status_response(job_stats=job_stats)

        assert response.node_sequence == []
        assert response.node_metadata == []

    def test_to_status_response_multiple_nodes_with_logs(self):
        """Should include logs for all nodes when requested."""
        node1 = NodeStats(
            id="11111111-1111-1111-1111-111111111111",
            name="Node1",
            node_status=ExecutionStatus.COMPLETED.value,
            start_time=1704067200,
            end_time=1704067260,
        )
        node2 = NodeStats(
            id="22222222-2222-2222-2222-222222222222",
            name="Node2",
            node_status=ExecutionStatus.FAILED.value,
            start_time=1704067300,
            end_time=1704067360,
            error="Test error",
        )

        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id="87654321-4321-4321-4321-cba987654321",
            status=ExecutionStatus.FAILED,
            start_time=1704067200,
            node_stats={"11111111-1111-1111-1111-111111111111": node1, "22222222-2222-2222-2222-222222222222": node2},
            batch_node_stats={},
        )

        response = JobStatsMapper.to_status_response(job_stats=job_stats, include_logs=True)

        assert hasattr(response, "11111111-1111-1111-1111-111111111111")
        assert hasattr(response, "22222222-2222-2222-2222-222222222222")
        assert "Completed execution: Node1" in getattr(response, "11111111-1111-1111-1111-111111111111")
        assert "Failed execution: Node2" in getattr(response, "22222222-2222-2222-2222-222222222222")
        assert "Test error" in getattr(response, "22222222-2222-2222-2222-222222222222")
