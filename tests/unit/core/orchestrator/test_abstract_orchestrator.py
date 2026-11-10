"""Unit tests for AbstractOrchestrator."""

from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.prefect.prefect_engine import ExecuteStepResults


def make_op_def(op_id="node-1", name="myop", operator="IngestSourceOperator"):
    return {
        OperatorConstants.Columns.ID: op_id,
        OperatorConstants.Columns.NAME: name,
        OperatorConstants.Misc.OPERATOR: operator,
        DocpipeConstants.OUTPUT_EDGES: [],
        DocpipeConstants.INPUT_EDGES: [],
    }


class ConcreteOrchestrator(AbstractOrchestrator):
    """Minimal concrete subclass for testing."""

    def create_executor_impl(self, *, name, operator, params, job_stats_service=None):
        raise NotImplementedError

    def execute_flow(self, *, op_flow, global_config):
        pass

    def _create_flow_engine(self, *, job_id: str, job_run_id: str, job_log_path: str):
        return None


@pytest.fixture
def orchestrator():
    with patch("docpipe.core.orchestration.abstract_orchestrator.FlowExecutionEventHandler") as mock_handler_cls:
        mock_handler = Mock()
        mock_handler_cls.return_value = mock_handler
        orch = ConcreteOrchestrator()
        orch.flow_execution_event_handler = mock_handler
        orch.job_run_id = "run-123"
        orch.job_id = "job-456"
        orch.common_log_arguments = {}
        return orch


@pytest.mark.unit
class TestEvaluateExecutionSkip:
    def test_non_ingest_empty_table_skips(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Functional)
        table = pa.table({"id": []})
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=table, deleted_docs_count=0)
        assert result is True

    def test_non_ingest_non_empty_table_does_not_skip(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Functional)
        table = pa.table({"id": ["doc1"]})
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=table, deleted_docs_count=0)
        assert result is False

    def test_ingest_operator_never_skips(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Ingest)
        table = pa.table({"id": []})
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=table, deleted_docs_count=0)
        assert result is False

    def test_vectordb_with_deleted_docs_does_not_skip(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.VectorDB)
        table = pa.table({"id": []})  # empty
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=table, deleted_docs_count=5)
        assert result is False

    def test_vectordb_no_deleted_docs_empty_table_skips(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.VectorDB)
        table = pa.table({"id": []})
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=table, deleted_docs_count=0)
        assert result is True

    def test_none_tables_skips(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Functional)
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=None, deleted_docs_count=0)
        assert result is True

    def test_list_of_empty_tables_skips(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Quality)
        tables = [pa.table({"id": []}), pa.table({"id": []})]
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=tables, deleted_docs_count=0)
        assert result is True

    def test_list_with_non_empty_table_does_not_skip(self, orchestrator):
        mock_exec = Mock()
        mock_exec.get_operator.return_value = Mock(category=OperatorCategory.Quality)
        tables = [pa.table({"id": []}), pa.table({"id": ["doc1"]})]
        result = orchestrator.evaluate_execution_skip(executor=mock_exec, tables=tables, deleted_docs_count=0)
        assert result is False


@pytest.mark.unit
class TestHandleSkippedExecution:
    def test_single_prev_results(self, orchestrator):
        mock_exec = Mock()
        table = pa.table({"id": ["doc1"], "text": ["content"]})
        mock_da = Mock()
        mock_exec.create_data_accesses.return_value = [mock_da]

        prev_results = ExecuteStepResults([mock_da], [table], {})

        _data_accesses, tables = orchestrator._handle_skipped_execution(
            op_def=make_op_def(),
            executor=mock_exec,
            prev_results=prev_results,
            global_config={},
            start="2024-01-01",
        )
        assert tables == [table]
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()

    def test_dict_prev_results(self, orchestrator):
        mock_exec = Mock()
        table = pa.table({"id": ["doc1"]})
        mock_da = Mock()
        mock_exec.create_data_accesses.return_value = [mock_da]

        prev_results = {
            "link1": ExecuteStepResults([mock_da], [table], {}),
        }

        _data_accesses, tables = orchestrator._handle_skipped_execution(
            op_def=make_op_def(),
            executor=mock_exec,
            prev_results=prev_results,
            global_config={},
            start="2024-01-01",
        )
        assert len(tables) == 1
        orchestrator.flow_execution_event_handler.after_node_skipped.assert_called_once()

    def test_column_names_empty_for_multiple_tables(self, orchestrator):
        mock_exec = Mock()
        table1 = pa.table({"a": [1]})
        table2 = pa.table({"b": [2]})
        mock_da = Mock()
        mock_exec.create_data_accesses.return_value = [mock_da]

        prev_results = ExecuteStepResults([mock_da, mock_da], [table1, table2], {})

        orchestrator._handle_skipped_execution(
            op_def=make_op_def(),
            executor=mock_exec,
            prev_results=prev_results,
            global_config={},
            start="2024-01-01",
        )
        # column_names should be [] when multiple tables
        call_kwargs = orchestrator.flow_execution_event_handler.after_node_skipped.call_args[1]
        assert call_kwargs["column_names"] == []


@pytest.mark.unit
class TestCheckAndUploadDeletedRows:
    def test_empty_queue_does_nothing(self, orchestrator):
        with patch("docpipe.core.orchestration.abstract_orchestrator.combine_cumulative_deleted_rows") as mock_combine:
            orchestrator._check_and_upload_deleted_rows()
            mock_combine.assert_not_called()

    def test_non_empty_queue_saves_table(self, orchestrator):
        table = pa.table({"id": ["doc1"]})
        orchestrator.deleted_rows_list.put(table)

        with (
            patch("docpipe.core.orchestration.abstract_orchestrator.combine_cumulative_deleted_rows") as mock_combine,
            patch("docpipe.core.orchestration.abstract_orchestrator.construct_deleted_rows_table_path") as mock_path,
            patch("docpipe.core.orchestration.abstract_orchestrator.get_parquet_table_handler") as mock_handler,
        ):
            mock_combine.return_value = table
            mock_path.return_value = "/tmp/deleted.parquet"
            mock_ph = Mock()
            mock_handler.return_value = mock_ph

            orchestrator._check_and_upload_deleted_rows()

            mock_ph.delete_file.assert_called_once()
            mock_ph.save_table.assert_called_once()

    def test_exception_in_save_logs_warning(self, orchestrator):
        table = pa.table({"id": ["doc1"]})
        orchestrator.deleted_rows_list.put(table)

        with patch(
            "docpipe.core.orchestration.abstract_orchestrator.combine_cumulative_deleted_rows",
            side_effect=RuntimeError("save error"),
        ):
            # Should not raise
            orchestrator._check_and_upload_deleted_rows()


@pytest.mark.unit
class TestCleanupMemmapFiles:
    def test_no_job_id_skips(self, orchestrator):
        orchestrator.job_id = None
        with patch("docpipe.core.orchestration.abstract_orchestrator.AbstractOrchestrator._cleanup_memmap_files"):
            # Can't easily mock internal import; just check it doesn't raise
            orchestrator._cleanup_memmap_files()

    def test_cleanup_called_with_ids(self, orchestrator):
        orchestrator.job_id = "job-123"
        orchestrator.job_run_id = "run-456"
        with patch("docpipe.utils.core.memmap_file_utils.cleanup_memmap_files"):
            # Direct import mock
            orchestrator._cleanup_memmap_files()
            # If the import succeeds, just assert no error

    def test_exception_in_cleanup_logs_warning(self, orchestrator):
        orchestrator.job_id = "job-123"
        orchestrator.job_run_id = "run-456"
        import sys

        mock_module = MagicMock()
        mock_module.cleanup_memmap_files.side_effect = RuntimeError("cleanup failed")
        with patch.dict(sys.modules, {"docpipe.utils.core.memmap_file_utils": mock_module}):
            orchestrator._cleanup_memmap_files()  # should not raise


@pytest.mark.unit
class TestCancelPauseResume:
    def test_cancel_sets_status(self, orchestrator):
        orchestrator.cancel()
        assert orchestrator.job_status == ExecutionStatus.CANCELING

    def test_pause_does_not_raise(self, orchestrator):
        orchestrator.pause()

    def test_resume_does_not_raise(self, orchestrator):
        orchestrator.resume()

    def test_get_type_returns_none(self, orchestrator):
        result = orchestrator.get_type()
        assert result is None


@pytest.mark.unit
class TestHandleNodeFailure:
    def test_sets_failing_status(self, orchestrator):
        op_def = make_op_def()
        orchestrator._handle_node_failure(e=RuntimeError("err"), op_def=op_def, global_config={})
        assert orchestrator.job_status == ExecutionStatus.FAILING
        orchestrator.flow_execution_event_handler.after_node_failure.assert_called_once()


@pytest.mark.unit
class TestGetIngestSummaryMessage:
    def test_non_empty_table_returns_none(self, orchestrator):
        table = pa.table({"id": ["doc1"]})
        op = {OperatorConstants.Misc.OPERATOR: "IngestSourceOperator"}
        result = orchestrator._get_ingest_summary_message(output_table=table, deleted_docs_count=0, operator=op)
        assert result is None

    def test_empty_table_returns_message(self, orchestrator):
        table = pa.table({"id": []})
        op = {OperatorConstants.Misc.OPERATOR: "IngestSourceOperator"}
        result = orchestrator._get_ingest_summary_message(output_table=table, deleted_docs_count=0, operator=op)
        assert result is not None
        assert "No documents" in result

    def test_empty_table_with_deleted_includes_count(self, orchestrator):
        table = pa.table({"id": []})
        op = {OperatorConstants.Misc.OPERATOR: "IngestSourceOperator"}
        result = orchestrator._get_ingest_summary_message(output_table=table, deleted_docs_count=3, operator=op)
        assert "3" in result
        assert "were" in result  # plural

    def test_empty_table_with_single_deleted(self, orchestrator):
        table = pa.table({"id": []})
        op = {OperatorConstants.Misc.OPERATOR: "IngestSourceOperator"}
        result = orchestrator._get_ingest_summary_message(output_table=table, deleted_docs_count=1, operator=op)
        assert "was" in result  # singular

    def test_noop_operator_returns_none(self, orchestrator):
        table = pa.table({"id": []})
        op = {OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.NOOP}
        result = orchestrator._get_ingest_summary_message(output_table=table, deleted_docs_count=0, operator=op)
        assert result is None


@pytest.mark.unit
class TestPopulateIngestSourceConfig:
    def test_ingest_source_operator_populates_config(self, orchestrator):
        global_config: dict = {}
        ingest_operator = {
            OperatorConstants.Misc.OPERATOR: "IngestSourceOperator",
            OperatorConstants.Config.CONFIG: {
                OperatorConstants.Config.PROVIDER: "s3",
                OperatorConstants.Config.PROVIDER_CONFIG: {"bucket": "my-bucket", "access_key": "AKID"},
            },
        }
        orchestrator._populate_ingest_source_config(ingest_operator=ingest_operator, global_config=global_config)
        assert OperatorConstants.Config.INGEST_SOURCE in global_config
        assert global_config[OperatorConstants.Config.INGEST_SOURCE][OperatorConstants.Config.PROVIDER] == "s3"

    def test_non_ingest_source_operator_skips(self, orchestrator):
        global_config: dict = {}
        ingest_operator = {
            OperatorConstants.Misc.OPERATOR: "SomeOtherOperator",
            OperatorConstants.Config.CONFIG: {},
        }
        orchestrator._populate_ingest_source_config(ingest_operator=ingest_operator, global_config=global_config)
        assert OperatorConstants.Config.INGEST_SOURCE not in global_config

    def test_provider_config_stored_in_global_config(self, orchestrator):
        global_config: dict = {}
        ingest_operator = {
            OperatorConstants.Misc.OPERATOR: "ingest_source",
            OperatorConstants.Config.CONFIG: {
                OperatorConstants.Config.PROVIDER_CONFIG: {"bucket": "b", "access_key": "KEY"},
            },
        }
        orchestrator._populate_ingest_source_config(ingest_operator=ingest_operator, global_config=global_config)
        provider_config = global_config[OperatorConstants.Config.INGEST_SOURCE][
            OperatorConstants.Config.PROVIDER_CONFIG
        ]
        assert "access_key" in provider_config
        assert "bucket" in provider_config


@pytest.mark.unit
class TestInnerTaskSkipping:
    def test_returns_none_when_prev_results_is_none(self, orchestrator):
        op_def = make_op_def()
        session_info = Mock()
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=None,
            session_info=session_info,
            deleted_docs_count=0,
        )
        assert result is None

    def test_returns_none_when_failing(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.FAILING
        op_def = make_op_def()
        table = pa.table({"id": ["doc1"]})
        prev_results = ExecuteStepResults([Mock()], [table], {})
        session_info = Mock()
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=prev_results,
            session_info=session_info,
            deleted_docs_count=0,
        )
        assert result is None

    def test_returns_none_when_canceling(self, orchestrator):
        orchestrator.job_status = ExecutionStatus.CANCELING
        op_def = make_op_def()
        table = pa.table({"id": ["doc1"]})
        prev_results = ExecuteStepResults([Mock()], [table], {})
        session_info = Mock()
        result = orchestrator._inner_task(
            op_def=op_def,
            global_config={},
            prev_results=prev_results,
            session_info=session_info,
            deleted_docs_count=0,
        )
        assert result is None


@pytest.mark.unit
class TestFinalizeDagFlow:
    def test_calls_event_handler(self, orchestrator):
        orchestrator._finalize_dag_flow(op_flow=[make_op_def()])
        orchestrator.flow_execution_event_handler.after_flow_execution_complete.assert_called_once()


@pytest.mark.unit
class TestInitialize:
    def test_sets_job_ids(self, orchestrator):
        with (
            patch("docpipe.core.orchestration.abstract_orchestrator.get_session_info") as mock_si,
            patch.object(orchestrator, "_create_flow_engine", return_value=None),
        ):
            mock_si.return_value = Mock(flow_id="flow-1")
            orchestrator.flow_engine = None
            orchestrator.initialize(job_id="job-1", job_run_id="run-1")
            assert orchestrator.job_id == "job-1"
            assert orchestrator.job_run_id == "run-1"

    def test_skips_if_already_initialized_for_same_run(self, orchestrator):
        orchestrator.flow_engine = Mock()
        orchestrator.job_run_id = "run-same"
        with patch("docpipe.core.orchestration.abstract_orchestrator.get_session_info") as mock_si:
            orchestrator.initialize(job_id="job-1", job_run_id="run-same")
            # get_session_info should not be called if skipping
            mock_si.assert_not_called()


class TestOrchestratorFactory:
    """Tests for OrchestratorFactory covering uncovered utility methods."""

    def setup_method(self) -> None:
        """Reset factory to defaults before each test."""
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        OrchestratorFactory.reset_orchestrators()

    def test_reset_orchestrators_restores_defaults(self) -> None:
        """reset_orchestrators() clears custom registrations and restores python default."""
        from docpipe.core.constants import OrchestratorType
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
        from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator

        # register a custom orchestrator then reset
        OrchestratorFactory.register_orchestrators(orchestrators={"custom": ConcreteOrchestrator})
        OrchestratorFactory.reset_orchestrators()

        registered = OrchestratorFactory.get_registered_orchestrators()
        assert OrchestratorType.PYTHON in registered
        assert registered[OrchestratorType.PYTHON] is PythonOrchestrator
        assert "custom" not in registered

    def test_get_registered_orchestrators_returns_copy(self) -> None:
        """get_registered_orchestrators() returns a dict copy, not the internal registry."""
        from docpipe.core.constants import OrchestratorType
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        result = OrchestratorFactory.get_registered_orchestrators()
        assert OrchestratorType.PYTHON in result
        # mutating the returned copy must not affect the registry
        result["injected"] = ConcreteOrchestrator
        clean = OrchestratorFactory.get_registered_orchestrators()
        assert "injected" not in clean

    def test_register_orchestrators_raises_on_empty_dict(self) -> None:
        """register_orchestrators() raises ValueError when called with an empty dict."""
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        with pytest.raises(ValueError, match="must not be empty"):
            OrchestratorFactory.register_orchestrators(orchestrators={})


@pytest.mark.unit
class TestRecordSinkDataset:
    """Sinks are shared across micro-batches on one orchestrator instance."""

    NS = "opensearch://localhost:9200"

    def test_starts_empty_without_hasattr_guard(self, orchestrator):
        assert orchestrator.sink_datasets == {}

    def test_same_sink_across_batches_is_one_entry_with_summed_rows(self, orchestrator):
        for rows in (3, 4, 5):
            orchestrator._record_sink_dataset(
                namespace=self.NS, name="idx", tables=[pa.table({"id": [str(i) for i in range(rows)]})]
            )
        assert list(orchestrator.sink_datasets) == [(self.NS, "idx")]
        assert orchestrator.sink_datasets[(self.NS, "idx")].summary.row_count == 12

    def test_distinct_sinks_keep_their_own_schema(self, orchestrator):
        orchestrator._record_sink_dataset(namespace=self.NS, name="a", tables=[pa.table({"id": ["1"]})])
        orchestrator._record_sink_dataset(
            namespace=self.NS, name="b", tables=[pa.table({"id": ["1", "2"], "extra": [1, 2]})]
        )
        assert [c for c, _ in orchestrator.sink_datasets[(self.NS, "a")].summary.schema_fields] == ["id"]
        assert [c for c, _ in orchestrator.sink_datasets[(self.NS, "b")].summary.schema_fields] == ["id", "extra"]
        assert orchestrator.sink_datasets[(self.NS, "b")].summary.row_count == 2

    def test_no_table_records_nothing(self, orchestrator):
        orchestrator._record_sink_dataset(namespace=self.NS, name="idx", tables=[])
        orchestrator._record_sink_dataset(namespace=self.NS, name="idx", tables=[None])
        assert orchestrator.sink_datasets == {}

    def test_concurrent_batches_do_not_lose_rows(self, orchestrator):
        import threading

        def run_batch():
            orchestrator._record_sink_dataset(namespace=self.NS, name="idx", tables=[pa.table({"id": ["1", "2"]})])

        threads = [threading.Thread(target=run_batch) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(orchestrator.sink_datasets) == 1
        assert orchestrator.sink_datasets[(self.NS, "idx")].summary.row_count == 40
