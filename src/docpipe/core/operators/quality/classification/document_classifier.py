#!/usr/bin/env python3
"""
Document Classification Operator
Classifies documents into predefined types using LLM-based classification.
Supports multiple LLM providers through hexagonal architecture.
"""

import logging
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pyarrow as pa
from data_processing.utils import TransformUtils

import docpipe.core.operators.quality.classification.adapters.outbound  # noqa: F401  (registers adapters)
from docpipe.core.constants import AttributeDataTypes, DocpipeConstants, Metrics, OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory import (
    ClassificationAdapterFactory,
)
from docpipe.core.operators.quality.classification.ports.outbound.classification_port import ClassificationPort
from docpipe.core.ports.document_class_provider import DocumentClassProvider, get_default_document_class_provider
from docpipe.utils.infrastructure.concurrency import submit_task_with_context_propagation
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()

# Private keys used to pass adapter side products through the result dict
_EXTRACTED_CONTENT = "__extracted_content__"
_EXTRACTION_METADATA = "__extraction_metadata__"


class DocumentClassifierOperator(AbstractOperator):  # type: ignore[misc]
    """
    Operator for classifying documents into predefined types using LLM.

    This operator uses LLM-based classification to identify document types
    with confidence scores and reasoning. Supports watsonx and litellm providers.

    Features:
    - Multi-provider support (watsonx, litellm)
    - Confidence scoring (1-10 scale)
    - Optional reasoning output
    - Flexible document type definitions

    Input Requirements:
    - PyArrow Table with document content (text or binary)
    - Document types to classify into

    Output:
    - Adds classification columns to the table:
      * document_type: The classified type
      * classification_confidence (optional): Confidence score (1-10)
      * classification_reasoning (optional): Explanation

    Attributes:
        provider (str): LLM provider (litellm or watsonx)
        provider_config (dict): Provider-specific configuration
            - model_id (str): Model identifier for the provider
            - api_base (str): API endpoint URL
            - api_key (str): Authentication key
            - temperature (float): Sampling temperature (optional)
            - max_tokens (int): Maximum tokens for response (optional)
        document_types (list or dict): Document types to classify into
        confidence_threshold (float): Minimum confidence score (1-10)
        doc_column (str): Column containing document content
        output_column (str): Column name for classification result
        include_confidence (bool): Include confidence score in output
        include_reasoning (bool): Include reasoning explanation in output

    Example Configuration:
        # LiteLLM provider (default configuration)
        {
            "provider": "litellm",
            "provider_config": {
                "api_base": "http://localhost:11434/v1",
                "api_key": "${OLLAMA_API_KEY}" # pragma: allowlist secret
            },
            "model_id": "openai/granite3.1-dense:8b",
            "document_types": ["invoice", "receipt", "contract"]
        }
        # Note: Default examples use LiteLLM with Ollama's OpenAI-compatible endpoint

        # LiteLLM provider with custom Ollama model
        {
            "provider": "litellm",
            "provider_config": {
                "api_base": "http://localhost:11434/v1",
                "api_key": "${OLLAMA_API_KEY}" # pragma: allowlist secret
            },
            "model_id": "openai/llama3.2:latest",
            "document_types": {...}
        }

        # WatsonX provider (with environment variables for security)
        {
            "provider": "watsonx",
            "provider_config": {
                "api_base": "https://api.watsonx.example.com",
                "container_kind": "project",
                "timeout": 120
            },
            "model_id": "ibm/granite-3-8b-instruct",
            "document_types": {...}
        }
        # Required environment variables for watsonx:
        # export WATSONX_API_KEY="${your-api-key}"
        # export WATSONX_CONTAINER_ID="your-project-id"
    """

    short_name: str = OperatorConstants.Misc.DOCUMENT_CLASSIFIER
    category: OperatorCategory = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(
        self,
        config: dict[str, Any],
        *,
        document_class_provider: DocumentClassProvider | None = None,
        classification_adapter: ClassificationPort | None = None,
    ) -> None:
        """
        Initialize the document classifier operator.

        Args:
            config: Configuration dictionary containing:
                - provider: Classification adapter ("litellm" or "watsonx")
                - provider_config: Provider-specific configuration dictionary.
                    For litellm / watsonx:
                        - model_id: Model identifier (e.g. "openai/granite3.1-dense:8b")
                        - api_base: API endpoint URL
                        - api_key: API key for authentication
                - document_types: List of document types or dict with descriptions
                - confidence_threshold: Minimum confidence for classification (default: 7.0)
                - doc_column: Column containing document text (default: "content")
                - output_column: Column name for classification result (default: "document_type")
                - include_confidence: Include confidence score in output (default: True)
                - include_reasoning: Include reasoning in output (default: False)
            document_class_provider: Port used to resolve document types when
                ``document_types`` is not given in *config*.  Defaults to
                :class:`StaticDocumentClassProvider` (local JSON files).  Custom
                implementations can be injected by callers.
            classification_adapter: Pre-built :class:`ClassificationPort`.  When
                given, :class:`ClassificationAdapterFactory` is bypassed and
                ``provider`` / ``provider_config`` are not used to build an adapter.

        Raises:
            ValueError: When provider configuration is invalid (delegated to
                :class:`ClassificationAdapterFactory`).
        """
        super().__init__(config)

        self._document_class_provider: DocumentClassProvider = (
            document_class_provider if document_class_provider is not None else get_default_document_class_provider()
        )

        # Store full config for on-demand binary fetching (includes ingest_source if present)
        self.global_config = config

        # Provider name stored for logging only
        self.provider: str = config.get(
            OperatorConstants.Config.PROVIDER, OperatorConstants.Classification.DEFAULT_PROVIDER
        ).lower()

        # Document types: explicit config wins; otherwise resolved lazily from the
        # provider on first access (see the ``document_types`` property) so that
        # remote providers do no I/O during construction.
        self._document_types: list[str] | dict[str, str] | None = (
            config.get(OperatorConstants.Config.DOCUMENT_TYPES) or None
        )

        # Classification parameters
        self.confidence_threshold: float = config.get(
            OperatorConstants.Config.CONFIDENCE_THRESHOLD, OperatorConstants.Classification.DEFAULT_CONFIDENCE_THRESHOLD
        )

        # Column configuration
        self.output_column: str = config.get(
            OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Classification.DEFAULT_OUTPUT_COLUMN
        )

        # Output options
        self.include_confidence: bool = config.get(OperatorConstants.Config.INCLUDE_CONFIDENCE, True)
        self.include_reasoning: bool = config.get(OperatorConstants.Config.INCLUDE_REASONING, False)

        # Job tracking context for progress updates
        self.batch_id = config.get(DocpipeConstants.BATCH_ID)

        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        self.adapter: ClassificationPort = (
            classification_adapter
            if classification_adapter is not None
            else ClassificationAdapterFactory.create_adapter(provider=self.provider, config=self.config)
        )

        logger.debug(
            "DocumentClassifierOperator: created adapter=%s for provider=%s",
            type(self.adapter).__name__,
            self.provider,
        )

        # Parallel processing configuration
        # Uses ThreadPoolExecutor for I/O-bound LLM API calls
        self.max_workers: int = config.get(
            OperatorConstants.Config.MAX_WORKERS, OperatorUtils.get_optimal_workers(is_cpu_intensive=False)
        )

        logger.info("Initialized DocumentClassifierOperator with provider=%s", self.provider)

    @property
    def document_types(self) -> list[str] | dict[str, str]:
        """Document types to classify into.

        Uses ``document_types`` from the config when present, otherwise asks the
        injected :class:`DocumentClassProvider`.  The result is cached.
        """
        if self._document_types is None:
            self._document_types = self._document_class_provider.get_document_types()
        return self._document_types

    @document_types.setter
    def document_types(self, value: list[str] | dict[str, str]) -> None:
        self._document_types = value or None

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """
        Validate operator configuration and dependencies using generic metadata introspection.

        Args:
            errors: List to append error messages to
            warnings: List to append warning messages to
            available_features: List of features available from previous operators
        """
        super().validate(errors, warnings, available_features)

        # Import validation helper
        from docpipe.utils.operators.config_validation import validate_config_from_metadata

        # Get the ATTRIBUTES metadata for this operator
        attributes = self.get_metadata().get(OperatorConstants.Config.ATTRIBUTES, {})

        # Use generic validation helper
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        # Validate provider — delegate to factory which is the single source of truth.
        if self.should_validate_field(field_value=self.provider):
            supported_providers = ClassificationAdapterFactory.get_supported_providers()
            if self.provider not in supported_providers:
                deprecation_message = ClassificationAdapterFactory.get_deprecation_message(self.provider)
                if deprecation_message is not None:
                    errors.append(deprecation_message)
                else:
                    errors.append(f"provider must be one of {sorted(supported_providers)}, got '{self.provider}'")

        # Validate document types (may be resolved from the document class provider)
        try:
            document_types = self.document_types
        except Exception as exc:  # provider failures must surface as validation errors
            logger.warning("Failed to resolve document types from provider: %s", exc)
            errors.append(f"Unable to resolve document types from document class provider: {exc}")
        else:
            if self.should_validate_field(field_value=document_types) and not document_types:
                errors.append("document_types cannot be empty")

        # Validate confidence threshold (optional, defaults to 7.0)
        if self.should_validate_field(field_value=self.confidence_threshold):
            if self.confidence_threshold is not None:
                if not isinstance(self.confidence_threshold, (int, float)):
                    errors.append("confidence_threshold must be a number")
                elif not (1.0 <= self.confidence_threshold <= 10.0):
                    errors.append("confidence_threshold must be between 1.0 and 10.0")

    def _update_classification_progress(
        self, *, completed: int, total: int, progress_percentage: float, failed_count: int
    ) -> None:
        """Update node stats with classification progress.

        This method updates the node metadata with transient classification progress fields
        that are used by the batch aggregator to calculate and display classification progress.

        The transient fields (classification_running, classification_completed, progress_percentage)
        are removed by the batch aggregator after reading them, ensuring they don't
        persist in the final aggregated metadata.

        Args:
            completed: Number of documents successfully classified
            total: Total number of documents being classified
            progress_percentage: Percentage of classification completion
            failed_count: Number of failed classifications
        """
        try:
            # Only update if we have job tracking context
            if not self.job_run_id or not self.id:
                return

            from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
            from docpipe.core.job_management.domain.models.node_stats import NodeMetadataItem

            factory = get_default_factory()
            job_tracker = factory.create_job_stats_service()

            # Build transient progress metadata (only classification fields)
            progress_metadata: dict[str, Any] = {
                "classification_running": total,
                "classification_completed": completed,
                "progress_percentage": f"{progress_percentage:.2f}%",
            }

            # Wrap in proper NodeMetadataItem structure
            metadata_item: NodeMetadataItem = NodeMetadataItem(
                id=self.id,
                operator=self.name or "DocumentClassifierOperator",
                node_metadata=progress_metadata,
            )

            # Create node_stats dict with proper structure
            node_stats = {OperatorConstants.Metadata.NODE_METADATA: metadata_item.model_dump()}

            # Update node stats through job tracker
            job_tracker.update_node_stats(
                job_run_id=self.job_run_id, node_id=self.id, node_stats=node_stats, batch_id=self.batch_id
            )

        except Exception as e:
            # Log but don't fail the operation if progress update fails
            logger.warning("Failed to update classification progress: %s", e)

    def _classify_document(
        self,
        *,
        content: str | None,
        document_types: list[str] | dict[str, str],
        binary_content: bytes | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Classify a single document using the configured adapter.

        The operator does not extract text itself.  It passes whatever it has
        (existing text and/or raw bytes) to the adapter, which decides what it
        needs.  Adapters that extract text as a by-product report it back via
        ``extracted_content`` / ``extraction_metadata``.

        Args:
            content: Existing document text, or ``None`` when not available
            document_types: Document types to classify into, resolved once per batch by :meth:`transform`
            binary_content: Raw document bytes, or ``None`` when text is given
            doc_name: Optional document name for logging

        Returns:
            Dictionary containing classification results
        """
        logger.debug(
            "DocumentClassifierOperator._classify_document: doc_name=%s adapter=%s",
            doc_name,
            type(self.adapter).__name__,
        )
        try:
            response = self.adapter.classify_document(
                doc_name=doc_name or "",
                binary_content=binary_content,
                existing_text=content,
                document_types=document_types,
            )

            if not response.success:
                logger.debug(
                    "DocumentClassifierOperator: classification unsuccessful for %s: %s",
                    doc_name,
                    response.error,
                )
                return {
                    OperatorConstants.Extraction.SUCCESS: False,
                    OperatorConstants.Extraction.ERROR: response.error or "Unknown classification error",
                    OperatorConstants.Classification.FIELD_DOCUMENT_TYPE: None,
                    OperatorConstants.Classification.FIELD_CONFIDENCE: 0,
                    OperatorConstants.Classification.FIELD_REASONING: response.reasoning,
                    _EXTRACTED_CONTENT: response.extracted_content,
                    _EXTRACTION_METADATA: response.extraction_metadata,
                }

            logger.info(
                "Classified document %s: type=%s confidence=%s",
                doc_name or OperatorConstants.Classification.UNKNOWN_TYPE,
                response.document_type,
                response.confidence,
            )

            return {
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Classification.FIELD_DOCUMENT_TYPE: response.document_type,
                OperatorConstants.Classification.FIELD_CONFIDENCE: response.confidence,
                OperatorConstants.Classification.FIELD_REASONING: response.reasoning,
                "is_confident": response.confidence >= self.confidence_threshold,
                _EXTRACTED_CONTENT: response.extracted_content,
                _EXTRACTION_METADATA: response.extraction_metadata,
            }
        except Exception as e:
            logger.error("Classification failed for %s: %s", doc_name or "unknown", e)
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: str(e),
                "document_type": None,
                "confidence": 0,
                "reasoning": "",
            }

    def _validate_extensions_for_existing_content(
        self, *, table: pa.Table, doc_contents: list[Any], metadata: dict[str, Any]
    ) -> set[int]:
        """
        Validate file extensions for documents with existing content.

        Args:
            table: Input PyArrow table with document metadata
            doc_contents: List of document contents (will be modified in-place)
            metadata: Metadata dictionary to record skipped documents

        Returns:
            Set of indices that were skipped due to unsupported extensions
        """
        skipped_indices: set[int] = set()

        if OperatorConstants.Columns.NAME not in table.column_names:
            return skipped_indices

        for idx in range(table.num_rows):
            doc_name = table[OperatorConstants.Columns.NAME][idx].as_py()
            file_ext = pathlib.Path(doc_name).suffix.lower()

            if file_ext not in OperatorConstants.FileExtensions.CLASSIFICATION_FILE_EXTENSIONS:
                doc_id = (
                    table[OperatorConstants.Columns.ID][idx].as_py()
                    if OperatorConstants.Columns.ID in table.column_names
                    else f"doc_{idx}"
                )
                error_msg = f"Unsupported file extension: {file_ext}"
                logger.info("Skipping document %s: %s", doc_name, error_msg)

                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=str(doc_id),
                    doc_name=doc_name,
                    reason=error_msg,
                )
                skipped_indices.add(idx)
                # Clear content for this index so it's skipped in classification
                doc_contents[idx] = None

        return skipped_indices

    def transform(self, table: pa.Table, file_name: str = "") -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Classify documents in the input table.

        Args:
            table: Input PyArrow table with document content
            file_name: Optional file name (required by AbstractTableTransform signature)

        Returns:
            Tuple of (list of output tables, metadata dictionary)
        """
        # Initialize metadata
        total_docs = table.num_rows
        metadata = self.create_base_metadata(total_docs_count=total_docs)

        if total_docs == 0:
            logger.warning("Empty table provided to DocumentClassifierOperator")
            return [table], metadata

        if self.output_column in table.column_names:
            logger.warning("Output column '%s' already present. Moving to next operator", self.output_column)
            return [table], metadata

        # Resolve once before the thread pool so a remote DocumentClassProvider is not hit concurrently.
        document_types = self.document_types

        doc_column_exists = self.doc_column in table.column_names
        content_was_fetched = False
        doc_contents: list[Any] = [None] * table.num_rows
        # Raw bytes for rows without a text column; the adapter decides whether it needs them.
        doc_binaries: dict[int, bytes] = {}
        skipped_indices: set[int] = set()  # Rows skipped due to unsupported extensions
        failed_indices: set[int] = set()  # Rows already recorded as failed (e.g. binary fetch error)

        if doc_column_exists:
            # Use existing content column directly; LLM classifiers benefit from structured DocLang XML
            doc_contents = table.column(self.doc_column).to_pylist()
            logger.info("Using existing '%s' column for classification", self.doc_column)

            # Validate file extensions for existing content
            skipped_indices = self._validate_extensions_for_existing_content(
                table=table, doc_contents=doc_contents, metadata=metadata
            )
        else:
            # Fetch raw bytes only. Text extraction (if any) is the adapter's concern.
            logger.info("'%s' column not found, fetching document binaries", self.doc_column)
            content_was_fetched = True
            doc_tasks = OperatorUtils.prepare_document_content_fetch(
                table=table,
                global_config=self.global_config,
                supported_extensions=set(OperatorConstants.FileExtensions.CLASSIFICATION_FILE_EXTENSIONS),
            )
            for task in doc_tasks:
                if "error" not in task:
                    doc_binaries[task["idx"]] = task["binary_content"]
                elif task.get("skip_reason") == "unsupported_extension":
                    # Unsupported extensions are skipped, not failed
                    self.record_skipped_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=task["error"],
                    )
                    skipped_indices.add(task["idx"])
                else:
                    self.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=task["error"],
                    )
                    failed_indices.add(task["idx"])

        # Process each document
        classifications: list[Any] = [None] * table.num_rows
        confidences: list[Any] = [0] * table.num_rows
        reasonings: list[Any] = [None] * table.num_rows
        # Side products an adapter may report when it extracted text itself
        extracted_contents: list[str | None] = [None] * table.num_rows
        extraction_metadatas: list[dict[str, Any] | None] = [None] * table.num_rows

        # Use ThreadPoolExecutor for classification (I/O-bound LLM API calls)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_task: dict[Any, dict[str, Any]] = {}
            for idx, content in enumerate(doc_contents):
                doc_id = (
                    table[OperatorConstants.Columns.ID][idx].as_py()
                    if OperatorConstants.Columns.ID in table.column_names
                    else f"doc_{idx}"
                )
                doc_name = (
                    table[OperatorConstants.Columns.NAME][idx].as_py()
                    if OperatorConstants.Columns.NAME in table.column_names
                    else f"document_{idx}"
                )

                binary_content = doc_binaries.pop(idx, None)

                has_text = bool(content) and not (isinstance(content, str) and not content.strip())
                if not has_text and binary_content is None:
                    if idx in failed_indices:
                        # Already recorded as failed while fetching the binary
                        reasonings[idx] = "Failed to fetch document content"
                    elif idx not in skipped_indices:
                        logger.warning("Empty content for document %s, skipping classification", doc_name)
                        self.record_skipped_document(
                            metadata=metadata, doc_id=str(idx), doc_name=doc_name, reason="Empty content"
                        )
                        reasonings[idx] = "Empty content"
                    else:
                        # Already recorded as skipped due to unsupported extension
                        reasonings[idx] = "Unsupported file extension"
                    classifications[idx] = None
                    continue

                future = submit_task_with_context_propagation(
                    executor,
                    self._classify_document,
                    content=content if has_text else None,
                    document_types=document_types,
                    binary_content=None if has_text else binary_content,
                    doc_name=doc_name,
                )
                del binary_content  # release the reference; the worker holds its own

                future_to_task[future] = {"idx": idx, "doc_name": doc_name, "doc_id": doc_id}

            # Collect results as they complete
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                idx = task["idx"]

                try:
                    result = future.result()
                    extracted_contents[idx] = result.get(_EXTRACTED_CONTENT)
                    extraction_metadatas[idx] = result.get(_EXTRACTION_METADATA)

                    if result[OperatorConstants.Extraction.SUCCESS]:
                        # Enforce confidence threshold using pre-calculated is_confident flag
                        if result["is_confident"]:
                            classifications[idx] = result[OperatorConstants.Classification.FIELD_DOCUMENT_TYPE]
                            confidences[idx] = result[OperatorConstants.Classification.FIELD_CONFIDENCE]
                            reasonings[idx] = result.get(OperatorConstants.Classification.FIELD_REASONING, "")
                            metadata[Metrics.External.PROCESSED_DOCS] += 1
                        else:
                            # Below threshold - return None
                            classifications[idx] = None
                            confidences[idx] = result[OperatorConstants.Classification.FIELD_CONFIDENCE]
                            reasonings[idx] = (
                                f"Confidence {result[OperatorConstants.Classification.FIELD_CONFIDENCE]} "
                                f"below threshold {self.confidence_threshold} "
                                f"to classify as {result[OperatorConstants.Classification.FIELD_DOCUMENT_TYPE]}"
                            )
                            logger.info(
                                "Document %s confidence %s below threshold %s, predicted type %s, returning None",
                                task["doc_name"],
                                result[OperatorConstants.Classification.FIELD_CONFIDENCE],
                                self.confidence_threshold,
                                result[OperatorConstants.Classification.FIELD_DOCUMENT_TYPE],
                                extra=self.common_log_arguments,
                            )
                            metadata[Metrics.External.PROCESSED_DOCS] += 1
                        # Update progress tracking
                        completed = metadata[Metrics.External.PROCESSED_DOCS]
                        failed = metadata[Metrics.External.FAILED_DOCS_COUNT]
                        progress_pct = (completed / total_docs) * 100 if total_docs > 0 else 0
                        self._update_classification_progress(
                            completed=completed,
                            total=total_docs,
                            progress_percentage=progress_pct,
                            failed_count=failed,
                        )
                    elif (extracted := result.get(_EXTRACTED_CONTENT)) is not None and not extracted.strip():
                        # The adapter extracted text but it was blank: same outcome as an
                        # empty text column, so skipped rather than failed.
                        logger.warning("Empty content for document %s, skipping classification", task["doc_name"])
                        self.record_skipped_document(
                            metadata=metadata,
                            doc_id=str(task["doc_id"]),
                            doc_name=task["doc_name"],
                            reason="Empty content",
                        )
                        skipped_indices.add(idx)
                        classifications[idx] = None
                        reasonings[idx] = "Empty content"
                    else:
                        self.record_failed_document(
                            metadata=metadata,
                            doc_id=str(task["doc_id"]),
                            doc_name=task["doc_name"],
                            reason=result.get(OperatorConstants.Extraction.ERROR, "Unknown error"),
                        )
                        classifications[idx] = None
                        reasonings[idx] = result.get(OperatorConstants.Extraction.ERROR, "")
                        logger.error(
                            "Failed to classify content from %s: %s",
                            task["doc_name"],
                            result.get(OperatorConstants.Extraction.ERROR),
                            extra=self.common_log_arguments,
                        )

                except Exception as e:
                    self.record_failed_document(
                        metadata=metadata, doc_id=str(task["doc_id"]), doc_name=task["doc_name"], reason=str(e)
                    )
                    classifications[idx] = None
                    reasonings[idx] = str(e)
                    logger.error("Error processing document at index %s: %s", idx, e)

        # Start with the original table
        output_table = table

        # Reuse columns for the extract operator exist only when the adapter extracted
        # text itself (the standard adapter does; the hybrid adapter does not).
        # They are written only if ALL documents were extracted (no skipped rows), so
        # the Extract operator never sees mixed content (some null, some not).
        if content_was_fetched and any(text is not None for text in extracted_contents):
            if not skipped_indices and not failed_indices and all(text is not None for text in extracted_contents):
                output_table = self._add_extraction_reuse_columns(
                    table=output_table,
                    extracted_contents=extracted_contents,
                    extraction_metadatas=extraction_metadatas,
                )
            else:
                logger.info(
                    "Skipping temp column creation: not every document was extracted "
                    "(%s skipped, %s failed fetch). Extract operator will fetch content for all documents.",
                    len(skipped_indices),
                    len(failed_indices),
                )

        # Add classification columns to table
        output_table = TransformUtils.add_column(output_table, self.output_column, classifications)

        if self.include_confidence:
            output_table = TransformUtils.add_column(output_table, f"{self.output_column}_confidence", confidences)

        if self.include_reasoning:
            output_table = TransformUtils.add_column(output_table, f"{self.output_column}_reasoning", reasonings)

        # Determine and set final execution status
        processed_count = metadata[Metrics.External.PROCESSED_DOCS]
        failed_count = metadata[Metrics.External.FAILED_DOCS_COUNT]
        skipped_count = metadata[Metrics.External.SKIPPED_DOCS_COUNT]

        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.determine_execution_status(
            processed_count=processed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )

        logger.info(
            "Classification complete: %s/%s documents classified, %s failed, %s skipped, status=%s",
            processed_count,
            total_docs,
            failed_count,
            skipped_count,
            metadata[Metrics.External.NODE_STATUS],
        )

        return [output_table], metadata

    @staticmethod
    def _calculate_pages_processed(*, content: str | None, extraction_metadata: dict[str, Any] | None) -> int:
        """Return the page count for a document.

        Uses the native ``page_count`` from *extraction_metadata* when present,
        otherwise estimates from character count.
        """
        native = (extraction_metadata or {}).get("page_count")
        if native and isinstance(native, (int, float)) and native > 0:
            return int(native)
        char_count = len(content) if content else 0
        chars_per_page = OperatorConstants.Processing.CHARS_PER_PAGE
        return max(1, (char_count + chars_per_page - 1) // chars_per_page)

    @staticmethod
    def _add_extraction_reuse_columns(
        *,
        table: pa.Table,
        extracted_contents: list[str | None],
        extraction_metadatas: list[dict[str, Any] | None],
    ) -> pa.Table:
        """Append ``TEMP_CONTENT_COLUMN`` and ``TEMP_PAGES_PROCESSED_COLUMN`` to *table*.

        These columns let :class:`ExtractOperator` skip a second Docling pass
        when the classifier already extracted the text.
        """
        table = TransformUtils.add_column(table, DocpipeConstants.TEMP_CONTENT_COLUMN, extracted_contents)
        logger.info(
            "Stored extracted content in '%s' column for potential reuse by extract operator",
            DocpipeConstants.TEMP_CONTENT_COLUMN,
        )
        pages_processed_list = [
            DocumentClassifierOperator._calculate_pages_processed(content=text, extraction_metadata=meta)
            for text, meta in zip(extracted_contents, extraction_metadatas, strict=True)
        ]
        table = TransformUtils.add_column(table, DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN, pages_processed_list)
        logger.info(
            "Calculated and stored page counts in '%s' column for extract operator",
            DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN,
        )
        return table

    @staticmethod
    def _get_classifier_provider_schemas() -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for the provider_config field.

        Add a new entry here when registering a new classification provider.
        """
        from docpipe.core.operators.shared.llm_provider_config import LLMProviderConfig, WatsonxProviderConfig

        return {
            OperatorConstants.Classification.PROVIDER_LITELLM: OperatorUtils.model_schema_to_docpipe(
                schema=LLMProviderConfig.model_json_schema()
            ),
            OperatorConstants.Classification.PROVIDER_WATSONX: OperatorUtils.model_schema_to_docpipe(
                schema=WatsonxProviderConfig.model_json_schema()
            ),
        }

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """
        Return operator metadata for UI and documentation.

        Returns:
            dict: Operator metadata including features and attributes
        """
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: DocumentClassifierOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: DocumentClassifierOperator.is_available(),
            OperatorConstants.Misc.LABEL: "Document Classifier",
            OperatorConstants.Config.DESCRIPTION: "Classify documents into predefined types using LLM (litellm or watsonx providers). Default: litellm with Ollama",
            OperatorConstants.Config.FEATURES: {
                OperatorConstants.Classification.DEFAULT_OUTPUT_COLUMN: {
                    OperatorConstants.Misc.NAME: "Document Type",
                    OperatorConstants.Config.DESCRIPTION: "Classified document type",
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
                f"{OperatorConstants.Classification.DEFAULT_OUTPUT_COLUMN}_confidence": {
                    OperatorConstants.Misc.NAME: "Classification Confidence",
                    OperatorConstants.Config.DESCRIPTION: "Confidence score for classification (1-10)",
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_FLOAT,
                },
                f"{OperatorConstants.Classification.DEFAULT_OUTPUT_COLUMN}_reasoning": {
                    OperatorConstants.Misc.NAME: "Classification Reasoning",
                    OperatorConstants.Config.DESCRIPTION: "Explanation for the classification decision",
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
            },
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Config.PROVIDER: {
                    OperatorConstants.Misc.NAME: "Provider",
                    OperatorConstants.Config.DESCRIPTION: "LLM provider (litellm or watsonx). Default is litellm configured for Ollama. Note: Ollama is no longer supported as a direct provider; use litellm with OpenAI-compatible API instead.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Classification.DEFAULT_PROVIDER,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.VALID_VALUES: [
                        OperatorConstants.Classification.PROVIDER_WATSONX,
                        OperatorConstants.Classification.PROVIDER_LITELLM,
                    ],
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration. Fields vary by provider — see the 'providers' schema for details.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROVIDERS: DocumentClassifierOperator._get_classifier_provider_schemas(),
                },
                OperatorConstants.Config.DOCUMENT_TYPES: {
                    OperatorConstants.Misc.NAME: "Document Types",
                    OperatorConstants.Config.DESCRIPTION: "List of document types or dictionary with descriptions",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: [],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                OperatorConstants.Config.CONFIDENCE_THRESHOLD: {
                    OperatorConstants.Misc.NAME: "Confidence Threshold",
                    OperatorConstants.Config.DESCRIPTION: "Minimum confidence score for classification (1-10)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Classification.DEFAULT_CONFIDENCE_THRESHOLD,
                    OperatorConstants.Filtering.MIN_VALUE: 1.0,
                    OperatorConstants.Filtering.MAX_VALUE: 10.0,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                },
                OperatorConstants.Columns.OUTPUT_COLUMN: {
                    OperatorConstants.Misc.NAME: "Output Column",
                    OperatorConstants.Config.DESCRIPTION: "Column name for classification result",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Classification.DEFAULT_OUTPUT_COLUMN,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Config.INCLUDE_CONFIDENCE: {
                    OperatorConstants.Misc.NAME: "Include Confidence",
                    OperatorConstants.Config.DESCRIPTION: "Include confidence score in output",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.Config.INCLUDE_REASONING: {
                    OperatorConstants.Misc.NAME: "Include Reasoning",
                    OperatorConstants.Config.DESCRIPTION: "Include reasoning explanation in output",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.Config.STRICT_LABEL_MATCHING: {
                    OperatorConstants.Misc.NAME: "Strict Label Matching",
                    OperatorConstants.Config.DESCRIPTION: "When enabled, the model's label is resolved to the configured document type spelling and labels that match no configured type are rejected (document type is null). When disabled (default), any label is accepted and normalised to lower-case with underscores.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Classification.DEFAULT_STRICT_LABEL_MATCHING,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.Config.MAX_WORKERS: {
                    OperatorConstants.Misc.NAME: "Max Workers",
                    OperatorConstants.Config.DESCRIPTION: "Maximum number of parallel workers for processing (uses ThreadPoolExecutor for I/O-bound LLM API calls)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                OperatorConstants.Classification.DOC_COLUMN_KEY: {
                    OperatorConstants.Misc.NAME: "Document Column",
                    OperatorConstants.Config.DESCRIPTION: "Column name containing document content to classify",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Classification.DEFAULT_DOC_COLUMN,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
            },
        }
