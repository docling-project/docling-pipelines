# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for batch_subflow.py — covers _load_batch, _deserialize_batch_data,
and the top-level batch_subflow function.

batch_subflow() itself requires a live Prefect context (it is decorated with @flow)
so those paths are verified via the public helpers that the function delegates to.
The _load_batch / _deserialize_batch_data helpers are pure functions and can be
tested directly without any Prefect infrastructure.
"""

import base64
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException


class TestDeserializeBatchData:
    """Unit tests for _deserialize_batch_data."""

    def _call(self, batch_data):
        from docpipe.core.orchestration.prefect.batch_subflow import _deserialize_batch_data

        return _deserialize_batch_data(batch_data=batch_data)

    def test_round_trip_simple_table(self):
        """Serialise a table to the inline dict format then deserialise it back."""
        columns = ["id", "name"]
        data = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        batch_data = {"columns": columns, "data": data}

        result = self._call(batch_data)

        assert isinstance(result, pa.Table)
        assert result.num_rows == 2
        assert set(result.schema.names) == {"id", "name"}
        assert result.column("name").to_pylist() == ["alice", "bob"]

    def test_binary_columns_are_decoded(self):
        """Binary columns encoded as base64 strings are decoded back to bytes."""
        raw_bytes = b"hello binary"
        encoded = base64.b64encode(raw_bytes).decode("utf-8")

        columns = ["id", "payload"]
        data = [{"id": 1, "payload": encoded}]
        batch_data = {"columns": columns, "data": data, "binary_columns": ["payload"]}

        result = self._call(batch_data)

        assert result.column("payload")[0].as_py() == raw_bytes

    def test_non_binary_column_none_is_preserved(self):
        """None values in non-binary columns pass through unchanged."""
        columns = ["id", "notes"]
        data = [{"id": 1, "notes": None}, {"id": 2, "notes": "present"}]
        batch_data = {"columns": columns, "data": data}

        result = self._call(batch_data)

        assert result.column("notes").to_pylist() == [None, "present"]

    def test_binary_column_none_value_skipped(self):
        """None values inside a binary column are NOT decoded (guard in production code)."""
        columns = ["id", "payload"]
        data = [{"id": 1, "payload": None}]
        batch_data = {"columns": columns, "data": data, "binary_columns": ["payload"]}

        # Should not raise — None is left as-is
        result = self._call(batch_data)
        assert result.num_rows == 1

    def test_missing_columns_key_raises_flow_exception(self):
        """Missing required 'columns' key in batch_data raises FlowExecutionFailedException."""
        with pytest.raises(FlowExecutionFailedException, match="deserialization failed"):
            self._call({"data": []})  # no 'columns'


class TestLoadBatch:
    """Unit tests for _load_batch."""

    def _call(self, batch_transfer, batch_num=0):
        from docpipe.core.orchestration.prefect.batch_subflow import _load_batch

        return _load_batch(batch_transfer=batch_transfer, batch_num=batch_num)

    # ─── inline ─────────────────────────────────────────────────────────────

    def test_inline_loads_correctly(self):
        """Inline storage type deserialises the embedded dict."""
        columns = ["id", "text"]
        data = [{"id": 1, "text": "hello"}, {"id": 2, "text": "world"}]
        batch_transfer = {
            "type": "inline",
            "data": {"columns": columns, "data": data},
        }

        table = self._call(batch_transfer)

        assert isinstance(table, pa.Table)
        assert table.num_rows == 2

    def test_inline_default_type(self):
        """When 'type' key is absent, 'inline' is assumed."""
        columns = ["val"]
        data = [{"val": 42}]
        batch_transfer = {"data": {"columns": columns, "data": data}}  # no 'type'

        table = self._call(batch_transfer)
        assert table.num_rows == 1

    # ─── local ──────────────────────────────────────────────────────────────

    def test_local_reads_parquet_file(self, tmp_path):
        """'local' storage type reads a parquet file from disk."""
        expected = pa.table({"x": [10, 20], "y": ["a", "b"]})
        path = str(tmp_path / "batch.parquet")
        pq.write_table(expected, path)

        batch_transfer = {"type": "local", "ref": path}
        result = self._call(batch_transfer)

        assert result.num_rows == 2
        assert result.column("x").to_pylist() == [10, 20]

    def test_local_missing_file_raises(self):
        """Non-existent path in local storage raises FlowExecutionFailedException."""
        batch_transfer = {"type": "local", "ref": "/no/such/file.parquet"}

        with pytest.raises(FlowExecutionFailedException, match="Failed to load batch"):
            self._call(batch_transfer)

    # ─── s3 ─────────────────────────────────────────────────────────────────

    def test_s3_calls_read_table_with_filesystem(self):
        """S3 storage constructs an S3FileSystem and calls pq.read_table."""
        expected = pa.table({"col": [1, 2]})

        batch_transfer = {
            "type": "s3",
            "bucket": "my-bucket",
            "key": "batches/batch-0.parquet",
            "access_key": "AKID",
            "secret_key": "SECRET",  # pragma: allowlist secret
        }

        mock_fs = MagicMock()

        with patch("docpipe.core.orchestration.prefect.batch_subflow.pq") as mock_pq:
            with patch("pyarrow.fs.S3FileSystem", return_value=mock_fs):
                mock_pq.read_table.return_value = expected
                result = self._call(batch_transfer)

        mock_pq.read_table.assert_called_once()
        assert result is expected

    def test_s3_with_region_and_endpoint(self):
        """S3 kwargs include region and endpoint_override when provided."""
        captured_kwargs = {}

        def fake_s3_fs(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        batch_transfer = {
            "type": "s3",
            "bucket": "bkt",
            "key": "k/file.parquet",
            "access_key": "AK",
            "secret_key": "SK",  # pragma: allowlist secret
            "region": "us-east-1",
            "endpoint_url": "http://minio:9000",
        }

        with patch("docpipe.core.orchestration.prefect.batch_subflow.pq") as mock_pq:
            with patch("pyarrow.fs.S3FileSystem", side_effect=fake_s3_fs):
                mock_pq.read_table.return_value = pa.table({"a": [1]})
                self._call(batch_transfer)

        assert captured_kwargs["region"] == "us-east-1"
        assert captured_kwargs["endpoint_override"] == "http://minio:9000"

    def test_s3_read_error_raises_flow_exception(self):
        """S3 read failure wraps the error in FlowExecutionFailedException."""
        batch_transfer = {
            "type": "s3",
            "bucket": "bkt",
            "key": "file.parquet",
            "access_key": "AK",
            "secret_key": "SK",  # pragma: allowlist secret
        }

        with patch("pyarrow.fs.S3FileSystem") as mock_fs_cls:
            mock_fs_cls.return_value = MagicMock()
            with patch("docpipe.core.orchestration.prefect.batch_subflow.pq") as mock_pq:
                mock_pq.read_table.side_effect = OSError("network timeout")

                with pytest.raises(FlowExecutionFailedException, match="Failed to load batch"):
                    self._call(batch_transfer)

    # ─── unknown type ────────────────────────────────────────────────────────

    def test_unknown_storage_type_raises(self):
        """Unknown storage type raises FlowExecutionFailedException with descriptive message."""
        batch_transfer = {"type": "nfs", "ref": "/mnt/shared/batch.parquet"}

        with pytest.raises(FlowExecutionFailedException, match="Unknown batch storage type"):
            self._call(batch_transfer)

    # ─── FlowExecutionFailedException re-raised as-is ───────────────────────

    def test_flow_exception_from_deserialize_is_not_double_wrapped(self):
        """A FlowExecutionFailedException from _deserialize_batch_data is re-raised unchanged."""
        batch_transfer = {
            "type": "inline",
            "data": {},  # missing 'columns' — causes deserialization error
        }

        # The exception is FlowExecutionFailedException (not double-wrapped)
        with pytest.raises(FlowExecutionFailedException):
            self._call(batch_transfer)


class TestBatchSubflowIntegration:
    """
    Smoke tests for the batch_subflow @flow function.

    batch_subflow is decorated with @flow, so calling it outside a Prefect run
    context creates an ephemeral flow run. We patch enough infrastructure so the
    orchestrator initialisation and operator execution succeed without real deps.
    """

    def _make_simple_table(self):
        return pa.table({"id": [1, 2], "content": ["hello", "world"]})

    def test_batch_subflow_inline_happy_path(self):
        """batch_subflow with inline storage and a mocked operator flow completes."""
        columns = ["id", "content"]
        data = [{"id": 1, "content": "hello"}, {"id": 2, "content": "world"}]
        batch_transfer = {"type": "inline", "data": {"columns": columns, "data": data}}

        mock_engine = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.flow_engine = mock_engine

        mock_factory = MagicMock()
        mock_factory.create_job_stats_service.return_value = MagicMock()
        mock_factory.create_job_run_manager.return_value = MagicMock()

        with patch(
            "docpipe.core.orchestration.prefect.batch_subflow.get_default_factory",
            return_value=mock_factory,
        ):
            with patch(
                "docpipe.core.orchestration.prefect.batch_subflow.PythonOrchestrator",
                return_value=mock_orchestrator,
            ):
                with patch("docpipe.core.orchestration.prefect.batch_subflow.set_session_info"):
                    from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow

                    # Should not raise
                    batch_subflow(
                        job_run_id="jr-test-1",
                        batch_id="b-001",
                        batch_num=0,
                        batch_transfer=batch_transfer,
                        op_flow=[],
                        global_config={"job_id": "job-1"},
                    )

        mock_engine.execute_operator_flow.assert_called_once()

    def test_batch_subflow_raises_when_flow_engine_is_none(self):
        """batch_subflow wraps FlowExecutionFailedException when flow_engine is None."""
        columns = ["id"]
        data = [{"id": 1}]
        batch_transfer = {"type": "inline", "data": {"columns": columns, "data": data}}

        mock_orchestrator = MagicMock()
        mock_orchestrator.flow_engine = None  # <-- triggers the guard

        mock_factory = MagicMock()
        mock_factory.create_job_stats_service.return_value = MagicMock()
        mock_factory.create_job_run_manager.return_value = MagicMock()

        with patch(
            "docpipe.core.orchestration.prefect.batch_subflow.get_default_factory",
            return_value=mock_factory,
        ):
            with patch(
                "docpipe.core.orchestration.prefect.batch_subflow.PythonOrchestrator",
                return_value=mock_orchestrator,
            ):
                with patch("docpipe.core.orchestration.prefect.batch_subflow.set_session_info"):
                    from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow

                    with pytest.raises(FlowExecutionFailedException, match="Batch 1 failed"):
                        batch_subflow(
                            job_run_id="jr-test-2",
                            batch_id="b-002",
                            batch_num=1,
                            batch_transfer=batch_transfer,
                            op_flow=[],
                            global_config={"job_id": "job-1"},
                        )

    def test_batch_subflow_propagates_operator_error(self):
        """An exception inside execute_operator_flow is caught and re-raised as FlowExecutionFailedException."""
        columns = ["id"]
        data = [{"id": 1}]
        batch_transfer = {"type": "inline", "data": {"columns": columns, "data": data}}

        mock_engine = MagicMock()
        mock_engine.execute_operator_flow.side_effect = RuntimeError("operator boom")
        mock_orchestrator = MagicMock()
        mock_orchestrator.flow_engine = mock_engine

        mock_factory = MagicMock()
        mock_factory.create_job_stats_service.return_value = MagicMock()
        mock_factory.create_job_run_manager.return_value = MagicMock()

        with patch(
            "docpipe.core.orchestration.prefect.batch_subflow.get_default_factory",
            return_value=mock_factory,
        ):
            with patch(
                "docpipe.core.orchestration.prefect.batch_subflow.PythonOrchestrator",
                return_value=mock_orchestrator,
            ):
                with patch("docpipe.core.orchestration.prefect.batch_subflow.set_session_info"):
                    from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow

                    with pytest.raises(FlowExecutionFailedException, match="operator boom"):
                        batch_subflow(
                            job_run_id="jr-test-3",
                            batch_id="b-003",
                            batch_num=2,
                            batch_transfer=batch_transfer,
                            op_flow=[],
                            global_config={"job_id": "job-1"},
                        )


class TestBatchSubflowCustomOperatorSetting:
    """The worker orchestrator uses the submitter's resolved custom-operator setting (#575)."""

    @staticmethod
    def _worker_setting(*, global_config: dict) -> bool:
        """Run batch_subflow and return the setting its worker orchestrator resolves."""
        from docpipe.core.orchestration.operator_factory import OperatorFactory

        resolved = []

        def build_orchestrator(**kwargs):
            # AbstractOrchestrator resolves the argument the same way.
            resolved.append(
                OperatorFactory.resolve_enable_custom_operators(
                    enable_custom_operators=kwargs.get("enable_custom_operators")
                )
            )
            orchestrator = MagicMock()
            orchestrator.flow_engine = MagicMock()
            return orchestrator

        batch_transfer = {"type": "inline", "data": {"columns": ["id"], "data": [{"id": 1}]}}
        with (
            patch("docpipe.core.orchestration.prefect.batch_subflow.get_default_factory", return_value=MagicMock()),
            patch(
                "docpipe.core.orchestration.prefect.batch_subflow.PythonOrchestrator",
                side_effect=build_orchestrator,
            ),
            patch("docpipe.core.orchestration.prefect.batch_subflow.set_session_info"),
        ):
            from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow

            batch_subflow(
                job_run_id="jr-custom-ops",
                batch_id="b-custom-ops",
                batch_num=0,
                batch_transfer=batch_transfer,
                op_flow=[],
                global_config=global_config,
            )
        return resolved[0]

    @pytest.mark.parametrize("worker_env", [None, "false"])
    def test_explicit_opt_in_survives_a_worker_without_the_flag(self, monkeypatch, worker_env):
        if worker_env is None:
            monkeypatch.delenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", raising=False)
        else:
            monkeypatch.setenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", worker_env)

        assert self._worker_setting(global_config={"job_id": "job-1", "enable_custom_operators": True}) is True

    def test_explicit_opt_out_stays_disabled_when_the_worker_enables_them(self, monkeypatch):
        monkeypatch.setenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", "true")

        assert self._worker_setting(global_config={"job_id": "job-1", "enable_custom_operators": False}) is False

    @pytest.mark.parametrize(("worker_env", "expected"), [("true", True), (None, False)])
    def test_without_a_submitted_setting_the_worker_environment_decides(self, monkeypatch, worker_env, expected):
        if worker_env is None:
            monkeypatch.delenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", raising=False)
        else:
            monkeypatch.setenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", worker_env)

        assert self._worker_setting(global_config={"job_id": "job-1"}) is expected
