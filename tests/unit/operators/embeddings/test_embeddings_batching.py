"""Tests for cross-document request batching and concurrency in EmbeddingsOperator."""

import json
import math
import random
import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import litellm
import numpy as np
import pyarrow as pa
import pytest
import requests

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.models.session_info import SessionInfo, session_info_var
from docpipe.core.operators.functional.embeddings import EmbeddingsOperator
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.rest_client import RestClient, RestClientConfig
from docpipe.integrations.watsonx.rest_client import WatsonxRestEmbeddingClient

_ADAPTER_FACTORY_PATH = "docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter"


class _ProviderError(Exception):
    """Provider error carrying an HTTP status, like LiteLLM/OpenAI exceptions."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _bad_request() -> Exception:
    """Input-dependent failure: the provider rejected a text of the request."""
    return _ProviderError("invalid input text", status_code=400)


def _vector_for(text: str) -> list[float]:
    """Deterministic 3-d vector derived from the text itself."""
    return [float(sum(map(ord, text)) % 997), float(len(text)), float(ord(text[0]))]


class _RecordingAdapter(LLMEmbeddingPort):
    """Embedding port double that records calls and measures in-flight concurrency."""

    def __init__(
        self,
        *,
        batch_size: int,
        max_concurrent_requests: int = 1,
        delay: float = 0.0,
        jitter: float = 0.0,
        fail_when: Any = None,
        error_factory: Callable[[], Exception] = _bad_request,
    ) -> None:
        self._batch_size = batch_size
        self._max_concurrent_requests = max_concurrent_requests
        self._delay = delay
        self._jitter = jitter
        self._fail_when = fail_when
        self._error_factory = error_factory
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.calls: list[list[str]] = []
        self.call_sessions: list[SessionInfo | None] = []

    def generate_embeddings(self, *, text: str) -> list[float]:
        return _vector_for(text)

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self.calls.append(list(texts))
            self.call_sessions.append(session_info_var.get())
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            if self._delay or self._jitter:
                time.sleep(self._delay + random.uniform(0.0, self._jitter))
            if self._fail_when is not None and self._fail_when(texts):
                raise self._error_factory()
            return [_vector_for(text) for text in texts]
        finally:
            with self._lock:
                self._in_flight -= 1

    def get_embedding_dimension(self) -> int:
        return 3

    def get_embedding_batch_size(self) -> int:
        return self._batch_size

    def get_max_concurrent_requests(self) -> int:
        return self._max_concurrent_requests


def _make_operator(*, adapter: LLMEmbeddingPort, **config: Any) -> EmbeddingsOperator:
    base_config: dict[str, Any] = {
        "provider": "litellm",
        "embeddings_column": "embeddings",
        "provider_config": {"model_id": "openai/text-embedding-3-small", "api_key": "<test-api-key>"},
    }
    base_config.update(config)
    with patch(_ADAPTER_FACTORY_PATH, return_value=adapter):
        return EmbeddingsOperator(base_config)


def _chunked_table(*, chunks_per_doc: list[list[Any]]) -> pa.Table:
    count = len(chunks_per_doc)
    return pa.table(
        {
            "id": [f"doc{i}" for i in range(count)],
            "name": [f"Document {i}" for i in range(count)],
            "content": [f"content {i}" for i in range(count)],
            "doc_id_hash": [f"hash{i}" for i in range(count)],
            "chunked_content": [
                [{"chunk": c} if isinstance(c, str) else c for c in chunks] for chunks in chunks_per_doc
            ],
        }
    )


def _unchunked_table(*, contents: list[str]) -> pa.Table:
    count = len(contents)
    return pa.table(
        {
            "id": [f"doc{i}" for i in range(count)],
            "name": [f"Document {i}" for i in range(count)],
            "content": contents,
            "doc_id_hash": [f"hash{i}" for i in range(count)],
        }
    )


class TestRequestCount:
    """Texts from all documents are packed into full requests of batch_size."""

    def test_chunked_request_count_spans_documents(self):
        adapter = _RecordingAdapter(batch_size=16)
        operator = _make_operator(adapter=adapter)
        chunks = [[f"d{d}-c{c}" for c in range(7)] for d in range(10)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))

        total_texts = 70
        assert len(adapter.calls) == math.ceil(total_texts / 16)
        assert [len(call) for call in adapter.calls] == [16, 16, 16, 16, 6]
        # Every text is sent exactly once, in document order
        assert [text for call in adapter.calls for text in call] == [t for doc in chunks for t in doc]
        assert metadata[Metrics.External.PROCESSED_DOCS] == 10
        assert result_tables[0].num_rows == 10

    def test_unchunked_request_count_spans_documents(self):
        adapter = _RecordingAdapter(batch_size=8)
        operator = _make_operator(adapter=adapter)

        operator.transform(_unchunked_table(contents=[f"document text {i}" for i in range(50)]))

        assert len(adapter.calls) == math.ceil(50 / 8)
        assert all(len(call) == 8 for call in adapter.calls[:-1])

    def test_empty_texts_are_not_sent(self):
        adapter = _RecordingAdapter(batch_size=4)
        operator = _make_operator(adapter=adapter)

        operator.transform(_chunked_table(chunks_per_doc=[["a1", "   ", "a2"], ["   "], ["b1"]]))

        assert [text for call in adapter.calls for text in call] == ["a1", "a2", "b1"]
        assert len(adapter.calls) == 1


class TestConcurrency:
    """At most max_concurrent_requests requests are in flight."""

    def test_in_flight_requests_never_exceed_limit(self):
        adapter = _RecordingAdapter(batch_size=2, max_concurrent_requests=3, delay=0.02)
        operator = _make_operator(adapter=adapter)

        operator.transform(_unchunked_table(contents=[f"text {i}" for i in range(40)]))

        assert len(adapter.calls) == 20
        assert adapter.max_in_flight <= 3
        assert adapter.max_in_flight > 1, "requests should actually overlap"

    def test_single_request_limit_is_sequential(self):
        adapter = _RecordingAdapter(batch_size=2, max_concurrent_requests=1, delay=0.005)
        operator = _make_operator(adapter=adapter)

        operator.transform(_unchunked_table(contents=[f"text {i}" for i in range(10)]))

        assert adapter.max_in_flight == 1

    def test_worker_threads_see_caller_session_info(self):
        adapter = _RecordingAdapter(batch_size=1, max_concurrent_requests=4, delay=0.005)
        operator = _make_operator(adapter=adapter)
        session = SessionInfo(job_id="job-1", job_run_id="run-1")
        token = session_info_var.set(session)
        try:
            operator.transform(_unchunked_table(contents=[f"text {i}" for i in range(8)]))
        finally:
            session_info_var.reset(token)

        assert len(adapter.call_sessions) == 8
        assert all(s is session for s in adapter.call_sessions)


class TestScatter:
    """Vectors are returned to the right documents in the right order."""

    @pytest.mark.parametrize("max_concurrent_requests", [1, 4])
    def test_chunked_vectors_land_on_their_documents(self, max_concurrent_requests):
        adapter = _RecordingAdapter(batch_size=3, max_concurrent_requests=max_concurrent_requests, jitter=0.01)
        operator = _make_operator(adapter=adapter)
        chunks: list[list[Any]] = [
            ["alpha", "beta", "gamma", "delta"],
            ["   ", "epsilon"],  # whitespace-only chunk -> zero vector
            [{"chunk": "zeta", "summary": "about zeta"}],
            ["eta", "theta", "iota", "kappa", "lambda"],
        ]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))
        result = result_tables[0]

        expected = [
            [_vector_for(t) for t in ["alpha", "beta", "gamma", "delta"]],
            [[0.0, 0.0, 0.0], _vector_for("epsilon")],
            [_vector_for("abstract: about zeta\ncontent: zeta")],
            [_vector_for(t) for t in ["eta", "theta", "iota", "kappa", "lambda"]],
        ]
        assert result["embeddings"].to_pylist() == expected
        assert result["id"].to_pylist() == ["doc0", "doc1", "doc2", "doc3"]
        assert result["doc_id_hash"].to_pylist() == ["hash0", "hash1", "hash2", "hash3"]
        assert metadata[Metrics.External.PROCESSED_DOCS] == 4
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

    @pytest.mark.parametrize("max_concurrent_requests", [1, 4])
    def test_unchunked_vectors_land_on_their_documents(self, max_concurrent_requests):
        adapter = _RecordingAdapter(batch_size=2, max_concurrent_requests=max_concurrent_requests, jitter=0.01)
        operator = _make_operator(adapter=adapter)
        contents = ["first doc", "second doc", "   ", "fourth doc", "fifth doc"]

        result_tables, metadata = operator.transform(_unchunked_table(contents=contents))
        result = result_tables[0]

        expected = [
            _vector_for("first doc"),
            _vector_for("second doc"),
            [0.0, 0.0, 0.0],  # whitespace-only content -> zero vector with the model's dimension
            _vector_for("fourth doc"),
            _vector_for("fifth doc"),
        ]
        assert result["embeddings"].to_pylist() == expected
        assert metadata[Metrics.External.PROCESSED_DOCS] == 5

    def test_documents_without_content_fail_without_affecting_others(self):
        adapter = _RecordingAdapter(batch_size=4)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(
            _chunked_table(chunks_per_doc=[["a1", "a2"], [], ["c1"], [{"chunk": ""}]])
        )
        result = result_tables[0]

        assert result["id"].to_pylist() == ["doc0", "doc2"]
        assert result["embeddings"].to_pylist() == [[_vector_for("a1"), _vector_for("a2")], [_vector_for("c1")]]
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1", "doc3"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value

    def test_long_text_pieces_are_averaged(self):
        adapter = _RecordingAdapter(batch_size=2)
        # token_limit 5 -> char limit 20, overlap 0.2 -> 4 chars
        operator = _make_operator(adapter=adapter, token_limit=5)
        long_text = "abcdefghijklmnopqrstuvwxyz0123456789"
        pieces = EmbeddingsOperator._split_long_text(text=long_text, char_limit=20, overlap_chars=4)

        result_tables, _metadata = operator.transform(_chunked_table(chunks_per_doc=[["short", long_text, "tail"]]))

        assert pieces == ["abcdefghijklmnopqrst", "qrstuvwxyz0123456789"]
        expected_long = np.mean([_vector_for(p) for p in pieces], axis=0).tolist()
        assert result_tables[0]["embeddings"].to_pylist() == [
            [_vector_for("short"), expected_long, _vector_for("tail")]
        ]
        assert [text for call in adapter.calls for text in call] == ["short", *pieces, "tail"]


class TestRequestFailures:
    """A bad text only fails its own document; shared failures are retried per document."""

    @pytest.mark.parametrize("max_concurrent_requests", [1, 3])
    def test_poison_text_fails_only_its_document(self, max_concurrent_requests):
        # One request of 6 texts carries docs A, B and C; "B-poison" makes any request containing it fail
        adapter = _RecordingAdapter(
            batch_size=6,
            max_concurrent_requests=max_concurrent_requests,
            fail_when=lambda texts: "B-poison" in texts,
        )
        operator = _make_operator(adapter=adapter)
        chunks = [["A-1", "A-2"], ["B-1", "B-poison"], ["C-1", "C-2"]]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))
        result = result_tables[0]

        assert result["id"].to_pylist() == ["doc0", "doc2"]
        assert result["doc_id_hash"].to_pylist() == ["hash0", "hash2"]
        assert result["embeddings"].to_pylist() == [[_vector_for(t) for t in chunks[d]] for d in (0, 2)]
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        failed = metadata[Metrics.External.FAILED_DOCS]
        assert [d["id"] for d in failed] == ["doc1"]
        assert "invalid input text" in failed[0]["reason"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value
        # 1 shared request, then one isolated request per affected document, each with its own texts only
        assert len(adapter.calls) == 4
        assert sorted(adapter.calls[1:]) == [["A-1", "A-2"], ["B-1", "B-poison"], ["C-1", "C-2"]]

    def test_only_documents_of_the_failed_request_are_retried(self):
        # 2 chunks per document and batch_size 4 -> request k carries docs 2k and 2k+1
        adapter = _RecordingAdapter(batch_size=4, fail_when=lambda texts: "d3-c0" in texts)
        operator = _make_operator(adapter=adapter)
        chunks = [[f"d{d}-c0", f"d{d}-c1"] for d in range(6)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))
        result = result_tables[0]

        assert result["id"].to_pylist() == ["doc0", "doc1", "doc2", "doc4", "doc5"]
        assert result["embeddings"].to_pylist() == [[_vector_for(t) for t in chunks[d]] for d in (0, 1, 2, 4, 5)]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc3"]
        # 3 shared requests + isolated retries of doc2 and doc3 only
        assert len(adapter.calls) == 5
        assert adapter.calls[3:] == [["d2-c0", "d2-c1"], ["d3-c0", "d3-c1"]]

    def test_document_spanning_a_failed_request_resends_only_failed_texts(self):
        # batch_size 3: doc0 = texts 0-1, doc1 = texts 2-4 (spans requests 0 and 1), doc2 = text 5
        adapter = _RecordingAdapter(batch_size=3, fail_when=lambda texts: "b3" in texts)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(
            _chunked_table(chunks_per_doc=[["a1", "a2"], ["b1", "b2", "b3"], ["c1"]])
        )

        # Request 1 = ["b2", "b3", "c1"] failed and is retried per document: doc1 still fails, doc2 succeeds
        assert result_tables[0]["id"].to_pylist() == ["doc0", "doc2"]
        assert result_tables[0]["embeddings"].to_pylist() == [
            [_vector_for("a1"), _vector_for("a2")],
            [_vector_for("c1")],
        ]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1"]
        assert adapter.calls[2:] == [["b2", "b3"], ["c1"]]

    def test_isolated_retry_assembles_vectors_from_both_passes(self):
        # Fail only the first attempt of the shared request: doc1 then gets vectors from both passes
        attempts: list[int] = []

        def fail_first_shared(texts: list[str]) -> bool:
            if "b3" in texts and "c1" in texts:
                attempts.append(1)
                return True
            return False

        adapter = _RecordingAdapter(batch_size=3, fail_when=fail_first_shared)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(
            _chunked_table(chunks_per_doc=[["a1", "a2"], ["b1", "b2", "b3"], ["c1"]])
        )

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
        assert result_tables[0]["embeddings"].to_pylist() == [
            [_vector_for("a1"), _vector_for("a2")],
            [_vector_for("b1"), _vector_for("b2"), _vector_for("b3")],
            [_vector_for("c1")],
        ]
        assert attempts == [1]

    @pytest.mark.parametrize("max_concurrent_requests", [1, 4])
    def test_input_errors_on_every_request_have_bounded_extra_calls(self, max_concurrent_requests):
        adapter = _RecordingAdapter(
            batch_size=4, max_concurrent_requests=max_concurrent_requests, fail_when=lambda texts: True
        )
        operator = _make_operator(adapter=adapter)
        # 10 docs x 3 chunks = 30 texts -> 8 shared requests; the last one (d9-c1, d9-c2) carries
        # only doc9, so doc9 fails on its own error and is not retried
        chunks = [[f"d{d}-c{c}" for c in range(3)] for d in range(10)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))

        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 10
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        shared_requests = math.ceil(30 / 4)
        # One isolated retry per remaining document (its failed texts fit in one request)
        assert len(adapter.calls) == shared_requests + 9
        # General bound on extra requests: failed shared requests + affected documents
        assert len(adapter.calls) - shared_requests <= shared_requests + 10

    def test_single_document_request_failure_does_not_retry(self):
        # batch_size 4, each document has exactly 4 texts -> every request carries one document
        adapter = _RecordingAdapter(batch_size=4, fail_when=lambda texts: "d1-c2" in texts)
        operator = _make_operator(adapter=adapter)
        chunks = [[f"d{d}-c{c}" for c in range(4)] for d in range(3)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))

        assert result_tables[0]["id"].to_pylist() == ["doc0", "doc2"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1"]
        assert len(adapter.calls) == 3

    def test_document_failed_by_own_request_is_not_retried_again(self):
        # batch_size 2: doc0 = [x1, x2] (own request, fails), shared request [x3, y1] also fails
        adapter = _RecordingAdapter(batch_size=2, fail_when=lambda texts: any(t.startswith("x") for t in texts))
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=[["x1", "x2", "x3"], ["y1"]]))

        assert result_tables[0]["id"].to_pylist() == ["doc1"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc0"]
        # 2 shared requests + isolated retry of doc1 only
        assert adapter.calls == [["x1", "x2"], ["x3", "y1"], ["y1"]]

    def test_vector_count_mismatch_fails_request(self):
        class _ShortAdapter(_RecordingAdapter):
            def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
                return super().generate_embeddings_batch(texts=texts)[:-1]

        adapter = _ShortAdapter(batch_size=10)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(_unchunked_table(contents=["one", "two"]))

        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2
        # A malformed response does not depend on the texts: both documents fail, nothing is re-sent
        assert "returned 1 vectors for 2 texts" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
        assert len(adapter.calls) == 1

    def test_context_length_error_keeps_actionable_message(self):
        class _ContextAdapter(_RecordingAdapter):
            def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
                raise ValueError("input length exceeds the context length")

        operator = _make_operator(adapter=_ContextAdapter(batch_size=10))

        _result_tables, metadata = operator.transform(_unchunked_table(contents=["one"]))

        assert "context length" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
        assert "Chunking operator" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]


class TestAdapterLimits:
    """batch_size / max_concurrent_requests come from the adapter, with safe fallbacks."""

    def test_limits_read_from_adapter(self):
        operator = _make_operator(adapter=_RecordingAdapter(batch_size=7, max_concurrent_requests=5))

        assert operator._batch_size == 7
        assert operator._max_concurrent_requests == 5

    @pytest.mark.parametrize("bad_value", [0, -1, None, "8", True, 2.5])
    def test_invalid_adapter_limits_fall_back_to_defaults(self, bad_value):
        adapter = _RecordingAdapter(batch_size=1)
        adapter._batch_size = bad_value
        adapter._max_concurrent_requests = bad_value

        operator = _make_operator(adapter=adapter)

        assert operator._batch_size == 32
        assert operator._max_concurrent_requests == 1


def _litellm_error(name: str) -> Exception:
    """Build a real LiteLLM exception by class name."""
    error_cls = getattr(litellm, name)
    if name in ("BadRequestError", "ContextWindowExceededError", "ContentPolicyViolationError", "Timeout"):
        return error_cls(f"{name} raised by provider", model="m", llm_provider="openai")
    return error_cls(f"{name} raised by provider", llm_provider="openai", model="m")


_PROVIDER_WIDE_ERRORS: dict[str, Callable[[], Exception]] = {
    "litellm_rate_limit_429": lambda: _litellm_error("RateLimitError"),
    "litellm_timeout_408": lambda: _litellm_error("Timeout"),
    "litellm_connection": lambda: _litellm_error("APIConnectionError"),
    "litellm_service_unavailable_503": lambda: _litellm_error("ServiceUnavailableError"),
    "litellm_internal_server_500": lambda: _litellm_error("InternalServerError"),
    "litellm_bad_gateway_502": lambda: _litellm_error("BadGatewayError"),
    "litellm_authentication_401": lambda: _litellm_error("AuthenticationError"),
    "litellm_not_found_404": lambda: _litellm_error("NotFoundError"),
    "http_429": lambda: _ProviderError("Too Many Requests", status_code=429),
    "http_504": lambda: _ProviderError("Gateway Timeout", status_code=504),
    "builtin_timeout": lambda: TimeoutError("read timed out"),
    "builtin_connection": lambda: ConnectionError("connection refused"),
    "unknown_error": lambda: RuntimeError("provider unavailable"),
}

_INPUT_DEPENDENT_ERRORS: dict[str, Callable[[], Exception]] = {
    "litellm_bad_request_400": lambda: _litellm_error("BadRequestError"),
    "litellm_context_window": lambda: _litellm_error("ContextWindowExceededError"),
    "litellm_content_policy": lambda: _litellm_error("ContentPolicyViolationError"),
    "http_400": lambda: _ProviderError("invalid input", status_code=400),
    "http_413": lambda: _ProviderError("payload too large", status_code=413),
    "http_422": lambda: _ProviderError("unprocessable input", status_code=422),
    # Ollama-style context error reported with a generic 500 status
    "context_length_message_500": lambda: _ProviderError(
        "the input length exceeds the context length", status_code=500
    ),
}


class TestProviderWideFailures:
    """Rate limits, timeouts, outages and auth errors fail the request's documents without re-sending."""

    @pytest.mark.parametrize("max_concurrent_requests", [1, 4])
    def test_rate_limit_is_not_amplified(self, max_concurrent_requests):
        # Reviewer scenario: 100 one-text documents, batch_size 32, provider always answers 429
        adapter = _RecordingAdapter(
            batch_size=32,
            max_concurrent_requests=max_concurrent_requests,
            fail_when=lambda texts: True,
            error_factory=_PROVIDER_WIDE_ERRORS["litellm_rate_limit_429"],
        )
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(
            _unchunked_table(contents=[f"document text {i}" for i in range(100)])
        )

        assert len(adapter.calls) == 4
        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 100
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        failed = metadata[Metrics.External.FAILED_DOCS]
        assert [d["id"] for d in failed] == [f"doc{i}" for i in range(100)]
        assert all("RateLimitError" in d["reason"] for d in failed)

    @pytest.mark.parametrize("error_name", sorted(_PROVIDER_WIDE_ERRORS))
    def test_provider_wide_errors_fail_documents_without_resending(self, error_name):
        adapter = _RecordingAdapter(
            batch_size=4, fail_when=lambda texts: True, error_factory=_PROVIDER_WIDE_ERRORS[error_name]
        )
        operator = _make_operator(adapter=adapter)
        chunks = [[f"d{d}-c{c}" for c in range(3)] for d in range(10)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))

        assert len(adapter.calls) == math.ceil(30 / 4)
        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 10

    def test_provider_wide_failure_spares_documents_of_successful_requests(self):
        # batch_size 4, 2 texts per doc -> request k carries docs 2k and 2k+1; request 1 hits a 503
        adapter = _RecordingAdapter(
            batch_size=4,
            fail_when=lambda texts: "d2-c0" in texts,
            error_factory=_PROVIDER_WIDE_ERRORS["litellm_service_unavailable_503"],
        )
        operator = _make_operator(adapter=adapter)
        chunks = [[f"d{d}-c0", f"d{d}-c1"] for d in range(6)]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))

        assert result_tables[0]["id"].to_pylist() == ["doc0", "doc1", "doc4", "doc5"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc2", "doc3"]
        assert len(adapter.calls) == 3

    def test_provider_wide_failure_wins_over_isolation_of_the_same_document(self):
        # batch_size 2: request 0 = [a1, b1] fails with a 400, request 1 = [b2, c1] with a 429.
        # doc1 (b) and doc2 (c) fail on the 429 without re-sending; only doc0 is re-sent on its own.
        errors = iter([_bad_request(), _ProviderError("Too Many Requests", status_code=429)])
        adapter = _RecordingAdapter(
            batch_size=2,
            fail_when=lambda texts: "b1" in texts or "b2" in texts,
            error_factory=lambda: next(errors),
        )
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=[["a1"], ["b1", "b2"], ["c1"]]))

        assert result_tables[0]["id"].to_pylist() == ["doc0"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1", "doc2"]
        assert adapter.calls == [["a1", "b1"], ["b2", "c1"], ["a1"]]


class TestInputDependentFailures:
    """Errors that can be caused by one text isolate documents so only the offending one fails."""

    @pytest.mark.parametrize("error_name", sorted(_INPUT_DEPENDENT_ERRORS))
    def test_bad_text_fails_only_its_document(self, error_name):
        adapter = _RecordingAdapter(
            batch_size=6,
            fail_when=lambda texts: "B-too-long" in texts,
            error_factory=_INPUT_DEPENDENT_ERRORS[error_name],
        )
        operator = _make_operator(adapter=adapter)
        chunks = [["A-1", "A-2"], ["B-1", "B-too-long"], ["C-1", "C-2"]]

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=chunks))
        result = result_tables[0]

        assert result["id"].to_pylist() == ["doc0", "doc2"]
        assert result["embeddings"].to_pylist() == [[_vector_for(t) for t in chunks[d]] for d in (0, 2)]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1"]
        assert len(adapter.calls) == 4


class TestErrorClassification:
    """Unit tests of the classification helpers on wrapped error chains."""

    @staticmethod
    def _wrapped(error: Exception) -> Exception:
        """Wrap ``error`` the way the LiteLLM client and the operator do."""
        try:
            try:
                raise error
            except Exception as inner:
                raise ExternalServiceError("Failed to generate batch embeddings with LiteLLM") from inner
        except Exception as client_error:
            wrapped = DocpipeException(f"Batch embedding generation failed: {client_error!s}")
            wrapped.__cause__ = client_error
            return wrapped

    @pytest.mark.parametrize("error_name", sorted(_PROVIDER_WIDE_ERRORS))
    def test_provider_wide_errors(self, error_name):
        error = _PROVIDER_WIDE_ERRORS[error_name]()
        assert EmbeddingsOperator._is_input_dependent_error(error) is False
        assert EmbeddingsOperator._is_input_dependent_error(self._wrapped(error)) is False

    @pytest.mark.parametrize("error_name", sorted(_INPUT_DEPENDENT_ERRORS))
    def test_input_dependent_errors(self, error_name):
        error = _INPUT_DEPENDENT_ERRORS[error_name]()
        assert EmbeddingsOperator._is_input_dependent_error(error) is True
        assert EmbeddingsOperator._is_input_dependent_error(self._wrapped(error)) is True

    def test_docpipe_status_code_is_only_trusted_for_http_errors(self):
        # DocpipeException status codes default to 400/500/502 and are not provider answers
        assert EmbeddingsOperator._is_input_dependent_error(DocpipeException("x", status_code=400)) is False
        http_400 = ExternalServiceError("x", error_code=ErrorCode.HTTP_ERROR, status_code=400)
        http_429 = ExternalServiceError("x", error_code=ErrorCode.HTTP_ERROR, status_code=429)
        assert EmbeddingsOperator._is_input_dependent_error(http_400) is True
        assert EmbeddingsOperator._is_input_dependent_error(http_429) is False

    def test_status_read_from_http_response(self):
        response = requests.Response()
        response.status_code = 422
        assert EmbeddingsOperator._is_input_dependent_error(requests.HTTPError("x", response=response)) is True
        response.status_code = 503
        assert EmbeddingsOperator._is_input_dependent_error(requests.HTTPError("x", response=response)) is False

    def test_implicit_context_is_followed_unless_suppressed(self):
        # An exception raised while handling another one keeps it as __context__
        outer = RuntimeError("while handling")
        outer.__context__ = _ProviderError("bad", status_code=400)
        assert EmbeddingsOperator._is_input_dependent_error(outer) is True

        # "raise ... from None" suppresses the context
        outer.__suppress_context__ = True
        assert EmbeddingsOperator._is_input_dependent_error(outer) is False

    def test_error_chain_stops_on_cycles(self):
        first = RuntimeError("a")
        second = RuntimeError("b")
        first.__cause__ = second
        second.__cause__ = first

        assert EmbeddingsOperator._error_chain(first) == [first, second]


# WatsonxRestEmbeddingClient.generate_embeddings_batch is decorated with retry_with_backoff(max_retries=5)
_WATSONX_CLIENT_ATTEMPTS = 5


class TestWrappedClientErrors:
    """Errors keep their classification through the real client and adapter wrapping layers."""

    @staticmethod
    def _litellm_operator(*, batch_size: int) -> EmbeddingsOperator:
        return EmbeddingsOperator(
            {
                "provider": "litellm",
                "embeddings_column": "embeddings",
                "provider_config": {
                    "model_id": "openai/text-embedding-3-small",
                    "api_key": "<test-api-key>",  # pragma: allowlist secret
                    "batch_size": batch_size,
                    "max_concurrent_requests": 2,
                },
            }
        )

    def test_litellm_rate_limit_through_client_is_not_resent(self):
        calls: list[list[str]] = []

        def embedding(**kwargs: Any) -> Any:
            calls.append(list(kwargs["input"]))
            raise litellm.RateLimitError("Rate limit exceeded", llm_provider="openai", model="text-embedding-3-small")

        with (
            patch("litellm.embedding", side_effect=embedding),
            patch("docpipe.integrations.base_llm_client.time.sleep"),
        ):
            operator = self._litellm_operator(batch_size=32)
            result_tables, metadata = operator.transform(
                _unchunked_table(contents=[f"document text {i}" for i in range(100)])
            )

        # 4 shared requests, each tried 3 times by the LiteLLM client; no per-document re-sends
        assert len(calls) == 4 * 3
        assert {len(call) for call in calls} == {32, 4}
        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 100
        assert "RateLimitError" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]

    def test_litellm_context_window_through_client_isolates(self):
        def embedding(**kwargs: Any) -> Any:
            texts = kwargs["input"]
            if "B-too-long" in texts:
                raise litellm.ContextWindowExceededError(
                    "maximum context length exceeded", model="text-embedding-3-small", llm_provider="openai"
                )
            return {"data": [{"embedding": _vector_for(text)} for text in texts]}

        with (
            patch("litellm.embedding", side_effect=embedding),
            patch("docpipe.integrations.base_llm_client.time.sleep"),
        ):
            operator = self._litellm_operator(batch_size=6)
            result_tables, metadata = operator.transform(
                _chunked_table(chunks_per_doc=[["A-1", "A-2"], ["B-1", "B-too-long"], ["C-1", "C-2"]])
            )

        assert result_tables[0]["id"].to_pylist() == ["doc0", "doc2"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1"]

    @staticmethod
    def _watsonx_adapter(*, status_for: Callable[[list[str]], int]) -> tuple[_RecordingAdapter, list[list[str]]]:
        """Embedding port backed by a real watsonx REST client whose HTTP session is faked."""
        sent: list[list[str]] = []

        def request(**kwargs: Any) -> requests.Response:
            texts = kwargs["json"]["inputs"]
            sent.append(list(texts))
            response = requests.Response()
            response.status_code = status_for(texts)
            response.url = "https://us-south.ml.cloud.ibm.com/ml/v1/text/embeddings"
            response.reason = "error"
            results = [{"embedding": _vector_for(t)} for t in texts] if response.status_code == 200 else []
            response._content = json.dumps({"results": results}).encode()
            return response

        WatsonxRestEmbeddingClient.clear_client_cache()
        WatsonxRestEmbeddingClient.clear_token_limit_cache()
        with (
            patch("docpipe.integrations.watsonx.rest_client.IAMTokenManager") as iam,
            patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models", side_effect=Exception),
        ):
            iam.return_value.get_token.return_value = "test-iam-token"
            client = WatsonxRestEmbeddingClient(
                api_key="<test-api-key>",  # pragma: allowlist secret
                url="https://us-south.ml.cloud.ibm.com",
                container_kind="project",
                container_id="test-project-id",
                model_name="ibm/slate-30m-english-rtrvr",
                batch_size=4,
            )
        WatsonxRestEmbeddingClient.clear_client_cache()
        # Real RestClient (status handling and ExternalServiceError wrapping), without retry waits
        client.rest_client = RestClient(
            config=RestClientConfig(retry_max_attempts=1), base_url=client.url, auth_token="test-iam-token"
        )
        client.rest_client.session.request = request  # type: ignore[method-assign]

        class _WatsonxBackedAdapter(_RecordingAdapter):
            def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
                # The client retries each request itself (5 attempts); skip its backoff waits
                with patch("docpipe.integrations.base_llm_client.time.sleep"):
                    return client.generate_embeddings_batch(texts=texts)

        return _WatsonxBackedAdapter(batch_size=4), sent

    def test_watsonx_http_429_is_not_resent(self):
        adapter, sent = self._watsonx_adapter(status_for=lambda texts: 429)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(_unchunked_table(contents=[f"text {i}" for i in range(10)]))

        # 3 shared requests, each tried 5 times by the watsonx client; no per-document re-sends
        assert len(sent) == 3 * _WATSONX_CLIENT_ATTEMPTS
        assert result_tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 10
        assert "429" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]

    def test_watsonx_http_400_isolates(self):
        adapter, sent = self._watsonx_adapter(status_for=lambda texts: 400 if "bad" in texts else 200)
        operator = _make_operator(adapter=adapter)

        result_tables, metadata = operator.transform(_chunked_table(chunks_per_doc=[["a1", "a2"], ["bad"], ["c1"]]))

        assert result_tables[0]["id"].to_pylist() == ["doc0", "doc2"]
        assert result_tables[0]["embeddings"].to_pylist() == [
            [_vector_for("a1"), _vector_for("a2")],
            [_vector_for("c1")],
        ]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["doc1"]
        # The shared request (tried 5 times) is followed by one isolated request per document
        assert sent == [
            *[["a1", "a2", "bad", "c1"]] * _WATSONX_CLIENT_ATTEMPTS,
            ["a1", "a2"],
            *[["bad"]] * _WATSONX_CLIENT_ATTEMPTS,
            ["c1"],
        ]
