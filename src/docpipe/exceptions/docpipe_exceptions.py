"""Custom exception types for docpipe flow validation and execution."""

from json import JSONEncoder
from typing import Any, ClassVar

from docpipe.exceptions.error_codes import ErrorCode
from docpipe.exceptions.error_messages import ValidationMessage

TROUBLESHOOTING_DOCS_URL = "https://github.com/docling-project/docling-pipelines/tree/main/TROUBLESHOOTING.md"
DOCLING_PIPELINES_DOCS_URL = "https://github.com/docling-project/docling-pipelines/tree/main/docs"


class DocpipeException(Exception):
    """Docpipeexception."""

    def __init__(
        self,
        message,
        status_code: int = 500,
        error_code: ErrorCode | None = None,
        message_code: str | None = None,
        more_info: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.more_info = more_info
        self.message_code = message_code


class ValidationAlert(dict):
    """Validationalert."""

    def __init__(
        self,
        code=None,
        message=None,
        message_code=None,
        node_id=None,
        node_name=None,
        operator=None,
        **kwargs,
    ):
        all_fields = {
            "code": code,
            "message": message,
            "message_code": message_code,
            "node_id": node_id,
            "node_name": node_name,
            "operator": operator,
            **kwargs,
        }

        super().__init__(**all_fields)

        self.code: ErrorCode = code
        self.message: str = message
        self.message_code: str = message_code
        self.node_id = node_id
        self.node_name = node_name
        self.operator: str = operator

        # Set extra fields as instance attributes with validation
        self._set_extra_attributes(kwargs)

    def _set_extra_attributes(self, kwargs: dict[str, Any]) -> None:
        """Set extra fields as instance attributes with basic validation."""
        for key, value in kwargs.items():
            if not isinstance(key, str) or not key.isidentifier():
                # Lazy import to avoid circular dependency
                from docpipe.utils.infrastructure.logging import get_logger

                logger = get_logger()
                logger.warning("Invalid attribute name: %s", key, stack_info=True)
                continue
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the dictionary representation."""
        return dict(self)


class ValidationAlertEncoder(JSONEncoder):
    """Validationalertencoder."""

    def default(self, o):
        """Default."""
        return o.__dict__


class FlowExecutionFailedException(DocpipeException):
    # Thrown when the given flow or flow definition not found
    """Flowexecutionfailedexception."""

    def __init__(self, message: str, status_code: int = 500, errors: list[ValidationAlert] | None = None):
        from docpipe.exceptions.error_codes import ErrorCode

        super().__init__(
            message,
            status_code,
            error_code=ErrorCode.FLOW_EXECUTION_FAILED,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-flow-execution-failed",
        )
        self.errors = errors


class FlowValidationException(DocpipeException):
    """Flowvalidationexception."""

    def __init__(
        self,
        message="Invalid Flow definition",
        errors: list[ValidationAlert | ValidationMessage] | None = None,
        warnings: list[ValidationAlert | ValidationMessage] | None = None,
    ):
        super().__init__(
            message,
            400,
            error_code=ErrorCode.FLOW_VALIDATION_FAILED,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-flow-validation-failed",
        )

        self.errors = errors
        self.warnings = warnings

    def log_details(self, *, job_run_id: str | None = None) -> None:
        """
        Log detailed errors, warnings, and full traceback for debugging.
        Encapsulates all validation logging logic within the exception for better modularity.

        Args:
            job_run_id: Optional job run ID for context in log messages
        """
        # Lazy import to avoid circular dependency
        import json
        import traceback

        from docpipe.utils.infrastructure.logging import get_logger

        logger = get_logger()

        # Log full traceback for Prefect framework compatibility
        # Prefect consumes standard exception stacktraces, so we explicitly format and log them
        tb_lines = traceback.format_exception(type(self), self, self.__traceback__)
        full_traceback = "".join(tb_lines)
        context = f" for job_run_id={job_run_id}" if job_run_id else ""
        logger.error(
            "Flow validation failed%s: %s",
            context,
            full_traceback,
            exc_info=True,
        )

        # Log detailed errors and warnings
        if self.errors:
            logger.error(
                "Validation errors: %s",
                json.dumps([vars(e) if hasattr(e, "__dict__") else e for e in self.errors]),
            )
        if self.warnings:
            logger.warning(
                "Validation warnings: %s",
                json.dumps([vars(w) if hasattr(w, "__dict__") else w for w in self.warnings]),
            )


class PrefectFlowFailed(DocpipeException):
    # thrown when a prefect flow execution failed for a task
    """Prefectflowfailed."""

    def __init__(
        self,
        message,
        error_code: ErrorCode,
        message_code: str | None = None,
        status_code: int = 500,
    ):
        super().__init__(
            message,
            error_code=error_code,
            message_code=message_code,
            status_code=status_code,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-prefect-flow-task-failed",
        )


class ValidationException(DocpipeException):
    """Validationexception."""

    def __init__(
        self,
        message="Invalid definition",
        errors: list[ValidationAlert | ValidationMessage] | None = None,
        warnings: list[ValidationAlert | ValidationMessage] | None = None,
    ):
        super().__init__(message, 400)

        self.errors = errors
        self.warnings = warnings


class ConfigurationError(DocpipeException):
    """
    Exception raised for configuration errors.

    Used when required configuration parameters are missing or invalid,
    such as missing API keys, invalid credentials, or malformed settings.
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode | None = ErrorCode.INVALID_CONFIGURATION,
        status_code: int = 400,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
        )


class DependencyError(DocpipeException):
    """
    Exception raised when required dependencies are missing.

    Used when optional packages or libraries are not installed
    but are required for specific functionality.
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode | None = ErrorCode.EXTERNAL_SERVICE_ERROR,
        status_code: int = 500,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
        )


class ExternalServiceError(DocpipeException):
    """
    Exception raised when external service calls fail.

    Used for API errors, network failures, authentication errors,
    rate limits, and other external service-related issues.
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode | None = ErrorCode.EXTERNAL_SERVICE_ERROR,
        status_code: int = 502,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
        )


class AssetNotFoundException(DocpipeException):
    """
    Generic exception raised when an asset is not found.

    Used in asset CRUD operations when attempting to retrieve, update,
    or delete an asset that does not exist. Works for Flow, DocumentSet,
    DocumentLibrary, and other asset types.
    """

    # Map asset type names to their specific error codes
    _ERROR_CODE_MAP: ClassVar[dict[str, ErrorCode]] = {
        "Flow": ErrorCode.FLOW_NOT_FOUND,
        "DocumentSet": ErrorCode.DOCUMENT_SET_NOT_FOUND,
        # Add more as needed: "DocumentLibrary": ErrorCode.DOCUMENT_LIBRARY_NOT_FOUND,
    }

    def __init__(
        self,
        message: str,
        asset_id: str | None = None,
        asset_type: str | None = None,
    ):
        if asset_id and asset_type and not message:
            message = f"{asset_type.capitalize()} {asset_id} not found"

        # Determine error code based on asset type
        error_code = self._ERROR_CODE_MAP.get(asset_type or "Flow", ErrorCode.FLOW_NOT_FOUND)

        super().__init__(
            message,
            status_code=404,
            error_code=error_code,
        )
        self.asset_id = asset_id
        self.asset_type = asset_type


class AssetAlreadyExistsException(DocpipeException):
    """
    Generic exception raised when attempting to create an asset that already exists.

    Used in asset creation when an asset with the same name or ID already exists.
    Works for Flow, DocumentSet, DocumentLibrary, and other asset types.
    """

    # Map asset type names to their specific error codes
    _ERROR_CODE_MAP: ClassVar[dict[str, ErrorCode]] = {
        "Flow": ErrorCode.FLOW_ALREADY_EXISTS,
        "DocumentSet": ErrorCode.DOCUMENT_SET_ALREADY_EXISTS,
        # Add more as needed: "DocumentLibrary": ErrorCode.DOCUMENT_LIBRARY_ALREADY_EXISTS,
    }

    def __init__(
        self,
        message: str,
        asset_id: str | None = None,
        asset_name: str | None = None,
        asset_type: str | None = None,
    ):
        # Determine error code based on asset type
        error_code = self._ERROR_CODE_MAP.get(asset_type or "Flow", ErrorCode.FLOW_ALREADY_EXISTS)

        super().__init__(
            message,
            status_code=409,
            error_code=error_code,
        )
        self.asset_id = asset_id
        self.asset_name = asset_name
        self.asset_type = asset_type


class AssetInvalidDataException(DocpipeException):
    """
    Generic exception raised when asset data is invalid.

    Used in asset CRUD operations when validation fails due to invalid
    asset data, empty names, invalid field values, or malformed data.
    Works for Flow, DocumentSet, DocumentLibrary, and other asset types.
    """

    def __init__(
        self,
        message: str,
        field_name: str | None = None,
        asset_type: str | None = None,
    ):
        super().__init__(
            message,
            status_code=400,
            error_code=ErrorCode.FLOW_INVALID_DATA,  # Reuse existing error code
        )
        self.field_name = field_name
        self.asset_type = asset_type


class FlowNotFoundException(DocpipeException):
    """
    Exception raised when a flow is not found.

    Used in flow CRUD operations when attempting to retrieve, update,
    or delete a flow that does not exist.
    """

    def __init__(
        self,
        message: str,
        flow_id: str | None = None,
    ):
        if flow_id and not message:
            message = f"Flow {flow_id} not found"
        super().__init__(
            message,
            status_code=404,
            error_code=ErrorCode.FLOW_NOT_FOUND,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors",
        )
        self.flow_id = flow_id


class FlowAlreadyExistsException(DocpipeException):
    """
    Exception raised when attempting to create a flow that already exists.

    Used in flow creation when a flow with the same name or ID already exists.
    """

    def __init__(
        self,
        message: str,
        flow_id: str | None = None,
        flow_name: str | None = None,
    ):
        super().__init__(
            message,
            status_code=409,
            error_code=ErrorCode.FLOW_ALREADY_EXISTS,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors",
        )
        self.flow_id = flow_id
        self.flow_name = flow_name


class FlowInvalidDataException(DocpipeException):
    """
    Exception raised when flow data is invalid.

    Used in flow CRUD operations when validation fails due to invalid
    flow data, empty names, invalid field values, or malformed JSON.
    """

    def __init__(
        self,
        message: str,
        field_name: str | None = None,
    ):
        super().__init__(
            message,
            status_code=400,
            error_code=ErrorCode.FLOW_INVALID_DATA,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors",
        )
        self.field_name = field_name


class FlowStorageException(DocpipeException):
    """
    Exception raised when flow storage operations fail.

    Used in flow CRUD operations when file system errors occur,
    such as permission errors, disk full, corrupted files, or I/O errors.
    """

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        flow_id: str | None = None,
    ):
        super().__init__(
            message,
            status_code=500,
            error_code=ErrorCode.FLOW_STORAGE_ERROR,
            more_info=f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors",
        )
        self.operation = operation
        self.flow_id = flow_id


class ProjectNotFoundException(DocpipeException):
    """
    Exception raised when a project is not found.

    Used in project CRUD operations when attempting to retrieve, update,
    or delete a project that does not exist.
    """

    def __init__(
        self,
        message: str = "",
        *,
        project_id: str | None = None,
        status_code: int = 404,
    ):
        super().__init__(
            message or f"Project '{project_id}' not found",
            status_code=status_code,
            error_code=ErrorCode.PROJECT_NOT_FOUND,
        )
        self.project_id = project_id


class ProjectAlreadyExistsException(DocpipeException):
    """
    Exception raised when a project with the same name already exists.

    Used in project creation to prevent duplicate project names.
    """

    def __init__(
        self,
        message: str = "",
        *,
        project_name: str | None = None,
        status_code: int = 409,
    ):
        super().__init__(
            message or f"A project named '{project_name}' already exists",
            status_code=status_code,
            error_code=ErrorCode.PROJECT_ALREADY_EXISTS,
        )
        self.project_name = project_name


class ProjectInvalidDataException(DocpipeException):
    """
    Exception raised when project data fails validation.

    Used when project name is empty, exceeds length limits, or other
    field-level validation errors occur.
    """

    def __init__(
        self,
        message: str = "",
        *,
        field_name: str | None = None,
        status_code: int = 400,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=ErrorCode.PROJECT_INVALID_DATA,
        )
        self.field_name = field_name


class RepositoryConfigurationException(DocpipeException):
    """
    Exception raised when repository configuration is invalid.

    Used when repository type selection or repository-specific settings
    are missing, unsupported, or malformed.
    """

    def __init__(
        self,
        message: str,
        repository_type: str | None = None,
        valid_types: list[str] | None = None,
        status_code: int = 400,
    ):
        super().__init__(message, status_code=status_code, error_code=ErrorCode.INVALID_CONFIGURATION)
        self.repository_type = repository_type
        self.valid_types = valid_types


class JobRunNotFoundException(DocpipeException):
    """
    Exception raised when a job run is not found.

    Used in job run operations when attempting to retrieve, update,
    cancel, or delete a job run that does not exist.
    """

    def __init__(
        self,
        message: str,
        job_run_id: str | None = None,
    ):
        if job_run_id and not message:
            message = f"Job run {job_run_id} not found"
        super().__init__(
            message,
            status_code=404,
            error_code=ErrorCode.JOB_RUN_NOT_FOUND,
        )
        self.job_run_id = job_run_id


class JobRunAlreadyExistsException(DocpipeException):
    """
    Exception raised when attempting to create a job run that already exists.

    Used in job run creation when a job run with the same ID already exists.
    """

    def __init__(
        self,
        message: str,
        job_run_id: str | None = None,
    ):
        super().__init__(
            message,
            status_code=409,
            error_code=ErrorCode.JOB_RUN_ALREADY_EXISTS,
        )
        self.job_run_id = job_run_id


class JobRunInvalidStateException(DocpipeException):
    """
    Exception raised when job run operation is invalid for current state.

    Used when attempting operations that are not valid for the job run's
    current state (e.g., canceling a completed job, deleting a running job).
    """

    def __init__(
        self,
        message: str,
        job_run_id: str | None = None,
        current_state: str | None = None,
        status_code: int = 400,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=ErrorCode.JOB_RUN_INVALID_STATE,
        )
        self.job_run_id = job_run_id
        self.current_state = current_state


class JobRunOperationFailedException(DocpipeException):
    """
    Exception raised when a job run operation fails.

    Used for general job run operation failures such as cancellation
    failures, deletion failures, or status update failures.
    """

    def __init__(
        self,
        message: str,
        job_run_id: str | None = None,
        operation: str | None = None,
        status_code: int = 500,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=ErrorCode.JOB_RUN_OPERATION_FAILED,
        )
        self.job_run_id = job_run_id
        self.operation = operation


class DatabaseMigrationException(DocpipeException):
    """
    Exception raised when database migration operations fail.

    Used for Alembic migration failures, schema initialization errors,
    or migration configuration issues.
    """

    def __init__(
        self,
        *,
        message: str,
        operation: str | None = None,
        status_code: int = 500,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=ErrorCode.DATABASE_MIGRATION_FAILED,
        )
        self.operation = operation


class JobStatsStoreException(DocpipeException):
    """
    Base exception for job stats store operations.

    Used as base class for all job stats store-related exceptions.
    """

    def __init__(
        self,
        *,
        message: str,
        error_code: ErrorCode,
        job_run_id: str | None = None,
        operation: str | None = None,
        status_code: int = 500,
    ):
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
        )
        self.job_run_id = job_run_id
        self.operation = operation


class JobStatsStoreReadException(JobStatsStoreException):
    """
    Exception raised when reading from job stats store fails.

    Used for get_job_stats, get_node_stats, list_jobs failures.
    """

    def __init__(
        self,
        *,
        message: str,
        job_run_id: str | None = None,
        operation: str | None = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.JOB_STATS_STORE_READ_FAILED,
            job_run_id=job_run_id,
            operation=operation,
            status_code=500,
        )


class JobStatsStoreWriteException(JobStatsStoreException):
    """
    Exception raised when writing to job stats store fails.

    Used for store_job_stats, store_node_stats, bulk_store_node_stats failures.
    """

    def __init__(
        self,
        *,
        message: str,
        job_run_id: str | None = None,
        operation: str | None = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.JOB_STATS_STORE_WRITE_FAILED,
            job_run_id=job_run_id,
            operation=operation,
            status_code=500,
        )


class JobStatsStoreDeleteException(JobStatsStoreException):
    """
    Exception raised when deleting from job stats store fails.

    Used for delete_job_stats failures.
    """

    def __init__(
        self,
        *,
        message: str,
        job_run_id: str | None = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.JOB_STATS_STORE_DELETE_FAILED,
            job_run_id=job_run_id,
            operation="delete",
            status_code=500,
        )


class JobStatsStoreAtomicUpdateException(JobStatsStoreException):
    """
    Exception raised when atomic update operations fail.

    Used for atomic_increment_fields failures.
    """

    def __init__(
        self,
        *,
        message: str,
        job_run_id: str | None = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.JOB_STATS_STORE_ATOMIC_UPDATE_FAILED,
            job_run_id=job_run_id,
            operation="atomic_update",
            status_code=500,
        )


class JobStatsStoreInitializationException(JobStatsStoreException):
    """
    Exception raised when job stats store initialization fails.

    Used for store initialization, connection setup, migration failures.
    """

    def __init__(
        self,
        *,
        message: str,
        store_type: str | None = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.JOB_STATS_STORE_INITIALIZATION_FAILED,
            operation="initialization",
            status_code=500,
        )
        self.store_type = store_type


class PostgresConnectionException(DocpipeException):
    """
    Exception raised when PostgreSQL connection fails.

    Used for connection establishment, engine creation failures.
    """

    def __init__(
        self,
        *,
        message: str,
        host: str | None = None,
        database: str | None = None,
    ):
        super().__init__(
            message,
            status_code=500,
            error_code=ErrorCode.POSTGRES_CONNECTION_FAILED,
        )
        self.host = host
        self.database = database


class PostgresOperationException(DocpipeException):
    """
    Exception raised when PostgreSQL operations fail.

    Used for DAO/DAL operation failures (insert, update, delete, select).
    """

    def __init__(
        self,
        *,
        message: str,
        operation: str | None = None,
        table: str | None = None,
    ):
        super().__init__(
            message,
            status_code=500,
            error_code=ErrorCode.POSTGRES_OPERATION_FAILED,
        )
        self.operation = operation
        self.table = table


class PostgresTransactionException(DocpipeException):
    """
    Exception raised when PostgreSQL transaction fails.

    Used for transaction commit, rollback failures.
    """

    def __init__(
        self,
        *,
        message: str,
        operation: str | None = None,
    ):
        super().__init__(
            message,
            status_code=500,
            error_code=ErrorCode.POSTGRES_TRANSACTION_FAILED,
        )
        self.operation = operation


class PostgresQueryException(DocpipeException):
    """
    Exception raised when PostgreSQL query execution fails.

    Used for SQL query execution failures, syntax errors.
    """

    def __init__(
        self,
        *,
        message: str,
        query: str | None = None,
    ):
        super().__init__(
            message,
            status_code=500,
            error_code=ErrorCode.POSTGRES_QUERY_FAILED,
        )
        self.query = query


class CustomOperatorNotFoundException(DocpipeException):
    """Exception raised when a custom operator is not found."""

    def __init__(
        self,
        *,
        message: str,
        operator_id: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=404,
            error_code=ErrorCode.CUSTOM_OPERATOR_NOT_FOUND,
        )
        self.operator_id = operator_id


class CustomOperatorAlreadyExistsException(DocpipeException):
    """Exception raised when attempting to create a custom operator that already exists."""

    def __init__(
        self,
        *,
        message: str,
        operator_id: str | None = None,
        short_name: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=409,
            error_code=ErrorCode.CUSTOM_OPERATOR_ALREADY_EXISTS,
        )
        self.operator_id = operator_id
        self.short_name = short_name


class CustomOperatorInvalidDataException(DocpipeException):
    """Exception raised when custom operator data or file is invalid."""

    def __init__(
        self,
        *,
        message: str,
        field_name: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_code=ErrorCode.CUSTOM_OPERATOR_INVALID_DATA,
        )
        self.field_name = field_name


__all__ = [
    "ConfigurationError",
    "CustomOperatorAlreadyExistsException",
    "CustomOperatorInvalidDataException",
    "CustomOperatorNotFoundException",
    "DatabaseMigrationException",
    "DependencyError",
    "DocpipeException",
    "ExternalServiceError",
    "FlowAlreadyExistsException",
    "FlowExecutionFailedException",
    "FlowInvalidDataException",
    "FlowNotFoundException",
    "FlowStorageException",
    "FlowValidationException",
    "JobRunAlreadyExistsException",
    "JobRunInvalidStateException",
    "JobRunNotFoundException",
    "JobRunOperationFailedException",
    "JobStatsStoreAtomicUpdateException",
    "JobStatsStoreDeleteException",
    "JobStatsStoreException",
    "JobStatsStoreInitializationException",
    "JobStatsStoreReadException",
    "JobStatsStoreWriteException",
    "PostgresConnectionException",
    "PostgresOperationException",
    "PostgresQueryException",
    "PostgresTransactionException",
    "PrefectFlowFailed",
    "ProjectAlreadyExistsException",
    "ProjectInvalidDataException",
    "ProjectNotFoundException",
    "RepositoryConfigurationException",
    "ValidationAlert",
    "ValidationAlertEncoder",
    "ValidationException",
]
