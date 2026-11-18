"""
Incremental update service - Core business logic for incremental processing.

This service encapsulates all business logic for managing incremental document
processing, including metadata tracking, soft deletion, and document filtering.
"""

from typing import Any

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.incremental_metadata.domain import (
    IncrementalMetadataRecord,
    IncrementalMetadataStore,
)
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(f"{DocpipeConstants.LOGGER_NAME} : INCREMENTAL UPDATE SERVICE")


class IncrementalUpdateService:
    """
    Service for managing incremental document processing metadata.

    This service provides high-level operations for:
    - Tracking processed documents with modification times
    - Managing soft-deleted documents
    - Filtering and concatenating document tables
    - Handling force ingest and retention policies

    The service coordinates between the domain layer (IncrementalMetadataStore)
    and application-level business logic.
    """

    def __init__(self, *, store: IncrementalMetadataStore):
        """
        Initialize service with storage adapter.

        Args:
            store: Storage adapter implementing IncrementalMetadataStore interface
        """
        self.store = store

    def delete_failed_doc(self, *, table: pa.Table, result_table: pa.Table, job_id: str) -> set[str]:
        """
        Delete documents that failed processing and return remaining document IDs.

        Args:
            table: Input table containing document IDs
            result_table: Result table containing successfully processed document IDs
            job_id: Job identifier

        Returns:
            Set of remaining document IDs after deleting failed documents
        """
        ids_to_delete = self._get_ids_to_delete(input_table=table, result_table=result_table)
        self.delete_docs_for_ids(doc_ids=ids_to_delete, job_id=job_id)
        return set(table[OperatorConstants.Misc.ID].to_pylist()) if table.num_rows != 0 else set()

    def save_metadata_for_incremental_update(
        self,
        *,
        job_id: str,
        job_run_id: str,
        tables: list[pa.Table],
        failed_doc_ids: list[Any] | None = None,
        non_recoverable_docs_table: pa.Table | None = None,
    ) -> None:
        """
        Save incremental metadata for processed documents.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            tables: List of PyArrow tables containing document metadata
            failed_doc_ids: Optional list of document IDs that failed processing (both recoverable and non-recoverable)
            non_recoverable_docs_table: Optional PyArrow table containing non-recoverable docs with (id, name, modified_time)

        Raises:
            FlowExecutionFailedException: If saving metadata fails
        """
        try:
            # Merge all tables into a single table
            table_to_save: pa.Table | None = None
            if tables:
                for table in tables:
                    if table.num_rows == 0:
                        continue

                    # Select required columns
                    table = table.select(
                        [
                            OperatorConstants.Misc.ID,
                            OperatorConstants.Misc.NAME,
                            OperatorConstants.Metadata.MODIFIED_TIME,
                        ]
                    )

                    if table_to_save is None:
                        table_to_save = table
                    else:
                        table_to_save = self.concatenate_tables(table1=table_to_save, table2=table)

            # Process non-recoverable docs and merge with successful docs
            table_to_save, recoverable_failed_ids = self._process_non_recoverable_docs(
                table_to_save=table_to_save,
                non_recoverable_docs_table=non_recoverable_docs_table,
                failed_doc_ids=failed_doc_ids,
                job_id=job_id,
                job_run_id=job_run_id,
            )

            # After merging, check if we have anything to save
            if table_to_save is None or table_to_save.num_rows == 0:
                logger.info(f"No documents to save to incremental metadata for job_id={job_id}")
                return

            # Filter out ONLY recoverable failed docs from the merged table
            table_to_save = self.filter_rows(table=table_to_save, ids_to_delete=recoverable_failed_ids)

            if table_to_save is None or table_to_save.num_rows == 0:
                logger.info(f"No documents remaining after filtering for job_id={job_id}")
                return

            # Convert table to records and save
            records = self._prepare_records_for_save(
                table=table_to_save,
                job_id=job_id,
                job_run_id=job_run_id,
            )

            self.store.upsert_records(job_id=job_id, job_run_id=job_run_id, records=records)
            logger.info(
                f"Incremental metadata saved successfully for job_id={job_id}, "
                f"job_run_id={job_run_id}, records={len(records)}"
            )
        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to save incremental metadata for job_id={job_id}, job_run_id={job_run_id}. Error: {exc!s}"
            ) from exc

    def _process_non_recoverable_docs(
        self,
        *,
        table_to_save: pa.Table | None,
        non_recoverable_docs_table: pa.Table | None,
        failed_doc_ids: list[Any] | None,
        job_id: str,
        job_run_id: str,
    ) -> tuple[pa.Table | None, list[str]]:
        """
        Process non-recoverable docs and merge with successful docs table.

        Non-recoverable documents are permanent failures that should be marked as processed
        to prevent reprocessing in subsequent incremental runs.

        Args:
            table_to_save: Table with successful docs
            non_recoverable_docs_table: Table with non-recoverable docs (id, name, modified_time)
            failed_doc_ids: List of all failed doc IDs (both recoverable and non-recoverable)
            job_id: Job identifier
            job_run_id: Job run identifier

        Returns:
            Tuple of (merged_table, recoverable_failed_ids)
        """
        # Extract non-recoverable doc IDs from the table for filtering
        non_recoverable_doc_ids: list[str] = []
        if non_recoverable_docs_table and non_recoverable_docs_table.num_rows > 0:
            non_recoverable_doc_ids = non_recoverable_docs_table[OperatorConstants.Misc.ID].to_pylist()
            logger.info(f"Processing {len(non_recoverable_doc_ids)} non-recoverable docs from table")

        # Calculate recoverable failed doc IDs (failed_doc_ids - non_recoverable_doc_ids)
        recoverable_failed_ids = list(failed_doc_ids or [])
        if failed_doc_ids and non_recoverable_doc_ids:
            recoverable_failed_ids = list(set(failed_doc_ids) - set(non_recoverable_doc_ids))
            logger.info(
                f"Filtering out {len(recoverable_failed_ids)} recoverable failed docs, "
                f"keeping {len(non_recoverable_doc_ids)} non-recoverable docs in metadata"
            )

        # Merge non-recoverable docs table with successful docs table
        if non_recoverable_docs_table is not None and non_recoverable_docs_table.num_rows > 0:
            logger.info(f"Processing {non_recoverable_docs_table.num_rows} non-recoverable docs for metadata save")

            non_rec_prepared = non_recoverable_docs_table.select(
                [
                    OperatorConstants.Misc.ID,
                    OperatorConstants.Misc.NAME,
                    OperatorConstants.Metadata.MODIFIED_TIME,
                ]
            )

            if table_to_save is not None and table_to_save.num_rows > 0:
                successful_count = table_to_save.num_rows
                merged_table = self.concatenate_tables(table1=table_to_save, table2=non_rec_prepared)
                logger.info(
                    f"Merged {non_rec_prepared.num_rows} non-recoverable docs with "
                    f"{successful_count} successful docs. Total: {merged_table.num_rows}"
                )
                table_to_save = merged_table
            else:
                table_to_save = non_rec_prepared
                logger.info(
                    f"No successful docs this run. Saving {non_rec_prepared.num_rows} non-recoverable docs to metadata"
                )

        return table_to_save, recoverable_failed_ids

    def concatenate_tables(self, *, table1: pa.Table, table2: pa.Table) -> pa.Table:
        """
        Concatenate two tables with same schema, preferring table1 for duplicates.

        If the same document exists in both tables, the version from table1 is retained.

        Args:
            table1: First table (takes precedence for duplicates)
            table2: Second table

        Returns:
            Concatenated PyArrow table
        """
        ids_to_delete = list(table1.column(OperatorConstants.Misc.ID).to_pylist())
        filtered_table2 = self.filter_rows(table=table2, ids_to_delete=ids_to_delete)
        return pa.concat_tables([table1, filtered_table2])

    @staticmethod
    def filter_rows(*, table: pa.Table, ids_to_delete: list[str]) -> pa.Table | None:
        """
        Filter out rows with specified document IDs.

        Args:
            table: PyArrow table to filter
            ids_to_delete: List of document IDs to remove

        Returns:
            Filtered PyArrow table, or original table if no IDs to delete
        """
        if not table or not ids_to_delete:
            return table
        ids_to_delete_set = set(ids_to_delete)
        filtered_rows = [
            row for row in table.to_pylist() if row.get(OperatorConstants.Misc.ID) not in ids_to_delete_set
        ]
        return pa.Table.from_pylist(filtered_rows, schema=table.schema)

    def get_all_processed_docs(self, *, job_id: str) -> dict[str, Any]:
        """
        Retrieve processed document IDs with modification times.

        Note: Soft-deleted documents are not returned.

        Args:
            job_id: Job identifier

        Returns:
            Dictionary mapping document IDs to modification times

        Raises:
            FlowExecutionFailedException: If retrieval fails
        """
        try:
            logger.debug(f"Retrieving processed documents for job_id={job_id}")
            return self.store.get_processed_docs(job_id=job_id)
        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to retrieve processed document IDs for job_id={job_id}. Error: {exc!s}"
            ) from exc

    @staticmethod
    def get_deleted_doc_ids_from_dict(
        *, previously_processed_docs_dict: dict[str, Any], doc_ids: list[str]
    ) -> list[str]:
        """
        Get document IDs that were previously processed but are now missing.

        Args:
            previously_processed_docs_dict: Dictionary of previously processed documents
            doc_ids: List of currently existing document IDs

        Returns:
            List of deleted document IDs
        """
        if not previously_processed_docs_dict:
            return []
        return list(set(previously_processed_docs_dict.keys()) - set(doc_ids))

    def process_ingested_docs(self, *, config: dict[str, Any], job_id: str, doc_ids: list[str]) -> None:
        """
        Update incremental processing metadata based on configuration.

        Handles force ingest and document retention policies.

        Args:
            config: Configuration dictionary with force_ingest and retain_deleted_docs flags
            job_id: Job identifier
            doc_ids: List of document IDs identified by ingest operator
        """
        if config.get(DocpipeConstants.FORCE_INGEST):
            # Force ingest: clear all previously saved metadata
            self.clear_incremental_table(job_id=job_id)

        if bool(config.get(DocpipeConstants.RETAIN_DELETED_DOCS, DocpipeConstants.RETAIN_DELETED_DOCS_DEFAULT)):
            # Retain deleted documents: no changes needed
            return

        self.mark_soft_deleted_docs(job_id=job_id, doc_ids=doc_ids)

    def mark_soft_deleted_docs(self, *, job_id: str, doc_ids: list[str]) -> set[str]:
        """
        Mark documents as soft-deleted for a given job.

        Documents that were previously processed but are not in doc_ids
        will be marked as deleted.

        Args:
            job_id: Job identifier
            doc_ids: List of currently existing document IDs

        Returns:
            Set of document IDs marked as soft-deleted

        Raises:
            FlowExecutionFailedException: If marking fails
        """
        try:
            previously_soft_deleted_doc_ids = self.get_soft_deleted_doc_ids(job_id=job_id)
            self.delete_docs_for_ids(doc_ids=list(previously_soft_deleted_doc_ids), job_id=job_id)
            return self.store.mark_missing_docs_as_deleted(job_id=job_id, doc_ids=doc_ids)
        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to mark soft-deleted document IDs for job_id={job_id}. Error: {exc!s}"
            ) from exc

    def get_soft_deleted_doc_ids(self, *, job_id: str) -> set[str]:
        """
        Retrieve soft-deleted document IDs for a given job.

        Args:
            job_id: Job identifier

        Returns:
            Set of soft-deleted document IDs

        Raises:
            FlowExecutionFailedException: If retrieval fails
        """
        try:
            return self.store.get_soft_deleted_doc_ids(job_id=job_id)
        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to retrieve soft-deleted document IDs for job_id={job_id}. Error: {exc!s}"
            ) from exc

    def delete_docs_for_ids(self, *, doc_ids: list[str], job_id: str) -> None:
        """
        Permanently delete metadata records for specified documents.

        Args:
            doc_ids: List of document IDs to delete
            job_id: Job identifier

        Raises:
            FlowExecutionFailedException: If deletion fails
        """
        try:
            if doc_ids:
                self.store.delete_docs(job_id=job_id, doc_ids=doc_ids)
        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to delete document IDs for job_id={job_id}. Error: {exc!s}"
            ) from exc

    def clear_incremental_table(self, *, job_id: str) -> None:
        """
        Clear all incremental metadata for a specific job.

        This delegates to the store's clear method, which handles all cleanup
        including file deletion for the specific storage backend.

        Args:
            job_id: Job identifier
        """
        self.store.clear(job_id=job_id)

    @staticmethod
    def _prepare_records_for_save(
        *,
        table: pa.Table,
        job_id: str,
        job_run_id: str,
    ) -> list[IncrementalMetadataRecord]:
        """
        Prepare incremental metadata records from PyArrow table.

        Args:
            table: PyArrow table containing document metadata
            job_id: Job identifier
            job_run_id: Job run identifier

        Returns:
            List of IncrementalMetadataRecord objects
        """
        rows = table.to_pylist()

        return [
            IncrementalMetadataRecord(
                job_id=job_id,
                doc_id=row[OperatorConstants.Misc.ID],
                name=row.get(OperatorConstants.Misc.NAME),
                modified_time=row.get(OperatorConstants.Metadata.MODIFIED_TIME),
                job_run_id=job_run_id,
                deleted=False,
            )
            for row in rows
            if row.get(OperatorConstants.Misc.ID)
        ]

    @staticmethod
    def _get_ids_to_delete(*, input_table: pa.Table, result_table: pa.Table) -> list[str]:
        """
        Determine document IDs to delete based on input and result tables.

        Documents present in input but not in result are considered failed.

        Args:
            input_table: Input table with document IDs
            result_table: Result table with successfully processed document IDs

        Returns:
            List of document IDs to delete
        """
        input_doc_ids = set(input_table[OperatorConstants.Misc.ID].to_pylist()) if input_table.num_rows != 0 else set()
        output_doc_ids = (
            set(result_table[OperatorConstants.Misc.ID].to_pylist()) if result_table.num_rows != 0 else set()
        )

        return list(input_doc_ids - output_doc_ids)
