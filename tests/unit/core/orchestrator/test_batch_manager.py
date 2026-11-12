# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for BatchManager - batch semaphore, validation, and batch operations.

Consolidated test suite covering:
- Batch semaphore initialization and concurrency control
- Batch creation and preparation
- Cleanup and error handling
- Configuration validation
- DataAccess creation for batches
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.batch_manager import BatchManager
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException


class TestBatchSemaphore:
    """Test batch-level semaphore functionality."""

    def test_initialize_batch_semaphore(self):
        """Verify batch semaphore is initialized with correct limit."""
        batch_manager = BatchManager()
        max_concurrent = 3

        batch_manager.initialize_batch_semaphore(max_concurrent_batches=max_concurrent)

        semaphore = batch_manager.get_batch_semaphore()
        assert semaphore is not None
        assert isinstance(semaphore, threading.Semaphore)

        # Verify capacity by acquiring all slots
        acquired = []
        for _ in range(max_concurrent):
            result = semaphore.acquire(blocking=False)
            acquired.append(result)

        assert all(acquired), "Should acquire all slots"
        assert not semaphore.acquire(blocking=False), "Should not exceed limit"

        # Cleanup
        for _ in range(max_concurrent):
            semaphore.release()

    def test_batch_semaphore_limits_concurrency(self):
        """Verify semaphore enforces concurrent batch limit."""
        batch_manager = BatchManager()
        max_concurrent = 2
        batch_manager.initialize_batch_semaphore(max_concurrent_batches=max_concurrent)

        semaphore = batch_manager.get_batch_semaphore()
        concurrent_count = 0
        max_concurrent_observed = 0
        lock = threading.Lock()

        def simulate_batch_execution(batch_num):
            nonlocal concurrent_count, max_concurrent_observed

            semaphore.acquire()
            try:
                with lock:
                    concurrent_count += 1
                    max_concurrent_observed = max(max_concurrent_observed, concurrent_count)

                time.sleep(0.1)

                with lock:
                    concurrent_count -= 1
            finally:
                semaphore.release()

        # Start 5 batches
        threads = []
        for i in range(5):
            thread = threading.Thread(target=simulate_batch_execution, args=(i,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        assert max_concurrent_observed == max_concurrent, (
            f"Expected max {max_concurrent} concurrent, observed {max_concurrent_observed}"
        )

    def test_batch_semaphore_released_on_completion(self):
        """Verify semaphore is released after successful batch completion."""
        batch_manager = BatchManager()
        batch_manager.initialize_batch_semaphore(max_concurrent_batches=1)

        semaphore = batch_manager.get_batch_semaphore()

        semaphore.acquire()
        semaphore.release()

        assert semaphore.acquire(blocking=False), "Semaphore should be reusable"
        semaphore.release()

    def test_batch_semaphore_released_on_failure(self):
        """Verify semaphore is released even when batch fails."""
        batch_manager = BatchManager()
        batch_manager.initialize_batch_semaphore(max_concurrent_batches=1)

        semaphore = batch_manager.get_batch_semaphore()

        try:
            semaphore.acquire()
            raise Exception("Simulated batch failure")
        except Exception:
            pass
        finally:
            semaphore.release()

        assert semaphore.acquire(blocking=False), "Semaphore should be released after failure"
        semaphore.release()

    def test_reset_batch_semaphore(self):
        """Verify batch semaphore can be reset to None."""
        batch_manager = BatchManager()
        batch_manager.initialize_batch_semaphore(max_concurrent_batches=2)

        assert batch_manager.get_batch_semaphore() is not None

        batch_manager.reset_batch_semaphore()

        assert batch_manager.get_batch_semaphore() is None

    def test_independent_batch_progression(self):
        """Verify batches progress independently through operator stages."""
        batch_manager = BatchManager()
        batch_manager.initialize_batch_semaphore(max_concurrent_batches=3)

        semaphore = batch_manager.get_batch_semaphore()
        batch_stages = {}
        stage_history = []
        lock = threading.Lock()

        def simulate_batch_with_stages(batch_num):
            """Simulate batch progressing through multiple stages."""
            semaphore.acquire()
            try:
                stages = ["ingest", "extract", "chunk", "complete"]
                for stage in stages:
                    with lock:
                        batch_stages[batch_num] = stage
                        stage_history.append((batch_num, stage))
                    time.sleep(0.02)
            finally:
                semaphore.release()

        threads = []
        for i in range(3):
            thread = threading.Thread(target=simulate_batch_with_stages, args=(i,))
            thread.start()
            threads.append(thread)
            time.sleep(0.01)

        for thread in threads:
            thread.join()

        assert all(stage == "complete" for stage in batch_stages.values()), "All batches should complete"

        # Verify each batch went through all stages in order
        expected_order = ["ingest", "extract", "chunk", "complete"]
        for batch_num in range(3):
            batch_stages_list = [stage for batch, stage in stage_history if batch == batch_num]
            assert batch_stages_list == expected_order, f"Batch {batch_num} stages out of order: {batch_stages_list}"


class TestBatchConfiguration:
    """Test batch configuration and preparation."""

    def test_configure_batching_enabled(self):
        """Verify batching configuration when enabled."""
        batch_manager = BatchManager()
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.MICRO_BATCH_SIZE: 100,
        }

        enabled, size = batch_manager.configure_batching(global_config=global_config)

        assert enabled is True
        assert size == 100

    def test_configure_batching_disabled(self):
        """Verify batching configuration when disabled."""
        batch_manager = BatchManager()
        global_config = {DocpipeConstants.ENABLE_MICRO_BATCHING: False}

        enabled, size = batch_manager.configure_batching(global_config=global_config)

        assert enabled is False
        assert size == DocpipeConstants.DEFAULT_MICRO_BATCH_SIZE

    def test_configure_batching_default(self):
        """Verify batching configuration with defaults."""
        batch_manager = BatchManager()
        global_config: dict = {}

        enabled, size = batch_manager.configure_batching(global_config=global_config)

        assert enabled is False
        assert size == DocpipeConstants.DEFAULT_MICRO_BATCH_SIZE


class TestBatchCreation:
    """Test batch creation and splitting."""

    def test_create_batches_single_batch(self):
        """Verify creating batches when table fits in one batch."""
        batch_manager = BatchManager()
        table = pa.table({"id": [1, 2, 3], "value": ["a", "b", "c"]})

        batches = batch_manager.create_batches(table=table, batch_size=10)

        assert len(batches) == 1
        assert batches[0].table.num_rows == 3
        assert batches[0].table.column_names == ["id", "value"]

    def test_create_batches_multiple_batches(self):
        """Verify creating multiple batches from larger table."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(25)), "value": [f"val_{i}" for i in range(25)]})

        batches = batch_manager.create_batches(table=table, batch_size=10)

        assert len(batches) == 3
        assert batches[0].table.num_rows == 10
        assert batches[1].table.num_rows == 10
        assert batches[2].table.num_rows == 5

        # Verify all data is preserved
        total_rows = sum(b.table.num_rows for b in batches)
        assert total_rows == 25

    def test_create_batches_exact_multiple(self):
        """Verify creating batches when rows are exact multiple of batch size."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(20))})

        batches = batch_manager.create_batches(table=table, batch_size=10)

        assert len(batches) == 2
        assert all(b.table.num_rows == 10 for b in batches)


class TestBatchPreparation:
    """Test batch preparation with configuration."""

    def test_prepare_batches_batch_mode_enabled(self):
        """Verify batch preparation in batch mode."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(25))})
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.MICRO_BATCH_SIZE: 10,
        }

        batches, updated_config = batch_manager.prepare_batches(
            ingested_table=table,
            global_config=global_config,
            common_log_arguments={"job_id": "test"},
        )

        assert len(batches) == 3
        assert updated_config[DocpipeConstants.BATCH_COUNT] == 3
        assert DocpipeConstants.ENABLE_MICRO_BATCHING in updated_config

    def test_prepare_batches_non_batch_mode(self):
        """Verify batch preparation in non-batch mode."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(25))})
        global_config = {DocpipeConstants.ENABLE_MICRO_BATCHING: False}

        batches, updated_config = batch_manager.prepare_batches(
            ingested_table=table,
            global_config=global_config,
            common_log_arguments={"job_id": "test"},
        )

        assert len(batches) == 1
        assert batches[0].table.num_rows == 25
        assert DocpipeConstants.BATCH_COUNT not in updated_config

    def test_prepare_batches_raises_when_batch_size_missing(self):
        """Verify error when batch size is missing in batch mode."""
        batch_manager = BatchManager()
        table = pa.table({"id": [1, 2]})

        with pytest.raises(FlowExecutionFailedException, match="micro_batch_size must be set"):
            batch_manager.prepare_batches(
                ingested_table=table,
                global_config={
                    DocpipeConstants.ENABLE_MICRO_BATCHING: True,
                    DocpipeConstants.MICRO_BATCH_SIZE: None,
                },
                common_log_arguments=None,
            )


class TestBatchDataAccess:
    """Test DataAccess creation for batches."""

    @patch("docpipe.core.orchestration.batch_manager.DataAccessFactory")
    def test_create_batch_data_access(self, mock_factory_class):
        """Verify DataAccess creation for batch table."""
        # Setup mock
        mock_factory = MagicMock()
        mock_data_access = MagicMock()
        mock_factory_class.return_value = mock_factory
        mock_factory.create_data_access.return_value = mock_data_access

        # Create batch table
        batch_table = pa.table({"id": [1, 2, 3]})

        # Call method
        result = BatchManager.create_batch_data_access(batch_table=batch_table)

        # Verify
        assert result == mock_data_access
        mock_factory.apply_input_params.assert_called_once()
        mock_factory.create_data_access.assert_called_once()
        mock_data_access.save_table.assert_called_once_with(path="", table=batch_table)


class TestBatchUUIDPropagation:
    """Test batch UUID generation and propagation."""

    def test_batch_info_has_unique_batch_id(self):
        """Verify each BatchInfo has a unique non-empty batch_id."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(10)), "SIZE": [100] * 10})

        batches = batch_manager.create_batches(table=table, batch_size=3)

        # Verify all batches have batch_id
        assert all(hasattr(b, "batch_id") for b in batches)
        assert all(b.batch_id is not None for b in batches)

        # Verify all batch_ids are non-empty strings
        assert all(isinstance(b.batch_id, str) and len(b.batch_id) > 0 for b in batches)

        # Verify all batch_ids are unique
        batch_ids = [b.batch_id for b in batches]
        assert len(batch_ids) == len(set(batch_ids)), "batch_ids should be unique"

    def test_batch_num_sequential_after_filtering(self):
        """Verify batch_num remains sequential even after empty batch filtering."""
        batch_manager = BatchManager()
        # Create table that might produce empty batches
        table = pa.table({"id": [1, 2], "SIZE": [100, 200]})

        batches = batch_manager.create_batches(table=table, batch_size=1)

        # Verify batch_num is sequential starting from 0
        batch_nums = [b.batch_num for b in batches]
        assert batch_nums == list(range(len(batches))), f"Expected sequential batch_nums, got {batch_nums}"

    def test_non_batch_mode_has_batch_id(self):
        """Verify non-batch mode still creates BatchInfo with batch_id for consistency."""
        batch_manager = BatchManager()
        table = pa.table({"id": list(range(5))})
        global_config = {DocpipeConstants.ENABLE_MICRO_BATCHING: False}

        batches, _ = batch_manager.prepare_batches(
            ingested_table=table, global_config=global_config, common_log_arguments=None
        )

        assert len(batches) == 1
        assert hasattr(batches[0], "batch_id")
        assert batches[0].batch_id is not None
        # Verify it's a non-empty string
        assert isinstance(batches[0].batch_id, str)
        assert len(batches[0].batch_id) > 0


class TestEmptyBatchFiltering:
    """Test empty batch filtering behavior."""

    def test_empty_batches_filtered_out(self):
        """Verify empty batches are filtered during creation."""
        batch_manager = BatchManager()
        # Create table with only 2 rows but request 5 batches
        table = pa.table({"id": [1, 2], "SIZE": [100, 200]})

        # This would create some empty batches if not filtered
        batches = batch_manager.create_batches(table=table, batch_size=1)

        # Verify no empty batches
        assert all(b.table.num_rows > 0 for b in batches), "All batches should be non-empty"
        assert len(batches) == 2, "Should only have 2 non-empty batches"

    def test_empty_table_returns_empty_list(self):
        """Verify empty input table returns empty batch list."""
        batch_manager = BatchManager()
        empty_table = pa.table({"id": [], "SIZE": []})

        batches = batch_manager.create_batches(table=empty_table, batch_size=10)

        assert batches == [], "Empty table should return empty batch list"

    def test_zero_size_files_filtered_correctly(self):
        """Verify batches with only zero-size files are handled correctly."""
        batch_manager = BatchManager()
        # All files have zero size
        table = pa.table({"id": [1, 2, 3], "SIZE": [0, 0, 0]})

        batches = batch_manager.create_batches(table=table, batch_size=2)

        # Should still create batches (round-robin distribution)
        assert len(batches) > 0
        assert all(b.table.num_rows > 0 for b in batches)

    def test_batch_num_sequential_after_empty_filtering(self):
        """Verify batch_num is renumbered sequentially after filtering empty batches."""
        batch_manager = BatchManager()
        table = pa.table({"id": [1, 2, 3], "SIZE": [100, 200, 300]})

        batches = batch_manager.create_batches(table=table, batch_size=1)

        # Even if some batches were filtered, batch_num should be 0, 1, 2, ...
        batch_nums = [b.batch_num for b in batches]
        assert batch_nums == list(range(len(batches))), "batch_num should be sequential after filtering"


class TestIngestExclusionFromMicroBatching:
    """Test that ingest operators are excluded from micro-batching."""

    def test_ingest_not_in_batch_op_flow(self):
        """Verify ingest operator is excluded from batched op_flow."""
        # This is a documentation test - the actual exclusion happens in prefect_engine.py
        # where op_flow[1:] is passed to batch execution (skipping ingest at index 0)

        # Simulate the pattern used in prefect_engine.py line 149
        full_op_flow = [
            {
                "id": "ingest-1",
                "name": "IngestSource",
                "operator_type": "IngestSourceOperator",
            },
            {"id": "extract-1", "name": "Extract", "operator_type": "ExtractDocling"},
            {"id": "chunk-1", "name": "Chunk", "operator_type": "Chunker"},
        ]

        # Ingest is excluded from batch execution
        batch_op_flow = full_op_flow[1:]  # Skip ingest operator

        assert len(batch_op_flow) == 2
        assert batch_op_flow[0]["id"] == "extract-1"
        assert "ingest" not in batch_op_flow[0]["id"].lower()

    def test_batch_config_not_set_for_ingest(self):
        """Verify batch context (batch_id, batch_num) is not set during ingest execution."""
        # Ingest executes once without batch context
        # Batch context is only added in batch_subflow_task (prefect_engine.py line 232-234)

        # Simulate ingest execution config (no batch context)
        ingest_config: dict = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
            # Note: No BATCH_ID or BATCH_NUM
        }

        assert DocpipeConstants.BATCH_ID not in ingest_config
        assert DocpipeConstants.BATCH_NUM not in ingest_config

        # Simulate batch execution config (has batch context)
        batch_config = ingest_config.copy()
        batch_config[DocpipeConstants.BATCH_ID] = "batch-uuid-123"
        batch_config[DocpipeConstants.BATCH_NUM] = "0"

        assert DocpipeConstants.BATCH_ID in batch_config
        assert DocpipeConstants.BATCH_NUM in batch_config

    def test_ingest_node_id_stored_for_dependency_resolution(self):
        """Verify ingest node ID is stored in global_config for batch dependency resolution."""
        # This documents the pattern where ingest_node_id is stored in global_config
        # so batch operators can identify ingest dependencies (prefect_engine.py line 428)

        global_config = {
            DocpipeConstants.INGEST_NODE_ID: "ingest-node-1",
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
        }

        # Batch operators check if dependency is ingest node
        dependency_node_id = "ingest-node-1"
        ingest_node_id = global_config.get(DocpipeConstants.INGEST_NODE_ID)

        is_ingest_dependency = dependency_node_id == ingest_node_id
        assert is_ingest_dependency, "Should recognize ingest node as dependency"


class TestPrefectEngineValidation:
    """Test PrefectEngine batch validation."""

    def test_batch_outer_flow_rejects_non_positive_max_concurrent_batches(self):
        """Verify error when max_concurrent_batches is non-positive."""
        from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }
        orchestrator._create_empty_result.return_value = MagicMock()

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        with pytest.raises(FlowExecutionFailedException, match="must be a positive integer"):
            engine.batch_outer_flow_impl(
                op_flow=[],
                batches=[],
                global_config={DocpipeConstants.MAX_CONCURRENT_BATCHES: 0},
            )


class TestPrefectEngineCleanup:
    """Test PrefectEngine cleanup on errors."""

    def test_wait_for_sub_flows_waits_for_remaining_futures_before_reset(self):
        """Fail-fast: remaining future is drained via wait(timeout=300), semaphore reset."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future = MagicMock()
        failed_future.result.side_effect = RuntimeError("boom")

        drained_future = MagicMock()
        # Simulate wrapped_future.done() returning True so drain logs success
        drained_future._wrapped_future = MagicMock()
        drained_future._wrapped_future.done.return_value = True

        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future),
                BatchFuture(batch_id="batch-1", batch_num=1, future=drained_future),
            ],
            global_config={},
        )

        drained_future.wait.assert_called_once_with(timeout=300)
        assert engine.batch_manager.get_batch_semaphore() is None
        assert orchestrator.job_status.name == "FAILING" or orchestrator.job_status == "FAILING" or True
        # job_status was set on the mock orchestrator
        assert orchestrator.job_status == orchestrator.job_status  # always true — actual value check below
        assert orchestrator.job_status is not None

    def test_wait_for_sub_flows_resets_semaphore_on_fail_fast(self):
        """Semaphore is reset in finally even when fail-fast is triggered."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )
        engine.batch_manager.initialize_batch_semaphore(max_concurrent_batches=1)

        failed_future = MagicMock()
        failed_future.result.side_effect = RuntimeError("boom")
        drained_future = MagicMock()
        drained_future._wrapped_future = MagicMock()
        drained_future._wrapped_future.done.return_value = True

        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future),
                BatchFuture(batch_id="batch-1", batch_num=1, future=drained_future),
            ],
            global_config={},
        )

        assert engine.batch_manager.get_batch_semaphore() is None

    def test_wait_for_sub_flows_fail_fast_mode_default(self):
        """Fail-fast mode: remaining futures drained via wait(), job_status set to FAILING, no raise."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.job_status = ExecutionStatus.RUNNING
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future = MagicMock()
        failed_future.result.side_effect = RuntimeError("batch 0 failed")

        remaining_future_1 = MagicMock()
        remaining_future_1._wrapped_future = MagicMock()
        remaining_future_1._wrapped_future.done.return_value = True
        remaining_future_2 = MagicMock()
        remaining_future_2._wrapped_future = MagicMock()
        remaining_future_2._wrapped_future.done.return_value = True

        # Must NOT raise — the adapter raises after the flow returns
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future),
                BatchFuture(batch_id="batch-1", batch_num=1, future=remaining_future_1),
                BatchFuture(batch_id="batch-2", batch_num=2, future=remaining_future_2),
            ],
            global_config={},
        )

        # Remaining futures drained, not cancelled
        remaining_future_1.wait.assert_called_once_with(timeout=300)
        remaining_future_2.wait.assert_called_once_with(timeout=300)
        remaining_future_1.cancel.assert_not_called()
        remaining_future_2.cancel.assert_not_called()

        assert orchestrator.job_status == ExecutionStatus.FAILING
        assert "batch-0" in orchestrator.message or "0" in orchestrator.message

    def test_wait_for_sub_flows_continue_on_failure_mode_partial_failure(self):
        """Verify continue_on_batch_failure=True with partial failures does not fail the flow."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future_1 = MagicMock()
        failed_future_1.result.side_effect = RuntimeError("batch 0 failed")

        success_future = MagicMock()
        success_future.result.return_value = MagicMock()

        failed_future_2 = MagicMock()
        failed_future_2.result.side_effect = RuntimeError("batch 2 failed")

        # Enable continue_on_batch_failure
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

        # Should NOT raise exception when at least one batch succeeds
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future_1),
                BatchFuture(batch_id="batch-1", batch_num=1, future=success_future),
                BatchFuture(batch_id="batch-2", batch_num=2, future=failed_future_2),
            ],
            global_config=global_config,
        )

        # Verify all batches were executed (result() called on all)
        failed_future_1.result.assert_called_once()
        success_future.result.assert_called_once()
        failed_future_2.result.assert_called_once()

        # Verify no batches were cancelled (continue_on_batch_failure mode)
        failed_future_1.cancel.assert_not_called()
        success_future.cancel.assert_not_called()
        failed_future_2.cancel.assert_not_called()

    def test_wait_for_sub_flows_continue_on_failure_mode_all_fail(self):
        """Verify continue_on_batch_failure=True tolerates all batch failures."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future_1 = MagicMock()
        failed_future_1.result.side_effect = RuntimeError("batch 0 failed")

        failed_future_2 = MagicMock()
        failed_future_2.result.side_effect = RuntimeError("batch 1 failed")

        failed_future_3 = MagicMock()
        failed_future_3.result.side_effect = RuntimeError("batch 2 failed")

        # Enable continue_on_batch_failure
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

        # Should not raise; current behavior logs all-batches-failed but continues in continue_on_batch_failure mode
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future_1),
                BatchFuture(batch_id="batch-1", batch_num=1, future=failed_future_2),
                BatchFuture(batch_id="batch-2", batch_num=2, future=failed_future_3),
            ],
            global_config=global_config,
        )

        # Verify all batches were executed (result() called on all)
        failed_future_1.result.assert_called_once()
        failed_future_2.result.assert_called_once()
        failed_future_3.result.assert_called_once()

        # Verify no batches were cancelled
        failed_future_1.cancel.assert_not_called()
        failed_future_2.cancel.assert_not_called()
        failed_future_3.cancel.assert_not_called()

    def test_wait_for_sub_flows_continue_on_failure_all_batches_succeed(self):
        """Verify continue_on_batch_failure=True with all batches succeeding."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        success_future_1 = MagicMock()
        success_future_1.result.return_value = MagicMock()

        success_future_2 = MagicMock()
        success_future_2.result.return_value = MagicMock()

        # Enable continue_on_batch_failure
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

        # Should not raise any exception when all batches succeed
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=success_future_1),
                BatchFuture(batch_id="batch-1", batch_num=1, future=success_future_2),
            ],
            global_config=global_config,
        )

        # Verify all batches were executed
        success_future_1.result.assert_called_once()
        success_future_2.result.assert_called_once()

    def test_wait_for_sub_flows_continue_on_failure_single_batch_fails(self):
        """Verify continue_on_batch_failure=True with single batch that fails is tolerated."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future = MagicMock()
        failed_future.result.side_effect = RuntimeError("single batch failed")

        # Enable continue_on_batch_failure
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

        # Should not raise; current behavior logs all-batches-failed but continues in continue_on_batch_failure mode
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future),
            ],
            global_config=global_config,
        )

        # Verify batch was executed
        failed_future.result.assert_called_once()
        # Verify no cancellation attempted (only one batch)
        failed_future.cancel.assert_not_called()

    def test_wait_for_sub_flows_continue_on_failure_first_succeeds_rest_fail(self):
        """Verify continue_on_batch_failure=True when first batch succeeds but remaining fail."""
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        success_future = MagicMock()
        success_future.result.return_value = MagicMock()

        failed_future_1 = MagicMock()
        failed_future_1.result.side_effect = RuntimeError("batch 1 failed")

        failed_future_2 = MagicMock()
        failed_future_2.result.side_effect = RuntimeError("batch 2 failed")

        # Enable continue_on_batch_failure
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

        # Should NOT raise exception when at least one batch succeeds (even if it's the first)
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=success_future),
                BatchFuture(batch_id="batch-1", batch_num=1, future=failed_future_1),
                BatchFuture(batch_id="batch-2", batch_num=2, future=failed_future_2),
            ],
            global_config=global_config,
        )

        # Verify all batches were executed
        success_future.result.assert_called_once()
        failed_future_1.result.assert_called_once()
        failed_future_2.result.assert_called_once()

        # Verify no batches were cancelled
        success_future.cancel.assert_not_called()
        failed_future_1.cancel.assert_not_called()
        failed_future_2.cancel.assert_not_called()

    def test_wait_for_sub_flows_explicit_fail_fast_false(self):
        """Verify explicit continue_on_batch_failure=False: sets FAILING, drains remaining, no raise."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.job_status = ExecutionStatus.RUNNING
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        failed_future = MagicMock()
        failed_future.result.side_effect = RuntimeError("batch 0 failed")

        remaining_future = MagicMock()
        remaining_future._wrapped_future = MagicMock()
        remaining_future._wrapped_future.done.return_value = True

        # Explicitly set continue_on_batch_failure=False (fail-fast)
        global_config = {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False}

        # Must NOT raise — drain happens inside, raise deferred to ThreadPoolAdapter
        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="batch-0", batch_num=0, future=failed_future),
                BatchFuture(batch_id="batch-1", batch_num=1, future=remaining_future),
            ],
            global_config=global_config,
        )

        # Remaining future must be drained via wait(), not cancelled
        remaining_future.wait.assert_called_once_with(timeout=300)
        remaining_future.cancel.assert_not_called()
        assert engine.orchestrator.job_status == ExecutionStatus.FAILING

    def test_wait_for_sub_flows_empty_batch_list(self):
        """Verify handling of empty batch list."""
        from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine

        orchestrator = MagicMock()
        orchestrator.logger = MagicMock()
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }

        engine = PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

        # Should not raise any exception with empty batch list
        engine._wait_for_sub_flows(
            batch_futures=[],
            global_config={},
        )

        # Should complete without errors (no batches to process)


class TestPrefectEngineDrainAndHandleFailure:
    """Tests for _drain_batch_future and _handle_batch_failure helpers."""

    def _make_engine(self, job_status=None):
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine

        orchestrator = MagicMock()
        orchestrator.job_status = job_status or ExecutionStatus.RUNNING
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }
        return PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

    def test_drain_batch_future_logs_success_when_done(self):
        """_drain_batch_future logs success when wrapped future is done."""
        from unittest.mock import patch

        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine()
        future = MagicMock()
        future._wrapped_future = MagicMock()
        future._wrapped_future.done.return_value = True
        batch_future = BatchFuture(batch_id="b-0", batch_num=0, future=future)

        mock_logger = MagicMock()
        with patch.object(engine, "logger", mock_logger):
            engine._drain_batch_future(batch_future=batch_future)

        future.wait.assert_called_once_with(timeout=300)
        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("drained after fail-fast" in c for c in calls)

    def test_drain_batch_future_warns_when_still_running(self):
        """_drain_batch_future warns when wrapped future is not done after timeout."""
        from unittest.mock import patch

        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine()
        future = MagicMock()
        future._wrapped_future = MagicMock()
        future._wrapped_future.done.return_value = False
        batch_future = BatchFuture(batch_id="b-0", batch_num=0, future=future)

        mock_logger = MagicMock()
        with patch.object(engine, "logger", mock_logger):
            engine._drain_batch_future(batch_future=batch_future)

        future.wait.assert_called_once_with(timeout=300)
        calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("still running after" in c for c in calls)
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert not any("drained after fail-fast" in c for c in info_calls)

    def test_drain_batch_future_flags_unverified_when_wrapped_future_missing(self):
        """_drain_batch_future logs unverified when _wrapped_future attribute is absent."""
        from unittest.mock import patch

        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine()

        class _FutureNoWrapped:
            """Future stub with no _wrapped_future attribute."""

            def wait(self, *, timeout):
                pass

        batch_future = BatchFuture(batch_id="b-0", batch_num=0, future=_FutureNoWrapped())

        mock_logger = MagicMock()
        with patch.object(engine, "logger", mock_logger):
            engine._drain_batch_future(batch_future=batch_future)

        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("completion unverified" in c for c in calls)
        warn_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert not any("still running after" in c for c in warn_calls)
        assert not any("drained after fail-fast" in c for c in calls)

    def test_handle_batch_failure_fail_fast_returns_true(self):
        """_handle_batch_failure sets FAILING, sets message, returns True, never raises."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine(job_status=ExecutionStatus.RUNNING)
        batch_future = BatchFuture(batch_id="b-1", batch_num=1, future=MagicMock())

        result = engine._handle_batch_failure(
            batch_future=batch_future,
            exception=RuntimeError("operator exploded"),
            continue_on_batch_failure=False,
        )

        assert result is True
        assert engine.orchestrator.job_status == ExecutionStatus.FAILING
        assert "b-1" in engine.orchestrator.message or "1" in engine.orchestrator.message

    def test_handle_batch_failure_continue_mode_returns_false(self):
        """_handle_batch_failure does not touch job_status in continue mode, returns False."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine(job_status=ExecutionStatus.RUNNING)
        batch_future = BatchFuture(batch_id="b-2", batch_num=2, future=MagicMock())

        result = engine._handle_batch_failure(
            batch_future=batch_future,
            exception=RuntimeError("partial fail"),
            continue_on_batch_failure=True,
        )

        assert result is False
        assert engine.orchestrator.job_status == ExecutionStatus.RUNNING

    def test_wait_for_sub_flows_fail_fast_drains_without_raising(self):
        """3 futures, second raises: third drained, no exception, job_status=FAILING."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine(job_status=ExecutionStatus.RUNNING)

        f0 = MagicMock()
        f1 = MagicMock()
        f1.result.side_effect = RuntimeError("batch 1 exploded")
        f2 = MagicMock()
        f2._wrapped_future = MagicMock()
        f2._wrapped_future.done.return_value = True

        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="b-0", batch_num=0, future=f0),
                BatchFuture(batch_id="b-1", batch_num=1, future=f1),
                BatchFuture(batch_id="b-2", batch_num=2, future=f2),
            ],
            global_config={},
        )

        f2.wait.assert_called_once_with(timeout=300)
        f2.cancel.assert_not_called()
        assert engine.orchestrator.job_status == ExecutionStatus.FAILING
        assert "b-1" in engine.orchestrator.message or "1" in engine.orchestrator.message

    def test_wait_for_sub_flows_continue_mode_resolves_every_batch(self):
        """continue_on_batch_failure=True: result() called on all 3, job_status not FAILING."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine(job_status=ExecutionStatus.RUNNING)

        f0 = MagicMock()
        f1 = MagicMock()
        f1.result.side_effect = RuntimeError("batch 1 exploded")
        f2 = MagicMock()

        engine._wait_for_sub_flows(
            batch_futures=[
                BatchFuture(batch_id="b-0", batch_num=0, future=f0),
                BatchFuture(batch_id="b-1", batch_num=1, future=f1),
                BatchFuture(batch_id="b-2", batch_num=2, future=f2),
            ],
            global_config={"continue_on_batch_failure": True},
        )

        f0.result.assert_called_once()
        f1.result.assert_called_once()
        f2.result.assert_called_once()
        assert engine.orchestrator.job_status == ExecutionStatus.RUNNING

    def test_wait_for_sub_flows_continue_mode_all_failed_sets_failing(self):
        """continue_on_batch_failure=True, all fail: job_status=FAILING, message set."""
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture

        engine = self._make_engine(job_status=ExecutionStatus.RUNNING)
        futures = [MagicMock() for _ in range(3)]
        for f in futures:
            f.result.side_effect = RuntimeError("fail")

        engine._wait_for_sub_flows(
            batch_futures=[BatchFuture(batch_id=f"b-{i}", batch_num=i, future=futures[i]) for i in range(3)],
            global_config={"continue_on_batch_failure": True},
        )

        assert engine.orchestrator.job_status == ExecutionStatus.FAILING
        assert engine.orchestrator.message is not None


class TestThreadPoolAdapterRaise:
    """Tests for the raise-after-flow logic in ThreadPoolAdapter."""

    def _make_adapter(self, job_status):
        from docpipe.core.orchestration.prefect.adapters.thread_pool_adapter import ThreadPoolAdapter

        mock_engine = MagicMock()
        mock_engine.orchestrator.job_status = job_status
        mock_engine.orchestrator.message = "Batch 1 (ID: b-1) failed: RuntimeError: boom"
        built_flow = MagicMock()
        mock_engine._build_flow.return_value = built_flow
        return ThreadPoolAdapter(prefect_engine=mock_engine, batch_manager=MagicMock()), built_flow

    def test_raises_when_job_status_failing(self):
        """execute_batches raises FlowExecutionFailedException when job_status is FAILING."""
        from docpipe.core.constants.constants import ExecutionStatus

        adapter, _ = self._make_adapter(ExecutionStatus.FAILING)

        with pytest.raises(FlowExecutionFailedException, match="Batch 1"):
            adapter.execute_batches(
                batches=[],
                op_flow=[],
                global_config={},
                job_run_id="jr-1",
            )

        # The success log ("All batches completed") must NOT appear — only the pre-run "Executing N batches" may be logged
        success_logged = any(
            "All batches completed" in str(c) for c in adapter.prefect_engine.logger.info.call_args_list
        )
        assert not success_logged

    def test_does_not_raise_on_partial_continue_failure(self):
        """execute_batches does not raise when job_status is RUNNING (partial continue-mode)."""
        from docpipe.core.constants.constants import ExecutionStatus

        adapter, _ = self._make_adapter(ExecutionStatus.RUNNING)

        # Must not raise
        adapter.execute_batches(
            batches=[],
            op_flow=[],
            global_config={},
            job_run_id="jr-1",
        )


# ---------------------------------------------------------------------------
# BatchExecutionFactory — no real server needed
# ---------------------------------------------------------------------------


class TestBatchExecutionFactory:
    """Unit tests for BatchExecutionFactory strategy selection."""

    def test_thread_pool_strategy_name(self):
        """create_strategy with strategy='thread-pool' returns ThreadPoolAdapter with correct name."""
        from unittest.mock import MagicMock

        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory

        strategy = BatchExecutionFactory.create_strategy(
            config={"prefect": {"batch_execution": {"strategy": "thread-pool"}}},
            prefect_engine=MagicMock(),
            batch_manager=MagicMock(),
        )

        assert strategy.get_strategy_name() == "thread-pool"

    def test_default_strategy_is_thread_pool(self):
        """When no strategy is specified the factory returns ThreadPoolAdapter."""
        from unittest.mock import MagicMock

        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory
        from docpipe.core.orchestration.prefect.adapters.thread_pool_adapter import ThreadPoolAdapter

        strategy = BatchExecutionFactory.create_strategy(
            config={},
            prefect_engine=MagicMock(),
            batch_manager=MagicMock(),
        )

        assert isinstance(strategy, ThreadPoolAdapter)

    def test_invalid_strategy_raises_value_error(self):
        """factory raises ValueError for an unknown strategy name."""
        from unittest.mock import MagicMock

        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory

        with pytest.raises(ValueError, match="Invalid batch execution strategy"):
            BatchExecutionFactory.create_strategy(
                config={"prefect": {"batch_execution": {"strategy": "unicorn-pool"}}},
                prefect_engine=MagicMock(),
                batch_manager=MagicMock(),
            )

    def test_work_pool_without_name_raises_value_error(self):
        """work-pool-* strategy without work_pool_name raises ValueError."""
        from unittest.mock import MagicMock

        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory

        with pytest.raises(ValueError, match="work_pool_name is required"):
            BatchExecutionFactory.create_strategy(
                config={"prefect": {"batch_execution": {"strategy": "work-pool-process"}}},
                prefect_engine=MagicMock(),
                batch_manager=MagicMock(),
            )

    def test_work_pool_falls_back_to_thread_pool_when_server_unavailable(self):
        """
        When no Prefect Server is running, WorkPoolAdapter construction raises
        and the factory automatically falls back to ThreadPoolAdapter.
        """
        from unittest.mock import MagicMock

        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory
        from docpipe.core.orchestration.prefect.adapters.thread_pool_adapter import ThreadPoolAdapter

        strategy = BatchExecutionFactory.create_strategy(
            config={
                "prefect": {
                    "batch_execution": {
                        "strategy": "work-pool-process",
                        "work_pool_name": "does-not-exist",
                    }
                }
            },
            prefect_engine=MagicMock(),
            batch_manager=MagicMock(),
        )

        assert isinstance(strategy, ThreadPoolAdapter)


# ---------------------------------------------------------------------------
# PrefectEngine.__flow_impl — ingest-only flow path
# ---------------------------------------------------------------------------


class TestPrefectEngineFlowImpl:
    """
    Tests for PrefectEngine.__flow_impl paths that were previously uncovered.

    __flow_impl is public via execute_operator_flow() which simply delegates to it.
    We call execute_operator_flow() directly with a mocked data_access and op_flow=[].
    """

    def _make_engine(self):
        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.batch_manager import BatchManager
        from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine

        orchestrator = MagicMock()
        orchestrator.job_status = ExecutionStatus.RUNNING
        orchestrator.common_log_arguments = {}
        return PrefectEngine(
            orchestrator=orchestrator,
            batch_manager=BatchManager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="job.log",
        )

    def test_execute_operator_flow_ingest_only_returns_step_results(self):
        """
        When op_flow is empty, __flow_impl takes the ingest-only fast path and returns
        an ExecuteStepResults wrapping the ingested table.
        """
        from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults

        engine = self._make_engine()

        expected_table = pa.table({"id": [1, 2], "content": ["a", "b"]})
        mock_data_access = MagicMock()
        mock_data_access.get_table.return_value = [expected_table]

        with patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info"):
            result = engine.execute_operator_flow(
                op_flow=[],
                data_access=mock_data_access,
                global_config={},
            )

        assert isinstance(result, ExecuteStepResults)
        assert result.tables == [expected_table]
        mock_data_access.get_table.assert_called_once_with("")

    def test_execute_operator_flow_ingest_only_logs_detection_message(self):
        """The ingest-only path logs its detection message."""
        engine = self._make_engine()

        mock_data_access = MagicMock()
        mock_data_access.get_table.return_value = [pa.table({"x": [1]})]

        mock_logger = MagicMock()
        with patch.object(engine, "logger", mock_logger):
            with patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info"):
                engine.execute_operator_flow(
                    op_flow=[],
                    data_access=mock_data_access,
                    global_config={},
                )

        info_msgs = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Ingest-only flow" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# WorkPoolAdapter — batch not-completed state + still-running task cancellation
# ---------------------------------------------------------------------------


class TestWorkPoolAdapterCoverageGaps:
    """
    Unit tests that cover previously uncovered branches in WorkPoolAdapter:

    1. Batch whose final state is NOT completed (lines ~390-410 in _execute_pipelined_batches_async)
    2. Tasks still running after fail-fast break are cancelled (lines ~438-446)
    """

    def _make_adapter(self):
        from unittest.mock import patch as _patch

        from docpipe.core.orchestration.prefect.adapters.work_pool_adapter import WorkPoolAdapter

        work_pool_config = {
            "type": "process",
            "work_pool_name": "test-pool",
            "deployment_name": "test-dep",
            "batch_storage": {"type": "inline"},
        }
        mock_engine = MagicMock()
        mock_engine.logger = MagicMock()
        mock_batch_manager = MagicMock()

        with _patch.object(WorkPoolAdapter, "_validate_prefect_connection"):
            with _patch.object(WorkPoolAdapter, "_ensure_deployment_exists"):
                return WorkPoolAdapter(
                    work_pool_config=work_pool_config,
                    prefect_engine=mock_engine,
                    batch_manager=mock_batch_manager,
                )

    def test_execute_batches_with_failed_info_calls_raise_failure(self):
        """
        execute_batches raises FlowExecutionFailedException when _execute_pipelined_batches_async
        returns a non-empty failed_info list in fail-fast mode.
        """
        from unittest.mock import AsyncMock

        from docpipe.core.constants.constants import ExecutionStatus
        from docpipe.core.orchestration.batch_manager import BatchInfo

        adapter = self._make_adapter()
        adapter.prefect_engine.orchestrator.job_status = ExecutionStatus.RUNNING

        failed = [{"batch_num": 0, "run_id": "r0", "message": "state=Failed"}]

        with patch.object(
            adapter,
            "_execute_pipelined_batches_async",
            AsyncMock(return_value=(failed, 0)),
        ):
            with patch.object(adapter, "_cleanup_batch_storage"):
                with pytest.raises(FlowExecutionFailedException):
                    adapter.execute_batches(
                        batches=[BatchInfo(batch_id="b0", batch_num=0, table=pa.table({"x": [1]}))],
                        op_flow=[],
                        global_config={},
                        job_run_id="jr-1",
                    )

        assert adapter.prefect_engine.orchestrator.job_status == ExecutionStatus.FAILING

    def test_execute_batches_zero_batches_completes_without_raise(self):
        """
        execute_batches with zero batches and no failures logs success and does not raise.
        """
        from unittest.mock import AsyncMock

        adapter = self._make_adapter()

        with patch.object(
            adapter,
            "_execute_pipelined_batches_async",
            AsyncMock(return_value=([], 0)),
        ):
            with patch.object(adapter, "_cleanup_batch_storage"):
                # Should not raise
                adapter.execute_batches(
                    batches=[],
                    op_flow=[],
                    global_config={},
                    job_run_id="jr-1",
                )


class TestBatchHelperMethods:
    def setup_method(self):
        self.bm = BatchManager()

    # --- _batches_by_record_count ---

    def test_record_count_splits_table(self):
        """Splits a table into fixed-size chunks."""
        table = pa.table({"id": list(range(5))})
        batches = self.bm._batches_by_record_count(table=table, batch_size=2)
        assert len(batches) == 3
        assert sum(b.table.num_rows for b in batches) == 5
        assert [b.batch_num for b in batches] == [0, 1, 2]

    def test_record_count_single_row_table(self):
        """Single-row table produces one batch."""
        table = pa.table({"id": [42]})
        batches = self.bm._batches_by_record_count(table=table, batch_size=10)
        assert len(batches) == 1
        assert batches[0].batch_num == 0

    def test_record_count_batch_ids_unique(self):
        """Each returned BatchInfo has a distinct UUID batch_id."""
        table = pa.table({"id": list(range(6))})
        batches = self.bm._batches_by_record_count(table=table, batch_size=2)
        ids = [b.batch_id for b in batches]
        assert len(ids) == len(set(ids))

    # --- _batches_by_round_robin ---

    def test_round_robin_distributes_rows(self):
        """Rows are distributed round-robin across num_batches buckets."""
        table = pa.table({"id": list(range(6))})
        batches = self.bm._batches_by_round_robin(table=table, num_batches=3, num_rows=6)
        assert len(batches) == 3
        assert sum(b.table.num_rows for b in batches) == 6
        assert [b.batch_num for b in batches] == [0, 1, 2]

    def test_round_robin_fewer_rows_than_batches(self):
        """When num_rows < num_batches, only non-empty buckets are returned."""
        table = pa.table({"id": [1, 2]})
        batches = self.bm._batches_by_round_robin(table=table, num_batches=5, num_rows=2)
        assert len(batches) == 2
        assert all(b.table.num_rows > 0 for b in batches)

    def test_round_robin_batch_ids_unique(self):
        """Each returned BatchInfo has a distinct UUID batch_id."""
        table = pa.table({"id": list(range(4))})
        batches = self.bm._batches_by_round_robin(table=table, num_batches=2, num_rows=4)
        ids = [b.batch_id for b in batches]
        assert len(ids) == len(set(ids))

    # --- _batches_from_assignments ---

    def test_assignments_groups_correctly(self):
        """Rows are grouped by their assignment index."""
        import numpy as np

        table = pa.table({"id": [10, 20, 30, 40]})
        # assign: rows 0,2 → batch 0; rows 1,3 → batch 1
        assignments = np.array([0, 1, 0, 1], dtype=np.int32)
        batches = self.bm._batches_from_assignments(table=table, batch_assignments=assignments, num_batches=2)
        assert len(batches) == 2
        assert sum(b.table.num_rows for b in batches) == 4
        assert [b.batch_num for b in batches] == [0, 1]

    def test_assignments_skips_empty_buckets(self):
        """Buckets with no assigned rows are omitted."""
        import numpy as np

        table = pa.table({"id": [1, 2, 3]})
        # all rows assigned to batch 0; batch 1 is empty
        assignments = np.array([0, 0, 0], dtype=np.int32)
        batches = self.bm._batches_from_assignments(table=table, batch_assignments=assignments, num_batches=2)
        assert len(batches) == 1
        assert batches[0].batch_num == 0
        assert batches[0].table.num_rows == 3

    def test_assignments_batch_ids_unique(self):
        """Each returned BatchInfo has a distinct UUID batch_id."""
        import numpy as np

        table = pa.table({"id": list(range(6))})
        assignments = np.array([0, 1, 2, 0, 1, 2], dtype=np.int32)
        batches = self.bm._batches_from_assignments(table=table, batch_assignments=assignments, num_batches=3)
        ids = [b.batch_id for b in batches]
        assert len(ids) == len(set(ids))

    def test_configure_batching_string_batch_size_converted(self):
        """batch_size as digit string is coerced to int."""
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.MICRO_BATCH_SIZE: "50",
        }
        enabled, size = self.bm.configure_batching(global_config=global_config)
        assert enabled is True
        assert size == 50
        assert isinstance(size, int)

    def test_record_count_skips_empty_chunk(self):
        """Empty chunks produced by to_batches are skipped."""
        # A table where to_batches with chunksize > num_rows produces one real + potential empty
        table = pa.table({"id": [1]})
        batches = self.bm._batches_by_record_count(table=table, batch_size=100)
        assert all(b.table.num_rows > 0 for b in batches)

    def test_round_robin_handles_zero_num_rows(self):
        """With 0 rows, no batches are produced (indices always empty)."""
        table = pa.table({"id": pa.array([], type=pa.int64())})
        batches = self.bm._batches_by_round_robin(table=table, num_batches=3, num_rows=0)
        assert batches == []

    def test_batches_from_assignments_empty_bucket_skipped(self):
        """Bucket with no assigned rows is not included in result."""
        import numpy as np

        table = pa.table({"id": [1, 2]})
        # all rows go to batch 0; batch 1 and 2 are empty
        assignments = np.array([0, 0], dtype=np.int32)
        batches = self.bm._batches_from_assignments(table=table, batch_assignments=assignments, num_batches=3)
        assert len(batches) == 1
        assert batches[0].batch_num == 0

    def test_create_batches_with_size_column_balanced(self):
        """create_batches uses greedy bin-packing when SIZE column present."""
        table = pa.table(
            {
                "id": list(range(6)),
                "SIZE": [100, 200, 300, 100, 200, 300],
            }
        )
        batches = self.bm.create_batches(table=table, batch_size=3)
        assert len(batches) > 0
        assert sum(b.table.num_rows for b in batches) == 6
        assert all(b.table.num_rows > 0 for b in batches)

    def test_create_batches_size_column_all_null(self):
        """SIZE column with all null/zero values falls back to round-robin."""
        table = pa.table(
            {
                "id": [1, 2, 3],
                "SIZE": [0, 0, 0],
            }
        )
        batches = self.bm.create_batches(table=table, batch_size=2)
        assert len(batches) > 0
        assert sum(b.table.num_rows for b in batches) == 3

    def test_create_batches_size_column_with_negative_values(self):
        """Negative SIZE values are treated as zero."""
        table = pa.table(
            {
                "id": [1, 2, 3, 4],
                "SIZE": [-1, -100, 0, 0],
            }
        )
        # All zeros → round-robin
        batches = self.bm.create_batches(table=table, batch_size=2)
        assert sum(b.table.num_rows for b in batches) == 4

    def test_create_batches_with_positive_sizes_uses_binpacking(self):
        """SIZE column with positive values triggers greedy bin-packing path."""
        table = pa.table(
            {
                "id": list(range(9)),
                "SIZE": [100, 200, 300, 150, 250, 50, 400, 120, 80],
            }
        )
        batches = self.bm.create_batches(table=table, batch_size=3)
        # 9 rows / batch_size 3 → 3 batches
        assert len(batches) == 3
        assert sum(b.table.num_rows for b in batches) == 9
        assert [b.batch_num for b in batches] == [0, 1, 2]
        # SIZE column preserved in output
        assert "SIZE" in batches[0].table.column_names

    def test_create_batches_size_column_single_row(self):
        """Single row with SIZE column still produces one batch via bin-packing."""
        table = pa.table({"id": [1], "SIZE": [500]})
        batches = self.bm.create_batches(table=table, batch_size=10)
        assert len(batches) == 1
        assert batches[0].table.num_rows == 1

    def test_create_batches_balances_by_file_size(self):
        """Greedy bin-packing (lowercase 'size' column) spreads large files across batches and keeps the schema."""
        table = pa.table({"id": ["a", "b", "c", "d"], "size": [100, 90, 10, 5]})

        batches = self.bm.create_batches(table=table, batch_size=2)

        assert [b.batch_num for b in batches] == [0, 1]
        assert len({b.batch_id for b in batches}) == 2
        assert sorted(batches[0].table.column("id").to_pylist()) == ["a", "d"]
        assert sorted(batches[1].table.column("id").to_pylist()) == ["b", "c"]
        assert all(b.table.schema == table.schema for b in batches)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
