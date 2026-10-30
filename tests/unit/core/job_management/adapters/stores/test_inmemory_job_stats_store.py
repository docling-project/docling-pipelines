"""
Unit tests for InMemoryJobStatsStore - Phase 5 compatibility tests

Tests cover:
- Port signature compliance (keyword-only args)
- Batch-scoped write semantics
- Fine-grained locking behavior
- Immutability guarantees
- Concurrent micro-batching scenarios
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import (
    InMemoryJobStatsStore,
)
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.exceptions.docpipe_exceptions import JobStatsStoreDeleteException


@pytest.fixture
def store():
    """Create fresh store for each test."""
    store = InMemoryJobStatsStore()
    yield store
    store.clear()


@pytest.fixture
def sample_job_stats():
    """Sample job stats for testing."""
    return JobStats(
        job_id="12345678-1234-1234-1234-123456789abc",
        job_run_id="87654321-4321-4321-4321-cba987654321",
        status=ExecutionStatus.RUNNING,
        processed_docs=100,
        failed_docs=5,
        progress_timestamp=1704067300,
    )


@pytest.fixture
def sample_node_stats():
    """Sample node stats for testing."""
    return NodeStats(
        id="abcdef12-3456-7890-abcd-ef1234567890",
        name="TestNode",
        node_status=ExecutionStatus.COMPLETED,
        batch_id="fedcba98-7654-3210-fedc-ba9876543210",
        batch_num=0,
    )


class TestPortSignatureCompliance:
    """Test that all methods match port signatures (keyword-only args)."""

    def test_store_node_stats_requires_keyword_args(self, *, store, sample_node_stats):
        """store_node_stats must use keyword-only arguments."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"

        # Should work with keyword args
        store.store_node_stats(job_run_id=job_run_id, node_stats=sample_node_stats)

        # Should fail with positional args (if we tried)
        # store.store_node_stats(job_run_id, sample_node_stats)  # Would raise TypeError

    def test_get_node_stats_requires_keyword_args(self, *, store):
        """get_node_stats must use keyword-only arguments."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"

        # Should work with keyword args
        result = store.get_node_stats(job_run_id=job_run_id)
        assert result == []

    def test_bulk_store_node_stats_requires_keyword_args(self, *, store, sample_node_stats):
        """bulk_store_node_stats must use keyword-only arguments."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"

        # Should work with keyword args
        store.bulk_store_node_stats(job_run_id=job_run_id, node_stats_list=[sample_node_stats])


class TestBatchScopedWrites:
    """Test batch-scoped persistence semantics."""

    def test_store_multiple_batches_same_node(self, *, store):
        """Multiple batches for same node should be stored separately."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"
        node_id = "abcdef12-3456-7890-abcd-ef1234567890"

        # Store 3 batches for same node
        for i in range(3):
            batch_id = str(uuid.uuid4())
            node_stats = NodeStats(
                id=node_id,
                name="TestNode",
                batch_id=batch_id,
                batch_num=i,
                docs_completed_count=10 * (i + 1),
            )
            store.store_node_stats(job_run_id=job_run_id, node_stats=node_stats)

        # Retrieve all node stats
        all_stats = store.get_node_stats(job_run_id=job_run_id)
        assert len(all_stats) == 3

        # Verify each batch is separate
        batch_ids = {stats.batch_id for stats in all_stats}
        assert len(batch_ids) == 3

    def test_get_batch_node_stats_filters_non_batch(self, *, store):
        """get_batch_node_stats should only return batch records."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"
        node_id = "abcdef12-3456-7890-abcd-ef1234567890"

        # Store batch record
        batch_stats = NodeStats(
            id=node_id,
            name="TestNode",
            batch_id="fedcba98-7654-3210-fedc-ba9876543210",
            batch_num=0,
            node_status=ExecutionStatus.COMPLETED,
        )
        store.store_node_stats(job_run_id=job_run_id, node_stats=batch_stats)

        # Store non-batch record (batch_id=None)
        non_batch_stats = NodeStats(
            id=node_id,
            name="TestNode",
            batch_id=None,
            node_status=ExecutionStatus.COMPLETED,
        )
        store.store_node_stats(job_run_id=job_run_id, node_stats=non_batch_stats)

        # get_batch_node_stats should only return batch record
        batch_dict = store.get_batch_node_stats(job_run_id=job_run_id)
        assert node_id in batch_dict
        assert len(batch_dict[node_id]) == 1
        assert "fedcba98-7654-3210-fedc-ba9876543210" in batch_dict[node_id]

    def test_get_node_stats_by_batch_and_node_with_none(self, *, store):
        """get_node_stats_by_batch_and_node should handle batch_id=None."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"
        node_id = "abcdef12-3456-7890-abcd-ef1234567890"

        # Store non-batch record
        non_batch_stats = NodeStats(
            id=node_id,
            name="TestNode",
            batch_id=None,
            node_status=ExecutionStatus.COMPLETED,
        )
        store.store_node_stats(job_run_id=job_run_id, node_stats=non_batch_stats)

        # Retrieve with batch_id=None
        result = store.get_node_stats_by_batch_and_node(job_run_id=job_run_id, node_id=node_id, batch_id=None)
        assert result is not None
        assert result.batch_id is None


class TestImmutability:
    """Test that deep copy prevents external mutations."""

    def test_store_job_stats_deep_copy(self, *, store, sample_job_stats):
        """Stored job stats should be independent copy."""
        job_run_id = sample_job_stats.job_run_id

        # Store job stats
        store.store_job_stats(sample_job_stats)

        # Modify original
        sample_job_stats.processed_docs = 999

        # Retrieved should be unchanged
        retrieved = store.get_job_stats(job_run_id)
        assert retrieved.processed_docs == 100
        assert retrieved.progress_timestamp == 1704067300

    def test_get_job_stats_deep_copy(self, *, store, sample_job_stats):
        """Retrieved job stats should be independent copy."""
        job_run_id = sample_job_stats.job_run_id

        # Store job stats
        store.store_job_stats(sample_job_stats)

        # Retrieve and modify
        retrieved = store.get_job_stats(job_run_id)
        retrieved.processed_docs = 999

        # Re-retrieve should be unchanged
        retrieved_again = store.get_job_stats(job_run_id)
        assert retrieved_again.processed_docs == 100

    def test_atomic_increment_immutability(self, *, store, sample_job_stats):
        """atomic_increment_fields should not mutate stored object in-place."""
        job_run_id = sample_job_stats.job_run_id

        # Store job stats
        store.store_job_stats(sample_job_stats)

        # Get reference before update
        before_update = store.get_job_stats(job_run_id)

        # Atomic increment
        store.atomic_increment_fields(job_run_id=job_run_id, increments={"processed_docs": 50})

        # Original reference should be unchanged (deep copy)
        assert before_update.processed_docs == 100

        # New retrieval should have updated value
        after_update = store.get_job_stats(job_run_id)
        assert after_update.processed_docs == 150


class TestFineGrainedLocking:
    """Test fine-grained per-job locking behavior."""

    def test_concurrent_different_jobs_no_contention(self, *, store):
        """Different job runs should not block each other."""
        results = []

        def store_job(job_num):
            job_run_id = str(uuid.uuid4())
            job_stats = JobStats(
                job_id="12345678-1234-1234-1234-123456789abc",
                job_run_id=job_run_id,
                status=ExecutionStatus.RUNNING,
                processed_docs=job_num,
            )
            store.store_job_stats(job_stats)
            results.append(job_num)

        # Run 10 concurrent jobs
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(store_job, i) for i in range(10)]
            for future in futures:
                future.result()

        # All jobs should complete
        assert len(results) == 10
        assert set(results) == set(range(10))

    def test_concurrent_same_job_serializes(self, *, store):
        """Concurrent updates to same job should serialize correctly."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"
        job_stats = JobStats(
            job_id="12345678-1234-1234-1234-123456789abc",
            job_run_id=job_run_id,
            status=ExecutionStatus.RUNNING,
            processed_docs=0,
        )
        store.store_job_stats(job_stats)

        def increment_docs():
            for _ in range(100):
                store.atomic_increment_fields(job_run_id=job_run_id, increments={"processed_docs": 1})

        # Run 5 threads incrementing concurrently
        threads = [threading.Thread(target=increment_docs) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Final count should be 500 (5 threads * 100 increments)
        final_stats = store.get_job_stats(job_run_id)
        assert final_stats.processed_docs == 500

    def test_lock_cleanup_on_delete(self, *, store, sample_job_stats):
        """Deleting job should clean up its lock."""
        job_run_id = sample_job_stats.job_run_id

        # Store job stats (creates lock)
        store.store_job_stats(sample_job_stats)
        assert job_run_id in store._job_locks

        # Delete job stats
        store.delete_job_stats(job_run_id)

        # Lock should be cleaned up
        assert job_run_id not in store._job_locks


class TestAtomicOperations:
    """Test atomic_increment_fields with various scenarios."""

    def test_atomic_increment_basic(self, *, store, sample_job_stats):
        """Basic increment operation."""
        job_run_id = sample_job_stats.job_run_id
        store.store_job_stats(sample_job_stats)

        store.atomic_increment_fields(job_run_id=job_run_id, increments={"processed_docs": 50, "failed_docs": 2})

        result = store.get_job_stats(job_run_id)
        assert result.processed_docs == 150
        assert result.failed_docs == 7

    def test_atomic_increment_with_updates(self, *, store, sample_job_stats):
        """Increment with field updates."""
        job_run_id = sample_job_stats.job_run_id
        store.store_job_stats(sample_job_stats)

        store.atomic_increment_fields(
            job_run_id=job_run_id,
            increments={"processed_docs": 50},
            updates={"status": ExecutionStatus.COMPLETED},
        )

        result = store.get_job_stats(job_run_id)
        assert result.processed_docs == 150
        assert result.status == ExecutionStatus.COMPLETED

    def test_atomic_increment_with_jsonb_merge(self, *, store, sample_job_stats):
        """Increment with JSONB merge."""
        job_run_id = sample_job_stats.job_run_id
        sample_job_stats.page_type_stats = {"pdf": 10, "docx": 5}
        store.store_job_stats(sample_job_stats)

        store.atomic_increment_fields(
            job_run_id=job_run_id,
            increments={"processed_docs": 50},
            jsonb_merges={"page_type_stats": {"pdf": 15, "xlsx": 3}},
        )

        result = store.get_job_stats(job_run_id)
        assert result.page_type_stats == {"pdf": 15, "docx": 5, "xlsx": 3}

    def test_atomic_increment_nonexistent_job(self, *, store):
        """Increment on nonexistent job should not raise error."""
        # Should log warning but not raise
        store.atomic_increment_fields(job_run_id="nonexistent", increments={"processed_docs": 10})


class TestBulkOperations:
    """Test bulk_store_node_stats for micro-batching."""

    def test_bulk_store_multiple_batches(self, *, store):
        """Bulk store should handle multiple batches efficiently."""
        job_run_id = "87654321-4321-4321-4321-cba987654321"
        node_id = "abcdef12-3456-7890-abcd-ef1234567890"

        # Create 10 batch records
        node_stats_list = [
            NodeStats(
                id=node_id,
                name="TestNode",
                batch_id=str(uuid.uuid4()),
                batch_num=i,
                node_status=ExecutionStatus.PENDING,
            )
            for i in range(10)
        ]

        # Bulk store
        store.bulk_store_node_stats(job_run_id=job_run_id, node_stats_list=node_stats_list)

        # Verify all stored
        all_stats = store.get_node_stats(job_run_id=job_run_id)
        assert len(all_stats) == 10

        batch_dict = store.get_batch_node_stats(job_run_id=job_run_id)
        assert len(batch_dict[node_id]) == 10


class TestListJobRuns:
    """Test list_job_runs filtering."""

    def test_list_job_runs_no_filter(self, *, store):
        """List all job runs."""
        # Store 3 jobs
        for _i in range(3):
            job_stats = JobStats(
                job_id=str(uuid.uuid4()),
                job_run_id=str(uuid.uuid4()),
                status=ExecutionStatus.RUNNING,
            )
            store.store_job_stats(job_stats)

        result = store.list_job_runs()
        assert len(result) == 3

    def test_list_job_runs_filter_by_status(self, *, store):
        """Filter job runs by status."""
        # Store jobs with different statuses
        for _i, status in enumerate([ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]):
            job_stats = JobStats(job_id=str(uuid.uuid4()), job_run_id=str(uuid.uuid4()), status=status)
            store.store_job_stats(job_stats)

        result = store.list_job_runs(status=ExecutionStatus.COMPLETED)
        assert len(result) == 1
        assert result[0].status == ExecutionStatus.COMPLETED

    def test_list_job_runs_sorted_by_start_time(self, *, store):
        """Job runs should be sorted by start_time descending."""
        # Store jobs with different start times
        for i in range(3):
            job_stats = JobStats(
                job_id=str(uuid.uuid4()),
                job_run_id=str(uuid.uuid4()),
                status=ExecutionStatus.RUNNING,
                start_time=1000 + i * 100,
            )
            store.store_job_stats(job_stats)

        result = store.list_job_runs()
        # Should be sorted descending (most recent first)
        assert result[0].start_time == 1200
        assert result[1].start_time == 1100
        assert result[2].start_time == 1000


class TestCountJobRuns:
    """Count uses the same filters as list and ignores the list limit."""

    def test_count_job_runs_empty(self, *, store):
        assert store.count_job_runs() == 0

    def test_count_job_runs_matches_filters_past_list_limit(self, *, store):
        for index in range(6):
            store.store_job_stats(
                JobStats(
                    job_id="job-a" if index < 4 else "job-b",
                    job_run_id=str(uuid.uuid4()),
                    status=ExecutionStatus.COMPLETED if index % 2 == 0 else ExecutionStatus.FAILED,
                )
            )

        assert len(store.list_job_runs(job_id="job-a", limit=1)) == 1
        assert store.count_job_runs(job_id="job-a") == 4
        assert store.count_job_runs(job_ids=["job-b"]) == 2
        assert store.count_job_runs(status=ExecutionStatus.COMPLETED) == 3
        assert store.count_job_runs(job_id="job-a", status=ExecutionStatus.FAILED) == 2
        assert store.count_job_runs() == 6


class TestClearAndDelete:
    """Test cleanup operations."""

    def test_clear_removes_all_data(self, *, store, sample_job_stats, sample_node_stats):
        """clear() should remove all data."""
        job_run_id = sample_job_stats.job_run_id

        store.store_job_stats(sample_job_stats)
        store.store_node_stats(job_run_id=job_run_id, node_stats=sample_node_stats)

        # Verify data exists before clear
        assert store.get_job_stats(job_run_id) is not None
        assert len(store.get_node_stats(job_run_id=job_run_id)) > 0

        store.clear()

        # After clear, all data and locks should be gone
        assert len(store._job_stats) == 0
        assert len(store._node_stats) == 0
        assert len(store._job_locks) == 0

    def test_delete_job_stats_removes_all_related(self, *, store, sample_job_stats, sample_node_stats):
        """delete_job_stats should remove job and node stats."""
        job_run_id = sample_job_stats.job_run_id

        store.store_job_stats(sample_job_stats)
        store.store_node_stats(job_run_id=job_run_id, node_stats=sample_node_stats)

        store.delete_job_stats(job_run_id)

        assert store.get_job_stats(job_run_id) is None
        assert store.get_node_stats(job_run_id=job_run_id) == []

    def test_delete_nonexistent_job_raises(self, *, store):
        """Deleting nonexistent job should raise JobStatsStoreDeleteException."""
        with pytest.raises(JobStatsStoreDeleteException, match="Job run not found"):
            store.delete_job_stats("nonexistent")
