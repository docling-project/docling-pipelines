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

Configuration (all optional)::

    audit:
      retention_days: 90               # enables the rotating file; keeps this many daily files
      file: ./data/audit/docpipe-audit.log   # default: <DOCPIPE_DATA_PATH>/audit/docpipe-audit.log
"""

import json
import logging
import sys
import threading
from datetime import UTC, datetime
from enum import StrEnum
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

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


def _build_handlers() -> list[logging.Handler]:
    """Create the default audit handlers from configuration."""
    audit_config = DocpipeConfigLoader.get(key=AUDIT_CONFIG_KEY, default={})
    if not isinstance(audit_config, dict):
        audit_config = {}
    handlers: list[logging.Handler] = [_AuditStreamHandler(sys.stdout)]
    retention_days = _read_retention_days(audit_config=audit_config)
    if retention_days:
        configured_file = audit_config.get("file")
        path = (
            Path(str(configured_file))
            if configured_file
            else Path(get_data_path(sub_dir="/audit")) / DEFAULT_AUDIT_FILE_NAME
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            _AuditFileHandler(path, when="midnight", backupCount=retention_days, encoding="utf-8", utc=True)
        )
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

    Args:
        caller: Authenticated username, or ``None`` when unknown.
        action: The attempted action.
        outcome: ``success`` or ``rejected``.
        operator_id: Operator UUID, when known.
        short_name: Operator short name, when known.
        script_sha256: Hex SHA-256 of the uploaded or deleted script, when there is one.
        reason: Fixed error code or exception class name for a rejected attempt. Never a message.
    """
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
