"""REST API standard error response DTOs.

These models implement an industry-standard error response format following
REST API best practices for structured error handling.

Models:
- ErrorTarget: Identifies the specific element that caused an error (field, parameter, header)
- ErrorDetail: Individual error with code, message, and optional target
- ErrorResponse: Complete error response with array of errors and trace ID

Validation errors are handled by the validation_exception_handler in error_handler.py,
which converts FastAPI RequestValidationError to ErrorResponse format.
"""

from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field


class TargetType(StrEnum):
    """Error target types."""

    PARAMETER = "parameter"
    FIELD = "field"
    HEADER = "header"


# Standard error codes used across the API
ErrorCode = Literal[
    "invalid_request",
    "invalid_parameter",
    "unauthorized",
    "forbidden",
    "not_found",
    "method_not_allowed",
    "conflict",
    "validation_error",
    "too_early",
    "too_many_requests",
    "internal_error",
    "service_unavailable",
    "unknown_error",
    # Flow operation error codes
    "flow_not_found",
    "flow_already_exists",
    "flow_invalid_data",
    "flow_storage_error",
    "flow_validation_failed",
    "flow_execution_failed",
    "prefect_flow_failed",
    # Event mapping operations
    "event_mapping_not_found",
    "event_mapping_already_exists",
    # Configuration and external service error codes
    "invalid_configuration",
    "external_service_error",
    # Operator error codes
    "operator_configuration_invalid",
    "operator_execution_failed",
    "operator_metadata_failed",
    "sql_filter_error",
    # Custom Operator error codes
    "custom_operator_not_found",
    "custom_operator_already_exists",
    "custom_operator_invalid_data",
    # Project error codes
    "project_not_found",
    "project_already_exists",
    "project_invalid_data",
    # Document Library error codes
    "document_library_not_found",
    "document_library_already_exists",
    "document_library_invalid_data",
    "document_library_storage_error",
    "document_library_documentset_not_found",
    # Document Set error codes
    "document_set_not_found",
    # Job run operation error codes
    "job_run_not_found",
    "job_run_already_exists",
    "job_run_invalid_state",
    "job_run_operation_failed",
    # Database and PostgreSQL error codes
    "database_migration_failed",
    "postgres_connection_failed",
    "postgres_operation_failed",
    "postgres_transaction_failed",
    "postgres_query_failed",
    # Job stats store error codes
    "job_stats_store_read_failed",
    "job_stats_store_write_failed",
    "job_stats_store_delete_failed",
    "job_stats_store_list_failed",
    "job_stats_store_atomic_update_failed",
    "job_stats_store_initialization_failed",
    # Integration error codes
    "ollama_connection_failed",
    "ollama_model_not_found",
    "opensearch_connection_failed",
    "opensearch_index_error",
    # REST client error codes
    "http_error",
    "connection_error",
    "invalid_response",
    # Document set operation error codes
    "document_set_not_found",
    "document_set_already_exists",
    "document_set_invalid_data",
    "document_set_creation_failed",
    "document_set_update_failed",
    "document_set_delete_failed",
    "document_set_data_operation_failed",
    "document_set_invalid_config",
    "document_set_adapter_not_found",
    # Document class operation error codes
    "document_class_list_failed",
]


class ErrorTarget(BaseModel):
    """Target information for an error."""

    type: str = Field(
        min_length=1,
        max_length=50,
        pattern="^[a-z_]+$",
        description="Type of target (e.g., 'parameter', 'field', 'header')",
        examples=["parameter", "field", "header"],
        json_schema_extra={
            "minLength": 1,
            "maxLength": 50,
            "pattern": "^[a-z_]+$",
        },
    )
    name: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[\s\S]{1,256}$",
        description="Name of the target element",
        examples=["flow_id", "name", "Authorization", "definition -> nodes -> 0 -> operator_type"],
        json_schema_extra={
            "minLength": 1,
            "maxLength": 256,
            "pattern": r"^[\s\S]{1,256}$",
        },
    )

    class Config:
        """Pydantic model configuration."""

        json_schema_extra: ClassVar[dict] = {
            "examples": [
                {"type": "parameter", "name": "flow_id"},
                {"type": "field", "name": "definition"},
                {"type": "header", "name": "Authorization"},
            ]
        }


class ErrorDetail(BaseModel):
    """Individual error detail following REST API standard format."""

    code: ErrorCode = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z_]+$",
        description="Machine-readable error code (snake_case)",
        examples=["invalid_parameter", "not_found", "validation_error", "internal_error"],
        json_schema_extra={
            "minLength": 1,
            "maxLength": 100,
            "pattern": r"^[a-z_]+$",
        },
    )
    message: str = Field(
        min_length=1,
        max_length=10000,
        pattern=r"^[\x20-\x7E\r\n]{1,10000}$",
        description="Human-readable error message explaining what went wrong",
        examples=["The 'flow_id' parameter is invalid", "Flow not found", "Validation failed for field 'name'"],
        json_schema_extra={
            "minLength": 1,
            "maxLength": 10000,
            "pattern": r"^[\x20-\x7E\r\n]{1,10000}$",
        },
    )
    more_info: str | None = Field(
        default=None,
        min_length=0,
        max_length=10000,
        pattern=r"^[ -~]{0,10000}$",
        description="URL to documentation about this error",
        examples=["https://docs.example.com/errors/invalid_parameter"],
        json_schema_extra={
            "minLength": 0,
            "maxLength": 10000,
            "pattern": r"^[ -~]{0,10000}$",
        },
    )
    target: ErrorTarget | None = Field(default=None, description="Specific element that caused the error")

    class Config:
        """Pydantic model configuration."""

        json_schema_extra: ClassVar[dict] = {
            "examples": [
                {
                    "code": "invalid_parameter",
                    "message": "The 'flow_id' parameter must be a valid UUID",
                    "more_info": "https://docs.example.com/errors/invalid_parameter",
                    "target": {"type": "parameter", "name": "flow_id"},
                },
                {
                    "code": "not_found",
                    "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                    "more_info": "https://docs.example.com/errors/not_found",
                },
                {
                    "code": "validation_error",
                    "message": "Field 'name' is required and cannot be empty",
                    "target": {"type": "field", "name": "name"},
                },
                {"code": "internal_error", "message": "An unexpected error occurred"},
            ]
        }


class ErrorResponse(BaseModel):
    """REST API standard error response format."""

    errors: list[ErrorDetail] = Field(
        min_length=1,
        max_length=100,
        description="Array of error details (at least one error required)",
        json_schema_extra={
            "minItems": 1,
            "maxItems": 100,
        },
    )
    trace: str = Field(
        min_length=36,
        max_length=36,
        pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-7][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$",
        description="Unique trace ID for debugging and request tracking",
        examples=["98765432-1098-1654-0210-987654321098"],
        json_schema_extra={
            "minLength": 36,
            "maxLength": 36,
            "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-7][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$",
        },
    )
    status_code: int = Field(
        description="HTTP status code",
        ge=400,
        le=599,
        examples=[400, 404, 500],
        json_schema_extra={"format": "int32"},
    )

    class Config:
        """Pydantic model configuration."""

        json_schema_extra: ClassVar[dict] = {
            "examples": [
                {
                    "errors": [
                        {
                            "code": "not_found",
                            "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                        }
                    ],
                    "trace": "550e8400-e29b-41d4-a716-446655440000",
                    "status_code": 404,
                },
                {
                    "errors": [
                        {
                            "code": "validation_error",
                            "message": "Field 'name' is required",
                            "target": {"type": "field", "name": "name"},
                        },
                        {
                            "code": "validation_error",
                            "message": "Field 'definition' must be a valid JSON object",
                            "target": {"type": "field", "name": "definition"},
                        },
                    ],
                    "trace": "98765432-1098-7654-3210-987654321098",
                    "status_code": 400,
                },
                {
                    "errors": [
                        {
                            "code": "internal_error",
                            "message": "An unexpected error occurred while processing the request",
                            "more_info": "https://docs.example.com/errors/internal_error",
                        }
                    ],
                    "trace": "12345678-9abc-def0-1234-56789abcdef0",
                    "status_code": 500,
                },
            ]
        }
