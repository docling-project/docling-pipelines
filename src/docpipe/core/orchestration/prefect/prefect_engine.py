# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Prefect Flow Engine - Prefect-specific implementation of FlowEnginePort.

This adapter implements flow execution using Prefect's task orchestration,
following hexagonal architecture principles by implementing the FlowEnginePort interface.
"""

import copy
from typing import Any, Callable, ParamSpec, Protocol, TypeVar, cast

# CRITICAL: Set Prefect env vars BEFORE importing Prefect modules
from docpipe.utils.orchestration.prefect_config import set_prefect_env_variables

set_prefect_env_variables()

from prefect import flow, task  # noqa: E402
from prefect.cache_policies import NO_CACHE  # noqa: E402
from prefect.futures import PrefectFuture  # noqa: E402
from prefect.runtime import task_run  # noqa: E402
from prefect.states import Completed  # noqa: E402
from prefect.task_runners import TaskRunner, ThreadPoolTaskRunner  # noqa: E402

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, TaskType  # noqa: E402
from docpipe.core.constants.operator_constants import OperatorConstants  # noqa: E402
from docpipe.core.incremental_metadata import get_incremental_update_service  # noqa: E402
from docpipe.core.models.session_info import get_session_info  # noqa: E402
from docpipe.core.orchestration.futured_list import FuturedList  # noqa: E402
from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults, FlowEnginePort  # noqa: E402
from docpipe.core.orchestration.prefect.ports.batch_execution_port import (  # noqa: E402
    BatchExecutionPort,
)
from docpipe.exceptions.docpipe_exceptions import (  # noqa: E402
    ErrorCode,
    FlowExecutionFailedException,
    FlowValidationException,
    PrefectFlowFailed,
)
from docpipe.utils.infrastructure.logging import get_logger  # noqa: E402
from docpipe.utils.orchestration.flow_utils import create_node_id_to_index_map  # noqa: E402

logger = get_logger()

DRAIN_TIMEOUT_SECONDS = 300


R = TypeVar("R")  # The return type of the user's function
P = ParamSpec("P")


class SupportsSubmit(Protocol):
    """Supportssubmit."""

    def submit(self, *args: Any, **kwargs: Any) -> PrefectFuture: ...


class BatchFuture:
    """Container for batch execution future with metadata."""

    def __init__(self, *, batch_id: str, batch_num: int, future: PrefectFuture, batch_info=None, data_access=None):
        self.batch_id = batch_id
        self.batch_num = batch_num
        self.future: PrefectFuture[Any] | None = future
        # Kept so the batch's table and DataAccess can be dropped the moment the
        # batch finishes, instead of living until the whole outer flow returns.
        self.batch_info = batch_info
        self.data_access = data_access
        self.released = False

    def release(self) -> None:
        """Drop this batch's data once it has reached a terminal state.

        The outer flow holds one BatchFuture per batch for the whole job.  Without
        this, every batch's table stays resident until the last batch finishes, so
        memory scales with batch count instead of with concurrency.

        The DataAccess is also passed to Prefect as a task parameter, and Prefect
        may keep its own reference to it.  Emptying the DataAccess's table dict
        frees the table regardless of who still holds the object.

        Only the data is dropped.  batch_id and batch_num stay, so logging and
        failure reporting keep working.
        """
        if self.released:
            return
        if self.data_access is not None:
            try:
                self.data_access.tables = None
            except Exception:  # nosec B110 - pragma: no cover - releasing memory must never fail a flow
                pass
            self.data_access = None
        if self.batch_info is not None:
            self.batch_info.table = None
            self.batch_info = None
        self.future = None
        self.released = True

    def describe_state(self) -> str:
        """Describe state."""
        state_parts: list[str] = []

        if self.future is None:
            return "released"

        try:
            state_parts.append(f"is_completed={self.future.state.is_completed()}")
            state_parts.append(f"is_failed={self.future.state.is_failed()}")
            state_parts.append(f"is_crashed={self.future.state.is_crashed()}")
            state_parts.append(f"is_cancelled={self.future.state.is_cancelled()}")
            state_parts.append(f"state_type={getattr(self.future.state.type, 'value', self.future.state.type)}")
            state_parts.append(f"state_name={getattr(self.future.state, 'name', 'unknown')}")
        except Exception as exc:
            state_parts.append(f"state_unavailable={exc}")

        wrapped_future = getattr(self.future, "_wrapped_future", None)
        if wrapped_future is not None:
            try:
                state_parts.append(f"wrapped_done={wrapped_future.done()}")
                state_parts.append(f"wrapped_cancelled={wrapped_future.cancelled()}")
                state_parts.append(f"wrapped_running={wrapped_future.running()}")
            except Exception as exc:
                state_parts.append(f"wrapped_state_unavailable={exc}")

        return ", ".join(state_parts)


class PrefectEngine(FlowEnginePort):
    """
    Prefect-specific implementation of FlowEnginePort.

    This adapter implements flow execution using Prefect's task orchestration.
    It is responsible for:
    - Building Prefect flows with appropriate configuration
    - Creating and managing Prefect tasks
    - Executing flows with proper task orchestration
    - Managing batch execution with parallelism control
    """

    def __init__(self, *, orchestrator, batch_manager, job_id: str, job_run_id: str, job_log_path: str):
        super().__init__(
            orchestrator=orchestrator,
            batch_manager=batch_manager,
            job_id=job_id,
            job_run_id=job_run_id,
            job_log_path=job_log_path,
        )
        self.logger = get_logger()
        self.common_log_arguments = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

    def execute_batch_flow(self, *, op_flow, batches, global_config):
        """
        Execute batches using configured strategy (ThreadPool or WorkPool).

        Strategy is selected based on global_config.prefect.batch_execution.strategy:
        - "thread-pool" (default): Local execution using ThreadPoolTaskRunner
        - "work-pool-*": Distributed execution via Prefect work pools

        The strategy pattern enables seamless switching between local and distributed
        execution without changing the orchestrator code.
        """
        from docpipe.core.orchestration.prefect.adapters.factories.batch_execution_factory import BatchExecutionFactory

        # Create appropriate strategy based on configuration
        strategy: BatchExecutionPort = BatchExecutionFactory.create_strategy(
            config=global_config, prefect_engine=self, batch_manager=self.batch_manager
        )

        # Execute batches using the selected strategy
        strategy.execute_batches(
            batches=batches,
            op_flow=op_flow[1:],  # Skip ingest operator
            global_config=global_config,
            job_run_id=self.job_run_id,
        )

    def execute_non_execute_flow(self, *, flow_name: str, task: Any, dag: Any):
        """Execute non execute flow."""
        flow = self.build_non_execute_flow(flow_name=flow_name)
        flow(TaskType.VALIDATE_FLOW, task, dag, None)

    def _build_flow(self, *, name, flow_impl, timeout_seconds: int | None = None):
        """Build a Prefect flow for operator execution."""
        prefect_config = self.__get_prefect_config()
        effective_timeout = timeout_seconds if timeout_seconds is not None else prefect_config["timeout_seconds"]

        return flow(
            name=name,
            timeout_seconds=effective_timeout,
            retries=prefect_config["flow_retries"],
            retry_delay_seconds=prefect_config["retry_delay_seconds"],
            log_prints=prefect_config["log_prints"],
            task_runner=cast(
                "TaskRunner[PrefectFuture[Any]]", ThreadPoolTaskRunner(max_workers=prefect_config["max_workers"])
            ),
        )(flow_impl)

    def build_non_execute_flow(self, *, flow_name=None):
        """Build a Prefect flow for non-execution tasks (validation, etc.)."""
        prefect_config = self.__get_prefect_config()

        return flow(
            name="task_pipeline" if flow_name is None else flow_name,
            timeout_seconds=prefect_config["timeout_seconds"],
            retries=prefect_config["flow_retries"],
            retry_delay_seconds=prefect_config["retry_delay_seconds"],
            log_prints=prefect_config["log_prints"],
            task_runner=cast(
                "TaskRunner[PrefectFuture[Any]]", ThreadPoolTaskRunner(max_workers=prefect_config["max_workers"])
            ),
        )(self.__non_execute_inner_flow)

    def batch_outer_flow_impl(self, op_flow, batches, global_config) -> list[BatchFuture]:
        """
        Process batches using Prefect sub-flows with DAG parallelism.

        Each batch executes as an independent Prefect sub-flow that processes
        the entire DAG with full operator-level parallelism.

        Manages batch semaphore lifecycle:
        - Initializes semaphore at start
        - Resets semaphore in finally block (via _wait_for_sub_flows)
        """
        # Initialize batch semaphore for batch-level concurrency control
        max_concurrent_batches = global_config.get(
            DocpipeConstants.MAX_CONCURRENT_BATCHES,
            DocpipeConstants.DEFAULT_MAX_CONCURRENT_BATCHES,
        )
        if not isinstance(max_concurrent_batches, int) or max_concurrent_batches <= 0:
            raise FlowExecutionFailedException(
                f"{DocpipeConstants.MAX_CONCURRENT_BATCHES} must be a positive integer, got {max_concurrent_batches!r}"
            )

        self.batch_manager.initialize_batch_semaphore(max_concurrent_batches=max_concurrent_batches)

        # 1. Build the inner flow to execute a batch once (reusable for all batches).
        inner_flow = self._build_flow(
            name="batch_sub_flow",
            flow_impl=self.__flow_impl,
            timeout_seconds=self.__get_prefect_config()["sub_flow_timeout_seconds"],
        )

        # 2. Define a task to execute inner flow.
        #    NO_CACHE avoids result persistence that cache_key_fn silently enabled.
        @task(cache_policy=NO_CACHE)
        def batch_subflow_task(batch_id, batch_num, op_flow, global_config, batch_data_access):
            """Execute a single batch as a Prefect subflow."""
            # Throttle concurrent batches. The task runner has 50 workers, so
            # without this every batch runs at once and max_concurrent_batches
            # is silently ignored. Snapshot it before acquire() so its finally
            # block releases the same semaphore if the main thread resets it.
            batch_semaphore = self.batch_manager.get_batch_semaphore()
            if batch_semaphore:
                batch_semaphore.acquire()
                self.logger.info(
                    "Batch %s (ID: %s): acquired batch semaphore slot",
                    batch_num,
                    batch_id,
                    extra=self.common_log_arguments,
                )

            try:
                self.logger.info(
                    "Batch %s (ID: %s): starting execution",
                    batch_num,
                    batch_id,
                    extra=self.common_log_arguments,
                )
                from docpipe.core.constants.operator_constants import OperatorConstants

                self.logger.debug(
                    "Batch %s: global_config has ingest_source=%s",
                    batch_num,
                    OperatorConstants.Config.INGEST_SOURCE in global_config,
                    extra=self.common_log_arguments,
                )
                batch_global_config = global_config.copy()
                self.logger.debug(
                    "Batch %s: batch_global_config (after copy) has ingest_source=%s",
                    batch_num,
                    OperatorConstants.Config.INGEST_SOURCE in batch_global_config,
                    extra=self.common_log_arguments,
                )
                if global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False):
                    batch_global_config[DocpipeConstants.BATCH_NUM] = batch_num
                    batch_global_config[DocpipeConstants.BATCH_ID] = batch_id

                flow_def = global_config.get(DocpipeConstants.FLOW_DEFINITION, {})
                flow_name = flow_def.get(DocpipeConstants.FLOW_NAME) or flow_def.get(
                    DocpipeConstants.NAME, "docpipe_flow"
                )
                run_name = f"{flow_name}_batch_{batch_num}"
                result = inner_flow.with_options(flow_run_name=run_name)(
                    op_flow=op_flow,
                    data_access=batch_data_access,
                    global_config=batch_global_config,
                )
                self.logger.info(
                    "Batch %s (ID: %s): completed execution",
                    batch_num,
                    batch_id,
                    extra=self.common_log_arguments,
                )
                return result
            finally:
                # Release in finally so a failed or cancelled batch never strands a slot.
                if batch_semaphore:
                    batch_semaphore.release()
                    self.logger.info(
                        "Batch %s (ID: %s): released batch semaphore slot",
                        batch_num,
                        batch_id,
                        extra=self.common_log_arguments,
                    )
                # Last-resort drop of this batch's non-recoverable-docs bucket.
                # The sub-flow drops it on both its success and fail-fast paths;
                # this covers any other exception, so a bucket keyed by batch_id
                # can never outlive the batch.  pop() is idempotent.
                try:
                    self.orchestrator._non_recoverable_docs_tables.pop(batch_id, None)
                except Exception:  # nosec B110 - cleanup must never fail a batch
                    pass

        # Submit all batches as tasks
        batch_futures: list[BatchFuture] = []

        for batch_info in batches:
            batch_data_access = self.batch_manager.create_batch_data_access(batch_table=batch_info.table)

            flow_def = global_config.get(DocpipeConstants.FLOW_DEFINITION, {})
            flow_name = flow_def.get(DocpipeConstants.FLOW_NAME) or flow_def.get(DocpipeConstants.NAME, "docpipe_flow")
            run_name = f"{flow_name}_batch_{batch_info.batch_num}"
            # 3. Submit task that executes sub flow for each batch
            future = batch_subflow_task.with_options(task_run_name=run_name).submit(
                batch_id=batch_info.batch_id,
                batch_num=batch_info.batch_num,
                op_flow=op_flow,
                global_config=global_config,
                batch_data_access=batch_data_access,
            )
            batch_future = BatchFuture(
                batch_id=batch_info.batch_id,
                batch_num=batch_info.batch_num,
                future=future,
                batch_info=batch_info,
                data_access=batch_data_access,
            )
            batch_futures.append(batch_future)
            self.logger.info(
                "Submitted batch %s (ID: %s) future: %s",
                batch_future.batch_num,
                batch_future.batch_id,
                batch_future.describe_state(),
                extra=self.common_log_arguments,
            )

        # IMPORTANT: Wait for all batch futures INSIDE the outer flow.
        # When the @flow function returns, Prefect exits its run_context which
        # calls ThreadPoolTaskRunner.__exit__ → cancel_all() → executor.shutdown(cancel_futures=True).
        # Any tasks still running at that point get cancelled with CancelledError → Crashed state.
        # By resolving all futures here, we ensure the ThreadPoolTaskRunner is still active.
        self._wait_for_sub_flows(batch_futures=batch_futures, global_config=global_config)

        return batch_futures

    def _drain_batch_future(self, *, batch_future: BatchFuture) -> None:
        """Wait for a remaining batch without calling Prefect's removed cancel API."""
        if batch_future.future is None:
            return
        batch_future.future.wait(timeout=DRAIN_TIMEOUT_SECONDS)
        wrapped = getattr(batch_future.future, "_wrapped_future", None)
        if wrapped is None:
            self.logger.info(
                "Batch %s (ID: %s): drain finished, completion unverified",
                batch_future.batch_num,
                batch_future.batch_id,
                extra=self.common_log_arguments,
            )
            return
        if not wrapped.done():
            self.logger.warning(
                "Batch %s (ID: %s): still running after %ss drain timeout",
                batch_future.batch_num,
                batch_future.batch_id,
                DRAIN_TIMEOUT_SECONDS,
                extra=self.common_log_arguments,
            )
            return
        self.logger.info(
            "Batch %s (ID: %s): drained after fail-fast",
            batch_future.batch_num,
            batch_future.batch_id,
            extra=self.common_log_arguments,
        )
        batch_future.release()

    def _handle_batch_failure(
        self, *, batch_future: BatchFuture, exception: Exception, continue_on_batch_failure: bool
    ) -> bool:
        """Apply the batch failure policy and return whether fail-fast was triggered."""
        if continue_on_batch_failure:
            self.logger.warning(
                "Batch %s (ID: %s) failed, continuing because continue_on_batch_failure=True: %s",
                batch_future.batch_num,
                batch_future.batch_id,
                exception,
                extra=self.common_log_arguments,
            )
            return False
        self.orchestrator.job_status = ExecutionStatus.FAILING
        self.orchestrator.message = (
            f"Batch {batch_future.batch_num} (ID: {batch_future.batch_id}) failed: "
            f"{type(exception).__name__}: {exception}"
        )
        self.logger.error(
            "Batch %s (ID: %s) failed, triggering fail-fast: %s",
            batch_future.batch_num,
            batch_future.batch_id,
            exception,
            extra=self.common_log_arguments,
            exc_info=True,
        )
        return True

    def _wait_for_sub_flows(self, *, batch_futures: list[BatchFuture], global_config: dict) -> None:
        """Wait for every batch to reach a terminal state without raising."""
        continue_on_batch_failure = global_config.get(
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE_DEFAULT,
        )
        fail_fast_triggered = False
        failed_batch_nums: list[int] = []
        try:
            for batch_future in batch_futures:
                if fail_fast_triggered:
                    self._drain_batch_future(batch_future=batch_future)
                    continue
                try:
                    if batch_future.future is None:
                        continue
                    batch_future.future.result()
                    batch_future.release()
                except Exception as exception:
                    failed_batch_nums.append(batch_future.batch_num)
                    fail_fast_triggered = self._handle_batch_failure(
                        batch_future=batch_future,
                        exception=exception,
                        continue_on_batch_failure=continue_on_batch_failure,
                    )
                    batch_future.release()
            if continue_on_batch_failure and failed_batch_nums:
                if len(failed_batch_nums) == len(batch_futures):
                    self.orchestrator.job_status = ExecutionStatus.FAILING
                    self.orchestrator.message = f"All {len(batch_futures)} batches failed: {failed_batch_nums}"
                else:
                    self.logger.warning(
                        "Partial batch failure: %s of %s batches failed: %s",
                        len(failed_batch_nums),
                        len(batch_futures),
                        failed_batch_nums,
                        extra=self.common_log_arguments,
                    )
        finally:
            self.logger.info(
                "Resetting batch semaphore after sub-flow completion",
                extra=self.common_log_arguments,
            )
            self.batch_manager.reset_batch_semaphore()

    def __get_prefect_config(self) -> dict:
        """Get the default values for Prefect settings."""
        return {
            "task_retries": 0,
            "persist_result": False,
            "flow_retries": 0,
            "max_workers": 50,
            "log_prints": True,
            "retry_delay_seconds": 60,
            # Outer flow timeout: 120000s (33.3h). Large jobs (50k+ docs) can exceed 16.7h.
            # Inner sub-flow timeout is set separately — each sub-flow handles one batch only.
            "timeout_seconds": 120000,
            # Sub-flow timeout: 60000s (16.7h). One sub-flow processes a single batch,
            # so the original 60000s ceiling is appropriate here.
            "sub_flow_timeout_seconds": 60000,
        }

    def __create_task(
        self,
        *,
        task_func: Callable[..., Any],
        retries: int = 0,
        persist_result: bool = False,
    ) -> SupportsSubmit:
        """Create a Prefect task for operator execution."""

        def generate_task_name():
            """Generate task name."""
            parameters = task_run.parameters
            return parameters["op_def"]["name"]

        return task(
            task_run_name=generate_task_name,
            retries=retries,
            persist_result=persist_result,
        )(task_func)

    def __create_main_task(
        self,
        main_task: Callable[..., Any],
        retries: int = 0,
        persist_result: bool = False,
    ) -> SupportsSubmit:
        """Create a Prefect task for non-execution flows."""

        def generate_task_name():
            """Generate task name."""
            parameters = task_run.parameters
            return parameters["task_name"]

        return task(
            task_run_name=generate_task_name,
            retries=retries,
            persist_result=persist_result,
        )(main_task)

    def execute_operator_flow(self, *, op_flow, data_access, global_config):
        """
        Public method to execute operator flow - used by batch workers.

        This is the entry point for distributed batch workers to execute
        operator flows using the same logic as local execution.

        Args:
            op_flow: List of operator definitions
            data_access: DataAccess object containing batch data
            global_config: Global configuration dictionary
        """
        return self.__flow_impl(op_flow=op_flow, data_access=data_access, global_config=global_config)

    def __flow_impl(self, op_flow, data_access, global_config):
        """
        Execute the inner flow with Prefect task orchestration.

        This method builds and executes a DAG of operators using Prefect tasks,
        handling dependencies and parallelism automatically.
        """
        # In batch mode, get the ingest operator ID from global_config
        ingest_node_id = global_config.get(DocpipeConstants.INGEST_NODE_ID)
        batch_num = global_config.get(DocpipeConstants.BATCH_NUM)

        self.logger.info(
            "inner_flow: batch_num=%s, ingest_node_id=%s, op_flow_length=%s",
            batch_num,
            ingest_node_id,
            len(op_flow),
            extra=self.common_log_arguments,
        )

        def get_prev_results(
            op_definitions, results_: FuturedList, initial_batch_result
        ) -> PrefectFuture | dict[str, PrefectFuture]:
            """Get prev results."""
            prev_res: dict[str, PrefectFuture] = {}
            has_ingest_dependency = False

            for prev_node in op_definitions.get(DocpipeConstants.INPUT_EDGES, []):
                node_id_ref = prev_node["node_id_ref"]

                if node_id_ref not in node_id_to_index_map:
                    self.logger.debug(
                        "Node %s not in node_id_to_index_map. Checking: ingest_node_id=%s, match=%s",
                        node_id_ref,
                        ingest_node_id,
                        node_id_ref == ingest_node_id,
                        extra=self.common_log_arguments,
                    )

                    if ingest_node_id and node_id_ref == ingest_node_id:
                        self.logger.debug(
                            "Found ingest node dependency %s - will use batch data",
                            node_id_ref,
                            extra=self.common_log_arguments,
                        )
                        has_ingest_dependency = True
                        continue
                    self.logger.error(
                        "Node %s not found in flow. ingest_node_id=%s",
                        node_id_ref,
                        ingest_node_id,
                        extra=self.common_log_arguments,
                    )
                    raise FlowExecutionFailedException(f"Node {node_id_ref} not found in flow")

                prev_index = node_id_to_index_map[node_id_ref]
                prev_res[prev_node.get(DocpipeConstants.LINK_NAME)] = results_.get_future(prev_index)

            # If the only dependency is the ingest node, return the initial batch result
            if not prev_res and has_ingest_dependency:
                return initial_batch_result

            if len(prev_res) == 1:
                return next(iter(prev_res.values()))
            return prev_res

        prefect_config = self.__get_prefect_config()
        task_retries = prefect_config["task_retries"]
        persist_result = prefect_config["persist_result"]
        inner_task = self.__create_task(
            task_func=self.orchestrator._inner_task,
            retries=task_retries,
            persist_result=persist_result,
        )
        session_info = get_session_info()

        # Handle ingest-only flows (no downstream operators)
        if not op_flow:
            self.logger.info(
                "Ingest-only flow detected - no downstream operators to process. "
                "Returning ingested data without further processing.",
                extra=self.common_log_arguments,
            )
            # Create initial batch result with ingested data
            batch_table = data_access.get_table("")[0]
            return ExecuteStepResults([data_access], [batch_table], {})

        results: FuturedList = FuturedList.from_size(len(op_flow))
        destinations: list[tuple[PrefectFuture, Any]] = []
        node_id_to_index_map = create_node_id_to_index_map(flow_def=op_flow)
        incremental_update_util = get_incremental_update_service()
        deleted_docs_count = (
            len(incremental_update_util.get_soft_deleted_doc_ids(job_id=self.orchestrator.job_id))
            if self.orchestrator.job_id
            else 0
        )

        is_sequential_flow = (
            False
            if op_flow[0].get(DocpipeConstants.INPUT_EDGES) or op_flow[0].get(DocpipeConstants.OUTPUT_EDGES)
            else True
        )
        prev_index = None

        # Create initial batch result for first operator after ingest
        batch_table = data_access.get_table("")[0]
        initial_batch_result = ExecuteStepResults([data_access], [batch_table], {})

        for op_def in op_flow:
            # In fail-fast mode, stop submitting new tasks if a failure has occurred
            if self.orchestrator.job_status == ExecutionStatus.FAILING:
                # Skip remaining operators - they will be recorded as skipped by _inner_task
                continue

            index = node_id_to_index_map[op_def[OperatorConstants.Columns.ID]]
            try:
                link_id = op_def.get(OperatorConstants.Misc.LINK_ID, None)
                if prev_index is None:
                    prev_results = initial_batch_result
                else:
                    prev_results = (
                        results.get_future(prev_index)
                        if is_sequential_flow
                        else get_prev_results(op_def, results, initial_batch_result)
                    )

                future = inner_task.submit(
                    op_def=op_def,
                    global_config=global_config,
                    prev_results=prev_results,
                    session_info=session_info,
                    deleted_docs_count=deleted_docs_count,
                    link_id=link_id,
                )

                if is_sequential_flow:
                    destinations = [(future, op_def)]
                    results.set_entry(index, future, 1)
                else:
                    if not op_def.get(DocpipeConstants.OUTPUT_EDGES):
                        destinations.append((future, op_def))
                    else:
                        results.set_entry(index, future, len(op_def.get(DocpipeConstants.OUTPUT_EDGES)))
                prev_index = index
            except Exception as e:
                self.orchestrator._handle_node_failure(e=e, op_def=op_def, global_config=global_config)

        self.__wait_for_tasks(destinations=destinations)

        continue_on_batch_failure = global_config.get(
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE, DocpipeConstants.CONTINUE_ON_BATCH_FAILURE_DEFAULT
        )
        micro_batching_enabled = global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
        batch_num = global_config.get(DocpipeConstants.BATCH_NUM, "unknown")
        batch_failed = micro_batching_enabled and self.orchestrator.has_batch_failed(batch_num=batch_num)
        fail_fast_triggered = self.orchestrator.job_status == ExecutionStatus.FAILING and not continue_on_batch_failure
        if batch_failed or fail_fast_triggered:
            self.orchestrator._reset_non_recoverable_docs_for_batch(
                global_config=global_config, common_log_arguments=self.common_log_arguments
            )
            raise FlowExecutionFailedException(
                f"Batch {batch_num}: One or more operators failed "
                f"(micro_batching_enabled={micro_batching_enabled}, continue_on_batch_failure={continue_on_batch_failure})"
            )

        # Only collect results and save metadata if batch succeeded
        batch_id = global_config.get(DocpipeConstants.BATCH_ID)
        failed_doc_ids = self._collect_failed_doc_ids(batch_id=batch_id)

        tables = [
            destination[0].result().tables[0]
            for destination in destinations
            if hasattr(destination[0], "result")
            and destination[0].result()
            and hasattr(destination[0].result(), "tables")
        ]

        # Get merged non-recoverable docs table from orchestrator
        non_recoverable_docs_table = self.orchestrator._merge_non_recoverable_docs(
            global_config=global_config, common_log_arguments=self.common_log_arguments
        )

        incremental_update_util.save_metadata_for_incremental_update(
            job_id=self.orchestrator.context_id,
            job_run_id=self.job_run_id,
            tables=tables,
            failed_doc_ids=failed_doc_ids,
            non_recoverable_docs_table=non_recoverable_docs_table,
        )

        # Reset non-recoverable docs for micro-batching support
        self.orchestrator._reset_non_recoverable_docs_for_batch(
            global_config=global_config, common_log_arguments=self.common_log_arguments
        )
        return None

    def __non_execute_inner_flow(
        self,
        task_type: TaskType,
        inner_task: Any,
        op_flow,
        local_result,
        **kwargs,
    ):
        """Execute non-execution flow (validation, etc.) with Prefect tasks."""
        prefect_config = self.__get_prefect_config()
        task_retries = prefect_config["task_retries"]
        persist_result = prefect_config["persist_result"]
        main_task = self.__create_main_task(main_task=inner_task, retries=task_retries, persist_result=persist_result)
        results: FuturedList = FuturedList.from_size(len(op_flow))
        destinations: list[tuple[PrefectFuture, Any]] = []
        final_destination = None
        node_id_to_index_map = create_node_id_to_index_map(flow_def=op_flow)
        stop_submission = False
        submitted_futures: list[tuple[PrefectFuture, Any]] = []
        result = copy.copy(local_result)

        for op_def in op_flow:
            if stop_submission:
                continue
            index = node_id_to_index_map[op_def.get("id")]
            try:
                if op_def["input_edges"]:
                    link_name = op_def.get(OperatorConstants.Misc.LINK_NAME)
                    prev_futures = []
                    for edge in op_def["input_edges"]:
                        prev_index = node_id_to_index_map[edge["node_id_ref"]]
                        prev_future = results.get_future(prev_index)
                        prev_futures.append(prev_future)

                    if len(prev_futures) == 1:
                        prev_results = prev_futures[0]
                    else:
                        prev_results = prev_futures

                    future = main_task.submit(op_def[OperatorConstants.Columns.NAME], op_def, prev_results, link_name)

                else:
                    future = main_task.submit(op_def[OperatorConstants.Columns.NAME], op_def, result, None)
                submitted_futures.append((future, op_def))

                if not op_def.get(DocpipeConstants.OUTPUT_EDGES):
                    destinations.append((future, op_def))
                else:
                    results.set_entry(index, future, len(op_def.get(DocpipeConstants.OUTPUT_EDGES)))

                if kwargs.get("stop_node_id") == op_def.get(OperatorConstants.Columns.ID):
                    logger.info(
                        "Stop node reached: %s id:%s",
                        op_def.get(OperatorConstants.Columns.NAME),
                        op_def.get(OperatorConstants.Columns.ID),
                    )
                    logger.info(
                        "No more tasks will be submitted, waiting for current tasks: %s to complete",
                        len(submitted_futures),
                    )
                    stop_submission = True
                    final_destination = future

            except Exception as e:
                error = f"Branched flow task execution failed for {task_type.value} in non operator execution flow with error:{e!s}"
                logger.exception(error, stack_info=True)
                raise PrefectFlowFailed(message=error, error_code=ErrorCode.PREFECT_FLOW_TASK_FAILED) from e

        self.__wait_for_tasks_with_exceptions(destinations=submitted_futures, task_type=task_type)
        self.__wait_for_tasks_with_exceptions(destinations=destinations, task_type=task_type)
        if stop_submission:
            if final_destination is not None:
                local_result.update_final_result(final_destination.result())
            return Completed(
                message=f"Flow stopped after node but allowed {len(submitted_futures)} tasks to complete",
                name="EarlyStopped",
            )
        return None

    def __wait_for_tasks(self, *, destinations):
        """Wait for all tasks to complete."""
        futures = [item[0] for item in destinations]
        for future in futures:
            if hasattr(future, "wait"):
                future.wait()

    def __wait_for_tasks_with_exceptions(self, *, destinations, task_type: TaskType):
        """Wait for all tasks to complete and handle exceptions."""
        futures = [item[0] for item in destinations]
        try:
            for future in futures:
                future.result()
        except FlowValidationException as se:
            error = f"Branched flow task execution failed for {task_type.value} in non operator execution flow with error:{se!s}"
            logger.exception(error, stack_info=True)
            raise se
        except Exception as e:
            error = f"Branched flow task execution failed for {task_type.value} in non operator execution flow with error:{e!s}"
            logger.exception(error, stack_info=True)
            raise PrefectFlowFailed(message=error, error_code=ErrorCode.PREFECT_FLOW_TASK_FAILED) from e

    def _collect_failed_doc_ids(self, *, batch_id: str | None) -> list[str]:
        """Collect failed document IDs for the current batch only.

        Scopes the query to batch_id to avoid O(N²) growth — previously
        fetched aggregated node stats for the entire job on every batch.
        """
        job_stats_service = self.orchestrator.job_stats_service
        if not job_stats_service:
            logger.warning("Job stats service not available")
            return []

        if not batch_id:
            # Non-batched flow: fall back to full aggregated fetch (single call, no growth)
            job_stats = job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=True)
            if not job_stats or not job_stats.node_stats:
                return []
            failed_doc_ids: list[str] = []
            for node_stats in job_stats.node_stats.values():
                if hasattr(node_stats, "failed_docs") and node_stats.failed_docs:
                    failed_doc_ids.extend(node_stats.failed_docs)
                elif isinstance(node_stats, dict) and node_stats.get("failed_docs"):
                    failed_doc_ids.extend(node_stats["failed_docs"])
            return failed_doc_ids

        return job_stats_service.get_failed_doc_ids_for_batch(job_run_id=self.job_run_id, batch_id=batch_id)
