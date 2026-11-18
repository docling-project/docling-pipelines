import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe.cli.docpipe_cli import (
    generate_job_id_from_flow_name,
    load_flow_definition,
    run_command_line_executor,
    sanitize_flow_name_for_job_id,
)
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import FlowValidationException


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
            "global_config": {"force_ingest": True},
            "dag": [
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9500",
                    "name": "ingest",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.INGEST_SOURCE,
                    "config": {
                        "provider": "filesystem",
                        "provider_config": {"paths": ["tests/fixtures/customer_support_docs"]},
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

        # Use a path relative to the repo root so it works regardless of cwd
        repo_root = Path(__file__).parent.parent
        filepath = str(repo_root / "sample_flows" / "quickstart" / "complete_pipeline_ollama.json")

        if not Path(filepath).exists():
            pytest.skip(f"Sample flow file not found: {filepath}")

        original_flow, flow_def = load_flow_definition(file_path=filepath)
        assert flow_def is not None
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
        file_path = "non_existent_file.json"

        # load_flow_definition raises FileNotFoundError directly — verify it propagates
        with pytest.raises(FileNotFoundError):
            load_flow_definition(file_path=file_path)

    def test_invalid_json_exception(self):
        """
        Test handling of invalid JSON in load_flow_definition
        """
        import json

        # Create a temporary file with invalid JSON content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
            temp_file.write("{ This is not valid JSON }")
            temp_file_path = temp_file.name

        try:
            # load_flow_definition raises JSONDecodeError directly — verify it propagates
            with pytest.raises(json.JSONDecodeError):
                load_flow_definition(file_path=temp_file_path)
        finally:
            Path(temp_file_path).unlink()

    def test_flow_execution_failure(self):
        """
        Test handling of flow execution failure
        """
        from docpipe.core.orchestration.flow_executor import FlowExecutor

        # Create a simple flow definition with an unknown operator to force a validation error
        flow_def = {
            "name": "test-flow-execution-failure",
            "dag": [
                {
                    "id": "test-id",
                    "name": "test-operator",
                    OperatorConstants.Misc.OPERATOR: "non_existent_operator_xyz",
                    "config": {},
                    "input_edges": [],
                    "output_edges": [],
                }
            ],
        }

        # Patch FlowExecutor.execute to raise so the exception propagates out of run_command_line_executor
        with patch.object(FlowExecutor, "execute", side_effect=Exception("Flow execution failed")):
            with self.assertRaises(Exception):  # noqa: B017
                run_command_line_executor(flow_def=flow_def)

    def test_merge_operator_flow(self):
        """
        Test orchestrating a pipeline with merge operator (row merge)
        """
        flow_def = {  # noqa: F841
            "name": "test-merge-operator-flow",
            "dag": [
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9510",
                    "name": "ingest",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.INGEST_SOURCE,
                    "config": {
                        "provider": "filesystem",
                        "provider_config": {"paths": ["tests/fixtures/customer_support_docs"]},
                        "include_filter": "txt",
                    },
                    "input_edges": [],
                    "output_edges": [
                        {"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9511"},
                        {"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9512"},
                    ],
                },
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9511",
                    "name": "branch1_noop",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.NOOP,
                    "config": {"sleep_sec": 0},
                    "input_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9510"}],
                    "output_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9513"}],
                },
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9512",
                    "name": "branch2_noop",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.NOOP,
                    "config": {"sleep_sec": 0},
                    "input_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9510"}],
                    "output_edges": [{"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9513"}],
                },
                {
                    "id": "e9c41958-2d27-4c02-ab03-789e031b9513",
                    "name": "merge_branches",
                    OperatorConstants.Misc.OPERATOR: OperatorConstants.Operators.MERGE,
                    "config": {
                        "merge_type": "rows",
                        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
                    },
                    "input_edges": [
                        {"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9511", "link_name": "branch1"},
                        {"node_id_ref": "e9c41958-2d27-4c02-ab03-789e031b9512", "link_name": "branch2"},
                    ],
                    "output_edges": [],
                },
            ],
        }


class TestSanitizeFlowNameForJobId:
    """
    Comprehensive test suite for sanitize_flow_name_for_job_id function.
    Tests various input scenarios including valid names, special characters,
    Unicode characters, and edge cases.
    """

    @pytest.mark.parametrize(
        "flow_name,expected",
        [
            # Valid flow names - simple cases
            ("my-flow", "my-flow"),
            ("simple", "simple"),
            ("flow123", "flow123"),
            # Mixed case conversion
            ("My Flow Name", "my-flow-name"),
            ("UPPERCASE", "uppercase"),
            ("MixedCase", "mixedcase"),
            ("CamelCaseFlow", "camelcaseflow"),
            # With spaces
            ("Invoice Processing", "invoice-processing"),
            ("my flow", "my-flow"),
            ("data   pipeline", "data-pipeline"),
            # With underscores (underscores are preserved as word characters)
            ("my_flow_name", "my_flow_name"),
            ("test_flow", "test_flow"),
            ("flow_with_multiple_underscores", "flow_with_multiple_underscores"),
            # Special characters
            ("My Flow! @2024", "my-flow-2024"),
            ("Flow::Name--Test", "flow-name-test"),
            ("Flow (Test)", "flow-test"),
            ("flow@name#test", "flow-name-test"),
            ("flow$name%test", "flow-name-test"),
            ("flow&name*test", "flow-name-test"),
            ("flow+name=test", "flow-name-test"),
            ("flow[name]test", "flow-name-test"),
            ("flow{name}test", "flow-name-test"),
            ("flow|name\\test", "flow-name-test"),
            ("flow;name:test", "flow-name-test"),
            ("flow'name\"test", "flow-name-test"),
            ("flow<name>test", "flow-name-test"),
            ("flow,name.test", "flow-name-test"),
            ("flow?name/test", "flow-name-test"),
            # Unicode characters - Chinese
            ("文档处理流程", "文档处理流程"),
            ("My 文档 Flow", "my-文档-flow"),
            ("数据管道", "数据管道"),
            # Unicode characters - Arabic
            ("معالجة المستندات", "معالجة-المستندات"),
            ("تدفق البيانات", "تدفق-البيانات"),
            # Unicode characters - Japanese
            ("データパイプライン", "データパイプライン"),
            ("フロー処理", "フロー処理"),
            # Unicode characters - Korean
            ("데이터파이프라인", "데이터파이프라인"),
            ("문서처리", "문서처리"),
            # Unicode characters - Cyrillic
            ("обработка документов", "обработка-документов"),
            ("поток данных", "поток-данных"),
            # Unicode characters - Greek
            ("επεξεργασία εγγράφων", "επεξεργασία-εγγράφων"),
            # Mixed Unicode and ASCII
            ("My 文档 Flow 2024", "my-文档-flow-2024"),
            ("Data パイプライン Test", "data-パイプライン-test"),
            ("Flow معالجة Name", "flow-معالجة-name"),
            # Edge cases - leading/trailing spaces
            ("  my flow  ", "my-flow"),
            ("   flow   ", "flow"),
            ("\tflow\t", "flow"),
            ("\nflow\n", "flow"),
            # Edge cases - multiple consecutive spaces
            ("my    flow", "my-flow"),
            ("flow     name     test", "flow-name-test"),
            # Edge cases - leading/trailing hyphens
            ("--my-flow--", "my-flow"),
            ("---flow---", "flow"),
            ("-flow-", "flow"),
            # Edge cases - mixed separators
            ("my__flow--name", "my__flow-name"),
            ("flow___test", "flow___test"),
            ("test---flow", "test-flow"),
            # Long names
            (
                "this-is-a-very-long-flow-name-with-many-words-and-hyphens",
                "this-is-a-very-long-flow-name-with-many-words-and-hyphens",
            ),
            ("VeryLongCamelCaseFlowNameWithManyWordsAndNoSpaces", "verylongcamelcaseflownamewithmanywordsandnospaces"),
            # Numbers and alphanumeric
            ("flow-v1.0", "flow-v1-0"),
            ("pipeline_2024_q1", "pipeline_2024_q1"),
            ("test123flow456", "test123flow456"),
            # Real-world examples
            ("Invoice Processing Pipeline", "invoice-processing-pipeline"),
            ("Customer_Support_Flow", "customer_support_flow"),
            ("Data Quality Check (v2)", "data-quality-check-v2"),
            ("ETL::Extract->Transform->Load", "etl-extract-transform-load"),
        ],
    )
    def test_sanitize_flow_name(self, flow_name, expected):
        """Test sanitize_flow_name_for_job_id with various inputs."""
        result = sanitize_flow_name_for_job_id(flow_name=flow_name)
        assert result == expected

    @pytest.mark.parametrize(
        "invalid_flow_name",
        [
            "",  # Empty string
            "   ",  # Whitespace only
            "\t\t",  # Tabs only
            "\n\n",  # Newlines only
            "  \t\n  ",  # Mixed whitespace
        ],
    )
    def test_sanitize_empty_or_whitespace_raises_error(self, invalid_flow_name):
        """Test that empty or whitespace-only flow_name raises ValueError."""
        with pytest.raises(ValueError, match="flow_name cannot be empty"):
            sanitize_flow_name_for_job_id(flow_name=invalid_flow_name)


class TestGenerateJobIdFromFlowName:
    """Tests for generate_job_id_from_flow_name function."""

    def test_generate_deterministic(self):
        """Test job_id generation is deterministic."""
        job_id1 = generate_job_id_from_flow_name(flow_name="test-flow")
        job_id2 = generate_job_id_from_flow_name(flow_name="test-flow")
        assert job_id1 == job_id2

    def test_generate_format_is_uuid(self):
        """Test job_id format is UUID v5 (36 characters with hyphens)."""
        job_id = generate_job_id_from_flow_name(flow_name="test-flow")
        # UUID format: 8-4-4-4-12 (36 chars total including hyphens)
        assert len(job_id) == 36
        assert job_id.count("-") == 4
        parts = job_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    def test_generate_different_names_different_ids(self):
        """Test different flow_names produce different job_ids."""
        job_id1 = generate_job_id_from_flow_name(flow_name="flow-one")
        job_id2 = generate_job_id_from_flow_name(flow_name="flow-two")
        assert job_id1 != job_id2
        # Both should be valid UUIDs
        assert len(job_id1) == 36
        assert len(job_id2) == 36

    def test_generate_uuid_consistency(self):
        """Test UUID is consistent for same input."""
        job_id1 = generate_job_id_from_flow_name(flow_name="consistent-test")
        job_id2 = generate_job_id_from_flow_name(flow_name="consistent-test")
        assert job_id1 == job_id2
        assert len(job_id1) == 36

    def test_generate_uuid_different_for_different_input(self):
        """Test UUID differs for different inputs."""
        job_id1 = generate_job_id_from_flow_name(flow_name="flow-a")
        job_id2 = generate_job_id_from_flow_name(flow_name="flow-b")
        assert job_id1 != job_id2
        assert len(job_id1) == 36
        assert len(job_id2) == 36

    @pytest.mark.parametrize(
        "flow_name",
        [
            "My Test Flow",
            "测试流程",
            "データ処理フロー",
            "데이터 처리",
            "تدفق البيانات",
            "Production Pipeline v2.0 (2024)",
            "My 文档 Flow 2024",
        ],
    )
    def test_generate_with_various_flow_names(self, flow_name):
        """Test job_id generation with various flow_names produces valid UUIDs."""
        job_id = generate_job_id_from_flow_name(flow_name=flow_name)
        # Should be valid UUID format
        assert len(job_id) == 36
        assert job_id.count("-") == 4
        # Should be deterministic
        job_id2 = generate_job_id_from_flow_name(flow_name=flow_name)
        assert job_id == job_id2

    def test_generate_empty_flow_name_raises_error(self):
        """Test empty flow_name raises ValueError through sanitization."""
        with pytest.raises(ValueError, match="flow_name cannot be empty"):
            generate_job_id_from_flow_name(flow_name="")

    def test_generate_postgresql_compatible_length(self):
        """Test job_id is exactly 36 characters (PostgreSQL compatible)."""
        # Test with various flow names
        flow_names = [
            "short",
            "this-is-a-very-long-flow-name-with-many-words-and-characters",
            "测试流程名称很长",
            "My Complex Flow Name (v2.0) - Production 2024",
        ]
        for flow_name in flow_names:
            job_id = generate_job_id_from_flow_name(flow_name=flow_name)
            assert len(job_id) == 36, f"job_id length {len(job_id)} != 36 for flow_name: {flow_name}"
