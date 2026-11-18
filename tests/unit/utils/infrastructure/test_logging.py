# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the colored and JSON formatters and the file handling of setup_logging."""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants, EnvironmentVariables
from docpipe.utils.infrastructure.logging import (
    ColoredFormatter,
    Colors,
    ConditionalFormatter,
    ScrubFilter,
    set_dpk_log_level_from_ds_log_level,
    setup_logging,
)


def _record(*, level=logging.INFO, msg="hello %s", args=("world",), **extra):
    """Build a LogRecord on the docpipe logger with optional extra attributes."""
    record = logging.LogRecord(DocpipeConstants.LOGGER_NAME, level, __file__, 10, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.fixture
def docpipe_root():
    """Yield the docpipe root logger and restore its handlers, level and propagation afterwards."""
    root = logging.getLogger(DocpipeConstants.LOGGER_NAME)
    saved = (list(root.handlers), root.level, root.propagate)
    root.handlers = []
    try:
        yield root
    finally:
        for handler in root.handlers:
            if handler not in saved[0]:
                handler.close()
        root.handlers, root.level, root.propagate = saved


class TestColoredFormatter:
    """ColoredFormatter decides on ANSI colors from the environment and the TTY state."""

    @pytest.mark.parametrize("value", ["1", "true", "YES"])
    def test_force_color_enables_colors_even_without_tty(self, monkeypatch, value):
        """FORCE_COLOR wins over NO_COLOR and a non-TTY stdout."""
        monkeypatch.setenv("FORCE_COLOR", value)
        monkeypatch.setenv("NO_COLOR", "1")
        with patch.object(sys.stdout, "isatty", return_value=False, create=True):
            assert ColoredFormatter()._colors_enabled is True

    def test_no_color_disables_colors_on_a_tty(self, monkeypatch):
        """NO_COLOR disables colors when FORCE_COLOR is not set."""
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setenv("NO_COLOR", "1")
        with patch.object(sys.stdout, "isatty", return_value=True, create=True):
            assert ColoredFormatter()._colors_enabled is False

    @pytest.mark.parametrize("is_tty", [True, False])
    def test_tty_state_decides_without_env_overrides(self, monkeypatch, is_tty):
        """Without FORCE_COLOR/NO_COLOR, colors follow sys.stdout.isatty()."""
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch.object(sys.stdout, "isatty", return_value=is_tty, create=True):
            assert ColoredFormatter()._colors_enabled is is_tty

    def test_colored_output_wraps_each_component(self, monkeypatch):
        """With colors enabled, time, name and level carry their ANSI codes."""
        monkeypatch.setenv("FORCE_COLOR", "1")
        formatter = ColoredFormatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M")

        output = formatter.format(_record(level=logging.WARNING))

        assert f"{Colors.NAME}{DocpipeConstants.LOGGER_NAME}{Colors.RESET}" in output
        assert f"{Colors.WARNING}{Colors.BOLD}WARNING{Colors.RESET}" in output
        assert output.startswith(Colors.TIME)
        assert output.endswith(" - hello world")

    def test_plain_output_has_no_ansi_codes(self, monkeypatch):
        """With colors disabled the output is plain text."""
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setenv("NO_COLOR", "1")

        output = ColoredFormatter(datefmt="%H:%M").format(_record())

        assert "\033[" not in output
        assert output.endswith(f" - {DocpipeConstants.LOGGER_NAME} - INFO - hello world")


class TestConditionalFormatterTransactionId:
    """The JSON formatter takes the transaction id from session info, with a default fallback."""

    @pytest.fixture
    def formatter(self):
        """Return a formatter with telemetry trace lookup stubbed out."""
        formatter = ConditionalFormatter(datefmt="%H:%M:%S")
        with patch.object(ConditionalFormatter, "_get_trace_context", return_value={"trace_id": "", "span_id": ""}):
            yield formatter

    @pytest.mark.parametrize("session_info", [None, MagicMock(transaction_id="")])
    def test_missing_session_or_transaction_id_uses_default(self, formatter, session_info):
        """No session info, or one without a transaction id, yields the default id."""
        with patch("docpipe.core.models.session_info.get_session_info", return_value=session_info):
            payload = json.loads(formatter.format(_record()))

        assert payload["transaction_ID"] == DocpipeConstants.DEFAULT_TRANSACTION_ID

    def test_session_lookup_failure_uses_default(self, formatter):
        """An error while reading session info does not break logging."""
        with patch("docpipe.core.models.session_info.get_session_info", side_effect=RuntimeError("no context")):
            record = _record()
            payload = json.loads(formatter.format(record))

        assert payload["transaction_ID"] == DocpipeConstants.DEFAULT_TRANSACTION_ID
        assert record.transaction_id == DocpipeConstants.DEFAULT_TRANSACTION_ID

    def test_optional_fields_are_included_only_when_set(self, formatter):
        """job_id and job_run_id appear when present on the record; None values are left out."""
        record = _record(**{DocpipeConstants.JOB_ID: "job-1", DocpipeConstants.JOB_RUN_ID: None})
        with patch("docpipe.core.models.session_info.get_session_info", return_value=None):
            payload = json.loads(formatter.format(record))

        assert payload[DocpipeConstants.JOB_ID] == "job-1"
        assert DocpipeConstants.JOB_RUN_ID not in payload
        assert DocpipeConstants.TRACK_PERF not in payload


class TestSetupLogging:
    """setup_logging installs console and file handlers on the docpipe root logger."""

    def test_integer_level_is_used_as_is(self, docpipe_root, monkeypatch):
        """An int level is applied directly and propagation is turned off."""
        monkeypatch.setenv("DS_LOG_JSON", "False")

        setup_logging(level=logging.WARNING)

        assert docpipe_root.level == logging.WARNING
        assert docpipe_root.propagate is False

    def test_plain_file_handler_is_added_once_per_path(self, docpipe_root, monkeypatch, tmp_path):
        """A file handler with the plain formatter is added once, and every handler gets the scrub filter."""
        monkeypatch.setenv("DS_LOG_JSON", "False")
        log_file = str(tmp_path / "docpipe.log")

        setup_logging(level="info", file=log_file)
        setup_logging(level="info", file=log_file)

        file_handlers = [h for h in docpipe_root.handlers if isinstance(h, logging.FileHandler)]
        assert [h.baseFilename for h in file_handlers] == [log_file]
        formatter = file_handlers[0].formatter
        assert type(formatter) is logging.Formatter
        assert formatter._fmt == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        assert all(any(isinstance(f, ScrubFilter) for f in h.filters) for h in docpipe_root.handlers)

    def test_json_file_handler_uses_conditional_formatter(self, docpipe_root, monkeypatch, tmp_path):
        """With DS_LOG_JSON=True the file handler writes JSON."""
        monkeypatch.setenv("DS_LOG_JSON", "True")

        setup_logging(level="DEBUG", file=str(tmp_path / "docpipe.json.log"))

        file_handlers = [h for h in docpipe_root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        assert isinstance(file_handlers[0].formatter, ConditionalFormatter)


def test_dpk_log_level_follows_ds_log_level(monkeypatch):
    """DPK_LOG_LEVEL is set to the upper-cased DS_LOG_LEVEL."""
    monkeypatch.setenv(EnvironmentVariables.DS_LOG_LEVEL, "debug")
    monkeypatch.setenv(EnvironmentVariables.DPK_LOG_LEVEL, "INFO")  # restored after the test

    set_dpk_log_level_from_ds_log_level()

    assert os.environ[EnvironmentVariables.DPK_LOG_LEVEL] == "DEBUG"
