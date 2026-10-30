import json
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.core.memmap_file_utils import (
    cleanup_memmap_files,
    load_chunks_from_file,
    load_embeddings_from_memmap_file,
    read_embedding_metadata,
    replace_memmap_paths_combined,
    write_chunks_to_file,
    write_content_to_file,
    write_embedding_metadata,
    yield_chunks_from_file,
    yield_embeddings_from_memmap_file,
)


class TestMemmapFileUtils:
    """Test suite for memmap file utilities."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def sample_embeddings(self):
        """Create sample embeddings for testing."""
        return [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
            [0.9, 1.0, 1.1, 1.2],
        ]

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks for testing."""
        return [
            {"chunk": "First chunk text", "metadata": {"page": 1}},
            {"chunk": "Second chunk text", "metadata": {"page": 2}},
            {"chunk": "Third chunk text", "metadata": {"page": 3}},
        ]

    def test_write_and_read_embeddings(self, *, temp_dir, sample_embeddings):
        """Test writing and reading embeddings to/from memmap file."""
        filepath = str(Path(temp_dir) / "test_embeddings.bin")

        # Write embeddings
        write_content_to_file(content_list=sample_embeddings, filepath=filepath)

        # Verify file exists
        assert Path(filepath).exists()

        # Read embeddings back
        loaded_embeddings = load_embeddings_from_memmap_file(filepath=filepath)

        # Verify content matches
        assert len(loaded_embeddings) == len(sample_embeddings)
        for original, loaded in zip(sample_embeddings, loaded_embeddings, strict=False):
            np.testing.assert_array_almost_equal(original, loaded, decimal=5)

    def test_write_and_read_embedding_metadata(self, *, temp_dir):
        """Test writing and reading embedding metadata."""
        filepath = str(Path(temp_dir) / "test_embeddings.bin")
        dim = 128

        # Write metadata
        write_embedding_metadata(filepath=filepath, dim=dim)

        # Verify metadata file exists
        metadata_path = filepath + DocpipeConstants.METADATA_SUFFIX
        assert Path(metadata_path).exists()

        # Read metadata back
        loaded_dim = read_embedding_metadata(filepath=filepath)

        # Verify dimension matches
        assert loaded_dim == dim

    def test_yield_embeddings_from_memmap_file(self, *, temp_dir, sample_embeddings):
        """Test streaming embeddings using generator."""
        filepath = str(Path(temp_dir) / "test_embeddings.bin")

        # Write embeddings
        write_content_to_file(content_list=sample_embeddings, filepath=filepath)

        # Get dimension
        dim = len(sample_embeddings[0])

        # Stream embeddings using generator
        embeddings_gen = yield_embeddings_from_memmap_file(filepath=filepath, dim=dim)
        loaded_embeddings = list(embeddings_gen)

        # Verify content matches
        assert len(loaded_embeddings) == len(sample_embeddings)
        for original, loaded in zip(sample_embeddings, loaded_embeddings, strict=False):
            np.testing.assert_array_almost_equal(original, loaded, decimal=5)

    def test_write_and_read_chunks(self, *, temp_dir, sample_chunks):
        """Test writing and reading chunks to/from binary file."""
        filepath = str(Path(temp_dir) / "test_chunks.bin")

        # Write chunks
        write_chunks_to_file(chunks_list=sample_chunks, filepath=filepath)

        # Verify file exists
        assert Path(filepath).exists()

        # Read chunks back
        loaded_chunks = load_chunks_from_file(filepath=filepath)

        # Verify content matches
        assert len(loaded_chunks) == len(sample_chunks)
        for original, loaded in zip(sample_chunks, loaded_chunks, strict=False):
            assert original == loaded

    def test_yield_chunks_from_file(self, *, temp_dir, sample_chunks):
        """Test streaming chunks using generator."""
        filepath = str(Path(temp_dir) / "test_chunks.bin")

        # Write chunks
        write_chunks_to_file(chunks_list=sample_chunks, filepath=filepath)

        # Stream chunks using generator
        chunks_gen = yield_chunks_from_file(filepath=filepath)
        loaded_chunks = []
        for chunk_str in chunks_gen:
            loaded_chunks.append(json.loads(chunk_str))

        # Verify content matches
        assert len(loaded_chunks) == len(sample_chunks)
        for original, loaded in zip(sample_chunks, loaded_chunks, strict=False):
            assert original == loaded

    def test_replace_memmap_paths_combined_with_embeddings(self, *, temp_dir, sample_embeddings):
        """Test replacing memmap paths with actual embeddings data in PyArrow table."""
        filepath = str(Path(temp_dir) / "test_embeddings.bin")

        # Write embeddings
        write_content_to_file(content_list=sample_embeddings, filepath=filepath)

        # Create table with memmap path reference
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1"],
                "embeddings": [{DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: filepath}],
            }
        )

        # Replace memmap paths
        result_table = replace_memmap_paths_combined(table=table)

        # Verify embeddings were loaded
        embeddings_value = result_table["embeddings"][0].as_py()
        assert isinstance(embeddings_value, list)
        assert len(embeddings_value) == len(sample_embeddings)

        # Verify content matches
        for original, loaded in zip(sample_embeddings, embeddings_value, strict=False):
            np.testing.assert_array_almost_equal(original, loaded, decimal=5)

    def test_replace_memmap_paths_combined_with_chunks(self, *, temp_dir, sample_chunks):
        """Test replacing memmap paths with actual chunks data in PyArrow table."""
        filepath = str(Path(temp_dir) / "test_chunks.bin")

        # Write chunks
        write_chunks_to_file(chunks_list=sample_chunks, filepath=filepath)

        # Create table with memmap path reference
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1"],
                OperatorConstants.Columns.CHUNKED_CONTENT: [{DocpipeConstants.CHUNKS_MEMMAP_FILE: filepath}],
            }
        )

        # Replace memmap paths
        result_table = replace_memmap_paths_combined(table=table)

        # Verify chunks were loaded
        chunks_value = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        assert isinstance(chunks_value, list)
        assert len(chunks_value) == len(sample_chunks)

        # Verify content matches
        for original, loaded in zip(sample_chunks, chunks_value, strict=False):
            assert original == loaded

    def test_replace_memmap_paths_combined_with_both(self, *, temp_dir, sample_embeddings, sample_chunks):
        """Test replacing both embeddings and chunks memmap paths in PyArrow table."""
        embeddings_filepath = str(Path(temp_dir) / "test_embeddings.bin")
        chunks_filepath = str(Path(temp_dir) / "test_chunks.bin")

        # Write both embeddings and chunks
        write_content_to_file(content_list=sample_embeddings, filepath=embeddings_filepath)
        write_chunks_to_file(chunks_list=sample_chunks, filepath=chunks_filepath)

        # Create table with both memmap path references
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1"],
                "embeddings": [{DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: embeddings_filepath}],
                OperatorConstants.Columns.CHUNKED_CONTENT: [{DocpipeConstants.CHUNKS_MEMMAP_FILE: chunks_filepath}],
            }
        )

        # Replace memmap paths
        result_table = replace_memmap_paths_combined(table=table)

        # Verify embeddings were loaded
        embeddings_value = result_table["embeddings"][0].as_py()
        assert isinstance(embeddings_value, list)
        assert len(embeddings_value) == len(sample_embeddings)

        # Verify chunks were loaded
        chunks_value = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        assert isinstance(chunks_value, list)
        assert len(chunks_value) == len(sample_chunks)

    def test_replace_memmap_paths_combined_no_memmap_columns(self):
        """Test that tables without memmap columns are returned unchanged."""
        # Create table without memmap references
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1", "doc2"],
                "content": ["text1", "text2"],
            }
        )

        # Replace memmap paths (should be no-op)
        result_table = replace_memmap_paths_combined(table=table)

        # Verify table is unchanged
        assert result_table.equals(table)

    def test_cleanup_memmap_files(self, *, temp_dir):
        """Test cleanup of memmap files."""
        job_id = "test_job"
        job_run_id = "test_run"

        # Create directory structure
        chunks_dir = str(Path(temp_dir) / "chunks_files" / job_id / job_run_id)
        embeddings_dir = str(Path(temp_dir) / "embeddings_files" / job_id / job_run_id)
        Path(chunks_dir).mkdir(parents=True, exist_ok=True)
        Path(embeddings_dir).mkdir(parents=True, exist_ok=True)

        # Create some test files
        (Path(chunks_dir) / "test_chunk.bin").touch()
        (Path(embeddings_dir) / "test_embedding.bin").touch()

        # Verify directories exist
        assert Path(chunks_dir).exists()
        assert Path(embeddings_dir).exists()

        # Mock get_data_path to return our temp directory
        from unittest.mock import patch

        def mock_get_data_path(*, sub_dir):
            return str(Path(temp_dir) / sub_dir.lstrip("/"))

        # Use patch to mock get_data_path from the filesystem module
        with patch("docpipe.utils.infrastructure.filesystem.get_data_path", side_effect=mock_get_data_path):
            # Cleanup
            cleanup_memmap_files(job_id=job_id, job_run_id=job_run_id)

            # Verify directories were removed
            assert not Path(chunks_dir).exists()
            assert not Path(embeddings_dir).exists()

    def test_write_embeddings_creates_directory(self, *, temp_dir, sample_embeddings):
        """Test that writing embeddings creates necessary directories."""
        nested_path = str(Path(temp_dir) / "nested" / "dir" / "test_embeddings.bin")

        # Write embeddings (should create directories)
        write_content_to_file(content_list=sample_embeddings, filepath=nested_path)

        # Verify file and directories exist
        assert Path(nested_path).exists()
        assert Path(nested_path).parent.exists()

    def test_write_chunks_creates_directory(self, *, temp_dir, sample_chunks):
        """Test that writing chunks creates necessary directories."""
        nested_path = str(Path(temp_dir) / "nested" / "dir" / "test_chunks.bin")

        # Write chunks (should create directories)
        write_chunks_to_file(chunks_list=sample_chunks, filepath=nested_path)

        # Verify file and directories exist
        assert Path(nested_path).exists()
        assert Path(nested_path).parent.exists()

    def test_empty_embeddings_list(self, *, temp_dir):
        """Test handling of empty embeddings list."""
        filepath = str(Path(temp_dir) / "empty_embeddings.bin")

        # Write empty list
        write_content_to_file(content_list=[], filepath=filepath)

        # File is created but empty
        assert Path(filepath).exists()
        assert Path(filepath).stat().st_size == 0

        # No metadata file should be created for empty list
        metadata_path = filepath + DocpipeConstants.METADATA_SUFFIX
        assert not Path(metadata_path).exists()

    def test_empty_chunks_list(self, *, temp_dir):
        """Test handling of empty chunks list."""
        filepath = str(Path(temp_dir) / "empty_chunks.bin")

        # Write empty list
        write_chunks_to_file(chunks_list=[], filepath=filepath)

        # File should still be created
        assert Path(filepath).exists()

        # Reading should return empty list
        loaded = load_chunks_from_file(filepath=filepath)
        assert len(loaded) == 0


class TestPackedBitEmbeddings:
    """Binary (1-bit packed) embeddings must survive the memmap round trip with a bit-count dimension."""

    @pytest.fixture
    def packed_rows(self):
        return [b"\xa5" * 48, b"\x00" * 48, b"\xff" * 48]  # 384-bit vectors

    def test_metadata_records_bit_dimension_and_layout(self, tmp_path, packed_rows):
        filepath = str(tmp_path / "bin_embeddings.bin")

        write_content_to_file(content_list=packed_rows, filepath=filepath)

        assert read_embedding_metadata(filepath=filepath) == 384
        metadata = json.loads(Path(filepath + DocpipeConstants.METADATA_SUFFIX).read_text())
        assert metadata == {"dim": 384, "dtype": "packed_bits"}
        assert Path(filepath).stat().st_size == 48 * 3

    def test_load_returns_original_bytes(self, tmp_path, packed_rows):
        filepath = str(tmp_path / "bin_embeddings.bin")
        write_content_to_file(content_list=packed_rows, filepath=filepath)

        assert load_embeddings_from_memmap_file(filepath=filepath) == packed_rows

    def test_yield_streams_original_bytes(self, tmp_path, packed_rows):
        filepath = str(tmp_path / "bin_embeddings.bin")
        write_content_to_file(content_list=packed_rows, filepath=filepath)

        assert list(yield_embeddings_from_memmap_file(filepath=filepath, dim=384)) == packed_rows

    def test_float_metadata_stays_backward_compatible(self, tmp_path):
        filepath = str(tmp_path / "float_embeddings.bin")

        write_content_to_file(content_list=[[0.1, 0.2], [0.3, 0.4]], filepath=filepath)

        metadata = json.loads(Path(filepath + DocpipeConstants.METADATA_SUFFIX).read_text())
        assert metadata == {"dim": 2}

    def test_replace_memmap_paths_combined_expands_packed_bits(self, tmp_path, packed_rows):
        filepath = str(tmp_path / "bin_embeddings.bin")
        write_content_to_file(content_list=packed_rows, filepath=filepath)
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1"],
                "embeddings": [{DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: filepath}],
            }
        )

        result = replace_memmap_paths_combined(table=table)

        assert result.column("embeddings").to_pylist() == [packed_rows]
