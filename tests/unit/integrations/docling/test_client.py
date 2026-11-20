# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the docling-serve client: option building, errors, polling and retries.

Complements ``tests/unit/common/clients/test_docling_serve_client.py``. All HTTP goes
through an in-process fake of :class:`RestClient`; time and sleeping are faked, so no
test waits for real.
"""

from collections import deque
from types import SimpleNamespace
from typing import Any

import pytest

from docpipe.core.constants.constants import DoclingClientConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations import base_llm_client
from docpipe.integrations.docling import client as client_module
from docpipe.integrations.docling.client import DoclingServeClient, DoclingServeErrorHandler

BASE_URL = "http://docling-serve.test:5001"


class _FakeRestClient:
    """In-process stand-in for the REST transport: replays queued answers, records calls."""

    def __init__(self) -> None:
        self.json_answers: deque[Any] = deque()
        self.multipart_answers: deque[Any] = deque()
        self.json_calls: list[dict[str, Any]] = []
        self.multipart_calls: list[dict[str, Any]] = []

    @staticmethod
    def _answer(queue: deque[Any]) -> Any:
        answer = queue.popleft()
        if isinstance(answer, Exception):
            raise answer
        return answer

    def call_rest_json(self, **kwargs: Any) -> Any:
        self.json_calls.append(kwargs)
        return self._answer(self.json_answers)

    def call_rest_multipart(self, **kwargs: Any) -> Any:
        self.multipart_calls.append(kwargs)
        return self._answer(self.multipart_answers)


class _FakeClock:
    """Replacement for the ``time`` module used by the client: sleeping advances the clock."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    """Fake clock for the polling loop and no-op sleeps for the retry decorator."""
    fake = _FakeClock()
    monkeypatch.setattr(client_module, "time", fake)
    retry_sleeps: list[float] = []
    monkeypatch.setattr(base_llm_client, "time", SimpleNamespace(sleep=retry_sleeps.append))
    fake.retry_sleeps = retry_sleeps  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def rest():
    """The fake transport, installed by :func:`make_client`."""
    return _FakeRestClient()


@pytest.fixture
def make_client(rest):
    """Build a client whose transport is the in-process fake."""

    def _make(**kwargs: Any) -> DoclingServeClient:
        client = DoclingServeClient(base_url=BASE_URL, **kwargs)
        client.rest_client = rest  # type: ignore[assignment]
        return client

    return _make


def _error(*, status: int, message: str = "boom", code: ErrorCode = ErrorCode.EXTERNAL_SERVICE_ERROR):
    return DocpipeException(message=message, status_code=status, error_code=code)


class TestErrorHandler:
    """Classification and enhancement of docling-serve errors."""

    def test_422_is_reported_as_format_incompatibility(self):
        """A 422 response gets an actionable message naming the instance and formats."""
        original = _error(status=422, message="Unprocessable Entity")
        enhanced = DoclingServeErrorHandler(base_url=BASE_URL).handle(
            original, {"requested_formats": ["md", "doctags"]}
        )

        assert enhanced is not original
        assert enhanced.status_code == 422
        assert enhanced.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR
        assert BASE_URL in str(enhanced)
        assert "['md', 'doctags']" in str(enhanced)
        assert "Original error: Unprocessable Entity" in str(enhanced)

    @pytest.mark.parametrize("message", ["Unsupported output", "to_formats invalid", "Format X NOT SUPPORTED"])
    def test_format_wording_is_reported_as_format_incompatibility(self, message):
        """Format-related wording is recognised regardless of status code and case."""
        enhanced = DoclingServeErrorHandler(base_url=BASE_URL).handle(_error(status=400, message=message))
        assert "rejected the requested output formats" in str(enhanced)
        assert "[]" in str(enhanced)

    def test_unrelated_errors_are_returned_unchanged(self):
        """Errors no handler recognises are passed through as the same object."""
        original = _error(status=503, message="Service Unavailable")
        assert DoclingServeErrorHandler(base_url=BASE_URL).handle(original) is original

    def test_registered_handlers_are_consulted_in_order(self):
        """Custom handlers run after the defaults; the first match wins."""
        handler = DoclingServeErrorHandler(base_url=BASE_URL)
        replacement = _error(status=429, message="slow down")
        seen: list[str] = []

        def _matches(exc: DocpipeException) -> bool:
            seen.append(str(exc))
            return exc.status_code == 429

        handler.register(_matches, lambda exc, ctx: replacement)
        handler.register(lambda exc: True, lambda exc, ctx: pytest.fail("later handler must not run"))

        assert handler.handle(_error(status=429, message="Too Many Requests")) is replacement
        assert seen == ["Too Many Requests"]


class TestBuildOptions:
    """Defaults and output-format merging of the submission options."""

    def test_additional_formats_are_appended_once(self):
        """Extra formats follow ``md``; duplicates and empty entries are skipped."""
        client = DoclingServeClient(base_url=BASE_URL)
        options = {"additional_formats": ["json", "md", "", "json", "doctags"], "do_ocr": False}

        built = client._build_options(options)

        assert built["to_formats"] == ["md", "json", "doctags"]
        assert built["do_ocr"] is False
        assert "additional_formats" not in built
        assert options["additional_formats"] == ["json", "md", "", "json", "doctags"]

    def test_explicit_to_formats_always_include_md(self):
        """An explicit ``to_formats`` override gets ``md`` prepended when absent."""
        built = DoclingServeClient(base_url=BASE_URL)._build_options({"to_formats": ["json"]})
        assert built["to_formats"] == ["md", "json"]

    def test_explicit_to_formats_with_md_are_kept_as_given(self):
        """An override that already contains ``md`` is used in the given order."""
        built = DoclingServeClient(base_url=BASE_URL)._build_options({"to_formats": ["json", "md"]})
        assert built["to_formats"] == ["json", "md"]

    def test_none_values_are_dropped(self):
        """``None`` options are stripped instead of being sent as the string ``"None"``."""
        built = DoclingServeClient(base_url=BASE_URL)._build_options({"ocr_engine": None, "pdf_backend": None})
        assert "ocr_engine" not in built
        assert "pdf_backend" not in built
        assert built["do_ocr"] is True


class TestSubmit:
    """Document submission."""

    def test_missing_file_is_rejected_before_any_request(self, make_client, rest, tmp_path):
        """A non-existent path raises FileNotFoundError and sends nothing."""
        client = make_client()
        with pytest.raises(FileNotFoundError, match=r"missing\.pdf"):
            client.submit_document(file_path=str(tmp_path / "missing.pdf"))
        assert rest.multipart_calls == []

    def test_file_is_uploaded_with_its_name_type_and_api_key(self, make_client, rest, tmp_path):
        """A file on disk is sent with its name, MIME type, options and the API key header."""
        source = tmp_path / "report.PDF"
        source.write_bytes(b"%PDF-1.7")
        rest.multipart_answers.append({"task_id": "t-1"})
        client = make_client(api_key="key-123")  # pragma: allowlist secret

        assert client.submit_document(file_path=str(source), options={"additional_formats": ["json"]}) == "t-1"

        (call,) = rest.multipart_calls
        assert call["url"] == "/v1/convert/file/async"
        assert call["files"] == {"files": ("report.PDF", b"%PDF-1.7", "application/pdf")}
        assert call["form_data"]["to_formats"] == ["md", "json"]
        assert call["headers"] == {"X-API-KEY": "key-123"}  # pragma: allowlist secret

    def test_empty_filename_is_sent_as_octet_stream(self, make_client, rest):
        """Without a filename the content is sent with the generic binary MIME type."""
        rest.multipart_answers.append({"task_id": "t-2"})
        assert make_client()._submit_request_multipart(endpoint="/e", file_content=b"x", filename="") == "t-2"
        assert rest.multipart_calls[0]["files"]["files"] == ("", b"x", "application/octet-stream")

    @pytest.mark.parametrize("response", [{}, {"task_id": ""}, {"task_id": None}])
    def test_response_without_task_id_is_an_error(self, make_client, rest, response):
        """A submission answer without a task id fails instead of returning a bogus id."""
        rest.multipart_answers.append(response)
        with pytest.raises(DocpipeException, match="No task_id in response") as excinfo:
            make_client().submit_document(binary_content=b"x", filename="a.pdf")
        assert excinfo.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_format_rejection_is_enhanced_with_requested_formats(self, make_client, rest):
        """A 422 from the server is re-raised with the formats that were requested, chained."""
        original = _error(status=422, message="Unprocessable Entity")
        rest.multipart_answers.append(original)

        with pytest.raises(DocpipeException, match="rejected the requested output formats") as excinfo:
            make_client().submit_document(
                binary_content=b"x", filename="a.pdf", options={"additional_formats": ["doctags"]}
            )

        assert "['md', 'doctags']" in str(excinfo.value)
        assert excinfo.value.__cause__ is original


class TestPolling:
    """Status polling until a terminal state."""

    def test_pending_then_success_polls_with_interval(self, make_client, rest, clock):
        """Non-terminal statuses are polled again after the configured interval."""
        rest.json_answers.extend(
            [{"task_status": "pending"}, {"task_status": "started"}, {}, {"task_status": "success", "x": 1}]
        )
        result = make_client(poll_interval=3).poll_status(task_id="t-9")

        assert result == {"task_status": "success", "x": 1}
        assert clock.sleeps == [3, 3, 3]
        assert [c["url"] for c in rest.json_calls] == ["/v1/status/poll/t-9"] * 4

    def test_poll_interval_override(self, make_client, rest, clock):
        """An explicit poll interval overrides the client's default."""
        rest.json_answers.extend([{"task_status": "PENDING"}, {"task_status": "SUCCESS"}])
        make_client(poll_interval=3).poll_status(task_id="t", poll_interval=7)
        assert clock.sleeps == [7]

    def test_failure_status_raises_with_server_message(self, make_client, rest, clock):
        """A FAILURE status ends polling with the server's error message."""
        rest.json_answers.append({"task_status": "FAILURE", "error_message": "Internal processing error"})
        with pytest.raises(DocpipeException, match="Task t failed: Internal processing error"):
            make_client().poll_status(task_id="t")
        assert clock.sleeps == []

    def test_timeout_is_enforced(self, make_client, rest, clock):
        """Polling gives up once more than ``timeout`` seconds have elapsed."""
        rest.json_answers.extend([{"task_status": "PENDING"}] * 10)
        with pytest.raises(DocpipeException, match="Polling timeout after 5 seconds for task t"):
            make_client(poll_interval=2).poll_status(task_id="t", timeout=5)
        assert clock.sleeps == [2, 2, 2]

    def test_connection_errors_are_retried(self, make_client, rest, clock):
        """Connection errors that outlast the status-call retries are logged and polling continues."""
        connection_error = _error(status=503, message="reset", code=ErrorCode.CONNECTION_ERROR)
        attempts = DoclingClientConstants.STATUS_404_MAX_RETRIES
        rest.json_answers.extend([connection_error] * attempts + [{"task_status": "SUCCESS"}])

        assert make_client(poll_interval=4).poll_status(task_id="t") == {"task_status": "SUCCESS"}
        assert clock.sleeps
        assert set(clock.sleeps) == {4}

    def test_status_404_is_retried_with_backoff(self, make_client, rest, clock):
        """A 404 (task briefly unknown during pod restarts) is retried with exponential backoff."""
        rest.json_answers.extend([_error(status=404, message="Not Found"), {"task_status": "SUCCESS"}])

        assert make_client().poll_status(task_id="t") == {"task_status": "SUCCESS"}
        assert clock.retry_sleeps == [DoclingClientConstants.STATUS_404_BACKOFF_BASE]

    def test_persistent_404_is_raised(self, make_client, rest, clock):
        """A 404 that outlasts all retries is raised to the caller."""
        rest.json_answers.extend(
            [_error(status=404, message="Not Found")] * DoclingClientConstants.STATUS_404_MAX_RETRIES
        )
        with pytest.raises(DocpipeException, match="Not Found") as excinfo:
            make_client().poll_status(task_id="t")
        assert excinfo.value.status_code == 404
        assert len(rest.json_calls) == DoclingClientConstants.STATUS_404_MAX_RETRIES

    def test_other_http_errors_are_raised(self, make_client, rest, clock):
        """Non-404, non-connection errors end polling with the original error."""
        rest.json_answers.extend([_error(status=500, message="Server Error")] * 10)
        with pytest.raises(DocpipeException, match="Server Error") as excinfo:
            make_client().poll_status(task_id="t")
        assert excinfo.value.status_code == 500
        assert clock.sleeps == []


class TestProcessDocument:
    """Submit, poll and fetch in one call."""

    def test_end_to_end_against_fake_server(self, make_client, rest, clock):
        """The result is fetched only after the task reported SUCCESS."""
        rest.multipart_answers.append({"task_id": "t-42"})
        rest.json_answers.extend(
            [{"task_status": "PENDING"}, {"task_status": "SUCCESS"}, {"document": {"md_content": "# Title"}}]
        )

        result = make_client().process_document(binary_content=b"<h1>Title</h1>", filename="page.html")

        assert result == {"document": {"md_content": "# Title"}}
        assert [c["url"] for c in rest.json_calls] == [
            "/v1/status/poll/t-42",
            "/v1/status/poll/t-42",
            "/v1/result/t-42",
        ]
        assert rest.multipart_calls[0]["files"]["files"][2] == "text/html"

    def test_non_success_final_status_is_not_fetched(self, make_client, rest, monkeypatch):
        """If polling ever returns a non-SUCCESS state, no result is fetched and an error is raised."""
        rest.multipart_answers.append({"task_id": "t-7"})
        client = make_client()
        monkeypatch.setattr(
            client, "_poll_for_completion", lambda **_: {"task_status": "REVOKED", "error_message": "cancelled"}
        )

        with pytest.raises(DocpipeException, match=r"Task t-7 did not complete successfully.*cancelled"):
            client.process_document(binary_content=b"x", filename="a.pdf")

        assert rest.json_calls == []
