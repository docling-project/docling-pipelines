"""Process-wide bounded pool of reusable Docling converter/extractor instances.

Why a pool
----------
Docling's ``DocumentConverter`` and ``DocumentExtractor`` lazily build their model
pipelines (layout, TableFormer, OCR, VLM, ...) on first use and cache them per
*instance*. Building a pipeline loads model weights and Docling serialises that work
under a module-global lock, so it is by far the most expensive part of converting a
small batch of documents.

Extraction runs in short-lived worker threads (a fresh executor per ``transform()``
call, and a fresh operator instance per micro-batch), so any per-thread or
per-operator cache is thrown away after every batch. This pool keeps instances alive
for the lifetime of the process instead, so model pipelines are built once per
configuration and reused by every later batch and operator instance.

Guarantees
----------
* **Exclusive use** -- an instance is handed to exactly one caller at a time
  (``lease()``), so ``convert()``/``extract()`` is never called concurrently on the
  same instance. This preserves the guarantee of the previous per-thread cache,
  which existed because concurrent ``convert()`` calls on one instance backed by
  docling-parse are not safe.
* **Bounded** -- at most ``max_size`` instances (across all configurations) are
  alive at any time. When the pool is full, an idle instance of another
  configuration may be evicted (fair-share rules prevent thrashing between
  configurations that run side by side); otherwise the caller blocks until an
  instance is returned, or until an idle instance of another configuration has been
  idle long enough to be evicted, instead of constructing more.
* **Correct keys** -- callers key instances with :func:`options_fingerprint`, which
  hashes the actual option *values* (recursively, including nested model types),
  so two configurations that differ in any setting never share an instance.
* **Bounded idle memory** -- idle instances are dropped after ``idle_ttl_seconds``
  (default 600 s) by a daemon reaper thread so a long-lived API process does not
  keep models resident forever after a job finishes.

Configuration
-------------
The pool is shared by every flow in the process, so it is configured process-wide
rather than per flow or operator. Each setting is read from, in order of precedence,
an environment variable, the ``docling.converter_pool`` section of the runtime config
file ``docling-pipelines-config.yaml`` (path override: ``DOCPIPE_CONFIG_PATH``), and
the built-in default. Settings are read when the pool is first used.

``DOCPIPE_DOCLING_CONVERTER_POOL_SIZE`` / ``docling.converter_pool.size``
    Maximum number of live instances in the process. Default:
    ``min(2 * cpu_count, 16)``, i.e. the default number of text-extraction workers,
    so a single batch at default settings never waits while concurrent micro-batches
    share the same set of converters instead of multiplying them.
``DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS`` / ``docling.converter_pool.idle_ttl_seconds``
    Seconds an instance may stay idle before it is released. ``0`` keeps idle
    instances until process exit. Default: ``600``.
"""

from __future__ import annotations

import atexit
import enum
import hashlib
import json
import math
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePath
from typing import Any

import yaml

from docpipe.core.constants.constants import DocpipeConfigKeys, EnvironmentVariables, _find_project_root
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"
_CONFIG_SECTION_LABEL = f"{DocpipeConfigKeys.DOCLING}.{DocpipeConfigKeys.CONVERTER_POOL}"
_CONFIG_FILE_KEYS = frozenset({DocpipeConfigKeys.SIZE, DocpipeConfigKeys.IDLE_TTL_SECONDS})

_DEFAULT_IDLE_TTL_SECONDS = 600.0
_MAX_SIZE_CEILING = 16
_REAPER_MAX_INTERVAL_SECONDS = 60.0
_COLD_IDLE_SECONDS = 30.0
_MIN_COLD_WAIT_SECONDS = 0.01
_MAX_FINGERPRINT_DEPTH = 64


# ---------------------------------------------------------------------------
# Configuration fingerprinting
# ---------------------------------------------------------------------------


def _qualified_name(cls: type) -> str:
    """Return ``module.QualName`` for a class."""
    return f"{getattr(cls, '__module__', '?')}.{getattr(cls, '__qualname__', repr(cls))}"


def _canonical_sequence(*, values: Any, depth: int, active: set[int]) -> list[Any]:
    """Canonicalise every element of an iterable."""
    return [_canonical(value=item, depth=depth + 1, active=active) for item in values]


def _canonical_object(*, value: Any, depth: int, active: set[int]) -> Any:
    """Canonicalise a container or model object (cycle-protected by the caller)."""
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        fields = {name: getattr(value, name, None) for name in type(value).model_fields}
        fields.update(getattr(value, "__pydantic_extra__", None) or {})
        return {
            "__model__": _qualified_name(type(value)),
            "fields": {name: _canonical(value=fields[name], depth=depth + 1, active=active) for name in sorted(fields)},
        }
    if isinstance(value, dict):
        items = [
            (
                json.dumps(_canonical(value=key, depth=depth + 1, active=active), sort_keys=True, default=str),
                _canonical(value=item, depth=depth + 1, active=active),
            )
            for key, item in value.items()
        ]
        return {"__dict__": sorted(items, key=lambda pair: pair[0])}
    if isinstance(value, (set, frozenset)):
        members = _canonical_sequence(values=value, depth=depth, active=active)
        return {"__set__": sorted(json.dumps(member, sort_keys=True, default=str) for member in members)}
    return _canonical_sequence(values=value, depth=depth, active=active)


def _canonical(*, value: Any, depth: int, active: set[int]) -> Any:
    """Convert an option object into a JSON-serialisable, value-based structure.

    Pydantic models are walked field by field (keeping each nested model's concrete
    type, so e.g. two OCR option subclasses with identical field values still differ).
    Secrets are represented by a digest of their real value rather than the masked
    ``**********`` string, so configurations that differ only in a credential never
    share an instance. Anything unknown falls back to ``type + repr``; for objects whose
    ``repr`` embeds an address this can only cause an unnecessary cache miss, never a
    false match.
    """
    from pydantic import SecretBytes, SecretStr

    if depth > _MAX_FINGERPRINT_DEPTH:
        return {"__too_deep__": _qualified_name(type(value))}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (SecretStr, SecretBytes)):
        secret = value.get_secret_value()
        raw = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
        return {"__secret__": hashlib.sha256(raw).hexdigest()}
    if isinstance(value, bytes):
        return {"__bytes__": hashlib.sha256(value).hexdigest()}
    if isinstance(value, enum.Enum):
        return {
            "__enum__": _qualified_name(type(value)),
            "value": _canonical(value=value.value, depth=depth + 1, active=active),
        }
    if isinstance(value, type):
        return {"__class__": _qualified_name(value)}
    if isinstance(value, PurePath):
        return {"__path__": str(value)}

    from pydantic import BaseModel

    if not isinstance(value, (BaseModel, dict, list, tuple, set, frozenset)):
        return {"__repr__": _qualified_name(type(value)), "value": repr(value)}

    marker = id(value)
    if marker in active:
        return {"__cycle__": _qualified_name(type(value))}
    active.add(marker)
    try:
        return _canonical_object(value=value, depth=depth, active=active)
    finally:
        active.discard(marker)


def options_fingerprint(options: Any) -> str:
    """Return a stable SHA-256 hex digest of the *values* held by ``options``.

    Equal option values always give the same fingerprint within a process; options that
    differ in any value, nested model type, enum member, class reference or secret give
    different fingerprints.

    Args:
        options: Any combination of dicts, lists, pydantic models (e.g. Docling
            ``PdfFormatOption`` / ``PipelineOptions``), enums, classes and scalars.

    Returns:
        A 64-character hexadecimal digest.
    """
    canonical = _canonical(value=options, depth=0, active=set())
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


class DoclingInstancePool:
    """Thread-safe, bounded, keyed pool of expensive Docling objects.

    Use :meth:`lease` to borrow an instance for one operation. Instances are created
    lazily with the supplied factory and returned to the pool afterwards.
    """

    def __init__(self, *, max_size: int, idle_ttl_seconds: float) -> None:
        """Create an empty pool.

        Args:
            max_size: Maximum number of live instances across all keys (>= 1).
            idle_ttl_seconds: Idle lifetime of an instance; ``<= 0`` disables expiry.
        """
        if max_size < 1:
            msg = f"max_size must be >= 1, got {max_size}"
            raise ValueError(msg)
        self._max_size = max_size
        self._idle_ttl_seconds = max(0.0, float(idle_ttl_seconds))
        self._cond = threading.Condition()
        # key -> stack of (instance, last_released_monotonic); most recently used last
        self._idle: dict[str, list[tuple[Any, float]]] = {}
        self._live_per_key: dict[str, int] = {}
        self._live_total = 0
        self._constructed_total = 0
        self._waiting_logged = False
        self._reaper: threading.Thread | None = None
        self._reaper_stop = threading.Event()
        self._closed = False

    @property
    def max_size(self) -> int:
        """Maximum number of live instances."""
        return self._max_size

    @property
    def idle_ttl_seconds(self) -> float:
        """Idle lifetime in seconds (0 = never expire)."""
        return self._idle_ttl_seconds

    def stats(self) -> dict[str, int]:
        """Return a snapshot of pool counters (for logging, tests and benchmarks)."""
        with self._cond:
            return {
                "max_size": self._max_size,
                "live": self._live_total,
                "idle": sum(len(stack) for stack in self._idle.values()),
                "constructed": self._constructed_total,
                "keys": len(self._live_per_key),
            }

    @contextmanager
    def lease(self, *, key: str, factory: Callable[[], Any]) -> Iterator[Any]:
        """Borrow an instance for ``key`` exclusively for the duration of the block.

        Args:
            key: Configuration key; only instances created for the same key are reused.
            factory: Zero-argument callable that builds a new instance for ``key``.

        Yields:
            An instance no other caller holds until the block exits.
        """
        instance = self._acquire(key=key, factory=factory)
        try:
            yield instance
        finally:
            self._release(key=key, instance=instance)

    def _acquire(self, *, key: str, factory: Callable[[], Any]) -> Any:
        """Check out an idle instance for ``key`` or reserve a slot and build one."""
        with self._cond:
            while True:
                stack = self._idle.get(key)
                if stack:
                    instance, _ = stack.pop()
                    if not stack:
                        del self._idle[key]
                    return instance
                if self._live_total < self._max_size or self._evict_lru_idle_locked(requester=key):
                    self._live_total += 1
                    self._live_per_key[key] = self._live_per_key.get(key, 0) + 1
                    break
                if not self._waiting_logged:
                    self._waiting_logged = True
                    logger.info(
                        "Docling converter pool is at capacity (%s); callers wait for a free instance. "
                        "Set %s or %s.%s in the runtime config file to change the limit.",
                        self._max_size,
                        EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE,
                        _CONFIG_SECTION_LABEL,
                        DocpipeConfigKeys.SIZE,
                    )
                # Besides a release/eviction notification, an idle instance of another key
                # turning cold also makes room, and nothing notifies about that: wake up at
                # the next cold deadline and retry the eviction.
                self._cond.wait(timeout=self._cold_wait_timeout_locked(requester=key))

        try:
            logger.info("Creating pooled Docling instance for key %s", key)
            instance = factory()
        except BaseException:
            with self._cond:
                self._forget_locked(key=key)
                self._cond.notify_all()
            raise

        with self._cond:
            self._constructed_total += 1
        return instance

    def _release(self, *, key: str, instance: Any) -> None:
        """Return a checked-out instance to the idle stack and wake waiters.

        After :meth:`close` the instance is dropped instead, so a lease that outlives
        the pool's retirement cannot repopulate it or restart its reaper.
        """
        with self._cond:
            if self._closed:
                self._forget_locked(key=key)
                self._cond.notify_all()
                return
            self._idle.setdefault(key, []).append((instance, time.monotonic()))
            self._cond.notify_all()
        self._ensure_reaper()

    def _forget_locked(self, *, key: str) -> None:
        """Drop one live-instance reservation for ``key``. Caller holds ``_cond``."""
        self._live_total -= 1
        remaining = self._live_per_key.get(key, 0) - 1
        if remaining > 0:
            self._live_per_key[key] = remaining
        else:
            self._live_per_key.pop(key, None)

    def _evict_lru_idle_locked(self, *, requester: str) -> bool:
        """Make room for ``requester`` by dropping an idle instance of another key.

        To avoid evict/rebuild thrash when several configurations compete for a full
        pool (e.g. text conversion and entity extraction running side by side), an idle
        instance of key ``X`` is only evicted when
        * ``requester`` has no live instance at all (guarantees progress), or
        * ``X`` holds at least two more instances than ``requester`` (converges to a
          fair split and can never ping-pong), or
        * the instance has been idle for ``_COLD_IDLE_SECONDS`` (its workload is gone).
        Otherwise the requester waits for one of its own instances. Among eligible
        instances the least recently used one is dropped. Caller holds ``_cond``.

        Returns:
            True if an instance was evicted.
        """
        own_live = self._live_per_key.get(requester, 0)
        cold_before = time.monotonic() - _COLD_IDLE_SECONDS
        oldest_key: str | None = None
        oldest_time = float("inf")
        for key, stack in self._idle.items():
            if key == requester or not stack or stack[0][1] >= oldest_time:
                continue
            eligible = own_live == 0 or self._live_per_key.get(key, 0) >= own_live + 2 or stack[0][1] <= cold_before
            if eligible:
                oldest_key, oldest_time = key, stack[0][1]
        if oldest_key is None:
            return False
        stack = self._idle[oldest_key]
        stack.pop(0)
        if not stack:
            del self._idle[oldest_key]
        self._forget_locked(key=oldest_key)
        logger.debug("Evicted idle Docling instance for key %s to make room", oldest_key)
        return True

    def _cold_wait_timeout_locked(self, *, requester: str) -> float | None:
        """Return how long a blocked ``requester`` may wait before an eviction retry can succeed.

        That is the time until the oldest idle instance of another key reaches
        ``_COLD_IDLE_SECONDS`` and becomes evictable by :meth:`_evict_lru_idle_locked`.
        The result is never below ``_MIN_COLD_WAIT_SECONDS``, so a deadline that has just
        passed cannot turn the wait into a busy loop. Caller holds ``_cond``.

        Returns:
            Seconds to wait, or ``None`` (wait for a notification only) when no idle
            instance of another key exists.
        """
        oldest = min(
            (stack[0][1] for key, stack in self._idle.items() if key != requester and stack),
            default=None,
        )
        if oldest is None:
            return None
        return max(oldest + _COLD_IDLE_SECONDS - time.monotonic(), _MIN_COLD_WAIT_SECONDS)

    def evict_expired(self, *, now: float | None = None) -> int:
        """Drop idle instances that exceeded the idle TTL.

        Args:
            now: Monotonic timestamp to compare against (defaults to ``time.monotonic()``).

        Returns:
            Number of instances dropped.
        """
        if self._idle_ttl_seconds <= 0:
            return 0
        current = time.monotonic() if now is None else now
        dropped = 0
        with self._cond:
            for key in list(self._idle):
                stack = self._idle[key]
                keep = [entry for entry in stack if current - entry[1] < self._idle_ttl_seconds]
                for _ in range(len(stack) - len(keep)):
                    self._forget_locked(key=key)
                    dropped += 1
                if keep:
                    self._idle[key] = keep
                else:
                    del self._idle[key]
            if dropped:
                self._cond.notify_all()
        if dropped:
            logger.info(
                "Released %s idle Docling instance(s) after %.0f s of inactivity", dropped, self._idle_ttl_seconds
            )
        return dropped

    def clear_idle(self) -> int:
        """Drop every idle instance (checked-out instances are unaffected).

        Returns:
            Number of instances dropped.
        """
        with self._cond:
            dropped = 0
            for key, stack in self._idle.items():
                for _ in stack:
                    self._forget_locked(key=key)
                    dropped += 1
            self._idle.clear()
            self._cond.notify_all()
        return dropped

    def shutdown(self) -> None:
        """Stop the idle reaper and drop all idle instances. The pool stays usable."""
        self._reaper_stop.set()
        reaper = self._reaper
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=5)
        self._reaper = None
        self.clear_idle()

    def close(self) -> None:
        """Retire the pool for good: like :meth:`shutdown`, and late releases are dropped.

        Leases still active when the pool is closed finish normally, but their instances
        are discarded on release instead of being kept idle, and no reaper is restarted.
        """
        with self._cond:
            self._closed = True
        self.shutdown()

    def _ensure_reaper(self) -> None:
        """Start the daemon thread that expires idle instances (once, lazily)."""
        if self._idle_ttl_seconds <= 0 or self._reaper is not None:
            return
        with self._cond:
            if self._reaper is not None or self._closed:
                return
            self._reaper_stop.clear()
            self._reaper = threading.Thread(target=self._reap_loop, name="docling-converter-pool-reaper", daemon=True)
            self._reaper.start()

    def _reap_loop(self) -> None:
        """Periodically drop expired idle instances until shutdown."""
        interval = min(self._idle_ttl_seconds / 2, _REAPER_MAX_INTERVAL_SECONDS)
        while not self._reaper_stop.wait(interval):
            try:
                self.evict_expired()
            except Exception:
                logger.warning("Docling converter pool reaper failed", exc_info=True)


# ---------------------------------------------------------------------------
# Process-wide default pool
# ---------------------------------------------------------------------------

_default_pool: DoclingInstancePool | None = None
_default_pool_lock = threading.Lock()


def default_pool_size() -> int:
    """Return the default pool size: the default text-extraction worker count."""
    return min((os.cpu_count() or 4) * 2, _MAX_SIZE_CEILING)


def _parse_number(*, raw: Any, source: str, fallback: float, minimum: float) -> float:
    """Parse one numeric pool setting, returning ``fallback`` when it is unset or invalid.

    Args:
        raw: Value from the environment (``str``) or the config file (any YAML scalar);
            ``None`` and blank strings mean "not set".
        source: Human-readable origin of ``raw`` for the warning message.
        fallback: Value used when ``raw`` is unset or rejected.
        minimum: Smallest accepted value.

    Returns:
        The parsed value, or ``fallback``.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return fallback
    value: float | None = None
    if not isinstance(raw, bool):  # YAML true/false would otherwise parse as 1/0
        with suppress(TypeError, ValueError):
            value = float(raw)
    if value is None:
        logger.warning("Ignoring invalid value %r for %s; using %s", raw, source, fallback)
        return fallback
    if not math.isfinite(value) or value < minimum:
        logger.warning("Ignoring out-of-range value %r for %s; using %s", raw, source, fallback)
        return fallback
    return value


def _load_config_file_settings() -> tuple[dict[str, Any], str]:
    """Return the ``docling.converter_pool`` section of the runtime config file.

    The file is ``docling-pipelines-config.yaml`` at the project root, or the path in
    ``DOCPIPE_CONFIG_PATH`` (the same lookup as the other runtime settings). A missing
    file or section yields ``{}`` silently; an unreadable file or a malformed section
    is ignored with a warning so the pool still starts with its defaults.

    Returns:
        ``(settings, label)`` where ``label`` names the section for log messages.
    """
    config_path = Path(os.getenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(_DEFAULT_CONFIG_PATH)))
    label = f"{config_path} ({_CONFIG_SECTION_LABEL})"
    if not config_path.exists():
        return {}, label
    try:
        with config_path.open(encoding="utf-8") as handle:
            yaml_config = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s; ignoring its Docling converter pool settings: %s", config_path, exc)
        return {}, label

    section: Any = yaml_config if isinstance(yaml_config, dict) else {}
    for name in (DocpipeConfigKeys.DOCLING, DocpipeConfigKeys.CONVERTER_POOL):
        section = section.get(name)
        if section is None:
            return {}, label
        if not isinstance(section, dict):
            logger.warning("Ignoring %s: '%s' must be a mapping, got %s", label, name, type(section).__name__)
            return {}, label
    unknown = sorted(str(name) for name in section if name not in _CONFIG_FILE_KEYS)
    if unknown:
        logger.warning("Ignoring unknown key(s) %s in %s", ", ".join(unknown), label)
    return section, label


def _resolve_pool_settings() -> tuple[int, float]:
    """Resolve ``(max_size, idle_ttl_seconds)``: environment > config file > built-in default.

    An invalid value is skipped with a warning and the next source in that order is used.
    """
    file_settings, label = _load_config_file_settings()
    size_fallback = _parse_number(
        raw=file_settings.get(DocpipeConfigKeys.SIZE),
        source=f"{DocpipeConfigKeys.SIZE} in {label}",
        fallback=default_pool_size(),
        minimum=1,
    )
    size = _parse_number(
        raw=os.getenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE),
        source=EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE,
        fallback=size_fallback,
        minimum=1,
    )
    ttl_fallback = _parse_number(
        raw=file_settings.get(DocpipeConfigKeys.IDLE_TTL_SECONDS),
        source=f"{DocpipeConfigKeys.IDLE_TTL_SECONDS} in {label}",
        fallback=_DEFAULT_IDLE_TTL_SECONDS,
        minimum=0,
    )
    ttl = _parse_number(
        raw=os.getenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS),
        source=EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS,
        fallback=ttl_fallback,
        minimum=0,
    )
    return int(size), ttl


def get_docling_pool() -> DoclingInstancePool:
    """Return the process-wide pool, creating it on first use.

    Settings are resolved once per pool (see :func:`_resolve_pool_settings`); call
    :func:`reset_docling_pool` to pick up changed settings.
    """
    global _default_pool
    pool = _default_pool
    if pool is not None:
        return pool
    with _default_pool_lock:
        if _default_pool is None:
            size, ttl = _resolve_pool_settings()
            _default_pool = DoclingInstancePool(max_size=size, idle_ttl_seconds=ttl)
            logger.info("Initialised Docling converter pool (max_size=%s, idle_ttl_seconds=%s)", size, ttl)
        return _default_pool


def reset_docling_pool() -> None:
    """Close and discard the process-wide pool; the next use re-reads env and config file."""
    global _default_pool
    with _default_pool_lock:
        pool, _default_pool = _default_pool, None
    if pool is not None:
        pool.close()


def shutdown_docling_pool() -> None:
    """Process-exit hook: release idle Docling instances and stop the reaper."""
    pool = _default_pool
    if pool is not None:
        pool.shutdown()


def _reinit_after_fork() -> None:
    """Give a forked child a fresh pool: inherited locks/threads are unusable there."""
    global _default_pool, _default_pool_lock
    _default_pool = None
    _default_pool_lock = threading.Lock()


atexit.register(shutdown_docling_pool)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reinit_after_fork)
