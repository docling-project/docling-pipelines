"""Entity extraction service for orchestrating parallel document processing.

This service contains the orchestration logic for entity extraction operations,
managing parallel processing, task submission, result collection, and progress tracking.
It delegates the actual extraction work to EntityExtractionPort adapters.
"""

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

import pyarrow as pa

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.extract.ports.outbound.entity_extraction import EntityExtractionPort
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.document_class_utils import DocumentClassUtils
from docpipe.utils.infrastructure.concurrency import submit_task_with_context_propagation
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


class EntityExtractionService:
    """Service for orchestrating parallel entity extraction across documents.

    This service manages the complete entity extraction workflow:
    - Parallel processing framework (executor management)
    - Worker task submission and result fetching
    - Result aggregation and error handling
    - Progress tracking and metadata collection
    - Schema loading and validation
    - Table transformation and finalization

    The service depends on an EntityExtractionPort adapter for the actual
    extraction logic, following the adapter pattern.

    Attributes:
        adapter: EntityExtractionPort implementation for extraction
        max_workers: Number of parallel workers for processing
        doc_column: Column name containing document text
        output_column: Column name for storing extracted entities
        expand_extracted_data: Whether to expand entities into individual columns
        doc_id_hash_column: Column name for document hash IDs
        custom_schema: Custom schema for entity extraction
        job_run_id: Job run identifier for progress tracking
        node_id: Node identifier for progress tracking
        node_name: Node name for progress tracking
        batch_id: Batch identifier for progress tracking
    """

    def __init__(
        self,
        *,
        adapter: EntityExtractionPort,
        config: dict[str, Any],
        max_workers: int = 4,
        job_run_id: str | None = None,
        node_id: str | None = None,
        node_name: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        """Initialize the entity extraction service.

        Args:
            adapter: EntityExtractionPort implementation for extraction
            config: Configuration dictionary containing extraction parameters
            max_workers: Number of parallel workers (default: 4)
            job_run_id: Job run identifier for progress tracking (optional)
            node_id: Node identifier for progress tracking (optional)
            node_name: Node name for progress tracking (optional)
            batch_id: Batch identifier for progress tracking (optional)
        """
        self.adapter = adapter
        self.max_workers = max_workers
        self.doc_column = config.get(OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
        self.output_column = config.get(OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Misc.ENTITIES)
        self.expand_extracted_data = config.get(OperatorConstants.Config.EXPAND_EXTRACTED_DATA, False)
        self.doc_id_hash_column = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )
        self.custom_schema = config.get(OperatorConstants.Config.CUSTOM_SCHEMA, {})
        self.common_log_arguments = config.get("common_log_arguments", {})

        # Job tracking context for progress updates
        self.job_run_id = job_run_id
        self.node_id = node_id
        self.node_name = node_name
        self.batch_id = batch_id

        # Thread safety lock for metadata updates
        self._metadata_lock = threading.Lock()

        logger.info(
            "Initialized EntityExtractionService with job_run_id=%s, node_id=%s, batch_id=%s",
            self.job_run_id,
            self.node_id,
            self.batch_id,
            extra=self.common_log_arguments,
        )

    def transform(self, *, table: pa.Table, metadata: dict[str, Any]) -> tuple[list[pa.Table], dict[str, Any]]:
        """Orchestrate parallel entity extraction across documents.

        This method implements the parallel processing pattern:
        1. Validate input and prepare document tasks
        2. Load schemas/templates if using schema-based extraction
        3. Create ThreadPoolExecutor for parallel processing
        4. Submit tasks to workers via _submit_extraction_task
        5. Collect results using as_completed pattern
        6. Aggregate results and handle errors
        7. Add extracted entities to table
        8. Optionally expand entities into individual columns
        9. Generate document hash IDs
        10. Return transformed table with metadata

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - doc_content: Document text content
                - document_type: Document type for schema selection (optional)
            metadata: Optional metadata dictionary to update.

                Metadata is mutated in-place during processing. Callers must treat
                the provided dictionary as owned by this transform invocation for
                the duration of processing and must not read or write it
                concurrently from other threads.

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)
        """
        # Prepare schemas and document tasks
        document_types, schema_templates = self.prepare_schemas(table=table)
        doc_tasks = self._prepare_document_tasks(table, document_types, metadata)
        entities_list: list[dict[str, Any]] = [{} for _ in range(table.num_rows)]

        logger.info(
            "Processing %s documents in parallel with %s workers using %s",
            len(doc_tasks),
            self.max_workers,
            self.adapter.ADAPTER_DISPLAY_NAME,
        )

        # Process documents in parallel and collect results
        self._process_documents_parallel(doc_tasks, schema_templates, entities_list, metadata)

        # Add entities to table and finalize
        table = self._finalize_table(table=table, entities_list=entities_list, metadata=metadata)
        metadata = self._set_execution_status(metadata=metadata)

        return [table], metadata

    def prepare_schemas(self, *, table: pa.Table) -> tuple[list[str], dict[str, dict]]:
        """Prepare document types and load schema templates.

        Args:
            table: PyArrow table containing document data

        Returns:
            Tuple of (document_types list, schema_templates dict)

        Raises:
            ConfigurationError: If entity extraction is enabled without custom_schema or document_type column
        """
        from docpipe.exceptions.docpipe_exceptions import ConfigurationError

        document_types: list[str] = []
        schema_templates: dict[str, dict] = {}

        # Check if document_type column exists
        has_document_type_column = OperatorConstants.Columns.DOCUMENT_TYPE in table.column_names

        # Validate that entity extraction has either custom_schema or document_type column
        has_custom_schema = self.custom_schema and len(self.custom_schema) > 0
        if not has_custom_schema and not has_document_type_column:
            raise ConfigurationError(
                "Entity extraction requires either a custom_schema in operator config OR a document_type column from upstream classification operator"
            )

        if has_document_type_column:
            document_types = table.column(OperatorConstants.Columns.DOCUMENT_TYPE).to_pylist()
            self._load_schema_templates(document_types=document_types, schema_templates=schema_templates)
            self.validate_loaded_schemas(document_types=document_types, schema_templates=schema_templates)

        return document_types, schema_templates

    def _prepare_document_tasks(
        self, table: pa.Table, document_types: list[str], metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Prepare document tasks for parallel processing.

        This method iterates through the table rows and creates a list of task
        dictionaries containing document information needed for entity extraction.
        Documents with empty content are skipped and recorded in metadata.

        Args:
            table: PyArrow table containing document data
            document_types: List of document types corresponding to table rows
            metadata: Metadata dictionary for recording skipped documents

        Returns:
            List of task dictionaries, each containing:
                - idx: Row index in the table
                - doc_id: Document identifier
                - doc_name: Document name
                - content: Document content from self.doc_column
                - document_type: Document type (if available)
        """
        doc_tasks: list[dict[str, Any]] = []

        for row_idx in range(table.num_rows):
            row = {col: table.column(col)[row_idx].as_py() for col in table.column_names}
            doc_id_value = row.get(OperatorConstants.Columns.ID)
            if doc_id_value is None:
                doc_id_value = row.get(OperatorConstants.Columns.PATH, f"doc_{row_idx}")
            doc_id = str(doc_id_value)
            doc_name = str(row.get(OperatorConstants.Columns.NAME, f"doc_{row_idx}"))
            content = row.get(self.doc_column) or ""

            if not content:
                AbstractOperator.record_skipped_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=f"Column '{self.doc_column}' is empty or missing.",
                )
                continue

            doc_tasks.append(
                {
                    "idx": row_idx,
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "content": content,
                    "document_type": document_types[row_idx] if document_types else None,
                }
            )

        return doc_tasks

    def _process_documents_parallel(
        self,
        doc_tasks: list[dict[str, Any]],
        schema_templates: dict[str, dict],
        entities_list: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        """Process documents in parallel using ThreadPoolExecutor.

        Args:
            doc_tasks: List of document task dictionaries
            schema_templates: Cache of loaded schemas by document type
            entities_list: List to populate with extracted entities
            metadata: Metadata dictionary for tracking results
        """
        # Progress tracking variables
        completed_count = 0
        failed_count = 0
        total_documents = len(doc_tasks)
        last_update_time = 0.0
        update_interval = 5  # Update progress every 5 seconds

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task: dict[Future, dict[str, Any]] = {}

            # Submit all tasks
            for task in doc_tasks:
                future = self._submit_extraction_task(executor=executor, task=task, schema_templates=schema_templates)
                future_to_task[future] = task

            # Collect results as they complete
            for future in as_completed(future_to_task):
                task = future_to_task[future]

                # Track result before handling
                try:
                    result = future.result()
                    if result.get(OperatorConstants.Extraction.SUCCESS):
                        completed_count += 1
                    else:
                        failed_count += 1
                except Exception:
                    failed_count += 1

                # Handle the extraction result
                self._handle_extraction_result(future, task, entities_list, metadata)

                # Update progress periodically (every update_interval seconds)
                current_time = time.time()
                if (current_time - last_update_time) >= update_interval and (
                    completed_count + failed_count
                ) < total_documents:
                    progress_percentage = ((completed_count + failed_count) / total_documents) * 100
                    self._update_extraction_progress(
                        completed=completed_count,
                        total=total_documents,
                        progress_percentage=progress_percentage,
                        failed_count=failed_count,
                    )
                    last_update_time = current_time
                    logger.info(
                        "Entity extraction progress: %s/%s documents (%.1f%%)",
                        completed_count + failed_count,
                        total_documents,
                        progress_percentage,
                        extra=self.common_log_arguments,
                    )

            # Final progress update to reach terminal state
            if total_documents > 0:
                progress_percentage = ((completed_count + failed_count) / total_documents) * 100
                self._update_extraction_progress(
                    completed=completed_count,
                    total=total_documents,
                    progress_percentage=progress_percentage,
                    failed_count=failed_count,
                )
                logger.info(
                    "Final entity extraction progress: %s/%s documents (%.1f%%)",
                    completed_count + failed_count,
                    total_documents,
                    progress_percentage,
                    extra=self.common_log_arguments,
                )

    def _submit_extraction_task(
        self, executor: ThreadPoolExecutor, task: dict[str, Any], schema_templates: dict[str, dict]
    ) -> Future:
        """Submit extraction task to executor.

        This method determines the appropriate schema (if using schema-based extraction)
        and submits the task to the executor by calling the adapter's extract_entities_single
        method.

        Args:
            executor: ThreadPoolExecutor instance
            task: Document task dictionary containing:
                - idx: Task index
                - doc_id: Document ID
                - doc_name: Document name
                - content: Document text content
                - document_type: Document type for schema selection
            schema_templates: Cache of loaded schemas by document type

        Returns:
            Future object for result retrieval
        """
        # Determine schema if using schema-based extraction
        schema_to_use = self.custom_schema
        if schema_templates:
            doc_type = task.get("document_type")
            if doc_type and doc_type in schema_templates:
                schema_to_use = schema_templates[doc_type]
                logger.debug("Using schema for document type '%s' for %s", doc_type, task["doc_name"])
        content = task.get("content", task.get("binary_content", b""))
        return submit_task_with_context_propagation(
            executor,
            self.adapter.extract_entities_single,
            doc_id=task["doc_id"],
            doc_name=task["doc_name"],
            content=content,
            schema=schema_to_use,
        )

    def _handle_extraction_result(
        self,
        future: Future,
        task: dict[str, Any],
        entities_list: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        """Handle the result of a single extraction task.

        Args:
            future: Future object containing extraction result
            task: Task dictionary with document information
            entities_list: List to populate with extracted entities
            metadata: Metadata dictionary for tracking results
        """
        idx = task["idx"]

        try:
            result = future.result()

            if result[OperatorConstants.Extraction.SUCCESS]:
                # All shared data structure updates need thread safety
                with self._metadata_lock:
                    entities_list[idx] = result[OperatorConstants.Misc.ENTITIES]
                    metadata[Metrics.External.PROCESSED_DOCS] += 1
                logger.debug("Extracted entities for document %s:\n %s", task["doc_name"], entities_list[idx])
                return

            # Handle extraction failure
            self._record_extraction_failure(task=task, error=result.get("error", "Unknown error"), metadata=metadata)

        except Exception as e:
            logger.error("Error processing document at index %s: %s", idx, e)
            self._record_extraction_failure(task=task, error=str(e), metadata=metadata)

    def _finalize_table(
        self,
        *,
        table: pa.Table,
        entities_list: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> pa.Table:
        """Add entities column and hash IDs to table.

        Args:
            table: PyArrow table to finalize
            entities_list: List of extracted entities
            metadata: Metadata dictionary containing processing stats

        Returns:
            Finalized PyArrow table with entities and hash columns
        """
        # Check if any documents were successfully processed using metadata
        processed_count = metadata.get(Metrics.External.PROCESSED_DOCS, 0)

        if processed_count > 0:
            # Optionally expand entities into individual columns
            if self.expand_extracted_data and entities_list:
                table = self.expand_entities_columns(table=table, entities_list=entities_list)

            # Add entities column - convert to JSON strings for PyArrow compatibility
            entities_json_list: list[str] = [json.dumps(entity) if entity else "{}" for entity in entities_list]
            table = TransformUtils.add_column(table=table, name=self.output_column, content=entities_json_list)

            # Ensure doc_id_hash column exists
            if self.doc_id_hash_column not in table.column_names:
                logger.info("Generating hash id and adding it to table")
                hash_operator = DocIdHashOperator(
                    {
                        OperatorConstants.Columns.DOC_COLUMN: self.doc_column,
                        OperatorConstants.Columns.DOC_ID_HASH: self.doc_id_hash_column,
                    }
                )
                table_list, _ = hash_operator.transform(table)
                table = table_list[0]
        else:
            logger.warning(
                "No successful entity extractions - entities column not added. All documents failed extraction.",
                extra=self.common_log_arguments,
            )

        return table

    def _set_execution_status(self, *, metadata: dict[str, Any]) -> dict[str, Any]:
        """Determine and set the final execution status in metadata.

        Args:
            metadata: Metadata dictionary to update

        Returns:
            Updated metadata dictionary
        """
        execution_status = ExecutionStatus.COMPLETED.value

        # Check failed docs first (higher priority)
        if metadata[Metrics.External.FAILED_DOCS_COUNT] > 0:
            execution_status = ExecutionStatus.COMPLETED_WITH_ERRORS.value
        elif metadata[Metrics.External.SKIPPED_DOCS_COUNT] > 0:
            execution_status = ExecutionStatus.COMPLETED_WITH_WARNINGS.value

        metadata[Metrics.External.NODE_STATUS] = execution_status
        return metadata

    def _update_extraction_progress(
        self, *, completed: int, total: int, progress_percentage: float, failed_count: int
    ) -> None:
        """Update node stats with entity extraction stage progress.

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
            from docpipe.core.job_management.domain.models.node_stats import NodeMetadataItem

            factory = get_default_factory()
            job_tracker = factory.create_job_stats_service()

            # Determine stage status
            stage_status = (
                OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
                if completed >= total
                else OperatorConstants.Extraction.STAGE_STATUS_RUNNING
            )

            # Get job stats store to read existing metadata
            factory_for_store = get_default_factory()
            job_stats_store = factory_for_store.create_job_stats_store()

            # Read existing node stats to preserve text extraction progress
            existing_stage_progress = {}
            try:
                existing_node = job_stats_store.get_node_stats_by_batch_and_node(
                    job_run_id=self.job_run_id, node_id=self.node_id, batch_id=self.batch_id
                )

                # Extract existing extraction_stage_progress
                if existing_node and existing_node.node_metadata:
                    node_metadata_dict = existing_node.node_metadata
                    if isinstance(node_metadata_dict, dict):
                        inner_metadata = node_metadata_dict.get(OperatorConstants.Metadata.NODE_METADATA, {})
                        if isinstance(inner_metadata, dict):
                            existing_stage_progress = inner_metadata.get(
                                OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS, {}
                            )
                            if existing_stage_progress:
                                logger.debug(
                                    "Found existing stage progress with %d stages",
                                    len(existing_stage_progress),
                                    extra=self.common_log_arguments,
                                )
            except Exception as e:
                logger.error(
                    "Could not read existing node stats, starting fresh: %s",
                    e,
                    extra=self.common_log_arguments,
                )

            # Merge entity stage with existing text stage
            merged_stage_progress = dict(existing_stage_progress) if isinstance(existing_stage_progress, dict) else {}
            merged_stage_progress[OperatorConstants.Extraction.STAGE_ENTITY_EXTRACTION] = {
                OperatorConstants.Extraction.STAGE_STATUS: stage_status,
                OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: total,
                OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: completed,
                OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: failed_count,
                OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE: round(progress_percentage, 2),
            }

            # Build complete progress metadata with both stages
            progress_metadata: dict[str, Any] = {
                OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS: merged_stage_progress
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
                "Updated entity extraction progress: %s/%s documents (%.1f%%), stages: %s",
                completed,
                total,
                progress_percentage,
                list(merged_stage_progress.keys()),
                extra=self.common_log_arguments,
            )
        except Exception as e:
            # Don't fail extraction if progress update fails
            logger.warning("Failed to update extraction progress: %s", e, extra=self.common_log_arguments)

    def _record_extraction_failure(self, *, task: dict[str, Any], error: str, metadata: dict[str, Any]) -> None:
        """Record a failed extraction in metadata.

        Args:
            task: Task dictionary with document information
            error: Error message describing the failure
            metadata: Metadata dictionary for tracking results
        """
        with self._metadata_lock:
            AbstractOperator.record_failed_document(
                metadata=metadata, doc_id=task["doc_id"], doc_name=task["doc_name"], reason=error
            )
        logger.error("Failed to extract entities from %s: %s", task["doc_name"], error)

    def _load_schema_templates(self, *, document_types: list[str], schema_templates: dict[str, dict]) -> None:
        """Load schema templates for given document types.

        Args:
            document_types: List of document types to load schemas for
            schema_templates: Dictionary to populate with loaded schemas
        """
        loaded_schemas = DocumentClassUtils.get_schema_templates(document_types)
        schema_templates.update(loaded_schemas)

    def validate_loaded_schemas(self, *, document_types: list[str], schema_templates: dict[str, dict]) -> None:
        """Validate which schemas were successfully loaded.

        Args:
            document_types: List of document types to load schemas for
            schema_templates: Dictionary to populate with loaded schemas
        """
        unique_doc_types = {dt for dt in document_types if dt}
        missing_schemas = unique_doc_types - set(schema_templates.keys())
        if missing_schemas:
            logger.warning(
                "Could not load schemas for document types: %s. These documents will use the default schema instead.",
                missing_schemas,
            )
        if schema_templates:
            logger.info("Successfully loaded schemas for: %s", list(schema_templates.keys()))

    def expand_entities_columns(self, *, table: pa.Table, entities_list: list[dict[str, Any]]) -> pa.Table:
        """Expand entity dict into individual columns, one per entity key.

        Args:
            table: PyArrow table to add columns to
            entities_list: List of entity dictionaries

        Returns:
            PyArrow table with expanded entity columns
        """
        # Collect all unique keys
        all_keys: set[str] = set()
        for entity in entities_list:
            if entity and isinstance(entity, dict):
                all_keys.update(entity.keys())

        if not all_keys:
            return table

        logger.info("Expanding entities into %s columns: %s", len(all_keys), sorted(all_keys))

        # Create one column per key
        for key in sorted(all_keys):
            column_values = [
                (entity[key] if (entity and isinstance(entity, dict) and key in entity) else None)
                for entity in entities_list
            ]
            # Convert values to strings for PyArrow compatibility
            column_values = [str(val) if val is not None else None for val in column_values]
            table = TransformUtils.add_column(table, name=f"entity_{key}", content=column_values)

        return table
