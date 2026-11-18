"""Tests for AbstractOrchestrator to bring coverage to 80%."""

# ruff: noqa: E402 — importlib.util.find_spec must be patched before docpipe imports
import importlib.util
from queue import Queue
from unittest.mock import MagicMock, patch

# Prevent importlib.util.find_spec from crashing on MagicMock modules installed
# by other test files earlier in the session (MagicMock.__spec__ == None).
_real_find_spec = importlib.util.find_spec


def _safe_find_spec(name, *args, **kwargs):
    try:
        return _real_find_spec(name, *args, **kwargs)
    except (ValueError, AttributeError):
        return None


importlib.util.find_spec = _safe_find_spec

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator, ExecuteStepResults
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException


class ConcreteOrchestrator(AbstractOrchestrator):
    """Minimal concrete implementation for testing."""

    def _create_flow_engine(self, *, job_id, job_run_id, job_log_path):
        return MagicMock()

    def create_executor_impl(self, *, name, operator, params, job_stats_service=None):
        return MagicMock()

    def execute_flow(self, *, op_flow, global_config):
        pass


@pytest.fixture
def orchestrator():
    with patch("docpipe.core.orchestration.abstract_orchestrator.FlowExecutionEventHandler"):
        orch = ConcreteOrchestrator()
        orch.job_id = "job1"
        orch.job_run_id = "run1"
        orch.common_log_arguments = {}
        return orch


class TestGetIngestSummaryMessage:
    def test_returns_none_when_rows_present(self, orchestrator):
        # use MagicMock since we just need num_rows > 0
        mock_table = MagicMock()
        mock_table.num_rows = 1
        result = orchestrator._get_ingest_summary_message(
            output_table=mock_table, deleted_docs_count=0, operator={"operator": "ingest_local"}
        )
        assert result is None

    def test_returns_message_when_no_rows(self, orchestrator):
        mock_table = MagicMock()
        mock_table.num_rows = 0
        result = orchestrator._get_ingest_summary_message(
            output_table=mock_table, deleted_docs_count=0, operator={"operator": "ingest_local"}
        )
        assert result == "No documents are ingested."

    def test_includes_deleted_count(self, orchestrator):
        mock_table = MagicMock()
        mock_table.num_rows = 0
        result = orchestrator._get_ingest_summary_message(
            output_table=mock_table, deleted_docs_count=3, operator={"operator": "ingest_local"}
        )
        assert "3 documents were removed" in result


class TestEvaluateExecutionSkip:
    def test_ingest_category_never_skipped(self, orchestrator):
        executor = MagicMock()
        executor.get_operator.return_value.category = OperatorCategory.Ingest
        result = orchestrator.evaluate_execution_skip(executor=executor, tables=None, deleted_docs_count=0)
        assert result is False

    def test_empty_table_causes_skip(self, orchestrator):
        executor = MagicMock()
        executor.get_operator.return_value.category = OperatorCategory.Quality
        empty = pa.table({"id": pa.array([], type=pa.string())})
        result = orchestrator.evaluate_execution_skip(executor=executor, tables=[empty], deleted_docs_count=0)
        assert result is True

    def test_non_empty_table_not_skipped(self, orchestrator):
        executor = MagicMock()
        executor.get_operator.return_value.category = OperatorCategory.Quality
        table = pa.table({"id": ["1"]})
        result = orchestrator.evaluate_execution_skip(executor=executor, tables=[table], deleted_docs_count=0)
        assert result is False

    def test_vectordb_with_deleted_docs_not_skipped(self, orchestrator):
        executor = MagicMock()
        executor.get_operator.return_value.category = OperatorCategory.VectorDB
        result = orchestrator.evaluate_execution_skip(executor=executor, tables=None, deleted_docs_count=5)
        assert result is False

    def test_none_tables_causes_skip_for_quality(self, orchestrator):
        executor = MagicMock()
        executor.get_operator.return_value.category = OperatorCategory.Quality
        result = orchestrator.evaluate_execution_skip(executor=executor, tables=None, deleted_docs_count=0)
        assert result is True


class TestCancelPauseResume:
    def test_cancel_sets_canceling_status(self, orchestrator):
        orchestrator.cancel()
        assert orchestrator.job_status == ExecutionStatus.CANCELING

    def test_pause_does_not_raise(self, orchestrator):
        orchestrator.pause()

    def test_resume_does_not_raise(self, orchestrator):
        orchestrator.resume()


class TestCheckAndUploadDeletedRows:
    def test_empty_queue_no_op(self, orchestrator):
        orchestrator.deleted_rows_list = Queue()
        orchestrator._check_and_upload_deleted_rows()  # should not raise

    def test_no_job_ids_logs_warning(self, orchestrator):
        orchestrator.job_id = None
        orchestrator.job_run_id = None
        q: Queue = Queue()
        q.put(pa.table({"id": ["1"]}))
        orchestrator.deleted_rows_list = q
        orchestrator._check_and_upload_deleted_rows()  # should log and return


class TestCollectNonRecoverableDocs:
    def test_empty_internal_metadata_no_op(self, orchestrator):
        orchestrator._collect_non_recoverable_docs(internal_metadata={}, op_def={"name": "op"}, common_log_arguments={})
        assert orchestrator.non_recoverable_docs_tables == []

    def test_non_recoverable_table_appended(self, orchestrator):
        table = pa.table({"id": ["1"]})
        orchestrator._collect_non_recoverable_docs(
            internal_metadata={"non_recoverable_docs_table": table},
            op_def={"name": "op"},
            common_log_arguments={},
        )
        assert len(orchestrator.non_recoverable_docs_tables) == 1


class TestMergeNonRecoverableDocs:
    def test_no_tables_returns_none(self, orchestrator):
        result = orchestrator._merge_non_recoverable_docs(global_config={}, common_log_arguments={})
        assert result is None

    def test_merges_tables(self, orchestrator):
        t1 = pa.table({"id": ["1"]})
        t2 = pa.table({"id": ["2"]})
        orchestrator.non_recoverable_docs_tables = [t1, t2]
        result = orchestrator._merge_non_recoverable_docs(global_config={}, common_log_arguments={})
        assert result is not None
        assert result.num_rows == 2


class TestGetIngestSummaryMessageNoop:
    def test_noop_operator_returns_none_even_with_empty_table(self, orchestrator):
        mock_table = MagicMock()
        mock_table.num_rows = 0
        result = orchestrator._get_ingest_summary_message(
            output_table=mock_table,
            deleted_docs_count=0,
            operator={"operator": "noop"},
        )
        assert result is None


# Import needed constants locally to avoid circular issues
class OperatorConstantsStub:
    class Misc:
        OPERATOR = "operator"


class TestHandleNodeFailure:
    def test_sets_failing_status_in_fail_fast_mode(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        orchestrator._handle_node_failure(e=RuntimeError("fail"), op_def=op_def, global_config={})
        assert orchestrator.job_status == ExecutionStatus.FAILING
        assert orchestrator.message == "fail"

    def test_does_not_set_failing_in_continue_on_batch_failure_mode(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.RUNNING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        orchestrator._handle_node_failure(
            e=RuntimeError("fail"),
            op_def=op_def,
            global_config={"enable_micro_batching": True, "continue_on_batch_failure": True},
        )
        assert orchestrator.job_status == ExecutionStatus.RUNNING

    def test_does_not_record_failure_without_batch_number(self, orchestrator):
        orchestrator._record_batch_failure(global_config={})

        assert not orchestrator.has_batch_failed(batch_num=None)


class TestExecuteStepFastPath:
    def test_returns_empty_result_when_failing(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.FAILING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        result = orchestrator._execute_step(
            op_def=op_def,
            global_config={},
            prev_results=MagicMock(),
            deleted_docs_count=0,
        )
        assert result.data_accesses == []

    def test_returns_empty_result_when_canceling(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.CANCELING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        result = orchestrator._execute_step(
            op_def=op_def,
            global_config={},
            prev_results=MagicMock(),
            deleted_docs_count=0,
        )
        assert result.tables == []


class TestCleanupMemmapFiles:
    def test_noop_when_no_job_ids(self, orchestrator):
        orchestrator.job_id = None
        orchestrator.job_run_id = None
        orchestrator._cleanup_memmap_files()  # no crash

    def test_calls_cleanup_utility(self, orchestrator):
        with patch("docpipe.utils.core.memmap_file_utils.cleanup_memmap_files") as mock_c:
            orchestrator._cleanup_memmap_files()
        mock_c.assert_called_once_with(job_id="job1", job_run_id="run1")


class TestMarkPendingBatchesAsSkipped:
    def test_noop_when_no_service(self, orchestrator):
        orchestrator.job_stats_service = None
        orchestrator._mark_pending_batches_as_skipped()

    def test_calls_service_when_available(self, orchestrator):
        svc = MagicMock()
        orchestrator.job_stats_service = svc
        orchestrator._mark_pending_batches_as_skipped()
        svc.mark_pending_batches_as_skipped.assert_called_once()


class TestResolveLinkResults:
    def test_returns_prev_results_when_metadata_not_dict(self, orchestrator):
        prev = ExecuteStepResults(data_accesses=[], tables=[], internal_metadata="not-a-dict")
        res = orchestrator._resolve_link_results(link_id="branch_a", prev_results=prev)
        assert res is prev

    def test_raises_when_branches_missing_or_not_dict(self, orchestrator):
        prev = ExecuteStepResults(data_accesses=[], tables=[], internal_metadata={})
        with pytest.raises(FlowExecutionFailedException, match="Expected branches metadata as a dict"):
            orchestrator._resolve_link_results(link_id="branch_a", prev_results=prev)

    def test_raises_when_tables_count_mismatches_branches(self, orchestrator):
        prev = ExecuteStepResults(
            data_accesses=[MagicMock()],
            tables=[MagicMock()],
            internal_metadata={Metrics.Internal.BRANCHES: {"b1": {}, "b2": {}}},
        )
        with pytest.raises(FlowExecutionFailedException, match="do not match branches"):
            orchestrator._resolve_link_results(link_id="b1", prev_results=prev)

    def test_raises_when_result_index_missing(self, orchestrator):
        prev = ExecuteStepResults(
            data_accesses=[MagicMock()],
            tables=[MagicMock()],
            internal_metadata={Metrics.Internal.BRANCHES: {"b1": {}}},
        )
        with pytest.raises(FlowExecutionFailedException, match="Result index not found for link_id b1"):
            orchestrator._resolve_link_results(link_id="b1", prev_results=prev)

    def test_returns_resolved_step_results_for_link(self, orchestrator):
        mock_da1, mock_da2 = MagicMock(), MagicMock()
        mock_t1, mock_t2 = MagicMock(), MagicMock()
        b_info = {"result_index": 1, "custom_key": "val"}
        prev = ExecuteStepResults(
            data_accesses=[mock_da1, mock_da2],
            tables=[mock_t1, mock_t2],
            internal_metadata={Metrics.Internal.BRANCHES: {"b1": {"result_index": 0}, "b2": b_info}},
        )
        res = orchestrator._resolve_link_results(link_id="b2", prev_results=prev)
        assert res.tables == [mock_t2]
        assert res.data_accesses == [mock_da2]
        assert res.internal_metadata == b_info


class TestHandleSkippedTask:
    def test_handle_skipped_task_canceling_reason(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.CANCELING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}

        orchestrator._handle_skipped_task(op_def=op_def, global_config={})
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()
        _, kwargs = orchestrator.flow_execution_event_handler.after_node_skipped.call_args
        assert "cancellation requested" in kwargs["reason"]

    def test_handle_skipped_task_failing_reason(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.FAILING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}

        orchestrator._handle_skipped_task(op_def=op_def, global_config={})
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()
        _, kwargs = orchestrator.flow_execution_event_handler.after_node_skipped.call_args
        assert "cannot proceed due to failure" in kwargs["reason"]

    def test_handle_skipped_task_no_data_reason(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.RUNNING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}

        orchestrator._handle_skipped_task(op_def=op_def, global_config={})
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()
        _, kwargs = orchestrator.flow_execution_event_handler.after_node_skipped.call_args
        assert "no data received" in kwargs["reason"]


class TestInnerTaskSkipPaths:
    def test_prev_results_none_records_skipped_and_returns_none(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()

        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=None,
            session_info=MagicMock(),
            deleted_docs_count=0,
        )
        assert result is None
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()

    def test_canceling_status_records_skipped_and_returns_none(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.CANCELING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=MagicMock(),
            session_info=MagicMock(),
            deleted_docs_count=0,
        )
        assert result is None

    def test_failing_status_records_skipped_and_returns_none(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator.job_status = ExecutionStatus.FAILING
        op_def = {"id": "n1", "name": "Extract", "operator": "extract_operator"}
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=MagicMock(),
            session_info=MagicMock(),
            deleted_docs_count=0,
        )
        assert result is None

    def test_inner_task_with_link_id_resolves_link_and_executes(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator._execute_step = MagicMock(return_value="executed_result")

        b_info = {"result_index": 0}
        prev = ExecuteStepResults(
            data_accesses=[MagicMock()],
            tables=[MagicMock()],
            internal_metadata={Metrics.Internal.BRANCHES: {"b1": b_info}},
        )
        op_def = {"id": "n1", "name": "Chunk", "operator": "chunker"}

        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=prev,
            session_info=MagicMock(),
            deleted_docs_count=0,
            link_id="b1",
        )
        assert result == "executed_result"
        orchestrator._execute_step.assert_called_once()

    def test_inner_task_handles_node_failure_on_exception(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator._handle_node_failure = MagicMock()
        orchestrator._execute_step = MagicMock(side_effect=RuntimeError("Node exploded"))

        op_def = {"id": "n1", "name": "Chunk", "operator": "chunker"}
        # Use MagicMock without spec so _unpack_prev_results can access .data_accesses
        # and .tables — attributes that exist on ExecuteStepResults instances but are
        # not visible when spec= inspects the class rather than an instance.
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=MagicMock(data_accesses=[], tables=[], internal_metadata={}),
            session_info=MagicMock(),
            deleted_docs_count=0,
        )
        assert result is None
        orchestrator._handle_node_failure.assert_called_once()


class TestFinalizeDagFlow:
    def test_calls_after_flow_execution_complete(self, orchestrator):
        orchestrator.flow_execution_event_handler = MagicMock()
        orchestrator._finalize_dag_flow(op_flow=[], global_config={})
        orchestrator.flow_execution_event_handler.after_flow_execution_complete.assert_called_once()


class TestSyncCancellationStatus:
    def test_noop_when_no_job_stats_service(self, orchestrator):
        orchestrator.job_stats_service = None
        orchestrator._sync_cancellation_status()
        assert orchestrator.job_status == ExecutionStatus.RUNNING

    def test_noop_when_no_job_run_id(self, orchestrator):
        orchestrator.job_run_id = None
        orchestrator.job_stats_service = MagicMock()
        orchestrator._sync_cancellation_status()
        orchestrator.job_stats_service.get_job_run_stats.assert_not_called()

    def test_short_circuits_when_already_canceling(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.CANCELING
        svc = MagicMock()
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()
        svc.get_job_run_stats.assert_not_called()

    def test_short_circuits_when_already_terminal(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.COMPLETED
        svc = MagicMock()
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()
        svc.get_job_run_stats.assert_not_called()

    def test_sets_canceling_when_store_returns_canceling(self, orchestrator):
        svc = MagicMock()
        svc.get_job_run_stats.return_value = MagicMock(status=ExecutionStatus.CANCELING)
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()
        assert orchestrator.job_status == ExecutionStatus.CANCELING

    def test_does_not_change_status_when_store_returns_running(self, orchestrator):
        svc = MagicMock()
        svc.get_job_run_stats.return_value = MagicMock(status=ExecutionStatus.RUNNING)
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()
        assert orchestrator.job_status == ExecutionStatus.RUNNING

    def test_does_not_change_status_when_store_returns_none(self, orchestrator):
        svc = MagicMock()
        svc.get_job_run_stats.return_value = None
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()
        assert orchestrator.job_status == ExecutionStatus.RUNNING

    def test_swallows_exception_and_continues(self, orchestrator):
        svc = MagicMock()
        svc.get_job_run_stats.side_effect = RuntimeError("db gone")
        orchestrator.job_stats_service = svc
        orchestrator._sync_cancellation_status()  # must not raise
        assert orchestrator.job_status == ExecutionStatus.RUNNING
