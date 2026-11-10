# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Infrastructure utilities for logging, configuration, performance, retry, caching, filesystem, concurrency, and telemetry."""

from .caching import LRUCache
from .concurrency import (
    process_batches_in_parallel,
    run_with_session_info,
    submit_task_with_context_propagation,
)
from .config import get_opensearch_config
from .config_utils import DocpipeConfigLoader
from .filesystem import delete_folders, get_data_path
from .logging import get_logger, setup_logging
from .performance import (
    get_process_memory_mb,
    get_pyarrow_table_size_mb,
    log_elapsed_time,
    reclaim_memory,
)
from .retry import retry_with_exponential_backoff, should_retry_on_result
from .telemetry_service import TelemetryConfig, get_telemetry_service

__all__ = [
    "DocpipeConfigLoader",
    "LRUCache",
    "TelemetryConfig",
    "delete_folders",
    "get_data_path",
    "get_logger",
    "get_opensearch_config",
    "get_process_memory_mb",
    "get_pyarrow_table_size_mb",
    "get_telemetry_service",
    "log_elapsed_time",
    "process_batches_in_parallel",
    "reclaim_memory",
    "retry_with_exponential_backoff",
    "run_with_session_info",
    "setup_logging",
    "should_retry_on_result",
    "submit_task_with_context_propagation",
]
