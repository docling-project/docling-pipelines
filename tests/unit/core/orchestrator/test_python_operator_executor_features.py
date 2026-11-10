# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for feature dropping and renaming in PythonOperatorExecutor."""

from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor


class TestPythonOperatorExecutorFeatures:
    """Test feature dropping and renaming on PythonOperatorExecutor."""

    @pytest.fixture
    def mock_operator(self):
        """Create a mock operator."""
        operator = Mock()
        operator.name = "test_operator"
        operator.short_name = "test_op"
        operator.doc_column = OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        operator.common_log_arguments = {}
        operator.config = {
            OperatorConstants.Columns.ID: "node_1",
            "job_id": "test_job",
            "job_run_id": "test_run",
        }
        operator._create_operator_span = Mock(return_value=Mock())
        operator._record_operator_metrics = Mock()
        return operator

    @pytest.fixture
    def executor(self, mock_operator):
        """Create a PythonOperatorExecutor instance for testing."""
        executor = PythonOperatorExecutor(
            name="test_executor",
            operator="test_operator",
            params={
                OperatorConstants.Columns.ID: "node_1",
                OperatorConstants.Columns.NAME: "test_executor",
                "job_id": "test_job",
                "job_run_id": "test_run",
            },
        )
        executor.get_operator = Mock(return_value=mock_operator)
        return executor

    @patch("docpipe.core.orchestration.python.python_operator_executor.log_memory_usage")
    @patch("docpipe.core.orchestration.python.python_operator_executor.cleanup_pyarrow_buffers")
    def test_execute_impl_applies_drops_and_renames_to_multiple_tables(
        self, mock_cleanup, mock_log_mem, executor, mock_operator
    ):
        """Test that output_features_to_drop and updated_features are applied to all returned tables."""
        # 1. Setup mock operator attributes and transform result
        mock_operator.output_features_to_drop = ["secret"]
        mock_operator.updated_features = [{"old_feature": "content", "new_feature": "text"}]

        table1 = pa.table(
            {
                "id": ["doc1"],
                "content": ["hello"],
                "secret": ["sssh"],
            }
        )
        table2 = pa.table(
            {
                "id": ["doc2"],
                "content": ["world"],
                "secret": ["dontlook"],
            }
        )

        # Mock transform to return 2 tables
        mock_operator.transform = Mock(return_value=([table1, table2], {"metric": 1}))

        # 2. Patch executor methods that have database or logging side effects
        with (
            patch.object(executor, "_log_start"),
            patch.object(executor, "set_default_node_stats"),
            patch.object(executor, "update_final_node_stats"),
            patch.object(executor, "_log_completion"),
            patch.object(
                executor, "_handle_empty_documents", side_effect=lambda out_tables, metadata: (out_tables, metadata)
            ),
        ):
            out_tables, _metadata = executor._execute_impl(tables=None)

            # 3. Assertions
            assert len(out_tables) == 2

            # Assert secret column is dropped from both tables
            assert "secret" not in out_tables[0].column_names
            assert "secret" not in out_tables[1].column_names

            # Assert content column is renamed to text in both tables
            assert "text" in out_tables[0].column_names
            assert "content" not in out_tables[0].column_names
            assert "text" in out_tables[1].column_names
            assert "content" not in out_tables[1].column_names

            assert out_tables[0]["text"].to_pylist() == ["hello"]
            assert out_tables[1]["text"].to_pylist() == ["world"]

    @patch("docpipe.core.orchestration.python.python_operator_executor.log_memory_usage")
    @patch("docpipe.core.orchestration.python.python_operator_executor.cleanup_pyarrow_buffers")
    def test_execute_impl_applies_drops_and_renames_to_merge_operator(
        self, mock_cleanup, mock_log_mem, executor, mock_operator
    ):
        """Test that drops and renames are also applied when executing a merge operator."""
        # 1. Setup mock operator attributes and transform result
        mock_operator.output_features_to_drop = ["secret"]
        mock_operator.updated_features = [{"old_feature": "content", "new_feature": "text"}]

        table1 = pa.table(
            {
                "id": ["doc1"],
                "content": ["hello"],
                "secret": ["sssh"],
            }
        )

        mock_operator.transform = Mock(return_value=([table1], {"metric": 1}))

        # 2. Patch executor methods
        with (
            patch.object(executor, "_log_start"),
            patch.object(executor, "set_default_node_stats"),
            patch.object(executor, "update_final_node_stats"),
            patch.object(executor, "_log_completion"),
        ):
            # Pass a dict to simulate is_merge_operator = True
            input_tables = {"input1": pa.table({"id": ["doc1"]})}
            out_tables, _metadata = executor._execute_impl(tables=input_tables)

            # 3. Assertions
            assert len(out_tables) == 1
            assert "secret" not in out_tables[0].column_names
            assert "text" in out_tables[0].column_names
            assert "content" not in out_tables[0].column_names
