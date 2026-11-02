# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Logging infrastructure with structured JSON formatting and transaction tracking.

This module provides:
- ConditionalFormatter: JSON formatter with transaction ID injection
- setup_logging: Configures handlers and formatters for process-owning entry points
- get_logger: Library-safe factory that attaches only a NullHandler
- get_log_level: Utility for resolving log levels from environment
"""

import json
import logging
import os
import sys
from typing import ClassVar

from docpipe.core.constants.constants import DocpipeConstants, EnvironmentVariables


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    # Log level colors
    DEBUG = "\033[36m"  # Cyan
    INFO = "\033[32m"  # Green
    WARNING = "\033[33m"  # Yellow
    ERROR = "\033[31m"  # Red
    CRITICAL = "\033[35m"  # Magenta

    # Component colors
    TIME = "\033[90m"  # Gray
    NAME = "\033[94m"  # Blue


HEALTH_API_SUFFIX = "/health"


class ColoredFormatter(logging.Formatter):
    """Formatter that adds color coding to log messages when output is a TTY.
    This formatter automatically detects whether output is going to a terminal (TTY)
    or being redirected to a file/pipe. Colors are only applied when:
    1. Output stream is a TTY (terminal)
    2. NO_COLOR environment variable is not set
    3. FORCE_COLOR environment variable is not explicitly disabled
    When output is redirected to a file or NO_COLOR is set, plain text formatting
    is used without ANSI escape sequences.
    """

    LEVEL_COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: Colors.DEBUG,
        logging.INFO: Colors.INFO,
        logging.WARNING: Colors.WARNING,
        logging.ERROR: Colors.ERROR,
        logging.CRITICAL: Colors.CRITICAL,
    }

    def __init__(self, *args, **kwargs):
        """Initialize formatter and determine if colors should be enabled.
        Colors are enabled when:
        - FORCE_COLOR=1/true/yes is set, OR
        - Output is a TTY AND NO_COLOR is not set
        """
        super().__init__(*args, **kwargs)
        self._colors_enabled = self._should_use_colors()

    def _should_use_colors(self) -> bool:
        """Determine if ANSI colors should be used based on environment and TTY status.
        Returns:
            True if colors should be used, False otherwise
        """
        # Check FORCE_COLOR environment variable
        force_color = os.getenv("FORCE_COLOR", "").lower()
        if force_color in ("1", "true", "yes"):
            return True

        # Check NO_COLOR environment variable (standard: https://no-color.org/)
        if os.getenv("NO_COLOR", ""):
            return False

        # Check if stdout is a TTY (terminal)
        # When output is redirected to file/pipe, isatty() returns False
        return sys.stdout.isatty()

    def format(self, record):
        # Format the message using parent formatter to populate record.asctime
        super().format(record)

        # Extract components directly from LogRecord attributes
        # The parent format() call populates record.asctime
        time_str = getattr(record, "asctime", "")
        name_str = record.name
        level_str = record.levelname
        msg_str = record.getMessage()

        # Use colors only if enabled (TTY output and not disabled by env vars)
        if self._colors_enabled:
            # Get the color for this log level
            level_color = self.LEVEL_COLORS.get(record.levelno, Colors.RESET)

            # Construct colored message using LogRecord attributes
            return (
                f"{Colors.TIME}{time_str}{Colors.RESET} - "
                f"{Colors.NAME}{name_str}{Colors.RESET} - "
                f"{level_color}{Colors.BOLD}{level_str}{Colors.RESET} - "
                f"{msg_str}"
            )
        # Plain text format without ANSI codes for file output
        return f"{time_str} - {name_str} - {level_str} - {msg_str}"


class ConditionalFormatter(logging.Formatter):
    """Logging formatter with conditional field inclusion and transaction tracking.

    This formatter provides structured JSON logging with:
    - Automatic transaction ID injection from session_info context
    - Conditional field inclusion (job_id, job_run_id, track_perf)
    - Enhanced debug logging with file location information
    - Pretty-printed exceptions and stack traces for readability

    Transaction ID Flow:
    1. TransactionMiddleware extracts/generates X-Global-Transaction-Id from request headers
    2. Middleware stores it in request.state.transaction_id
    3. Middleware populates session_info context via create_session_info(transaction_id=...)
    4. ConditionalFormatter retrieves transaction_id from session_info context

    Fallback Behavior:
    If session_info is not available or not populated (e.g., CLI operations),
    the formatter uses a default transaction ID to maintain consistent log structure.
    """

    fields_to_be_included: ClassVar[list[str]] = [
        DocpipeConstants.JOB_ID,
        DocpipeConstants.JOB_RUN_ID,
        DocpipeConstants.TRACK_PERF,
    ]

    def _get_transaction_id(self) -> str:
        """Get transaction ID from session_info context.

        Retrieves the transaction ID from session_info context, which should be
        populated by TransactionMiddleware via create_session_info(transaction_id=...).
        This ensures all logs within a request include the same transaction ID for
        distributed tracing.

        Returns:
            Transaction ID string from session_info, or default value if not available
            (e.g., during CLI operations or when session_info is not initialized)
        """
        # Get transaction ID from session_info (set by TransactionMiddleware)
        try:
            from docpipe.core.models.session_info import get_session_info

            session_info = get_session_info()
            if session_info and session_info.transaction_id:
                return session_info.transaction_id
        except Exception:  # nosec B110 — intentional: session info lookup is best-effort in non-API contexts; fallback to default transaction ID below
            pass

        # Fallback to default for non-API contexts (CLI, background jobs, etc.)
        return DocpipeConstants.DEFAULT_TRANSACTION_ID

    def _get_trace_context(self) -> dict[str, str]:
        """Get trace_id and span_id from the active OTEL span, if any.

        Returns:
            Dict with 'trace_id' and 'span_id' strings, or empty strings when
            telemetry is disabled or there is no active span.
        """
        try:
            from docpipe.utils.infrastructure.telemetry_service import get_telemetry_service

            return get_telemetry_service().get_trace_context()
        except Exception:  # nosec B110 — intentional: telemetry is optional; any failure returns empty trace context so logging always succeeds
            return {"trace_id": "", "span_id": ""}

    def format(self, record):
        """Format log record as JSON with transaction ID, trace context, and conditional fields.

        Args:
            record: LogRecord instance to format

        Returns:
            JSON string with structured log data, pretty-printed if exceptions present
        """
        # Get transaction ID with fallback support
        transaction_id = self._get_transaction_id()

        # Get trace context for log-trace correlation
        trace_context = self._get_trace_context()

        # Add transaction_id to the record for potential use by other handlers
        record.transaction_id = transaction_id

        log_dict = {
            "time": self.formatTime(record, self.datefmt),
            "logger": record.name,
            "logLevel": record.levelname,
            "transaction_ID": transaction_id,
            "trace_id": trace_context["trace_id"],
            "span_id": trace_context["span_id"],
            "message": record.getMessage() if record.getMessage() else record.msg,
            "saveServiceCopy": "false",
            "appname": "docling-pipelines-api",
        }

        # Include exc_info if it is present.
        if record.exc_info:
            log_dict.update({"exc_info": self.formatException(record.exc_info)})

        # Include stack_info if it is present.
        if record.stack_info:
            log_dict.update({"stack_info": record.stack_info})

        # check for optional field if present in the record dictionary then include in the log dictionary.
        for field in ConditionalFormatter.fields_to_be_included:
            if field in record.__dict__ and record.__dict__.get(field) is not None:
                log_dict.update({field: record.__dict__.get(field)})

        # if record level is debug then update the message.
        if record.levelno == logging.DEBUG:
            log_dict["message"] = f"{record.getMessage()} at {record.pathname}:{record.lineno}"

        # The below changes are specific for Local Environment.
        if "exc_info" in log_dict:
            log_dict["exc_info"] = log_dict["exc_info"].splitlines()
        if "stack_info" in log_dict:
            log_dict["stack_info"] = log_dict["stack_info"].splitlines()

        # if the record has exc_info or stack_info then indent the message so that the stack_info visible on console is in formatted option.
        if any(key in log_dict for key in ["exc_info", "stack_info"]):
            return json.dumps(log_dict, indent=2)

        return json.dumps(log_dict)


def get_log_level(name: str | None = None):
    """Resolve log level from name or environment variable.

    Args:
        name: Log level name (e.g., "INFO", "DEBUG"). If None, reads from DS_LOG_LEVEL env var.

    Returns:
        Log level name string (uppercase)
    """
    if name is None:
        level_name = os.environ.get(EnvironmentVariables.DS_LOG_LEVEL, logging.INFO)
    else:
        level_name = name.upper()
    return level_name


def configure_third_party_loggers(*, log_level: int | str, handler: logging.Handler) -> None:
    """Configure third-party library loggers to respect application log level from env variable.

    Many third-party libraries (uvicorn, prefect, httpx, etc.) set their own log levels
    explicitly, ignoring the root logger configuration. This function ensures they all
    respect the application's DS_LOG_LEVEL setting.

    Args:
        log_level: The log level to apply (int like logging.INFO or str like "INFO")
        handler: The logging handler to use for output
    """
    third_party_loggers = [
        # Uvicorn web server loggers
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        # Prefect workflow orchestration loggers
        "prefect",
        "prefect.flow_runs",
        "prefect.task_runs",
        "prefect.engine",
        "prefect.client",
        "prefect.server",
        # HTTP client loggers
        "httpx",
        "httpcore",
        "urllib3",
        "requests",
        # Other third-party loggers
        "filelock",
        "websockets",
        "graphviz",
        "huggingface_hub",
    ]

    for logger_name in third_party_loggers:
        lib_logger = logging.getLogger(logger_name)
        lib_logger.setLevel(log_level)
        lib_logger.handlers = []
        lib_logger.addHandler(handler)
        lib_logger.propagate = False


def set_dpk_log_level_from_ds_log_level() -> None:
    """Configure DPK (data_processing library) log level to match DS_LOG_LEVEL.

    The data_processing library uses its own logging system that reads from the
    DPK_LOG_LEVEL environment variable instead of respecting Python's logging
    configuration. This function synchronizes DPK's log level with the application's
    DS_LOG_LEVEL setting.

    This function should be called early in the application startup, before any
    data_processing library code is imported, in all entry points:
    - FastAPI server (main.py)
    - CLI (docpipe_cli.py)
    - Programmatic API (DocpipeFlowManager)
    """
    log_level_name = os.getenv(EnvironmentVariables.DS_LOG_LEVEL, "INFO").upper()
    os.environ[EnvironmentVariables.DPK_LOG_LEVEL] = log_level_name


def setup_logging(
    level: int | str | None = None,
    file: str | None = None,
) -> None:
    """Configure handlers and formatters on the root docpipe logger.

    Must be called only from process-owning entry points (e.g. the CLI or
    standalone programmatic usage). Embedders that control their own logging
    infrastructure should not call this.

    Args:
        level: Log level string or int. Defaults to DS_LOG_LEVEL env var or INFO.
        file: Optional file path to also write logs to.
    """
    root = logging.getLogger(DocpipeConstants.LOGGER_NAME)

    # Resolve level
    if isinstance(level, int):
        resolved_level = level
    else:
        level_name = level.upper() if isinstance(level, str) else get_log_level()
        resolved_level = logging.getLevelName(level_name)

    root.setLevel(resolved_level)

    use_json_format: bool = os.environ.get("DS_LOG_JSON", "False") == "True"
    timefmt = "%H:%M:%S"

    # Console handler — add only once
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        if use_json_format:
            console_handler.setFormatter(ConditionalFormatter(datefmt=timefmt))
        else:
            console_handler.setFormatter(
                ColoredFormatter(
                    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    datefmt=timefmt,
                )
            )
        root.addHandler(console_handler)

    # Optional file handler — add only once per path
    if file:
        existing_paths = {h.baseFilename for h in root.handlers if isinstance(h, logging.FileHandler)}
        if file not in existing_paths:
            file_handler = logging.FileHandler(file)
            if use_json_format:
                file_handler.setFormatter(ConditionalFormatter(datefmt=timefmt))
            else:
                file_handler.setFormatter(
                    logging.Formatter(
                        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                        datefmt=timefmt,
                    )
                )
            root.addHandler(file_handler)

    # Stop propagation to root — the entry point owns its output
    root.propagate = False


def get_logger(
    name: str = DocpipeConstants.LOGGER_NAME,
    level: int | str | None = None,
    file: str | None = None,
) -> logging.Logger:
    """Return a library-safe logger for the given name.

    Attaches a NullHandler if no handlers are present and enables propagation
    so that host applications can control all output via their own logging
    configuration. When setup_logging() has already been called (e.g. from
    the CLI), the existing handler configuration on the root docpipe logger
    is preserved and the NullHandler is not duplicated.

    Args:
        name: Logger name. Defaults to DocpipeConstants.LOGGER_NAME ("docpipe").
        level: Log level string or int (e.g., "INFO" or logging.INFO).
               When omitted, defaults to DS_LOG_LEVEL env var or INFO.
        file: Kept for backward compatibility. Ignored — attach file handlers
              at the entry-point level via setup_logging().

    Returns:
        logging.Logger
    """
    logger = logging.getLogger(name)

    # Set level when explicitly requested; otherwise apply default only if unset
    if level is not None:
        if isinstance(level, int):
            logger.setLevel(level)
        else:
            logger.setLevel(logging.getLevelName(level.upper()))
    elif not logger.level:
        logger.setLevel(logging.getLevelName(get_log_level()))

    # Attach NullHandler once to suppress "No handlers found" warnings when
    # no entry-point has called setup_logging() yet.
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    # Only enable propagation when setup_logging() has not yet installed real
    # handlers — avoids double-emission when the entry point owns the output.
    has_real_handler = any(not isinstance(h, logging.NullHandler) for h in logger.handlers)
    if not has_real_handler:
        logger.propagate = True

    return logger
