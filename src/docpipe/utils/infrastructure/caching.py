"""LRU cache utilities for docpipe infrastructure."""

import threading
import time
from collections.abc import Hashable, Iterable
from typing import Any

from cachetools import TTLCache

from docpipe.utils.core.patterns import Singleton
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Error message constant
CACHE_NOT_INITIALIZED_ERROR = "Cache accessed before initialization"


class LRUCache(metaclass=Singleton):
    """Lrucache."""

    _is_initialized: bool = False

    def __init__(self, maxsize: int = 128, ttl: int = 1800):
        if not getattr(self, "_cache_lock", None):
            self._cache_lock = threading.Lock()

        with self._cache_lock:
            if not self._is_initialized:
                if not isinstance(maxsize, int) or maxsize <= 0:
                    raise ValueError("maxsize must be a positive integer")

                if not isinstance(ttl, int) or ttl < 0:
                    raise ValueError("TTL must be a non-negative integer")

                self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl, timer=time.time)

                self._is_initialized = True
                logger.debug(
                    "Initialized %s with size %s and TTL %s",
                    self.__class__.__name__,
                    maxsize,
                    ttl,
                )
            else:
                logger.warning("Cache %s already initialized", self.__class__.__name__)

    def get(self, *, cache_key: Hashable) -> Any | None:
        """Get."""
        if not getattr(self, "_cache_lock", None):
            raise RuntimeError(CACHE_NOT_INITIALIZED_ERROR)

        with self._cache_lock:
            container_object = self._cache.get(cache_key)

            if container_object is None:
                logger.info("Cache miss for key %s", cache_key)
            else:
                logger.info("Cache hit for key %s", cache_key)

            return container_object

    def put(self, *, cache_key: Hashable, value: Any):
        """Put."""
        if not getattr(self, "_cache_lock", None):
            raise RuntimeError(CACHE_NOT_INITIALIZED_ERROR)

        with self._cache_lock:
            self._cache[cache_key] = value

            logger.info("Current cache size: %s/%s", len(self._cache), self._cache.maxsize)

    def remove_keys(self, *, keys: Iterable[Hashable]) -> None:
        """Remove keys."""
        if not getattr(self, "_cache_lock", None):
            raise RuntimeError(CACHE_NOT_INITIALIZED_ERROR)

        with self._cache_lock:
            for key in keys:
                self._cache.pop(key)
            logger.info("Current cache size: %s/%s", len(self._cache), self._cache.maxsize)

    def clear(self):
        """Clear all entries from the cache."""
        if not getattr(self, "_cache_lock", None):
            raise RuntimeError(CACHE_NOT_INITIALIZED_ERROR)

        with self._cache_lock:
            self._cache.clear()
            logger.debug("Cleared cache %s", self.__class__.__name__)
