# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Non-Recoverable Document Utilities

Utilities for detecting and tracking documents with permanent failures that should not be reprocessed.
These utilities help identify documents with issues like password protection, corruption, or zero-byte files
that cannot be fixed by retrying the extraction.
"""

import pyarrow as pa

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


def is_non_recoverable_error(error_message: str, *, failure_reason: str | None = None) -> bool:
    """
    Check if error message indicates a non-recoverable error.

    Non-recoverable errors are permanent failures that won't be fixed by retrying:
    - Password-protected/encrypted documents
    - Zero-byte/empty files
    - Corrupted or malformed documents
    - Docling/PDFium conversion failures

    A failure with an explicit recoverable ``failure_reason`` (for example ``password_required``
    from in-memory decryption) is never non-recoverable, because a configuration change such as
    adding a password fixes it on the next run.

    Args:
        error_message: Error message from extraction process
        failure_reason: Explicit failure reason code set by the producer of the error, if any

    Returns:
        True if error is non-recoverable, False otherwise

    Examples:
        >>> is_non_recoverable_error("Failed to load document (PDFium: Incorrect password error)")
        True
        >>> is_non_recoverable_error("Network timeout")
        False
    """
    if failure_reason in OperatorConstants.Extraction.RECOVERABLE_FAILURE_REASONS:
        return False

    if not error_message:
        return False

    error_lower = error_message.lower()

    # Based on actual Docling and PDFium error messages:
    # - "PDF document is encrypted/password protected"
    # - "Failed to load document (PDFium: Data format error)"
    # - "Failed to load document (PDFium: Incorrect password error)"
    # - "Input document <filename> is not valid"
    # - "Extracted content is empty"
    # - "File size is 0"

    non_recoverable_keywords = [
        "password",
        "encrypted",
        "password protected",
        "password-protected",
        "file size is 0",
        "corrupted",
        "malformed",
        "pdfium: data format error",
        "pdfium: incorrect password",
        "failed to load document",
        "extracted content is empty",
        "input document",
        "is not valid",
    ]

    return any(pattern in error_lower for pattern in non_recoverable_keywords)


def extract_non_recoverable_rows(*, table: pa.Table, non_recoverable_doc_ids: list[int]) -> pa.Table:
    """
    Extract row data for non-recoverable error documents.

    This utility function extracts only the essential columns (id, name, modified_time)
    for documents that have non-recoverable errors, to be saved in incremental metadata.

    Args:
        table: PyArrow table containing all documents
        non_recoverable_doc_ids: List of row indices for non-recoverable errors

    Returns:
        PyArrow table with only id, name, modified_time columns

    Examples:
        >>> non_rec_table = extract_non_recoverable_rows(
        ...     table=table,
        ...     non_recoverable_doc_ids=[0, 5, 10]
        ... )
        >>> print(non_rec_table.column_names)
        ['id', 'name', 'modified_time']
    """
    columns_to_keep = [
        OperatorConstants.Columns.ID,
        OperatorConstants.Columns.NAME,
        OperatorConstants.Metadata.MODIFIED_TIME,
    ]

    # Filter to only columns that exist in the table
    existing_columns = [col for col in columns_to_keep if col in table.column_names]

    if not existing_columns:
        logger.warning("No standard columns (id, name, modified_time) found in table for non-recoverable docs")
        return pa.table({})

    return table.select(existing_columns).take(non_recoverable_doc_ids)


def process_non_recoverable_errors(
    *, table: pa.Table, non_recoverable_doc_ids: list[int], metadata: dict, common_log_arguments: dict
) -> dict:
    """
    Process non-recoverable error documents.

    Extracts row data for non-recoverable errors and stores in metadata
    for orchestrator to save to incremental metadata.

    Args:
        table: PyArrow table containing all documents
        non_recoverable_doc_ids: List of row indices for non-recoverable errors
        metadata: Metadata dictionary to update (will be moved to internal_metadata by orchestrator)
        common_log_arguments: Common logging arguments for structured logging

    Returns:
        Updated metadata dictionary

    Examples:
        >>> metadata = process_non_recoverable_errors(
        ...     table=table,
        ...     non_recoverable_doc_ids=[0, 5],
        ...     metadata={},
        ...     common_log_arguments={"job_id": "123"}
        ... )
        >>> assert Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE in metadata
    """
    if not non_recoverable_doc_ids:
        logger.debug("No non-recoverable error documents to track", extra=common_log_arguments)
        return metadata

    # Extract row data for non-recoverable docs
    non_recoverable_rows_table = extract_non_recoverable_rows(
        table=table, non_recoverable_doc_ids=non_recoverable_doc_ids
    )

    if non_recoverable_rows_table.num_rows == 0:
        logger.warning(
            "Could not extract row data for non-recoverable docs (missing required columns)", extra=common_log_arguments
        )
        return metadata

    # Store in metadata using internal metrics key (won't show in UI)
    # The orchestrator's remove_internal_metrics_from_metadata() will move this to internal_metadata
    metadata[Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE] = non_recoverable_rows_table

    logger.info(
        "Tracked %s non-recoverable error documents in internal metadata",
        non_recoverable_rows_table.num_rows,
        extra=common_log_arguments,
    )

    return metadata
