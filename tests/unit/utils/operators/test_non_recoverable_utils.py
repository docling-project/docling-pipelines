# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for non-recoverable document utilities."""

from typing import Any

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.operators.non_recoverable_utils import (
    extract_non_recoverable_rows,
    is_non_recoverable_error,
    process_non_recoverable_errors,
)


@pytest.mark.parametrize(
    "error_message",
    [
        "Document is password protected",
        "Document is encrypted",
        "File size is 0",
        "Corrupted document",
        "Malformed document",
        "PDFium: Data format error",
        "Failed to load document",
        "Extracted content is empty",
        "Input document report.pdf is not valid",
    ],
)
def test_is_non_recoverable_error_recognizes_permanent_failures(error_message: str) -> None:
    assert is_non_recoverable_error(error_message)


def test_is_non_recoverable_error_is_case_insensitive() -> None:
    assert is_non_recoverable_error("FAILED TO LOAD DOCUMENT")


@pytest.mark.parametrize("error_message", ["", None, "Network timeout"])
def test_is_non_recoverable_error_rejects_recoverable_or_empty_messages(error_message: Any) -> None:
    assert not is_non_recoverable_error(error_message)


@pytest.mark.parametrize(
    "failure_reason",
    [
        OperatorConstants.Extraction.PASSWORD_REQUIRED,
        OperatorConstants.Extraction.PASSWORD_INCORRECT,
        OperatorConstants.Extraction.DECRYPTION_UNAVAILABLE,
    ],
)
def test_is_non_recoverable_error_exempts_recoverable_failure_reasons(failure_reason: str) -> None:
    # The message would match the "password" keyword; the explicit reason takes precedence
    message = f"{failure_reason}: Document is password-protected"
    assert is_non_recoverable_error(message)
    assert not is_non_recoverable_error(message, failure_reason=failure_reason)


@pytest.mark.parametrize("failure_reason", [None, "", "network_error"])
def test_is_non_recoverable_error_other_failure_reasons_keep_keyword_classification(failure_reason: Any) -> None:
    assert is_non_recoverable_error(
        "Failed to load document (PDFium: Incorrect password error)", failure_reason=failure_reason
    )
    assert not is_non_recoverable_error("Network timeout", failure_reason=failure_reason)


def test_extract_non_recoverable_rows_selects_rows_and_standard_columns() -> None:
    table = pa.table(
        {
            OperatorConstants.Columns.ID: ["doc-1", "doc-2", "doc-3"],
            OperatorConstants.Columns.NAME: ["one.pdf", "two.pdf", "three.pdf"],
            OperatorConstants.Metadata.MODIFIED_TIME: [1, 2, 3],
            "content": ["one", "two", "three"],
        }
    )

    result = extract_non_recoverable_rows(table=table, non_recoverable_doc_ids=[2, 0])

    assert result.column_names == [
        OperatorConstants.Columns.ID,
        OperatorConstants.Columns.NAME,
        OperatorConstants.Metadata.MODIFIED_TIME,
    ]
    assert result.to_pydict() == {
        OperatorConstants.Columns.ID: ["doc-3", "doc-1"],
        OperatorConstants.Columns.NAME: ["three.pdf", "one.pdf"],
        OperatorConstants.Metadata.MODIFIED_TIME: [3, 1],
    }


def test_extract_non_recoverable_rows_keeps_available_standard_columns() -> None:
    table = pa.table({OperatorConstants.Columns.NAME: ["one.pdf", "two.pdf"], "content": ["one", "two"]})

    result = extract_non_recoverable_rows(table=table, non_recoverable_doc_ids=[1])

    assert result.column_names == [OperatorConstants.Columns.NAME]
    assert result.to_pydict() == {OperatorConstants.Columns.NAME: ["two.pdf"]}


def test_extract_non_recoverable_rows_returns_empty_table_without_standard_columns() -> None:
    table = pa.table({"content": ["one", "two"]})

    result = extract_non_recoverable_rows(table=table, non_recoverable_doc_ids=[0])

    assert result.equals(pa.table({}))


def test_process_non_recoverable_errors_leaves_metadata_unchanged_for_empty_ids() -> None:
    metadata = {"existing": "value"}

    result = process_non_recoverable_errors(
        table=pa.table({OperatorConstants.Columns.ID: ["doc-1"]}),
        non_recoverable_doc_ids=[],
        metadata=metadata,
        common_log_arguments={},
    )

    assert result is metadata
    assert Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE not in result


def test_process_non_recoverable_errors_stores_extracted_rows() -> None:
    metadata: dict = {}
    table = pa.table(
        {
            OperatorConstants.Columns.ID: ["doc-1", "doc-2"],
            OperatorConstants.Columns.NAME: ["one.pdf", "two.pdf"],
            OperatorConstants.Metadata.MODIFIED_TIME: [1, 2],
        }
    )

    result = process_non_recoverable_errors(
        table=table,
        non_recoverable_doc_ids=[1],
        metadata=metadata,
        common_log_arguments={},
    )

    assert result is metadata
    stored_table = result[Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE]
    assert isinstance(stored_table, pa.Table)
    assert stored_table.equals(table.take([1]))


def test_process_non_recoverable_errors_leaves_metadata_unchanged_without_standard_columns() -> None:
    metadata = {"existing": "value"}

    result = process_non_recoverable_errors(
        table=pa.table({"content": ["one"]}),
        non_recoverable_doc_ids=[0],
        metadata=metadata,
        common_log_arguments={},
    )

    assert result is metadata
    assert result == {"existing": "value"}
