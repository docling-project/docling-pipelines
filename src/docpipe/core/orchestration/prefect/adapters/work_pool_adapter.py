# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
WorkPoolAdapter - Distributed batch execution via Prefect work pools.

This adapter implements distributed execution by submitting batches to
Prefect deployments that are executed by remote workers.

Uses Prefect's native high-level APIs:
- run_deployment() for non-blocking flow run submission
- wait_for_flow_run() for efficient state monitoring (event-based, not polling)
- get_client(sync_client=True) for synchronous Prefect API calls

Supports configurable batch data transfer:
- S3: For cross-machine distributed execution (production)
- Local filesystem: For Docker Compose / single-machine setups
- Inline (parameters): For small batches (<512KB) without shared storage
"""

import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
from prefect import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterId
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import run_deployment
from prefect.states import Cancelling

from docpipe.core.constants import EnvironmentVariables
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.config.job_management_factory import JobManagementFactory
from docpipe.core.orchestration.batch_manager import BatchInfo
from docpipe.core.orchestration.prefect.config.work_pool_config import (
    DockerWorkPoolConfig,
    ProcessWorkPoolConfig,
    create_work_pool_config,
)
from docpipe.core.orchestration.prefect.domain.models import (
    BatchStorageType,
    BatchStrategyConstants,
    WorkPoolType,
)
from docpipe.core.orchestration.prefect.ports.batch_execution_port import BatchExecutionPort
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.core.memmap_file_utils import replace_memmap_paths_combined
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class WorkPoolAdapter(BatchExecutionPort):
    """
    Adapter: Distributed batch execution via Prefect work pools.

    This strategy submits batches to Prefect deployments which are executed
    by workers polling from work pools. Each batch runs on a potentially
    different worker machine.

    Architecture:
    - User's machine: Submits flow runs to Prefect Server
    - Prefect Server: Queues flow runs in work pool
    - Workers: Poll work pool, execute flow runs, report results

    Batch Data Transfer:
    - S3: Write to S3 bucket, pass URI as parameter (cross-machine)
    - Local: Write to shared filesystem, pass path as parameter (same machine)
    - Inline: Serialize to JSON in parameters (small data only, <512KB)

    Characteristics:
    - Non-blocking submission via run_deployment(timeout=0)
    - Efficient monitoring via wait_for_flow_run() (event-based in Prefect v3)
    - Fail-fast: First failure triggers cancellation of remaining batches
    - Network-dependent: Requires Prefect Server accessible

    Use Cases:
    - Production deployments with multiple workers
    - Large-scale data processing
    - When horizontal scalability is needed
    - Distributed team environments
    """

    def __init__(self, *, work_pool_config: dict[str, Any], prefect_engine, batch_manager):
        """
        Initialize work pool adapter.

        Args:
            work_pool_config: Configuration for work pool
                {
                    "type": "process|docker",
                    "work_pool_name": "docpipe-pool",
                    "deployment_name": "docpipe-batch-subflow",
                    "batch_storage": {
                        "type": "s3|local|inline",
                        "bucket": "my-bucket",          # S3 only
                        "prefix": "tmp/batches/",       # S3 only
                        "path": "/data/batches"          # local only
                    }
                }
            prefect_engine: PrefectEngine instance (for accessing flow building)
            batch_manager: BatchManager instance (for batch operations)

        Raises:
            ValueError: If required config parameters are missing
        """
        self.work_pool_config = work_pool_config
        self.prefect_engine = prefect_engine
        self.batch_manager = batch_manager

        # Extract configuration using constants
        self.work_pool_type = work_pool_config.get(BatchStrategyConstants.CONFIG_KEY_TYPE, WorkPoolType.PROCESS.value)
        self.work_pool_name = work_pool_config.get(BatchStrategyConstants.CONFIG_KEY_WORK_POOL_NAME)
        self.deployment_name = work_pool_config.get(
            BatchStrategyConstants.CONFIG_KEY_DEPLOYMENT_NAME, BatchStrategyConstants.DEFAULT_DEPLOYMENT_NAME
        )
        self.work_pool_runtime_config = create_work_pool_config(
            work_pool_type=self.work_pool_type,
            config_dict=work_pool_config,
        )

        # Batch storage configuration
        batch_storage_config = work_pool_config.get(BatchStrategyConstants.CONFIG_KEY_BATCH_STORAGE, {})
        self.batch_storage_type = BatchStorageType(
            batch_storage_config.get(
                BatchStrategyConstants.CONFIG_KEY_BATCH_STORAGE_TYPE, BatchStorageType.INLINE.value
            )
        )
        self.batch_storage_path = batch_storage_config.get(BatchStrategyConstants.CONFIG_KEY_BATCH_STORAGE_PATH)
        self.batch_storage_bucket = batch_storage_config.get(BatchStrategyConstants.CONFIG_KEY_BATCH_STORAGE_BUCKET)
        self.batch_storage_prefix = batch_storage_config.get(
            BatchStrategyConstants.CONFIG_KEY_BATCH_STORAGE_PREFIX, "tmp/batches/"
        )

        # S3 credentials (required when batch_storage.type is 's3')
        # Support both AWS standard names and shorter aliases
        self.s3_access_key = batch_storage_config.get("access_key_id") or batch_storage_config.get("access_key")
        self.s3_secret_key = batch_storage_config.get("secret_access_key") or batch_storage_config.get("secret_key")
        self.s3_endpoint_url = batch_storage_config.get("endpoint_url")
        self.s3_region = batch_storage_config.get("region")

        # Validate required parameters
        if not self.work_pool_name:
            raise ValueError(
                f"{BatchStrategyConstants.CONFIG_KEY_WORK_POOL_NAME} is required for WorkPool strategy. "
                f"Set in global_config.prefect.batch_execution.{BatchStrategyConstants.CONFIG_KEY_WORK_POOL_NAME}"
            )

        # Validate batch storage-specific requirements
        if self.batch_storage_type == BatchStorageType.LOCAL and not self.batch_storage_path:
            raise ValueError(
                "batch_storage.path is required when batch_storage.type is 'local'. "
                "Set the shared filesystem path accessible by both submitter and workers."
            )

        if self.batch_storage_type == BatchStorageType.S3:
            if not self.batch_storage_bucket:
                raise ValueError(
                    "batch_storage.bucket is required when batch_storage.type is 's3'. "
                    "Set the S3 bucket name accessible by both submitter and workers."
                )
            if not self.s3_access_key or not self.s3_secret_key:
                raise ValueError(
                    "S3 credentials are required when batch_storage.type is 's3'. "
                    "Provide either (access_key_id, secret_access_key) or (access_key, secret_key). "
                    "These credentials must have read/write access to the specified bucket."
                )

        # Validate Prefect Server connectivity
        self._validate_prefect_connection()

        # Ensure deployment exists in Prefect Server
        # This must happen after validation so we know the server is reachable
        self._ensure_deployment_exists()

    def execute_batches(
        self, *, batches: list[BatchInfo], op_flow: list[dict], global_config: dict, job_run_id: str
    ) -> None:
        """
        Execute batches using distributed work pool with semaphore-controlled concurrency.

        Process:
        1. Acquire semaphore slot (respecting max_concurrent_batches)
        2. Transfer batch data to storage (S3/local/inline)
        3. Submit batch as a flow run via run_deployment()
        4. Wait for completion via wait_for_flow_run()
        5. Release slot and repeat for remaining batches
        """
        self.prefect_engine.logger.info(
            "Executing %s batches using WorkPool strategy (pool=%s, type=%s, storage=%s)",
            len(batches),
            self.work_pool_name,
            self.work_pool_type,
            self.batch_storage_type.value,
            extra={"job_run_id": job_run_id},
        )

        from docpipe.core.constants.constants import DocpipeConstants

        continue_on_batch_failure = global_config.get(
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE_DEFAULT,
        )

        failed_info, completed_count = asyncio.run(
            self._execute_pipelined_batches_async(
                batches=batches,
                op_flow=op_flow,
                global_config=global_config,
                job_run_id=job_run_id,
                continue_on_batch_failure=continue_on_batch_failure,
            )
        )

        # Cleanup batch storage (best-effort)
        self._cleanup_batch_storage(job_run_id=job_run_id)

        orchestrator = self.prefect_engine.orchestrator

        # Raise when: fail-fast mode with any failure, or continue mode but ALL batches failed.
        # Only raise when FAILING — a partial continue-mode failure must not raise,
        # or the API path overwrites COMPLETED_WITH_ERRORS with FAILED.
        if failed_info and (not continue_on_batch_failure or len(failed_info) == len(batches)):
            orchestrator.job_status = ExecutionStatus.FAILING
            orchestrator.message = (
                f"Batch execution failed. Failed: {len(failed_info)}, "
                f"Completed: {completed_count}, Total: {len(batches)}"
            )
            self._raise_failure(failed_info=failed_info, completed_count=completed_count, total_count=len(batches))

        if failed_info:
            # Partial failure in continue mode — warn and return without raising.
            self.prefect_engine.logger.warning(
                "Partial batch failure: %s of %s batches failed: %s",
                len(failed_info),
                len(batches),
                [f["batch_num"] for f in failed_info],
                extra={"job_run_id": job_run_id},
            )
            return

        self.prefect_engine.logger.info("All batches completed successfully", extra={"job_run_id": job_run_id})

    async def _execute_pipelined_batches_async(
        self,
        *,
        batches: list[BatchInfo],
        op_flow: list[dict],
        global_config: dict,
        job_run_id: str,
        continue_on_batch_failure: bool,
    ) -> tuple[list[dict], int]:
        """
        Async implementation of pipelined batch execution.

        Returns (failed_info, completed_count). Never raises — execute_batches()
        decides whether to raise based on the returned outcome and the flag.
        """
        from docpipe.core.constants.constants import DocpipeConstants

        max_concurrent = global_config.get(DocpipeConstants.MAX_CONCURRENT_BATCHES, 10)
        semaphore = asyncio.Semaphore(max_concurrent)
        # Only 5 batches can be actively submitted at the exact same millisecond
        submission_semaphore = asyncio.Semaphore(5)

        self.prefect_engine.logger.info(
            "Using submission semaphore with %s slots", max_concurrent, extra={"job_run_id": job_run_id}
        )

        # One shared box for all batches — each task increments the same counter.
        completed_count_ref: list[int] = [0]
        failed_info: list[dict] = []
        submitted_runs: list[FlowRun] = []
        pending_runs: dict[str, asyncio.Future] = {}

        poller_task = asyncio.create_task(self._bulk_poll_runs(pending_runs=pending_runs, job_run_id=job_run_id))

        running_tasks = [
            asyncio.create_task(
                self._run_single_batch(
                    batch_info=b,
                    op_flow=op_flow,
                    global_config=global_config,
                    job_run_id=job_run_id,
                    semaphore=semaphore,
                    submission_semaphore=submission_semaphore,
                    pending_runs=pending_runs,
                    submitted_runs=submitted_runs,
                    failed_info=failed_info,
                    completed_count_ref=completed_count_ref,
                )
            )
            for b in batches
        ]

        try:
            for coro in asyncio.as_completed(running_tasks):
                await coro
                if failed_info and not continue_on_batch_failure:
                    # Fail-fast: first failure detected, stop monitoring
                    break
        finally:
            poller_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller_task

            # CRITICAL: If we break due to failure (or an exception occurs),
            # we must cancel ALL background tasks that haven't finished yet.
            # This prevents "ghost submissions" of remaining batches.
            # In continue mode nothing breaks early, so still_running is empty.
            still_running = [t for t in running_tasks if not t.done()]
            if still_running:
                self.prefect_engine.logger.warning(
                    "Cancelling %s background submission tasks", len(still_running), extra={"job_run_id": job_run_id}
                )
                for t in still_running:
                    t.cancel()
                await asyncio.gather(*still_running, return_exceptions=True)

        # Only fail-fast cancels remote runs. In continue mode every batch is
        # allowed to finish, so cancellation would be counterproductive.
        if failed_info and not continue_on_batch_failure:
            await self._cancel_remaining_runs_async(flow_runs=submitted_runs, job_run_id=job_run_id)

        return failed_info, completed_count_ref[0]

    @staticmethod
    def _resolve_finished_runs(*, flow_runs: list[FlowRun], pending_runs: dict[str, asyncio.Future]) -> None:
        """Hand each finished flow run to the batch task still waiting on it."""
        for fr in flow_runs:
            if not (fr.state and fr.state.is_final()):
                continue
            future = pending_runs.get(str(fr.id))
            if future is not None and not future.done():
                future.set_result(fr)

    async def _bulk_poll_runs(self, *, pending_runs: dict[str, asyncio.Future], job_run_id: str) -> None:
        """Centralized bulk poller: resolves futures for completed Prefect flow runs."""
        async with get_client() as client:
            while True:
                await asyncio.sleep(5)
                if not pending_runs:
                    continue
                ids_to_check = list(pending_runs.keys())
                try:
                    flow_runs = await client.read_flow_runs(
                        flow_run_filter=FlowRunFilter(id=FlowRunFilterId(any_=[UUID(i) for i in ids_to_check]))
                    )
                    self._resolve_finished_runs(flow_runs=flow_runs, pending_runs=pending_runs)
                except Exception as e:
                    self.prefect_engine.logger.warning(
                        "Bulk poller encountered an error: %s", e, extra={"job_run_id": job_run_id}
                    )

    async def _run_single_batch(
        self,
        *,
        batch_info: BatchInfo,
        op_flow: list[dict],
        global_config: dict,
        job_run_id: str,
        semaphore: asyncio.Semaphore,
        submission_semaphore: asyncio.Semaphore,
        pending_runs: dict[str, asyncio.Future],
        submitted_runs: list[FlowRun],
        failed_info: list[dict],
        completed_count_ref: list[int],
    ) -> None:
        """Submit, wait, and classify a single batch flow run."""
        from docpipe.core.constants.constants import DocpipeConstants

        async with semaphore:
            try:
                batch_transfer = self._transfer_batch(
                    batch_table=batch_info.table, batch_num=batch_info.batch_num, job_run_id=job_run_id
                )
                flow_run_id = await self._submit_batch_flow_run(
                    batch_info=batch_info,
                    batch_transfer=batch_transfer,
                    op_flow=op_flow,
                    global_config=global_config,
                    job_run_id=job_run_id,
                    submission_semaphore=submission_semaphore,
                    submitted_runs=submitted_runs,
                    docpipe_constants=DocpipeConstants,
                )
                final_flow_run = await self._wait_for_batch_completion(
                    flow_run_id=flow_run_id,
                    batch_num=batch_info.batch_num,
                    pending_runs=pending_runs,
                    job_run_id=job_run_id,
                )
                self._classify_batch_result(
                    batch_info=batch_info,
                    final_flow_run=final_flow_run,
                    flow_run_id=flow_run_id,
                    job_run_id=job_run_id,
                    failed_info=failed_info,
                    completed_count_ref=completed_count_ref,
                )
            except Exception as e:
                failed_info.append({"batch_num": batch_info.batch_num, "run_id": "N/A", "message": str(e)})
                self.prefect_engine.logger.exception(
                    "Exception in batch %s: %s",
                    batch_info.batch_num,
                    e,
                    extra={"job_run_id": job_run_id},
                )

    async def _submit_batch_flow_run(
        self,
        *,
        batch_info: BatchInfo,
        batch_transfer: dict[str, Any],
        op_flow: list[dict],
        global_config: dict,
        job_run_id: str,
        submission_semaphore: asyncio.Semaphore,
        submitted_runs: list[FlowRun],
        docpipe_constants: Any,
    ) -> str:
        """Submit a single batch flow run to Prefect and return its run ID."""
        deployment_full_name = f"{BatchStrategyConstants.BATCH_SUBFLOW_NAME}/{self.deployment_name}"
        flow_def = global_config.get(docpipe_constants.FLOW_DEFINITION, {})
        flow_name = flow_def.get(docpipe_constants.FLOW_NAME) or flow_def.get(docpipe_constants.NAME, "docpipe_flow")
        run_name = f"{flow_name}_batch_{batch_info.batch_num}"

        async with submission_semaphore:
            flow_run_result = await run_deployment(  # type: ignore[misc]
                name=deployment_full_name,
                parameters={
                    "batch_id": batch_info.batch_id,
                    "batch_num": batch_info.batch_num,
                    "batch_transfer": batch_transfer,
                    "op_flow": op_flow,
                    "global_config": global_config,
                    "job_run_id": job_run_id,
                },
                flow_run_name=run_name,
                timeout=0,
                as_subflow=False,
            )

            if not flow_run_result or not isinstance(flow_run_result, FlowRun):
                raise FlowExecutionFailedException(f"Failed to submit batch {batch_info.batch_num}")

            submitted_runs.append(flow_run_result)
            flow_run_id = str(flow_run_result.id)
            self.prefect_engine.logger.info(
                "Batch %s submitted: flow_run_id=%s",
                batch_info.batch_num,
                flow_run_id,
                extra={"job_run_id": job_run_id},
            )
            return flow_run_id

    async def _wait_for_batch_completion(
        self,
        *,
        flow_run_id: str,
        batch_num: int,
        pending_runs: dict[str, asyncio.Future],
        job_run_id: str,
    ) -> Any:
        """Register a future for the batch and wait for the bulk poller to resolve it."""
        loop = asyncio.get_running_loop()
        completion_future = loop.create_future()
        pending_runs[flow_run_id] = completion_future
        try:
            return await asyncio.wait_for(completion_future, timeout=10800)
        except TimeoutError as e:
            raise FlowExecutionFailedException(f"Batch {batch_num} timed out after 3 hours.") from e
        finally:
            pending_runs.pop(flow_run_id, None)

    def _classify_batch_result(
        self,
        *,
        batch_info: BatchInfo,
        final_flow_run: Any,
        flow_run_id: str,
        job_run_id: str,
        failed_info: list[dict],
        completed_count_ref: list[int],
    ) -> None:
        """Inspect the final flow run state and update completed/failed bookkeeping."""
        if not final_flow_run:
            return
        state = final_flow_run.state
        if not state:
            # A run that finished without a state is a failure, not a no-op.
            # Dropping it here would let the job report success with a batch missing.
            self.prefect_engine.logger.error(
                "Batch %s NOT completed — no state on flow run",
                batch_info.batch_num,
                extra={"job_run_id": job_run_id},
            )
            failed_info.append(
                {
                    "batch_num": batch_info.batch_num,
                    "run_id": flow_run_id,
                    "message": "state_type=N/A, name=N/A, msg=Unknown state",
                }
            )
            return
        if state.is_completed() or str(state.name).lower() == "completed":
            completed_count_ref[0] += 1
            self.prefect_engine.logger.info(
                "Batch %s completed successfully", batch_info.batch_num, extra={"job_run_id": job_run_id}
            )
        else:
            state_type_str = getattr(getattr(state, "type", None), "value", "N/A")
            state_name_str = getattr(state, "name", "N/A")
            state_msg = state.message
            self.prefect_engine.logger.error(
                "Batch %s NOT completed — state_type=%s, state_name=%s, message=%s",
                batch_info.batch_num,
                state_type_str,
                state_name_str,
                state_msg,
                extra={"job_run_id": job_run_id},
            )
            failed_info.append(
                {
                    "batch_num": batch_info.batch_num,
                    "run_id": flow_run_id,
                    "message": f"state_type={state_type_str}, name={state_name_str}, msg={state_msg}",
                }
            )

    # ─── Batch Data Transfer ────────────────────────────────────────────

    def _transfer_batch(self, *, batch_table: pa.Table, batch_num: int, job_run_id: str) -> dict[str, Any]:
        """
        Transfer batch data to storage for worker access.

        Returns a transfer descriptor dict that tells the worker how and
        where to load the batch data.

        Args:
            batch_table: PyArrow table to transfer
            batch_num: Batch number for identification
            job_run_id: Job run ID for path namespacing

        Returns:
            Dict describing the transfer:
            - {"type": "s3", "ref": "s3://bucket/path/batch-0.parquet"}
            - {"type": "local", "ref": "/data/batches/job-123/batch-0.parquet"}
            - {"type": "inline", "data": {...}}
        """
        if self.batch_storage_type == BatchStorageType.S3:
            return self._transfer_batch_s3(batch_table=batch_table, batch_num=batch_num, job_run_id=job_run_id)
        if self.batch_storage_type == BatchStorageType.LOCAL:
            return self._transfer_batch_local(batch_table=batch_table, batch_num=batch_num, job_run_id=job_run_id)
        return self._transfer_batch_inline(batch_table=batch_table, batch_num=batch_num, job_run_id=job_run_id)

    def _create_s3_filesystem(self):
        """
        Create a PyArrow S3FileSystem with explicit credentials.

        Uses the same credential pattern as docpipe's S3SourceAdapter
        (access_key, secret_key, endpoint_url, region).

        Returns:
            pyarrow.fs.S3FileSystem configured with credentials
        """
        from pyarrow.fs import S3FileSystem

        fs_kwargs = {
            "access_key": self.s3_access_key,
            "secret_key": self.s3_secret_key,
        }

        if self.s3_region:
            fs_kwargs["region"] = self.s3_region

        if self.s3_endpoint_url:
            # For S3-compatible storage (MinIO, IBM COS, etc.)
            fs_kwargs["endpoint_override"] = self.s3_endpoint_url

        return S3FileSystem(**fs_kwargs)

    def _transfer_batch_s3(self, *, batch_table: pa.Table, batch_num: int, job_run_id: str) -> dict[str, Any]:
        """Write batch to S3 using PyArrow S3FileSystem with explicit credentials."""
        s3_key = f"{self.batch_storage_prefix}{job_run_id}/batch-{batch_num}.parquet"
        s3_uri = f"s3://{self.batch_storage_bucket}/{s3_key}"

        try:
            s3_fs = self._create_s3_filesystem()

            # Replace memmap paths with actual data before writing to S3
            batch_table = replace_memmap_paths_combined(table=batch_table)

            # Write using the authenticated filesystem
            pq.write_table(batch_table, f"{self.batch_storage_bucket}/{s3_key}", filesystem=s3_fs)

            self.prefect_engine.logger.info(
                "Batch %s: written to S3 (%s rows) -> %s",
                batch_num,
                len(batch_table),
                s3_uri,
                extra={"job_run_id": job_run_id},
            )

            # Return credentials in transfer descriptor so workers can read
            return {
                "type": BatchStorageType.S3.value,
                "ref": s3_uri,
                "bucket": self.batch_storage_bucket,
                "key": s3_key,
                "access_key": self.s3_access_key,
                "secret_key": self.s3_secret_key,
                "endpoint_url": self.s3_endpoint_url,
                "region": self.s3_region,
            }
        except Exception as e:
            raise FlowExecutionFailedException(f"Failed to write batch {batch_num} to S3 ({s3_uri}): {e}") from e

    def _transfer_batch_local(self, *, batch_table: pa.Table, batch_num: int, job_run_id: str) -> dict[str, Any]:
        """Write batch to local shared filesystem and return path."""
        batch_dir = Path(self.batch_storage_path) / job_run_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        local_path = str(batch_dir / f"batch-{batch_num}.parquet")

        try:
            # Replace memmap paths with actual data before writing to local storage
            batch_table = replace_memmap_paths_combined(table=batch_table)

            pq.write_table(batch_table, local_path)

            self.prefect_engine.logger.info(
                "Batch %s: written to local (%s rows) -> %s",
                batch_num,
                len(batch_table),
                local_path,
                extra={"job_run_id": job_run_id},
            )

            return {"type": BatchStorageType.LOCAL.value, "ref": local_path}
        except Exception as e:
            raise FlowExecutionFailedException(
                f"Failed to write batch {batch_num} to local path ({local_path}): {e}"
            ) from e

    def _transfer_batch_inline(self, *, batch_table: pa.Table, batch_num: int, job_run_id: str) -> dict[str, Any]:
        """Serialize batch to JSON dict for passing as Prefect parameter."""
        # Detect binary columns (binary or large_binary types)
        binary_columns = [
            col_name
            for col_name in batch_table.column_names
            if pa.types.is_binary(batch_table.schema.field(col_name).type)
            or pa.types.is_large_binary(batch_table.schema.field(col_name).type)
        ]

        # Convert table to list of dicts
        data = batch_table.to_pylist()

        # Base64-encode binary columns for JSON serialization
        if binary_columns:
            for row in data:
                for col_name in binary_columns:
                    value = row.get(col_name)
                    if value is not None and isinstance(value, bytes):
                        # Encode bytes to base64 string
                        row[col_name] = base64.b64encode(value).decode("utf-8")

        batch_dict = {
            "columns": batch_table.column_names,
            "data": data,
            "schema": {col: str(batch_table.schema.field(col).type) for col in batch_table.column_names},
            "row_count": len(batch_table),
            "binary_columns": binary_columns,
        }

        # Check size and warn/error if too large
        size_bytes = len(json.dumps(batch_dict).encode("utf-8"))
        size_limit = BatchStrategyConstants.get_inline_size_limit()
        warning_threshold = int(size_limit * BatchStrategyConstants.INLINE_SIZE_WARNING_THRESHOLD)

        self.prefect_engine.logger.info(
            "Batch %s: serialized inline (%s rows, %s bytes)",
            batch_num,
            len(batch_table),
            size_bytes,
            extra={"job_run_id": job_run_id, "size_bytes": size_bytes},
        )

        if size_bytes > size_limit:
            raise FlowExecutionFailedException(
                f"Batch {batch_num} is {size_bytes:,} bytes, exceeding Prefect's "
                f"parameter limit (PREFECT_SERVER_API_MAX_PARAMETER_SIZE={size_limit:,} bytes). "
                f"Options:\n"
                f"1. Configure batch_storage with type 's3' or 'local' for larger batches:\n"
                f'   "batch_storage": {{"type": "s3", "bucket": "my-bucket"}}\n'
                f"2. Increase the limit by setting PREFECT_SERVER_API_MAX_PARAMETER_SIZE environment variable on Prefect Server:\n"
                f"   export PREFECT_SERVER_API_MAX_PARAMETER_SIZE=2097152  # 2MB\n"
                f"3. Disable the limit entirely (not recommended):\n"
                f"   export PREFECT_SERVER_API_MAX_PARAMETER_SIZE=0"
            )
        if size_bytes > warning_threshold:
            self.prefect_engine.logger.warning(
                "Batch %s: size %s bytes approaching Prefect parameter limit (%s bytes, controlled by "
                "PREFECT_SERVER_API_MAX_PARAMETER_SIZE). Consider configuring batch_storage.type='s3' or "
                "'local' for better performance, or increase PREFECT_SERVER_API_MAX_PARAMETER_SIZE on Prefect Server.",
                batch_num,
                size_bytes,
                size_limit,
                extra={"job_run_id": job_run_id},
            )

        return {"type": BatchStorageType.INLINE.value, "data": batch_dict}

    # ─── Flow Run Cancellation ──────────────────────────────────────────

    async def _cancel_single_run(self, *, client: Any, flow_run: FlowRun, job_run_id: str) -> Any | None:
        """Cancel a single flow run if it is not already in a terminal state.

        Returns the flow_run.id when a Cancelling request was sent, otherwise None.
        """
        try:
            current_run = await client.read_flow_run(flow_run.id)
            if current_run.state and current_run.state.is_final():
                return None
            await client.set_flow_run_state(
                flow_run_id=flow_run.id,
                state=Cancelling(message="Cancelled due to batch failure (fail-fast)"),
            )
            self.prefect_engine.logger.info("Cancelled flow_run=%s", flow_run.id, extra={"job_run_id": job_run_id})
            return flow_run.id
        except Exception as e:
            self.prefect_engine.logger.warning(
                "Failed to cancel flow_run=%s: %s",
                flow_run.id,
                e,
                extra={"job_run_id": job_run_id},
            )
            return None

    async def _wait_for_pending_termination(self, *, client: Any, pending_runs: list, job_run_id: str) -> None:
        """Poll until all pending-cancellation runs reach a terminal state or 60 s elapse."""
        from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterId

        self.prefect_engine.logger.info(
            "Waiting for %s flow runs to reach terminal state...",
            len(pending_runs),
            extra={"job_run_id": job_run_id},
        )
        start_wait = asyncio.get_event_loop().time()
        while pending_runs:
            if asyncio.get_event_loop().time() - start_wait > 60:
                self.prefect_engine.logger.warning(
                    "Timeout waiting for %s flow runs to terminate",
                    len(pending_runs),
                    extra={"job_run_id": job_run_id},
                )
                break
            await asyncio.sleep(2.0)
            try:
                runs = await client.read_flow_runs(flow_run_filter=FlowRunFilter(id=FlowRunFilterId(any_=pending_runs)))
                pending_runs[:] = [run.id for run in runs if run.state and not run.state.is_final()]
            except Exception as e:
                self.prefect_engine.logger.warning(
                    "Error while polling cancelled runs: %s", e, extra={"job_run_id": job_run_id}
                )

    async def _cancel_remaining_runs_async(self, *, flow_runs: list[FlowRun], job_run_id: str) -> None:
        """
        Cancel all flow runs (async version for use within async context).
        Waits for runs to reach a terminal state to prevent late updates from workers.

        Args:
            flow_runs: List of flow runs to cancel
            job_run_id: Parent job run ID for logging context
        """
        async with get_client() as client:
            pending_runs = []
            for flow_run in flow_runs:
                run_id = await self._cancel_single_run(client=client, flow_run=flow_run, job_run_id=job_run_id)
                if run_id is not None:
                    pending_runs.append(run_id)

            if pending_runs:
                await self._wait_for_pending_termination(
                    client=client, pending_runs=pending_runs, job_run_id=job_run_id
                )

    def _cancel_remaining_runs(self, *, flow_runs: list[FlowRun], failed_run_id: str, job_run_id: str) -> None:
        """
        Cancel remaining pending flow runs after a failure (sync version).

        Uses the synchronous Prefect client to avoid asyncio.run() conflicts
        inside Prefect's already-running event loop.

        Args:
            flow_runs: List of FlowRun objects to cancel
            failed_run_id: ID of the flow run that triggered cancellation
            job_run_id: Parent job run ID for logging context
        """
        self.prefect_engine.logger.warning(
            "Triggering fail-fast cancellation for %s remaining flow runs",
            len(flow_runs),
            extra={"job_run_id": job_run_id},
        )

        # Use sync client — safe inside Prefect context (no asyncio.run needed)
        with get_client(sync_client=True) as client:
            for fr in flow_runs:
                try:
                    client.set_flow_run_state(
                        flow_run_id=fr.id,
                        state=Cancelling(message=f"Cancelled due to failure in flow run {failed_run_id}"),
                        force=True,
                    )
                    self.prefect_engine.logger.info("Cancelled flow run %s", fr.id, extra={"job_run_id": job_run_id})
                except Exception as cancel_error:
                    self.prefect_engine.logger.warning(
                        "Could not cancel flow run %s: %s", fr.id, cancel_error, extra={"job_run_id": job_run_id}
                    )

    @staticmethod
    def _raise_failure(*, failed_info: list[dict], completed_count: int, total_count: int) -> None:
        """Raise FlowExecutionFailedException with failure details."""
        error_details = "\n".join(
            [f"  - Batch {f['batch_num']} (flow_run={f['run_id']}): {f['message']}" for f in failed_info]
        )

        raise FlowExecutionFailedException(
            f"Batch execution failed. "
            f"Failed: {len(failed_info)}, "
            f"Completed: {completed_count}, "
            f"Total: {total_count}\n"
            f"Failure details:\n{error_details}"
        )

    # ─── Prefect Connectivity ───────────────────────────────────────────

    def _validate_prefect_connection(self) -> None:
        """
        Validate that Prefect Server is accessible.

        Uses the sync client to perform a health check.

        Raises:
            ValueError: If Prefect Server is not accessible
        """
        try:
            with get_client(sync_client=True) as client:
                health_error = client.api_healthcheck()
                if health_error:
                    raise ValueError(
                        f"Prefect Server health check failed: {health_error}. "
                        f"Ensure Prefect Server is running and PREFECT_API_URL is set correctly."
                    )

            self.prefect_engine.logger.info(
                "Prefect Server connection verified (pool=%s, deployment=%s)",
                self.work_pool_name,
                self.deployment_name,
            )
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                f"Cannot connect to Prefect Server: {e}. "
                f"Ensure Prefect Server is running and PREFECT_API_URL is set correctly. "
                f"For local setup, run: docker-compose -f docker/docker-compose.distributed.yml up -d"
            ) from e

    @staticmethod
    def _resolve_job_management_config_path() -> Path:
        config_path = os.getenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH)
        if config_path:
            return Path(config_path).resolve()
        return Path(__file__).resolve().parents[5] / "docling-pipelines-config.yaml"

    def _get_effective_job_management_env(self) -> dict[str, str]:
        """Resolve effective submitter-side job-management environment for worker propagation."""
        resolved_env: dict[str, str] = {}
        config_path = self._resolve_job_management_config_path()

        if config_path.exists():
            resolved_env[EnvironmentVariables.DOCPIPE_CONFIG_PATH] = str(config_path)

        # Delegate to JobManagementFactory for resolving job management environment
        try:
            factory = JobManagementFactory.create_default_factory()
            job_management_env = factory.resolve_worker_env()
            resolved_env.update(job_management_env)
        except Exception as exc:
            logger.warning("Failed to resolve job management environment for work pool propagation: %s", exc)

        return resolved_env

    def _build_container_env(self, *, base_env: dict[str, str], deployment_path: str | None) -> dict[str, str]:
        """Build container environment with required defaults."""
        env = base_env.copy()
        self._apply_env_defaults(env=env, deployment_path=deployment_path)
        for key, value in self._get_effective_job_management_env().items():
            if key not in env:
                env[key] = value
        return env

    def _apply_env_defaults(self, *, env: dict[str, str], deployment_path: str | None) -> None:
        """Fill in missing runtime environment defaults for container/process workers."""
        defaults: dict[str, str] = {
            EnvironmentVariables.PREFECT_API_URL: os.getenv(
                EnvironmentVariables.PREFECT_API_URL, "http://prefect-server:4200/api"
            ),
            EnvironmentVariables.PREFECT_MODE: "server",
            EnvironmentVariables.PYTHONPATH: deployment_path or str(Path.cwd()),
            EnvironmentVariables.OLLAMA_HOST: os.getenv(EnvironmentVariables.OLLAMA_HOST, "http://localhost:11434"),
            EnvironmentVariables.PREFECT_LOGGING_EXTRA_LOGGERS: os.getenv(
                EnvironmentVariables.PREFECT_LOGGING_EXTRA_LOGGERS, "DOCPIPE"
            ),
        }
        for key, value in defaults.items():
            if key not in env:
                env[key] = value

    def _build_job_variables(self) -> dict[str, Any] | None:
        """Build deployment job variables from typed work pool config."""
        config = self.work_pool_runtime_config

        if isinstance(config, DockerWorkPoolConfig):
            job_vars: dict[str, Any] = {
                "image": config.image,
                "image_pull_policy": config.image_pull_policy,
                "env": self._build_container_env(
                    base_env=config.env,
                    deployment_path=config.deployment_path,
                ),
            }
            if config.networks:
                job_vars["networks"] = config.networks
            return job_vars

        if isinstance(config, ProcessWorkPoolConfig):
            # Process workers need environment variables passed via job_variables.
            # Start with config-provided env, then fill runtime defaults/overrides.
            return {
                "env": self._build_container_env(
                    base_env=config.env,
                    deployment_path=config.deployment_path,
                )
            }

        return None

    def _ensure_deployment_exists(self) -> None:
        """
        Ensure the batch subflow deployment exists in Prefect Server.

        Uses batch_subflow.deploy() — Prefect's recommended high-level API.
        This is idempotent: calling deploy() with the same name creates the
        deployment if it doesn't exist, or updates it if it does.

        For process work pools:
            No Docker image needed — workers use the local Python environment.

        For docker work pools:
            Users provide their image via work_pool_config["image"].
            The image must have docpipe and all dependencies installed.

        This is called once during __init__, not per-batch.
        """
        from prefect import get_client

        from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow

        self.prefect_engine.logger.info(
            "Ensuring deployment exists: %s (work_pool=%s, type=%s)",
            self.deployment_name,
            self.work_pool_name,
            self.work_pool_type,
        )

        try:
            client = get_client(sync_client=True)
            if self._deployment_already_exists(client=client, flow_name=batch_subflow.name):
                return

            flow_obj = self._register_flow_if_needed(client=client, batch_subflow=batch_subflow)
            deployment_params = self._build_deployment_params(flow_id=flow_obj.id)

            deployment_id = client.create_deployment(**deployment_params)
            self.prefect_engine.logger.info("Deployment created: %s (id=%s)", self.deployment_name, deployment_id)
        except Exception as e:
            raise RuntimeError(self._deployment_failure_message(error=e)) from e

    def _deployment_already_exists(self, *, client: Any, flow_name: str) -> bool:
        """Return True if the deployment is already registered in Prefect Server."""
        try:
            existing = client.read_deployment_by_name(f"{flow_name}/{self.deployment_name}")
        except Exception:
            self.prefect_engine.logger.info("Deployment not found, will create: %s", self.deployment_name)
            return False
        self.prefect_engine.logger.info("Deployment exists: %s (id=%s)", self.deployment_name, existing.id)
        return True

    def _register_flow_if_needed(self, *, client: Any, batch_subflow: Any) -> Any:
        """Return the registered flow object, registering the flow first if needed."""
        try:
            flow_obj = client.read_flow_by_name(batch_subflow.name)
            self.prefect_engine.logger.info("Flow already registered: %s (id=%s)", batch_subflow.name, flow_obj.id)
            return flow_obj
        except Exception:
            self.prefect_engine.logger.info("Registering flow: %s", batch_subflow.name)
            flow_id = client.create_flow(batch_subflow)
            self.prefect_engine.logger.info("Flow registered: %s (id=%s)", batch_subflow.name, flow_id)
            # Read the flow object back for deployment creation
            return client.read_flow_by_name(batch_subflow.name)

    def _build_deployment_params(self, *, flow_id: Any) -> dict[str, Any]:
        """Assemble the create_deployment payload for this work pool."""
        is_process = isinstance(self.work_pool_runtime_config, ProcessWorkPoolConfig)

        # The entrypoint tells workers where to find the flow code.
        entrypoint = (
            "docpipe.core.orchestration.prefect.batch_subflow:batch_subflow"
            if is_process
            else "docpipe/core/orchestration/prefect/batch_subflow.py:batch_subflow"
        )

        params: dict[str, Any] = {
            "flow_id": flow_id,
            "name": self.deployment_name,
            "work_pool_name": self.work_pool_name,
            "entrypoint": entrypoint,
            **self._build_deployment_code_location(is_process=is_process),
        }

        job_vars = self._build_job_variables()
        if job_vars:
            params["job_variables"] = job_vars

        self._log_docker_work_pool_config()
        return params

    def _build_deployment_code_location(self, *, is_process: bool) -> dict[str, Any]:
        """
        Work out where the flow code lives on the WORKER's filesystem.

        Two scenarios for process workers:
        1. Local dev: submitter and worker share a filesystem → Path.cwd() is right.
        2. Docker compose: the worker container holds the code at a different path
           (e.g. /app/src/docpipe_app/backend) → the user sets deployment_path.

        Container workers fall back to the path pre-baked into the image.
        """
        configured_path = self.work_pool_runtime_config.deployment_path

        if is_process:
            worker_code_dir = configured_path or str(Path.cwd())
            self.prefect_engine.logger.info(
                "Process work pool: worker code directory = %s (source=%s)",
                worker_code_dir,
                "config" if configured_path else "Path.cwd()",
            )
            return {
                "path": worker_code_dir,
                "pull_steps": [{"prefect.deployments.steps.set_working_directory": {"directory": worker_code_dir}}],
            }

        deployment_path = configured_path or BatchStrategyConstants.DEFAULT_DEPLOYMENT_PATH
        self.prefect_engine.logger.info(
            "Container work pool: deployment path = %s (source=%s)",
            deployment_path,
            "config" if configured_path else "default",
        )
        return {"path": deployment_path, "pull_steps": []}

    def _log_docker_work_pool_config(self) -> None:
        """Log the resolved Docker work pool settings, if this is a Docker pool."""
        if not isinstance(self.work_pool_runtime_config, DockerWorkPoolConfig):
            return
        docker_job_vars = self._build_job_variables() or {}
        self.prefect_engine.logger.info(
            "Configured Docker work pool with image: %s, networks: %s, env vars: %s",
            self.work_pool_runtime_config.image,
            self.work_pool_runtime_config.networks,
            len(docker_job_vars.get("env", {})),
        )

    def _deployment_failure_message(self, *, error: Exception) -> str:
        """Build the deployment failure message, with manual-recovery instructions."""
        return (
            f"Failed to create deployment '{self.deployment_name}': {error}\n\n"
            f"Possible causes:\n"
            f"1. Work pool '{self.work_pool_name}' doesn't exist\n"
            f"2. Network/connectivity issues with Prefect Server\n"
            f"3. Flow registration failed\n\n"
            f"To create manually:\n"
            f"  docker exec -it $(docker ps -q -f name=prefect-worker | head -1) bash\n"
            f'  python -c "from docpipe.core.orchestration.prefect.batch_subflow import batch_subflow; '
            f"batch_subflow.deploy(name='{self.deployment_name}', work_pool_name='{self.work_pool_name}', build=False, push=False)\"\n"
        )

    # ─── Cleanup ────────────────────────────────────────────────────────

    def _cleanup_batch_storage(self, *, job_run_id: str) -> None:
        """
        Clean up temporary batch data from storage after all batches complete.

        Best-effort cleanup — failures are logged but don't raise exceptions.

        Args:
            job_run_id: Job run ID for path namespacing
        """
        if self.batch_storage_type == BatchStorageType.LOCAL:
            try:
                import shutil

                batch_dir = Path(self.batch_storage_path) / job_run_id
                if batch_dir.exists():
                    shutil.rmtree(batch_dir)
                    self.prefect_engine.logger.info(
                        "Cleaned up batch storage: %s", batch_dir, extra={"job_run_id": job_run_id}
                    )
            except Exception as e:
                self.prefect_engine.logger.warning(
                    "Could not clean up batch storage: %s", e, extra={"job_run_id": job_run_id}
                )

        elif self.batch_storage_type == BatchStorageType.S3:
            # S3 cleanup is more complex and should be done via lifecycle policies
            # or a separate cleanup process. Log a note for now.
            self.prefect_engine.logger.info(
                "S3 batch data at s3://%s/%s%s/ can be cleaned up via S3 lifecycle policies.",
                self.batch_storage_bucket,
                self.batch_storage_prefix,
                job_run_id,
                extra={"job_run_id": job_run_id},
            )

    # ─── Strategy Info ──────────────────────────────────────────────────

    def get_strategy_name(self) -> str:
        """Return strategy name for logging."""
        return f"work-pool-{self.work_pool_type}"
