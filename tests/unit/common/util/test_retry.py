# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for retry helper functions and decorator behaviour."""

from unittest.mock import MagicMock, call, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowExecutionFailedException, LockTimeoutError
from docpipe.utils.infrastructure.retry import (
    _DEFAULT_ERROR_MESSAGE,
    _parse_retry_result,
    _raise_on_exhaustion,
    retry_with_exponential_backoff,
    should_retry_on_lock_timeout,
)

# ---------------------------------------------------------------------------
# _parse_retry_result
# ---------------------------------------------------------------------------


class TestParseRetryResult:
    def test_valid_tuple_returns_values(self):
        should_retry, msg = _parse_retry_result((True, "some error"))
        assert should_retry is True
        assert msg == "some error"

    def test_not_a_tuple_disables_retry(self):
        should_retry, msg = _parse_retry_result("not a tuple")
        assert should_retry is False
        assert msg == _DEFAULT_ERROR_MESSAGE

    def test_tuple_wrong_length_disables_retry(self):
        should_retry, msg = _parse_retry_result((True,))
        assert should_retry is False
        assert msg == _DEFAULT_ERROR_MESSAGE

    def test_tuple_with_non_string_message_uses_default(self):
        should_retry, msg = _parse_retry_result((True, 42))
        assert should_retry is True
        assert msg == _DEFAULT_ERROR_MESSAGE

    def test_false_retry_flag_preserved(self):
        should_retry, msg = _parse_retry_result((False, "done"))
        assert should_retry is False
        assert msg == "done"


# ---------------------------------------------------------------------------
# _raise_on_exhaustion
# ---------------------------------------------------------------------------


class TestRaiseOnExhaustion:
    def test_raises_original_exception_when_present(self):
        original = ValueError("original failure")
        with pytest.raises(ValueError, match="original failure"):
            _raise_on_exhaustion(
                max_retries=3,
                exception=original,
                error_message="unused",
            )

    def test_raises_docpipe_exception_when_no_exception(self):
        with pytest.raises(DocpipeException, match="successful call after 3 attempts: custom msg"):
            _raise_on_exhaustion(
                max_retries=3,
                exception=None,
                error_message="custom msg",
            )

    def test_docpipe_exception_uses_provided_error_message(self):
        with pytest.raises(DocpipeException) as exc_info:
            _raise_on_exhaustion(
                max_retries=5,
                exception=None,
                error_message="lock not acquired",
            )
        assert "lock not acquired" in str(exc_info.value)


# ---------------------------------------------------------------------------
# retry_with_exponential_backoff — malformed retry_logic return values
# ---------------------------------------------------------------------------


class TestRetryDecoratorMalformedRetryLogic:
    def test_non_tuple_return_disables_retries_and_raises_exception(self):
        """If retry_logic returns a non-tuple, retries are disabled; the original exception propagates."""
        calls = 0

        @retry_with_exponential_backoff(max_retries=3, initial_delay=1, retry_logic=lambda result, exception: "bad")
        def failing():
            nonlocal calls
            calls += 1
            raise RuntimeError("boom")

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="boom"):
                failing()

        # No retries — called exactly once because disabling retries means raise immediately
        assert calls == 1

    def test_non_string_message_uses_default_in_docpipe_exception(self):
        """If retry_logic returns (True, non-str), DocpipeException uses the default message."""

        @retry_with_exponential_backoff(
            max_retries=2,
            initial_delay=1,
            retry_logic=lambda result, exception: (True, 999),
        )
        def always_succeeds():
            return "ok"

        with patch("time.sleep"):
            with pytest.raises(DocpipeException) as exc_info:
                always_succeeds()

        assert _DEFAULT_ERROR_MESSAGE in str(exc_info.value)


# ---------------------------------------------------------------------------
# Integration: existing decorator scenarios (regression guard)
# ---------------------------------------------------------------------------


class TestRetryDecoratorIntegration:
    def test_retries_then_raises_on_exhaustion(self):
        call_count = 0

        def retry_on_exc(result, exception):
            return isinstance(exception, RuntimeError), "runtime failure"

        @retry_with_exponential_backoff(max_retries=3, initial_delay=1, retry_logic=retry_on_exc)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        sleep_mock = MagicMock()
        with patch("time.sleep", sleep_mock):
            with pytest.raises(RuntimeError, match="boom"):
                always_fails()

        assert call_count == 3
        assert sleep_mock.call_count == 2
        sleep_mock.assert_has_calls([call(1), call(2)])

    def test_succeeds_after_transient_failures(self):
        call_count = 0

        def retry_on_exc(result, exception):
            return isinstance(exception, RuntimeError), "runtime failure"

        @retry_with_exponential_backoff(max_retries=4, initial_delay=1, retry_logic=retry_on_exc)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("temporary")
            return "ok"

        with patch("time.sleep"):
            result = flaky()

        assert result == "ok"
        assert call_count == 3


# ---------------------------------------------------------------------------
# should_retry_on_lock_timeout
# ---------------------------------------------------------------------------


class TestShouldRetryOnLockTimeout:
    def test_lock_timeout_error_triggers_retry(self):
        exc = LockTimeoutError("Lock timeout for job_123")
        should_retry, msg = should_retry_on_lock_timeout(result=None, exception=exc)
        assert should_retry is True
        assert "Lock timeout for job_123" in msg

    def test_other_flow_execution_failure_does_not_retry(self):
        exc = FlowExecutionFailedException("Generic execution failure")
        should_retry, msg = should_retry_on_lock_timeout(result=None, exception=exc)
        assert should_retry is False
        assert msg == ""

    def test_no_exception_does_not_retry(self):
        should_retry, msg = should_retry_on_lock_timeout(result="ok", exception=None)
        assert should_retry is False
        assert msg == ""
