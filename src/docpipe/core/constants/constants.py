"""Project-wide string constants, enums, and configuration keys for docpipe."""

import os
from enum import Enum, StrEnum
from pathlib import Path
from typing import ClassVar, Final, TypedDict

# Import OperatorConstants for re-export


def _find_project_root() -> Path:
    """Find project root by searching upward for docpipe package structure.

    Looks for directories containing integrations/, storage/, and core/
    which indicates the docpipe package root, then returns two levels up
    to get the actual project root.

    Returns:
        Path: Project root directory containing docling-pipelines-config.yaml

    Examples:
        Container: /opt/app-root/src/docpipe -> /opt/app-root
        Local: /path/to/project/src/docpipe -> /path/to/project
        Library consumer: process cwd when docling-pipelines-config.yaml is present there
    """
    current = Path(__file__).resolve()
    # 1. Walk up — works for standalone docpipe project
    for parent in [current, *list(current.parents)]:
        # Check if this directory has the docpipe package structure
        if (parent / "integrations").exists() and (parent / "storage").exists() and (parent / "core").exists():
            # Return two levels up: docpipe -> src -> project_root
            return parent.parent.parent

    # 2. Library consumer case — check the process working directory
    if (Path.cwd() / "docling-pipelines-config.yaml").exists():
        return Path.cwd()

    # 3. Last resort: use fixed parent count
    # constants.py -> constants -> core -> docpipe -> src -> project_root
    return Path(__file__).resolve().parents[5]


class DocpipeConstants:
    # Defines constants that are used across Docpipe service
    """Docpipeconstants."""

    DOCPIPE_DATA_PATH = "DOCPIPE_DATA_PATH"
    INPUT_EDGES = "input_edges"
    NODE_ID_REF = "node_id_ref"
    OUTPUT_EDGES = "output_edges"
    INPUT = "input"
    LOGGER_NAME = "docpipe"
    SESSION_INFO = "session_info"
    CONTEXT_ID = "context_id"
    FORCE_INGEST = "force_ingest"
    RETAIN_DELETED_DOCS = "retain_deleted_docs"
    RETAIN_DELETED_DOCS_DEFAULT = True
    DATA_FOLDER = "data_folder"
    OPERAND_NAMESPACE = "OPERAND_NAMESPACE"
    DAG = "dag"
    DEFINITION = "definition"
    DESCRIPTION = "description"
    FLOW = "flow"
    FLOW_ID = "flow_id"
    FLOW_NAME = "flow_name"
    FIELD_NAME = "field_name"
    FLOW_DESCRIPTION = "flow_description"
    FLOW_DEFINITION = "flow_definition"
    FLOW_SOURCE = "flow_source"
    JOB = "job"
    JOB_ID = "job_id"
    NODE_ID = "node_id"
    NODE_NAME = "node_name"
    JOB_RUN = "job_run"
    JOB_RUN_ID = "job_run_id"
    TRACK_PERF = "track_perf"
    DOCPIPE = "docpipe"
    METADATA = "metadata"
    TRACE_MEMORY_ALLOCATIONS = "TRACE_MEMORY_ALLOCATIONS"
    METRICS = "metrics"
    DEFAULT_TRANSACTION_ID = "TRANSACTION999"
    DOCPIPE_LOGS = "docpipe_logs"
    INCREMENTAL_PROCESSING_METADATA_PATH = "inc_process_metadata"
    INCREMENTAL_METADATA_REPOSITORY_CONFIG = "incremental_metadata"
    UNPROCESSED_DOCS_PATH = "unprocessed_docs"
    JOBS_STATS_PATH = "job-stats"
    NODE_STATS_PATH = "node-stats"
    TRANSACTION_ID = "transaction_id"
    OUTPUT_FOLDER = "output_folder"
    OUTPUT_FEATURES_TO_DROP = "output_features_to_drop"
    LINK_NAME = "link_name"
    UPDATED_FEATURES = "updated_features"
    NAME = "name"
    UNNAMED_FLOW = "Unnamed flow"
    UUID = "uuid"
    STATUS = "status"
    STATE = "state"
    MESSAGE = "message"
    LAST_UPDATED_AT = "last_updated_at"
    DETAILS = "details"
    JOBS = "jobs"
    RUNS = "runs"
    OPERATORS = "operators"
    DOCUMENTS = "documents"
    # Use absolute path based on this file's location to work from anywhere
    DOCUMENT_CLASSES_PATH = str(Path(__file__).parent.parent / "document_classes")
    OPERATOR_FILE = "operator_file"
    SUMMARY = "summary"
    VALIDATION_FAILED = "validation_failed"
    PYTHON_PATH = "PYTHONPATH"
    LOCAL = "local"
    STORAGE = "storage"
    STORAGE_IN_MEMORY = "in-memory"
    EXECUTE_TYPE = "execute_type"
    TRUE = "True"
    ABSTRACT_OPERATOR = "AbstractOperator"
    VALIDATING_FLOW = "validating_flow"
    SKIP_CUSTOM_OP_VALIDATION = "skip_custom_op_validation"
    SUCCESS = "success"
    TMP = "tmp"
    DATA_STORAGE_TYPE = "data_storage_type"
    DISABLE_VALIDATION = "disable_validation"
    TEMP_CONTENT_COLUMN = "_temp_content_for_extract"
    TEMP_PAGES_PROCESSED_COLUMN = "_temp_pages_processed"

    # Custom Operator Control
    ENABLE_CUSTOM_OPERATORS = "enable_custom_operators"
    ENABLE_CUSTOM_OPERATORS_DEFAULT = True

    # Operator Ownership Tiers
    OWNER_DOCPIPE = "docpipe"
    OWNER_CUSTOM = "custom"
    OWNER_ATTRIBUTE = "owner"

    # Operator Priority Map: lower number = higher priority
    # Used for resolving conflicts when multiple operators have the same short_name.
    # Additional owner tiers can be registered at runtime via OperatorFactory.register_owner_priority().
    # Built-in tiers are spaced at intervals of 100 to leave room for consumer tiers:
    #   0-99   : available for consumer tiers above OWNER_CUSTOM
    #   100    : OWNER_CUSTOM
    #   101-199: available for consumer tiers between OWNER_CUSTOM and OWNER_DOCPIPE
    #   200    : OWNER_DOCPIPE
    OPERATOR_PRIORITY_MAP: ClassVar[dict[str, int]] = {
        OWNER_CUSTOM: 100,
        OWNER_DOCPIPE: 200,
    }

    # Feature Flag States
    FEATURE_ENABLED = "enabled"
    FEATURE_DISABLED = "disabled"

    ENABLE_MICRO_BATCHING = "enable_micro_batching"
    MICRO_BATCH_SIZE = "micro_batch_size"
    DEFAULT_MICRO_BATCH_SIZE = 100
    BATCH_NUM = "batch_num"
    BATCH_ID = "batch_id"
    BATCH_COUNT = "batch_count"
    CONTINUE_ON_BATCH_FAILURE = "continue_on_batch_failure"
    CONTINUE_ON_BATCH_FAILURE_DEFAULT = False
    INGEST_NODE_ID = "ingest_node_id"
    # Batch-level concurrency control
    MAX_CONCURRENT_BATCHES = "max_concurrent_batches"
    DEFAULT_MAX_CONCURRENT_BATCHES = 10
    BUILD_VERSION = "BUILD_VERSION"
    PARQUET_BATCH_SIZE = 1000
    LANGUAGE_LABEL = "language_label"
    LANGUAGE_CODE = "language_code"
    SCRIPT_CODE = "script_code"
    SCRIPT_LABEL = "script_label"
    SUMMARY_MODEL_ID_KEY = "summarization_model_id"
    MAX_INPUT_TOKENS_DEFAULT = 8000
    OVERLAP_RATIO_DEFAULT = 0.2
    SUMMARY_SENTENCES_DEFAULT = 2
    SUMMARY_MAX_WORDS_DEFAULT = 20
    SUMMARY_MODEL_ID_DEFAULT = "granite4"
    FLOW_EXECUTION_EVENT_HANDLER = "flow_execution_event_handler"
    JOB_LOG_PATH = "job_log_path"
    FLOW_EXECUTE_LOG = "flow_execute.log"
    FLOW_DEFINITION_FILE = "flow_definition.json"
    START_TIME = "start_time"
    END_TIME = "end_time"
    DURATION = "duration"
    TOTAL_DOCS = "total_docs"
    PROCESSED_DOCS = "processed_docs"
    COMPLETED_DOCS = "completed_docs"
    FAILED_DOCS = "failed_docs"
    SKIPPED_DOCS = "skipped_docs"
    ORCHESTRATOR = "orchestrator"
    USER_ID = "user_id"
    ACCOUNT_ID = "account_id"
    USER_ENTITLEMENTS = "user_entitlements"
    HEARTBEAT_TIMESTAMP = "heartbeat_timestamp"
    DELETED_DOC_COUNT = "deleted_doc_count"
    TOTAL_PAGES_PROCESSED = "total_pages_processed"
    PAGE_TYPE_STATS = "page_type_stats"
    EXECUTION_TIME = "execution_time"
    CONTAINER_KIND = "container_kind"
    CONTAINER_ID = "container_id"
    NODE_STATS = "node_stats"
    BATCH_NODE_STATS = "batch_node_stats"

    # Document Library constants
    DOCUMENT_LIBRARY_TABLE_NAME = "document_libraries"
    LIBRARY_DOCUMENTSET_JUNCTION_TABLE = "library_documentset_junction"

    # Find project root by searching for marker files (pyproject.toml, .git)
    _DEFAULT_DATA_ROOT = _find_project_root() / "data"
    _DUCKDB_ROOT = Path(os.getenv(DOCPIPE_DATA_PATH, _DEFAULT_DATA_ROOT)).resolve()
    DOCUMENT_SET_DEFAULT_DB_PATH = str(_DUCKDB_ROOT / "duckdb" / "document_sets.duckdb")
    DOCUMENT_LIBRARY_DEFAULT_DB_PATH = DOCUMENT_SET_DEFAULT_DB_PATH
    JOB_STATS_DEFAULT_DB_PATH = str(_DUCKDB_ROOT / "duckdb" / "job_stats.duckdb")

    # Prefect Constants
    PREFECT_CONFIG = "prefect"
    STRATEGY = "strategy"
    WORK_POOL_NAME = "work_pool_name"
    DEPLOYMENT_NAME = "deployment_name"
    DEPLOYMENT_PATH = "deployment_path"
    IMAGE = "image"
    ENV = "env"
    IMAGE_PULL_POLICY = "image_pull_policy"
    NETWORKS = "networks"
    TYPE = "type"

    # Memmap related constants
    EMBEDDINGS_CACHE_FILE = "embeddings.bin"
    EMBEDDINGS_MEMMAP_FILE = "embeddings_memmap_file"
    CHUNKS_MEMMAP_FILE = "chunks_memmap_file"
    METADATA_SUFFIX = ".meta"

    # Feature flags
    # threshhold in MB after which persistent storage would be used for chunks and embeddings
    MEMMAP_THRESHOLD = "memmap_threshold"
    MEMMAP_THRESHOLD_DEFAULT = 100


class DocumentLibraryConstants:
    """Constants for Document Library validation and constraints.

    These constants define field length limits and value constraints
    used throughout the Document Library domain model and storage layer.
    """

    # Field length limits
    MAX_NAME_LENGTH = 128
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_PURPOSE_LENGTH = 1024
    MAX_CREATED_BY_LENGTH = 63
    MIN_HREF_LENGTH = 5
    MAX_HREF_LENGTH = 8000

    # Name validation pattern
    # Must start with letter, contain only letters/digits/spaces/underscores
    NAME_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_ ]*$"

    # Size value limits (JavaScript MAX_SAFE_INTEGER for JSON compatibility)
    MAX_SAFE_INTEGER = 9007199254740991

    # Bulk operation limits
    MAX_BULK_OPERATION_SIZE = 1000  # Maximum number of items in bulk operations


class DocpipeConfigKeys:
    """YAML configuration keys for Docpipe."""

    JOB_MANAGEMENT = "job_management"
    FRAMEWORK = "framework"
    STORE = "store"
    TYPE = "type"
    STORAGE_BACKEND = "storage_backend"
    FRAMEWORK_TYPE = "framework_type"
    STORAGE_CONFIG = "storage_config"
    FRAMEWORK_CONFIG = "framework_config"
    CONFIG = "config"
    STORAGE_INITIALIZED = "storage_initialized"
    RUN_MIGRATIONS = "run_migrations"
    BASE_DIR = "base_dir"
    POSTGRES = "postgres"
    LOCK_TIMEOUT = "lock_timeout"
    HOST = "host"
    PORT = "port"
    DATABASE = "database"
    USER = "user"
    PASSWORD = "password"  # pragma: allowlist secret  # nosec B105
    POOL_SIZE = "pool_size"
    MAX_OVERFLOW = "max_overflow"
    POOL_TIMEOUT = "pool_timeout"

    # Incremental metadata configuration keys
    INCREMENTAL_METADATA = "incremental_metadata"
    STORAGE = "storage"
    # Note: Use TYPE and CONFIG from above for storage_type and storage_config

    # Job run report configuration keys
    JOB_RUN_REPORT = "job_run_report"

    # Flow definition snapshot configuration keys
    FLOW_DEFINITION_SNAPSHOT = "flow_definition_snapshot"

    # Global storage configuration keys (shared defaults for all services)
    GLOBAL_STORAGE = "global_storage"

    # Docling converter pool configuration keys (docling.converter_pool.*)
    DOCLING = "docling"
    CONVERTER_POOL = "converter_pool"
    SIZE = "size"
    IDLE_TTL_SECONDS = "idle_ttl_seconds"


class EnvironmentVariables:
    """Environment variable names used across Docpipe runtime components."""

    PREFECT_API_URL = "PREFECT_API_URL"
    PREFECT_MODE = "PREFECT_MODE"
    PREFECT_LOGGING_EXTRA_LOGGERS = "PREFECT_LOGGING_EXTRA_LOGGERS"
    OLLAMA_HOST = "OLLAMA_HOST"
    PYTHONPATH = "PYTHONPATH"
    PREFECT_SERVER_API_MAX_PARAMETER_SIZE = "PREFECT_SERVER_API_MAX_PARAMETER_SIZE"

    # Logging Configuration
    DS_LOG_LEVEL = "DS_LOG_LEVEL"
    DPK_LOG_LEVEL = "DPK_LOG_LEVEL"

    # Custom Operator Control
    DOCPIPE_ENABLE_CUSTOM_OPERATORS = "DOCPIPE_ENABLE_CUSTOM_OPERATORS"
    DOCPIPE_CUSTOM_OPERATORS = "DOCPIPE_CUSTOM_OPERATORS"
    DOCPIPE_CONFIG_PATH = "DOCPIPE_CONFIG_PATH"

    # Secret Provider Control
    DOCPIPE_VAULT_ENABLED = "DOCPIPE_VAULT_ENABLED"  # "true" enables, "false" disables — overrides YAML config
    DOCPIPE_VAULT_PROVIDER_NAME = (
        "DOCPIPE_VAULT_PROVIDER_NAME"  # provider name used in vault:// URIs (default: hashicorp)
    )
    DOCPIPE_STORAGE_BACKEND = "DOCPIPE_STORAGE_BACKEND"
    DOCPIPE_FRAMEWORK_TYPE = "DOCPIPE_FRAMEWORK_TYPE"
    DOCPIPE_JOB_STATS_BASE_DIR = "DOCPIPE_JOB_STATS_BASE_DIR"
    DOCPIPE_POSTGRES_HOST = "DOCPIPE_POSTGRES_HOST"
    DOCPIPE_POSTGRES_PORT = "DOCPIPE_POSTGRES_PORT"
    DOCPIPE_POSTGRES_DB = "DOCPIPE_POSTGRES_DB"
    DOCPIPE_POSTGRES_USER = "DOCPIPE_POSTGRES_USER"
    DOCPIPE_POSTGRES_PASSWORD = "DOCPIPE_POSTGRES_PASSWORD"  # pragma: allowlist secret  # nosec B105

    # Docling converter pool (process-wide reuse of DocumentConverter / DocumentExtractor)
    DOCPIPE_DOCLING_CONVERTER_POOL_SIZE = "DOCPIPE_DOCLING_CONVERTER_POOL_SIZE"
    DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS = "DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS"

    # OpenLineage Configuration
    DOCPIPE_LINEAGE_ENABLED = "DOCPIPE_LINEAGE_ENABLED"
    DOCPIPE_LINEAGE_MODE = "DOCPIPE_LINEAGE_MODE"
    DOCPIPE_LINEAGE_NAMESPACE = "DOCPIPE_LINEAGE_NAMESPACE"
    DOCPIPE_LINEAGE_PRODUCER = "DOCPIPE_LINEAGE_PRODUCER"
    DOCPIPE_LINEAGE_STRICT = "DOCPIPE_LINEAGE_STRICT"

    DOCPIPE_EVENT_STREAMING_ENABLED = "DOCPIPE_EVENT_STREAMING_ENABLED"
    DOCPIPE_API_BASE_URL = "DOCPIPE_API_BASE_URL"
    KAFKA_BOOTSTRAP_SERVERS = "KAFKA_BOOTSTRAP_SERVERS"
    KAFKA_INPUT_TOPIC = "KAFKA_INPUT_TOPIC"
    KAFKA_GROUP_ID = "KAFKA_GROUP_ID"
    SCHEMA_REGISTRY_URL = "SCHEMA_REGISTRY_URL"


class LineageConstants:
    """Constants and defaults for OpenLineage integration."""

    # Emission modes
    MODE_FLOW = "flow"
    MODE_OPERATOR = "operator"

    # Environment-configured values with defaults
    DEFAULT_ENABLED = os.getenv(EnvironmentVariables.DOCPIPE_LINEAGE_ENABLED, "false")
    DEFAULT_MODE = os.getenv(EnvironmentVariables.DOCPIPE_LINEAGE_MODE, MODE_FLOW)
    DEFAULT_NAMESPACE = os.getenv(EnvironmentVariables.DOCPIPE_LINEAGE_NAMESPACE, "docpipe://local")
    DEFAULT_PRODUCER = os.getenv(
        EnvironmentVariables.DOCPIPE_LINEAGE_PRODUCER, "https://github.com/docling-project/docling-pipelines"
    )
    DEFAULT_STRICT = os.getenv(EnvironmentVariables.DOCPIPE_LINEAGE_STRICT, "false")

    # Standard dataset namespaces & schemes
    NAMESPACE_INMEMORY = "inmemory://"
    NAMESPACE_FILE = "file"
    NAMESPACE_GOOGLE_DRIVE = "googledrive://drive.google.com"
    NAMESPACE_DOCUMENT_SET = "docpipe://document_set"
    NAMESPACE_DROPBOX = "dropbox://api.dropbox.com"
    NAMESPACE_MILVUS_LITE = "milvus://lite"

    # Known storage & vector providers
    PROVIDER_FILESYSTEM = "filesystem"
    PROVIDER_LOCAL = "local"
    PROVIDER_FILE = "file"
    PROVIDER_S3 = "s3"
    PROVIDER_OPENSEARCH = "opensearch"
    PROVIDER_MILVUS = "milvus"
    PROVIDER_QDRANT = "qdrant"
    PROVIDER_WEAVIATE = "weaviate"
    PROVIDER_PINECONE = "pinecone"
    PROVIDER_CHROMA = "chroma"
    PROVIDER_BOX = "box"
    PROVIDER_SHAREPOINT = "sharepoint"
    PROVIDER_GOOGLE_DRIVE = "google_drive"
    PROVIDER_ONEDRIVE = "onedrive"
    PROVIDER_DROPBOX = "dropbox"
    PROVIDER_WEB = "web"

    # Job and processing types
    JOB_TYPE_FLOW = "FLOW"
    JOB_TYPE_OPERATOR = "OPERATOR"
    PROCESSING_TYPE_BATCH = "BATCH"
    INTEGRATION_NAME = "docling-pipelines"

    # Schema URLs
    JOB_TYPE_SCHEMA_URL = "https://openlineage.io/spec/facets/JobTypeJobFacet.json"
    SCHEMA_DATASET_FACET_URL = "https://openlineage.io/spec/facets/SchemaDatasetFacet.json"
    OUTPUT_STATISTICS_FACET_URL = "https://openlineage.io/spec/facets/OutputStatisticsOutputDatasetFacet.json"
    ERROR_MESSAGE_FACET_URL = "https://openlineage.io/spec/facets/ErrorMessageRunFacet.json"
    NOMINAL_TIME_FACET_URL = "https://openlineage.io/spec/facets/1-0-0/NominalTimeRunFacet.json"
    PARENT_RUN_FACET_URL = "https://openlineage.io/spec/facets/1-0-0/ParentRunFacet.json"
    DOCUMENTATION_JOB_FACET_URL = "https://openlineage.io/spec/facets/1-0-0/DocumentationJobFacet.json"

    # Custom facet schema URLs
    DOCPIPE_STATUS_FACET_URL = (
        "https://github.com/docling-project/docling-pipelines/schemas/docpipe-status-facet-1-0-0.json"
    )
    DOCPIPE_PROGRESS_FACET_URL = (
        "https://github.com/docling-project/docling-pipelines/schemas/docpipe-progress-facet-1-0-0.json"
    )
    DOCPIPE_NODE_STATS_FACET_URL = (
        "https://github.com/docling-project/docling-pipelines/spec/facets/1-0-0/DocpipeNodeStatsFacet.json"
    )
    DOCPIPE_NODE_STATUS_FACET_URL = (
        "https://github.com/docling-project/docling-pipelines/spec/facets/1-0-0/DocpipeNodeStatusFacet.json"
    )


class ServiceConstants:
    """Constants for external service configurations"""

    # Ollama service configuration
    DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    DEFAULT_OLLAMA_MAX_CONCURRENT_REQUESTS = 8  # Maximum concurrent requests for batch processing

    # Embeddings batch processing
    DEFAULT_EMBEDDINGS_BATCH_SIZE = 32  # Default batch size for embeddings generation
    # Default number of embedding sub-batch requests kept in flight at once for HTTP-based
    # providers (LiteLLM). Kept low so a single operator stays well below typical hosted-API
    # rate limits; a local Ollama server queues requests beyond its own OLLAMA_NUM_PARALLEL.
    DEFAULT_EMBEDDINGS_MAX_CONCURRENT_REQUESTS = 4
    # watsonx.ai embeddings: texts per request, and requests in flight (the service enforces
    # a per-instance limit of 8 req/s, so concurrency stays opt-in).
    DEFAULT_WATSONX_EMBEDDINGS_BATCH_SIZE = 800
    DEFAULT_WATSONX_EMBEDDINGS_MAX_CONCURRENT_REQUESTS = 1


class ProviderConstants:
    """Canonical provider name strings used across all provider-facing APIs.

    These values identify LLM/embedding providers in contexts that cut across
    operator categories (embeddings, chunking, classification, entity extraction,
    etc.) — for example, the GET /providers/{provider}/models endpoint.

    Use these constants anywhere a provider is identified by name at the service
    or API layer rather than within a single operator's configuration.
    """

    OLLAMA: Final[str] = "ollama"
    WATSONX: Final[str] = "watsonx"


class DoclingClientConstants:
    """Constants for Docling Serve client retry logic"""

    # Retry configuration for 404 errors during polling
    # These handle pod restarts, HPA scaling, and load balancer routing issues
    STATUS_404_MAX_RETRIES = 3
    STATUS_404_BACKOFF_BASE = 1.0  # seconds


class DoclingClientConfigConstants:
    """Constants for Docling entity extraction custom model configuration

    Note: Only inline model is supported. API model is not supported by DocumentExtractor.
    """

    # Configuration keys
    VLM_PIPELINE = "vlm_pipeline"
    MODEL_TYPE = "model_type"
    INLINE_MODEL = "inline_model"

    # Model types
    MODEL_TYPE_INLINE = "inline"

    # Inline model parameters
    REPO_ID = "repo_id"
    INFERENCE_FRAMEWORK = "inference_framework"
    SCALE = "scale"
    TEMPERATURE = "temperature"
    MAX_NEW_TOKENS = "max_new_tokens"
    LOAD_IN_8BIT = "load_in_8bit"
    TORCH_DTYPE = "torch_dtype"
    PROMPT = "prompt"
    RESPONSE_FORMAT = "response_format"

    # Default values
    DEFAULT_INFERENCE_FRAMEWORK = "transformers"
    DEFAULT_SCALE = 2.0
    DEFAULT_TEMPERATURE = 0.0
    DEFAULT_MAX_NEW_TOKENS = 4096
    DEFAULT_LOAD_IN_8BIT = True
    DEFAULT_TORCH_DTYPE = "bfloat16"
    DEFAULT_RESPONSE_FORMAT = "markdown"
    DEFAULT_PROMPT = ""


class Metrics:
    """Metrics."""

    class External:
        """External."""

        JOB_RUN_STATUS = "job_run_status"
        TOTAL_DOCS = "documents_in_scope"
        COMPLETED_DOCS_COUNT = "completed_docs_count"
        TOTAL_DOCS_COUNT_FROM_LOGS = "total_docs"
        PROCESSED_DOCS = "processed_docs"
        PROCESSED_ROWS = "processed_rows"
        FAILED_DOCS_COUNT = "failed_docs_count"
        FAILED_DOCS = "failed_docs"
        SKIPPED_DOCS_COUNT = "skipped_docs_count"
        SKIPPED_DOCS = "skipped_docs"
        DOCUMENT_URL = "document_url"
        TOTAL_PAGES_CONVERTED = "total_pages_converted"
        NODE_STATUS = "node_status"
        UNPROCESSED_DOC_COUNT = "unprocessed_doc_count"
        DELETED_DOC_COUNT = "deleted_doc_count"
        START_TIME = "start_time"
        END_TIME = "end_time"
        REMOVED_DOCUMENTS = "removed_documents"
        PROCESSING_MESSAGE = "processing_message"
        TOTAL_CHUNKS = "total_chunks"
        CHUNKS_PROCESSED = "chunks_processed"
        CHUNKS_FAILED = "chunks_failed"
        CHUNKS_SKIPPED_EXISTING = "chunks_skipped_existing"
        TOTAL_CHUNKS_TO_INDEX = "total_chunks_to_index"
        CHUNKS_INDEXED_SUCCESSFULLY = "chunks_indexed_successfully"
        CHUNKS_FAILED_TO_INDEX = "chunks_failed_to_index"
        ERROR = "error"

        # SQL Filter operator metrics
        DOCS_BEFORE_FILTER = "docs_before_filter"
        DOCS_AFTER_FILTER = "docs_after_filter"
        BYTES_BEFORE_FILTER = "bytes_before_filter"
        BYTES_AFTER_FILTER = "bytes_after_filter"
        COLUMNS_BEFORE_FILTER = "columns_before_filter"
        COLUMNS_AFTER_FILTER = "columns_after_filter"

        # VectorDB / indexing metrics
        RECORDS_INSERTED = "records_inserted"
        RECORDS_FAILED = "records_failed"

        # Page type breakdown
        PAGE_TYPE_STATS = "page_type_stats"

    class Internal:
        """Internal."""

        DELETED_FROM_LAST_RUN = "deleted_from_last_run"
        ALL_DOC_IDS = "all_doc_ids"
        BRANCHES = "branches"
        NON_RECOVERABLE_DOCS_TABLE = "non_recoverable_docs_table"

    # Metrics that require atomic aggregation to prevent race conditions
    AGGREGATION_METRICS = frozenset({External.TOTAL_PAGES_CONVERTED, External.DELETED_DOC_COUNT})


# Internal metrics used in multiple places so making it as a global variable
internal_metrics = {value for name, value in vars(Metrics.Internal).items() if not name.startswith("__")}


class TaskType(Enum):
    """Tasktype."""

    EXECUTE_FLOW = "execute_flow"
    VALIDATE_FLOW = "validate_flow"
    NON_EXECUTE_FLOW = "non_execute_flow"
    SET_NODE_FEATURES = "set_node_features"
    ADD_OPERATOR_CARD_DETAILS = "add_operator_card_details"


class DocumentConstants:
    """
    Consolidated document-related constants.
    Merged from DocumentClassKeys and DocsStructure.
    """

    # Top level keys
    SCHEMA = "document_class_schema"
    DOCUMENT = "document"
    TARGET_TABLES = "target_tables"

    # Table keys
    TABLE_NAME = "name"
    TABLE_DESCRIPTION = "description"
    COLUMNS = "columns"

    # Column keys
    COLUMN_NAME = "name"
    COLUMN_TYPE = "type"
    COLUMN_DESCRIPTION = "description"
    SOURCE = "source"

    # Transform keys
    TRANSFORM = "transform"
    TRANSFORM_NAME = "transform_name"
    ARGUMENTS = "arguments"

    # Argument keys
    ARG_NAME = "name"
    ARG_VALUE = "value"
    FIELD = "field"

    # Document structure type (from DocsStructure TypedDict)
    class Structure(TypedDict):
        """Document structure definition"""

        id: str
        name: str
        reason: str
        document_url: str


class OrchestratorType:
    """Orchestratortype."""

    PYTHON = "python"


class DataSourceType:
    """Datasourcetype."""

    AMAZON_S3 = "Amazon S3"
    BOX = "Box"
    FILENET = "AppConnectAdapter - FileNet"
    SHAREPOINT = "AppConnectAdapter - MsSharePoint"
    WXD_PRESTO = "IBM watsonx.data Presto"
    ICEBERG_METASTORE = "Iceberg metastore"
    SLACK = "Slack"
    CONFLUENCE = "Confluence"
    IBM_COS = "IBM Cloud Object Storage"


class ExecutionStatus(StrEnum):
    """Executionstatus."""

    QUEUED = "Queued"
    PENDING = "Pending"
    STARTING = "Starting"
    RUNNING = "Running"
    PAUSED = "Paused"
    RESUMING = "Resuming"
    CANCELING = "Canceling"
    CANCELED = "Canceled"
    FAILING = "Failing"
    FAILED = "Failed"
    COMPLETED = "Completed"
    COMPLETED_WITH_ERRORS = "CompletedWithErrors"
    COMPLETED_WITH_WARNINGS = "CompletedWithWarnings"
    SKIPPED = "Skipped"
    ABORTED = "Aborted"


# efficient membership checks (O(1) instead of O(n))
TERMINAL_JOB_STATUSES = frozenset(
    [
        ExecutionStatus.COMPLETED,
        ExecutionStatus.COMPLETED_WITH_ERRORS,
        ExecutionStatus.COMPLETED_WITH_WARNINGS,
        ExecutionStatus.CANCELED,
        ExecutionStatus.FAILED,
        ExecutionStatus.ABORTED,
    ]
)

TERMINAL_NODE_STATES = frozenset(TERMINAL_JOB_STATUSES | {ExecutionStatus.SKIPPED})

# Visual status indicators for batch execution summary (mirrors Enterprise NodeExecutionLogConstants)
STATUS_INDICATOR_MAP: dict[str, str] = {
    ExecutionStatus.COMPLETED.value: "✓",
    ExecutionStatus.FAILED.value: "✗",
    ExecutionStatus.COMPLETED_WITH_ERRORS.value: "✗",
    ExecutionStatus.COMPLETED_WITH_WARNINGS.value: "✓",
    ExecutionStatus.SKIPPED.value: "⊘",
    ExecutionStatus.RUNNING.value: "•",
    ExecutionStatus.PENDING.value: "○",
    ExecutionStatus.QUEUED.value: "○",
    ExecutionStatus.CANCELED.value: "⊗",
    ExecutionStatus.CANCELING.value: "•",
}

active_states = [
    ExecutionStatus.STARTING,
    ExecutionStatus.RUNNING,
    ExecutionStatus.RESUMING,
    ExecutionStatus.CANCELING,
]


class ValidationStatus(StrEnum):
    """Validationstatus."""

    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"


class DataTypes:
    """
    Data type constants for attributes.
    Renamed from AttributeDataTypes for brevity.
    """

    BOOLEAN = "boolean"
    CRN = "crn"
    DATE = "date"
    DOUBLE = "double"
    FLOAT = "sfloat"
    ENUM = "enum"
    INTEGER = "int64"
    JSON = "json"
    LIST = "list"
    STRING = "string"
    TIME = "time"
    TIMESTAMP = "timestamp"


class LLMConstants:
    """
    Consolidated LLM-related constants.
    Includes model names and catalog types.
    """

    class Models(StrEnum):
        """Supported LLM model names"""

        OPENAI = "openai"
        WATSONX = "watsonx"
        LLAMA_2 = "llama2"
        MISTRAL = "mistral"
        GEMMA = "gemma"
        CODELLAMA = "codellama"
        PHI = "phi"
        NEURAL_CHAT = "neural-chat"
        FALCON = "falcon"
        OPENHERMES = "openhermes"
        DEEPSEEK = "deepseek"
        QWEN = "qwen"
        MIXTRAL = "mixtral"
        GRANITE_3_2_2B = "granite3.2:2b"
        GRANITE_3_2_8B = "granite3.2:8b"

    class CatalogTypes:
        """Supported catalog types"""

        ICEBERG = "iceberg"
        SNOWFLAKE = "snowflake"
        JDBC = "jdbc"
        NESSIE = "nessie"

    class ValidationKeys:
        """Keys used in validation result dictionaries"""

        VALID = "valid"
        CONTEXT = "context"
        PROVIDER = "provider"
        ERRORS = "errors"
        WARNINGS = "warnings"

    class ValidationContexts:
        """Validation context identifiers"""

        INFERENCE = "inference"
        EMBEDDING = "embedding"
        DETECTION = "detection"


class ProcessingConstants:
    """
    Consolidated processing-related constants.
    Merged from MemoryLogPhases, ProcessingMessageConstants, and LiteralConstants.
    """

    # Memory log phases
    MEMORY_LOG_START = "Start"
    MEMORY_LOG_TRANSFORM_COMPLETED = "Transform Completed"

    # Processing messages
    DOCS_PROCESSED = "documents processed."
    MORE_DOCS_TO_PROCESS = "There are more documents to process. Run again to process."

    # Literal constants
    NEWLINE: str = "\n"
    SPACE: str = " "


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================
# These aliases maintain backward compatibility with code using old class names.
# New code should use the consolidated classes above.

# DocumentClassKeys -> DocumentConstants
DocumentClassKeys = DocumentConstants

# DocsStructure -> DocumentConstants.Structure
DocsStructure = DocumentConstants.Structure

# AttributeDataTypes -> DataTypes
AttributeDataTypes = DataTypes

# LlmModelName -> LLMConstants.Models
LlmModelName = LLMConstants.Models

# CatalogType -> LLMConstants.CatalogTypes
CatalogType = LLMConstants.CatalogTypes


# MemoryLogPhases constants -> ProcessingConstants
class MemoryLogPhases:
    """Backward compatibility wrapper for ProcessingConstants memory log phases"""

    START = ProcessingConstants.MEMORY_LOG_START
    TRANSFORM_COMPLETED = ProcessingConstants.MEMORY_LOG_TRANSFORM_COMPLETED


# ProcessingMessageConstants -> ProcessingConstants
class ProcessingMessageConstants:
    """Backward compatibility wrapper for ProcessingConstants messages"""

    DOCS_PROCESSED = ProcessingConstants.DOCS_PROCESSED
    MORE_DOCS_TO_PROCESS = ProcessingConstants.MORE_DOCS_TO_PROCESS


# LiteralConstants -> ProcessingConstants
class LiteralConstants:
    """Backward compatibility wrapper for ProcessingConstants literals"""

    NEWLINE: str = ProcessingConstants.NEWLINE
    SPACE: str = ProcessingConstants.SPACE
