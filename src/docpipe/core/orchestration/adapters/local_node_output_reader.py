# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Reads saved node outputs from the local intermediate storage written when ``data_storage_type`` is ``local``."""

import re
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.data_access.data_access_utils import DataAccessUtils
from docpipe.core.orchestration.ports.node_output_reader import NodeOutputReader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_OUTPUT_FILE = "output.parquet"


class LocalNodeOutputReader(NodeOutputReader):
    """Locates ``<output_folder>/<node_name>_<index>[/<batch_num>]/output.parquet`` of an earlier job run.

    The output folder is derived from ``job_id`` and ``job_run_id`` the same way the executors derive it when they
    save node outputs. An explicitly configured output folder is used as is.
    """

    def __init__(self, *, config: dict[str, Any]) -> None:
        self._config = config

    def _base_folder(self, *, job_run_id: str) -> Path:
        """Return the folder holding the node outputs of ``job_run_id``."""
        job_id = str(self._config.get(DocpipeConstants.JOB_ID))
        current_run_id = str(self._config.get(DocpipeConstants.JOB_RUN_ID))
        local_config = self._config.get("data_local_config") or {}
        configured = local_config.get(DocpipeConstants.OUTPUT_FOLDER)
        current_default = DataAccessUtils.default_intermediate_output_folder(job_id=job_id, job_run_id=current_run_id)
        if configured and configured != current_default:
            return Path(configured)
        return Path(DataAccessUtils.default_intermediate_output_folder(job_id=job_id, job_run_id=job_run_id))

    def read_rows(
        self,
        *,
        job_run_id: str,
        node_name: str,
        output_index: int,
        doc_ids: list[str],
    ) -> pa.Table | None:
        """Return the saved rows of ``doc_ids``; micro-batched runs keep one output file per batch."""
        if not doc_ids or not _SAFE_RUN_ID.match(job_run_id) or job_run_id in {".", ".."}:
            return None
        folder = self._base_folder(job_run_id=job_run_id) / re.sub(r"\W+", "_", f"{node_name}_{output_index}")
        id_column = OperatorConstants.Misc.ID
        remaining = set(doc_ids)
        parts: list[pa.Table] = []
        for file in [folder / _OUTPUT_FILE, *sorted(folder.glob(f"*/{_OUTPUT_FILE}"))]:
            if not file.is_file():
                continue
            try:
                rows = pq.read_table(file, filters=[(id_column, "in", sorted(remaining))])
            except Exception as exc:
                logger.warning("Failed to read saved node output for resumption: %s", type(exc).__name__)
                continue
            if rows.num_rows == 0:
                continue
            parts.append(rows)
            remaining -= set(rows[id_column].to_pylist())
            if not remaining:
                break
        if not parts:
            return None
        return pa.concat_tables(parts, promote_options="permissive")
