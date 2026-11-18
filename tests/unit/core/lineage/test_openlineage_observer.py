"""Unit tests for OpenLineageExecutionObserver."""

from unittest.mock import MagicMock

import pytest

from docpipe.core.constants.constants import LineageConstants
from docpipe.core.lineage.adapters.openlineage.observer import OpenLineageExecutionObserver
from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.orchestration.models.execution_event_context import (
    FlowAbortContext,
    FlowCompleteContext,
    FlowFailContext,
    FlowRunningContext,
    FlowStartContext,
    NodeCompleteContext,
    NodeFailContext,
    NodeSkipContext,
    NodeStartContext,
    NodeTableSummary,
)


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=LineageService)


@pytest.fixture
def flow_observer(mock_service: MagicMock) -> OpenLineageExecutionObserver:
    return OpenLineageExecutionObserver(lineage_service=mock_service, mode=LineageConstants.MODE_FLOW)


@pytest.fixture
def operator_observer(mock_service: MagicMock) -> OpenLineageExecutionObserver:
    return OpenLineageExecutionObserver(lineage_service=mock_service, mode=LineageConstants.MODE_OPERATOR)


@pytest.fixture
def sample_summary() -> NodeTableSummary:
    return NodeTableSummary(schema_fields=[("id", "string"), ("content", "string")], row_count=1)


class TestFlowModeObserver:
    """Flow mode emits only flow-level events; node events are no-ops."""

    def test_on_flow_start_delegates(
        self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock
    ) -> None:
        context = FlowStartContext(flow_id="f1", flow_name="test", job_run_id="r1", flow_def={})
        flow_observer.on_flow_start(context=context)
        mock_service.emit_flow_start.assert_called_once_with(context=context)

    def test_on_flow_running_delegates(
        self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock
    ) -> None:
        context = FlowRunningContext(flow_id="f1", flow_name="test", job_run_id="r1")
        flow_observer.on_flow_running(context=context)
        mock_service.emit_flow_running.assert_called_once_with(context=context)

    def test_on_flow_complete_delegates(
        self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock
    ) -> None:
        context = FlowCompleteContext(flow_id="f1", flow_name="test", job_run_id="r1", flow_def={})
        flow_observer.on_flow_complete(context=context)
        mock_service.emit_flow_complete.assert_called_once_with(context=context)

    def test_on_flow_fail_delegates(self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock) -> None:
        context = FlowFailContext(flow_id="f1", flow_name="test", job_run_id="r1", error_message="boom")
        flow_observer.on_flow_fail(context=context)
        mock_service.emit_flow_fail.assert_called_once_with(context=context)

    def test_on_flow_abort_delegates(
        self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock
    ) -> None:
        context = FlowAbortContext(flow_id="f1", flow_name="test", job_run_id="r1")
        flow_observer.on_flow_abort(context=context)
        mock_service.emit_flow_abort.assert_called_once_with(context=context)

    def test_node_events_are_noop_in_flow_mode(
        self, flow_observer: OpenLineageExecutionObserver, mock_service: MagicMock
    ) -> None:
        flow_observer.on_node_start(
            context=NodeStartContext(
                flow_id="f1",
                flow_name="test",
                job_run_id="r1",
                node_id="n1",
                node_name="chunker",
                operator_type="chunker",
            )
        )
        flow_observer.on_node_complete(
            context=NodeCompleteContext(
                flow_id="f1",
                flow_name="test",
                job_run_id="r1",
                node_id="n1",
                node_name="chunker",
                operator_type="chunker",
            )
        )
        flow_observer.on_node_fail(
            context=NodeFailContext(
                flow_id="f1",
                flow_name="test",
                job_run_id="r1",
                node_id="n1",
                node_name="chunker",
                operator_type="chunker",
                error_message="err",
            )
        )
        flow_observer.on_node_skip(
            context=NodeSkipContext(
                flow_id="f1",
                flow_name="test",
                job_run_id="r1",
                node_id="n1",
                node_name="chunker",
                operator_type="chunker",
                reason="empty",
            )
        )
        mock_service.emit_node_start.assert_not_called()
        mock_service.emit_node_complete.assert_not_called()
        mock_service.emit_node_fail.assert_not_called()
        mock_service.emit_node_skip.assert_not_called()


class TestOperatorModeFlowEvents:
    """Flow RUNNING and COMPLETE pass the full context in both modes.

    The flow job acts as a summary edge — it always carries dataset edges so
    Marquez can display it in the lineage graph regardless of mode.
    """

    def test_on_flow_running_passes_context_unchanged_in_operator_mode(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        import pyarrow as pa

        context = FlowRunningContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            ingested_table=pa.table({"id": ["a"]}),
            ingest_node_id="ingest_documents",
        )
        operator_observer.on_flow_running(context=context)
        mock_service.emit_flow_running.assert_called_once_with(context=context)

    def test_on_flow_complete_passes_context_unchanged_in_operator_mode(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        import pyarrow as pa

        context = FlowCompleteContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            flow_def={},
            output_tables=[pa.table({"id": ["a"]})],
            completed_docs=5,
            failed_docs=0,
            skipped_docs=0,
            total_docs=5,
        )
        operator_observer.on_flow_complete(context=context)
        mock_service.emit_flow_complete.assert_called_once_with(context=context)

    def test_on_flow_running_passes_context_unchanged_in_flow_mode(
        self,
        flow_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        import pyarrow as pa

        context = FlowRunningContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            ingested_table=pa.table({"id": ["a"]}),
            ingest_node_id="ingest_documents",
        )
        flow_observer.on_flow_running(context=context)
        mock_service.emit_flow_running.assert_called_once_with(context=context)


class TestOperatorModeObserver:
    """Operator mode delegates all node events directly to the service."""

    def test_on_node_start_delegates(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
        sample_summary: NodeTableSummary,
    ) -> None:
        context = NodeStartContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            input_summary=sample_summary,
        )
        operator_observer.on_node_start(context=context)
        mock_service.emit_node_start.assert_called_once_with(context=context)

    def test_on_node_start_no_input_summary(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        context = NodeStartContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
        )
        operator_observer.on_node_start(context=context)
        mock_service.emit_node_start.assert_called_once_with(context=context)

    def test_on_node_complete_delegates(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
        sample_summary: NodeTableSummary,
    ) -> None:
        context = NodeCompleteContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            output_summaries=[sample_summary],
        )
        operator_observer.on_node_complete(context=context)
        mock_service.emit_node_complete.assert_called_once_with(context=context)

    def test_on_node_fail_delegates(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
        sample_summary: NodeTableSummary,
    ) -> None:
        context = NodeFailContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            error_message="error",
            input_summary=sample_summary,
        )
        operator_observer.on_node_fail(context=context)
        mock_service.emit_node_fail.assert_called_once_with(context=context)

    def test_on_node_fail_without_input_summary(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        context = NodeFailContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n2",
            node_name="embeddings",
            operator_type="embeddings",
            error_message="error",
        )
        operator_observer.on_node_fail(context=context)
        mock_service.emit_node_fail.assert_called_once_with(context=context)

    def test_on_node_skip_delegates(
        self,
        operator_observer: OpenLineageExecutionObserver,
        mock_service: MagicMock,
    ) -> None:
        context = NodeSkipContext(
            flow_id="f1",
            flow_name="test",
            job_run_id="r1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            reason="empty input",
        )
        operator_observer.on_node_skip(context=context)
        mock_service.emit_node_skip.assert_called_once_with(context=context)


class TestOpenLineagePublisherAdapter:
    """Tests for OpenLineagePublisherAdapter covering publish() and import fallback."""

    def test_publish_emits_event(self) -> None:
        """publish() translates domain models into an SDK RunEvent and calls client.emit()."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_run_cls = MagicMock()
        mock_job_cls = MagicMock()
        mock_dataset_cls = MagicMock()
        mock_event_cls = MagicMock()
        mock_event_type_cls = MagicMock()
        mock_event_type_cls.START = "START"

        with (
            patch(
                "docpipe.core.lineage.adapters.openlineage.publisher._import_openlineage",
                return_value=(
                    MagicMock,  # OLClient — used in __init__
                    mock_event_cls,  # RunEvent
                    mock_event_type_cls,  # EventType
                    mock_dataset_cls,  # Dataset
                    mock_job_cls,  # Job
                    mock_run_cls,  # Run
                ),
            ),
            patch(
                "docpipe.core.lineage.adapters.openlineage.publisher.OpenLineagePublisherAdapter.__init__",
                return_value=None,
            ),
        ):
            from docpipe.core.lineage.adapters.openlineage.publisher import OpenLineagePublisherAdapter
            from docpipe.core.lineage.domain.models.dataset import LineageDataset
            from docpipe.core.lineage.domain.models.event_type import LineageEventType
            from docpipe.core.lineage.domain.models.job import LineageJob
            from docpipe.core.lineage.domain.models.run import LineageRun

            adapter = OpenLineagePublisherAdapter.__new__(OpenLineagePublisherAdapter)
            adapter._client = mock_client

            adapter.publish(
                event_type=LineageEventType.START,
                run=LineageRun(run_id="run-1", start_time="2024-01-01T00:00:00"),
                job=LineageJob(namespace="ns", name="myjob"),
                inputs=[LineageDataset(namespace="ns", name="in")],
                outputs=[LineageDataset(namespace="ns", name="out")],
            )

        mock_client.emit.assert_called_once()

    def test_publish_swallows_emit_exception(self) -> None:
        """publish() logs a warning and does not re-raise when client.emit() fails."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.emit.side_effect = RuntimeError("transport error")
        mock_event_type_cls = MagicMock()
        mock_event_type_cls.START = "START"

        with (
            patch(
                "docpipe.core.lineage.adapters.openlineage.publisher._import_openlineage",
                return_value=(
                    MagicMock,
                    MagicMock(),
                    mock_event_type_cls,
                    MagicMock(),
                    MagicMock(),
                    MagicMock(),
                ),
            ),
            patch(
                "docpipe.core.lineage.adapters.openlineage.publisher.OpenLineagePublisherAdapter.__init__",
                return_value=None,
            ),
        ):
            from docpipe.core.lineage.adapters.openlineage.publisher import OpenLineagePublisherAdapter
            from docpipe.core.lineage.domain.models.event_type import LineageEventType
            from docpipe.core.lineage.domain.models.job import LineageJob
            from docpipe.core.lineage.domain.models.run import LineageRun

            adapter = OpenLineagePublisherAdapter.__new__(OpenLineagePublisherAdapter)
            adapter._client = mock_client

            # must not raise — exception must be swallowed
            adapter.publish(
                event_type=LineageEventType.START,
                run=LineageRun(run_id="run-4"),
                job=LineageJob(namespace="ns", name="job"),
            )
