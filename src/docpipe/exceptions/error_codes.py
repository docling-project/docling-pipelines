from enum import StrEnum


class ErrorCode(StrEnum):
    # Flow validation and execution
    """Errorcode."""

    FLOW_VALIDATION_FAILED = "flow_validation_failed"
    FLOW_EXECUTION_FAILED = "flow_execution_failed"
    PREFECT_FLOW_TASK_FAILED = "prefect_flow_failed"

    # Flow CRUD operations
    FLOW_NOT_FOUND = "flow_not_found"
    FLOW_ALREADY_EXISTS = "flow_already_exists"
    FLOW_INVALID_DATA = "flow_invalid_data"
    FLOW_SAVE_ERROR = "flow_save_error"
    FLOW_LIST_ERROR = "flow_list_error"
    FLOW_DELETE_ERROR = "flow_delete_error"
    FLOW_UPDATE_ERROR = "flow_update_error"

    # Event mapping operations
    EVENT_MAPPING_NOT_FOUND = "event_mapping_not_found"
    EVENT_MAPPING_ALREADY_EXISTS = "event_mapping_already_exists"

    # Job run operations
    JOB_RUN_NOT_FOUND = "job_run_not_found"
    JOB_RUN_ALREADY_EXISTS = "job_run_already_exists"
    JOB_RUN_INVALID_STATE = "job_run_invalid_state"
    JOB_RUN_OPERATION_FAILED = "job_run_operation_failed"
    FLOW_STORAGE_ERROR = "flow_storage_error"

    # Document Set CRUD operations
    DOCUMENT_SET_NOT_FOUND = "document_set_not_found"
    DOCUMENT_SET_INVALID_DATA = "document_set_invalid_data"
    DOCUMENT_SET_STORAGE_ERROR = "document_set_storage_error"
    DOCUMENT_SET_ALREADY_EXISTS = "document_set_already_exists"
    DOCUMENT_SET_CONSTRAINT_VIOLATION = "document_set_constraint_violation"

    # Document Set Repository operations
    DOCUMENT_SET_REPOSITORY_ERROR = "document_set_repository_error"
    DOCUMENT_SET_REPOSITORY_CONNECTION_FAILED = "document_set_repository_connection_failed"
    DOCUMENT_SET_TRANSACTION_FAILED = "document_set_transaction_failed"

    # Document Set Data Store operations
    DOCUMENT_SET_DATA_STORE_ERROR = "document_set_data_store_error"
    DOCUMENT_SET_TABLE_NOT_FOUND = "document_set_table_not_found"
    DOCUMENT_SET_TABLE_ALREADY_EXISTS = "document_set_table_already_exists"
    DOCUMENT_SET_SCHEMA_MISMATCH = "document_set_schema_mismatch"

    # Operator errors
    OPERATOR_CONFIGURATION_INVALID = "operator_configuration_invalid"
    OPERATOR_EXECUTION_FAILED = "operator_execution_failed"
    OPERATOR_METADATA_FAILED = "operator_metadata_failed"
    SQL_FILTER_ERROR = "sql_filter_error"

    # Custom Operator operations
    CUSTOM_OPERATOR_NOT_FOUND = "custom_operator_not_found"
    CUSTOM_OPERATOR_ALREADY_EXISTS = "custom_operator_already_exists"
    CUSTOM_OPERATOR_INVALID_DATA = "custom_operator_invalid_data"

    # ACL extraction errors
    ACL_EXTRACTION_FAILED = "acl_extraction_failed"
    ACL_ADAPTER_INITIALIZATION_FAILED = "acl_adapter_initialization_failed"
    ACL_PROVIDER_NOT_SUPPORTED = "acl_provider_not_supported"
    ACL_AUTHENTICATION_FAILED = "acl_authentication_failed"
    ACL_PERMISSION_FETCH_FAILED = "acl_permission_fetch_failed"

    # Ollama integration
    OLLAMA_CONNECTION_FAILED = "ollama_connection_failed"
    OLLAMA_MODEL_NOT_FOUND = "ollama_model_not_found"

    # OpenSearch integration
    OPENSEARCH_CONNECTION_FAILED = "opensearch_connection_failed"
    OPENSEARCH_INDEX_ERROR = "opensearch_index_error"

    # Database operations - PostgreSQL
    DATABASE_MIGRATION_FAILED = "database_migration_failed"
    POSTGRES_CONNECTION_FAILED = "postgres_connection_failed"
    POSTGRES_OPERATION_FAILED = "postgres_operation_failed"
    POSTGRES_TRANSACTION_FAILED = "postgres_transaction_failed"
    POSTGRES_QUERY_FAILED = "postgres_query_failed"

    # Job stats store operations
    JOB_STATS_STORE_READ_FAILED = "job_stats_store_read_failed"
    JOB_STATS_STORE_WRITE_FAILED = "job_stats_store_write_failed"
    JOB_STATS_STORE_DELETE_FAILED = "job_stats_store_delete_failed"
    JOB_STATS_STORE_LIST_FAILED = "job_stats_store_list_failed"
    JOB_STATS_STORE_ATOMIC_UPDATE_FAILED = "job_stats_store_atomic_update_failed"
    JOB_STATS_STORE_INITIALIZATION_FAILED = "job_stats_store_initialization_failed"

    # Generic storage operations
    STORAGE_ERROR = "storage_error"
    STORAGE_VALIDATION_ERROR = "storage_validation_error"
    STORAGE_CONNECTION_ERROR = "storage_connection_error"

    # Configuration and external services
    INVALID_CONFIGURATION = "invalid_configuration"
    EXTERNAL_SERVICE_ERROR = "external_service_error"

    # REST client errors
    HTTP_ERROR = "http_error"
    CONNECTION_ERROR = "connection_error"
    INVALID_RESPONSE = "invalid_response"

    # Document Library CRUD operations
    DOCUMENT_LIBRARY_NOT_FOUND = "document_library_not_found"
    DOCUMENT_LIBRARY_ALREADY_EXISTS = "document_library_already_exists"
    DOCUMENT_LIBRARY_INVALID_DATA = "document_library_invalid_data"
    DOCUMENT_LIBRARY_STORAGE_ERROR = "document_library_storage_error"
    DOCUMENT_LIBRARY_DOCUMENTSET_NOT_FOUND = "document_library_documentset_not_found"

    # Document Class operations
    DOCUMENT_CLASS_LIST_FAILED = "document_class_list_failed"

    # Project CRUD operations
    PROJECT_NOT_FOUND = "project_not_found"
    PROJECT_ALREADY_EXISTS = "project_already_exists"
    PROJECT_INVALID_DATA = "project_invalid_data"
