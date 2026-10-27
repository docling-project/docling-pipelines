"""
Programmatic DocpipeFlowManager for embedding docpipe in notebooks and applications.

This module provides a high-level API for executing docpipe flows programmatically,
wrapping the CLI functionality in a class suitable for notebook and embedded usage.
"""

import json
import uuid
from logging import Logger
from pathlib import Path
from typing import Any

from docpipe.core.assets.flows.application.services.authoring_compiler import AuthoringCompiler
from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow, FlowSource
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.models.session_info import SessionInfo, create_session_info
from docpipe.core.orchestration.flow_executor import FlowExecutor
from docpipe.core.orchestration.flow_validator import FlowValidator
from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowInvalidDataException, FlowValidationException
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter
from docpipe.utils.infrastructure.logging import get_logger, set_dpk_log_level_from_ds_log_level, setup_logging
from docpipe.utils.operators.display import list_operators as _list_operators


class DocpipeFlowManager:
    """
    Programmatic interface for executing docpipe flows.

    This class provides a high-level API for running docpipe flows from Python code,
    notebooks, or embedded applications. It wraps the CLI functionality and provides
    a clean interface for programmatic execution.

    Attributes:
        flow_file (Optional[str]): Path to flow definition JSON file
        flow_def (dict): Flow definition as dictionary
        job_id (str): Unique job identifier
        job_run_id (str): Unique job run identifier
        flow_id (str): Flow identifier
        orchestrator: Orchestrator instance (created during execution)
        session_info: Session information (created during execution)
        executor: FlowExecutor instance (created during execution)

    Example:
        # Execute from file
        manager = DocpipeFlowManager(flow_file="path/to/flow.json")
        result = manager.execute()

        # Execute from dict
        flow_def = {
            "name": "My Flow",
            "dag": [...]
        }
        manager = DocpipeFlowManager(flow_def=flow_def)
        result = manager.execute()
    """

    def __init__(
        self,
        flow_file: str | None = None,
        flow_def: dict | None = None,
        job_id: str | None = None,
        job_run_id: str | None = None,
        flow_id: str | None = None,
        enable_custom_operators: bool | None = None,
        enable_execution_reporter: bool = True,
        configure_logging: bool = True,
    ):
        """
        Initialize DocpipeFlowManager.

        Args:
            flow_file: Path to JSON file containing flow definition
            flow_def: Flow definition as dictionary (used if flow_file not provided)
            job_id: Unique job identifier (priority: parameter > flow_def > UUID)
            job_run_id: Unique job run identifier (defaults to job_id if not provided)
            flow_id: Flow identifier (priority: parameter > flow_def > job_id)
            enable_custom_operators: Whether to enable custom operators (default: from env or True)
            enable_execution_reporter: Whether to enable user-friendly console output (default: True)
            configure_logging: When True (default), installs handlers and formatters on the
                               root docpipe logger. Set to False when the calling application
                               manages its own logging configuration.

        Raises:
            DocpipeException: If neither flow_file nor flow_def is provided
            DocpipeException: If both flow_file and flow_def are provided
            FileNotFoundError: If flow_file doesn't exist
            json.JSONDecodeError: If flow_file contains invalid JSON
            FlowInvalidDataException: If flow validation fails

        Note:
            Logging level is controlled via the DS_LOG_LEVEL environment variable.
            Set DS_LOG_LEVEL to DEBUG, INFO, WARNING, ERROR, or CRITICAL before
            creating the DocpipeFlowManager instance.
        """
        if flow_file is None and flow_def is None:
            raise DocpipeException("Either flow_file or flow_def must be provided", status_code=400)

        if flow_file is not None and flow_def is not None:
            raise DocpipeException("Only one of flow_file or flow_def should be provided", status_code=400)

        # Configure DPK log level to match DS_LOG_LEVEL
        set_dpk_log_level_from_ds_log_level()

        # Install handlers only when this instance owns the process output
        if configure_logging:
            setup_logging()

        self.logger: Logger = get_logger()

        # Initialize original_flow_def with proper type annotation
        self.original_flow_def: dict[str, Any] | None = None

        # Load and compile flow definition from authoring format
        if flow_file is not None:
            self.flow_file = flow_file
            # Load and compile - returns both original and compiled
            self.original_flow_def, self.flow_def = self._load_and_compile_flow(file_path=flow_file)
        else:
            self.flow_file = None  # type: ignore[assignment]
            self.original_flow_def = flow_def  # Store original for audit trail
            self.flow_def = self._compile_flow_dict(flow_dict=flow_def)  # type: ignore

        # Set up execution parameters with priority: parameter > flow_def > UUID
        flow_def_flow_id = self.flow_def.get(DocpipeConstants.FLOW_ID) if self.flow_def else None

        # job_id priority: parameter > flow_def > UUID
        self.job_id = job_id or flow_def_flow_id or str(uuid.uuid4())

        # job_run_id defaults to dynamically generated UUID if not provided
        self.job_run_id = job_run_id or str(uuid.uuid4())

        # flow_id priority: parameter > flow_def > job_id
        self.flow_id = flow_id or flow_def_flow_id or self.job_id

        # Custom operator support
        self.custom_operator_packages: list[str] = []
        self.enable_custom_operators = enable_custom_operators

        # Execution reporter support
        self.enable_execution_reporter = enable_execution_reporter
        self.execution_reporter: FlowExecutionReporter | None = None
        if self.enable_execution_reporter:
            self.execution_reporter = FlowExecutionReporter()

        # Execution state (initialized during execute())
        self.orchestrator: Any | None = None
        self.session_info: SessionInfo | None = None
        self.executor: FlowExecutor | None = None

    def _load_and_compile_flow(self, *, file_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Load authoring format flow from JSON file and compile to runtime DAG format.

        Args:
            file_path: Path to authoring format JSON file

        Returns:
            Tuple of (original_flow_data, compiled_runtime_dag)

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file contains invalid JSON
            FlowInvalidDataException: If authoring format validation fails
        """
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Flow definition file '{file_path}' not found")

        try:
            with Path(path_obj).open() as f:
                flow_data = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in flow definition file: {e.msg}", e.doc, e.pos) from e

        compiled_flow = self._compile_flow_dict(flow_dict=flow_data)
        return flow_data, compiled_flow

    def register_custom_operators(self, *, package_names: list[str]) -> None:
        """
        Register custom operator packages for use in flows.

        This method allows programmatic registration of custom operators by specifying
        Python package names. The packages will be loaded when the orchestrator is
        initialized during flow execution.

        Args:
            package_names: List of Python package names containing custom operators
                          (e.g., ["my_company.operators", "custom_ops"])

        Example:
            manager = DocpipeFlowManager(flow_file="flow.json")
            manager.register_custom_operators(package_names=["my_company.operators"])
            result = manager.execute()

        Note:
            - Custom operators must inherit from AbstractOperator
            - Custom operators must have unique short_name values
            - Custom operators take priority over docpipe operators with same short_name
            - Call this method before execute() to ensure operators are available
        """
        if not isinstance(package_names, list):
            raise DocpipeException(message="package_names must be a list of strings", status_code=400)

        if not all(isinstance(pkg, str) for pkg in package_names):
            raise DocpipeException(message="All package names must be strings", status_code=400)

        self.custom_operator_packages.extend(package_names)
        self.logger.info("Registered custom operator packages: %s", package_names)

    def _compile_flow_dict(self, *, flow_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Compile authoring format flow dictionary to runtime DAG format.

        Args:
            flow_dict: Authoring format flow definition dictionary

        Returns:
            Compiled runtime DAG format flow definition

        Raises:
            FlowInvalidDataException: If authoring format validation fails
        """
        self.logger.info("Loading authoring format flow definition")

        # Set flow_source to PROGRAMMATIC for Python API usage
        flow_dict[DocpipeConstants.FLOW_SOURCE] = FlowSource.PROGRAMMATIC

        try:
            # Parse and validate authoring format
            authoring_flow = AuthoringFlow.from_dict(data=flow_dict)
        except FlowInvalidDataException as e:
            self.logger.error("Authoring format validation failed: %s", e)
            raise

        # Compile to runtime DAG format
        self.logger.info("Compiling authoring format to runtime DAG format")
        compiler = AuthoringCompiler()
        compiled_flow = compiler.compile(authoring_flow=authoring_flow)

        self.logger.info("Successfully compiled authoring format to runtime DAG format")
        return compiled_flow

    def _initialize_execution_environment(self) -> None:
        """Initialize orchestrator and session for execution."""
        # Create orchestrator with custom operator settings
        # Default to True if enable_custom_operators is None
        enable_custom = self.enable_custom_operators if self.enable_custom_operators is not None else True
        self.orchestrator = OrchestratorFactory.create_orchestrator(
            enable_custom_operators=enable_custom,
            custom_operator_packages=self.custom_operator_packages if self.custom_operator_packages else None,
            execution_reporter=self.execution_reporter,
        )

        # Validate flow definition is initialized
        if self.flow_def is None:
            raise DocpipeException("Flow definition must be initialized before use", status_code=500)

        # Set up session info
        self.session_info = create_session_info(
            job_id=self.job_id, job_run_id=self.job_run_id, orchestrator=self.orchestrator, flow_id=self.flow_id
        )

        # Initialize orchestrator
        self.orchestrator.initialize(job_id=self.job_id, job_run_id=self.job_run_id)

        # Create flow executor - must be done after session_info is set
        self.executor = FlowExecutor(
            flow_def=self.flow_def, orchestrator=self.orchestrator, original_flow_def=self.original_flow_def
        )

    def validate(self) -> dict[str, Any]:
        """
        Validate the flow definition without executing it.

        Returns:
            Dictionary containing validation results with keys:
                - 'valid': bool indicating if flow is valid
                - 'errors': list of validation errors (if any)
                - 'warnings': list of validation warnings (if any)

        Raises:
            DocpipeException: If flow definition is not initialized

        Example:
            manager = DocpipeFlowManager(flow_file="flow.json")
            validation_result = manager.validate()
            if validation_result['valid']:
                result = manager.execute()
        """
        if self.flow_def is None:
            raise DocpipeException("Flow definition must be initialized before validation", status_code=500)

        try:
            # Create orchestrator with custom operator settings
            enable_custom = self.enable_custom_operators if self.enable_custom_operators is not None else True
            custom_packages = self.custom_operator_packages if len(self.custom_operator_packages) > 0 else None

            temp_orchestrator = OrchestratorFactory.create_orchestrator(
                enable_custom_operators=enable_custom,
                custom_operator_packages=custom_packages,
            )

            # Initialize the orchestrator (required for FlowValidator)
            temp_orchestrator.initialize(job_id=self.job_id, job_run_id=self.job_run_id)

            # Establish session context so validators and operators read correct job/flow IDs
            create_session_info(
                job_id=self.job_id,
                job_run_id=self.job_run_id,
                orchestrator=temp_orchestrator,
                flow_id=self.flow_id,
            )

            validator = FlowValidator(orchestrator=temp_orchestrator)

            # Prepare validation parameters
            params: dict[str, Any] = {
                DocpipeConstants.JOB_ID: self.job_id,
                DocpipeConstants.JOB_RUN_ID: self.job_run_id,
            }

            # FlowValidator.validate() raises FlowValidationException on errors/warnings
            validator.validate(flow_def=self.flow_def, params=params)

            # If we get here, validation succeeded with no errors or warnings
            return {"valid": True, "errors": [], "warnings": []}

        except FlowValidationException as e:
            # Extract errors and warnings from the exception
            errors = [str(err) for err in e.errors] if e.errors else []
            warnings = [str(warn) for warn in e.warnings] if e.warnings else []

            # Validation fails only if there are errors (warnings are acceptable)
            is_valid = len(errors) == 0

            return {
                "valid": is_valid,
                "errors": errors,
                "warnings": warnings,
            }
        except Exception as e:
            self.logger.error("Flow validation failed: %s", e)
            return {"valid": False, "errors": [str(e)], "warnings": []}

    def execute(self) -> Any:
        """
        Execute the flow.

        Returns:
            DataAccess object containing execution results

        Raises:
            DocpipeException: If flow definition is not initialized or execution fails

        Example:
            manager = DocpipeFlowManager(flow_file="flow.json")
            result = manager.execute()
            print(f"Execution completed: {result}")
        """
        # Initialize execution environment
        self._initialize_execution_environment()

        # Set up execution parameters
        params: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }
        flow_global_config = self.flow_def.get("global_config", {})
        if DocpipeConstants.ENABLE_MICRO_BATCHING not in flow_global_config:
            params[DocpipeConstants.ENABLE_MICRO_BATCHING] = True

        try:
            # Delegate execution to FlowExecutor (logging moved to FlowExecutor.execute())
            return self.executor.execute(orchestrator=self.orchestrator, params=params)  # type: ignore
        except Exception as e:
            self.logger.error("Flow execution failed: %s", e)
            raise

    def get_execution_metadata(self) -> dict[str, Any]:
        """
        Get metadata about the execution.

        Returns:
            Dictionary containing execution metadata

        Example:
            manager = DocpipeFlowManager(flow_file="flow.json")
            result = manager.execute()
            metadata = manager.get_execution_metadata()
            print(f"Job ID: {metadata['job_id']}")
        """
        return {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
            DocpipeConstants.FLOW_ID: self.flow_id,
            DocpipeConstants.FLOW_NAME: self.flow_def.get(DocpipeConstants.NAME, DocpipeConstants.UNNAMED_FLOW)
            if self.flow_def
            else DocpipeConstants.UNNAMED_FLOW,  # type: ignore
            DocpipeConstants.FLOW_DESCRIPTION: self.flow_def.get(DocpipeConstants.DESCRIPTION, "")
            if self.flow_def
            else "",  # type: ignore
            "num_operators": len(self.flow_def.get(DocpipeConstants.DAG, [])) if self.flow_def else 0,  # type: ignore
            "flow_file": self.flow_file,
        }

    def get_execution_logs(self) -> list[str]:
        """
        Get logs captured during flow execution.

        This method should be called after ``execute()`` has run. It reads logs
        from the orchestrator event handler when available and returns them as a
        list of log lines. If execution has not been run yet, or if no logs are
        available, an empty list is returned.

        Returns:
            List of log entries captured during execution, or an empty list if
            execution has not run or no logs are available.

        Example:
            manager = DocpipeFlowManager(flow_file="flow.json")
            result = manager.execute()
            logs = manager.get_execution_logs()
            print(logs)
        """
        if self.orchestrator is None:
            return []

        try:
            # Get formatted job stats with logs included
            job_stats_response = self.orchestrator.job_stats_service.get_formatted_job_stats(
                job_run_id=self.job_run_id, include_logs=True
            )

            # The response carries one log string per node as a dynamic attribute named after the node id
            return [getattr(job_stats_response, node_id) for node_id in job_stats_response.node_sequence]
        except Exception as e:
            self.logger.warning("Failed to retrieve execution logs: %s", e)
            return []

    @staticmethod
    def list_operators(verbose: bool = False) -> str:
        """
        List all available operators.

        Args:
            verbose: If True, show detailed information about each operator

        Returns:
            Formatted string listing all operators

        Example:
            # List operators with summary
            print(DocpipeFlowManager.list_operators())

            # List operators with details
            print(DocpipeFlowManager.list_operators(verbose=True))
        """
        return _list_operators(verbose=verbose, summary_only=not verbose)
