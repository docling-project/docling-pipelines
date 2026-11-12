# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Flow Engine Port - Abstract interface for flow execution engines.

This port defines the contract that any flow execution engine must implement,
enabling the orchestrator to work with different execution strategies
(Prefect, Airflow, pure Python, etc.) without tight coupling.

This follows hexagonal architecture principles by defining the port in the
domain layer, allowing adapters to be implemented in the infrastructure layer.
"""

from abc import ABC, abstractmethod
from typing import Any


class ExecuteStepResults:
    """
    Results from executing a single step/operator.

    This class encapsulates the output of an operator execution, including
    data accesses, tables, and internal metadata.
    """

    def __init__(self, data_accesses: list, tables: list, internal_metadata: dict[str, Any]):
        """
        Initialize execution step results.

        Args:
            data_accesses: List of DataAccess objects for the output data
            tables: List of PyArrow tables containing the processed data
            internal_metadata: Dictionary of internal metrics and metadata
        """
        self.data_accesses = data_accesses
        self.tables = tables
        self.internal_metadata = internal_metadata


class FlowEnginePort(ABC):
    """
    Abstract interface for flow execution engines.

    This port allows the orchestrator to delegate flow execution to different
    implementations (Prefect, Airflow, pure Python) without knowing the details.

    The port follows the Dependency Inversion Principle: the high-level orchestrator
    depends on this abstraction, not on concrete implementations.
    """

    def __init__(self, *, orchestrator, batch_manager, job_id: str, job_run_id: str, job_log_path: str):
        """
        Initialize the flow engine.

        Args:
            orchestrator: Reference to the parent AbstractOrchestrator instance
            batch_manager: Batch manager for handling batch operations
            job_id: Job identifier
            job_run_id: Job run identifier
            job_log_path: Path for job logs
        """
        self.orchestrator = orchestrator
        self.batch_manager = batch_manager
        self.job_id = job_id
        self.job_run_id = job_run_id
        self.job_log_path = job_log_path

    @abstractmethod
    def execute_batch_flow(
        self, *, op_flow: list[dict[str, Any]], batches: list, global_config: dict[str, Any]
    ) -> None:
        """
        Execute a batch flow with multiple batches.

        This method handles the execution of operators across multiple data batches,
        typically used for parallel processing of large datasets.

        Args:
            op_flow: List of operator definitions (DAG nodes)
            batches: List of batches to process
            global_config: Global configuration dictionary
        """
        ...

    @abstractmethod
    def execute_non_execute_flow(self, *, flow_name: str, task: Any, dag: Any) -> None:
        """
        Execute a non-execution flow (e.g., validation, visualization).

        This method handles flows that don't process data but perform other operations
        like validation, DAG visualization, or metadata extraction.

        Args:
            flow_name: Optional flow name for identification
            task: Task to execute (e.g., validation task)
            dag: DAG definition to operate on
        """
        ...

    @abstractmethod
    def execute_operator_flow(
        self, *, op_flow: list[dict[str, Any]], data_access: Any, global_config: dict[str, Any]
    ) -> Any:
        """
        Execute operator flow - used by batch workers.

        This method executes a sequence of operators on a single data batch,
        typically called by batch workers in parallel execution scenarios.

        Args:
            op_flow: List of operator definitions (DAG nodes)
            data_access: DataAccess object containing batch data
            global_config: Global configuration dictionary

        Returns:
            Execution results (implementation-specific)
        """
        ...
