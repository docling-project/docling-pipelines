# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the dedicated ``docpipe.audit`` logger."""

import io
import json
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from docpipe.utils.infrastructure.audit import (
    AUDIT_LOGGER_NAME,
    AuditAction,
    AuditOutcome,
    emit_audit_record,
    get_audit_logger,
    reset_audit_logger,
)
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


class _DropEverything(logging.Filter):
    """A filter like a debug-only or scrub filter that would suppress every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        return False


@pytest.fixture(autouse=True)
def _clean_audit_logger(*, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(DocpipeConfigLoader, "_config", {})
    reset_audit_logger()
    yield
    reset_audit_logger()
    DocpipeConfigLoader.reset()


def _emit(**overrides: Any) -> None:
    fields: dict[str, Any] = {
        "caller": "alice",
        "action": AuditAction.CREATE,
        "outcome": AuditOutcome.SUCCESS,
        "operator_id": "id-1",
        "short_name": "op",
        "script_sha256": "ab" * 32,
    }
    fields.update(overrides)
    emit_audit_record(**fields)


def _stream_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    handlers = [h for h in get_audit_logger().handlers if isinstance(h, logging.StreamHandler)]
    assert handlers
    return handlers[0]


def test_record_is_one_json_line_with_required_fields(capsys: pytest.CaptureFixture[str]) -> None:
    _emit()

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == {"timestamp", "caller", "operator_id", "short_name", "action", "script_sha256", "outcome"}
    assert record["outcome"] == "success"
    assert record["action"] == "create"


def test_reason_is_included_only_when_given(capsys: pytest.CaptureFixture[str]) -> None:
    _emit(outcome=AuditOutcome.REJECTED, reason="custom_operator_invalid_data")

    record = json.loads(next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")))
    assert record["outcome"] == "rejected"
    assert record["reason"] == "custom_operator_invalid_data"


def test_logger_does_not_propagate_to_application_logger() -> None:
    assert get_audit_logger().propagate is False


@pytest.mark.parametrize("level", [logging.WARNING, logging.ERROR, logging.CRITICAL])
def test_application_log_level_cannot_suppress_records(level: int, capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger("docpipe").setLevel(level)
    logging.getLogger(AUDIT_LOGGER_NAME).setLevel(level)

    _emit()

    assert '"outcome":"success"' in capsys.readouterr().out


def test_disabled_logger_cannot_suppress_records(capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger(AUDIT_LOGGER_NAME).disabled = True

    _emit()

    assert '"outcome":"success"' in capsys.readouterr().out


def test_filters_on_logger_and_handlers_cannot_suppress_records(capsys: pytest.CaptureFixture[str]) -> None:
    audit_logger = get_audit_logger()
    audit_logger.addFilter(_DropEverything())
    _stream_handler().addFilter(_DropEverything())

    _emit()

    assert '"outcome":"success"' in capsys.readouterr().out


def test_ds_log_level_warning_does_not_hide_records(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DS_LOG_LEVEL", "WARNING")

    _emit()

    assert '"outcome":"success"' in capsys.readouterr().out


def test_no_file_without_retention_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path))

    _emit()

    assert not (tmp_path / "audit").exists()


def test_retention_days_enables_rotating_file_that_keeps_that_many_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "audit" / "audit.log"
    monkeypatch.setattr(DocpipeConfigLoader, "_config", {"audit": {"retention_days": 30, "file": str(log_file)}})

    _emit()

    from logging.handlers import TimedRotatingFileHandler

    file_handlers = [h for h in get_audit_logger().handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].backupCount == 30
    assert json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])["caller"] == "alice"


@pytest.mark.parametrize("bad", [0, -1, "30", True, 1.5])
def test_invalid_retention_days_is_ignored(bad: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(DocpipeConfigLoader, "_config", {"audit": {"retention_days": bad}})

    _emit()

    assert not (tmp_path / "audit").exists()


def test_handlers_are_not_duplicated_across_emits(capsys: pytest.CaptureFixture[str]) -> None:
    _emit()
    _emit()

    out = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert len(out) == 2


def test_stdout_is_not_required_for_capture() -> None:
    """A test handler attached to the logger receives the message verbatim."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logging.getLogger(AUDIT_LOGGER_NAME).addHandler(handler)
    try:
        _emit()
    finally:
        logging.getLogger(AUDIT_LOGGER_NAME).removeHandler(handler)

    assert json.loads(stream.getvalue())["short_name"] == "op"
