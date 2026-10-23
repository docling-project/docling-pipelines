"""Unit tests for the process-wide Docling converter pool."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel, SecretStr

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.integrations.docling import converter_pool
from docpipe.integrations.docling.converter_pool import (
    DoclingInstancePool,
    get_docling_pool,
    options_fingerprint,
    reset_docling_pool,
)


class _Instrumented:
    """Stub converter that records construction count and concurrent use."""

    _lock = threading.Lock()
    constructed = 0
    violations = 0

    def __init__(self) -> None:
        with _Instrumented._lock:
            _Instrumented.constructed += 1
        self._users = 0

    def use(self, *, seconds: float) -> None:
        with _Instrumented._lock:
            self._users += 1
            if self._users > 1:
                _Instrumented.violations += 1
        time.sleep(seconds)
        with _Instrumented._lock:
            self._users -= 1


@pytest.fixture(autouse=True)
def _reset_instrumented():
    _Instrumented.constructed = 0
    _Instrumented.violations = 0
    return


# ---------------------------------------------------------------------------
# options_fingerprint
# ---------------------------------------------------------------------------


class _OcrBase(BaseModel):
    lang: list[str] = ["en"]


class _OcrA(_OcrBase):
    pass


class _OcrB(_OcrBase):
    pass


class _Pipeline(BaseModel):
    do_ocr: bool = True
    ocr: _OcrBase = _OcrA()
    api_key: SecretStr | None = None


class TestOptionsFingerprint:
    def test_same_values_same_fingerprint(self):
        assert options_fingerprint({"pdf": _Pipeline()}) == options_fingerprint({"pdf": _Pipeline()})

    def test_scalar_value_change_changes_fingerprint(self):
        assert options_fingerprint(_Pipeline()) != options_fingerprint(_Pipeline(do_ocr=False))

    def test_nested_list_value_change_changes_fingerprint(self):
        assert options_fingerprint(_Pipeline()) != options_fingerprint(_Pipeline(ocr=_OcrA(lang=["de"])))

    def test_nested_subclass_with_identical_fields_differs(self):
        """Subclasses with identical field values must not collide (concrete type is part of the key)."""
        assert options_fingerprint(_Pipeline(ocr=_OcrA())) != options_fingerprint(_Pipeline(ocr=_OcrB()))

    def test_secret_values_are_distinguished_but_not_leaked(self):
        key_a = options_fingerprint(_Pipeline(api_key=SecretStr("secret-a")))
        key_b = options_fingerprint(_Pipeline(api_key=SecretStr("secret-b")))
        assert key_a != key_b
        assert key_a == options_fingerprint(_Pipeline(api_key=SecretStr("secret-a")))
        assert "secret-a" not in key_a

    def test_dict_order_does_not_matter(self):
        assert options_fingerprint({"a": 1, "b": 2}) == options_fingerprint({"b": 2, "a": 1})

    def test_class_references_are_distinguished(self):
        assert options_fingerprint({"cls": _OcrA}) != options_fingerprint({"cls": _OcrB})

    def test_cycles_do_not_recurse_forever(self):
        cyclic: dict = {"x": 1}
        cyclic["self"] = cyclic
        assert len(options_fingerprint(cyclic)) == 64


# ---------------------------------------------------------------------------
# DoclingInstancePool
# ---------------------------------------------------------------------------


class TestDoclingInstancePool:
    def test_invalid_size_rejected(self):
        with pytest.raises(ValueError, match="max_size"):
            DoclingInstancePool(max_size=0, idle_ttl_seconds=0)

    def test_instance_reused_across_sequential_leases(self):
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=0)
        with pool.lease(key="k", factory=_Instrumented) as first:
            pass
        with pool.lease(key="k", factory=_Instrumented) as second:
            pass
        assert first is second
        assert _Instrumented.constructed == 1

    def test_different_keys_get_different_instances(self):
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=0)
        with pool.lease(key="a", factory=_Instrumented) as first:
            pass
        with pool.lease(key="b", factory=_Instrumented) as second:
            pass
        assert first is not second
        assert pool.stats()["keys"] == 2

    def test_exclusive_use_and_cap_under_concurrency(self):
        """Many threads, small cap: never more than cap instances and never shared concurrently."""
        cap = 3
        pool = DoclingInstancePool(max_size=cap, idle_ttl_seconds=0)
        live_peak = 0
        peak_lock = threading.Lock()

        def work(_: int) -> None:
            nonlocal live_peak
            with pool.lease(key="k", factory=_Instrumented) as inst:
                with peak_lock:
                    live_peak = max(live_peak, pool.stats()["live"])
                inst.use(seconds=0.005)

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(work, range(200)))

        assert _Instrumented.violations == 0
        assert _Instrumented.constructed <= cap
        assert live_peak <= cap
        assert pool.stats()["live"] <= cap

    def test_cap_respected_across_keys_with_eviction(self):
        """With a full pool, an idle instance of another key is evicted instead of growing."""
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=0)
        for key in ("a", "b", "c", "a"):
            with pool.lease(key=key, factory=_Instrumented):
                assert pool.stats()["live"] <= 2
        stats = pool.stats()
        assert stats["live"] <= 2
        # "a" was evicted (LRU) when "c" needed a slot, so it had to be rebuilt.
        assert _Instrumented.constructed == 4

    def test_waits_instead_of_constructing_beyond_cap(self):
        """When every instance is checked out, a new caller blocks until one is returned."""
        pool = DoclingInstancePool(max_size=1, idle_ttl_seconds=0)
        acquired = threading.Event()
        release = threading.Event()
        second_done = threading.Event()

        def holder() -> None:
            with pool.lease(key="k", factory=_Instrumented):
                acquired.set()
                release.wait(timeout=5)

        def waiter() -> None:
            with pool.lease(key="other", factory=_Instrumented):
                second_done.set()

        t1 = threading.Thread(target=holder)
        t1.start()
        assert acquired.wait(timeout=5)
        t2 = threading.Thread(target=waiter)
        t2.start()
        time.sleep(0.1)
        assert not second_done.is_set()
        assert _Instrumented.constructed == 1
        release.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert second_done.is_set()
        assert pool.stats()["live"] == 1

    def test_fair_share_eviction_then_wait(self, monkeypatch):
        """A newcomer key takes idle instances only until it holds a fair share, then waits."""
        monkeypatch.setattr(converter_pool, "_COLD_IDLE_SECONDS", 3600.0)
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=0)
        with (
            pool.lease(key="A", factory=_Instrumented),
            pool.lease(key="A", factory=_Instrumented),
            pool.lease(key="A", factory=_Instrumented),
            pool.lease(key="A", factory=_Instrumented),
        ):
            pass
        assert _Instrumented.constructed == 4

        b1 = pool._acquire(key="B", factory=_Instrumented)  # B has none -> evicts an idle A
        b2 = pool._acquire(key="B", factory=_Instrumented)  # A=3 >= B=1 + 2 -> evicts again
        assert _Instrumented.constructed == 6
        assert pool._live_per_key == {"A": 2, "B": 2}

        got_third = threading.Event()

        def third() -> None:
            with pool.lease(key="B", factory=_Instrumented):
                got_third.set()

        waiter = threading.Thread(target=third)
        waiter.start()
        time.sleep(0.1)
        assert not got_third.is_set()  # A=2 < B=2 + 2 and A is not cold -> B waits for its own
        pool._release(key="B", instance=b1)
        waiter.join(timeout=5)
        assert got_third.is_set()
        assert _Instrumented.constructed == 6  # the waiter reused b1, nothing rebuilt
        pool._release(key="B", instance=b2)

    def test_cold_idle_instances_of_other_keys_are_evictable(self, monkeypatch):
        monkeypatch.setattr(converter_pool, "_COLD_IDLE_SECONDS", 0.0)
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=0)
        with pool.lease(key="A", factory=_Instrumented), pool.lease(key="A", factory=_Instrumented):
            pass
        held = pool._acquire(key="B", factory=_Instrumented)
        with pool.lease(key="B", factory=_Instrumented):  # A=1 < B=1 + 2 but A is cold
            pass
        assert pool._live_per_key == {"B": 2}
        pool._release(key="B", instance=held)

    @pytest.mark.parametrize("idle_ttl_seconds", [0, 3600])
    def test_waiter_proceeds_when_other_key_turns_cold_while_waiting(self, monkeypatch, idle_ttl_seconds):
        """A caller already blocked on a full pool retries eviction once another key's idle instances turn cold.

        Full pool: two idle A instances (not cold yet) and two checked-out B instances. A third B
        request must wait at first (fair share), then proceed as soon as the A instances become
        cold, without any B lease being released and without waiting for the idle TTL.
        """
        cold_seconds = 0.4
        monkeypatch.setattr(converter_pool, "_COLD_IDLE_SECONDS", cold_seconds)
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=idle_ttl_seconds)
        a1 = pool._acquire(key="A", factory=_Instrumented)
        a2 = pool._acquire(key="A", factory=_Instrumented)
        b1 = pool._acquire(key="B", factory=_Instrumented)
        b2 = pool._acquire(key="B", factory=_Instrumented)
        pool._release(key="A", instance=a1)
        pool._release(key="A", instance=a2)
        idle_since = time.monotonic()
        assert pool.stats() == {"max_size": 4, "live": 4, "idle": 2, "constructed": 4, "keys": 2}

        got_third = threading.Event()
        acquired_at: list[float] = []

        def third() -> None:
            with pool.lease(key="B", factory=_Instrumented):
                acquired_at.append(time.monotonic())
                got_third.set()

        waiter = threading.Thread(target=third, daemon=True)
        try:
            waiter.start()
            deadline = time.monotonic() + 5
            while not pool._waiting_logged and time.monotonic() < deadline:
                time.sleep(0.005)
            assert pool._waiting_logged  # the third B request is blocked in the wait loop
            assert not got_third.is_set()

            assert got_third.wait(timeout=5), "waiter was not woken when the idle A instances turned cold"
            assert acquired_at[0] - idle_since >= cold_seconds * 0.9
            assert pool._live_per_key == {"A": 1, "B": 3}  # one cold A evicted; b1/b2 still checked out
            assert _Instrumented.constructed == 5
        finally:
            pool._release(key="B", instance=b1)
            pool._release(key="B", instance=b2)
            waiter.join(timeout=5)
            pool.shutdown()
        assert not waiter.is_alive()

    def test_cold_wait_timeout_targets_next_cold_deadline(self, monkeypatch):
        monkeypatch.setattr(converter_pool, "_COLD_IDLE_SECONDS", 30.0)
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=0)
        assert pool._cold_wait_timeout_locked(requester="B") is None  # nothing idle: wait for a notification
        with pool.lease(key="A", factory=_Instrumented):
            pass
        assert pool._cold_wait_timeout_locked(requester="A") is None  # own idle instances do not count
        assert 29.0 < pool._cold_wait_timeout_locked(requester="B") <= 30.0
        monkeypatch.setattr(converter_pool, "_COLD_IDLE_SECONDS", 0.0)
        # Deadline already passed: still a positive timeout, so the wait loop can never spin.
        assert pool._cold_wait_timeout_locked(requester="B") == converter_pool._MIN_COLD_WAIT_SECONDS

    def test_two_configs_side_by_side_do_not_thrash(self):
        """Text-like and entity-like workloads sharing a full pool settle instead of rebuilding per call."""
        cap = 6
        pool = DoclingInstancePool(max_size=cap, idle_ttl_seconds=0)

        def work(key: str) -> None:
            with pool.lease(key=key, factory=_Instrumented) as inst:
                inst.use(seconds=0.002)

        keys = ["text"] * 400 + ["entity"] * 100
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(work, keys))

        assert _Instrumented.violations == 0
        assert pool.stats()["live"] <= cap
        # Settles at a fair split (a few evictions), instead of one rebuild per call (~hundreds).
        assert _Instrumented.constructed <= 2 * cap

    def test_factory_failure_releases_reservation(self):
        pool = DoclingInstancePool(max_size=1, idle_ttl_seconds=0)

        def boom() -> object:
            raise RuntimeError("init failed")

        with pytest.raises(RuntimeError, match="init failed"):
            with pool.lease(key="k", factory=boom):
                pass
        assert pool.stats()["live"] == 0
        with pool.lease(key="k", factory=_Instrumented) as inst:
            assert isinstance(inst, _Instrumented)

    def test_exception_in_block_returns_instance(self):
        pool = DoclingInstancePool(max_size=1, idle_ttl_seconds=0)
        with pytest.raises(ValueError, match="convert failed"):
            with pool.lease(key="k", factory=_Instrumented):
                raise ValueError("convert failed")
        assert pool.stats() == {"max_size": 1, "live": 1, "idle": 1, "constructed": 1, "keys": 1}

    def test_evict_expired_drops_only_old_idle_instances(self):
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=10)
        with pool.lease(key="k", factory=_Instrumented):
            pass
        assert pool.evict_expired(now=time.monotonic()) == 0
        assert pool.evict_expired(now=time.monotonic() + 11) == 1
        assert pool.stats()["live"] == 0
        pool.shutdown()

    def test_ttl_zero_never_expires(self):
        pool = DoclingInstancePool(max_size=4, idle_ttl_seconds=0)
        with pool.lease(key="k", factory=_Instrumented):
            pass
        assert pool.evict_expired(now=time.monotonic() + 10_000) == 0
        assert pool.stats()["idle"] == 1

    def test_reaper_thread_expires_idle_instances(self):
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=0.1)
        with pool.lease(key="k", factory=_Instrumented):
            pass
        deadline = time.monotonic() + 5
        while pool.stats()["live"] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pool.stats()["live"] == 0
        pool.shutdown()

    def test_clear_idle_and_shutdown_keep_pool_usable(self):
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=60)
        with pool.lease(key="k", factory=_Instrumented):
            pass
        pool.shutdown()
        assert pool.stats()["live"] == 0
        with pool.lease(key="k", factory=_Instrumented):
            pass
        assert _Instrumented.constructed == 2
        pool.shutdown()

    def test_close_drops_late_release_and_starts_no_reaper(self):
        pool = DoclingInstancePool(max_size=2, idle_ttl_seconds=60)
        with pool.lease(key="k", factory=_Instrumented):
            pool.close()
        assert pool.stats() == {"max_size": 2, "live": 0, "idle": 0, "constructed": 1, "keys": 0}
        assert pool._reaper is None


# ---------------------------------------------------------------------------
# Process-wide pool configuration
# ---------------------------------------------------------------------------


_POOL_ENV_VARS = (
    EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE,
    EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS,
)


class TestDefaultPool:
    @pytest.fixture(autouse=True)
    def _isolated_settings(self, monkeypatch, tmp_path):
        """Point the runtime config file at an absent path and clear the pool env vars."""
        self.config_path = tmp_path / "docling-pipelines-config.yaml"
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(self.config_path))
        for name in _POOL_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        reset_docling_pool()
        yield
        reset_docling_pool()

    def _write_config(self, text: str) -> None:
        self.config_path.write_text(text, encoding="utf-8")

    def test_default_size_matches_default_text_workers(self):
        from docpipe.core.operators.operator_utils import OperatorUtils

        assert get_docling_pool().max_size == OperatorUtils.get_optimal_workers(is_cpu_intensive=False)

    def test_size_and_ttl_from_env(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE, "3")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS, "0")
        reset_docling_pool()
        pool = get_docling_pool()
        assert pool.max_size == 3
        assert pool.idle_ttl_seconds == 0
        assert get_docling_pool() is pool

    @pytest.mark.parametrize("raw", ["zero", "0", "-2", "", "nan", "NaN", "inf", "-inf"])
    def test_invalid_size_falls_back_to_default(self, monkeypatch, raw):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE, raw)
        reset_docling_pool()
        assert get_docling_pool().max_size == converter_pool.default_pool_size()

    @pytest.mark.parametrize("raw", ["nan", "inf", "-1"])
    def test_invalid_ttl_falls_back_to_default(self, monkeypatch, raw):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS, raw)
        reset_docling_pool()
        assert get_docling_pool().idle_ttl_seconds == converter_pool._DEFAULT_IDLE_TTL_SECONDS

    def test_size_and_ttl_from_config_file(self):
        self._write_config("docling:\n  converter_pool:\n    size: 3\n    idle_ttl_seconds: 0\n")
        pool = get_docling_pool()
        assert pool.max_size == 3
        assert pool.idle_ttl_seconds == 0

    def test_env_overrides_config_file_per_setting(self, monkeypatch):
        self._write_config("docling:\n  converter_pool:\n    size: 3\n    idle_ttl_seconds: 120\n")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE, "5")
        pool = get_docling_pool()
        assert pool.max_size == 5  # env wins
        assert pool.idle_ttl_seconds == 120  # not set in env -> config file

    def test_invalid_env_falls_back_to_config_file(self, monkeypatch, caplog):
        self._write_config("docling:\n  converter_pool:\n    size: 3\n    idle_ttl_seconds: 45\n")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE, "nan")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS, "-1")
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            pool = get_docling_pool()
        assert pool.max_size == 3
        assert pool.idle_ttl_seconds == 45
        assert sum("out-of-range" in record.getMessage() for record in caplog.records) == 2

    @pytest.mark.parametrize("raw", ["0", "-2", "2.0e-1", ".nan", ".inf", "-.inf", "zero", "true", "[4]", "{n: 4}"])
    def test_invalid_config_file_size_falls_back_to_default(self, raw, caplog):
        self._write_config(f"docling:\n  converter_pool:\n    size: {raw}\n")
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            assert get_docling_pool().max_size == converter_pool.default_pool_size()
        assert any("converter_pool" in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize("raw", ["-1", ".nan", ".inf", "soon", "false"])
    def test_invalid_config_file_ttl_falls_back_to_default(self, raw, caplog):
        self._write_config(f"docling:\n  converter_pool:\n    idle_ttl_seconds: {raw}\n")
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            assert get_docling_pool().idle_ttl_seconds == converter_pool._DEFAULT_IDLE_TTL_SECONDS
        assert any("idle_ttl_seconds" in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize(
        "content",
        [
            None,  # no file at all
            "",
            "job_management:\n  store:\n    type: filesystem\n",
            "docling:\n",
            "docling:\n  other: {}\n",
            "docling:\n  converter_pool:\n",
            "docling:\n  converter_pool: {}\n",
        ],
    )
    def test_missing_file_or_section_uses_defaults_silently(self, content, caplog):
        if content is not None:
            self._write_config(content)
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            pool = get_docling_pool()
        assert pool.max_size == converter_pool.default_pool_size()
        assert pool.idle_ttl_seconds == converter_pool._DEFAULT_IDLE_TTL_SECONDS
        assert not caplog.records

    @pytest.mark.parametrize(
        "content",
        [
            "docling: [1, 2\n",  # invalid YAML
            "docling: 8\n",  # section is not a mapping
            "docling:\n  converter_pool: 8\n",
            "docling:\n  converter_pool:\n    pool_size: 3\n",  # unknown key (typo)
        ],
    )
    def test_malformed_config_file_warns_and_uses_defaults(self, content, caplog):
        self._write_config(content)
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            pool = get_docling_pool()
        assert pool.max_size == converter_pool.default_pool_size()
        assert pool.idle_ttl_seconds == converter_pool._DEFAULT_IDLE_TTL_SECONDS
        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_reset_rereads_config_file(self):
        self._write_config("docling:\n  converter_pool:\n    size: 3\n")
        pool = get_docling_pool()
        self._write_config("docling:\n  converter_pool:\n    size: 5\n")
        assert get_docling_pool() is pool  # settings are read once per pool
        reset_docling_pool()
        assert get_docling_pool().max_size == 5

    def test_reset_during_active_lease_does_not_revive_old_pool(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS, "60")
        reset_docling_pool()
        old_pool = get_docling_pool()
        with old_pool.lease(key="k", factory=_Instrumented):
            reset_docling_pool()
        assert old_pool.stats()["idle"] == 0
        assert old_pool._reaper is None
        assert get_docling_pool() is not old_pool

    def test_fork_hook_gives_child_a_fresh_pool(self):
        pool = get_docling_pool()
        converter_pool._reinit_after_fork()
        assert get_docling_pool() is not pool
