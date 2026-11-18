# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for reclaim_memory and the PyArrow size fallback in the performance utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.utils.infrastructure import performance
from docpipe.utils.infrastructure.performance import get_pyarrow_table_size_mb, reclaim_memory

MIB = 1024 * 1024
PERF_EXTRA = {DocpipeConstants.TRACK_PERF: "true"}


class _TableWithoutNbytes:
    """Table stand-in whose ``nbytes`` fails, so the per-column fallback is used."""

    columns = (SimpleNamespace(nbytes=MIB), SimpleNamespace(nbytes=MIB // 2))

    @property
    def nbytes(self):
        """Raise like a table type that cannot report its total size."""
        raise AttributeError("nbytes unavailable")


def test_table_size_falls_back_to_column_sum():
    """When table.nbytes fails, the size is the sum of the column buffers."""
    assert get_pyarrow_table_size_mb(_TableWithoutNbytes()) == pytest.approx(1.5)


@pytest.fixture
def env():
    """Patch the OS-facing collaborators of reclaim_memory and expose them as mocks."""
    pool = MagicMock()
    libc = MagicMock()
    fake_ctypes = MagicMock()
    fake_ctypes.CDLL.return_value = libc
    with (
        patch.object(performance, "gc") as fake_gc,
        patch.object(performance.pa, "default_memory_pool", return_value=pool),
        patch.object(performance, "ctypes", fake_ctypes),
        patch.object(performance, "sys", SimpleNamespace(platform="linux")),
        patch.object(performance, "get_process_memory_mb", side_effect=[{"rss_mb": 300.0}, {"rss_mb": 200.0}]),
        patch.object(performance, "logger") as fake_logger,
    ):
        yield SimpleNamespace(gc=fake_gc, pool=pool, ctypes=fake_ctypes, libc=libc, logger=fake_logger)


class TestReclaimMemory:
    """reclaim_memory releases PyArrow and glibc memory and reports what came back."""

    def test_linux_success_logs_recovered_memory(self, env):
        """On Linux both release steps run and the RSS delta is logged."""
        reclaim_memory(context="after-flow")

        env.gc.collect.assert_called_once_with()
        env.pool.release_unused.assert_called_once_with()
        env.ctypes.CDLL.assert_called_once_with("libc.so.6")
        env.libc.malloc_trim.assert_called_once_with(env.ctypes.c_size_t.return_value)
        env.ctypes.c_size_t.assert_called_once_with(0)
        env.logger.info.assert_called_once_with(
            "Memory reclaim [%s]: RSS %.1f -> %.1f MiB (recovered %.1f MiB), release_unused=%s malloc_trim=%s",
            "after-flow",
            300.0,
            200.0,
            100.0,
            True,
            True,
            extra=PERF_EXTRA,
        )
        env.logger.warning.assert_not_called()

    def test_release_unused_failure_is_logged_not_raised(self, env):
        """A PyArrow pool failure is a warning and is reported as release_unused=False."""
        env.pool.release_unused.side_effect = RuntimeError("pool broken")

        reclaim_memory(context="ctx")

        env.logger.warning.assert_called_once_with("PyArrow release_unused failed (%s)", "ctx", exc_info=True)
        assert env.logger.info.call_args.args[5:] == (False, True)

    def test_malloc_trim_failure_on_linux_is_logged_not_raised(self, env):
        """A missing or failing libc on Linux is a warning and is reported as malloc_trim=False."""
        env.ctypes.CDLL.side_effect = OSError("libc.so.6: cannot open shared object file")

        reclaim_memory(context="ctx")

        env.logger.warning.assert_called_once_with("malloc_trim failed (%s)", "ctx", exc_info=True)
        assert env.logger.info.call_args.args[5:] == (True, False)

    def test_malloc_trim_is_skipped_off_linux(self, env):
        """On other platforms malloc_trim is not attempted and only a debug line is written."""
        with patch.object(performance, "sys", SimpleNamespace(platform="darwin")):
            reclaim_memory(context="ctx")

        env.ctypes.CDLL.assert_not_called()
        env.logger.debug.assert_called_once_with("malloc_trim skipped on %s (%s)", "darwin", "ctx")
        env.logger.warning.assert_not_called()
        assert env.logger.info.call_args.args[5:] == (True, False)

    def test_unavailable_rss_uses_the_short_message(self, env):
        """If process memory cannot be read, the summary omits the RSS figures."""
        with patch.object(performance, "get_process_memory_mb", side_effect=RuntimeError("no psutil")):
            reclaim_memory(context="ctx")

        env.logger.info.assert_called_once_with(
            "Memory reclaim [%s]: release_unused=%s malloc_trim=%s (RSS unavailable)",
            "ctx",
            True,
            True,
            extra=PERF_EXTRA,
        )
