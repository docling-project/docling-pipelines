# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from docpipe.core.constants import OrchestratorType
from docpipe.core.job_management.domain.ports import JobRunManager, JobStatsService
from docpipe.core.lineage.domain.ports.execution_lifecycle_observer import ExecutionLifecycleObserverPort
from docpipe.core.orchestration.abstract_operator_executor import AbstractOperatorExecutor
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.ports.flow_engine import FlowEnginePort
from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor


class PythonOrchestrator(AbstractOrchestrator):
    """
    This orchestrator is used for pure Python orchestrations
    """

    def __init__(
        self,
        *,
        job_stats_service: JobStatsService | None = None,
        job_run_manager: JobRunManager | None = None,
        enable_custom_operators: bool | None = None,
        custom_operator_packages: list[str] | None = None,
        execution_reporter=None,
        observer: ExecutionLifecycleObserverPort | None = None,
    ):
        super().__init__(
            job_stats_service=job_stats_service,
            job_run_manager=job_run_manager,
            enable_custom_operators=enable_custom_operators,
            custom_operator_packages=custom_operator_packages,
            execution_reporter=execution_reporter,
            observer=observer,
        )

    def create_executor_impl(
        self,
        *,
        name: str,
        operator: str,
        params: dict,
        job_stats_service: JobStatsService | None = None,
    ) -> AbstractOperatorExecutor:
        """Create executor impl."""
        return PythonOperatorExecutor(
            name=name,
            operator=operator,
            params=params,
            job_stats_service=job_stats_service,
            enable_custom_operators=self.enable_custom_operators,
            custom_operator_packages=self.custom_operator_packages,
        )

    def _create_flow_engine(self, *, job_id: str, job_run_id: str, job_log_path: str) -> FlowEnginePort:
        """
        Create Prefect-based flow engine for Python orchestrator.

        This factory method implements the abstract method from AbstractOrchestrator,
        providing a Prefect-based execution engine. The import is done locally to
        avoid tight coupling at the module level.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            job_log_path: Path for job logs

        Returns:
            FlowEnginePort: Prefect engine implementation
        """
        from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine

        return PrefectEngine(
            orchestrator=self,
            batch_manager=self.batch_manager,
            job_id=job_id,
            job_run_id=job_run_id,
            job_log_path=job_log_path,
        )

    def get_type(self) -> str:
        """Get type."""
        return OrchestratorType.PYTHON
