# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the LRUCache singleton guard clauses and re-initialization path."""

import re
from unittest.mock import patch

import pytest

from docpipe.utils.infrastructure.caching import CACHE_NOT_INITIALIZED_ERROR, LRUCache


@pytest.fixture(autouse=True)
def _isolated_singleton():
    """Give every test a fresh LRUCache singleton and restore the registry afterwards."""
    with patch.dict("docpipe.utils.core.patterns.Singleton._instances", clear=True):
        yield


@pytest.mark.parametrize("maxsize", [0, -1, 1.5, "10"])
def test_invalid_maxsize_is_rejected(maxsize):
    """A non-positive or non-integer maxsize raises ValueError."""
    with pytest.raises(ValueError, match="maxsize must be a positive integer"):
        LRUCache(maxsize=maxsize, ttl=10)


def test_reinitializing_an_initialized_cache_keeps_its_state():
    """Calling __init__ again reuses the lock, warns, and leaves size and entries untouched."""
    cache = LRUCache(maxsize=3, ttl=10)
    cache.put(cache_key="k", value="v")
    lock = cache._cache_lock

    with patch("docpipe.utils.infrastructure.caching.logger") as mock_logger:
        LRUCache.__init__(cache, maxsize=99, ttl=1)

    assert cache._cache_lock is lock
    assert cache._cache.maxsize == 3
    assert cache.get(cache_key="k") == "v"
    mock_logger.warning.assert_called_once_with("Cache %s already initialized", "LRUCache")


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.get(cache_key="k"),
        lambda c: c.put(cache_key="k", value="v"),
        lambda c: c.remove_keys(keys=["k"]),
        lambda c: c.clear(),
    ],
    ids=["get", "put", "remove_keys", "clear"],
)
def test_methods_refuse_to_run_before_initialization(call):
    """Every accessor raises RuntimeError when the instance was never initialized."""
    uninitialized = LRUCache.__new__(LRUCache)

    with pytest.raises(RuntimeError, match=re.escape(CACHE_NOT_INITIALIZED_ERROR)):
        call(uninitialized)


def test_clear_removes_all_entries():
    """clear() empties the cache."""
    cache = LRUCache(maxsize=5, ttl=10)
    cache.put(cache_key="a", value=1)
    cache.put(cache_key="b", value=2)

    cache.clear()

    assert cache.get(cache_key="a") is None
    assert len(cache._cache) == 0
