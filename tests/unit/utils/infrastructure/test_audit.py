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
    _AuditStreamHandler,
    emit_audit_record,
    get_audit_logger,
    initialize_audit_logger,
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
def test_application_log_level_cannot_suppress_records(
    level: int, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(level, logger="docpipe")  # restored by caplog at teardown
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


def test_retention_days_without_file_uses_default_path_under_data_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(DocpipeConfigLoader, "_config", {"audit": {"retention_days": 7}})

    _emit()

    log_file = tmp_path / "audit" / "docpipe-audit.log"
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


class _AppLogCapture(logging.Handler):
    """Collect messages that the audit module writes to the application logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def app_log() -> Generator[_AppLogCapture, None, None]:
    capture = _AppLogCapture()
    app_logger = logging.getLogger("docpipe.utils.infrastructure.audit")
    app_logger.addHandler(capture)
    yield capture
    app_logger.removeHandler(capture)


def _audit_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger(AUDIT_LOGGER_NAME).handlers if isinstance(h, _AuditStreamHandler)]


def _unwritable_file_config(*, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so it cannot be a parent directory", encoding="utf-8")
    monkeypatch.setattr(
        DocpipeConfigLoader, "_config", {"audit": {"retention_days": 30, "file": str(blocker / "sub" / "audit.log")}}
    )


def test_unwritable_audit_file_falls_back_to_stdout_and_logs_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    app_log: _AppLogCapture,
) -> None:
    _unwritable_file_config(tmp_path=tmp_path, monkeypatch=monkeypatch)

    _emit()

    assert '"outcome":"success"' in capsys.readouterr().out
    assert len(_audit_handlers()) == 1
    assert any("Audit file could not be opened" in m for m in app_log.messages)


def test_initialize_audit_logger_builds_handlers_before_the_first_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_log: _AppLogCapture
) -> None:
    _unwritable_file_config(tmp_path=tmp_path, monkeypatch=monkeypatch)

    initialize_audit_logger()

    assert len(_audit_handlers()) == 1
    assert any("Audit file could not be opened" in m for m in app_log.messages)


def test_write_failure_is_logged_and_not_raised(monkeypatch: pytest.MonkeyPatch, app_log: _AppLogCapture) -> None:
    def _fail(self: logging.Handler, record: logging.LogRecord) -> None:
        try:
            raise OSError("disk full")
        except OSError:
            self.handleError(record)

    monkeypatch.setattr(_AuditStreamHandler, "emit", _fail)

    _emit()

    assert any("Audit record could not be written (OSError)" in m for m in app_log.messages)


def test_emit_never_raises_when_logger_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, app_log: _AppLogCapture
) -> None:
    def _boom() -> logging.Logger:
        raise RuntimeError("canary-message")

    monkeypatch.setattr("docpipe.utils.infrastructure.audit.get_audit_logger", _boom)

    _emit()

    messages = " ".join(app_log.messages)
    assert "Audit record could not be written (RuntimeError)" in messages
    assert "canary-message" not in messages


def test_emit_resolution_audit_record(capsys: pytest.CaptureFixture[str]) -> None:
    from docpipe.core.models.session_info import create_session_info
    from docpipe.utils.infrastructure.audit import emit_resolution_audit_record

    # Set up session info
    create_session_info(job_id="test-job", job_run_id="test-run")

    levels: list[int] = []

    class _LevelCapture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            levels.append(record.levelno)

    get_audit_logger().addHandler(_LevelCapture())

    # Emit a resolved record
    emit_resolution_audit_record(
        node_name="node_1",
        config_key="provider_config.password",
        provider="hashicorp",
        outcome="resolved",
        correlation_id="corr-123",
    )

    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["job_id"] == "test-job"
    assert record["job_run_id"] == "test-run"
    assert record["node"] == "node_1"
    assert record["config_key"] == "provider_config.password"
    assert record["provider"] == "hashicorp"
    assert record["outcome"] == "resolved"
    assert record["correlation_id"] == "corr-123"
    assert "timestamp" in record
    assert levels == [logging.INFO]

    # Emit a policy denial record (which should go as WARNING)
    emit_resolution_audit_record(
        node_name="node_2",
        config_key="provider_config.token",
        provider="hashicorp",
        outcome="not permitted",
        correlation_id="corr-456",
    )

    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["node"] == "node_2"
    assert record["outcome"] == "not permitted"
    assert levels == [logging.INFO, logging.WARNING]


@pytest.mark.parametrize("ds_log_level", ["DEBUG", "WARNING"])
def test_ds_log_level_does_not_hide_resolution_records(
    ds_log_level: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from docpipe.core.models.session_info import create_session_info
    from docpipe.utils.infrastructure.audit import emit_resolution_audit_record

    create_session_info(job_id="test-job", job_run_id="test-run")
    monkeypatch.setenv("DS_LOG_LEVEL", ds_log_level)

    emit_resolution_audit_record(
        node_name="node_1",
        config_key="provider_config.password",
        provider="hashicorp",
        outcome="resolved",
        correlation_id="corr-123",
    )

    assert '"outcome":"resolved"' in capsys.readouterr().out


def test_emit_resolution_audit_record_never_raises(monkeypatch: pytest.MonkeyPatch, app_log: _AppLogCapture) -> None:
    from docpipe.utils.infrastructure.audit import emit_resolution_audit_record

    def _boom() -> logging.Logger:
        raise RuntimeError("canary-message")

    monkeypatch.setattr("docpipe.utils.infrastructure.audit.get_audit_logger", _boom)

    emit_resolution_audit_record(
        node_name="node_1",
        config_key="provider_config.password",
        provider="hashicorp",
        outcome="resolved",
        correlation_id="corr-123",
    )

    messages = " ".join(app_log.messages)
    assert "Audit record could not be written (RuntimeError)" in messages
    assert "canary-message" not in messages
