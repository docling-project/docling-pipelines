# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from typing import ClassVar

from docpipe.core.constants import OrchestratorType
from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
from docpipe.core.job_management.domain.ports import JobRunManager, JobStatsService
from docpipe.core.lineage.application import lineage_factory
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator

"""
Default orchestrators - can be overridden via register_orchestrators()
"""
_default_orchestrators: dict[str, type[AbstractOrchestrator]] = {OrchestratorType.PYTHON: PythonOrchestrator}


class OrchestratorFactory:
    """
    Factory class to create an instance of an orchestrator with dependency injection.
    Supports registering custom orchestrators to override or extend the default set.
    """

    # Class-level registry for orchestrators
    _orchestrators: ClassVar[dict[str, type[AbstractOrchestrator]]] = {}

    @classmethod
    def _initialize_orchestrators(cls) -> None:
        """Initialize orchestrators registry if empty."""
        if not cls._orchestrators:
            cls._orchestrators.update(_default_orchestrators)

    @classmethod
    def register_orchestrators(cls, *, orchestrators: dict[str, type[AbstractOrchestrator]]) -> None:
        """
        Register different set of orchestrator classes.

        Args:
            orchestrators: A dictionary of orchestrator name and class

        Raises:
            TypeError: If orchestrator_class is not a subclass of AbstractOrchestrator
        """
        if not orchestrators:
            raise ValueError("orchestrators dict must not be empty")
        cls._orchestrators = orchestrators

    @classmethod
    def get_registered_orchestrators(cls) -> dict[str, type[AbstractOrchestrator]]:
        """
        Get a copy of all registered orchestrators.

        Returns:
            Dictionary mapping orchestrator names to their classes
        """
        cls._initialize_orchestrators()
        return cls._orchestrators.copy()

    @classmethod
    def reset_orchestrators(cls) -> None:
        """
        Reset orchestrators to the default set.
        Useful for testing or when you want to clear custom registrations.
        """
        cls._orchestrators.clear()
        cls._orchestrators.update(_default_orchestrators)

    @classmethod
    def create_orchestrator(
        cls,
        *,
        orchestrator_name: str = OrchestratorType.PYTHON,
        job_stats_service: JobStatsService | None = None,
        job_run_manager: JobRunManager | None = None,
        enable_custom_operators: bool | None = None,
        custom_operator_packages: list[str] | None = None,
        execution_reporter=None,
    ) -> AbstractOrchestrator:  # pragma: no cover
        """
        Create an instance of the orchestrator with injected dependencies.

        Args:
            orchestrator_name: Type of orchestrator to create
            job_stats_service: Optional job stats service (uses default if None)
            job_run_manager: Optional job run manager for framework status updates
            enable_custom_operators: Whether to enable custom operators (passed to operator factory)
            custom_operator_packages: List of custom operator packages (passed to operator factory)
            execution_reporter: Optional output formatter for user-friendly console output

        Returns:
            Configured orchestrator instance

        Raises:
            KeyError: If orchestrator_name is not registered
        """
        cls._initialize_orchestrators()

        if job_stats_service is None:
            factory = get_default_factory()
            job_stats_service = factory.create_job_stats_service()

        if orchestrator_name not in cls._orchestrators:
            raise KeyError(
                f"Orchestrator '{orchestrator_name}' is not registered. Available: {list(cls._orchestrators.keys())}"
            )

        orchestrator_class = cls._orchestrators[orchestrator_name]
        observer = lineage_factory.create_lineage_observer()
        return orchestrator_class(
            job_stats_service=job_stats_service,
            job_run_manager=job_run_manager,
            enable_custom_operators=enable_custom_operators,
            custom_operator_packages=custom_operator_packages,
            execution_reporter=execution_reporter,
            observer=observer,
        )
