"""Tests for concurrency utilities."""

import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from docpipe.utils.infrastructure.concurrency import (
    process_batches_in_parallel,
    run_with_session_info,
    submit_task_with_context_propagation,
)


class TestProcessBatchesInParallel:
    """Test process_batches_in_parallel function."""

    def test_process_empty_batches(self):
        """Test processing empty batch list."""

        def worker_fn(batch):
            return batch

        results = process_batches_in_parallel(batches=[], worker_fn=worker_fn)

        assert results == []

    def test_process_single_batch(self):
        """Test processing single batch."""

        def worker_fn(batch):
            return batch * 2

        results = process_batches_in_parallel(batches=[5], worker_fn=worker_fn)

        assert results == [10]

    def test_process_multiple_batches(self):
        """Test processing multiple batches."""

        def worker_fn(batch):
            return batch * 2

        batches = [1, 2, 3, 4, 5]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)

        # Results may be in any order due to parallel execution
        assert sorted(results) == [2, 4, 6, 8, 10]

    def test_process_with_custom_max_workers(self):
        """Test processing with custom max_workers."""

        def worker_fn(batch):
            return batch

        batches = [1, 2, 3]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn, max_workers=2)

        assert sorted(results) == [1, 2, 3]

    def test_process_with_result_extractor(self):
        """Test processing with result extractor."""

        def worker_fn(batch):
            return {"data": [batch, batch * 2]}

        def result_extractor(result):
            return result["data"]

        batches = [1, 2]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn, result_extractor=result_extractor)

        # Results are flattened by extractor
        assert sorted(results) == [1, 2, 2, 4]

    def test_process_with_list_results(self):
        """Test that list results are extended, not appended."""

        def worker_fn(batch):
            return [batch, batch + 1]

        batches = [1, 3]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)

        # Lists should be extended
        assert sorted(results) == [1, 2, 3, 4]

    def test_process_with_none_results(self):
        """Test that None results are filtered out."""

        def worker_fn(batch):
            return None if batch % 2 == 0 else batch

        batches = [1, 2, 3, 4, 5]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)

        assert sorted(results) == [1, 3, 5]

    def test_process_with_empty_list_results(self):
        """Test that empty list results are filtered out."""

        def worker_fn(batch):
            return [] if batch % 2 == 0 else [batch]

        batches = [1, 2, 3, 4]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)

        assert sorted(results) == [1, 3]

    def test_process_handles_worker_exceptions(self, caplog, capfd):
        """Test that worker exceptions are caught and logged."""

        def worker_fn(batch):
            if batch == 2:
                raise ValueError("Test error")
            return batch

        batches = [1, 2, 3]

        # Attach caplog handler directly — docpipe logger has propagate=False when configured
        target_logger = logging.getLogger("docpipe")
        target_logger.addHandler(caplog.handler)
        try:
            results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)
        finally:
            target_logger.removeHandler(caplog.handler)

        # Should continue processing other batches
        assert sorted(results) == [1, 3]

        # Check that error was logged
        captured = capfd.readouterr()
        has_log_record = any(
            "failed with" in r.message.lower() or "test error" in r.message.lower() for r in caplog.records
        )
        has_stdout = "failed with" in captured.out.lower() or "test error" in captured.out.lower()
        assert has_log_record or has_stdout

    def test_process_with_complex_data(self):
        """Test processing with complex data structures."""

        def worker_fn(batch):
            return {"id": batch["id"], "value": batch["value"] * 2}

        batches = [
            {"id": 1, "value": 10},
            {"id": 2, "value": 20},
        ]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn)

        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)


class TestRunWithSessionInfo:
    """Test run_with_session_info function."""

    def test_run_without_session_info(self):
        """Test running function without session info."""

        def test_func(x, y):
            return x + y

        result = run_with_session_info(None, test_func, 5, 3)

        assert result == 8

    @patch("docpipe.core.models.session_info.set_session_info")
    def test_run_with_session_info(self, mock_set_session):
        """Test running function with session info."""
        mock_session = Mock()

        def test_func(x):
            return x * 2

        result = run_with_session_info(mock_session, test_func, 5)

        mock_set_session.assert_called_once_with(mock_session)
        assert result == 10

    @patch("docpipe.core.models.session_info.set_session_info")
    def test_run_with_kwargs(self, mock_set_session):
        """Test running function with keyword arguments."""
        mock_session = Mock()

        def test_func(*, x, y):
            return x - y

        result = run_with_session_info(mock_session, test_func, x=10, y=3)

        assert result == 7

    @patch("docpipe.core.models.session_info.set_session_info")
    def test_run_with_mixed_args(self, mock_set_session):
        """Test running function with mixed positional and keyword arguments."""
        mock_session = Mock()

        def test_func(a, b, *, c):
            return a + b + c

        result = run_with_session_info(mock_session, test_func, 1, 2, c=3)

        assert result == 6

    def test_run_propagates_exceptions(self):
        """Test that exceptions from the function are propagated."""

        def test_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError) as exc_info:
            run_with_session_info(None, test_func)

        assert "Test error" in str(exc_info.value)


class TestSubmitTaskWithContextPropagation:
    """Test submit_task_with_context_propagation function."""

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_submit_task_basic(self, mock_get_session):
        """Test basic task submission."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def test_func(x):
            return x * 2

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_task_with_context_propagation(executor, test_func, 5)
            result = future.result()

        assert result == 10

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_submit_task_with_kwargs(self, mock_get_session):
        """Test task submission with keyword arguments."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def test_func(*, x, y):
            return x + y

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_task_with_context_propagation(executor, test_func, x=3, y=7)
            result = future.result()

        assert result == 10

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_submit_multiple_tasks(self, mock_get_session):
        """Test submitting multiple tasks."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def test_func(x):
            return x**2

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [submit_task_with_context_propagation(executor, test_func, i) for i in range(5)]
            results = [f.result() for f in futures]

        assert results == [0, 1, 4, 9, 16]

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_submit_task_propagates_session(self, mock_get_session):
        """Test that session info is propagated to worker."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def test_func():
            return "executed"

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_task_with_context_propagation(executor, test_func)
            result = future.result()

        assert result == "executed"
        mock_get_session.assert_called_once()

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_submit_task_handles_exceptions(self, mock_get_session):
        """Test that exceptions in tasks are properly raised."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def test_func():
            raise RuntimeError("Task failed")

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_task_with_context_propagation(executor, test_func)

            with pytest.raises(RuntimeError) as exc_info:
                future.result()

            assert "Task failed" in str(exc_info.value)


class TestConcurrencyIntegration:
    """Integration tests for concurrency utilities."""

    @patch("docpipe.core.models.session_info.get_session_info")
    def test_process_batches_uses_context_propagation(self, mock_get_session):
        """Test that process_batches_in_parallel uses context propagation."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        def worker_fn(batch):
            return batch * 2

        batches = [1, 2, 3]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn, max_workers=2)

        assert sorted(results) == [2, 4, 6]
        # get_session_info should be called for each batch
        assert mock_get_session.call_count == len(batches)

    def test_concurrent_execution_is_parallel(self):
        """Test that batches are actually processed in parallel."""
        import time

        execution_times = []

        def worker_fn(batch):
            start = time.time()
            time.sleep(0.1)  # Simulate work
            execution_times.append(time.time() - start)
            return batch

        batches = [1, 2, 3, 4]
        start_time = time.time()
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn, max_workers=4)
        total_time = time.time() - start_time

        # With 4 workers and 4 batches, should complete in ~0.1s (parallel)
        # not ~0.4s (sequential)
        assert total_time < 0.3  # Allow some overhead
        assert len(results) == 4

    def test_result_extractor_with_none_values(self):
        """Test result extractor handling None values."""

        def worker_fn(batch):
            return {"data": None} if batch % 2 == 0 else {"data": [batch]}

        def result_extractor(result):
            return result.get("data")

        batches = [1, 2, 3, 4]
        results = process_batches_in_parallel(batches=batches, worker_fn=worker_fn, result_extractor=result_extractor)

        assert sorted(results) == [1, 3]


class TestModuleExports:
    """Test module exports."""

    def test_all_exports(self):
        """Test that __all__ contains expected exports."""
        from docpipe.utils.infrastructure import concurrency

        assert hasattr(concurrency, "__all__")
        assert "process_batches_in_parallel" in concurrency.__all__
        assert "run_with_session_info" in concurrency.__all__
        assert "submit_task_with_context_propagation" in concurrency.__all__
