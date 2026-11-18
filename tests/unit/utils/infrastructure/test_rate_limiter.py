# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for rate limiter utilities."""

import os
import time
from unittest.mock import Mock, patch

import pytest

from docpipe.utils.infrastructure.rate_limiter import (
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    ensure_global_concurrency_limit,
    get_prefect_mode,
    is_prefect_server_mode,
    rate_limit_context,
    rate_limited,
)


class TestTokenBucketRateLimiter:
    """Test TokenBucketRateLimiter class."""

    def test_init(self):
        """Test initialization."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=20)

        assert limiter.rate == 10.0
        assert limiter.capacity == 20
        assert limiter.tokens == 20.0

    def test_init_default_capacity(self):
        """Test initialization with default capacity."""
        limiter = TokenBucketRateLimiter(rate=7.5)

        assert limiter.rate == 7.5
        assert limiter.capacity == 7

    def test_acquire_single_token(self):
        """Test acquiring a single token."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)

        result = limiter.acquire(tokens=1)

        assert result is True
        assert limiter.tokens < 10.0

    def test_acquire_multiple_tokens(self):
        """Test acquiring multiple tokens."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)

        result = limiter.acquire(tokens=5)

        assert result is True
        assert limiter.tokens == 5.0

    def test_acquire_with_timeout_success(self):
        """Test acquiring with timeout that succeeds."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)

        result = limiter.acquire(tokens=5, timeout=1.0)

        assert result is True

    def test_acquire_with_timeout_failure(self):
        """Test acquiring with timeout that fails."""
        limiter = TokenBucketRateLimiter(rate=1.0, capacity=1)

        # Exhaust tokens
        limiter.acquire(tokens=1)

        # Try to acquire more than available with short timeout
        result = limiter.acquire(tokens=5, timeout=0.1)

        assert result is False

    def test_acquire_refills_tokens(self):
        """Test that tokens refill over time."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)

        # Exhaust tokens
        limiter.acquire(tokens=10)
        assert limiter.tokens == 0.0

        # Wait for refill
        time.sleep(0.2)

        # Should be able to acquire again
        result = limiter.acquire(tokens=1)
        assert result is True

    def test_limit_context_manager(self):
        """Test limit context manager."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)

        with limiter.limit(tokens=3):
            pass

        assert limiter.tokens == 7.0

    def test_thread_safety(self):
        """Test thread safety of token bucket."""
        import threading

        limiter = TokenBucketRateLimiter(rate=100.0, capacity=100)
        results = []

        def acquire_token():
            result = limiter.acquire(tokens=1)
            results.append(result)

        threads = [threading.Thread(target=acquire_token) for _ in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All acquisitions should succeed (verifies thread safety)
        assert all(results)
        assert len(results) == 50
        # Tokens should be less than initial capacity (some were consumed)
        assert limiter.tokens < 100.0


class TestSlidingWindowRateLimiter:
    """Test SlidingWindowRateLimiter class."""

    def test_init(self):
        """Test initialization."""
        limiter = SlidingWindowRateLimiter(rate=10.0, window_seconds=2.0)

        assert limiter.rate == 10.0
        assert limiter.window_seconds == 2.0
        assert len(limiter.requests) == 0

    def test_init_default_window(self):
        """Test initialization with default window."""
        limiter = SlidingWindowRateLimiter(rate=7.0)

        assert limiter.rate == 7.0
        assert limiter.window_seconds == 1.0

    def test_acquire_within_limit(self):
        """Test acquiring within rate limit."""
        limiter = SlidingWindowRateLimiter(rate=5.0, window_seconds=1.0)

        # Should be able to acquire 5 times
        for _ in range(5):
            result = limiter.acquire()
            assert result is True

        assert len(limiter.requests) == 5

    def test_acquire_exceeds_limit(self):
        """Test acquiring beyond rate limit."""
        limiter = SlidingWindowRateLimiter(rate=2.0, window_seconds=1.0)

        # Acquire up to limit
        limiter.acquire()
        limiter.acquire()

        # Next acquisition should block or timeout
        result = limiter.acquire(timeout=0.1)
        assert result is False

    def test_acquire_with_timeout_success(self):
        """Test acquiring with timeout that succeeds."""
        limiter = SlidingWindowRateLimiter(rate=5.0, window_seconds=1.0)

        result = limiter.acquire(timeout=1.0)

        assert result is True

    def test_sliding_window_cleanup(self):
        """Test that old requests are removed from window."""
        limiter = SlidingWindowRateLimiter(rate=2.0, window_seconds=0.2)

        # Make 2 requests
        limiter.acquire()
        limiter.acquire()

        # Wait for window to slide
        time.sleep(0.3)

        # Should be able to acquire again
        result = limiter.acquire()
        assert result is True

    def test_limit_context_manager(self):
        """Test limit context manager."""
        limiter = SlidingWindowRateLimiter(rate=5.0, window_seconds=1.0)

        with limiter.limit():
            pass

        assert len(limiter.requests) == 1

    def test_thread_safety(self):
        """Test thread safety of sliding window."""
        import threading

        limiter = SlidingWindowRateLimiter(rate=50.0, window_seconds=1.0)
        results = []

        def acquire_permission():
            result = limiter.acquire()
            results.append(result)

        threads = [threading.Thread(target=acquire_permission) for _ in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All acquisitions should succeed
        assert all(results)


class TestPrefectModeDetection:
    """Test Prefect mode detection functions."""

    def test_get_prefect_mode_default(self):
        """Test getting Prefect mode with default."""
        with patch.dict(os.environ, {}, clear=True):
            mode = get_prefect_mode()
            assert mode == "ephemeral"

    def test_get_prefect_mode_server(self):
        """Test getting Prefect mode when set to server."""
        with patch.dict(os.environ, {"PREFECT_MODE": "server"}):
            mode = get_prefect_mode()
            assert mode == "server"

    def test_get_prefect_mode_case_insensitive(self):
        """Test that mode detection is case insensitive."""
        with patch.dict(os.environ, {"PREFECT_MODE": "SERVER"}):
            mode = get_prefect_mode()
            assert mode == "server"

    def test_is_prefect_server_mode_true(self):
        """Test server mode detection when true."""
        with patch.dict(os.environ, {"PREFECT_MODE": "server"}):
            assert is_prefect_server_mode() is True

    def test_is_prefect_server_mode_false(self):
        """Test server mode detection when false."""
        with patch.dict(os.environ, {"PREFECT_MODE": "ephemeral"}):
            assert is_prefect_server_mode() is False

    def test_is_prefect_server_mode_default(self):
        """Test server mode detection with default."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_prefect_server_mode() is False


class TestEnsureGlobalConcurrencyLimit:
    """Test ensure_global_concurrency_limit function."""

    @pytest.mark.requires_prefect
    def test_ensure_limit_creates_new(self):
        """Test creating a new concurrency limit."""
        with patch("prefect.client.orchestration.get_client") as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value.__enter__.return_value = mock_client

            # Simulate limit doesn't exist
            mock_client.read_global_concurrency_limit_by_name.side_effect = Exception("Not found")

            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is True
            mock_client.create_global_concurrency_limit.assert_called_once()

    @pytest.mark.requires_prefect
    def test_ensure_limit_updates_existing(self):
        """Test updating an existing concurrency limit."""
        with patch("prefect.client.orchestration.get_client") as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value.__enter__.return_value = mock_client

            # Simulate existing limit with different settings
            existing_limit = Mock()
            existing_limit.limit = 5
            existing_limit.slot_decay_per_second = 2.0
            mock_client.read_global_concurrency_limit_by_name.return_value = existing_limit

            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is True
            mock_client.update_global_concurrency_limit.assert_called_once()

    @pytest.mark.requires_prefect
    def test_ensure_limit_no_update_needed(self):
        """Test when existing limit matches desired settings."""
        with patch("prefect.client.orchestration.get_client") as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value.__enter__.return_value = mock_client

            # Simulate existing limit with same settings
            existing_limit = Mock()
            existing_limit.limit = 10
            existing_limit.slot_decay_per_second = 5.0
            mock_client.read_global_concurrency_limit_by_name.return_value = existing_limit

            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is True
            mock_client.update_global_concurrency_limit.assert_not_called()

    @pytest.mark.requires_prefect
    def test_ensure_limit_tolerates_concurrent_update_failure(self):
        """A failed update (another worker updated simultaneously) still reports success and does not create."""
        with patch("prefect.client.orchestration.get_client") as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value.__enter__.return_value = mock_client
            existing_limit = Mock(limit=5, slot_decay_per_second=2.0)
            mock_client.read_global_concurrency_limit_by_name.return_value = existing_limit
            mock_client.update_global_concurrency_limit.side_effect = RuntimeError("conflict")

            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is True
            mock_client.update_global_concurrency_limit.assert_called_once()
            mock_client.create_global_concurrency_limit.assert_not_called()

    @pytest.mark.requires_prefect
    def test_ensure_limit_tolerates_create_race(self):
        """ObjectAlreadyExists on create (another worker won the race) still reports success."""
        from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound

        with patch("prefect.client.orchestration.get_client") as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value.__enter__.return_value = mock_client
            mock_client.read_global_concurrency_limit_by_name.side_effect = ObjectNotFound(http_exc=Exception("404"))
            mock_client.create_global_concurrency_limit.side_effect = ObjectAlreadyExists(http_exc=Exception("409"))

            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is True
            mock_client.create_global_concurrency_limit.assert_called_once()

    def test_ensure_limit_handles_import_error(self):
        """Test handling when Prefect is not available."""
        with patch("prefect.client.orchestration.get_client", side_effect=ImportError("No prefect")):
            result = ensure_global_concurrency_limit(limit_name="test-limit", limit=10, slot_decay_per_second=5.0)

            assert result is False


class TestRateLimitContext:
    """Test rate_limit_context context manager."""

    def test_rate_limit_context_local_mode(self):
        """Test rate limit context in local mode."""
        with patch.dict(os.environ, {"PREFECT_MODE": "ephemeral"}):
            with rate_limit_context(limit_name="test", rate=10.0):
                pass  # Should not raise

    def test_rate_limit_context_explicit_local(self):
        """Test rate limit context with explicit local mode."""
        with rate_limit_context(limit_name="test", rate=10.0, use_prefect=False):
            pass  # Should not raise

    @pytest.mark.requires_prefect
    def test_rate_limit_context_prefect_mode(self):
        """Test rate limit context in Prefect mode."""
        with patch.dict(os.environ, {"PREFECT_MODE": "server"}):
            with patch("prefect.concurrency.sync.rate_limit") as mock_rate_limit:
                with patch("docpipe.utils.infrastructure.rate_limiter.ensure_global_concurrency_limit") as mock_ensure:
                    mock_ensure.return_value = True

                    with rate_limit_context(limit_name="test", rate=7.0):
                        pass

                    mock_ensure.assert_called_once()
                    mock_rate_limit.assert_called_once_with("test", occupy=1)

    def test_rate_limit_context_prefect_fallback(self):
        """Test fallback to local when Prefect is unavailable."""
        with patch.dict(os.environ, {"PREFECT_MODE": "server"}):
            with patch("prefect.concurrency.sync.rate_limit", side_effect=ImportError("No prefect")):
                with rate_limit_context(limit_name="test", rate=10.0):
                    pass  # Should fallback to local limiter


class TestRateLimitedDecorator:
    """Test rate_limited decorator."""

    def test_rate_limited_decorator_basic(self):
        """Test basic rate limited decorator."""
        call_count = 0

        @rate_limited(limit_name="test", rate=10.0, use_prefect=False)
        def test_function():
            nonlocal call_count
            call_count += 1
            return "result"

        result = test_function()

        assert result == "result"
        assert call_count == 1

    def test_rate_limited_decorator_with_args(self):
        """Test rate limited decorator with function arguments."""

        @rate_limited(limit_name="test", rate=10.0, use_prefect=False)
        def test_function(x: int, y: int) -> int:
            return x + y

        result = test_function(5, 3)

        assert result == 8

    def test_rate_limited_decorator_with_kwargs(self):
        """Test rate limited decorator with keyword arguments."""

        @rate_limited(limit_name="test", rate=10.0, use_prefect=False)
        def test_function(*, name: str, value: int) -> str:
            return f"{name}={value}"

        result = test_function(name="test", value=42)

        assert result == "test=42"

    def test_rate_limited_decorator_preserves_function_name(self):
        """Test that decorator preserves function metadata."""

        @rate_limited(limit_name="test", rate=10.0, use_prefect=False)
        def my_function():
            """My docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_rate_limited_decorator_multiple_calls(self):
        """Test rate limited decorator with multiple calls."""
        call_times = []

        @rate_limited(limit_name="test", rate=5.0, use_prefect=False)
        def test_function():
            call_times.append(time.time())
            return "result"

        # Make multiple calls
        for _ in range(3):
            test_function()

        assert len(call_times) == 3


class TestRateLimiterIntegration:
    """Integration tests for rate limiter components."""

    def test_token_bucket_enforces_rate(self):
        """Test that token bucket actually enforces rate limit."""
        limiter = TokenBucketRateLimiter(rate=5.0, capacity=5)

        start_time = time.time()

        # Acquire 10 tokens (should take ~1 second at 5 tokens/sec)
        for _ in range(10):
            limiter.acquire(tokens=1)

        elapsed = time.time() - start_time

        # Should take at least 1 second (with some tolerance)
        assert elapsed >= 0.9

    def test_sliding_window_enforces_rate(self):
        """Test that sliding window actually enforces rate limit."""
        limiter = SlidingWindowRateLimiter(rate=3.0, window_seconds=1.0)

        # Acquire 3 times quickly
        for _ in range(3):
            limiter.acquire()

        # Fourth acquisition should fail with short timeout
        result = limiter.acquire(timeout=0.1)
        assert result is False

        # After window slides, should succeed
        time.sleep(1.1)
        result = limiter.acquire()
        assert result is True
