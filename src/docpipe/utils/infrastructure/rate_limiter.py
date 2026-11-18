"""Rate limiting utilities for API calls with Prefect and local fallback support."""

import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, TypeVar

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter for local mode.

    Implements a token bucket algorithm to limit requests per second.
    Tokens are added at a constant rate, and each request consumes one token.
    """

    def __init__(self, *, rate: float, capacity: int | None = None) -> None:
        """Initialize token bucket rate limiter.

        Args:
            rate: Maximum requests per second (e.g., 7.0 for 7 req/s)
            capacity: Maximum tokens in bucket (defaults to rate)
        """
        self.rate = rate
        self.capacity = capacity or int(rate)
        self.tokens = float(self.capacity)
        self.last_update = time.time()
        self.lock = threading.Lock()

        logger.info(
            "Initialized TokenBucketRateLimiter: rate=%s req/s, capacity=%s",
            rate,
            self.capacity,
        )

    def acquire(self, *, tokens: int = 1, timeout: float | None = None) -> bool:
        """Acquire tokens from the bucket, blocking if necessary.

        Args:
            tokens: Number of tokens to acquire (default: 1)
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            True if tokens acquired, False if timeout exceeded
        """
        start_time = time.time()

        while True:
            with self.lock:
                now = time.time()
                elapsed = now - self.last_update

                # Add tokens based on elapsed time
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

            # Check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                return False

            # Sleep briefly before retrying
            time.sleep(0.01)

    @contextmanager
    def limit(self, *, tokens: int = 1):
        """Context manager for rate limiting.

        Args:
            tokens: Number of tokens to acquire

        Yields:
            None
        """
        self.acquire(tokens=tokens)
        yield


class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter for local mode.

    Tracks request timestamps in a sliding window to enforce rate limits.
    More accurate than token bucket for bursty traffic.
    """

    def __init__(self, *, rate: float, window_seconds: float = 1.0) -> None:
        """Initialize sliding window rate limiter.

        Args:
            rate: Maximum requests per window (e.g., 7.0 for 7 req/s)
            window_seconds: Window size in seconds (default: 1.0)
        """
        self.rate = rate
        self.window_seconds = window_seconds
        self.requests: deque[float] = deque()
        self.lock = threading.Lock()

        logger.info(
            "Initialized SlidingWindowRateLimiter: rate=%s req/%ss",
            rate,
            window_seconds,
        )

    def acquire(self, *, timeout: float | None = None) -> bool:
        """Acquire permission to make a request, blocking if necessary.

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            True if permission granted, False if timeout exceeded
        """
        start_time = time.time()

        while True:
            with self.lock:
                now = time.time()
                cutoff = now - self.window_seconds

                # Remove old requests outside the window
                while self.requests and self.requests[0] < cutoff:
                    self.requests.popleft()

                # Check if we can make a request
                if len(self.requests) < self.rate:
                    self.requests.append(now)
                    return True

            # Check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                return False

            # Sleep briefly before retrying
            time.sleep(0.01)

    @contextmanager
    def limit(self):
        """Context manager for rate limiting.

        Yields:
            None
        """
        self.acquire()
        yield


def get_prefect_mode() -> str:
    """Get the current Prefect mode from environment.

    Returns:
        'server' if PREFECT_MODE=server, 'ephemeral' otherwise
    """
    return os.environ.get("PREFECT_MODE", "ephemeral").lower()


def is_prefect_server_mode() -> bool:
    """Check if running in Prefect server mode.

    Returns:
        True if PREFECT_MODE=server, False otherwise
    """
    return get_prefect_mode() == "server"


def ensure_global_concurrency_limit(*, limit_name: str, limit: int, slot_decay_per_second: float | None = None) -> bool:
    """Ensure a global concurrency limit exists in Prefect server.

    Manually implements idempotent upsert logic to support slot_decay_per_second.
    Designed to be safe for 100-200 parallel workers hitting it simultaneously.

    Args:
        limit_name: Name of the global concurrency limit
        limit: Maximum number of concurrent slots
        slot_decay_per_second: Rate at which slots are released per second.

    Returns:
        True if limit exists with correct settings, False otherwise
    """
    try:
        from prefect.client.orchestration import get_client
        from prefect.client.schemas.actions import GlobalConcurrencyLimitCreate, GlobalConcurrencyLimitUpdate
        from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound

        with get_client(sync_client=True) as client:
            try:
                # 1. Try to read the existing limit
                existing = client.read_global_concurrency_limit_by_name(name=limit_name)

                # 2. If it exists, check if update is needed (only update if settings changed)
                if existing.limit != limit or existing.slot_decay_per_second != slot_decay_per_second:
                    try:
                        client.update_global_concurrency_limit(
                            name=limit_name,
                            concurrency_limit=GlobalConcurrencyLimitUpdate(
                                limit=limit, slot_decay_per_second=slot_decay_per_second
                            ),
                        )
                        logger.debug("Updated global concurrency limit '%s'", limit_name)
                    except Exception as update_err:
                        # Another worker might have updated it simultaneously; that's fine
                        logger.debug("Simultaneous update for '%s': %s", limit_name, update_err)
                return True

            except (ObjectNotFound, Exception):
                # 3. If it doesn't exist, try to create it
                try:
                    client.create_global_concurrency_limit(
                        concurrency_limit=GlobalConcurrencyLimitCreate(
                            name=limit_name, limit=limit, slot_decay_per_second=slot_decay_per_second
                        )
                    )
                    logger.debug("Created global concurrency limit '%s'", limit_name)
                except ObjectAlreadyExists:
                    # Race condition: Another worker created it between our read and create
                    logger.debug("Limit '%s' was created by another worker", limit_name)
                return True

    except Exception as e:
        logger.warning("Failed to ensure global concurrency limit '%s': %s", limit_name, e)
        return False


@contextmanager
def rate_limit_context(*, limit_name: str, rate: float, use_prefect: bool | None = None):
    """Context manager for rate limiting with automatic Prefect/local fallback.

    Uses Prefect's rate_limit function (not concurrency context manager) to enforce
    a true requests-per-second limit across all distributed workers.

    Key distinction:
    - concurrency: Controls how many operations run simultaneously (parallelism).
      Slots are released when the operation completes. With fast API calls (~200ms),
      8 slots would allow ~40 req/s — NOT 8 req/s.
    - rate_limit: Controls how frequently operations can start (frequency).
      Slots decay at a fixed rate (slot_decay_per_second), ensuring a true N req/s cap.

    Args:
        limit_name: Name for the rate limit (used for Prefect global concurrency limit)
        rate: Maximum requests per second
        use_prefect: Force Prefect mode (None = auto-detect from PREFECT_MODE)

    Yields:
        None

    Example:
        with rate_limit_context(limit_name="watsonx-embeddings", rate=7.0):
            # Make API call
            result = api_call()
    """
    # Determine which mode to use
    if use_prefect is None:
        use_prefect = is_prefect_server_mode()

    if use_prefect:
        try:
            from prefect.concurrency.sync import rate_limit

            # Convert rate to slots (Prefect uses integer slots)
            # For 7 req/s, we use 7 slots with slot_decay_per_second=7.0
            slots = int(rate)

            # Ensure the global concurrency limit exists with slot decay.
            # slot_decay_per_second is REQUIRED for rate_limit to work;
            # without it Prefect will raise an error.
            ensure_global_concurrency_limit(
                limit_name=limit_name,
                limit=slots,
                slot_decay_per_second=rate,
            )

            logger.info("Using Prefect rate limit: %s (%s req/s)", limit_name, rate)

            # Block until a slot is available at the configured rate.
            # rate_limit is a function (not a context manager) — it blocks,
            # then returns. The slot decays automatically on the server.
            rate_limit(limit_name, occupy=1)
            yield

        except (ImportError, AttributeError) as e:
            logger.warning(
                "Prefect rate_limit not available (%s), falling back to local rate limiter",
                e,
            )
            limiter = TokenBucketRateLimiter(rate=rate)
            with limiter.limit():
                yield
    else:
        logger.debug("Using local rate limiter: %s (rate=%s req/s)", limit_name, rate)
        limiter = TokenBucketRateLimiter(rate=rate)
        with limiter.limit():
            yield


def rate_limited(*, limit_name: str, rate: float, use_prefect: bool | None = None) -> Callable:
    """Decorator for rate limiting function calls.

    Args:
        limit_name: Name for the rate limit (used for Prefect concurrency limit)
        rate: Maximum requests per second
        use_prefect: Force Prefect mode (None = auto-detect from PREFECT_MODE)

    Returns:
        Decorated function with rate limiting

    Example:
        @rate_limited(limit_name="watsonx-embeddings", rate=7.0)
        def generate_embeddings(text: str) -> list[float]:
            return api_call(text)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with rate_limit_context(limit_name=limit_name, rate=rate, use_prefect=use_prefect):
                return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
    "get_prefect_mode",
    "is_prefect_server_mode",
    "rate_limit_context",
    "rate_limited",
]
