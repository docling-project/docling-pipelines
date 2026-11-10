# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ingest_source global_config population."""

from unittest.mock import Mock, patch

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator


class TestIngestSourceGlobalConfig:
    """Test that ingest_source params are populated in global_config."""

    @patch("docpipe.core.orchestration.abstract_orchestrator.get_session_info")
    @patch("docpipe.core.orchestration.abstract_orchestrator.set_session_info")
    def test_ingest_source_populates_global_config(self, mock_set_session, mock_get_session):
        """Test that ingest_source operator params are added to global_config."""
        # Setup session info mock
        mock_session = Mock()
        mock_session.flow_id = "test_flow"
        mock_get_session.return_value = mock_session

        # Create orchestrator
        orchestrator = PythonOrchestrator()

        # Define a flow with ingest_source operator
        flow_def = {
            "name": "Test Flow",
            "description": "Test ingest_source global_config population",
            "dag": [
                {
                    "id": "ingest_node",
                    "name": "ingest_source_node",
                    "operator": "docpipe.core.operators.ingest.ingest_source.IngestSourceOperator",
                    "config": {
                        "provider": "s3",
                        "provider_config": {
                            "bucket": "test-bucket",
                            "prefix": "test-prefix",
                            "aws_access_key_id": "test_key",
                            "aws_secret_access_key": "test_secret",  # pragma: allowlist secret
                        },
                    },
                    "output_edges": [],
                }
            ],
        }

        params = {
            DocpipeConstants.JOB_ID: "test_job",
            DocpipeConstants.JOB_RUN_ID: "test_run",
        }

        # Capture global_config by wrapping execute_flow
        captured_global_config = {}
        original_execute_flow = orchestrator.execute_flow

        def wrapped_execute_flow(*, op_flow, global_config):
            # Call original to let it populate global_config
            try:
                original_execute_flow(op_flow=op_flow, global_config=global_config)
            except Exception:
                # Ignore any errors from actual execution
                pass
            finally:
                # Capture the global_config after population
                captured_global_config.update(global_config)

        # Mock _execute_step to prevent real operator execution
        def mock_execute_step(*, op_def, global_config, prev_results, deleted_docs_count):
            from docpipe.core.orchestration.prefect.prefect_engine import ExecuteStepResults

            return ExecuteStepResults(
                tables=[pa.Table.from_arrays([], names=[])],
                data_accesses=[Mock()],
                internal_metadata={},
            )

        # Mock other methods to prevent actual execution
        with patch.object(orchestrator, "_execute_step", side_effect=mock_execute_step):
            with patch.object(orchestrator, "execute_flow", side_effect=wrapped_execute_flow):
                with patch.object(orchestrator, "_finalize_dag_flow"):
                    with patch("docpipe.core.orchestration.abstract_orchestrator.clean_up_prefect_home"):
                        # Execute the flow
                        orchestrator.execute(flow_def=flow_def, params=params)
                        # Only non-secret source facts reach shared configuration (design D6)
                        ingest_source = captured_global_config["ingest_source"]
                        assert ingest_source["provider"] == "s3"
                        assert ingest_source["node_id"] == "ingest_node"
                        assert ingest_source["provider_config"] == {"prefix": "test-prefix"}
                        assert "test_key" not in str(ingest_source)
                        assert "test_secret" not in str(ingest_source)
