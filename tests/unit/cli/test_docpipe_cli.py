"""
Integration-style tests for CLI validation features.

Tests cover:
- --validate flag with valid/invalid flows
- validate-flow command with valid/invalid flows
- Error handling (FileNotFoundError, JSONDecodeError, FlowValidationException)
- Backward compatibility
- --list-operators functionality
- Help text display
- Validation with warnings

Uses real components where possible to minimize mocking.
"""

import json
from unittest.mock import Mock, patch

import pytest

from docpipe.cli.docpipe_cli import (
    _execute_flow_or_exit,
    _load_flow_or_exit,
    load_flow_definition,
    main,
    validate_flow_definition,
)
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.global_config_metadata import EXECUTION_CONTROL


@pytest.fixture
def real_flow_invoice(project_root):
    """Return path to real invoice flow file."""
    return str(project_root / "sample_flows" / "use_cases" / "invoice_processing.json")


@pytest.fixture
def valid_flow_dict_with_output(fixtures_customer_support_dir):
    """Return a valid flow definition dictionary with output operator in authoring format."""
    return {
        "flow_name": "test_flow",
        "description": "Test flow for CLI validation",
        "flow": [
            {
                "type": OperatorConstants.Operators.INGEST_SOURCE,
                "name": "ingest",
                "depends_on": [],
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": [str(fixtures_customer_support_dir)]},
                    "include_filter": "txt",
                },
            },
            {
                "type": OperatorConstants.Operators.NOOP,
                "name": "noop",
                "depends_on": ["ingest"],
                "config": {"sleep_sec": 1},
            },
        ],
        "global_config": {},
    }


@pytest.fixture
def valid_flow_dict(valid_flow_dict_with_output):
    """Alias for backward compatibility."""
    return valid_flow_dict_with_output


@pytest.fixture
def invalid_flow_dict():
    """Return an invalid flow definition (missing flow array)."""
    return {
        "flow_name": "invalid_flow",
        "description": "This flow is missing flow array",
        "global_config": {},
    }


@pytest.fixture
def valid_flow_file(tmp_path, valid_flow_dict):
    """Create a temporary file with valid flow definition."""
    flow_file = tmp_path / "valid_flow.json"
    flow_file.write_text(json.dumps(valid_flow_dict))
    return str(flow_file)


@pytest.fixture
def invalid_flow_file(tmp_path, invalid_flow_dict):
    """Create a temporary file with invalid flow definition."""
    flow_file = tmp_path / "invalid_flow.json"
    flow_file.write_text(json.dumps(invalid_flow_dict))
    return str(flow_file)


@pytest.fixture
def malformed_json_file(tmp_path):
    """Create a temporary file with malformed JSON."""
    flow_file = tmp_path / "malformed.json"
    flow_file.write_text("{ This is not valid JSON }")
    return str(flow_file)


@pytest.fixture
def elyra_format_file(tmp_path):
    """Create a temporary file with Elyra format (not supported by CLI load_flow_definition)."""
    flow_file = tmp_path / "elyra_flow.json"
    # Elyra format structure
    elyra_flow = {
        "definition": {
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [
                {
                    "id": "pipeline1",
                    "nodes": [
                        {
                            "id": "node1",
                            "type": "execution_node",
                            "op": "ingest_source",
                            "parameters": {"provider": "filesystem", "paths": ["./data"], "include_filter": "txt"},
                        }
                    ],
                }
            ],
            "parameters": {},
        }
    }
    flow_file.write_text(json.dumps(elyra_flow))
    return str(flow_file)


class TestLoadFlowDefinition:
    """Tests for load_flow_definition function using real file operations."""

    def test_load_valid_flow(self, valid_flow_file):
        """Test loading a valid flow definition from real file."""
        original_flow, flow_def = load_flow_definition(file_path=valid_flow_file)
        # After compilation, should have runtime DAG format
        assert "dag" in flow_def
        assert len(flow_def["dag"]) == 2
        assert "global_config" in flow_def
        # Original flow should also be returned
        assert original_flow is not None
        assert "flow_name" in original_flow

    def test_load_elyra_format_fails(self, elyra_format_file):
        """Test that Elyra format (with 'definition' wrapper) is not supported by CLI."""
        # CLI's load_flow_definition only supports authoring format, not Elyra format
        # Missing 'flow_name' raises FlowInvalidDataException (not a raw KeyError)
        from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

        with pytest.raises(FlowInvalidDataException) as exc_info:
            load_flow_definition(file_path=elyra_format_file)

        assert "flow_name" in str(exc_info.value)

    def test_load_real_invoice_flow(self, real_flow_invoice):
        """Test loading the real invoice flow file."""
        original_flow, flow_def = load_flow_definition(file_path=real_flow_invoice)
        # After compilation, should have runtime DAG format
        assert "dag" in flow_def
        assert len(flow_def["dag"]) == 6
        assert "global_config" in flow_def
        # Original flow should also be returned
        assert original_flow is not None
        assert "flow_name" in original_flow

    def test_file_not_found(self, tmp_path):
        """Test FileNotFoundError is raised for non-existent files."""
        non_existent = str(tmp_path / "does_not_exist.json")

        with pytest.raises(FileNotFoundError):
            load_flow_definition(file_path=non_existent)

    def test_invalid_json(self, malformed_json_file):
        """Test JSONDecodeError is raised for malformed JSON."""
        with pytest.raises(json.JSONDecodeError):
            load_flow_definition(file_path=malformed_json_file)


class TestValidateFlowDefinition:
    """Tests for validate_flow_definition function - only mock orchestrator execution."""

    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    def test_validate_invalid_flow_missing_flow_array(
        self,
        mock_orchestrator_factory,
        invalid_flow_file,
    ):
        """Test validation fails with invalid flow (missing flow array)."""
        result = validate_flow_definition(flow_file=invalid_flow_file)

        assert result is False

    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    def test_validate_unexpected_exception(self, mock_orchestrator_factory, valid_flow_file):
        """Test validation handles unexpected exceptions."""
        mock_orchestrator_factory.side_effect = RuntimeError("Unexpected error")

        result = validate_flow_definition(flow_file=valid_flow_file)

        assert result is False


class TestMainCLI:
    """Tests for main CLI function with minimal mocking."""

    @patch("docpipe.cli.docpipe_cli.validate_flow_definition")
    @patch("sys.argv", ["docling-pipelines", "validate-flow", "test.json"])
    def test_validate_flow_command_success(self, mock_validate):
        """Test validate-flow subcommand with successful validation."""
        mock_validate.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_validate.assert_called_once_with(flow_file="test.json")

    @patch("docpipe.cli.docpipe_cli.validate_flow_definition")
    @patch("sys.argv", ["docling-pipelines", "validate-flow", "test.json"])
    def test_validate_flow_command_failure(self, mock_validate):
        """Test validate-flow subcommand with failed validation."""
        mock_validate.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_validate.assert_called_once_with(flow_file="test.json")

    @patch("docpipe.cli.docpipe_cli.run_command_line_executor")
    @patch("sys.argv", ["docling-pipelines", "--flow-file", "test.json"])
    def test_backward_compatibility_execution(self, mock_execute, valid_flow_file):
        """Test backward compatibility: --flow-file without --validate executes flow."""
        with patch("sys.argv", ["docling-pipelines", "--flow-file", valid_flow_file]):
            main()

        mock_execute.assert_called_once()

    @patch("builtins.print")
    @patch("docpipe.utils.operators.display.list_operators")
    @patch("sys.argv", ["docling-pipelines", "--list-operators"])
    def test_list_operators(self, mock_list_ops, mock_print):
        """Test --list-operators functionality."""
        mock_list_ops.return_value = "Operator list output"

        main()

        mock_list_ops.assert_called_once_with(verbose=False, summary_only=True)
        mock_print.assert_called_once()

    @patch("builtins.print")
    @patch("docpipe.utils.operators.display.list_operators")
    @patch("sys.argv", ["docling-pipelines", "--list-operators", "--verbose"])
    def test_list_operators_verbose(self, mock_list_ops, mock_print):
        """Test --list-operators with --verbose flag."""
        mock_list_ops.return_value = "Detailed operator list"

        main()

        mock_list_ops.assert_called_once_with(verbose=True, summary_only=False)

    @pytest.mark.parametrize(
        ("cli_args", "expected_category", "expected_verbose"),
        [
            (["list-global-config"], None, False),
            (["--category", EXECUTION_CONTROL, "list-global-config"], EXECUTION_CONTROL, False),
            (["list-global-config", "--category", EXECUTION_CONTROL], EXECUTION_CONTROL, False),
            (["--verbose", "list-global-config"], None, True),
            (["list-global-config", "--verbose"], None, True),
            (
                ["--verbose", "--category", EXECUTION_CONTROL, "list-global-config"],
                EXECUTION_CONTROL,
                True,
            ),
            (
                ["list-global-config", "--verbose", "--category", EXECUTION_CONTROL],
                EXECUTION_CONTROL,
                True,
            ),
        ],
        ids=[
            "defaults-summary",
            "category-before-summary",
            "category-after-summary",
            "verbose-before-detailed",
            "verbose-after-detailed",
            "options-before-detailed",
            "options-after-detailed",
        ],
    )
    @patch("docpipe.utils.global_config.display.list_global_config")
    def test_list_global_config_option_ordering(
        self,
        mock_list_global_config,
        monkeypatch,
        cli_args,
        expected_category,
        expected_verbose,
    ):
        """Explicit options are preserved on either side of the subcommand."""
        mock_list_global_config.return_value = "Global config output"
        monkeypatch.setattr("sys.argv", ["docling-pipelines", *cli_args])

        main()

        mock_list_global_config.assert_called_once_with(
            category=expected_category,
            verbose=expected_verbose,
        )

    @patch("sys.argv", ["docling-pipelines"])
    def test_missing_flow_file_error(self):
        """Test error when --flow-file is missing."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2

    @patch("sys.argv", ["docling-pipelines", "--help"])
    def test_help_text(self):
        """Test help text displays correctly."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0

    @patch("docpipe.cli.docpipe_cli.validate_flow_definition")
    @patch("sys.argv", ["docling-pipelines", "validate-flow", "test.json"])
    def test_validate_flow_with_log_level(self, mock_validate, monkeypatch):
        """Test validate-flow command with custom log level via DS_LOG_LEVEL env var."""
        mock_validate.return_value = True
        monkeypatch.setenv(EnvironmentVariables.DS_LOG_LEVEL, "DEBUG")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_validate.assert_called_once_with(flow_file="test.json")

    @patch("docpipe.cli.docpipe_cli.validate_flow_definition")
    @patch("sys.argv", ["docling-pipelines", "--flow-file", "test.json", "--validate"])
    def test_validate_flag_with_flow_file(self, mock_validate):
        """Test --validate flag with --flow-file (backward compatibility)."""
        mock_validate.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_validate.assert_called_once_with(flow_file="test.json")

    @patch("docpipe.cli.docpipe_cli.validate_flow_definition")
    @patch("sys.argv", ["docling-pipelines", "--flow-file", "test.json", "--validate"])
    def test_validate_flag_with_custom_log_level(self, mock_validate, monkeypatch):
        """Test --validate flag with custom log level via DS_LOG_LEVEL env var."""
        mock_validate.return_value = False
        monkeypatch.setenv(EnvironmentVariables.DS_LOG_LEVEL, "ERROR")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_validate.assert_called_once_with(flow_file="test.json")

    @patch("docpipe.cli.docpipe_cli.run_command_line_executor")
    @patch("sys.argv", ["docling-pipelines", "--flow-file", "test.json"])
    def test_execution_with_custom_log_level(self, mock_execute, valid_flow_file, monkeypatch):
        """Test flow execution with custom log level via DS_LOG_LEVEL env var."""
        monkeypatch.setenv(EnvironmentVariables.DS_LOG_LEVEL, "DEBUG")

        with patch("sys.argv", ["docling-pipelines", "--flow-file", valid_flow_file]):
            main()

        mock_execute.assert_called_once()


class TestIntegrationScenarios:
    """Integration-style tests for complete CLI workflows using real components."""

    def test_load_and_parse_real_invoice_flow(self, real_flow_invoice):
        """Test loading and parsing the real invoice flow file."""
        _original_flow, flow_def = load_flow_definition(file_path=real_flow_invoice)

        # Verify structure (after compilation to runtime DAG)
        assert "dag" in flow_def
        assert len(flow_def["dag"]) == 6
        assert "global_config" in flow_def

        # Verify operators
        operators = [node["operator"] for node in flow_def["dag"]]
        assert "ingest_source" in operators
        assert "document_classifier" in operators
        assert "extract_operator" in operators
        assert "chunker" in operators
        assert "embeddings" in operators
        assert "vectordb" in operators

    def test_create_and_validate_temporary_flow(self, tmp_path, fixtures_customer_support_dir):
        """Test creating a temporary flow file and validating it."""
        flow = {
            "flow_name": "temp_test_flow",
            "description": "Temporary test flow",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "ingest",
                    "depends_on": [],
                    "config": {
                        "provider": "filesystem",
                        "paths": [str(fixtures_customer_support_dir)],
                        "include_filter": "txt",
                    },
                }
            ],
            "global_config": {},
        }

        flow_file = tmp_path / "temp_flow.json"
        flow_file.write_text(json.dumps(flow))

        _original_flow, loaded_flow = load_flow_definition(file_path=str(flow_file))

        # After compilation, should have runtime DAG format
        assert "dag" in loaded_flow
        assert len(loaded_flow["dag"]) == 1
        assert loaded_flow["dag"][0]["operator"] == "ingest_source"

    def test_empty_flow_validation_fails(self, tmp_path):
        """Test that empty flows (no operators) fail validation during load.

        load_flow_definition validates authoring format and raises
        FlowInvalidDataException for empty flows.
        """
        from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

        flow = {
            "flow_name": "empty_flow",
            "description": "Flow with no operators",
            "flow": [],
            "global_config": {},
        }

        flow_file = tmp_path / "empty_flow.json"
        flow_file.write_text(json.dumps(flow))

        # Empty flows fail validation (must have at least one operator)
        with pytest.raises(FlowInvalidDataException) as exc_info:
            load_flow_definition(file_path=str(flow_file))

        assert "at least one operator" in str(exc_info.value)


class TestValidateFlowDefinitionRealValidator:
    """Tests for validate_flow_definition using real FlowValidator."""

    def test_validate_valid_flow_success(self, valid_flow_file):
        """Test validation succeeds with valid flow using real FlowValidator.

        Note: This flow may have warnings (e.g., missing VectorDB operator) but should
        still pass validation as warnings don't cause validation failure.
        """
        result = validate_flow_definition(flow_file=valid_flow_file)

        # Flow has warnings but no errors, so validation returns True
        # This is correct behavior - only errors cause validation to fail, not warnings
        assert result is True

    def test_validate_flow_with_invalid_operator(self, tmp_path):
        """Test validation fails with invalid operator configuration."""
        flow = {
            "flow_name": "invalid_operator_flow",
            "description": "Flow with invalid operator config",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "bad_ingest",
                    "depends_on": [],
                    "config": {
                        "provider": "filesystem",
                        # Missing required 'paths' parameter
                        "include_filter": "txt",
                    },
                }
            ],
            "global_config": {},
        }

        flow_file = tmp_path / "invalid_operator.json"
        flow_file.write_text(json.dumps(flow))

        result = validate_flow_definition(flow_file=str(flow_file))

        # Should fail due to missing required parameter
        assert result is False

    def test_validate_flow_with_nonexistent_operator(self, tmp_path):
        """Test validation fails with non-existent operator type."""
        flow = {
            "flow_name": "nonexistent_operator_flow",
            "description": "Flow with non-existent operator",
            "flow": [
                {
                    "type": "nonexistent_operator_type",
                    "name": "fake_op",
                    "depends_on": [],
                    "config": {},
                }
            ],
            "global_config": {},
        }

        flow_file = tmp_path / "nonexistent_op.json"
        flow_file.write_text(json.dumps(flow))

        result = validate_flow_definition(flow_file=str(flow_file))

        # Should fail due to unknown operator
        assert result is False

    def test_validate_real_invoice_flow(self, real_flow_invoice):
        """Test validation of real invoice flow file."""
        result = validate_flow_definition(flow_file=real_flow_invoice)

        # Real invoice flow should validate successfully
        assert result is True


class TestVaultInitializerWiring:
    """Verify initialize_secret_providers() is called during CLI startup."""

    @patch("docpipe.integrations.secrets.vault_initializer.initialize_secret_providers")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    def test_initialize_secret_providers_called_on_execution(self, mock_executor, mock_init):
        """initialize_secret_providers() must be called in run_command_line_executor."""
        flow_def = {"name": "test", "global_config": {}, "pipeline": []}

        mock_executor.return_value.execute.return_value = None

        from docpipe.cli.docpipe_cli import run_command_line_executor

        run_command_line_executor(flow_def=flow_def)

        mock_init.assert_called_once()


class TestLoadFlowOrExit:
    """Unit tests for _load_flow_or_exit helper."""

    def test_returns_tuple_on_success(self, valid_flow_file):
        """Returns (original_json, compiled_dag) on a valid flow file."""
        original, dag = _load_flow_or_exit(flow_file=valid_flow_file)
        assert "flow_name" in original
        assert "dag" in dag

    def test_exits_1_on_file_not_found(self, tmp_path):
        """Exits with code 1 when the flow file does not exist."""
        with pytest.raises(SystemExit) as exc_info:
            _load_flow_or_exit(flow_file=str(tmp_path / "missing.json"))
        assert exc_info.value.code == 1

    def test_exits_1_on_invalid_json(self, malformed_json_file):
        """Exits with code 1 when the flow file contains malformed JSON."""
        with pytest.raises(SystemExit) as exc_info:
            _load_flow_or_exit(flow_file=malformed_json_file)
        assert exc_info.value.code == 1

    def test_exits_1_on_flow_invalid_data(self, tmp_path):
        """Exits with code 1 when the flow definition is invalid (FlowInvalidDataException)."""
        flow_file = tmp_path / "empty_flow.json"
        flow_file.write_text(json.dumps({"flow_name": "x", "flow": [], "global_config": {}}))
        with pytest.raises(SystemExit) as exc_info:
            _load_flow_or_exit(flow_file=str(flow_file))
        assert exc_info.value.code == 1

    def test_exits_1_on_missing_key(self, tmp_path):
        """Exits with code 1 when a required key (flow_name) is missing."""
        flow_file = tmp_path / "no_flow_name.json"
        flow_file.write_text(json.dumps({"flow": []}))
        with pytest.raises(SystemExit) as exc_info:
            _load_flow_or_exit(flow_file=str(flow_file))
        assert exc_info.value.code == 1

    def test_exits_1_on_unexpected_exception(self, valid_flow_file):
        """Exits with code 1 when load_flow_definition raises an unexpected exception."""
        with patch("docpipe.cli.docpipe_cli.load_flow_definition", side_effect=RuntimeError("error message")):
            with pytest.raises(SystemExit) as exc_info:
                _load_flow_or_exit(flow_file=valid_flow_file)
        assert exc_info.value.code == 1


class TestExecuteFlowOrExit:
    """Unit tests for _execute_flow_or_exit helper."""

    def test_calls_executor_and_returns(self):
        """Calls run_command_line_executor without raising on success."""
        flow_def = {"name": "test-flow", "dag": [], "global_config": {}}
        with patch("docpipe.cli.docpipe_cli.run_command_line_executor") as mock_exec:
            _execute_flow_or_exit(flow_def=flow_def, original_flow_json={})
        mock_exec.assert_called_once_with(flow_def=flow_def, original_flow_json={})

    def test_exits_1_on_docpipe_exception(self):
        """Exits with code 1 when a DocpipeException is raised."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        flow_def = {"name": "test-flow", "dag": [], "global_config": {}}
        with patch(
            "docpipe.cli.docpipe_cli.run_command_line_executor",
            side_effect=DocpipeException("something failed"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _execute_flow_or_exit(flow_def=flow_def, original_flow_json={})
        assert exc_info.value.code == 1

    def test_exits_1_on_flow_validation_exception_with_flow_name(self):
        """Exits with code 1 and uses format_validation_exception when FlowValidationException raised."""
        from docpipe.exceptions.docpipe_exceptions import FlowValidationException

        flow_def = {"name": "my-flow", "dag": [], "global_config": {}}
        exc = FlowValidationException(errors=[], warnings=[])
        with patch("docpipe.cli.docpipe_cli.run_command_line_executor", side_effect=exc):
            with patch(
                "docpipe.utils.infrastructure.error_formatter.format_validation_exception",
                return_value="formatted",
            ):
                with pytest.raises(SystemExit) as exc_info:
                    _execute_flow_or_exit(flow_def=flow_def, original_flow_json={})
        assert exc_info.value.code == 1

    def test_exits_1_on_generic_exception(self):
        """Exits with code 1 and formats via format_generic_exception for non-Docpipe errors."""
        flow_def = {"name": "test-flow", "dag": [], "global_config": {}}
        with patch(
            "docpipe.cli.docpipe_cli.run_command_line_executor",
            side_effect=ValueError("unexpected"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _execute_flow_or_exit(flow_def=flow_def, original_flow_json={})
        assert exc_info.value.code == 1


class TestMicroBatchingDefaults:
    """Verify CLI micro-batching default behavior."""

    @patch("docpipe.integrations.secrets.vault_initializer.initialize_secret_providers")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    def test_run_command_line_executor_defaults_micro_batching_when_missing(
        self,
        mock_create_orchestrator,
        mock_executor_class,
        mock_init,
    ):
        """Test CLI execution defaults micro-batching when flow global_config omits it."""
        flow_def = {"name": "test", "global_config": {}, "dag": []}
        mock_executor = mock_executor_class.return_value
        mock_executor.execute.return_value = None
        mock_create_orchestrator.return_value = Mock()

        from docpipe.cli.docpipe_cli import run_command_line_executor

        run_command_line_executor(flow_def=flow_def)

        execute_kwargs = mock_executor.execute.call_args.kwargs
        assert execute_kwargs["params"]["enable_micro_batching"] is True
        mock_init.assert_called_once()

    @patch("docpipe.integrations.secrets.vault_initializer.initialize_secret_providers")
    @patch("docpipe.core.orchestration.flow_executor.FlowExecutor")
    @patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory.create_orchestrator")
    def test_run_command_line_executor_respects_explicit_micro_batching_value(
        self,
        mock_create_orchestrator,
        mock_executor_class,
        mock_init,
    ):
        """Test CLI execution does not override explicit micro-batching config."""
        flow_def = {"name": "test", "global_config": {"enable_micro_batching": False}, "dag": []}
        mock_executor = mock_executor_class.return_value
        mock_executor.execute.return_value = None
        mock_create_orchestrator.return_value = Mock()

        from docpipe.cli.docpipe_cli import run_command_line_executor

        run_command_line_executor(flow_def=flow_def)

        execute_kwargs = mock_executor.execute.call_args.kwargs
        assert "enable_micro_batching" not in execute_kwargs["params"]
        mock_init.assert_called_once()


if __name__ == "__main__":
    pytest.main(["-v", __file__])
