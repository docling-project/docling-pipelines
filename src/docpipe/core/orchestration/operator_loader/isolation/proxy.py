# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parent-side stand-in for an untrusted operator that runs in an isolation worker (design D12, task D.3).

The executor treats the proxy like any operator: it reads ``config``, ``name``, ``output_features_to_drop`` and
friends, and calls ``transform``. ``transform`` sends the table to the node's worker and returns what the worker sends
back. Nothing of the untrusted module is imported in this process.
"""

from typing import Any, Final

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.orchestration.operator_loader.isolation.worker_client import get_worker_pool
from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.secret_provider import has_vault_references
from docpipe.types import TransformResult
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# The only keys of the flow-wide ``global_config`` an untrusted operator receives.
GLOBAL_CONFIG_ALLOWLIST: Final[tuple[str, ...]] = (OperatorConstants.Columns.DOC_COLUMN, DocpipeConstants.JOB_ID)
# The node's identity. These are the node's own values, not flow-wide ones.
_IDENTITY_KEYS: Final[tuple[str, ...]] = (
    OperatorConstants.Columns.NAME,
    OperatorConstants.Columns.ID,
    DocpipeConstants.NODE_ID,
    DocpipeConstants.NODE_NAME,
)

REFERENCES_NOT_PERMITTED_MESSAGE: Final[str] = (
    "not permitted: untrusted custom operator '%s' holds a vault:// reference; references are not delivered to "
    "untrusted operators"
)


def extract_own_config(*, merged_config: dict[str, Any]) -> dict[str, Any]:
    """Return the node's own configuration from the executor's merged configuration.

    The executor merges the flow ``global_config`` (which carries every node, ingest credentials and run parameters)
    into each node's configuration. The node's own part is rebuilt the way the orchestrator builds it: the ``config``
    of its entry in the flow definition, overridden by the run-parameter entry keyed by node name, node id or operator
    type. Without a flow definition nothing can be attributed to the node, so the result is empty.
    """
    flow_definition = merged_config.get(DocpipeConstants.FLOW_DEFINITION)
    dag = flow_definition.get(DocpipeConstants.DAG) if isinstance(flow_definition, dict) else None
    name = merged_config.get(OperatorConstants.Columns.NAME)
    if not isinstance(dag, list) or not isinstance(name, str):
        return {}
    node = next((n for n in dag if isinstance(n, dict) and n.get(OperatorConstants.Columns.NAME) == name), None)
    if node is None:
        return {}
    own: dict[str, Any] = dict(node.get(OperatorConstants.Config.CONFIG) or {})
    for key in (name, node.get(OperatorConstants.Columns.ID), node.get(OperatorConstants.Misc.OPERATOR)):
        override = merged_config.get(key) if isinstance(key, str) else None
        if isinstance(override, dict):
            own.update(override)
            break
    return own


def build_isolated_config(*, merged_config: dict[str, Any]) -> dict[str, Any]:
    """Return the configuration an untrusted operator is constructed with: its own plus the allowlisted keys."""
    delivered = {key: merged_config[key] for key in GLOBAL_CONFIG_ALLOWLIST if key in merged_config}
    delivered.update({key: merged_config[key] for key in _IDENTITY_KEYS if key in merged_config})
    return {**delivered, **extract_own_config(merged_config=merged_config)}


def run_id_of(*, merged_config: dict[str, Any]) -> str:
    """Return the key under which a run's workers are held and released."""
    run_id = merged_config.get(DocpipeConstants.JOB_RUN_ID)
    return str(run_id) if run_id else ""


class IsolatedOperatorProxy(AbstractOperator):
    """An operator whose ``transform`` runs in the isolation worker of its run."""

    owner: str | None = DocpipeConstants.OWNER_CUSTOM
    short_name: str = "isolated_operator_proxy"
    category: OperatorCategory = OperatorCategory.Functional

    def __init__(self, config: dict[str, Any], *, operator_info: OperatorInfo, run_id: str) -> None:
        super().__init__(config)
        self.short_name = operator_info.short_name
        self.category = OperatorCategory(operator_info.category)
        self._operator_info: OperatorInfo = operator_info
        self._run_id = run_id
        self._worker_config = {key: value for key, value in config.items() if key != DocpipeConstants.JOB_RUN_ID}

    @classmethod
    def for_node(cls, *, operator_info: OperatorInfo, merged_config: dict[str, Any]) -> "IsolatedOperatorProxy":
        """Build the proxy for a node from the executor's merged configuration.

        Raises:
            DocpipeException: The node's own configuration holds a ``vault://`` reference (403, ``not permitted``).
        """
        scoped = build_isolated_config(merged_config=merged_config)
        if has_vault_references(scoped):
            raise DocpipeException(REFERENCES_NOT_PERMITTED_MESSAGE % operator_info.short_name, status_code=403)
        run_id = run_id_of(merged_config=merged_config)
        parent_config = {**scoped, DocpipeConstants.JOB_RUN_ID: merged_config.get(DocpipeConstants.JOB_RUN_ID)}
        return cls(parent_config, operator_info=operator_info, run_id=run_id)

    def transform(self, table: pa.Table, tables: dict[str, pa.Table] | None = None) -> TransformResult:
        """Send ``table`` to the node's worker and return its output tables and metadata."""
        if tables is not None:
            raise DocpipeException(
                f"Untrusted custom operator '{self.short_name}' cannot run with several input tables", status_code=400
            )
        info = self._operator_info
        if info.source_file is None:
            raise DocpipeException("Untrusted custom operator has no source file", status_code=500)
        worker = get_worker_pool().acquire(
            run_id=self._run_id,
            label=info.short_name,
            source_file=info.source_file,
            load_header={
                "class_name": info.name,
                "short_name": info.short_name,
                "module_path": info.module_path,
                "category": info.category,
                "source_file": info.source_file,
            },
        )
        out_tables, metadata, _ = worker.run(config=self._worker_config, table=table)
        return out_tables, metadata

    def cleanup(self) -> None:
        """Nothing to do per batch: the worker belongs to the run and is stopped when the run ends."""
