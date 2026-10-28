# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
OperatorConstants with nested class organization.

All constants are organized into logical nested classes for better structure
and discoverability. Import and use as:
    from docpipe.core.constants.operator_constants import OperatorConstants
    index_name = config.get(OperatorConstants.VectorDB.INDEX_NAME)

All constants must be accessed through their nested class structure:
    - OperatorConstants.Operators.* for operator names
    - OperatorConstants.Columns.* for column names
    - OperatorConstants.Config.* for configuration keys
    - OperatorConstants.VectorDB.* for vector database settings
    - OperatorConstants.Types.* for data types
    - OperatorConstants.Extraction.* for extraction settings
    - OperatorConstants.ExtractionModes.* for extraction mode settings
    - OperatorConstants.LLM.* for LLM-specific settings
    - OperatorConstants.PIIHAP.* for PII/HAP settings
    - OperatorConstants.Filtering.* for filtering settings
    - OperatorConstants.Processing.* for processing settings
    - OperatorConstants.Metadata.* for metadata keys
    - OperatorConstants.Storage.* for storage settings
    - OperatorConstants.Misc.* for miscellaneous constants
"""

from enum import StrEnum
from typing import Final


class OperatorConstants:
    """Main constants class with nested subclasses for organization."""

    class Operators:
        """Operator name constants."""

        # Ingestion Operators
        INGEST: Final[str] = "ingest"
        INGEST_CSV: Final[str] = "ingest_csv"
        INGEST_SOURCE: Final[str] = "ingest_source"

        # Embeddings Operators
        EMBEDDINGS: Final[str] = "embeddings"

        # Extraction Operators
        ACL: Final[str] = "acl"
        ACL_OPERATOR: Final[str] = "acl_operator"
        EXTRACT_OPERATOR: Final[str] = "extract_operator"
        ENTITY_EXTRACT: Final[str] = "extract_entity"
        EXTRACT_JSON: Final[str] = "extract_json"

        # Processing Operators
        BRANCHING: Final[str] = "branching"
        CHUNKER: Final[str] = "chunker"
        DOC_ID_OPERATOR: Final[str] = "doc_id_hash"
        DOC_QUALITY: Final[str] = "doc_quality"
        EDEDUP: Final[str] = "ededup"
        LANG_DETECT: Final[str] = "lang_detect"
        LANG_DETECT_FASTTEXT: Final[str] = "lang_detect_fasttext"
        MERGE: Final[str] = "merge"
        ML_ENRICHMENT: Final[str] = "ml_enrichment"
        READABILITY: Final[str] = "readability"
        REDACTION: Final[str] = "redaction"
        REGEX_ANNOTATOR: Final[str] = "regex_annotator"
        PII_AND_HAP: Final[str] = "pii_and_hap"
        SQL_FILTER: Final[str] = "sql_filter"

        # Storage Operators
        DOCUMENT_SET: Final[str] = "document_set"
        ENTITY_CURATION_OPERATOR: Final[str] = "entity_curation_operator"
        ENTITY_STORE_OPERATOR: Final[str] = "entity_store"
        OPENSEARCH: Final[str] = "opensearch"
        VECTORDB: Final[str] = "vectordb"

        # Storage Output Operators
        STORAGE_OUTPUT: Final[str] = "storage_output"

        # Utility Operators
        DESIGN_FLOW_OUTPUT_OPERATOR: Final[str] = "design_flow_output"
        NOOP: Final[str] = "noop"

    class Columns:
        """DataFrame column name constants."""

        # Content and Document Columns
        ALLOWED_USERS: Final[str] = "allowed_users"
        BINARY_CONTENT: Final[str] = "binary_content"
        CHUNK: Final[str] = "chunk"
        CHUNKED_CONTENT: Final[str] = "chunked_content"
        CHUNK_SEQUENCE_NUMBER: Final[str] = "chunk_sequence_number"
        DOC_COLUMN: Final[str] = "doc_column"
        DOC_COLUMN_DEFAULT: Final[str] = "content"
        DOC_ID_COLUMN: Final[str] = "doc_id_column"
        DOC_ID_HASH: Final[str] = "doc_id_hash_column"
        DOC_ID_HASH_DEFAULT: Final[str] = "doc_id_hash"
        DOCLING_DOCUMENT: Final[str] = "docling_document"
        DOCUMENT_TYPE: Final[str] = "document_type"
        ID: Final[str] = "id"
        JSON_CONTENT: Final[str] = "json_content"
        KVP_COLUMN: Final[str] = "kvp_column"
        NAME: Final[str] = "name"
        PATH: Final[str] = "path"
        RAW_TEXT: Final[str] = "raw_text"
        SOURCE_ID: Final[str] = "source_id"
        USER_DEFINED_CONTENT_COLUMN: Final[str] = "user_defined_content_column"
        SUMMARY: Final[str] = "summary"

        # Multi-format extraction columns
        CONTENT_MARKDOWN: Final[str] = "content_markdown"
        CONTENT_HTML: Final[str] = "content_html"
        CONTENT_JSON: Final[str] = "content_json"
        CONTENT_TEXT: Final[str] = "content_text"
        CONTENT_DOCTAGS: Final[str] = "content_doctags"
        CONTENT_DOCLANG: Final[str] = "content_doclang"

        # Embeddings and Vector Columns
        DENSE_EMBEDDINGS_COLUMN_DEFAULT: Final[str] = "vector_embeddings"
        EMBEDDINGS: Final[str] = "embeddings"
        EMBEDDINGS_COLUMN: Final[str] = "embeddings_column"
        EMBEDDINGS_COLUMN_DEFAULT: Final[str] = "embeddings"
        SPARSE_EMBEDDINGS_COLUMN: Final[str] = "sparse_embeddings_column"
        SPARSE_EMBEDDINGS_COLUMN_DEFAULT: Final[str] = "sparse_embeddings"

        # Entity and Extraction Columns
        DATABASE_TABLES_COLUMN_NAME: Final[str] = "database_tables"
        ENTITY_IDS_COLUMN_NAME: Final[str] = "entity_ids"
        EXTRACTED_DATA: Final[str] = "extracted_data"
        IMAGES: Final[str] = "images"
        PAGE_IMAGES: Final[str] = "page_images"
        PAGES_PROCESSED_COLUMN: Final[str] = "pages_processed"
        STRUCTURED_DATA: Final[str] = "structured_data"
        TABLES: Final[str] = "tables"
        TRANSFORMED_ENTITIES_COLUMN_NAME: Final[str] = "transformed_entities"

        # Page calculation columns
        PAGES_PROCESSED: Final[str] = "pages_processed"

        # Language Detection Columns
        LANGUAGE_NAME_COLUMN_KEY: Final[str] = "lang_name"
        LANGUAGE_SCORE_COLUMN_KEY: Final[str] = "lang_score"

        # ML Enrichment Columns
        LANG_COLUMN = "lang_column"
        OUTPUT_COLUMN = "output_column"
        OUTPUT_COLUMN_PREFIX = "output_column_prefix"
        NEWLINE_NORMALIZED_COLUMN_NAME = "newline_normalized_column_name"
        ERROR_COLUMN_NAME = "error_column_name"
        CONTENT_COLUMN_NAME = "content_column_name"
        LANG_COLUMN_NAME = "lang_column_name"

        # Merge and Join Columns
        COLUMN_LIST: Final[str] = "column_list"
        FEATURES: Final[str] = "columns"
        INNER_JOIN_DUPLICATE_COLUMN: Final[str] = "inner_join"

        # Readability Operator - Score Feature Names
        FLESCH_READING_EASE: Final[str] = "flesch_reading_ease"
        FLESCH_KINCAID_GRADE: Final[str] = "flesch_kincaid_grade"
        GUNNING_FOG: Final[str] = "gunning_fog"
        SMOG_INDEX: Final[str] = "smog_index"
        COLEMAN_LIAU_INDEX: Final[str] = "coleman_liau_index"
        AUTOMATED_READABILITY_INDEX: Final[str] = "automated_readability_index"
        DALE_CHALL_READABILITY_SCORE: Final[str] = "dale_chall_readability_score"
        DIFFICULT_WORDS: Final[str] = "difficult_words"
        LINSEAR_WRITE_FORMULA: Final[str] = "linsear_write_formula"
        TEXT_STANDARD: Final[str] = "text_standard"
        SPACHE_READABILITY: Final[str] = "spache_readability"
        MCALPINE_EFLAW: Final[str] = "mcalpine_eflaw"
        READING_TIME: Final[str] = "reading_time"

    class Merge:
        """Merge operator constants."""

        # Merge Configuration Keys
        MERGE_TYPE: Final[str] = "merge_type"
        COLUMN_OPTION: Final[str] = "column_option"
        INPUT_LINKS: Final[str] = "input_links"

        # Merge Type Values
        ROWS: Final[str] = "rows"
        COLUMNS: Final[str] = "columns"

        # Column Option Values (for COLUMNS merge type)
        FULL_OUTER_JOIN: Final[str] = "full_outer"

    class Config:
        """Configuration key constants."""

        # Core Configuration Keys
        ALLOW_EXTRA_KEYS: Final[str] = "allow_extra_keys"
        API_KEY: Final[str] = "api_key"  # pragma: allowlist secret
        ATTRIBUTES: Final[str] = "attributes"
        BATCH_SIZE: Final[str] = "batch_size"
        CONFIG: Final[str] = "config"
        CONFIGURATION: Final[str] = "configuration"
        CONNECTION_PARAMS: Final[str] = "connection_params"
        CREDENTIALS: Final[str] = "credentials"
        CUSTOM_SCHEMA: Final[str] = "custom_schema"
        DEFAULT: Final[str] = "default"
        DESCRIPTION: Final[str] = "description"
        DOC_COLUMN: Final[str] = "doc_column"
        ENGINE: Final[str] = "engine"
        ENGINE_OPTIONS: Final[str] = "engine_options"
        FAIL_ON_ERROR: Final[str] = "fail_on_error"
        GLOBAL_CONFIG: Final[str] = "global_config"
        INGEST_SOURCE: Final[str] = "ingest_source"
        ITEMS: Final[str] = "items"
        MAX_CONCURRENT_REQUESTS: Final[str] = "max_concurrent_requests"
        OUTPUT_COLUMN: Final[str] = "output_column"
        PARAMETERS: Final[str] = "parameters"
        PRESET: Final[str] = "preset"
        PROPERTIES: Final[str] = "properties"
        PROVIDER: Final[str] = "provider"
        PROVIDERS: Final[str] = "providers"
        PROVIDER_CONFIG: Final[str] = "provider_config"
        # Attribute-metadata key naming the sibling field that selects the active provider
        # for a provider-config attribute (defaults to "provider" when absent).
        PROVIDER_FIELD: Final[str] = "provider_field"
        PROVIDER_LITELLM: Final[str] = "litellm"
        PROVIDER_WATSONX: Final[str] = "watsonx"
        REQUIRED: Final[str] = "required"
        SENSITIVE: Final[str] = "sensitive"
        USERNAME: Final[str] = "username"

        # Logging Configuration
        COMMON_LOG_ARGUMENTS: Final[str] = "common_log_arguments"

        # Summarization Configuration
        SUMMARIZATION: Final[str] = "summarization"  # Nested config object
        SUMMARIZATION_PROVIDER: Final[str] = "summarization_provider"  # Backward compatibility
        SUMMARIZATION_PROVIDER_CONFIG: Final[str] = "summarization_provider_config"  # Backward compatibility

        # Extraction Configuration (nested objects)
        TEXT_EXTRACTION: Final[str] = "text_extraction"  # Nested config for text extraction
        ENTITY_EXTRACTION: Final[str] = "entity_extraction"  # Nested config for entity extraction
        VLM_PIPELINE: Final[str] = "vlm_pipeline"  # Nested config for VLM pipeline
        ASR_PIPELINE: Final[str] = "asr_pipeline"  # Nested config for ASR pipeline

        # Feature and Schema Configuration
        ALL_SCHEMA_DETAILS: Final[str] = "all_schema_details"
        AVAILABLE_FEATURES: Final[str] = "available_features"
        AVAILABLE_FOR_FILTER: Final[str] = "available_for_filter"
        AVAILABLE_FOR_OPENSEARCH: Final[str] = "available_for_opensearch"
        AVAILABLE_FOR_VECTOR_DB: Final[str] = "available_for_vector_db"
        DEFAULT_FEATURE_MAPPINGS: Final[str] = "default_feature_mappings"
        FEATURE_MAPPINGS: Final[str] = "feature_mappings"
        FEATURES: Final[str] = "features"
        INPUT_FEATURES: Final[str] = "input_features"
        MANDATORY_FOR_VECTOR_DB: Final[str] = "mandatory_for_vector_db"
        NEW_COLLECTION_DEFAULT_FEATURE_MAPPINGS: Final[str] = "new_collection_default_feature_mappings"
        OUTPUT_FEATURES: Final[str] = "output_features"
        VALID_COLUMNS: Final[str] = "valid_columns"
        VALID_VALUES: Final[str] = "valid_values"

        # Extraction Configuration
        EXPAND_EXTRACTED_DATA: Final[str] = "expand_extracted_data"
        EXTRACT_CUSTOM_SCHEMA: Final[str] = "extract_schema"
        EXTRACT_JSON: Final[str] = "extract_json"
        JSON_SCHEMA: Final[str] = "json_schema"
        LANGUAGES: Final[str] = "languages"
        MAX_WORKERS: Final[str] = "max_workers"
        OCR_MODE: Final[str] = "ocr_mode"
        TEMPLATE: Final[str] = "template"
        USE_PROCESSES: Final[str] = "use_processes"
        USE_TEMPLATE: Final[str] = "use_template"
        USE_VLM_PIPELINE: Final[str] = "use_vlm_pipeline"
        VLM_PRESET: Final[str] = "vlm_preset"
        VLM_PRESET_DEFAULT: Final[str] = "granite_docling"
        VLM_ENGINE_TYPE: Final[str] = "vlm_engine_type"
        VLM_ENGINE_TRANSFORMERS: Final[str] = "transformers"
        VLM_ENGINE_MLX: Final[str] = "mlx"
        VLM_ENGINE_API: Final[str] = "api"
        VLM_ENGINE_API_LMSTUDIO: Final[str] = "api_lmstudio"
        VLM_ENGINE_API_OLLAMA: Final[str] = "api_ollama"
        VLM_ENGINE_API_OPENAI: Final[str] = "api_openai"
        VLM_ENGINE_API_WATSONX: Final[str] = "api_watsonx"
        VLM_API_BASE_URL: Final[str] = "vlm_api_base_url"
        VLM_WATSONX_CONTAINER_KIND: Final[str] = "vlm_watsonx_container_kind"
        VLM_WATSONX_CONTAINER_ID: Final[str] = "vlm_watsonx_container_id"
        VLM_MODEL_NAME: Final[str] = "vlm_model_name"
        VLM_API_KEY: Final[str] = "vlm_api_key"
        VLM_PROVIDER_CONFIG: Final[str] = "vlm_provider_config"

        # ASR (Automatic Speech Recognition) Configuration
        USE_ASR_PIPELINE: Final[str] = "use_asr_pipeline"
        ASR_MODEL_NAME: Final[str] = "asr_model_name"
        ASR_MODEL_DEFAULT: Final[str] = "whisper_turbo"

        # Docling-Serve Configuration (used by ExtractOperator)
        USE_DOCLING_SERVE: Final[str] = "use_docling_serve"
        DOCLING_SERVE_CONFIG: Final[str] = "docling_serve_config"
        BASE_URL: Final[str] = "base_url"
        DO_OCR: Final[str] = "do_ocr"
        OCR_ENGINE: Final[str] = "ocr_engine"
        OCR_LANGUAGES: Final[str] = "ocr_languages"
        OCR_BLOCK: Final[str] = "ocr"  # New canonical OCR config block key
        OCR_PRESET: Final[str] = "ocr_preset"
        OCR_LANG: Final[str] = "ocr_lang"
        PDF_BACKEND: Final[str] = "pdf_backend"
        TABLE_MODE: Final[str] = "table_mode"
        IMAGE_EXPORT_MODE: Final[str] = "image_export_mode"
        OUTPUT_FORMATS: Final[str] = "output_formats"
        FORMAT_OPTIONS: Final[str] = "format_options"

        # Processing Configuration
        ALWAYS_RETRIEVE_DOCUMENT: Final[str] = "always_retrieve_document"
        COMPUTE_EMBEDDINGS: Final[str] = "compute_embeddings"
        CREATE_EMBEDDED_IMAGES: Final[str] = "create_embedded_images"
        DISABLE_VALIDATION: Final[str] = "disable_validation"
        FILTER_UNKNOWN_LANGUAGE: Final[str] = "filter_unknown_language"
        MAX_FILE_SIZE: Final[str] = "max_file_size"
        PARTIAL_INGEST: Final[str] = "partial_ingest"
        SAMPLING_PERCENTAGE: Final[str] = "sampling_percentage"

        # Model Configuration
        EMBEDDINGS_MODEL_ID: Final[str] = "embeddings_model_id"
        MODEL_ID: Final[str] = "model_id"
        MODEL_NAME: Final[str] = "model_name"

        # Classification Configuration
        API_BASE: Final[str] = "api_base"
        DOCUMENT_TYPES: Final[str] = "document_types"
        CONFIDENCE_THRESHOLD: Final[str] = "confidence_threshold"
        INCLUDE_CONFIDENCE: Final[str] = "include_confidence"
        INCLUDE_REASONING: Final[str] = "include_reasoning"
        MAX_CONTENT_LENGTH: Final[str] = "max_content_length"
        STRICT_LABEL_MATCHING: Final[str] = "strict_label_matching"

        # Watsonx Configuration
        CONTAINER_KIND: Final[str] = "container_kind"
        CONTAINER_ID: Final[str] = "container_id"
        REQUEST_TIMEOUT: Final[str] = "request_timeout"

        # Node and Pipeline Configuration
        NODE_METADATA: Final[str] = "node_metadata"
        NODE_PARAMETERS: Final[str] = "node_parameters"
        NODES_METADATA_FILE: Final[str] = "nodes_metadata.json"
        PIPELINE_DETAILS: Final[str] = "pipeline_details"

    class Classification:
        """Document classification constants."""

        # Provider Configuration
        DEFAULT_PROVIDER: Final[str] = "litellm"
        DEFAULT_MODEL: Final[str] = "openai/granite3.1-dense:8b"

        # Classification Parameters
        DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 7.0
        DEFAULT_OUTPUT_COLUMN: Final[str] = "document_type"
        DEFAULT_DOC_COLUMN: Final[str] = "content"  # References Columns.DOC_COLUMN_DEFAULT
        DEFAULT_REQUEST_TIMEOUT: Final[int] = 120
        DEFAULT_MAX_CONTENT_LENGTH: Final[int] = 2000
        DEFAULT_TEMPERATURE: Final[float] = 0.0
        DEFAULT_MAX_TOKENS: Final[int] = 500
        DEFAULT_STRICT_LABEL_MATCHING: Final[bool] = False

        # Configuration Keys
        DOC_COLUMN_KEY: Final[str] = "doc_column"  # References Columns.DOC_COLUMN

        # Response Field Names
        FIELD_DOCUMENT_TYPE: Final[str] = "document_type"
        FIELD_CONFIDENCE: Final[str] = "confidence"
        FIELD_REASONING: Final[str] = "reasoning"

        # Default Values
        UNKNOWN_TYPE: Final[str] = "unknown"

        # Adapter and Provider Names
        ADAPTER_LLM: Final[str] = "llm"
        PROVIDER_WATSONX: Final[str] = "watsonx"
        PROVIDER_LITELLM: Final[str] = "litellm"
        PROVIDER_OLLAMA: Final[str] = "ollama"  # Deprecated - for validation/rejection only

    class VectorDB:
        """Vector database constants."""

        # Vector Database Connection Configuration
        HOST: Final[str] = "host"
        PORT: Final[str] = "port"
        USERNAME: Final[str] = "username"
        PASSWORD: Final[str] = "password"
        USE_SSL: Final[str] = "use_ssl"
        VERIFY_CERTS: Final[str] = "verify_certs"
        AWS_AUTH: Final[str] = "aws_auth"
        AWS_REGION: Final[str] = "aws_region"
        JWT_TOKEN: Final[str] = "jwt_token"

        # Milvus-specific Configuration
        URI: Final[str] = "uri"
        TOKEN: Final[str] = "token"
        DATABASE: Final[str] = "database"
        DB_NAME: Final[str] = "db_name"
        SSL: Final[str] = "ssl"
        SSL_CERTIFICATE: Final[str] = "ssl_certificate"
        AUTH_TYPE: Final[str] = "auth_type"
        SECURE: Final[str] = "secure"

        # Milvus Authentication Types
        AUTH_TYPE_STANDALONE: Final[str] = "standalone"
        AUTH_TYPE_GRPC: Final[str] = "grpc"
        AUTH_TYPE_URI: Final[str] = "uri"
        AUTH_TYPE_TOKEN: Final[str] = "token"

        # Provider resource name keys — each provider declares its resource name
        # inside provider_config using the key appropriate for that backend.
        INDEX_NAME: Final[str] = "index_name"
        COLLECTION_NAME: Final[str] = "collection_name"

        # Index / collection configuration
        INDEX_MAPPINGS: Final[str] = "index_mappings"
        INDEX_SETTINGS: Final[str] = "index_settings"
        INDEX_TYPE: Final[str] = "index_type"
        OPENSEARCH_FEATURE_MAPPINGS: Final[str] = "opensearch_feature_mappings"
        STORED_INDEX_METADATA: Final[str] = "stored_index_metadata"

        # Vector Configuration
        ADD_SPARSE_VECTOR: Final[str] = "add_sparse_vector"
        ADD_SPARSE_VECTOR_DEFAULT: Final[bool] = False
        SPARSE_EMBEDDINGS_COLUMN_DEFAULT: Final[str] = "sparse_embeddings"
        DENSE_EMBEDDINGS_COLUMN_DEFAULT: Final[str] = "dense_embeddings"
        # Milvus field names (mapped names in collection schema)
        SPARSE_VECTOR_FIELD_NAME: Final[str] = "sparse_vector"
        DENSE_VECTOR_FIELD_NAME: Final[str] = "vector"

        # VectorDB Metrics and Configuration
        METRIC_TYPE: Final[str] = "metric_type"
        SEMANTIC_CONFIG: Final[str] = "semantic_config"
        VECTOR_DIMENSION: Final[str] = "vector_dimension"
        DEFAULT_VECTOR_DIMENSION: Final[int] = 384
        VECTOR_SIMILARITY_KEY: Final[str] = "vector_similarity"

        # Vector DB General
        OPENSEARCH: Final[str] = "opensearch"
        MILVUS: Final[str] = "milvus"
        VECTOR_DB_NAME: Final[str] = "vector_db_name"

        # Default target field names — adapter-agnostic names used in feature mappings
        DEFAULT_PRIMARY_KEY_FIELD: Final[str] = "pk"
        DEFAULT_DOCUMENT_ID_FIELD: Final[str] = "document_id"
        DEFAULT_DOCUMENT_NAME_FIELD: Final[str] = "document_name"
        DEFAULT_TEXT_FIELD_NAME: Final[str] = "text"

        # Response metadata keys written into node.parameters by FlowEnrichmentService
        AVAILABLE_RESOURCES: Final[str] = "available_resources"
        SELECTED_RESOURCE_SCHEMA: Final[str] = "selected_resource_schema"
        FEATURE_MAPPINGS_RESPONSE: Final[str] = "feature_mappings"
        IS_DOCPIPE_SUPPORTED_RESOURCE: Final[str] = "is_docpipe_supported_resource"
        STORED_RESOURCE_METADATA: Final[str] = "stored_resource_metadata"

        # OpenSearch-specific parameters
        ENGINE: Final[str] = "engine"
        ALGORITHM: Final[str] = "algorithm"
        SPACE_TYPE: Final[str] = "space_type"
        ENGINE_PARAMETERS: Final[str] = "engine_parameters"

        # Milvus-specific parameters
        INDEX_PARAMETERS: Final[str] = "index_parameters"
        PRIMARY_KEY_FIELD: Final[str] = "primary_key_field"

        # Environment Variable Keys for OpenSearch
        OPENSEARCH_HOST: Final[str] = "OPENSEARCH_HOST"
        OPENSEARCH_PORT: Final[str] = "OPENSEARCH_PORT"
        OPENSEARCH_USE_SSL: Final[str] = "OPENSEARCH_USE_SSL"
        OPENSEARCH_VERIFY_CERTS: Final[str] = "OPENSEARCH_VERIFY_CERTS"
        OPENSEARCH_ENGINE: Final[str] = "OPENSEARCH_ENGINE"
        OPENSEARCH_ALGORITHM: Final[str] = "OPENSEARCH_ALGORITHM"
        OPENSEARCH_SPACE_TYPE: Final[str] = "OPENSEARCH_SPACE_TYPE"
        OPENSEARCH_BATCH_SIZE: Final[str] = "OPENSEARCH_BATCH_SIZE"
        OPENSEARCH_USERNAME: Final[str] = "OPENSEARCH_USERNAME"
        OPENSEARCH_PASSWORD: Final[str] = "OPENSEARCH_PASSWORD"
        OPENSEARCH_AWS_AUTH: Final[str] = "OPENSEARCH_AWS_AUTH"
        OPENSEARCH_AWS_REGION: Final[str] = "OPENSEARCH_AWS_REGION"
        OPENSEARCH_JWT_TOKEN: Final[str] = "OPENSEARCH_JWT_TOKEN"
        OPENSEARCH_VECTOR_DIMENSION: Final[str] = "OPENSEARCH_VECTOR_DIMENSION"
        OPENSEARCH_INDEX_NAME: Final[str] = "OPENSEARCH_INDEX_NAME"
        OPENSEARCH_DOC_ID_COLUMN: Final[str] = "OPENSEARCH_DOC_ID_COLUMN"
        OPENSEARCH_EMBEDDINGS_COLUMN: Final[str] = "OPENSEARCH_EMBEDDINGS_COLUMN"

        # Environment Variable Keys for Milvus
        MILVUS_HOST: Final[str] = "MILVUS_HOST"
        MILVUS_PORT: Final[str] = "MILVUS_PORT"
        MILVUS_URI: Final[str] = "MILVUS_URI"
        MILVUS_DATABASE: Final[str] = "MILVUS_DATABASE"
        MILVUS_INDEX_TYPE: Final[str] = "MILVUS_INDEX_TYPE"
        MILVUS_METRIC_TYPE: Final[str] = "MILVUS_METRIC_TYPE"
        MILVUS_BATCH_SIZE: Final[str] = "MILVUS_BATCH_SIZE"
        MILVUS_USERNAME: Final[str] = "MILVUS_USERNAME"
        MILVUS_PASSWORD: Final[str] = "MILVUS_PASSWORD"
        MILVUS_TOKEN: Final[str] = "MILVUS_TOKEN"
        MILVUS_SSL: Final[str] = "MILVUS_SSL"
        MILVUS_SSL_CERTIFICATE: Final[str] = "MILVUS_SSL_CERTIFICATE"
        MILVUS_AUTH_TYPE: Final[str] = "MILVUS_AUTH_TYPE"
        MILVUS_VECTOR_DIMENSION: Final[str] = "MILVUS_VECTOR_DIMENSION"
        MILVUS_COLLECTION_NAME: Final[str] = "MILVUS_COLLECTION_NAME"
        MILVUS_DOC_ID_COLUMN: Final[str] = "MILVUS_DOC_ID_COLUMN"
        MILVUS_EMBEDDINGS_COLUMN: Final[str] = "MILVUS_EMBEDDINGS_COLUMN"

        # OpenSearch Schema Keys
        SCHEMA_KEY_FIELD_TYPES: Final[str] = "field_types"
        SCHEMA_KEY_MAPPINGS: Final[str] = "mappings"
        SCHEMA_KEY_SETTINGS: Final[str] = "settings"
        SCHEMA_KEY_INDEXING_RULES: Final[str] = "indexing_rules"
        SCHEMA_KEY_SCHEMA_NAME: Final[str] = "schema_name"
        SCHEMA_KEY_SCHEMA_VERSION: Final[str] = "schema_version"
        SCHEMA_KEY_PROPERTIES: Final[str] = "properties"
        SCHEMA_KEY_ANALYSIS: Final[str] = "analysis"
        SCHEMA_KEY_META: Final[str] = "_meta"
        SCHEMA_KEY_KNN_VECTOR: Final[str] = "knn_vector"

    class Types:
        """Data type constants."""

        # Primitive Data Types
        TYPE_BOOL: Final[str] = "bool"
        TYPE_DOUBLE: Final[str] = "double"
        TYPE_FLOAT: Final[str] = "float"
        TYPE_STRING: Final[str] = "string"
        TYPE_TEXT: Final[str] = "text"

        # Integer Data Types
        TYPE_INT8: Final[str] = "int8"
        TYPE_INT16: Final[str] = "int16"
        TYPE_INT32: Final[str] = "int32"
        TYPE_INT64: Final[str] = "int64"

        # Complex Data Types
        TYPE_JSON: Final[str] = "json"
        TYPE_VECTOR: Final[str] = "vector"
        TYPE_VECTOR_SPARSE: Final[str] = "vector_sparse"

    class FileExtensions:
        """File extension constants."""

        # Document formats
        EXT_PDF: Final[str] = ".pdf"
        EXT_DOCX: Final[str] = ".docx"
        EXT_PPTX: Final[str] = ".pptx"
        EXT_XLSX: Final[str] = ".xlsx"

        # Text formats
        EXT_MD: Final[str] = ".md"
        EXT_TXT: Final[str] = ".txt"
        EXT_HTML: Final[str] = ".html"

        # Image formats
        EXT_PNG: Final[str] = ".png"
        EXT_JPEG: Final[str] = ".jpeg"
        EXT_JPG: Final[str] = ".jpg"
        EXT_TIFF: Final[str] = ".tiff"
        EXT_TIF: Final[str] = ".tif"
        EXT_BMP: Final[str] = ".bmp"
        EXT_WEBP: Final[str] = ".webp"
        EXT_GIF: Final[str] = ".gif"
        EXT_JFIF: Final[str] = ".jfif"

        # Audio formats (require ASR)
        EXT_WAV: Final[str] = ".wav"
        EXT_MP3: Final[str] = ".mp3"
        EXT_M4A: Final[str] = ".m4a"
        EXT_AAC: Final[str] = ".aac"
        EXT_OGG: Final[str] = ".ogg"
        EXT_FLAC: Final[str] = ".flac"

        # Video formats (require ASR)
        EXT_MP4: Final[str] = ".mp4"
        EXT_AVI: Final[str] = ".avi"
        EXT_MOV: Final[str] = ".mov"

        BASE_EXTENSIONS: Final[list[str]] = [
            EXT_PDF,
            EXT_DOCX,
            EXT_PPTX,
            EXT_XLSX,
            EXT_MD,
            EXT_TXT,
            EXT_HTML,
            EXT_PNG,
            EXT_JPEG,
            EXT_JPG,
            EXT_TIFF,
            EXT_TIF,
            EXT_BMP,
            EXT_WEBP,
            EXT_GIF,
            EXT_JFIF,
        ]

        AUDIO_VIDEO_EXTENSIONS: Final[list[str]] = [
            EXT_WAV,
            EXT_MP3,
            EXT_M4A,
            EXT_AAC,
            EXT_OGG,
            EXT_FLAC,
            EXT_MP4,
            EXT_AVI,
            EXT_MOV,
        ]

        DOCLING_LIBRARY_BASE_EXTENSIONS: Final[list[str]] = [*BASE_EXTENSIONS]

        DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS: Final[list[str]] = [*AUDIO_VIDEO_EXTENSIONS]

        DOCLING_SERVE_EXTENSIONS: Final[list[str]] = [*BASE_EXTENSIONS]

        DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY: Final[list[str]] = [
            EXT_PDF,  # .pdf  → InputFormat.PDF
            EXT_PNG,  # .png  → InputFormat.IMAGE
            EXT_JPEG,  # .jpeg → InputFormat.IMAGE
            EXT_JPG,  # .jpg  → InputFormat.IMAGE
            EXT_TIFF,  # .tiff → InputFormat.IMAGE
            EXT_TIF,  # .tif  → InputFormat.IMAGE
            EXT_BMP,  # .bmp  → InputFormat.IMAGE
            EXT_GIF,  # .gif  → InputFormat.IMAGE
            EXT_JFIF,  # .jfif → InputFormat.IMAGE
        ]

        CLASSIFICATION_FILE_EXTENSIONS: Final[list[str]] = [
            EXT_PDF,
            EXT_DOCX,
            EXT_PPTX,
            EXT_XLSX,
            EXT_HTML,
            EXT_PNG,
            EXT_JPEG,
            EXT_JPG,
            EXT_TIFF,
            EXT_TIF,
            EXT_BMP,
            EXT_WEBP,
            EXT_GIF,
            EXT_JFIF,
        ]

    class Extraction:
        """Document extraction constants."""

        # Extraction Output Fields
        ERROR: Final[str] = "error"
        ERRORS: Final[str] = "errors"
        MESSAGE: Final[str] = "message"
        PAGE_NO: Final[str] = "page_no"
        SEMANTIC_LABEL: Final[str] = "semantic_label"
        STATUS: Final[str] = "status"
        SUCCESS: Final[str] = "success"

        # Extraction Configuration
        KEY: Final[str] = "key"

        # Multi-format extraction configuration
        ADDITIONAL_FORMATS: Final[str] = "additional_formats"

        # Output format values
        OUTPUT_FORMAT_MARKDOWN: Final[str] = "markdown"
        OUTPUT_FORMAT_HTML: Final[str] = "html"
        OUTPUT_FORMAT_JSON: Final[str] = "json"
        OUTPUT_FORMAT_TEXT: Final[str] = "text"
        OUTPUT_FORMAT_DOCTAGS: Final[str] = "doctags"
        OUTPUT_FORMAT_DOCLANG: Final[str] = "doclang"

        # Docling Serve API response keys
        DOCLING_SERVE_DOCUMENT: Final[str] = "document"
        DOCLING_SERVE_PROCESSING_TIME: Final[str] = "processing_time"
        DOCLING_SERVE_PAGES: Final[str] = "pages"
        DOCLING_SERVE_HTML_CONTENT: Final[str] = "html_content"
        DOCLING_SERVE_JSON_CONTENT: Final[str] = "json_content"
        DOCLING_SERVE_TEXT_CONTENT: Final[str] = "text_content"
        DOCLING_SERVE_DOCTAGS_CONTENT: Final[str] = "doctags_content"
        DOCLING_SERVE_DOCLANG_CONTENT: Final[str] = "doclang_content"

        # Valid output formats list
        VALID_OUTPUT_FORMATS: Final[list[str]] = [
            OUTPUT_FORMAT_MARKDOWN,
            OUTPUT_FORMAT_HTML,
            OUTPUT_FORMAT_JSON,
            OUTPUT_FORMAT_TEXT,
            OUTPUT_FORMAT_DOCTAGS,
            OUTPUT_FORMAT_DOCLANG,
        ]

        # Mapping from format name to output column name
        FORMAT_COLUMN_MAPPING: Final[dict[str, str]] = {
            OUTPUT_FORMAT_MARKDOWN: "content_markdown",
            OUTPUT_FORMAT_HTML: "content_html",
            OUTPUT_FORMAT_JSON: "content_json",
            OUTPUT_FORMAT_TEXT: "content_text",
            OUTPUT_FORMAT_DOCTAGS: "content_doctags",
            OUTPUT_FORMAT_DOCLANG: "content_doclang",
        }

        # Default Filenames
        DEFAULT_FALLBACK_FILENAME: Final[str] = "document.pdf"

        # Extraction stage names
        STAGE_TEXT_EXTRACTION: Final[str] = "text_extraction"
        STAGE_ENTITY_EXTRACTION: Final[str] = "entity_extraction"

        # Extraction stage progress metadata field names
        STAGE_STATUS: Final[str] = "status"
        STAGE_DOCUMENTS_TOTAL: Final[str] = "documents_total"
        STAGE_DOCUMENTS_COMPLETED: Final[str] = "documents_completed"
        STAGE_DOCUMENTS_FAILED: Final[str] = "documents_failed"
        STAGE_PROGRESS_PERCENTAGE: Final[str] = "progress_percentage"

        # Extraction stage status values
        STAGE_STATUS_PENDING: Final[str] = "pending"
        STAGE_STATUS_RUNNING: Final[str] = "running"
        STAGE_STATUS_COMPLETED: Final[str] = "completed"
        STAGE_STATUS_FAILED: Final[str] = "failed"
        # GPU Acceleration Configuration (Docling Library Standard Pipeline)
        STANDARD_PIPELINE: Final[str] = "standard_pipeline"
        ACCELERATOR: Final[str] = "accelerator"
        DEVICE: Final[str] = "device"
        NUM_THREADS: Final[str] = "num_threads"

        # GPU Device Types
        DEVICE_MPS: Final[str] = "mps"
        DEVICE_CUDA: Final[str] = "cuda"
        DEVICE_XPU: Final[str] = "xpu"

    class ExtractionModes:
        """Extraction mode constants for ExtractOperator."""

        # Text Extraction Mode Values
        TEXT_MODE_DOCLING_LIBRARY: Final[str] = "docling_library"
        TEXT_MODE_DOCLING_SERVE: Final[str] = "docling_serve"

        # Entity Extraction Mode Values
        ENTITY_MODE_DOCLING: Final[str] = "docling"
        ENTITY_MODE_LITELLM: Final[str] = "litellm"
        ENTITY_MODE_WATSONX: Final[str] = "watsonx"
        ENTITY_MODE_NONE: Final[str] = "none"

        # Entity Extraction Configuration
        ENTITY_MODEL_NAME: Final[str] = "entity_model_id"
        ENTITY_TEMPERATURE: Final[str] = "entity_temperature"
        ENTITY_MAX_TOKENS: Final[str] = "entity_max_tokens"
        ENTITY_MAX_DOC_CHARS: Final[str] = "entity_max_doc_chars"

        # Entity Extraction System Prompts
        ENTITY_EXTRACTION_SYSTEM_PROMPT: Final[str] = """\
You are a precise document entity extraction assistant.
Your task is to extract structured information from document text and return it \
as valid JSON that exactly matches the provided schema template.

Rules:
1. Return ONLY a valid JSON object — no markdown fences, no explanation text.
2. Use DOUBLE QUOTES for all strings (not single quotes).
3. Use null for any field that cannot be found in the document.
4. For NESTED fields, return a list of objects.
5. Do not add extra fields not in the template.
6. Preserve original values (dates, amounts, names) exactly as they appear.

Example format: {"key": "value", "number": 123, "missing": null}
"""

        ENTITY_EXTRACTION_SCHEMA_FREE_SYSTEM_PROMPT: Final[str] = """\
You are a precise document entity extraction assistant.
Your task is to identify and extract ALL named entities and key structured information
from the document text and return them as a valid JSON object.

Rules:
1. Return ONLY a valid JSON object — no markdown fences, no explanation text.
2. Use DOUBLE QUOTES for all strings (not single quotes).
3. Use meaningful key names that describe the entity type (e.g. "invoice_number", "vendor_name", "total_amount").
4. Group related entities under nested objects where appropriate (e.g. "vendor": {"name": ..., "address": ...}).
5. Use null for any field that cannot be determined.
6. Preserve original values (dates, amounts, names) exactly as they appear.
7. Include all significant entities: people, organizations, dates, amounts, locations, identifiers, etc.

Example format: {"customer": {"name": "John Doe", "email": "john@example.com"}, "total": 100.50, "date": null}
"""

    class LLM:
        """LLM-specific constants."""

        TEMPERATURE: Final[str] = "temperature"
        MAX_TOKENS: Final[str] = "max_tokens"
        MAX_DOC_CHARS: Final[str] = "max_doc_chars"
        API_BASE: Final[str] = "api_base"

    class PIIHAP:
        """PII/HAP constants."""

        # Payload field constants
        INPUT_FIELD: Final[str] = "input"
        DETECTIONS_FIELD: Final[str] = "detections"
        DEFAULT_MODEL_NAME: Final[str] = "granite4"

        # PII Configuration
        PII_AND_HAP_EXTRACT_REDACT: Final[str] = "pii_and_hap_extract_redact"
        PII_FIELD_NAME: Final[str] = "pii"
        PII_LIST: Final[str] = "pii_list"
        PII_REDACTION_CHARACTER_KEY: Final[str] = "redaction_character"
        PII_REDACTION_KEY: Final[str] = "redaction"
        PII_THRESHOLD_KEY: Final[str] = "pii_threshold"

        # HAP Configuration
        HAP_FIELD_NAME: Final[str] = "hap"
        HAP_REDACTION_CHARACTER_KEY: Final[str] = "hap_redaction_character"
        HAP_REDACTION_KEY: Final[str] = "hap_redaction"
        HAP_THRESHOLD_KEY: Final[str] = "hap_threshold"

        # Per-capability provider selection (legacy "provider"/"provider_config" sets both)
        PII_PROVIDER_KEY: Final[str] = "pii_provider"
        PII_PROVIDER_CONFIG_KEY: Final[str] = "pii_provider_config"
        HAP_PROVIDER_KEY: Final[str] = "hap_provider"
        HAP_PROVIDER_CONFIG_KEY: Final[str] = "hap_provider_config"
        MODERATIONS: Final[str] = "moderations"

        # Redaction Configuration
        DEFAULT_REDACTION_CHARACTER_VALUE: Final[str] = "*"
        DEFAULT_REDACTION_VALUE: Final[bool] = False
        EXPECTED_REDACTIONS: Final[str] = "expected_redactions"
        REDACTION_CHARACTER_KEY: Final[str] = "redaction_character"
        REDACTION_KEY: Final[str] = "redaction"
        REDACTION_MASKING_CHARACTER_KEY: Final[str] = "redaction_masking_character"
        REDACTION_REGEX_KEY: Final[str] = "redaction_regex"

        # Redaction Type Values
        REDACTION_TYPE_PII: Final[str] = "PII"
        REDACTION_TYPE_HAP: Final[str] = "HAP"

        # PII Type Values (as they appear in pii_list)
        PII_TYPE_PHONE_NUMBER: Final[str] = "PhoneNumber"
        PII_TYPE_SOCIAL_SECURITY_NUMBER: Final[str] = "SocialSecurityNumber"
        PII_TYPE_BANK_ACCOUNT_NUMBER: Final[str] = "BankAccountNumber"
        PII_TYPE_IP_ADDRESS: Final[str] = "IPAddress"
        PII_TYPE_EMAIL_ADDRESS: Final[str] = "EmailAddress"
        PII_TYPE_CREDIT_CARD_NUMBER: Final[str] = "CreditCardNumber"
        PII_TYPE_PERSON_NAME: Final[str] = "PersonName"
        PII_TYPE_DATE_OF_BIRTH: Final[str] = "DateOfBirth"
        PII_TYPE_ADDRESS: Final[str] = "Address"
        PII_TYPE_PASSPORT_NUMBER: Final[str] = "PassportNumber"
        PII_TYPE_DRIVER_LICENSE: Final[str] = "DriverLicenseNumber"
        PII_TYPE_NATIONAL_ID: Final[str] = "NationalID"
        PII_TYPE_MEDICAL_RECORD: Final[str] = "MedicalRecordNumber"

        # Normalized search terms for feature name matching
        PII_SEARCH_PHONE_NUMBER: Final[str] = "phone_number"
        PII_SEARCH_SSN: Final[str] = "ssn_details"
        PII_SEARCH_BANK_ACCOUNT: Final[str] = "bank_account"
        PII_SEARCH_IP_ADDRESS: Final[str] = "ip_address"
        PII_SEARCH_EMAIL_ADDRESS: Final[str] = "email_address"
        PII_SEARCH_CREDIT_CARD: Final[str] = "credit_card"
        PII_SEARCH_PERSON_NAME: Final[str] = "person_name"
        PII_SEARCH_DATE_OF_BIRTH: Final[str] = "date_of_birth"
        PII_SEARCH_ADDRESS: Final[str] = "address"
        PII_SEARCH_PASSPORT_NUMBER: Final[str] = "passport_number"
        PII_SEARCH_DRIVER_LICENSE: Final[str] = "driver_license"
        PII_SEARCH_NATIONAL_ID: Final[str] = "national_id"
        PII_SEARCH_MEDICAL_RECORD: Final[str] = "medical_record"

    class Filtering:
        """Filtering constants."""

        # Filter Configuration
        AVAILABLE_FOR_FILTER: Final[str] = "available_for_filter"
        FILTER_CRITERIA_JSON: Final[str] = "criteria_json"
        FILTER_CRITERIA_LIST: Final[str] = "criteria_list"
        FILTER_FEATURES_TO_DROP_KEY: Final[str] = "features_to_drop"
        FILTER_LOGICAL_OPERATOR_KEY: Final[str] = "logical_operator"
        INCLUDE_FILTER_KEY: Final[str] = "include_filter"

        # DuckDB resource limits (sql_filter operator)
        DUCKDB_MEMORY_LIMIT: Final[str] = "duckdb_memory_limit"
        DUCKDB_THREADS: Final[str] = "duckdb_threads"

        # SQL Operations
        SQL_FILTER: Final[str] = "sql_filter"

        # Value Range Filtering
        MAX_VALUE: Final[str] = "max_value"
        MIN_VALUE: Final[str] = "min_value"

    class Processing:
        """Processing constants."""

        # Chunking Configuration
        CHUNK_SIZE: Final[str] = "chunk_size"
        CHUNK_SIZE_DEFAULT: Final[int] = 2048
        CHUNKER: Final[str] = "chunker"
        START_INDEX: Final[str] = "start_index"

        # Chunking Provider Values
        PROVIDER_DOCLING_LIBRARY: Final[str] = "docling_library"
        PROVIDER_DOCLING_SERVE: Final[str] = "docling_serve"
        PROVIDER_SIMPLE: Final[str] = "simple"
        PROVIDER_SEMANTIC: Final[str] = "semantic"

        # Provider option keys (for remote chunking services)
        TIMEOUT: Final[str] = "timeout"
        POLL_INTERVAL: Final[str] = "poll_interval"
        MAX_RETRIES: Final[str] = "max_retries"
        VERIFY_SSL: Final[str] = "verify_ssl"

        # Embedding Configuration
        COMPUTE_EMBEDDINGS: Final[str] = "compute_embeddings"

        # Deduplication Configuration
        DOC_ID_HASH: Final[str] = "doc_id_hash_column"
        DOC_ID_HASH_DEFAULT: Final[str] = "doc_id_hash"

        # Page calculation configuration
        CHARS_PER_PAGE: Final[int] = 3000

    class Metadata:
        """Metadata constants."""

        # Document Metadata
        CREATED_TIME: Final[str] = "created_time"
        DOCUMENT_CLASS: Final[str] = "document_class"
        DOCUMENT_CLASS_ID: Final[str] = "document_class_id"
        DOCUMENT_FORMAT: Final[str] = "document_format"
        DOCUMENT_ID: Final[str] = "document_id"
        DOCUMENT_TYPE: Final[str] = "document_type"
        FORMAT: Final[str] = "format"
        LANGUAGE: Final[str] = "language"
        LANGUAGE_SCORE: Final[str] = "language_score"
        LAST_MODIFIED_TIME: Final[str] = "last_modified_time"
        MODIFIED_TIME: Final[str] = "modified_time"
        PAGE_COUNT: Final[str] = "page_count"
        PROCESSING_STATE: Final[str] = "processing_state"

        # Pipeline Metadata
        METADATA: Final[str] = "metadata"
        NODE_METADATA: Final[str] = "node_metadata"
        PIPELINE_DETAILS: Final[str] = "pipeline_details"
        UNSTRUCTURED_DATA_CURATION_ID: Final[str] = "unstructured_data_curation_id"
        UPDATED_DOCUMENTS: Final[str] = "updated_documents"

        # Tracking and Identification
        TOTAL_PAGES_PROCESSED: Final[str] = "total_pages_converted"

        # Page statistics
        PAGE_TYPE_STATS: Final[str] = "page_type_stats"

        # Extraction stage progress fields (transient - removed after aggregation)
        EXTRACTION_STAGE_PROGRESS: Final[str] = "extraction_stage_progress"

        # Display field names for UI
        FIELD_PROGRESS: Final[str] = "Progress"
        FIELD_TEXT_EXTRACTED: Final[str] = "Text Extracted"
        FIELD_ENTITIES_EXTRACTED: Final[str] = "Entities Extracted"
        FIELD_DOCS_CLASSIFIED: Final[str] = "Documents Classified"

        # Numeric progress percentage (float 0-100) for programmatic UI consumption
        PROGRESS_PERCENTAGE: Final[str] = "progress_percentage"

    class Storage:
        """Storage constants."""

        # Storage Configuration
        CONNECTION_PATH: Final[str] = "connection_path"
        COS_ENDPOINT: Final[str] = "cos_endpoint"
        DATASOURCE_TYPE: Final[str] = "datasource_type"
        SCHEMA_NAME: Final[str] = "schema_name"
        STORAGE: Final[str] = "storage"
        TABLE_NAME: Final[str] = "table_name"
        TARGET_STORE: Final[str] = "target_store"

        # Table storage backends shared by the storage operators
        BACKEND_DUCKDB: Final[str] = "duckdb"
        BACKEND_POSTGRES: Final[str] = "postgres"
        DATA_BACKEND: Final[str] = "data_backend"
        DATABASE_PATH: Final[str] = "database_path"
        DEFAULT_DATA_BACKEND: Final[str] = "duckdb"
        DEFAULT_DATABASE_PATH: Final[str] = ":memory:"
        SCHEMA: Final[str] = "schema"
        TABLE_PREFIX: Final[str] = "table_prefix"

        # Storage Types
        AWS_STORAGE_TYPE: Final[str] = "amazon_s3"
        COS_STORAGE_TYPE: Final[str] = "bmcos_object_storage"
        DEFAULT_S3_REGION: Final[str] = "us-east-1"

        # Output Configuration
        OUTPUT_FEATURES_TO_DROP: Final[str] = "output_features_to_drop"
        OUTPUT_FOLDER: Final[str] = "output_folder"

    class Misc:
        """Miscellaneous constants."""

        # General Identifiers
        CATEGORY: Final[str] = "category"
        COUNT: Final[str] = "count"
        DELETED: Final[str] = "deleted"
        ENTITY: Final[str] = "entity"
        ID: Final[str] = "id"
        IS_PRIMARY: Final[str] = "is_primary"
        LABEL: Final[str] = "label"
        NAME: Final[str] = "name"
        OPERATOR: Final[str] = "operator"
        PAGES: Final[str] = "pages"
        PATH: Final[str] = "path"
        PATHS: Final[str] = "paths"
        PRIMARY: Final[str] = "primary"
        REGEX_KEY: Final[str] = "regex"
        ROWS: Final[str] = "rows"
        SDK: Final[str] = "sdk"
        SLEEP_SEC: Final[str] = "sleep_sec"
        SHORT_NAME: Final[str] = "short_name"
        SIZE: Final[str] = "size"
        TAGS: Final[str] = "tags"
        UNKNOWN: Final[str] = "unknown"
        URL: Final[str] = "url"
        VALUE: Final[str] = "value"

        # Feature and Transform Constants
        BRANCHING: Final[str] = "branching"
        BRANCHES: Final[str] = "branches"
        CONTENT_TYPE: Final[str] = "content_type"
        ENTITIES: Final[str] = "entities"
        FEATURE_NAME: Final[str] = "feature_name"
        INGEST_TYPE: Final[str] = "ingest_type"
        INTERNAL_FEATURE: Final[str] = "internal_feature"
        IS_INTERNAL_FEATURE: Final[str] = "is_internal_feature"
        IS_OPERATOR_AVAILABLE: Final[str] = "is_operator_available"
        JSON_IDENTIFIER: Final[str] = "json_identifier"
        KEY_VALUE: Final[str] = "key_value"
        LINK_CONDITIONS: Final[str] = "link_conditions"
        LINK_ID: Final[str] = "link_id"
        LINK_NAME: Final[str] = "link_name"
        MANDATORY: Final[str] = "mandatory"
        MAPPED_COLUMN_NAME: Final[str] = "mapped_column_name"
        NEW_FEATURE: Final[str] = "new_feature"
        NORMALIZED_VALUE: Final[str] = "normalized_value"
        OLD_FEATURE: Final[str] = "old_feature"
        ORIGINAL_FEATURE: Final[str] = "original_feature"
        TRANSFORM: Final[str] = "transform"
        TYPE: Final[str] = "type"
        USER_CODE: Final[str] = "user_code"
        USER_DATA: Final[str] = "user_data"

        # Merge Operator - Strategy Names
        MERGE_STRATEGY_CONCATENATION: Final[str] = "concatenation_with_different_schema"
        MERGE_STRATEGY_INNER_JOIN: Final[str] = "inner_join_with_duplicate_columns"
        MERGE_STRATEGY_FULL_OUTER_JOIN: Final[str] = "full_outer_join"

        # Feature Attribute Keys (for feature dictionaries)
        FEATURE_ATTR_NAME: Final[str] = "name"
        FEATURE_ATTR_DESCRIPTION: Final[str] = "description"
        FEATURE_ATTR_AVAILABLE_FOR_FILTER: Final[str] = "available_for_filter"
        FEATURE_ATTR_AVAILABLE_FOR_VECTOR_DB: Final[str] = "available_for_vector_db"
        FEATURE_ATTR_MANDATORY_FOR_VECTOR_DB: Final[str] = "mandatory_for_vector_db"
        FEATURE_ATTR_NODE_ID: Final[str] = "node_id"
        VALUE_DATA_TYPE: Final[str] = "value_data_type"

        # Operator and Collection Constants
        AVAILABLE_COLLECTIONS: Final[str] = "available_collections"
        AVAILABLE_INDICES: Final[str] = "available_indices"
        COLLECTION_COLUMNS: Final[str] = "collection_columns"
        COLUMN_OPTION: Final[str] = "column_option"
        COMPUTE: Final[str] = "compute"
        CORE_OPERATORS_PATH: Final[str] = "core.operators"
        DESIGN_FLOW_OUTPUT_OPERATOR: Final[str] = "design_flow_output"
        DISABLED: Final[str] = "disabled"
        DOCUMENTS: Final[str] = "documents"
        ENABLED_TEXT: Final[str] = "enabled_text"
        ENTITY_CURATION_OPERATOR: Final[str] = "entity_curation_operator"
        ENTITY_EXTRACT: Final[str] = "extract_entity"
        DOCUMENT_CLASSIFIER: Final[str] = "document_classifier"
        DOCLING_CHUNKER: Final[str] = "docling_chunker"
        ENTITY_STORE_OPERATOR: Final[str] = "entity_store"
        FORCED: Final[str] = "forced"
        FULL_OUTER_JOIN: Final[str] = "full_outer"
        HEARTBEAT_EMBEDDINGS_PUBLISH_SIZE: Final[str] = "embeddings_publish_compute_size"
        INPUT_LINKS: Final[str] = "input_links"
        IS_DOCPIPE_SUPPORTED_COLLECTION: Final[str] = "is_docpipe_supported_collection"
        IS_DOCPIPE_SUPPORTED_INDEX: Final[str] = "is_docpipe_supported_index"
        MARKED_UNSTRUCTURED_STATUS: Final[str] = "marked_unstructured_status"
        MAX_BATCH_SIZE_MB: Final[str] = "max_batch_size_mb"
        MERGE_OPTION: Final[str] = "merge_option"
        MERGE_TYPE: Final[str] = "merge_type"
        NEW_COLUMNS: Final[str] = "selected_python_features"
        NODE_IDS: Final[str] = "node_ids"
        REASON: Final[str] = "reason"
        RESOURCE_KEY: Final[str] = "resource_key"
        SELECTED_PYTHON_FEATURES: Final[str] = "selected_python_features"
        SUPPORTED: Final[str] = "supported"
        TOTAL_FILE_COUNT: Final[str] = "file_count"
        UPDATED_FEATURES: Final[str] = "updated_features"

        # Default Values and Limits
        DEFAULT_MAX_THREADS: Final[int] = 25
        DEFAULT_WXAI_API_MAX_WAIT_TIME: Final[int] = 3600
        MAX_CONCURRENT_DELETIONS: Final[int] = 10

        # Operator Paths - organized by OperatorCategory
        ALL_OPERATORS_PATH: Final[list[str]] = [
            "docpipe.core.operators.extract",
            "docpipe.core.operators.ingest",
            "docpipe.core.operators.functional",
            "docpipe.core.operators.quality",
            "docpipe.core.operators.vectordb",
            "docpipe.core.operators.document_sets",
        ]

        # Flow Authoring Constants
        BRANCH_SEPARATOR: Final[str] = "."
        BRANCH_CONDITION_KEY: Final[str] = "condition"
        DEPENDS_ON: Final[str] = "depends_on"

    class ContainerKinds:
        CATALOG: Final[str] = "catalog"
        PROJECT: Final[str] = "project"
        SPACE: Final[str] = "space"

    class MimeTypes:
        """MIME type constants for document processing and ingestion."""

        # Standard Document Types
        PDF: Final[str] = "application/pdf"
        HTML: Final[str] = "text/html"
        PLAIN: Final[str] = "text/plain"

        # Google Workspace Document Types
        GOOGLE_APPS_PREFIX: Final[str] = "application/vnd.google-apps."
        GOOGLE_APPS_DOCUMENT: Final[str] = "application/vnd.google-apps.document"
        GOOGLE_APPS_SPREADSHEET: Final[str] = "application/vnd.google-apps.spreadsheet"
        GOOGLE_APPS_PRESENTATION: Final[str] = "application/vnd.google-apps.presentation"
        GOOGLE_APPS_DRAWING: Final[str] = "application/vnd.google-apps.drawing"

        # Export Formats
        EXCEL_XLSX: Final[str] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    class DocumentSet:
        """Document Set constants."""

        # Adapter Names
        ADAPTER_DUCKDB: Final[str] = "duckdb"
        ADAPTER_FILESYSTEM: Final[str] = "filesystem"
        ADAPTER_POSTGRES: Final[str] = "postgres"

        # Configuration Keys
        DATABASE_PATH: Final[str] = "database_path"
        DATA_BACKEND: Final[str] = "data_backend"
        DEFAULT_DATA_BACKEND: Final[str] = "duckdb"
        METADATA_CONFIG: Final[str] = "metadata_config"
        DATA_CONFIG: Final[str] = "data_config"
        DOCUMENT_SET_NAME: Final[str] = "document_set_name"
        DOCUMENT_SET_ID: Final[str] = "document_set_id"

        # Table Names
        TABLE_DOCUMENT_SETS_METADATA: Final[str] = "document_sets"

        # Column Names
        COL_ID: Final[str] = "id"
        COL_NAME: Final[str] = "name"
        COL_DESCRIPTION: Final[str] = "description"
        COL_STORAGE_BACKEND: Final[str] = "storage_backend"
        COL_DATABASE_PATH: Final[str] = "database_path"
        COL_TABLE_NAME: Final[str] = "table_name"
        COL_TOTAL_DOCUMENTS: Final[str] = "total_documents"
        COL_TOTAL_SIZE_BYTES: Final[str] = "total_size_bytes"
        COL_TOTAL_PAGES: Final[str] = "total_pages"
        COL_CREATED_AT: Final[str] = "created_at"
        COL_UPDATED_AT: Final[str] = "updated_at"
        COL_METADATA: Final[str] = "metadata"

        # Health Status
        HEALTH_HEALTHY: Final[str] = "healthy"
        HEALTH_UNHEALTHY: Final[str] = "unhealthy"

        # Metadata Keys
        META_DOCUMENT_SET_NAME: Final[str] = "document_set_name"
        META_DOCUMENT_SET_ID: Final[str] = "document_set_id"
        META_DATABASE_PATH: Final[str] = "database_path"
        META_TABLE_NAME: Final[str] = "table_name"
        META_STORED_DOCUMENTS: Final[str] = "stored_documents"
        META_TOTAL_SIZE_BYTES: Final[str] = "total_size_bytes"
        META_TOTAL_PAGES: Final[str] = "total_pages"
        META_ERROR: Final[str] = "error"
        META_DATA_CARD: Final[str] = "data_card"

        # Query Strings
        QUERY_TABLE_EXISTS: Final[str] = (
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'document_sets'"
        )
        QUERY_CONNECTIVITY_TEST: Final[str] = "SELECT 1"
        QUERY_BEGIN_TRANSACTION: Final[str] = "BEGIN TRANSACTION"
        QUERY_COMMIT: Final[str] = "COMMIT"
        QUERY_ROLLBACK: Final[str] = "ROLLBACK"

    class ACL:
        """ACL (Access Control List) extraction constants."""

        # ACL Provider Types
        PROVIDER_SHAREPOINT: Final[str] = "sharepoint"
        PROVIDER_S3: Final[str] = "s3"
        PROVIDER_GOOGLE_DRIVE: Final[str] = "google_drive"
        PROVIDER_ONEDRIVE: Final[str] = "onedrive"
        PROVIDER_BOX: Final[str] = "box"

        # ACL Configuration Keys (used across multiple modules)
        RESOLVE_INHERITANCE: Final[str] = "resolve_inheritance"
        EXPAND_GROUPS: Final[str] = "expand_groups"
        NORMALIZE_IDENTITIES: Final[str] = "normalize_identities"

        # ACL Response Fields
        DENIED_USERS: Final[str] = "denied_users"
        INHERITANCE_CHAIN: Final[str] = "inheritance_chain"
        HAS_UNIQUE_PERMISSIONS: Final[str] = "has_unique_permissions"
        RESOLUTION_METADATA: Final[str] = "resolution_metadata"

        # Column name
        ALLOWED_USERS_COLUMN: Final[str] = "allowed_users"

        # Default Values
        DEFAULT_FAIL_ON_ERROR: Final[bool] = True
        DEFAULT_RESOLVE_INHERITANCE: Final[bool] = True
        DEFAULT_EXPAND_GROUPS: Final[bool] = True
        DEFAULT_NORMALIZE_IDENTITIES: Final[bool] = True

    class DocFormat(StrEnum):
        """Document format values for the ``doc_format`` global config key.

        Being a :class:`~enum.StrEnum`, members compare equal to their string
        counterparts (``DocFormat.MARKDOWN == "markdown"``), so existing
        ``config.get(...)`` calls and equality checks work without change.
        Iterating over the class yields all valid values, removing the need for
        a separate ``VALID_VALUES`` list.
        """

        MARKDOWN = "markdown"
        DOCLANG = "doclang"

    # Config key for doc_format — kept outside the StrEnum so it is not an enum member
    DOC_FORMAT_KEY: Final[str] = "doc_format"
    DOC_FORMAT_DEFAULT: Final[str] = DocFormat.MARKDOWN

    # Columns that cannot be dropped by any operator (e.g. SQLFilterOperator).
    # Downstream operators depend on these being present in the pipeline table.
    PROTECTED_PIPELINE_COLUMNS: frozenset = frozenset(
        {
            "id",
            "content",
            "pages_processed",
            "allowed_users",
            "chunked_content",
        }
    )
