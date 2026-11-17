# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the scrub filter on application log handlers and its separation from ``docpipe.audit``."""

import io
import json
import logging
from collections.abc import Generator

import pytest

from docpipe.integrations.secrets import registry as registry_module
from docpipe.integrations.secrets.registry import MASK, SCRUB_FAILURE_PLACEHOLDER, get_registry, register_secret
from docpipe.utils.infrastructure.audit import (
    AuditAction,
    AuditOutcome,
    _is_audit_handler,
    emit_audit_record,
    get_audit_logger,
    reset_audit_logger,
)
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import (
    AUDIT_LOGGER_NAME,
    ConditionalFormatter,
    ScrubFilter,
    configure_third_party_loggers,
    install_scrub_filter,
)

# pragma: allowlist nextline secret
PASSWORD = "hunter2/with space&x"
RUN = "run-log"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    get_registry().clear_all()
    monkeypatch.setattr(DocpipeConfigLoader, "_config", {})
    reset_audit_logger()
    yield
    get_registry().clear_all()
    reset_audit_logger()
    DocpipeConfigLoader.reset()


@pytest.fixture
def app_logger() -> Generator[tuple[logging.Logger, io.StringIO], None, None]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    install_scrub_filter(handler=handler)
    logger = logging.getLogger("docpipe.test_scrub_filter")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, stream
    logger.handlers = []


class TestScrubFilterOnHandlers:
    def test_forgotten_debug_log_with_a_password_is_scrubbed(self, app_logger) -> None:
        logger, stream = app_logger
        register_secret(value=PASSWORD, run_id=RUN)
        logger.debug("connecting with password %s", PASSWORD)
        assert PASSWORD not in stream.getvalue()
        assert f"password {MASK}" in stream.getvalue()

    def test_every_level_is_scrubbed(self, app_logger) -> None:
        logger, stream = app_logger
        register_secret(value=PASSWORD, run_id=RUN)
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
            logger.log(level, "value=%s", PASSWORD)
        assert PASSWORD not in stream.getvalue()
        assert stream.getvalue().count(MASK) == 5

    def test_percent_encoded_form_is_scrubbed(self, app_logger) -> None:
        from urllib.parse import quote

        logger, stream = app_logger
        register_secret(value=PASSWORD, run_id=RUN)
        logger.info("GET /x?p=%s", quote(PASSWORD))
        assert quote(PASSWORD) not in stream.getvalue()

    def test_secret_in_a_traceback_is_scrubbed(self, app_logger) -> None:
        logger, stream = app_logger
        register_secret(value=PASSWORD, run_id=RUN)
        try:
            raise ValueError(f"bad credential {PASSWORD}")
        except ValueError:
            logger.exception("failed")
        assert PASSWORD not in stream.getvalue()
        assert "ValueError" in stream.getvalue()

    def test_secret_in_stack_info_is_scrubbed(self, app_logger) -> None:
        logger, stream = app_logger
        register_secret(value="stack-secret", run_id=RUN)
        record = logger.makeRecord("n", logging.ERROR, "f", 1, "m", None, None, sinfo="frame stack-secret")
        for handler in logger.handlers:
            handler.handle(record)
        assert "stack-secret" not in stream.getvalue()

    def test_child_logger_records_reach_the_filter(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        install_scrub_filter(handler=handler)
        parent = logging.getLogger("docpipe.test_scrub_parent")
        parent.handlers = [handler]
        parent.propagate = False
        parent.setLevel(logging.DEBUG)
        register_secret(value=PASSWORD, run_id=RUN)
        logging.getLogger("docpipe.test_scrub_parent.child.deep").warning("pw=%s", PASSWORD)
        parent.handlers = []
        assert PASSWORD not in stream.getvalue()

    def test_json_formatter_output_is_scrubbed(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ConditionalFormatter())
        install_scrub_filter(handler=handler)
        logger = logging.getLogger("docpipe.test_scrub_json")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        register_secret(value=PASSWORD, run_id=RUN)
        try:
            raise ValueError(PASSWORD)
        except ValueError:
            logger.debug("pw=%s", PASSWORD, exc_info=True)
        logger.handlers = []
        output = stream.getvalue()
        assert PASSWORD not in output
        assert MASK in output

    def test_record_is_never_dropped(self, app_logger) -> None:
        logger, stream = app_logger
        logger.info("no secrets registered")
        assert "no secrets registered" in stream.getvalue()

    def test_install_is_idempotent(self) -> None:
        handler = logging.StreamHandler(io.StringIO())
        install_scrub_filter(handler=handler)
        install_scrub_filter(handler=handler)
        assert sum(isinstance(f, ScrubFilter) for f in handler.filters) == 1

    def test_third_party_handler_gets_the_filter(self) -> None:
        handler = logging.StreamHandler(io.StringIO())
        configure_third_party_loggers(log_level=logging.INFO, handler=handler)
        assert any(isinstance(f, ScrubFilter) for f in handler.filters)


class TestScrubberFailure:
    def test_failure_emits_the_placeholder_not_the_message(self, app_logger, monkeypatch) -> None:
        logger, stream = app_logger
        register_secret(value=PASSWORD, run_id=RUN)

        def boom(text: str) -> str:
            raise RuntimeError("scrubber broke")

        monkeypatch.setattr(registry_module, "scrub", boom)
        logger.info("leaks %s", PASSWORD)
        assert PASSWORD not in stream.getvalue()
        assert SCRUB_FAILURE_PLACEHOLDER in stream.getvalue()


class TestAuditSeparation:
    def test_scrub_filter_cannot_be_attached_to_an_audit_handler(self) -> None:
        handlers = [h for h in get_audit_logger().handlers if _is_audit_handler(h)]
        assert handlers
        for handler in handlers:
            install_scrub_filter(handler=handler)
            assert not any(isinstance(f, ScrubFilter) for f in handler.filters)

    def test_audit_logger_does_not_propagate_to_application_handlers(self) -> None:
        assert get_audit_logger().propagate is False

    def test_a_scrub_filter_cannot_drop_or_alter_an_audit_record(self, capsys: pytest.CaptureFixture[str]) -> None:
        register_secret(value="ab", run_id=RUN)
        audit = get_audit_logger()
        for handler in audit.handlers:
            handler.addFilter(ScrubFilter())
        audit.addFilter(ScrubFilter())
        emit_audit_record(
            caller="abby",
            action=AuditAction.CREATE,
            outcome=AuditOutcome.SUCCESS,
            operator_id="id-1",
            short_name="op",
            script_sha256="cd" * 32,
        )
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["caller"] == "abby"
        assert MASK not in lines[0]

    def test_filter_leaves_records_of_the_audit_logger_untouched(self) -> None:
        register_secret(value="ab", run_id=RUN)
        record = logging.LogRecord(AUDIT_LOGGER_NAME, logging.INFO, "f", 1, "caller abby", None, None)
        assert ScrubFilter().filter(record) is True
        assert record.msg == "caller abby"
