# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Global Configuration Metadata

This module defines metadata for all global configuration parameters that can be
set in docpipe flow definitions. These parameters control flow-level behavior
and are specified in the `global_config` section of flow JSON files.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from docpipe.core.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants

EXECUTION_CONTROL = "Execution Control"
INCREMENTAL_PROCESSING = "Incremental Processing"
ORCHESTRATION = "Orchestration configuration"


@dataclass
class GlobalConfigParam:
    """Metadata for a single global configuration parameter."""

    name: str
    type: str
    required: bool
    description: str
    category: str
    default: Any = None


class GlobalConfigMetadata:
    # All global config parameters organized by category
    """Globalconfigmetadata."""

    _PARAMETERS: ClassVar[dict[str, GlobalConfigParam]] = {
        # Incremental Processing
        DocpipeConstants.FORCE_INGEST: GlobalConfigParam(
            name="Disable incremental processing",
            type="bool",
            default=False,
            required=False,
            description="Forces re-ingestion of all documents, even if they were previously processed. Useful for reprocessing data after operator configuration changes.",
            category=INCREMENTAL_PROCESSING,
        ),
        DocpipeConstants.RETAIN_DELETED_DOCS: GlobalConfigParam(
            name="Retain deleted documents",
            type="bool",
            default=True,
            required=False,
            description="Controls whether documents deleted from the source should be retained in the output or removed.",
            category=INCREMENTAL_PROCESSING,
        ),
        DocpipeConstants.DISABLE_VALIDATION: GlobalConfigParam(
            name="Disable flow validation",
            type="bool",
            default=False,
            required=False,
            description="Disables flow validation before execution. Not recommended for production use.",
            category=EXECUTION_CONTROL,
        ),
        DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION: GlobalConfigParam(
            name="Skip custom operator validation",
            type="bool",
            default=False,
            required=False,
            description="Skips validation for custom operators while still validating built-in operators.",
            category=EXECUTION_CONTROL,
        ),
        DocpipeConstants.OUTPUT_FOLDER: GlobalConfigParam(
            name="Output folder",
            type="string",
            required=False,
            description="Directory for storing final output files. Can be either a relative path (relative to workspace directory) or an absolute path. If not provided, the system generates a unique path based on job execution IDs.",
            category=EXECUTION_CONTROL,
        ),
        DocpipeConstants.DATA_STORAGE_TYPE: GlobalConfigParam(
            name="Data storage type",
            type="string",
            required=False,
            description="Storage backend type for intermediate data during flow execution (memory or local)",
            category=EXECUTION_CONTROL,
        ),
        # Incremental Processing
        DocpipeConstants.INCREMENTAL_METADATA_REPOSITORY_CONFIG: GlobalConfigParam(
            name="Incremental metadata repository config",
            type="JSON",
            default={},
            required=False,
            description=(
                "Configuration for incremental metadata repository. Tracks processed documents to enable incremental updates.\n"
                "JSON format:\n"
                "{\n"
                '  "storage_type": "<storage_type>",\n'
                '  "config": {<storage_type_specific_config>}\n'
                "}\n\n"
                "Default value for storage_type: in_memory\n"
                "Supported storage_type values and their config details:\n"
                "- in_memory: config = {} (no additional settings required)\n"
                '- file_system: config = {"base_dir": "<directory_path>"}\n'
                "- postgresql: config = {\n"
                '    "host": "<db_host>",\n'
                '    "port": <db_port>,\n'
                '    "database": "<db_name>",\n'
                '    "username": "<username>",\n'
                '    "password": "<password>"\n'
                '    "schema": "<schema>"\n'
                "  }"
            ),
            category=INCREMENTAL_PROCESSING,
        ),
        # Orchestration configuration (Prefect + Micro-Batching)
        DocpipeConstants.MAX_RETRY_ATTEMPTS: GlobalConfigParam(
            name="Maximum retry attempts",
            type="int",
            default=DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS,
            required=False,
            description=(
                "Retries allowed for a document that failed at a node, resumed from the upstream checkpoint on "
                "later runs (total attempts = 1 + max_retry_attempts). Requires local intermediate storage."
            ),
            category=ORCHESTRATION,
        ),
        DocpipeConstants.MICRO_BATCH_SIZE: GlobalConfigParam(
            name="Micro batch size",
            type="int",
            default=DocpipeConstants.DEFAULT_MICRO_BATCH_SIZE,
            required=False,
            description="Number of records per batch when micro-batching is enabled",
            category=ORCHESTRATION,
        ),
        DocpipeConstants.MAX_CONCURRENT_BATCHES: GlobalConfigParam(
            name="Maximum concurrent batches",
            type="int",
            default=DocpipeConstants.DEFAULT_MAX_CONCURRENT_BATCHES,
            required=False,
            description="Maximum number of batches to execute concurrently",
            category=ORCHESTRATION,
        ),
        DocpipeConstants.PREFECT_CONFIG: GlobalConfigParam(
            name="Prefect config",
            type="JSON",
            required=False,
            description=(
                "Prefect orchestration configuration.\n\n"
                "JSON format:\n"
                "{\n"
                '  "strategy": "<strategy>",\n'
                '  "work_pool_name": "<work_pool_name>",\n'
                '  "deployment_name": "<deployment_name>",\n'
                '  "deployment_path": "<deployment_path>",\n'
                '  "image": "<image>",\n'
                '  "env": <env>,\n'
                '  "image_pull_policy": "<image_pull_policy>",\n'
                '  "networks": <networks>,\n'
                '  "batch_storage": {\n'
                '    "type": "inline or local",\n'
                "  }\n"
                "}\n\n"
                "Default values (only explicitly defined defaults):\n"
                "- strategy: 'thread-pool'\n"
                "- env: {}\n"
                "- image_pull_policy: 'Never'\n"
                "- networks: []\n"
                "- type: 'inline'\n\n"
                "Supported strategy values:\n"
                "- thread-pool\n"
                "- work-pool-process\n"
                "- work-pool-docker\n\n"
                "Execution behavior:\n"
                "- By default, the execution strategy is 'thread-pool'.\n"
                "- Distributed execution requires self-hosted Prefect.\n"
                "- For distributed execution setup and configuration, refer to:\n"
                "  docs/prefect/DISTRIBUTED_EXECUTION_GUIDE.md\n\n"
                "Required environment variables for distributed execution:\n"
                "- PREFECT_MODE=server\n"
                "- PREFECT_API_URL=http://localhost:4200/api\n"
                "  (PREFECT_API_URL should point to the Prefect Server API URL.)\n\n"
                "Critical:\n"
                "- Without PREFECT_MODE=server, Docpipe runs in ephemeral mode and ignores the work pool configuration."
            ),
            category=ORCHESTRATION,
        ),
        DocpipeConstants.MEMMAP_THRESHOLD: GlobalConfigParam(
            name="Persistent Storage Threshold",
            type="int",
            required=False,
            default=DocpipeConstants.MEMMAP_THRESHOLD_DEFAULT,
            description="Threshold in MB after which persistent storage is used for chunks and embeddings, threshold value should be greater than 1",
            category=EXECUTION_CONTROL,
        ),
        OperatorConstants.DOC_FORMAT_KEY: GlobalConfigParam(
            name="Document format",
            type="string",
            required=False,
            default=OperatorConstants.DOC_FORMAT_DEFAULT,
            description=(
                "Primary document format used throughout the pipeline. "
                "Controls how operators process text content in doc_column. "
                "Valid values: 'markdown' (default), 'doclang'. "
                "When set to 'doclang', quality and functional operators automatically "
                "strip DocLang XML tags before text processing."
            ),
            category=EXECUTION_CONTROL,
        ),
    }

    @classmethod
    def get_all_config_metadata(cls) -> dict[str, GlobalConfigParam]:
        """Get all config metadata."""
        return cls._PARAMETERS.copy()

    @classmethod
    def get_config_by_category(cls) -> dict[str, list[GlobalConfigParam]]:
        """Get config by category."""
        by_category: dict[str, list[GlobalConfigParam]] = {}
        for param in cls._PARAMETERS.values():
            if param.category not in by_category:
                by_category[param.category] = []
            by_category[param.category].append(param)
        return by_category

    @classmethod
    def get_categories(cls) -> list[str]:
        """Get categories."""
        categories = {param.category for param in cls._PARAMETERS.values()}
        return sorted(categories)
