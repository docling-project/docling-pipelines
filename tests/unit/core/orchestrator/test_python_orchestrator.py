"""Unit tests for PythonOrchestrator."""

from docpipe.core.constants.constants import OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.noop import NOOPOperator
from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator


class TestPythonOrchestrator:
    """Type reporting and executor creation of the in-process orchestrator."""

    def test_get_type_is_python(self) -> None:
        """The orchestrator reports the python orchestrator type."""
        assert PythonOrchestrator().get_type() == OrchestratorType.PYTHON == "python"

    def test_create_executor_impl_builds_python_executor_for_operator(self) -> None:
        """The executor it creates is a PythonOperatorExecutor that resolves the requested operator."""
        orchestrator = PythonOrchestrator(enable_custom_operators=False)

        executor = orchestrator.create_executor_impl(
            name="noop_node",
            operator=OperatorConstants.Operators.NOOP,
            params={OperatorConstants.Columns.ID: "noop_node"},
        )

        assert isinstance(executor, PythonOperatorExecutor)
        assert executor.operator_factory.enable_custom_operators is False
        assert isinstance(executor.get_operator(), NOOPOperator)
