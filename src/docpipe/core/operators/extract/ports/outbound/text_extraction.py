# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Text extraction port interface.

This module defines the port interface for text extraction operations following
hexagonal architecture principles. The port contains the parallel processing
orchestration logic, while adapters implement the specific extraction mechanics.
"""

import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models.node_stats import NodeMetadataItem
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.extract.encrypted_documents import DocumentDecryptor
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator
from docpipe.core.operators.operator_utils import OperatorUtils, format_failed_docs_summary
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.non_recoverable_utils import is_non_recoverable_error, process_non_recoverable_errors

logger: logging.Logger = get_logger()


class TextExtractionPort(ABC):
    """Port interface for text extraction with parallel processing orchestration.

    The port acts as an orchestrator that manages:
    - Parallel processing framework (executor management)
    - Worker task submission and result fetching
    - Result aggregation and error handling
    - Progress tracking and metadata collection

    Adapters implement the specific extraction logic via the extract_single_document
    method, which is called by the port's parallel processing framework.

    Document Content Resolution:
        The port expects input tables with a 'path' column (primary) from local ingest
        operators. Document bytes are resolved from either:
        - 'path' column: File path to read bytes from (primary behavior)
        - 'binary_content' column: Pre-loaded bytes (backward compatibility fallback)

    Design Philosophy:
        Port = Orchestration + Parallel Processing
        Adapter = Specific Extraction Logic

    Attributes:
        ADAPTER_NAME: Short identifier for the adapter (e.g., "docling", "vlm")
        ADAPTER_DISPLAY_NAME: Human-readable adapter name (e.g., "Docling", "VLM")
        max_workers: Number of parallel workers for processing
        use_processes: Whether to use ProcessPoolExecutor (True) or ThreadPoolExecutor (False)
        doc_column: Column name for storing extracted document content
    """

    ADAPTER_NAME: str = "base"
    ADAPTER_DISPLAY_NAME: str = "Base Adapter"

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the text extraction port with configuration.

        Args:
            config: Configuration dictionary containing:
                - max_workers: Number of parallel workers (default: 4)
                - use_processes: Use processes vs threads (default: False)
                - doc_column: Column name for extracted content (default: "doc_content")
                - additional_formats: List of additional output formats (default: [])
                  Options: 'html', 'json', 'text', 'doctags', 'doclang'
                - ingest_source: Ingest source configuration for on-demand binary fetching (optional)
                - job_run_id: Job run identifier for progress tracking (optional)
                - node_id: Node identifier for progress tracking (optional)
                - node_name: Node name for progress tracking (optional)
                - batch_id: Batch identifier for progress tracking (optional)
                - Additional adapter-specific configuration
        """
        self.max_workers = config.get("max_workers", 4)
        self.use_processes = config.get("use_processes", False)
        self.doc_column = config.get("doc_column", OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
        self.common_log_arguments = config.get("common_log_arguments", {})
        self.additional_formats = config.get(OperatorConstants.Extraction.ADDITIONAL_FORMATS, [])

        # Store full config for on-demand binary fetching (includes ingest_source if present)
        self.global_config = config

        # Job tracking context for progress updates
        self.job_run_id = config.get(DocpipeConstants.JOB_RUN_ID)
        self.node_id = config.get(DocpipeConstants.NODE_ID)
        self.node_name = config.get(DocpipeConstants.NODE_NAME)
        self.batch_id = config.get(DocpipeConstants.BATCH_ID)

        # Decrypts password-protected documents after fetch; set by the owning operator.
        # Kept out of ``global_config`` so passwords never reach content fetchers.
        self.document_decryptor: DocumentDecryptor | None = None

        logger.info(
            "Initialized %s with job_run_id=%s, node_id=%s, batch_id=%s",
            self.__class__.__name__,
            self.job_run_id,
            self.node_id,
            self.batch_id,
            extra=self.common_log_arguments,
        )

        # Subclasses should initialize their adapter-specific configuration
        self._init_adapter_config(config=config)

    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize adapter-specific configuration.

        Subclasses should override this method to set up their specific configuration
        parameters (e.g., VLM settings, Docling Serve URL, template configuration).

        Args:
            config: Full configuration dictionary
        """
        # Default implementation does nothing - subclasses override as needed

    @staticmethod
    @abstractmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        ...

    def _update_extraction_progress(
        self, *, completed: int, total: int, progress_percentage: float, failed_count: int
    ) -> None:
        """Update node stats with text extraction stage progress.

        Reports stage-based progress metadata that the batch aggregator uses to
        display per-stage extraction progress (Text Extracted, Entities Extracted).

        Args:
            completed: Number of documents successfully extracted
            total: Total number of documents being extracted
            progress_percentage: Percentage of extraction completion
            failed_count: Number of failed extractions
        """
        try:
            # Only update if we have job tracking context
            if not self.job_run_id or not self.node_id:
                return

            from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory

            factory = get_default_factory()
            job_tracker = factory.create_job_stats_service()

            # Determine stage status
            stage_status = (
                OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
                if completed >= total
                else OperatorConstants.Extraction.STAGE_STATUS_RUNNING
            )

            # Build stage-based progress metadata
            progress_metadata: dict[str, Any] = {
                OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS: {
                    OperatorConstants.Extraction.STAGE_TEXT_EXTRACTION: {
                        OperatorConstants.Extraction.STAGE_STATUS: stage_status,
                        OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: total,
                        OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: completed,
                        OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: failed_count,
                        OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE: round(progress_percentage, 2),
                    }
                }
            }

            # Wrap in proper NodeMetadataItem structure
            metadata_item: NodeMetadataItem = NodeMetadataItem(
                id=self.node_id,
                operator=self.node_name or "ExtractOperator",
                node_metadata=progress_metadata,
            )

            # Create node_stats dict with proper structure
            node_stats = {OperatorConstants.Metadata.NODE_METADATA: metadata_item.model_dump()}

            # Update node stats through job tracker
            job_tracker.update_node_stats(
                job_run_id=self.job_run_id, node_id=self.node_id, node_stats=node_stats, batch_id=self.batch_id
            )

            logger.info(
                "Updated text extraction progress: %s/%s files (%.1f%%)",
                completed,
                total,
                progress_percentage,
                extra=self.common_log_arguments,
            )
        except Exception as e:
            # Don't fail extraction if progress update fails
            logger.warning("Failed to update extraction progress: %s", e, extra=self.common_log_arguments)

    def transform(self, *, table: pa.Table, metadata: dict[str, Any]) -> tuple[list[pa.Table], dict[str, Any]]:
        """Orchestrate parallel extraction across documents.

        This method implements the parallel processing pattern:
        1. Validate input and check for existing features
        2. Prepare document tasks from PyArrow table
        3. Create executor (ProcessPoolExecutor or ThreadPoolExecutor)
        4. Submit tasks to workers via _submit_extraction_task
        5. Collect results using as_completed pattern
        6. Aggregate results and handle errors
        7. Add extracted content to table and generate document IDs
        8. Return transformed table with metadata

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - path: Document path (optional)
                - binary_content: Binary content of the document (optional)
            metadata: Optional metadata dictionary to update

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)
        """
        # Check if extraction features already exist
        if self._check_existing_features(table=table):
            metadata[OperatorConstants.Extraction.MESSAGE] = (
                f"{self.doc_column} already present. Moving to next operation"
            )
            return [table], metadata

        # Prepare document tasks with on-demand binary fetching support
        doc_tasks: list[dict[str, Any]] = OperatorUtils.prepare_document_content_fetch(
            table=table, global_config=self.global_config
        )
        if self.document_decryptor is not None:
            self.document_decryptor.decrypt_tasks(tasks=doc_tasks, table=table)
        doc_contents: list[str] = [""] * table.num_rows
        doc_metadata_list: list[dict[str, Any]] = [{}] * table.num_rows

        # Initialize format lists only for requested additional formats
        format_lists: dict[str, list[str | None]] = {}
        for fmt in self.additional_formats:
            if fmt in OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING:
                format_lists[fmt] = [None] * table.num_rows

        doc_pages_processed: list[int] = [0] * table.num_rows
        remove_row_idx: list[int] = []
        non_recoverable_doc_ids: list[int] = []  # Track non-recoverable failed document indices

        completed_count, _failed_count = self._run_parallel_extraction(
            doc_tasks=doc_tasks,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            non_recoverable_doc_ids=non_recoverable_doc_ids,
            metadata=metadata,
        )

        # Save original table before removing rows (needed for non-recoverable error processing)
        original_table = table
        table = self._apply_extracted_content(
            table=table,
            doc_contents=doc_contents,
            doc_pages_processed=doc_pages_processed,
            format_lists=format_lists,
            remove_row_idx=remove_row_idx,
            completed_count=completed_count,
            total_files=len(doc_tasks),
            metadata=metadata,
        )

        # Process non-recoverable errors before returning
        # This populates metadata[NON_RECOVERABLE_DOCS_TABLE] for the orchestrator to save
        # Use original_table (before row removal) since non_recoverable_doc_ids contains original indices
        metadata = process_non_recoverable_errors(
            table=original_table,
            non_recoverable_doc_ids=non_recoverable_doc_ids,
            metadata=metadata,
            common_log_arguments=self.common_log_arguments,
        )

        # Set final status
        metadata[Metrics.External.NODE_STATUS] = (
            ExecutionStatus.COMPLETED_WITH_ERRORS.value
            if metadata[Metrics.External.FAILED_DOCS_COUNT] > 0
            else ExecutionStatus.COMPLETED.value
        )

        return [table], metadata

    def _run_parallel_extraction(
        self,
        *,
        doc_tasks: list[dict[str, Any]],
        doc_contents: list[str],
        doc_metadata_list: list[dict[str, Any]],
        format_lists: dict[str, list[str | None]],
        doc_pages_processed: list[int],
        remove_row_idx: list[int],
        non_recoverable_doc_ids: list[int],
        metadata: dict[str, Any],
    ) -> tuple[int, int]:
        """Submit all extraction tasks to a thread/process pool and collect results.

        Returns (completed_count, failed_count).
        """
        total_files = len(doc_tasks)
        completed_count = 0
        failed_count = 0
        last_update_time = 0.0
        update_interval = 5  # seconds between progress updates

        executor_class = ProcessPoolExecutor if self.use_processes else ThreadPoolExecutor

        logger.info(
            "Processing %s documents in parallel with %s workers using %s",
            total_files,
            self.max_workers,
            self.ADAPTER_DISPLAY_NAME,
        )

        with executor_class(max_workers=self.max_workers) as executor:
            future_to_task: dict[Future, dict[str, Any]] = {}

            # Submit all tasks
            for task in doc_tasks:
                if "error" in task:
                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=task["error"],
                    )
                    failed_count += 1
                    continue
                # A document that could not be decrypted is reported through the normal result handling
                future = DocumentDecryptor.failed_result_future(task=task)
                if future is None:
                    future = self._submit_extraction_task(executor=executor, task=task)
                future_to_task[future] = task

            # Collect results as they complete
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                idx = task["idx"]
                try:
                    result = future.result()
                    self._process_extraction_result(
                        result=result,
                        task=task,
                        idx=idx,
                        doc_contents=doc_contents,
                        doc_metadata_list=doc_metadata_list,
                        format_lists=format_lists,
                        doc_pages_processed=doc_pages_processed,
                        remove_row_idx=remove_row_idx,
                        non_recoverable_doc_ids=non_recoverable_doc_ids,
                        metadata=metadata,
                    )
                    if result.get(OperatorConstants.Extraction.SUCCESS):
                        completed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error("Error processing document at index %s: %s", idx, e)
                    AbstractOperator.record_failed_document(
                        metadata=metadata,
                        doc_id=str(task["doc_id"]),
                        doc_name=task["doc_name"],
                        reason=str(e),
                    )
                    failed_count += 1

                # Update progress periodically (every update_interval seconds)
                current_time = time.time()
                done_so_far = completed_count + failed_count
                if (current_time - last_update_time) >= update_interval and done_so_far < total_files:
                    progress_percentage = (done_so_far / total_files) * 100
                    self._update_extraction_progress(
                        completed=completed_count,
                        total=total_files,
                        progress_percentage=progress_percentage,
                        failed_count=failed_count,
                    )
                    last_update_time = current_time
                    logger.info(
                        "Extraction progress: %s/%s files (%.1f%%)",
                        done_so_far,
                        total_files,
                        progress_percentage,
                        extra=self.common_log_arguments,
                    )

            # Final progress update to reach terminal state
            if total_files > 0:
                progress_percentage = ((completed_count + failed_count) / total_files) * 100
                self._update_extraction_progress(
                    completed=completed_count,
                    total=total_files,
                    progress_percentage=progress_percentage,
                    failed_count=failed_count,
                )
                logger.info(
                    "Final extraction progress: %s/%s files (%.1f%%)",
                    completed_count + failed_count,
                    total_files,
                    progress_percentage,
                    extra=self.common_log_arguments,
                )

        return completed_count, failed_count

    def _apply_extracted_content(
        self,
        *,
        table: pa.Table,
        doc_contents: list[str],
        doc_pages_processed: list[int],
        format_lists: dict[str, list[str | None]],
        remove_row_idx: list[int],
        completed_count: int,
        total_files: int,
        metadata: dict[str, Any],
    ) -> pa.Table:
        """Remove failed rows, attach extracted content columns, and hash document IDs.

        Raises ValueError if no documents were successfully extracted.
        """
        if remove_row_idx:
            table = OperatorUtils.remove_rows(table=table, remove_row_idx=remove_row_idx)
            doc_contents[:] = [c for i, c in enumerate(doc_contents) if i not in remove_row_idx]
            # Remove rows from format lists
            for fmt in format_lists:
                format_lists[fmt] = [c for i, c in enumerate(format_lists[fmt]) if i not in remove_row_idx]
            doc_pages_processed[:] = [p for i, p in enumerate(doc_pages_processed) if i not in remove_row_idx]

        if completed_count == 0:
            # All extractions failed - stop pipeline.
            suffix = format_failed_docs_summary(failed_docs=metadata.get(Metrics.External.FAILED_DOCS, []))
            error_msg = (
                f"All {total_files} document(s) failed extraction. "
                f"No content was extracted. Cannot continue pipeline with empty content.{suffix}"
            )
            logger.error(error_msg, extra=self.common_log_arguments)
            raise ValueError(error_msg)

        # Add extracted content to table
        if doc_contents:
            table = TransformUtils.add_column(table=table, name=self.doc_column, content=doc_contents)

        # Add additional format columns dynamically based on requested formats
        for fmt, content_list in format_lists.items():
            if fmt in OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING:
                column_name = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING[fmt]
                # Only add column if it contains at least one non-None value
                if any(content is not None for content in content_list):
                    table = TransformUtils.add_column(table=table, name=column_name, content=content_list)

        # Add pages_processed column
        if doc_pages_processed:
            table = TransformUtils.add_column(
                table=table, name=OperatorConstants.Columns.PAGES_PROCESSED, content=doc_pages_processed
            )

        # Generate document hash IDs
        logger.info("Generating hash id and adding it to table")
        hash_operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: self.doc_column})
        table_list, _ = hash_operator.transform(table)
        return table_list[0]

    def _submit_extraction_task(
        self, executor: ProcessPoolExecutor | ThreadPoolExecutor, task: dict[str, Any]
    ) -> Future:
        """Submit extraction task to executor.

        Document bytes in the task are resolved from either the 'path' column
        (primary behavior) or 'binary_content' column (backward compatibility)
        by the prepare_document_content_fetch() utility method.

        Args:
            executor: ProcessPoolExecutor or ThreadPoolExecutor instance
            task: Document task dictionary containing:
                - idx: Task index
                - doc_id: Document ID
                - doc_name: Document name/path
                - binary_content: Binary document content (resolved from path or binary_content column)

        Returns:
            Future object for result retrieval
        """
        # Submit task to executor
        return executor.submit(
            self.extract_single_document, file_path=task["doc_name"], binary_content=task["binary_content"]
        )

    @abstractmethod
    def extract_single_document(self, *, file_path: str, binary_content: bytes, **kwargs: Any) -> dict[str, Any]:
        """Extract content from a single document.

        This is the adapter-specific extraction logic that runs in parallel workers.
        Each adapter implements its own extraction mechanics here.

        Args:
            file_path: Path to the document (used for logging and file type detection)
            binary_content: Binary content of the document
            **kwargs: Adapter-specific parameters (e.g., vlm_config)

        Returns:
            Dictionary with extraction results:
            {
                "success": bool,                    # Extraction success indicator
                "doc_content": str,                 # Extracted text content (markdown)
                "metadata": dict,                   # Additional metadata (page_count, etc.)
                "error": str                        # Error message if failed
            }
        """
        ...

    def _process_extraction_result(
        self,
        *,
        result: dict[str, Any],
        task: dict[str, Any],
        idx: int,
        doc_contents: list[str],
        doc_metadata_list: list[dict[str, Any]],
        format_lists: dict[str, list[str | None]],
        doc_pages_processed: list[int],
        remove_row_idx: list[int],
        non_recoverable_doc_ids: list[int],
        metadata: dict[str, Any],
    ) -> None:
        """Process extraction result and update data structures.

        Handles both successful and failed extraction results by updating the
        appropriate lists and metadata in place.

        Args:
            result: Extraction result dictionary from extract_single_document
            task: Document task dictionary containing doc_id and doc_name
            idx: Index in the result lists
            doc_contents: List to store extracted document contents
            doc_metadata_list: List to store document metadata
            format_lists: Dictionary mapping format names to their content lists
            doc_pages_processed: List to store page counts
            remove_row_idx: List of row indices to remove
            non_recoverable_doc_ids: List to track indices of documents with non-recoverable errors
            metadata: Metadata dictionary to update with processing stats
        """
        if result[OperatorConstants.Extraction.SUCCESS]:
            extracted_content = result.get(OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
            doc_contents[idx] = extracted_content if extracted_content else ""
            doc_metadata_list[idx] = result.get(OperatorConstants.Metadata.METADATA, {})

            # Extract additional format columns if present in result and requested
            for fmt, content_list in format_lists.items():
                column_name = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING.get(fmt)
                if column_name and column_name in result:
                    content_list[idx] = result[column_name]

            # Calculate page count: use native page_count from metadata if available, else fallback to character-based
            extraction_metadata = result.get(OperatorConstants.Metadata.METADATA, {})
            native_page_count = extraction_metadata.get("page_count")

            if native_page_count and isinstance(native_page_count, (int, float)) and native_page_count > 0:
                # Use native page count from Docling metadata
                page_count = int(native_page_count)
            else:
                # Fallback to character-based calculation
                char_count = len(extracted_content) if extracted_content else 0
                chars_per_page = OperatorConstants.Processing.CHARS_PER_PAGE
                page_count = max(1, (char_count + chars_per_page - 1) // chars_per_page)

            doc_pages_processed[idx] = page_count

            # Increment processed count
            metadata[Metrics.External.PROCESSED_DOCS] += 1
            return

        # Handle extraction failure
        error_message = result.get(OperatorConstants.Extraction.ERROR, "Unknown error")

        # Check if error is non-recoverable (password-protected, corrupted, etc.)
        if is_non_recoverable_error(
            error_message, failure_reason=result.get(OperatorConstants.Extraction.FAILURE_REASON)
        ):
            non_recoverable_doc_ids.append(idx)
            # Enhance error message to indicate document won't be reprocessed
            error_message = f"{error_message}. This document will not be processed in future flow executions unless the document is modified."
            logger.warning(
                "Non-recoverable error detected for document %s: %s",
                task["doc_name"],
                error_message,
                extra=self.common_log_arguments,
            )

        AbstractOperator.record_failed_document(
            metadata=metadata,
            doc_id=str(task["doc_id"]),
            doc_name=task["doc_name"],
            reason=error_message,
        )
        logger.error("Failed to extract content from %s: %s", task["doc_name"], error_message)
        remove_row_idx.append(idx)

    def _check_existing_features(self, *, table: pa.Table) -> bool:
        """Check if requested extraction features already exist in the table.

        Args:
            table: PyArrow table to check

        Returns:
            True if all requested features exist, False otherwise
        """
        return self.doc_column in table.column_names
