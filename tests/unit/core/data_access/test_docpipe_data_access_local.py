"""Unit tests for DocpipeDataAccessLocal.save_table (memmap-aware parquet writing)."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.data_access.docpipe_data_access_local import DocpipeDataAccessLocal
from docpipe.utils.core.memmap_file_utils import write_content_to_file

_EMBEDDINGS = [[0.5, 1.5, 2.5], [3.0, 4.0, 5.0]]


def _data_access(*, root: Path, cache: bool) -> DocpipeDataAccessLocal:
    return DocpipeDataAccessLocal(
        config={"input_folder": str(root / "input"), "output_folder": str(root / "output"), "cache": cache}
    )


@pytest.fixture
def memmap_table(tmp_path: Path) -> pa.Table:
    """One document whose embeddings column points to a real memmap file."""
    memmap_path = str(tmp_path / "memmap" / "embeddings.bin")
    write_content_to_file(content_list=_EMBEDDINGS, filepath=memmap_path)
    return pa.table(
        {
            "document_id": ["doc-1"],
            "embeddings": [{DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: memmap_path}],
        }
    )


class TestSaveTable:
    """save_table writes expanded data to parquet and caches the original table."""

    def test_parquet_contains_embedding_values_not_memmap_path(self, tmp_path: Path, memmap_table: pa.Table) -> None:
        data_access = _data_access(root=tmp_path, cache=False)
        path = str(tmp_path / "output" / "nested" / "batch.parquet")

        size_in_memory, file_info, retries = data_access.save_table(path, memmap_table)

        written = pq.read_table(path)
        assert written.column_names == ["document_id", "embeddings"]
        assert written.column("document_id").to_pylist() == ["doc-1"]
        assert written.column("embeddings").to_pylist() == [_EMBEDDINGS]
        assert size_in_memory == memmap_table.nbytes
        assert file_info == {"name": "batch.parquet", "size": Path(path).stat().st_size}
        assert retries == 0

    def test_cache_keeps_memmap_reference(self, tmp_path: Path, memmap_table: pa.Table) -> None:
        data_access = _data_access(root=tmp_path, cache=True)
        path = str(tmp_path / "output" / "batch.parquet")

        data_access.save_table(path, memmap_table)

        assert data_access.tables[path] is memmap_table
        cached = data_access.tables[path].column("embeddings").to_pylist()
        assert DocpipeConstants.EMBEDDINGS_MEMMAP_FILE in cached[0]

    def test_without_cache_nothing_is_kept_in_memory(self, tmp_path: Path, memmap_table: pa.Table) -> None:
        data_access = _data_access(root=tmp_path, cache=False)

        data_access.save_table(str(tmp_path / "output" / "batch.parquet"), memmap_table)

        assert data_access.tables == {}

    def test_table_without_memmap_columns_is_written_unchanged(self, tmp_path: Path) -> None:
        data_access = _data_access(root=tmp_path, cache=False)
        table = pa.table({"document_id": ["doc-1", "doc-2"], "content": ["first", "second"]})
        path = str(tmp_path / "output" / "plain.parquet")

        _, file_info, _ = data_access.save_table(path, table)

        assert pq.read_table(path).equals(table)
        assert file_info["name"] == "plain.parquet"

    def test_relative_file_name_is_written_to_working_directory(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        data_access = _data_access(root=tmp_path, cache=False)
        table = pa.table({"document_id": ["doc-1"]})

        _, file_info, _ = data_access.save_table("relative.parquet", table)

        assert pq.read_table(tmp_path / "relative.parquet").equals(table)
        assert file_info["name"] == "relative.parquet"


class TestSaveTableFailures:
    """Errors are reported through the return value, not raised."""

    def test_missing_memmap_file_reports_failure(self, tmp_path: Path) -> None:
        data_access = _data_access(root=tmp_path, cache=False)
        table = pa.table(
            {
                "document_id": ["doc-1"],
                "embeddings": [{DocpipeConstants.EMBEDDINGS_MEMMAP_FILE: str(tmp_path / "missing.bin")}],
            }
        )
        path = tmp_path / "output" / "batch.parquet"

        assert data_access.save_table(str(path), table) == (-1, {}, 0)
        assert not path.exists()

    def test_unwritable_path_reports_failure_but_table_stays_cached(self, tmp_path: Path) -> None:
        data_access = _data_access(root=tmp_path, cache=True)
        table = pa.table({"document_id": ["doc-1"]})
        directory_as_path = tmp_path / "output" / "is_a_directory"
        directory_as_path.mkdir(parents=True)

        result = data_access.save_table(str(directory_as_path), table)

        assert result == (-1, {}, 0)
        assert data_access.tables[str(directory_as_path)] is table
