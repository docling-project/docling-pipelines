# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Per-node scoping around :func:`~docpipe.integrations.secrets.resolver.resolve_node_config`.

The configuration an executor hands to an operator is a merge: the node's own
settings, the flow ``global_config``, and framework-owned shared keys. A
reference is resolved only for the node whose own configuration holds it
(design D6). :func:`resolve_operator_config` removes the framework-owned shared
keys, resolves the rest through the shared resolver, and merges the result back.

The operator constructor receives :class:`SecretValue` objects for resolved
fields. Adapters call ``reveal()`` (through
:func:`~docpipe.integrations.secrets.secret_value.reveal_value`) at the one place
where they build a client or a validated configuration model (task B.5).
"""

from typing import TYPE_CHECKING, Any, Final

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.operator_loader.ports.operator_source import TrustClass
from docpipe.integrations.secrets.resolver import resolve_node_config
from docpipe.integrations.secrets.secret_provider import has_vault_references

if TYPE_CHECKING:
    from docpipe.core.operators.abstract_operator import AbstractOperator

# Keys the framework adds to every node's merged configuration. They are not the
# node's own settings, so a reference inside them is never resolved for the node:
# ``flow_definition`` is the whole unresolved flow, ``ingest_source`` carries
# non-secret source facts, ``common_log_arguments`` carries log identifiers.
SHARED_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        DocpipeConstants.FLOW_DEFINITION,
        OperatorConstants.Config.INGEST_SOURCE,
        OperatorConstants.Config.COMMON_LOG_ARGUMENTS,
    }
)


def _foreign_keys(*, operator_class: "type[AbstractOperator]", config: dict[str, Any]) -> set[str]:
    """Return keys of ``config`` that hold per-node run-parameter overrides, not this node's own settings.

    The orchestrator merges the whole run-parameter ``global_config`` into every node, so an
    override entry keyed by a node name, node id, or operator type shows up as a dict-valued
    key in every node's configuration. Its contents are merged flat into the node it
    addresses, which resolves them there. A key that the operator declares as one of its own
    attributes is never foreign.
    """
    flow_definition = config.get(DocpipeConstants.FLOW_DEFINITION)
    dag = flow_definition.get(DocpipeConstants.DAG) if isinstance(flow_definition, dict) else None
    if not isinstance(dag, list):
        return set()
    names: set[str] = set()
    for node in dag:
        if isinstance(node, dict):
            for key in (OperatorConstants.Columns.NAME, OperatorConstants.Columns.ID, OperatorConstants.Misc.OPERATOR):
                value = node.get(key)
                if isinstance(value, str):
                    names.add(value)
    candidates = {key for key in names if isinstance(config.get(key), dict)}
    if not candidates:
        return set()
    own_attributes = operator_class.get_metadata().get(OperatorConstants.Config.ATTRIBUTES, {})
    return candidates - set(own_attributes)


def resolve_operator_config(*, operator_class: "type[AbstractOperator]", config: dict[str, Any]) -> dict[str, Any]:
    """Resolve the references in a node's own configuration, leaving shared keys untouched.

    The node's own part is ``config`` without the framework-owned shared keys
    (:data:`SHARED_CONFIG_KEYS`) and without the override entries of nodes (see
    ``_foreign_keys``). Returns ``config`` itself when that part holds no ``vault://``
    text, so a node without references costs no provider request and no copy. A value
    that is already a :class:`SecretValue` holds no text, so a configuration that was
    resolved once is not resolved again. Nothing is resolved while a flow is only being
    validated.

    Raises:
        SecretResolutionError: A reference is malformed, undeclared, outside the
            deployment policy, or cannot be read. The first failure aborts the node.
    """
    if config.get(DocpipeConstants.VALIDATING_FLOW):
        return config
    unshared = {key: value for key, value in config.items() if key not in SHARED_CONFIG_KEYS}
    if not has_vault_references(unshared):
        return config
    foreign = _foreign_keys(operator_class=operator_class, config=config)
    own = {key: value for key, value in unshared.items() if key not in foreign}
    if not has_vault_references(own):
        return config
    node_name = str(config.get(OperatorConstants.Columns.NAME) or "")
    resolved_own = resolve_node_config(node_name=node_name, operator_class=operator_class, config=own)
    return {**config, **resolved_own}


class ResolvedNodeConfig(dict[str, Any]):
    """Marks a configuration that already went through :func:`prepare_operator_config`.

    A resolved secret may legitimately contain the text ``vault://``; the marker
    keeps a second pass (the operator constructor after the executor) from reading
    it as a reference.
    """


def prepare_operator_config(*, operator_class: "type[AbstractOperator]", config: dict[str, Any]) -> dict[str, Any]:
    """Return the configuration an operator constructor should read.

    Resolves the node's own references. The resolved values stay :class:`SecretValue`
    objects; each adapter reveals them at its client-construction point. A configuration
    that was already prepared is returned unchanged, so the executor and the constructor
    never both call a provider. A configuration without references is returned as is.

    An untrusted custom operator is not resolved here: its references are never resolved in the process that holds
    the provider, and its isolation proxy decides what crosses to the worker (design D12).
    """
    if isinstance(config, ResolvedNodeConfig) or getattr(operator_class, "trust_class", None) == TrustClass.UNTRUSTED:
        return config
    resolved = resolve_operator_config(operator_class=operator_class, config=config)
    if resolved is config:
        return config
    return ResolvedNodeConfig(resolved)
