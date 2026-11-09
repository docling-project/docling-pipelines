# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""In-process sliding-window rate limiter for authentication endpoints.

Tracks per-IP attempt counts within a sliding time window.

Limitations:
- Single-process only: state is lost on restart and not shared across
  workers/replicas. Replace with a Redis-backed store for multi-instance
  deployments.
- Reverse-proxy deployments: client_ip is derived from the TCP peer address
  (request.client.host). Behind nginx or a k8s Ingress this will be the proxy
  IP, making the limit ineffective for all real clients. Configure your proxy
  to forward X-Forwarded-For and update get_client_ip() to read that header
  when the deployment is behind a trusted reverse proxy.
"""

import time
from collections import defaultdict

RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60

_login_attempts: dict[str, list[float]] = defaultdict(list)


def check_login_rate_limit(*, client_ip: str) -> bool:
    """Return True if the client is within the allowed rate limit, False if exceeded.

    Args:
        client_ip: IP address of the client making the request.

    Returns:
        True when the attempt should be allowed, False when the limit is exceeded.
    """
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    # Discard timestamps that have slid out of the window
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if t > window_start]
    if len(_login_attempts[client_ip]) >= RATE_LIMIT_MAX_ATTEMPTS:
        return False
    _login_attempts[client_ip].append(now)
    return True


def reset_all_state() -> None:
    """Forget all recorded login attempts (used by tests)."""
    _login_attempts.clear()
