# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
JobStatsMapper module for converting JobStats domain models to enterprise-compatible DTOs.
"""

from docpipe.api.dto.job_run_dto import JobRunStatusResponse
from docpipe.api.dto.job_stats_dto import JobStatsDto
from docpipe.core.job_management.domain.models import JobStats
from docpipe.utils.orchestration.node_ordering import order_node_items

from .node_stats_mapper import NodeStatsMapper

# Constants for duration calculations
MIN_DURATION_SECONDS = 0
MAX_DURATION_LIMIT_SECONDS = 31536000


class JobStatsMapper:
    """Mapper for JobStats domain models to DTOs."""

    @staticmethod
    def to_dto(*, job_stats: JobStats, node_order: list[str] | None = None) -> JobStatsDto:
        """Convert JobStats domain model to JobStatsDto with topologically or chronologically sorted node_stats."""
        sorted_node_items = order_node_items(
            node_stats=job_stats.node_stats,
            node_order=node_order,
        )
        node_stats_dto = {node_id: NodeStatsMapper.to_dto(stats) for node_id, stats in sorted_node_items}

        # Convert nested batch_node_stats
        batch_node_stats_dto = {
            node_id: {batch_id: NodeStatsMapper.to_dto(stats) for batch_id, stats in batch_stats.items()}
            for node_id, batch_stats in job_stats.batch_node_stats.items()
        }

        # Dynamically calculate duration if it is not yet fully populated (e.g. for running jobs)
        duration = job_stats.duration
        if duration <= MIN_DURATION_SECONDS < job_stats.start_time:
            from datetime import UTC, datetime

            end_t = job_stats.end_time if job_stats.end_time > 0 else int(datetime.now(tz=UTC).timestamp())
            duration = max(MIN_DURATION_SECONDS, end_t - job_stats.start_time)
            # Clamp duration to the maximum supported seconds to avoid validation errors with far-apart mock times
            duration = min(duration, MAX_DURATION_LIMIT_SECONDS)

        return JobStatsDto(
            job_id=job_stats.job_id,
            job_run_id=job_stats.job_run_id,
            status=job_stats.status,
            message=job_stats.message,
            start_time=job_stats.start_time,
            end_time=job_stats.end_time,
            duration=duration,
            heartbeat_timestamp=job_stats.heartbeat_timestamp,
            progress_timestamp=job_stats.progress_timestamp,
            total_docs=job_stats.total_docs,
            processed_docs=job_stats.processed_docs,
            completed_docs=job_stats.completed_docs,
            failed_docs=job_stats.failed_docs,
            skipped_docs=job_stats.skipped_docs,
            deleted_doc_count=job_stats.deleted_doc_count,
            total_pages_processed=job_stats.total_pages_processed,
            page_type_stats=job_stats.page_type_stats,
            execution_time=job_stats.execution_time,
            orchestrator=job_stats.orchestrator,
            container_kind=job_stats.container_kind,
            container_id=job_stats.container_id,
            flow_id=job_stats.flow_id,
            flow_name=job_stats.flow_name,
            user_id=job_stats.user_id,
            account_id=job_stats.account_id,
            user_entitlements=job_stats.user_entitlements,
            report_status=job_stats.report_status,
            report_generation_started_at=job_stats.report_generation_started_at,
            report_generation_completed_at=job_stats.report_generation_completed_at,
            node_stats=node_stats_dto,
            batch_node_stats=batch_node_stats_dto,
        )

    @staticmethod
    def to_status_response(
        *,
        job_stats: JobStats,
        include_logs: bool = False,
        node_order: list[str] | None = None,
    ) -> JobRunStatusResponse:
        """
        Convert JobStats domain model to a JobRunStatusResponse DTO.

        Args:
            job_stats: JobStats domain model
            include_logs: Whether to include individual node log strings as dynamic fields
            node_order: Optional pre-resolved topological list of node IDs

        Returns:
            JobRunStatusResponse DTO ready for API response
        """
        from docpipe.api.dto.job_run_dto import JobRunStatusResponse

        # Calculate node_sequence (topological order if provided, otherwise chronological)
        sorted_nodes = order_node_items(
            node_stats=job_stats.node_stats,
            node_order=node_order,
        )
        node_sequence = [node_id for node_id, _ in sorted_nodes]

        # Build node_metadata array in the same order as node_sequence
        node_metadata = [NodeStatsMapper.to_node_metadata_item(node_id, stats) for node_id, stats in sorted_nodes]

        # Convert to DTO with matching node ordering
        job_stats_dto = JobStatsMapper.to_dto(job_stats=job_stats, node_order=node_order)

        response = JobRunStatusResponse(
            node_sequence=node_sequence, job_stats=job_stats_dto, node_metadata=node_metadata
        )

        # Add individual node log strings as dynamic fields (only if include_logs=True)
        if include_logs:
            for node_id in node_sequence:
                if node_id in job_stats.node_stats:
                    node_stat = job_stats.node_stats[node_id]
                    batch_stats = job_stats.batch_node_stats.get(node_id) if job_stats.batch_node_stats else None
                    log_str = NodeStatsMapper.to_log_string(
                        node_id=node_id, node_stat=node_stat, batch_stats=batch_stats
                    )
                    # Set dynamic attribute on the Pydantic model
                    setattr(response, node_id, log_str)

        return response
