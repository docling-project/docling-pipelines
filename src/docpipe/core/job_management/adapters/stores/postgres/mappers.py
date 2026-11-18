from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats


class PostgresModelMapper:
    """
    Mapper class to convert between Domain Models and Postgres Models.
    Separates DB schema from domain logic as per hexagonal architecture.
    """

    @staticmethod
    def to_db_job_stats(*, domain_model: JobStats, job_stats_cls=None):
        """
        Convert domain JobStats to Postgres JobRunStats.
        """
        from .models import JobStatsModel

        cls = job_stats_cls or JobStatsModel
        return cls(
            job_id=domain_model.job_id,
            job_run_id=domain_model.job_run_id,
            status=str(domain_model.status.value)
            if hasattr(domain_model.status, "value")
            else str(domain_model.status),
            message=domain_model.message,
            start_time=domain_model.start_time,
            end_time=domain_model.end_time,
            duration=domain_model.duration,
            heartbeat_timestamp=domain_model.heartbeat_timestamp,
            progress_timestamp=domain_model.progress_timestamp,
            total_docs=domain_model.total_docs,
            processed_docs=domain_model.processed_docs,
            completed_docs=domain_model.completed_docs,
            failed_docs=domain_model.failed_docs,
            skipped_docs=domain_model.skipped_docs,
            deleted_doc_count=domain_model.deleted_doc_count,
            total_pages_processed=domain_model.total_pages_processed,
            page_type_stats=domain_model.page_type_stats,
            execution_time=domain_model.execution_time,
            orchestrator=domain_model.orchestrator,
            container_kind=domain_model.container_kind,
            container_id=domain_model.container_id,
            flow_id=domain_model.flow_id,
            flow_name=getattr(domain_model, "flow_name", None),
            user_id=domain_model.user_id,
            account_id=domain_model.account_id,
            user_entitlements=domain_model.user_entitlements,
            report_status=domain_model.report_status,
            report_generation_started_at=domain_model.report_generation_started_at,
            report_generation_completed_at=domain_model.report_generation_completed_at,
        )

    @staticmethod
    def to_db_node_stats(*, domain_model: NodeStats, job_run_id: str, node_stats_cls=None):
        """
        Convert domain NodeStats to Postgres NodeStats.
        """
        from .models import NodeStatsModel

        cls = node_stats_cls or NodeStatsModel
        return cls(
            job_run_id=job_run_id,
            node_id=domain_model.id,
            name=domain_model.name,
            node_status=str(domain_model.node_status.value)
            if hasattr(domain_model.node_status, "value")
            else str(domain_model.node_status),
            start_time=domain_model.start_time,
            end_time=domain_model.end_time,
            time_taken=domain_model.time_taken,
            col_names=domain_model.col_names,
            total_docs=domain_model.total_docs,
            failed_docs=domain_model.failed_docs,
            skipped_docs=domain_model.skipped_docs,
            docs_completed=domain_model.docs_completed,
            docs_completed_count=domain_model.docs_completed_count,
            node_metadata=domain_model.node_metadata,
            error=domain_model.error,
            batch_id=domain_model.batch_id,
            batch_num=domain_model.batch_num,
        )

    @staticmethod
    def to_domain_job_stats(*, db_model) -> JobStats:
        """
        Convert Postgres JobRunStats to domain JobStats.
        """
        return JobStats(
            job_id=db_model.job_id,
            job_run_id=db_model.job_run_id,
            status=ExecutionStatus(db_model.status) if db_model.status else ExecutionStatus.PENDING,
            message=db_model.message,
            start_time=db_model.start_time,
            end_time=db_model.end_time,
            duration=db_model.duration,
            heartbeat_timestamp=db_model.heartbeat_timestamp,
            progress_timestamp=db_model.progress_timestamp,
            total_docs=db_model.total_docs or 0,
            processed_docs=db_model.processed_docs or 0,
            completed_docs=db_model.completed_docs or 0,
            failed_docs=db_model.failed_docs or 0,
            skipped_docs=db_model.skipped_docs or 0,
            deleted_doc_count=db_model.deleted_doc_count or 0,
            total_pages_processed=db_model.total_pages_processed,
            page_type_stats=db_model.page_type_stats,
            execution_time=db_model.execution_time,
            orchestrator=db_model.orchestrator,
            container_kind=db_model.container_kind,
            container_id=db_model.container_id,
            flow_id=db_model.flow_id,
            flow_name=getattr(db_model, "flow_name", None),
            user_id=db_model.user_id,
            account_id=db_model.account_id,
            user_entitlements=db_model.user_entitlements,
            report_status=db_model.report_status,
            report_generation_started_at=db_model.report_generation_started_at,
            report_generation_completed_at=db_model.report_generation_completed_at,
        )

    @staticmethod
    def to_domain_node_stats(*, db_model) -> NodeStats:
        """
        Convert Postgres NodeStats to domain NodeStats.
        """
        return NodeStats(
            id=db_model.node_id,
            name=db_model.name,
            node_status=db_model.node_status,
            start_time=db_model.start_time,
            end_time=db_model.end_time,
            time_taken=db_model.time_taken,
            col_names=db_model.col_names,
            total_docs=db_model.total_docs,
            failed_docs=db_model.failed_docs,
            skipped_docs=db_model.skipped_docs,
            docs_completed=db_model.docs_completed,
            docs_completed_count=getattr(db_model, "docs_completed_count", 0),
            node_metadata=db_model.node_metadata,
            error=db_model.error,
            batch_id=db_model.batch_id,
            batch_num=db_model.batch_num,
        )
