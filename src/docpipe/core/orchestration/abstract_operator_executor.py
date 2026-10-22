"""Abstract base class for operator executors in the docpipe orchestration layer."""

import copy
import pprint
from abc import abstractmethod
from queue import Queue
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from data_processing.data_access import DataAccess, DataAccessFactory

from docpipe.core.constants.constants import (
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.data_access.data_access_utils import DataAccessUtils
from docpipe.core.job_management.domain.ports import JobStatsService
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.deleted_rows_tracker import update_deleted_rows

logger = get_logger()


class AbstractOperatorExecutor:
    """Base class for operator executors.

    An executor wraps an AbstractOperator instance, wires up data access, and
    manages the execution lifecycle (pre/post transform hooks, stats recording)."""

    def __init__(
        self,
        *,
        name: str,
        operator: str,
        params: dict,
        job_stats_service: JobStatsService | None = None,
    ):
        """
        Initialize operator executor with explicit dependency injection.

        Args:
            name: The name of the step mentioned in the flow. Note that the name of the step is different from the operator name.
                  This is because the user can have multiple steps with the same operator but different name.
                  For example, we can have a flow with one regex operator for e-mail and another regex operator for ssn.
            operator: Identifies the operator to be executed
            params: dictionary of configuration information used while executing the operator
            job_stats_service: Optional job statistics service for tracking node execution
        """
        self._name = name
        self._operator = operator
        self._params = params | {OperatorConstants.Columns.NAME: name}
        self._job_stats_service = job_stats_service
        job_id: str = str(self._params.get(DocpipeConstants.JOB_ID))
        job_run_id: str = str(self._params.get(DocpipeConstants.JOB_RUN_ID))
        DataAccessUtils.add_intermediate_storage_config(
            config=self._params,
            job_id=job_id,
            job_run_id=job_run_id,
        )

    def execute(
        self,
        *,
        data_access: DataAccess | dict[str, DataAccess | None] | None,
        deleted_rows_list: Queue[pa.Table] | None,
    ) -> tuple[list[DataAccess], dict[str, Any]]:
        """Execute the operator and return data accesses and metadata.

        Args:
            data_access: Upstream data access or dict of data accesses.
            deleted_rows_list: Queue for accumulating deleted-row tables.

        Returns:
            Tuple of (list[DataAccess], metadata dict)."""
        input_tables = self._get_input_tables(data_access=data_access)
        out_tables, metadata = self._execute_impl(tables=input_tables)
        if deleted_rows_list is not None:
            deleted_rows = update_deleted_rows(
                prev_tables=input_tables,
                current_tables=out_tables,
                op=self.get_operator(),
                skip_columns=[
                    OperatorConstants.Columns.KVP_COLUMN,
                    OperatorConstants.Columns.DOC_COLUMN,
                ],
            )
            if deleted_rows.num_rows > 0:
                deleted_rows_list.put(deleted_rows)
        output_data_accesses = self.create_data_accesses(out_tables)

        return output_data_accesses, metadata

    def create_data_accesses(self, tables):
        """Create data access objects for the given output tables.

        Args:
            tables: List of PyArrow tables to wrap.

        Returns:
            List of DataAccess instances."""
        data_accesses = []
        for index, table in enumerate(tables):
            data_access_factory = DataAccessFactory()
            params_copy = self._safely_deep_copy_params(params=self._params)
            # Add node name + index of the branch to the output folder
            DataAccessUtils.add_node_name_to_output_folder(
                params=params_copy, node_name=f"{params_copy['name']}_{index}"
            )
            data_access_factory.apply_input_params(params_copy)
            output_data_access = data_access_factory.create_data_access()
            output_file_path = self.get_output_file_path(data_access=output_data_access)

            # Note: memmap path replacement is now handled by CustomDataAccessLocal.save_table()
            # The custom class caches tables with memmap paths (memory efficient)
            # but writes expanded data to parquet files (persistent and portable)
            output_data_access.save_table(output_file_path, table)
            data_accesses.append(output_data_access)
        return data_accesses

    @staticmethod
    def _safely_deep_copy_params(*, params: dict) -> dict:
        """Deep copy params, shallow-copying any value that cannot be pickled (e.g. thread locks, clients)."""
        import pickle  # nosec B403 — used only to test pickleability, never to deserialise untrusted data

        copied = {}
        for k, v in params.items():
            try:
                pickle.dumps(v)
                copied[k] = copy.deepcopy(v)
            except Exception:
                copied[k] = v  # shallow copy — keep original reference
        return copied

    def release(self) -> None:
        """Release resources held by this executor's operator.

        Default is a no-op.  Subclasses that construct and cache an operator
        override this to run the operator's ``cleanup()``.  Must never raise.
        """

    @abstractmethod
    def get_operator(self) -> AbstractOperator:
        # The concrete class implements the method by returning the operator for the corresponding orchestrator.
        """Return the operator instance managed by this executor.

        Returns:
            The AbstractOperator instance."""
        ...

    def validate(self, *, errors: list, warnings: list, available_features: list):
        """Validate."""
        op = self.get_operator()
        op.validate(errors=errors, warnings=warnings, available_features=available_features)

    def get_metadata(self):
        """
        The concrete subclasses give the given operator metadata identified by _operator by passing the given table
        """
        op = self.get_operator()
        return op.get_metadata()

    def _execute_impl(self, tables: pa.Table | dict[str, pa.Table] | None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        The concrete subclasses execute the given operator identified by _operator by passing the given tables
        """
        raise NotImplementedError("Subclasses must implement _execute_impl")

    def _get_input_tables(
        self,
        *,
        data_access: DataAccess | dict[str, DataAccess | None] | None,
    ) -> pa.Table | dict[str, pa.Table] | None:
        if data_access is None:
            tables = None
        elif isinstance(data_access, DataAccess):
            input_file_path = self.get_output_file_path(data_access=data_access)
            tables, _ = data_access.get_table(input_file_path)
        else:
            tables = {}
            for link_name, access in data_access.items():
                if access is None:
                    # Note: Merge operators should be ready to receive an empty list of tables, or a list with a single table.
                    continue
                input_file_path = self.get_output_file_path(data_access=access)
                table, _ = access.get_table(input_file_path)
                tables[link_name] = table
        return tables

    def set_default_node_stats(self, *, tables: pa.Table | dict[str, pa.Table] | None):
        """Initialize node statistics for the current node execution.

        Builds the initial node statistics inputs from the current node input
        tables and delegates persistence to the job stats service.

        Args:
            tables: Input tables for the current node. This may be a single
                PyArrow table, a dict of PyArrow tables keyed by input link
                name, or None for nodes without upstream input data.
        """
        node_id = self._params[OperatorConstants.Columns.ID]
        logger.info("Initializing stats for node '%s' (ID: %s).", self._name, node_id)

        # Use injected job stats service
        if not self._job_stats_service:
            logger.warning("Job stats service not available for node '%s'", node_id)
            return

        # Extract batch_id and batch_num from params if micro-batching is enabled
        batch_id = self._params.get(DocpipeConstants.BATCH_ID)
        batch_num = self._params.get(DocpipeConstants.BATCH_NUM)

        self._job_stats_service.start_node_execution(
            job_run_id=self._params[DocpipeConstants.JOB_RUN_ID],
            node_id=node_id,
            node_name=self._name,
            total_docs=OperatorUtils.get_unique_ids(tables=tables),
            batch_id=batch_id,
            batch_num=batch_num,
        )
        logger.info("Initial stats for node '%s' stored successfully.", node_id)

    def update_final_node_stats(self, *, tables: list[pa.Table], metadata: dict):
        """Finalize node statistics for the current node execution.

        Extracts completed, failed, skipped, schema, and status information
        from the node outputs and operator metadata, then delegates final node
        statistics assembly and persistence to the job stats service.

        Args:
            tables: Output PyArrow tables produced by the current node.
            metadata: Operator metadata for the current node execution,
                including node status and optional failed/skipped document
                details.
        """
        node_id = self._params[OperatorConstants.Columns.ID]
        job_run_id = self._params[DocpipeConstants.JOB_RUN_ID]
        logger.info("Updating final stats for node '%s'.", node_id)

        # Use injected job stats service
        if not self._job_stats_service:
            logger.warning("Job stats service not available for node '%s'", node_id)
            return

        # Remove 'non_recoverable_docs_table' from metadata before saving
        metadata_copy = copy.deepcopy(metadata)
        metadata_copy.pop(Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE, None)
        # Extract batch_id and batch_num from params if micro-batching is enabled
        batch_id = self._params.get(DocpipeConstants.BATCH_ID)
        batch_num = self._params.get(DocpipeConstants.BATCH_NUM)

        all_doc_ids = OperatorUtils.get_unique_ids(tables=tables) if tables else []
        failed_docs = [
            doc.get("id", "") for doc in metadata_copy.get(Metrics.External.FAILED_DOCS, []) if isinstance(doc, dict)
        ]
        skipped_docs = [
            doc.get("id", "") for doc in metadata_copy.get(Metrics.External.SKIPPED_DOCS, []) if isinstance(doc, dict)
        ]
        failed_and_skipped_set = set(failed_docs) | set(skipped_docs)
        docs_completed = [doc_id for doc_id in all_doc_ids if doc_id not in failed_and_skipped_set]
        col_names = tables[0].column_names if tables else []
        node_status = metadata_copy.get(Metrics.External.NODE_STATUS, ExecutionStatus.COMPLETED.value)

        logger.info(
            "Node '%s' stats summary: %s completed, %s failed, %s skipped.",
            node_id,
            len(docs_completed),
            len(failed_docs),
            len(skipped_docs),
        )

        if failed_docs or skipped_docs:
            logger.warning(
                "Node '%s' completed with issues: failed=%s, skipped=%s", node_id, len(failed_docs), len(skipped_docs)
            )

        self._job_stats_service.complete_node_execution(
            job_run_id=job_run_id,
            node_id=node_id,
            node_name=self._name,
            docs_completed=docs_completed,
            failed_docs=failed_docs,
            skipped_docs=skipped_docs,
            col_names=col_names,
            node_status=node_status,
            node_metadata=metadata_copy,
            batch_id=batch_id,
            batch_num=batch_num,
        )
        logger.info("Final stats for node '%s' stored successfully.", node_id)

    @staticmethod
    def get_output_file_path(*, data_access):
        """Return the output file path for a given data access.

        Args:
            data_access: The DataAccess instance.

        Returns:
            File path string."""
        output_folder = data_access.get_output_folder()
        if output_folder is None:
            return ""
        if not output_folder.endswith("/"):
            output_folder += "/"
        return output_folder + "output.parquet"

    def _log_start(self, *, op_logger, name, short_name, common_log_arguments):
        op_logger.info(
            "Starting execution: Step Name: %s, operator: %s",
            name,
            short_name,
            extra=common_log_arguments,
        )

    def _log_completion(self, *, op_logger, name, time_taken, result, metadata, common_log_arguments):
        # Schema and metadata moved to DEBUG - they're shown in formatted output
        if result[0] and result[0][0]:
            op_logger.debug("Schema:%s", str(result[0][0].schema), extra=common_log_arguments)
        op_logger.debug("Operator Metadata:\n%s", pprint.pformat(metadata, indent=2))
        op_logger.info(
            "Completed execution: %s, time= %.2f seconds",
            name,
            time_taken,
            extra=common_log_arguments,
        )

    def _process_table_for_empty_docs(self, *, table: pa.Table, doc_column: str, metadata: dict[str, Any]) -> pa.Table:
        """
        Process a single table to handle empty documents and zero-byte files.

        This method implements the OUTPUT validation layer that checks for:
        1. Empty content in doc_column (e.g., empty strings, None values)
        2. Zero-byte files in SIZE column (files with size = 0)

        Args:
            table: PyArrow table to process
            doc_column: Name of the document content column
            metadata: Metadata dictionary to update

        Returns:
            Processed PyArrow table with empty documents and zero-byte files removed
        """
        # Skip processing if table is empty
        if table.num_rows == 0:
            return table

        # Check if either doc_column or SIZE column exists
        has_doc_column = doc_column in table.column_names
        has_size_column = OperatorConstants.Misc.SIZE in table.column_names

        # If neither column exists, nothing to validate
        if not has_doc_column and not has_size_column:
            return table

        # Initialize empty mask
        is_empty_mask = None

        # Check for empty content in doc_column
        if has_doc_column:
            doc_col = table[doc_column]
            # Create mask for empty documents: null OR empty/whitespace-only strings
            is_null = pc.is_null(doc_col)  # type: ignore[attr-defined]
            doc_col_filled = pc.fill_null(doc_col, "")  # type: ignore[attr-defined]
            stripped = pc.utf8_trim_whitespace(doc_col_filled)  # type: ignore[attr-defined]
            is_empty_string = pc.equal(pc.utf8_length(stripped), 0)  # type: ignore[attr-defined]
            is_empty_mask = pc.or_(is_null, is_empty_string)  # type: ignore[attr-defined]

        # Check for zero-byte files in SIZE column
        if has_size_column:
            size_col = table[OperatorConstants.Misc.SIZE]
            # Create mask for zero-byte files
            is_zero_byte = pc.equal(size_col, 0)  # type: ignore[attr-defined]

            # Combine masks: empty content OR zero-byte file
            if is_empty_mask is not None:
                is_empty_mask = pc.or_(is_empty_mask, is_zero_byte)  # type: ignore[attr-defined]
            else:
                is_empty_mask = is_zero_byte

        # If no mask was created (shouldn't happen due to earlier check), return table
        if is_empty_mask is None:
            return table

        # Get indices of empty documents for metadata tracking
        empty_doc_indices = pc.indices_nonzero(is_empty_mask).to_pylist()  # type: ignore[attr-defined]

        # If no empty documents or zero-byte files, return table as is
        if not empty_doc_indices:
            return table

        # Save empty documents to incremental metadata
        self._save_empty_docs_to_incremental_metadata(table=table, empty_doc_indices=empty_doc_indices)

        # Add empty documents as skipped in metadata
        self._add_empty_docs_to_skipped_metadata(table=table, empty_doc_indices=empty_doc_indices, metadata=metadata)

        # Filter out empty documents using inverted mask
        non_empty_mask = pc.invert(is_empty_mask)  # type: ignore[attr-defined]
        filtered_table = table.filter(non_empty_mask)

        return filtered_table if filtered_table.num_rows > 0 else table.slice(0, 0)

    def _save_empty_docs_to_incremental_metadata(self, *, table: pa.Table, empty_doc_indices: list):
        """
        Save empty documents to incremental metadata so they are marked as processed
        and won't be reprocessed in subsequent incremental runs.

        Args:
            table: The PyArrow table containing all documents
            empty_doc_indices: List of indices for documents with empty content
        """
        if not empty_doc_indices:
            return

        try:
            from docpipe.core.incremental_metadata import get_incremental_update_service

            # Create a table with only the empty documents
            empty_docs_table = table.take(empty_doc_indices)

            incremental_service = get_incremental_update_service()

            # Save empty documents to incremental metadata
            incremental_service.save_metadata_for_incremental_update(
                job_id=self._params.get(DocpipeConstants.JOB_ID),
                job_run_id=self._params.get(DocpipeConstants.JOB_RUN_ID),
                tables=[empty_docs_table],
                failed_doc_ids=None,
            )

            logger.info(
                "Saved %s empty documents to incremental metadata",
                len(empty_doc_indices),
                extra={
                    DocpipeConstants.JOB_ID: self._params.get(DocpipeConstants.JOB_ID),
                    DocpipeConstants.JOB_RUN_ID: self._params.get(DocpipeConstants.JOB_RUN_ID),
                },
            )
        except Exception as e:
            logger.warning(
                "Failed to save empty documents to incremental metadata: %s",
                e,
                extra={
                    DocpipeConstants.JOB_ID: self._params.get(DocpipeConstants.JOB_ID),
                    DocpipeConstants.JOB_RUN_ID: self._params.get(DocpipeConstants.JOB_RUN_ID),
                },
            )

    def _add_empty_docs_to_skipped_metadata(
        self, *, table: pa.Table, empty_doc_indices: list, metadata: dict[str, Any]
    ):
        """
        Add empty documents to the skipped documents list in metadata.

        Args:
            table: The PyArrow table containing all documents
            empty_doc_indices: List of indices for documents with empty content
            metadata: Metadata dictionary to update
        """
        if not empty_doc_indices:
            return

        operator = self.get_operator()

        # Extract columns once for better performance
        id_col = table[OperatorConstants.Columns.ID] if OperatorConstants.Columns.ID in table.column_names else None
        name_col = (
            table[OperatorConstants.Columns.NAME] if OperatorConstants.Columns.NAME in table.column_names else None
        )

        for idx in empty_doc_indices:
            doc_id = id_col[idx].as_py() if id_col is not None else f"doc_{idx}"
            doc_name = name_col[idx].as_py() if name_col is not None else f"document_{idx}"

            logger.info(
                "Skipping document '%s' (ID: %s) due to empty content",
                doc_name,
                doc_id,
                extra={
                    DocpipeConstants.JOB_ID: self._params.get(DocpipeConstants.JOB_ID),
                    DocpipeConstants.JOB_RUN_ID: self._params.get(DocpipeConstants.JOB_RUN_ID),
                },
            )

            operator.record_skipped_document(
                metadata=metadata, doc_id=str(doc_id), doc_name=str(doc_name), reason="Extracted content is empty"
            )

        # Update processed_docs count to exclude empty documents
        if Metrics.External.PROCESSED_DOCS in metadata:
            metadata[Metrics.External.PROCESSED_DOCS] = metadata[Metrics.External.PROCESSED_DOCS] - len(
                empty_doc_indices
            )

        # Update node status to indicate completion with warnings if there are skipped docs
        if empty_doc_indices:
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                metadata.get(Metrics.External.NODE_STATUS, ExecutionStatus.COMPLETED.value),
                ExecutionStatus.COMPLETED_WITH_WARNINGS.value,
            )

    def _handle_empty_documents(
        self, *, out_tables: list[pa.Table], metadata: dict[str, Any]
    ) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Handle empty documents after operator execution.
        - Check if DOC_COLUMN is empty for any documents
        - Save empty docs to incremental processing metadata
        - Remove empty docs from the PyArrow table
        - Add empty docs as skipped documents in metadata

        Args:
            out_tables: List of output PyArrow tables from operator execution
            metadata: Metadata dictionary from operator execution

        Returns:
            tuple: (processed_tables, updated_metadata)
        """
        if not out_tables or len(out_tables) == 0:
            return out_tables, metadata

        processed_tables = []
        operator = self.get_operator()
        doc_column = getattr(operator, "doc_column", OperatorConstants.Columns.DOC_COLUMN_DEFAULT)

        for item in out_tables:
            # Handle nested lists (e.g., from branching operator which returns multiple branches)
            if isinstance(item, list):
                processed_branch = []
                for table in item:
                    processed_table = self._process_table_for_empty_docs(
                        table=table, doc_column=doc_column, metadata=metadata
                    )
                    processed_branch.append(processed_table)
                processed_tables.append(processed_branch)
            else:
                processed_table = self._process_table_for_empty_docs(
                    table=item, doc_column=doc_column, metadata=metadata
                )
                processed_tables.append(processed_table)

        return processed_tables, metadata
