# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for mapping helpers and dimension detection in docpipe.utils.operators.vectordb_utils."""

from unittest.mock import patch

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.operators.vectordb_utils import detect_vector_dimension, feature_mapping_items

FN = OperatorConstants.Misc.FEATURE_NAME
MC = OperatorConstants.Misc.MAPPED_COLUMN_NAME


class TestFeatureMappingItems:
    """Tests for feature_mapping_items."""

    def test_incomplete_entries_are_skipped(self):
        """Entries missing either key are not yielded; complete ones keep their order."""
        mappings = [
            {FN: "a", MC: "col_a"},
            {FN: "no_column"},
            {MC: "no_feature"},
            {FN: "b", MC: "col_b"},
        ]
        assert list(feature_mapping_items(mappings)) == [("a", "col_a"), ("b", "col_b")]


class TestDetectVectorDimension:
    """Tests for detect_vector_dimension edge cases."""

    def test_memmap_reference_reads_dimension_from_metadata(self):
        """A memmap file reference resolves the dimension via read_embedding_metadata."""
        key = DocpipeConstants.EMBEDDINGS_MEMMAP_FILE
        table = pa.table({"emb": [{key: "/tmp/emb.memmap"}]})
        with patch("docpipe.utils.core.memmap_file_utils.read_embedding_metadata", return_value=384) as mock_read:
            assert detect_vector_dimension(table=table, embeddings_column="emb") == 384
        mock_read.assert_called_once_with("/tmp/emb.memmap")

    def test_empty_nested_embedding_falls_through_to_next_row(self):
        """A nested embedding whose first chunk is empty is skipped in favour of the next row."""
        table = pa.table({"emb": [[[]], [[0.1, 0.2, 0.3]]]})
        assert detect_vector_dimension(table=table, embeddings_column="emb") == 3

    def test_unexpected_element_type_is_skipped(self):
        """Lists of unsupported element types (e.g. strings) are skipped, yielding None."""
        table = pa.table({"emb": [["a", "b"], ["c"]]})
        assert detect_vector_dimension(table=table, embeddings_column="emb") is None

    def test_errors_during_detection_return_none(self):
        """Any exception while reading the column is swallowed and None is returned."""
        key = DocpipeConstants.EMBEDDINGS_MEMMAP_FILE
        table = pa.table({"emb": [{key: "/missing.memmap"}]})
        with patch(
            "docpipe.utils.core.memmap_file_utils.read_embedding_metadata",
            side_effect=FileNotFoundError("gone"),
        ):
            assert detect_vector_dimension(table=table, embeddings_column="emb") is None
