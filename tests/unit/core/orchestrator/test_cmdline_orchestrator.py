import os
import tempfile
import unittest
from pathlib import Path

from docpipe.cli.docpipe_cli import (
    load_flow_definition,
    run_command_line_executor,
)
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import FlowValidationException

_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class TestCommandLineOrchestrator(unittest.TestCase):
    def setUp(self):
        os.environ["test_mode"] = "True"
        os.environ[DocpipeConstants.DATA_FOLDER] = "/tmp/data"

    def test_basic_flow(self):
        """
        Test orchestrating a basic pipeline with two operators
        """
        flow_def = {
            "name": "test-basic-flow",
            "dag": [
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9500",
                    "name": "ingest",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.INGEST_SOURCE,
                    "config": {
                        "provider": "filesystem",
                        "provider_config": {
                            "paths": [str(_PROJECT_ROOT / "tests" / "fixtures" / "customer_support_docs")]
                        },
                        "include_filter": "txt",
                    },
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9501"}],
                },
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9501",
                    "name": "Sleep",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.NOOP,
                    "config": {"sleep_sec": 2},
                    "input_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9500"}],
                    "output_edges": [],
                },
            ],
        }

        run_command_line_executor(flow_def=flow_def)

    def test_load_flow_definition(self):
        """
        Test loading a flow definition from a file
        """
        from docpipe.cli.docpipe_cli import load_flow_definition

        filepath = str(_PROJECT_ROOT / "sample_flows" / "quickstart" / "complete_pipeline_ollama.json")

        original_flow, flow_def = load_flow_definition(file_path=filepath)
        # After compilation, should have runtime DAG format
        assert flow_def is not None
        assert "dag" in flow_def
        assert "global_config" in flow_def
        assert original_flow is not None

    def test_invalid_flow_definition(self):
        """
        Test handling of invalid flow definition (missing 'sequence' or 'dag')
        """
        # Create an invalid flow definition without sequence or dag
        invalid_flow_def = {
            "name": "invalid flow",
            "flow_id": "12345",
            "description": "This flow is invalid",
        }

        # Test that the orchestrator raises an exception for invalid flow
        with self.assertRaises(FlowValidationException):
            run_command_line_executor(flow_def=invalid_flow_def)

    def test_file_not_found_exception(self):
        """
        Test handling of FileNotFoundError in load_flow_definition
        """
        # Use a non-existent file path
        file_path = "non_existent_file.json"

        # load_flow_definition now raises FileNotFoundError instead of calling sys.exit
        with self.assertRaises(FileNotFoundError):
            load_flow_definition(file_path=file_path)

    def test_invalid_json_exception(self):
        """
        Test handling of invalid JSON in load_flow_definition
        """
        import json

        # Create a temporary file with invalid JSON content
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("{ This is not valid JSON }")
            temp_file_path = temp_file.name

        try:
            # load_flow_definition now raises JSONDecodeError instead of calling sys.exit
            with self.assertRaises(json.JSONDecodeError):
                load_flow_definition(file_path=temp_file_path)
        finally:
            # Clean up the temporary file
            Path(temp_file_path).unlink()

    def test_flow_execution_failure(self):
        """
        Test handling of flow execution failure
        """

        # Create a simple flow definition
        flow_def = {
            "name": "test-flow-execution-failure",
            "dag": [
                {
                    "id": "test-id",
                    "name": "test-operator",
                    OperatorConstants.Misc.OPERATOR: "test-operator",
                    "config": {},
                    "input_edges": [],
                    "output_edges": [],
                }
            ],
        }

        # Test that the exception is propagated
        with self.assertRaises(FlowValidationException):
            run_command_line_executor(flow_def=flow_def)
