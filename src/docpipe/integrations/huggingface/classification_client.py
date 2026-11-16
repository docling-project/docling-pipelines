# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Local Hugging Face sequence-classification client.

Wraps the Hugging Face "text-classification" task for local models: it loads a
tokenizer/model pair, splits overlong character spans into token windows, and returns
per-label probabilities for each window.  It knows nothing about what the labels mean
(HAP, sentiment, ...) or about thresholds; callers decide that.

Design notes:
    - ``transformers`` and ``torch`` are imported lazily, so importing this module is
      cheap and never touches the network.
    - Models are cached once per process for each ``(model_id, revision, device)`` and
      shared by every client instance and thread.  Failed loads are not cached.
    - Inference on a shared model is serialized with a per-model lock, because fast
      tokenizers are not safe to use from several threads at once.
    - Repository code is never executed (``trust_remote_code=False``).
    - Text, spans and tokens are never logged or placed in error messages.
"""

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from docpipe.core.constants.constants import EnvironmentVariables, ServiceConstants
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.utils.core.strings import trim_whitespace_span
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# model.config.problem_type of multi-label classifiers; "auto" activation resolves to sigmoid for them.
MULTI_LABEL_PROBLEM_TYPE: Final[str] = "multi_label_classification"

_OFFLINE_ENV_VARS: Final[tuple[str, ...]] = (
    EnvironmentVariables.HF_HUB_OFFLINE,
    EnvironmentVariables.TRANSFORMERS_OFFLINE,
)
# Tokenizers report a huge sentinel as model_max_length when a model declares no maximum.
_UNBOUNDED_MODEL_MAX_LENGTH: Final[int] = 1_000_000
# Encoded with and without special tokens to learn which tokens the model wraps around one sequence.
_SPECIAL_TOKEN_PROBE: Final[str] = "probe"
# Padding ID for tokenizers that define none; padded positions are masked out either way.
_FALLBACK_PAD_TOKEN_ID: Final[int] = 0


@dataclass(frozen=True)
class TextWindow:
    """A character range of the source text that is scored as one model input.

    Attributes:
        start: Start offset in the source text (inclusive).
        end: End offset in the source text (exclusive).
        token_ids: The span's own token IDs for the range, without special tokens.  These are
            scored as they are; the window text is never tokenized again.
    """

    start: int
    end: int
    token_ids: tuple[int, ...]


@dataclass(frozen=True)
class SpecialTokens:
    """Token IDs a model expects around one sequence, and the ID used for padding.

    Attributes:
        prefix_ids: Tokens placed before the sequence, for example ``[CLS]`` or ``<s>``.
        suffix_ids: Tokens placed after the sequence, for example ``[SEP]`` or ``</s>``.
        pad_token_id: Token ID used to pad shorter rows of a batch.
    """

    prefix_ids: tuple[int, ...] = ()
    suffix_ids: tuple[int, ...] = ()
    pad_token_id: int = _FALLBACK_PAD_TOKEN_ID


@dataclass(frozen=True)
class WindowScores:
    """Label probabilities for one scored window of the source text.

    Attributes:
        start: Start offset in the source text (inclusive).
        end: End offset in the source text (exclusive).
        probabilities: Probability (0.0 - 1.0) for every model label, keyed by label name.
    """

    start: int
    end: int
    probabilities: dict[str, float]


@dataclass
class LoadedModel:
    """A tokenizer/model pair shared by all clients that use the same cache key.

    Attributes:
        tokenizer: Hugging Face fast tokenizer.
        model: Hugging Face sequence-classification model in eval mode.
        device: Device the model runs on.
        inference_lock: Serializes tokenization and forward passes on this model.
    """

    tokenizer: Any
    model: Any
    device: str
    inference_lock: threading.Lock = field(default_factory=threading.Lock)


class HuggingFaceClassificationClient:
    """Window-level text classification with a local Hugging Face model.

    Public API: ``load()``, ``get_labels()`` and ``score_spans()``.  The model is loaded
    on the first call to any of them; call ``load()`` at startup to surface
    configuration errors before any text is scored.  Defaults for ``activation``,
    ``max_length`` and ``batch_size`` are resolved by the caller, not here.

    ``loaded``, ``labels``, ``resolved_activation``, ``model_max_length``,
    ``special_tokens`` and ``max_window_tokens`` are set by ``load()`` and are only
    meaningful after it ran.
    """

    _models: ClassVar[dict[tuple[str, str | None, str], LoadedModel]] = {}
    _load_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        *,
        model_id: str,
        activation: str,
        max_length: int,
        batch_size: int,
        revision: str | None = None,
        device: str | None = None,
        local_files_only: bool = False,
        load_error_hint: str | None = None,
    ) -> None:
        """Validate options.  No model is loaded here.

        Args:
            model_id: Hugging Face model repository id.
            activation: ``softmax``, ``sigmoid`` or ``auto`` (sigmoid for multi-label models).
            max_length: Maximum model tokens per window (capped at the model maximum).
            batch_size: Number of windows per forward pass.
            revision: Model commit, tag or branch; ``None`` uses the Hub's default branch.
            device: ``auto``/``None``, ``cpu``, ``cuda`` or ``mps``.
            local_files_only: Load only from the local Hugging Face cache.
            load_error_hint: Optional sentence appended to model load errors.

        Raises:
            ConfigurationError: If an option is invalid.
        """
        errors = HuggingFaceClassificationClient._check_options(
            model_id=model_id,
            activation=activation,
            max_length=max_length,
            batch_size=batch_size,
            device=device,
        )
        if errors:
            raise ConfigurationError("; ".join(errors))
        self.model_id = model_id
        self.revision = revision
        self.activation = activation
        self.max_length = max_length
        self.batch_size = batch_size
        self.device = device
        self.local_files_only = local_files_only
        self.load_error_hint = load_error_hint
        self.loaded: LoadedModel | None = None
        self.labels: tuple[str, ...] = ()
        self.resolved_activation = ServiceConstants.HUGGINGFACE_ACTIVATION_SOFTMAX
        self.model_max_length = max_length
        self.special_tokens = SpecialTokens()
        self.max_window_tokens = max_length
        self.instance_lock = threading.Lock()

    # ------------------------------------------------------------------ public API

    def load(self) -> LoadedModel:
        """Load the model (at most once per process) and resolve labels, activation and window size.

        Returns:
            The shared tokenizer/model pair.

        Raises:
            ConfigurationError: If the device, model or tokenizer is invalid.
        """
        if self.loaded is not None:
            return self.loaded
        with self.instance_lock:
            if self.loaded is not None:
                return self.loaded
            device = HuggingFaceClassificationClient._resolve_device(device=self.device)
            loaded = HuggingFaceClassificationClient._get_or_load(
                model_id=self.model_id,
                revision=self.revision,
                device=device,
                local_files_only=self.local_files_only,
                hint=self.load_error_hint,
            )
            config = loaded.model.config
            self.labels = HuggingFaceClassificationClient._ordered_labels(id2label=dict(config.id2label))
            self.resolved_activation = HuggingFaceClassificationClient._resolve_activation(
                activation=self.activation, problem_type=getattr(config, "problem_type", None)
            )
            self.model_max_length = HuggingFaceClassificationClient._cap_max_length(
                max_length=self.max_length, model_max_length=getattr(loaded.tokenizer, "model_max_length", None)
            )
            self.special_tokens = HuggingFaceClassificationClient._learn_special_tokens(
                model_id=self.model_id, tokenizer=loaded.tokenizer
            )
            special_count = len(self.special_tokens.prefix_ids) + len(self.special_tokens.suffix_ids)
            self.max_window_tokens = max(1, self.model_max_length - special_count)
            self.loaded = loaded
            return loaded

    def get_labels(self) -> tuple[str, ...]:
        """Return the model's label names ordered by class index, loading the model if needed.

        Raises:
            ConfigurationError: If the model cannot be loaded.
        """
        self.load()
        return self.labels

    def score_spans(self, *, text: str, spans: Sequence[tuple[int, int]]) -> list[WindowScores]:
        """Score character spans of ``text``, splitting spans longer than the model limit.

        Holds the per-model inference lock while windowing and scoring.

        Args:
            text: Source text.
            spans: ``(start, end)`` offsets into ``text`` to score.

        Returns:
            One ``WindowScores`` per window, in span order; a span that fits the model
            limit yields exactly one window with the span's offsets.

        Raises:
            ConfigurationError: If the model cannot be loaded.
            Exception: Tokenizer or model errors during scoring.
        """
        if not spans:
            return []
        loaded = self.load()
        started = time.perf_counter()
        with loaded.inference_lock:
            windows = [
                window
                for start, end in spans
                for window in HuggingFaceClassificationClient._window_span(
                    tokenizer=loaded.tokenizer,
                    text=text,
                    start=start,
                    end=end,
                    max_window_tokens=self.max_window_tokens,
                )
            ]
            scores = HuggingFaceClassificationClient._score_windows(
                loaded=loaded,
                windows=windows,
                labels=self.labels,
                activation=self.resolved_activation,
                batch_size=self.batch_size,
                special_tokens=self.special_tokens,
            )
        logger.debug(
            "Scored %s windows from %s spans with %s in %.1f ms",
            len(windows),
            len(spans),
            self.model_id,
            (time.perf_counter() - started) * 1000,
        )
        return scores

    # ------------------------------------------------------------------ option checks

    @staticmethod
    def _check_options(
        *,
        model_id: str,
        activation: str,
        max_length: int,
        batch_size: int,
        device: str | None,
    ) -> list[str]:
        """Return error messages for invalid options, without loading anything."""
        errors: list[str] = []
        if not model_id or not isinstance(model_id, str):
            errors.append("model_id must be a non-empty string")
        if activation not in ServiceConstants.HUGGINGFACE_ACTIVATIONS:
            errors.append(
                f"activation must be one of {list(ServiceConstants.HUGGINGFACE_ACTIVATIONS)}, got {activation!r}"
            )
        for name, value in (("max_length", max_length), ("batch_size", batch_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"{name} must be a positive integer, got {value!r}")
        if device is not None and device not in ServiceConstants.HUGGINGFACE_DEVICES:
            errors.append(f"device must be one of {list(ServiceConstants.HUGGINGFACE_DEVICES)}, got {device!r}")
        return errors

    # ------------------------------------------------------------------ loading

    @classmethod
    def _get_or_load(
        cls,
        *,
        model_id: str,
        revision: str | None,
        device: str,
        local_files_only: bool,
        hint: str | None,
    ) -> LoadedModel:
        """Return the cached model for the key, loading it at most once per process.

        Raises:
            ConfigurationError: If the model cannot be loaded.
        """
        key = (model_id, revision, device)
        loaded = cls._models.get(key)
        if loaded is not None:
            return loaded
        with cls._load_lock:
            loaded = cls._models.get(key)
            if loaded is not None:
                return loaded
            started = time.perf_counter()
            try:
                loaded = cls._load_model(
                    model_id=model_id, revision=revision, device=device, local_files_only=local_files_only
                )
            except ConfigurationError:
                raise
            except Exception as exc:
                raise ConfigurationError(
                    cls._load_error_message(
                        model_id=model_id,
                        revision=revision,
                        local_files_only=local_files_only,
                        exc=exc,
                        hint=hint,
                    )
                ) from exc
            cls._models[key] = loaded
            logger.info(
                "Loaded Hugging Face classification model %s (revision=%s, device=%s) in %.2fs",
                model_id,
                revision or "default",
                device,
                time.perf_counter() - started,
            )
            return loaded

    @staticmethod
    def _load_model(*, model_id: str, revision: str | None, device: str, local_files_only: bool) -> LoadedModel:
        """Load tokenizer and model from the Hub or local cache, never running repository code.

        Raises:
            ConfigurationError: If the tokenizer is not a fast tokenizer.
            Exception: Whatever ``from_pretrained`` raises (wrapped by the caller).
        """
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        # B615 accepts only a literal commit hash; revision comes from config (the default model is pinned to a
        # commit in HuggingFaceHAPConfig, other models when the user sets revision) and remote code never runs.
        tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
            model_id, revision=revision, local_files_only=local_files_only, trust_remote_code=False
        )
        if not getattr(tokenizer, "is_fast", False):
            raise ConfigurationError(
                f"Model '{model_id}' does not provide a fast tokenizer, which is required to map "
                "scores back to character offsets. Choose a model that ships a tokenizer.json or whose "
                "tokenizer transformers can convert to a fast one (for example BERT or RoBERTa models)."
            )
        model = AutoModelForSequenceClassification.from_pretrained(  # nosec B615 - same revision as the tokenizer
            model_id, revision=revision, local_files_only=local_files_only, trust_remote_code=False
        )
        model.to(device)
        model.eval()
        return LoadedModel(tokenizer=tokenizer, model=model, device=device)

    @staticmethod
    def _load_error_message(
        *, model_id: str, revision: str | None, local_files_only: bool, exc: Exception, hint: str | None
    ) -> str:
        """Build the startup error for a model or tokenizer that cannot be loaded."""
        revision_text = f" at revision '{revision}'" if revision else ""
        message = f"Failed to load Hugging Face model '{model_id}'{revision_text}: {type(exc).__name__}: {exc}"
        if HuggingFaceClassificationClient._is_offline(local_files_only=local_files_only):
            revision_arg = f" --revision {revision}" if revision else ""
            message += (
                ". Offline mode is enabled (local_files_only or HF_HUB_OFFLINE), so the model must already be in "
                f"the local Hugging Face cache. Pre-fetch it with: huggingface-cli download {model_id}{revision_arg}"
            )
        if hint:
            message += f". {hint}"
        return message

    @staticmethod
    def _is_offline(*, local_files_only: bool) -> bool:
        """Return True when local-only loading is requested or Hugging Face offline mode is on."""
        from docpipe.utils.infrastructure.config import get_env_bool

        return local_files_only or any(get_env_bool(name, default=False) for name in _OFFLINE_ENV_VARS)

    @staticmethod
    def _resolve_device(*, device: str | None) -> str:
        """Resolve ``None``/``auto`` to ``cuda`` when available, else ``cpu``.

        ``mps`` is used only when requested explicitly.

        Raises:
            ConfigurationError: If ``cuda`` is requested but not available.
        """
        import torch

        if device in (None, ServiceConstants.HUGGINGFACE_DEVICE_AUTO):
            return (
                ServiceConstants.HUGGINGFACE_DEVICE_CUDA
                if torch.cuda.is_available()
                else ServiceConstants.HUGGINGFACE_DEVICE_CPU
            )
        if device == ServiceConstants.HUGGINGFACE_DEVICE_CUDA and not torch.cuda.is_available():
            raise ConfigurationError("device 'cuda' was requested but CUDA is not available")
        return str(device)

    @staticmethod
    def _resolve_activation(*, activation: str, problem_type: str | None) -> str:
        """Resolve ``auto`` to ``sigmoid`` for multi-label models and ``softmax`` otherwise."""
        if activation != ServiceConstants.HUGGINGFACE_ACTIVATION_AUTO:
            return activation
        return (
            ServiceConstants.HUGGINGFACE_ACTIVATION_SIGMOID
            if problem_type == MULTI_LABEL_PROBLEM_TYPE
            else ServiceConstants.HUGGINGFACE_ACTIVATION_SOFTMAX
        )

    @staticmethod
    def _cap_max_length(*, max_length: int, model_max_length: Any) -> int:
        """Cap ``max_length`` at the tokenizer's declared model maximum, when it has one."""
        if isinstance(model_max_length, int) and 0 < model_max_length < _UNBOUNDED_MODEL_MAX_LENGTH:
            return min(max_length, model_max_length)
        return max_length

    @staticmethod
    def _ordered_labels(*, id2label: dict[Any, str]) -> tuple[str, ...]:
        """Return label names ordered by class index."""
        by_index = {int(index): str(label) for index, label in id2label.items()}
        return tuple(by_index[index] for index in sorted(by_index))

    @staticmethod
    def _learn_special_tokens(*, model_id: str, tokenizer: Any) -> SpecialTokens:
        """Learn the tokens the model wraps around one sequence by encoding a probe with and without them.

        Fast tokenizers in ``transformers`` 5 no longer expose a helper that adds special
        tokens to existing token IDs, so they are read off the difference between the two
        encodings: whatever comes before the probe's own tokens is the prefix, whatever
        comes after is the suffix.

        Raises:
            ConfigurationError: If the probe's tokens do not appear unchanged between the special tokens.
        """
        with_special = [int(token) for token in tokenizer(_SPECIAL_TOKEN_PROBE, add_special_tokens=True)["input_ids"]]
        probe = [int(token) for token in tokenizer(_SPECIAL_TOKEN_PROBE, add_special_tokens=False)["input_ids"]]
        for offset in range(len(with_special) - len(probe) + 1):
            if with_special[offset : offset + len(probe)] == probe:
                pad_token_id = getattr(tokenizer, "pad_token_id", None)
                return SpecialTokens(
                    prefix_ids=tuple(with_special[:offset]),
                    suffix_ids=tuple(with_special[offset + len(probe) :]),
                    pad_token_id=_FALLBACK_PAD_TOKEN_ID if pad_token_id is None else int(pad_token_id),
                )
        raise ConfigurationError(
            f"Could not determine the special tokens of model '{model_id}': its tokenizer does not wrap a "
            "sequence in fixed start and end tokens. Choose a model whose tokenizer only adds special tokens "
            "before and after the text (for example BERT or RoBERTa models)."
        )

    # ------------------------------------------------------------------ windowing and scoring

    @staticmethod
    def _window_span(*, tokenizer: Any, text: str, start: int, end: int, max_window_tokens: int) -> list[TextWindow]:
        """Cut one span into consecutive, non-overlapping token windows.

        The span is tokenized once and each window carries its share of those token IDs,
        so the model later scores exactly the tokens counted here.  Windows end where a
        new word starts, so no word is split across windows, unless a single word has
        more tokens than ``max_window_tokens``.  The fast tokenizer's ``offset_mapping``
        maps each window back to character offsets inside the span.  A span that fits is
        returned as one window with the span's own offsets; windows without any text
        (whitespace or zero-width tokens only) are dropped.

        Args:
            tokenizer: Hugging Face fast tokenizer.
            text: Source text.
            start: Span start offset in ``text``.
            end: Span end offset in ``text``.
            max_window_tokens: Maximum tokens per window, without special tokens.

        Returns:
            Windows in order; their offsets lie inside ``[start, end)``.
        """
        span_text = text[start:end]
        encoding = tokenizer(span_text, add_special_tokens=False, return_offsets_mapping=True)
        token_ids = tuple(int(token) for token in encoding["input_ids"])
        offsets = [(int(token_start), int(token_end)) for token_start, token_end in encoding["offset_mapping"]]
        if len(token_ids) <= max_window_tokens:
            return [TextWindow(start=start, end=end, token_ids=token_ids)]

        word_starts = HuggingFaceClassificationClient._word_starts(text=span_text, offsets=offsets)
        windows: list[TextWindow] = []
        first = 0
        while first < len(token_ids):
            limit = first + max_window_tokens
            if limit >= len(token_ids):
                last = len(token_ids)
            else:
                # Cut before the latest word start that fits; cut inside a word only when it alone exceeds the budget.
                last = next((index for index in range(limit, first, -1) if word_starts[index]), limit)
            text_offsets = [
                (token_start, token_end) for token_start, token_end in offsets[first:last] if token_end > token_start
            ]
            if text_offsets:
                window_start, window_end = trim_whitespace_span(
                    text=text, start=start + text_offsets[0][0], end=start + text_offsets[-1][1]
                )
                if window_start < window_end:
                    windows.append(TextWindow(start=window_start, end=window_end, token_ids=token_ids[first:last]))
            first = last
        return windows

    @staticmethod
    def _word_starts(*, text: str, offsets: Sequence[tuple[int, int]]) -> list[bool]:
        """Return, for each token, whether a window may start at it without splitting a word.

        A token starts a word when whitespace separates it from the previous token: a gap
        between their offsets (most tokenizers leave spaces out of tokens) or whitespace at
        the boundary (tokenizers that emit whitespace as tokens of their own).

        Args:
            text: The tokenized text.
            offsets: Character offsets of each token in ``text``.
        """
        starts = [True] * len(offsets)
        for index in range(1, len(offsets)):
            previous_end = offsets[index - 1][1]
            token_start = offsets[index][0]
            starts[index] = (
                token_start > previous_end
                or text[previous_end - 1 : previous_end].isspace()
                or text[token_start : token_start + 1].isspace()
            )
        return starts

    @staticmethod
    def _score_windows(
        *,
        loaded: LoadedModel,
        windows: Sequence[TextWindow],
        labels: Sequence[str],
        activation: str,
        batch_size: int,
        special_tokens: SpecialTokens,
    ) -> list[WindowScores]:
        """Run the forward passes for already-windowed input, in length-sorted batches.

        Args:
            loaded: Tokenizer/model pair (the caller holds its inference lock).
            windows: Windows to score.
            labels: Label names ordered by class index.
            activation: ``softmax`` or ``sigmoid``.
            batch_size: Windows per forward pass.
            special_tokens: Tokens wrapped around each window and the padding ID.

        Returns:
            One ``WindowScores`` per window, in the order of ``windows``.
        """
        import torch

        order = sorted(range(len(windows)), key=lambda window_index: len(windows[window_index].token_ids))
        results: list[WindowScores | None] = [None] * len(windows)
        with torch.inference_mode():
            for batch_start in range(0, len(order), batch_size):
                batch = order[batch_start : batch_start + batch_size]
                input_ids, attention_mask = HuggingFaceClassificationClient._model_inputs(
                    rows=[windows[window_index].token_ids for window_index in batch], special_tokens=special_tokens
                )
                logits = (
                    loaded.model(input_ids=input_ids.to(loaded.device), attention_mask=attention_mask.to(loaded.device))
                    .logits.float()
                    .cpu()
                )
                if activation == ServiceConstants.HUGGINGFACE_ACTIVATION_SIGMOID:
                    probabilities = torch.sigmoid(logits)
                else:
                    probabilities = torch.softmax(logits, dim=-1)
                for row, window_index in enumerate(batch):
                    window = windows[window_index]
                    values = probabilities[row].tolist()
                    results[window_index] = WindowScores(
                        start=window.start,
                        end=window.end,
                        probabilities={label: float(values[index]) for index, label in enumerate(labels)},
                    )
        return [result for result in results if result is not None]

    @staticmethod
    def _model_inputs(*, rows: Sequence[Sequence[int]], special_tokens: SpecialTokens) -> tuple[Any, Any]:
        """Wrap each row of token IDs in the model's special tokens and pad the batch to its longest row.

        Args:
            rows: Token IDs of each window, without special tokens.
            special_tokens: Tokens wrapped around each row and the padding ID.

        Returns:
            ``input_ids`` and ``attention_mask`` tensors; padded positions have mask 0.
        """
        import torch

        sequences = [[*special_tokens.prefix_ids, *row, *special_tokens.suffix_ids] for row in rows]
        width = max(len(sequence) for sequence in sequences)
        input_ids = [sequence + [special_tokens.pad_token_id] * (width - len(sequence)) for sequence in sequences]
        attention_mask = [[1] * len(sequence) + [0] * (width - len(sequence)) for sequence in sequences]
        return torch.tensor(input_ids, dtype=torch.long), torch.tensor(attention_mask, dtype=torch.long)
