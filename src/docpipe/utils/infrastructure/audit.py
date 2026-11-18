# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Dedicated audit logger (``docpipe.audit``) that writes one structured JSON record per event.

The audit logger is deliberately separate from the application logging configuration:

- it does not propagate to the ``docpipe`` logger, so ``DS_LOG_LEVEL`` and any filter installed on
  application handlers (debug filters, secret scrubbers) never see or suppress its records;
- its own level is pinned to ``INFO`` and re-asserted on every emit, so a later ``dictConfig`` or
  ``logger.setLevel`` call cannot silence it;
- its handlers ignore filters, and filters attached to the logger itself are dropped on every emit.

Records are written to stdout as JSON lines. When ``audit.retention_days`` is set in
``docling-pipelines-config.yaml`` a daily-rotating file is written as well, keeping that many days.

Failure policy (fail-open): the audit trail never decides the outcome of a request. Handlers are built at
application start (``initialize_audit_logger``), stdout first. If the file cannot be created or opened, an ERROR is
logged and records go to stdout only. A write failure, at setup or later, is logged through the application
logger and never raised, so it cannot turn a finished operation into an error or replace the real error of a
rejected one.

Configuration (all optional)::

    audit:
      retention_days: 90               # enables the rotating file; keeps this many daily files
      file: ./data/audit/docpipe-audit.log   # default: <DOCPIPE_DATA_PATH>/audit/docpipe-audit.log
"""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
import functools
import inspect
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import re
import sys
import threading
from typing import Any, TypeVar

from docpipe.core.models.actor_context import ActorContext
from docpipe.exceptions.docpipe_exceptions import DocpipeException, PermissionDeniedException
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import AUDIT_LOGGER_NAME, get_logger

AUDIT_CONFIG_KEY = "audit"
DEFAULT_AUDIT_FILE_NAME = "docpipe-audit.log"

_logger = get_logger(__name__)
_lock = threading.Lock()


class AuditAction(StrEnum):
    """Audited custom operator actions."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class AuditOutcome(StrEnum):
    """Result of an audited attempt."""

    SUCCESS = "success"
    REJECTED = "rejected"


class _UnfilterableMixin:
    """Make a handler immune to filters so no debug or scrub filter can drop an audit record."""

    def addFilter(self, filter: Any) -> None:  # noqa: N802 - logging.Handler API
        """Ignore the filter."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Accept every record."""
        return True

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - logging.Handler API
        """Report a failed write through the application logger instead of dropping it."""
        exc_type = sys.exc_info()[0]
        _logger.error("Audit record could not be written (%s)", exc_type.__name__ if exc_type else "unknown error")


class _AuditStreamHandler(_UnfilterableMixin, logging.StreamHandler):  # type: ignore[type-arg]
    """Stdout handler for audit records."""


class _AuditFileHandler(_UnfilterableMixin, TimedRotatingFileHandler):
    """Daily-rotating file handler for audit records."""


def _is_audit_handler(handler: logging.Handler) -> bool:
    return isinstance(handler, _UnfilterableMixin)


def _read_retention_days(*, audit_config: dict[str, Any]) -> int:
    """Return ``audit.retention_days`` as a positive int, or 0 when unset or invalid."""
    raw = audit_config.get("retention_days")
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        _logger.warning("Ignoring invalid audit.retention_days; it must be a positive integer")
        return 0
    return raw


def _build_file_handler(*, audit_config: dict[str, Any], retention_days: int) -> logging.Handler | None:
    """Create the rotating file handler, or return None (after logging an ERROR) when it cannot be opened."""
    configured_file = audit_config.get("file")
    try:
        path = (
            Path(str(configured_file))
            if configured_file
            else Path(get_data_path(sub_dir="/audit")) / DEFAULT_AUDIT_FILE_NAME
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return _AuditFileHandler(path, when="midnight", backupCount=retention_days, encoding="utf-8", utc=True)
    except OSError as exc:
        _logger.error(
            "Audit file could not be opened (%s); audit records go to stdout only. Check audit.file and permissions.",
            type(exc).__name__,
        )
        return None


def _build_handlers() -> list[logging.Handler]:
    """Create the default audit handlers from configuration. Stdout is always first; the file is optional."""
    audit_config = DocpipeConfigLoader.get(key=AUDIT_CONFIG_KEY, default={})
    if not isinstance(audit_config, dict):
        audit_config = {}
    handlers: list[logging.Handler] = [_AuditStreamHandler(sys.stdout)]
    retention_days = _read_retention_days(audit_config=audit_config)
    if retention_days:
        file_handler = _build_file_handler(audit_config=audit_config, retention_days=retention_days)
        if file_handler is not None:
            handlers.append(file_handler)
    formatter = logging.Formatter("%(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
    return handlers


def get_audit_logger() -> logging.Logger:
    """Return the ``docpipe.audit`` logger, (re)asserting the settings that keep it from being suppressed."""
    audit_logger = get_logger(name=AUDIT_LOGGER_NAME, level=logging.INFO)
    with _lock:
        audit_logger.setLevel(logging.INFO)
        audit_logger.disabled = False
        audit_logger.propagate = False
        audit_logger.filters.clear()
        if not any(_is_audit_handler(h) for h in audit_logger.handlers):
            for handler in list(audit_logger.handlers):
                if isinstance(handler, logging.NullHandler):
                    audit_logger.removeHandler(handler)
            for handler in _build_handlers():
                audit_logger.addHandler(handler)
    return audit_logger


def initialize_audit_logger() -> None:
    """Build the audit handlers now, so a bad ``audit.file`` is reported at start-up and not on the first write."""
    get_audit_logger()


def reset_audit_logger() -> None:
    """Remove all audit handlers so the next emit rebuilds them from configuration (tests)."""
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    with _lock:
        for handler in list(audit_logger.handlers):
            audit_logger.removeHandler(handler)
            handler.close()


def emit_audit_record(
    *,
    caller: str | None,
    action: AuditAction,
    outcome: AuditOutcome,
    operator_id: str | None = None,
    short_name: str | None = None,
    script_sha256: str | None = None,
    reason: str | None = None,
) -> None:
    """Write one audit record as a single JSON line to the ``docpipe.audit`` logger.

    Never raises: a failure to write is logged through the application logger (see the module docstring).

    Args:
        caller: Authenticated username, or ``None`` when unknown.
        action: The attempted action.
        outcome: ``success`` or ``rejected``.
        operator_id: Operator UUID, when known.
        short_name: Operator short name, when known.
        script_sha256: Hex SHA-256 of the uploaded or deleted script, when there is one.
        reason: Fixed error code or exception class name for a rejected attempt. Never a message.
    """
    try:
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "caller": caller,
            "operator_id": operator_id,
            "short_name": short_name,
            "action": action.value,
            "script_sha256": script_sha256,
            "outcome": outcome.value,
        }
        if reason is not None:
            record["reason"] = reason
        get_audit_logger().info("%s", json.dumps(record, separators=(",", ":")))
    except Exception as exc:
        _logger.error("Audit record could not be written (%s)", type(exc).__name__)


def emit_resolution_audit_record(
    *,
    node_name: str,
    config_key: str,
    provider: str | None,
    outcome: str,
    correlation_id: str,
) -> None:
    """Emit one structured JSON record per resolution attempt to the ``docpipe.audit`` logger.

    Never raises, like ``emit_audit_record``: the audit trail does not decide whether a secret resolves.

    Args:
        node_name: Node name (node).
        config_key: Config key path (config_key).
        provider: Provider name (provider), if any.
        outcome: Resolution outcome, e.g. "resolved", "not permitted".
        correlation_id: Correlation ID.
    """
    try:
        from docpipe.core.models.session_info import get_session_info

        session_info = get_session_info()
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "job_id": session_info.job_id,
            "job_run_id": session_info.job_run_id,
            "node": node_name,
            "config_key": config_key,
            "provider": provider,
            "outcome": outcome,
            "correlation_id": correlation_id,
        }
        logger = get_audit_logger()
        if outcome == "not permitted":
            logger.warning("%s", json.dumps(record, separators=(",", ":")))
        else:
            logger.info("%s", json.dumps(record, separators=(",", ":")))
    except Exception as exc:
        _logger.error("Audit record could not be written (%s)", type(exc).__name__)


# Plain text audit log elements from PR #591
audit_logger = get_logger(AUDIT_LOGGER_NAME)

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
            username = actor.username if actor is not None and not actor.is_system else None
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
