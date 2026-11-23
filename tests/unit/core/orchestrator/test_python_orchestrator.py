# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

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

    def test_default_orchestrator_has_custom_operators_disabled(self, monkeypatch) -> None:
        """With nothing configured the orchestrator reports a resolved boolean False, and so does its executor."""
        monkeypatch.delenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", raising=False)
        orchestrator = PythonOrchestrator()

        executor = orchestrator.create_executor_impl(
            name="noop_node",
            operator=OperatorConstants.Operators.NOOP,
            params={OperatorConstants.Columns.ID: "noop_node"},
        )

        assert orchestrator.enable_custom_operators is False
        assert executor.operator_factory.enable_custom_operators is False

    def test_env_var_enables_custom_operators_when_not_passed(self, monkeypatch) -> None:
        """DOCPIPE_ENABLE_CUSTOM_OPERATORS=true is honoured when the caller passes nothing."""
        monkeypatch.setenv("DOCPIPE_ENABLE_CUSTOM_OPERATORS", "true")

        assert PythonOrchestrator().enable_custom_operators is True
