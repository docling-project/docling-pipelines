# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory wiring the resumption service to its storages."""

import re
from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.data_access.data_access_utils import DataAccessConstants, DataAccessUtils
from docpipe.core.orchestration.application.services.resumption_service import ResumptionService
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.storage.file_system.table_file_system_storage import TableFileSystemStorage
from docpipe.utils.infrastructure.filesystem import get_data_path


def is_resumption_enabled(*, config: dict[str, Any]) -> bool:
    """Resumption reads the intermediate node output, so it is inactive when that output only lives in memory."""
    storage_type = config.get(DocpipeConstants.DATA_STORAGE_TYPE, "")
    return bool(storage_type) and storage_type != DataAccessConstants.MEMORY


def _node_folder(*, node_name: str, output_index: int, batch_num: int | None) -> str:
    """Return the folder of a node output below the intermediate output folder.

    Sanitized and laid out the same way ``DataAccessUtils.add_node_name_to_output_folder`` does when saving:
    ``<node name>_<output index>`` and, for micro-batched runs, ``/<batch_num>``.
    """
    folder = re.sub(r"\W+", "_", f"{node_name}_{output_index}")
    return folder if batch_num is None else f"{folder}/{int(batch_num)}"


def create_resumption_service(*, config: dict[str, Any]) -> ResumptionService | None:
    """Create a ResumptionService for the given flow/operator config, or None when resumption is inactive.

    Failure records live below the data path. The node outputs are read from
    ``<data path>/<job_id>/<job_run_id>/data/<node name>_<output index>[/<batch_num>]``, the folder the executors save
    them to; ``job_run_id`` and ``batch_num`` come from the failure record. An explicitly configured output folder is
    used as is for every job run.
    """
    if not is_resumption_enabled(config=config):
        return None
    data_path = get_data_path()
    job_id = str(config.get(DocpipeConstants.JOB_ID))
    current_run_id = str(config.get(DocpipeConstants.JOB_RUN_ID))
    configured = (config.get("data_local_config") or {}).get(DocpipeConstants.OUTPUT_FOLDER)
    default_current = DataAccessUtils.default_intermediate_output_folder(job_id=job_id, job_run_id=current_run_id)
    configured_folder = configured if configured and configured != default_current else None

    def output_table_name(*, job_run_id: str, node_name: str, output_index: int, batch_num: int | None) -> str:
        folder = _node_folder(node_name=node_name, output_index=output_index, batch_num=batch_num)
        return folder if configured_folder else f"{job_id}/{job_run_id}/data/{folder}"

    return ResumptionService(
        record_storage=KeyValueFileSystemStorage(base_dir=data_path),
        table_storage=TableFileSystemStorage(base_dir=configured_folder or data_path),
        output_table_name=output_table_name,
        max_retry_attempts=int(
            config.get(DocpipeConstants.MAX_RETRY_ATTEMPTS, DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS)
        ),
    )
