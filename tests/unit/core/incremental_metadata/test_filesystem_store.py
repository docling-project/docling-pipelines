# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for Filesystem-based incremental metadata store."""

import pyarrow.parquet as pq
import pytest

from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException


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
