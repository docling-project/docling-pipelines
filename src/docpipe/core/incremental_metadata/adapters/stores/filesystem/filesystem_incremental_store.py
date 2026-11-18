# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Filesystem-based implementation of IncrementalMetadataStore.

Provides persistent storage for incremental metadata using Apache Parquet format,
offering efficient columnar storage and fast query performance.

Features:
- One parquet file per job_id for isolation
- Efficient columnar storage with PyArrow
- Thread-safe operations with file locking
- Atomic writes with temporary files
"""

import shutil
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq
from filelock import FileLock, Timeout

from docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory import (
    register_incremental_update_store,
)
from docpipe.core.incremental_metadata.domain import (
    IncrementalMetadataRecord,
    IncrementalMetadataStore,
)
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.retry import retry_with_exponential_backoff

logger = get_logger("INCREMENTAL_METADATA_FILESYSTEM")


def _should_retry_on_lock_timeout(result, exception):
    """
    Retry logic for file lock timeout errors.

    Args:
        result: The result from the function call
        exception: Any exception that occurred

    Returns:
        Tuple of (should_retry: bool, error_message: str)
    """
    if isinstance(exception, Timeout):
        return True, f"File lock timeout: {exception!s}"
    if isinstance(exception, FlowExecutionFailedException) and "Failed to acquire write lock" in str(exception):
        return True, f"Failed to acquire write lock: {exception!s}"
    return False, ""


@register_incremental_update_store
class FilesystemIncrementalMetadataStore(IncrementalMetadataStore):
    """
    Filesystem-based storage adapter for incremental metadata.

    Stores metadata in Parquet format with one file per job_id:
    {base_dir}/{job_id}/inc_update_metadata/inc_update_metadata.parquet

    Schema:
        - job_id: string
        - id: string
        - name: string (nullable)
        - modified_time: int64 (nullable)
        - job_run_id: string (nullable)
        - deleted: bool
    """

    STORE_BACKEND = "filesystem"

    # Parquet schema definition
    SCHEMA = pa.schema(
        [
            ("job_id", pa.string()),
            ("id", pa.string()),
            ("name", pa.string()),
            ("modified_time", pa.int64()),
            ("job_run_id", pa.string()),
            ("deleted", pa.bool_()),
        ]
    )

    def __init__(self, *, config: dict[str, Any] | None = None):
        """
        Initialize Filesystem incremental metadata store.

        Args:
            config: Configuration dict. Recognised keys:
                    - base_dir: base directory for parquet files
                    - lock_timeout: seconds to wait for file lock (default 120.0)
        """
        self.config = config or {}

        # Resolve base_dir:  config dict > default data path
        if self.config.get("base_dir") is not None:
            config_base_dir = self.config["base_dir"]
            resolved = Path(config_base_dir) if isinstance(config_base_dir, str) else config_base_dir
            resolved = resolved if resolved.is_absolute() else resolved.resolve()
        else:
            resolved = Path(get_data_path())

        if self.config.get("base_dir"):
            resolved.mkdir(parents=True, exist_ok=True)

        self._base_dir = resolved
        self._lock_timeout: float = self.config.get("lock_timeout", 120.0)

        logger.info(
            "FilesystemIncrementalMetadataStore initialized: base_dir=%s, config_keys=%s",
            self._base_dir,
            list(self.config.keys()),
        )

    def _get_job_dir(self, *, job_id: str) -> Path:
        """Get directory path for job's incremental metadata."""
        return self._base_dir / job_id / "inc_update_metadata"

    def _get_parquet_path(self, *, job_id: str) -> Path:
        """Get parquet file path for job."""
        return self._get_job_dir(job_id=job_id) / "inc_update_metadata.parquet"

    def _get_lock_path(self, *, job_id: str) -> Path:
        """Get lock file path for job."""
        lock_dir = self._get_job_dir(job_id=job_id) / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        return lock_dir / "metadata.lock"

    def _read_table(self, *, job_id: str) -> pa.Table | None:
        """
        Read parquet table for job with file locking.

        Args:
            job_id: Job identifier

        Returns:
            PyArrow table or None if file doesn't exist
        """
        parquet_path = self._get_parquet_path(job_id=job_id)

        if not parquet_path.exists():
            return None

        try:
            table = pq.read_table(parquet_path)
            logger.debug("Read %s records from %s", table.num_rows, parquet_path)
            return table
        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to read parquet file for job_id={job_id}: {exc}") from exc

    def _write_table(self, *, job_id: str, table: pa.Table) -> None:
        """
        Write parquet table for job atomically with file locking.

        Uses temporary file and atomic rename for crash safety.

        Args:
            job_id: Job identifier
            table: PyArrow table to write
        """
        parquet_path = self._get_parquet_path(job_id=job_id)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first
        temp_path = parquet_path.with_suffix(".tmp")

        try:
            pq.write_table(
                table,
                temp_path,
                compression="snappy",
                use_dictionary=True,
                write_statistics=True,
            )
            # Atomic rename
            temp_path.replace(parquet_path)
            logger.debug("Wrote %s records to %s", table.num_rows, parquet_path)
        except Exception as exc:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise FlowExecutionFailedException(f"Failed to write parquet file for job_id = {job_id}: {exc}") from exc

    def _records_to_table(self, *, records: list[IncrementalMetadataRecord]) -> pa.Table:
        """Convert list of records to PyArrow table."""
        data = {
            "job_id": [r.job_id for r in records],
            "id": [r.doc_id for r in records],
            "name": [r.name for r in records],
            "modified_time": [r.modified_time for r in records],
            "job_run_id": [r.job_run_id for r in records],
            "deleted": [r.deleted for r in records],
        }
        return pa.table(data, schema=self.SCHEMA)

    def get_processed_docs(self, *, job_id: str) -> dict[str, Any]:
        """Retrieve processed document IDs with modification times and job run IDs (non-deleted only)."""
        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                table = self._read_table(job_id=job_id)

                if table is None or table.num_rows == 0:
                    return {}

                # Filter for non-deleted documents
                mask = pc.equal(table["deleted"], False)  # type: ignore[attr-defined]
                filtered_table = table.filter(mask)

                # Build result dictionary
                result = {}
                for i in range(filtered_table.num_rows):
                    doc_id = filtered_table["id"][i].as_py()
                    modified_time = filtered_table["modified_time"][i].as_py()
                    job_run_id = filtered_table["job_run_id"][i].as_py()
                    result[doc_id] = {"modified_time": modified_time, "job_run_id": job_run_id}

                logger.debug("Retrieved %s processed docs for job_id=%s", len(result), job_id)
                return result

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire read lock for job_id={job_id}") from exc

    @retry_with_exponential_backoff(
        max_retries=5, initial_delay=1, max_delay=30, retry_logic=_should_retry_on_lock_timeout
    )
    def upsert_records(self, *, job_id: str, job_run_id: str, records: list[IncrementalMetadataRecord]) -> None:
        """Insert or update incremental metadata records with retry on lock timeout."""
        if not records:
            return

        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                existing_table = self._read_table(job_id=job_id)
                new_table = self._records_to_table(records=records)

                if existing_table is None or existing_table.num_rows == 0:
                    # No existing data, just write new records
                    self._write_table(job_id=job_id, table=new_table)
                    logger.info("Inserted %s new records for job_id=%s", len(records), job_id)
                    return

                # Get doc_ids from new records
                new_doc_ids = {r.doc_id for r in records}

                # Filter out existing records that will be updated
                mask = pc.invert(pc.is_in(existing_table["id"], pa.array(list(new_doc_ids))))  # type: ignore[attr-defined]
                filtered_existing = existing_table.filter(mask)

                # Concatenate filtered existing with new records
                combined_table = pa.concat_tables([filtered_existing, new_table])

                self._write_table(job_id=job_id, table=combined_table)
                logger.info(
                    "Upserted %s records for job_id=%s (total: %s)", len(records), job_id, combined_table.num_rows
                )

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire write lock for job_id={job_id}") from exc

    def get_soft_deleted_doc_ids(self, *, job_id: str) -> set[str]:
        """Retrieve document IDs marked as soft-deleted."""
        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                table = self._read_table(job_id=job_id)

                if table is None or table.num_rows == 0:
                    return set()

                # Filter for deleted documents
                mask = pc.equal(table["deleted"], True)  # type: ignore[attr-defined]
                deleted_table = table.filter(mask)

                result = set(deleted_table["id"].to_pylist())
                logger.debug("Retrieved %s soft-deleted docs for job_id=%s", len(result), job_id)
                return result

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire read lock for job_id={job_id}") from exc

    def mark_missing_docs_as_deleted(self, *, job_id: str, doc_ids: list[str]) -> set[str]:
        """Mark documents as soft-deleted if not in provided list."""
        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                table = self._read_table(job_id=job_id)

                if table is None or table.num_rows == 0:
                    return set()

                current_doc_ids = set(doc_ids)

                # Find documents not in current list and not already deleted
                mask_not_deleted = pc.equal(table["deleted"], False)  # type: ignore[attr-defined]
                mask_not_in_current = pc.invert(pc.is_in(table["id"], pa.array(list(current_doc_ids))))  # type: ignore[attr-defined]
                mask_to_delete = pc.and_(mask_not_deleted, mask_not_in_current)  # type: ignore[attr-defined]

                # Get doc_ids to mark as deleted
                to_delete_table = table.filter(mask_to_delete)
                deleted_ids = set(to_delete_table["id"].to_pylist())

                if not deleted_ids:
                    return set()

                # Update deleted flag
                deleted_column = pc.if_else(mask_to_delete, pa.array([True] * table.num_rows), table["deleted"])  # type: ignore[attr-defined]

                updated_table = table.set_column(table.schema.get_field_index("deleted"), "deleted", deleted_column)

                self._write_table(job_id=job_id, table=updated_table)
                logger.info("Marked %s docs as deleted for job_id=%s", len(deleted_ids), job_id)
                return deleted_ids

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire write lock for job_id={job_id}") from exc

    def delete_docs(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Permanently delete metadata records for specified documents."""
        if not doc_ids:
            return

        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                table = self._read_table(job_id=job_id)

                if table is None or table.num_rows == 0:
                    return

                # Filter out documents to delete
                mask = pc.invert(pc.is_in(table["id"], pa.array(doc_ids)))  # type: ignore[attr-defined]
                filtered_table = table.filter(mask)

                if filtered_table.num_rows == 0:
                    # All records deleted, remove file
                    parquet_path = self._get_parquet_path(job_id=job_id)
                    if parquet_path.exists():
                        parquet_path.unlink()
                    logger.info("Deleted all records for job_id=%s", job_id)
                else:
                    self._write_table(job_id=job_id, table=filtered_table)
                    logger.info(
                        "Deleted %s docs for job_id=%s (remaining: %s)", len(doc_ids), job_id, filtered_table.num_rows
                    )

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire write lock for job_id={job_id}") from exc

    def clear(self, *, job_id: str) -> None:
        """Clear all incremental metadata for a specific job."""
        job_dir = self._get_job_dir(job_id=job_id)

        if not job_dir.exists():
            return

        lock = FileLock(str(self._get_lock_path(job_id=job_id)), timeout=self._lock_timeout)

        try:
            with lock.acquire(timeout=self._lock_timeout):
                # Remove parquet file
                parquet_path = self._get_parquet_path(job_id=job_id)
                if parquet_path.exists():
                    parquet_path.unlink()

            # Remove locks directory AFTER releasing the lock
            locks_dir = job_dir / ".locks"
            if locks_dir.exists():
                shutil.rmtree(locks_dir)

            # Remove job directory if empty
            if job_dir.exists():
                remaining = list(job_dir.iterdir())
                if not remaining:
                    job_dir.rmdir()

            logger.info("Cleared all metadata for job_id=%s", job_id)

        except Timeout as exc:
            raise FlowExecutionFailedException(f"Failed to acquire clear lock for job_id={job_id}") from exc
