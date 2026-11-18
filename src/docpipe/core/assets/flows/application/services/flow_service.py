"""Application service for flow management operations.

Provides CRUD operations for flows with validation, filtering, and pagination.

Exception Handling:
    Service layer raises business logic exceptions (FlowNotFoundException,
    FlowAlreadyExistsException, FlowInvalidDataException) directly. Infrastructure
    exceptions (PermissionError, OSError) from the repository layer bubble up
    naturally and are handled by the error_handler middleware.
"""

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from docpipe.core.assets.common.application.services.asset_service import AssetService
from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import (
    FlowAlreadyExistsException,
    FlowInvalidDataException,
    FlowNotFoundException,
)

if TYPE_CHECKING:
    from docpipe.core.job_management.domain.ports.job_stats_service import JobStatsService

logger = logging.getLogger(__name__)


class FlowService(AssetService[Flow]):
    """Application service for creating, retrieving, updating, and deleting flows.

    Extends AssetService[Flow] to inherit common operations (get, delete, exists, list, count).
    Implements Flow-specific operations (create, update, validate, partial_update).
    """

    # Fields that can be updated via partial_update_flow()
    UPDATABLE_FIELDS: ClassVar[set[str]] = {
        "name",
        "description",
        "definition",
        "tags",
        "is_hidden",
        "modified_by",
        "flow_version",
        "container_kind",
        "container_id",
        "job_id",
        "href",
        "flow_name",  # Authoring format: maps to "name"
        "flow",  # Authoring format: maps to "definition"
        "global_config",  # Authoring format: part of definition
    }

    # Fields that cannot be modified after creation
    PROTECTED_FIELDS: ClassVar[set[str]] = {"flow_id", "created_on", "created_by"}

    def __init__(
        self,
        *,
        repository: AssetRepository[Flow],
        job_stats_service: "JobStatsService | None" = None,
    ):
        """Initialize the service with a flow repository.

        Args:
            repository: Flow repository implementation (LocalFlowRepository or CamsFlowRepository)
            job_stats_service: Optional job stats service used to cascade-delete job runs
                when a flow is deleted.  When None, job runs are not deleted.
        """
        super().__init__(repository=repository)
        self._job_stats_service = job_stats_service
        logger.debug("FlowService initialized with repository: %s", type(repository).__name__)

    def _transform_authoring_updates(self, *, updates: dict[str, Any], existing_flow: Flow) -> dict[str, Any]:
        """Transform authoring format fields to Flow model fields.

        Maps authoring-specific fields to Flow attributes:
        - flow_name -> name
        - flow + global_config -> definition (complete authoring format)

        Args:
            updates: Dictionary with potential authoring format fields
            existing_flow: Existing flow to merge with for partial updates

        Returns:
            Transformed updates dict with Flow model fields
        """
        has_authoring_fields = (
            DocpipeConstants.FLOW_NAME in updates
            or DocpipeConstants.FLOW in updates
            or OperatorConstants.Config.GLOBAL_CONFIG in updates
        )

        # Map flow_name to name
        if DocpipeConstants.FLOW_NAME in updates:
            updates[DocpipeConstants.NAME] = updates.pop(DocpipeConstants.FLOW_NAME)
            logger.debug("Mapped flow_name to name")

        # If any authoring field is provided, rebuild complete authoring definition
        if has_authoring_fields:
            from docpipe.api.dto.authoring_flow_dto import AuthoringFlowCreateRequest
            from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow

            # Get existing authoring format data if available
            existing_def = existing_flow.definition
            existing_flow_name = (
                existing_def.get(DocpipeConstants.FLOW_NAME, existing_flow.name)
                if isinstance(existing_def, dict)
                else existing_flow.name
            )
            existing_flow_list = existing_def.get(DocpipeConstants.FLOW, []) if isinstance(existing_def, dict) else []
            existing_global_config = (
                existing_def.get(OperatorConstants.Config.GLOBAL_CONFIG, {}) if isinstance(existing_def, dict) else {}
            )

            authoring_dto = AuthoringFlowCreateRequest(
                flow_name=updates.get(DocpipeConstants.NAME, existing_flow_name),
                flow=updates.get(DocpipeConstants.FLOW, existing_flow_list),
                global_config=updates.get(OperatorConstants.Config.GLOBAL_CONFIG, existing_global_config),
                description=updates.get(DocpipeConstants.DESCRIPTION, existing_flow.description),
                tags=updates.get(OperatorConstants.Misc.TAGS, existing_flow.tags),
            )
            authoring_flow = AuthoringFlow.from_dict(data=authoring_dto.model_dump())
            authoring_flow.validate()

            updates[DocpipeConstants.DEFINITION] = authoring_dto.model_dump()
            # Remove authoring-specific fields after transformation
            updates.pop(DocpipeConstants.FLOW, None)
            updates.pop(OperatorConstants.Config.GLOBAL_CONFIG, None)
            logger.debug("Transformed authoring format to definition")

        return updates

    def _validate_flow_id(self, flow_id: str) -> str:
        """Validate that flow_id is not None, empty, or whitespace.

        Args:
            flow_id: The flow identifier to validate

        Returns:
            str: The validated flow_id

        Raises:
            FlowInvalidDataException: If flow_id is None, empty, or whitespace
        """
        if not flow_id or not flow_id.strip():
            raise FlowInvalidDataException("flow_id cannot be empty", field_name="flow_id")
        return flow_id

    def _filter_flows(
        self,
        flows: list[Flow],
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
        is_hidden: bool | None = None,
        container_id: str | None = None,
    ) -> list[Flow]:
        """Apply filters to a list of flows.

        Args:
            flows: List of flows to filter
            name_filter: Optional case-insensitive name substring filter
            tags_filter: Optional list of tags (flow must have at least one)
            is_hidden: Optional filter by hidden status
            container_id: Optional filter by container_id (project/space UUID)

        Returns:
            List[Flow]: Filtered list of flows
        """
        if name_filter:
            name_lower = name_filter.lower()
            flows = [f for f in flows if name_lower in f.name.lower()]

        if tags_filter:
            flows = [f for f in flows if any(tag in f.tags for tag in tags_filter)]

        if is_hidden is not None:
            flows = [f for f in flows if f.is_hidden == is_hidden]

        if container_id is not None:
            flows = [f for f in flows if f.container_id == container_id]

        return flows

    def _filter_flows_by_format(self, *, flows: list[Flow], is_elyra: bool | None) -> list[Flow]:
        """Filter flows by format (authoring vs Elyra).

        Args:
            flows: List of hydrated Flow objects
            is_elyra: True = Elyra only, False = Authoring only, None = all formats

        Returns:
            List[Flow]: Flows matching the requested format
        """
        if is_elyra is None:
            return flows
        if is_elyra:
            return [f for f in flows if DocpipeConstants.FLOW_NAME not in f.definition]
        return [f for f in flows if DocpipeConstants.FLOW_NAME in f.definition]

    def create_flow(self, *, flow: Flow, is_elyra: bool = False) -> Flow:
        """Create and store a new flow.

        This method creates a new flow in the repository with proper validation
        and duplicate prevention. It ensures that flows with duplicate names cannot
        be created, protecting against accidental overwrites. Timestamps are set
        automatically. Flows are stored in their original format
        (Elyra or Authoring) without conversion.

        Args:
            flow (Flow): Flow domain entity to create. Must have valid name and definition.
                        If flow_id is None, a UUID will be generated automatically by the
                        repository. The flow must pass validation before creation.
            is_elyra (bool): Indicates the format of the flow definition.
                           True = Elyra format, False = Authoring format.
                           This parameter is kept for backward compatibility but flows
                           are now stored in their original format. Default: False.

        Returns:
            Flow: The created flow with generated metadata (flow_id, created_on, modified_on).
                 All timestamps are set to current UTC time.

        Raises:
            FlowAlreadyExistsException: If flow with the same name already exists.
            FlowInvalidDataException: If flow validation fails (empty name, invalid definition, etc.).
            FlowStorageException: If storage operation fails (I/O errors, permission issues, etc.).

        Example:
            >>> # Create flow with internal DAG format (will be converted to Elyra)
            >>> flow = Flow(name="My Pipeline", definition={"flow": {"dag": [], "global_config": {}}})
            >>> created_flow = service.create_flow(flow=flow, is_elyra=False)
            >>>
            >>> # Create flow with Elyra format (stored as-is)
            >>> flow = Flow(
            ...     name="Elyra Pipeline",
            ...     definition={"doc_type": "pipeline", "pipelines": [...]}
            ... )
            >>> created_flow = service.create_flow(flow=flow, is_elyra=True)

        Note:
            - Flows are stored in their original format (no conversion)
            - Conversion to runtime DAG happens at execution time if needed
            - created_at and modified_at are set automatically to current UTC time
            - Use update_flow() to modify existing flows
            - flow name must be unique across all flows in the repository
            - Validation occurs before any persistence operations
        """
        try:
            flow.validate()
        except ValueError as exc:
            logger.error("Flow validation failed: %s", exc)
            raise FlowInvalidDataException(f"Invalid flow data: {exc!s}") from exc

        logger.info("Creating flow with name: %s (format: %s)", flow.name, "Elyra" if is_elyra else "Authoring")

        if self._repository.exists_by_name(name=flow.name):
            logger.warning("Attempted to create flow with existing name: %s", flow.name)
            raise FlowAlreadyExistsException(f"Flow with name '{flow.name}' already exists", flow_name=flow.name)

        saved_flow = self._repository.save(asset=flow)

        logger.info("Successfully created flow %s with name %s", saved_flow.flow_id, saved_flow.name)
        return saved_flow

    def get_flow(self, flow_id: str) -> Flow:
        """Retrieve a flow by ID.

        Fetches a single flow from the repository by its unique identifier.
        This is the primary method for retrieving flow details.

        Args:
            flow_id (str): Unique identifier of the flow (typically a UUID string).
                          Cannot be None, empty, or whitespace-only.

        Returns:
            Flow: The requested flow entity with all its properties including:
                 - flow_id: Unique identifier
                 - name: Flow name
                 - definition: Flow configuration (nodes, edges)
                 - description: Optional description
                 - tags: List of tags
                 - created_on, modified_on: Timestamps
                 - is_hidden: Visibility flag

        Raises:
            FlowInvalidDataException: If flow_id is None, empty string, or whitespace-only.
            FlowNotFoundException: If flow with given ID does not exist in repository.
            FlowStorageException: If retrieval operation fails (I/O errors, parsing errors, etc.).

        Example:
            >>> # Retrieve by UUID
            >>> flow = service.get_flow("550e8400-e29b-41d4-a716-446655440000")
            >>> print(f"Flow: {flow.name}")
            >>> print(f"Created: {flow.created_at}")
            >>>
            >>> # Handle missing flow
            >>> try:
            ...     flow = service.get_flow("nonexistent-id")
            ... except FlowNotFoundException:
            ...     print("Flow not found")

        Note:
            - Use flow_exists() for lightweight existence checks
            - This method loads the complete flow object from storage
            - Flow validation is performed during loading
        """
        # Delegate to inherited get_by_id() from AssetService
        return self.get_by_id(asset_id=flow_id)

    def _migrate_root_path(self, definition: Any) -> Any:
        """Migrate legacy ``root_path`` string to ``paths`` list in-memory.

        Flows saved before the multi-path filesystem change stored a single
        ``root_path`` string under ``connection_params``.  This rewrites the
        definition on load so the rest of the system always sees the new
        ``paths`` list format without requiring a data migration on disk.
        """
        if not isinstance(definition, dict):
            return definition

        nodes = definition.get("flow") or definition.get("dag") or []
        for node in nodes:
            config = node.get("config", {})
            if not isinstance(config, dict):
                continue
            if config.get("provider") != "filesystem":
                continue
            conn = config.get("connection_params", {})
            if not isinstance(conn, dict):
                continue
            if "root_path" in conn and "paths" not in conn:
                root_path = conn.pop("root_path")
                conn["paths"] = [root_path] if isinstance(root_path, str) else list(root_path)
                logger.debug("Migrated root_path -> paths for filesystem node '%s'", node.get("name", ""))

        return definition

    def update_flow(self, flow: Flow) -> Flow:
        """Update an existing flow with full replacement.

        Performs a complete update of the flow, replacing all fields. The flow must
        exist in the repository. If the flow name changes, the repository's update()
        method handles renaming the file atomically. The modified_at timestamp is
        updated automatically.

        Args:
            flow (Flow): Flow domain entity with updated data. Must have a valid flow_id
                        that exists in the repository. All fields will be updated, so
                        ensure the flow object contains complete data.

        Returns:
            Flow: The updated flow with refreshed modified_on timestamp set to current
                 UTC time.

        Raises:
            FlowInvalidDataException: If flow_id is None, empty, or if flow validation fails
                       (invalid name, definition, etc.).
            FlowNotFoundException: If flow with given ID does not exist in repository.
            FlowStorageException: If update operation fails (I/O errors, permission issues, etc.).

        Example:
            >>> # Full update of existing flow
            >>> flow = service.get_flow("abc123")
            >>> flow.name = "Updated Name"
            >>> flow.description = "New description"
            >>> flow.tags = ["production", "v2"]
            >>> updated = service.update_flow(flow)
            >>> print(updated.modified_at)  # Updated timestamp
            >>>
            >>> # Update with validation
            >>> try:
            ...     flow.name = ""  # Invalid
            ...     service.update_flow(flow)
            ... except FlowInvalidDataException as e:
            ...     print(f"Validation failed: {e}")

        Note:
            - This is a full replacement operation - all fields are updated
            - Use partial_update_flow() to update only specific fields
            - modified_at timestamp is set automatically
            - Validation occurs before any file operations
            - Name changes trigger atomic file rename in repository
        """
        try:
            if flow.flow_id is None or not flow.flow_id.strip():
                raise FlowInvalidDataException("Flow ID is required for update", field_name="flow_id")

            flow.validate()
        except ValueError as exc:
            logger.error("Flow validation failed: %s", exc)
            raise FlowInvalidDataException(f"Invalid flow data: {exc!s}") from exc

        # Fetch existing flow to verify existence and preserve immutable creation metadata
        existing = self._repository.find_by_id(asset_id=flow.flow_id)
        if existing is None:
            raise FlowNotFoundException(f"Flow {flow.flow_id} not found", flow_id=flow.flow_id)

        # Preserve protected fields from the stored flow so a full-replacement PUT
        # never overwrites created_on / created_by with the current timestamp.
        flow.created_on = existing.created_on
        flow.created_by = existing.created_by

        flow.update_timestamp()

        updated_flow = self._repository.update(asset=flow)

        logger.info("Successfully updated flow %s", updated_flow.flow_id)
        return updated_flow

    def delete_flow(self, flow_id: str) -> bool:
        """Delete a flow by ID.

        This standardizes error handling - service layer now raises exceptions directly rather than
        returning None/False and letting the route layer check and raise.

        Args:
            flow_id (str): Unique identifier of the flow to delete. Cannot be None,
                          empty, or whitespace-only.

        Returns:
            bool: True if flow was deleted successfully.

        Raises:
            FlowNotFoundException: If flow with given ID does not exist.
            FlowInvalidDataException: If flow_id is None, empty string, or whitespace-only.
            FlowStorageException: If delete operation fails (I/O errors, permission issues, etc.).

        Example:
            >>> # Delete existing flow
            >>> service.delete_flow("abc123")  # Returns True
            >>>
            >>> # Delete non-existent flow
            >>> service.delete_flow("nonexistent")  # Raises FlowNotFoundException

        Note:
            - Deletion is permanent and cannot be undone
            - Now raises FlowNotFoundException instead of returning False for missing flows
            - Cascades to delete all associated job runs when job_stats_service is set
        """
        # Delegate to inherited delete() from AssetService
        result = self.delete(asset_id=flow_id)
        if result:
            self._delete_job_runs_for_flow(flow_id)
        return result

    def bulk_delete_flows(self, flow_ids: list[str]) -> dict[str, Any]:
        """Delete multiple flows by their IDs in a single operation.

        Uses the repository's bulk_delete method for efficient batch deletion.
        The operation is atomic at the repository level, using global locking
        to ensure consistency. Individual flow failures don't stop the entire
        operation - partial success is supported.

        Args:
            flow_ids (list[str]): List of flow identifiers to delete. Cannot be empty.
                                 Each flow_id is validated by the repository.

        Returns:
            dict[str, Any]: Dictionary containing:
                - deleted (list[str]): List of successfully deleted flow_ids
                - failed (list[dict]): List of dicts with 'flow_id' and 'error' for failures
                - total_requested (int): Total number of flow_ids requested for deletion
                - total_deleted (int): Count of successfully deleted flows
                - total_failed (int): Count of failed deletions

        Raises:
            FlowInvalidDataException: If flow_ids list is empty or None.
            FlowStorageException: If a critical error occurs during bulk operation.

        Example:
            >>> # Delete multiple flows
            >>> result = service.bulk_delete_flows(["flow1", "flow2", "flow3"])
            >>> print(f"Deleted: {result['total_deleted']}, Failed: {result['total_failed']}")
            >>> for failure in result['failed']:
            ...     print(f"Flow {failure['flow_id']} failed: {failure['error']}")
            >>>
            >>> # All successful
            >>> result = service.bulk_delete_flows(["flow1", "flow2"])
            >>> assert result['total_deleted'] == 2
            >>> assert result['total_failed'] == 0
            >>>
            >>> # Partial failure
            >>> result = service.bulk_delete_flows(["existing", "nonexistent"])
            >>> assert result['total_deleted'] == 1
            >>> assert result['total_failed'] == 1

        Note:
            - Uses repository's bulk_delete for efficient batch processing
            - Operation is atomic at repository level with global locking
            - Individual flow failures don't stop the entire operation
            - Returns detailed results for all requested deletions
        """
        if not flow_ids:
            raise FlowInvalidDataException("flow_ids list cannot be empty", field_name="flow_ids")

        logger.info("Starting bulk delete for %d flows", len(flow_ids))

        # Delegate to repository's bulk_delete
        result = self._repository.bulk_delete(asset_ids=flow_ids)

        # Cascade-delete job runs for every successfully deleted flow
        for flow_id in result.get("deleted", []):
            self._delete_job_runs_for_flow(flow_id)

        logger.info(
            "Bulk delete completed: %d deleted, %d failed out of %d requested",
            result["total_deleted"],
            result["total_failed"],
            result["total_requested"],
        )

        return result

    def _delete_job_runs_for_flow(self, flow_id: str) -> None:
        """Cascade-delete all job runs for a flow after it has been removed.

        Silently skips if no job_stats_service is configured.  Failures are
        logged as warnings so a job-stats error never blocks a flow delete.

        Args:
            flow_id: UUID of the deleted flow.
        """
        if self._job_stats_service is None:
            return
        try:
            deleted = self._job_stats_service.delete_job_runs_by_job_id(job_id=flow_id)
            if deleted:
                logger.info("Cascade-deleted %d job run(s) for flow %s", deleted, flow_id)
        except Exception as exc:
            logger.warning(
                "Could not cascade-delete job runs for flow %s: %s",
                flow_id,
                exc,
            )

    def list_flows(
        self,
        skip: int = 0,
        limit: int = 100,
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
        is_hidden: bool | None = None,
        container_id: str | None = None,
        is_elyra: bool | None = None,
    ) -> list[Flow]:
        """List flows with pagination and filtering.

        Retrieves flows from the repository and applies filters and pagination.
        Filters are applied in-memory after retrieving all flows. For large
        repositories, consider using count_flows() to get total count efficiently
        for pagination calculations.

        Args:
            skip (int): Number of items to skip (for pagination). Must be >= 0.
                       Default: 0. Use with limit for pagination.
            limit (int): Maximum number of items to return. Must be > 0.
                        Default: 100. Maximum page size.
            name_filter (Optional[str]): Filter by name (partial match, case-insensitive).
                                        Example: "pipeline" matches "My Pipeline" and
                                        "Test Pipeline". None returns all flows.
            tags_filter (Optional[List[str]]): Filter by tags (flows must have at least
                                              one matching tag). Example: ["production", "test"]
                                              matches flows with either tag. None returns all.
            is_hidden (Optional[bool]): Filter by visibility status. True returns only hidden
                                       flows, False returns only visible flows, None returns all.

        Returns:
            List[Flow]: List of flows matching filters and pagination constraints.
                       Empty list if no flows match. Flows are returned in the order
                       they are stored in the repository.

        Raises:
            ValueError: If skip < 0 or limit <= 0. Pagination parameters must be valid.
            Exception: If list operation fails (I/O errors, parsing errors, etc.).

        Example:
            >>> # Get first 10 visible flows
            >>> flows = service.list_flows(skip=0, limit=10, is_hidden=False)
            >>> print(f"Retrieved {len(flows)} flows")
            >>>
            >>> # Get flows with "etl" in name
            >>> etl_flows = service.list_flows(name_filter="etl")
            >>>
            >>> # Get flows tagged as "production"
            >>> prod_flows = service.list_flows(tags_filter=["production"])
            >>>
            >>> # Pagination example
            >>> page_size = 20
            >>> page_num = 2
            >>> flows = service.list_flows(skip=page_num * page_size, limit=page_size)
            >>>
            >>> # Combined filters
            >>> flows = service.list_flows(
            ...     name_filter="pipeline",
            ...     tags_filter=["production"],
            ...     is_hidden=False,
            ...     skip=0,
            ...     limit=50
            ... )

        Note:
            - Filters are applied in-memory after loading all flows
            - Use count_flows() with same filters to get total count
            - Case-insensitive name matching for better UX
            - Tags filter uses OR logic (any matching tag)
            - Empty result list is returned if no matches found
        """
        if skip < 0:
            raise FlowInvalidDataException("skip must be >= 0", field_name="skip")
        if limit <= 0:
            raise FlowInvalidDataException("limit must be > 0", field_name="limit")

        all_flows = self._repository.find_all()
        filtered_flows = self._filter_flows(all_flows, name_filter, tags_filter, is_hidden, container_id)
        filtered_flows = self._filter_flows_by_format(flows=filtered_flows, is_elyra=is_elyra)

        # Sort newest-first (most recently modified at top) using modified_on / updated_at
        def _sort_key(flow: Flow) -> str:
            ts = flow.get_updated_at() or flow.get_created_at()
            return ts.isoformat() if ts is not None else ""

        filtered_flows.sort(key=_sort_key, reverse=True)
        paginated_flows = filtered_flows[skip : skip + limit]

        logger.info(
            "Listed %d flows (filtered from %d, paginated from %d)",
            len(paginated_flows),
            len(filtered_flows),
            len(all_flows),
        )
        return paginated_flows

    def count_flows(
        self,
        name_filter: str | None = None,
        tags_filter: list[str] | None = None,
        is_hidden: bool | None = None,
        container_id: str | None = None,
        is_elyra: bool | None = None,
    ) -> int:
        """Count flows matching filters.

        Useful for pagination to determine total pages. Uses the same filtering
        logic as list_flows() but returns only the count, making it efficient
        for pagination calculations.

        Args:
            name_filter (Optional[str]): Filter by name (partial match, case-insensitive).
                                        Same logic as list_flows(). None counts all flows.
            tags_filter (Optional[List[str]]): Filter by tags (flows must have at least
                                              one matching tag). Same logic as list_flows().
            is_hidden (Optional[bool]): Filter by visibility status. None counts all flows.

        Returns:
            int: Total number of flows matching filters. Returns 0 if no matches.
                Always returns a non-negative integer.

        Raises:
            Exception: If count operation fails (I/O errors, parsing errors, etc.).

        Example:
            >>> # Get total count
            >>> total = service.count_flows()
            >>> print(f"Total flows: {total}")
            >>>
            >>> # Count visible flows
            >>> visible = service.count_flows(is_hidden=False)
            >>>
            >>> # Count production flows
            >>> prod_count = service.count_flows(tags_filter=["production"])
            >>>
            >>> # Calculate pagination
            >>> page_size = 10
            >>> total = service.count_flows(is_hidden=False)
            >>> total_pages = (total + page_size - 1) // page_size
            >>> print(f"Total pages: {total_pages}")
            >>>
            >>> # Combined with list_flows for pagination
            >>> total = service.count_flows(name_filter="pipeline")
            >>> flows = service.list_flows(name_filter="pipeline", skip=0, limit=10)
            >>> print(f"Showing {len(flows)} of {total} flows")

        Note:
            - Uses identical filtering logic to list_flows() for consistency
            - More efficient than len(list_flows()) for large result sets
            - Returns 0 for no matches, never raises FileNotFoundError
            - Useful for pagination UI (total pages, showing X of Y, etc.)
        """
        all_flows = self._repository.find_all()
        filtered_flows = self._filter_flows(all_flows, name_filter, tags_filter, is_hidden, container_id)
        filtered_flows = self._filter_flows_by_format(flows=filtered_flows, is_elyra=is_elyra)

        logger.info("Counted %d flows (filtered from %d)", len(filtered_flows), len(all_flows))
        return len(filtered_flows)

    def partial_update_flow(self, flow_id: str, updates: dict[str, Any]) -> Flow:
        """Partially update a flow (only provided fields).

        Updates only the fields specified in the updates dictionary. Protected fields
        (flow_id, created_at, created_by) cannot be modified and are ignored with a
        warning. Unknown fields are also ignored. When the flow name is updated, the
        repository handles file renaming atomically. Validation occurs before any
        file operations to prevent data loss.

        Args:
            flow_id (str): Unique identifier of the flow to update. Cannot be None,
                          empty, or whitespace-only.
            updates (Dict[str, Any]): Dictionary of fields to update. Keys must match
                                     Flow attributes. Protected fields are ignored.
                                     Cannot be empty dictionary.
                                     Valid fields: name, description, definition, tags,
                                     is_hidden, modified_by, etc.

        Returns:
            Flow: The updated flow with refreshed modified_on timestamp. Only the
                 specified fields are modified; other fields remain unchanged.

        Raises:
            ValueError: If flow_id is empty, updates is empty dictionary, or if
                       validation fails after applying updates.
            FileNotFoundError: If flow with given ID does not exist in repository.
            Exception: If update operation fails (I/O errors, permission issues, etc.).

        Example:
            >>> # Update only description
            >>> updated = service.partial_update_flow(
            ...     "abc123",
            ...     {"description": "New description"}
            ... )
            >>> print(updated.description)
            >>>
            >>> # Update multiple fields
            >>> updated = service.partial_update_flow(
            ...     "abc123",
            ...     {
            ...         "name": "Renamed Flow",
            ...         "tags": ["production", "v2"],
            ...         "is_hidden": False
            ...     }
            ... )
            >>>
            >>> # Protected fields are ignored
            >>> updated = service.partial_update_flow(
            ...     "abc123",
            ...     {
            ...         "flow_id": "new-id",  # Ignored with warning
            ...         "description": "Updated"  # Applied
            ...     }
            ... )
            >>>
            >>> # Unknown fields are ignored
            >>> updated = service.partial_update_flow(
            ...     "abc123",
            ...     {
            ...         "invalid_field": "value",  # Ignored with warning
            ...         "name": "Valid Update"  # Applied
            ...     }
            ... )

        Note:
            - Only specified fields are updated; others remain unchanged
            - Protected fields (flow_id, created_on, created_by) cannot be modified
            - Unknown fields are logged as warnings and ignored
            - modified_on timestamp is updated automatically
            - Validation occurs before persistence
            - Uses repository.update() for atomic operations
            - Name changes trigger atomic file rename
            - Returns original flow if no valid fields to update
        """
        self._validate_flow_id(flow_id)

        if not updates:
            raise FlowInvalidDataException("updates dictionary cannot be empty", field_name="updates")

        existing_flow = self.get_flow(flow_id)

        # Filter unknown fields
        unknown_fields = [
            k for k in updates.keys() if k not in self.UPDATABLE_FIELDS and k not in self.PROTECTED_FIELDS
        ]
        if unknown_fields:
            logger.warning("Ignoring unknown fields: %s", unknown_fields)

        # Transform authoring format fields if present
        updates = self._transform_authoring_updates(updates=updates, existing_flow=existing_flow)

        # Remove protected fields and build validated updates dictionary
        validated_updates = {}
        for field, value in updates.items():
            if field in self.PROTECTED_FIELDS:
                logger.warning("Ignoring update to protected field: %s", field)
                continue
            if field in self.UPDATABLE_FIELDS:
                validated_updates[field] = value

        if not validated_updates:
            logger.info("No valid fields to update for flow %s", flow_id)
            return existing_flow

        # Delegate to repository for actual update (applies updates, validates, updates timestamp, persists)
        updated_flow = self._repository.partial_update(existing_flow, validated_updates)

        logger.info("Updated fields for flow %s: %s", flow_id, list(validated_updates.keys()))

        return updated_flow

    def flow_exists(self, flow_id: str) -> bool:
        """Check if a flow exists.

        Lightweight operation to check flow existence without loading the full flow
        object. This is more efficient than get_flow() when you only need to verify
        existence. Useful for validation before operations or conditional logic.

        Args:
            flow_id (str): Unique identifier of the flow to check. Cannot be None,
                          empty, or whitespace-only.

        Returns:
            bool: True if flow exists in repository, False otherwise. Always returns
                 a boolean value, never None.

        Raises:
            ValueError: If flow_id is None, empty string, or whitespace-only.
            Exception: If check operation fails (I/O errors, permission issues, etc.).
                      Does not raise FileNotFoundError for missing flows.

        Example:
            >>> # Check before get
            >>> if service.flow_exists("abc123"):
            ...     flow = service.get_flow("abc123")
            ...     print(f"Found: {flow.name}")
            ... else:
            ...     print("Flow not found")
            >>>
            >>> # Validate before create
            >>> if not service.flow_exists("new-flow-id"):
            ...     flow = Flow(flow_id="new-flow-id", name="New Flow", ...)
            ...     service.create_flow(flow)
            >>>
            >>> # Conditional delete
            >>> if service.flow_exists("abc123"):
            ...     service.delete_flow("abc123")
            ...     print("Deleted")

        Note:
            - More efficient than get_flow() for existence checks
            - Does not load full flow object from storage
            - Returns False for non-existent flows (no exception)
            - Use before operations to avoid FileNotFoundError
            - Useful for conditional logic and validation
        """
        # Delegate to inherited exists() from AssetService
        return self.exists(asset_id=flow_id)
