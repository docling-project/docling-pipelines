# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""HuggingFace adapter for LLM operations.

One consolidated adapter for the Hugging Face provider (see
``docs/guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md``):

- ``LLMEmbeddingPort``: embeddings with local sentence-transformers models or the
  Hugging Face Inference API, through ``HuggingFaceLLMClient``.
- ``TextDetectionPort``: local HAP detection with a sequence-classification model,
  through ``HuggingFaceClassificationClient``.  The text is split into sentence spans
  whose offsets point into the original text; each span whose highest probability
  among ``toxic_labels`` reaches the threshold is reported as a ``has_HAP`` detection.

Each capability's client is created lazily, on first use or in its ``validate_*`` hook,
so an adapter built for one capability never loads the other capability's model.
"""

import functools
import re
import threading
from collections.abc import Sequence
from typing import Any, Final

from docpipe.core.constants.constants import LLMConstants, ProviderConstants, ServiceConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.text_detection_port import TextDetectionPort
from docpipe.integrations.huggingface.classification_client import (
    HuggingFaceClassificationClient,
    WindowScores,
)
from docpipe.integrations.huggingface.client import HuggingFaceLLMClient
from docpipe.utils.core.strings import trim_whitespace_span
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PIIHAP = OperatorConstants.PIIHAP
_CONFIG = OperatorConstants.Config
_VALIDATION = LLMConstants.ValidationKeys

# Lines are split first: Docling Markdown has headings, list items and table rows without
# sentence-final punctuation.
_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\r\n]+")
_DEFAULT_MODEL_LOAD_HINT: Final[str] = (
    f"To use another classifier, set '{_CONFIG.MODEL_ID}' and '{_CONFIG.TOXIC_LABELS}' "
    f"in '{_PIIHAP.HAP_PROVIDER_CONFIG_KEY}'"
)


class HuggingFaceAdapter(LLMEmbeddingPort, TextDetectionPort):
    """Adapter for Hugging Face embedding and HAP text detection operations.

    ``model_name`` names the embedding model or the classification model, depending on
    the capability the adapter is built for (as for ``WatsonXAdapter``).  The detection
    options (``revision`` to ``local_files_only``) are used only for text detection.

    Because both ports define a template ``validate()``, ``validate()`` resolves to the
    embedding hook (``LLMEmbeddingPort`` is the first base).  Callers that use the
    adapter for detection call ``validate_detection()`` directly.
    """

    def __init__(
        self,
        *,
        model_name: str,
        use_local: bool = True,
        api_token: str | None = None,
        device: str | None = None,
        batch_size: int = ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
        revision: str | None = None,
        toxic_labels: Sequence[str] = (),
        activation: str = ServiceConstants.HUGGINGFACE_ACTIVATION_AUTO,
        max_length: int = ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MAX_LENGTH,
        local_files_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Store the options.  No client and no model is created here.

        Args:
            model_name: Hugging Face model id (embedding model, or classifier for detection).
            use_local: Embeddings only: local sentence-transformers (True) or the Inference API (False).
            api_token: Embeddings only: Hugging Face API token for API inference.
            device: Device for local inference ('auto', 'cpu', 'cuda', 'mps', or None for auto).
            batch_size: Texts (embeddings) or spans (detection) per forward pass.
            revision: Detection only: model commit, tag or branch (None = Hub default branch).
            toxic_labels: Detection only: class labels whose highest probability is the span score.
            activation: Detection only: 'softmax', 'sigmoid' or 'auto'.
            max_length: Detection only: maximum model tokens per scored window.
            local_files_only: Detection only: load the classifier from the local cache only.
            **kwargs: Additional embedding client options.
        """
        self.model_name = model_name
        self.use_local = use_local
        self.api_token = api_token
        self.device = device
        self.batch_size = batch_size
        self.embedding_options = kwargs
        self.revision = revision
        self.toxic_labels = tuple(toxic_labels)
        self.activation = activation
        self.max_length = max_length
        self.local_files_only = local_files_only
        self.client: HuggingFaceLLMClient | None = None
        self.detection_client: HuggingFaceClassificationClient | None = None
        self.client_lock = threading.Lock()

    # ------------------------------------------------------------------ embeddings

    def generate_embeddings(self, *, text: str) -> list[float]:
        """Generate embeddings for a single text.

        Args:
            text: Input text to embed

        Returns:
            List of floats representing the embedding vector
        """
        return self._get_embedding_client().generate_embeddings(text)

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts to embed

        Returns:
            List of embedding vectors, one per input text
        """
        return self._get_embedding_client().generate_embeddings_batch(texts)

    def get_embedding_batch_size(self) -> int:
        """Return the number of texts encoded per call, without creating the client.

        Concurrency keeps the port default of 1: local inference is CPU/GPU bound and
        the sentence-transformers model is not shared safely across threads.
        """
        return self.batch_size

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for this model.

        Returns:
            Dimension of embedding vectors
        """
        return HuggingFaceLLMClient.get_embedding_dimension(self.model_name)

    def validate_embedding(self) -> dict[str, Any]:
        """Create the embedding client so a bad model or token fails at startup.

        Returns:
            Validation result with ``valid``, ``context``, ``errors`` and ``warnings``.
        """
        try:
            self._get_embedding_client()
        except Exception as exc:
            return HuggingFaceAdapter._validation_result(
                context=LLMConstants.ValidationContexts.EMBEDDING,
                errors=[f"Failed to initialise Hugging Face embedding model '{self.model_name}': {exc}"],
            )
        return HuggingFaceAdapter._validation_result(context=LLMConstants.ValidationContexts.EMBEDDING, errors=[])

    # ------------------------------------------------------------------ text detection

    def detect(self, *, text: str, detection_types: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        """Detect HAP sentence spans in ``text``.

        Args:
            text: Text to analyse.  Whitespace-only text yields no detections.
            detection_types: ``None`` or ``["hap"]``; anything else is unsupported.
            **kwargs: ``detectors`` - ``{"hap": {"threshold": float}}`` (default threshold
                ``ServiceConstants.DEFAULT_HUGGINGFACE_HAP_THRESHOLD``).  Other detector keys
                are unsupported.

        Returns:
            ``{"success", "detections", "error"}``.  Scoring errors return
            ``success: False`` with an error naming only the exception class and model,
            because tokenizer and model errors can echo the input.
        """
        detectors = kwargs.get(_PIIHAP.DETECTORS_FIELD)
        unsupported = HuggingFaceAdapter._unsupported_detectors(detection_types=detection_types, detectors=detectors)
        if unsupported:
            return HuggingFaceAdapter._detection_result(
                error=(
                    f"Unsupported detector(s) {unsupported}: the '{ProviderConstants.HUGGINGFACE}' text detection "
                    f"provider supports only '{_PIIHAP.HAP_FIELD_NAME}'"
                )
            )
        threshold = HuggingFaceAdapter._hap_threshold(detectors=detectors)
        spans = HuggingFaceAdapter._segment_text(text=text)
        try:
            window_scores = self._get_detection_client().score_spans(text=text, spans=spans)
            detections = self._to_detections(text=text, window_scores=window_scores, threshold=threshold)
        except Exception as exc:
            logger.error("HAP scoring failed with model %s: %s", self.model_name, type(exc).__name__)
            return HuggingFaceAdapter._detection_result(
                error=f"{type(exc).__name__} while scoring with model '{self.model_name}'"
            )
        logger.debug(
            "HAP detection with %s: %s spans, %s windows, %s flagged",
            self.model_name,
            len(spans),
            len(window_scores),
            len(detections),
        )
        return HuggingFaceAdapter._detection_result(detections=detections)

    def validate_detection(self) -> dict[str, Any]:
        """Load the classifier and check ``toxic_labels`` against its labels (fail-fast).

        Returns:
            Validation result with ``valid``, ``context``, ``errors`` and ``warnings``.
        """
        context = LLMConstants.ValidationContexts.DETECTION
        if not self.toxic_labels:
            return HuggingFaceAdapter._validation_result(
                context=context,
                errors=[f"'{_CONFIG.TOXIC_LABELS}' must name at least one label of model '{self.model_name}'"],
            )
        try:
            labels = self._get_detection_client().get_labels()
        except Exception as exc:
            return HuggingFaceAdapter._validation_result(context=context, errors=[str(exc)])
        unknown = [label for label in self.toxic_labels if label not in labels]
        if unknown:
            return HuggingFaceAdapter._validation_result(
                context=context,
                errors=[
                    f"{_CONFIG.TOXIC_LABELS} {unknown} are not labels of model '{self.model_name}'. "
                    f"Available labels: {list(labels)}"
                ],
            )
        return HuggingFaceAdapter._validation_result(context=context, errors=[])

    def _to_detections(
        self, *, text: str, window_scores: Sequence[WindowScores], threshold: float
    ) -> list[dict[str, Any]]:
        """Turn scored windows into ``has_HAP`` detection dicts for windows at or above ``threshold``."""
        detections: list[dict[str, Any]] = []
        for window in window_scores:
            label, score = max(
                ((label, window.probabilities[label]) for label in self.toxic_labels),
                key=lambda label_score: label_score[1],
            )
            if score < threshold:
                continue
            detections.append(
                {
                    _PIIHAP.DETECTION_FIELD: _PIIHAP.HAS_HAP_LABEL,
                    _PIIHAP.DETECTION_TYPE_FIELD: _PIIHAP.HAP_FIELD_NAME,
                    _PIIHAP.SCORE_FIELD: score,
                    _PIIHAP.START_FIELD: window.start,
                    _PIIHAP.END_FIELD: window.end,
                    _PIIHAP.TEXT_FIELD: text[window.start : window.end],
                    _PIIHAP.EVIDENCES_FIELD: [
                        {
                            _PIIHAP.EVIDENCE_SOURCE_FIELD: ProviderConstants.HUGGINGFACE,
                            _PIIHAP.EVIDENCE_MODEL_ID_FIELD: self.model_name,
                            _PIIHAP.EVIDENCE_LABEL_FIELD: label,
                        }
                    ],
                }
            )
        return detections

    # ------------------------------------------------------------------ lazy clients

    def _get_embedding_client(self) -> HuggingFaceLLMClient:
        """Return the embedding client, creating it on first use (thread-safe)."""
        if self.client is None:
            with self.client_lock:
                if self.client is None:
                    self.client = HuggingFaceLLMClient(
                        model_name=self.model_name,
                        use_local=self.use_local,
                        api_token=self.api_token,
                        device=self.device,
                        batch_size=self.batch_size,
                        **self.embedding_options,
                    )
        return self.client

    def _get_detection_client(self) -> HuggingFaceClassificationClient:
        """Return the classification client, creating it on first use (thread-safe).

        Creating the client loads no model; the model loads on first scoring or label lookup.
        """
        if self.detection_client is None:
            with self.client_lock:
                if self.detection_client is None:
                    is_default_model = self.model_name == ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID
                    self.detection_client = HuggingFaceClassificationClient(
                        model_id=self.model_name,
                        activation=self.activation,
                        max_length=self.max_length,
                        batch_size=self.batch_size,
                        revision=self.revision,
                        device=self.device,
                        local_files_only=self.local_files_only,
                        load_error_hint=_DEFAULT_MODEL_LOAD_HINT if is_default_model else None,
                    )
        return self.detection_client

    # ------------------------------------------------------------------ helpers

    @staticmethod
    @functools.cache
    def _sentence_tokenizer() -> Any:
        """Return a shared untrained Punkt tokenizer (needs no ``nltk.download``, so no network)."""
        from nltk.tokenize.punkt import PunktSentenceTokenizer

        return PunktSentenceTokenizer()

    @staticmethod
    def _segment_text(*, text: str) -> list[tuple[int, int]]:
        """Split ``text`` into sentence spans at line breaks and sentence boundaries.

        The text is never rewritten, so ``text[start:end]`` is always the span.
        Surrounding whitespace is excluded and empty spans are dropped.

        Args:
            text: Source text.

        Returns:
            ``(start, end)`` character offsets into ``text``, in reading order.
        """
        spans: list[tuple[int, int]] = []
        for line_match in _LINE_PATTERN.finditer(text):
            line = line_match.group()
            if not line.strip():
                continue
            offset = line_match.start()
            for line_start, line_end in HuggingFaceAdapter._sentence_tokenizer().span_tokenize(line):
                start, end = trim_whitespace_span(text=text, start=offset + line_start, end=offset + line_end)
                if start < end:
                    spans.append((start, end))
        return spans

    @staticmethod
    def _unsupported_detectors(*, detection_types: list[str] | None, detectors: Any) -> list[str]:
        """Return requested detector names other than ``hap``."""
        requested = list(detection_types or [])
        if isinstance(detectors, dict):
            requested.extend(detectors)
        return sorted({name for name in requested if name != _PIIHAP.HAP_FIELD_NAME})

    @staticmethod
    def _hap_threshold(*, detectors: Any) -> float:
        """Read ``detectors["hap"]["threshold"]``, falling back to the default HAP threshold."""
        settings = detectors.get(_PIIHAP.HAP_FIELD_NAME) if isinstance(detectors, dict) else None
        if isinstance(settings, dict) and settings.get(_PIIHAP.THRESHOLD_FIELD) is not None:
            return float(settings[_PIIHAP.THRESHOLD_FIELD])
        return ServiceConstants.DEFAULT_HUGGINGFACE_HAP_THRESHOLD

    @staticmethod
    def _detection_result(
        *, detections: list[dict[str, Any]] | None = None, error: str | None = None
    ) -> dict[str, Any]:
        """Build the ``TextDetectionPort`` result dict."""
        return {
            _PIIHAP.SUCCESS_FIELD: error is None,
            _PIIHAP.DETECTIONS_FIELD: detections or [],
            _PIIHAP.ERROR_FIELD: error,
        }

    @staticmethod
    def _validation_result(*, context: str, errors: list[str]) -> dict[str, Any]:
        """Build a validation result dict."""
        return {
            _VALIDATION.VALID: not errors,
            _VALIDATION.CONTEXT: context,
            _VALIDATION.ERRORS: errors,
            _VALIDATION.WARNINGS: [],
        }
