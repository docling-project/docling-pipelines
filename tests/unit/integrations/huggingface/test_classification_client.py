# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the local Hugging Face sequence-classification client.

No model is downloaded: ``_load_model`` (or ``from_pretrained``) is patched with a fake
word-level fast tokenizer and a fake model that decodes the token IDs it receives and
returns fixed logits per decoded text, or with a real WordPiece tokenizer built in memory.
"""

import itertools
import math
import re
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
import torch
import transformers

from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.integrations.huggingface.classification_client import (
    HuggingFaceClassificationClient,
    LoadedModel,
    SpecialTokens,
)

_MODEL_ID = "org/fake-classifier"
_WORD = re.compile(r"\S+")
# Like SentencePiece tokenizers, also emits whitespace runs as their own tokens.
_WORD_OR_WHITESPACE = re.compile(r"\S+|\s+")


_FAKE_PAD_ID, _FAKE_CLS_ID, _FAKE_SEP_ID = 0, 1, 2
_FAKE_FIRST_TOKEN_ID = 3


class FakeTokenizer:
    """Regex-based stand-in for a Hugging Face fast tokenizer: one token per pattern match."""

    is_fast = True
    pad_token_id: int | None = _FAKE_PAD_ID

    def __init__(self, *, model_max_length: int = 512, token_pattern: re.Pattern[str] = _WORD) -> None:
        """Store limits and start an empty vocabulary that grows as text is tokenized."""
        self.model_max_length = model_max_length
        self.token_pattern = token_pattern
        self.vocab: dict[str, int] = {}

    def __call__(self, text: str, *, add_special_tokens: bool = True, **_: Any) -> dict[str, Any]:
        """Return token IDs and offsets, wrapping the IDs in [CLS] and [SEP] when special tokens are requested."""
        matches = list(self.token_pattern.finditer(text))
        input_ids = [self.vocab.setdefault(match.group(), _FAKE_FIRST_TOKEN_ID + len(self.vocab)) for match in matches]
        if add_special_tokens:
            input_ids = [_FAKE_CLS_ID, *input_ids, _FAKE_SEP_ID]
        return {"input_ids": input_ids, "offset_mapping": [(match.start(), match.end()) for match in matches]}

    def decode(self, token_ids: list[int]) -> str:
        """Join the tokens for ``token_ids`` with single spaces."""
        tokens = {token_id: token for token, token_id in self.vocab.items()}
        return " ".join(tokens[token_id] for token_id in token_ids)


class FakeModel:
    """Sequence-classification stand-in returning fixed logits per decoded input text."""

    def __init__(
        self,
        *,
        tokenizer: FakeTokenizer,
        logits_by_text: dict[str, list[float]],
        id2label: dict[int, str],
        problem_type: str | None = None,
    ) -> None:
        """Store the logits table and model config, and record every scored batch."""
        self.tokenizer = tokenizer
        self.logits_by_text = logits_by_text
        self.config = SimpleNamespace(id2label=id2label, problem_type=problem_type)
        self.batches: list[list[str]] = []

    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor, **_: Any) -> SimpleNamespace:
        """Decode each row without special and padding tokens and return the logits for that text."""
        texts = [
            self.tokenizer.decode(
                [token for token, keep in zip(row, mask, strict=True) if keep and token >= _FAKE_FIRST_TOKEN_ID]
            )
            for row, mask in zip(input_ids.tolist(), attention_mask.tolist(), strict=True)
        ]
        self.batches.append(texts)
        default = [0.0] * len(self.config.id2label)
        rows = [self.logits_by_text.get(text, default) for text in texts]
        return SimpleNamespace(logits=torch.tensor(rows, dtype=torch.float32))


@pytest.fixture(autouse=True)
def empty_model_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own empty process-wide model cache."""
    monkeypatch.setattr(HuggingFaceClassificationClient, "_models", {})
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def _make_loaded(
    *,
    logits_by_text: dict[str, list[float]] | None = None,
    id2label: dict[int, str] | None = None,
    problem_type: str | None = None,
    model_max_length: int = 512,
) -> LoadedModel:
    """Build a LoadedModel around the fake tokenizer and model."""
    tokenizer = FakeTokenizer(model_max_length=model_max_length)
    model = FakeModel(
        tokenizer=tokenizer,
        logits_by_text=logits_by_text or {},
        id2label=id2label or {0: "LABEL_0", 1: "LABEL_1"},
        problem_type=problem_type,
    )
    return LoadedModel(tokenizer=tokenizer, model=model, device="cpu")


def _make_client(**overrides: Any) -> HuggingFaceClassificationClient:
    """Build a client with required options filled in."""
    options: dict[str, Any] = {
        "model_id": _MODEL_ID,
        "activation": "auto",
        "max_length": 512,
        "batch_size": 32,
        "device": "cpu",
    }
    options.update(overrides)
    return HuggingFaceClassificationClient(**options)


def _spans_of(text: str, *parts: str) -> list[tuple[int, int]]:
    """Return the (start, end) offsets of each part in text."""
    return [(text.index(part), text.index(part) + len(part)) for part in parts]


# ---------------------------------------------------------------------- options


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"model_id": ""}, "model_id must be a non-empty string"),
        ({"activation": "relu"}, "activation must be one of"),
        ({"max_length": 0}, "max_length must be a positive integer"),
        ({"batch_size": -1}, "batch_size must be a positive integer"),
        ({"batch_size": True}, "batch_size must be a positive integer"),
        ({"device": "tpu"}, "device must be one of"),
    ],
)
def test_client_init_rejects_invalid_option(overrides: dict[str, Any], expected: str) -> None:
    """Invalid options raise ConfigurationError naming the option."""
    with pytest.raises(ConfigurationError, match=expected):
        _make_client(**overrides)


def test_client_init_loads_nothing(mocker: Any) -> None:
    """Constructing a client does not load a model."""
    load_model = mocker.patch.object(HuggingFaceClassificationClient, "_load_model")
    _make_client()
    load_model.assert_not_called()


# ---------------------------------------------------------------------- windowing


def test_window_span_returns_span_when_it_fits() -> None:
    """A span within the token limit is one window with the span's own offsets."""
    text = "Intro. You are a worthless idiot. Bye."
    start, end = _spans_of(text, "You are a worthless idiot.")[0]
    windows = HuggingFaceClassificationClient._window_span(
        tokenizer=FakeTokenizer(), text=text, start=start, end=end, max_window_tokens=10
    )
    assert [(window.start, window.end, len(window.token_ids)) for window in windows] == [(start, end, 5)]


@pytest.mark.parametrize("max_window_tokens", [1, 3, 4, 9])
def test_window_span_splits_long_span_into_covering_windows(max_window_tokens: int) -> None:
    """Overlong spans become ordered, non-overlapping windows inside the span covering every token."""
    prefix = "Header line\n"
    sentence = "one two three four five six seven eight nine ten"
    text = prefix + sentence + "\nfooter"
    start, end = len(prefix), len(prefix) + len(sentence)

    windows = HuggingFaceClassificationClient._window_span(
        tokenizer=FakeTokenizer(), text=text, start=start, end=end, max_window_tokens=max_window_tokens
    )

    assert len(windows) == math.ceil(10 / max_window_tokens)
    assert all(start <= window.start < window.end <= end for window in windows)
    assert all(left.end <= right.start for left, right in itertools.pairwise(windows))
    covered_words = [word for window in windows for word in text[window.start : window.end].split()]
    assert covered_words == sentence.split()
    assert all(len(window.token_ids) <= max_window_tokens for window in windows)


@pytest.mark.parametrize(
    ("max_window_tokens", "expected_windows"),
    [
        # Whitespace-only windows trim to nothing and are dropped.
        (1, ["a", "b", "c"]),
        # Windows ending in a whitespace token are trimmed back to the word.
        (2, ["a", "b", "c"]),
        # Windows starting with a whitespace token are trimmed forward to the word.
        (3, ["a  b", "c"]),
    ],
)
def test_window_span_trims_whitespace_tokens_from_windows(max_window_tokens: int, expected_windows: list[str]) -> None:
    """Windows never start or end on whitespace, and whitespace-only windows are dropped."""
    text = "a  b  c"
    tokenizer = FakeTokenizer(token_pattern=_WORD_OR_WHITESPACE)

    windows = HuggingFaceClassificationClient._window_span(
        tokenizer=tokenizer, text=text, start=0, end=len(text), max_window_tokens=max_window_tokens
    )

    assert [text[window.start : window.end] for window in windows] == expected_windows


def test_window_span_drops_windows_of_zero_width_tokens() -> None:
    """A window holding only tokens without characters (like SentencePiece word markers) is dropped."""
    text = "a b c"
    tokenizer = FakeTokenizer(token_pattern=re.compile(r"\S+|(?=\s)"))

    windows = HuggingFaceClassificationClient._window_span(
        tokenizer=tokenizer, text=text, start=0, end=len(text), max_window_tokens=1
    )

    assert [text[window.start : window.end] for window in windows] == ["a", "b", "c"]


def test_score_spans_windows_by_model_max_length(mocker: Any) -> None:
    """max_length is capped at model_max_length minus special tokens before windowing."""
    loaded = _make_loaded(model_max_length=6)
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)
    text = "a b c d e f g h i j"
    client = _make_client(max_length=512)

    scores = client.score_spans(text=text, spans=[(0, len(text))])

    assert client.model_max_length == 6
    assert client.max_window_tokens == 4
    assert [text[score.start : score.end] for score in scores] == ["a b c d", "e f g h", "i j"]


# ---------------------------------------------------------------------- scoring


def test_score_spans_returns_softmax_probabilities_per_label(mocker: Any) -> None:
    """Softmax probabilities are returned for every label, keyed by label name."""
    text = "Thanks for the report.\nYou are a worthless idiot."
    toxic = "You are a worthless idiot."
    loaded = _make_loaded(logits_by_text={toxic: [0.0, math.log(4.0)]})
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)

    scores = _make_client().score_spans(text=text, spans=_spans_of(text, "Thanks for the report.", toxic))

    assert [text[score.start : score.end] for score in scores] == ["Thanks for the report.", toxic]
    assert scores[0].probabilities == pytest.approx({"LABEL_0": 0.5, "LABEL_1": 0.5})
    assert scores[1].probabilities == pytest.approx({"LABEL_0": 0.2, "LABEL_1": 0.8})


def test_score_spans_applies_sigmoid_independently_per_label(mocker: Any) -> None:
    """Sigmoid scores each label independently, so probabilities need not sum to one."""
    text = "Some insulting text."
    loaded = _make_loaded(
        logits_by_text={text: [0.0, 0.0, math.log(9.0)]},
        id2label={0: "toxicity", 1: "insult", 2: "threat"},
    )
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)

    scores = _make_client(activation="sigmoid").score_spans(text=text, spans=[(0, len(text))])

    assert scores[0].probabilities == pytest.approx({"toxicity": 0.5, "insult": 0.5, "threat": 0.9})


@pytest.mark.parametrize(
    ("problem_type", "expected_activation"),
    [
        ("multi_label_classification", "sigmoid"),
        ("single_label_classification", "softmax"),
        (None, "softmax"),
    ],
)
def test_load_resolves_auto_activation_from_problem_type(
    mocker: Any, problem_type: str | None, expected_activation: str
) -> None:
    """auto activation becomes sigmoid only for multi-label models."""
    mocker.patch.object(
        HuggingFaceClassificationClient, "_load_model", return_value=_make_loaded(problem_type=problem_type)
    )
    client = _make_client(activation="auto")

    client.load()

    assert client.resolved_activation == expected_activation


def test_score_spans_restores_span_order_across_length_sorted_batches(mocker: Any) -> None:
    """Windows are batched shortest first but returned in the original span order."""
    text = "a b c d. e. f g."
    loaded = _make_loaded()
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)
    spans = _spans_of(text, "a b c d.", "e.", "f g.")

    scores = _make_client(batch_size=1).score_spans(text=text, spans=spans)

    assert [(score.start, score.end) for score in scores] == spans
    assert loaded.model.batches == [["e."], ["f g."], ["a b c d."]]


def test_score_spans_returns_empty_list_without_loading_for_no_spans(mocker: Any) -> None:
    """No spans means no model load and no scores."""
    load_model = mocker.patch.object(HuggingFaceClassificationClient, "_load_model")

    assert _make_client().score_spans(text="   ", spans=[]) == []
    load_model.assert_not_called()


def test_get_labels_orders_labels_by_class_index(mocker: Any) -> None:
    """Labels come back ordered by class index, not by dict order."""
    mocker.patch.object(
        HuggingFaceClassificationClient,
        "_load_model",
        return_value=_make_loaded(id2label={1: "toxic", 0: "clean"}),
    )

    assert _make_client().get_labels() == ("clean", "toxic")


# ---------------------------------------------------------------------- loading and cache


def test_load_runs_once_across_concurrent_threads(mocker: Any) -> None:
    """Eight threads loading the same model trigger a single load."""
    loaded = _make_loaded()

    def slow_load(**_: Any) -> LoadedModel:
        time.sleep(0.05)
        return loaded

    load_model = mocker.patch.object(HuggingFaceClassificationClient, "_load_model", side_effect=slow_load)
    clients = [_make_client() for _ in range(8)]
    threads = [threading.Thread(target=client.load) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert load_model.call_count == 1
    assert all(client.loaded is loaded for client in clients)


def test_load_is_a_no_op_when_instance_already_loaded(mocker: Any) -> None:
    """Calling load() again on a loaded client neither reloads nor re-resolves."""
    load_model = mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=_make_loaded())
    resolve_device = mocker.spy(HuggingFaceClassificationClient, "_resolve_device")
    client = _make_client()

    client.load()
    client.load()
    client.get_labels()

    assert load_model.call_count == 1
    assert resolve_device.call_count == 1


class _LoadFinishedWhileWaiting:
    """Instance-lock stand-in that simulates another thread finishing load() while this one waited."""

    def __init__(self, *, client: HuggingFaceClassificationClient, loaded: LoadedModel) -> None:
        """Store the client and the model the other thread loaded."""
        self.client = client
        self.loaded = loaded

    def __enter__(self) -> "_LoadFinishedWhileWaiting":
        """Mark the client loaded at the moment the lock is acquired."""
        self.client.loaded = self.loaded
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Release nothing; the stand-in holds no real lock."""


def test_load_returns_when_another_thread_loaded_while_waiting_for_lock(mocker: Any) -> None:
    """The check inside the instance lock stops a second load after another thread won the race."""
    load_model = mocker.patch.object(HuggingFaceClassificationClient, "_load_model")
    client = _make_client()
    loaded_by_other_thread = _make_loaded()
    client.instance_lock = _LoadFinishedWhileWaiting(client=client, loaded=loaded_by_other_thread)  # type: ignore[assignment]

    client.load()

    load_model.assert_not_called()
    assert client.loaded is loaded_by_other_thread


def test_load_caches_each_revision_separately(mocker: Any) -> None:
    """The same model at two revisions is loaded twice, each revision once."""
    load_model = mocker.patch.object(
        HuggingFaceClassificationClient, "_load_model", side_effect=lambda **_: _make_loaded()
    )

    first_a = _make_client(revision="rev-a")
    second_a = _make_client(revision="rev-a")
    only_b = _make_client(revision="rev-b")
    for client in (first_a, second_a, only_b):
        client.load()

    assert load_model.call_count == 2
    assert first_a.loaded is second_a.loaded
    assert first_a.loaded is not only_b.loaded


def test_load_retries_after_failed_load(mocker: Any) -> None:
    """A failed load is not cached, so the next attempt loads again."""
    loaded = _make_loaded()
    load_model = mocker.patch.object(
        HuggingFaceClassificationClient, "_load_model", side_effect=[OSError("connection reset"), loaded]
    )

    with pytest.raises(ConfigurationError, match="Failed to load Hugging Face model 'org/fake-classifier'"):
        _make_client().load()
    retry_client = _make_client()
    retry_client.load()

    assert load_model.call_count == 2
    assert retry_client.loaded is loaded


@pytest.mark.parametrize(
    ("local_files_only", "env_var"),
    [(True, None), (False, "HF_HUB_OFFLINE"), (False, "TRANSFORMERS_OFFLINE")],
)
def test_load_error_says_offline_mode_when_enabled(
    mocker: Any, monkeypatch: pytest.MonkeyPatch, local_files_only: bool, env_var: str | None
) -> None:
    """With local_files_only or an offline env var, the load error names the model and offline mode."""
    if env_var:
        monkeypatch.setenv(env_var, "1")
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", side_effect=OSError("not cached"))

    with pytest.raises(ConfigurationError) as error:
        _make_client(local_files_only=local_files_only, revision="abc123").load()

    assert "org/fake-classifier" in str(error.value)
    assert "Offline mode is enabled" in str(error.value)
    assert "huggingface-cli download org/fake-classifier --revision abc123" in str(error.value)


def test_load_error_omits_offline_note_when_online(mocker: Any) -> None:
    """Without offline mode, the load error does not mention it."""
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", side_effect=OSError("404"))

    with pytest.raises(ConfigurationError) as error:
        _make_client().load()

    assert "Offline mode" not in str(error.value)


def test_load_error_appends_hint(mocker: Any) -> None:
    """A load_error_hint is appended to the load error."""
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", side_effect=OSError("gone"))
    hint = "Set model_id and toxic_labels in hap_provider_config to use another classifier."

    with pytest.raises(ConfigurationError, match=re.escape(hint)):
        _make_client(load_error_hint=hint).load()


def test_load_model_rejects_slow_tokenizer_without_loading_model(mocker: Any) -> None:
    """A model without a fast tokenizer is rejected before its weights are loaded."""
    tokenizer_load = mocker.patch.object(
        transformers.AutoTokenizer, "from_pretrained", return_value=SimpleNamespace(is_fast=False)
    )
    model_load = mocker.patch.object(transformers.AutoModelForSequenceClassification, "from_pretrained")

    with pytest.raises(ConfigurationError, match="'org/fake-classifier' does not provide a fast tokenizer"):
        _make_client().load()

    model_load.assert_not_called()
    assert tokenizer_load.call_args.kwargs["trust_remote_code"] is False


def test_load_model_never_trusts_remote_code(mocker: Any) -> None:
    """Tokenizer and model are loaded with trust_remote_code=False and the requested revision."""
    tokenizer = FakeTokenizer()
    model = mocker.Mock()
    model.config = SimpleNamespace(id2label={0: "LABEL_0", 1: "LABEL_1"}, problem_type=None)
    tokenizer_load = mocker.patch.object(transformers.AutoTokenizer, "from_pretrained", return_value=tokenizer)
    model_load = mocker.patch.object(
        transformers.AutoModelForSequenceClassification, "from_pretrained", return_value=model
    )

    _make_client(revision="abc123", local_files_only=True).load()

    for loader in (tokenizer_load, model_load):
        assert loader.call_args.kwargs == {
            "revision": "abc123",
            "local_files_only": True,
            "trust_remote_code": False,
        }
    model.eval.assert_called_once()


@pytest.mark.parametrize(("device", "expected"), [(None, "cpu"), ("auto", "cpu"), ("cpu", "cpu"), ("mps", "mps")])
def test_resolve_device_uses_cpu_when_cuda_unavailable(mocker: Any, device: str | None, expected: str) -> None:
    """auto/None fall back to cpu without CUDA; explicit devices are kept."""
    mocker.patch.object(torch.cuda, "is_available", return_value=False)

    assert HuggingFaceClassificationClient._resolve_device(device=device) == expected


def test_resolve_device_rejects_cuda_when_unavailable(mocker: Any) -> None:
    """Requesting cuda without CUDA is a configuration error."""
    mocker.patch.object(torch.cuda, "is_available", return_value=False)

    with pytest.raises(ConfigurationError, match="CUDA is not available"):
        HuggingFaceClassificationClient._resolve_device(device="cuda")


@pytest.mark.parametrize(
    ("model_max_length", "expected"),
    [(256, 256), (1024, 512), (int(1e30), 512), (None, 512)],
)
def test_cap_max_length_respects_declared_model_maximum(model_max_length: Any, expected: int) -> None:
    """max_length is capped only by a real, declared model maximum."""
    assert (
        HuggingFaceClassificationClient._cap_max_length(max_length=512, model_max_length=model_max_length) == expected
    )


# ---------------------------------------------------------------------- real subword tokenizer

# A real WordPiece vocabulary with multi-token words. A window cut inside such a word changes how
# the window's text re-tokenizes (e.g. "thought" + "##lessness" vs "less" + "##ness"), so these
# tests check what the model actually receives, not only the window offsets.
_WORDPIECE_VOCAB = {
    "[PAD]": 0,
    "[UNK]": 1,
    "[CLS]": 2,
    "[SEP]": 3,
    "x": 4,
    "hello": 5,
    "world": 6,
    "idiot": 7,
    "thought": 8,
    "less": 9,
    "##lessness": 10,
    "##ness": 11,
    "care": 12,
    "un": 13,
    "##believ": 14,
    "##able": 15,
    ",": 16,
    ".": 17,
}
_WORDPIECE_SPECIAL_IDS = {0, 2, 3}
_IDIOT_ID = _WORDPIECE_VOCAB["idiot"]

_WINDOWING_TEXTS = {
    "subword_word_before_last": "x " * 9 + "thoughtlessness " + "x " * 8 + "idiot",
    "subword_heavy": "unbelievable carelessness hello thoughtlessness world unbelievable idiot",
    "single_token_words": "hello world x x x hello world x idiot",
    "punctuation": "hello, world. unbelievable carelessness, idiot.",
}
_WINDOW_BUDGETS = (1, 2, 3, 5, 10)


def _wordpiece_tokenizer(*, model_max_length: int = 512) -> transformers.PreTrainedTokenizerFast:
    """Build a real WordPiece fast tokenizer in memory (no download)."""
    from tokenizers import Tokenizer, models, pre_tokenizers, processors

    backend = Tokenizer(models.WordPiece(vocab=_WORDPIECE_VOCAB, unk_token="[UNK]"))
    backend.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    backend.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)]
    )
    return transformers.PreTrainedTokenizerFast(
        tokenizer_object=backend,
        unk_token="[UNK]",
        pad_token="[PAD]",
        cls_token="[CLS]",
        sep_token="[SEP]",
        model_max_length=model_max_length,
    )


def _span_tokens(text: str) -> tuple[list[int], list[tuple[int, int]]]:
    """Return the WordPiece token IDs and character offsets of ``text``."""
    encoding = _wordpiece_tokenizer()(text, add_special_tokens=False, return_offsets_mapping=True)
    return list(encoding["input_ids"]), [(int(start), int(end)) for start, end in encoding["offset_mapping"]]


def _word_sizes(offsets: list[tuple[int, int]]) -> list[int]:
    """For each token, the token count of the whitespace-delimited word it belongs to."""
    words: list[list[int]] = []
    for index, (start, _) in enumerate(offsets):
        if index == 0 or start > offsets[index - 1][1]:
            words.append([])
        words[-1].append(index)
    return [len(word) for word in words for _ in word]


class _IdiotFlaggingModel:
    """Stub classifier that flags any input containing the ``idiot`` token and records its inputs."""

    def __init__(self) -> None:
        """Expose a binary-label config and an empty record of scored token IDs."""
        self.config = SimpleNamespace(id2label={0: "LABEL_0", 1: "LABEL_1"}, problem_type=None)
        self.scored_token_ids: list[list[int]] = []

    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor, **_: Any) -> SimpleNamespace:
        """Record each row's non-special tokens and return logits flagging rows with ``idiot``."""
        for row, mask in zip(input_ids.tolist(), attention_mask.tolist(), strict=True):
            self.scored_token_ids.append(
                [token for token, keep in zip(row, mask, strict=True) if keep and token not in _WORDPIECE_SPECIAL_IDS]
            )
        flagged = (input_ids == _IDIOT_ID).any(dim=1)
        logits = torch.where(flagged[:, None], torch.tensor([0.0, 10.0]), torch.tensor([10.0, 0.0]))
        return SimpleNamespace(logits=logits)


def _wordpiece_client(mocker: Any, *, budget: int) -> tuple[HuggingFaceClassificationClient, _IdiotFlaggingModel]:
    """Build a client whose real WordPiece tokenizer allows ``budget`` tokens per window."""
    model = _IdiotFlaggingModel()
    tokenizer = _wordpiece_tokenizer(model_max_length=budget + 2)  # + [CLS] and [SEP]
    loaded = LoadedModel(tokenizer=tokenizer, model=model, device="cpu")
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)
    return _make_client(activation="softmax", max_length=512), model


def test_load_learns_special_tokens_and_window_budget_from_tokenizer(mocker: Any) -> None:
    """The tokens wrapped around a sequence come from the tokenizer and shrink the window budget."""
    client, _ = _wordpiece_client(mocker, budget=10)

    client.load()

    assert client.special_tokens == SpecialTokens(
        prefix_ids=(_WORDPIECE_VOCAB["[CLS]"],), suffix_ids=(_WORDPIECE_VOCAB["[SEP]"],), pad_token_id=0
    )
    assert client.max_window_tokens == 10


def test_learn_special_tokens_falls_back_when_tokenizer_has_no_pad_token() -> None:
    """A tokenizer without a padding token gets the fallback padding ID; padded positions are masked anyway."""
    tokenizer = FakeTokenizer()
    tokenizer.pad_token_id = None

    special_tokens = HuggingFaceClassificationClient._learn_special_tokens(model_id=_MODEL_ID, tokenizer=tokenizer)

    assert special_tokens == SpecialTokens(prefix_ids=(_FAKE_CLS_ID,), suffix_ids=(_FAKE_SEP_ID,), pad_token_id=0)


def test_load_rejects_tokenizer_whose_special_tokens_cannot_be_learned(mocker: Any) -> None:
    """A tokenizer that changes the text's own tokens when adding special tokens fails at load, not silently."""
    tokenizer = mocker.Mock(
        side_effect=lambda text, *, add_special_tokens: {"input_ids": [1, 2] if add_special_tokens else [3]}
    )
    loaded = LoadedModel(tokenizer=tokenizer, model=_IdiotFlaggingModel(), device="cpu")
    mocker.patch.object(HuggingFaceClassificationClient, "_load_model", return_value=loaded)

    with pytest.raises(ConfigurationError, match="Could not determine the special tokens"):
        _make_client().load()


@pytest.mark.parametrize("budget", _WINDOW_BUDGETS)
@pytest.mark.parametrize("text", _WINDOWING_TEXTS.values(), ids=_WINDOWING_TEXTS.keys())
def test_window_span_follows_windowing_rules(text: str, budget: int) -> None:
    """Windows cover every token once, fit the budget, start at word starts, and keep clean offsets."""
    _, offsets = _span_tokens(text)
    word_sizes = _word_sizes(offsets)

    windows = HuggingFaceClassificationClient._window_span(
        tokenizer=_wordpiece_tokenizer(), text=text, start=0, end=len(text), max_window_tokens=budget
    )

    tokens_per_window = [
        [index for index, (start, end) in enumerate(offsets) if window.start <= start and end <= window.end]
        for window in windows
    ]
    assert [index for indexes in tokens_per_window for index in indexes] == list(range(len(offsets)))
    assert all(len(indexes) <= budget for indexes in tokens_per_window)
    for indexes in tokens_per_window:
        first = indexes[0]
        starts_word = first == 0 or offsets[first][0] > offsets[first - 1][1]
        assert starts_word or word_sizes[first] > budget, text[offsets[first][0] :]
    assert all(left.end <= right.start for left, right in itertools.pairwise(windows))
    assert all(text[window.start : window.end] == text[window.start : window.end].strip() for window in windows)


@pytest.mark.parametrize("budget", _WINDOW_BUDGETS)
@pytest.mark.parametrize("text", _WINDOWING_TEXTS.values(), ids=_WINDOWING_TEXTS.keys())
def test_score_spans_gives_the_model_every_span_token_once(mocker: Any, text: str, budget: int) -> None:
    """The model receives exactly the span's tokens, each once, and no input exceeds the budget."""
    client, model = _wordpiece_client(mocker, budget=budget)
    span_token_ids, _ = _span_tokens(text)

    client.score_spans(text=text, spans=[(0, len(text))])

    assert all(len(window) <= budget for window in model.scored_token_ids)
    assert sorted(token for window in model.scored_token_ids for token in window) == sorted(span_token_ids)


@pytest.mark.parametrize(
    "text",
    [
        "idiot " + "x " * 22 + "x",
        "x " * 11 + "idiot " + "x " * 11 + "x",
        "x " * 23 + "idiot",
        "x " * 9 + "thoughtlessness " + "x " * 8 + "idiot",
        "x " * 8 + "unbelievable carelessness idiot " + "x " * 6 + "x",
    ],
    ids=["first", "middle", "last", "last_after_split_word", "after_split_words"],
)
def test_score_spans_detects_flagged_token_at_any_position(mocker: Any, text: str) -> None:
    """A flagged word is detected wherever it sits in a span longer than one window."""
    client, _ = _wordpiece_client(mocker, budget=10)

    scores = client.score_spans(text=text, spans=[(0, len(text))])

    flagged = [score for score in scores if score.probabilities["LABEL_1"] > 0.5]
    assert len(flagged) == 1
    assert "idiot" in text[flagged[0].start : flagged[0].end]


# ---------------------------------------------------------------------- import side effects


def test_import_does_not_load_torch_or_transformers() -> None:
    """Importing the client and the core Hugging Face adapter package stays lightweight."""
    code = (
        "import sys\n"
        "import docpipe.integrations.huggingface.classification_client\n"
        "import docpipe.core.adapters.huggingface\n"
        "print(sorted(name for name in ('torch', 'transformers', 'nltk') if name in sys.modules))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"
