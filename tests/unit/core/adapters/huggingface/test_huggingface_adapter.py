# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the consolidated HuggingFace adapter: embeddings and text detection (HAP).

Text detection tests replace the classification client with a fake that returns fixed
label probabilities per span text, so no model is loaded.
"""

import logging
from collections.abc import Generator, Sequence
from typing import Any
from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters.huggingface import HuggingFaceAdapter, huggingface_adapter
from docpipe.core.constants.constants import ServiceConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.text_detection_port import TextDetectionPort
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.integrations.huggingface.classification_client import WindowScores

_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_CLASSIFIER = "org/toxicity-classifier"
_CLEAN = {"LABEL_0": 0.99, "LABEL_1": 0.01}


class TestHuggingFaceAdapter:
    """Test suite for HuggingFaceAdapter delegation to HuggingFaceLLMClient."""

    @pytest.fixture
    def mock_client_class(self):
        """Patch the HuggingFace client class used by the adapter."""
        with patch.object(huggingface_adapter, "HuggingFaceLLMClient") as client_cls:
            client_cls.return_value = Mock()
            yield client_cls

    @pytest.fixture
    def adapter(self, mock_client_class):
        """Create a HuggingFace adapter backed by a mock client."""
        return HuggingFaceAdapter(model_name=_MODEL, use_local=True, device="cpu", batch_size=8)

    def test_implements_embedding_and_detection_ports(self, adapter):
        """The consolidated adapter implements both Hugging Face ports."""
        assert isinstance(adapter, LLMEmbeddingPort)
        assert isinstance(adapter, TextDetectionPort)

    def test_construction_creates_no_client(self, mock_client_class):
        """Constructing the adapter neither builds the embedding client nor loads a model."""
        HuggingFaceAdapter(model_name=_MODEL)

        mock_client_class.assert_not_called()

    def test_client_created_once_on_first_use_with_all_options(self, mock_client_class):
        """The first embedding call builds the client with every option (including extra kwargs), once."""
        adapter = HuggingFaceAdapter(
            model_name=_MODEL,
            use_local=False,
            api_token="hf-test-token",  # pragma: allowlist secret
            device="cuda",
            batch_size=4,
            normalize=True,
        )

        adapter.generate_embeddings(text="a")
        adapter.generate_embeddings_batch(texts=["b"])

        mock_client_class.assert_called_once_with(
            model_name=_MODEL,
            use_local=False,
            api_token="hf-test-token",  # pragma: allowlist secret
            device="cuda",
            batch_size=4,
            normalize=True,
        )

    def test_generate_embeddings_delegates_to_client(self, adapter, mock_client_class):
        """Single-text embedding is delegated to the client and its result returned."""
        client = mock_client_class.return_value
        client.generate_embeddings.return_value = [0.1, 0.2, 0.3]

        result = adapter.generate_embeddings(text="hello")

        assert result == [0.1, 0.2, 0.3]
        client.generate_embeddings.assert_called_once_with("hello")

    def test_generate_embeddings_batch_delegates_to_client(self, adapter, mock_client_class):
        """Batch embedding is delegated to the client and its result returned."""
        client = mock_client_class.return_value
        client.generate_embeddings_batch.return_value = [[0.1], [0.2]]

        result = adapter.generate_embeddings_batch(texts=["a", "b"])

        assert result == [[0.1], [0.2]]
        client.generate_embeddings_batch.assert_called_once_with(["a", "b"])

    def test_generate_embeddings_propagates_client_errors(self, adapter, mock_client_class):
        """Client errors are not swallowed by the adapter."""
        mock_client_class.return_value.generate_embeddings.side_effect = RuntimeError("model failure")

        with pytest.raises(RuntimeError, match="model failure"):
            adapter.generate_embeddings(text="hello")

    def test_get_embedding_batch_size_does_not_create_client(self, adapter, mock_client_class):
        """Batch size is reported from the adapter's options without building the client."""
        assert adapter.get_embedding_batch_size() == 8
        mock_client_class.assert_not_called()

    def test_get_max_concurrent_requests_defaults_to_one(self, adapter):
        """Local inference keeps the port default of a single in-flight request."""
        assert adapter.get_max_concurrent_requests() == 1

    def test_get_embedding_dimension_uses_static_lookup(self, adapter, mock_client_class):
        """Dimension lookup uses the client's static helper with the adapter's model name."""
        mock_client_class.get_embedding_dimension.return_value = 384

        assert adapter.get_embedding_dimension() == 384
        mock_client_class.get_embedding_dimension.assert_called_once_with(_MODEL)

    def test_validate_embedding_builds_client_and_passes(self, adapter, mock_client_class):
        """Validation builds the client at startup and passes when that succeeds."""
        result = adapter.validate_embedding()

        assert result == {"valid": True, "context": "embedding", "errors": [], "warnings": []}
        mock_client_class.assert_called_once()

    def test_validate_resolves_to_embedding_validation(self, adapter, mock_client_class):
        """validate() runs the embedding hook, so the embeddings operator still fails fast."""
        mock_client_class.side_effect = OSError("model not found")

        result = adapter.validate()

        assert result["valid"] is False
        assert result["context"] == "embedding"

    def test_validate_embedding_reports_client_build_failure(self, adapter, mock_client_class):
        """A client that cannot be built is reported as invalid, naming the model and the cause."""
        mock_client_class.side_effect = OSError("model not found")

        result = adapter.validate_embedding()

        assert result["valid"] is False
        assert result["errors"] == [f"Failed to initialise Hugging Face embedding model '{_MODEL}': model not found"]

    def test_failed_client_build_is_retried_on_next_use(self, adapter, mock_client_class):
        """A failed build leaves no client behind, so the next call tries again."""
        mock_client_class.side_effect = [OSError("transient"), Mock()]

        assert adapter.validate_embedding()["valid"] is False
        assert adapter.validate_embedding()["valid"] is True
        assert mock_client_class.call_count == 2


class FakeClassificationClient:
    """Stand-in for HuggingFaceClassificationClient with fixed probabilities per span text."""

    def __init__(
        self,
        *,
        probabilities_by_text: dict[str, dict[str, float]] | None = None,
        labels: tuple[str, ...] = ("LABEL_0", "LABEL_1"),
        error: Exception | None = None,
    ) -> None:
        """Store canned scores, labels and an optional error to raise."""
        self.probabilities_by_text = probabilities_by_text or {}
        self.labels = labels
        self.error = error
        self.scored_spans: list[list[tuple[int, int]]] = []

    def get_labels(self) -> tuple[str, ...]:
        """Return the labels, or raise the configured error."""
        if self.error:
            raise self.error
        return self.labels

    def score_spans(self, *, text: str, spans: Sequence[tuple[int, int]]) -> list[WindowScores]:
        """Return one WindowScores per span, or raise the configured error."""
        self.scored_spans.append(list(spans))
        if self.error:
            raise self.error
        return [
            WindowScores(start=start, end=end, probabilities=self.probabilities_by_text.get(text[start:end], _CLEAN))
            for start, end in spans
        ]


class _ClientsBuiltWhileWaiting:
    """Lock stand-in that simulates another thread building the clients while this one waited."""

    def __init__(self, *, adapter: HuggingFaceAdapter) -> None:
        """Store the adapter whose clients the other thread builds."""
        self.adapter = adapter
        self.embedding_client = Mock()
        self.detection_client = FakeClassificationClient()

    def __enter__(self) -> "_ClientsBuiltWhileWaiting":
        """Install both clients at the moment the lock is acquired."""
        self.adapter.client = self.embedding_client
        self.adapter.detection_client = self.detection_client  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Release nothing; the stand-in holds no real lock."""


def _make_detection_adapter(
    *, client: FakeClassificationClient | None = None, toxic_labels: Sequence[str] = ("LABEL_1",)
) -> HuggingFaceAdapter:
    """Build an adapter for detection with an injected fake classification client."""
    adapter = HuggingFaceAdapter(model_name=_CLASSIFIER, toxic_labels=toxic_labels)
    adapter.detection_client = client or FakeClassificationClient()  # type: ignore[assignment]
    return adapter


def _hap(threshold: float) -> dict[str, Any]:
    """Return a detectors payload asking for HAP at ``threshold``."""
    return {"hap": {"threshold": threshold}}


class TestHuggingFaceAdapterTextDetection:
    """Test suite for HuggingFaceAdapter's TextDetectionPort (HAP) implementation."""

    @pytest.fixture
    def adapter_logs(self, caplog: pytest.LogCaptureFixture) -> Generator[pytest.LogCaptureFixture, None, None]:
        """Capture every record of the adapter module's logger, at DEBUG level."""
        module_logger = huggingface_adapter.logger
        previous_level = module_logger.level
        module_logger.addHandler(caplog.handler)
        module_logger.setLevel(logging.DEBUG)
        yield caplog
        module_logger.removeHandler(caplog.handler)
        module_logger.setLevel(previous_level)

    # ------------------------------------------------------------------ segmentation

    @pytest.mark.parametrize(
        ("text", "expected_spans"),
        [
            ("Thanks for the report.\nYou are a worthless idiot. See you tomorrow.", ["Thanks for the report.", "You are a worthless idiot.", "See you tomorrow."]),
            ("First line.\r\nSecond line. Third.", ["First line.", "Second line.", "Third."]),
            ("# Heading\n\n- item one\n- item two\n| a | b |", ["# Heading", "- item one", "- item two", "| a | b |"]),
            ("Dr. Smith arrived. He left.", ["Dr.", "Smith arrived.", "He left."]),
            ("   Indented sentence.   \n", ["Indented sentence."]),
            (" \n\t \r\n ", []),
            ("", []),
        ],
    )  # fmt: skip
    def test_segment_text_returns_trimmed_spans_with_original_offsets(
        self, text: str, expected_spans: list[str]
    ) -> None:
        """Spans split at line breaks and sentences, exclude whitespace, and index into the unchanged text."""
        spans = HuggingFaceAdapter._segment_text(text=text)

        assert [text[start:end] for start, end in spans] == expected_spans
        assert spans == sorted(spans)

    def test_segment_text_drops_spans_that_are_only_whitespace(self) -> None:
        """A sentence span that trims to nothing is dropped instead of being scored."""
        text = "Hello.   World."
        sentence_tokenizer = Mock()
        sentence_tokenizer.span_tokenize.return_value = [(0, 6), (6, 9), (9, 15)]

        with patch.object(HuggingFaceAdapter, "_sentence_tokenizer", return_value=sentence_tokenizer):
            spans = HuggingFaceAdapter._segment_text(text=text)

        assert [text[start:end] for start, end in spans] == ["Hello.", "World."]

    # ------------------------------------------------------------------ detection

    def test_detect_returns_only_the_toxic_sentence_with_its_offsets(self) -> None:
        """One toxic sentence among clean ones yields exactly one detection covering that sentence."""
        text = "Thanks for the report.\nYou are a worthless idiot. See you tomorrow."
        toxic = "You are a worthless idiot."
        client = FakeClassificationClient(probabilities_by_text={toxic: {"LABEL_0": 0.05, "LABEL_1": 0.95}})

        result = _make_detection_adapter(client=client).detect(text=text, detectors=_hap(0.8))

        assert result["success"] is True
        assert result["error"] is None
        assert result["detections"] == [
            {
                "detection": "has_HAP",
                "detection_type": "hap",
                "score": 0.95,
                "start": text.index(toxic),
                "end": text.index(toxic) + len(toxic),
                "text": toxic,
                "evidences": [{"source": "huggingface", "model_id": _CLASSIFIER, "label": "LABEL_1"}],
            }
        ]

    @pytest.mark.parametrize(("score", "reported"), [(0.8, True), (0.79, False)])
    def test_detect_reports_span_only_at_or_above_threshold(self, score: float, reported: bool) -> None:
        """A span scoring exactly the threshold is reported; one just below it is not."""
        text = "Borderline sentence."
        client = FakeClassificationClient(probabilities_by_text={text: {"LABEL_0": 1 - score, "LABEL_1": score}})

        result = _make_detection_adapter(client=client).detect(text=text, detectors=_hap(0.8))

        assert len(result["detections"]) == (1 if reported else 0)

    @pytest.mark.parametrize("detectors", [None, {"hap": None}, {"hap": {}}, {"hap": {"threshold": None}}])
    def test_detect_uses_default_threshold_when_not_given(self, detectors: Any) -> None:
        """Without a threshold, the default HAP threshold applies."""
        text = "Borderline sentence."
        default = ServiceConstants.DEFAULT_HUGGINGFACE_HAP_THRESHOLD
        client = FakeClassificationClient(probabilities_by_text={text: {"LABEL_0": 1 - default, "LABEL_1": default}})

        result = _make_detection_adapter(client=client).detect(text=text, detectors=detectors)

        assert len(result["detections"]) == 1

    def test_detect_scores_span_by_highest_configured_toxic_label(self) -> None:
        """The span score is the max over toxic_labels only; other labels are ignored."""
        text = "An insulting sentence."
        client = FakeClassificationClient(
            labels=("toxicity", "insult", "threat"),
            probabilities_by_text={text: {"toxicity": 0.3, "insult": 0.9, "threat": 0.99}},
        )
        adapter = _make_detection_adapter(client=client, toxic_labels=("toxicity", "insult"))

        result = adapter.detect(text=text, detectors=_hap(0.5))

        (detection,) = result["detections"]
        assert detection["score"] == 0.9
        assert detection["evidences"][0]["label"] == "insult"

    def test_detect_returns_no_detections_for_whitespace_only_text(self) -> None:
        """Whitespace-only text scores no span and yields no detection."""
        client = FakeClassificationClient()

        result = _make_detection_adapter(client=client).detect(text=" \n\t ", detectors=_hap(0.8))

        assert result == {"success": True, "detections": [], "error": None}
        assert client.scored_spans == [[]]

    @pytest.mark.parametrize(
        ("detection_types", "detectors", "unsupported"),
        [
            (None, {"pii": {"threshold": 0.5}}, "['pii']"),
            (None, {"pii": {}, "hap": {}}, "['pii']"),
            (["pii"], None, "['pii']"),
            (["hap", "sentiment"], {"hap": {"threshold": 0.8}}, "['sentiment']"),
        ],
    )
    def test_detect_rejects_detectors_other_than_hap(
        self, detection_types: list[str] | None, detectors: Any, unsupported: str
    ) -> None:
        """Requests for anything but HAP fail without scoring."""
        client = FakeClassificationClient()

        result = _make_detection_adapter(client=client).detect(
            text="Hi.", detection_types=detection_types, detectors=detectors
        )

        assert result["success"] is False
        assert result["detections"] == []
        assert f"Unsupported detector(s) {unsupported}" in result["error"]
        assert client.scored_spans == []

    def test_detect_accepts_hap_detection_type(self) -> None:
        """detection_types=['hap'] is supported."""
        result = _make_detection_adapter().detect(text="Hi.", detection_types=["hap"], detectors=_hap(0.8))

        assert result["success"] is True

    def test_detect_failure_hides_exception_message_and_logs_no_text(
        self, adapter_logs: pytest.LogCaptureFixture
    ) -> None:
        """A scoring error returns success False naming only the exception class and model, never the input."""
        text = "Secret customer text that must never leak."
        client = FakeClassificationClient(error=ValueError(f"cannot tokenize: {text}"))

        result = _make_detection_adapter(client=client).detect(text=text, detectors=_hap(0.8))

        assert result == {
            "success": False,
            "detections": [],
            "error": f"ValueError while scoring with model '{_CLASSIFIER}'",
        }
        assert adapter_logs.records
        assert all("Secret customer text" not in record.getMessage() for record in adapter_logs.records)

    def test_detect_debug_logs_contain_no_document_text(self, adapter_logs: pytest.LogCaptureFixture) -> None:
        """Successful detection logs counts at DEBUG but no document or span text."""
        text = "Private sentence one. You are a worthless idiot."
        client = FakeClassificationClient(
            probabilities_by_text={"You are a worthless idiot.": {"LABEL_0": 0.1, "LABEL_1": 0.9}}
        )

        _make_detection_adapter(client=client).detect(text=text, detectors=_hap(0.8))

        debug_messages = [record.getMessage() for record in adapter_logs.records if record.levelno == logging.DEBUG]
        assert debug_messages
        assert all("Private sentence" not in message and "idiot" not in message for message in debug_messages)

    def test_detect_fails_when_toxic_label_missing_from_scores(self) -> None:
        """An unknown toxic label at scoring time is a per-call failure, not a crash."""
        result = _make_detection_adapter(toxic_labels=("toxic",)).detect(text="Hi.", detectors=_hap(0.8))

        assert result["success"] is False
        assert result["error"] == f"KeyError while scoring with model '{_CLASSIFIER}'"

    # ------------------------------------------------------------------ validation

    def test_validate_detection_passes_for_known_labels(self) -> None:
        """Known toxic labels validate."""
        result = _make_detection_adapter().validate_detection()

        assert result == {"valid": True, "context": "detection", "errors": [], "warnings": []}

    def test_validate_detection_lists_available_labels_for_unknown_label(self) -> None:
        """Unknown toxic labels fail validation, listing the unknown names and the model's labels."""
        result = _make_detection_adapter(toxic_labels=("LABEL_1", "toxic")).validate_detection()

        assert result["valid"] is False
        assert result["errors"] == [
            f"toxic_labels ['toxic'] are not labels of model '{_CLASSIFIER}'. Available labels: ['LABEL_0', 'LABEL_1']"
        ]

    def test_validate_detection_requires_toxic_labels(self) -> None:
        """An empty toxic_labels fails validation without loading the model."""
        client = FakeClassificationClient(error=AssertionError("must not load"))

        result = _make_detection_adapter(client=client, toxic_labels=()).validate_detection()

        assert result["valid"] is False
        assert result["errors"] == [f"'toxic_labels' must name at least one label of model '{_CLASSIFIER}'"]

    def test_validate_detection_reports_model_load_error(self) -> None:
        """A model that cannot be loaded fails validation with the client's error message."""
        client = FakeClassificationClient(
            error=ConfigurationError(f"Failed to load Hugging Face model '{_CLASSIFIER}'")
        )

        result = _make_detection_adapter(client=client).validate_detection()

        assert result["valid"] is False
        assert result["errors"] == [f"Failed to load Hugging Face model '{_CLASSIFIER}'"]

    def test_validate_resolves_to_embedding_hook_not_detection(self) -> None:
        """Callers using the adapter for detection must call validate_detection() explicitly."""
        adapter = _make_detection_adapter()

        with patch.object(huggingface_adapter, "HuggingFaceLLMClient"):
            assert adapter.validate()["context"] == "embedding"

    # ------------------------------------------------------------------ lazy clients

    @pytest.mark.parametrize(
        ("model_name", "expected_hint"),
        [
            (
                ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID,
                "To use another classifier, set 'model_id' and 'toxic_labels' in 'hap_provider_config'",
            ),
            (_CLASSIFIER, None),
        ],
    )
    def test_detection_client_built_once_with_options_and_default_model_hint(
        self, model_name: str, expected_hint: str | None
    ) -> None:
        """The classifier client gets every detection option; only the default model gets the load hint."""
        with patch.object(huggingface_adapter, "HuggingFaceClassificationClient") as client_cls:
            client_cls.return_value.get_labels.return_value = ("LABEL_0", "LABEL_1")
            adapter = HuggingFaceAdapter(
                model_name=model_name,
                toxic_labels=("LABEL_1",),
                revision="abc123",
                activation="softmax",
                max_length=256,
                batch_size=8,
                device="cpu",
                local_files_only=True,
            )
            client_cls.assert_not_called()

            adapter.validate_detection()
            adapter.validate_detection()

        client_cls.assert_called_once_with(
            model_id=model_name,
            activation="softmax",
            max_length=256,
            batch_size=8,
            revision="abc123",
            device="cpu",
            local_files_only=True,
            load_error_hint=expected_hint,
        )

    def test_lazy_clients_are_not_rebuilt_after_another_thread_built_them(self) -> None:
        """The checks inside the lock keep the clients another thread created."""
        adapter = HuggingFaceAdapter(model_name=_CLASSIFIER, toxic_labels=("LABEL_1",))
        stand_in = _ClientsBuiltWhileWaiting(adapter=adapter)
        adapter.client_lock = stand_in  # type: ignore[assignment]

        with (
            patch.object(huggingface_adapter, "HuggingFaceLLMClient") as embedding_cls,
            patch.object(huggingface_adapter, "HuggingFaceClassificationClient") as detection_cls,
        ):
            assert adapter._get_embedding_client() is stand_in.embedding_client
            adapter.client = None
            adapter.detection_client = None
            assert adapter._get_detection_client() is stand_in.detection_client

        embedding_cls.assert_not_called()
        detection_cls.assert_not_called()
