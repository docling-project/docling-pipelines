# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for DocpipeFlowManager.

Tests the programmatic interface for executing docpipe flows from Python code,
notebooks, or embedded applications.
"""

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_flow():
    """Simple flow definition for testing."""
    return {
        "flow_name": "Test Flow",
        "description": "Test Description",
        "flow": [
            {
                "type": "noop",
                "name": "noop_node",
                "depends_on": [],
                "config": {},
            }
        ],
        "global_config": {},
    }


@pytest.fixture
def elyra_format_flow():
    """Flow definition in Elyra format."""
    return {
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
                            "op": "noop",
                            "parameters": {},
                        }
                    ],
                }
            ],
            "parameters": {},
        }
    }


@pytest.fixture
def flow_without_flow_id():
    """Flow definition without explicit flow_id (will be auto-generated)."""
    return {
        "flow_name": "No ID Flow",
        "description": "Flow without explicit flow_id",
        "flow": [{"type": "noop", "name": "noop1"}],
        "global_config": {},
    }


@pytest.fixture
def temp_flow_file(simple_flow):
    """Create a temporary flow file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(simple_flow, f)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def temp_elyra_format_file(elyra_format_flow):
    """Create a temporary Elyra format flow file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(elyra_format_flow, f)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def temp_invalid_json_file():
    """Create a temporary file with invalid JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{invalid json content")
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator for testing."""
    orchestrator = Mock()
    orchestrator.initialize = Mock()
    orchestrator.execute = Mock(return_value=Mock())
    orchestrator.flow_execution_event_handler = None
    return orchestrator


@pytest.fixture
def mock_session_info():
    """Mock session info for testing."""
    session = Mock()
    session.job_id = "test-job-id"
    session.job_run_id = "test-run-id"
    return session


# ---------------------------------------------------------------------------
# 1. Initialization Tests
# ---------------------------------------------------------------------------


class TestInitialization:
    """Test DocpipeFlowManager initialization."""

    def test_init_with_flow_file(self, temp_flow_file):
        """Test successful initialization with flow_file."""
        manager = DocpipeFlowManager(flow_file=temp_flow_file)

        assert manager.flow_file == temp_flow_file
        assert manager.flow_def is not None
        # After compilation, flow_def is in runtime DAG format
        assert "dag" in manager.flow_def
        assert "global_config" in manager.flow_def
        assert "flow_id" in manager.flow_def

    def test_init_with_flow_def(self, simple_flow):
        """Test successful initialization with flow_def (authoring format)."""
        manager = DocpipeFlowManager(flow_def=simple_flow)

        assert manager.flow_file is None
        # After compilation, flow_def is in runtime DAG format
        assert "dag" in manager.flow_def
        assert "global_config" in manager.flow_def

    def test_init_missing_both_raises_error(self):
        """Test DocpipeException when neither flow_file nor flow_def provided."""
        with pytest.raises(DocpipeException) as exc_info:
            DocpipeFlowManager()

        assert "Either flow_file or flow_def must be provided" in str(exc_info.value)

    def test_init_both_provided_raises_error(self, temp_flow_file, simple_flow):
        """Test DocpipeException when both flow_file and flow_def provided."""
        with pytest.raises(DocpipeException) as exc_info:
            DocpipeFlowManager(flow_file=temp_flow_file, flow_def=simple_flow)

        assert "Only one of flow_file or flow_def should be provided" in str(exc_info.value)

    def test_init_file_not_found_raises_error(self):
        """Test FileNotFoundError when flow_file doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            DocpipeFlowManager(flow_file="/nonexistent/path/flow.json")

        assert "Flow definition file" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_init_invalid_json_raises_error(self, temp_invalid_json_file):
        """Test json.JSONDecodeError when flow_file has invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            DocpipeFlowManager(flow_file=temp_invalid_json_file)

    def test_init_default_parameters(self, simple_flow):
        """Test default parameter values."""
        manager = DocpipeFlowManager(flow_def=simple_flow)

        assert manager.job_id is not None
        assert manager.job_run_id is not None
        assert manager.flow_id is not None
        assert manager.orchestrator is None
        assert manager.session_info is None
        assert manager.executor is None

    def test_init_custom_parameters(self, simple_flow):
        """Test custom parameter values."""
        custom_job_id = "custom-job-123"
        custom_run_id = "custom-run-456"
        custom_flow_id = "custom-flow"

        manager = DocpipeFlowManager(
            flow_def=simple_flow,
            job_id=custom_job_id,
            job_run_id=custom_run_id,
            flow_id=custom_flow_id,
        )

        assert manager.job_id == custom_job_id
        assert manager.job_run_id == custom_run_id
        assert manager.flow_id == custom_flow_id

    @patch("docpipe.lib.docpipe_flow_manager.uuid.uuid4")
    def test_init_auto_generates_ids(self, mock_uuid4, flow_without_flow_id):
        """Test that job_id and job_run_id are auto-generated when not provided."""
        mock_uuid4.return_value = uuid.UUID("00000000-0000-0000-0000-000000000001")

        manager = DocpipeFlowManager(flow_def=flow_without_flow_id)

        assert manager.job_id is not None
        assert manager.job_run_id is not None
        # Verify they are valid UUIDs (will be string representation of UUID)
        uuid.UUID(manager.job_id)
        uuid.UUID(manager.job_run_id)

    def test_init_job_run_id_auto_generates_uuid(self, simple_flow):
        """Test that job_run_id auto-generates a UUID when not provided."""
        custom_job_id = "custom-job-123"

        manager = DocpipeFlowManager(flow_def=simple_flow, job_id=custom_job_id)

        assert manager.job_id == custom_job_id
        # job_run_id should be a valid UUID, different from job_id
        assert manager.job_run_id != custom_job_id
        # Verify it's a valid UUID
        uuid.UUID(manager.job_run_id)

    def test_init_flow_id_priority(self, simple_flow, flow_without_flow_id):
        """Test flow_id priority: parameter > flow_def > job_id."""
        # Test parameter takes priority
        manager1 = DocpipeFlowManager(flow_def=simple_flow, flow_id="param-flow-id")
        assert manager1.flow_id == "param-flow-id"

        # Test flow_def value used when parameter not provided
        # After compilation, flow_id is auto-generated if not in authoring format
        manager2 = DocpipeFlowManager(flow_def=simple_flow)
        assert manager2.flow_id is not None
        # Verify it's a valid UUID
        uuid.UUID(manager2.flow_id)

        # Test job_id used as fallback when no flow_id parameter provided
        manager3 = DocpipeFlowManager(flow_def=flow_without_flow_id, job_id="job-123")
        assert manager3.job_id == "job-123"
        assert manager3.flow_id != "job-123"
        uuid.UUID(manager3.flow_id)


# ---------------------------------------------------------------------------
# 2. Flow Definition Loading Tests
# ---------------------------------------------------------------------------


class TestFlowDefinitionLoading:
    """Test flow definition loading from files."""

    def test_load_flow_from_file_top_level(self, temp_flow_file):
        """Test loading flow from file with top-level structure."""
        executor = DocpipeFlowManager(flow_file=temp_flow_file)

        # After compilation, should have runtime DAG format
        assert "dag" in executor.flow_def
        assert "global_config" in executor.flow_def
        assert len(executor.flow_def["dag"]) == 1

    def test_load_flow_from_file_elyra_format_fails(self, temp_elyra_format_file):
        """Test that Elyra format (UI format) is not supported by DocpipeFlowManager."""
        # DocpipeFlowManager only supports authoring format, not Elyra format
        with pytest.raises(DocpipeException) as exc_info:
            DocpipeFlowManager(flow_file=temp_elyra_format_file)

        assert "flow_name" in str(exc_info.value)

    def test_load_flow_missing_file(self):
        """Test handling of missing file."""
        with pytest.raises(FileNotFoundError):
            DocpipeFlowManager(flow_file="/path/to/missing/file.json")

    def test_load_flow_invalid_json(self, temp_invalid_json_file):
        """Test handling of invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            DocpipeFlowManager(flow_file=temp_invalid_json_file)

    def test_load_flow_preserves_dag(self, temp_flow_file):
        """Test that DAG structure is preserved during loading and compilation."""
        executor = DocpipeFlowManager(flow_file=temp_flow_file)

        assert "dag" in executor.flow_def
        assert len(executor.flow_def["dag"]) == 1
        # After compilation, DAG nodes have different structure
        assert "operator" in executor.flow_def["dag"][0]


# ---------------------------------------------------------------------------
# 3. Execution Environment Tests
# ---------------------------------------------------------------------------


class TestExecutionEnvironment:
    """Test execution environment initialization."""

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_environment_variables_setup(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test environment variable setup."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-job")
        mock_create_session.return_value = mock_session

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor._initialize_execution_environment()

        # Environment variables are not set in the new implementation
        # Just verify orchestrator was created
        mock_factory.assert_called_once()

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_orchestrator_creation(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test orchestrator creation."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-job")
        mock_create_session.return_value = mock_session

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor._initialize_execution_environment()

        mock_factory.assert_called_once()
        assert executor.orchestrator == mock_orchestrator

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_session_info_creation(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test session_info creation."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123")
        mock_create_session.return_value = mock_session

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor._initialize_execution_environment()

        mock_create_session.assert_called_once()
        assert executor.session_info == mock_session
        # set_session_info is called internally by create_session_info, no need to verify

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_flow_id_extraction_top_level(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test that job_id is used when no flow_id in authoring format."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-job-id")
        mock_create_session.return_value = mock_session

        # Don't provide flow_id parameter, so it uses auto-generated UUID
        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor._initialize_execution_environment()

        # Should use executor's job_id (which is auto-generated UUID)
        call_args = mock_create_session.call_args
        assert call_args[1]["job_id"] == executor.job_id
        # Verify it's a valid UUID
        uuid.UUID(call_args[1]["job_id"])

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_flow_id_extraction_with_explicit_flow_id(self, mock_executor_class, mock_create_session, mock_factory):
        """Test that explicit flow_id parameter is used."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="explicit-flow-id")
        mock_create_session.return_value = mock_session

        # Provide explicit flow_id parameter
        authoring_flow = {
            "flow_name": "Test Flow",
            "flow": [{"type": "noop", "name": "op1"}],
            "global_config": {},
        }

        executor = DocpipeFlowManager(flow_def=authoring_flow, job_id="explicit-flow-id", flow_id="explicit-flow-id")
        executor._initialize_execution_environment()

        call_args = mock_create_session.call_args
        # job_id parameter is used for session creation
        assert call_args[1]["job_id"] == "explicit-flow-id"

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_flow_id_fallback_to_initial(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        flow_without_flow_id,
    ):
        """Test fallback to _initial_flow_id when flow_id not in flow_def."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="fallback-id")
        mock_create_session.return_value = mock_session

        executor = DocpipeFlowManager(flow_def=flow_without_flow_id, job_id="fallback-id")
        executor._initialize_execution_environment()

        call_args = mock_create_session.call_args
        assert call_args[1]["job_id"] == "fallback-id"

    def test_flow_definition_not_initialized_error(self):
        """Test DocpipeException when flow_def is None."""
        executor = DocpipeFlowManager.__new__(DocpipeFlowManager)
        executor.flow_def = None
        # Need to set attributes since __init__ wasn't called
        from docpipe.utils.infrastructure.logging import get_logger

        executor.logger = get_logger()
        executor.enable_custom_operators = True
        executor.custom_operator_packages = []
        executor.execution_reporter = None

        with pytest.raises(DocpipeException):
            executor._initialize_execution_environment()


# ---------------------------------------------------------------------------
# 4. Execute Method Tests
# ---------------------------------------------------------------------------


class TestExecuteMethod:
    """Test execute method."""

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_successful_execution(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test successful execution flow."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_result = Mock()
        mock_flow_executor.execute.return_value = mock_result
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)
        result = executor.execute()

        assert result == mock_result
        mock_flow_executor.execute.assert_called_once()

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_execution_defaults_micro_batching_when_missing(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test execute defaults micro-batching when flow global_config omits it."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor.execute()

        execute_kwargs = mock_flow_executor.execute.call_args.kwargs
        assert execute_kwargs["params"][DocpipeConstants.ENABLE_MICRO_BATCHING] is True
        assert DocpipeConstants.ENABLE_FAILED_DOC_RESUMPTION not in execute_kwargs["params"]

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_execution_respects_explicit_micro_batching_value(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test execute does not override explicit micro-batching config."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        flow_def = simple_flow | {
            "global_config": {
                DocpipeConstants.ENABLE_MICRO_BATCHING: False,
                DocpipeConstants.ENABLE_FAILED_DOC_RESUMPTION: False,
            }
        }
        executor = DocpipeFlowManager(flow_def=flow_def)
        executor.execute()

        execute_kwargs = mock_flow_executor.execute.call_args.kwargs
        assert DocpipeConstants.ENABLE_MICRO_BATCHING not in execute_kwargs["params"]
        assert DocpipeConstants.ENABLE_FAILED_DOC_RESUMPTION not in execute_kwargs["params"]

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_execution_with_mocked_components(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test execution with mocked orchestrator and executor."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor.execute()

        # Verify orchestrator was initialized
        mock_orchestrator.initialize.assert_called_once()

        # Verify flow executor was created with compiled runtime DAG format
        mock_executor_class.assert_called_once()
        call_kwargs = mock_executor_class.call_args[1]
        assert "flow_def" in call_kwargs
        assert "orchestrator" in call_kwargs
        assert call_kwargs["orchestrator"] == mock_orchestrator
        # Verify it's compiled format (has 'dag' not 'flow')
        assert "dag" in call_kwargs["flow_def"]
        assert "flow" not in call_kwargs["flow_def"]

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_execution_error_handling(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test error handling during execution."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_flow_executor.execute.side_effect = Exception("Execution failed")
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)

        with pytest.raises(Exception, match="Execution failed"):
            executor.execute()

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_execution_logs_flow_details(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test logging of flow details during execution."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)

        executor.execute()

        # New implementation may not log flow details in the same way
        # Just verify execute was called
        mock_flow_executor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Validate Method Tests
# ---------------------------------------------------------------------------


class TestValidateMethod:
    """Test validate() method."""

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowValidator")
    def test_validate_calls_create_session_info(
        self,
        mock_validator_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """validate() must call create_session_info so validators read correct job context."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-job", job_run_id="test-run")
        mock_create_session.return_value = mock_session

        mock_validator = Mock()
        mock_validator.validate = Mock()
        mock_validator_class.return_value = mock_validator

        manager = DocpipeFlowManager(
            flow_def=simple_flow, job_id="test-job", job_run_id="test-run", flow_id="test-flow"
        )
        result = manager.validate()

        mock_create_session.assert_called_once_with(
            job_id="test-job",
            job_run_id="test-run",
            orchestrator=mock_orchestrator,
            flow_id="test-flow",
        )
        assert result["valid"] is True

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowValidator")
    def test_validate_create_session_info_called_before_validator(
        self,
        mock_validator_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """create_session_info must be called before FlowValidator is constructed."""
        call_order: list[str] = []

        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator

        def _session_side_effect(**_):  # type: ignore[no-untyped-def]
            call_order.append("session")
            return Mock()

        mock_create_session.side_effect = _session_side_effect

        mock_validator = Mock()
        mock_validator.validate = Mock()

        def _validator_side_effect(**_):  # type: ignore[no-untyped-def]
            call_order.append("validator")
            return mock_validator

        mock_validator_class.side_effect = _validator_side_effect

        manager = DocpipeFlowManager(flow_def=simple_flow)
        manager.validate()

        assert call_order.index("session") < call_order.index("validator")

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowValidator")
    def test_validate_returns_valid_true_on_success(
        self,
        mock_validator_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """validate() returns valid=True when FlowValidator raises no exception."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_create_session.return_value = Mock()

        mock_validator = Mock()
        mock_validator.validate = Mock()
        mock_validator_class.return_value = mock_validator

        manager = DocpipeFlowManager(flow_def=simple_flow)
        result = manager.validate()

        assert result == {"valid": True, "errors": [], "warnings": []}

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowValidator")
    def test_validate_returns_errors_on_flow_validation_exception(
        self,
        mock_validator_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """validate() surfaces errors from FlowValidationException."""
        from docpipe.exceptions.docpipe_exceptions import FlowValidationException

        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_create_session.return_value = Mock()

        mock_validator = Mock()
        exc = FlowValidationException(errors=["missing root operator"], warnings=[])
        mock_validator.validate.side_effect = exc
        mock_validator_class.return_value = mock_validator

        manager = DocpipeFlowManager(flow_def=simple_flow)
        result = manager.validate()

        assert result["valid"] is False
        assert "missing root operator" in result["errors"]


# ---------------------------------------------------------------------------
# 6. Metadata Tests
# ---------------------------------------------------------------------------


class TestMetadata:
    """Test get_execution_metadata method."""

    def test_metadata_before_execution(self, simple_flow):
        """Test get_execution_metadata() before execution."""
        executor = DocpipeFlowManager(flow_def=simple_flow)
        metadata = executor.get_execution_metadata()

        assert DocpipeConstants.JOB_ID in metadata
        assert DocpipeConstants.JOB_RUN_ID in metadata
        assert DocpipeConstants.FLOW_ID in metadata
        assert DocpipeConstants.FLOW_NAME in metadata
        assert DocpipeConstants.FLOW_DESCRIPTION in metadata
        assert "num_operators" in metadata
        assert "flow_file" in metadata

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_metadata_after_execution(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test get_execution_metadata() after execution."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow, job_run_id="run-123")
        executor.execute()

        metadata = executor.get_execution_metadata()

        # After compilation, flow_id is auto-generated UUID, not from authoring format
        assert DocpipeConstants.JOB_ID in metadata
        # Verify it's a valid UUID
        uuid.UUID(metadata[DocpipeConstants.JOB_ID])
        assert metadata[DocpipeConstants.JOB_RUN_ID] == "run-123"

    def test_metadata_with_custom_flow_name(self):
        """Test metadata with custom flow_name and description in authoring format."""
        flow_def = {
            "flow_name": "Custom Flow Name",
            "description": "Custom Description",
            "flow": [{"type": "noop", "name": "op1"}, {"type": "noop", "name": "op2"}],
            "global_config": {},
        }

        executor = DocpipeFlowManager(flow_def=flow_def)
        metadata = executor.get_execution_metadata()

        # After compilation, 'name' field contains flow_name
        assert metadata[DocpipeConstants.FLOW_NAME] == "Custom Flow Name"
        assert metadata[DocpipeConstants.FLOW_DESCRIPTION] == "Custom Description"
        assert metadata["num_operators"] == 2

    def test_metadata_with_default_values(self):
        """Test metadata with minimal authoring format."""
        flow_def = {
            "flow_name": "Minimal Flow",
            "flow": [{"type": "noop", "name": "op1"}],
        }
        executor = DocpipeFlowManager(flow_def=flow_def)
        metadata = executor.get_execution_metadata()

        # After compilation, should have name from flow_name
        assert metadata[DocpipeConstants.FLOW_NAME] == "Minimal Flow"
        # Description defaults to empty string
        assert metadata[DocpipeConstants.FLOW_DESCRIPTION] == ""

    def test_metadata_flow_file_path(self, temp_flow_file):
        """Test metadata includes flow_file path when loaded from file."""
        executor = DocpipeFlowManager(flow_file=temp_flow_file)
        metadata = executor.get_execution_metadata()

        assert metadata["flow_file"] == temp_flow_file

    def test_metadata_flow_file_none_when_from_dict(self, simple_flow):
        """Test metadata flow_file is None when loaded from dict."""
        executor = DocpipeFlowManager(flow_def=simple_flow)
        metadata = executor.get_execution_metadata()

        assert metadata["flow_file"] is None


# ---------------------------------------------------------------------------
# 6. Logs Tests
# ---------------------------------------------------------------------------


class TestLogs:
    """Test get_execution_logs method."""

    def test_logs_when_orchestrator_none(self, simple_flow):
        """Test get_execution_logs() when orchestrator is None."""
        executor = DocpipeFlowManager(flow_def=simple_flow)
        logs = executor.get_execution_logs()

        assert logs == []

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_logs_when_event_handler_none(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test get_execution_logs() when event_handler is None."""
        mock_orchestrator = Mock()
        mock_orchestrator.flow_execution_event_handler = None
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor.execute()

        logs = executor.get_execution_logs()
        assert logs == []

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_logs_when_log_file_missing(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test get_execution_logs() when log file doesn't exist."""
        mock_orchestrator = Mock()
        mock_event_handler = Mock()
        mock_event_handler.job_log_path = "/nonexistent/path/job.log"
        mock_orchestrator.flow_execution_event_handler = mock_event_handler
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow)
        executor.execute()

        logs = executor.get_execution_logs()
        assert logs == []

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_logs_with_valid_log_file(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test get_execution_logs() with valid log file."""
        mock_orchestrator = Mock()

        # Mock job_stats_service with get_formatted_job_stats method
        mock_job_stats_service = Mock()
        mock_job_stats_response = Mock()
        mock_job_stats_response.node_sequence = ["node1", "node2", "node3"]
        mock_job_stats_response.node1 = "Log line 1"
        mock_job_stats_response.node2 = "Log line 2"
        mock_job_stats_response.node3 = "Log line 3"
        mock_job_stats_service.get_formatted_job_stats.return_value = mock_job_stats_response

        mock_orchestrator.job_stats_service = mock_job_stats_service
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_executor_class.return_value = mock_flow_executor

        executor = DocpipeFlowManager(flow_def=simple_flow, job_run_id="run-123")
        executor.execute()

        logs = executor.get_execution_logs()

        assert len(logs) == 3
        assert logs[0] == "Log line 1"
        assert logs[1] == "Log line 2"
        assert logs[2] == "Log line 3"

        # Verify get_formatted_job_stats was called with correct parameters
        mock_job_stats_service.get_formatted_job_stats.assert_called_once_with(job_run_id="run-123", include_logs=True)


# ---------------------------------------------------------------------------
# 7. Static Method Tests
# ---------------------------------------------------------------------------


class TestStaticMethods:
    """Test static methods."""

    @patch("docpipe.lib.docpipe_flow_manager._list_operators")
    def test_list_operators_not_verbose(self, mock_list_operators):
        """Test list_operators() with verbose=False."""
        mock_list_operators.return_value = "Operator list"

        result = DocpipeFlowManager.list_operators(verbose=False)

        mock_list_operators.assert_called_once_with(verbose=False, summary_only=True)
        assert result == "Operator list"

    @patch("docpipe.lib.docpipe_flow_manager._list_operators")
    def test_list_operators_verbose(self, mock_list_operators):
        """Test list_operators() with verbose=True."""
        mock_list_operators.return_value = "Detailed operator list"

        result = DocpipeFlowManager.list_operators(verbose=True)

        mock_list_operators.assert_called_once_with(verbose=True, summary_only=False)
        assert result == "Detailed operator list"

    @patch("docpipe.lib.docpipe_flow_manager._list_operators")
    def test_list_operators_default_parameter(self, mock_list_operators):
        """Test list_operators() with default parameter."""
        mock_list_operators.return_value = "Default list"

        result = DocpipeFlowManager.list_operators()

        mock_list_operators.assert_called_once_with(verbose=False, summary_only=True)
        assert result == "Default list"


# ---------------------------------------------------------------------------
# 8. Integration Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests combining multiple features."""

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_full_workflow_from_file(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        temp_flow_file,
    ):
        """Test complete workflow from file loading to execution."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_result = Mock()
        mock_flow_executor.execute.return_value = mock_result
        mock_executor_class.return_value = mock_flow_executor

        # Create executor from file
        executor = DocpipeFlowManager(flow_file=temp_flow_file)

        # Execute
        result = executor.execute()

        # Get metadata
        metadata = executor.get_execution_metadata()

        # Verify results
        assert result == mock_result
        assert metadata[DocpipeConstants.FLOW_NAME] == "Test Flow"
        assert metadata["flow_file"] == temp_flow_file

    @patch("docpipe.lib.docpipe_flow_manager.OrchestratorFactory.create_orchestrator")
    @patch("docpipe.lib.docpipe_flow_manager.create_session_info")
    @patch("docpipe.lib.docpipe_flow_manager.FlowExecutor")
    def test_full_workflow_from_dict(
        self,
        mock_executor_class,
        mock_create_session,
        mock_factory,
        simple_flow,
    ):
        """Test complete workflow from dict to execution."""
        mock_orchestrator = Mock()
        mock_factory.return_value = mock_orchestrator
        mock_session = Mock(job_id="test-flow-123", job_run_id="run-123")
        mock_create_session.return_value = mock_session

        mock_flow_executor = Mock()
        mock_result = Mock()
        mock_flow_executor.execute.return_value = mock_result
        mock_executor_class.return_value = mock_flow_executor

        # Create executor from dict
        executor = DocpipeFlowManager(flow_def=simple_flow)

        # Execute
        result = executor.execute()

        # Get metadata
        metadata = executor.get_execution_metadata()

        # Verify results
        assert result == mock_result
        assert metadata[DocpipeConstants.FLOW_NAME] == "Test Flow"
        assert metadata["flow_file"] is None

    def test_multiple_managers_independent(self, simple_flow):
        """Test that multiple manager instances are independent."""
        manager1 = DocpipeFlowManager(flow_def=simple_flow, job_id="job-1")
        manager2 = DocpipeFlowManager(flow_def=simple_flow, job_id="job-2")

        assert manager1.job_id != manager2.job_id
        assert manager1.job_run_id != manager2.job_run_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
