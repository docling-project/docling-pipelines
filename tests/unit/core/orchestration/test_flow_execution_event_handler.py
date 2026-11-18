"""Unit tests for FlowExecutionEventHandler."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.orchestration.flow_execution_event_handler import FlowExecutionEventHandler


@pytest.fixture
def mock_job_stats_service():
    service = MagicMock()
    service.cancel_job_run_if_cancelling.return_value = False
    return service


@pytest.fixture
def mock_job_run_manager():
    return MagicMock()


@pytest.fixture
def mock_execution_reporter():
    return MagicMock()


@pytest.fixture
def handler(mock_job_stats_service, mock_job_run_manager, mock_execution_reporter):
    h = FlowExecutionEventHandler(
        job_stats_service=mock_job_stats_service,
        job_run_manager=mock_job_run_manager,
        execution_reporter=mock_execution_reporter,
    )
    h.job_id = "job-123"
    h.job_run_id = "run-456"
    h.flow_id = "flow-789"
    h.job_log_path = "/tmp/logs/job_stats.json"
    h.common_log_arguments = {"job_id": "job-123", "job_run_id": "run-456"}
    return h


@pytest.fixture
def handler_no_services():
    return FlowExecutionEventHandler()


class TestInitialization:
    """Test FlowExecutionEventHandler initialization."""

    def test_default_init(self):
        handler = FlowExecutionEventHandler()
        assert handler.job_stats_service is None
        assert handler.job_run_manager is None
        assert handler.execution_reporter is None

    def test_init_with_services(self, mock_job_stats_service, mock_job_run_manager, mock_execution_reporter):
        handler = FlowExecutionEventHandler(
            job_stats_service=mock_job_stats_service,
            job_run_manager=mock_job_run_manager,
            execution_reporter=mock_execution_reporter,
        )
        assert handler.job_stats_service is mock_job_stats_service
        assert handler.job_run_manager is mock_job_run_manager
        assert handler.execution_reporter is mock_execution_reporter


class TestBeforeFlowExecutionStart:
    """Test before_flow_execution_start event handler."""

    def test_with_execution_reporter_and_flow_def(self, handler, mock_execution_reporter):
        flow_def = {DocpipeConstants.NAME: "Test Flow", DocpipeConstants.DAG: [{"id": "1"}, {"id": "2"}]}
        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)
        mock_execution_reporter.print_flow_header.assert_called_once_with(flow_name="Test Flow", operator_count=2)

    def test_without_execution_reporter(self, handler, mock_job_stats_service):
        handler.execution_reporter = None
        flow_def = {DocpipeConstants.NAME: "Test Flow", DocpipeConstants.DAG: []}
        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)
        mock_job_stats_service.start_tracking_job.assert_called_once()

    def test_cancels_job_if_cancelling(self, handler, mock_job_stats_service):
        mock_job_stats_service.cancel_job_run_if_cancelling.return_value = True
        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=None)
        mock_job_stats_service.start_tracking_job.assert_not_called()

    def test_no_job_stats_service(self, handler_no_services):
        # Should not raise
        handler_no_services.job_id = "job-1"
        handler_no_services.job_run_id = "run-1"
        handler_no_services.common_log_arguments = {}
        handler_no_services.before_flow_execution_start(orchestrator=MagicMock(), flow_def=None)


class TestAfterFlowExecutionComplete:
    """Test after_flow_execution_complete event handler."""

    def test_no_job_stats_service_logs_warning(self, handler_no_services):
        handler_no_services.job_run_id = "run-1"
        handler_no_services.common_log_arguments = {}
        # Should not raise
        handler_no_services.after_flow_execution_complete(
            op_flow=[], present_job_status=ExecutionStatus.COMPLETED, message=None
        )

    def test_canceling_status_sets_canceled(self, handler, mock_job_stats_service):
        job_stats_mock = MagicMock()
        job_stats_mock.node_stats = {}
        mock_job_stats_service.get_job.return_value = job_stats_mock
        with patch.object(handler, "_start_background_report_generation"):
            handler.after_flow_execution_complete(
                op_flow=[], present_job_status=ExecutionStatus.CANCELING, message="Canceled"
            )
        mock_job_stats_service.end_job.assert_called_once()
        call_kwargs = mock_job_stats_service.end_job.call_args[1]
        assert call_kwargs["status"] == ExecutionStatus.CANCELED.value

    def test_failing_status_sets_failed(self, handler, mock_job_stats_service):
        job_stats_mock = MagicMock()
        job_stats_mock.node_stats = {}
        mock_job_stats_service.get_job.return_value = job_stats_mock
        with patch.object(handler, "_start_background_report_generation"):
            handler.after_flow_execution_complete(
                op_flow=[], present_job_status=ExecutionStatus.FAILING, message="Error"
            )
        mock_job_stats_service.end_job.assert_called_once()
        call_kwargs = mock_job_stats_service.end_job.call_args[1]
        assert call_kwargs["status"] == ExecutionStatus.FAILED.value

    def test_completed_status_determines_from_node_stats(self, handler, mock_job_stats_service):
        node_stats_mock = MagicMock()
        node_stats_mock.node_status = "Completed"
        job_stats_mock = MagicMock()
        job_stats_mock.node_stats = {"node1": node_stats_mock}
        mock_job_stats_service.get_job.return_value = job_stats_mock

        with patch(
            "docpipe.core.operators.operator_utils.OperatorUtils.determine_final_job_status",
            return_value=ExecutionStatus.COMPLETED,
        ):
            handler.after_flow_execution_complete(
                op_flow=[], present_job_status=ExecutionStatus.COMPLETED, message=None
            )
        mock_job_stats_service.end_job.assert_called()

    def test_prints_flow_summary_when_reporter_present(self, handler, mock_job_stats_service, mock_execution_reporter):
        job_stats_mock = MagicMock()
        job_stats_mock.node_stats = {}
        mock_job_stats_service.get_job.return_value = job_stats_mock

        with patch(
            "docpipe.core.operators.operator_utils.OperatorUtils.determine_final_job_status",
            return_value=ExecutionStatus.COMPLETED,
        ):
            handler.after_flow_execution_complete(
                op_flow=[], present_job_status=ExecutionStatus.COMPLETED, message=None
            )
        mock_execution_reporter.print_flow_summary.assert_called_once()


class TestBeforeStepExecutionStart:
    """Test before_step_execution_start event handler."""

    def test_prints_operator_start_when_not_skipped(self, handler, mock_execution_reporter):
        handler.before_step_execution_start(
            node_id="n1",
            node_name="extract",
            global_config={"operator_type": "ExtractOperator"},
            job_status=ExecutionStatus.RUNNING,
            prev_results=MagicMock(),
        )
        mock_execution_reporter.print_operator_start.assert_called_once_with(
            step_name="extract", operator_type="ExtractOperator"
        )

    def test_does_not_print_when_prev_results_is_none(self, handler, mock_execution_reporter):
        handler.before_step_execution_start(
            node_id="n1",
            node_name="extract",
            global_config=None,
            job_status=ExecutionStatus.RUNNING,
            prev_results=None,
        )
        mock_execution_reporter.print_operator_start.assert_not_called()

    def test_does_not_print_when_canceling(self, handler, mock_execution_reporter):
        handler.before_step_execution_start(
            node_id="n1",
            node_name="extract",
            global_config=None,
            job_status=ExecutionStatus.CANCELING,
            prev_results=MagicMock(),
        )
        mock_execution_reporter.print_operator_start.assert_not_called()

    def test_does_not_print_when_failing(self, handler, mock_execution_reporter):
        handler.before_step_execution_start(
            node_id="n1",
            node_name="extract",
            global_config=None,
            job_status=ExecutionStatus.FAILING,
            prev_results=MagicMock(),
        )
        mock_execution_reporter.print_operator_start.assert_not_called()


class TestAfterStepExecutionComplete:
    """Test after_step_execution_complete event handler."""

    def test_updates_doc_counts_and_framework_status(self, handler, mock_job_stats_service, mock_job_run_manager):
        from docpipe.core.operators.abstract_operator import OperatorCategory

        handler.after_step_execution_complete(
            node_id="n1",
            node_name="ingest",
            operator_category=OperatorCategory.Ingest,
            operator=MagicMock(),
            global_config={},
            is_last_step=False,
            metadata={"total_docs_count": 5},
            start_time=0,
            tables=None,
        )
        mock_job_stats_service.update_doc_counts.assert_called_once()


class TestAfterNodeSkipped:
    """Test after_node_skipped event handler."""

    def test_calls_skip_node_execution(self, handler, mock_job_stats_service):
        handler.after_node_skipped(
            node_id="n1",
            node_name="extract",
            operator_type="ExtractOperator",
            global_config={},
            start_time=0,
            end_time=1,
            column_names=["id", "content"],
        )
        mock_job_stats_service.skip_node_execution.assert_called_once()

    def test_skips_with_micro_batching_context(self, handler, mock_job_stats_service):
        global_config = {
            DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            DocpipeConstants.BATCH_ID: "batch-1",
            DocpipeConstants.BATCH_NUM: 0,
        }
        handler.after_node_skipped(
            node_id="n1",
            node_name="extract",
            operator_type="ExtractOperator",
            global_config=global_config,
            start_time=0,
            end_time=1,
            column_names=[],
        )
        call_kwargs = mock_job_stats_service.skip_node_execution.call_args[1]
        assert call_kwargs["batch_id"] == "batch-1"


class TestAfterNodeFailure:
    """Test after_node_failure event handler."""

    def test_calls_fail_node_execution(self, handler, mock_job_stats_service, mock_job_run_manager):
        job_stats_mock = MagicMock()
        mock_job_stats_service.get_job.return_value = job_stats_mock

        handler.after_node_failure(node_id="n1", node_name="extract", global_config={}, e=RuntimeError("Test error"))
        mock_job_stats_service.fail_node_execution.assert_called_once()
        mock_job_run_manager.update_job_run_status.assert_called()

    def test_no_job_stats_service(self, handler):
        handler.job_stats_service = None
        # Should not raise even without services
        with patch.object(handler, "_update_framework_status"):
            handler.after_node_failure(node_id="n1", node_name="extract", global_config={}, e=RuntimeError("Error"))


class TestAfterBatchesPrepared:
    """Test after_batches_prepared event handler."""

    def test_skips_when_micro_batching_disabled(self, handler, mock_job_stats_service):
        handler.after_batches_prepared(
            batches=[],
            op_flow=[{"id": "n1", "name": "ingest"}, {"id": "n2", "name": "extract"}],
            global_config={DocpipeConstants.ENABLE_MICRO_BATCHING: False},
        )
        mock_job_stats_service.create_pending_batch_node_stats.assert_not_called()

    def test_creates_pending_stats_when_micro_batching_enabled(self, handler, mock_job_stats_service):
        from docpipe.core.orchestration.batch_manager import BatchInfo

        batches = [
            BatchInfo(batch_id="batch-1", batch_num=0, table=MagicMock()),
            BatchInfo(batch_id="batch-2", batch_num=1, table=MagicMock()),
        ]
        op_flow = [
            {"id": "n0", "name": "ingest"},
            {"id": "n1", "name": "extract"},
            {"id": "n2", "name": "chunk"},
        ]
        handler.after_batches_prepared(
            batches=batches,
            op_flow=op_flow,
            global_config={DocpipeConstants.ENABLE_MICRO_BATCHING: True},
        )
        mock_job_stats_service.create_pending_batch_node_stats.assert_called_once()

    def test_no_job_stats_service_skips(self, handler):
        handler.job_stats_service = None
        # Should not raise
        handler.after_batches_prepared(
            batches=[MagicMock()],
            op_flow=[{"id": "n1"}],
            global_config={DocpipeConstants.ENABLE_MICRO_BATCHING: True},
        )


class TestShouldPrintOperatorSummary:
    """Test _should_print_operator_summary static method."""

    def test_non_batch_mode_always_returns_true(self):
        node_stats = MagicMock()
        job_stats = MagicMock()
        result = FlowExecutionEventHandler._should_print_operator_summary(
            node_id="n1",
            node_stats=node_stats,
            global_config=None,
            job_stats=job_stats,
        )
        assert result is True

    def test_non_batch_mode_with_no_batch_id(self):
        result = FlowExecutionEventHandler._should_print_operator_summary(
            node_id="n1",
            node_stats=MagicMock(),
            global_config={},
            job_stats=MagicMock(),
        )
        assert result is True

    def test_batch_mode_no_batch_records_returns_false(self):
        job_stats = MagicMock()
        job_stats.batch_node_stats = {}
        result = FlowExecutionEventHandler._should_print_operator_summary(
            node_id="n1",
            node_stats=MagicMock(),
            global_config={DocpipeConstants.BATCH_ID: "batch-1"},
            job_stats=job_stats,
        )
        assert result is False


class TestGetCompleteJobStats:
    """Test _get_complete_job_stats helper."""

    def test_no_job_stats_service_returns_message(self, handler):
        handler.job_stats_service = None
        result = handler._get_complete_job_stats(message="Error occurred")
        assert result == {"message": "Error occurred"}

    def test_no_job_stats_service_returns_none_when_no_message(self, handler):
        handler.job_stats_service = None
        result = handler._get_complete_job_stats()
        assert result is None

    def test_returns_job_stats_with_message(self, handler, mock_job_stats_service):
        job_stats_mock = MagicMock()
        job_stats_mock.model_dump.return_value = {"job_id": "123", "status": "running"}
        mock_job_stats_service.get_job.return_value = job_stats_mock

        result = handler._get_complete_job_stats(message="Done")
        assert result["message"] == "Done"
        assert result["job_id"] == "123"


class TestUpdateFrameworkStatus:
    """Test _update_framework_status helper."""

    def test_calls_job_run_manager(self, handler, mock_job_run_manager):
        handler._update_framework_status(status="Running", job_run_stats={"count": 1})
        mock_job_run_manager.update_job_run_status.assert_called_once()

    def test_no_job_run_manager_does_nothing(self, handler):
        handler.job_run_manager = None
        # Should not raise
        handler._update_framework_status(status="Running")

    def test_framework_exception_is_swallowed(self, handler, mock_job_run_manager):
        mock_job_run_manager.update_job_run_status.side_effect = RuntimeError("Framework error")
        # Should not raise
        handler._update_framework_status(status="Running")


# ---------------------------------------------------------------------------
# Flow-identity tests  (added by fix-job-stats-flow-identity)
# ---------------------------------------------------------------------------
# Covers all three execution paths from the event-handler's perspective:
#
#   PATH 1 - API  : session_info.flow_id = asset UUID (patched before submit)
#   PATH 2 - CLI  : session_info.flow_id = job_id slug (set by run_command_line_executor)
#   PATH 3 - Library: session_info.flow_id = UUID or job_id (set by DocpipeFlowManager)
#
# The event handler is path-agnostic: it reads self.flow_id from SessionInfo
# during initialize() and forwards it unchanged into start_tracking_job.
# ---------------------------------------------------------------------------


class TestFlowIdentityEventHandler:
    """
    Verifies that FlowExecutionEventHandler.before_flow_execution_start calls
    start_tracking_job with:
      - flow_id = self.flow_id (whatever was set during initialize)
      - flow_name = flow_def["name"] when present, None when absent
    Covers all three execution paths by varying self.flow_id.
    """

    # ------------------------------------------------------------------
    # PATH 1 — API: event handler receives asset UUID as flow_id
    # ------------------------------------------------------------------

    def test_api_path_start_tracking_uses_asset_uuid(self, handler, mock_job_stats_service):
        """
        After session_info.flow_id is patched to the asset UUID in _create_job_run,
        the event handler must forward that UUID verbatim to start_tracking_job.
        """
        handler.flow_id = "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        flow_def = {DocpipeConstants.NAME: "flow_06_oct_2026_11_16_PM-jyoti", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        mock_job_stats_service.start_tracking_job.assert_called_once_with(
            job_id="job-123",
            job_run_id="run-456",
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_name="flow_06_oct_2026_11_16_PM-jyoti",
        )

    def test_api_path_flow_id_not_overwritten_by_flow_name(self, handler, mock_job_stats_service):
        """
        flow_id must remain the asset UUID — not be replaced by the human name.
        """
        handler.flow_id = "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        flow_def = {DocpipeConstants.NAME: "My Flow Name", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        assert call_kwargs["flow_name"] == "My Flow Name"

    # ------------------------------------------------------------------
    # PATH 2 — CLI: event handler receives job_id slug as flow_id
    # ------------------------------------------------------------------

    def test_cli_path_start_tracking_uses_job_id_slug(self, handler, mock_job_stats_service):
        """
        CLI sets session_info.flow_id = flow_def.get("flow_id", job_id) which
        resolves to the job_id slug when the compiled flow has no flow_id key.
        The event handler must forward that slug as flow_id.
        """
        handler.flow_id = "my-flow-a3f2b1"  # job_id slug set by CLI
        flow_def = {DocpipeConstants.NAME: "my-flow", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "my-flow-a3f2b1"
        assert call_kwargs["flow_name"] == "my-flow"

    def test_cli_path_flow_name_from_flow_def_name(self, handler, mock_job_stats_service):
        """
        The CLI does not call start_tracking_job directly. Tracking happens only
        in before_flow_execution_start. flow_name must come from flow_def["name"],
        not from self.flow_id.
        """
        handler.flow_id = "my-flow-a3f2b1"
        flow_def = {DocpipeConstants.NAME: "my-flow", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        # Exactly one call — CLI has no QUEUED pre-call from _create_job_run
        assert mock_job_stats_service.start_tracking_job.call_count == 1
        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_name"] == "my-flow"

    # ------------------------------------------------------------------
    # PATH 3 — Library: event handler receives UUID or job_id as flow_id
    # ------------------------------------------------------------------

    def test_library_path_start_tracking_uses_uuid_flow_id(self, handler, mock_job_stats_service):
        """
        DocpipeFlowManager sets session_info.flow_id = flow_id or flow_def_flow_id or job_id.
        When no explicit flow_id is given, this resolves to a UUID job_id.
        The event handler must forward that UUID as flow_id.
        """
        handler.flow_id = "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a"  # UUID job_id
        flow_def = {DocpipeConstants.NAME: "My Notebook Flow", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a"
        assert call_kwargs["flow_name"] == "My Notebook Flow"

    # ------------------------------------------------------------------
    # Edge cases common to all paths
    # ------------------------------------------------------------------

    def test_flow_id_falls_back_to_unknown_when_none(self, handler, mock_job_stats_service):
        """
        When self.flow_id is None (session_info was never patched), the event
        handler must use the literal string "unknown" rather than passing None.
        """
        handler.flow_id = None
        flow_def = {DocpipeConstants.NAME: "Some Flow", DocpipeConstants.DAG: []}

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "unknown"
        assert call_kwargs["flow_name"] == "Some Flow"

    def test_flow_name_is_none_when_flow_def_has_no_name(self, handler, mock_job_stats_service):
        """
        When flow_def exists but has no "name" key, flow_name must be None —
        not raised, not defaulted to self.flow_id.
        """
        handler.flow_id = "my-flow-slug"
        flow_def: dict = {DocpipeConstants.DAG: []}  # no "name" key

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=flow_def)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "my-flow-slug"
        assert call_kwargs["flow_name"] is None

    def test_flow_name_is_none_when_flow_def_absent(self, handler, mock_job_stats_service):
        """
        When flow_def is None entirely, flow_name must be None.
        """
        handler.flow_id = "my-flow-slug"

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def=None)

        call_kwargs = mock_job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "my-flow-slug"
        assert call_kwargs["flow_name"] is None

    def test_start_tracking_job_not_called_when_job_is_cancelling(self, handler, mock_job_stats_service):
        """
        If the job is being cancelled, start_tracking_job must not be called
        regardless of the flow_id value.
        """
        mock_job_stats_service.cancel_job_run_if_cancelling.return_value = True
        handler.flow_id = "any-flow-id"

        handler.before_flow_execution_start(orchestrator=MagicMock(), flow_def={DocpipeConstants.NAME: "My Flow"})

        mock_job_stats_service.start_tracking_job.assert_not_called()


class TestFlowIdentityInitialize:
    """
    Verifies that FlowExecutionEventHandler.initialize() reads flow_id from
    the current thread's SessionInfo, not from any hard-coded or default value.
    Covers all three paths by varying the SessionInfo.flow_id value.
    """

    @patch("docpipe.core.orchestration.flow_execution_event_handler.get_session_info")
    def test_initialize_reads_flow_id_from_session_info_api_path(self, mock_get_session_info):
        """PATH 1 — API: session_info carries asset UUID after the patch in _create_job_run."""
        from docpipe.core.models.session_info import SessionInfo

        session = SessionInfo(flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a")
        mock_get_session_info.return_value = session

        h = FlowExecutionEventHandler()
        h.initialize(job_id="job-1", job_run_id="run-1", common_log_arguments={})

        assert h.flow_id == "5f429668-ded4-41b5-80b9-f1d6278dc07a"

    @patch("docpipe.core.orchestration.flow_execution_event_handler.get_session_info")
    def test_initialize_reads_flow_id_from_session_info_cli_path(self, mock_get_session_info):
        """PATH 2 — CLI: session_info carries job_id slug."""
        from docpipe.core.models.session_info import SessionInfo

        session = SessionInfo(flow_id="my-flow-a3f2b1")
        mock_get_session_info.return_value = session

        h = FlowExecutionEventHandler()
        h.initialize(job_id="my-flow-a3f2b1", job_run_id="run-1", common_log_arguments={})

        assert h.flow_id == "my-flow-a3f2b1"

    @patch("docpipe.core.orchestration.flow_execution_event_handler.get_session_info")
    def test_initialize_reads_flow_id_from_session_info_library_path(self, mock_get_session_info):
        """PATH 3 — Library: session_info carries UUID (job_id when no explicit flow_id)."""
        from docpipe.core.models.session_info import SessionInfo

        session = SessionInfo(flow_id="d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a")
        mock_get_session_info.return_value = session

        h = FlowExecutionEventHandler()
        h.initialize(job_id="d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a", job_run_id="run-1", common_log_arguments={})

        assert h.flow_id == "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a"

    @patch("docpipe.core.orchestration.flow_execution_event_handler.get_session_info")
    def test_initialize_sets_flow_id_none_when_session_has_no_flow_id(self, mock_get_session_info):
        """
        When session_info.flow_id is None (e.g. API path before the fix was applied to
        a given codepath), h.flow_id must be None — before_flow_execution_start will then
        substitute "unknown".
        """
        from docpipe.core.models.session_info import SessionInfo

        session = SessionInfo(flow_id=None)
        mock_get_session_info.return_value = session

        h = FlowExecutionEventHandler()
        h.initialize(job_id="job-1", job_run_id="run-1", common_log_arguments={})

        assert h.flow_id is None
