"""JobManagementService tests against a real JobTrackerService.

The job stats side is the production ``JobTrackerService`` over an
``InMemoryJobStatsStore``; flow definition snapshots are written by the real
filesystem snapshot storage under ``tmp_path``. Only the flow executor is
replaced (it would load every operator), and the framework adapter is a
``DefaultJobRunManager`` subclass where a test needs the framework to fail.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import docpipe.storage.file_system.key_value_file_system_storage  # noqa: F401  (registers the filesystem backend)
from docpipe.api.dto.job_run_dto import JobsAPIExecuteModel
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.adapters.config import flow_definition_snapshot_storage_factory
from docpipe.core.job_management.adapters.frameworks.default_job_run_manager import DefaultJobRunManager
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.job_management_service import JobManagementService
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator
from docpipe.core.models.session_info import get_session_info, session_info_var
from docpipe.core.orchestration import flow_executor as flow_executor_module
from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
from docpipe.exceptions.docpipe_exceptions import (
    FlowExecutionFailedException,
    FlowValidationException,
    ValidationAlert,
)
from docpipe.exceptions.error_messages import ValidationMessage

FLOW_ID = "5f429668-ded4-41b5-80b9-f1d6278dc07a"
JOB_ID = "job-invoices"
JOB_RUN_ID = "run-0001"

AUTHORING_DEFINITION = {
    DocpipeConstants.FLOW_NAME: "Invoice flow",
    "global_config": {},
    "flow": [
        {"type": "ingest_source", "name": "ingest", "config": {}},
        {"type": "chunker", "name": "chunk", "config": {}, "depends_on": ["ingest"]},
    ],
}


class StaticFlowService:
    """Flow service stand-in that serves one stored Flow by id."""

    def __init__(self, flow: Flow) -> None:
        self._flow = flow

    def get_flow(self, flow_id: str) -> Flow:
        """Return the stored flow (the id is not checked)."""
        return self._flow


class FlakyFrameworkJobRunManager(DefaultJobRunManager):
    """DefaultJobRunManager whose framework rejects some status updates."""

    def __init__(self, *, job_stats_service: JobTrackerService, failing_statuses: set[str]) -> None:
        super().__init__(job_stats_service=job_stats_service)
        self.failing_statuses = failing_statuses
        self.rejected: list[str] = []

    def update_job_run_status(
        self, *, job_run_id: str, status: str, job_run_stats: dict[str, Any] | None = None
    ) -> None:
        """Raise for the configured statuses, delegate otherwise."""
        if status in self.failing_statuses:
            self.rejected.append(status)
            raise ConnectionError(f"framework unavailable while setting {status}")
        super().update_job_run_status(job_run_id=job_run_id, status=status, job_run_stats=job_run_stats)


class IncompleteJobRunManager(DefaultJobRunManager):
    """DefaultJobRunManager whose framework returns a fixed, incomplete create response."""

    def __init__(self, *, job_stats_service: JobTrackerService, create_response: dict[str, Any]) -> None:
        super().__init__(job_stats_service=job_stats_service)
        self.create_response = create_response

    def create_job_run(self, *, job_id: str, job_config: dict[str, Any]) -> dict[str, Any]:
        """Return the preset response instead of a generated job run id."""
        return self.create_response


class ExecutorRecorder:
    """Records FlowExecutor usage and raises the configured error from execute()."""

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.executed_params: list[dict[str, Any]] = []

    def build(self, flow_def=None, orchestrator=None, original_flow_def=None) -> SimpleNamespace:
        """Create a FlowExecutor stand-in bound to this recorder."""
        return SimpleNamespace(execute=self._execute)

    def _execute(self, *, orchestrator, params) -> None:
        self.executed_params.append(params)
        if self.error is not None:
            raise self.error


class AlertWithBrokenToDict:
    """Validation alert from a plugin whose to_dict() fails."""

    def to_dict(self) -> dict[str, Any]:
        """Fail like a broken plugin serializer."""
        raise KeyError("node_name")

    def __str__(self) -> str:
        return "broken alert"


class ErrorsAttributeException(Exception):
    """Exception carrying a pydantic-style ``errors`` list attribute."""

    def __init__(self, message: str, errors: list[Any]) -> None:
        super().__init__(message)
        self.errors = errors


class BatchSizeConfig(BaseModel):
    """Small pydantic model used to produce a real ValidationError."""

    batch_size: int


@pytest.fixture(autouse=True)
def isolated_session_info():
    """Give each test its own SessionInfo (the service mutates the current one)."""
    token = session_info_var.set(None)
    yield
    session_info_var.reset(token)


@pytest.fixture
def snapshot_storage_root(*, tmp_path, monkeypatch):
    """Point the flow definition snapshot storage at tmp_path."""
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path))
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "no-config.yaml"))
    monkeypatch.setattr(flow_definition_snapshot_storage_factory, "_default_factory", None)
    return tmp_path


@pytest.fixture
def tracker() -> JobTrackerService:
    """Production JobTrackerService over an in-memory store."""
    store = InMemoryJobStatsStore()
    return JobTrackerService(job_stats_store=store, node_stats_aggregator=NodeStatsAggregator(job_stats_store=store))


@pytest.fixture
def executor_recorder(monkeypatch) -> ExecutorRecorder:
    """Replace FlowExecutor and the orchestrator factory used by _execute_flow_async."""
    recorder = ExecutorRecorder()
    monkeypatch.setattr(flow_executor_module, "FlowExecutor", recorder.build)
    monkeypatch.setattr(
        OrchestratorFactory,
        "create_orchestrator",
        staticmethod(lambda **kwargs: SimpleNamespace(name="python")),
    )
    return recorder


def _service(*, tracker: JobTrackerService, job_run_manager: DefaultJobRunManager | None = None, flow=None):
    return JobManagementService(
        job_stats_service=tracker,
        job_run_manager=job_run_manager or DefaultJobRunManager(job_stats_service=tracker),
        flow_service=StaticFlowService(flow or Flow(asset_id=FLOW_ID, name="Invoice flow")),
    )


def _run_in_background(*, service: JobManagementService, flow_config: dict[str, Any] | None = None) -> None:
    service._execute_flow_async(
        get_session_info(),
        JOB_ID,
        JOB_RUN_ID,
        {"dag": []},
        flow_config or {},
    )


def _stored_run(tracker: JobTrackerService):
    return tracker.get_job_run_stats(job_run_id=JOB_RUN_ID)


class TestListJobRunsRecoversFlowNameFromSnapshot:
    """Runs stored without flow_name get it from the saved flow definition snapshot."""

    @pytest.mark.parametrize(
        ("flow_definition", "expected_name"),
        [
            pytest.param(AUTHORING_DEFINITION, "Invoice flow", id="authoring-flow-name"),
            pytest.param(
                {
                    "doc_type": "pipeline",
                    "pipelines": [{"app_data": {"ui_data": {"name": "Canvas name"}, "ds_flow": {"name": "DS name"}}}],
                },
                "Canvas name",
                id="elyra-ui-data-name-wins",
            ),
            pytest.param(
                {"doc_type": "pipeline", "pipelines": [{"app_data": {"ds_flow": {"name": "DS name"}}}]},
                "DS name",
                id="elyra-ds-flow-fallback",
            ),
            pytest.param(
                {"doc_type": "pipeline", "pipelines": [{"app_data": {"ui_data": {"name": ""}}}]},
                None,
                id="elyra-without-names",
            ),
            pytest.param({"doc_type": "pipeline", "pipelines": []}, None, id="elyra-without-pipelines"),
            pytest.param({"dag": [{"id": "n1"}]}, None, id="runtime-dag-has-no-name"),
        ],
    )
    def test_flow_name_from_snapshot(self, *, tracker, snapshot_storage_root, flow_definition, expected_name):
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID, flow_name=None)
        tracker.save_flow_definition(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_definition=flow_definition)

        result = _service(tracker=tracker).list_job_runs(job_id=JOB_ID)

        assert result["count"] == 1
        assert result["list"][0][DocpipeConstants.JOB_RUN_ID] == JOB_RUN_ID
        assert result["list"][0][DocpipeConstants.FLOW_NAME] == expected_name

    def test_corrupt_snapshot_leaves_flow_name_empty(self, *, tracker, snapshot_storage_root):
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID, flow_name=None)
        snapshot_file = snapshot_storage_root / JOB_ID / JOB_RUN_ID / "flow_definition.json"
        snapshot_file.parent.mkdir(parents=True)
        snapshot_file.write_text("{not json", encoding="utf-8")

        result = _service(tracker=tracker).list_job_runs()

        assert result["list"][0][DocpipeConstants.JOB_RUN_ID] == JOB_RUN_ID
        assert result["list"][0][DocpipeConstants.FLOW_NAME] is None


class TestCreateJobRunFrameworkContract:
    """The framework adapter must return both job_id and job_run_id."""

    @staticmethod
    def _request() -> JobsAPIExecuteModel:
        return JobsAPIExecuteModel.model_validate({"entity": {"job": {"asset_ref": FLOW_ID}}})

    @pytest.mark.parametrize(
        ("create_response", "error_pattern"),
        [
            pytest.param({}, f"did not return job_id for flow_id: {FLOW_ID}", id="empty-response"),
            pytest.param(
                {DocpipeConstants.JOB_ID: JOB_ID}, f"did not return job_run_id for job_id: {JOB_ID}", id="no-run-id"
            ),
        ],
    )
    def test_incomplete_framework_response_is_rejected_before_tracking(
        self, *, tracker, create_response, error_pattern
    ):
        manager = IncompleteJobRunManager(job_stats_service=tracker, create_response=create_response)
        service = _service(tracker=tracker, job_run_manager=manager)

        with pytest.raises(RuntimeError, match=error_pattern):
            service.create_job_run_from_request(request_body=self._request())

        assert tracker.list_job_runs() == []

    def test_background_validation_failure_marks_tracked_run_failed(self, *, tracker, executor_recorder):
        executor_recorder.error = FlowValidationException(
            errors=[ValidationAlert(code="flow_validation_failed", message="Unknown operator", node_name="chunk")]
        )
        flow = Flow(asset_id=FLOW_ID, name="Invoice flow", definition=AUTHORING_DEFINITION)
        service = _service(tracker=tracker, flow=flow)

        created = service.create_job_run_from_request(request_body=self._request())
        service.shutdown()  # waits for the background execution

        stored = tracker.get_job_run_stats(job_run_id=created[DocpipeConstants.JOB_RUN_ID])
        assert stored.flow_id == FLOW_ID
        assert stored.flow_name == "Invoice flow"
        assert stored.status == ExecutionStatus.FAILED
        assert stored.message.startswith("Flow validation error: Invalid Flow definition\n")
        assert '"message": "Unknown operator"' in stored.message
        assert executor_recorder.executed_params[0][DocpipeConstants.JOB_RUN_ID] == created[DocpipeConstants.JOB_RUN_ID]


class TestExecuteFlowAsyncFrameworkFailures:
    """Framework status update failures never stop the run from being finalized."""

    def test_flow_still_runs_when_starting_update_fails(self, *, tracker, executor_recorder):
        tracker.start_tracking_job(
            job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID, initial_status=ExecutionStatus.QUEUED
        )
        manager = FlakyFrameworkJobRunManager(
            job_stats_service=tracker, failing_statuses={ExecutionStatus.STARTING.value}
        )

        _run_in_background(service=_service(tracker=tracker, job_run_manager=manager), flow_config={"k": "v"})

        assert manager.rejected == [ExecutionStatus.STARTING.value]
        assert executor_recorder.executed_params == [
            {
                DocpipeConstants.JOB_ID: JOB_ID,
                DocpipeConstants.JOB_RUN_ID: JOB_RUN_ID,
                "k": "v",
                DocpipeConstants.ENABLE_MICRO_BATCHING: True,
            }
        ]
        assert _stored_run(tracker).status == ExecutionStatus.QUEUED

    def test_validation_failure_is_recorded_when_framework_rejects_failed_status(self, *, tracker, executor_recorder):
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID)
        manager = FlakyFrameworkJobRunManager(
            job_stats_service=tracker,
            failing_statuses={ExecutionStatus.STARTING.value, ExecutionStatus.FAILED.value},
        )
        executor_recorder.error = FlowValidationException(
            errors=[ValidationAlert(message="Ingest operator missing", node_name="chunk", operator="chunker")]
        )

        _run_in_background(service=_service(tracker=tracker, job_run_manager=manager))

        stored = _stored_run(tracker)
        assert manager.rejected == [ExecutionStatus.STARTING.value, ExecutionStatus.FAILED.value]
        assert stored.status == ExecutionStatus.FAILED
        assert stored.message.startswith("Flow validation error: Invalid Flow definition\n")
        assert '"operator": "chunker"' in stored.message

    def test_runtime_failure_is_recorded_when_framework_rejects_failed_status(self, *, tracker, executor_recorder):
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID)
        manager = FlakyFrameworkJobRunManager(
            job_stats_service=tracker, failing_statuses={ExecutionStatus.FAILED.value}
        )
        executor_recorder.error = RuntimeError("worker crashed")

        _run_in_background(service=_service(tracker=tracker, job_run_manager=manager))

        stored = _stored_run(tracker)
        assert manager.rejected == [ExecutionStatus.FAILED.value]
        assert stored.status == ExecutionStatus.FAILED
        assert stored.message == "RuntimeError: worker crashed"

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(FlowValidationException(errors=[ValidationAlert(message="bad")]), id="validation-error"),
            pytest.param(RuntimeError("worker crashed"), id="runtime-error"),
        ],
    )
    def test_failure_of_a_run_deleted_meanwhile_is_swallowed(self, *, tracker, executor_recorder, error):
        """end_job raises JobRunNotFoundException for a deleted run; the worker must not crash."""
        executor_recorder.error = error

        _run_in_background(service=_service(tracker=tracker))

        assert _stored_run(tracker) is None
        assert tracker.list_job_runs() == []


class TestValidationFailureMessage:
    """Validation alerts of every supported shape end up in the stored failure message."""

    def test_alerts_without_message_and_broken_alerts_are_kept(self, *, tracker, executor_recorder):
        alert_without_message = ValidationAlert(code="flow_validation_failed", node_name="ingest")
        message_without_text = ValidationMessage(message_code="MISSING_PARAM", node_name="chunk")
        broken = AlertWithBrokenToDict()
        executor_recorder.error = FlowValidationException(
            errors=[alert_without_message, message_without_text], warnings=[broken]
        )
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID)

        _run_in_background(service=_service(tracker=tracker))

        summary, details = _stored_run(tracker).message.split("\n", 1)
        assert summary == "Flow validation error: Invalid Flow definition"
        assert json.loads(details) == {
            "errors": [
                {"node_name": "ingest", "operator": None, "message": str(alert_without_message)},
                {"node_name": "chunk", "message": str(message_without_text)},
            ],
            "warnings": [{"message": "broken alert", "serialization_error": "'node_name'"}],
        }


class TestRuntimeFailureMessage:
    """The stored message for runtime failures carries the exception type and details."""

    @staticmethod
    def _stored_message_for(*, tracker, executor_recorder, error: Exception) -> str:
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id=FLOW_ID)
        executor_recorder.error = error
        _run_in_background(service=_service(tracker=tracker))
        return _stored_run(tracker).message

    def test_docpipe_exception_without_errors(self, *, tracker, executor_recorder):
        error = FlowExecutionFailedException("Failed to acquire write lock for job_id=j1")

        message = self._stored_message_for(tracker=tracker, executor_recorder=executor_recorder, error=error)

        assert message == "FlowExecutionFailedException: Failed to acquire write lock for job_id=j1"

    def test_pydantic_validation_error_keeps_its_own_text(self, *, tracker, executor_recorder):
        with pytest.raises(ValidationError) as caught:
            BatchSizeConfig(batch_size="many")

        message = self._stored_message_for(tracker=tracker, executor_recorder=executor_recorder, error=caught.value)

        assert message == f"ValidationError: {caught.value}"

    @pytest.mark.parametrize(
        ("errors", "expected_suffix"),
        [
            pytest.param(["disk full"], "", id="non-dict-entries-ignored"),
            pytest.param(
                ["noise", {"loc": ["config", "batch_size"], "msg": "must be positive"}],
                ". Details: config -> batch_size: must be positive",
                id="dict-entries-kept",
            ),
            pytest.param([{"loc": None, "msg": "unparseable"}], "", id="malformed-loc-ignored"),
        ],
    )
    def test_errors_attribute_details(self, *, tracker, executor_recorder, errors, expected_suffix):
        error = ErrorsAttributeException("operator config rejected", errors)

        message = self._stored_message_for(tracker=tracker, executor_recorder=executor_recorder, error=error)

        assert message == f"ErrorsAttributeException: operator config rejected{expected_suffix}"
