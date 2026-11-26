# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for Filesystem-based incremental metadata store."""

import subprocess
import sys

import pyarrow.parquet as pq
import pytest

from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord
from docpipe.exceptions import FlowExecutionFailedException, JobStatsStoreInitializationException, LockTimeoutError


@pytest.fixture
def store(*, tmp_path):
    """Create Filesystem store with temporary directory."""
    return FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 5.0})


@pytest.fixture
def sample_records():
    """Sample incremental metadata records."""
    return [
        IncrementalMetadataRecord(
            job_id="job-1",
            doc_id="doc-1",
            name="document1.pdf",
            modified_time=1000,
            job_run_id="run-1",
            deleted=False,
        ),
        IncrementalMetadataRecord(
            job_id="job-1",
            doc_id="doc-2",
            name="document2.pdf",
            modified_time=2000,
            job_run_id="run-1",
            deleted=False,
        ),
    ]


class TestFilesystemIncrementalMetadataStore:
    """Test Filesystem-based incremental metadata store."""

    def test_upsert_and_get_processed_docs(self, *, store, sample_records):
        """Test upserting records and retrieving processed docs."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        result = store.get_processed_docs(job_id="job-1")

        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_upsert_overwrites_existing_doc(self, *, store, sample_records):
        """Test that upsert overwrites existing documents."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        updated_record = IncrementalMetadataRecord(
            job_id="job-1",
            doc_id="doc-1",
            name="document1_updated.pdf",
            modified_time=3000,
            job_run_id="run-2",
            deleted=False,
        )
        store.upsert_records(job_id="job-1", job_run_id="run-2", records=[updated_record])

        result = store.get_processed_docs(job_id="job-1")

        assert result == {
            "doc-1": {"modified_time": 3000, "job_run_id": "run-2"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_mark_missing_docs_as_deleted(self, *, store, sample_records):
        """Test marking missing documents as deleted."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        deleted_ids = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

        assert deleted_ids == {"doc-2"}
        assert store.get_processed_docs(job_id="job-1") == {"doc-1": {"modified_time": 1000, "job_run_id": "run-1"}}
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}

    def test_delete_docs(self, *, store, sample_records):
        """Test permanently deleting documents."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        store.delete_docs(job_id="job-1", doc_ids=["doc-1"])

        assert store.get_processed_docs(job_id="job-1") == {"doc-2": {"modified_time": 2000, "job_run_id": "run-1"}}

    def test_clear(self, *, store, sample_records):
        """Test clearing all metadata for a job."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        store.clear(job_id="job-1")

        assert store.get_processed_docs(job_id="job-1") == {}
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == set()

    def test_get_processed_docs_empty(self, *, store):
        """Test getting processed docs when none exist."""
        result = store.get_processed_docs(job_id="job-1")

        assert result == {}

    def test_get_soft_deleted_doc_ids_empty(self, *, store):
        """Test getting soft-deleted docs when none exist."""
        result = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert result == set()

    def test_delete_docs_empty_list(self, *, store, sample_records):
        """Test deleting with empty list does nothing."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        store.delete_docs(job_id="job-1", doc_ids=[])

        assert store.get_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_upsert_empty_records(self, *, store):
        """Test upserting empty records list does nothing."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=[])

        assert store.get_processed_docs(job_id="job-1") == {}

    def test_mark_missing_docs_with_no_existing_docs(self, *, store):
        """Test marking missing docs when no docs exist."""
        deleted_ids = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

        assert deleted_ids == set()

    def test_filesystem_file_persistence(self, *, store, sample_records, tmp_path):
        """Test that data persists to filesystem Parquet file."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        parquet_path = tmp_path / "job-1" / "inc_update_metadata" / "inc_update_metadata.parquet"
        assert parquet_path.exists()

        table = pq.read_table(parquet_path)
        assert table.num_rows == 2
        assert set(table["id"].to_pylist()) == {"doc-1", "doc-2"}

    def test_filesystem_schema_validation(self, *, store, sample_records, tmp_path):
        """Test that filesystem Parquet file has correct schema."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        parquet_path = tmp_path / "job-1" / "inc_update_metadata" / "inc_update_metadata.parquet"
        table = pq.read_table(parquet_path)

        expected_fields = {"job_id", "id", "name", "modified_time", "job_run_id", "deleted"}
        actual_fields = set(table.schema.names)
        assert actual_fields == expected_fields

    def test_multiple_jobs_isolated(self, *, store, sample_records):
        """Test that different jobs are isolated."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        job2_records = [
            IncrementalMetadataRecord(
                job_id="job-2",
                doc_id="doc-3",
                name="document3.pdf",
                modified_time=3000,
                job_run_id="run-2",
                deleted=False,
            )
        ]
        store.upsert_records(job_id="job-2", job_run_id="run-2", records=job2_records)

        assert store.get_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }
        assert store.get_processed_docs(job_id="job-2") == {"doc-3": {"modified_time": 3000, "job_run_id": "run-2"}}

    def test_delete_all_docs_removes_file(self, *, store, sample_records, tmp_path):
        """Test that deleting all docs removes the Parquet file."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        parquet_path = tmp_path / "job-1" / "inc_update_metadata" / "inc_update_metadata.parquet"
        assert parquet_path.exists()

        store.delete_docs(job_id="job-1", doc_ids=["doc-1", "doc-2"])

        assert not parquet_path.exists()

    def test_soft_deleted_docs_not_in_processed(self, *, store, sample_records):
        """Test that soft-deleted docs are not returned in processed docs."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
        store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

        processed = store.get_processed_docs(job_id="job-1")
        deleted = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert processed == {"doc-1": {"modified_time": 1000, "job_run_id": "run-1"}}
        assert deleted == {"doc-2"}
        assert "doc-2" not in processed

    def test_clear_nonexistent_job(self, *, store):
        """Test clearing a job that doesn't exist."""
        store.clear(job_id="nonexistent-job")
        # Should not raise an error

    def test_atomic_write_on_failure(self, *, store, sample_records, tmp_path, mocker):
        """Test that failed writes don't corrupt data."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        # Mock pq.write_table to fail
        mocker.patch("pyarrow.parquet.write_table", side_effect=Exception("Write failed"))

        with pytest.raises(FlowExecutionFailedException):
            store.upsert_records(job_id="job-1", job_run_id="run-2", records=[sample_records[0]])

        # Original data should still be intact
        result = store.get_processed_docs(job_id="job-1")
        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

        # Temp file should be cleaned up
        temp_files = list((tmp_path / "job-1" / "inc_update_metadata").glob("*.tmp"))
        assert len(temp_files) == 0

    def test_upsert_with_null_values(self, *, store):
        """Test upserting records with null optional fields."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-1",
                name=None,
                modified_time=None,
                job_run_id=None,
                deleted=False,
            )
        ]

        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)

        result = store.get_processed_docs(job_id="job-1")
        assert "doc-1" in result
        assert result["doc-1"] == {"modified_time": None, "job_run_id": None}

    def test_large_batch_upsert(self, *, store):
        """Test upserting a large batch of records."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id=f"doc-{i}",
                name=f"document{i}.pdf",
                modified_time=i * 1000,
                job_run_id="run-1",
                deleted=False,
            )
            for i in range(1000)
        ]

        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)

        result = store.get_processed_docs(job_id="job-1")
        assert len(result) == 1000
        assert result["doc-500"] == {"modified_time": 500000, "job_run_id": "run-1"}

    def test_mark_multiple_docs_as_deleted(self, *, store):
        """Test marking multiple documents as deleted at once."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id=f"doc-{i}",
                name=f"document{i}.pdf",
                modified_time=i * 1000,
                job_run_id="run-1",
                deleted=False,
            )
            for i in range(10)
        ]
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)

        # Keep only doc-0, doc-1, doc-2
        deleted_ids = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-0", "doc-1", "doc-2"])

        assert len(deleted_ids) == 7
        assert store.get_processed_docs(job_id="job-1") == {
            "doc-0": {"modified_time": 0, "job_run_id": "run-1"},
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }
        assert len(store.get_soft_deleted_doc_ids(job_id="job-1")) == 7

    def test_unmark_soft_deleted_docs(self, *, store):
        """Test unmarking soft-deleted documents."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-1",
                name="document1.pdf",
                modified_time=1000,
                job_run_id="run-1",
                deleted=False,
            ),
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-2",
                name="document2.pdf",
                modified_time=2000,
                job_run_id="run-1",
                deleted=False,
            ),
        ]
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)
        store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}

        # Unmark specific doc
        store.unmark_soft_deleted_docs(job_id="job-1", doc_ids=["doc-2"])
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == set()
        assert "doc-2" in store.get_processed_docs(job_id="job-1")

        # Re-mark and unmark all
        store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}
        store.unmark_soft_deleted_docs(job_id="job-1", doc_ids=None)
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == set()

    def test_purge_soft_deleted_docs(self, *, store):
        """Test purging soft-deleted records."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-1",
                name="document1.pdf",
                modified_time=1000,
                job_run_id="run-1",
                deleted=False,
            ),
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-2",
                name="document2.pdf",
                modified_time=2000,
                job_run_id="run-1",
                deleted=False,
            ),
        ]
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)
        store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}

        store.purge_soft_deleted_docs(job_id="job-1")
        assert store.get_soft_deleted_doc_ids(job_id="job-1") == set()
        assert store.get_processed_docs(job_id="job-1") == {"doc-1": {"modified_time": 1000, "job_run_id": "run-1"}}

    def test_duplicate_doc_ids_in_single_batch(self, *, store):
        """Test that duplicate doc_ids in one batch store the last record once."""
        records = [
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-dup",
                name="first.pdf",
                modified_time=1000,
                job_run_id="run-1",
                deleted=False,
            ),
            IncrementalMetadataRecord(
                job_id="job-1",
                doc_id="doc-dup",
                name="second.pdf",
                modified_time=2000,
                job_run_id="run-1",
                deleted=False,
            ),
        ]
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)

        result = store.get_processed_docs(job_id="job-1")
        assert len(result) == 1
        assert result["doc-dup"] == {"modified_time": 2000, "job_run_id": "run-1"}

    def test_clear_preserves_lock_file(self, *, store, sample_records, tmp_path):
        """Test that clear() removes parquet data but preserves .locks/metadata.lock."""
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        parquet_path = tmp_path / "job-1" / "inc_update_metadata" / "inc_update_metadata.parquet"
        lock_path = tmp_path / "job-1" / "inc_update_metadata" / ".locks" / "metadata.lock"
        assert parquet_path.exists()
        assert lock_path.exists()

        store.clear(job_id="job-1")

        assert not parquet_path.exists()
        assert lock_path.exists()

    def test_default_lock_timeout_is_30_seconds(self, *, tmp_path):
        """Test that lock_timeout defaults to 30.0 seconds when not configured."""
        default_store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path)})
        assert default_store._lock_timeout == 30.0

    def test_custom_lock_timeout_is_applied(self, *, tmp_path):
        """Test that valid int and float lock_timeout values are accepted."""
        float_store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 12.5})
        int_store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 7})
        assert float_store._lock_timeout == 12.5
        assert int_store._lock_timeout == 7.0

    @pytest.mark.parametrize("invalid_timeout", [0, -1.0, "30", True, float("inf"), float("nan")])
    def test_invalid_lock_timeout_is_rejected(self, *, tmp_path, invalid_timeout):
        """Test that non-positive, non-numeric, bool and non-finite lock_timeout values are rejected."""
        with pytest.raises(JobStatsStoreInitializationException, match="Invalid lock_timeout"):
            FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": invalid_timeout})

    def test_lock_timeout_raises_lock_timeout_error(self, *, tmp_path):
        """Test that lock acquisition timeout raises LockTimeoutError."""
        fast_store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 0.2})
        lock_path = tmp_path / "job-1" / "inc_update_metadata" / ".locks" / "metadata.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        code = f"""
import portalocker, time
flags = portalocker.LOCK_EX | portalocker.LOCK_NB
with portalocker.Lock({str(lock_path)!r}, flags=flags, timeout=5.0):
    print("LOCKED", flush=True)
    time.sleep(2.0)
"""
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline() if proc.stdout else ""
            assert "LOCKED" in line

            with pytest.raises(LockTimeoutError) as exc_info:
                fast_store.get_processed_docs(job_id="job-1")
            assert "job-1" in str(exc_info.value)
        finally:
            proc.kill()
            proc.wait()

    def test_different_jobs_do_not_contend(self, *, tmp_path, sample_records):
        """Test that an exclusive lock on job-1 does not block operations on job-2."""
        store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 0.5})
        lock_path_1 = tmp_path / "job-1" / "inc_update_metadata" / ".locks" / "metadata.lock"
        lock_path_1.parent.mkdir(parents=True, exist_ok=True)

        code = f"""
import portalocker, time
flags = portalocker.LOCK_EX | portalocker.LOCK_NB
with portalocker.Lock({str(lock_path_1)!r}, flags=flags, timeout=5.0):
    print("LOCKED", flush=True)
    time.sleep(2.0)
"""
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline() if proc.stdout else ""
            assert "LOCKED" in line

            # Operations on job-2 should succeed without waiting
            job2_record = IncrementalMetadataRecord(
                job_id="job-2",
                doc_id="doc-99",
                name="job2.pdf",
                modified_time=5000,
                job_run_id="run-1",
                deleted=False,
            )
            store.upsert_records(job_id="job-2", job_run_id="run-1", records=[job2_record])
            res = store.get_processed_docs(job_id="job-2")
            assert "doc-99" in res
        finally:
            proc.kill()
            proc.wait()

    def test_concurrent_readers_do_not_block_each_other(self, *, tmp_path, sample_records):
        """Test that multiple processes can hold shared read locks simultaneously."""
        store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 0.5})
        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
        lock_path = tmp_path / "job-1" / "inc_update_metadata" / ".locks" / "metadata.lock"

        code = f"""
import portalocker, time
flags = portalocker.LOCK_SH | portalocker.LOCK_NB
with portalocker.Lock({str(lock_path)!r}, flags=flags, timeout=5.0):
    print("READ_LOCKED", flush=True)
    time.sleep(2.0)
"""
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline() if proc.stdout else ""
            assert "READ_LOCKED" in line

            # Second reader can read without blocking or timing out
            result = store.get_processed_docs(job_id="job-1")
            assert len(result) == 2
        finally:
            proc.kill()
            proc.wait()

    def test_cross_process_writer_excludes_readers_and_writers(self, *, tmp_path, sample_records):
        """Test that an external process holding an exclusive lock excludes readers and writers."""
        fast_store = FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 0.2})
        fast_store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
        lock_path = tmp_path / "job-1" / "inc_update_metadata" / ".locks" / "metadata.lock"

        code = f"""
import portalocker, time
flags = portalocker.LOCK_EX | portalocker.LOCK_NB
with portalocker.Lock({str(lock_path)!r}, flags=flags, timeout=5.0):
    print("WRITE_LOCKED", flush=True)
    time.sleep(2.0)
"""
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline() if proc.stdout else ""
            assert "WRITE_LOCKED" in line

            # Reader fails with LockTimeoutError
            with pytest.raises(LockTimeoutError):
                fast_store.get_processed_docs(job_id="job-1")

            # Soft-delete query fails with LockTimeoutError
            with pytest.raises(LockTimeoutError):
                fast_store.get_soft_deleted_doc_ids(job_id="job-1")

            # Writer fails with LockTimeoutError
            with pytest.raises(LockTimeoutError):
                fast_store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])
        finally:
            proc.kill()
            proc.wait()
