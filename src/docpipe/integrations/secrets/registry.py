# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Per-run registry of resolved secret values, and the scrubber built on it.

The registry is defense in depth. The primary controls are where a reference may appear, the
``SecretValue`` type, per-node scope, and the data plane; this module removes known secret values
from text that is about to leave the process (logs, messages, metadata, lineage, REST errors)
even if upstream code forgot to.

What is registered
    Every non-empty resolved value, plus its percent-encoded (``quote`` and ``quote_plus``),
    JSON-escaped, and base64 (standard and URL-safe, padded and unpadded) forms. An empty value is
    never registered: replacing an empty string would corrupt every line. Short values are
    registered too; over-redaction is accepted.

Lifetime
    Entries belong to a run id and are removed by :func:`clear_run` when the run ends.

Failure
    :func:`scrub` never raises and never returns unscrubbed text on failure: it returns
    :data:`SCRUB_FAILURE_PLACEHOLDER` instead.

Cache keys
    :func:`cache_key_digest` keys adapter caches by ``HMAC-SHA256`` with a per-run random key that
    is never persisted and is dropped with the run, so a digest contains no substring of the secret
    and differs between runs.

This module has no ``docpipe`` imports at module level so low-level utilities (the logging
filter) can use it without import cycles.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, quote_plus

MASK: str = "***"
SCRUB_FAILURE_PLACEHOLDER: str = "[redacted: scrubbing failed]"
UNSCOPED_RUN: str = "unscoped"


class SecretRegistry:
    """Thread-safe store of secret strings, grouped by run id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._forms: dict[str, set[str]] = {}
        self._keys: dict[str, bytes] = {}
        self._pattern: re.Pattern[str] | None = None

    @staticmethod
    def derive_forms(*, value: str) -> set[str]:
        """Return ``value`` and its percent-encoded, JSON-escaped, and base64 forms."""
        raw = value.encode("utf-8")
        forms = {
            value,
            quote(value),
            quote(value, safe=""),
            quote_plus(value),
            json.dumps(value)[1:-1],
            base64.b64encode(raw).decode("ascii"),
            base64.urlsafe_b64encode(raw).decode("ascii"),
        }
        forms |= {form.rstrip("=") for form in tuple(forms) if form.endswith("=")}
        return {form for form in forms if form}

    @staticmethod
    def _strings_in(*, value: Any) -> Iterable[str]:
        """Yield every non-empty string held by a secret: the string, or the leaves of a structured one."""
        if isinstance(value, str):
            if value:
                yield value
        elif isinstance(value, dict):
            yield json.dumps(value, sort_keys=True)
            yield json.dumps(value)
            for item in value.values():
                yield from SecretRegistry._strings_in(value=item)
        elif isinstance(value, list | tuple):
            yield json.dumps(list(value))
            for item in value:
                yield from SecretRegistry._strings_in(value=item)

    def register(self, *, run_id: str | None, value: Any) -> int:
        """Register a resolved value (a string, or a parsed structured value) for a run.

        Returns:
            The number of registered strings. Zero for an empty value, which is never registered.
        """
        forms: set[str] = set()
        for text in self._strings_in(value=value):
            forms |= self.derive_forms(value=text)
        if not forms:
            return 0
        with self._lock:
            self._forms.setdefault(run_id or UNSCOPED_RUN, set()).update(forms)
            self._pattern = None
        return len(forms)

    def clear_run(self, *, run_id: str | None) -> None:
        """Drop every registered string and the cache-key secret of a run."""
        with self._lock:
            key = run_id or UNSCOPED_RUN
            self._forms.pop(key, None)
            self._keys.pop(key, None)
            self._pattern = None

    def clear_all(self) -> None:
        """Drop everything (tests)."""
        with self._lock:
            self._forms.clear()
            self._keys.clear()
            self._pattern = None

    def has_entries(self) -> bool:
        """Whether any run has a registered string."""
        return bool(self._forms)

    def _compiled(self) -> re.Pattern[str] | None:
        with self._lock:
            if self._pattern is None and self._forms:
                every = set().union(*self._forms.values())
                # Longest first: the alternation takes the first match at a position, so a long
                # form wins over a shorter value that happens to be its prefix.
                ordered = sorted(every, key=lambda item: (-len(item), item))
                self._pattern = re.compile("|".join(re.escape(item) for item in ordered))
            return self._pattern

    def scrub_text(self, *, text: str) -> str:
        """Replace every registered string in ``text`` with the mask. May raise; see :func:`scrub`.

        All active runs are applied, not only the caller's: a record logged by a worker thread
        that lost its run context must still be scrubbed.
        """
        pattern = self._compiled()
        if pattern is None:
            return text
        return pattern.sub(MASK, text)

    def cache_key_digest(self, *, run_id: str | None, namespace: str, parts: Iterable[str | None]) -> str:
        """Return ``HMAC-SHA256(run key, namespace and parts)`` as hex."""
        with self._lock:
            key = self._keys.setdefault(run_id or UNSCOPED_RUN, secrets.token_bytes(32))
        message = json.dumps([namespace, *["" if part is None else str(part) for part in parts]])
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


_REGISTRY = SecretRegistry()


def get_registry() -> SecretRegistry:
    """Return the process-wide registry."""
    return _REGISTRY


def _current_run_id() -> str | None:
    """Return the current job run id from the session context, or None."""
    from docpipe.core.models.session_info import session_info_var

    session_info = session_info_var.get()
    run_id = session_info.job_run_id if session_info is not None else None
    return str(run_id) if run_id else None


def register_secret(*, value: Any, run_id: str | None = None) -> int:
    """Register a resolved value, and its derived forms, with the registry for ``run_id``.

    ``run_id`` defaults to the current session's job run id. An empty value is not registered.
    """
    return _REGISTRY.register(run_id=run_id or _current_run_id(), value=value)


def clear_run(*, run_id: str | None = None) -> None:
    """Drop the registry entries and the cache-key secret of a run (the current run by default)."""
    _REGISTRY.clear_run(run_id=run_id or _current_run_id())


def scrub(text: str) -> str:
    """Remove registered secret values from ``text``. Fails closed.

    Returns:
        The text with every registered string replaced by ``***``, or
        :data:`SCRUB_FAILURE_PLACEHOLDER` when scrubbing raised.
    """
    try:
        return _REGISTRY.scrub_text(text=text)
    except Exception:
        return SCRUB_FAILURE_PLACEHOLDER


def scrub_value(value: Any) -> Any:
    """Return a copy of ``value`` with registered secrets removed from every string, key, and leaf.

    Containers are rebuilt (dicts, lists, tuples); other objects are returned as they are. Fails
    closed: when scrubbing raises, the placeholder string is returned in place of the value.
    """
    try:
        if not _REGISTRY.has_entries():
            return value
        return _scrub_node(value=value)
    except Exception:
        return SCRUB_FAILURE_PLACEHOLDER


def _scrub_node(*, value: Any) -> Any:
    if isinstance(value, str):
        return _REGISTRY.scrub_text(text=value)
    if isinstance(value, dict):
        return {_scrub_node(value=key): _scrub_node(value=item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_node(value=item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_node(value=item) for item in value)
    return value


def cache_key_digest(*, namespace: str, parts: Iterable[str | None], run_id: str | None = None) -> str:
    """Key an adapter cache by an ``HMAC-SHA256`` digest under the run's random key.

    Use this instead of a string containing the secret or an unsalted hash of it. The digest is
    stable within a run and different in another run. Never log it.
    """
    return _REGISTRY.cache_key_digest(run_id=run_id or _current_run_id(), namespace=namespace, parts=parts)
