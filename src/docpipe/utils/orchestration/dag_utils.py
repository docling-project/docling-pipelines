"""
DAG Utility Functions

Shared utilities for working with DAG (Directed Acyclic Graph) nodes.
"""

from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.elyra_converter import ElyraConstants, ElyraConverter

logger = get_logger()


def identify_ingest_and_destination_nodes(dag_nodes: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    """
    Identify ingest node (no input edges) and destination nodes (no output edges).

    This is a shared utility used by both JobTrackerService and JobReportGenerator
    to consistently identify special nodes in the DAG.

    Args:
        dag_nodes: List of DAG node dictionaries

    Returns:
        Tuple of (ingest_node_id, destination_node_ids)
    """
    ingest_node_id = None
    destination_node_ids = []

    for node in dag_nodes:
        node_id = node.get(OperatorConstants.Misc.ID)
        if not node_id:
            continue

        # Ingest node: has no input edges
        if not node.get(DocpipeConstants.INPUT_EDGES):
            ingest_node_id = node_id
            logger.debug("Identified ingest node: %s", node_id)

        # Destination nodes: have no output edges
        if not node.get(DocpipeConstants.OUTPUT_EDGES):
            destination_node_ids.append(node_id)

    if destination_node_ids:
        logger.debug("Identified %d destination nodes: %s", len(destination_node_ids), destination_node_ids)
    else:
        logger.warning("No destination nodes found in DAG")

    return ingest_node_id, destination_node_ids


def _resolve_node_name(ns: Any) -> str | None:
    """Return the operator name from a node-stats entry (object or dict)."""
    if hasattr(ns, OperatorConstants.Misc.NAME):
        return ns.name
    if isinstance(ns, dict):
        return ns.get(OperatorConstants.Misc.NAME)
    return None


def _build_name_to_uuid(node_stats: dict[str, Any]) -> dict[str, str]:
    """Map operator name -> UUID from node_stats."""
    name_to_uuid: dict[str, str] = {}
    for node_id, ns in node_stats.items():
        name = _resolve_node_name(ns)
        if name:
            name_to_uuid[name] = node_id
    return name_to_uuid


def _reconstruct_dag_nodes_from_authoring(
    *,
    authoring_ops: list[dict[str, Any]],
    node_stats: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rebuild DAG nodes from authoring flow + node_stats, preserving real UUIDs."""
    named_ops = [op for op in authoring_ops if isinstance(op, dict) and op.get(OperatorConstants.Misc.NAME)]

    name_to_op_type: dict[str, str] = {
        op[OperatorConstants.Misc.NAME]: op.get(OperatorConstants.Misc.TYPE, "") for op in named_ops
    }
    name_to_depends: dict[str, list[str]] = {
        op[OperatorConstants.Misc.NAME]: [
            # Authoring format uses "node_name.branch_name" for branching dependencies.
            # Strip the branch suffix so the dependency resolves to the plain node name.
            dep.split(".")[0]
            for dep in (op.get(OperatorConstants.Misc.DEPENDS_ON) or [])
        ]
        for op in named_ops
    }

    name_to_uuid = _build_name_to_uuid(node_stats)

    # Build output_edges: reverse of depends_on
    name_to_output_targets: dict[str, list[str]] = {n: [] for n in name_to_depends}
    for name, deps in name_to_depends.items():
        for dep in deps:
            if dep in name_to_output_targets:
                name_to_output_targets[dep].append(name)

    dag_nodes: list[dict[str, Any]] = []
    for name, uuid in name_to_uuid.items():
        input_deps = name_to_depends.get(name, [])
        output_targets = name_to_output_targets.get(name, [])
        dag_nodes.append(
            {
                OperatorConstants.Misc.ID: uuid,
                OperatorConstants.Misc.NAME: name,
                OperatorConstants.Misc.OPERATOR: name_to_op_type.get(name, ""),
                DocpipeConstants.INPUT_EDGES: [
                    {DocpipeConstants.NODE_ID_REF: name_to_uuid[d]} for d in input_deps if d in name_to_uuid
                ],
                DocpipeConstants.OUTPUT_EDGES: [
                    {DocpipeConstants.NODE_ID_REF: name_to_uuid[t]} for t in output_targets if t in name_to_uuid
                ],
            }
        )

    logger.info("Reconstructed %d DAG nodes from authoring flow + node_stats", len(dag_nodes))
    return dag_nodes


def _convert_elyra_to_dag(
    *,
    flow_definition: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """
    Convert an Elyra/CPD pipeline snapshot to a DAG node list.

    Returns the converted dag list on success, or None if the conversion raises
    so the caller can fall through to the warning branch.
    """
    try:
        converter = ElyraConverter()
        result = converter.transform_elyra_to_internal(elyra_json=flow_definition, flow_id="report-snapshot")
        dag = result.get(DocpipeConstants.FLOW, {}).get(DocpipeConstants.DAG, [])
        logger.info("Converted Elyra pipeline snapshot to %d DAG nodes for report generation", len(dag))
        return dag
    except Exception as exc:
        logger.warning("Failed to convert Elyra pipeline snapshot: %s", exc, exc_info=True)
        return None


def extract_dag_nodes(
    *,
    flow_definition: dict[str, Any] | None,
    node_stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Extract the list of runtime DAG nodes from a flow definition.

    Handles three formats that may be stored on disk:

    1. Runtime DAG format (compiled):
       ``{"dag": [{...}, ...], ...}``
       Returned directly — node IDs already match ``node_stats`` keys.

    2. Authoring format (original user input):
       ``{"flow": [{...}, ...], "global_config": {...}, ...}``
       Re-compiling is NOT safe because ``AuthoringCompiler`` generates fresh UUIDs
       that will never match the UUIDs stored in ``node_stats``.  Instead, the dag
       nodes are reconstructed from ``node_stats`` (real UUIDs + operator names)
       combined with the ``depends_on`` graph from the authoring ``flow`` list.

    3. Elyra / CPD pipeline format (Enterprise snapshot):
       ``{"doc_type": "pipeline", "pipelines": [{...}], ...}``
       Converted via ``ElyraConverter.transform_elyra_to_internal()`` and the
       resulting ``dag`` list is returned directly.  Node UUIDs in this format
       are the original Elyra node IDs and already match ``node_stats`` keys.

    Args:
        flow_definition: Flow definition dict as returned by
            ``job_stats_service.get_flow_definition()``, or None.
        node_stats: Aggregated node stats dict keyed by node_id.  Required for
            authoring-format reconstruction.

    Returns:
        List of runtime DAG node dicts with ``id``, ``name``, ``operator``,
        ``input_edges``, and ``output_edges``.  Empty list if nothing can be extracted.
    """
    if not flow_definition:
        return []

    # Runtime format — dag is a flat list of node dicts with real UUIDs
    dag = flow_definition.get(DocpipeConstants.DAG)
    if isinstance(dag, list):
        return dag

    # Elyra / CPD pipeline format — convert then return the dag list directly
    if flow_definition.get(ElyraConstants.DOC_TYPE) == "pipeline" and ElyraConstants.PIPELINES in flow_definition:
        converted = _convert_elyra_to_dag(flow_definition=flow_definition)
        if converted is not None:
            return converted

    # Authoring format — rebuild from node_stats to preserve real UUIDs
    if DocpipeConstants.FLOW not in flow_definition:
        logger.warning("Flow definition has neither 'dag' nor 'flow' key - cannot extract DAG nodes")
        return []

    if not node_stats:
        logger.warning("Authoring format flow found but no node_stats provided - cannot reconstruct DAG nodes")
        return []

    authoring_ops: list[dict[str, Any]] = flow_definition.get(DocpipeConstants.FLOW, [])
    return _reconstruct_dag_nodes_from_authoring(authoring_ops=authoring_ops, node_stats=node_stats)
