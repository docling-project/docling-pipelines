"""
Standalone Batch Subflow - Entry point for Prefect workers in distributed batch processing.

This module serves as the entry point that Prefect workers import and execute when processing
batches in distributed mode. It creates the necessary orchestrator context and delegates to
the existing PrefectEngine.__flow_impl() for execution, ensuring we reuse the same execution logic.

Architecture:
- This is a thin wrapper that workers execute
- Loads batch data from the configured storage (S3, local filesystem, or inline parameters)
- Creates minimal orchestrator context (PythonOrchestrator + PrefectEngine)
- Delegates to PrefectEngine.__flow_impl() to reuse existing execution logic
- No code duplication - single execution path for both local and distributed modes
"""

import base64

import pyarrow as pa
import pyarrow.parquet as pq
from prefect import flow

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
from docpipe.core.models.session_info import SessionInfo, set_session_info
from docpipe.core.orchestration.batch_manager import BatchManager
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


@flow(name="docpipe-batch-subflow", log_prints=True)
def batch_subflow(
    *, job_run_id: str, batch_id: str, batch_num: int, batch_transfer: dict, op_flow: list[dict], global_config: dict
):
    """
    Process a single batch of data through the operator flow.

    This flow is executed by Prefect workers in distributed mode. Each batch
    becomes a separate flow run with its own parameters.

    This is a thin wrapper that:
    1. Loads batch data from storage (S3, local, or inline)
    2. Creates orchestrator context (PythonOrchestrator + PrefectEngine)
    3. Delegates to PrefectEngine.execute_operator_flow() for execution

    Args:
        job_run_id: Unique identifier for the job run
        batch_id: Unique identifier for the batch (UUID)
        batch_num: Batch number (0-based index)
        batch_transfer: Batch transfer descriptor containing storage type and reference:
            - {"type": "s3", "ref": "s3://bucket/path/batch-0.parquet"}
            - {"type": "local", "ref": "/data/batches/job-123/batch-0.parquet"}
            - {"type": "inline", "data": {"columns": [...], "data": [...]}}
        op_flow: List of operator definitions to execute
        global_config: Global configuration dictionary

    Returns:
        None - Results are saved incrementally during execution
    """
    common_log_arguments = {
        DocpipeConstants.JOB_RUN_ID: job_run_id,
        DocpipeConstants.BATCH_ID: batch_id,
        DocpipeConstants.BATCH_NUM: batch_num,
    }

    storage_type = batch_transfer.get("type", "inline")

    logger.info(
        f"Starting batch subflow: batch_num={batch_num}, operators={len(op_flow)}, storage={storage_type}",
        extra=common_log_arguments,
    )

    try:
        # 1. Load batch data from storage
        batch_table = _load_batch(batch_transfer=batch_transfer, batch_num=batch_num)

        logger.info(
            f"Loaded batch: rows={len(batch_table)}, columns={batch_table.num_columns}", extra=common_log_arguments
        )

        # 2. Create DataAccess for the batch
        batch_data_access = BatchManager.create_batch_data_access(batch_table=batch_table)

        # 3. Update global config with batch-specific information
        batch_config = global_config.copy()
        batch_config[DocpipeConstants.BATCH_ID] = batch_id
        batch_config[DocpipeConstants.BATCH_NUM] = batch_num
        batch_config[DocpipeConstants.JOB_RUN_ID] = job_run_id

        # Extract job_id from config
        job_id = batch_config.get(DocpipeConstants.JOB_ID)

        # 4. Bootstrap worker-local job management dependencies from config/env
        job_management_factory = get_default_factory()
        job_stats_service = job_management_factory.create_job_stats_service()
        job_run_manager = job_management_factory.create_job_run_manager()

        # 5. Create minimal orchestrator context for execution
        # This provides the necessary infrastructure for PrefectEngine.
        # Reconstruct lineage observer from env vars so operator-level events
        # are emitted even when running inside a Prefect batch subflow worker.
        from docpipe.core.lineage.application import lineage_factory

        observer = lineage_factory.create_lineage_observer()
        orchestrator = PythonOrchestrator(
            job_stats_service=job_stats_service,
            job_run_manager=job_run_manager,
            observer=observer,
        )
        orchestrator.initialize(job_id=job_id, job_run_id=job_run_id)

        # Set context_id for incremental update functionality
        # This matches the behavior in AbstractOrchestrator.execute() (line 99)
        orchestrator.context_id = job_id
        # Restore flow_name so node-level lineage events use the human-readable name.
        # flow_name is nested under FLOW_DEFINITION (mirrors prefect_engine.py:280-283);
        # fall back to the top-level key for legacy / edge-case configs.
        flow_def = batch_config.get(DocpipeConstants.FLOW_DEFINITION, {})
        orchestrator.flow_name = (
            flow_def.get(DocpipeConstants.FLOW_NAME)
            or flow_def.get(DocpipeConstants.NAME)
            or batch_config.get(DocpipeConstants.FLOW_NAME, "")
        )

        # 6. Set session info for the worker
        session_info: SessionInfo = SessionInfo(
            orchestrator=orchestrator,
            job_id=job_id,
            job_run_id=job_run_id,
            flow_id=batch_config.get(DocpipeConstants.FLOW_ID, job_id),
            track_perf=batch_config.get(DocpipeConstants.TRACK_PERF, False),
        )
        set_session_info(session_info=session_info)

        # 7. Execute the operator flow using PrefectEngine.execute_operator_flow()
        # This reuses the existing execution logic - no code duplication
        if orchestrator.flow_engine is None:
            raise FlowExecutionFailedException("Failed to initialize PrefectEngine for batch subflow worker")

        orchestrator.flow_engine.execute_operator_flow(
            op_flow=op_flow, data_access=batch_data_access, global_config=batch_config
        )

        logger.info(f"Completed batch subflow: batch_num={batch_num}", extra=common_log_arguments)

    except Exception as e:
        logger.error(
            f"Batch subflow failed: batch_num={batch_num}, error={e!s}", extra=common_log_arguments, exc_info=True
        )
        raise FlowExecutionFailedException(f"Batch {batch_num} failed: {e!s}") from e


def _load_batch(*, batch_transfer: dict, batch_num: int) -> pa.Table:
    """
    Load batch data from the configured storage.

    Supports three storage types:
    - S3: Read Parquet file from S3 using PyArrow's S3 filesystem
    - Local: Read Parquet file from local/shared filesystem
    - Inline: Deserialize from JSON dict passed as parameter

    Args:
        batch_transfer: Transfer descriptor dict with type and ref/data
        batch_num: Batch number for error reporting

    Returns:
        PyArrow table with batch data

    Raises:
        FlowExecutionFailedException: If loading fails
    """
    storage_type = batch_transfer.get("type", "inline")

    try:
        if storage_type == "s3":
            bucket = batch_transfer["bucket"]
            key = batch_transfer["key"]
            s3_uri = batch_transfer.get("ref", f"s3://{bucket}/{key}")
            logger.info(f"Loading batch {batch_num} from S3: {s3_uri}")

            # Build S3FileSystem with credentials from transfer descriptor
            from pyarrow.fs import S3FileSystem

            fs_kwargs = {
                "access_key": batch_transfer["access_key"],
                "secret_key": batch_transfer["secret_key"],
            }
            if batch_transfer.get("region"):
                fs_kwargs["region"] = batch_transfer["region"]
            if batch_transfer.get("endpoint_url"):
                fs_kwargs["endpoint_override"] = batch_transfer["endpoint_url"]

            s3_fs = S3FileSystem(**fs_kwargs)
            return pq.read_table(f"{bucket}/{key}", filesystem=s3_fs)

        if storage_type == "local":
            ref = batch_transfer["ref"]
            logger.info(f"Loading batch {batch_num} from local: {ref}")
            return pq.read_table(ref)

        if storage_type == "inline":
            logger.info(f"Loading batch {batch_num} from inline parameters")
            return _deserialize_batch_data(batch_data=batch_transfer["data"])

        raise FlowExecutionFailedException(
            f"Unknown batch storage type: {storage_type}. Expected 's3', 'local', or 'inline'."
        )

    except FlowExecutionFailedException:
        raise
    except Exception as e:
        raise FlowExecutionFailedException(f"Failed to load batch {batch_num} from {storage_type}: {e!s}") from e


def _deserialize_batch_data(*, batch_data: dict) -> pa.Table:
    """
    Deserialize batch data from JSON-serializable dict back to PyArrow table.

    Args:
        batch_data: Dictionary containing serialized batch data
            Format: {"columns": [...], "data": [...], "schema": {...}, "binary_columns": [...]}

    Returns:
        PyArrow table
    """
    try:
        # Reconstruct PyArrow table from dict
        columns = batch_data["columns"]
        data = batch_data["data"]
        binary_columns = batch_data.get("binary_columns", [])

        # Decode base64-encoded binary columns back to bytes
        if binary_columns:
            for row in data:
                for col_name in binary_columns:
                    value = row.get(col_name)
                    if value is not None and isinstance(value, str):
                        # Decode base64 string back to bytes
                        row[col_name] = base64.b64decode(value)

        # Create arrays for each column
        arrays = []
        for col_name in columns:
            col_data = [row[col_name] for row in data]
            arrays.append(pa.array(col_data))

        # Create table
        return pa.Table.from_arrays(arrays, names=columns)

    except Exception as e:
        logger.error(f"Failed to deserialize batch data: {e!s}", exc_info=True)
        raise FlowExecutionFailedException(f"Batch data deserialization failed: {e!s}") from e
