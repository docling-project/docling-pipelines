"""
Data Access Layer for JobRunStats model.

Provides CRUD operations for job-level statistics.
"""

from sqlalchemy.sql.expression import func
from sqlmodel import select

from docpipe.exceptions.docpipe_exceptions import PostgresOperationException
from docpipe.utils.infrastructure.logging import get_logger

from .base_dao import BaseDAO

logger = get_logger()


class JobStatsDAL:
    """
    Data Access Layer for JobStatsModel model.

    Handles persistence and retrieval of job-level statistics.
    """

    def __init__(self, *, session_factory, model=None):
        """
        Initialize JobStatsDAL with session factory.

        Args:
            session_factory: SQLAlchemy session factory
            model: Optional SQLModel class to use instead of the default
        """
        from ..models import JobStatsModel

        self._dao = BaseDAO(model=model or JobStatsModel, session_factory=session_factory)

    def upsert(self, *, job_run_stats) -> None:
        """
        Insert or update job run stats.

        Args:
            job_run_stats: JobStatsModel model instance

        Raises:
            PostgresOperationException: If upsert operation fails
        """
        try:
            self._dao.upsert_no_refresh(obj=job_run_stats)
        except Exception as e:
            logger.error("Failed to upsert job run stats: %s", e)
            raise PostgresOperationException(
                message=f"Failed to upsert job run stats: {e}", operation="upsert", table="job_run_stats"
            ) from e

    def get_by_job_run_id(self, *, job_run_id: str):
        """
        Get job run stats by job_run_id.

        Args:
            job_run_id: Job run identifier

        Returns:
            Model instance if found, None otherwise

        Raises:
            PostgresOperationException: If retrieval operation fails
        """
        try:
            return self._dao.get_by_id(id=job_run_id)
        except Exception as e:
            logger.error("Failed to retrieve job run stats for %s: %s", job_run_id, e)
            raise PostgresOperationException(
                message=f"Failed to retrieve job run stats for {job_run_id}: {e}",
                operation="get_by_id",
                table="job_run_stats",
            ) from e

    def delete_job_stats(self, *, job_run_id: str) -> int:
        """
        Delete job run stats by job_run_id.

        Args:
            job_run_id: Job run identifier

        Returns:
            Number of rows deleted

        Raises:
            PostgresOperationException: If delete operation fails
        """
        try:
            return self._dao.delete_by_query(condition=self._dao.model.job_run_id == job_run_id)
        except Exception as e:
            logger.error("Failed to delete job run stats for %s: %s", job_run_id, e)
            raise PostgresOperationException(
                message=f"Failed to delete job run stats for {job_run_id}: {e}",
                operation="delete",
                table="job_run_stats",
            ) from e

    def atomic_increment_fields(
        self, *, job_run_id: str, increments: dict, updates: dict | None = None, jsonb_merges: dict | None = None
    ) -> None:
        """
        Atomically increment numeric fields and update others.

        Args:
            job_run_id: Job run identifier
            increments: Fields to increment {field_name: increment_value}
            updates: Fields to update {field_name: new_value}
            jsonb_merges: JSONB fields to merge {field_name: merge_dict}

        Raises:
            PostgresOperationException: If atomic update fails
        """
        try:
            condition = self._dao.model.job_run_id == job_run_id
            self._dao.atomic_increment_fields(
                condition=condition, increments=increments, updates=updates, jsonb_merges=jsonb_merges
            )
        except Exception as e:
            logger.error("Failed to atomically increment fields for %s: %s", job_run_id, e)
            raise PostgresOperationException(
                message=f"Failed to atomically increment fields for {job_run_id}: {e}",
                operation="atomic_increment",
                table="job_run_stats",
            ) from e

    def _apply_job_run_filters(self, *, query, job_id: str | None, job_ids: list[str] | None, status: str | None):
        model = self._dao.model
        if job_id:
            query = query.where(model.job_id == job_id)
        if job_ids:
            query = query.where(model.job_id.in_(job_ids))  # type: ignore[attr-defined]
        if status:
            query = query.where(model.status == status)
        return query

    def list_job_runs(
        self,
        *,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: str | None = None,
        limit: int = 100,
    ):
        """
        List job runs with optional filters.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids (adds WHERE job_id IN (...) clause)
            status: Optional filter by status
            limit: Maximum number of results

        Returns:
            List of model instances matching filters

        Raises:
            PostgresOperationException: If list operation fails
        """
        try:
            model = self._dao.model
            query = self._apply_job_run_filters(query=select(model), job_id=job_id, job_ids=job_ids, status=status)
            query = query.order_by(model.start_time.desc()).limit(limit)  # type: ignore[attr-defined]

            return self._dao.get_by_query(query=query)
        except Exception as e:
            logger.error("Failed to list jobs: %s", e)
            raise PostgresOperationException(
                message=f"Failed to list jobs: {e}", operation="list", table="job_run_stats"
            ) from e

    def count_job_runs(
        self,
        *,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: str | None = None,
    ) -> int:
        """
        Count job runs using the same filters as list_job_runs.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids
            status: Optional filter by status

        Returns:
            Number of matching job runs, with no result limit

        Raises:
            PostgresOperationException: If the count operation fails
        """
        try:
            model = self._dao.model
            query = self._apply_job_run_filters(
                query=select(func.count()).select_from(model),
                job_id=job_id,
                job_ids=job_ids,
                status=status,
            )

            def _read_count(session) -> int:
                return int(session.execute(query).scalar_one())

            return self._dao.execute_with_session(fn=_read_count)
        except Exception as e:
            logger.error("Failed to count jobs: %s", e)
            raise PostgresOperationException(
                message=f"Failed to count jobs: {e}", operation="count", table="job_run_stats"
            ) from e
