#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for DocIdHashOperator.
Tests hashing document content using SHA-256 and adding a doc_id_hash column.
"""

import hashlib

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Default doc column used in tests — must match what DocIDTransform receives
DOC_COL = "content"


def make_table(contents=None, extra_columns=None) -> pa.Table:
    """
    Create a test PyArrow table with 'id' and 'content' columns.

    Args:
        contents: list of content strings. Defaults to 3 sample documents.
        extra_columns: dict of additional columns to include.
    """
    if contents is None:
        contents = [
            "The quick brown fox jumps over the lazy dog.",
            "Hello, World! This is document two.",
            "Third document with some unique content here.",
        ]
    data = {
        "id": [str(i + 1) for i in range(len(contents))],
        DOC_COL: contents,
    }
    if extra_columns:
        data.update(extra_columns)
    return pa.table(data)


def make_operator(config=None) -> DocIdHashOperator:
    """
    Create a DocIdHashOperator.
    Always sets DOC_COLUMN to DOC_COL so DocIDTransform finds the column.
    """
    base = {OperatorConstants.Columns.DOC_COLUMN: DOC_COL}
    if config:
        base.update(config)
    return DocIdHashOperator(base)


def sha256_hex(text: str) -> str:
    """Compute SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. Basic hashing
# ---------------------------------------------------------------------------


def test_basic_hashing_adds_doc_id_hash_column():
    """Operator adds a 'doc_id_hash' column to the output table."""
    table = make_table()
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result.column_names, (
        f"Expected '{OperatorConstants.Columns.DOC_ID_HASH_DEFAULT}' column in output, "
        f"got columns: {result.column_names}"
    )


def test_basic_hashing_preserves_input_columns():
    """Operator preserves all original columns in the output."""
    table = make_table()
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    for col in table.column_names:
        assert col in result.column_names, f"Column '{col}' missing from output"


def test_basic_hashing_row_count_unchanged():
    """Output table has the same number of rows as the input."""
    table = make_table()
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == table.num_rows


# ---------------------------------------------------------------------------
# 2. Hash format — 64-character hex string (SHA-256)
# ---------------------------------------------------------------------------


def test_hash_is_64_char_hex_string():
    """Each hash value is a 64-character hexadecimal string."""
    table = make_table()
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    for h in hashes:
        assert isinstance(h, str), f"Hash should be a string, got {type(h)}"
        assert len(h) == 64, f"SHA-256 hash should be 64 chars, got {len(h)}: {h}"
        # Verify it's valid hex
        int(h, 16)  # raises ValueError if not valid hex


def test_hash_is_lowercase_hex():
    """Hash values use lowercase hexadecimal characters."""
    table = make_table()
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    for h in hashes:
        assert h == h.lower(), f"Hash should be lowercase, got: {h}"


def test_list_content_yields_16_char_truncated_hash():
    """
    Non-string (list-typed) content is hashed by DocIDTransform as the
    SHA-256 of its canonical JSON, truncated to 16 hex characters. This is the
    only case where the hash is not 64 characters and is documented in the
    operator readme.
    """
    table = pa.table({"id": ["1"], DOC_COL: [["alpha", "beta"]]})
    operator = make_operator()
    result_tables, _ = operator.transform(table)

    hashes = result_tables[0][OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    canonical_json = '["alpha","beta"]'
    assert hashes == [sha256_hex(canonical_json)[:16]]
    assert hashes[0] == hashes[0].lower()


# ---------------------------------------------------------------------------
# 3. Deterministic — same content always produces the same hash
# ---------------------------------------------------------------------------


def test_hash_is_deterministic():
    """Same content always produces the same hash across two operator runs."""
    table = make_table()
    operator1 = make_operator()
    operator2 = make_operator()

    result1, _ = operator1.transform(table)
    result2, _ = operator2.transform(table)

    hashes1 = result1[0][OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    hashes2 = result2[0][OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()

    assert hashes1 == hashes2, "Hashes should be identical for the same content"


def test_hash_matches_expected_sha256():
    """Hash values match the expected SHA-256 digest of the content."""
    contents = [
        "The quick brown fox jumps over the lazy dog.",
        "Hello, World!",
    ]
    table = make_table(contents=contents)
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    for i, content in enumerate(contents):
        expected = sha256_hex(content)
        assert hashes[i] == expected, f"Hash mismatch for row {i}: expected {expected}, got {hashes[i]}"


# ---------------------------------------------------------------------------
# 4. Different content → different hash
# ---------------------------------------------------------------------------


def test_different_content_produces_different_hashes():
    """Two rows with different content get different hashes."""
    contents = [
        "First unique document content.",
        "Second completely different document content.",
    ]
    table = make_table(contents=contents)
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert hashes[0] != hashes[1], "Different content should produce different hashes"


def test_all_hashes_unique_for_unique_content():
    """All rows with unique content produce unique hashes."""
    contents = [f"Unique document number {i}" for i in range(10)]
    table = make_table(contents=contents)
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert len(set(hashes)) == len(hashes), "All hashes should be unique for unique content"


def test_identical_content_produces_same_hash():
    """Two rows with identical content produce the same hash."""
    contents = ["Same content here.", "Same content here."]
    table = make_table(contents=contents)
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert hashes[0] == hashes[1], "Identical content should produce the same hash"


# ---------------------------------------------------------------------------
# 5. Custom doc_column
# ---------------------------------------------------------------------------


def test_custom_doc_column():
    """Operator respects doc_column config param."""
    table = pa.table(
        {
            "id": ["1", "2"],
            "text": ["Custom column content A.", "Custom column content B."],
        }
    )

    operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: "text"})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result.column_names

    # Verify hashes match SHA-256 of the 'text' column values
    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    texts = table["text"].to_pylist()
    for i, text in enumerate(texts):
        expected = sha256_hex(text)
        assert hashes[i] == expected, f"Hash mismatch for custom column row {i}"


def test_custom_hash_column_name():
    """Operator respects doc_id_hash_column config param for output column name."""
    table = make_table()
    custom_hash_col = "my_custom_hash"
    operator = make_operator({OperatorConstants.Columns.DOC_ID_HASH: custom_hash_col})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert custom_hash_col in result.column_names, (
        f"Expected custom hash column '{custom_hash_col}' in output, got: {result.column_names}"
    )


# ---------------------------------------------------------------------------
# 6. Missing doc_column — raises exception when dpk_doc_id is available
# ---------------------------------------------------------------------------


def test_missing_doc_column_raises_exception():
    """
    When the configured doc_column doesn't exist in the table,
    dpk_doc_id.DocIDTransform raises an Exception (column validation failure).
    """
    table = pa.table(
        {
            "id": ["1", "2", "3"],
            "other_column": ["a", "b", "c"],
        }
    )
    # doc_column is "content" but table only has "other_column"
    operator = make_operator()
    with pytest.raises(Exception, match="Not all required columns are present"):
        operator.transform(table)


# ---------------------------------------------------------------------------
# 7. get_metadata()
# ---------------------------------------------------------------------------


def test_get_metadata_is_operator_available_false():
    """get_metadata() returns IS_OPERATOR_AVAILABLE: False (internal operator)."""
    # get_metadata() is now a static method, call it on the class
    meta = DocIdHashOperator.get_metadata()

    assert OperatorConstants.Misc.IS_OPERATOR_AVAILABLE in meta
    assert meta[OperatorConstants.Misc.IS_OPERATOR_AVAILABLE] is False


def test_get_metadata_returns_dict():
    """get_metadata() returns a dictionary."""
    # get_metadata() is now a static method, call it on the class
    meta = DocIdHashOperator.get_metadata()

    assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# 8. short_name
# ---------------------------------------------------------------------------


def test_short_name_matches_doc_id_operator_constant():
    """short_name matches OperatorConstants.Operators.DOC_ID_OPERATOR."""
    assert DocIdHashOperator.short_name == OperatorConstants.Operators.DOC_ID_OPERATOR


def test_short_name_value():
    """short_name is 'doc_id_hash'."""
    assert DocIdHashOperator.short_name == "doc_id_hash"


# ---------------------------------------------------------------------------
# 9. Existing doc_id_hash column
# ---------------------------------------------------------------------------


def test_existing_doc_id_hash_column_new_hash_added():
    """
    If doc_id_hash already exists in the table, dpk_doc_id appends a new
    doc_id_hash column. The output table has the hash column and correct row count.
    """
    table = pa.table(
        {
            "id": ["1", "2"],
            "content": ["Content A", "Content B"],
            "doc_id_hash": ["old_hash_1", "old_hash_2"],
        }
    )

    operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: "content"})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    # The result should have the hash column
    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result.column_names
    assert result.num_rows == 2


def test_existing_doc_id_hash_column_no_original_column_created():
    """
    When doc_id_hash already exists, DocIDTransform would normally rename it to
    doc_id_hash.original before computing a new hash. The operator must drop the
    existing column first so no spurious .original column appears in the output.
    """
    table = pa.table(
        {
            "id": ["1", "2"],
            "content": ["Content A", "Content B"],
            "doc_id_hash": ["old_hash_1", "old_hash_2"],
        }
    )

    operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: "content"})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert "doc_id_hash.original" not in result.column_names, (
        "Spurious 'doc_id_hash.original' column should not appear in output"
    )
    # Hash must be freshly computed, not the stale value
    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert hashes[0] != "old_hash_1"
    assert hashes[1] != "old_hash_2"
    # And must match the expected SHA-256 of the content
    assert hashes[0] == sha256_hex("Content A")
    assert hashes[1] == sha256_hex("Content B")


# ---------------------------------------------------------------------------
# 10. Empty table
# ---------------------------------------------------------------------------


def test_empty_table_returns_empty_table_with_hash_column():
    """Operator handles an empty table gracefully."""
    table = pa.table(
        {
            "id": pa.array([], type=pa.string()),
            "content": pa.array([], type=pa.string()),
        }
    )

    operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: "content"})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    # Should return a table (possibly empty) with the hash column
    assert result is not None
    assert result.num_rows == 0
    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result.column_names


def test_empty_table_metadata():
    """Operator metadata for empty table has zero processed docs."""
    table = pa.table(
        {
            "id": pa.array([], type=pa.string()),
            "content": pa.array([], type=pa.string()),
        }
    )

    operator = DocIdHashOperator({OperatorConstants.Columns.DOC_COLUMN: "content"})
    _, metadata = operator.transform(table)

    assert metadata[Metrics.External.TOTAL_DOCS] == 0
    assert metadata[Metrics.External.PROCESSED_DOCS] == 0


# ---------------------------------------------------------------------------
# 11. Metadata structure
# ---------------------------------------------------------------------------


def test_transform_metadata_contains_total_docs():
    """transform() metadata contains documents_in_scope."""
    table = make_table()
    operator = make_operator()
    _, metadata = operator.transform(table)

    assert Metrics.External.TOTAL_DOCS in metadata
    assert metadata[Metrics.External.TOTAL_DOCS] == table.num_rows


def test_transform_metadata_contains_processed_docs():
    """transform() metadata contains processed_docs."""
    table = make_table()
    operator = make_operator()
    _, metadata = operator.transform(table)

    assert Metrics.External.PROCESSED_DOCS in metadata
    assert metadata[Metrics.External.PROCESSED_DOCS] == table.num_rows


def test_transform_metadata_contains_hashed_rows():
    """transform() metadata contains hashed_rows count."""
    table = make_table()
    operator = make_operator()
    _, metadata = operator.transform(table)

    assert "hashed_rows" in metadata
    assert metadata["hashed_rows"] == table.num_rows


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------


def test_empty_string_content_hashed():
    """Empty string content is hashed (not skipped)."""
    table = make_table(contents=[""])
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert len(hashes) == 1
    assert isinstance(hashes[0], str)
    assert len(hashes[0]) == 64
    # SHA-256 of empty string is well-known
    expected = sha256_hex("")
    assert hashes[0] == expected


def test_unicode_content_hashed():
    """Unicode content is hashed correctly."""
    contents = ["こんにちは世界", "Héllo Wörld", "مرحبا بالعالم"]
    table = make_table(contents=contents)
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    for i, content in enumerate(contents):
        expected = sha256_hex(content)
        assert hashes[i] == expected, f"Unicode hash mismatch at row {i}"


def test_single_row_table():
    """Operator works correctly on a single-row table."""
    table = make_table(contents=["Single document."])
    operator = make_operator()
    result_tables, metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 1
    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result.column_names
    assert metadata[Metrics.External.PROCESSED_DOCS] == 1


def test_large_content_hashed():
    """Large content strings are hashed without error."""
    large_content = "A" * 100_000
    table = make_table(contents=[large_content])
    operator = make_operator()
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    hashes = result[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert len(hashes[0]) == 64
    assert hashes[0] == sha256_hex(large_content)


def test_operator_init_with_empty_config():
    """Operator initializes successfully with an empty config dict."""
    operator = DocIdHashOperator({})
    assert operator is not None
    assert operator.doc_column == OperatorConstants.Columns.DOC_COLUMN_DEFAULT
    assert operator.hash_column == OperatorConstants.Columns.DOC_ID_HASH_DEFAULT


def test_operator_init_with_custom_config():
    """Operator initializes with custom doc_column and hash_column."""
    config = {
        OperatorConstants.Columns.DOC_COLUMN: "my_text",
        OperatorConstants.Columns.DOC_ID_HASH: "my_hash",
    }
    operator = DocIdHashOperator(config)
    assert operator.doc_column == "my_text"
    assert operator.hash_column == "my_hash"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
