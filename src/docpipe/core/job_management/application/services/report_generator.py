"""
Job Report Generator Module

This module provides functionality to generate CSV reports for Docpipe job runs.
The report includes details about documents discovered, ingested, skipped, and failed during job execution.

Report persistence is delegated to the ContentStoragePort so storage backends
can be swapped without modifying this module.
"""

import csv
import io
import re
import time
import typing
from datetime import UTC
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from fastapi.responses import StreamingResponse

from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.exceptions.docpipe_exceptions import JobRunInvalidStateException, JobRunNotFoundException
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.dag_utils import identify_ingest_and_destination_nodes

logger = get_logger()

# Constants for report generation
GENERIC_SKIP_MESSAGE = "Document skipped during processing"
GENERIC_FAILURE_MESSAGE = "Job failed before document reached destination"


def _build_node_metadata_list(*, node_stats: dict) -> list[dict]:
    """Build the node_metadata_list expected by JobReportGenerator from node_stats.

    Each entry is the ``NodeMetadataItem``-shaped dict stored on each NodeStats
    (i.e. ``{"id": ..., "operator": ..., "node_metadata": {...}}``) — the same
    shape produced by the on-the-fly path in ``flow_execution_event_handler.py``.
    ``_extract_reason_from_node_metadata`` then reaches ``failed_docs``/``skipped_docs``
    via ``entry["node_metadata"]["failed_docs"]``.
    """
    result = []
    for node_stat in node_stats.values():
        node_metadata = (
            node_stat.get("node_metadata") if isinstance(node_stat, dict) else getattr(node_stat, "node_metadata", None)
        )
        if node_metadata:
            result.append(node_metadata)
    return result


class JobReportGenerator:
    """
    Generates CSV reports for job runs containing document processing details.

    The report format is one row per document with the following columns:
    - GUID: Document identifier
    - File name: Document name
    - Status: Ingested/Failed/Skipped
    - Status reason: Reason for failure or skipping
    - Time stamp: Processing timestamp
    - Pages: Number of pages (if available)
    - Processing time: Time taken to process (in seconds)
    """

    # CSV column headers - one row per document format
    HEADERS: typing.ClassVar[list[str]] = [
        "GUID",
        "File name",
        "Status",
        "Status reason",
        "Time stamp",
        "Pages",
        "Processing time (in seconds)",
    ]

    def __init__(
        self,
        *,
        job_stats: JobStats,
        flow_def: dict | None = None,
        dag_nodes: list[dict] | None = None,
        node_metadata_list: list[dict[str, Any]] | None = None,
    ):
        """
        Initialize the report generator.

        Args:
            job_stats: Job statistics containing document processing information
            flow_def: Flow definition containing DAG nodes (deprecated, use dag_nodes)
            dag_nodes: List of DAG nodes for context (preferred)
            node_metadata_list: Optional list of node metadata (for non-batched flows only)
        """
        self.job_stats = job_stats

        # Support both flow_def (old) and dag_nodes (new) parameters
        if dag_nodes is not None:
            self.dag_nodes = dag_nodes
        elif flow_def is not None:
            self.dag_nodes = flow_def.get("dag", {}).get("nodes", [])
        else:
            self.dag_nodes = []

        self.node_metadata_list = node_metadata_list or []
        self.node_id_to_name = self._build_node_name_map()
        self.job_id = job_stats.job_id
        self.job_run_id = job_stats.job_run_id

    @staticmethod
    def download_report(*, job_run_id: str, job_stats_service) -> StreamingResponse:
        """
        Download job run report as a CSV file.

        This method encapsulates the entire workflow for report download:
        1. Check if report already exists (fast path)
        2. Validate job status (must be in terminal state)
        3. Check parquet file availability
        4. Generate report on-demand if needed
        5. Return streaming response

        Args:
            job_run_id: Job run identifier
            job_stats_service: Service for fetching job stats and flow definition

        Returns:
            StreamingResponse: CSV file download

        Raises:
            JobRunNotFoundException: If job run not found (404)
            JobRunInvalidStateException: If job not completed (425)
            JobRunOperationFailedException: If parquet data unavailable (422) or generation fails (500)
        """
        from docpipe.core.constants import TERMINAL_JOB_STATUSES
        from docpipe.core.job_management.application.services.report_utils import (
            check_parquet_availability,
            create_csv_streaming_response,
            read_report_from_storage,
        )
        from docpipe.core.models.session_info import update_session_info
        from docpipe.exceptions.docpipe_exceptions import JobRunOperationFailedException
        from docpipe.utils.orchestration.dag_utils import extract_dag_nodes

        logger.info("Downloading job report for job run: %s", job_run_id)

        # Step 1: Fetch job stats and validate status first
        job_stats = job_stats_service.get_job(job_run_id=job_run_id, include_node_stats=False)
        if not job_stats:
            raise JobRunNotFoundException(message=f"Job run {job_run_id} not found", job_run_id=job_run_id)

        # Check if job is in terminal status (before checking cached report)
        if job_stats.status not in TERMINAL_JOB_STATUSES:
            raise JobRunInvalidStateException(
                message=f"Cannot generate report: job run {job_run_id} is not yet completed (status: {job_stats.status}). "
                f"Please wait for the job to complete before requesting the report.",
                job_run_id=job_run_id,
                current_state=job_stats.status,
                status_code=425,
            )

        # Populate SessionInfo so all storage helpers (read_report_from_storage,
        # check_parquet_availability, save_report_to_file) resolve the correct
        # job_id/job_run_id from context rather than falling back to None.
        update_session_info(job_id=job_stats.job_id, job_run_id=job_run_id)

        # Step 2: Check if report already exists (fast path after status validation)
        report_content = read_report_from_storage()

        # If report exists, return it immediately
        if report_content:
            logger.info("Report found in storage for job run: %s", job_run_id)
            return create_csv_streaming_response(content=report_content, job_run_id=job_run_id)

        # Step 3: Report doesn't exist - proceed with generation
        logger.info("Report not found, proceeding with generation for %s", job_run_id)

        # Step 4: Check if parquet files are available before expensive operations
        parquet_available, error_message = check_parquet_availability()
        if not parquet_available:
            logger.info("Parquet files not available for job run %s: %s", job_run_id, error_message)
            raise JobRunOperationFailedException(
                message=f"Cannot generate report: {error_message}. "
                f'Job report is available only when "Intermediate data storage" is set to "Container file system" in "Flow run properties".',
                job_run_id=job_run_id,
                operation="generate_report",
                status_code=422,
            )

        # Step 5: Generate report on-demand (requires full job_stats with node_stats + batch_node_stats)
        logger.info("Generating report on-demand for job run %s", job_run_id)
        try:
            # include_batch_stats=True is required for correct micro-batch parquet path construction
            job_stats = job_stats_service.get_job(
                job_run_id=job_run_id, include_node_stats=True, include_batch_stats=True
            )

            # Fetch flow definition and reconstruct DAG nodes with real node UUIDs
            flow_definition = job_stats_service.get_flow_definition(job_run_id=job_run_id)
            dag_nodes = extract_dag_nodes(flow_definition=flow_definition, node_stats=job_stats.node_stats)

            # Build node_metadata_list so failure/skip reasons are available (same as on-the-fly path)
            node_metadata_list = _build_node_metadata_list(node_stats=job_stats.node_stats)

            # Generate report
            generator = JobReportGenerator(
                job_stats=job_stats, dag_nodes=dag_nodes, node_metadata_list=node_metadata_list
            )
            csv_content = generator.generate_csv_content()

            if not csv_content:
                logger.warning("Report generation skipped for job run %s - no document data available", job_run_id)
                raise JobRunOperationFailedException(
                    message="No document data found for this job run. The job may not have processed any documents.",
                    job_run_id=job_run_id,
                    operation="generate_report",
                    status_code=422,
                )

            # Save to file for future requests (pass content to avoid generating twice)
            generator.save_report_to_file(csv_content=csv_content)

            logger.info("On-demand report generated and saved for job run: %s", job_run_id)

        except JobRunOperationFailedException:
            raise
        except Exception as e:
            logger.exception("Failed to generate report on-demand for %s: %s", job_run_id, e)
            raise JobRunOperationFailedException(
                message=f"Failed to generate report: {e!s}", job_run_id=job_run_id, operation="generate_report"
            ) from e

        # Return generated report
        logger.info("Successfully generated report for job run: %s", job_run_id)
        return create_csv_streaming_response(content=csv_content, job_run_id=job_run_id)

    def generate_report_data(self) -> list[dict[str, str]]:
        """
        Generate report data from job statistics.

        Creates one row per document with columns:
        - GUID: Document identifier
        - File name: Document name
        - Status: Ingested/Failed/Skipped
        - Status reason: Reason for failure or skipping
        - Time stamp: Processing timestamp
        - Pages: Number of pages (if available)
        - Processing time: Time taken to process (if available)

        Returns:
            List of dictionaries containing report rows (one per document)
        """
        start_time = time.time()

        # Step 1: Initialize documents from ingest operator
        all_docs = self._initialize_docs_from_ingest()

        if not all_docs:
            logger.warning("No documents found in ingest operator")
            return []

        # Step 2: Update page counts
        self._update_page_counts(all_docs)

        # Step 3: Calculate processing times
        self._calculate_processing_times(all_docs)

        # Step 4: Update document status
        self._update_document_status(all_docs)

        # Create report rows
        report_rows = self._create_report_rows(all_docs)

        elapsed = time.time() - start_time
        logger.info("Generated report data for %s documents in %.2fs", len(report_rows), elapsed)
        return report_rows

    def generate_csv_content(self) -> str:
        """
        Generate CSV content as a string.

        Returns:
            CSV content as string, or empty string if no document data was
            found for this job run. Callers must check for an empty return
            value and skip persisting to storage.
        """
        logger.debug("Generating CSV content")

        report_data = self.generate_report_data()

        if not report_data:
            logger.warning("No document data found for this job run - skipping report generation")
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.HEADERS)
        writer.writeheader()
        writer.writerows(report_data)

        return output.getvalue()

    def save_report_to_file(self, *, csv_content: str | None = None) -> str:
        """
        Save report via the configured ContentStoragePort adapter.

        Reads job_id and job_run_id from SessionInfo.

        Args:
            csv_content: Pre-generated CSV content. If None, generates internally.

        Returns:
            Storage path or object key where the report was written
        """
        from docpipe.core.job_management.adapters.config.report_storage_factory import get_report_storage
        from docpipe.core.models.session_info import get_session_info

        if csv_content is None:
            csv_content = self.generate_csv_content()

        session = get_session_info()
        return get_report_storage().write_text(
            collection=f"{session.job_id}/{session.job_run_id}",
            file_name=f"job_report_{session.job_run_id}.csv",
            content=csv_content,
        )

    def _build_node_name_map(self) -> dict[str, str]:
        """Build mapping from node ID to node name."""
        node_map = {}
        for node in self.dag_nodes:
            node_id = node.get("id")
            node_name = node.get("name")
            if node_id and node_name:
                node_map[node_id] = node_name
        return node_map

    def _get_ingest_node_id(self) -> str | None:
        """
        Find the ingest operator node ID.

        Uses the shared utility function to identify the ingest node
        (node with no input edges).
        """
        ingest_node_id, _ = identify_ingest_and_destination_nodes(self.dag_nodes)
        if ingest_node_id:
            logger.debug("Found ingest node: %s", ingest_node_id)
        else:
            logger.warning("Could not find ingest node")
        return ingest_node_id

    def _get_destination_node_ids(self) -> list[str]:
        """
        Find destination operator node IDs.

        Uses the shared utility function to identify destination nodes
        (nodes with no output edges).
        """
        _, destination_node_ids = identify_ingest_and_destination_nodes(self.dag_nodes)
        return destination_node_ids

    def _get_actual_batch_nums(self, node_id: str) -> set:
        """
        Get actual batch numbers for a node from batch_node_stats.

        Logic:
        - If batch_node_stats has this node: Extract batch_num from each batch object
        - Otherwise: Return {None} (no micro-batching, no batch subdirectory in parquet path)

        Args:
            node_id: Node identifier

        Returns:
            Set of batch numbers (integers) or {None} for non-batched flows
        """
        # Extract batch numbers from batch_node_stats if available
        if self.job_stats.batch_node_stats and node_id in self.job_stats.batch_node_stats:
            batch_nums = set()
            for _batch_id, batch_stats in self.job_stats.batch_node_stats[node_id].items():
                batch_num = self._get_batch_attr(batch_stats, "batch_num")
                if batch_num is not None:
                    batch_nums.add(batch_num)

            if batch_nums:
                logger.info(
                    "Found %s batches for node %s from batch_node_stats: %s",
                    len(batch_nums),
                    node_id,
                    sorted(batch_nums),
                )
                return batch_nums

        # No micro-batching - return {None} to indicate no batch subdirectory in parquet path
        logger.info("No batch data for node %s - treating as non-batched (no batch subdirectory)", node_id)
        return {None}

    def _find_extract_operator(self) -> tuple[str | None, str | None]:
        """
        Find the extract operator node ID and name by checking the operator type.

        Uses the stable 'op' or 'op_type' field from dag_nodes rather than the
        user-visible node name, since users can rename operators arbitrarily.

        Returns:
            Tuple of (node_id, node_name) or (None, None) if not found
        """
        if not self.dag_nodes:
            logger.warning("No dag_nodes available to find extract operator")
            return None, None

        for node in self.dag_nodes:
            node_id = node.get("id")
            if not node_id:
                continue  # Skip nodes without IDs

            # Try multiple field names for operator type
            op_type = node.get("operator", "") or node.get("op", "")

            # Check app_data if op not found
            if not op_type:
                app_data = node.get("app_data", {})
                op_type = app_data.get("op_type", "")

            # Check if this is an extract operator (e.g., extract_cpd, extract_cloud)
            if op_type and "extract" in op_type.lower():
                node_name = self.node_id_to_name.get(node_id, "Unknown")
                logger.info("Found extract operator: %s (id: %s, op_type: %s)", node_name, node_id, op_type)
                return node_id, node_name

        logger.warning("No extract operator found in dag_nodes")
        return None, None

    @staticmethod
    def _get_timestamp_from_modified_time(modified_time: Any, doc_id: str) -> str:
        """
        Convert modified_time to YYYY-MM-DD:HH:MM:SS format.

        Handles both epoch-seconds (int/float) and string timestamps.
        For numeric timestamps ≥ 1e10, assumes milliseconds and divides by 1000.

        Args:
            modified_time: Timestamp value (int, float, or string)
            doc_id: Document ID for logging

        Returns:
            Formatted timestamp string in YYYY-MM-DD:HH:MM:SS format, or empty string on error
        """
        try:
            if isinstance(modified_time, (int, float)):
                from datetime import datetime

                # Epoch-ms if value >= 1e10 (CAMS/CPD assets returns milliseconds;
                # local/S3 operators return seconds). Divide by 1000 to normalise.
                ts = modified_time / 1000.0 if modified_time >= 1e10 else float(modified_time)
                dt = datetime.fromtimestamp(ts, tz=UTC)
                return dt.strftime("%Y-%m-%d:%H:%M:%S")
            if isinstance(modified_time, str):
                return modified_time
            return ""
        except Exception as e:
            logger.debug("Could not convert timestamp for doc %s: %s", doc_id, e)
            return ""

    @staticmethod
    def _create_doc_entry(*, doc_name: str, modified_time: Any, timestamp_str: str) -> dict[str, Any]:
        """Create initial document entry."""
        return {
            "name": doc_name,
            "status": "",
            "reason": "",
            "timestamp": timestamp_str,
            "pages": "",
            "processing_time": "",
            "modified_time": modified_time,
        }

    def _get_batch_attr(self, batch_stats: Any, attr: str, default: Any = None) -> Any:
        """
        Safely get attribute from batch_stats whether it's a dict or NodeStats object.

        Args:
            batch_stats: Either a dict or NodeStats object
            attr: Attribute name to retrieve
            default: Default value if attribute not found

        Returns:
            Attribute value or default
        """
        if isinstance(batch_stats, dict):
            return batch_stats.get(attr, default)
        return getattr(batch_stats, attr, default)

    def _find_first_batching_operator(self) -> str | None:
        """
        Find the first batching operator in the flow where document processing started.

        Returns:
            Node ID of the first batching operator, or None if not a batching flow
        """
        if not self.job_stats.batch_node_stats:
            return None

        nodes_with_batches = list(self.job_stats.batch_node_stats.keys())

        # Use DAG nodes to find the first batching operator in flow order
        if self.dag_nodes:
            for node in self.dag_nodes:
                node_id = node.get("id")
                if node_id in nodes_with_batches:
                    first_batch_stats = next(iter(self.job_stats.batch_node_stats[node_id].values()))
                    node_name = self._get_batch_attr(first_batch_stats, "name", "unknown")
                    logger.info("Found first batching operator: %s (id: %s)", node_name, node_id)
                    return node_id

        # If no DAG nodes, use first node in batch_node_stats
        first_batch_node = nodes_with_batches[0]
        first_batch_stats = next(iter(self.job_stats.batch_node_stats[first_batch_node].values()))
        node_name = self._get_batch_attr(first_batch_stats, "name", "unknown")
        logger.info("Using first node with batch info: %s (id: %s)", node_name, first_batch_node)
        return first_batch_node

    def _get_all_batch_docs(self, batch_stats: Any) -> set[str]:
        """Get all documents in a batch (completed, failed, and skipped)."""
        batch_docs = set(self._get_batch_attr(batch_stats, "total_docs") or [])
        batch_docs.update(self._get_batch_attr(batch_stats, "failed_docs") or [])
        batch_docs.update(self._get_batch_attr(batch_stats, "skipped_docs") or [])
        return batch_docs

    def _get_ingest_start_time(self) -> float:
        """Get ingest node start time from node_stats."""
        ingest_node_id = self._get_ingest_node_id()
        ingest_start_time = 0.0

        if ingest_node_id and ingest_node_id in self.job_stats.node_stats:
            ingest_start_time = self.job_stats.node_stats[ingest_node_id].start_time or 0.0
        else:
            logger.warning("Ingest node '%s' not found in node_stats", ingest_node_id)

        return ingest_start_time

    def _find_doc_end_time_in_destinations(
        self, doc_id: str, batch_id: str, destination_nodes: list[str], ingest_start_time: float
    ) -> tuple[float, bool]:
        """Find document end time by checking destination nodes."""
        for dest_node_id in destination_nodes:
            if dest_node_id not in self.job_stats.batch_node_stats:
                continue

            dest_node_batches = self.job_stats.batch_node_stats[dest_node_id]
            if batch_id not in dest_node_batches:
                continue

            dest_batch_stats = dest_node_batches[batch_id]
            dest_all_docs = self._get_all_batch_docs(dest_batch_stats)

            if doc_id in dest_all_docs:
                end_time = self._get_batch_attr(dest_batch_stats, "end_time")
                return (end_time if end_time else ingest_start_time, True)

        return (ingest_start_time, False)

    def _find_doc_max_end_time_in_all_nodes(self, doc_id: str, batch_id: str, ingest_start_time: float) -> float:
        """Find document's maximum end time by searching all nodes."""
        max_end_time = ingest_start_time

        for _node_id, node_batches in self.job_stats.batch_node_stats.items():
            if batch_id not in node_batches:
                continue

            node_batch_stats = node_batches[batch_id]
            node_all_docs = self._get_all_batch_docs(node_batch_stats)

            if doc_id in node_all_docs:
                node_end_time = self._get_batch_attr(node_batch_stats, "end_time") or 0.0
                if node_end_time > max_end_time:
                    max_end_time = node_end_time

        return max_end_time

    def _process_batch_documents(
        self,
        batch_id: str,
        batch_stats: Any,
        destination_nodes: list[str],
        ingest_start_time: float,
        doc_to_processing_time: dict[str, str],
    ) -> None:
        """Process all documents in a batch and calculate their processing times."""
        batch_docs = self._get_all_batch_docs(batch_stats)
        if not batch_docs:
            return

        for doc_id in batch_docs:
            # Find document end time
            batch_end_time, found_in_destination = self._find_doc_end_time_in_destinations(
                doc_id, batch_id, destination_nodes, ingest_start_time
            )

            if not found_in_destination:
                batch_end_time = self._find_doc_max_end_time_in_all_nodes(doc_id, batch_id, ingest_start_time)

            # Calculate processing time
            processing_time_seconds = max(0, int(batch_end_time - ingest_start_time))
            doc_to_processing_time[doc_id] = str(processing_time_seconds)

    def _collect_destination_times(self, ingest_start_time: float, destination_nodes: list[str]) -> dict[str, str]:
        """Collect processing times from destination nodes."""
        doc_to_processing_time = {}

        for dest_node_id in destination_nodes:
            if dest_node_id not in self.job_stats.node_stats:
                continue

            dest_stats = self.job_stats.node_stats[dest_node_id]
            if dest_stats.docs_completed and dest_stats.end_time:
                for doc_id in dest_stats.docs_completed:
                    processing_time_seconds = max(0, int(dest_stats.end_time - ingest_start_time))
                    doc_to_processing_time[doc_id] = str(processing_time_seconds)

        return doc_to_processing_time

    def _collect_all_docs_from_node(self, node_stats: NodeStats) -> set[str]:
        """Collect all document IDs from a node."""
        all_docs = set()
        if node_stats.total_docs:
            all_docs.update(node_stats.total_docs)
        if node_stats.failed_docs:
            all_docs.update(node_stats.failed_docs)
        if node_stats.skipped_docs:
            all_docs.update(node_stats.skipped_docs)
        return all_docs

    def _track_max_end_times(self) -> dict[str, float]:
        """Track maximum end time for all documents across all nodes."""
        doc_to_max_end_time: dict[str, float] = {}

        for node_stats in self.job_stats.node_stats.values():
            if not node_stats.end_time:
                continue

            all_docs = self._collect_all_docs_from_node(node_stats)

            for doc_id in all_docs:
                if doc_id not in doc_to_max_end_time or node_stats.end_time > doc_to_max_end_time[doc_id]:
                    doc_to_max_end_time[doc_id] = node_stats.end_time

        return doc_to_max_end_time

    def _collect_doc_end_times(
        self, ingest_start_time: float, destination_nodes: list[str]
    ) -> tuple[dict[str, str], dict[str, float]]:
        """Collect document end times from all nodes."""
        doc_to_processing_time = self._collect_destination_times(ingest_start_time, destination_nodes)
        doc_to_max_end_time = self._track_max_end_times()
        return doc_to_processing_time, doc_to_max_end_time

    def _build_doc_to_batch_mapping_fallback(self) -> dict[str, str]:
        """
        Fallback method for building document processing time when batching operators are not found.
        Uses node-level timing instead of batch-level timing.
        """
        logger.info("Using node-level timing fallback")

        ingest_start_time = self._get_ingest_start_time()
        destination_nodes = self._get_destination_node_ids() or []

        # Collect all documents and their end times
        doc_to_processing_time, doc_to_max_end_time = self._collect_doc_end_times(ingest_start_time, destination_nodes)

        # For documents not found in destination nodes, use maximum end time
        for doc_id, max_end_time in doc_to_max_end_time.items():
            if doc_id not in doc_to_processing_time:
                processing_time_seconds = max(0, int(max_end_time - ingest_start_time))
                doc_to_processing_time[doc_id] = str(processing_time_seconds)

        logger.info("Calculated end-to-end processing time for %s documents", len(doc_to_processing_time))
        return doc_to_processing_time

    def _build_doc_to_batch_mapping(self) -> dict[str, str]:
        """
        Build a mapping of document IDs to processing time from batch data.

        Logic:
        - If batch_node_stats available (micro-batching enabled): Use batch-level timing
        - If batch_node_stats NOT available: Fall back to node-level timing

        Returns:
            Dictionary mapping doc_id to processing_time string (e.g., "45")
        """
        # Find first batching operator (None when batch_node_stats is empty)
        first_batching_node = self._find_first_batching_operator()
        if not first_batching_node:
            logger.info("No batch_node_stats available, using node-level timing")
            return self._build_doc_to_batch_mapping_fallback()

        # Get destination nodes and ingest start time
        destination_nodes = self._get_destination_node_ids() or []
        if not destination_nodes:
            logger.warning("No destination nodes found in DAG")

        logger.info(
            "Using batch-level timing. First batching operator: %s, Destination nodes: %s",
            first_batching_node,
            destination_nodes,
        )

        ingest_start_time = self._get_ingest_start_time()

        # Build mappings from batch data
        doc_to_processing_time: dict[str, str] = {}
        first_node_batches = self.job_stats.batch_node_stats[first_batching_node]

        for batch_id, batch_stats in first_node_batches.items():
            self._process_batch_documents(
                batch_id, batch_stats, destination_nodes, ingest_start_time, doc_to_processing_time
            )

        logger.info("Calculated processing time for %s documents", len(doc_to_processing_time))
        return doc_to_processing_time

    def _get_required_columns(self, node_id: str) -> list[str]:
        """
        Get list of columns required for report generation based on node type.

        Args:
            node_id: Node identifier

        Returns:
            List of column names to read from parquet
        """
        # Identify node types from DAG
        ingest_id, extract_id = self._identify_key_node_ids()

        # Ingest node: document metadata
        if node_id == ingest_id:
            return ["id", "name", "modified_time"]

        # Extract node: page counts
        if node_id == extract_id:
            return ["id", "pages_processed"]

        # Default: return id only
        return ["id"]

    def _identify_key_node_ids(self) -> tuple[str | None, str | None]:
        """
        Identify ingest and extract node IDs from DAG.

        Returns:
            Tuple of (ingest_node_id, extract_node_id)
        """
        ingest_id = self._get_ingest_node_id()
        extract_id, _ = self._find_extract_operator()
        return ingest_id, extract_id

    def _read_parquet_file(
        self, node_id: str, batch_num: int | None = None, branch_index: int = 0
    ) -> dict[str, dict[str, Any]]:
        """
        Read parquet file for a node with column projection for performance.

        Only reads columns needed for report generation:
        - Ingest node: id, name, modified_time
        - Extract node: id, pages

        Args:
            node_id: Node identifier
            batch_num: Batch number (for micro-batched flows)
            branch_index: Branch index (for branching flows)

        Returns:
            Dictionary of {doc_id: row_data}
        """
        doc_data: dict[str, dict[str, Any]] = {}

        try:
            node_name = self.node_id_to_name.get(node_id, node_id)

            # Sanitize exactly as add_node_name_to_output_folder does so the
            # folder name matches what the orchestrator actually wrote
            sanitized_name = re.sub(r"\W+", "_", node_name)
            node_name_with_branch = f"{sanitized_name}_{branch_index}"
            data_path = Path(get_data_path()) / self.job_id / self.job_run_id / "data" / node_name_with_branch

            if batch_num is not None:
                file_path = data_path / str(batch_num) / "output.parquet"
            else:
                file_path = data_path / "output.parquet"

            logger.info(
                "Reading parquet: file=%s (node=%s branch=%s batch=%s)",
                file_path,
                node_name,
                branch_index,
                batch_num,
            )

            if not Path(file_path).exists():
                logger.warning("Parquet file not found: %s", file_path)
                return doc_data

            # Read only required columns for performance
            columns = self._get_required_columns(node_id)
            table = pq.read_table(file_path, columns=columns)

            for row in table.to_pylist():
                doc_id = row.get("id")
                if doc_id:
                    doc_data[doc_id] = row

            logger.info(
                "Read %d documents from %s (columns=%s)",
                len(doc_data),
                file_path,
                columns,
            )

        except Exception as e:
            logger.exception("Error reading parquet for node %s: %s", node_id, e)

        return doc_data

    def _initialize_docs_from_ingest(self) -> dict[str, dict[str, Any]]:
        """
        Initialize document data from ingest operator parquet file.

        Returns:
            Dictionary mapping doc_id to document information
        """
        logger.info("Step 1: Reading document data from ingest operator parquet file")

        all_docs: dict[str, dict[str, Any]] = {}
        ingest_node_id = self._get_ingest_node_id()

        logger.info("Ingest node ID identified: %s", ingest_node_id)

        if not ingest_node_id:
            logger.warning("No ingest operator found in flow definition")
            return all_docs

        # Read parquet file from ingest operator
        logger.info("Reading parquet file for ingest node: %s", ingest_node_id)
        ingest_data = self._read_parquet_file(ingest_node_id)

        logger.info("Ingest data retrieved: %s documents", len(ingest_data))

        if not ingest_data:
            logger.warning(
                "No documents found in ingest parquet file for node %s. "
                "Ensure the flow completed successfully and generated parquet output files.",
                ingest_node_id,
            )
            return all_docs

        # Initialize documents from parquet data
        for doc_id, row_data in ingest_data.items():
            doc_name = row_data.get("name", doc_id)
            modified_time = row_data.get("modified_time")

            logger.info("Processing doc_id=%s, name=%s, modified_time=%s", doc_id, doc_name, modified_time)

            # Convert modified_time to ISO 8601 string
            timestamp_str = self._get_timestamp_from_modified_time(modified_time, doc_id)

            logger.info("Converted timestamp for doc %s: %s", doc_id, timestamp_str)

            all_docs[doc_id] = self._create_doc_entry(
                doc_name=doc_name, modified_time=modified_time, timestamp_str=timestamp_str
            )

        logger.info("Initialized %s documents from ingest operator parquet file", len(all_docs))
        logger.info("Sample document entry: %s", next(iter(all_docs.values())) if all_docs else "No docs")
        return all_docs

    def _update_page_count_from_parquet(self, all_docs: dict[str, dict[str, Any]], doc_id: str, row_data: dict) -> bool:
        """Update page count for a single document from parquet data."""
        if doc_id not in all_docs:
            logger.debug("Doc %s from extract parquet not in all_docs", doc_id)
            return False

        page_count = row_data.get("pages_processed") or row_data.get("page_count")

        if page_count is not None:
            all_docs[doc_id]["pages"] = str(page_count)
            logger.debug("Updated page count for doc %s: %s", doc_id, page_count)
            return True
        logger.debug("No page count found for doc %s. Available keys: %s", doc_id, list(row_data.keys()))
        return False

    def _read_page_counts_from_batches(
        self, all_docs: dict[str, dict[str, Any]], extract_node_id: str, batch_nums: set
    ) -> int:
        """Read page counts from all batches."""
        updated_count = 0

        for batch_num in sorted(batch_nums):
            logger.info("Reading extract operator batch %s", batch_num)
            extract_data = self._read_parquet_file(extract_node_id, batch_num=batch_num)

            if not extract_data:
                logger.warning("No data found in extract parquet file for batch %s", batch_num)
                continue

            logger.info("Extract data retrieved for batch %s: %s documents", batch_num, len(extract_data))

            for doc_id, row_data in extract_data.items():
                if self._update_page_count_from_parquet(all_docs, doc_id, row_data):
                    updated_count += 1

        return updated_count

    def _update_page_counts(self, all_docs: dict[str, dict[str, Any]]) -> None:
        """
        Read and update page counts for documents from extract operator parquet files.
        Page counts are always read from the extract operator.

        Args:
            all_docs: Dictionary of document information to update
        """
        logger.info("Step 2: Reading page counts from extract operator")
        logger.info("Total documents to update: %s", len(all_docs))
        logger.info("Document IDs in all_docs: %s", list(all_docs.keys()))

        # Read from extract operator
        extract_node_id, extract_node_name = self._find_extract_operator()
        logger.info("Extract node ID identified: %s (name: %s)", extract_node_id, extract_node_name)

        if not extract_node_id:
            logger.warning("No extract operator found in flow definition")
            logger.info("Available DAG nodes: %s", [(n.get("id"), n.get("name"), n.get("op")) for n in self.dag_nodes])
            return

        batch_nums = self._get_actual_batch_nums(extract_node_id)
        logger.info(
            "DEBUG: batch_node_stats keys: %s",
            list(self.job_stats.batch_node_stats.keys()) if self.job_stats.batch_node_stats else "None",
        )
        logger.info("DEBUG: Looking for extract node ID: %s", extract_node_id)
        logger.info("Will read %s batch(es) for extract operator: %s", len(batch_nums), sorted(batch_nums))

        updated_count = self._read_page_counts_from_batches(all_docs, extract_node_id, batch_nums)
        logger.info("Updated page counts for %s documents from extract parquet file(s)", updated_count)

    def _calculate_processing_times(self, all_docs: dict[str, dict[str, Any]]) -> None:
        """
        Calculate processing times for documents using batch-level or node-level timing.

        Args:
            all_docs: Dictionary of document information to update
        """
        logger.info("Step 3: Calculating processing times")

        # Build document to processing time mapping (handles both batched and non-batched flows)
        doc_to_processing_time = self._build_doc_to_batch_mapping()

        # Update all_docs with processing times
        for doc_id, processing_time in doc_to_processing_time.items():
            if doc_id in all_docs:
                all_docs[doc_id]["processing_time"] = processing_time

        logger.info("Calculated processing time for %s documents", len(doc_to_processing_time))

    def _build_status_lookup_sets(self) -> tuple[set[str], set[str], set[str]]:
        """
        Build lookup sets for document status determination.

        Returns:
            Tuple of (failed_docs, skipped_docs, destination_completed_docs)
        """
        failed_docs_global = set()
        skipped_docs_global = set()
        destination_completed_docs = set()

        # Collect failed and skipped docs from all nodes
        for node_id, node_stats in self.job_stats.node_stats.items():
            node_name = node_stats.name
            if node_stats.failed_docs:
                logger.info("Node %s (%s): %s failed docs", node_name, node_id, len(node_stats.failed_docs))
                failed_docs_global.update(node_stats.failed_docs)
            if node_stats.skipped_docs:
                logger.info("Node %s (%s): %s skipped docs", node_name, node_id, len(node_stats.skipped_docs))
                skipped_docs_global.update(node_stats.skipped_docs)

        # Collect completed docs from destination nodes.
        # A document in docs_completed was successfully processed regardless of the node's
        # overall status — a node can be "Failed" because other docs failed while some
        # completed successfully (e.g. opensearch fails for 10 docs but completes 2).
        destination_node_ids = self._get_destination_node_ids()
        logger.info("Destination node IDs: %s", destination_node_ids)

        for node_id in destination_node_ids:
            node_stats = self.job_stats.node_stats.get(node_id)
            if node_stats and node_stats.docs_completed:
                destination_completed_docs.update(node_stats.docs_completed)
                logger.info(
                    "Added %s docs_completed from destination node %s (status: %s)",
                    len(node_stats.docs_completed),
                    node_stats.name,
                    node_stats.node_status,
                )

        return failed_docs_global, skipped_docs_global, destination_completed_docs

    def _extract_reason_from_docs_list(self, docs: list, doc_id: str) -> str | None:
        """Extract reason from a list of document structures."""
        for doc_struct in docs:
            if isinstance(doc_struct, dict) and doc_struct.get("id") == doc_id:
                reason = doc_struct.get("reason")
                return str(reason) if reason else None
        return None

    def _extract_reason_from_node_metadata(self, doc_id: str, metric_key: str) -> str | None:
        """
        Extract failure/skip reason for a document from node_metadata_list.

        Searches all nodes for the document and returns the first matching reason found.
        Works for both batched and non-batched flows since node_metadata_list is pre-extracted
        from node_stats before the background thread starts.

        Args:
            doc_id: Document identifier
            metric_key: 'failed_docs' or 'skipped_docs'

        Returns:
            Reason string if found, None otherwise
        """
        for node_meta in self.node_metadata_list:
            if not isinstance(node_meta, dict):
                continue

            # Reasons are stored under nested node_metadata key
            nested_metadata = node_meta.get("node_metadata")
            if not isinstance(nested_metadata, dict):
                continue

            docs_list = nested_metadata.get(metric_key, [])
            reason = self._extract_reason_from_docs_list(docs_list, doc_id)
            if reason:
                return reason

        return None

    def _find_failure_reason(self, doc_id: str) -> str:
        """Find failure reason for a document from node_metadata_list."""
        reason = self._extract_reason_from_node_metadata(doc_id, "failed_docs")
        return reason if reason else GENERIC_FAILURE_MESSAGE

    def _find_skip_reason(self, doc_id: str) -> str:
        """Find skip reason for a document from node_metadata_list."""
        reason = self._extract_reason_from_node_metadata(doc_id, "skipped_docs")
        return reason if reason else GENERIC_SKIP_MESSAGE

    def _handle_unclassified_document(self, doc_id: str, doc_info: dict[str, Any]) -> None:
        """Handle documents that didn't reach destination and weren't explicitly marked."""
        from docpipe.core.constants.constants import ExecutionStatus

        if self.job_stats.status in [
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELED,
            ExecutionStatus.COMPLETED_WITH_ERRORS,
        ]:
            doc_info["status"] = "Failed"
            doc_info["reason"] = self._find_failure_reason(doc_id)
            logger.debug("Doc %s: Failed - job did not complete successfully", doc_id)
        else:
            doc_info["status"] = "Unknown"
            logger.warning("Doc %s: Unknown status - not in failed/skipped/completed sets", doc_id)

    def _update_document_status(self, all_docs: dict[str, dict[str, Any]]) -> None:
        """
        Calculate and update status and reason for all documents.

        Args:
            all_docs: Dictionary of document information to update
        """
        logger.info("Step 4: Calculating document status")

        failed_docs_global, skipped_docs_global, destination_completed_docs = self._build_status_lookup_sets()

        logger.info(
            "Status sets - Failed: %s, Skipped: %s, Completed: %s",
            len(failed_docs_global),
            len(skipped_docs_global),
            len(destination_completed_docs),
        )

        for doc_id, doc_info in all_docs.items():
            if doc_id in failed_docs_global:
                doc_info["status"] = "Failed"
                doc_info["reason"] = self._find_failure_reason(doc_id)
            elif doc_id in skipped_docs_global:
                doc_info["status"] = "Skipped"
                doc_info["reason"] = self._find_skip_reason(doc_id)
            elif doc_id in destination_completed_docs:
                doc_info["status"] = "Ingested"
            else:
                self._handle_unclassified_document(doc_id, doc_info)

        logger.info("Calculated status for %s documents", len(all_docs))

    def _create_report_rows(self, all_docs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
        """
        Create report rows from document data.

        Args:
            all_docs: Dictionary of document information

        Returns:
            List of dictionaries containing report rows
        """
        report_rows = []
        for doc_id, doc_info in all_docs.items():
            row = {
                "GUID": doc_id,
                "File name": doc_info["name"],
                "Status": doc_info["status"] or "Unknown",
                "Status reason": doc_info["reason"],
                "Time stamp": doc_info["timestamp"],
                "Pages": doc_info["pages"],
                "Processing time (in seconds)": doc_info["processing_time"],
            }
            report_rows.append(row)
        return report_rows
