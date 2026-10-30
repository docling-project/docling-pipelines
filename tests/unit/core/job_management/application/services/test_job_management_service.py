"""Unit tests for JobManagementService."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.adapters.frameworks.default_job_run_manager import DefaultJobRunManager
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.job_management_service import JobManagementService
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator
from docpipe.exceptions.docpipe_exceptions import (
    FlowInvalidDataException,
    FlowNotFoundException,
    FlowValidationException,
)


class DummyConfigModel:
    """Simple stand-in for job_run configuration models."""

    def __init__(self, data: dict):
        self._data = data
        self.user_id = data.get("user_id")
        self.metadata = data.get("metadata", {})

    def model_dump(self, *, exclude_none: bool = True) -> dict:
        return {k: v for k, v in self._data.items() if not exclude_none or v is not None}


class DummyJobRun:
    """Simple stand-in for job run request payload."""

    def __init__(self, configuration=None):
        self.configuration = configuration


class DummyJob:
    """Simple stand-in for job request payload."""

    def __init__(self, *, asset_ref: str | None, name: str | None = None, configuration: dict | None = None):
        self.asset_ref = asset_ref
        self.name = name
        self.configuration = configuration or {}


class DummyRequestBody:
    """Simple stand-in for JobsAPIExecuteModel."""

    def __init__(self, *, job, job_run):
        self.entity = Mock(job=job, job_run=job_run)


class DummyJobRunItem:
    """Simple stand-in for job run list items."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.job_id = payload.get(DocpipeConstants.JOB_ID)
        self.job_run_id = payload.get(DocpipeConstants.JOB_RUN_ID)
        self.flow_id = payload.get(DocpipeConstants.FLOW_ID)
        self.flow_name = payload.get(DocpipeConstants.FLOW_NAME)

    def model_dump(self, *, include: set[str]):
        return {key: self.payload[key] for key in include if key in self.payload}


class TestJobManagementService:
    """Test JobManagementService."""

    def setup_method(self) -> None:
        self.job_stats_service = Mock()
        self.job_run_manager = Mock()
        self.flow_service = Mock()
        self.executor = Mock()
        self.service = JobManagementService(
            job_stats_service=self.job_stats_service,
            job_run_manager=self.job_run_manager,
            flow_service=self.flow_service,
            executor=self.executor,
        )

    def test_create_job_run_from_request_raises_when_asset_ref_missing(self):
        """Test request parsing fails when asset_ref is missing."""
        request_body = DummyRequestBody(job=DummyJob(asset_ref=None), job_run=DummyJobRun())

        with pytest.raises(FlowNotFoundException, match=r"entity\.job\.asset_ref is required"):
            self.service.create_job_run_from_request(request_body=request_body)

    def test_create_job_run_from_request_merges_job_and_job_run_config(self):
        """Test request parsing merges job and job run configuration."""
        request_body = DummyRequestBody(
            job=DummyJob(asset_ref="flow-1", name="My Flow", configuration={"from_job": "value"}),
            job_run=DummyJobRun(
                configuration=DummyConfigModel(
                    {
                        "from_run": "override",
                        "user_id": "user-1",
                        "metadata": {"source": "api"},
                    }
                )
            ),
        )
        self.service._create_job_run = Mock(return_value={"job_run_id": "run-1"})

        result = self.service.create_job_run_from_request(request_body=request_body)

        assert result == {"job_run_id": "run-1"}
        self.service._create_job_run.assert_called_once_with(
            flow_id="flow-1",
            flow_config={
                "from_job": "value",
                "from_run": "override",
                "user_id": "user-1",
                "metadata": {"source": "api"},
            },
            user_id="user-1",
            metadata={"source": "api"},
        )

    @patch("docpipe.core.assets.flows.domain.models.authoring_flow.AuthoringFlow.from_dict")
    @patch("docpipe.core.assets.flows.application.services.authoring_compiler.AuthoringCompiler.compile")
    @patch("docpipe.core.job_management.application.services.job_management_service.get_session_info")
    def test_create_job_run_compiles_authoring_flow(
        self,
        mock_get_session_info,
        mock_compile,
        mock_from_dict,
    ):
        """Test _create_job_run compiles authoring flows and submits async execution."""
        flow = Mock(name="Flow", job_id="job-123", definition={DocpipeConstants.FLOW_NAME: "Flow", "flow": []})
        flow.name = "Flow"
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "job-123",
            DocpipeConstants.JOB_RUN_ID: "run-123",
        }
        mock_compile.return_value = {"dag": []}
        mock_get_session_info.return_value = Mock()

        result = self.service._create_job_run(flow_id="flow-1", flow_config={"k": "v"})

        assert result[DocpipeConstants.JOB_RUN_ID] == "run-123"
        self.job_stats_service.start_tracking_job.assert_called_once_with(
            job_id="job-123",
            job_run_id="run-123",
            flow_id="flow-1",
            flow_name="Flow",
            user_id=None,
            metadata={},
            initial_status=ExecutionStatus.QUEUED,
        )
        self.executor.submit.assert_called_once()
        submit_args = self.executor.submit.call_args.args
        assert submit_args[0] == self.service._execute_flow_async
        assert submit_args[3] == "run-123"
        assert submit_args[4] == {"dag": []}
        assert submit_args[5][DocpipeConstants.JOB_ID] == "job-123"
        mock_from_dict.assert_called_once_with(data=flow.definition)

    @patch("docpipe.utils.orchestration.elyra_converter.ElyraConverter.transform_elyra_to_internal")
    @patch("docpipe.core.job_management.application.services.job_management_service.get_session_info")
    def test_create_job_run_transforms_elyra_flow(self, mock_get_session_info, mock_transform):
        """Test _create_job_run transforms Elyra flows and submits async execution."""
        flow = Mock(name="Flow", job_id=None, definition={"doc_type": "pipeline"})
        flow.name = "Flow"
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "flow-1",
            DocpipeConstants.JOB_RUN_ID: "run-123",
        }
        mock_transform.return_value = {"dag": []}
        mock_get_session_info.return_value = Mock()

        result = self.service._create_job_run(flow_id="flow-1", flow_config={})

        assert result[DocpipeConstants.JOB_ID] == "flow-1"
        mock_transform.assert_called_once_with(elyra_json=flow.definition, flow_id="flow-1")
        self.executor.submit.assert_called_once()

    def test_create_job_run_raises_for_unknown_flow_format(self):
        """Test _create_job_run rejects unknown flow formats."""
        flow = Mock(job_id=None, definition={"unexpected": True})
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "flow-1",
            DocpipeConstants.JOB_RUN_ID: "run-123",
        }

        with pytest.raises(FlowInvalidDataException, match="unknown format"):
            self.service._create_job_run(flow_id="flow-1", flow_config={})

    def test_get_job_run_status_returns_job_stats(self):
        """Test get_job_run_status delegates to job stats service."""
        expected = Mock()
        self.job_stats_service.get_job_run_stats.return_value = expected

        result = self.service.get_job_run_status(job_run_id="run-1")

        assert result is expected
        self.job_stats_service.get_job_run_stats.assert_called_once_with(job_run_id="run-1")

    def test_cancel_job_run_requests_cancel_and_notifies_manager(self):
        """Test cancel_job_run updates services."""
        self.service.cancel_job_run(job_run_id="run-1")

        self.job_stats_service.request_cancel_job.assert_called_once_with(job_run_id="run-1")
        self.job_run_manager.cancel_job_run.assert_called_once_with(job_run_id="run-1")

    def test_delete_job_run_requests_delete_and_notifies_manager(self):
        """Test delete_job_run updates services."""
        self.service.delete_job_run(job_run_id="run-1")

        self.job_stats_service.request_delete_job_run.assert_called_once_with(job_run_id="run-1")
        self.job_run_manager.delete_job_run.assert_called_once_with(job_run_id="run-1")

    def test_list_job_runs_formats_response(self):
        """Test list_job_runs returns snapshot flow_name directly from job_run."""
        dummy_run = DummyJobRunItem(
            {
                DocpipeConstants.JOB_RUN_ID: "run-1",
                DocpipeConstants.JOB_ID: "job-1",
                DocpipeConstants.STATUS: ExecutionStatus.COMPLETED.value,
                DocpipeConstants.MESSAGE: "done",
            }
        )
        dummy_run.flow_name = "My Test Flow"
        self.job_stats_service.list_job_runs.return_value = [dummy_run]

        result = self.service.list_job_runs(job_id="job-1", status=ExecutionStatus.COMPLETED, limit=10)

        assert result["count"] == 1
        assert result["total"] == 1
        assert result["list"][0][DocpipeConstants.JOB_RUN_ID] == "run-1"
        assert result["list"][0][DocpipeConstants.FLOW_NAME] == "My Test Flow"

    def test_list_job_runs_flow_name_none_when_not_set(self):
        """Test list_job_runs returns None for flow_name when no snapshot exists."""
        dummy_run = DummyJobRunItem(
            {
                DocpipeConstants.JOB_RUN_ID: "run-2",
                DocpipeConstants.JOB_ID: "job-1",
                DocpipeConstants.STATUS: ExecutionStatus.COMPLETED.value,
                DocpipeConstants.MESSAGE: "done",
            }
        )
        dummy_run.flow_name = None
        self.job_stats_service.list_job_runs.return_value = [dummy_run]
        self.job_stats_service.get_flow_definition.return_value = None

        result = self.service.list_job_runs(job_id="job-1", status=ExecutionStatus.COMPLETED, limit=10)

        assert result["list"][0][DocpipeConstants.FLOW_NAME] is None
        self.job_stats_service.list_job_runs.assert_called_once_with(
            job_id="job-1", status=ExecutionStatus.COMPLETED, limit=10
        )

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_defaults_micro_batching_when_missing(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """Test async execution defaults micro-batching to true when missing."""
        mock_orchestrator = Mock()
        mock_create_orchestrator.return_value = mock_orchestrator
        mock_flow_executor = Mock()
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": []},
            flow_config={"custom": "value"},
        )

        mock_set_session_info.assert_called_once()
        execute_kwargs = mock_flow_executor.execute.call_args.kwargs
        assert execute_kwargs["params"][DocpipeConstants.ENABLE_MICRO_BATCHING] is True
        assert execute_kwargs["params"]["custom"] == "value"

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_partial_failure_keeps_computed_status(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """A flow that returns without raising must not have its status overwritten.

        Both end_job() calls in _execute_flow_async live in exception handlers, and
        end_job() overwrites status, end_time, duration and message with no guard on
        what is already there. after_flow_execution_complete has already run by then,
        from _finalize_dag_flow's finally block, so any exception that escapes the
        flow replaces the status it just computed.

        A partial failure in continue mode resolves to COMPLETED_WITH_ERRORS. This
        test pins the rule the adapters have to keep: raise only when job_status is
        FAILING, never on a partial failure. If either adapter starts raising there,
        the API reports FAILED instead and this test goes red.
        """
        mock_create_orchestrator.return_value = Mock()
        mock_flow_executor = Mock()
        mock_flow_executor.execute.return_value = None  # partial failure: no raise
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": []},
            flow_config={},
        )

        self.job_stats_service.end_job.assert_not_called()

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_respects_explicit_micro_batching_value(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """Test async execution preserves explicit micro-batching config from flow_config."""
        mock_orchestrator = Mock()
        mock_create_orchestrator.return_value = mock_orchestrator
        mock_flow_executor = Mock()
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": []},
            flow_config={DocpipeConstants.ENABLE_MICRO_BATCHING: False},
        )

        mock_set_session_info.assert_called_once()
        execute_kwargs = mock_flow_executor.execute.call_args.kwargs
        assert execute_kwargs["params"][DocpipeConstants.ENABLE_MICRO_BATCHING] is False

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_respects_flow_definition_global_config_micro_batching(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """Test async execution does not override explicit enable_micro_batching in flow definition."""
        mock_orchestrator = Mock()
        mock_create_orchestrator.return_value = mock_orchestrator
        mock_flow_executor = Mock()
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": [], "global_config": {DocpipeConstants.ENABLE_MICRO_BATCHING: False}},
            flow_config={},
        )

        mock_set_session_info.assert_called_once()
        execute_kwargs = mock_flow_executor.execute.call_args.kwargs
        assert DocpipeConstants.ENABLE_MICRO_BATCHING not in execute_kwargs["params"]

    def test_serialize_validation_alerts_handles_dicts_and_unknown_types(self):
        """Test validation alert serialization across supported input shapes."""
        alerts = [
            {"node_name": "node-1", "operator": "noop", "message": "problem", "extra": "ignored"},
            "plain string alert",
        ]

        result = self.service._serialize_validation_alerts(alerts)

        assert result[0] == {"node_name": "node-1", "operator": "noop", "message": "problem"}
        assert result[1] == {"message": "plain string alert"}

    def test_serialize_validation_alerts_handles_model_dump_and_to_dict(self):
        """Test validation alert serialization for model-like objects and to_dict objects."""

        class ModelAlert:
            def model_dump(self, *, exclude_none: bool = True):
                return {"node_name": "node-2", "operator": "extract", "message": "warning"}

        class DictAlert:
            def to_dict(self):
                return {"node_name": "node-3", "operator": "chunk", "message": "notice"}

        result = self.service._serialize_validation_alerts([ModelAlert(), DictAlert()])

        assert result[0] == {"node_name": "node-2", "operator": "extract", "message": "warning"}
        assert result[1] == {"node_name": "node-3", "operator": "chunk", "message": "notice"}

    def test_format_validation_error_message_includes_errors_and_warnings(self):
        """Test validation error message formatting includes serialized details."""
        exc = FlowValidationException(
            message="validation failed",
            errors=[{"node_name": "node-1", "operator": "noop", "message": "error"}],
            warnings=[{"node_name": "node-2", "operator": "extract", "message": "warning"}],
        )

        result = self.service._format_validation_error_message(exc)

        assert "Flow validation error: validation failed" in result
        assert '"node_name": "node-1"' in result
        assert '"node_name": "node-2"' in result

    def test_build_detailed_error_message_adds_exception_type(self):
        """Test detailed error message includes exception type when missing."""
        result = self.service._build_detailed_error_message(ValueError("bad input"))

        assert result == "ValueError: bad input"

    def test_build_detailed_error_message_keeps_existing_exception_type(self):
        """Test detailed error message does not duplicate exception type text."""
        result = self.service._build_detailed_error_message(ValueError("ValueError: already prefixed"))

        assert result == "ValueError: already prefixed"

    def test_build_detailed_error_message_appends_structured_error_details(self):
        """Test detailed error message appends pydantic-style error details."""

        class ErrorWithDetails(Exception):
            def __init__(self):
                super().__init__("validation failed")
                self.errors = [
                    {"loc": ["body", "field"], "msg": "missing"},
                    {"loc": ["body", "other"], "msg": "invalid"},
                ]

        result = self.service._build_detailed_error_message(ErrorWithDetails())

        assert "ErrorWithDetails: validation failed" in result
        assert "body -> field: missing" in result
        assert "body -> other: invalid" in result

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_handles_validation_exception(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """Test async execution handles FlowValidationException and marks the run failed."""
        mock_orchestrator = Mock()
        mock_create_orchestrator.return_value = mock_orchestrator
        validation_exc = FlowValidationException(message="validation failed", errors=[{"message": "bad flow"}])
        mock_flow_executor = Mock()
        mock_flow_executor.execute.side_effect = validation_exc
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": []},
            flow_config={},
        )

        mock_set_session_info.assert_called_once()
        self.job_stats_service.end_job.assert_called_once()
        # update_job_run_status is called twice: STARTING then FAILED
        assert self.job_run_manager.update_job_run_status.call_count == 2
        final_update_kwargs = self.job_run_manager.update_job_run_status.call_args_list[-1].kwargs
        assert final_update_kwargs["status"] == ExecutionStatus.FAILED.value

    @patch("docpipe.core.job_management.application.services.job_management_service.set_session_info")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_execute_flow_async_handles_generic_exception(
        self,
        mock_flow_executor_class,
        mock_create_orchestrator,
        mock_set_session_info,
    ):
        """Test async execution handles generic exceptions and marks the run failed."""
        mock_orchestrator = Mock()
        mock_create_orchestrator.return_value = mock_orchestrator
        mock_flow_executor = Mock()
        mock_flow_executor.execute.side_effect = RuntimeError("boom")
        mock_flow_executor_class.return_value = mock_flow_executor

        self.service._execute_flow_async(
            session_info=Mock(),
            job_id="job-1",
            job_run_id="run-1",
            flow_definition={"dag": []},
            flow_config={},
        )

        mock_set_session_info.assert_called_once()
        self.job_stats_service.end_job.assert_called_once()
        # update_job_run_status is called twice: STARTING then FAILED
        assert self.job_run_manager.update_job_run_status.call_count == 2
        end_kwargs = self.job_stats_service.end_job.call_args.kwargs
        assert end_kwargs["status"] == ExecutionStatus.FAILED.value
        assert "RuntimeError: boom" in end_kwargs["job_run_stats"][DocpipeConstants.MESSAGE]

    def test_shutdown_closes_executor(self):
        """Test shutdown closes the executor."""
        self.service.shutdown()

        self.executor.shutdown.assert_called_once_with(wait=True)


# ---------------------------------------------------------------------------
# Flow-identity tests  (added by fix-job-stats-flow-identity)
# ---------------------------------------------------------------------------
# These classes verify the three execution paths produce the correct
# (flow_id, flow_name) values in every JobStats write.
#
#   PATH 1 - API  : create_job_run_from_request -> _create_job_run
#   PATH 2 - CLI  : tested via FlowExecutionEventHandler (see that test file)
#   PATH 3 - Library: tested via FlowExecutionEventHandler (see that test file)
# ---------------------------------------------------------------------------


class TestFlowIdentityAPIPath:
    """
    PATH 1 — API execution path.

    Verifies that create_job_run_from_request → _create_job_run:
      - strips the old flow_name parameter from the _create_job_run call
      - calls start_tracking_job with flow_id=asset_UUID, flow_name=flow.name
      - patches session_info.flow_id before executor.submit so the background
        thread's event handler receives the asset UUID
    """

    def setup_method(self) -> None:
        self.job_stats_service = Mock()
        self.job_run_manager = Mock()
        self.flow_service = Mock()
        self.executor = Mock()
        self.service = JobManagementService(
            job_stats_service=self.job_stats_service,
            job_run_manager=self.job_run_manager,
            flow_service=self.flow_service,
            executor=self.executor,
        )

    # ------------------------------------------------------------------
    # create_job_run_from_request
    # ------------------------------------------------------------------

    def test_api_path_passes_asset_uuid_as_flow_id_not_job_name(self):
        """
        create_job_run_from_request must NOT pass flow_name to _create_job_run.
        Only flow_id (asset UUID) and flow_config are forwarded.
        """
        self.service._create_job_run = Mock(return_value={"job_run_id": "run-1"})
        request_body = DummyRequestBody(
            job=DummyJob(
                asset_ref="5f429668-ded4-41b5-80b9-f1d6278dc07a",
                name="flow_06_oct_2026_11_16_PM-jyoti",
            ),
            job_run=DummyJobRun(),
        )

        self.service.create_job_run_from_request(request_body=request_body)

        self.service._create_job_run.assert_called_once_with(
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_config={},
            user_id=None,
            metadata={},
        )

    # ------------------------------------------------------------------
    # _create_job_run — start_tracking_job receives correct fields
    # ------------------------------------------------------------------

    @patch("docpipe.core.assets.flows.domain.models.authoring_flow.AuthoringFlow.from_dict")
    @patch("docpipe.core.assets.flows.application.services.authoring_compiler.AuthoringCompiler.compile")
    @patch("docpipe.core.job_management.application.services.job_management_service.get_session_info")
    def test_api_path_start_tracking_uses_asset_uuid_as_flow_id(
        self, mock_get_session_info, mock_compile, mock_from_dict
    ):
        """
        start_tracking_job must receive:
          flow_id = asset UUID (the value passed to _create_job_run)
          flow_name = flow.name (from the DB record, not from the request job.name)
        """
        flow = Mock(job_id="job-abc", definition={DocpipeConstants.FLOW_NAME: "My Flow", "flow": []})
        flow.name = "My Flow"
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "job-abc",
            DocpipeConstants.JOB_RUN_ID: "run-abc",
        }
        mock_compile.return_value = {"dag": []}
        mock_get_session_info.return_value = Mock()

        self.service._create_job_run(
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_config={},
        )

        self.job_stats_service.start_tracking_job.assert_called_once_with(
            job_id="job-abc",
            job_run_id="run-abc",
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_name="My Flow",
            user_id=None,
            metadata={},
            initial_status=ExecutionStatus.QUEUED,
        )

    @patch("docpipe.core.assets.flows.domain.models.authoring_flow.AuthoringFlow.from_dict")
    @patch("docpipe.core.assets.flows.application.services.authoring_compiler.AuthoringCompiler.compile")
    @patch("docpipe.core.job_management.application.services.job_management_service.get_session_info")
    def test_api_path_session_info_flow_id_patched_before_submit(
        self, mock_get_session_info, mock_compile, mock_from_dict
    ):
        """
        session_info.flow_id must equal the asset UUID by the time executor.submit
        is called, so the background thread's event handler reads the correct value.
        """
        flow = Mock(job_id="job-abc", definition={DocpipeConstants.FLOW_NAME: "My Flow", "flow": []})
        flow.name = "My Flow"
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "job-abc",
            DocpipeConstants.JOB_RUN_ID: "run-abc",
        }
        mock_compile.return_value = {"dag": []}

        # The session_info starts with flow_id=None (as TransactionMiddleware leaves it)
        session_info_obj = Mock()
        session_info_obj.flow_id = None
        mock_get_session_info.return_value = session_info_obj

        self.service._create_job_run(
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_config={},
        )

        # The object passed as first positional arg to executor.submit (after the callable)
        # must have flow_id set to the asset UUID
        submit_call = self.executor.submit.call_args
        passed_session_info = submit_call.args[1]
        assert passed_session_info.flow_id == "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        assert passed_session_info.job_id == "job-abc"
        assert passed_session_info.job_run_id == "run-abc"

    @patch("docpipe.core.assets.flows.domain.models.authoring_flow.AuthoringFlow.from_dict")
    @patch("docpipe.core.assets.flows.application.services.authoring_compiler.AuthoringCompiler.compile")
    @patch("docpipe.core.job_management.application.services.job_management_service.get_session_info")
    def test_api_path_resolved_flow_name_block_is_gone(self, mock_get_session_info, mock_compile, mock_from_dict):
        """
        The old resolved_flow_name heuristic (flow.name > flow_name > flow_id)
        must not exist: even when flow.name is None, flow_name must not fall back
        to the asset UUID — it stays None.
        """
        flow = Mock(job_id="job-abc", definition={DocpipeConstants.FLOW_NAME: "x", "flow": []})
        flow.name = None  # name absent from DB
        self.flow_service.get_flow.return_value = flow
        self.job_run_manager.create_job_run.return_value = {
            DocpipeConstants.JOB_ID: "job-abc",
            DocpipeConstants.JOB_RUN_ID: "run-abc",
        }
        mock_compile.return_value = {"dag": []}
        mock_get_session_info.return_value = Mock()

        self.service._create_job_run(
            flow_id="5f429668-ded4-41b5-80b9-f1d6278dc07a",
            flow_config={},
        )

        call_kwargs = self.job_stats_service.start_tracking_job.call_args.kwargs
        assert call_kwargs["flow_id"] == "5f429668-ded4-41b5-80b9-f1d6278dc07a"
        assert call_kwargs["flow_name"] is None  # not the UUID

    # ------------------------------------------------------------------
    # list_job_runs — snapshot, no live lookup
    # ------------------------------------------------------------------

    def test_list_job_runs_no_flow_service_call(self):
        """
        list_job_runs must never call flow_service.get_flow.
        It reads flow_name directly from job_run.flow_name (snapshot).
        """
        dummy = DummyJobRunItem(
            {
                DocpipeConstants.JOB_RUN_ID: "run-1",
                DocpipeConstants.JOB_ID: "job-1",
                DocpipeConstants.STATUS: ExecutionStatus.COMPLETED.value,
                DocpipeConstants.MESSAGE: "done",
            }
        )
        dummy.flow_name = "My Flow At Run Time"
        self.job_stats_service.list_job_runs.return_value = [dummy]

        result = self.service.list_job_runs(job_id="job-1")

        self.flow_service.get_flow.assert_not_called()
        assert result["list"][0][DocpipeConstants.FLOW_NAME] == "My Flow At Run Time"

    def test_list_job_runs_returns_none_for_old_rows_without_flow_name(self):
        """
        Pre-fix rows have flow_name=None. list_job_runs must return None,
        not attempt a lookup or raise.
        """
        dummy = DummyJobRunItem(
            {
                DocpipeConstants.JOB_RUN_ID: "run-2",
                DocpipeConstants.JOB_ID: "job-1",
                DocpipeConstants.STATUS: ExecutionStatus.RUNNING.value,
                DocpipeConstants.MESSAGE: "",
            }
        )
        dummy.flow_name = None
        self.job_stats_service.list_job_runs.return_value = [dummy]
        self.job_stats_service.get_flow_definition.return_value = None

        result = self.service.list_job_runs()

        self.flow_service.get_flow.assert_not_called()
        assert result["list"][0][DocpipeConstants.FLOW_NAME] is None

    def test_list_job_runs_total_equals_count_on_short_page(self):
        """A short page sets total to count and lists runs once."""
        runs = [_dummy_run(job_run_id=f"run-{index}") for index in range(3)]
        self.job_stats_service.list_job_runs.return_value = runs

        result = self.service.list_job_runs(job_id="flow-1", limit=10)

        assert result["count"] == 3
        assert result["total"] == 3
        assert len(result["list"]) == 3
        self.job_stats_service.list_job_runs.assert_called_once_with(job_id="flow-1", status=None, limit=10)
        self.job_stats_service.count_job_runs.assert_not_called()

    def test_list_job_runs_total_comes_from_count_when_page_is_full(self):
        """A full page reads total from count_job_runs, including matches past any list cap."""
        page = [_dummy_run(job_run_id=f"run-{index}") for index in range(5)]
        self.job_stats_service.list_job_runs.return_value = page
        self.job_stats_service.count_job_runs.return_value = 100_001

        result = self.service.list_job_runs(job_id="flow-1", status=ExecutionStatus.RUNNING, limit=5)

        assert result["count"] == 5
        assert result["total"] == 100_001
        assert [item[DocpipeConstants.JOB_RUN_ID] for item in result["list"]] == [f"run-{index}" for index in range(5)]
        self.job_stats_service.list_job_runs.assert_called_once_with(
            job_id="flow-1",
            status=ExecutionStatus.RUNNING,
            limit=5,
        )
        self.job_stats_service.count_job_runs.assert_called_once_with(
            job_id="flow-1",
            status=ExecutionStatus.RUNNING,
        )

    def test_list_job_runs_total_equals_count_when_page_fills_limit(self):
        """A page that fills the limit still takes total from count_job_runs."""
        page = [_dummy_run(job_run_id=f"run-{index}") for index in range(5)]
        self.job_stats_service.list_job_runs.return_value = page
        self.job_stats_service.count_job_runs.return_value = 5

        result = self.service.list_job_runs(job_id="flow-1", status=ExecutionStatus.RUNNING, limit=5)

        assert result["count"] == 5
        assert result["total"] == 5
        assert len(result["list"]) == 5
        self.job_stats_service.list_job_runs.assert_called_once_with(
            job_id="flow-1",
            status=ExecutionStatus.RUNNING,
            limit=5,
        )
        self.job_stats_service.count_job_runs.assert_called_once_with(
            job_id="flow-1",
            status=ExecutionStatus.RUNNING,
        )


def _dummy_run(*, job_run_id: str, job_id: str = "flow-1") -> DummyJobRunItem:
    item = DummyJobRunItem(
        {
            DocpipeConstants.JOB_RUN_ID: job_run_id,
            DocpipeConstants.JOB_ID: job_id,
            DocpipeConstants.STATUS: ExecutionStatus.RUNNING.value,
            DocpipeConstants.MESSAGE: "",
        }
    )
    item.flow_name = "Flow One"
    return item


def test_list_job_runs_total_counts_matches_beyond_the_page():
    """OpenSpec job-runs list. limit 5 with 20 stored runs returns count 5 and total 20."""
    store = InMemoryJobStatsStore()
    aggregator = NodeStatsAggregator(job_stats_store=store)
    tracker = JobTrackerService(job_stats_store=store, node_stats_aggregator=aggregator)
    for index in range(20):
        tracker.start_tracking_job(
            job_id="flow-1",
            job_run_id=f"{index:08x}-0000-4000-8000-000000000000",
            flow_id="flow-1",
            flow_name="Flow One",
        )
    service = JobManagementService(
        job_stats_service=tracker,
        job_run_manager=DefaultJobRunManager(job_stats_service=tracker),
        flow_service=Mock(),
    )

    result = service.list_job_runs(job_id="flow-1", limit=5)

    assert result["count"] == 5
    assert result["total"] == 20
    assert len(result["list"]) == 5
