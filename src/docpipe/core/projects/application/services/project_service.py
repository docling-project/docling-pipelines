"""ProjectService — application service for project CRUD operations.

Coordinates between:
- ProjectRepository: persistence of project entities
- AssetRepository[Flow]: read-only access for flow_count computation
- FlowService: cascade-deletion of flows on project delete, and project-scoped flow listing
- JobStatsService: job run summary enrichment for project flow lists
"""

from collections import defaultdict
from typing import ClassVar

from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.ports.job_stats_service import JobStatsService
from docpipe.core.projects.domain.models.flow_job_run_summary import FlowJobRunSummary
from docpipe.core.projects.domain.models.project import Project
from docpipe.core.projects.domain.ports.project_repository import ProjectRepository
from docpipe.exceptions.docpipe_exceptions import (
    ProjectAlreadyExistsException,
    ProjectInvalidDataException,
    ProjectNotFoundException,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_MAX_BULK_RUN_FETCH = 10_000


class ProjectService:
    """CRUD service for Project entities with flow_count enrichment.

    Responsibilities:
    - Create, read, update, delete projects via the ProjectStore port
    - Enrich every returned Project with the current flow_count by scanning
      the flow repository for flows whose container_id matches the project_id
    - Enforce name uniqueness and field-level validation
    - Protect immutable fields (project_id, created_on, created_by)

    Args:
        store: ProjectStore implementation for persistence.
        flow_repository: Read-only flow repository used to compute flow_count.
    """

    UPDATABLE_FIELDS: ClassVar[set[str]] = {
        "name",
        "description",
        "tags",
        "modified_by",
        "href",
    }
    PROTECTED_FIELDS: ClassVar[set[str]] = {"project_id", "created_on", "created_by"}

    def __init__(
        self,
        *,
        repository: ProjectRepository,
        flow_repository: AssetRepository[Flow],
        flow_service: FlowService,
        job_stats_service: JobStatsService,
    ) -> None:
        self._repository = repository
        self._flow_repository = flow_repository
        self._flow_service = flow_service
        self._job_stats_service = job_stats_service
        logger.debug("ProjectService initialised with repository: %s", type(repository).__name__)

    # ── CREATE ───────────────────────────────────────────────────────

    def create_project(self, *, project: Project) -> Project:
        """Create and persist a new project.

        Args:
            project: Project instance to create. project_id is auto-generated
                if not provided.

        Returns:
            The created project with flow_count=0.

        Raises:
            ProjectInvalidDataException: If name is empty or exceeds 255 chars.
            ProjectAlreadyExistsException: If a project with the same name exists.
        """
        self._validate_name(project.name)

        if self._repository.exists_by_name(name=project.name):
            logger.warning("Attempted to create duplicate project name: %s", project.name)
            raise ProjectAlreadyExistsException(project_name=project.name)

        saved = self._repository.save(project=project)
        saved.flow_count = 0  # brand-new project has no flows
        logger.info("Created project %s (%s)", saved.project_id, saved.name)
        return saved

    # ── GET ──────────────────────────────────────────────────────────

    def get_project(self, *, project_id: str) -> Project:
        """Retrieve a project by ID, enriched with flow_count.

        Args:
            project_id: UUID of the project.

        Returns:
            Project with current flow_count.

        Raises:
            ProjectNotFoundException: If no project with this ID exists.
        """
        project = self._repository.get(project_id=project_id)
        if project is None:
            raise ProjectNotFoundException(project_id=project_id)
        project.flow_count = self._count_flows_for(project_id=project_id)
        logger.debug("Retrieved project %s", project_id)
        return project

    # ── LIST ─────────────────────────────────────────────────────────

    def list_projects(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
    ) -> list[Project]:
        """List projects with optional filtering and pagination.

        Args:
            skip: Number of items to skip (offset).
            limit: Maximum number of items to return.
            name_filter: Case-insensitive substring match on project name.
            tags_filter: Return projects that have at least one of these tags.

        Returns:
            Paginated list of projects, each enriched with flow_count.
        """
        projects = self._filter(self._repository.find_all(), name_filter, tags_filter)
        page = projects[skip : skip + limit]
        # Load flows once for the entire page instead of once per project.
        all_flows = self._flow_repository.find_all()
        for project in page:
            project.flow_count = sum(1 for f in all_flows if f.container_id == project.project_id)
        logger.debug("Listed %d projects (skip=%d, limit=%d)", len(page), skip, limit)
        return page

    def count_projects(
        self,
        *,
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
    ) -> int:
        """Count projects after applying filters (no pagination).

        Used to populate total_count in paginated list responses.

        Args:
            name_filter: Case-insensitive substring match on project name.
            tags_filter: Return projects that have at least one of these tags.

        Returns:
            Total number of matching projects.
        """
        return len(self._filter(self._repository.find_all(), name_filter, tags_filter))

    # ── FULL UPDATE ──────────────────────────────────────────────────

    def update_project(self, *, project: Project) -> Project:
        """Fully replace a project's mutable fields.

        Args:
            project: Project with updated data. Must carry the existing project_id.

        Returns:
            The updated project enriched with flow_count.

        Raises:
            ProjectNotFoundException: If no project with this ID exists.
        """
        if not self._repository.exists(project_id=project.project_id):
            raise ProjectNotFoundException(project_id=project.project_id)
        project.update_timestamp()
        updated = self._repository.update(project=project)
        updated.flow_count = self._count_flows_for(project_id=updated.project_id)
        logger.info("Updated project %s", updated.project_id)
        return updated

    # ── PARTIAL UPDATE ────────────────────────────────────────────────

    def partial_update_project(self, *, project_id: str, updates: dict) -> Project:
        """Apply a partial update, modifying only the provided fields.

        Protected fields (project_id, created_on, created_by) are silently
        stripped from updates before being applied.

        Args:
            project_id: UUID of the project to update.
            updates: Dictionary of fields to update (from PATCH body).

        Returns:
            The updated project enriched with flow_count.

        Raises:
            ProjectNotFoundException: If no project with this ID exists.
            ProjectInvalidDataException: If an updated name fails validation.
        """
        existing = self.get_project(project_id=project_id)  # raises 404 if missing

        # Strip immutable fields silently
        for field in self.PROTECTED_FIELDS:
            updates.pop(field, None)

        # Validate name if it is being updated
        if "name" in updates:
            self._validate_name(updates["name"])

        # Apply only allowed fields
        for key, value in updates.items():
            if key in self.UPDATABLE_FIELDS:
                setattr(existing, key, value)

        existing.update_timestamp()
        updated = self._repository.update(project=existing)
        updated.flow_count = self._count_flows_for(project_id=updated.project_id)
        logger.info("Partially updated project %s", updated.project_id)
        return updated

    # ── DELETE ───────────────────────────────────────────────────────

    def delete_project(self, *, project_id: str) -> None:
        """Delete a project and cascade-delete all flows linked to it.

        Finds all flows whose container_id matches project_id and bulk-deletes
        them before removing the project record. Individual flow deletion
        failures are logged as warnings but do not block the project deletion.

        Args:
            project_id: UUID of the project to delete.

        Raises:
            ProjectNotFoundException: If no project with this ID exists.
        """
        if not self._repository.exists(project_id=project_id):
            raise ProjectNotFoundException(project_id=project_id)

        # Cascade: delete all flows linked to this project
        flow_ids = [f.asset_id for f in self._flow_repository.find_all() if f.container_id == project_id and f.asset_id]
        if flow_ids:
            result = self._flow_service.bulk_delete_flows(flow_ids=flow_ids)
            if result.get("total_failed", 0):
                logger.warning(
                    "Deleted project %s but %d linked flow(s) could not be removed: %s",
                    project_id,
                    result["total_failed"],
                    [f["flow_id"] for f in result.get("failed", [])],
                )
            else:
                logger.info(
                    "Cascade-deleted %d flow(s) for project %s",
                    result["total_deleted"],
                    project_id,
                )

        self._repository.delete(project_id=project_id)
        logger.info("Deleted project %s", project_id)

    # ── PROJECT FLOWS — GET /api/v1/projects/{project_id}/flows ───────

    def get_project_flows_with_run_summary(
        self,
        *,
        project_id: str,
        skip: int = 0,
        limit: int = 100,
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
        is_hidden: bool | None = None,
        is_elyra: bool | None = None,
    ) -> tuple[list[Flow], dict[str, FlowJobRunSummary], int]:
        """Return a paginated page of project flows, their run summaries, and the total count.

        Makes downstream calls:
          1. Existence check via repository.exists() — cheap 404 guard.
          2. FlowService.list_flows(container_id=project_id, ...) — scoped,
             paginated, filtered flow list.
          3. FlowService.count_flows(container_id=project_id, ...) — total count
             for the same filters, used to populate PaginatedProjectFlowResponse.total_count.
          4. _build_job_run_summaries(flow_ids=[...]) — single scoped
             JobStatsService call that produces one FlowJobRunSummary per flow
             that has at least one run.

        Returning flows, summaries, and total_count together eliminates the need
        for a separate count_project_flows() call in the route handler and ensures
        both the page and its count are computed from the same filter state.

        Args:
            project_id: UUID of the project. Raises ProjectNotFoundException if absent.
            skip: Number of flows to skip (pagination offset).
            limit: Maximum number of flows to return per page.
            name_filter: Case-insensitive substring match on flow name.
                         None returns flows with any name.
            tags_filter: Returns flows that carry at least one of these tags.
                         None returns flows with any tags.
            is_hidden: True/False filters by visibility; None returns all.
            is_elyra: True=Elyra only, False=Authoring only, None=all formats.

        Returns:
            Tuple of:
              - list[Flow]: Paginated, filtered flows belonging to the project.
              - dict[str, FlowJobRunSummary]: Summaries keyed by flow_id.
                Flows with no recorded runs are absent from this dict.
              - int: Total number of flows matching all filters (before pagination).

        Raises:
            ProjectNotFoundException: If project_id does not correspond to a
                                      known project.
        """
        if not self._repository.exists(project_id=project_id):
            raise ProjectNotFoundException(project_id=project_id)

        flows = self._flow_service.list_flows(
            skip=skip,
            limit=limit,
            name_filter=name_filter,
            tags_filter=tags_filter,
            is_hidden=is_hidden,
            container_id=project_id,
            is_elyra=is_elyra,
        )
        total = self._flow_service.count_flows(
            name_filter=name_filter,
            tags_filter=tags_filter,
            is_hidden=is_hidden,
            container_id=project_id,
            is_elyra=is_elyra,
        )
        summaries = self._build_job_run_summaries(flow_ids=[f.flow_id for f in flows if f.flow_id])
        logger.debug(
            "Listed %d flows for project %s with %d run summaries (total=%d)",
            len(flows),
            project_id,
            len(summaries),
            total,
        )
        return flows, summaries, total

    def _build_job_run_summaries(
        self,
        *,
        flow_ids: list[str],
    ) -> dict[str, FlowJobRunSummary]:
        """Aggregate job run statistics for a set of flows using a single scoped fetch.

        Implementation notes:
        - Issues one JobStatsService.list_job_runs(job_ids=flow_ids) call scoped
          to the flows on this page.  SQL stores translate this to a WHERE job_id
          IN (...) clause; the JSON store skips non-matching files during iteration.
          This avoids both full-table scans and N+1 per-flow queries.
        - In the standard OSS execution path, JobStats.job_id is set to the flow's
          UUID.  Grouping by run.job_id therefore partitions runs by flow.
        - Runs within each group are sorted by start_time descending; the first
          entry becomes the "latest run" fields on FlowJobRunSummary.
        - Flows absent from the returned dict had no matching runs and will have
          job_run_summary=None in the API response.
        - _MAX_BULK_RUN_FETCH caps the result set.  A warning is logged if the
          limit is hit, as summaries would then be incomplete for high-volume flows.

        Args:
            flow_ids: UUIDs of the flows whose run stats are needed.  An empty
                      list short-circuits immediately and returns {}.

        Returns:
            Dict mapping flow_id (str) → FlowJobRunSummary.
            Only flows that have at least one recorded JobStats entry appear.
        """
        if not flow_ids:
            return {}

        all_runs = self._job_stats_service.list_job_runs(
            job_ids=flow_ids,
            limit=_MAX_BULK_RUN_FETCH,
        )
        if len(all_runs) == _MAX_BULK_RUN_FETCH:
            logger.warning(
                "Job run fetch hit limit of %d; summaries for project flows may be incomplete",
                _MAX_BULK_RUN_FETCH,
            )

        runs_by_flow: dict[str, list[JobStats]] = defaultdict(list)
        for run in all_runs:
            runs_by_flow[run.job_id].append(run)

        summaries: dict[str, FlowJobRunSummary] = {}
        for flow_id, runs in runs_by_flow.items():
            sorted_runs = sorted(runs, key=lambda r: r.start_time, reverse=True)
            latest = sorted_runs[0]
            status_counts: dict[str, int] = defaultdict(int)
            for r in runs:
                status_counts[str(r.status)] += 1
            summaries[flow_id] = FlowJobRunSummary(
                total_runs=len(runs),
                last_run_id=latest.job_run_id,
                last_run_status=str(latest.status),
                last_run_start_time=latest.start_time if latest.start_time is not None else None,
                status_counts=dict(status_counts),
            )
        return summaries

    # ── PRIVATE ──────────────────────────────────────────────────────

    def _count_flows_for(self, *, project_id: str | None) -> int:
        """Count flows whose container_id matches this project_id."""
        if not project_id:
            return 0
        return sum(1 for f in self._flow_repository.find_all() if f.container_id == project_id)

    @staticmethod
    def _validate_name(name: str | None) -> None:
        """Validate project name: non-empty and <= 255 chars."""
        if not name or not name.strip():
            raise ProjectInvalidDataException("Project name cannot be empty", field_name="name")
        if len(name) > 255:
            raise ProjectInvalidDataException("Project name cannot exceed 255 characters", field_name="name")

    @staticmethod
    def _filter(
        projects: list[Project],
        name_filter: str | None,
        tags_filter: list[str] | None,
    ) -> list[Project]:
        """Apply name and tag filters to a project list."""
        if name_filter:
            name_lower = name_filter.lower()
            projects = [p for p in projects if name_lower in p.name.lower()]
        if tags_filter:
            projects = [p for p in projects if any(t in p.tags for t in tags_filter)]
        return projects
