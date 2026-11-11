# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for TableFileSystemStorage."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docpipe.storage.exceptions import StorageException, StorageValidationError
from docpipe.storage.file_system.table_file_system_storage import TableFileSystemStorage
from docpipe.storage.interfaces.table_storage_port import TableStoragePort

SCHEMA = pa.schema([("id", pa.string()), ("content", pa.string())])


def _table(*doc_ids: str, suffix: str = "") -> pa.Table:
    return pa.table({"id": list(doc_ids), "content": [f"text-{d}{suffix}" for d in doc_ids]})


@pytest.fixture
def storage(tmp_path):
    return TableFileSystemStorage(base_dir=str(tmp_path))


def _write_parquet(base, table_name: str, table: pa.Table, *, sub: str | None = None) -> None:
    target = base / table_name
    if sub:
        target = target / sub
    target.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target / "output.parquet")


class TestContract:
    def test_is_a_table_storage_port(self, storage):
        assert isinstance(storage, TableStoragePort)

    def test_create_table_makes_an_empty_table(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)

        assert storage.table_exists(table_name="docs")
        assert storage.get_row_count(table_name="docs") == 0

    def test_create_table_is_idempotent(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)
        storage.upsert_data(table_name="docs", data=_table("a"))

        storage.create_table(table_name="docs", schema=SCHEMA)

        assert storage.get_row_count(table_name="docs") == 1

    def test_upsert_inserts_and_replaces_by_id(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)
        storage.upsert_data(table_name="docs", data=_table("a", "b"))

        storage.upsert_data(table_name="docs", data=_table("b", "c", suffix="-new"))

        rows = storage.read_data(table_name="docs")
        assert rows.column("id").to_pylist() == ["a", "b", "c"]
        assert rows.column("content").to_pylist() == ["text-a", "text-b-new", "text-c-new"]

    def test_upsert_requires_id_column(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)

        with pytest.raises(StorageValidationError):
            storage.upsert_data(table_name="docs", data=pa.table({"content": ["x"]}))

    def test_upsert_into_missing_table_fails(self, storage):
        with pytest.raises(StorageException):
            storage.upsert_data(table_name="nope", data=_table("a"))

    def test_read_data_supports_limit_and_offset(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)
        storage.upsert_data(table_name="docs", data=_table("a", "b", "c", "d"))

        rows = storage.read_data(table_name="docs", limit=2, offset=1)

        assert rows.column("id").to_pylist() == ["b", "c"]

    def test_read_missing_table_raises_key_error(self, storage):
        with pytest.raises(KeyError):
            storage.read_data(table_name="nope")

    def test_row_count_of_missing_table_raises_key_error(self, storage):
        with pytest.raises(KeyError):
            storage.get_row_count(table_name="nope")

    def test_delete_table(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)

        assert storage.delete_table(table_name="docs") is True
        assert storage.table_exists(table_name="docs") is False
        assert storage.delete_table(table_name="docs") is False

    @pytest.mark.parametrize("name", ["../escape", "a/../b", "/etc", "a\\b", ""])
    def test_invalid_table_names_are_rejected(self, storage, name):
        with pytest.raises(StorageValidationError):
            storage.table_exists(table_name=name)


class TestExistingParquetFolders:
    def test_folder_written_by_another_component_is_a_table(self, storage, tmp_path):
        _write_parquet(tmp_path, "job/run/data/node_0", _table("a", "b"))

        assert storage.table_exists(table_name="job/run/data/node_0")
        assert storage.get_row_count(table_name="job/run/data/node_0") == 2

    def test_rows_of_batch_subfolders_are_combined(self, storage, tmp_path):
        _write_parquet(tmp_path, "node_0", _table("a"), sub="0")
        _write_parquet(tmp_path, "node_0", _table("b"), sub="1")

        assert storage.read_data(table_name="node_0").column("id").to_pylist() == ["a", "b"]

    def test_files_with_different_columns_are_combined(self, storage, tmp_path):
        _write_parquet(tmp_path, "node_0", _table("a"), sub="0")
        _write_parquet(tmp_path, "node_0", pa.table({"id": ["b"]}), sub="1")

        rows = storage.read_data(table_name="node_0")

        assert rows.column("content").to_pylist() == ["text-a", None]

    def test_folder_without_parquet_files_is_not_a_table(self, storage, tmp_path):
        (tmp_path / "empty").mkdir()

        assert storage.table_exists(table_name="empty") is False


class TestExecuteQuery:
    def test_select_with_bound_parameters(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)
        storage.upsert_data(table_name="docs", data=_table("a", "b", "c"))

        rows = storage.execute_query(query="SELECT * FROM docs WHERE id IN (?, ?)", params=["a", "c"])

        assert sorted(rows.column("id").to_pylist()) == ["a", "c"]

    def test_quoted_sub_path_table_name_over_batch_folders(self, storage, tmp_path):
        _write_parquet(tmp_path, "job/run/data/node_0", _table("a"), sub="0")
        _write_parquet(tmp_path, "job/run/data/node_0", _table("b"), sub="1")

        rows = storage.execute_query(query='SELECT id FROM "job/run/data/node_0" WHERE id = ?', params=["b"])

        assert rows.column("id").to_pylist() == ["b"]

    def test_query_sees_upserted_changes(self, storage):
        storage.create_table(table_name="docs", schema=SCHEMA)
        storage.upsert_data(table_name="docs", data=_table("a"))
        storage.upsert_data(table_name="docs", data=_table("a", suffix="-new"))

        rows = storage.execute_query(query="SELECT content FROM docs")

        assert rows.column("content").to_pylist() == ["text-a-new"]

    def test_bad_query_raises_storage_exception(self, storage):
        with pytest.raises(StorageException):
            storage.execute_query(query="SELECT * FROM missing_table")
