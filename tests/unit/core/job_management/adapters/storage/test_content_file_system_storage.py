# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for ContentFileSystemStorage."""

import pytest

from docpipe.storage.exceptions import StorageValidationError
from docpipe.storage.file_system.content_file_system_storage import ContentFileSystemStorage


def _storage(tmp_path):
    """Return a fresh ContentFileSystemStorage instance rooted at tmp_path."""
    ContentFileSystemStorage._instances.clear()
    return ContentFileSystemStorage(base_dir=str(tmp_path))


class TestCheckDataAvailability:
    """Tests for ContentFileSystemStorage.check_data_availability."""

    def test_returns_true_when_output_parquet_exists(self, tmp_path):
        """Returns (True, '') when output.parquet exists in any subdirectory of data/."""
        storage = _storage(tmp_path)
        parquet_path = tmp_path / "job-1" / "run-1" / "data" / "ingest_0"
        parquet_path.mkdir(parents=True)
        (parquet_path / "output.parquet").write_bytes(b"")

        result = storage.check_data_availability(collection="job-1/run-1")

        assert result == (True, "")

    def test_returns_false_when_data_directory_missing(self, tmp_path):
        """Returns (False, '...') when the data/ directory does not exist."""
        storage = _storage(tmp_path)

        available, message = storage.check_data_availability(collection="job-1/run-1")

        assert available is False
        assert "Data directory not found" in message

    def test_returns_false_when_data_dir_exists_but_no_parquet(self, tmp_path):
        """Returns (False, '...') when data/ exists but contains no output.parquet."""
        storage = _storage(tmp_path)
        data_dir = tmp_path / "job-1" / "run-1" / "data"
        data_dir.mkdir(parents=True)

        available, message = storage.check_data_availability(collection="job-1/run-1")

        assert available is False
        assert "No output.parquet found" in message

    def test_works_with_non_ingest_step_name(self, tmp_path):
        """Works correctly with a non-ingest step name (e.g. Data_assets_0)."""
        storage = _storage(tmp_path)
        parquet_path = tmp_path / "job-2" / "run-2" / "data" / "Data_assets_0"
        parquet_path.mkdir(parents=True)
        (parquet_path / "output.parquet").write_bytes(b"")

        result = storage.check_data_availability(collection="job-2/run-2")

        assert result == (True, "")

    def test_works_with_ingest_step_name_backward_compat(self, tmp_path):
        """Works correctly with a step named ingest_0 (backward compatibility)."""
        storage = _storage(tmp_path)
        parquet_path = tmp_path / "job-3" / "run-3" / "data" / "ingest_0"
        parquet_path.mkdir(parents=True)
        (parquet_path / "output.parquet").write_bytes(b"")

        result = storage.check_data_availability(collection="job-3/run-3")

        assert result == (True, "")


class TestWriteAndReadText:
    """Tests for write_text and read_text round-trip."""

    def test_write_text_creates_file_and_returns_path(self, tmp_path):
        """write_text persists content and returns the absolute path."""
        storage = _storage(tmp_path)

        path = storage.write_text(collection="job/run", file_name="report.csv", content="hello,world\n")

        assert path.endswith("report.csv")
        assert (tmp_path / "job" / "run" / "report.csv").read_text() == "hello,world\n"

    def test_read_text_returns_written_content(self, tmp_path):
        """read_text returns the same content previously written."""
        storage = _storage(tmp_path)
        storage.write_text(collection="job/run", file_name="report.csv", content="GUID,Status\ndoc1,Ingested\n")

        content = storage.read_text(collection="job/run", file_name="report.csv")

        assert content == "GUID,Status\ndoc1,Ingested\n"

    def test_read_text_returns_empty_string_when_file_missing(self, tmp_path):
        """read_text returns empty string when file does not exist."""
        storage = _storage(tmp_path)
        (tmp_path / "job" / "run").mkdir(parents=True)

        content = storage.read_text(collection="job/run", file_name="missing.csv")

        assert content == ""

    def test_write_text_overwrites_existing_file(self, tmp_path):
        """Subsequent write_text calls overwrite the previous content."""
        storage = _storage(tmp_path)
        storage.write_text(collection="job/run", file_name="r.csv", content="v1")
        storage.write_text(collection="job/run", file_name="r.csv", content="v2")

        assert storage.read_text(collection="job/run", file_name="r.csv") == "v2"

    def test_write_text_creates_nested_collection_dirs(self, tmp_path):
        """write_text creates any missing parent directories automatically."""
        storage = _storage(tmp_path)

        storage.write_text(collection="deep/nested/job/run", file_name="r.csv", content="x")

        assert (tmp_path / "deep" / "nested" / "job" / "run" / "r.csv").exists()

    def test_write_and_read_text_keep_line_endings(self, tmp_path):
        """CSV content with \\r\\n line endings is stored and read back unchanged (#386)."""
        storage = _storage(tmp_path)
        content = "GUID,Status\r\nd1,Ingested\r\n"

        storage.write_text(collection="job/run", file_name="r.csv", content=content)

        assert (tmp_path / "job" / "run" / "r.csv").read_bytes() == content.encode("utf-8")
        assert storage.read_text(collection="job/run", file_name="r.csv") == content


class TestFileExists:
    """Tests for file_exists."""

    def test_returns_true_when_file_exists(self, tmp_path):
        """file_exists returns True after write_text."""
        storage = _storage(tmp_path)
        storage.write_text(collection="job/run", file_name="r.csv", content="data")

        assert storage.file_exists(collection="job/run", file_name="r.csv") is True

    def test_returns_false_when_file_missing(self, tmp_path):
        """file_exists returns False for a file that was never written."""
        storage = _storage(tmp_path)

        assert storage.file_exists(collection="job/run", file_name="missing.csv") is False


class TestDeleteFile:
    """Tests for delete_file."""

    def test_deletes_existing_file_and_returns_true(self, tmp_path):
        """delete_file removes the file and returns True."""
        storage = _storage(tmp_path)
        storage.write_text(collection="job/run", file_name="r.csv", content="data")

        result = storage.delete_file(collection="job/run", file_name="r.csv")

        assert result is True
        assert not (tmp_path / "job" / "run" / "r.csv").exists()

    def test_returns_false_when_file_does_not_exist(self, tmp_path):
        """delete_file returns False when the file does not exist."""
        storage = _storage(tmp_path)

        result = storage.delete_file(collection="job/run", file_name="missing.csv")

        assert result is False


class TestListFiles:
    """Tests for list_files."""

    def test_returns_file_contents(self, tmp_path):
        """list_files returns the contents of all files in the collection directory."""
        storage = _storage(tmp_path)
        storage.write_text(collection="job/run", file_name="a.csv", content="aaa")
        storage.write_text(collection="job/run", file_name="b.csv", content="bbb")

        contents = storage.list_files(collection="job/run")

        assert sorted(contents) == ["aaa", "bbb"]

    def test_returns_empty_list_when_collection_missing(self, tmp_path):
        """list_files returns [] when the collection directory does not exist."""
        storage = _storage(tmp_path)

        assert storage.list_files(collection="nonexistent/run") == []

    def test_returns_empty_list_when_collection_is_empty(self, tmp_path):
        """list_files returns [] when the collection directory exists but is empty."""
        storage = _storage(tmp_path)
        (tmp_path / "job" / "run").mkdir(parents=True)

        assert storage.list_files(collection="job/run") == []


class TestValidation:
    """Tests for collection and file_name validation."""

    def test_rejects_empty_collection(self, tmp_path):
        """Empty collection raises StorageValidationError."""
        storage = _storage(tmp_path)

        with pytest.raises(StorageValidationError):
            storage.write_text(collection="", file_name="r.csv", content="x")

    def test_rejects_path_traversal_in_collection(self, tmp_path):
        """Collection containing '..' raises StorageValidationError."""
        storage = _storage(tmp_path)

        with pytest.raises(StorageValidationError):
            storage.write_text(collection="../escape", file_name="r.csv", content="x")

    def test_rejects_empty_file_name(self, tmp_path):
        """Empty file_name raises StorageValidationError."""
        storage = _storage(tmp_path)

        with pytest.raises(StorageValidationError):
            storage.write_text(collection="job/run", file_name="", content="x")

    def test_rejects_path_traversal_in_file_name(self, tmp_path):
        """file_name containing '/' raises StorageValidationError."""
        storage = _storage(tmp_path)

        with pytest.raises(StorageValidationError):
            storage.write_text(collection="job/run", file_name="../../etc/passwd", content="x")


class TestSingleton:
    """Singleton behavior: same base_dir returns same instance."""

    def test_same_base_dir_returns_same_instance(self, tmp_path):
        """Two calls with the same base_dir return the identical object."""
        ContentFileSystemStorage._instances.clear()
        a = ContentFileSystemStorage(base_dir=str(tmp_path))
        b = ContentFileSystemStorage(base_dir=str(tmp_path))

        assert a is b

    def test_different_base_dirs_return_different_instances(self, tmp_path):
        """Two calls with different base_dirs return different objects."""
        ContentFileSystemStorage._instances.clear()
        a = ContentFileSystemStorage(base_dir=str(tmp_path / "dir_a"))
        b = ContentFileSystemStorage(base_dir=str(tmp_path / "dir_b"))

        assert a is not b
