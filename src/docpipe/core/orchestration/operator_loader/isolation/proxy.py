# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parent-side stand-in for an untrusted operator that runs in an isolation worker (design D12, task D.3).

The executor treats the proxy like any operator: it reads ``config``, ``name``, ``output_features_to_drop`` and
friends, and calls ``transform``. ``transform`` sends the table to the node's worker and returns what the worker sends
back. Nothing of the untrusted module is imported in this process.
"""

import json
from typing import TYPE_CHECKING, Any, Final

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.orchestration.operator_loader.isolation.worker_client import get_worker_pool
from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.registry import register_secret
from docpipe.integrations.secrets.resolver import resolve_node_config
from docpipe.integrations.secrets.secret_value import SecretValue
from docpipe.types import TransformResult
from docpipe.utils.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from docpipe.core.operators.abstract_operator import AbstractOperator

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

ConfigPath = tuple[str | int, ...]


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


def detach_secrets(*, node: Any, path: ConfigPath = ()) -> tuple[Any, dict[ConfigPath, SecretValue]]:
    """Split resolved secrets out of a configuration.

    Returns a copy of ``node`` in which every :class:`SecretValue` is replaced by ``None``, and the detached values
    keyed by their path. The copy is safe to serialize and to keep on the proxy.
    """
    if isinstance(node, SecretValue):
        return None, {path: node}
    detached: dict[ConfigPath, SecretValue] = {}
    if isinstance(node, dict):
        copy_dict: dict[Any, Any] = {}
        for key, child in node.items():
            copy_dict[key], found = detach_secrets(node=child, path=(*path, str(key)))
            detached.update(found)
        return copy_dict, detached
    if isinstance(node, list):
        copy_list: list[Any] = []
        for index, child in enumerate(node):
            item, found = detach_secrets(node=child, path=(*path, index))
            copy_list.append(item)
            detached.update(found)
        return copy_list, detached
    return node, detached


def encode_secrets(*, secrets: dict[ConfigPath, SecretValue]) -> dict[str, Any]:
    """Return the hand-off payload: ``{JSON-encoded field path: revealed value}`` (design D12).

    This is the one place a resolved value is revealed for an isolated operator. The payload is sent to the node's
    worker over the private pipe and nowhere else.
    """
    return {json.dumps(list(path)): value.reveal() for path, value in secrets.items()}


def run_id_of(*, merged_config: dict[str, Any]) -> str:
    """Return the key under which a run's workers are held and released."""
    run_id = merged_config.get(DocpipeConstants.JOB_RUN_ID)
    return str(run_id) if run_id else ""


class IsolatedOperatorProxy(AbstractOperator):
    """An operator whose ``transform`` runs in the isolation worker of its run."""

    owner: str | None = DocpipeConstants.OWNER_CUSTOM
    short_name: str = "isolated_operator_proxy"
    category: OperatorCategory = OperatorCategory.Functional

    def __init__(
        self,
        config: dict[str, Any],
        *,
        operator_info: OperatorInfo,
        run_id: str,
        secrets: dict[ConfigPath, SecretValue] | None = None,
    ) -> None:
        super().__init__(config)
        self.short_name = operator_info.short_name
        self.category = OperatorCategory(operator_info.category)
        self._operator_info: OperatorInfo = operator_info
        self._run_id = run_id
        self._secrets: dict[ConfigPath, SecretValue] = secrets or {}
        self._worker_config = {key: value for key, value in config.items() if key != DocpipeConstants.JOB_RUN_ID}

    @classmethod
    def for_node(
        cls,
        *,
        operator_class: "type[AbstractOperator]",
        operator_info: OperatorInfo,
        merged_config: dict[str, Any],
    ) -> "IsolatedOperatorProxy":
        """Build the proxy for a node from the executor's merged configuration.

        Only the node's own configuration and the allowlisted ``global_config`` keys are considered. A reference in a
        field the operator declares secret-capable is resolved here, in the parent, and only when it matches
        ``secrets.vault.custom_operator_allowed_paths``; the policy runs before any provider call. Resolved values are
        registered with the scrubber and held as :class:`SecretValue` until they are sent to the worker.

        Raises:
            SecretResolutionError: A reference is undeclared, outside the custom-operator policy (``not permitted``,
                the default), or cannot be read. Vault is not contacted for a denied reference.
        """
        scoped = build_isolated_config(merged_config=merged_config)
        node_name = str(merged_config.get(OperatorConstants.Columns.NAME) or "")
        resolved = resolve_node_config(node_name=node_name, operator_class=operator_class, config=scoped)
        run_id = run_id_of(merged_config=merged_config)
        safe_config, secrets = detach_secrets(node=resolved)
        for value in secrets.values():
            register_secret(value=value.reveal(), run_id=run_id or None)
        parent_config = {**safe_config, DocpipeConstants.JOB_RUN_ID: merged_config.get(DocpipeConstants.JOB_RUN_ID)}
        return cls(parent_config, operator_info=operator_info, run_id=run_id, secrets=secrets)

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
        out_tables, metadata, _ = worker.run(
            config=self._worker_config, table=table, secrets=encode_secrets(secrets=self._secrets)
        )
        return out_tables, metadata

    def cleanup(self) -> None:
        """Nothing to do per batch: the worker belongs to the run and is stopped when the run ends."""
