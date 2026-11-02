"""Unit tests for operator resolution, failure handling and release in PythonOperatorExecutor."""

import logging
from collections.abc import Iterator
from typing import Any

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.models.session_info import get_session_info
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.functional.noop import NOOPOperator
from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_messages import ValidationCodeMessages

NODE_ID = "node_lifecycle"


class _RecordingTelemetry:
    """Minimal stand-in for the OTEL telemetry service that records what the executor reports."""

    def __init__(self) -> None:
        self.span = object()
        self.started: list[str] = []
        self.ended: list[object] = []
        self.exceptions: list[tuple[Exception, object]] = []
        self.executions: list[dict[str, Any]] = []

    def start_span(self, name: str, *, attributes: dict[str, Any] | None = None) -> object:
        """Record the span name and return a sentinel span."""
        self.started.append(name)
        return self.span

    def end_span(self, span: object) -> None:
        """Record that the span was ended."""
        self.ended.append(span)

    def set_span_attribute(self, key: str, value: Any, *, span: object = None) -> None:
        """Ignore span attributes."""

    def record_exception(self, exception: Exception, *, span: object = None) -> None:
        """Record the exception attached to the span."""
        self.exceptions.append((exception, span))

    def record_operator_execution(self, **kwargs: Any) -> None:
        """Record the operator execution metric."""
        self.executions.append(kwargs)


class _FailingOperator(AbstractOperator):
    """Operator whose transform always raises a specific error."""

    short_name = "test_failing_operator"
    category = OperatorCategory.Functional

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialise the operator with a recording telemetry service."""
        super().__init__(config)
        self._telemetry = _RecordingTelemetry()

    def transform(self, table: pa.Table) -> Any:
        """Always fail."""
        raise ValueError("transform exploded")


class _CleanupOperator(NOOPOperator):
    """NOOP operator that counts calls to ``cleanup()``."""

    short_name = "test_cleanup_operator"

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialise the cleanup counter."""
        super().__init__(config)
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        """Count the cleanup call."""
        self.cleanup_calls += 1


class _BrokenCleanupOperator(_CleanupOperator):
    """Operator whose ``cleanup()`` raises after counting the call."""

    short_name = "test_broken_cleanup_operator"

    def cleanup(self) -> None:
        """Count the call and fail."""
        super().cleanup()
        raise RuntimeError("cleanup exploded")


class _ListHandler(logging.Handler):
    """Collects log records emitted on the docpipe logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Store the record."""
        self.records.append(record)


@pytest.fixture
def docpipe_log_records() -> Iterator[list[logging.LogRecord]]:
    """Capture records on the docpipe logger regardless of its propagation setting."""
    docpipe_logger = logging.getLogger(DocpipeConstants.LOGGER_NAME)
    handler = _ListHandler()
    previous_level = docpipe_logger.level
    docpipe_logger.addHandler(handler)
    docpipe_logger.setLevel(logging.INFO)
    try:
        yield handler.records
    finally:
        docpipe_logger.removeHandler(handler)
        docpipe_logger.setLevel(previous_level)


def _make_executor(operator: str) -> PythonOperatorExecutor:
    """Create an executor for ``operator`` with the minimal node params."""
    return PythonOperatorExecutor(
        name="lifecycle_node",
        operator=operator,
        params={
            OperatorConstants.Columns.ID: NODE_ID,
            DocpipeConstants.JOB_ID: "job_lifecycle",
            DocpipeConstants.JOB_RUN_ID: "run_lifecycle",
        },
    )


def _make_executor_for(
    monkeypatch: pytest.MonkeyPatch, operator_class: type[AbstractOperator]
) -> PythonOperatorExecutor:
    """Create an executor whose real operator factory also resolves ``operator_class``."""
    executor = _make_executor(operator_class.short_name)
    monkeypatch.setitem(executor.operator_factory.operators, operator_class.short_name, operator_class)
    return executor


class TestGetOperator:
    """Operator resolution through the operator factory."""

    def test_unknown_operator_raises_docpipe_exception(self) -> None:
        """An operator name the factory does not know raises GET_OPERATOR_FAILED naming the operator."""
        executor = _make_executor("operator_that_does_not_exist")

        with pytest.raises(DocpipeException) as exc_info:
            executor.get_operator()

        assert str(exc_info.value) == (
            f"{ValidationCodeMessages.GET_OPERATOR_FAILED.value}: operator_that_does_not_exist"
        )

    def test_known_operator_is_built_once_and_cached(self) -> None:
        """A resolved operator is constructed with the node params and reused on later calls."""
        executor = _make_executor(OperatorConstants.Operators.NOOP)

        op = executor.get_operator()

        assert isinstance(op, NOOPOperator)
        assert op.id == NODE_ID
        assert executor.get_operator() is op


class TestExecuteFailure:
    """Failure handling when the operator's transform raises."""

    def test_transform_error_is_reported_and_reraised(
        self, monkeypatch: pytest.MonkeyPatch, docpipe_log_records: list[logging.LogRecord]
    ) -> None:
        """The original error propagates after metrics, span and error log record the failure."""
        executor = _make_executor_for(monkeypatch, _FailingOperator)

        with pytest.raises(ValueError, match="transform exploded") as exc_info:
            executor.execute(data_access=None, deleted_rows_list=None)

        op = executor.get_operator()
        telemetry = op._telemetry
        assert isinstance(telemetry, _RecordingTelemetry)
        assert telemetry.started == ["operator.test_failing_operator"]
        assert telemetry.exceptions == [(exc_info.value, telemetry.span)]
        assert telemetry.ended == [telemetry.span]
        assert len(telemetry.executions) == 1
        assert telemetry.executions[0]["operator_name"] == "test_failing_operator"
        assert telemetry.executions[0]["success"] is False
        assert telemetry.executions[0]["duration_ms"] >= 0

        error_records = [r for r in docpipe_log_records if r.levelno == logging.ERROR]
        assert len(error_records) == 1
        message = error_records[0].getMessage()
        assert f"node id: {NODE_ID}" in message
        assert f"transaction_ID: {get_session_info().transaction_id!s}" in message
        assert error_records[0].exc_info is not None
        assert error_records[0].exc_info[1] is exc_info.value


class TestRelease:
    """Releasing the operator held by the executor."""

    def test_release_before_operator_was_built_is_noop(self) -> None:
        """Releasing an executor that never built its operator does nothing and does not raise."""
        executor = _make_executor(OperatorConstants.Operators.NOOP)

        executor.release()
        executor.release()

        assert isinstance(executor.get_operator(), NOOPOperator)

    def test_release_drops_operator_without_cleanup(self) -> None:
        """An operator without ``cleanup()`` is dropped so the next ``get_operator()`` rebuilds it."""
        executor = _make_executor(OperatorConstants.Operators.NOOP)
        first = executor.get_operator()
        assert not hasattr(first, "cleanup")

        executor.release()

        rebuilt = executor.get_operator()
        assert isinstance(rebuilt, NOOPOperator)
        assert rebuilt is not first

    def test_release_runs_cleanup_once_and_drops_operator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``cleanup()`` runs exactly once, and a second release has nothing left to clean."""
        executor = _make_executor_for(monkeypatch, _CleanupOperator)
        op = executor.get_operator()
        assert isinstance(op, _CleanupOperator)

        executor.release()
        executor.release()

        assert op.cleanup_calls == 1
        assert executor.get_operator() is not op

    def test_release_swallows_cleanup_error_and_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, docpipe_log_records: list[logging.LogRecord]
    ) -> None:
        """A failing ``cleanup()`` is logged as a warning with the traceback and never propagates."""
        executor = _make_executor_for(monkeypatch, _BrokenCleanupOperator)
        op = executor.get_operator()
        assert isinstance(op, _BrokenCleanupOperator)

        executor.release()

        assert op.cleanup_calls == 1
        assert executor.get_operator() is not op
        warnings = [r for r in docpipe_log_records if r.levelno == logging.WARNING]
        assert [r.getMessage() for r in warnings] == ["operator cleanup failed for test_broken_cleanup_operator"]
        assert warnings[0].exc_info is not None
        assert isinstance(warnings[0].exc_info[1], RuntimeError)
