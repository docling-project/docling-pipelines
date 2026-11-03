# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Batch Manager - Handles batch creation and management for flow execution.

This class encapsulates all batch-related logic including:
- Batch creation from PyArrow tables
- Batch configuration management
- Semaphore management for concurrent operator execution
- UUID batch_id generation for retained batches
"""

import threading
import uuid
from typing import Any

import pyarrow as pa
from data_processing.data_access import DataAccess, DataAccessFactory

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class BatchInfo:
    """Container for batch data with metadata."""

    def __init__(self, *, batch_id: str, batch_num: int, table: pa.Table):
        self.batch_id = batch_id
        self.batch_num = batch_num
        self.table = table


class BatchManager:
    """
    Manages batch creation and execution control for flow processing.

    Responsibilities:
    - Split PyArrow tables into batches based on configuration
    - Manage global operator semaphore for concurrent execution control
    - Create DataAccess objects for batch tables
    - Determine batch mode vs non-batch mode execution
    """

    def __init__(self):
        """Initialize the batch manager."""
        self.logger = get_logger()
        self._batch_semaphore: threading.Semaphore | None = None

    def configure_batching(self, *, global_config: dict) -> tuple[bool, int | None]:
        """
        Determine batching configuration from global config.

        Args:
            global_config: Global configuration dictionary

        Returns:
            Tuple of (batching_enabled, batch_size)
            - batching_enabled: Whether micro-batching is enabled
            - batch_size: Size of each batch (None if batching disabled)
        """
        batching_enabled = global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
        batch_size = global_config.get(DocpipeConstants.MICRO_BATCH_SIZE, DocpipeConstants.DEFAULT_MICRO_BATCH_SIZE)
        if isinstance(batch_size, str) and batch_size.isdigit():
            batch_size = int(batch_size)
        return batching_enabled, batch_size

    def _batches_by_record_count(self, *, table: pa.Table, batch_size: int) -> list[BatchInfo]:
        """Fallback: split table into fixed-size record-count chunks, skipping empty batches."""
        batches = []
        batch_num = 0
        for batch in table.to_batches(max_chunksize=batch_size):
            batch_table = pa.Table.from_batches([batch])
            if batch_table.num_rows == 0:  # pragma: no cover
                self.logger.debug("Skipping empty batch at position %s", batch_num)
                continue
            batches.append(BatchInfo(batch_id=str(uuid.uuid4()), batch_num=batch_num, table=batch_table))
            batch_num += 1
        return batches

    def _batches_by_round_robin(self, *, table: pa.Table, num_batches: int, num_rows: int) -> list[BatchInfo]:
        """Round-robin distribution used when all file sizes are zero."""
        result_batches = []
        batch_num = 0
        for batch_idx in range(num_batches):
            indices = list(range(batch_idx, num_rows, num_batches))
            if indices:
                batch_table = table.take(indices)
                if batch_table.num_rows == 0:  # pragma: no cover
                    continue
                result_batches.append(BatchInfo(batch_id=str(uuid.uuid4()), batch_num=batch_num, table=batch_table))
                batch_num += 1
        return result_batches

    def _batches_from_assignments(
        self, *, table: pa.Table, batch_assignments: Any, num_batches: int
    ) -> list[BatchInfo]:
        """Convert greedy bin-pack assignments into BatchInfo objects, skipping empty batches."""
        import numpy as np

        result_batches = []
        batch_num = 0
        for batch_idx in range(num_batches):
            batch_indices: Any = np.nonzero(batch_assignments == batch_idx)[0]
            if len(batch_indices) > 0:
                batch_table = table.take(batch_indices.tolist())
                if batch_table.num_rows == 0:  # pragma: no cover
                    self.logger.debug("Skipping empty batch at index %s", batch_idx)
                    continue
                result_batches.append(BatchInfo(batch_id=str(uuid.uuid4()), batch_num=batch_num, table=batch_table))
                batch_num += 1
        return result_batches

    def create_batches(self, *, table: pa.Table, batch_size: int) -> list[BatchInfo]:
        """
        Split a PyArrow table into batches based on file size for balanced workload distribution.

        Filters out empty batches and assigns UUID batch_id to each retained batch.
        Uses file-size-based batching when SIZE column exists, falls back to record-count batching.

        Algorithm:
        - If SIZE column exists: Uses greedy bin-packing to distribute files by size
        - If SIZE column missing: Falls back to simple record-count batching
        - Memory-efficient: Uses numpy arrays and PyArrow's zero-copy operations
        - Schema-preserving: Uses PyArrow's take() which maintains exact schema structure

        Args:
            table: PyArrow table containing file metadata with SIZE field (in bytes)
            batch_size: Target number of records per batch (used as fallback or to calculate num_batches)

        Returns:
            List of BatchInfo objects with batch_id, batch_num, and non-empty tables
        """
        import numpy as np

        num_rows = table.num_rows

        # Handle empty table
        if num_rows == 0:
            return []

        # Check if SIZE column exists for file-size-based batching
        if OperatorConstants.Misc.SIZE not in table.column_names:
            self.logger.warning(
                "SIZE column not found in table. Falling back to record-count batching. Available columns: %s",
                table.column_names,
            )
            return self._batches_by_record_count(table=table, batch_size=batch_size)

        # Calculate number of batches based on batch_size
        num_batches = max(1, (num_rows + batch_size - 1) // batch_size)

        # Extract file sizes as numpy array (memory-efficient, zero-copy when possible)
        size_column = table.column(OperatorConstants.Misc.SIZE)
        size_array = size_column.to_numpy(zero_copy_only=False)

        # Handle None/null values and negative sizes
        size_array = np.where(np.isnan(size_array) | (size_array < 0), 0, size_array).astype(np.int64)

        total_size = size_array.sum()

        # Handle edge case: all files have zero size
        if total_size == 0:
            self.logger.warning("All files have zero size. Using simple round-robin distribution.")
            return self._batches_by_round_robin(table=table, num_batches=num_batches, num_rows=num_rows)

        # Create index array and sort by size (largest first) for better bin-packing
        sorted_indices = np.argsort(-size_array)  # Negative for descending order

        # Initialize batch tracking arrays (memory-efficient)
        batch_sizes = np.zeros(num_batches, dtype=np.int64)
        batch_assignments = np.zeros(num_rows, dtype=np.int32)

        # Greedy bin-packing: assign each file to the batch with smallest current total
        for i in range(num_rows):
            file_idx = sorted_indices[i]
            file_size = size_array[file_idx]
            # Find batch with minimum cumulative size
            min_batch_idx = np.argmin(batch_sizes)
            batch_assignments[file_idx] = min_batch_idx
            batch_sizes[min_batch_idx] += file_size

        # Log batch size distribution for monitoring
        mb_divisor = 1024 * 1024
        total_size_mb = total_size / mb_divisor
        avg_size_mb = total_size_mb / num_batches
        size_distribution = [f"Batch {i}: {batch_sizes[i] / mb_divisor:.2f} MB" for i in range(num_batches)]
        self.logger.info(
            "Created %s size-balanced batches. Total size: %.2f MB, Avg per batch: %.2f MB. Distribution: %s",
            num_batches,
            total_size_mb,
            avg_size_mb,
            "; ".join(size_distribution),
        )

        # Convert to BatchInfo objects using take() which preserves schema exactly
        return self._batches_from_assignments(table=table, batch_assignments=batch_assignments, num_batches=num_batches)

    def prepare_batches(
        self, *, ingested_table: pa.Table, global_config: dict, common_log_arguments: dict | None = None
    ) -> tuple[list[BatchInfo], dict[str, Any]]:
        """
        Prepare batches for execution based on configuration.

        This method determines whether to use batch mode or non-batch mode
        and prepares the appropriate batch list and updated global config.

        Args:
            ingested_table: The ingested PyArrow table
            global_config: Global configuration dictionary
            common_log_arguments: Common logging arguments

        Returns:
            Tuple of (batches, updated_global_config)
            - batches: List of BatchInfo objects (single BatchInfo for non-batch mode)
            - updated_global_config: Config with batch-related parameters added
        """
        batching_enabled, batch_size = self.configure_batching(global_config=global_config)
        updated_config = global_config.copy()

        if batching_enabled:
            # BATCH MODE: Split table into multiple batches
            if batch_size is None:
                raise FlowExecutionFailedException("micro_batch_size must be set when micro-batching is enabled")
            batches = self.create_batches(table=ingested_table, batch_size=batch_size)
            if not batches and ingested_table.num_rows == 0:
                batches = [BatchInfo(batch_id=str(uuid.uuid4()), batch_num=0, table=ingested_table)]
            batch_count = len(batches)

            self.logger.info(
                ">>> Split %s rows into %s batches of size %s",
                ingested_table.num_rows,
                batch_count,
                batch_size,
                extra=common_log_arguments,
            )

            # Add batch_count to config for operators to use
            updated_config[DocpipeConstants.BATCH_COUNT] = batch_count
        else:
            # NON-BATCH MODE: Use entire table as single "batch"
            # Create a single BatchInfo with batch_id for consistency
            batch_id: str = str(uuid.uuid4())
            batches = [BatchInfo(batch_id=batch_id, batch_num=0, table=ingested_table)]

            self.logger.info(
                ">>> Non-batch mode: Processing all %s rows in single execution",
                ingested_table.num_rows,
                extra=common_log_arguments,
            )

            # NOTE: Do NOT set BATCH_COUNT or BATCH_NUM in non-batch mode
            # This ensures output paths don't include batch number subdirectories

        return batches, updated_config

    def initialize_batch_semaphore(self, *, max_concurrent_batches: int):
        """
        Initialize the batch semaphore for concurrent batch execution control.

        Args:
            max_concurrent_batches: Maximum number of batches that can execute concurrently
        """
        self._batch_semaphore = threading.Semaphore(max_concurrent_batches)
        self.logger.debug("Initialized batch semaphore with %s slots", max_concurrent_batches)

    def get_batch_semaphore(self) -> threading.Semaphore | None:
        """
        Get the batch semaphore.

        Returns:
            The batch semaphore or None if not initialized
        """
        return self._batch_semaphore

    def reset_batch_semaphore(self):
        """Reset the batch semaphore."""
        self._batch_semaphore = None
        self.logger.debug("Reset batch semaphore")

    @staticmethod
    def create_batch_data_access(*, batch_table: pa.Table) -> DataAccess:
        """
        Create a DataAccess object for a batch table.

        Args:
            batch_table: PyArrow table for the batch

        Returns:
            DataAccess object containing the batch table
        """
        data_access_factory = DataAccessFactory()
        config = {"data_config": {"da_class": "data_processing.data_access.DataAccessMemory"}}
        data_access_factory.apply_input_params(config)
        batch_data_access = data_access_factory.create_data_access()
        batch_data_access.save_table(path="", table=batch_table)
        return batch_data_access
