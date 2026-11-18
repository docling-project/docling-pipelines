# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case and error-path tests for docpipe.utils.core.memmap_file_utils."""

import json
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.core.memmap_file_utils import (
    cleanup_memmap_files,
    load_chunks_from_file,
    load_embeddings_from_memmap_file,
    read_embedding_metadata,
    replace_memmap_paths_combined,
    write_chunks_to_file,
    write_content_to_file,
    yield_chunks_from_file,
    yield_embeddings_from_memmap_file,
)

META = DocpipeConstants.METADATA_SUFFIX
EMB_KEY = DocpipeConstants.EMBEDDINGS_MEMMAP_FILE
CHUNK_KEY = DocpipeConstants.CHUNKS_MEMMAP_FILE


class TestEmbeddingFiles:
    """Tests for embedding memmap writing, metadata and reading."""

    def test_append_keeps_existing_metadata(self, tmp_path):
        """A second write appends rows and leaves the first write's metadata untouched."""
        path = str(tmp_path / "emb.memmap")
        write_content_to_file([[1.0, 2.0]], path)
        Path(path + META).write_text(json.dumps({"dim": 2, "marker": "first"}), encoding="utf-8")

        write_content_to_file([[3.0, 4.0]], path)

        assert json.loads(Path(path + META).read_text(encoding="utf-8")) == {"dim": 2, "marker": "first"}
        assert load_embeddings_from_memmap_file(path) == [[1.0, 2.0], [3.0, 4.0]]

    def test_metadata_without_dim_is_rejected(self, tmp_path):
        """Metadata lacking the 'dim' field raises a DocpipeException naming the file."""
        path = str(tmp_path / "emb.memmap")
        Path(path + META).write_text(json.dumps({"dtype": "float32"}), encoding="utf-8")

        with pytest.raises(DocpipeException, match="missing 'dim' field"):
            read_embedding_metadata(path)

    def test_yield_without_metadata_reads_float32(self, tmp_path):
        """Without a metadata file the memmap is read as float32 rows of the given dimension."""
        path = str(tmp_path / "emb.memmap")
        write_content_to_file([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], path)
        Path(path + META).unlink()

        rows = [row.tolist() for row in yield_embeddings_from_memmap_file(path, 3)]

        assert rows == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


class TestChunkFiles:
    """Tests for chunk file writing and reading."""

    def test_string_chunks_round_trip_through_yield(self, tmp_path):
        """Non-dict chunks are stored as their string form and yielded back unchanged."""
        path = str(tmp_path / "chunks.bin")
        write_chunks_to_file(["plain text", 42], path)

        assert list(yield_chunks_from_file(path)) == ["plain text", "42"]

    def test_missing_chunks_file_raises(self, tmp_path):
        """Reading a non-existent chunks file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Chunks file not found"):
            list(yield_chunks_from_file(str(tmp_path / "missing.bin")))

    def test_corrupt_chunk_payload_raises_docpipe_exception(self, tmp_path):
        """A length-prefixed payload that is not valid JSON is reported as DocpipeException."""
        path = tmp_path / "chunks.bin"
        payload = b"{broken"
        path.write_bytes(len(payload).to_bytes(4, byteorder="little") + payload)

        with pytest.raises(DocpipeException, match="loading chunked content"):
            load_chunks_from_file(str(path))


class TestReplaceMemmapPaths:
    """Tests for replace_memmap_paths_combined row and column handling."""

    def test_rows_without_memmap_reference_are_kept(self, tmp_path):
        """Only rows holding a memmap reference are expanded; other rows pass through."""
        emb_path = str(tmp_path / "emb.memmap")
        chunk_path = str(tmp_path / "chunks.bin")
        write_content_to_file([[1.0, 2.0]], emb_path)
        write_chunks_to_file([{"chunk": "a"}], chunk_path)
        table = pa.table(
            {
                "embeddings": [{EMB_KEY: emb_path}, None],
                "chunked_content": [{CHUNK_KEY: chunk_path}, None],
                "doc_id": ["d1", "d2"],
            }
        )

        result = replace_memmap_paths_combined(table)

        assert result.column_names == ["embeddings", "chunked_content", "doc_id"]
        assert result.column("embeddings").to_pylist() == [[[1.0, 2.0]], None]
        assert result.column("chunked_content").to_pylist() == [[{"chunk": "a"}], None]
        assert result.column("doc_id").to_pylist() == ["d1", "d2"]

    def test_empty_table_is_returned_unchanged(self):
        """An empty column cannot hold memmap references, so the table is returned as-is."""
        table = pa.table({"embeddings": pa.array([], type=pa.string())})
        assert replace_memmap_paths_combined(table) is table

    def test_unreadable_chunks_file_raises(self, tmp_path):
        """A chunks reference to a missing file is wrapped in a DocpipeException."""
        table = pa.table({"chunked_content": [{CHUNK_KEY: str(tmp_path / "gone.bin")}]})
        with pytest.raises(DocpipeException, match="Cannot load chunks from memmap file"):
            replace_memmap_paths_combined(table)

    def test_unreadable_embeddings_file_raises(self, tmp_path):
        """An embeddings reference without metadata is wrapped in a DocpipeException."""
        table = pa.table({"embeddings": [{EMB_KEY: str(tmp_path / "gone.memmap")}]})
        with pytest.raises(DocpipeException, match="Cannot load embeddings from memmap file"):
            replace_memmap_paths_combined(table)


class TestCleanupMemmapFiles:
    """Tests for cleanup_memmap_files."""

    def test_missing_directories_are_ignored(self, tmp_path):
        """Nothing is removed and no error is raised when neither directory exists."""
        with (
            patch(
                "docpipe.utils.infrastructure.filesystem.get_data_path",
                side_effect=lambda *, sub_dir: str(tmp_path / sub_dir.lstrip("/")),
            ),
            patch("shutil.rmtree") as mock_rmtree,
        ):
            cleanup_memmap_files(job_id="job", job_run_id="run")

        mock_rmtree.assert_not_called()

    def test_errors_are_logged_not_raised(self):
        """Failures while resolving directories are swallowed and logged as a warning."""
        with (
            patch("docpipe.utils.infrastructure.filesystem.get_data_path", side_effect=OSError("denied")),
            patch("docpipe.utils.core.memmap_file_utils.logger") as mock_logger,
        ):
            cleanup_memmap_files(job_id="job", job_run_id="run")

        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.args[1] == "run"
