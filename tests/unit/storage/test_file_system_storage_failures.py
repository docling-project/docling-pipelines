"""Failure-path tests for the filesystem storages on real directories."""

import re
from typing import IO, Any, ClassVar

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.exceptions import StorageValidationError
from docpipe.storage.file_system.abstract_file_system_storage import AbstractFileSystemStorage
from docpipe.storage.file_system.content_file_system_storage import ContentFileSystemStorage
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage


class _PlainTextStorage(AbstractFileSystemStorage):
    """Minimal concrete subclass that keeps the base class defaults."""

    _instances: ClassVar[dict[str, "_PlainTextStorage"]] = {}

    def save_file_content(self, *, file: IO[str], data: Any) -> None:
        """Write ``data`` unchanged."""
        file.write(data)

    def load_file_content(self, *, file: IO[str]) -> Any:
        """Return the file content unchanged."""
        return file.read()

    def list_files(self, *, collection: str) -> list[Any]:
        """Return the names of the files in the collection."""
        return sorted(path.name for path in self._get_collection_dir(collection=collection).iterdir())


@pytest.fixture
def content_storage(tmp_path):
    """ContentFileSystemStorage rooted in a fresh directory."""
    return ContentFileSystemStorage(base_dir=str(tmp_path / "content"))


@pytest.fixture
def kv_storage(tmp_path):
    """KeyValueFileSystemStorage rooted in a fresh directory."""
    return KeyValueFileSystemStorage(base_dir=str(tmp_path / "records"))


class TestAbstractFileSystemStorageDefaults:
    """Behaviour a subclass inherits when it does not override the hooks."""

    def test_missing_file_reads_as_none_by_default(self, tmp_path):
        """The base class returns None for files that do not exist."""
        storage = _PlainTextStorage(base_dir=str(tmp_path))

        assert storage.read_file(collection="notes", file_name="missing.txt") is None

    def test_round_trip_through_base_template_methods(self, tmp_path):
        """write_file and read_file delegate the I/O to the subclass hooks."""
        storage = _PlainTextStorage(base_dir=str(tmp_path))

        path = storage.write_file(collection="notes", file_name="hello.txt", data="hello")

        assert path == str(tmp_path.resolve() / "notes" / "hello.txt")
        assert storage.read_file(collection="notes", file_name="hello.txt") == "hello"
        assert storage.list_files(collection="notes") == ["hello.txt"]


class TestWriteFailures:
    """write_file wraps I/O and serialisation errors in DocpipeException."""

    def test_collection_path_occupied_by_file_raises_storage_error(self, content_storage):
        """The collection directory cannot be created where a file exists."""
        (content_storage.base_dir / "reports").write_text("not a directory", encoding="utf-8")

        with pytest.raises(DocpipeException, match=re.escape("Failed to write file reports/report.csv")) as exc_info:
            content_storage.write_text(collection="reports", file_name="report.csv", content="a,b")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, OSError)

    def test_unserialisable_record_raises_storage_error(self, kv_storage):
        """A record with a circular reference cannot be written as JSON."""
        record: dict[str, Any] = {"id": "flow-1"}
        record["self"] = record

        with pytest.raises(DocpipeException, match=re.escape("Failed to write file flows/flow-1.json")) as exc_info:
            kv_storage.save_record(collection="flows", key="flow-1", data=record)

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert kv_storage.record_exists(collection="flows", key="flow-1") is False


class TestReadFailures:
    """read_file re-raises validation errors and wraps everything else."""

    def test_path_traversal_in_collection_is_rejected(self, content_storage):
        """A collection containing '..' is rejected with StorageValidationError."""
        with pytest.raises(StorageValidationError, match="path traversal"):
            content_storage.read_text(collection="../outside", file_name="report.csv")

    def test_directory_in_place_of_file_raises_storage_error(self, content_storage):
        """Reading a path that is a directory fails with a storage error."""
        (content_storage.base_dir / "reports" / "report.csv").mkdir(parents=True)

        with pytest.raises(DocpipeException, match=re.escape("Failed to read file reports/report.csv")) as exc_info:
            content_storage.read_text(collection="reports", file_name="report.csv")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, OSError)

    def test_corrupted_json_record_raises_storage_error(self, kv_storage):
        """A record file that is not valid JSON is reported as corrupted."""
        collection_dir = kv_storage.base_dir / "flows"
        collection_dir.mkdir()
        (collection_dir / "flow-1.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(DocpipeException, match="Corrupted JSON file") as exc_info:
            kv_storage.get_record(collection="flows", key="flow-1")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR


class TestDeleteFailures:
    """delete_file re-raises validation errors and wraps everything else."""

    def test_path_traversal_in_collection_is_rejected(self, content_storage):
        """A collection containing '..' is rejected with StorageValidationError."""
        with pytest.raises(StorageValidationError, match="path traversal"):
            content_storage.delete_file(collection="../outside", file_name="report.csv")

    def test_directory_in_place_of_file_raises_storage_error(self, content_storage):
        """Deleting a path that is a directory fails and leaves it in place."""
        target = content_storage.base_dir / "reports" / "report.csv"
        target.mkdir(parents=True)

        with pytest.raises(DocpipeException, match=re.escape("Failed to delete file reports/report.csv")) as exc_info:
            content_storage.delete_file(collection="reports", file_name="report.csv")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, OSError)
        assert target.is_dir()


class TestContentListFiles:
    """ContentFileSystemStorage.list_files on unusual collection contents."""

    def test_subdirectories_are_ignored(self, content_storage):
        """Only regular files contribute to the listing."""
        content_storage.write_text(collection="reports", file_name="report.csv", content="a,b")
        (content_storage.base_dir / "reports" / "archive").mkdir()

        assert content_storage.list_files(collection="reports") == ["a,b"]

    def test_files_that_are_not_utf8_are_skipped(self, content_storage):
        """A file that cannot be decoded is skipped instead of failing the listing."""
        content_storage.write_text(collection="reports", file_name="report.csv", content="a,b")
        (content_storage.base_dir / "reports" / "binary.bin").write_bytes(b"\xff\xfe\xfa")

        assert content_storage.list_files(collection="reports") == ["a,b"]

    def test_collection_path_that_is_a_file_raises_storage_error(self, content_storage):
        """Listing a collection path that is a regular file fails."""
        (content_storage.base_dir / "reports").write_text("not a directory", encoding="utf-8")

        with pytest.raises(DocpipeException, match="Failed to list files in reports") as exc_info:
            content_storage.list_files(collection="reports")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, OSError)


class TestKeyValueListRecords:
    """KeyValueFileSystemStorage.list_records on unusual collection contents."""

    def test_missing_collection_lists_no_records(self, kv_storage):
        """A collection that was never written to has no records."""
        assert kv_storage.list_records(collection="never-written") == []

    def test_corrupted_record_files_are_skipped(self, kv_storage):
        """Record files with invalid JSON are skipped."""
        kv_storage.save_record(collection="flows", key="flow-1", data={"id": "flow-1"})
        (kv_storage.base_dir / "flows" / "flow-2.json").write_text("{not json", encoding="utf-8")

        assert kv_storage.list_records(collection="flows") == [{"id": "flow-1"}]

    def test_path_traversal_in_collection_raises(self, kv_storage):
        """A collection containing '..' is not listed."""
        with pytest.raises(DocpipeException, match="path traversal"):
            kv_storage.list_records(collection="../outside")
