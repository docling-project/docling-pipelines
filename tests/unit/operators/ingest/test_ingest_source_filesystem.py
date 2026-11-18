#!/usr/bin/env python3
"""
Unit tests for IngestSourceOperator (filesystem provider) output schema.
Tests that the operator produces the expected columns and metadata.
"""

import zipfile
from pathlib import Path

import pytest

from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

EXPECTED_METADATA_COLUMNS = {
    "id",
    "name",
    "document_format",
    "path",
    "metadata",
    "source_id",
    "modified_time",
}


def _make_config(path: str, **kwargs) -> dict:
    return {
        "provider": "filesystem",
        "provider_config": {"paths": [path]},
        "max_files": kwargs.get("max_files", 10),
        "force_ingest": True,
    }


class TestIngestSourceOperatorOutput:
    """Test suite for IngestSourceOperator (filesystem) output schema and metadata."""

    def test_transform_with_none_input_table(self, temp_test_dir):
        """Test transform with None input table produces expected output."""
        operator = IngestSourceOperator(_make_config(temp_test_dir))
        tables, metadata = operator.transform(None)
        table = tables[0]

        assert table is not None
        assert table.num_rows > 0
        assert EXPECTED_METADATA_COLUMNS.issubset(set(table.column_names))
        assert metadata["processed_docs"] == table.num_rows

    def test_transform_returns_only_ingested_rows(self, temp_test_dir):
        """Test that transform returns only the newly ingested rows (no input merging)."""
        operator = IngestSourceOperator(_make_config(temp_test_dir))
        tables, metadata = operator.transform(None)
        table = tables[0]

        # Output rows == processed docs
        assert table.num_rows == metadata["processed_docs"]

    def test_transform_with_schema_mismatch_input_ignored(self, temp_test_dir):
        """Test transform ignores any input table and returns fresh ingested rows."""
        import pyarrow as pa

        # IngestSourceOperator does not merge with input; it produces its own output
        input_data = [{"id": "existing_1", "name": "/path/to/existing1.txt", "custom_field": "custom_value"}]
        input_table = pa.Table.from_pylist(input_data)

        operator = IngestSourceOperator(_make_config(temp_test_dir))
        tables, metadata = operator.transform(input_table)
        result_table = tables[0]

        # Result should contain only ingested rows (no custom_field from input)
        assert result_table.num_rows > 0
        assert "path" in result_table.column_names
        # custom_field is NOT carried over — IngestSourceOperator does not merge
        assert "custom_field" not in result_table.column_names
        assert metadata["processed_docs"] > 0

    def test_transform_output_has_path_column(self, temp_test_dir):
        """Test that output contains path column with valid file paths."""
        operator = IngestSourceOperator(_make_config(temp_test_dir))
        tables, _ = operator.transform(None)
        table = tables[0]

        assert "path" in table.column_names
        for idx in range(table.num_rows):
            path_val = table["path"][idx].as_py()
            assert path_val is not None
            assert len(path_val) > 0

    def test_transform_empty_result_returns_schema_table(self, tmp_path):
        """Test transform with a directory of unsupported files returns empty schema table."""
        # Create a file with a non-supported extension
        (tmp_path / "file.xyz").write_text("content")

        operator = IngestSourceOperator(
            {
                "provider": "filesystem",
                "provider_config": {"paths": [str(tmp_path)]},
                "include_filter": "pdf",  # Only pdf, but we have .xyz
                "force_ingest": True,
            }
        )
        tables, metadata = operator.transform(None)
        table = tables[0]

        assert table.num_rows == 0
        assert "path" in table.column_names
        assert metadata["processed_docs"] == 0

    def test_transform_expands_archive_entries_with_synthetic_source_id(self, tmp_path):
        archive_path = tmp_path / "documents.zip"
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            archive.writestr("folder/report.txt", b"report")

        operator = IngestSourceOperator(
            {
                "provider": "filesystem",
                "provider_config": {"paths": [str(tmp_path)]},
                "include_filter": "zip,txt",
                "force_ingest": True,
            }
        )

        tables, metadata = operator.transform(None)
        row = tables[0].to_pylist()[0]

        assert metadata["processed_docs"] == 1
        assert row["path"].startswith("zip://")
        assert row["source_id"] == row["path"]
        assert row["name"] == "folder/report.txt"
        assert row["document_format"] == ".txt"


def test_table_output_basic():
    """Basic test for output schema without fixtures."""
    fixtures_dir = Path(__file__).parent.parent.parent.parent / "fixtures" / "invoices"

    if not fixtures_dir.exists():
        pytest.skip(f"Fixtures directory not found: {fixtures_dir}")

    config = {
        "provider": "filesystem",
        "provider_config": {"paths": [str(fixtures_dir)]},
        "include_filter": "pdf",
        "max_files": 2,
        "force_ingest": True,
    }

    operator = IngestSourceOperator(config)
    tables, metadata = operator.transform(None)
    result_table = tables[0]

    assert result_table.num_rows > 0
    assert "binary_content" not in result_table.column_names
    assert EXPECTED_METADATA_COLUMNS.issubset(set(result_table.column_names))
    assert metadata["processed_docs"] == result_table.num_rows


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
