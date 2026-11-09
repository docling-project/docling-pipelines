# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Audit trail for authorization denials and successful or failed writes.

Audit lines go through the regular logger (logger name ``docpipe.audit``) and carry the
username, action, target and outcome. Values that can come from untrusted sources have
control characters (including newlines) removed so they cannot forge extra log lines.
Passwords and tokens are never passed to this module.
"""

import functools
import inspect
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from docpipe.core.models.actor_context import ActorContext
from docpipe.exceptions.docpipe_exceptions import DocpipeException, PermissionDeniedException
from docpipe.utils.infrastructure.logging import get_logger

audit_logger = get_logger("docpipe.audit")

OUTCOME_SUCCESS = "success"
OUTCOME_DENIED = "denied"
OUTCOME_FAILED = "failed"

NO_USER = "-"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")

F = TypeVar("F", bound=Callable[..., Any])


def sanitize_for_log(value: object) -> str:
    """Return ``value`` as a string with newlines and other control characters removed.

    Args:
        value: Any value, typically a username or target taken from a request.

    Returns:
        The sanitised string.
    """
    return _CONTROL_CHARS.sub("", str(value))


def _safe_target(builder: Callable[[Any], str], value: Any) -> str:
    """Build an audit target, falling back to ``-`` so auditing never breaks a write."""
    try:
        return builder(value)
    except Exception:
        return NO_USER


def audit_event(
    *,
    username: str | None,
    action: str,
    target: str,
    outcome: str,
    status_code: int | None = None,
) -> None:
    """Write one audit line.

    Args:
        username: Caller's username, or ``None`` when there is no authenticated caller.
        action: Action name, for example ``flow.create``.
        target: Identifier of the asset the action applies to.
        outcome: One of ``success``, ``denied`` or ``failed``.
        status_code: HTTP status code for non-success outcomes, when known.
    """
    audit_logger.log(
        logging.INFO if outcome == OUTCOME_SUCCESS else logging.WARNING,
        "AUDIT user=%s action=%s target=%s outcome=%s status=%s",
        sanitize_for_log(username) if username else NO_USER,
        sanitize_for_log(action),
        sanitize_for_log(target),
        sanitize_for_log(outcome),
        status_code if status_code is not None else "-",
    )


def audited(
    *,
    action: str,
    target: Callable[[dict[str, Any]], str],
    result_target: Callable[[Any], str] | None = None,
) -> Callable[[F], F]:
    """Decorate a service write method so its outcome is written to the audit log.

    The wrapped method must accept a keyword-only ``actor`` argument. A success is logged
    as ``success``, a ``PermissionDeniedException`` as ``denied`` (403), and any other
    ``DocpipeException`` (404, 409, 400 and so on) as ``failed`` with its status code.
    Other exceptions propagate unlogged.

    Args:
        action: Action name, for example ``flow.update``.
        target: Builds the target identifier from the call's bound arguments.
        result_target: Optional builder of the target from the return value, used on
            success (for example the id of a newly created asset).

    Returns:
        A decorator for the service method.
    """

    def decorator(func: F) -> F:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            actor: ActorContext | None = bound.arguments.get("actor")
            username = actor.username if actor is not None else None
            call_target = _safe_target(target, bound.arguments)
            try:
                result = func(*args, **kwargs)
            except PermissionDeniedException:
                audit_event(
                    username=username, action=action, target=call_target, outcome=OUTCOME_DENIED, status_code=403
                )
                raise
            except DocpipeException as exc:
                audit_event(
                    username=username,
                    action=action,
                    target=call_target,
                    outcome=OUTCOME_FAILED,
                    status_code=exc.status_code,
                )
                raise
            audit_event(
                username=username,
                action=action,
                target=_safe_target(result_target, result) if result_target is not None else call_target,
                outcome=OUTCOME_SUCCESS,
            )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
