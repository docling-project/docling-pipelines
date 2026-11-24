# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for logging utilities.
Tests for logger configuration and formatting.
"""

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docpipe.utils.infrastructure.logging import (
    ConditionalFormatter,
    get_log_level,
    get_logger,
    setup_logging,
)


class TestGetLogLevel:
    """Test get_log_level functionality."""

    def test_get_log_level_with_none(self):
        """Test getting log level when name is None."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_log_level(None)
            assert result == logging.INFO

    def test_get_log_level_with_env_variable(self):
        """Test getting log level from environment variable."""
        with patch.dict(os.environ, {"DS_LOG_LEVEL": "DEBUG"}):
            result = get_log_level(None)
            assert result == "DEBUG"

    def test_get_log_level_with_name_parameter(self):
        """Test getting log level with name parameter."""
        result = get_log_level("debug")
        assert result == "DEBUG"

        result = get_log_level("info")
        assert result == "INFO"

        result = get_log_level("warning")
        assert result == "WARNING"

    def test_get_log_level_case_conversion(self):
        """Test that log level name is converted to uppercase."""
        test_cases = ["debug", "Debug", "DEBUG", "info", "Info", "INFO"]

        for name in test_cases:
            result = get_log_level(name)
            assert result == name.upper()


class TestGetLogger:
    """Test get_logger functionality."""

    def test_get_logger_default_parameters(self):
        """Test getting logger with default parameters."""
        logger = get_logger()

        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_get_logger_propagate_true_when_no_real_handler(self):
        """A fresh logger with only a NullHandler has propagate=True."""
        # Use a unique name to guarantee no prior state from other tests
        fresh = logging.getLogger("docpipe.test.fresh_propagate_check")
        fresh.handlers = []
        fresh.propagate = False  # reset to worst-case state

        result = get_logger("docpipe.test.fresh_propagate_check")

        assert result.propagate is True

    def test_get_logger_with_custom_name(self):
        """Test getting logger with custom name."""
        logger = get_logger(name="test_logger")

        assert logger.name == "test_logger"

    def test_get_logger_with_string_level(self):
        """Test getting logger with string log level."""
        logger = get_logger(level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_get_logger_with_int_level(self):
        """Test getting logger with integer log level."""
        logger = get_logger(level=logging.WARNING)

        assert logger.level == logging.WARNING

    def test_get_logger_with_file_output(self, tmp_path):
        """Test that get_logger ignores the file argument (file handlers belong in setup_logging)."""
        log_file = str(tmp_path / "test.log")
        logger = get_logger(name="test_file_logger_ignored", file=log_file)

        # file argument is ignored by get_logger — no FileHandler should be added
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0

    def test_get_logger_has_only_null_handler(self):
        """Test that get_logger attaches only a NullHandler (no StreamHandler)."""
        logger = get_logger(name="test_null_handler_only")

        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_setup_logging_without_json_format(self, tmp_path):
        """Test setup_logging installs a non-JSON StreamHandler by default."""
        with patch.dict(os.environ, {"DS_LOG_JSON": "False"}, clear=True):
            setup_logging()
            root = logging.getLogger("docpipe")
            stream_handlers = [
                h
                for h in root.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            ]
            assert len(stream_handlers) >= 1
            assert not isinstance(stream_handlers[0].formatter, ConditionalFormatter)

    def test_setup_logging_with_json_format(self):
        """Test setup_logging installs ConditionalFormatter when DS_LOG_JSON=True."""
        with patch.dict(os.environ, {"DS_LOG_JSON": "True"}, clear=True):
            # Reset handlers to test fresh installation
            root = logging.getLogger("docpipe")
            root.handlers = []
            setup_logging()
            stream_handlers = [
                h
                for h in root.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            ]
            assert any(isinstance(h.formatter, ConditionalFormatter) for h in stream_handlers)
            # Restore
            root.handlers = []

    def test_get_logger_does_not_duplicate_handlers(self):
        """Test that calling get_logger multiple times doesn't duplicate handlers."""
        logger_name = "test_no_duplicate"

        logger1 = get_logger(name=logger_name)
        initial_handler_count = len(logger1.handlers)

        logger2 = get_logger(name=logger_name)
        final_handler_count = len(logger2.handlers)

        # Handler count should not increase
        assert final_handler_count == initial_handler_count

    def test_get_logger_propagate_is_true(self):
        """Test that get_logger sets propagate to True for library-safe usage."""
        logger = get_logger(name="test_propagate_true")
        assert logger.propagate is True

    def test_get_logger_with_different_levels(self):
        """Test getting loggers with different log levels."""
        levels = [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ]

        for level_str, level_int in levels:
            logger = get_logger(name=f"test_{level_str}", level=level_str)
            assert logger.level == level_int

    def test_get_logger_case_insensitive_level(self):
        """Test that log level string is case-insensitive."""
        logger1 = get_logger(name="test_lower", level="debug")
        logger2 = get_logger(name="test_upper", level="DEBUG")
        logger3 = get_logger(name="test_mixed", level="Debug")

        assert logger1.level == logging.DEBUG
        assert logger2.level == logging.DEBUG
        assert logger3.level == logging.DEBUG

    def test_get_logger_with_none_level(self):
        """Test getting logger with None level uses INFO."""
        logger = get_logger(level=None)
        assert logger.level == logging.INFO


class TestSetupLoggingFileHandler:
    """Test the file handler added by setup_logging."""

    @pytest.fixture
    def clean_root(self, tmp_path, monkeypatch):
        """Empty docpipe root logger in a temp dir; restored afterwards."""
        monkeypatch.setenv("DS_LOG_JSON", "False")
        monkeypatch.chdir(tmp_path)
        root = logging.getLogger("docpipe")
        original_handlers = root.handlers[:]
        original_level = root.level
        root.handlers = []
        yield root
        for handler in root.handlers:
            handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)

    @staticmethod
    def _file_handlers(root: logging.Logger) -> list[logging.FileHandler]:
        return [h for h in root.handlers if isinstance(h, logging.FileHandler)]

    def test_file_handler_is_added_once_for_the_same_relative_path(self, clean_root):
        """Test same relative path twice gives one handler (#717)."""
        setup_logging(level="info", file="x.log")
        setup_logging(level="info", file="x.log")

        assert len(self._file_handlers(clean_root)) == 1

    def test_absolute_then_relative_path_gives_one_handler(self, clean_root, tmp_path):
        """Test absolute and relative paths to the same file share a handler."""
        setup_logging(level="info", file=str(tmp_path / "x.log"))
        setup_logging(level="info", file="x.log")

        handlers = self._file_handlers(clean_root)
        assert len(handlers) == 1
        assert Path(handlers[0].baseFilename).resolve() == (tmp_path / "x.log").resolve()

    def test_log_line_is_not_duplicated_in_file(self, clean_root, tmp_path):
        """Test each record is written to the log file only once."""
        setup_logging(level="info", file="x.log")
        setup_logging(level="info", file="x.log")

        get_logger("docpipe.test.file_once").info("hello")
        for handler in self._file_handlers(clean_root):
            handler.flush()

        assert (tmp_path / "x.log").read_text().count("hello") == 1


class TestConditionalFormatter:
    """Test ConditionalFormatter functionality."""

    @pytest.fixture
    def formatter(self):
        """Create a ConditionalFormatter instance."""
        return ConditionalFormatter(datefmt="%H:%M:%S")

    @pytest.fixture
    def mock_session_info(self):
        """Mock session info."""
        with patch("docpipe.core.models.session_info.get_session_info") as mock:
            session_info = MagicMock()
            session_info.transaction_id = "test-transaction-id"
            mock.return_value = session_info
            yield mock

    def test_formatter_basic_message(self, formatter, mock_session_info):
        """Test formatting a basic log message."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        assert "Test message" in result
        assert "test_logger" in result
        assert "INFO" in result
        assert "test-transaction-id" in result

    def test_formatter_with_debug_level(self, formatter, mock_session_info):
        """Test that DEBUG level includes file location."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.DEBUG,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Debug message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        assert "Debug message" in result
        assert "/path/to/test.py:42" in result

    def test_formatter_with_exception_info(self, formatter, mock_session_info):
        """Test formatting with exception information."""
        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

            record = logging.LogRecord(
                name="test_logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )

            result = formatter.format(record)

            assert "Error occurred" in result
            assert "exc_info" in result

    def test_formatter_with_stack_info(self, formatter, mock_session_info):
        """Test formatting with stack information."""
        import traceback

        stack_info = "".join(traceback.format_stack())

        record = logging.LogRecord(
            name="test_logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=10,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        record.stack_info = stack_info

        result = formatter.format(record)

        assert "Warning message" in result
        assert "stack_info" in result

    def test_formatter_json_output(self, formatter, mock_session_info):
        """Test that formatter produces valid JSON."""
        import json

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test_logger"
        assert parsed["logLevel"] == "INFO"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_get_logger_with_empty_name(self):
        """Test getting logger with empty name."""
        logger = get_logger(name="")
        assert logger is not None

    def test_get_logger_with_invalid_level_string(self):
        """Test getting logger with invalid level string raises ValueError."""
        # Invalid level should raise ValueError from logging.getLevelName
        with pytest.raises(ValueError, match="Unknown level"):
            get_logger(level="INVALID_LEVEL")

    def test_get_logger_multiple_calls_same_name(self):
        """Test that multiple calls with same name return same logger."""
        logger1 = get_logger(name="same_logger")
        logger2 = get_logger(name="same_logger")

        assert logger1 is logger2

    def test_formatter_with_empty_message(self):
        """Test formatting record with empty message."""
        formatter = ConditionalFormatter()

        with patch("docpipe.core.models.session_info.get_session_info") as mock:
            session_info = MagicMock()
            session_info.transaction_id = "test-id"
            mock.return_value = session_info

            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            assert result is not None

    def test_get_logger_with_very_long_name(self):
        """Test getting logger with very long name."""
        long_name = "a" * 1000
        logger = get_logger(name=long_name)
        assert logger.name == long_name

    def test_get_logger_with_unicode_name(self):
        """Test getting logger with Unicode name."""
        unicode_name = "测试日志器"
        logger = get_logger(name=unicode_name)
        assert logger.name == unicode_name


class TestEmbeddedLibraryUsage:
    """Test that docpipe behaves correctly when used as an embedded library.

    Simulates the scenario where a host application embeds docpipe and controls
    all logging output through its own infrastructure.
    """

    def test_host_handler_receives_all_docpipe_records(self):
        """A handler on the root docpipe logger receives records from all child loggers via propagation."""
        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        root = logging.getLogger("docpipe")
        handler = CapturingHandler()
        root.addHandler(handler)

        # Simulate records from two different docpipe child loggers
        get_logger("docpipe.core.operators.functional.doc_id_hash").warning("hash warning")
        get_logger("docpipe.integrations.docling.client").info("docling info")

        root.removeHandler(handler)

        assert len(captured) == 2

    def test_host_filter_on_handler_rewrites_logger_name(self):
        """A renaming Filter attached to the handler rewrites record.name for all propagated records.

        Filters must be attached to the handler, not the logger, to intercept
        records that propagate up from child loggers.
        """

        class RenamingFilter(logging.Filter):
            def filter(self, record):
                record.name = record.name.replace("docpipe", "host_app")
                return True

        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        root = logging.getLogger("docpipe")
        handler = CapturingHandler()
        handler.addFilter(RenamingFilter())
        root.addHandler(handler)

        get_logger("docpipe.core.operators.extract.extract_operator").info("extraction done")

        root.removeHandler(handler)

        assert len(captured) == 1
        assert captured[0].name == "host_app.core.operators.extract.extract_operator"

    def test_no_setup_logging_means_no_console_output(self):
        """Without setup_logging(), the root docpipe logger has no StreamHandler — only NullHandler."""
        root = logging.getLogger("docpipe")
        # setup_logging() may have been called by another test; reset to simulate clean embed
        original_handlers = root.handlers[:]
        original_propagate = root.propagate
        root.handlers = []
        root.propagate = True

        get_logger("docpipe.test.embedded_silence")
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert len(stream_handlers) == 0

        # Restore
        root.handlers = original_handlers
        root.propagate = original_propagate

    def test_propagate_true_allows_host_root_handler_to_receive_records(self):
        """With propagate=True, docpipe records reach the Python root logger's handlers."""
        root_logger = logging.getLogger()
        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        handler = CapturingHandler()
        root_logger.addHandler(handler)

        # Ensure docpipe root logger propagates and has no blocking handlers
        docpipe_root = logging.getLogger("docpipe")
        original_handlers = docpipe_root.handlers[:]
        original_propagate = docpipe_root.propagate
        docpipe_root.handlers = []
        docpipe_root.propagate = True

        get_logger("docpipe.core.operators.quality.ededup").warning("dedup warning")

        root_logger.removeHandler(handler)
        docpipe_root.handlers = original_handlers
        docpipe_root.propagate = original_propagate

        docpipe_records = [r for r in captured if r.name.startswith("docpipe")]
        assert len(docpipe_records) == 1
        assert docpipe_records[0].message == "dedup warning"


class TestConditionalFormatterTraceCorrelation:
    """Test that ConditionalFormatter injects trace_id and span_id for log-trace correlation."""

    @pytest.fixture
    def formatter(self):
        return ConditionalFormatter(datefmt="%H:%M:%S")

    @pytest.fixture
    def basic_record(self):
        return logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )

    def _format_json(self, formatter, record) -> dict:
        import json

        with patch("docpipe.core.models.session_info.get_session_info") as mock_session:
            session = MagicMock()
            session.transaction_id = "tx-1"
            mock_session.return_value = session
            return json.loads(formatter.format(record))

    def test_trace_id_and_span_id_present_in_output(self, formatter, basic_record):
        """JSON output must always contain trace_id and span_id keys."""
        parsed = self._format_json(formatter, basic_record)
        assert "trace_id" in parsed
        assert "span_id" in parsed

    def test_trace_id_and_span_id_empty_when_telemetry_disabled(self, formatter, basic_record):
        """When telemetry is disabled, both fields should be empty strings."""
        mock_telemetry = MagicMock()
        mock_telemetry.get_trace_context.return_value = {"trace_id": "", "span_id": ""}

        with patch(
            "docpipe.utils.infrastructure.telemetry_service.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            parsed = self._format_json(formatter, basic_record)

        assert parsed["trace_id"] == ""
        assert parsed["span_id"] == ""

    def test_trace_id_and_span_id_populated_when_span_active(self, formatter, basic_record):
        """When a span is active, trace_id and span_id should be hex strings."""
        mock_telemetry = MagicMock()
        mock_telemetry.get_trace_context.return_value = {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7",
        }

        with patch(
            "docpipe.utils.infrastructure.telemetry_service.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            parsed = self._format_json(formatter, basic_record)

        assert parsed["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert parsed["span_id"] == "00f067aa0ba902b7"

    def test_formatter_resilient_when_telemetry_raises(self, formatter, basic_record):
        """If get_telemetry_service raises, formatter should not propagate the error."""
        with patch(
            "docpipe.utils.infrastructure.telemetry_service.get_telemetry_service",
            side_effect=Exception("telemetry unavailable"),
        ):
            parsed = self._format_json(formatter, basic_record)

        # Keys must still be present with empty fallback
        assert parsed["trace_id"] == ""
        assert parsed["span_id"] == ""
