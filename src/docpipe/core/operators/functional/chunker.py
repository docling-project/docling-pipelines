"""Chunker operator that splits documents into smaller text segments."""

import io
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

import pyarrow as pa
from data_processing.utils import TransformUtils
from langchain_core.documents import Document

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.functional.chunker_validator import ChunkerValidator
from docpipe.core.operators.functional.summarization_service import SummarizationService
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage
from docpipe.integrations.ollama.client import InteractionMode, OllamaClient
from docpipe.integrations.ollama.embeddings import OllamaClientEmbeddings
from docpipe.utils.core.memmap_file_utils import write_chunks_to_file
from docpipe.utils.infrastructure import get_pyarrow_table_size_mb
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.config_validation import validate_config_from_metadata


# Chunk Type Constants
class ChunkType(StrEnum):
    """
    Enum for available chunking strategies.

    Attributes:
        SIMPLE: Fixed-size chunking with overlap (traditional approach)
        SEMANTIC: Content-aware chunking based on semantic similarity (LangChain)
        HYBRID: Hierarchical + semantic chunking using Docling's HybridChunker
    """

    SIMPLE = "simple"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


CHUNK_TYPE_KEY: str = "chunk_type"
CHUNK_TYPE_DEFAULT: str = ChunkType.SIMPLE.value
VALID_CHUNK_TYPES: list[str] = [t.value for t in ChunkType]

# Simple Chunking Constants
CHUNK_OVERLAP_KEY: str = "chunk_overlap"
CHUNK_OVERLAP_DEFAULT: int = 200  # Characters of overlap between consecutive chunks
CHUNK_MIN_SIZE: int = 500  # Minimum chunk size in characters
CHUNK_MAX_SIZE: int = 5000  # Maximum chunk size in characters
CHUNK_OVERLAP_MIN_SIZE: int = 0  # Minimum overlap size
CHUNK_OVERLAP_MAX_SIZE: int = 512  # Maximum overlap size

# Chunk Overlap Percentage Constants
CHUNK_OVERLAP_PERCENTAGE_KEY: str = "chunk_overlap_percentage"
CHUNK_OVERLAP_PERCENTAGE_DEFAULT: int = 20  # Warning threshold; values above this produce a validation warning
CHUNK_OVERLAP_PERCENTAGE_MIN_SIZE: int = 0  # Minimum overlap percentage
CHUNK_OVERLAP_PERCENTAGE_MAX_SIZE: int = 40  # Maximum overlap percentage

# Semantic Chunking Constants
SEMANTIC_EMBEDDINGS_MODEL_KEY: str = "semantic_embeddings_model"

# Docling Chunking Constants
DOCLING_TOKENIZER_KEY: str = "docling_tokenizer"
DOCLING_TOKENIZER_DEFAULT: str = "sentence-transformers/all-MiniLM-L6-v2"
DOCLING_CHUNK_SIZE_MIN: int = 100  # Minimum chunk size in tokens for Docling
DOCLING_CHUNK_SIZE_MAX: int = 2048  # Maximum chunk size in tokens for Docling

# Summarization Constants
ENABLE_SUMMARIZATION_DEFAULT: bool = False
MAX_INPUT_TOKENS_KEY: str = "max_input_tokens"
OVERLAP_RATIO_KEY: str = "overlap_ratio"
SUMMARY_SENTENCES_KEY: str = "summary_sentences"
SUMMARY_MAX_WORDS_KEY: str = "summary_max_words"


# Breakpoint Threshold Constants
class BreakpointThresholdType(StrEnum):
    """
    Enum for semantic chunking breakpoint detection methods.

    These methods determine where to split text based on semantic similarity:

    Attributes:
        PERCENTILE: Split at percentile threshold of dissimilarity scores
                   (e.g., 95th percentile = split at top 5% most dissimilar points)
        STANDARD_DEVIATION: Split when dissimilarity exceeds N standard deviations
                           from mean (e.g., 2.0 = split at 2 std devs above mean)
        INTERQUARTILE: Split based on interquartile range (IQR) of dissimilarity
        GRADIENT: Split at points with steepest changes in similarity gradient
    """

    PERCENTILE = "percentile"
    STANDARD_DEVIATION = "standard_deviation"
    INTERQUARTILE = "interquartile"
    GRADIENT = "gradient"


BREAKPOINT_THRESHOLD_TYPE_KEY: str = "breakpoint_threshold_type"
BREAKPOINT_THRESHOLD_TYPE_DEFAULT: str = BreakpointThresholdType.PERCENTILE.value
BREAKPOINT_THRESHOLD_AMOUNT_KEY: str = "breakpoint_threshold_amount"
BREAKPOINT_THRESHOLD_AMOUNT_DEFAULT: float | None = None  # None = use LangChain defaults
VALID_BREAKPOINT_TYPES: list[str] = [t.value for t in BreakpointThresholdType]

# General Constants
RETAIN_ORIGINAL_CONTENT_KEY: str = "retain_original_content"
RETAIN_ORIGINAL_CONTENT_DEFAULT: bool = False  # Drop original content unless explicitly retained

# Docling-serve Constants
DEFAULT_DOCUMENT_NAME: str = "document.md"  # Default filename for docling-serve chunking

logger = get_logger()


class ChunkerOperator(AbstractOperator):
    """
    Operator for intelligent text chunking with support for simple, semantic, and docling strategies.

    This operator provides three chunking approaches:

    1. **Simple Chunking**: Traditional fixed-size chunking with configurable overlap.
       Uses LangChain's CharacterTextSplitter for consistent chunk sizes.

    2. **Semantic Chunking**: Content-aware chunking based on semantic similarity.
       Uses LangChain's SemanticChunker with Ollama embeddings to identify natural
       breakpoints in text, creating chunks that maintain semantic coherence.

    3. **Docling Chunking**: Hierarchical chunking using Docling's HybridChunker.
       Respects document structure and uses tokenizer-based chunking.

    Configuration Parameters:
        chunk_type (str): Chunking strategy - "simple", "semantic", or "docling"

        Simple Chunking Parameters:
            chunk_size (int): Size of each chunk in characters (500-5000)
            chunk_overlap (int): Overlap between consecutive chunks (0-512)

        Semantic Chunking Parameters:
            semantic_embeddings_model (str): Ollama model for embeddings (default: "granite4")
            breakpoint_threshold_type (str): Method for detecting boundaries:
                - "percentile": Split at percentile of dissimilarity (e.g., 95th)
                - "standard_deviation": Split at N std devs from mean
                - "interquartile": Split based on IQR
                - "gradient": Split at steepest similarity changes
            breakpoint_threshold_amount (float): Threshold value for the method
                - For percentile: 0-100 (e.g., 95.0 for 95th percentile)
                - For std dev: positive number (e.g., 2.0 for 2 std devs)
                - None: Use LangChain defaults

        Docling Chunking Parameters:
            chunk_size (int): Size of each chunk in tokens (100-2048)
            chunk_overlap (int): Overlap between consecutive chunks (0-512)
            docling_tokenizer (str): HuggingFace tokenizer model (default: "sentence-transformers/all-MiniLM-L6-v2")

    Example Configurations:
        Simple chunking:
            {"chunk_type": "simple", "chunk_size": 1000, "chunk_overlap": 200}

        Semantic chunking:
            {
                "chunk_type": "semantic",
                "semantic_embeddings_model": "granite4",
                "breakpoint_threshold_type": "percentile",
                "breakpoint_threshold_amount": 95.0
            }

        Docling chunking:
            {
                "chunk_type": "hybrid",
                "chunk_size": 512,
                "chunk_overlap": 50,
                "docling_tokenizer": "sentence-transformers/all-MiniLM-L6-v2"
            }

    Attributes:
        chunk_type (str): Chunking strategy (simple, semantic, or hybrid)
        chunk_size (int): Size of each chunk in characters or tokens
        chunk_overlap (int): Overlap between consecutive chunks
        semantic_embeddings_model (str): Ollama model for semantic chunking
        breakpoint_threshold_type (str): Method for detecting semantic boundaries
        breakpoint_threshold_amount (float): Threshold value for boundary detection
        docling_tokenizer (str): HuggingFace tokenizer for docling chunking
        retain_original_content (bool): Whether to keep original content column
        summarization (dict): Summarization configuration
            - provider (str): LLM provider for summarization (litellm or watsonx)
            - provider_config (dict): Provider-specific configuration
                - model_id (str): Model identifier for summarization
        doc_column (str): Column containing document content
    """

    short_name: str = OperatorConstants.Operators.CHUNKER
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the chunker operator with configuration parameters.

        Args:
            config: Configuration dictionary containing:
                - doc_column (str): Column name containing document content
                - chunk_type (str): "simple", "semantic", or "docling" chunking strategy
                - chunk_size (int): Size for simple/docling chunking (default: 1000)
                - chunk_overlap (int): Overlap for simple chunking (default: 200)
                - semantic_embeddings_model (str): Ollama model for semantic chunking (default: "granite4")
                - breakpoint_threshold_type (str): Boundary detection method (default: "percentile")
                - breakpoint_threshold_amount (float): Threshold value (default: None)
                - docling_tokenizer (str): Tokenizer for docling chunking (default: "sentence-transformers/all-MiniLM-L6-v2")
                - retain_original_content (bool): Keep original content (default: False)
        """
        super().__init__(config)
        self.chunk_type: str = config.get(CHUNK_TYPE_KEY, CHUNK_TYPE_DEFAULT)
        self.chunk_size: int = config.get(
            OperatorConstants.Processing.CHUNK_SIZE, OperatorConstants.Processing.CHUNK_SIZE_DEFAULT
        )
        self.chunk_overlap: int = config.get(CHUNK_OVERLAP_KEY, CHUNK_OVERLAP_DEFAULT)
        self.chunk_overlap_percentage: int = config.get(CHUNK_OVERLAP_PERCENTAGE_KEY, CHUNK_OVERLAP_PERCENTAGE_DEFAULT)
        self.retain_original_content: bool = config.get(RETAIN_ORIGINAL_CONTENT_KEY, RETAIN_ORIGINAL_CONTENT_DEFAULT)
        self.semantic_embeddings_model: str | None = config.get(SEMANTIC_EMBEDDINGS_MODEL_KEY)
        self.breakpoint_threshold_type: str = config.get(
            BREAKPOINT_THRESHOLD_TYPE_KEY, BREAKPOINT_THRESHOLD_TYPE_DEFAULT
        )
        self.breakpoint_threshold_amount: float | None = config.get(
            BREAKPOINT_THRESHOLD_AMOUNT_KEY, BREAKPOINT_THRESHOLD_AMOUNT_DEFAULT
        )
        self.docling_tokenizer: str = config.get(DOCLING_TOKENIZER_KEY, DOCLING_TOKENIZER_DEFAULT)

        # Summarization configuration (nested structure only)
        summarization_config = config.get(OperatorConstants.Config.SUMMARIZATION, {})

        # Use dict presence pattern - empty dict enables with defaults
        self.enable_summarization: bool = bool(summarization_config)

        if self.enable_summarization:
            # Multi-provider support for summarization
            self.summarization_provider: str = summarization_config.get(
                OperatorConstants.Config.PROVIDER, OperatorConstants.Config.PROVIDER_LITELLM
            )

            self.summarization_provider_config: dict = summarization_config.get(
                OperatorConstants.Config.PROVIDER_CONFIG, {}
            )

            # Get model_id from provider_config
            self.summarization_model: str = self.summarization_provider_config.get(
                OperatorConstants.Config.MODEL_ID, DocpipeConstants.SUMMARY_MODEL_ID_DEFAULT
            )

            # Auto-configure Ollama via LiteLLM if no provider config
            if not self.summarization_provider_config:
                self.summarization_provider_config = {
                    OperatorConstants.Config.API_BASE: "http://localhost:11434/v1",
                    OperatorConstants.Config.API_KEY: "<ollama>",  # pragma: allowlist secret
                }
            # Auto-prefix model with "openai/" for Ollama via LiteLLM if not already prefixed
            # Models starting with provider prefixes (openai/, huggingface/, anthropic/) are passed through as-is
            # OpenAI models (gpt-*) work directly with LiteLLM without needing the openai/ prefix
            # Ollama models (e.g., llama3, mistral) need the openai/ prefix to route through Ollama's OpenAI-compatible API
            if self.summarization_provider == OperatorConstants.Config.PROVIDER_LITELLM:
                if not self.summarization_model.startswith(("openai/", "huggingface/", "anthropic/", "gpt-")):
                    self.summarization_model = f"openai/{self.summarization_model}"

            # Read summarization parameters from nested config
            self.max_length: int = summarization_config.get(
                MAX_INPUT_TOKENS_KEY, DocpipeConstants.MAX_INPUT_TOKENS_DEFAULT
            )
            self.overlap_ratio: float = summarization_config.get(
                OVERLAP_RATIO_KEY, DocpipeConstants.OVERLAP_RATIO_DEFAULT
            )
            self.summary_sentences: int = summarization_config.get(
                SUMMARY_SENTENCES_KEY, DocpipeConstants.SUMMARY_SENTENCES_DEFAULT
            )
            self.summary_max_words: int = summarization_config.get(
                SUMMARY_MAX_WORDS_KEY, DocpipeConstants.SUMMARY_MAX_WORDS_DEFAULT
            )

        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        # Initialize Ollama client for semantic chunking (lazy initialization)
        self._ollama_client: OllamaClient | None = None

        # Docling HybridChunker will be lazily initialized when needed
        self._docling_chunker: object | None = None

        # Simple and semantic splitters will be lazily initialized when needed
        self._simple_splitter: object | None = None
        self._semantic_splitter: object | None = None

        # Summarization service (lazy initialization)
        self._summarization_service = None

        # Provider-based configuration for remote chunking
        self.provider = config.get(OperatorConstants.Config.PROVIDER)
        self.provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        # HTTP client for remote chunking (lazy initialization)
        self._remote_chunking_client = None

    @staticmethod
    def _get_summarization_provider_schemas() -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for the summarization provider_config field.

        Add a new entry here when registering a new summarization provider.
        """
        from docpipe.core.operators.shared.llm_provider_config import LLMProviderConfig, WatsonxProviderConfig

        return {
            OperatorConstants.Config.PROVIDER_LITELLM: OperatorUtils.model_schema_to_docpipe(
                schema=LLMProviderConfig.model_json_schema()
            ),
            OperatorConstants.Config.PROVIDER_WATSONX: OperatorUtils.model_schema_to_docpipe(
                schema=WatsonxProviderConfig.model_json_schema()
            ),
        }

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: ChunkerOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: ChunkerOperator.is_available(),
            OperatorConstants.Misc.LABEL: "Chunking",
            OperatorConstants.Config.DESCRIPTION: "Split document content into smaller chunks using simple, semantic, or Docling-based chunking strategies.",
            OperatorConstants.Config.FEATURES: {
                OperatorConstants.Columns.CHUNK_SEQUENCE_NUMBER: {
                    OperatorConstants.Misc.NAME: "Chunk Sequence number",
                    OperatorConstants.Config.DESCRIPTION: "Sequential chunk number for each text chunk, representing its position within a larger document",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                    OperatorConstants.Misc.TAGS: [
                        OperatorConstants.Misc.MANDATORY,
                        OperatorConstants.Misc.INTERNAL_FEATURE,
                    ],
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_INT64,
                },
                OperatorConstants.Processing.START_INDEX: {
                    OperatorConstants.Misc.NAME: "Start Index",
                    OperatorConstants.Config.DESCRIPTION: "Chunk starting token position in the source document",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                    OperatorConstants.Misc.TAGS: [
                        OperatorConstants.Misc.MANDATORY,
                        OperatorConstants.Misc.INTERNAL_FEATURE,
                    ],
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_INT64,
                },
                OperatorConstants.Columns.CHUNKED_CONTENT: {
                    OperatorConstants.Misc.NAME: "Chunked Content",
                    OperatorConstants.Config.DESCRIPTION: "Content containing segmented portions of larger text data.",
                    OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
            },
            OperatorConstants.Config.ATTRIBUTES: {
                CHUNK_TYPE_KEY: {
                    OperatorConstants.Misc.NAME: "Chunk Type",
                    OperatorConstants.Config.DESCRIPTION: "Type of Chunker model being used",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: CHUNK_TYPE_DEFAULT,
                    OperatorConstants.Config.VALID_VALUES: VALID_CHUNK_TYPES,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Processing.CHUNK_SIZE: {
                    OperatorConstants.Misc.NAME: "Chunk Size",
                    OperatorConstants.Config.DESCRIPTION: "Chunk size in characters (simple: 500-5000) or tokens (docling: 100-2048)."
                    " Validation enforced based on chunk_type. Chunk Size is not used for semantic Chunk Type",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Processing.CHUNK_SIZE_DEFAULT,
                    OperatorConstants.Filtering.MIN_VALUE: DOCLING_CHUNK_SIZE_MIN,  # Use minimum across all types (100)
                    OperatorConstants.Filtering.MAX_VALUE: CHUNK_MAX_SIZE,  # Use maximum across all types (5000)
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                CHUNK_OVERLAP_KEY: {
                    OperatorConstants.Misc.NAME: "Chunk Overlap",
                    OperatorConstants.Config.DESCRIPTION: "If consecutive chunks share overlapping portions to retain context across boundaries",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: CHUNK_OVERLAP_DEFAULT,
                    OperatorConstants.Filtering.MIN_VALUE: CHUNK_OVERLAP_MIN_SIZE,
                    OperatorConstants.Filtering.MAX_VALUE: CHUNK_OVERLAP_MAX_SIZE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                CHUNK_OVERLAP_PERCENTAGE_KEY: {
                    OperatorConstants.Misc.NAME: "Chunk Overlap Percentage",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Overlap expressed as a percentage of chunk_size (0-40). Values above 20 produce a warning."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: CHUNK_OVERLAP_PERCENTAGE_DEFAULT,
                    OperatorConstants.Filtering.MIN_VALUE: CHUNK_OVERLAP_PERCENTAGE_MIN_SIZE,
                    OperatorConstants.Filtering.MAX_VALUE: CHUNK_OVERLAP_PERCENTAGE_MAX_SIZE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                SEMANTIC_EMBEDDINGS_MODEL_KEY: {
                    OperatorConstants.Misc.NAME: "Semantic Embeddings Model",
                    OperatorConstants.Config.DESCRIPTION: "Ollama model name for generating embeddings in semantic chunking. Required if chunking type is semantic.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                BREAKPOINT_THRESHOLD_TYPE_KEY: {
                    OperatorConstants.Misc.NAME: "Breakpoint Threshold Type",
                    OperatorConstants.Config.DESCRIPTION: "Method for determining semantic chunk boundaries",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: BREAKPOINT_THRESHOLD_TYPE_DEFAULT,
                    OperatorConstants.Config.VALID_VALUES: VALID_BREAKPOINT_TYPES,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                BREAKPOINT_THRESHOLD_AMOUNT_KEY: {
                    OperatorConstants.Misc.NAME: "Breakpoint Threshold Amount",
                    OperatorConstants.Config.DESCRIPTION: "Threshold value for the selected breakpoint type (e.g., 95.0 for 95th percentile)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: BREAKPOINT_THRESHOLD_AMOUNT_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                },
                DOCLING_TOKENIZER_KEY: {
                    OperatorConstants.Misc.NAME: "Docling Tokenizer",
                    OperatorConstants.Config.DESCRIPTION: "Tokenizer model to use for Docling chunking (HuggingFace model name)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: DOCLING_TOKENIZER_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                RETAIN_ORIGINAL_CONTENT_KEY: {
                    OperatorConstants.Misc.NAME: "Retain Original Content",
                    OperatorConstants.Config.DESCRIPTION: "Whether to keep the original content column after chunking",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: RETAIN_ORIGINAL_CONTENT_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.Config.SUMMARIZATION: {
                    OperatorConstants.Misc.NAME: "Summarization Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Configuration for chunk summarization. Provide empty dict {} to enable with defaults, or omit to disable.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROPERTIES: {
                        OperatorConstants.Config.PROVIDER: {
                            OperatorConstants.Misc.NAME: "Summarization Provider",
                            OperatorConstants.Config.DESCRIPTION: "LLM provider for summarization: 'litellm' (default, supports 100+ providers) or 'watsonx'",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: OperatorConstants.Config.PROVIDER_LITELLM,
                            OperatorConstants.Config.VALID_VALUES: [
                                OperatorConstants.Config.PROVIDER_LITELLM,
                                "watsonx",
                            ],
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                        OperatorConstants.Config.PROVIDER_CONFIG: {
                            OperatorConstants.Misc.NAME: "Provider Configuration",
                            OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration. Fields vary by provider — see the 'providers' schema for details.",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: {},
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            OperatorConstants.Config.PROVIDERS: ChunkerOperator._get_summarization_provider_schemas(),
                        },
                        SUMMARY_SENTENCES_KEY: {
                            OperatorConstants.Misc.NAME: "Summary Sentences",
                            OperatorConstants.Config.DESCRIPTION: "Number of sentences in each summary",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: DocpipeConstants.SUMMARY_SENTENCES_DEFAULT,
                            OperatorConstants.Filtering.MIN_VALUE: 1,
                            OperatorConstants.Filtering.MAX_VALUE: 5,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                        },
                        SUMMARY_MAX_WORDS_KEY: {
                            OperatorConstants.Misc.NAME: "Summary Max Words",
                            OperatorConstants.Config.DESCRIPTION: "Maximum words per summary",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: DocpipeConstants.SUMMARY_MAX_WORDS_DEFAULT,
                            OperatorConstants.Filtering.MIN_VALUE: 10,
                            OperatorConstants.Filtering.MAX_VALUE: 100,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                        },
                        MAX_INPUT_TOKENS_KEY: {
                            OperatorConstants.Misc.NAME: "Max Input Tokens",
                            OperatorConstants.Config.DESCRIPTION: "Maximum input tokens per summarization request",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: DocpipeConstants.MAX_INPUT_TOKENS_DEFAULT,
                            OperatorConstants.Filtering.MIN_VALUE: 1000,
                            OperatorConstants.Filtering.MAX_VALUE: 32000,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                        },
                        OVERLAP_RATIO_KEY: {
                            OperatorConstants.Misc.NAME: "Overlap Ratio",
                            OperatorConstants.Config.DESCRIPTION: "Ratio of overlap between consecutive text segments during summarization",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: DocpipeConstants.OVERLAP_RATIO_DEFAULT,
                            OperatorConstants.Filtering.MIN_VALUE: 0.0,
                            OperatorConstants.Filtering.MAX_VALUE: 1.0,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                        },
                    },
                },
                # New provider-based configuration (recommended)
                OperatorConstants.Config.PROVIDER: {
                    OperatorConstants.Misc.NAME: "Chunking Provider",
                    OperatorConstants.Config.DESCRIPTION: "Chunking provider: 'docling_library' (local), 'docling_serve' (remote), 'simple', or 'semantic'",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Config.VALID_VALUES: [
                        OperatorConstants.Processing.PROVIDER_DOCLING_LIBRARY,
                        OperatorConstants.Processing.PROVIDER_DOCLING_SERVE,
                        OperatorConstants.Processing.PROVIDER_SIMPLE,
                        OperatorConstants.Processing.PROVIDER_SEMANTIC,
                    ],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration options (nested object)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: {},
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                },
            },
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Get required features."""
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate."""
        super().validate(errors, warnings, available_features)

        # Get metadata and extract ATTRIBUTES for validation
        metadata = self.get_metadata()
        attributes = metadata.get(OperatorConstants.Config.ATTRIBUTES, {})

        # Validate configuration against metadata
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        if OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT in available_features:
            errors.append(
                ValidationMessage.create(
                    message=ValidationCodeMessages.CHUNKER_OPERATOR_MISPLACED.value,
                    message_code=ValidationCodeMessages.CHUNKER_OPERATOR_MISPLACED.name,
                )
            )

        # Validate retain_original_content type
        if self.should_validate_field(field_value=self.retain_original_content):
            if not isinstance(self.retain_original_content, bool):
                errors.append(
                    ValidationMessage.create(
                        message=f"Invalid type for retain_original_content: expected bool, got {type(self.retain_original_content).__name__}",
                        message_code="CHUNKER_INVALID_RETAIN_ORIGINAL_CONTENT_TYPE",
                    )
                )

        # Validate simple chunker parameters (always validate these base parameters)
        ChunkerValidator.validate_simple_chunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            chunk_type=self.chunk_type,
            should_validate_field_fn=self.should_validate_field,
            errors=errors,
        )

        # Validate chunk_overlap_percentage (only meaningful for chunk types that use a fixed overlap window)
        if self.chunk_type in (ChunkType.SIMPLE.value, ChunkType.HYBRID.value):
            ChunkerValidator.validate_overlap_percentage(
                chunk_overlap_percentage=self.chunk_overlap_percentage,
                should_validate_field_fn=self.should_validate_field,
                errors=errors,
                warnings=warnings,
            )

        # Validate semantic chunking parameters if using semantic chunking
        if self.chunk_type == ChunkType.SEMANTIC.value:
            ChunkerValidator.validate_semantic_chunker(
                breakpoint_threshold_type=self.breakpoint_threshold_type,
                breakpoint_threshold_amount=self.breakpoint_threshold_amount,
                semantic_embeddings_model=self.semantic_embeddings_model,
                should_validate_field_fn=self.should_validate_field,
                errors=errors,
            )

        # Validate hybrid chunking parameters if using hybrid chunking
        elif self.chunk_type == ChunkType.HYBRID.value:
            ChunkerValidator.validate_docling_chunker(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                docling_tokenizer=self.docling_tokenizer,
                should_validate_field_fn=self.should_validate_field,
                errors=errors,
            )

        # Validate summarization model and parameters
        ChunkerValidator.validate_summarization(
            enable_summarization=self.enable_summarization,
            summarization_model=self.summarization_model if self.enable_summarization else "",
            should_validate_field_fn=self.should_validate_field,
            errors=errors,
            max_input_tokens=self.max_length if self.enable_summarization else None,
            summary_sentences=self.summary_sentences if self.enable_summarization else None,
            summary_max_words=self.summary_max_words if self.enable_summarization else None,
        )

        # Validate remote chunking configuration (provider-based)
        if self.provider == OperatorConstants.Processing.PROVIDER_DOCLING_SERVE:
            # Validate base URL
            api_base = self.provider_config.get(OperatorConstants.Config.API_BASE)
            if not api_base:
                errors.append(
                    ValidationMessage.create(
                        message="API base URL is required in provider_config when provider is 'docling_serve'",
                        message_code="DOCLING_SERVE_BASE_URL_REQUIRED",
                    )
                )

            # Validate timeout
            timeout = self.provider_config.get(OperatorConstants.Processing.TIMEOUT, 300)
            if timeout <= 0:
                errors.append(
                    ValidationMessage.create(
                        message="Timeout must be positive in provider_config",
                        message_code="DOCLING_SERVE_TIMEOUT_INVALID",
                    )
                )

            # Validate poll interval
            poll_interval = self.provider_config.get(OperatorConstants.Processing.POLL_INTERVAL, 2)
            if poll_interval <= 0:
                errors.append(
                    ValidationMessage.create(
                        message="Poll interval must be positive in provider_config",
                        message_code="DOCLING_SERVE_POLL_INTERVAL_INVALID",
                    )
                )

            # Validate max retries
            max_retries = self.provider_config.get(OperatorConstants.Processing.MAX_RETRIES, 3)
            if max_retries < 0:
                errors.append(
                    ValidationMessage.create(
                        message="Max retries must be non-negative in provider_config",
                        message_code="DOCLING_SERVE_MAX_RETRIES_INVALID",
                    )
                )

            # Warn if using docling-serve with non-hybrid chunk type
            if self.chunk_type != ChunkType.HYBRID.value:
                warnings.append(
                    ValidationMessage.create(
                        message=f"Provider 'docling_serve' is enabled but chunk_type is '{self.chunk_type}'. "
                        "Remote chunking works best with 'hybrid' chunk type.",
                        message_code="DOCLING_SERVE_CHUNK_TYPE_MISMATCH",
                    )
                )

    def _get_docling_serve_client(self):
        """
        Lazy initialization of HTTP client for docling-serve chunking API.

        Creates and caches a RestClient instance configured for docling-serve requests.
        The client is reused across multiple chunking operations for efficiency.

        Returns:
            RestClient: Configured HTTP client

        Raises:
            DocpipeException: If client initialization fails
        """
        if self._remote_chunking_client is None:
            try:
                from docpipe.integrations.rest_client import RestClient, RestClientConfig

                # Get configuration from provider_config
                timeout = self.provider_config.get(OperatorConstants.Processing.TIMEOUT, 300)
                max_retries = self.provider_config.get(OperatorConstants.Processing.MAX_RETRIES, 3)
                verify_ssl = self.provider_config.get(OperatorConstants.Processing.VERIFY_SSL, True)
                api_base = self.provider_config.get(OperatorConstants.Config.API_BASE, "http://localhost:5001")

                # Initialize RestClient with configuration
                rest_config = RestClientConfig(
                    timeout=timeout,
                    max_retries=max_retries,
                    verify_ssl=verify_ssl,
                )
                self._remote_chunking_client = RestClient(
                    config=rest_config,
                    base_url=api_base,
                )
                logger.info(
                    "Initialized docling-serve chunking client for %s", api_base, extra=self.common_log_arguments
                )
            except Exception as e:
                raise DocpipeException(f"Failed to initialize docling-serve HTTP client: {e!s}") from e
        return self._remote_chunking_client

    def _docling_serve_split_text(self, *, content: str, doc_name: str | None = None) -> list[Document]:
        """
        Perform remote chunking using docling-serve API.

        Sends markdown content to docling-serve's /v1/chunk/hybrid/source endpoint for chunking.
        The markdown content is base64-encoded and sent in a JSON request body with proper
        convert_options and chunking_options.

        Args:
            content: Text content to split into chunks
            doc_name: Optional document name for metadata

        Returns:
            List of Document objects containing chunks from docling-serve

        Raises:
            DocpipeException: If API request fails or response is invalid
        """
        import base64

        from docpipe.integrations.rest_client import RestMethod

        client = self._get_docling_serve_client()

        try:
            # Base64 encode the markdown content
            encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            markdown_filename = str(Path(doc_name).with_suffix(".md")) if doc_name else DEFAULT_DOCUMENT_NAME

            # Prepare JSON payload for /v1/chunk/hybrid/source endpoint
            payload = {
                "sources": [{"kind": "file", "base64_string": encoded_content, "filename": markdown_filename}],
                "convert_options": {"from_formats": ["md"], "to_formats": ["md"]},
                "include_converted_doc": False,
                "target": {"kind": "inbody"},
                "chunking_options": {
                    "chunker": "hybrid",
                    "tokenizer": self.docling_tokenizer,
                    "max_tokens": self.chunk_size,
                    "merge_peers": True,
                    "use_markdown_tables": False,
                    "include_raw_text": False,
                },
            }

            # Prepare headers
            headers = {"Content-Type": "application/json"}
            api_key = self.provider_config.get(OperatorConstants.Config.API_KEY)
            if api_key:
                headers["X-Api-Key"] = api_key

            # Make request to docling-serve
            logger.info(
                "Sending chunking request to docling-serve for document: %s",
                doc_name or "unnamed",
                extra=self.common_log_arguments,
            )
            response = client.call_rest_json(
                method=RestMethod.POST,
                url="/v1/chunk/hybrid/source",
                json_data=payload,
                headers=headers,
            )

            # Parse response
            if not isinstance(response, dict):
                raise DocpipeException(f"Invalid response from docling-serve: expected dict, got {type(response)}")

            # Debug: Log the full response to understand structure
            logger.info(
                "Docling-serve response keys: %s, content length: %s",
                list(response.keys()),
                len(content),
                extra=self.common_log_arguments,
            )

            chunks_data = response.get("chunks", [])

            if not chunks_data:
                logger.warning(
                    "Docling-serve returned no chunks for content of length %s",
                    len(content),
                    extra=self.common_log_arguments,
                )
                return []

            # Convert to LangChain Documents
            documents = []
            for idx, chunk in enumerate(chunks_data):
                if isinstance(chunk, dict):
                    chunk_text = chunk.get("text", "")
                else:
                    chunk_text = str(chunk)

                if chunk_text:
                    doc = Document(
                        page_content=chunk_text,
                        metadata={
                            "chunk_index": idx,
                            "start_index": (
                                chunk.get("start_index", idx * self.chunk_size)
                                if isinstance(chunk, dict)
                                else idx * self.chunk_size
                            ),
                            "source": OperatorConstants.Processing.PROVIDER_DOCLING_SERVE,
                            "doc_name": doc_name,
                        },
                    )
                    documents.append(doc)

            logger.info("Docling-serve chunking produced %s chunks", len(documents), extra=self.common_log_arguments)
            return documents

        except Exception as e:
            raise DocpipeException(f"Docling-serve chunking failed: {e!s}") from e

    def _get_simple_splitter(self):
        """
        Lazy initialization of RecursiveCharacterTextSplitter for simple chunking.

        Creates and caches a splitter instance configured with the fixed chunk_size
        and chunk_overlap. The splitter is reused across all documents for efficiency.

        Returns:
            RecursiveCharacterTextSplitter: Configured splitter for simple chunking
        """
        if self._simple_splitter is None:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            self._simple_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=[".", "\n\n", "\n", " ", ""],
                add_start_index=True,
            )
        return self._simple_splitter

    def _simple_split_text(self, content: str) -> list[Document]:
        """
        Perform simple fixed-size chunking with overlap using LangChain's CharacterTextSplitter.

        This is an internal method that splits text into chunks of approximately equal size
        with configurable overlap between consecutive chunks. Uses period (.) as the primary
        separator.

        Args:
            content: Text content to split into chunks

        Returns:
            List of Document objects, each containing a chunk of text

        Note:
            Uses self.chunk_size and self.chunk_overlap configuration parameters.
            This method is called internally by _split_text() and should not be called directly.
        """
        doc: Document = Document(page_content=content, metadata={"source": "parameter"})
        return self._get_simple_splitter().split_documents([doc])

    def _get_ollama_client(self) -> OllamaClient:
        """
        Lazy initialization of OllamaClient for semantic chunking.

        Creates and caches an OllamaClient instance configured with the semantic
        embeddings model. The client is reused across multiple chunking operations
        for efficiency. Reuses the same client pattern as EmbeddingsOperator.

        Returns:
            OllamaClient: Configured client for generating embeddings

        Raises:
            DocpipeException: If client initialization fails

        Note:
            The client is initialized with validate_model=True to ensure the
            specified model is available before use. If provider_config contains
            a 'host' parameter, it will be used to connect to a custom Ollama server.
        """
        if self._ollama_client is None:
            try:
                host = self.provider_config.get(OperatorConstants.VectorDB.HOST) if self.provider_config else None
                self._ollama_client = OllamaClient(
                    model_name=self.semantic_embeddings_model,
                    mode=InteractionMode.EMBEDDINGS,
                    host=host,
                    validate_model=True,
                )
                logger.info(
                    "Initialized OllamaClient with model: %s",
                    self.semantic_embeddings_model,
                    extra=self.common_log_arguments,
                )
            except Exception as e:
                raise DocpipeException(f"Failed to initialize OllamaClient for semantic chunking: {e!s}") from e
        return self._ollama_client

    def _semantic_split_text(self, content: str) -> list[Document]:
        """
        Perform semantic chunking using LangChain's SemanticChunker with Ollama embeddings.

        This is an internal method that uses embeddings to identify natural breakpoints in
        text based on semantic similarity. Text is split into sentences, embeddings are
        generated for sentence groups, and chunks are created at points where semantic
        similarity drops below the configured threshold.

        The method integrates with the project's OllamaClient for consistency with other
        operators and reuses the embeddings infrastructure.

        Args:
            content: Text content to split into semantic chunks

        Returns:
            List of Document objects, each containing a semantically coherent chunk

        Raises:
            DocpipeException: If semantic_embeddings_model is not configured, or if
                OllamaClient initialization or embedding generation fails

        Note:
            Uses configuration parameters:
            - self.semantic_embeddings_model: Ollama model for embeddings (required)
            - self.breakpoint_threshold_type: Method for detecting boundaries
            - self.breakpoint_threshold_amount: Threshold value for the method
            This method is called internally by _split_text() and should not be called directly.
        """
        # Validate that semantic_embeddings_model is configured for semantic chunking
        if not self.semantic_embeddings_model:
            raise DocpipeException(
                "The 'semantic_embeddings_model' parameter is required for semantic chunking but was not provided. "
                "Please add 'semantic_embeddings_model' to your chunker configuration with a valid Ollama model name."
            )

        text_splitter = self._get_semantic_splitter()

        # Split the text semantically
        docs = text_splitter.create_documents([content])

        logger.debug(
            "Semantic chunking created %s chunks using OllamaClient (threshold_type=%s, threshold_amount=%s)",
            len(docs),
            self.breakpoint_threshold_type,
            self.breakpoint_threshold_amount,
            extra=self.common_log_arguments,
        )

        return docs

    def _get_semantic_splitter(self):
        """
        Lazy initialization of SemanticChunker for semantic chunking.

        Creates and caches a SemanticChunker instance configured with the Ollama
        embeddings model and breakpoint threshold settings. The splitter is reused
        across all documents for efficiency.

        Returns:
            SemanticChunker: Configured chunker for semantic chunking

        Raises:
            DocpipeException: If OllamaClient initialization fails
        """
        if self._semantic_splitter is None:
            try:
                from langchain_experimental.text_splitter import SemanticChunker

                # Get OllamaClient instance (reuses existing pattern from EmbeddingsOperator)
                ollama_client = self._get_ollama_client()

                # Use the OllamaClientEmbeddings adapter to make OllamaClient compatible with LangChain
                embeddings = OllamaClientEmbeddings(ollama_client)

                # Cast breakpoint_threshold_type to the expected Literal type for mypy
                threshold_type = cast(
                    Literal["percentile", "standard_deviation", "interquartile", "gradient"],
                    self.breakpoint_threshold_type,
                )

                if self.breakpoint_threshold_amount is not None:
                    self._semantic_splitter = SemanticChunker(
                        embeddings=embeddings,
                        breakpoint_threshold_type=threshold_type,
                        breakpoint_threshold_amount=self.breakpoint_threshold_amount,
                    )
                else:
                    self._semantic_splitter = SemanticChunker(
                        embeddings=embeddings,
                        breakpoint_threshold_type=threshold_type,
                    )
            except DocpipeException:
                raise
            except Exception as e:
                raise DocpipeException(f"Failed to initialize SemanticChunker: {e!s}") from e
        return self._semantic_splitter

    def _get_docling_chunker(self):
        """
        Lazy initialization of Docling HybridChunker.

        Creates and caches a HybridChunker instance configured with the specified
        tokenizer and chunk size. The chunker is reused across multiple chunking
        operations for efficiency.

        Returns:
            HybridChunker: Configured chunker for Docling-based chunking

        Raises:
            DocpipeException: If chunker initialization fails

        Note:
            Uses self.docling_tokenizer and self.chunk_size configuration parameters.
        """
        if self._docling_chunker is None:
            try:
                from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                from transformers import AutoTokenizer

                hf_tokenizer = HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self.docling_tokenizer),  # nosec B615 — revision pinning is the user's responsibility via docling_tokenizer config
                    max_tokens=self.chunk_size,
                )
                self._docling_chunker = HybridChunker(
                    tokenizer=hf_tokenizer,
                    merge_peers=True,  # Merge chunks at the same hierarchy level
                )
                logger.info(
                    "Initialized Docling HybridChunker with tokenizer: %s, max_tokens: %s",
                    self.docling_tokenizer,
                    self.chunk_size,
                    extra=self.common_log_arguments,
                )
            except Exception as e:
                raise DocpipeException(f"Failed to initialize Docling HybridChunker: {e!s}") from e
        return self._docling_chunker

    @staticmethod
    def _create_docling_document_from_doclang(*, doclang_content: str, doc_name: str | None = None):
        """
        Create a DoclingDocument by deserializing DocLang XML content.

        Uses DocLangDocDeserializer to parse DocLang XML into a DoclingDocument.
        If deserialization fails or docling_core is unavailable, falls back to
        converting DocLang to Markdown and building via MarkdownDocumentBackend.

        Args:
            doclang_content: DocLang XML text content
            doc_name: Document name used as filename hint

        Returns:
            DoclingDocument instance with full structural metadata
        """
        try:
            deserializer = OperatorUtils.get_doclang_deserializer()
            if deserializer is not None:
                return deserializer.deserialize_str(doclang_content)
            raise ImportError("docling_core is not available")
        except Exception as e:
            logger.warning(
                "Direct DocLang deserialization failed: %s; falling back to Markdown document backend for hybrid chunking",
                e,
            )
            markdown_content = OperatorUtils.doclang_to_markdown(doclang_content)
            return ChunkerOperator._create_docling_document_from_markdown(
                markdown_content=markdown_content, doc_name=doc_name
            )

    @staticmethod
    def _create_docling_document_from_markdown(*, markdown_content: str, doc_name: str | None = None):
        """
        Create a structure-preserving DoclingDocument from markdown content.

        Uses MarkdownDocumentBackend to parse the markdown so that headings,
        tables, and code blocks are represented as typed nodes in the resulting
        DoclingDocument. This is required for HybridChunker to exploit document
        structure; without it, hybrid chunking degrades to simple chunking.

        Args:
            markdown_content: Markdown text content
            doc_name: Document name used as the filename hint for the backend

        Returns:
            DoclingDocument instance with full structural metadata
        """
        from docling.backend.md_backend import MarkdownDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.document import InputDocument

        filename = doc_name or "document.md"
        stream = io.BytesIO(markdown_content.encode("utf-8"))
        in_doc = InputDocument(
            path_or_stream=stream,
            format=InputFormat.MD,
            backend=MarkdownDocumentBackend,
            filename=filename,
        )
        backend = MarkdownDocumentBackend(in_doc=in_doc, path_or_stream=stream)
        return backend.convert()

    @staticmethod
    def _prepare_text_for_splitting(*, content: str, doc_format: str) -> str:
        """
        Prepare text for plain-text splitters (simple and semantic).

        Converts DocLang XML to Markdown when doc_format is DOCLANG.

        Args:
            content: Raw text or DocLang XML string.
            doc_format: Format mode from configuration.

        Returns:
            Clean text/markdown string suitable for splitting.
        """
        if doc_format == OperatorConstants.DocFormat.DOCLANG:
            return OperatorUtils.doclang_to_markdown(content)
        return content

    def _docling_split_text(self, *, content: str, doc_name: str | None = None) -> list[Document]:
        """
        Perform Docling-based chunking using HybridChunker.

        This is an internal method that uses Docling's hybrid chunking approach which combines:
        - Hierarchical chunking (respects document structure)
        - Semantic chunking (groups related content)

        Args:
            content: Text content to split into chunks
            doc_name: Optional document name for metadata

        Returns:
            List of Document objects, each containing a chunk of text with metadata

        Raises:
            DocpipeException: If chunking fails

        Note:
            Uses self.chunk_size and self.docling_tokenizer configuration parameters.
            This method is called internally by _split_text() and should not be called directly.
        """
        try:
            # Get the Docling chunker instance
            chunker = self._get_docling_chunker()

            # Create DoclingDocument from DocLang or markdown content based on doc_format
            if self.doc_format == OperatorConstants.DocFormat.DOCLANG:
                docling_doc = self._create_docling_document_from_doclang(doclang_content=content, doc_name=doc_name)
            else:
                docling_doc = self._create_docling_document_from_markdown(markdown_content=content, doc_name=doc_name)

            # Chunk the document
            chunk_iter = chunker.chunk(dl_doc=docling_doc)

            # Convert chunks to LangChain Document format
            docs: list[Document] = []
            for idx, chunk in enumerate(chunk_iter):
                doc = Document(
                    page_content=chunk.text,
                    metadata={
                        "start_index": getattr(chunk, "start_index", idx * self.chunk_size),
                        "chunk_id": idx,
                        "doc_name": doc_name,
                        "token_count": len(chunk.text.split()),  # Approximate token count
                    },
                )
                docs.append(doc)

            logger.debug(
                "Docling chunking created %s chunks",
                len(docs),
                extra=self.common_log_arguments,
            )

            return docs

        except Exception as e:
            logger.error(
                "Error in Docling chunking: %s",
                e,
                extra=self.common_log_arguments,
            )
            raise DocpipeException(f"Docling chunking failed: {e!s}") from e

    def _split_text(self, *, content: str, doc_name: str | None = None) -> list[Document]:
        """
        Route text to the appropriate chunking method based on chunk_type.

        This is an internal dispatcher method that selects the chunking strategy
        (simple, semantic, hybrid, or docling-serve) based on configuration.

        Args:
            content: Text content to split into chunks
            doc_name: Optional document name for metadata

        Returns:
            List of Document objects containing chunks

        Raises:
            DocpipeException: If an invalid chunk_type is configured

        Note:
            This method is called internally by transform() and should not be called directly.
        """
        # For hybrid chunking, raw content (XML or MD) is parsed into DoclingDocument
        chunk_type: str = self.chunk_type.lower()
        if (
            chunk_type == ChunkType.HYBRID.value
            and self.provider != OperatorConstants.Processing.PROVIDER_DOCLING_SERVE
        ):
            return self._docling_split_text(content=content, doc_name=doc_name)

        # For plain-text splitters (simple, semantic, docling-serve), prepare text once
        prepared_text = self._prepare_text_for_splitting(content=content, doc_format=self.doc_format)

        if self.provider == OperatorConstants.Processing.PROVIDER_DOCLING_SERVE:
            return self._docling_serve_split_text(content=prepared_text, doc_name=doc_name)
        if chunk_type == ChunkType.SIMPLE.value:
            return self._simple_split_text(prepared_text)
        if chunk_type == ChunkType.SEMANTIC.value:
            return self._semantic_split_text(prepared_text)
        raise DocpipeException(f"Invalid chunk type: {self.chunk_type}")

    def _initialize_summarization(self, metadata: dict[str, Any]) -> bool:
        """
        Initialize LLM adapter for summarization if enabled.

        Uses the common LLM infrastructure (LLMAdapterFactory) to support multiple providers
        (LiteLLM, WatsonX) instead of being hardcoded to Ollama.

        Args:
            metadata: Metadata dictionary to update with warnings if initialization fails

        Returns:
            bool: True if initialization successful, False otherwise

        Note:
            Updates metadata with warnings and status if initialization fails.
            Sets self._summarization_service on success.
        """
        if not self.enable_summarization:
            return False

        try:
            from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory

            llm_adapter = LLMAdapterFactory.create_inference_adapter(
                provider=self.summarization_provider,
                model_id=self.summarization_model,
                provider_config=self.summarization_provider_config,
            )

            # Create the summarization service with the LLM adapter
            self._summarization_service = SummarizationService(
                llm_adapter=llm_adapter,
                max_input_tokens=self.max_length,
                overlap_ratio=self.overlap_ratio,
                summary_sentences=self.summary_sentences,
                summary_max_words=self.summary_max_words,
            )

            logger.info(
                "Initialized summarization with provider=%s, model=%s",
                self.summarization_provider,
                self.summarization_model,
                extra=self.common_log_arguments,
            )
            return True

        except Exception as e:
            logger.warning(
                "Summarization initialization failed, skipping summary generation: %s",
                e,
                exc_info=True,
                extra=self.common_log_arguments,
            )
            self.enable_summarization = False
            metadata[Metrics.External.PROCESSING_MESSAGE] = (
                "Failed to generate summary as summarization model initialization failed"
            )
            current_status = metadata[Metrics.External.NODE_STATUS]
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
                ExecutionStatus.COMPLETED_WITH_WARNINGS,
            ).value
            return False

    @staticmethod
    def _build_chunk_dicts(*, chunks: list) -> list[dict[str, Any]]:
        """Convert a list of Document chunks into the serialisable dict format."""
        chunked_content: list[dict[str, Any]] = []
        for chunk_seq, chunk in enumerate(chunks):
            chunked_content.append(
                {
                    OperatorConstants.Columns.CHUNK: chunk.page_content,
                    OperatorConstants.Columns.CHUNK_SEQUENCE_NUMBER: chunk_seq,
                    OperatorConstants.Processing.START_INDEX: chunk.metadata.get(
                        OperatorConstants.Processing.START_INDEX, 0
                    )
                    if chunk.metadata
                    else 0,
                }
            )
        return chunked_content

    def _apply_summarization(
        self, *, doc: dict[str, Any], chunked_content: list[dict[str, Any]], metadata: dict[str, Any]
    ) -> None:
        """Generate summaries for chunked content when summarisation is enabled, logging warnings on failure."""
        if not (self.enable_summarization and chunked_content and self._summarization_service):
            return
        try:
            self._summarization_service.generate_summary_for_chunked_content(chunked_content=chunked_content)
        except Exception as e:
            logger.warning(
                "Summary generation failed for document %s: %s",
                doc.get(OperatorConstants.Misc.NAME, doc.get(OperatorConstants.Columns.ID)),
                e,
                extra=self.common_log_arguments,
            )
            metadata[Metrics.External.PROCESSING_MESSAGE] = "Failed to generate summary for some or all documents"
            current_status = metadata[Metrics.External.NODE_STATUS]
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
                ExecutionStatus.COMPLETED_WITH_WARNINGS,
            ).value

    def _process_single_document(
        self, doc: dict[str, Any], idx: int, metadata: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """
        Process a single document to create chunks.

        Args:
            doc: Document dictionary containing content and metadata
            idx: Document index in the input data
            metadata: Metadata dictionary to update with processing results

        Returns:
            The chunked_content list, or None if processing failed and the row should be removed

        Note:
            Updates metadata with error information if processing fails
        """
        try:
            logger.debug(
                "Creating chunks for the document %s with %s chunk type",
                doc.get(OperatorConstants.Misc.NAME, doc.get(OperatorConstants.Columns.ID)),
                self.chunk_type.lower(),
                extra=self.common_log_arguments,
            )

            # Check if the column exists first
            if self.doc_column not in doc:
                raise DocpipeException(
                    f"The column '{self.doc_column}' was not found in the input data. "
                    f"Available columns: {list(doc.keys())}. "
                    f"This may occur if: (1) the previous extraction operator failed to produce content, "
                    f"(2) the doc_column configuration doesn't match between operators, or "
                    f"(3) a merge operator is using 'columns' merge type instead of 'rows'."
                )

            content: str = doc[self.doc_column]
            if not content or (isinstance(content, str) and not content.strip()):
                raise DocpipeException(
                    f"The column '{self.doc_column}' exists but contains empty or whitespace-only content."
                )
            doc_name = str(doc.get(OperatorConstants.Misc.NAME, doc.get(OperatorConstants.Columns.ID, "")))
            chunks: list[Document] = self._split_text(content=content, doc_name=doc_name)
        except Exception as exc:
            logger.exception(
                "An error occurred while creating chunking for the document %s : \n %s",
                doc.get(OperatorConstants.Misc.NAME, doc.get(OperatorConstants.Columns.ID)),
                exc,
                stack_info=True,
            )
            self.record_failed_document(
                metadata=metadata,
                doc_id=str(doc.get(OperatorConstants.Columns.ID, "")),
                doc_name=str(doc.get(OperatorConstants.Misc.NAME, "")),
                reason=f"Failed to create a data chunk for the document '{doc.get(OperatorConstants.Misc.NAME)}' due to the following error: {getattr(exc, 'message', str(exc)) if getattr(exc, 'message', str(exc)) else getattr(exc, 'message', repr(exc))}",
            )
            current_status = metadata[Metrics.External.NODE_STATUS]
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
                ExecutionStatus.COMPLETED_WITH_ERRORS,
            ).value
            return None

        chunked_content = self._build_chunk_dicts(chunks=chunks)
        self._apply_summarization(doc=doc, chunked_content=chunked_content, metadata=metadata)
        return chunked_content

    def _finalize_table(
        self, table: pa.Table, chunked_content_column: list[list[dict[str, Any]]], total_chunks: int
    ) -> pa.Table:
        """
        Finalize the output table by adding chunked content and optionally removing original content.
        Writes chunks to binary files and stores file path references in the table.

        Args:
            table: Input PyArrow table
            chunked_content_column: List of chunked content for each document
            total_chunks: Total number of chunks created

        Returns:
            Finalized PyArrow table with chunked content (as binary file path references)

        Note:
            Removes original content column if retain_original_content is False
        """
        if chunked_content_column:
            # Check if memmap storage is enabled
            memmap_threshold = self.config.get(
                DocpipeConstants.MEMMAP_THRESHOLD, DocpipeConstants.MEMMAP_THRESHOLD_DEFAULT
            )
            table_size = get_pyarrow_table_size_mb(table)

            if table_size > memmap_threshold > 0:
                # Write chunks to binary files and create path references
                chunks_column_data = []

                # Create base directory for chunks binary files with job_id/job_run_id structure
                chunks_dir = get_data_path(sub_dir=f"/{self.job_id}/{self.job_run_id}/temp_data/chunked_content")

                # Get document IDs from table for filename generation
                doc_ids = (
                    table[OperatorConstants.Columns.ID].to_pylist()
                    if OperatorConstants.Columns.ID in table.column_names
                    else None
                )

                for idx, chunks_list in enumerate(chunked_content_column):
                    # Generate filename using sanitized document ID
                    if doc_ids and idx < len(doc_ids):
                        from docpipe.core.operators.operator_utils import sanitize_doc_id_for_filename

                        sanitized_doc_id = sanitize_doc_id_for_filename(doc_ids[idx])
                        chunks_filename = f"{sanitized_doc_id}_chunks.bin"
                    else:
                        # Fallback to UUID if doc_id not available
                        chunks_filename = f"chunks_{uuid.uuid4().hex}.bin"
                    chunks_filepath = str(Path(chunks_dir) / chunks_filename)

                    # Write chunks to binary file
                    write_chunks_to_file(chunks_list=chunks_list, filepath=chunks_filepath)

                    # Store file path reference in table
                    chunks_column_data.append({DocpipeConstants.CHUNKS_MEMMAP_FILE: chunks_filepath})

                    logger.debug(
                        "Wrote %s chunks to binary file: %s",
                        len(chunks_list),
                        chunks_filepath,
                        extra=self.common_log_arguments,
                    )

                # Add column with binary file path references
                table = TransformUtils.add_column(
                    table=table,
                    name=OperatorConstants.Columns.CHUNKED_CONTENT,
                    content=chunks_column_data,
                )
            else:
                # Store chunks directly in table (original behavior)
                table = TransformUtils.add_column(
                    table=table,
                    name=OperatorConstants.Columns.CHUNKED_CONTENT,
                    content=chunked_content_column,
                )
            logger.info(
                "Added chunked_content column with %s total chunks", total_chunks, extra=self.common_log_arguments
            )

        # If original content is not to be retained then drop the content column.
        if self.doc_column in table.column_names and not self.retain_original_content:
            table = table.drop_columns([self.doc_column])
            logger.info("Dropped original content column: %s", self.doc_column, extra=self.common_log_arguments)

        return table

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform."""
        logger.info("Using %s for generating chunks", self.chunk_type, extra=self.common_log_arguments)

        input_doc_data: list[dict[str, Any]] = table.to_pylist()
        chunked_content_column: list[list[dict[str, Any]]] = []
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=OperatorUtils.find_doc_count(table=table))

        # Initialize summarization if enabled
        self._initialize_summarization(metadata)

        # Process each document
        total_chunks: int = 0
        remove_row_idx: list[int] = []
        for idx, doc in enumerate(input_doc_data):
            chunked_content = self._process_single_document(doc, idx, metadata)

            if chunked_content is None:
                remove_row_idx.append(idx)
                continue

            chunked_content_column.append(chunked_content)
            metadata[Metrics.External.PROCESSED_DOCS] += 1
            total_chunks += len(chunked_content)

        # Add total_chunks to metadata
        metadata[Metrics.External.TOTAL_CHUNKS] = total_chunks

        # Remove failed rows and finalize table
        table = OperatorUtils.remove_rows(table=table, remove_row_idx=remove_row_idx)
        table = self._finalize_table(table, chunked_content_column, total_chunks)

        return [table], metadata
