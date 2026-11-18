"""Reusable field definitions and constants for Flow API DTOs.

This module provides field definitions, validation patterns, and constraints
used across Flow API DTOs and Job Statistics DTOs.

Module Organization:
--------------------
1. Shared Metadata: Unified patterns and constraints for all DTOs
2. Flow-Specific Patterns: Validation patterns for Flow API
3. Flow-Specific Constraints: Length and array constraints for Flow API
4. Example Values: Realistic examples for documentation
5. JSON Schema Extras: Additional OpenAPI schema constraints
6. Flow Field Descriptions: Human-readable field documentation for Flow API
7. Field Factory Functions: datetime_field() for complex OpenAPI schemas

Architectural Note:
-------------------
All field metadata (patterns, lengths, descriptions) has been consolidated
into this module to simplify the DTO layer while maintaining strict validation.
Core domain models remain decoupled from these API-specific validation rules.
"""

from typing import Any

from pydantic import Field

# ============================================================================
# VALIDATION PATTERNS
# ============================================================================

# Identity Patterns
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
"""UUID v4 format pattern (lowercase hex with hyphens)."""

USER_ID_PATTERN = r"^[a-zA-Z0-9@._-]+$"
"""User identifier pattern (alphanumeric with common email/username characters)."""

# Job/Node Patterns
JOB_STATUS_PATTERN = r"^(Pending|Running|Completed|Failed|Canceled|Skipped|Queued|Starting|Paused|Resuming|Canceling|Failing|CompletedWithErrors|CompletedWithWarnings|Aborted)$"
"""Job status pattern (exact match for ExecutionStatus values)."""

ORCHESTRATOR_PATTERN = r"^[A-Za-z0-9_-]+$"
"""Orchestrator type pattern (alphanumeric with separators)."""

MESSAGE_PATTERN = r"^[\s\S]*$"
"""Message/error pattern allowing all characters."""

COLUMN_NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
"""Column name pattern (alphanumeric with separators)."""

# ============================================================================
# LENGTH CONSTRAINTS
# ============================================================================

# Identity Field Lengths
UUID_LENGTH = 36  # Standard UUID format: 8-4-4-4-12 + 4 hyphens
USER_ID_MIN_LENGTH = 1
USER_ID_MAX_LENGTH = 256

# Job Runs Field Lengths
JOB_STATUS_MIN_LENGTH = 1
JOB_STATUS_MAX_LENGTH = 64
ORCHESTRATOR_MIN_LENGTH = 1
ORCHESTRATOR_MAX_LENGTH = 64
MESSAGE_MIN_LENGTH = 0  # Allow empty messages
MESSAGE_MAX_LENGTH = 5000
ERROR_MESSAGE_MAX_LENGTH = 50000  # Longer for stack traces
COLUMN_NAME_MIN_LENGTH = 1
COLUMN_NAME_MAX_LENGTH = 256

# Container Field Lengths
CONTAINER_KIND_MIN_LENGTH = 1
CONTAINER_KIND_MAX_LENGTH = 50

# Account ID
ACCOUNT_ID_MIN_LENGTH = 1
ACCOUNT_ID_MAX_LENGTH = 256

# Custom Operator Field Lengths
OPERATOR_SHORT_NAME_MIN_LENGTH = 1
OPERATOR_SHORT_NAME_MAX_LENGTH = 128
OPERATOR_FILE_MIN_LENGTH = 1
OPERATOR_FILE_MAX_LENGTH = 255

# Document ID Lists
DOCS_IDS_LISTS_MIN_LENGTH = 0
DOCS_IDS_LISTS_MAX_LENGTH = 100000  # Max number of document IDs in lists

# ============================================================================
# INTEGER CONSTRAINTS
# ============================================================================

# Timestamps (Unix epoch seconds)
TIMESTAMP_MIN = 0  # Unix epoch start (1970-01-01)
TIMESTAMP_MAX = 9999999999

# Document Counts
DOCS_COUNT_MIN = 0
DOCS_COUNT_MAX = 1000000000  # 1 billion documents

# Durations (seconds)
DURATION_MIN = 0
DURATION_MAX_SECONDS = 31536000  # 1 year in seconds

# Batch ID
BATCH_ID_PATTERN = r"^[A-Za-z0-9_-]+$"
"""Batch ID pattern — alphanumeric, underscores, hyphens. Accepts UUIDs and short deterministic keys."""
BATCH_ID_MAX_LENGTH = 256

# Batch Numbers
BATCH_NUM_MIN = 0
BATCH_NUM_MAX = 10000

# Execution Time (seconds)
EXECUTION_TIME_MIN = 0
EXECUTION_TIME_MAX = 2147483647  # Max int32

# Pages
PAGES_COUNT_MIN = 0
PAGES_COUNT_MAX = 1000000000  # 1 billion pages

# ============================================================================
# FIELD DESCRIPTIONS
# ============================================================================

# Identity Field Descriptions
JOB_ID_DESC = "UUID of the associated Prefect job/execution"
JOB_RUN_ID_DESC = "Unique identifier for the job run (UUID format)"
NODE_ID_DESC = "Unique identifier for the node within the flow"
USER_ID_DESC = "User identifier associated with the job run"

# Status & Message Descriptions
JOB_STATUS_DESC = "Current execution status of the job run"
NODE_STATUS_DESC = "Execution status of the node"
MESSAGE_DESC = "Status message"
ERROR_DESC = "Error message if failed"

# Timing Field Descriptions
START_TIME_DESC = "Start timestamp (Unix epoch seconds)"
END_TIME_DESC = "End timestamp (Unix epoch seconds)"
DURATION_DESC = "Duration in seconds"
HEARTBEAT_DESC = "Last heartbeat timestamp (Unix epoch seconds)"
PROGRESS_TIMESTAMP_DESC = "Timestamp of the last measurable unit of forward progress (Unix epoch seconds)"
TIME_TAKEN_DESC = "Execution time for this node in seconds"
EXECUTION_TIME_DESC = "Execution time in seconds"

# Document Count Descriptions
TOTAL_DOCS_DESC = "Total number of documents"
PROCESSED_DOCS_DESC = "Number of processed documents"
COMPLETED_DOCS_DESC = "Number of completed documents"
FAILED_DOCS_DESC = "Number of failed documents"
SKIPPED_DOCS_DESC = "Number of skipped documents"
DELETED_DOCS_DESC = "Number of deleted documents"

# Document List Descriptions
TOTAL_DOCS_LIST_DESC = "List of total document IDs processed"
FAILED_DOCS_LIST_DESC = "List of failed document IDs"
SKIPPED_DOCS_LIST_DESC = "List of skipped document IDs"
DOCS_COMPLETED_LIST_DESC = "List of successfully completed document IDs"
DOCS_COMPLETED_COUNT_DESC = "Count of completed documents"

# Page Processing Descriptions
TOTAL_PAGES_DESC = "Total number of pages processed"
PAGE_TYPE_STATS_DESC = "Page type statistics"

# Execution Context Descriptions
ORCHESTRATOR_DESC = "Orchestrator type used for execution (e.g., Python)"
CONTAINER_TYPE_DESC = "Container type (PROJECT, SPACE, etc.)"
CONTAINER_ID_DESC_JOB = "Container identifier"
FLOW_ID_DESC_JOB = "Flow definition ID"
FLOW_NAME_DESC_JOB = "Human-readable name of the flow at run creation time"
ACCOUNT_ID_DESC = "Account/tenant identifier"
USER_ENTITLEMENTS_DESC = "User entitlements and permissions for this job run"

# Node Field Descriptions
NAME_DESC_NODE = "Human-readable node name"
COL_NAMES_DESC = "Column names from node output"
NODE_METADATA_DESC = "Operator-specific metadata"

# Batch Field Descriptions
BATCH_ID_DESC = "Unique identifier for batch execution"
BATCH_NUM_DESC = "Sequence number for batch execution"

# Aggregated Stats Descriptions
NODE_STATS_DESC = "Aggregated node-level statistics keyed by node_id"
BATCH_NODE_STATS_DESC = "Batch-level node stats: {node_id: {batch_id: NodeStats}}"

# ============================================================================
# FLOW-SPECIFIC PATTERNS
# ============================================================================
# All patterns are designed for IBM OpenAPI validator compliance and security.
# Patterns use raw strings and avoid end anchors for Pydantic compatibility.

# Identity Patterns

# Content Patterns
NAME_PATTERN = r"^.*\S.*$"
r"""Name pattern requiring at least one non-whitespace character.

Rationale: Names must contain meaningful content, not just whitespace.
Allows: Any characters including Unicode, but must have at least one non-whitespace character
Example: "Invoice Pipeline", "文档处理流程", "Traitement des factures"
Note: Pattern is compatible with rust-based regex engines (pydantic-core).
The pattern matches any string that contains at least one non-whitespace character (\S).
"""

TYPE_PATTERN = r"^[^\x00-\x1F]+$"
"""Type pattern requiring at least one character and excluding control characters.

Rationale: Type identifiers must be non-empty and without control characters.
Allows: All Unicode characters except ASCII control characters, minimum 1 character
Example: "ingest_source", "extract_operator", "embeddings"
"""

DESCRIPTION_PATTERN = r"^[\s\S]*$"
"""Description pattern allowing all characters including newlines.

Rationale: Descriptions need maximum flexibility for documentation.
Allows: Any character including newlines, tabs, Unicode
Example: Multi-line descriptions with formatting
"""

TAG_PATTERN = r"^[A-Za-z0-9._:/# -]+$"
"""Tag pattern (alphanumeric with special characters for flexible tagging).

Rationale: Tags are used for filtering/searching; flexible format supports various use cases.
Can contain: uppercase/lowercase letters, digits, dots, underscores, colons, slashes, hashes, spaces, hyphens
Example: "invoice", "Production-v2", "ml_model_123", "env:prod", "type/document"
"""

PARAM_NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
"""Parameter name pattern (alphanumeric with underscore, dot, hyphen).

Rationale: Parameter names should be simple identifiers.
Can contain: uppercase/lowercase letters, digits, underscores, dots, hyphens
Example: "batch_size", "max_workers", "timeout.seconds"
"""

PARAM_VALUE_PATTERN = r"^[\s\S]{1,1000}$"
"""Parameter value pattern (any character, 1-1000 length).

Rationale: Parameter values can be any string representation.
Allows: Any character including newlines, Unicode
Example: "100", "true", "{'key': 'value'}"
"""

ASSET_REF_TYPE_PATTERN = r"^[A-Za-z0-9_.-]+$"
"""Asset reference type pattern (alphanumeric with underscore, dot, hyphen).

Rationale: Asset types should be simple identifiers.
Can contain: uppercase/lowercase letters, digits, underscores, dots, hyphens
Example: "ibm_udp_flow", "custom_pipeline", "ml-model"
"""

# Container Patterns
CONTAINER_KIND_PATTERN = r"^(project|space)$"
"""Container kind pattern (must be 'project' or 'space').

Rationale: Enum-like validation for container types.
Allowed values: "project", "space" (case-sensitive)
"""

# Version Patterns
VERSION_PATTERN = r"^[0-9]+\.[0-9]+$"
"""Version pattern (semantic versioning: major.minor).

Rationale: Simple versioning for flow definition formats.
Format: <major>.<minor> (e.g., "2.0", "1.5")
Note: Patch version not included as flow formats rarely need that granularity
"""

# URL Patterns
URL_PATTERN = r"^https?://.*$"
"""URL pattern (http or https protocol).

Rationale: Pagination links must be valid HTTP(S) URLs.
Allows: http:// or https:// followed by any characters
Example: https://api.example.com/v1/flows?offset=10&limit=10
"""

API_PATH_PATTERN = r"^/api(/v[0-9]+)?/flows/[a-zA-Z0-9_-]+$"
"""API path pattern for flow resource URLs.

Rationale: HATEOAS self-reference links follow consistent format.
Format: /api[/v<version>]/flows/<flow-id>
Example: /api/v1/flows/550e8400-e29b-41d4-a716-446655440000
"""

# Datetime Patterns
DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
"""ISO 8601 datetime pattern with optional timezone.

Rationale: Standard datetime format for API responses.
Format: YYYY-MM-DDTHH:MM:SS[.microseconds][timezone]
Examples:
  - 2026-04-01T11:00:00Z (UTC)
  - 2026-04-01T11:00:00.123456+05:30 (with timezone)
  - 2026-04-01T11:00:00 (no timezone)
"""

# Operator Patterns
OPERATOR_TYPE_PATTERN = r"^(bool|boolean|crn|date|double|float|sfloat|enum|int8|int16|int32|int64|json|list|string|time|timestamp|vector|vector_sparse)$"
"""Operator type pattern (exact match for DataTypes enum values and common aliases).

Rationale: Operator types are predefined enums from DataTypes (AttributeDataTypes) and OperatorConstants.Types.
Includes common aliases used in operators: "float" (alias for "sfloat"), "int32" (alias for "int64"), "bool" (alias for "boolean")
Allowed values: "bool", "boolean", "crn", "date", "double", "float", "sfloat", "enum", "int8", "int16", "int32", "int64", "json", "list", "string", "time", "timestamp", "vector", "vector_sparse"
Example: "string", "int64", "int32", "double", "float", "sfloat", "boolean", "bool", "list", "json", "vector", "vector_sparse"
"""

OPERATOR_LABEL_PATTERN = r"^[\w\s\-\(\)]+$"
"""Operator label pattern (alphanumeric with spaces, hyphens, parentheses).

Rationale: Labels are human-readable names that may include special characters.
Allows: word characters, spaces, hyphens, parentheses
Example: "Entity Extraction (Ollama)", "ML Text Enrichment", "Document Classifier"
"""

OPERATOR_CATEGORY_PATTERN = r"^(Extract|Ingest|Functional|Quality|VectorDB|Storage|Custom)$"
"""Operator category pattern (exact match for OperatorCategory enum values).

Rationale: Categories are predefined enums from OperatorCategory.
Allowed values: "Extract", "Ingest", "Functional", "Quality", "VectorDB", "Storage", "Custom"
Example: "Extract", "Ingest", "Functional", "Quality", "VectorDB", "Storage", "Custom"
"""

OPERATOR_FEATURE_NAME_PATTERN = r"^[\w_]+$"
"""Operator feature name pattern (alphanumeric with underscores).

Rationale: Feature names are internal identifiers.
Allows: word characters and underscores
Example: "content", "doc_id_hash", "num_words", "avg_word_length"
"""

# ============================================================================
# FLOW-SPECIFIC CONSTRAINTS
# ============================================================================
# Organized by category for easy maintenance and reference.
# All constraints validated against IBM OpenAPI validator requirements.

# Identity Field Lengths

# Content Field Lengths
NAME_MIN_LENGTH = 1
NAME_MAX_LENGTH = 256
TYPE_MIN_LENGTH = 1
TYPE_MAX_LENGTH = 256
DESCRIPTION_MIN_LENGTH = 0  # Allow empty strings for optional descriptions
DESCRIPTION_MAX_LENGTH = 10000
TAG_MIN_LENGTH = 1
TAG_MAX_LENGTH = 256

# Version Field Lengths
VERSION_MIN_LENGTH = 1
VERSION_MAX_LENGTH = 10  # Supports versions like "99.99"

# URL Field Lengths
HREF_MIN_LENGTH = 1
HREF_MAX_LENGTH = 256
URL_MIN_LENGTH = 1
URL_MAX_LENGTH = 1000  # Full URLs with query params can be longer

# Datetime Field Lengths
DATETIME_MIN_LENGTH = 20  # "2024-01-01T00:00:00Z"
DATETIME_MAX_LENGTH = 35  # "2024-01-01T00:00:00.123456+00:00"

# Array Constraints
TAGS_ARRAY_MIN = 0  # Tags are optional
TAGS_ARRAY_MAX = 36
FLOWS_ARRAY_MIN = 0  # Empty result sets are valid
FLOWS_ARRAY_MAX = 100  # Maximum items per page
OPERATORS_ARRAY_MIN = 1  # At least one operator required
OPERATORS_ARRAY_MAX = 10000  # Maximum operators per flow

# Pagination Constraints
OFFSET_MIN = 0  # 0-based offset
OFFSET_MAX = 1000000  # Reasonable upper limit
LIMIT_MIN = 1  # At least one item per page
LIMIT_MAX = 100  # Prevents excessive page sizes
TOTAL_COUNT_MIN = 0  # Empty collections are valid
TOTAL_COUNT_MAX = 1000000  # Reasonable upper limit

# Operator Field Lengths
OPERATOR_TYPE_MIN_LENGTH = 1
OPERATOR_TYPE_MAX_LENGTH = 50
OPERATOR_LABEL_MIN_LENGTH = 1
OPERATOR_LABEL_MAX_LENGTH = 256
OPERATOR_CATEGORY_MIN_LENGTH = 1
OPERATOR_CATEGORY_MAX_LENGTH = 50
OPERATOR_DESCRIPTION_MIN_LENGTH = 1
OPERATOR_DESCRIPTION_MAX_LENGTH = 10000
OPERATOR_FEATURE_DESCRIPTION_MIN_LENGTH = 1
OPERATOR_FEATURE_DESCRIPTION_MAX_LENGTH = 10000
OPERATOR_FEATURE_NAME_MIN_LENGTH = 1
OPERATOR_FEATURE_NAME_MAX_LENGTH = 100

# Operator Array Constraints
OPERATOR_FEATURES_MIN = 0  # Some operators have no features
OPERATOR_FEATURES_MAX = 100  # Maximum features per operator
OPERATOR_REQUIRED_FEATURES_MIN = 0  # Most operators have no required features
OPERATOR_REQUIRED_FEATURES_MAX = 50  # Maximum required features
OPERATOR_ATTRIBUTES_MIN = 0  # Some operators have no attributes
OPERATOR_ATTRIBUTES_MAX = 100  # Maximum attributes per operator

# Job Parameters and Configuration
PARAM_NAME_MIN_LENGTH = 1
PARAM_NAME_MAX_LENGTH = 128
PARAM_VALUE_MIN_LENGTH = 1
PARAM_VALUE_MAX_LENGTH = 1000
CONFIG_VALUE_MIN_LENGTH = 1
CONFIG_VALUE_MAX_LENGTH = 1000
METADATA_VALUE_MIN_LENGTH = 1
METADATA_VALUE_MAX_LENGTH = 1000

# Array Limits
JOB_PARAMS_MIN_ITEMS = 0
JOB_PARAMS_MAX_ITEMS = 100
NODE_SEQUENCE_MIN_ITEMS = 0
NODE_SEQUENCE_MAX_ITEMS = 1000
NODE_METADATA_MIN_ITEMS = 0
NODE_METADATA_MAX_ITEMS = 1000

# List Response Limits
JOB_RUNS_LIST_MIN_ITEMS = 0
JOB_RUNS_LIST_MAX_ITEMS = 1000
LIST_COUNT_MIN = 0
LIST_COUNT_MAX = 1000
LIST_TOTAL_MIN = 0
LIST_TOTAL_MAX = 1000000

# Asset Reference
ASSET_REF_TYPE_MIN_LENGTH = 1
ASSET_REF_TYPE_MAX_LENGTH = 64

# ============================================================================
# EXAMPLE VALUES
# ============================================================================
# Realistic example values for documentation and testing.
# All examples pass validation rules defined above.

# UUID Examples (valid v4 UUIDs)
UUID_EXAMPLE = "550e8400-e29b-41d4-a716-446655440000"
UUID_EXAMPLE_2 = "9a5137a7-15d5-431c-b945-b147a3043694"
UUID_EXAMPLE_3 = "123e4567-e89b-12d3-a456-426614174000"

# Flow Definition Example (Elyra format)
DEFINITION_EXAMPLE: dict[str, Any] = {
    "doc_type": "pipeline",
    "version": "3.0",
    "pipelines": [
        {
            "id": UUID_EXAMPLE,
            "nodes": [],
            "app_data": {"ui_data": {}, "version": 3.0},
        }
    ],
    "schemas": [],
}
"""Example flow definition in Elyra pipeline format.

This is one of two supported formats:
1. Elyra format (shown here): Legacy format with doc_type, version, pipelines, schemas
2. DAG format: Modern format with nodes and edges arrays

Both formats are validated by validate_flow_definition() in common.util.core.validation.
"""

# ============================================================================
# JSON SCHEMA EXTRAS
# ============================================================================
# Additional schema constraints for OpenAPI generation.
# These provide item-level validation for arrays.

TAG_ITEMS_SCHEMA: dict = {
    "items": {
        "type": "string",
        "minLength": TAG_MIN_LENGTH,
        "maxLength": TAG_MAX_LENGTH,
        "pattern": TAG_PATTERN,
    }
}
"""JSON schema for tag array items.

Rationale: OpenAPI requires item-level constraints for arrays.
This ensures each tag in the array is validated individually.
Applied via json_schema_extra parameter in Field definitions.
"""

# ============================================================================
# FIELD DESCRIPTIONS
# ============================================================================
# Organized by category for easy reference and maintenance.
# Descriptions are concise but informative for API documentation.

# Identity Field Descriptions
FLOW_ID_DESC = "Unique identifier for the flow (UUID format)"
CONTAINER_ID_DESC = "UUID of the container (project/space) this flow belongs to"
CREATED_BY_DESC = "User identifier of the flow creator"
MODIFIED_BY_DESC = "User identifier of the last person to modify the flow"

# Content Field Descriptions
NAME_DESC = "Human-readable name for the flow"
DESCRIPTION_DESC = "Detailed description of the flow's purpose and functionality"
DEFINITION_DESC = (
    "Flow definition in DAG or Elyra format. Supports: "
    "DAG format with {'nodes': [...], 'edges': [...]} structure, "
    "and Elyra pipeline format with doc_type, version, pipelines, and schemas fields"
)

# Tag Field Descriptions
TAGS_DESC = "List of tags for categorizing and filtering flows"
TAGS_DESC_DEDUP = "List of tags for categorizing and filtering flows (duplicates removed automatically)"
TAGS_DESC_ALWAYS_PRESENT = "List of tags for categorizing and filtering flows (always present, empty array if no tags)"

# Container Field Descriptions
CONTAINER_KIND_DESC = "Container type: must be 'project' or 'space' if provided"
CONTAINER_KIND_DESC_SHORT = "Container type: 'project' or 'space'"

# Version Field Descriptions
FLOW_VERSION_DESC = "Version of the flow definition format"
FLOW_VERSION_DESC_DEFAULT = "Version of the flow definition format (defaults to '2.0')"

# Visibility Field Descriptions
IS_HIDDEN_DESC = "Whether the flow should be hidden from default listings"
IS_HIDDEN_DESC_RESPONSE = "Whether the flow is hidden from default listings"

# Timestamp Field Descriptions
CREATED_ON_DESC = "Timestamp when the flow was created (ISO 8601 format)"
MODIFIED_ON_DESC = "Timestamp when the flow was last modified (ISO 8601 format)"

# URL Field Descriptions
HREF_DESC = "API URL reference to this flow resource"

# Pagination Field Descriptions
FLOWS_LIST_DESC = "List of flows in the current page"
TOTAL_COUNT_DESC = "Total number of flows across all pages"
OFFSET_DESC = "Current offset position in the result set"
LIMIT_DESC = "Maximum number of flows per page"
FIRST_URL_DESC = "URL to the first page of results"
NEXT_URL_DESC = "URL to the next page of results (null if no more pages)"
PREV_URL_DESC = "URL to the previous page of results (null if on first page)"

# Job Run, Node Field Descriptions
NODE_SEQUENCE_DESC = "Ordered list of node IDs in execution sequence"

# Operator Field Descriptions
OPERATOR_TYPE_DESC = "Data type of the feature (e.g., 'string', 'int64', 'double', 'float', 'int32', 'boolean', 'list')"
OPERATOR_FEATURE_DESCRIPTION_DESC = "Human-readable description of the feature"
OPERATOR_FEATURE_NAME_DESC = "Human-readable display name for the feature"
OPERATOR_FEATURE_REQUIRED_DESC = "Whether this feature is required"
OPERATOR_FEATURE_DEFAULT_DESC = "Default value for the feature"
OPERATOR_FEATURE_FILTER_DESC = "Whether this feature can be used for filtering"
OPERATOR_FEATURE_VECTOR_DB_DESC = "Whether this feature can be used in vector database operations"
OPERATOR_FEATURE_OPENSEARCH_DESC = "Whether this feature can be stored in OpenSearch"
OPERATOR_FEATURE_MANDATORY_VECTOR_DB_DESC = "Whether this feature is mandatory for vector database operations"
OPERATOR_FEATURE_IS_PRIMARY_DESC = "Whether this feature is the primary key"
OPERATOR_FEATURE_TAGS_DESC = "Tags for this feature (e.g., 'mandatory', 'primary', 'internal_feature')"
OPERATOR_FEATURE_PROPERTIES_DESC = "Nested property definitions for structured/JSON-type attributes"
OPERATOR_FEATURE_VALID_VALUES_DESC = "List of valid values for constrained attributes"
OPERATOR_FEATURE_PROVIDERS_DESC = "Per-provider JSON Schema definitions for provider_config fields, keyed by provider name (e.g., 'opensearch', 'litellm'). Each value is a JSON Schema object produced by model_json_schema()."
OPERATOR_LABEL_DESC = "Human-readable label for the operator"
OPERATOR_CATEGORY_DESC = "Category of the operator"
OPERATOR_DESCRIPTION_DESC = "Detailed description of the operator's functionality"
OPERATOR_FEATURES_DESC = "Dictionary of features provided by this operator"
OPERATOR_REQUIRED_FEATURES_DESC = "List of feature names required by this operator"
OPERATOR_ATTRIBUTES_DESC = "Dictionary of configuration attributes/parameters for this operator"
OPERATOR_OWNER_DESC = "Owner of the operator ('docpipe' for built-in operators, None for custom)"
OPERATOR_IS_AVAILABLE_DESC = "Whether this operator is currently available in the system"

# ============================================================================
# FIELD FACTORY FUNCTIONS
# ============================================================================
# Factory functions for fields with complex logic or reused configurations.
# Simple fields should use Field() directly in DTOs for clarity.
#
# Only 1 factory remains after refactoring:
# - datetime_field: Complex json_schema_extra structure for OpenAPI compliance
#
# Why only one factory?
# - Previous factories (name_field, description_field, etc.) were removed
# - They added unnecessary indirection without significant value
# - Direct Field() usage in DTOs is clearer and more maintainable
# - datetime_field remains because its json_schema_extra is complex and reused


def datetime_field(description: str, example: str, **kwargs):
    """Create a datetime field with ISO 8601 format constraints.

    This factory exists because datetime fields require complex json_schema_extra
    configuration for OpenAPI compliance. The json_schema_extra includes format,
    length constraints, and pattern validation for the serialized string representation.

    Why This Factory Exists:
        - Datetime fields need multiple json_schema_extra properties for OpenAPI
        - Configuration is identical for created_on and modified_on
        - Centralizing prevents duplication and ensures consistency
        - OpenAPI "date-time" format requires specific schema structure

    Args:
        description: Field description for API documentation
        example: Example datetime value in ISO 8601 format (e.g., "2026-04-01T11:00:00Z")
        **kwargs: Additional Field parameters (passed through to Field())

    Returns:
        FieldInfo: Pydantic FieldInfo object with datetime-specific OpenAPI schema constraints.
            Must be used with a `datetime` type annotation in the model.
    """
    return Field(
        description=description,
        examples=[example],
        json_schema_extra={
            "type": "string",
            "format": "date-time",  # OpenAPI standard format
            "minLength": DATETIME_MIN_LENGTH,
            "maxLength": DATETIME_MAX_LENGTH,
            "pattern": DATETIME_PATTERN,
        },
        **kwargs,
    )


# ============================================================================
# DOCUMENT LIBRARY SPECIFIC CONSTANTS
# ============================================================================
# Constants for Document Library DTOs following the same pattern as Flow DTOs.
# Document Libraries are collections of Document Sets with aggregate metadata.
#
# Note: Document Libraries have stricter name validation than generic names:
# - Must be 3-128 characters (not 1-256)
# - Must start with a letter
# - Can only contain letters, digits, spaces, and underscores (no hyphens or special chars)

# Document Library Name Validation (stricter than generic NAME_* constants)
DOCUMENT_LIBRARY_NAME_MIN_LENGTH = 3  # Minimum 3 characters for library names
DOCUMENT_LIBRARY_NAME_MAX_LENGTH = 128  # Maximum 128 characters (not 256)
DOCUMENT_LIBRARY_NAME_PATTERN = (
    r"^[a-zA-Z][a-zA-Z0-9_ ]*$"  # Must start with letter, alphanumeric with spaces/underscores only
)

# Document Library Field Descriptions
DOCUMENT_LIBRARY_ID_DESC = "Unique identifier for the document library (UUID format)"
DOCUMENT_LIBRARY_NAME_DESC = "Unique document library name"
DOCUMENT_LIBRARY_DESCRIPTION_DESC = "Optional human-readable description of the document library"
DOCUMENT_LIBRARY_PURPOSE_DESC = "Purpose or use case for the document library"
DOCUMENT_LIBRARY_ORIGINAL_SIZE_DESC = "Aggregate original size from all associated document sets (bytes)"
DOCUMENT_LIBRARY_FINAL_SIZE_DESC = "Aggregate processed size from all associated document sets (bytes)"
DOCUMENT_LIBRARY_TAGS_DESC = "Tags for categorizing and filtering document libraries"
DOCUMENT_LIBRARY_CREATED_BY_DESC = "User who created the document library"
DOCUMENT_LIBRARY_CREATED_AT_DESC = "Timestamp when the document library was created (ISO 8601 format)"
DOCUMENT_LIBRARY_UPDATED_AT_DESC = "Timestamp when the document library was last updated (ISO 8601 format)"
DOCUMENT_LIBRARY_DOCUMENTSET_IDS_DESC = "List of document set IDs associated with this library"
DOCUMENT_LIBRARY_DOCUMENTSET_COUNT_DESC = "Number of document sets in this library"
DOCUMENT_LIBRARY_METADATA_DESC = "Additional metadata as key-value pairs"

# Purpose Field Constraints
PURPOSE_MIN_LENGTH = 0
PURPOSE_MAX_LENGTH = 1024
PURPOSE_PATTERN = DESCRIPTION_PATTERN  # Same as description - allows all characters

# Size Field Constraints (int64 - JavaScript MAX_SAFE_INTEGER)
SIZE_MIN = 0
SIZE_MAX = 9007199254740991

# Document Set ID Array Constraints
DOCUMENTSET_IDS_ARRAY_MIN = 0
DOCUMENTSET_IDS_ARRAY_MAX = 1000

# Document Library List Response Constraints
DOCUMENT_LIBRARIES_ARRAY_MIN = 0
DOCUMENT_LIBRARIES_ARRAY_MAX = 100

# Document Library Pagination Descriptions
DOCUMENT_LIBRARIES_LIST_DESC = "List of document libraries in the current page"
DOCUMENT_LIBRARIES_TOTAL_DESC = "Total number of document libraries across all pages"
DOCUMENT_LIBRARIES_LIMIT_DESC = "Maximum number of document libraries per page"

# Additional Document Library Field Aliases for DTO compatibility
LIBRARY_ID_DESC = DOCUMENT_LIBRARY_ID_DESC
LIBRARY_ID_EXAMPLE = UUID_EXAMPLE
LIBRARY_NAME_DESC = DOCUMENT_LIBRARY_NAME_DESC
LIBRARY_NAME_MIN_LENGTH = DOCUMENT_LIBRARY_NAME_MIN_LENGTH  # 3 (not generic 1)
LIBRARY_NAME_MAX_LENGTH = DOCUMENT_LIBRARY_NAME_MAX_LENGTH  # 128 (not generic 256)
LIBRARY_NAME_PATTERN = DOCUMENT_LIBRARY_NAME_PATTERN  # Stricter pattern (must start with letter)
LIBRARY_DESCRIPTION_DESC = DOCUMENT_LIBRARY_DESCRIPTION_DESC
LIBRARY_DESCRIPTION_MIN_LENGTH = DESCRIPTION_MIN_LENGTH
LIBRARY_DESCRIPTION_MAX_LENGTH = 1000  # Library description is shorter than flow description
LIBRARY_CREATED_AT_DESC = DOCUMENT_LIBRARY_CREATED_AT_DESC
LIBRARY_LAST_MODIFIED_DESC = DOCUMENT_LIBRARY_UPDATED_AT_DESC
LIBRARY_DOCUMENT_SET_IDS_DESC = DOCUMENT_LIBRARY_DOCUMENTSET_IDS_DESC
LIBRARY_TOTAL_DOCUMENT_SETS_DESC = DOCUMENT_LIBRARY_DOCUMENTSET_COUNT_DESC
LIBRARY_TOTAL_DOCUMENTS_DESC = "Total number of documents across all document sets in the library"
LIBRARY_TOTAL_SIZE_BYTES_DESC = "Total size in bytes across all document sets in the library"
LIBRARY_LIMIT_DESC = DOCUMENT_LIBRARIES_LIMIT_DESC
LIBRARY_LIMIT_MIN = LIMIT_MIN
LIBRARY_LIMIT_MAX = LIMIT_MAX
LIBRARY_OFFSET_DESC = "Number of document libraries skipped before this page"
LIBRARY_OFFSET_MIN = OFFSET_MIN
LIBRARY_OFFSET_MAX = OFFSET_MAX
LIBRARY_TOTAL_COUNT_DESC = DOCUMENT_LIBRARIES_TOTAL_DESC
DOCUMENT_LIBRARIES_OFFSET_DESC = "Number of document libraries skipped before this page"
