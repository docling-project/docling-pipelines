# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Flow execution utilities for node mapping, logging, and validation."""

import json
from collections import defaultdict, deque
from pathlib import Path

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import ErrorCode, FlowValidationException, ValidationAlert
from docpipe.exceptions.error_messages import ValidationMessage
from docpipe.utils.infrastructure.filesystem import get_data_path


def sort_dag_topologically(*, dag: list[dict]) -> list[dict]:
    """Sort DAG nodes in topological order using Kahn's algorithm.

    Builds the sort from ``output_edges`` so no additional adjacency structure
    is required from the caller. Nodes that do not appear in any edge list
    (isolated nodes) are included with in-degree zero and processed first.

    Args:
        dag: List of node dicts, each containing an ``"id"`` key and an
            optional ``"output_edges"`` list of ``{"node_id_ref": "<id>"}``
            dicts. Order of the input list is irrelevant.

    Returns:
        New list of the same node dicts in valid topological order.

    Raises:
        FlowValidationException: If the graph contains a cycle.
    """
    by_id = {node["id"]: node for node in dag}
    original_index = {node["id"]: idx for idx, node in enumerate(dag)}

    # Build adjacency list from output_edges; initialise every node so isolated
    # nodes (no edges at all) are still included with in-degree zero.
    adjacency: dict[str, list[str]] = defaultdict(list)
    for node in dag:
        adjacency[node["id"]]  # ensure every node is present even with no edges
        for edge in node.get(DocpipeConstants.OUTPUT_EDGES, []):
            child_id = edge.get(DocpipeConstants.NODE_ID_REF)
            if child_id and child_id in by_id:
                adjacency[node["id"]].append(child_id)

    in_degree: dict[str, int] = defaultdict(int)
    for node_id in adjacency:
        in_degree[node_id]  # initialise
        for child_id in adjacency[node_id]:
            in_degree[child_id] += 1

    # Deterministic initial queue ordered by original node position in dag
    queue: deque[str] = deque(
        sorted((nid for nid, deg in in_degree.items() if deg == 0), key=lambda nid: original_index.get(nid, 0))
    )
    topo_order: list[dict] = []

    while queue:
        node_id = queue.popleft()
        topo_order.append(by_id[node_id])
        # Sort children deterministically by original position before appending to queue
        for child_id in sorted(adjacency[node_id], key=lambda cid: original_index.get(cid, 0)):
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    if len(topo_order) != len(in_degree):
        raise FlowValidationException(
            errors=[
                ValidationAlert(
                    code=ErrorCode.FLOW_VALIDATION_FAILED.value,
                    message="DAG contains a cycle; topological sort not possible",
                    message_code="DAG_CYCLE_DETECTED",
                )
            ]
        )

    return topo_order


def create_node_id_to_index_map(*, flow_def: dict) -> dict:
    """
    Return a mapping between each node ID and its corresponding index,
    representing the position where it appears in the original JSON node sequence.

    Args:
        flow_def: a dict holding a flow.

    Returns:
        dict: A mapping between node id and its index in the input flow.
    """
    node_id_to_index_map = {}
    index = 0
    for node in flow_def:
        node_id_to_index_map[node["id"]] = index
        index = index + 1
    return node_id_to_index_map


def create_log_folders(job_id, job_run_id, type):
    """
    Created folders for logs: <job_id>/<job_run_id>/docpipe_logs. The log for that job will be stored there
    """
    log_location_path = get_data_path()

    log_app_location = DocpipeConstants.DOCPIPE_LOGS

    log_job_location = Path(log_location_path) / job_id / str(job_run_id) / log_app_location
    log_job_location.mkdir(parents=True, exist_ok=True)
    if type == "job":
        log_job_run_file_name = "job_stats.json"
    elif type == "agg_logs":
        log_job_run_file_name = "flow_execute_aggregated.json"

    return str(log_job_location / log_job_run_file_name)


def write_job_logs(job_stats, job_log_path):
    """
    Write job statistics to a JSON log file.

    Args:
        job_stats: Job statistics object with __dict__ attribute
        job_log_path: Path to write the log file
    """
    with Path(job_log_path).open("w") as file:
        json.dump(job_stats.__dict__, file, indent=4)


def construct_deleted_rows_table_path(*, job_id: str, job_run_id):
    """
    Construct the path for storing deleted rows table.

    Args:
        job_id: Job identifier
        job_run_id: Job run identifier

    Returns:
        Path to the deleted rows parquet file
    """
    parquet_file_name = "unprocessed_docs.parquet"
    return str(
        Path(get_data_path()) / job_id / str(job_run_id) / DocpipeConstants.UNPROCESSED_DOCS_PATH / parquet_file_name
    )


def add_validation_alert(message: str | ValidationMessage, op_def: dict, alerts: list, **kwargs):
    """
    Add a validation alert to the alerts list.

    Parameters
    ----------
       message: Either a plain string or a ValidationMessage object.
        op_def: Dictionary with operator definition keys: ID, NAME, OPERATOR.
        alerts: List to which the new ValidationAlert will be appended.
        **kwargs: Optional extra parameters to include in the alert.

    Returns
    -------
    instance of ValidationAlert model
    """
    message_obj = message if isinstance(message, ValidationMessage) else ValidationMessage(message=message)

    alerts.append(
        ValidationAlert(
            code=ErrorCode.FLOW_VALIDATION_FAILED.value,
            node_id=op_def.get(OperatorConstants.Misc.ID),
            node_name=op_def.get(OperatorConstants.Misc.NAME),
            operator=op_def.get(OperatorConstants.Misc.OPERATOR),
            **message_obj.model_dump(mode="python"),
            **kwargs,
        )
    )


__all__ = [
    "add_validation_alert",
    "construct_deleted_rows_table_path",
    "create_log_folders",
    "create_node_id_to_index_map",
    "sort_dag_topologically",
    "write_job_logs",
]
