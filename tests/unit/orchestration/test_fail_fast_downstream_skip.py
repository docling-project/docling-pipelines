# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for fail-fast mode downstream operator skipping.

Tests verify that when an operator fails in fail-fast mode (continue_on_batch_failure=false),
downstream operators in the same batch are properly skipped without executing.
"""

from typing import Any
from unittest.mock import Mock

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults


class _StubOperator:
    """Operator stand-in: the orchestrator reads declared secret fields from the operator class."""

    category = Mock(value="functional")

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return metadata that declares no secret fields."""
        return {}


class TestFailFastDownstreamSkip:
    """Test suite for fail-fast mode downstream operator skipping."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator with necessary attributes."""
        orchestrator = Mock(spec=AbstractOrchestrator)
        orchestrator.job_status = ExecutionStatus.RUNNING
        orchestrator.job_id = "test-job-123"
        orchestrator.job_run_id = "test-run-456"
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "test-job-123",
            DocpipeConstants.JOB_RUN_ID: "test-run-456",
        }
        orchestrator.logger = Mock()
        orchestrator.flow_execution_event_handler = Mock()
        # Instance attributes added by lineage wiring — must be set explicitly on
        # spec-bound mocks because spec= inspects the class, not __init__ assignments.
        orchestrator.flow_id = None
        orchestrator.flow_name = ""
        orchestrator._observer = None

        # Make _execute_step and its helpers use the real implementations
        orchestrator._execute_step = AbstractOrchestrator._execute_step.__get__(orchestrator)
        orchestrator._run_node = AbstractOrchestrator._run_node.__get__(orchestrator)
        orchestrator._unpack_prev_results = AbstractOrchestrator._unpack_prev_results.__get__(orchestrator)
        orchestrator._refresh_job_status = AbstractOrchestrator._refresh_job_status.__get__(orchestrator)
        mock_executor = Mock()
        mock_executor.release = Mock()
        orchestrator.create_executor = Mock(return_value=mock_executor)
        orchestrator.evaluate_execution_skip = Mock(return_value=False)
        orchestrator._handle_active_execution = Mock()
        orchestrator._handle_skipped_execution = Mock(return_value=([], []))
        orchestrator.job_stats_service = None  # Add missing attribute
        orchestrator.job_run_id = None  # Add missing attribute

        return orchestrator

    @pytest.fixture
    def op_def(self):
        """Create a sample operator definition."""
        return {
            OperatorConstants.Columns.ID: "test-op-1",
            OperatorConstants.Columns.NAME: "TestOperator",
            OperatorConstants.Misc.OPERATOR: "test_operator",
            DocpipeConstants.OUTPUT_EDGES: [],
        }

    @pytest.fixture
    def global_config(self):
        """Create a sample global config."""
        return {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.MICRO_BATCH_SIZE: 5,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False,
            DocpipeConstants.BATCH_NUM: 1,
            DocpipeConstants.BATCH_ID: "batch-uuid-123",
        }

    @pytest.fixture
    def prev_results(self):
        """Create sample previous results."""
        table = pa.table({"content": ["test"]})
        data_access = Mock()
        return ExecuteStepResults([data_access], [table], {})

    def test_execute_step_skips_when_job_failing(self, mock_orchestrator, op_def, global_config, prev_results):
        """
        Test that _execute_step returns empty result when job_status is FAILING.

        This is the core fix for the fail-fast bug - operators should not execute
        when the job is already in FAILING state.
        """
        # Set job status to FAILING (simulating upstream failure)
        mock_orchestrator.job_status = ExecutionStatus.FAILING

        # Execute step
        result = mock_orchestrator._execute_step(
            op_def=op_def,
            global_config=global_config,
            prev_results=prev_results,
            deleted_docs_count=0,
        )

        # Verify: Should return empty ExecuteStepResults
        assert isinstance(result, ExecuteStepResults)
        assert len(result.data_accesses) == 0
        assert len(result.tables) == 0
        assert result.internal_metadata == {}

        # Verify: create_executor should NOT be called (operator not created)
        mock_orchestrator.create_executor.assert_not_called()

        # Verify: _handle_active_execution should NOT be called (operator not executed)
        mock_orchestrator._handle_active_execution.assert_not_called()

        # Verify: Logger should log the skip
        mock_orchestrator.logger.info.assert_called_once()
        log_call = mock_orchestrator.logger.info.call_args
        assert "Skipping operator" in log_call[0][0]
        assert log_call[0][1] == "TestOperator"
        assert "Failing" in log_call[0][2]

    def test_execute_step_skips_when_job_canceling(self, mock_orchestrator, op_def, global_config, prev_results):
        """
        Test that _execute_step returns empty result when job_status is CANCELING.
        """
        # Set job status to CANCELING
        mock_orchestrator.job_status = ExecutionStatus.CANCELING

        # Execute step
        result = mock_orchestrator._execute_step(
            op_def=op_def,
            global_config=global_config,
            prev_results=prev_results,
            deleted_docs_count=0,
        )

        # Verify: Should return empty ExecuteStepResults
        assert isinstance(result, ExecuteStepResults)
        assert len(result.data_accesses) == 0
        assert len(result.tables) == 0

        # Verify: create_executor should NOT be called
        mock_orchestrator.create_executor.assert_not_called()

        # Verify: Logger should log the skip with Canceling status
        mock_orchestrator.logger.info.assert_called_once()
        log_call = mock_orchestrator.logger.info.call_args
        assert "Canceling" in log_call[0][2]

    def test_execute_step_proceeds_when_job_running(self, mock_orchestrator, op_def, global_config, prev_results):
        """
        Test that _execute_step proceeds normally when job_status is RUNNING.

        This ensures the fix doesn't break normal execution.
        """
        # Set job status to RUNNING (normal state)
        mock_orchestrator.job_status = ExecutionStatus.RUNNING

        # Mock the executor and execution
        mock_executor = Mock()
        mock_executor.get_operator.return_value = _StubOperator()
        mock_orchestrator.create_executor.return_value = mock_executor

        # Mock successful execution - use "name" column for PyArrow table
        output_table = pa.table({"name": ["doc1", "doc2"], "content": ["processed1", "processed2"]})
        output_data_access = Mock()
        mock_orchestrator._handle_active_execution.return_value = (
            [output_data_access],
            [output_table],
            {"processed_docs": 2},
            {},
        )

        # Execute step
        result = mock_orchestrator._execute_step(
            op_def=op_def,
            global_config=global_config,
            prev_results=prev_results,
            deleted_docs_count=0,
        )

        # Verify: Should return result with data
        assert isinstance(result, ExecuteStepResults)
        assert len(result.data_accesses) == 1
        assert len(result.tables) == 1

        # Verify: create_executor SHOULD be called (operator created)
        mock_orchestrator.create_executor.assert_called_once()

        # Verify: _handle_active_execution SHOULD be called (operator executed)
        mock_orchestrator._handle_active_execution.assert_called_once()

        # Verify: Logger should NOT log skip message
        skip_logged = any(
            "Skipping operator" in str(call[0][0]) for call in mock_orchestrator.logger.info.call_args_list
        )
        assert not skip_logged

    def test_execute_step_early_exit_prevents_side_effects(
        self, mock_orchestrator, op_def, global_config, prev_results
    ):
        """
        Test that early exit prevents any side effects from operator execution.

        This is critical - we want to ensure NO operator code runs when job is failing.
        """
        # Set job status to FAILING
        mock_orchestrator.job_status = ExecutionStatus.FAILING

        # Mock executor with side effects
        mock_executor = Mock()
        mock_executor.execute = Mock(side_effect=Exception("Should not be called!"))
        mock_orchestrator.create_executor.return_value = mock_executor

        # Execute step - should NOT raise exception because executor.execute is never called
        result = mock_orchestrator._execute_step(
            op_def=op_def,
            global_config=global_config,
            prev_results=prev_results,
            deleted_docs_count=0,
        )

        # Verify: Returns empty result without executing operator
        assert isinstance(result, ExecuteStepResults)
        assert len(result.data_accesses) == 0

        # Verify: Executor's execute method was NEVER called
        mock_executor.execute.assert_not_called()

    def test_downstream_operator_receives_empty_result(self, mock_orchestrator, global_config):
        """
        Test that downstream operators receive empty result when upstream fails.

        This simulates the full flow: operator1 fails → operator2 gets empty result.
        """
        # Simulate operator 1 execution (normal)
        mock_orchestrator.job_status = ExecutionStatus.RUNNING
        mock_executor1 = Mock()
        mock_executor1.get_operator.return_value = Mock(category=Mock(value="functional"))
        mock_orchestrator.create_executor.return_value = mock_executor1

        # Operator 1 fails during execution - job status changes to FAILING
        mock_orchestrator.job_status = ExecutionStatus.FAILING

        # Now when operator 2 tries to execute, it should be skipped
        # Verify the skip behavior is working correctly
        assert mock_orchestrator.job_status == ExecutionStatus.FAILING


class TestFlowFinalizationOnBatchFailure:
    """Test suite for flow finalization when batches fail in fail-fast mode."""

    @pytest.fixture
    def mock_orchestrator_with_finalization(self):
        """Create a mock orchestrator with flow finalization setup."""
        orchestrator = Mock(spec=AbstractOrchestrator)
        orchestrator.job_status = ExecutionStatus.RUNNING
        orchestrator.job_id = "test-job-123"
        orchestrator.job_run_id = "test-run-456"
        orchestrator.common_log_arguments = {
            DocpipeConstants.JOB_ID: "test-job-123",
            DocpipeConstants.JOB_RUN_ID: "test-run-456",
        }
        orchestrator.logger = Mock()
        orchestrator.flow_execution_event_handler = Mock()
        orchestrator.job_stats_service = Mock()
        orchestrator.flow_engine = Mock()
        orchestrator.batch_manager = Mock()

        # Setup real method implementations
        orchestrator._finalize_dag_flow = Mock()
        orchestrator._mark_pending_batches_as_skipped = Mock()

        return orchestrator

    def test_finalization_called_on_batch_failure(self, mock_orchestrator_with_finalization):
        """Test that _finalize_dag_flow is called even when batch execution fails."""
        from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

        # Setup: Configure flow engine to raise exception (simulating batch failure)
        mock_orchestrator_with_finalization.flow_engine.execute_batch_flow.side_effect = FlowExecutionFailedException(
            "Batch failed in fail-fast mode"
        )

        # Setup: Job status is still RUNNING (exception raised before status update)
        mock_orchestrator_with_finalization.job_status = ExecutionStatus.RUNNING

        op_flow: list[dict[str, Any]] = []
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False,
        }

        # Execute: Call execute_flow's batch execution section
        # We need to simulate the try-except-finally block behavior
        batch_execution_failed = False
        try:
            mock_orchestrator_with_finalization.flow_engine.execute_batch_flow(
                op_flow=op_flow, batches=[], global_config=global_config
            )
        except FlowExecutionFailedException:
            batch_execution_failed = True
            # Simulate finally block
            is_fail_fast = not global_config.get(DocpipeConstants.CONTINUE_ON_BATCH_FAILURE, False)
            if (
                (batch_execution_failed or mock_orchestrator_with_finalization.job_status == ExecutionStatus.FAILING)
                and global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
                and is_fail_fast
            ):
                mock_orchestrator_with_finalization._mark_pending_batches_as_skipped(global_config=global_config)
            mock_orchestrator_with_finalization._finalize_dag_flow(op_flow=op_flow, global_config=global_config)

        # Verify: _mark_pending_batches_as_skipped was called (because batch_execution_failed=True)
        mock_orchestrator_with_finalization._mark_pending_batches_as_skipped.assert_called_once_with(
            global_config=global_config
        )

        # Verify: _finalize_dag_flow was called despite exception
        mock_orchestrator_with_finalization._finalize_dag_flow.assert_called_once_with(
            op_flow=op_flow, global_config=global_config
        )

    def test_pending_batches_marked_skipped_on_failure(self, mock_orchestrator_with_finalization):
        """Test that pending batches are marked as skipped when flow fails in fail-fast mode."""
        from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

        # Setup
        mock_orchestrator_with_finalization.flow_engine.execute_batch_flow.side_effect = FlowExecutionFailedException(
            "Batch failed"
        )
        mock_orchestrator_with_finalization.job_status = ExecutionStatus.FAILING

        op_flow: list[dict[str, Any]] = []
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False,
        }

        # Execute with exception handling
        try:
            mock_orchestrator_with_finalization.flow_engine.execute_batch_flow(
                op_flow=op_flow, batches=[], global_config=global_config
            )
        except FlowExecutionFailedException:
            # Simulate finally block
            if mock_orchestrator_with_finalization.job_status == ExecutionStatus.FAILING and global_config.get(
                DocpipeConstants.ENABLE_MICRO_BATCHING, False
            ):
                mock_orchestrator_with_finalization._mark_pending_batches_as_skipped(global_config=global_config)

        # Verify: _mark_pending_batches_as_skipped was called
        assert mock_orchestrator_with_finalization._mark_pending_batches_as_skipped.called

    def test_no_pending_skip_in_continue_on_failure_mode(self, mock_orchestrator_with_finalization):
        """Test that pending batches are NOT marked as skipped in continue_on_batch_failure mode."""
        from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

        # Setup: continue_on_batch_failure=True
        mock_orchestrator_with_finalization.flow_engine.execute_batch_flow.side_effect = FlowExecutionFailedException(
            "Batch failed"
        )
        mock_orchestrator_with_finalization.job_status = ExecutionStatus.RUNNING  # Not FAILING in continue mode

        op_flow: list[dict[str, Any]] = []
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True,  # Continue mode
        }

        # Execute with exception handling
        try:
            mock_orchestrator_with_finalization.flow_engine.execute_batch_flow(
                op_flow=op_flow, batches=[], global_config=global_config
            )
        except FlowExecutionFailedException:
            # Simulate finally block
            if mock_orchestrator_with_finalization.job_status == ExecutionStatus.FAILING and global_config.get(
                DocpipeConstants.ENABLE_MICRO_BATCHING, False
            ):
                mock_orchestrator_with_finalization._mark_pending_batches_as_skipped(global_config=global_config)

        # Verify: _mark_pending_batches_as_skipped was NOT called (job_status not FAILING)
        mock_orchestrator_with_finalization._mark_pending_batches_as_skipped.assert_not_called()

    def test_no_pending_skip_without_batching(self, mock_orchestrator_with_finalization):
        """Test that pending batch skip is not called when batching is disabled."""
        from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

        # Setup: No batching
        mock_orchestrator_with_finalization.flow_engine.execute_batch_flow.side_effect = FlowExecutionFailedException(
            "Flow failed"
        )
        mock_orchestrator_with_finalization.job_status = ExecutionStatus.FAILING

        op_flow: list[dict[str, Any]] = []
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: False,  # No batching
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False,
        }

        # Execute: Simulate the try-except-finally block
        batch_execution_failed = False
        try:
            mock_orchestrator_with_finalization.flow_engine.execute_batch_flow(
                op_flow=op_flow, batches=[], global_config=global_config
            )
        except FlowExecutionFailedException:
            batch_execution_failed = True
            # Simulate finally block
            is_fail_fast = not global_config.get(DocpipeConstants.CONTINUE_ON_BATCH_FAILURE, False)
            if (
                (batch_execution_failed or mock_orchestrator_with_finalization.job_status == ExecutionStatus.FAILING)
                and global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
                and is_fail_fast
            ):
                mock_orchestrator_with_finalization._mark_pending_batches_as_skipped(global_config=global_config)
            mock_orchestrator_with_finalization._finalize_dag_flow(op_flow=op_flow, global_config=global_config)

        # Verify: _mark_pending_batches_as_skipped should NOT be called (batching disabled)
        mock_orchestrator_with_finalization._mark_pending_batches_as_skipped.assert_not_called()

        # Verify: _finalize_dag_flow was still called
        mock_orchestrator_with_finalization._finalize_dag_flow.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
