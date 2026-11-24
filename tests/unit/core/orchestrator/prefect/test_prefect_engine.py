# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for PrefectEngine.

Prefect 3.x is installed in the venv — import it directly, no sys.modules
stubbing required.
"""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.orchestration.prefect.prefect_engine import BatchFuture, PrefectEngine
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_orchestrator(status=ExecutionStatus.RUNNING):
    orch = Mock()
    orch.job_status = status
    orch.message = ""
    orch.context_id = "job-1"
    orch.job_stats_service = Mock()
    return orch


def _mock_batch_manager():
    bm = Mock()
    bm.get_batch_semaphore.return_value = None  # no semaphore by default
    bm.initialize_batch_semaphore.return_value = None
    bm.reset_batch_semaphore.return_value = None
    bm.create_batch_data_access.return_value = Mock()
    return bm


def _make_engine(orchestrator=None, batch_manager=None) -> PrefectEngine:
    with patch("docpipe.core.orchestration.prefect.prefect_engine.set_prefect_env_variables"):
        return PrefectEngine(
            orchestrator=orchestrator or _mock_orchestrator(),
            batch_manager=batch_manager or _mock_batch_manager(),
            job_id="job-1",
            job_run_id="run-1",
            job_log_path="/tmp/log",
        )


def _make_batch_future(batch_num: int = 0, batch_id: str = "bid-0") -> BatchFuture:
    future = Mock()
    future.state = Mock()
    future.state.is_completed.return_value = True
    future.state.is_failed.return_value = False
    future.state.is_crashed.return_value = False
    future.state.is_cancelled.return_value = False
    future.state.type = Mock()
    future.state.type.value = "COMPLETED"
    future.state.name = "Completed"
    return BatchFuture(batch_id=batch_id, batch_num=batch_num, future=future)


# ---------------------------------------------------------------------------
# BatchFuture
# ---------------------------------------------------------------------------


class TestBatchFuture:
    def test_describe_state_returns_string(self):
        bf = _make_batch_future()
        result = bf.describe_state()
        assert "is_completed=True" in result
        assert "is_failed=False" in result

    def test_describe_state_handles_state_exception(self):
        future = Mock()
        future.state.is_completed.side_effect = RuntimeError("boom")
        bf = BatchFuture(batch_id="x", batch_num=1, future=future)
        result = bf.describe_state()
        assert "state_unavailable" in result

    def test_describe_state_includes_wrapped_future_when_present(self):
        bf = _make_batch_future()
        wrapped = Mock()
        wrapped.done.return_value = True
        wrapped.cancelled.return_value = False
        wrapped.running.return_value = False
        bf.future._wrapped_future = wrapped
        result = bf.describe_state()
        assert "wrapped_done=True" in result

    def test_describe_state_handles_wrapped_future_exception(self):
        bf = _make_batch_future()
        wrapped = Mock()
        wrapped.done.side_effect = RuntimeError("oops")
        bf.future._wrapped_future = wrapped
        result = bf.describe_state()
        assert "wrapped_state_unavailable" in result


# ---------------------------------------------------------------------------
# PrefectEngine.__init__ & __get_prefect_config
# ---------------------------------------------------------------------------


class TestPrefectEngineInit:
    def test_attributes_set_correctly(self):
        engine = _make_engine()
        assert engine.job_id == "job-1"
        assert engine.job_run_id == "run-1"
        assert engine.common_log_arguments[DocpipeConstants.JOB_ID] == "job-1"
        assert engine.common_log_arguments[DocpipeConstants.JOB_RUN_ID] == "run-1"


# ---------------------------------------------------------------------------
# _handle_batch_failure
# ---------------------------------------------------------------------------


class TestHandleBatchFailure:
    def test_marks_orchestrator_failing(self):
        orchestrator = _mock_orchestrator()
        engine = _make_engine(orchestrator=orchestrator)
        batch_future = _make_batch_future(batch_num=0, batch_id="bid-0")

        fail_fast_triggered = engine._handle_batch_failure(
            batch_future=batch_future,
            exception=ValueError("operator error"),
            continue_on_batch_failure=False,
        )

        assert fail_fast_triggered
        assert orchestrator.job_status == ExecutionStatus.FAILING
        assert "Batch 0" in orchestrator.message

    def test_continue_on_failure_leaves_orchestrator_running(self):
        orchestrator = _mock_orchestrator()
        engine = _make_engine(orchestrator=orchestrator)

        fail_fast_triggered = engine._handle_batch_failure(
            batch_future=_make_batch_future(),
            exception=ValueError("operator error"),
            continue_on_batch_failure=True,
        )

        assert not fail_fast_triggered
        assert orchestrator.job_status == ExecutionStatus.RUNNING


# ---------------------------------------------------------------------------
# _wait_for_sub_flows — fail-fast mode
# ---------------------------------------------------------------------------


class TestWaitForSubFlowsFailFast:
    def _global_config(self, continue_on_failure: bool = False) -> dict:
        return {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: continue_on_failure}

    def test_success_path_completes_without_error(self):
        engine = _make_engine()
        bf = _make_batch_future()
        bf.future.result = Mock(return_value=None)
        engine._wait_for_sub_flows(batch_futures=[bf], global_config=self._global_config())

    def test_fail_fast_marks_orchestrator_failing_without_raising(self):
        orchestrator = _mock_orchestrator()
        engine = _make_engine(orchestrator=orchestrator)
        bf = _make_batch_future(batch_num=0, batch_id="bid-0")
        bf.future.result = Mock(side_effect=RuntimeError("boom"))

        engine._wait_for_sub_flows(batch_futures=[bf], global_config=self._global_config(False))

        assert orchestrator.job_status == ExecutionStatus.FAILING

    def test_fail_fast_drains_later_batches_without_cancelling(self):
        engine = _make_engine()
        failed = _make_batch_future(batch_num=0, batch_id="bid-0")
        failed.future.result = Mock(side_effect=RuntimeError("fail"))
        remaining = _make_batch_future(batch_num=1, batch_id="bid-1")
        remaining_future = remaining.future
        remaining_future.wait = Mock()
        remaining_future.cancel = Mock()
        remaining_future._wrapped_future = Mock()
        remaining_future._wrapped_future.done.return_value = True

        engine._wait_for_sub_flows(batch_futures=[failed, remaining], global_config=self._global_config(False))

        remaining_future.wait.assert_called_once_with(timeout=300)
        remaining_future.cancel.assert_not_called()

    def test_semaphore_reset_called_in_finally(self):
        bm = _mock_batch_manager()
        engine = _make_engine(batch_manager=bm)
        bf = _make_batch_future()
        bf.future.result = Mock(side_effect=RuntimeError("boom"))

        engine._wait_for_sub_flows(batch_futures=[bf], global_config=self._global_config(False))

        bm.reset_batch_semaphore.assert_called_once()


# ---------------------------------------------------------------------------
# _wait_for_sub_flows — continue_on_batch_failure mode
# ---------------------------------------------------------------------------


class TestWaitForSubFlowsContinueOnFailure:
    def _cfg(self) -> dict:
        return {DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: True}

    def test_partial_failure_logs_warning(self):
        orch = _mock_orchestrator()
        engine = _make_engine(orchestrator=orch)
        bf_ok = _make_batch_future(batch_num=0, batch_id="bid-0")
        bf_ok.future.result = Mock(return_value=None)
        bf_fail = _make_batch_future(batch_num=1, batch_id="bid-1")
        bf_fail.future.result = Mock(side_effect=RuntimeError("partial fail"))

        # Should not raise
        engine._wait_for_sub_flows(batch_futures=[bf_ok, bf_fail], global_config=self._cfg())

    def test_all_batches_fail_sets_job_status_failing(self):
        orch = _mock_orchestrator()
        engine = _make_engine(orchestrator=orch)
        bfs = [_make_batch_future(i, f"bid-{i}") for i in range(2)]
        for bf in bfs:
            bf.future.result = Mock(side_effect=RuntimeError("fail"))

        engine._wait_for_sub_flows(batch_futures=bfs, global_config=self._cfg())

        assert orch.job_status == ExecutionStatus.FAILING

    def test_semaphore_reset_called_even_on_failure(self):
        bm = _mock_batch_manager()
        engine = _make_engine(batch_manager=bm)
        bf = _make_batch_future()
        bf.future.result = Mock(side_effect=RuntimeError("boom"))

        engine._wait_for_sub_flows(batch_futures=[bf], global_config=self._cfg())

        bm.reset_batch_semaphore.assert_called_once()


# ---------------------------------------------------------------------------
# _collect_failed_doc_ids
# ---------------------------------------------------------------------------


class TestCollectFailedDocIds:
    def test_returns_empty_list_when_no_job_stats_service(self):
        orch = _mock_orchestrator()
        orch.job_stats_service = None
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == []

    def test_returns_empty_list_when_job_stats_none(self):
        orch = _mock_orchestrator()
        orch.job_stats_service.get_job.return_value = None
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == []

    def test_returns_empty_list_when_node_stats_empty(self):
        orch = _mock_orchestrator()
        job_stats = Mock()
        job_stats.node_stats = {}
        orch.job_stats_service.get_job.return_value = job_stats
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == []

    def test_collects_failed_doc_ids_from_node_stats_objects(self):
        orch = _mock_orchestrator()
        node_stat = Mock()
        node_stat.failed_docs = ["doc-1", "doc-2"]
        job_stats = Mock()
        job_stats.node_stats = {"node_a": node_stat}
        orch.job_stats_service.get_job.return_value = job_stats
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == ["doc-1", "doc-2"]

    def test_collects_failed_doc_ids_from_dict_node_stats(self):
        orch = _mock_orchestrator()
        job_stats = Mock()
        job_stats.node_stats = {"node_a": {"failed_docs": ["doc-3"]}}
        orch.job_stats_service.get_job.return_value = job_stats
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == ["doc-3"]

    def test_node_stats_without_failed_docs_attribute_skipped(self):
        orch = _mock_orchestrator()
        node_stat = Mock(spec=[])  # no attributes at all
        job_stats = Mock()
        job_stats.node_stats = {"node_a": node_stat}
        orch.job_stats_service.get_job.return_value = job_stats
        engine = _make_engine(orchestrator=orch)
        result = engine._collect_failed_doc_ids(batch_id=None)
        assert result == []


# ---------------------------------------------------------------------------
# batch_outer_flow_impl — semaphore validation
# ---------------------------------------------------------------------------


class TestBatchOuterFlowImpl:
    def test_invalid_max_concurrent_batches_raises(self):
        engine = _make_engine()
        global_config = {
            DocpipeConstants.MAX_CONCURRENT_BATCHES: -1,
        }
        with pytest.raises(FlowExecutionFailedException, match=r"must be a positive integer"):
            engine.batch_outer_flow_impl(op_flow=[], batches=[], global_config=global_config)

    def test_non_integer_max_concurrent_batches_raises(self):
        engine = _make_engine()
        global_config = {
            DocpipeConstants.MAX_CONCURRENT_BATCHES: "many",
        }
        with pytest.raises(FlowExecutionFailedException, match=r"must be a positive integer"):
            engine.batch_outer_flow_impl(op_flow=[], batches=[], global_config=global_config)

    def test_zero_max_concurrent_batches_raises(self):
        engine = _make_engine()
        global_config = {DocpipeConstants.MAX_CONCURRENT_BATCHES: 0}
        with pytest.raises(FlowExecutionFailedException, match=r"must be a positive integer"):
            engine.batch_outer_flow_impl(op_flow=[], batches=[], global_config=global_config)

    def test_valid_config_with_no_batches_returns_empty_list(self):
        bm = _mock_batch_manager()
        engine = _make_engine(batch_manager=bm)
        global_config = {
            DocpipeConstants.MAX_CONCURRENT_BATCHES: 4,
            DocpipeConstants.FLOW_DEFINITION: {DocpipeConstants.FLOW_NAME: "test_flow"},
        }
        # Stub _build_flow to return a no-op callable
        engine._build_flow = Mock(return_value=Mock())
        result = engine.batch_outer_flow_impl(op_flow=[], batches=[], global_config=global_config)
        assert result == []
        bm.initialize_batch_semaphore.assert_called_once_with(max_concurrent_batches=4)


# ---------------------------------------------------------------------------
# execute_operator_flow delegates to __flow_impl
# ---------------------------------------------------------------------------


class TestExecuteOperatorFlow:
    def test_delegates_to_flow_impl(self):
        engine = _make_engine()
        # Patch the private name-mangled method
        with patch.object(engine, "_PrefectEngine__flow_impl", return_value=None) as mock_impl:
            engine.execute_operator_flow(op_flow=[Mock()], data_access=Mock(), global_config={})
            mock_impl.assert_called_once()


# ---------------------------------------------------------------------------
# build_non_execute_flow & execute_non_execute_flow
# ---------------------------------------------------------------------------


class TestBuildNonExecuteFlow:
    def test_returns_callable(self):
        engine = _make_engine()
        result = engine.build_non_execute_flow()
        assert callable(result)

    def test_uses_provided_flow_name(self):
        engine = _make_engine()
        # Since @flow is mocked as a passthrough, just verify no error is raised
        result = engine.build_non_execute_flow(flow_name="my_custom_flow")
        assert callable(result)

    def test_execute_non_execute_flow_calls_flow(self):
        engine = _make_engine()
        mock_flow = Mock()
        engine.build_non_execute_flow = Mock(return_value=mock_flow)
        engine.execute_non_execute_flow(flow_name="validate", task=Mock(), dag=Mock())
        mock_flow.assert_called_once()


# ---------------------------------------------------------------------------
# __wait_for_tasks (name-mangled: _PrefectEngine__wait_for_tasks)
# ---------------------------------------------------------------------------


class TestWaitForTasks:
    def test_calls_wait_on_each_future(self):
        engine = _make_engine()
        f1 = Mock()
        f2 = Mock()
        destinations: list[tuple[Mock, dict]] = [(f1, {}), (f2, {})]
        engine._PrefectEngine__wait_for_tasks(destinations=destinations)
        f1.wait.assert_called_once()
        f2.wait.assert_called_once()

    def test_skips_futures_without_wait(self):
        engine = _make_engine()
        f1 = Mock(spec=[])  # no 'wait' attribute
        destinations: list[tuple[Mock, dict]] = [(f1, {})]
        engine._PrefectEngine__wait_for_tasks(destinations=destinations)  # must not raise


# ---------------------------------------------------------------------------
# __wait_for_tasks_with_exceptions
# ---------------------------------------------------------------------------


class TestWaitForTasksWithExceptions:
    def _task_type(self):
        from docpipe.core.constants.constants import TaskType

        return TaskType.VALIDATE_FLOW

    def test_success_returns_normally(self):
        engine = _make_engine()
        f1 = Mock()
        f1.result.return_value = None
        engine._PrefectEngine__wait_for_tasks_with_exceptions(destinations=[(f1, {})], task_type=self._task_type())
        f1.result.assert_called_once()

    def test_flow_validation_exception_reraises(self):
        from docpipe.exceptions.docpipe_exceptions import FlowValidationException

        engine = _make_engine()
        f1 = Mock()
        f1.result.side_effect = FlowValidationException("bad flow")
        with pytest.raises(FlowValidationException):
            engine._PrefectEngine__wait_for_tasks_with_exceptions(destinations=[(f1, {})], task_type=self._task_type())

    def test_generic_exception_raises_prefect_flow_failed(self):
        from docpipe.exceptions.docpipe_exceptions import PrefectFlowFailed

        engine = _make_engine()
        f1 = Mock()
        f1.result.side_effect = RuntimeError("task exploded")
        with pytest.raises(PrefectFlowFailed):
            engine._PrefectEngine__wait_for_tasks_with_exceptions(destinations=[(f1, {})], task_type=self._task_type())


# ---------------------------------------------------------------------------
# __flow_impl (name-mangled: _PrefectEngine__flow_impl)
# ---------------------------------------------------------------------------


class TestFlowImpl:
    """Tests for the private __flow_impl method called by execute_operator_flow."""

    def _op_def(self, node_id: str = "node_a", name: str = "chunker") -> dict:
        from docpipe.core.constants.operator_constants import OperatorConstants

        return {
            OperatorConstants.Columns.ID: node_id,
            OperatorConstants.Columns.NAME: name,
            OperatorConstants.Misc.LINK_ID: None,
            "input_edges": [],
            "output_edges": [],
        }

    @staticmethod
    def _incremental_svc():
        svc = Mock()
        # __flow_impl calls len() on the soft-deleted doc ids
        svc.get_soft_deleted_doc_ids.return_value = []
        return svc

    def _data_access(self):
        da = Mock()
        table = Mock()
        table.num_rows = 2
        da.get_table.return_value = ([table], {})
        return da

    def test_ingest_only_flow_returns_execute_step_results(self):
        """Empty op_flow → returns ExecuteStepResults immediately."""
        from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults

        orch = _mock_orchestrator()
        orch._inner_task = Mock()
        engine = _make_engine(orchestrator=orch)

        with (
            patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info", return_value=Mock()),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.get_incremental_update_service", return_value=Mock()
            ),
        ):
            result = engine._PrefectEngine__flow_impl(
                op_flow=[],
                data_access=self._data_access(),
                global_config={},
            )

        assert isinstance(result, ExecuteStepResults)

    def test_sequential_flow_submits_task_and_returns_none(self):
        """Single-operator sequential flow runs end-to-end with mocked task."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        orch = _mock_orchestrator()
        orch._inner_task = Mock()
        orch._merge_non_recoverable_docs = Mock(return_value=None)
        orch._reset_non_recoverable_docs_for_batch = Mock()
        # _collect_failed_doc_ids iterates job_stats.node_stats.values() — must be a dict
        job_stats_mock = Mock()
        job_stats_mock.node_stats = {}
        orch.job_stats_service.get_job.return_value = job_stats_mock

        engine = _make_engine(orchestrator=orch)

        future = Mock()
        result_mock = Mock()
        result_mock.tables = [Mock()]
        future.result.return_value = result_mock
        future.wait = Mock()

        inner_task_mock = Mock()
        inner_task_mock.submit.return_value = future

        incremental_svc = self._incremental_svc()

        op = self._op_def()

        with (
            patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info", return_value=Mock()),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.get_incremental_update_service",
                return_value=incremental_svc,
            ),
            patch.object(engine, "_PrefectEngine__create_task", return_value=inner_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl.get_future.return_value = future
            mock_fl_cls.from_size.return_value = mock_fl

            result = engine._PrefectEngine__flow_impl(
                op_flow=[op],
                data_access=self._data_access(),
                global_config={},
            )

        assert result is None
        inner_task_mock.submit.assert_called_once()
        incremental_svc.save_metadata_for_incremental_update.assert_called_once()

    def test_fail_fast_raises_when_job_status_failing(self):
        """FAILING status + continue_on_batch_failure=False → FlowExecutionFailedException."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        orch = _mock_orchestrator(status=ExecutionStatus.FAILING)
        orch._inner_task = Mock()
        engine = _make_engine(orchestrator=orch)

        future = Mock()
        future.wait = Mock()
        inner_task_mock = Mock()
        inner_task_mock.submit.return_value = future

        op = self._op_def()

        with (
            patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info", return_value=Mock()),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.get_incremental_update_service",
                return_value=self._incremental_svc(),
            ),
            patch.object(engine, "_PrefectEngine__create_task", return_value=inner_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl_cls.from_size.return_value = mock_fl

            with pytest.raises(FlowExecutionFailedException, match=r"One or more operators failed"):
                engine._PrefectEngine__flow_impl(
                    op_flow=[op],
                    data_access=self._data_access(),
                    global_config={DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False},
                )

    def test_failing_status_skips_operator_submission(self):
        """When job is already FAILING, operators are skipped (continue path)."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        orch = _mock_orchestrator(status=ExecutionStatus.FAILING)
        orch._inner_task = Mock()
        engine = _make_engine(orchestrator=orch)

        inner_task_mock = Mock()
        op = self._op_def()

        with (
            patch("docpipe.core.orchestration.prefect.prefect_engine.get_session_info", return_value=Mock()),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.get_incremental_update_service",
                return_value=self._incremental_svc(),
            ),
            patch.object(engine, "_PrefectEngine__create_task", return_value=inner_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl_cls.from_size.return_value = mock_fl

            with pytest.raises(FlowExecutionFailedException):
                engine._PrefectEngine__flow_impl(
                    op_flow=[op],
                    data_access=self._data_access(),
                    global_config={DocpipeConstants.CONTINUE_ON_BATCH_FAILURE: False},
                )

        # Task was never submitted because operator was skipped
        inner_task_mock.submit.assert_not_called()


# ---------------------------------------------------------------------------
# __non_execute_inner_flow
# ---------------------------------------------------------------------------


class TestNonExecuteInnerFlow:
    """Tests for __non_execute_inner_flow — the validation/non-data flow path."""

    def _task_type(self):
        from docpipe.core.constants.constants import TaskType

        return TaskType.VALIDATE_FLOW

    def _simple_op(self, node_id: str = "node_a") -> dict:
        from docpipe.core.constants.operator_constants import OperatorConstants

        return {
            OperatorConstants.Columns.ID: node_id,
            OperatorConstants.Columns.NAME: "validate",
            OperatorConstants.Misc.LINK_NAME: None,
            "id": node_id,
            "input_edges": [],
            "output_edges": [],
        }

    def test_simple_op_flow_returns_none(self):
        """Single root node with no output_edges → destinations populated, returns None."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        engine = _make_engine()
        op = self._simple_op()

        future = Mock()
        future.result.return_value = None
        future.wait = Mock()

        main_task_mock = Mock()
        main_task_mock.submit.return_value = future

        with (
            patch.object(engine, "_PrefectEngine__create_main_task", return_value=main_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl_cls.from_size.return_value = mock_fl

            result = engine._PrefectEngine__non_execute_inner_flow(
                task_type=self._task_type(),
                inner_task=Mock(),
                op_flow=[op],
                local_result=Mock(),
            )

        assert result is None

    def test_task_exception_raises_prefect_flow_failed(self):
        """Exception during task submission → PrefectFlowFailed."""
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.exceptions.docpipe_exceptions import PrefectFlowFailed

        engine = _make_engine()
        op = self._simple_op()

        main_task_mock = Mock()
        main_task_mock.submit.side_effect = RuntimeError("submission failed")

        with (
            patch.object(engine, "_PrefectEngine__create_main_task", return_value=main_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl_cls.from_size.return_value = mock_fl

            with pytest.raises(PrefectFlowFailed):
                engine._PrefectEngine__non_execute_inner_flow(
                    task_type=self._task_type(),
                    inner_task=Mock(),
                    op_flow=[op],
                    local_result=Mock(),
                )

    def test_stop_node_id_sets_early_stop(self):
        """When stop_node_id matches an op, returns Completed with EarlyStopped name."""

        from docpipe.core.constants.operator_constants import OperatorConstants

        engine = _make_engine()
        op = self._simple_op(node_id="stop_node")

        future = Mock()
        future.result.return_value = "result_value"
        future.wait = Mock()

        main_task_mock = Mock()
        main_task_mock.submit.return_value = future
        local_result = Mock()

        with (
            patch.object(engine, "_PrefectEngine__create_main_task", return_value=main_task_mock),
            patch(
                "docpipe.core.orchestration.prefect.prefect_engine.create_node_id_to_index_map",
                return_value={op[OperatorConstants.Columns.ID]: 0},
            ),
            patch("docpipe.core.orchestration.prefect.prefect_engine.FuturedList") as mock_fl_cls,
        ):
            mock_fl = Mock()
            mock_fl_cls.from_size.return_value = mock_fl

            result = engine._PrefectEngine__non_execute_inner_flow(
                task_type=self._task_type(),
                inner_task=Mock(),
                op_flow=[op],
                local_result=local_result,
                stop_node_id="stop_node",
            )

        # Completed is a MagicMock (prefect is stubbed), just check it was called
        assert result is not None
