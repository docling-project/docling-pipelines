# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""In-process throttle for failed login attempts.

Two independent rules apply, and only failed attempts are counted:

* Per address: at most ``RATE_LIMIT_MAX_ATTEMPTS`` failures per ``RATE_LIMIT_WINDOW_SECONDS``
  (sliding window).
* Per (address, username) pair: ``PAIR_LOCKOUT_THRESHOLD`` consecutive failures lock that pair
  for ``PAIR_LOCKOUT_SECONDS``. A successful login clears the pair's consecutive failures.

A different address is never locked out by another address's failures, so an attacker cannot
lock a legitimate user out from elsewhere beyond the pair they control.

The state is guarded by one lock and bounded: expired entries are pruned on every call and the
number of tracked keys is capped (oldest entries are evicted first).

Limitations:
- Single-process only: state is lost on restart and not shared across workers/replicas.
  Replace with a Redis-backed store for multi-instance deployments.
- Behind a reverse proxy the TCP peer is the proxy. Set ``DOCPIPE_TRUST_PROXY_HEADERS=true`` only
  when the proxy appends the real client address to ``X-Forwarded-For``; the rightmost entry is
  then used, because it is the one the trusted proxy added and the client cannot forge it.
"""

import threading
import time
from dataclasses import dataclass

from fastapi import Request

RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60
PAIR_LOCKOUT_THRESHOLD = 5
PAIR_LOCKOUT_SECONDS = 300
MAX_TRACKED_KEYS = 10_000
MAX_USERNAME_KEY_LENGTH = 256
UNKNOWN_CLIENT = "unknown"
FORWARDED_FOR_HEADER = "x-forwarded-for"


@dataclass
class _PairState:
    """Consecutive failures for one (address, username) pair."""

    failures: int = 0
    last_failure: float = 0.0
    locked_until: float = 0.0


_lock = threading.Lock()
# Failure timestamps (time.monotonic) per client address, oldest first.
_login_attempts: dict[str, list[float]] = {}
_pair_state: dict[tuple[str, str], _PairState] = {}


def get_client_ip(*, request: Request, trust_proxy_headers: bool) -> str:
    """Return the client address used as the throttle key.

    Args:
        request: Current request.
        trust_proxy_headers: Whether ``X-Forwarded-For`` comes from a trusted proxy.

    Returns:
        The TCP peer address, or the rightmost ``X-Forwarded-For`` entry when proxy headers are trusted.
    """
    peer = request.client.host if request.client else UNKNOWN_CLIENT
    if not trust_proxy_headers:
        return peer
    entries = [entry.strip() for entry in request.headers.get(FORWARDED_FOR_HEADER, "").split(",")]
    forwarded = next((entry for entry in reversed(entries) if entry), None)
    return forwarded or peer


def _pair_key(*, client_ip: str, username: str) -> tuple[str, str]:
    """Normalise the (address, username) key so case and padding do not bypass the lockout."""
    return client_ip, username.strip().casefold()[:MAX_USERNAME_KEY_LENGTH]


def _prune(*, now: float) -> None:
    """Drop expired entries and cap the number of tracked keys. The caller holds ``_lock``."""
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    for ip in list(_login_attempts):
        fresh = [t for t in _login_attempts[ip] if t > window_start]
        if fresh:
            _login_attempts[ip] = fresh
        else:
            del _login_attempts[ip]
    for key in list(_pair_state):
        state = _pair_state[key]
        if state.locked_until <= now and state.last_failure <= now - PAIR_LOCKOUT_SECONDS:
            del _pair_state[key]
    # Dicts keep insertion order, so the first keys are the oldest.
    while len(_login_attempts) > MAX_TRACKED_KEYS:
        del _login_attempts[next(iter(_login_attempts))]
    while len(_pair_state) > MAX_TRACKED_KEYS:
        del _pair_state[next(iter(_pair_state))]


def login_retry_after(*, client_ip: str, username: str | None = None) -> int:
    """Return how many seconds the client must wait, or 0 when the attempt is allowed.

    This is a pure check: it never records an attempt.

    Args:
        client_ip: Address of the client making the request.
        username: Username being tried, enabling the per-pair lockout.

    Returns:
        0 when allowed, otherwise the whole seconds until the throttle lifts (at least 1).
    """
    with _lock:
        now = time.monotonic()
        _prune(now=now)
        wait = 0.0
        attempts = _login_attempts.get(client_ip, [])
        if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
            # The slot reopens when the oldest counted failure leaves the window.
            wait = attempts[-RATE_LIMIT_MAX_ATTEMPTS] + RATE_LIMIT_WINDOW_SECONDS - now
        if username is not None:
            state = _pair_state.get(_pair_key(client_ip=client_ip, username=username))
            if state is not None and state.locked_until > now:
                wait = max(wait, state.locked_until - now)
    if wait <= 0:
        return 0
    return max(1, int(wait) + 1)


def check_login_rate_limit(*, client_ip: str, username: str | None = None) -> bool:
    """Return True if the attempt is allowed, False if the client is throttled.

    Args:
        client_ip: Address of the client making the request.
        username: Username being tried, enabling the per-pair lockout.

    Returns:
        True when the attempt may proceed. This call does not record anything.
    """
    return login_retry_after(client_ip=client_ip, username=username) == 0


def record_failed_login(*, client_ip: str, username: str) -> None:
    """Record one failed login for the address and for the (address, username) pair.

    Args:
        client_ip: Address of the client that failed to authenticate.
        username: Username that was tried.
    """
    with _lock:
        now = time.monotonic()
        _prune(now=now)
        _login_attempts.setdefault(client_ip, []).append(now)
        key = _pair_key(client_ip=client_ip, username=username)
        state = _pair_state.setdefault(key, _PairState())
        state.failures += 1
        state.last_failure = now
        if state.failures >= PAIR_LOCKOUT_THRESHOLD:
            state.locked_until = now + PAIR_LOCKOUT_SECONDS
            state.failures = 0
        _prune(now=now)


def reset_login_failures(*, client_ip: str, username: str) -> None:
    """Clear the consecutive failures of the (address, username) pair after a successful login.

    The per-address window is left alone, so a valid account cannot be used to reset the
    counter while guessing other usernames.

    Args:
        client_ip: Address of the client that authenticated.
        username: Username that authenticated.
    """
    with _lock:
        _pair_state.pop(_pair_key(client_ip=client_ip, username=username), None)


def reset_all_state() -> None:
    """Forget all recorded login failures (used by tests)."""
    with _lock:
        _login_attempts.clear()
        _pair_state.clear()
