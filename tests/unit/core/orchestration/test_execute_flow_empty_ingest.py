# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for execute_flow() early-exit behaviour when the ingest table is empty.

Covers:
- All downstream nodes are marked as SKIPPED via after_node_skipped when ingest returns 0 rows
- after_node_skipped is called once per downstream node with the correct arguments
- after_node_skipped is NOT called when the flow has only an ingest node (no downstream)
- after_node_skipped is NOT called when ingest returns rows (normal execution path)
- A failing after_node_skipped call is swallowed and remaining nodes are still processed
- _finalize_dag_flow and clean_up_prefect_home are always called on the early-exit path
- The skip reason is "Skipped - no documents ingested in previous step"
- global_config is forwarded unchanged to each after_node_skipped call
"""

from unittest.mock import MagicMock, patch

import pyarrow as pa

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator

JOB_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
JOB_RUN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_INGEST_NODE = {
    OperatorConstants.Columns.ID: "node-ingest",
    OperatorConstants.Columns.NAME: "ingest_step",
    OperatorConstants.Misc.OPERATOR: "ingest_source",
}
_CHUNKER_NODE = {
    OperatorConstants.Columns.ID: "node-chunker",
    OperatorConstants.Columns.NAME: "chunker_step",
    OperatorConstants.Misc.OPERATOR: "chunker",
}
_EMBEDDINGS_NODE = {
    OperatorConstants.Columns.ID: "node-embeddings",
    OperatorConstants.Columns.NAME: "embeddings_step",
    OperatorConstants.Misc.OPERATOR: "embeddings",
}

_SKIP_REASON = "Skipped - no documents ingested in previous step"


def _make_orchestrator() -> PythonOrchestrator:
    orchestrator = PythonOrchestrator()
    orchestrator.job_id = JOB_ID
    orchestrator.job_run_id = JOB_RUN_ID
    orchestrator.common_log_arguments = {}
    return orchestrator


def _ingest_result(num_rows: int) -> ExecuteStepResults:
    table = pa.table({"content": pa.array(["doc"] * num_rows, type=pa.string())})
    return ExecuteStepResults(
        data_accesses=[MagicMock()],
        tables=[table],
        internal_metadata={},
    )


def _run_execute_flow(orchestrator, op_flow, global_config, ingest_result):
    """
    Patch all side-effectful dependencies of execute_flow that are unrelated
    to the code under test, then call execute_flow().

    Returns the mocks for clean_up_prefect_home and _finalize_dag_flow so
    callers can assert on them.
    """
    with (
        patch.object(PythonOrchestrator, "_create_empty_result", return_value=MagicMock()),
        patch.object(PythonOrchestrator, "_execute_step", return_value=ingest_result),
        patch.object(PythonOrchestrator, "_populate_ingest_source_config"),
        patch.object(PythonOrchestrator, "_get_ingest_summary_message", return_value=""),
        patch(
            "docpipe.core.orchestration.abstract_orchestrator.get_incremental_update_service",
            return_value=MagicMock(
                get_soft_deleted_doc_ids=MagicMock(return_value=set()),
                process_ingested_docs=MagicMock(return_value=set()),
            ),
        ),
        patch("docpipe.core.orchestration.abstract_orchestrator.clean_up_prefect_home") as mock_cleanup,
        patch.object(PythonOrchestrator, "_finalize_dag_flow") as mock_finalize,
    ):
        orchestrator.execute_flow(op_flow=op_flow, global_config=global_config)

    return {"clean_up": mock_cleanup, "finalize": mock_finalize}


class TestExecuteFlowEmptyIngest:
    def test_downstream_nodes_marked_skipped(self):
        """after_node_skipped is called once for every node after the ingest node."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE, _CHUNKER_NODE, _EMBEDDINGS_NODE]
        _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        assert mock_handler.after_node_skipped.call_count == 2

    def test_after_node_skipped_called_with_correct_node_attributes(self):
        """after_node_skipped receives the id, name, and operator_type from each downstream node."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE, _CHUNKER_NODE, _EMBEDDINGS_NODE]
        _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        calls = mock_handler.after_node_skipped.call_args_list

        assert calls[0].kwargs["node_id"] == "node-chunker"
        assert calls[0].kwargs["node_name"] == "chunker_step"
        assert calls[0].kwargs["operator_type"] == "chunker"
        assert calls[0].kwargs["column_names"] == []

        assert calls[1].kwargs["node_id"] == "node-embeddings"
        assert calls[1].kwargs["node_name"] == "embeddings_step"
        assert calls[1].kwargs["operator_type"] == "embeddings"
        assert calls[1].kwargs["column_names"] == []

    def test_skip_reason_is_correct(self):
        """The reason kwarg matches the expected constant string."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE, _CHUNKER_NODE]
        _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        reason = mock_handler.after_node_skipped.call_args.kwargs["reason"]
        assert reason == _SKIP_REASON

    def test_no_after_node_skipped_when_only_ingest_node(self):
        """When the flow has only an ingest node, after_node_skipped is never called."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE]
        _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        mock_handler.after_node_skipped.assert_not_called()

    def test_no_after_node_skipped_when_ingest_has_rows(self):
        """after_node_skipped must NOT be called when the ingest table has rows."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE, _CHUNKER_NODE]

        with (
            patch.object(PythonOrchestrator, "_create_empty_result", return_value=MagicMock()),
            patch.object(PythonOrchestrator, "_execute_step", return_value=_ingest_result(1)),
            patch.object(PythonOrchestrator, "_populate_ingest_source_config"),
            patch.object(PythonOrchestrator, "_get_ingest_summary_message", return_value=""),
            patch(
                "docpipe.core.orchestration.abstract_orchestrator.get_incremental_update_service",
                return_value=MagicMock(get_soft_deleted_doc_ids=MagicMock(return_value=set())),
            ),
            patch.object(orchestrator.batch_manager, "prepare_batches", return_value=([MagicMock()], {})),
            patch("docpipe.core.orchestration.abstract_orchestrator.clean_up_prefect_home"),
            patch.object(PythonOrchestrator, "_finalize_dag_flow"),
        ):
            orchestrator.execute_flow(op_flow=op_flow, global_config={})

        mock_handler.after_node_skipped.assert_not_called()

    def test_failing_after_node_skipped_does_not_abort_remaining_nodes(self):
        """If after_node_skipped raises for one node, remaining nodes are still processed."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        mock_handler.after_node_skipped.side_effect = [RuntimeError("db unavailable"), None]
        orchestrator.flow_execution_event_handler = mock_handler

        op_flow = [_INGEST_NODE, _CHUNKER_NODE, _EMBEDDINGS_NODE]
        _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        assert mock_handler.after_node_skipped.call_count == 2
        second_call = mock_handler.after_node_skipped.call_args_list[1]
        assert second_call.kwargs["node_id"] == "node-embeddings"

    def test_finalize_and_cleanup_called_on_early_exit(self):
        """_finalize_dag_flow and clean_up_prefect_home are called even on the empty-ingest path."""
        orchestrator = _make_orchestrator()
        orchestrator.flow_execution_event_handler = MagicMock()

        op_flow = [_INGEST_NODE, _CHUNKER_NODE]
        mocks = _run_execute_flow(orchestrator, op_flow, {}, _ingest_result(0))

        mocks["clean_up"].assert_called_once()
        mocks["finalize"].assert_called_once_with(op_flow=op_flow, global_config={})

    def test_global_config_forwarded_to_after_node_skipped(self):
        """global_config is passed through unchanged to each after_node_skipped call."""
        orchestrator = _make_orchestrator()
        mock_handler = MagicMock()
        orchestrator.flow_execution_event_handler = mock_handler

        config = {"doc_column": "content", "storage": "in-memory"}
        op_flow = [_INGEST_NODE, _CHUNKER_NODE]
        _run_execute_flow(orchestrator, op_flow, config, _ingest_result(0))

        passed_config = mock_handler.after_node_skipped.call_args.kwargs["global_config"]
        assert passed_config["doc_column"] == "content"
        assert passed_config["storage"] == "in-memory"
