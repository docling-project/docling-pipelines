"""
Embeddings Operator

This operator generates vector embeddings for text content using LLM providers.
Supports watsonx and litellm (which provides access to 100+ providers including Ollama, HuggingFace, OpenAI, etc.).
"""

import contextvars
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
    ServiceConstants,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.core.memmap_file_utils import write_content_to_file
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.config_validation import validate_config_from_metadata

logger = get_logger()

# Overlap ratio for chunking
OVERLAP_RATIO_KEY: str = "overlap_ratio"
OVERLAP_RATIO_DEFAULT: float = 0.2
OVERLAP_RATIO_MIN: float = 0.0
OVERLAP_RATIO_MAX: float = 0.5

# Token limit for chunking
TOKEN_LIMIT_KEY: str = "token_limit"
TOKEN_LIMIT_DEFAULT: int = 8192

# Provider configuration key
PROVIDER_KEY: str = "provider"
PROVIDER_DEFAULT: str = "litellm"

# Fallback zero-vector dimension when no successful embedding has been produced yet
EMBEDDING_DIM_FALLBACK: int = 384

# Where the vector for one input text comes from once the provider has answered:
#   None      -> empty/whitespace-only text, filled with a zero vector
#   int       -> position of the text in the flattened request stream
#   list[int] -> positions of the pieces of a text longer than the char limit (averaged)
_TextSlot = int | list[int] | None

# HTTP statuses with which a provider rejects the content of a request (invalid input,
# payload too large, unprocessable text). Only these failures can depend on which texts
# were sent together; any other status (401/403/404, 408, 429, 5xx, ...) is provider-wide.
_INPUT_DEPENDENT_HTTP_STATUSES: frozenset[int] = frozenset({400, 413, 422})

# Message fragments of errors raised for a text that is too long for the model. Some
# providers (e.g. older Ollama releases) report them with a generic 5xx status.
_INPUT_DEPENDENT_ERROR_MARKERS: tuple[str, ...] = ("context length", "context window")


class EmbeddingsOperator(AbstractOperator):  # type: ignore[misc]
    """
    Operator for generating embeddings using LLM providers.

    This operator processes documents and generates vector embeddings using
    watsonx or litellm providers. It supports:
    - Multiple embedding providers (watsonx, litellm)
    - Automatic chunking for long text
    - Pre-chunked content processing
    - Document hash generation
    - Error handling per document
    - Batch processing across documents: texts from all documents of a slice are sent
      in requests of ``batch_size`` texts, with up to ``max_concurrent_requests``
      requests in flight (both reported by the embedding adapter)

    Supported Providers:
    - watsonx: IBM watsonx.ai embedding models
    - litellm: 100+ providers via LiteLLM including:
      * Ollama (via OpenAI-compatible API with model prefix 'openai/')
      * HuggingFace (via API with model prefix 'huggingface/')
      * OpenAI, Anthropic, Cohere, AWS Bedrock, Google Vertex AI, and 90+ more

    LiteLLM Provider Examples:
    - OpenAI: text-embedding-3-small, text-embedding-ada-002
    - Ollama: openai/nomic-embed-text, openai/llama2
    - HuggingFace: huggingface/sentence-transformers/all-MiniLM-L6-v2
    - Azure OpenAI, Cohere, Bedrock, Vertex AI, etc.

    Attributes:
        provider (str): Embedding provider (watsonx or litellm)
        provider_config (dict): Provider-specific configuration
            - model_id (str): Model identifier in <provider>/<model_id> format for litellm
            - api_base (str): API endpoint URL (optional)
            - api_key (str): Authentication key (optional)
        embeddings_column (str): Output column name for embeddings
        overlap_ratio (float): Overlap ratio for chunking long text (0.0-0.5)
        token_limit (int): Maximum token limit for text chunking
        doc_column (str): Input column containing document content
        doc_id_hash_column (str): Column for document hash
    """

    short_name: str = OperatorConstants.Operators.EMBEDDINGS
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the Embeddings Operator.

        Args:
            config: Configuration dictionary containing:
                - provider: Provider type ("watsonx" or "litellm", default: "litellm")
                - provider_config: Provider-specific configuration dictionary containing:
                    - model_id: Model identifier in <provider>/<model_id> format for litellm (e.g., "openai/nomic-embed-text")
                    - batch_size: Texts per embedding request, across documents (optional)
                    - max_concurrent_requests: Embedding requests kept in flight at once (optional)
                - embeddings_column: Output column name for embeddings (default: "embeddings")
                - overlap_ratio: Overlap ratio for chunking long text (default: 0.2)
                - token_limit: Maximum token limit for chunking (default: 8192)
                - doc_column: Input column containing document content (default: "content")
                - doc_id_hash_column: Column for document hash (default: "doc_id_hash")
        """
        super().__init__(config)

        # Provider configuration
        self.provider: str = config.get(PROVIDER_KEY, PROVIDER_DEFAULT).lower()

        # Provider-specific configuration
        self.provider_config: dict[str, Any] = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        # Model configuration - now from provider_config
        self.model_id: str = self.provider_config.get(OperatorConstants.Config.MODEL_ID, "openai/nomic-embed-text")

        # Column names
        self.embeddings_column: str = config.get(
            OperatorConstants.Columns.EMBEDDINGS_COLUMN,
            OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT,
        )
        self.doc_id_hash_column: str = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )

        # Chunking configuration
        self.overlap_ratio: float = config.get(OVERLAP_RATIO_KEY, OVERLAP_RATIO_DEFAULT)
        self.token_limit: int = config.get(TOKEN_LIMIT_KEY, TOKEN_LIMIT_DEFAULT)

        # Logging
        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        # Initialize embedding adapter using unified factory
        self.embedding_adapter: LLMEmbeddingPort = self._initialize_embedding_adapter()

        # Cache DocIdHashOperator instance to avoid re-instantiation on every transform() call
        self._doc_id_op: DocIdHashOperator = DocIdHashOperator(
            config={
                OperatorConstants.Columns.DOC_COLUMN: self.doc_column,
                OperatorConstants.Columns.DOC_ID_HASH: self.doc_id_hash_column,
            }
        )

        # Cached embedding dimension — determined on first successful embedding call
        self._embedding_dim: int | None = None

        # Request shaping reported by the adapter (configured via provider_config.batch_size
        # and provider_config.max_concurrent_requests).
        self._batch_size: int = self._positive_int_or_default(
            value=self.embedding_adapter.get_embedding_batch_size(),
            default=ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
        )
        self._max_concurrent_requests: int = self._positive_int_or_default(
            value=self.embedding_adapter.get_max_concurrent_requests(),
            default=1,
        )

        logger.info(
            "Initialized EmbeddingsOperator with provider: %s, model: %s, batch_size: %s, max_concurrent_requests: %s",
            self.provider,
            self.model_id,
            self._batch_size,
            self._max_concurrent_requests,
            extra=self.common_log_arguments,
        )

    @staticmethod
    def _positive_int_or_default(*, value: Any, default: int) -> int:
        """Return ``value`` when it is a positive int, otherwise ``default``."""
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return default
        return value

    def _initialize_embedding_adapter(self) -> LLMEmbeddingPort:
        """
        Initialize the appropriate embedding adapter based on provider.

        Uses the unified LLMAdapterFactory to create adapters for watsonx or litellm providers.

        Returns:
            The initialized embedding adapter implementing LLMEmbeddingPort

        Raises:
            DocpipeException: If the provider is unsupported or initialization fails
        """
        try:
            # Create adapter using unified factory
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider=self.provider,
                model_id=self.model_id,
                provider_config=self.provider_config,
            )

            # Validate adapter configuration
            self._validate_adapter(adapter)

            return adapter
        except Exception as e:
            raise DocpipeException(f"Failed to initialize embedding adapter '{self.provider}': {e!s}") from e

    def _validate_adapter(self, adapter: LLMEmbeddingPort) -> None:
        """Validate embedding adapter configuration on initialization.

        Args:
            adapter: The embedding adapter to validate

        Raises:
            DocpipeException: If adapter validation fails
        """
        result = adapter.validate()

        # Log warnings
        if result.get("warnings"):
            for warning in result["warnings"]:
                logger.warning("Embedding adapter validation warning: %s", warning)

        # Raise error if validation failed
        if not result.get("valid", True):
            errors = result.get("errors", ["Unknown validation error"])
            raise DocpipeException(
                message=f"Embedding adapter validation failed: {'; '.join(errors)}",
                status_code=400,
            )

    @staticmethod
    def get_required_features() -> list[str]:
        """Return list of required input features."""
        return []

    def _validate_provider(self, *, errors: list[str]) -> None:
        """Validate provider type and value against supported providers."""
        if not self.should_validate_field(field_value=self.provider):
            return
        if not isinstance(self.provider, str):
            errors.append(f"provider must be a string, got {type(self.provider)}")
            return
        supported_providers = LLMAdapterFactory.get_supported_providers(capability="embedding")
        if self.provider not in supported_providers:
            errors.append(f"provider must be one of {sorted(supported_providers)}, got '{self.provider}'")

    def _validate_overlap_and_token(self, *, errors: list[str]) -> None:
        """Validate overlap_ratio and token_limit configuration values."""
        if self.should_validate_field(field_value=self.overlap_ratio):
            if not isinstance(self.overlap_ratio, (int, float)):
                errors.append(f"overlap_ratio must be a number, got {type(self.overlap_ratio)}")
            elif not (OVERLAP_RATIO_MIN <= self.overlap_ratio <= OVERLAP_RATIO_MAX):
                errors.append(f"overlap_ratio must be between {OVERLAP_RATIO_MIN} and {OVERLAP_RATIO_MAX}")

        if self.should_validate_field(field_value=self.token_limit):
            if not isinstance(self.token_limit, int):
                errors.append(f"token_limit must be an integer, got {type(self.token_limit)}")
            elif self.token_limit <= 0:
                errors.append(f"token_limit must be positive, got {self.token_limit}")

    def _validate_provider_config(self, *, errors: list[str]) -> None:
        """Validate provider_config dict including model_id, max_concurrent_requests, and batch_size."""
        if not self.should_validate_field(field_value=self.provider_config):
            return
        if not isinstance(self.provider_config, dict):
            errors.append(f"provider_config must be a dictionary, got {type(self.provider_config)}")
            return

        model_id = self.provider_config.get(OperatorConstants.Config.MODEL_ID)
        if not model_id or not isinstance(model_id, str):
            errors.append("provider_config.model_id is required and must be a non-empty string")

        max_concurrent_requests = self.provider_config.get(OperatorConstants.Config.MAX_CONCURRENT_REQUESTS)
        if max_concurrent_requests is not None and self.should_validate_field(field_value=max_concurrent_requests):
            if not isinstance(max_concurrent_requests, int):
                errors.append(
                    f"provider_config.max_concurrent_requests must be an integer, got {type(max_concurrent_requests).__name__}"
                )
            elif max_concurrent_requests <= 0:
                errors.append(
                    f"provider_config.max_concurrent_requests must be positive, got {max_concurrent_requests}"
                )

        batch_size = self.provider_config.get(OperatorConstants.Config.BATCH_SIZE)
        if batch_size is not None and self.should_validate_field(field_value=batch_size):
            if not isinstance(batch_size, int):
                errors.append(f"provider_config.batch_size must be an integer, got {type(batch_size).__name__}")
            elif batch_size <= 0:
                errors.append(f"provider_config.batch_size must be positive, got {batch_size}")

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """
        Validate operator configuration.

        Args:
            errors: List to append validation errors
            warnings: List to append validation warnings
            available_features: List of available input features
        """
        super().validate(errors, warnings, available_features)

        # Check for content OR chunked_content column
        has_content = OperatorConstants.Columns.DOC_COLUMN_DEFAULT in available_features
        has_chunked_content = OperatorConstants.Columns.CHUNKED_CONTENT in available_features

        if not has_content and not has_chunked_content:
            errors.append(
                f"Embeddings operator requires either '{OperatorConstants.Columns.DOC_COLUMN_DEFAULT}' "
                f"or '{OperatorConstants.Columns.CHUNKED_CONTENT}' column to be available"
            )

        # Validate configuration against metadata
        metadata = self.get_metadata()
        attributes = metadata.get(OperatorConstants.Config.ATTRIBUTES, {})
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        self._validate_provider(errors=errors)
        self._validate_overlap_and_token(errors=errors)
        self._validate_provider_config(errors=errors)

        # Check if chunked_content feature is available (always validate, even during flow validation)
        if OperatorConstants.Columns.CHUNKED_CONTENT not in available_features:
            from docpipe.exceptions.error_messages import ValidationCodeMessages

            warnings.append(ValidationCodeMessages.CHUNKER_OPERATOR_MISSING)

    @staticmethod
    def _get_embeddings_provider_schemas() -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for the provider_config field.

        Add a new entry here when registering a new embeddings provider.
        """
        from docpipe.core.operators.shared.llm_provider_config import (
            LLMEmbeddingProviderConfig,
            WatsonxEmbeddingProviderConfig,
        )

        return {
            OperatorConstants.Config.PROVIDER_LITELLM: OperatorUtils.model_schema_to_docpipe(
                schema=LLMEmbeddingProviderConfig.model_json_schema()
            ),
            OperatorConstants.Config.PROVIDER_WATSONX: OperatorUtils.model_schema_to_docpipe(
                schema=WatsonxEmbeddingProviderConfig.model_json_schema()
            ),
        }

    @staticmethod
    def _get_embedding_provider_names() -> list[str]:
        """Return registered embedding provider names from the local adapter factory."""
        from docpipe.core.operators.functional.embeddings.adapters.outbound.factories.llm_adapter_factory import (
            LLMAdapterFactory as LocalLLMAdapterFactory,
        )

        return LocalLLMAdapterFactory.list_adapters()

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """
        Return operator metadata for UI and documentation.

        Returns:
            dict: Operator metadata including features and attributes
        """
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: OperatorCategory.Functional.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: EmbeddingsOperator.is_available(),
            OperatorConstants.Misc.LABEL: "Embeddings",
            OperatorConstants.Config.DESCRIPTION: "Generate vector embeddings using watsonx or litellm (100+ providers including Ollama, HuggingFace, OpenAI, Azure, Cohere, etc.)",
            OperatorConstants.Config.FEATURES: {
                OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT: {
                    OperatorConstants.Misc.NAME: "Embeddings",
                    OperatorConstants.Config.DESCRIPTION: "Vector embeddings generated from document content",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                    OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB: True,
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_VECTOR,
                },
            },
            OperatorConstants.Config.ATTRIBUTES: {
                PROVIDER_KEY: {
                    OperatorConstants.Misc.NAME: "Provider",
                    OperatorConstants.Config.DESCRIPTION: "Embedding provider: litellm (100+ providers including Ollama, OpenAI, Azure, Cohere), watsonx (IBM watsonx.ai), or huggingface (local inference).",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Config.DEFAULT: PROVIDER_DEFAULT,
                    OperatorConstants.Config.VALID_VALUES: EmbeddingsOperator._get_embedding_provider_names(),
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration. Fields vary by provider — see the 'providers' schema for details.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROVIDERS: EmbeddingsOperator._get_embeddings_provider_schemas(),
                },
                OperatorConstants.Columns.EMBEDDINGS_COLUMN: {
                    OperatorConstants.Misc.NAME: "Embeddings Column",
                    OperatorConstants.Config.DESCRIPTION: "Name of the output column for embeddings",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OVERLAP_RATIO_KEY: {
                    OperatorConstants.Misc.NAME: "Overlap Ratio",
                    OperatorConstants.Config.DESCRIPTION: "Overlap ratio for chunking long text (0.0 to 0.5)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OVERLAP_RATIO_DEFAULT,
                    OperatorConstants.Filtering.MIN_VALUE: OVERLAP_RATIO_MIN,
                    OperatorConstants.Filtering.MAX_VALUE: OVERLAP_RATIO_MAX,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                },
                TOKEN_LIMIT_KEY: {
                    OperatorConstants.Misc.NAME: "Token Limit",
                    OperatorConstants.Config.DESCRIPTION: "Maximum token limit for text chunking. Most embedding models support 512-8192 tokens. Adjust based on your model's context window.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: TOKEN_LIMIT_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
            },
        }

    @staticmethod
    def _build_chunk_text_for_embedding(*, chunk: dict[str, Any]) -> str:
        """
        Prepends summary to chunk text if summary is present.
        chunk text will be generated as : abstract: <summary>\ncontent: <chunk_text>

        Args:
            chunk: Dictionary containing chunk data with 'chunk' and optionally 'summary' keys

        Returns:
            Formatted chunk text with optional summary prefix
        """
        chunk_text = chunk.get(OperatorConstants.Columns.CHUNK, "")

        if not chunk_text:
            return ""

        # If summary exists, prepend it to the chunk text
        summary = chunk.get(OperatorConstants.Columns.SUMMARY)
        if summary:
            return f"abstract: {summary}\ncontent: {chunk_text}"

        return str(chunk_text)

    @staticmethod
    def _generate_document_hash(content: str) -> str:
        """
        Generate a SHA-256 hash for document content.

        Args:
            content: Document content string

        Returns:
            64-character hexadecimal SHA-256 hash string
        """
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _build_embedding_error(self, *, error: Exception, text_count: int) -> DocpipeException:
        """
        Log a failed embedding request and wrap it in a context-aware DocpipeException.

        Args:
            error: The exception raised by the embedding adapter
            text_count: Number of texts in the failed request

        Returns:
            DocpipeException describing the failure, chained to ``error``
        """
        error_msg = str(error)

        # Check if this is a context length error (from any provider)
        if "input length exceeds the context length" in error_msg.lower() or "context length" in error_msg.lower():
            logger.error(
                "Context length exceeded in a request of %d texts: text is too long for model '%s'",
                text_count,
                self.model_id,
                exc_info=error,
                extra=self.common_log_arguments,
            )
            wrapped = DocpipeException(
                f"Chunked text exceeds the configured embeddings model's (Provider: {self.provider}, "
                f"Model: {self.model_id}) context length. Add Chunking operator and/or adjust the chunk_type/chunk_size"
                " in Chunking operator and the Embeddings model ID in Embeddings operator to avoid this error."
            )
        else:
            logger.error(
                "Failed to generate embeddings for a request of %d texts: %s",
                text_count,
                error_msg,
                exc_info=error,
                extra=self.common_log_arguments,
            )
            wrapped = DocpipeException(f"Batch embedding generation failed: {error!s}")
        wrapped.__cause__ = error
        return wrapped

    @staticmethod
    def _split_long_text(*, text: str, char_limit: int, overlap_chars: int) -> list[str]:
        """
        Split a text longer than ``char_limit`` into overlapping pieces.

        Args:
            text: Text to split
            char_limit: Maximum characters per piece
            overlap_chars: Characters shared by consecutive pieces

        Returns:
            Ordered list of pieces covering the whole text
        """
        pieces: list[str] = []
        start: int = 0
        while start < len(text):
            end: int = start + char_limit
            pieces.append(text[start:end])
            start = end - overlap_chars if end < len(text) else end
        return pieces

    def _plan_document_texts(self, *, texts: list[str], flat_texts: list[str]) -> list[_TextSlot]:
        """
        Append the texts of one document to the flattened request stream.

        Texts longer than the approximate character limit (``token_limit`` * 4) are split
        into overlapping pieces whose embeddings are averaged afterwards.

        Args:
            texts: Texts of one document (one output vector per text)
            flat_texts: Request stream shared by all documents; extended in place

        Returns:
            One slot per input text describing where its vector comes from
        """
        # Approximate: 1 token = 4 characters
        char_limit: int = self.token_limit * 4
        overlap_chars: int = int(char_limit * self.overlap_ratio)

        slots: list[_TextSlot] = []
        for idx, text_item in enumerate(texts):
            if not text_item or not text_item.strip():
                # Empty text - filled with a zero vector once the dimension is known
                slots.append(None)
            elif len(text_item) <= char_limit:
                slots.append(len(flat_texts))
                flat_texts.append(text_item)
            else:
                pieces = self._split_long_text(text=text_item, char_limit=char_limit, overlap_chars=overlap_chars)
                logger.debug(
                    "Text at index %d (length %d) exceeds limit %d, split into %d pieces",
                    idx,
                    len(text_item),
                    char_limit,
                    len(pieces),
                    extra=self.common_log_arguments,
                )
                slots.append(list(range(len(flat_texts), len(flat_texts) + len(pieces))))
                flat_texts.extend(pieces)
        return slots

    def _embed_request(self, *, texts: list[str]) -> list[list[float]] | DocpipeException:
        """
        Embed one request worth of texts (at most ``batch_size``).

        Retries are handled by the adapter, so a transient failure re-sends only this
        request. A permanent failure is returned instead of raised so that the caller
        can decide which documents it affects (see ``_embed_documents``).

        Args:
            texts: Texts sent together in one provider request

        Returns:
            One vector per text in order, or the error that failed the request
        """
        try:
            vectors = self.embedding_adapter.generate_embeddings_batch(texts=texts)
            if len(vectors) != len(texts):
                raise DocpipeException(f"Embedding provider returned {len(vectors)} vectors for {len(texts)} texts")
            return vectors
        except Exception as e:
            return self._build_embedding_error(error=e, text_count=len(texts))

    def _run_requests(self, *, requests: list[list[str]]) -> list[list[list[float]] | DocpipeException]:
        """
        Run embedding requests with at most ``max_concurrent_requests`` in flight.

        Args:
            requests: Texts of each request, in stream order

        Returns:
            Result of each request (vectors or error), in the same order as ``requests``
        """
        workers = min(self._max_concurrent_requests, len(requests))
        if workers <= 1:
            return [self._embed_request(texts=request) for request in requests]

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="EmbeddingsRequest") as executor:
            # Each task runs in a copy of the caller's context so the session info
            # (job_id, job_run_id) stays visible to logging inside the worker threads.
            futures = [
                executor.submit(contextvars.copy_context().run, self._embed_request, texts=request)
                for request in requests
            ]
            return [future.result() for future in futures]

    def _assemble_document_vectors(
        self,
        *,
        slots: list[_TextSlot],
        flat_vectors: list[list[float] | None],
    ) -> list[list[float]]:
        """
        Build the output vectors of one document from the flattened request results.

        Args:
            slots: Slots returned by ``_plan_document_texts`` for the document
            flat_vectors: Vectors of the flattened request stream

        Returns:
            One vector per input text, in input order
        """
        vectors: list[list[float]] = []
        for idx, slot in enumerate(slots):
            if slot is None:
                # Empty text — use a zero vector matching the model's actual output dimension.
                # Fall back to 384 only if no successful embedding has been produced yet.
                dim = self._embedding_dim if self._embedding_dim is not None else EMBEDDING_DIM_FALLBACK
                logger.warning(
                    "Empty text at index %d provided for embedding generation",
                    idx,
                    extra=self.common_log_arguments,
                )
                vectors.append([0.0] * dim)
            elif isinstance(slot, int):
                vectors.append(flat_vectors[slot])  # type: ignore[arg-type]
            else:
                # Average the embeddings of the pieces of a long text
                vectors.append(np.mean([flat_vectors[pos] for pos in slot], axis=0).tolist())
        return vectors

    @staticmethod
    def _error_chain(error: BaseException) -> list[BaseException]:
        """
        Return ``error`` followed by the exceptions it was raised from.

        Follows ``__cause__`` (``raise ... from``) and otherwise the implicit
        ``__context__`` unless it was suppressed, stopping at the first repeated exception.

        Args:
            error: Outermost exception

        Returns:
            The exceptions of the chain, outermost first
        """
        chain: list[BaseException] = []
        current: BaseException | None = error
        while current is not None and all(current is not seen for seen in chain):
            chain.append(current)
            current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        return chain

    @staticmethod
    def _http_status_of(error: BaseException) -> int | None:
        """
        Return the HTTP status a provider answered with, if ``error`` carries one.

        LiteLLM/OpenAI exceptions expose ``status_code``; requests/httpx/huggingface_hub
        HTTP errors expose ``response.status_code``. ``DocpipeException.status_code``
        defaults to 500/502 for any error, so it is only trusted for the REST client's
        HTTP errors (``ErrorCode.HTTP_ERROR``, used by the watsonx client).

        Args:
            error: One exception of an error chain

        Returns:
            The HTTP status, or None when the exception does not carry one
        """
        if isinstance(error, DocpipeException):
            status = error.status_code if error.error_code == ErrorCode.HTTP_ERROR else None
        else:
            status = getattr(error, "status_code", None)
            if status is None:
                status = getattr(getattr(error, "response", None), "status_code", None)
        return status if isinstance(status, int) and not isinstance(status, bool) else None

    @staticmethod
    def _is_input_dependent_error(error: BaseException) -> bool:
        """
        Tell whether a failed request could have failed because of one of its texts.

        Input-dependent: a context-length / context-window error (by message, whatever
        the status), or an HTTP 400, 413 or 422 response (bad request, payload too large,
        unprocessable input, which includes LiteLLM's ``ContextWindowExceededError`` and
        ``ContentPolicyViolationError``). The first HTTP status found in the error chain
        decides; any other status (rate limit, timeout, authentication, not found, 5xx)
        and errors without an HTTP status (connection errors, malformed responses, local
        failures) are treated as provider-wide, because re-sending the texts would fail
        the same way and only add load.

        Args:
            error: Error of a failed embedding request, possibly wrapped by the client,
                adapter and operator layers

        Returns:
            True when re-sending each document on its own can isolate the failure
        """
        chain = EmbeddingsOperator._error_chain(error)
        if any(marker in str(exc).lower() for exc in chain for marker in _INPUT_DEPENDENT_ERROR_MARKERS):
            return True
        for exc in chain:
            status = EmbeddingsOperator._http_status_of(exc)
            if status is not None:
                return status in _INPUT_DEPENDENT_HTTP_STATUSES
        return False

    def _route_failed_request(
        self,
        *,
        error: Exception,
        owners: list[int],
        stream_start: int,
        doc_errors: dict[int, Exception],
        retry_positions: dict[int, list[int]],
    ) -> None:
        """
        Decide what happens to the documents of a request that failed permanently.

        The documents are retried in isolation only when the request carried texts of
        several documents and the error could depend on one of those texts. Otherwise
        (a single-document request, or a provider-wide error such as a rate limit,
        timeout, outage or authentication failure) every document of the request fails
        with ``error`` and nothing is re-sent.

        Args:
            error: Error of the failed request
            owners: Owning document of each text of the request, in stream order
            stream_start: Stream position of the first text of the request
            doc_errors: Error per failed document; extended in place
            retry_positions: Stream positions to retry in isolation, per document;
                extended in place
        """
        documents = list(dict.fromkeys(owners))
        if len(documents) > 1 and self._is_input_dependent_error(error):
            for offset, doc_pos in enumerate(owners):
                retry_positions.setdefault(doc_pos, []).append(stream_start + offset)
            return
        if len(documents) > 1:
            logger.warning(
                "A shared embedding request failed with an error that does not depend on its texts; "
                "failing its %d documents without re-sending them",
                len(documents),
                extra=self.common_log_arguments,
            )
        for doc_pos in documents:
            doc_errors.setdefault(doc_pos, error)

    def _embed_in_isolation(
        self,
        *,
        positions_by_doc: dict[int, list[int]],
        flat_texts: list[str],
        flat_vectors: list[list[float] | None],
    ) -> dict[int, Exception]:
        """
        Re-embed texts of failed shared requests, one document per request.

        Only the texts that were in failed requests are re-sent, grouped per document in
        requests of at most ``batch_size`` texts (with up to ``max_concurrent_requests`` in
        flight). The number of extra requests is bounded by the number of failed shared
        requests plus the number of affected documents.

        Args:
            positions_by_doc: Stream positions to re-embed, per document
            flat_texts: Flattened request stream
            flat_vectors: Vectors of the stream; filled in place for successful requests

        Returns:
            The error of each document that still fails on its own
        """
        batch_size = self._batch_size
        groups: list[tuple[int, list[int]]] = [
            (doc_pos, positions[start : start + batch_size])
            for doc_pos, positions in positions_by_doc.items()
            for start in range(0, len(positions), batch_size)
        ]
        logger.warning(
            "A shared embedding request failed; re-embedding %d affected documents in isolation (%d requests)",
            len(positions_by_doc),
            len(groups),
            extra=self.common_log_arguments,
        )

        errors: dict[int, Exception] = {}
        results = self._run_requests(requests=[[flat_texts[pos] for pos in positions] for _, positions in groups])
        for (doc_pos, positions), result in zip(groups, results, strict=True):
            if isinstance(result, Exception):
                errors.setdefault(doc_pos, result)
                continue
            for pos, vector in zip(positions, result, strict=True):
                flat_vectors[pos] = vector
            if self._embedding_dim is None and result:
                self._embedding_dim = len(result[0])
        return errors

    def _embed_documents(self, *, texts_per_doc: list[list[str]]) -> list[list[list[float]] | Exception]:
        """
        Embed the texts of several documents using shared, full-size requests.

        All texts are flattened into one stream, sent in requests of ``batch_size``
        texts with up to ``max_concurrent_requests`` requests in flight, and the
        resulting vectors are scattered back to their documents in order.

        A request that fails permanently fails all documents whose texts it carried,
        without re-sending them, unless it carried texts of several documents and its
        error could depend on one of those texts (see ``_is_input_dependent_error``):
        then each of those documents is re-embedded in isolation (see
        ``_embed_in_isolation``) so that one bad text only fails its own document.

        Args:
            texts_per_doc: Texts of each document (one output vector per text)

        Returns:
            Per document, either its vectors (one per input text, in order) or the
            error that failed it
        """
        flat_texts: list[str] = []
        flat_owner: list[int] = []
        slots_per_doc: list[list[_TextSlot]] = []
        doc_errors: dict[int, Exception] = {}

        for doc_pos, texts in enumerate(texts_per_doc):
            stream_start = len(flat_texts)
            try:
                slots = self._plan_document_texts(texts=texts, flat_texts=flat_texts)
            except Exception as e:
                del flat_texts[stream_start:]
                doc_errors[doc_pos] = e
                slots = []
            flat_owner.extend([doc_pos] * (len(flat_texts) - stream_start))
            slots_per_doc.append(slots)

        batch_size = self._batch_size
        requests = [flat_texts[start : start + batch_size] for start in range(0, len(flat_texts), batch_size)]
        if requests:
            logger.info(
                "Embedding %d texts from %d documents in %d requests (batch_size=%d, max_concurrent_requests=%d)",
                len(flat_texts),
                len(texts_per_doc),
                len(requests),
                batch_size,
                self._max_concurrent_requests,
                extra=self.common_log_arguments,
            )

        flat_vectors: list[list[float] | None] = [None] * len(flat_texts)
        # Stream positions of failed shared requests, per document, to retry in isolation
        retry_positions: dict[int, list[int]] = {}
        for request_idx, result in enumerate(self._run_requests(requests=requests)):
            start = request_idx * batch_size
            end = start + len(requests[request_idx])
            if isinstance(result, Exception):
                self._route_failed_request(
                    error=result,
                    owners=flat_owner[start:end],
                    stream_start=start,
                    doc_errors=doc_errors,
                    retry_positions=retry_positions,
                )
                continue
            flat_vectors[start:end] = result
            # Cache embedding dimension from the first result available
            if self._embedding_dim is None and result:
                self._embedding_dim = len(result[0])

        # A document whose own single-document request already failed is not retried
        retry_positions = {doc: pos for doc, pos in retry_positions.items() if doc not in doc_errors}
        if retry_positions:
            for doc_pos, error in self._embed_in_isolation(
                positions_by_doc=retry_positions, flat_texts=flat_texts, flat_vectors=flat_vectors
            ).items():
                doc_errors.setdefault(doc_pos, error)

        results: list[list[list[float]] | Exception] = []
        for doc_pos, slots in enumerate(slots_per_doc):
            if doc_pos in doc_errors:
                results.append(doc_errors[doc_pos])
            else:
                results.append(self._assemble_document_vectors(slots=slots, flat_vectors=flat_vectors))
        return results

    def _get_doc_identifiers(self, table: pa.Table, idx: int) -> tuple[str, str]:
        """
        Get document ID and name from table at given index.

        Args:
            table: PyArrow table containing documents
            idx: Row index

        Returns:
            tuple: (doc_id, doc_name) as strings
        """
        doc_id: str = (
            table[OperatorConstants.Columns.ID][idx].as_py()
            if OperatorConstants.Columns.ID in table.column_names
            else f"doc_{idx}"
        )
        doc_name: str = (
            table[OperatorConstants.Columns.NAME][idx].as_py()
            if OperatorConstants.Columns.NAME in table.column_names
            else str(doc_id)
        )
        return str(doc_id), str(doc_name)

    def _parse_chunked_content(self, table: pa.Table, idx: int, doc_name: str) -> list[str]:
        """
        Parse and extract text from chunked content.

        Args:
            table: PyArrow table containing documents
            idx: Row index
            doc_name: Document name for logging

        Returns:
            List of text strings from chunks

        Raises:
            DocpipeException: If chunked content is invalid or empty
        """
        chunked_content_raw: str | list[Any] | dict[str, Any] = table[OperatorConstants.Columns.CHUNKED_CONTENT][
            idx
        ].as_py()
        if not chunked_content_raw:
            raise DocpipeException("Chunked content is empty")

        # Parse chunked_content - it can be a JSON string, a list, or a dict with file path reference
        chunked_content: list[Any] = []
        if isinstance(chunked_content_raw, dict) and DocpipeConstants.CHUNKS_MEMMAP_FILE in chunked_content_raw:
            # Load chunks from binary file
            chunks_filepath = chunked_content_raw[DocpipeConstants.CHUNKS_MEMMAP_FILE]
            logger.debug(
                "Loading chunks from binary file: %s for document: %s",
                chunks_filepath,
                doc_name,
                extra=self.common_log_arguments,
            )
            from docpipe.utils.core.memmap_file_utils import load_chunks_from_file

            chunked_content = load_chunks_from_file(filepath=chunks_filepath)
        elif isinstance(chunked_content_raw, str):
            # Parse JSON string from chunker operator
            try:
                chunked_content = json.loads(chunked_content_raw)
                logger.debug(
                    "Parsed chunked_content from JSON string for document: %s",
                    doc_name,
                    extra=self.common_log_arguments,
                )
            except json.JSONDecodeError as e:
                logger.error(
                    "Failed to parse chunked_content JSON for document %s: %s",
                    doc_name,
                    e,
                    extra=self.common_log_arguments,
                )
                raise DocpipeException(f"Invalid chunked_content JSON format: {e!s}") from e
        elif isinstance(chunked_content_raw, list):
            # Already a list
            chunked_content = chunked_content_raw
            logger.debug(
                "Using chunked_content as list for document: %s",
                doc_name,
                extra=self.common_log_arguments,
            )
        else:
            raise DocpipeException(f"Unexpected chunked_content type: {type(chunked_content_raw).__name__}")

        # Extract text from chunks - handle both dict and string formats
        texts: list[str] = []
        for chunk in chunked_content:
            if isinstance(chunk, dict):
                # Chunk is a dictionary with 'chunk' key
                chunk_text = self._build_chunk_text_for_embedding(chunk=chunk)
                if chunk_text:
                    texts.append(chunk_text)
            elif isinstance(chunk, str):
                # Chunk is already a string
                if chunk:
                    texts.append(chunk)
            else:
                logger.warning(
                    "Skipping chunk with unexpected type: %s",
                    type(chunk).__name__,
                    extra=self.common_log_arguments,
                )

        if not texts:
            raise DocpipeException("No valid text chunks found after parsing")

        logger.debug(
            "Processing %s chunks for document: %s",
            len(texts),
            doc_name,
            extra=self.common_log_arguments,
        )
        return texts

    def _get_full_document_content(self, table: pa.Table, idx: int) -> list[str]:
        """
        Extract full document content as a single-item list.

        Args:
            table: PyArrow table containing documents
            idx: Row index

        Returns:
            List containing single document content string

        Raises:
            DocpipeException: If content is missing or empty
        """
        content: str = table[self.doc_column][idx].as_py()
        if not content:
            raise DocpipeException(f"Document content column '{self.doc_column}' is empty or missing")

        # Convert DocLang to markdown for unchunked pipelines where EmbeddingsOperator
        # operates directly on the raw document content column without a preceding ChunkerOperator
        if self.doc_format == OperatorConstants.DocFormat.DOCLANG:
            content = OperatorUtils.doclang_to_markdown(content)

        return [content]

    def _handle_doc_hash_generation_failure(
        self, table: pa.Table, error: Exception, metadata: dict[str, Any]
    ) -> tuple[pa.Table, dict[str, Any]]:
        """
        Handle failure in document hash generation by marking all docs as failed.

        Args:
            table: PyArrow table containing documents
            error: The exception that occurred
            metadata: Metadata dictionary to update

        Returns:
            tuple: (empty table slice, updated metadata)
        """
        logger.error(
            "Failed to generate document hashes: %s",
            error,
            extra=self.common_log_arguments,
        )

        # Mark all documents as failed
        for idx in range(table.num_rows):
            doc_id, doc_name = self._get_doc_identifiers(table, idx)
            self.record_failed_document(
                metadata=metadata,
                doc_id=doc_id,
                doc_name=doc_name,
                reason=str(error),
            )

        current_status = metadata[Metrics.External.NODE_STATUS]
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
            current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
            ExecutionStatus.COMPLETED_WITH_ERRORS,
        ).value
        return [table.slice(0, 0)], metadata

    def _update_doc_hash_column(self, table: pa.Table, doc_id_hashes: list[str]) -> pa.Table:
        """
        Update or add document hash column to table.

        Args:
            table: PyArrow table to update
            doc_id_hashes: List of document hashes

        Returns:
            Updated PyArrow table with hash column
        """
        if not doc_id_hashes:
            return table

        if self.doc_id_hash_column in table.column_names:
            table = table.drop_columns([self.doc_id_hash_column])

        table = TransformUtils.add_column(table=table, name=self.doc_id_hash_column, content=doc_id_hashes)

        logger.info(
            "Added document hash column '%s' to table",
            self.doc_id_hash_column,
            extra=self.common_log_arguments,
        )
        return table

    def _store_embedding_for_row(
        self,
        *,
        idx: int,
        embeddings: list[float] | list[list[float]],
        chunks_column_data: list | None,
        doc_ids: list | None,
        embeddings_dir_ref: list[str | None],
    ) -> dict[str, str] | list[float] | list[list[float]]:
        """
        Decide whether to write embeddings to a memmap file (when the matching
        chunk row is already file-backed) or keep them in memory.

        ``embeddings_dir_ref`` is a one-element list used as a mutable reference
        so the directory path is lazily initialised only once per slice.
        """
        row_chunks_as_files = (
            chunks_column_data is not None
            and idx < len(chunks_column_data)
            and isinstance(chunks_column_data[idx], dict)
            and DocpipeConstants.CHUNKS_MEMMAP_FILE in chunks_column_data[idx]
        )
        if not row_chunks_as_files:
            return embeddings  # type: ignore[return-value]

        # Lazy-initialise the embeddings directory once per slice
        if embeddings_dir_ref[0] is None:
            embeddings_dir_ref[0] = get_data_path(
                sub_dir=f"/{self.job_id}/{self.job_run_id}/temp_data/embeddings/{self.embeddings_column}"
            )

        if doc_ids and idx < len(doc_ids):
            from docpipe.core.operators.operator_utils import sanitize_doc_id_for_filename

            embeddings_filename = f"{sanitize_doc_id_for_filename(doc_ids[idx])}_embeddings.bin"
        else:
            embeddings_filename = f"embeddings_{uuid.uuid4().hex}.bin"

        embeddings_filepath = str(Path(embeddings_dir_ref[0] or "") / embeddings_filename)
        write_content_to_file(content_list=embeddings, filepath=embeddings_filepath)
        logger.debug("Wrote embeddings to memmap file: %s", embeddings_filepath, extra=self.common_log_arguments)
        return {DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: embeddings_filepath}

    def _add_embeddings_to_slice(
        self,
        *,
        slice_table: pa.Table,
        slice_embeddings: list,
        slice_doc_id_hashes: list[str],
        has_chunked_content: bool,
    ) -> pa.Table:
        """
        Attach the generated embeddings (and updated doc-id hashes) to a
        slice table, routing each row to either in-memory or file-backed
        storage depending on whether its chunks are already file-backed.
        """
        chunks_column_data = (
            slice_table[OperatorConstants.Columns.CHUNKED_CONTENT].to_pylist() if has_chunked_content else None
        )
        doc_ids = (
            slice_table[OperatorConstants.Columns.ID].to_pylist()
            if OperatorConstants.Columns.ID in slice_table.column_names
            else None
        )
        embeddings_dir_ref: list[str | None] = [None]

        embeddings_column_data: list[dict[str, str] | list[float] | list[list[float]]] = [
            self._store_embedding_for_row(
                idx=idx,
                embeddings=emb,
                chunks_column_data=chunks_column_data,
                doc_ids=doc_ids,
                embeddings_dir_ref=embeddings_dir_ref,
            )
            for idx, emb in enumerate(slice_embeddings)
        ]

        slice_table = TransformUtils.add_column(
            table=slice_table, name=self.embeddings_column, content=embeddings_column_data
        )
        logger.info("Added embeddings column '%s' to table", self.embeddings_column, extra=self.common_log_arguments)

        if self.doc_id_hash_column in slice_table.column_names:
            slice_table = slice_table.drop_columns([self.doc_id_hash_column])
            slice_table = TransformUtils.add_column(
                table=slice_table, name=self.doc_id_hash_column, content=slice_doc_id_hashes
            )
        return slice_table

    def _ensure_doc_id_hash_column(self, *, table: pa.Table) -> tuple[pa.Table, Exception | None]:
        """
        Make sure the doc_id_hash column exists, generating it when it does not.

        Returns ``(table, None)`` on success, or ``(table, error)`` when the hash
        cannot be generated — the caller turns that error into a failure result.
        """
        if self.doc_id_hash_column in table.column_names:
            return table, None

        # DocIdHashOperator needs the content column to derive a hash from.
        if self.doc_column not in table.column_names:
            return table, DocpipeException(
                f"Cannot generate '{self.doc_id_hash_column}' column: '{self.doc_column}' column is missing."
            )

        try:
            result_tables: list[pa.Table]
            result_tables, _ = self._doc_id_op.transform(table)
            return result_tables[0], None
        except Exception as e:
            return table, e

    def _embed_slice_rows(
        self,
        *,
        slice_table: pa.Table,
        has_chunked_content: bool,
        metadata: dict[str, Any],
    ) -> tuple[list, list[str], list[int]]:
        """
        Embed every row of one slice.

        Texts of all rows are embedded together (see ``_embed_documents``); outcomes are
        then recorded per document in row order.

        Returns (embeddings, doc_id_hashes, indices of rows that failed).
        """
        slice_embeddings: list[list[float] | list[list[float]]] = []
        slice_doc_id_hashes: list[str] = []
        slice_remove_idx: list[int] = []
        slice_hash_values: list[str] = slice_table[self.doc_id_hash_column].to_pylist()

        # Extract the texts of every row; rows whose content cannot be read fail here
        row_texts: dict[int, list[str]] = {}
        row_errors: dict[int, Exception] = {}
        for i in range(slice_table.num_rows):
            try:
                if has_chunked_content:
                    _doc_id, doc_name = self._get_doc_identifiers(slice_table, i)
                    row_texts[i] = self._parse_chunked_content(slice_table, i, doc_name)
                else:
                    row_texts[i] = self._get_full_document_content(slice_table, i)
            except Exception as exc:
                row_errors[i] = exc

        embedded_rows = list(row_texts)
        doc_results = self._embed_documents(texts_per_doc=[row_texts[i] for i in embedded_rows])
        row_vectors: dict[int, list[list[float]]] = {}
        for i, result in zip(embedded_rows, doc_results, strict=True):
            if isinstance(result, Exception):
                row_errors[i] = result
            else:
                row_vectors[i] = result

        for i in range(slice_table.num_rows):
            doc_id, doc_name = self._get_doc_identifiers(slice_table, i)
            if i in row_errors:
                error = row_errors[i]
                logger.error("Failed embeddings for %s: %s", doc_name, error, extra=self.common_log_arguments)
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=f"Embedding failure: {error!s}",
                )
                slice_remove_idx.append(i)
                continue

            # For chunked content, store all embeddings; for full doc, store single embedding
            doc_embeddings = row_vectors[i]
            slice_embeddings.append(doc_embeddings if has_chunked_content else doc_embeddings[0])
            slice_doc_id_hashes.append(slice_hash_values[i])
            metadata[Metrics.External.PROCESSED_DOCS] += 1
            logger.debug(
                "Successfully generated embeddings for document: %s", doc_name, extra=self.common_log_arguments
            )

        return slice_embeddings, slice_doc_id_hashes, slice_remove_idx

    def _process_slice(
        self,
        *,
        slice_table: pa.Table,
        slice_num: int,
        total_slices: int,
        has_chunked_content: bool,
        metadata: dict[str, Any],
    ) -> pa.Table | None:
        """
        Embed one slice and attach the results to it.

        Returns None when every row in the slice failed — that slice contributes
        nothing to the final table.
        """
        slice_embeddings, slice_doc_id_hashes, slice_remove_idx = self._embed_slice_rows(
            slice_table=slice_table,
            has_chunked_content=has_chunked_content,
            metadata=metadata,
        )

        if slice_remove_idx:
            slice_table = OperatorUtils.remove_rows(table=slice_table, remove_row_idx=slice_remove_idx)

        if not slice_embeddings:
            return None

        slice_table = self._add_embeddings_to_slice(
            slice_table=slice_table,
            slice_embeddings=slice_embeddings,
            slice_doc_id_hashes=slice_doc_id_hashes,
            has_chunked_content=has_chunked_content,
        )
        logger.info(
            "Slice %d/%d complete: processed %d docs, failed %d docs",
            slice_num,
            total_slices,
            len(slice_embeddings),
            len(slice_remove_idx),
            extra=self.common_log_arguments,
        )
        return slice_table

    def _finalize_node_status(self, *, metadata: dict[str, Any]) -> None:
        """Downgrade the node status to COMPLETED_WITH_ERRORS if any document failed."""
        if metadata[Metrics.External.FAILED_DOCS_COUNT] <= 0:
            return
        current_status = metadata[Metrics.External.NODE_STATUS]
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
            current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
            ExecutionStatus.COMPLETED_WITH_ERRORS,
        ).value

    def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Transform the input table by adding embeddings using memory-efficient internal slicing.

        Args:
            table: Input PyArrow table with document content
            file_name: Optional file name (not used)

        Returns:
            tuple: (list of output tables, metadata dictionary)
        """
        logger.info(
            "Starting embeddings generation with provider: %s, model: %s",
            self.provider,
            self.model_id,
            extra=self.common_log_arguments,
        )

        # Initialize metadata
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=OperatorUtils.find_doc_count(table=table))

        # Ensure doc_id_hash column exists
        table, hash_error = self._ensure_doc_id_hash_column(table=table)
        if hash_error is not None:
            return self._handle_doc_hash_generation_failure(table, hash_error, metadata)

        # Check if we have chunked content
        has_chunked_content: bool = OperatorConstants.Columns.CHUNKED_CONTENT in table.column_names

        # Internal slicing to prevent Python memory spikes for large tables
        # We process in slices of 2,000 rows to keep object overhead low
        internal_slice_size = 2000
        processed_tables: list[pa.Table] = []

        num_rows = table.num_rows
        total_slices = (num_rows + internal_slice_size - 1) // internal_slice_size

        for start_idx in range(0, num_rows, internal_slice_size):
            end_idx = min(start_idx + internal_slice_size, num_rows)
            slice_num = (start_idx // internal_slice_size) + 1
            slice_table = table.slice(start_idx, end_idx - start_idx)

            logger.info(
                "Processing slice %d/%d (rows %d-%d)",
                slice_num,
                total_slices,
                start_idx,
                end_idx - 1,
                extra=self.common_log_arguments,
            )

            processed_slice = self._process_slice(
                slice_table=slice_table,
                slice_num=slice_num,
                total_slices=total_slices,
                has_chunked_content=has_chunked_content,
                metadata=metadata,
            )
            if processed_slice is not None:
                processed_tables.append(processed_slice)

        # Final assembly
        final_table = pa.concat_tables(processed_tables) if processed_tables else table.slice(0, 0)

        self._finalize_node_status(metadata=metadata)

        logger.info(
            "Embeddings generation completed. Processed: %s, Failed: %s",
            metadata[Metrics.External.PROCESSED_DOCS],
            metadata[Metrics.External.FAILED_DOCS_COUNT],
            extra=self.common_log_arguments,
        )

        return [final_table], metadata
