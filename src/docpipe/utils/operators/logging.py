"""Logging utilities for docpipe operator execution tracking."""

import copy
import datetime
import json
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models import NodeStats
from docpipe.utils.infrastructure.filesystem import get_data_path


def epoch_to_datetime(*, epoch_time):
    """Converts epoch time to a datetime object."""
    if not epoch_time:
        return ""
    return datetime.datetime.fromtimestamp(epoch_time, tz=datetime.UTC)


def _operator_log_split(*, value, operator_logs_combined):
    value_split = value.split("\n")
    value_split = [val for val in value_split if len(val) > 0]

    if len(value_split) > 0 and ":" in value_split[0]:
        # Below operator is to get nodeId from logs
        operator_node_id = value_split[0].split(":")[1][1:]
        # Combine all values except the NodeID
        combined_string = "\n ".join(value_split[1:])
        operator_logs_combined["node_sequence"].append(operator_node_id)
        operator_logs_combined[operator_node_id] = combined_string
    return operator_logs_combined


def get_log_and_job_file_path(*, job_id, jobrun_id):
    # Path structure: ./data/<job_id>/<job_run_id>/docpipe_logs/
    """Get log and job file path."""
    log_app_location = DocpipeConstants.DOCPIPE_LOGS
    log_job_run_file_name = "flow_execute.log"
    job_log_file_name = "job_stats.json"
    log_location_path = get_data_path()

    stats_dir = Path(log_location_path) / job_id / str(jobrun_id) / log_app_location

    log_final_path = str(stats_dir / log_job_run_file_name)
    job_log_final_path = str(stats_dir / job_log_file_name)
    aggregated_job_log_path = str(stats_dir / "flow_execute_aggregated.json")

    nodes_metadata_final_path = str(
        Path(log_location_path) / job_id / str(jobrun_id) / OperatorConstants.Config.NODES_METADATA_FILE
    )
    return (
        log_final_path,
        job_log_final_path,
        nodes_metadata_final_path,
        aggregated_job_log_path,
    )


def retrieve_operator_logs(*, job_id, jobrun_id):
    """Retrieve operator logs."""
    (
        log_final_path,
        job_log_final_path,
        nodes_metadata_final_path,
        aggregated_job_log_path,
    ) = get_log_and_job_file_path(job_id=job_id, jobrun_id=jobrun_id)

    # # Try to get logs from database first (new pipeline branching approach)
    # from docpipe_integrations.db.dal.node_level_execution_log_dal import NodeLevelExecutionLogDAL
    # dal = NodeLevelExecutionLogDAL()
    # postgres_logs = dal.get_logs_for_all_nodes(job_id=job_id, job_run_id=jobrun_id)
    # content = postgres_logs["node_logs"] if postgres_logs and "node_logs" in postgres_logs else {}
    #
    # # If database returns empty, try aggregated file (new format) or fall back to old sequential flow format
    # if not content:
    # Try new aggregated format first
    if Path(aggregated_job_log_path).exists():
        aggregated_content = read_json_if_exists(path=aggregated_job_log_path)
        if aggregated_content:
            # Aggregated file has complete structure, return it
            return aggregated_content

    # Fall back to old sequential flow format (backward compatibility).
    # No log file at all gives the same empty result as an empty log file.
    content = ""
    if Path(log_final_path).exists():
        with Path(log_final_path).open() as file:
            content = file.read()

    return get_logs(
        content=content,
        job_log_final_path=job_log_final_path,
        nodes_metadata_final_path=nodes_metadata_final_path,
    )


def read_json_if_exists(*, path):
    """Reads and returns JSON if file exists."""
    if path and Path(path).exists():
        with Path(path).open() as f:
            return json.load(f)
    return None


def _parse_sequential_log_content(log_content: str, operator_logs_combined: dict) -> dict:
    """
    Parses sequential flow log content (Backward compatibility).
    """
    content_split = log_content.split(">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    for value in content_split:
        operator_logs_combined = _operator_log_split(value=value, operator_logs_combined=operator_logs_combined)
    return operator_logs_combined


def _handle_dict_with_logs_key(content: dict, operator_logs_combined: dict) -> dict:
    """Handle dict with 'logs' key format (Cloud/MCSP backward compatibility)."""
    if "jobs" in content:
        operator_logs_combined["job_stats"] = content["jobs"]

    log_content = content.get("logs", "")
    if log_content:
        operator_logs_combined = _parse_sequential_log_content(log_content, operator_logs_combined)
    return operator_logs_combined


def _handle_string_logs(
    content: str,
    operator_logs_combined: dict,
    job_log_final_path: str | None,
    nodes_metadata_final_path: str | None,
) -> dict:
    """Handle string format logs (old sequential flow backward compatibility)."""
    operator_logs_combined = _parse_sequential_log_content(content, operator_logs_combined)

    # Merge additional files if present (old format)
    job_stats = read_json_if_exists(path=job_log_final_path)
    if job_stats is not None:
        operator_logs_combined["job_stats"] = job_stats

    nodes_metadata = read_json_if_exists(path=nodes_metadata_final_path)
    if nodes_metadata is not None:
        operator_logs_combined["nodes_metadata"] = nodes_metadata

    return operator_logs_combined


def get_logs(*, content, job_log_final_path: str | None = None, nodes_metadata_final_path: str | None = None):
    """
    Processes log content from various sources and formats.

    Handles three formats:
    1. Dict with "logs" key - from get_non_branching_logs() for Cloud/MCSP (Backward compatibility)
    2. Dict with node logs - from PostgreSQL database (new pipeline branching)
    3. String content - from flow_execute.log (old sequential flow) (Backward compatibility)

    Args:
        content: Log content (dict or string)
        job_log_final_path: Path to job_stats.json file
        nodes_metadata_final_path: Path to nodes_metadata file

    Returns:
        Dict with operator logs, node_sequence, job_stats, and nodes_metadata
    """
    operator_logs_combined: dict[str, Any] = {"node_sequence": []}
    # Check if content is a dict with "logs" key (from get_non_branching_logs for Cloud/MCSP)
    if isinstance(content, dict) and "logs" in content:
        return _handle_dict_with_logs_key(content, operator_logs_combined)

    if isinstance(content, dict) and content:
        operator_logs_combined.update(content)
        operator_logs_combined["node_sequence"] = list(content.keys())
        return operator_logs_combined

    # Old sequential flow format: content is a string from flow_execute.log (backward compatibility)
    if isinstance(content, str) and content:
        return _handle_string_logs(
            content,
            operator_logs_combined,
            job_log_final_path,
            nodes_metadata_final_path,
        )

    return operator_logs_combined


def retrieve_node_specific_operator_logs(*, job_id, jobrun_id, node_id):
    """Retrieve node specific operator logs."""
    return retrieve_operator_logs(job_id=job_id, jobrun_id=jobrun_id).get(node_id)


def retrieve_operators_sequence(*, job_id: str, job_run_id: str) -> list:
    """Retrieves the sequence of operators for a given job and job run id."""
    operators_log = retrieve_operator_logs(job_id=job_id, jobrun_id=job_run_id)
    return operators_log.get("node_sequence", [])


def _extract_document_level_errors(*, node_metadata: dict) -> list:
    """
    Extracts document-level errors from node metadata.
    Looks for 'failed_docs' and 'skipped_docs' lists and returns their contents.
    """
    errors = []
    metadata = node_metadata.get(OperatorConstants.Metadata.NODE_METADATA, {})
    for field in [Metrics.External.FAILED_DOCS, Metrics.External.SKIPPED_DOCS]:
        if field in metadata and isinstance(metadata[field], list) and metadata[field]:
            errors.extend(metadata.get(field, [f"Unable to find details of {field}."]))
    return errors


def _count_and_remove_lists(*, node_info: dict, keys_to_count: list) -> None:
    """
    Converts lists in node_info to count values and removes the original lists.
    """
    _key_rename = {"total_docs": Metrics.External.TOTAL_DOCS}
    for key in keys_to_count:
        if key in node_info and isinstance(node_info[key], list):
            count_key = _key_rename.get(key, f"{key}_count")
            node_info[count_key] = len(node_info[key])
            del node_info[key]


def format_node_stats(*, node_stats: dict, node_sequence: list) -> str:
    """
    Formats node statistics into a readable JSON string.
    Keeps node order and replaces document ID lists with counts for clarity.
    """
    keys_to_count = ["total_docs", "docs_completed", "skipped_docs", "failed_docs"]
    new_node_stats = []

    for node in node_sequence:
        if node not in node_stats:
            continue  # Skip nodes not present in stats

        node_stat = node_stats[node]
        if isinstance(node_stat, NodeStats):
            node_info = copy.deepcopy(node_stat.model_dump())
        else:
            node_info = copy.deepcopy(node_stat)

        metadata = node_info.get(OperatorConstants.Metadata.NODE_METADATA, {})
        if node_info.get(Metrics.External.START_TIME):
            node_info[Metrics.External.START_TIME] = datetime.datetime.fromtimestamp(
                node_info[Metrics.External.START_TIME], tz=datetime.UTC
            ).strftime("%Y-%m-%d %H:%M:%S")
        if node_info.get(Metrics.External.END_TIME):
            node_info[Metrics.External.END_TIME] = datetime.datetime.fromtimestamp(
                node_info[Metrics.External.END_TIME], tz=datetime.UTC
            ).strftime("%Y-%m-%d %H:%M:%S")
        # Extract and append document-level errors if present
        if metadata:
            errors = _extract_document_level_errors(node_metadata=metadata)
            if errors:
                node_info.setdefault("document_level_errors", []).extend(errors)
            node_info.pop(OperatorConstants.Metadata.NODE_METADATA, None)  # Remove metadata after processing

        # Replace document ID lists with their counts
        _count_and_remove_lists(node_info=node_info, keys_to_count=keys_to_count)

        # Append formatted node info using its name as key
        new_node_stats.append({node_info.get(OperatorConstants.Columns.NAME): node_info})

    return json.dumps(new_node_stats, indent=6)


def format_operator_logs(*, job_id: str, job_stats: dict, node_sequence: list | None = None) -> str:
    """Format operator logs."""
    status = job_stats.get("status")
    job_status = status.value if status is not None and isinstance(status, ExecutionStatus) else status

    if node_sequence is None:
        job_run_id_value = job_stats.get(DocpipeConstants.JOB_RUN_ID)
        if job_run_id_value:
            node_sequence = retrieve_operators_sequence(job_id=job_id, job_run_id=job_run_id_value)
        else:
            node_sequence = []

    node_stats_value = job_stats.get("node_stats")
    if node_stats_value:
        node_stats = format_node_stats(node_stats=node_stats_value, node_sequence=node_sequence)
    else:
        node_stats = ""
    return f"""
>>> The flow execution is {job_status}.
>>> Job Statistics:
    > Job ID          : {job_id}
    > Job Run ID      : {job_stats.get(DocpipeConstants.JOB_RUN_ID)}
    > Status          : {job_status}
    > Message         : {job_stats.get("message")}
    > End Time        : {epoch_to_datetime(epoch_time=job_stats.get(Metrics.External.END_TIME))}
    > Start Time      : {epoch_to_datetime(epoch_time=job_stats.get(Metrics.External.START_TIME))}
    > Duration        : {job_stats.get("duration"):.2f} seconds
    > Total Docs      : {job_stats.get(Metrics.External.TOTAL_DOCS_COUNT_FROM_LOGS)}
    > Processed Docs  : {job_stats.get(Metrics.External.PROCESSED_DOCS)}
    > Failed Docs     : {job_stats.get(Metrics.External.FAILED_DOCS)}
    > Skipped Docs     : {job_stats.get(Metrics.External.SKIPPED_DOCS)}
    > Deleted Docs    : {job_stats.get(Metrics.External.DELETED_DOC_COUNT, 0)}
    > Total Pages Processed : {job_stats.get("total_pages_processed")}
    > Node Statistics :
    {node_stats}
    >>> ===============================================================
    """
