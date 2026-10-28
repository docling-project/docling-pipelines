#!/usr/bin/env python3
"""
Extract Operator

A unified extraction operator that uses hexagonal architecture to support multiple
extraction strategies through a single interface. This operator delegates extraction
logic to specialized adapters based on the configured extraction modes.

Supported Text Extraction Modes:
    - docling_library: Local Docling extraction with tables, images, and optional VLM support
    - docling_serve: Remote extraction via Docling Serve API

Supported Entity Extraction Modes:
    - litellm: Multi-provider LLM extraction using LiteLLM (supports Ollama via OpenAI-compatible API)
    - watsonx: LLM-based entity extraction using IBM watsonx
    - docling: Template-based entity extraction using Docling templates
    - none: No entity extraction (default)

Architecture:
    This operator follows hexagonal architecture principles:
    - Operator (this file): Thin wrapper that handles configuration and delegation
    - Port (TextExtractionPort): Defines the extraction interface
    - Adapters: Implement specific extraction strategies
    - Factory: Creates appropriate adapter based on mode

Example Usage:
    # Standard text extraction only
    {
        "operator_type": "docpipe.core.operators.extract.extract_operator.ExtractOperator",
        "operator_params": {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "document"
            },
            "max_workers": 4
        }
    }

    # Text extraction with entity extraction (LiteLLM with Ollama)
    {
        "operator_type": "docpipe.core.operators.extract.extract_operator.ExtractOperator",
        "operator_params": {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "document"
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/granite4:latest",
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "<ollama_key>",
                    "temperature": 0.0,
                    "max_tokens": 4096
                },
                "output_column": "entities",
                "max_doc_chars": 8000
            },
            "max_workers": 4
        }
    }

    # VLM-enhanced text extraction
    {
        "operator_type": "docpipe.core.operators.extract.extract_operator.ExtractOperator",
        "operator_params": {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "document",
                "max_workers": 2,
                "provider_config": {
                    "vlm_pipeline": {
                        "preset": "granite_docling",
                        "engine": "api_ollama",
                        "engine_options": {
                            "api_base": "http://localhost:11434",
                            "model_id": "ibm/granite-docling:258m"
                        }
                    }
                }
            }
        }
    }

    # Docling Serve text extraction
    {
        "operator_type": "docpipe.core.operators.extract.extract_operator.ExtractOperator",
        "operator_params": {
            "text_extraction": {
                "provider": "docling_serve",
                "doc_column": "document",
                "provider_config": {
                    "base_url": "http://localhost:5001",
                    "timeout": 300,
                    "do_ocr": true
                }
            }
        }
    }
"""

import json
import logging
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.adapters.config import get_default_factory
from docpipe.core.job_management.adapters.stores.json.json_job_stats_store import JsonJobStatsStore
from docpipe.core.job_management.domain.models.node_stats import NodeMetadataItem, NodeStats
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
    EntityExtractionAdapterFactory,
)
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    TextExtractionAdapterFactory,
)
from docpipe.core.operators.extract.domain.models import (
    EntityExtractionMode,
    TextExtractionMode,
)
from docpipe.core.operators.extract.ports.outbound.entity_extraction import EntityExtractionPort
from docpipe.core.operators.extract.ports.outbound.text_extraction import TextExtractionPort
from docpipe.core.operators.extract.services.entity_extraction_service import EntityExtractionService
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator
from docpipe.core.operators.operator_utils import OperatorUtils, format_failed_docs_summary
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.config_validation import validate_config_from_metadata
from docpipe.utils.operators.non_recoverable_utils import is_non_recoverable_error, process_non_recoverable_errors

logger: logging.Logger = get_logger()


def _build_stage_dict(*, completed: int, failed: int, total: int) -> dict[str, Any]:
    """Build a single extraction stage progress dict.

    Args:
        completed: Documents successfully processed in this stage.
        failed: Documents that failed in this stage.
        total: Total documents submitted to this stage.

    Returns:
        Dict with status, counts, and progress_percentage.
    """
    done = completed + failed
    pct = (done / total * 100) if total > 0 else 0.0
    status = (
        OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
        if done >= total > 0
        else OperatorConstants.Extraction.STAGE_STATUS_RUNNING
    )
    return {
        OperatorConstants.Extraction.STAGE_STATUS: status,
        OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: total,
        OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: completed,
        OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: failed,
        OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE: round(pct, 2),
    }


class ExtractOperator(AbstractOperator):  # type: ignore[misc]
    """Unified extraction operator using hexagonal architecture.

    This operator provides a single interface for multiple extraction strategies,
    delegating the actual extraction work to specialized adapters. The operator
    handles configuration parsing and adapter creation, while the adapter handles
    the extraction logic and parallel processing.

    Attributes:
        short_name: Operator identifier ("extract_operator")
        category: Operator category (OperatorCategory.EXTRACT)
        text_extraction (dict): Text extraction configuration
            - provider (str): Provider for text extraction (docling_library, docling_serve)
            - provider_config (dict): Provider-specific configuration
        entity_extraction (dict): Entity extraction configuration
            - provider (str): Provider for entity extraction (litellm, watsonx, docling, none)
            - provider_config (dict): Provider-specific configuration
        doc_column (str): Column name for storing extracted content
        expand_extracted_data (bool): Whether to expand entity data into columns (entity extraction only)
    """

    short_name = OperatorConstants.Operators.EXTRACT_OPERATOR
    category = OperatorCategory.Extract
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, *, config: dict[str, Any]):
        """Initialize the unified extract operator.

        Parses the extraction mode, builds adapter-specific configuration,
        and creates the appropriate adapter using the factory.

        Args:
            config: Configuration dictionary with nested structure:
                - text_extraction: Nested object containing:
                    - provider: Text provider ("docling_library", "docling_serve")
                    - provider_config: Provider-specific configuration
                    - doc_column: Column name for extracted content
                    - additional_formats: List of additional output formats
                      Options: 'html', 'json', 'text', 'doctags', 'doclang'
                - entity_extraction: Optional nested object containing:
                    - provider: Entity provider ("litellm", "watsonx", "docling")
                    - provider_config: Provider-specific configuration (model_id, api_base, etc.)
                    - output_column: Column name for extracted entities
                    - max_doc_chars: Maximum document characters
                    - custom_schema: Schema dictionary for structured extraction
                    - expand_extracted_data: Expand entity data flag
                - max_workers: Number of parallel workers (default: auto-detect)
                - use_processes: Use processes vs threads (default: False)

        Raises:
            FlowExecutionFailedException: If extraction_mode is invalid or configuration is incomplete
        """
        super().__init__(config)

        # Extract text_extraction nested config and store for later use.
        # Uses `or {}` so that an explicit null is treated the same
        # as a missing key. Both result in an empty dict that triggers the
        # "required" error below rather than crashing with AttributeError.
        self.text_extraction_config = config.get(OperatorConstants.Config.TEXT_EXTRACTION) or {}
        if not self.text_extraction_config:
            raise FlowExecutionFailedException(
                f"Missing required '{OperatorConstants.Config.TEXT_EXTRACTION}' configuration object"
            )

        # Parse text extraction mode
        text_mode_str = self.text_extraction_config.get(
            OperatorConstants.Config.PROVIDER,
            OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY,
        )
        try:
            self.text_extraction_mode = TextExtractionMode(text_mode_str)
        except ValueError as e:
            supported_modes = [mode.value for mode in TextExtractionMode]
            raise FlowExecutionFailedException(
                f"Invalid text_extraction.provider '{text_mode_str}'. Supported providers: {supported_modes}"
            ) from e

        # Extract entity_extraction nested config (optional).
        # Treat an explicit null the same as absent.
        entity_extraction_config = config.get(OperatorConstants.Config.ENTITY_EXTRACTION)

        # Parse entity extraction mode
        if entity_extraction_config:
            entity_mode_str = entity_extraction_config.get(OperatorConstants.Config.PROVIDER)
            if not entity_mode_str:
                raise FlowExecutionFailedException(
                    "entity_extraction.provider is required when entity_extraction is present"
                )
            try:
                self.entity_extraction_mode = EntityExtractionMode(entity_mode_str)
            except ValueError as e:
                supported_modes = [mode.value for mode in EntityExtractionMode]
                raise FlowExecutionFailedException(
                    f"Invalid entity_extraction.provider '{entity_mode_str}'. Supported providers: {supported_modes}"
                ) from e
        else:
            self.entity_extraction_mode = EntityExtractionMode.NONE

        # Extract common parameters from text_extraction
        self.doc_column = self.text_extraction_config.get(
            OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        )
        # Extract entity extraction parameters
        if entity_extraction_config:
            self.output_column = entity_extraction_config.get(
                OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Misc.ENTITIES
            )
            self.expand_extracted_data = entity_extraction_config.get(
                OperatorConstants.Config.EXPAND_EXTRACTED_DATA, False
            )
        else:
            self.output_column = OperatorConstants.Misc.ENTITIES
            self.expand_extracted_data = False

        # Auto-detect optimal workers based on CPU count
        default_text_workers = OperatorUtils.get_optimal_workers(is_cpu_intensive=False)
        default_entity_workers = OperatorUtils.get_optimal_workers(is_cpu_intensive=True)
        _raw_workers = config.get(OperatorConstants.Config.MAX_WORKERS)
        _workers = _raw_workers if isinstance(_raw_workers, int) and _raw_workers > 0 else None
        text_max_workers = _workers if _workers is not None else default_text_workers
        entity_max_workers = _workers if _workers is not None else default_entity_workers
        use_processes = config.get(OperatorConstants.Config.USE_PROCESSES, False)

        # Prepare global config for job tracking and other global settings.
        # Include ingest_source for on-demand binary fetching from cloud sources.
        # Note: job-tracking values are read from config here rather than stored as
        # instance attrs; use self.text_adapter.global_config to access them later
        # so SessionInfo (set by the orchestrator per execution) remains the single
        # source of truth and is not shadowed by stale construction-time snapshots.
        global_config = {
            OperatorConstants.Config.COMMON_LOG_ARGUMENTS: config.get(
                OperatorConstants.Config.COMMON_LOG_ARGUMENTS, {}
            ),
            DocpipeConstants.JOB_RUN_ID: config.get(DocpipeConstants.JOB_RUN_ID),
            DocpipeConstants.NODE_ID: config.get(DocpipeConstants.NODE_ID),
            DocpipeConstants.NODE_NAME: config.get(DocpipeConstants.NODE_NAME),
            DocpipeConstants.BATCH_ID: config.get(DocpipeConstants.BATCH_ID),
        }

        # Preserve ingest_source from config if present (for cloud source binary fetching)
        if OperatorConstants.Config.INGEST_SOURCE in config:
            global_config[OperatorConstants.Config.INGEST_SOURCE] = config[OperatorConstants.Config.INGEST_SOURCE]

        # Propagate doc_format to global_config so text adapters know the primary target format
        if self.doc_format == OperatorConstants.DocFormat.DOCLANG:
            global_config[OperatorConstants.DOC_FORMAT_KEY] = self.doc_format

        # Create text extraction adapter - pass nested config directly
        try:
            self.text_adapter: TextExtractionPort = TextExtractionAdapterFactory.create_adapter(
                mode=self.text_extraction_mode,
                text_extraction_config=self.text_extraction_config,
                global_config=global_config,
                max_workers=text_max_workers,
                use_processes=use_processes,
            )
            logger.info(
                "Created %s adapter for text extraction mode: %s",
                self.text_adapter.ADAPTER_DISPLAY_NAME,
                self.text_extraction_mode.value,
            )
        except Exception as e:
            logger.error("Failed to create text extraction adapter: %s", e)
            raise FlowExecutionFailedException(
                f"Failed to initialize text extraction adapter for provider '{self.text_extraction_mode.value}': {e}"
            ) from e

        # Create entity extraction adapter if enabled - pass nested config directly
        self.entity_adapter: EntityExtractionPort | None = None
        if self.entity_extraction_mode != EntityExtractionMode.NONE and entity_extraction_config:
            try:
                self.entity_adapter = EntityExtractionAdapterFactory.create_adapter(
                    mode=self.entity_extraction_mode,
                    entity_extraction_config=entity_extraction_config,
                    global_config=global_config,
                    doc_column=self.doc_column,
                    max_workers=entity_max_workers,
                )
                if self.entity_adapter:
                    logger.info(
                        "Created %s adapter for entity extraction mode: %s",
                        self.entity_adapter.ADAPTER_DISPLAY_NAME,
                        self.entity_extraction_mode.value,
                    )
            except Exception as e:
                logger.error("Failed to create entity extraction adapter: %s", e)
                raise FlowExecutionFailedException(
                    f"Failed to initialize entity extraction adapter for provider '{self.entity_extraction_mode.value}': {e}"
                ) from e

    def _extract_doc_ids(self, *, doc_list: list[dict[str, Any]]) -> set[str]:
        """Extract document IDs from a document list.

        Args:
            doc_list: List of document dictionaries

        Returns:
            Set of normalized document IDs
        """
        doc_ids: set[str] = set()
        for doc in doc_list:
            if not isinstance(doc, dict):
                continue

            doc_id = doc.get(OperatorConstants.Columns.ID) or doc.get(OperatorConstants.Columns.DOC_ID_COLUMN)
            if doc_id is not None:
                doc_ids.add(str(doc_id))

        return doc_ids

    def _build_doc_id_map(self, *, doc_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Build a map of document IDs to document dictionaries for O(1) lookups.

        Args:
            doc_list: List of document dictionaries

        Returns:
            Dictionary mapping normalized document IDs to document dictionaries
        """
        doc_map: dict[str, dict[str, Any]] = {}
        for doc in doc_list:
            if not isinstance(doc, dict):
                continue

            doc_id = doc.get(OperatorConstants.Columns.ID) or doc.get(OperatorConstants.Columns.DOC_ID_COLUMN)
            if doc_id is not None:
                # setdefault preserves the first occurrence, matching the old
                # _find_document_by_id() behaviour which returned the first match.
                doc_map.setdefault(str(doc_id), doc)

        return doc_map

    def _merge_document_maps(
        self,
        *,
        text_doc_ids: set[str],
        entity_doc_ids: set[str],
        text_doc_list: list[dict[str, Any]],
        entity_doc_list: list[dict[str, Any]],
        default_reason: str,
    ) -> dict[str, dict[str, Any]]:
        """Merge documents from text and entity extraction stages.

        When the same document appears in both stages, their reasons are combined.

        Args:
            text_doc_ids: Document IDs from text extraction stage
            entity_doc_ids: Document IDs from entity extraction stage
            text_doc_list: Original text extraction document list
            entity_doc_list: Original entity extraction document list
            default_reason: Default reason to use if none is provided

        Returns:
            Merged document map with combined reasons where applicable
        """
        # Build id-to-doc maps once for O(1) lookups instead of O(N) linear scans
        text_doc_map = self._build_doc_id_map(doc_list=text_doc_list)
        entity_doc_map = self._build_doc_id_map(doc_list=entity_doc_list)

        merged_map: dict[str, dict[str, Any]] = {}
        shared_doc_ids = text_doc_ids & entity_doc_ids

        for doc_id in shared_doc_ids:
            text_doc = text_doc_map.get(doc_id)
            entity_doc = entity_doc_map.get(doc_id)
            if text_doc is None or entity_doc is None:
                continue

            text_reason = text_doc.get(OperatorConstants.Misc.REASON, default_reason)
            entity_reason = entity_doc.get(OperatorConstants.Misc.REASON, default_reason)
            merged_map[doc_id] = {
                **text_doc,
                OperatorConstants.Misc.REASON: f"Text extraction: {text_reason} | Entity extraction: {entity_reason}",
            }

        for doc_id in text_doc_ids - shared_doc_ids:
            text_doc = text_doc_map.get(doc_id)
            if text_doc is not None:
                merged_map[doc_id] = text_doc

        for doc_id in entity_doc_ids - shared_doc_ids:
            entity_doc = entity_doc_map.get(doc_id)
            if entity_doc is not None:
                merged_map[doc_id] = entity_doc

        return merged_map

    def _consolidate_metadata(
        self, *, text_metadata: dict[str, Any], entity_metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Consolidate metadata from text and entity extraction.

        A document is considered processed only if it succeeded in both text and entity
        extraction stages. If it failed or was skipped in either stage, it's marked
        accordingly in the consolidated metadata.

        This method uses a hybrid approach:
        1. Builds ID-to-document mappings for efficient lookup
        2. Merges failure/skip reasons when same document fails in both stages
        3. Calculates final processed count: total - (failed + skipped)

        Args:
            text_metadata: Metadata dictionary from text extraction adapter
            entity_metadata: Metadata dictionary from entity extraction adapter (None if disabled)

        Returns:
            Consolidated metadata dictionary with accurate counts and merged document lists
        """
        # If no entity extraction, return text metadata as-is
        if entity_metadata is None:
            return text_metadata

        text_failed_docs = text_metadata.get(Metrics.External.FAILED_DOCS, [])
        text_skipped_docs = text_metadata.get(Metrics.External.SKIPPED_DOCS, [])
        entity_failed_docs = entity_metadata.get(Metrics.External.FAILED_DOCS, [])
        entity_skipped_docs = entity_metadata.get(Metrics.External.SKIPPED_DOCS, [])

        merged_failed_map = self._merge_document_maps(
            text_doc_ids=self._extract_doc_ids(doc_list=text_failed_docs),
            entity_doc_ids=self._extract_doc_ids(doc_list=entity_failed_docs),
            text_doc_list=text_failed_docs,
            entity_doc_list=entity_failed_docs,
            default_reason=OperatorConstants.Extraction.ERROR,
        )

        merged_skipped_map = self._merge_document_maps(
            text_doc_ids=self._extract_doc_ids(doc_list=text_skipped_docs),
            entity_doc_ids=self._extract_doc_ids(doc_list=entity_skipped_docs),
            text_doc_list=text_skipped_docs,
            entity_doc_list=entity_skipped_docs,
            default_reason="Unknown reason",
        )

        # Calculate final processed count
        # Processed = total - (failed + skipped)
        total_docs = text_metadata.get(Metrics.External.TOTAL_DOCS, 0)
        failed_or_skipped_count = len(merged_failed_map) + len(merged_skipped_map)
        processed_count = total_docs - failed_or_skipped_count

        # Determine final execution status
        final_status = OperatorUtils.determine_execution_status(
            processed_count=processed_count,
            failed_count=len(merged_failed_map),
            skipped_count=len(merged_skipped_map),
        )

        # Return consolidated metadata
        return {
            Metrics.External.TOTAL_DOCS: total_docs,
            Metrics.External.PROCESSED_DOCS: processed_count,
            Metrics.External.FAILED_DOCS_COUNT: len(merged_failed_map),
            Metrics.External.FAILED_DOCS: list(merged_failed_map.values()),
            Metrics.External.SKIPPED_DOCS_COUNT: len(merged_skipped_map),
            Metrics.External.SKIPPED_DOCS: list(merged_skipped_map.values()),
            Metrics.External.NODE_STATUS: final_status,
        }

    @staticmethod
    def _add_page_statistics(*, metadata: dict[str, Any], table: pa.Table) -> dict[str, Any]:
        """Add page statistics by format to metadata using PyArrow C++ compute operations.

        Extension extraction and grouping are performed entirely in PyArrow's C++ layer —
        no Python loop over rows, no full table copy.

        Args:
            metadata: Existing metadata dictionary
            table: PyArrow table containing 'name' and 'pages_processed' columns

        Returns:
            Updated metadata with page_type_stats and total_pages_converted statistics
        """
        if OperatorConstants.Columns.PAGES_PROCESSED not in table.column_names:
            logger.warning("Pages processed column not found in table, skipping page statistics")
            return metadata

        if OperatorConstants.Columns.NAME not in table.column_names:
            logger.warning("Name column not found in table, skipping page statistics")
            return metadata

        pages_column = table.column(OperatorConstants.Columns.PAGES_PROCESSED)
        total_pages = pc.sum(pages_column).as_py()  # type: ignore[attr-defined]

        # Extract last extension entirely in C++ — no Python loop, no to_pylist()
        name_column = pc.cast(table.column(OperatorConstants.Columns.NAME), pa.string())
        extracted = pc.extract_regex(name_column, r"\.(?P<ext>[^.]+)$")  # type: ignore[attr-defined]
        ext_col = pc.struct_field(extracted, "ext")  # type: ignore[attr-defined]
        extensions = pc.if_else(  # type: ignore[attr-defined]
            pc.invert(pc.is_null(ext_col)),  # type: ignore[attr-defined]
            ext_col,
            pa.scalar(OperatorConstants.Misc.UNKNOWN, pa.string()),
        )
        extensions = pc.utf8_lower(extensions)  # type: ignore[attr-defined]

        # Group on a 2-column mini-table — avoids copying the full input table
        mini_table = pa.table(
            {
                "__ext": extensions,
                OperatorConstants.Columns.PAGES_PROCESSED: pages_column,
            }
        )
        grouped = mini_table.group_by(["__ext"]).aggregate([(OperatorConstants.Columns.PAGES_PROCESSED, "sum")])
        page_type_stats: dict[str, int] = dict(
            zip(
                grouped.column("__ext").to_pylist(),
                grouped.column(f"{OperatorConstants.Columns.PAGES_PROCESSED}_sum").to_pylist(),
                strict=True,
            )
        )

        metadata[OperatorConstants.Metadata.PAGE_TYPE_STATS] = page_type_stats
        metadata[OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED] = total_pages
        logger.info("Page statistics by format: %s, total pages: %d", page_type_stats, total_pages)

        return metadata

    @staticmethod
    def _drop_binary_content_column(*, tables: list[pa.Table]) -> list[pa.Table]:
        """Drop binary_content column from tables if present.

        After extraction is complete, the binary_content column is no longer needed
        and can be dropped to reduce memory usage and table size.

        Args:
            tables: List of PyArrow tables to process

        Returns:
            List of tables with binary_content column removed (if it existed)
        """
        result_tables = []

        for idx, table in enumerate(tables):
            if OperatorConstants.Columns.BINARY_CONTENT in table.column_names:
                # Log columns before dropping
                logger.info("Table %d BEFORE dropping binary_content - Columns: %s", idx, table.column_names)

                # Drop binary_content column in-place for memory efficiency
                table_without_binary = table.drop([OperatorConstants.Columns.BINARY_CONTENT])
                result_tables.append(table_without_binary)

                # Log columns after dropping
                logger.info(
                    "Table %d AFTER dropping binary_content - Columns: %s (dropped from %d rows)",
                    idx,
                    table_without_binary.column_names,
                    table.num_rows,
                )
            else:
                logger.info(
                    "Table %d - No binary_content column present; extraction uses on-demand binary fetch and populates "
                    "'content'. Columns: %s",
                    idx,
                    table.column_names,
                )
                result_tables.append(table)

        return result_tables

    def _get_supported_extensions(self) -> set[str]:
        """Get supported file extensions based on extraction mode and available dependencies.

        Returns:
            Set of supported file extensions (e.g., {'.pdf', '.docx', '.txt'})
        """
        from docpipe.core.operators.operator_utils import is_asr_available

        if self.text_extraction_mode == TextExtractionMode.DOCLING_LIBRARY:
            extensions = set(OperatorConstants.FileExtensions.DOCLING_LIBRARY_BASE_EXTENSIONS)
            # Add audio/video if ASR is available
            if is_asr_available():
                extensions.update(OperatorConstants.FileExtensions.DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS)
            return extensions

        if self.text_extraction_mode == TextExtractionMode.DOCLING_SERVE:
            return set(OperatorConstants.FileExtensions.DOCLING_SERVE_EXTENSIONS)

        # Default: return base extensions
        return set(OperatorConstants.FileExtensions.DOCLING_LIBRARY_BASE_EXTENSIONS)

    def _validate_extensions(self, table: pa.Table, metadata: dict[str, Any]) -> set[int]:
        """Validate file extensions for documents before extraction.

        Similar to DocumentClassifierOperator::_validate_extensions_for_existing_content,
        this validates extensions upfront to skip unsupported files early.

        Args:
            table: Input PyArrow table with document metadata
            metadata: Metadata dictionary to record skipped documents

        Returns:
            Set of row indices that were skipped due to unsupported extensions
        """
        skipped_indices: set[int] = set()

        if OperatorConstants.Columns.NAME not in table.column_names:
            return skipped_indices

        supported_extensions = self._get_supported_extensions()

        for idx in range(table.num_rows):
            doc_name = table[OperatorConstants.Columns.NAME][idx].as_py()

            # Try to get extension from document_format column first (set by ingest operators for cloud files)
            # Fall back to extracting from filename if not available
            file_ext = ""
            if "document_format" in table.column_names:
                doc_fmt = table["document_format"][idx].as_py() or ""
                if doc_fmt:
                    file_ext = f".{doc_fmt.lstrip('.')}"

            if not file_ext:
                file_ext = Path(doc_name).suffix.lower()

            if file_ext not in supported_extensions:
                doc_id = (
                    table[OperatorConstants.Columns.ID][idx].as_py()
                    if OperatorConstants.Columns.ID in table.column_names
                    else f"doc_{idx}"
                )
                error_msg = f"Unsupported file extension for {self.text_extraction_mode.value}: {file_ext}"
                logger.info("Skipping document %s: %s", doc_name, error_msg)

                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=str(doc_id),
                    doc_name=doc_name,
                    reason=error_msg,
                )
                skipped_indices.add(idx)

        return skipped_indices

    # ------------------------------------------------------------------
    # Streaming pipeline — runs text and entity extraction concurrently
    # ------------------------------------------------------------------

    @staticmethod
    def _build_extraction_stage_progress(
        *,
        text_completed: int,
        text_failed: int,
        text_total: int,
        entity_completed: int,
        entity_failed: int,
        entity_total: int,
    ) -> dict[str, Any]:
        """Build the extraction_stage_progress payload for both stages.

        Returns a dict suitable for embedding directly into the operator metadata
        that transform() returns, so it survives the complete_node_execution path
        without any intermediate store read-back.

        Args:
            text_completed: Successfully text-extracted documents.
            text_failed: Failed text-extraction documents.
            text_total: Total documents submitted for text extraction.
            entity_completed: Successfully entity-extracted documents.
            entity_failed: Failed entity-extraction documents.
            entity_total: Documents submitted for entity extraction.

        Returns:
            Dict with key ``extraction_stage_progress`` containing per-stage dicts.
        """
        return {
            OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS: {
                OperatorConstants.Extraction.STAGE_TEXT_EXTRACTION: _build_stage_dict(
                    completed=text_completed,
                    failed=text_failed,
                    total=text_total,
                ),
                OperatorConstants.Extraction.STAGE_ENTITY_EXTRACTION: _build_stage_dict(
                    completed=entity_completed,
                    failed=entity_failed,
                    total=entity_total,
                ),
            }
        }

    def _write_streaming_progress(
        self,
        *,
        text_completed: int,
        text_failed: int,
        text_total: int,
        entity_completed: int,
        entity_failed: int,
        entity_total: int,
    ) -> None:
        """Write live extraction stage progress to the DB while the batch is still running.

        Mirrors the periodic update_node_stats() calls that TextExtractionPort makes in
        the sequential path, so the batch aggregator can display "Text Extracted" /
        "Entities Extracted" counters while the streaming pipeline is in flight.

        No-ops silently when job tracking context is unavailable (no job_run_id/node_id)
        or when the DB write fails — progress updates must never abort extraction.
        """
        try:
            job_run_id = self.text_adapter.job_run_id
            node_id = self.text_adapter.node_id
            if not job_run_id or not node_id:
                return

            factory = get_default_factory()
            job_stats_store = factory.create_job_stats_store()

            def _stage(*, completed: int, failed: int, total: int) -> dict[str, Any]:
                done = completed + failed
                pct = round((done / total) * 100, 2) if total else 0.0
                status = (
                    OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
                    if done >= total
                    else OperatorConstants.Extraction.STAGE_STATUS_RUNNING
                )
                return {
                    OperatorConstants.Extraction.STAGE_STATUS: status,
                    OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: total,
                    OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: completed,
                    OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: failed,
                    OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE: pct,
                }

            progress_metadata: dict[str, Any] = {
                OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS: {
                    OperatorConstants.Extraction.STAGE_TEXT_EXTRACTION: _stage(
                        completed=text_completed, failed=text_failed, total=text_total
                    ),
                    OperatorConstants.Extraction.STAGE_ENTITY_EXTRACTION: _stage(
                        completed=entity_completed, failed=entity_failed, total=entity_total
                    ),
                }
            }

            metadata_item = NodeMetadataItem(
                id=node_id,
                operator=self.text_adapter.node_name or "ExtractOperator",
                node_metadata=progress_metadata,
            )

            # Read existing stats to preserve fields set by the orchestrator
            # (total_docs, start_time, etc.), then merge in the progress metadata.
            batch_id = self.text_adapter.batch_id
            existing = None
            try:
                existing = job_stats_store.get_node_stats_by_batch_and_node(
                    job_run_id=job_run_id, node_id=node_id, batch_id=batch_id
                )
            except Exception:  # nosec B110
                pass  # partial merge is acceptable for live progress

            merged = (
                existing.model_dump()
                if existing
                else {
                    "id": node_id,
                    "name": self.text_adapter.node_name or "ExtractOperator",
                }
            )
            merged[OperatorConstants.Metadata.NODE_METADATA] = metadata_item.model_dump()
            merged["node_status"] = merged.get("node_status", "Running")

            node_stats_obj = NodeStats(**{k: v for k, v in merged.items() if k in NodeStats.model_fields})

            if isinstance(job_stats_store, JsonJobStatsStore):
                # Use a short lock timeout so a busy write (entity worker threads also
                # hold node_stats.lock) skips rather than blocking for 30 seconds.
                wrote = job_stats_store.try_store_node_stats(
                    job_run_id=job_run_id, node_stats=node_stats_obj, lock_timeout=0.5
                )
                if not wrote:
                    logger.debug("Skipping streaming progress update: node_stats.lock busy")
                    return
            else:
                # Non-filesystem stores have no shared file lock — use the normal path.
                job_stats_store.store_node_stats(job_run_id=job_run_id, node_stats=node_stats_obj)

            logger.info(
                "Streaming progress: text=%s/%s entity=%s/%s",
                text_completed,
                text_total,
                entity_completed,
                entity_total,
            )
        except Exception as exc:
            logger.warning("Failed to write streaming progress update: %s", exc)

    def _run_streaming_pipeline(
        self,
        *,
        table: pa.Table,
        metadata: dict[str, Any],
    ) -> tuple[list[pa.Table], dict[str, Any]]:
        """Run text and entity extraction concurrently in a producer-consumer pipeline.

        As soon as a document finishes text extraction it is immediately submitted for
        entity extraction, without waiting for the remaining text-extraction workers to
        finish. This eliminates the hard sequential barrier between the two stages.

        Architecture
        ------------
        - Thread pool A  : text workers — calls text_adapter.extract_single_document()
        - Thread pool B  : entity workers — calls entity_adapter.extract_entities_single()

        All text futures are submitted up-front.  The main thread drains them via
        ``concurrent.futures.as_completed`` and submits an entity task immediately
        for each successfully extracted document.  Entity futures are drained in a
        second ``as_completed`` loop after all text futures resolve.

        Progress tracking
        -----------------
        Final stage counters are written directly into the returned ``metadata`` dict
        as ``extraction_stage_progress``, so they survive ``complete_node_execution``
        without any intermediate store read-back.

        Args:
            table: PyArrow table with document information.
            metadata: Metadata dict to populate (already initialised by transform()).

        Returns:
            Tuple of ([result_table], consolidated_metadata).

        Raises:
            ValueError: If every document fails text extraction (same as TextExtractionPort).
        """
        if self.entity_adapter is None:
            raise ValueError(
                "_run_streaming_pipeline requires entity_adapter to be set. "
                "Call transform() instead, which routes to the correct path."
            )

        doc_tasks: list[dict[str, Any]] = OperatorUtils.prepare_document_content_fetch(
            table=table, global_config=self.text_adapter.global_config
        )
        total_docs = len(doc_tasks)

        # Per-row accumulators (positional, same length as table)
        doc_contents: list[str] = [""] * table.num_rows
        doc_pages_processed: list[int] = [0] * table.num_rows
        entities_list: list[dict[str, Any]] = [{} for _ in range(table.num_rows)]

        # Initialise format lists for any additional output formats requested
        format_lists: dict[str, list[str | None]] = {}
        for fmt in self.text_adapter.additional_formats:
            if fmt in OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING:
                format_lists[fmt] = [None] * table.num_rows

        remove_row_idx: list[int] = []
        non_recoverable_doc_ids: list[int] = []

        # Counters — accessed only from the main thread (after future.result())
        text_completed = 0
        text_failed = 0
        entity_completed = 0
        entity_failed = 0

        # Periodic progress tracking — same 5-second interval as TextExtractionPort
        last_progress_update = 0.0
        progress_update_interval = 5

        # Prepare schemas once before any processing (read-only during execution)
        service = EntityExtractionService(
            adapter=self.entity_adapter,
            config={
                OperatorConstants.Columns.DOC_COLUMN: self.doc_column,
                OperatorConstants.Columns.OUTPUT_COLUMN: self.output_column,
                OperatorConstants.Config.EXPAND_EXTRACTED_DATA: self.expand_extracted_data,
                OperatorConstants.Columns.DOC_ID_HASH: self.entity_adapter.doc_id_hash_column,
                OperatorConstants.Config.CUSTOM_SCHEMA: self.entity_adapter.custom_schema,
                "common_log_arguments": self.entity_adapter.common_log_arguments,
            },
            max_workers=self.entity_adapter.max_workers,
            job_run_id=self.entity_adapter.job_run_id,
            node_id=self.entity_adapter.node_id,
            node_name=self.entity_adapter.node_name,
            batch_id=self.entity_adapter.batch_id,
        )
        _doc_types, schema_templates = service.prepare_schemas(table=table)

        logger.info(
            "Streaming pipeline: %s documents, text_workers=%s, entity_workers=%s",
            total_docs,
            self.text_adapter.max_workers,
            self.entity_adapter.max_workers,
        )

        use_processes = self.text_adapter.use_processes
        text_executor_cls = ProcessPoolExecutor if use_processes else ThreadPoolExecutor

        # Entity extraction always uses threads regardless of use_processes.
        # Every entity adapter (LiteLLM, WatsonX, Docling) makes outbound HTTP
        # calls — they are IO-bound, never CPU-bound in-process.
        with (
            text_executor_cls(max_workers=self.text_adapter.max_workers) as text_executor,
            ThreadPoolExecutor(max_workers=self.entity_adapter.max_workers) as entity_executor,
        ):
            # Map from text Future → task dict
            text_future_to_task: dict[Future, dict[str, Any]] = {}

            # Submit all text-extraction tasks up front
            for task in doc_tasks:
                if "error" in task:
                    # Extension/fetch error recorded before executor runs
                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=task["error"],
                    )
                    text_failed += 1
                    continue

                future = text_executor.submit(
                    self.text_adapter.extract_single_document,
                    file_path=task["doc_name"],
                    binary_content=task["binary_content"],
                )
                text_future_to_task[future] = task

            # Map from entity Future → (idx, doc_id, doc_name)
            entity_future_to_info: dict[Future, tuple[int, str, str]] = {}

            # Collect text results as they complete; immediately submit entity tasks
            for text_future in as_completed(text_future_to_task):
                task = text_future_to_task[text_future]
                idx = task["idx"]

                try:
                    result = text_future.result()
                except Exception as exc:
                    error_msg = str(exc)
                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=error_msg,
                    )
                    remove_row_idx.append(idx)
                    text_failed += 1
                    continue

                if result.get(OperatorConstants.Extraction.SUCCESS):
                    # ---- Text extraction succeeded ----
                    extracted_content = result.get(OperatorConstants.Columns.DOC_COLUMN_DEFAULT) or ""
                    doc_contents[idx] = extracted_content

                    # Additional formats
                    for fmt, content_list in format_lists.items():
                        col_name = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING.get(fmt)
                        if col_name and col_name in result:
                            content_list[idx] = result[col_name]

                    # Page count
                    ext_meta = result.get(OperatorConstants.Metadata.METADATA, {})
                    native_pages = ext_meta.get("page_count")
                    if native_pages and isinstance(native_pages, (int, float)) and native_pages > 0:
                        doc_pages_processed[idx] = int(native_pages)
                    else:
                        chars = len(extracted_content)
                        cpp = OperatorConstants.Processing.CHARS_PER_PAGE
                        doc_pages_processed[idx] = max(1, (chars + cpp - 1) // cpp)

                    metadata[Metrics.External.PROCESSED_DOCS] += 1
                    text_completed += 1

                    # ---- Immediately queue entity extraction ----
                    # Determine schema for this document
                    schema_to_use = self.entity_adapter.custom_schema
                    if schema_templates:
                        doc_type = (
                            table.column(OperatorConstants.Columns.DOCUMENT_TYPE)[idx].as_py()
                            if OperatorConstants.Columns.DOCUMENT_TYPE in table.column_names
                            else None
                        )
                        if doc_type and doc_type in schema_templates:
                            schema_to_use = schema_templates[doc_type]

                    if not extracted_content:
                        # Nothing to feed to the LLM — skip
                        AbstractOperator.record_skipped_document(
                            metadata=metadata,
                            doc_id=str(task["doc_id"]),
                            doc_name=task["doc_name"],
                            reason=f"Column '{self.doc_column}' is empty after text extraction.",
                        )
                    else:
                        entity_future = entity_executor.submit(
                            self.entity_adapter.extract_entities_single,
                            doc_id=str(task["doc_id"]),
                            doc_name=task["doc_name"],
                            content=extracted_content,
                            schema=schema_to_use,
                        )
                        entity_future_to_info[entity_future] = (idx, str(task["doc_id"]), task["doc_name"])

                else:
                    # ---- Text extraction failed ----
                    error_msg = result.get(OperatorConstants.Extraction.ERROR, "Unknown error")

                    if is_non_recoverable_error(error_msg):
                        non_recoverable_doc_ids.append(idx)
                        error_msg = (
                            f"{error_msg}. This document will not be processed in future "
                            "flow executions unless the document is modified."
                        )
                        logger.warning(
                            "Non-recoverable error for document %s: %s",
                            task["doc_name"],
                            error_msg,
                        )

                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=error_msg,
                    )
                    remove_row_idx.append(idx)
                    text_failed += 1

                # Periodic live progress update — write both stage counters to DB so the
                # batch aggregator can display "Text Extracted" / "Entities Extracted"
                # while the batch is still running (same 5-second cadence as TextExtractionPort).
                now = time.time()
                if now - last_progress_update >= progress_update_interval:
                    self._write_streaming_progress(
                        text_completed=text_completed,
                        text_failed=text_failed,
                        text_total=total_docs,
                        entity_completed=entity_completed,
                        entity_failed=entity_failed,
                        entity_total=len(entity_future_to_info),
                    )
                    last_progress_update = now

            # Text stage is fully done — guard against all-failed case
            if text_completed == 0:
                suffix = format_failed_docs_summary(failed_docs=metadata.get(Metrics.External.FAILED_DOCS, []))
                raise ValueError(
                    f"All {total_docs} document(s) failed text extraction. "
                    f"No content was extracted. Cannot continue pipeline with empty content.{suffix}"
                )

            # Drain entity futures
            for entity_future in as_completed(entity_future_to_info):
                idx, doc_id, doc_name = entity_future_to_info[entity_future]
                try:
                    result = entity_future.result()
                    if result.get(OperatorConstants.Extraction.SUCCESS):
                        # Entity futures are drained in the main thread via as_completed —
                        # no concurrent writes to entities_list, no lock needed.
                        entities_list[idx] = result.get(OperatorConstants.Misc.ENTITIES, {})
                        entity_completed += 1
                    else:
                        error = result.get(OperatorConstants.Extraction.ERROR, "Unknown error")
                        AbstractOperator.record_failed_document(
                            metadata=metadata,
                            doc_id=doc_id,
                            doc_name=doc_name,
                            reason=error,
                        )
                        logger.error("Entity extraction failed for %s: %s", doc_name, error)
                        entity_failed += 1
                except Exception as exc:
                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        reason=str(exc),
                    )
                    logger.error("Entity extraction error for %s: %s", doc_name, exc)
                    entity_failed += 1

                # Periodic live progress update during entity drain loop.
                now = time.time()
                if now - last_progress_update >= progress_update_interval:
                    self._write_streaming_progress(
                        text_completed=text_completed,
                        text_failed=text_failed,
                        text_total=total_docs,
                        entity_completed=entity_completed,
                        entity_failed=entity_failed,
                        entity_total=len(entity_future_to_info),
                    )
                    last_progress_update = now

        # Write the final stage progress into metadata so it is carried through
        # complete_node_execution without any intermediate store read-back.
        metadata.update(
            self._build_extraction_stage_progress(
                text_completed=text_completed,
                text_failed=text_failed,
                text_total=total_docs,
                entity_completed=entity_completed,
                entity_failed=entity_failed,
                entity_total=len(entity_future_to_info),
            )
        )

        logger.info(
            "Streaming pipeline complete: text=%s/%s ok, entity=%s/%s ok",
            text_completed,
            total_docs,
            entity_completed,
            len(entity_future_to_info),
        )

        # ----------------------------------------------------------------
        # Assemble the final table
        # ----------------------------------------------------------------
        original_table = table

        # Remove rows whose text extraction failed
        if remove_row_idx:
            table = OperatorUtils.remove_rows(table=table, remove_row_idx=remove_row_idx)
            remove_set = set(remove_row_idx)
            doc_contents = [c for i, c in enumerate(doc_contents) if i not in remove_set]
            doc_pages_processed = [p for i, p in enumerate(doc_pages_processed) if i not in remove_set]
            entities_list = [e for i, e in enumerate(entities_list) if i not in remove_set]
            for fmt in format_lists:
                format_lists[fmt] = [v for i, v in enumerate(format_lists[fmt]) if i not in remove_set]

        # Add extracted content column (markdown or doclang depending on doc_format)
        table = TransformUtils.add_column(table=table, name=self.doc_column, content=doc_contents)

        # Add additional format columns
        for fmt, content_list in format_lists.items():
            col_name = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING[fmt]
            if any(v is not None for v in content_list):
                table = TransformUtils.add_column(table=table, name=col_name, content=content_list)

        # Add pages_processed column
        table = TransformUtils.add_column(
            table=table, name=OperatorConstants.Columns.PAGES_PROCESSED, content=doc_pages_processed
        )

        # Generate doc_id_hash
        logger.info("Generating hash id and adding it to table")
        hash_operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: self.doc_column})
        table_list, _ = hash_operator.transform(table)
        table = table_list[0]

        # Add entities column
        entities_json_list: list[str] = [json.dumps(e) if e else "{}" for e in entities_list]
        table = TransformUtils.add_column(table=table, name=self.output_column, content=entities_json_list)

        # Optionally expand entities into individual columns
        if self.expand_extracted_data:
            table = service.expand_entities_columns(table=table, entities_list=entities_list)

        # Process non-recoverable errors
        metadata = process_non_recoverable_errors(
            table=original_table,
            non_recoverable_doc_ids=non_recoverable_doc_ids,
            metadata=metadata,
            common_log_arguments=self.text_adapter.global_config.get(OperatorConstants.Config.COMMON_LOG_ARGUMENTS, {}),
        )

        # Determine final execution status
        failed_count = metadata.get(Metrics.External.FAILED_DOCS_COUNT, 0)
        skipped_count = metadata.get(Metrics.External.SKIPPED_DOCS_COUNT, 0)
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.determine_execution_status(
            processed_count=metadata.get(Metrics.External.PROCESSED_DOCS, 0),
            failed_count=failed_count,
            skipped_count=skipped_count,
        )

        return [table], metadata

    def transform(
        self, table: pa.Table, file_name: str | None = None, metadata: dict[str, Any] | None = None
    ) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform documents using text and entity extraction adapters.

        This method orchestrates both text and entity extraction:
        1. First performs text extraction using text_adapter
        2. Then performs entity extraction using entity_adapter (if enabled)

        Text extraction reads document bytes from file paths provided by ingest operators.
        The extraction utilities resolve bytes from either the 'path' column (primary)
        or 'binary_content' column (backward compatibility fallback).

        Content Reuse:
        If document_classifier pre-fetched content and stored it in '_temp_content_for_extract',
        this operator will reuse it for docling_library text extraction mode, skipping re-extraction.

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - path: File path to document (primary input from local ingest)
                - binary_content: Pre-loaded binary content (optional, for backward compatibility)
                - document_type: Document type for template selection (optional)
                - _temp_content_for_extract: Pre-fetched content from document_classifier (optional)
            file_name: Optional file name for logging
            metadata: Optional metadata dictionary to update

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)

        Raises:
            FlowExecutionFailedException: If extraction fails
        """

        logger.info(
            "Starting extraction: text_mode='%s', entity_mode='%s' for %s documents",
            self.text_extraction_mode.value,
            self.entity_extraction_mode.value,
            table.num_rows,
        )
        if metadata is None:
            metadata = self.create_base_metadata(total_docs_count=table.num_rows)

        if table.num_rows == 0:
            # Add page metadata fields with zero/empty values for empty tables
            metadata[OperatorConstants.Metadata.PAGE_TYPE_STATS] = {}
            metadata[OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED] = 0
            return [table], metadata

        skipped_indices = self._validate_extensions(table, metadata)

        if skipped_indices:
            # Filter out skipped documents
            valid_indices = [i for i in range(table.num_rows) if i not in skipped_indices]
            if not valid_indices:
                logger.warning("All documents skipped due to unsupported extensions")
                metadata[OperatorConstants.Metadata.PAGE_TYPE_STATS] = {}
                metadata[OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED] = 0
                return [table], metadata

            table = table.take(valid_indices)
            logger.info("Filtered table: %s valid documents, %s skipped", len(valid_indices), len(skipped_indices))

        # Check for pre-fetched content from document_classifier (hybrid approach)
        content_reused = False

        if DocpipeConstants.TEMP_CONTENT_COLUMN in table.column_names:
            # Reuse prefetched content only when using docling_library mode with no provider_config
            provider_config = self.text_extraction_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
            can_reuse_prefetched_content = (
                self.text_extraction_mode == TextExtractionMode.DOCLING_LIBRARY and not provider_config
            )

            if can_reuse_prefetched_content:
                logger.info(
                    "Reusing pre-fetched content from '%s' for %s (no provider_config)",
                    DocpipeConstants.TEMP_CONTENT_COLUMN,
                    self.text_extraction_mode.value,
                )

                column_names = list(table.column_names)
                temp_idx = column_names.index(DocpipeConstants.TEMP_CONTENT_COLUMN)
                column_names[temp_idx] = self.doc_column

                # Also rename _temp_pages_processed if present
                if DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN in table.column_names:
                    temp_pages_idx = column_names.index(DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN)
                    column_names[temp_pages_idx] = OperatorConstants.Columns.PAGES_PROCESSED
                    logger.info(
                        "Renaming '%s' to '%s'",
                        DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN,
                        OperatorConstants.Columns.PAGES_PROCESSED,
                    )

                table = pa.table(
                    {
                        name: table.column(old_name)
                        for old_name, name in zip(table.column_names, column_names, strict=True)
                    },
                    schema=pa.schema(
                        [
                            (name, table.schema.field(old_name).type)
                            for old_name, name in zip(table.column_names, column_names, strict=True)
                        ]
                    ),
                )

                content_reused = True
                logger.info("Content reuse successful: skipping text extraction for %s documents", table.num_rows)
            else:
                reason = []
                if self.text_extraction_mode != TextExtractionMode.DOCLING_LIBRARY:
                    reason.append(f"text_mode={self.text_extraction_mode.value}")
                if provider_config:
                    reason.append("provider_config is set")
                reason_str = ", ".join(reason) if reason else "unknown reason"

                logger.info(
                    "Pre-fetched content found but not reusable (%s). Dropping temporary columns and performing fresh extraction.",
                    reason_str,
                )
                # Drop both temp columns if present
                columns_to_drop = []
                if DocpipeConstants.TEMP_CONTENT_COLUMN in table.column_names:
                    columns_to_drop.append(DocpipeConstants.TEMP_CONTENT_COLUMN)
                if DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN in table.column_names:
                    columns_to_drop.append(DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN)

                if columns_to_drop:
                    table = table.drop(columns_to_drop)

        result_tables: list[pa.Table] = []
        text_metadata: dict[str, Any] = {}
        entity_metadata: dict[str, Any] | None = None

        try:
            # ------------------------------------------------------------------
            # Streaming path: text + entity run concurrently (entity enabled,
            # content not pre-fetched).  All other cases fall through to the
            # original sequential steps below.
            # ------------------------------------------------------------------
            if self.entity_adapter is not None and not content_reused:
                result_tables, consolidated_metadata = self._run_streaming_pipeline(table=table, metadata=metadata)
                # Page statistics and binary-content drop still apply
                consolidated_metadata = self._add_page_statistics(
                    metadata=consolidated_metadata, table=result_tables[0]
                )
                result_tables = self._drop_binary_content_column(tables=result_tables)

                logger.info(
                    "Final extraction results: %s/%s documents processed, %s failed, %s skipped",
                    consolidated_metadata.get(Metrics.External.PROCESSED_DOCS, 0),
                    consolidated_metadata.get(Metrics.External.TOTAL_DOCS, table.num_rows),
                    consolidated_metadata.get(Metrics.External.FAILED_DOCS_COUNT, 0),
                    consolidated_metadata.get(Metrics.External.SKIPPED_DOCS_COUNT, 0),
                )
                return result_tables, consolidated_metadata

            # ------------------------------------------------------------------
            # Sequential path (entity disabled, or content reused from
            # document_classifier pre-fetch).
            # ------------------------------------------------------------------

            # Step 1: Text extraction (skip if content was reused)
            if content_reused:
                # Content already present in doc_column, skip text extraction
                # But we still need to generate doc_hash_id if not present
                if OperatorConstants.Columns.DOC_ID_HASH_DEFAULT not in table.column_names:
                    logger.info("Generating hash id for reused content")
                    hash_operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: self.doc_column})
                    table_list, _ = hash_operator.transform(table)
                    table = table_list[0]

                result_tables = [table]
                text_metadata = metadata.copy()
                text_metadata[Metrics.External.PROCESSED_DOCS] = table.num_rows
                logger.info(
                    "Skipped text extraction: reused pre-fetched content for %s documents",
                    table.num_rows,
                )
            else:
                # Perform normal text extraction
                result_tables, text_metadata = self.text_adapter.transform(table=table, metadata=metadata)

                logger.info(
                    "Text extraction completed: %s/%s documents processed",
                    text_metadata.get(Metrics.External.PROCESSED_DOCS, 0),
                    text_metadata.get(Metrics.External.TOTAL_DOCS, table.num_rows),
                )

            # Step 2: Entity extraction (if enabled — only reached when content_reused=True)
            if self.entity_adapter is not None:
                logger.info("Starting entity extraction on pre-fetched content")
                # Reset metadata for entity extraction to track independently
                # Note: result_tables[0] already has failed docs removed by text extraction
                entity_base_metadata = self.create_base_metadata(total_docs_count=result_tables[0].num_rows)
                result_tables, entity_metadata = self.entity_adapter.transform(
                    table=result_tables[0], metadata=entity_base_metadata
                )

                logger.info(
                    "Entity extraction completed: %s/%s documents processed",
                    entity_metadata.get(Metrics.External.PROCESSED_DOCS, 0),
                    entity_metadata.get(Metrics.External.TOTAL_DOCS, table.num_rows),
                )

            # Step 3: Consolidate metadata from both stages
            consolidated_metadata = self._consolidate_metadata(
                text_metadata=text_metadata, entity_metadata=entity_metadata
            )

            # Step 4: Add page statistics to metadata
            consolidated_metadata = self._add_page_statistics(metadata=consolidated_metadata, table=result_tables[0])

            # Step 5: Drop binary_content column after extraction is complete
            result_tables = self._drop_binary_content_column(tables=result_tables)

            logger.info(
                "Final extraction results: %s/%s documents processed, %s failed, %s skipped",
                consolidated_metadata.get(Metrics.External.PROCESSED_DOCS, 0),
                consolidated_metadata.get(Metrics.External.TOTAL_DOCS, table.num_rows),
                consolidated_metadata.get(Metrics.External.FAILED_DOCS_COUNT, 0),
                consolidated_metadata.get(Metrics.External.SKIPPED_DOCS_COUNT, 0),
            )

            return result_tables, consolidated_metadata

        except FlowExecutionFailedException:
            # Re-raise flow execution exceptions as-is
            raise
        except Exception as e:
            logger.error("Extraction failed: %s", e)
            raise FlowExecutionFailedException(
                f"Extraction failed (text_provider='{self.text_extraction_mode.value}', "
                f"entity_provider='{self.entity_extraction_mode.value}'): {e}"
            ) from e

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate operator configuration against metadata.

        Args:
            errors: List to append validation errors
            warnings: List to append validation warnings
            available_features: List of available input features
        """
        super().validate(errors, warnings, available_features)

        # Get metadata and extract ATTRIBUTES for validation
        metadata = self.get_metadata()
        attributes = metadata.get(OperatorConstants.Config.ATTRIBUTES, {})

        # Validate configuration against metadata
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        # Warn about any additional_formats values that won't produce an output column
        provider_config = self.text_extraction_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
        additional_formats = provider_config.get(OperatorConstants.Extraction.ADDITIONAL_FORMATS, [])
        if additional_formats:
            unknown = [
                fmt for fmt in additional_formats if fmt not in OperatorConstants.Extraction.VALID_OUTPUT_FORMATS
            ]
            if unknown:
                warnings.append(
                    f"text_extraction.provider_config.additional_formats contains unknown values {unknown}. "
                    f"These will be ignored. Valid options are: {OperatorConstants.Extraction.VALID_OUTPUT_FORMATS}"
                )

    @staticmethod
    def _get_text_extraction_provider_schemas() -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for the text_extraction provider_config field.

        Schemas are derived automatically from every adapter registered via
        ``@register_text_extraction_adapter``.
        """
        # Import the adapter modules so their @register_text_extraction_adapter decorators fire.
        import docpipe.core.operators.extract.adapters.outbound.text_extraction  # noqa: F401
        from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
            TextExtractionAdapterFactory,
        )

        return {
            name: OperatorUtils.model_schema_to_docpipe(schema=adapter_cls.get_config_schema().model_json_schema())
            for name, adapter_cls in TextExtractionAdapterFactory._registry.items()
        }

    @staticmethod
    def _get_entity_extraction_provider_schemas() -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for the entity_extraction provider_config field.

        Schemas are derived automatically from every adapter registered via
        ``@register_entity_extraction_adapter``. Importing the package triggers all
        decorator registrations before the registry is iterated.
        """
        import docpipe.core.operators.extract.adapters.outbound.entity_extraction  # noqa: F401
        from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
            EntityExtractionAdapterFactory,
        )

        return {
            name: OperatorUtils.model_schema_to_docpipe(schema=adapter_cls.get_config_schema().model_json_schema())
            for name, adapter_cls in EntityExtractionAdapterFactory.get_registry_items()
        }

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata about the operator including features and attributes.

        Returns comprehensive metadata describing the operator's capabilities,
        configuration parameters, and output features. This metadata is used
        for flow validation and UI generation.

        Returns:
            Dictionary containing operator metadata with:
                - category: Operator category
                - features: Output features/columns produced
                - is_operator_available: Availability status
                - attributes: Configuration parameters with descriptions
        """
        metadata_features = {
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: {
                OperatorConstants.Misc.NAME: "Document Content",
                OperatorConstants.Config.DESCRIPTION: "The markdown content extracted from the document (always present)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY],
            },
            OperatorConstants.Columns.CONTENT_HTML: {
                OperatorConstants.Misc.NAME: "HTML Content",
                OperatorConstants.Config.DESCRIPTION: "HTML format of extracted content (optional, if 'html' in additional_formats)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.CONTENT_JSON: {
                OperatorConstants.Misc.NAME: "JSON Content",
                OperatorConstants.Config.DESCRIPTION: "JSON format of extracted content (optional, if 'json' in additional_formats)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.CONTENT_TEXT: {
                OperatorConstants.Misc.NAME: "Text Content",
                OperatorConstants.Config.DESCRIPTION: "Plain text format of extracted content (optional, if 'text' in additional_formats)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.CONTENT_DOCTAGS: {
                OperatorConstants.Misc.NAME: "DocTags Content",
                OperatorConstants.Config.DESCRIPTION: "DocTags format of extracted content (optional, if 'doctags' in additional_formats)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.CONTENT_DOCLANG: {
                OperatorConstants.Misc.NAME: "DocLang Content",
                OperatorConstants.Config.DESCRIPTION: "DocLang format of extracted content (optional, if 'doclang' in additional_formats)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: {
                OperatorConstants.Misc.NAME: "Hash ID",
                OperatorConstants.Config.DESCRIPTION: "Hash ID of the document row",
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.IS_PRIMARY: True,
                OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY, OperatorConstants.Misc.PRIMARY],
            },
            OperatorConstants.Misc.ENTITIES: {
                OperatorConstants.Misc.NAME: "Entities",
                OperatorConstants.Config.DESCRIPTION: "Extracted entities from document content (when entity extraction is enabled)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.TAGS: [],
            },
            OperatorConstants.Columns.PAGES_PROCESSED: {
                OperatorConstants.Misc.NAME: "Pages Processed",
                OperatorConstants.Config.DESCRIPTION: "Estimated page count based on content length (3000 chars per page)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_INT32,
                OperatorConstants.Misc.TAGS: [],
            },
        }

        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: ExtractOperator.category.value,
            OperatorConstants.Misc.LABEL: "Document Extractor",
            OperatorConstants.Config.DESCRIPTION: "Extract text and entities from documents (PDF, DOCX, PPTX, images, audio, etc.) using Docling.",
            OperatorConstants.Config.FEATURES: metadata_features,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: ExtractOperator.is_available(),
            OperatorConstants.Config.ATTRIBUTES: {
                # Text extraction configuration (nested)
                OperatorConstants.Config.TEXT_EXTRACTION: {
                    OperatorConstants.Misc.NAME: "Text Extraction Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Configuration for text extraction from documents",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.DEFAULT: {
                        OperatorConstants.Config.PROVIDER: OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY,
                        OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                    },
                    OperatorConstants.Config.PROPERTIES: {
                        OperatorConstants.Config.PROVIDER: {
                            OperatorConstants.Misc.NAME: "Text Extraction Provider",
                            OperatorConstants.Config.DESCRIPTION: (
                                f"Text extraction strategy: '{OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY}' (local Docling with optional VLM), "
                                f"or '{OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_SERVE}' (remote API)"
                            ),
                            OperatorConstants.Config.REQUIRED: True,
                            OperatorConstants.Config.DEFAULT: OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                        OperatorConstants.Config.PROVIDER_CONFIG: {
                            OperatorConstants.Misc.NAME: "Provider Configuration",
                            OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration for text extraction. Fields vary by provider — see the 'providers' schema for details.",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            OperatorConstants.Config.PROVIDERS: ExtractOperator._get_text_extraction_provider_schemas(),
                        },
                        OperatorConstants.Columns.DOC_COLUMN: {
                            OperatorConstants.Misc.NAME: "Document Column",
                            OperatorConstants.Config.DESCRIPTION: "Name of the column to store extracted document content",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                    },
                },
                # Entity extraction configuration (nested)
                OperatorConstants.Config.ENTITY_EXTRACTION: {
                    OperatorConstants.Misc.NAME: "Entity Extraction Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Configuration for entity extraction from documents (optional)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.DEFAULT: {
                        OperatorConstants.Config.PROVIDER: OperatorConstants.ExtractionModes.ENTITY_MODE_NONE,
                    },
                    OperatorConstants.Config.PROPERTIES: {
                        OperatorConstants.Config.PROVIDER: {
                            OperatorConstants.Misc.NAME: "Entity Extraction Provider",
                            OperatorConstants.Config.DESCRIPTION: (
                                f"Entity extraction strategy: '{OperatorConstants.ExtractionModes.ENTITY_MODE_LITELLM}' (LiteLLM multi-provider), "
                                f"'{OperatorConstants.ExtractionModes.ENTITY_MODE_WATSONX}' (IBM watsonx), "
                                f"'{OperatorConstants.ExtractionModes.ENTITY_MODE_DOCLING}' (template-based), "
                                f"or '{OperatorConstants.ExtractionModes.ENTITY_MODE_NONE}' (no entity extraction)"
                            ),
                            OperatorConstants.Config.REQUIRED: True,
                            OperatorConstants.Config.DEFAULT: OperatorConstants.ExtractionModes.ENTITY_MODE_NONE,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                        OperatorConstants.Config.PROVIDER_CONFIG: {
                            OperatorConstants.Misc.NAME: "Provider Configuration",
                            OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration for entity extraction. Fields vary by provider — see the 'providers' schema for details.",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            OperatorConstants.Config.PROVIDERS: ExtractOperator._get_entity_extraction_provider_schemas(),
                        },
                        OperatorConstants.Columns.OUTPUT_COLUMN: {
                            OperatorConstants.Misc.NAME: "Output Column",
                            OperatorConstants.Config.DESCRIPTION: "Name of the column to store extracted entities",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: OperatorConstants.Misc.ENTITIES,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                        OperatorConstants.ExtractionModes.ENTITY_MAX_DOC_CHARS: {
                            OperatorConstants.Misc.NAME: "Max Document Characters",
                            OperatorConstants.Config.DESCRIPTION: "Maximum characters to pass for entity extraction",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: 8000,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                        },
                        OperatorConstants.Config.CUSTOM_SCHEMA: {
                            OperatorConstants.Misc.NAME: "Custom Extraction Schema",
                            OperatorConstants.Config.DESCRIPTION: "Schema dictionary for structured entity extraction",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: None,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                        },
                        OperatorConstants.Config.EXPAND_EXTRACTED_DATA: {
                            OperatorConstants.Misc.NAME: "Expand Extracted Data",
                            OperatorConstants.Config.DESCRIPTION: "Whether to expand entity data JSON into individual columns",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                        },
                    },
                },
                # Performance configuration
                OperatorConstants.Config.MAX_WORKERS: {
                    OperatorConstants.Misc.NAME: "Max Workers",
                    OperatorConstants.Config.DESCRIPTION: "Maximum number of parallel workers for extraction (auto-detects based on CPU count if not specified)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                OperatorConstants.Config.USE_PROCESSES: {
                    OperatorConstants.Misc.NAME: "Use Processes",
                    OperatorConstants.Config.DESCRIPTION: "Use ProcessPoolExecutor instead of ThreadPoolExecutor for CPU-intensive tasks",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
            },
        }
