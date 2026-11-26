# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for LiteralMatcher, StemMatcher, and LemmaMatcher."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.functional.keyword_normalization import (
    LiteralMatcher,
    StemMatcher,
    _is_valid_model_identifier,
)

# ===========================================================================
# LiteralMatcher
# ===========================================================================


class TestLiteralMatcherBasic:
    def _make(self, keywords, *, case_sensitive=False, whole_word=True, norm="NFC", overlapping=False):
        return LiteralMatcher(
            keywords=keywords,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            unicode_normalization=norm,
            allow_overlapping=overlapping,
        )

    def test_metacharacters_are_literal(self):
        m = self._make(["a.b"])
        # "axb" should NOT match; "a.b" should
        counts = m.count(text="axb a.b", keywords=["a.b"])
        assert counts == [1]

    def test_case_insensitive_default(self):
        m = self._make(["Contract"])
        counts = m.count(text="CONTRACT contract Contract", keywords=["Contract"])
        assert counts == [3]

    def test_case_sensitive(self):
        m = self._make(["Contract"], case_sensitive=True)
        counts = m.count(text="contract Contract", keywords=["Contract"])
        assert counts == [1]

    def test_phrase_no_whitespace_variant(self):
        # spec: "machine-learning", "machine\nlearning", "machine  learning" → 0
        m = self._make(["machine learning"])
        text = "machine-learning machine\nlearning machine  learning"
        counts = m.count(text=text, keywords=["machine learning"])
        assert counts == [0]

    def test_whole_word_embedded_match_excluded(self):
        m = self._make(["art"])
        counts = m.count(text="party art", keywords=["art"])
        assert counts == [1]

    def test_whole_word_false_allows_embedded(self):
        m = self._make(["art"], whole_word=False)
        counts = m.count(text="party art", keywords=["art"])
        assert counts == [2]

    def test_whole_word_non_ascii_boundary(self):
        m = self._make(["café"])
        counts = m.count(text="cafés café", keywords=["café"])
        assert counts == [1]

    def test_whole_word_underscore_digit_are_word_chars(self):
        m = self._make(["id"])
        counts = m.count(text="id_1 id2 id", keywords=["id"])
        assert counts == [1]

    def test_non_overlapping(self):
        # "ana" in "banana": only one non-overlapping match
        m = self._make(["ana"], whole_word=False)
        counts = m.count(text="banana", keywords=["ana"])
        assert counts == [1]

    def test_overlapping(self):
        # "ana" in "banana": two overlapping matches
        m = self._make(["ana"], whole_word=False, overlapping=True)
        counts = m.count(text="banana", keywords=["ana"])
        assert counts == [2]

    def test_multiple_keywords(self):
        m = self._make(["machine", "machine learning"])
        counts = m.count(text="machine learning", keywords=["machine", "machine learning"])
        assert counts == [1, 1]

    def test_empty_text_returns_zero_counts(self):
        m = self._make(["hello"])
        counts = m.count(text="", keywords=["hello"])
        assert counts == [0]

    def test_unicode_nfc_normalization(self):
        # Keyword with precomposed "é", document with decomposed equivalent
        composed = "\xe9"
        decomposed = "e\u0301"
        m = self._make([composed], norm="NFC")
        counts = m.count(text=decomposed + " tail", keywords=[composed])
        assert counts == [1]

    def test_unicode_nfkc_fullwidth(self):
        # Full-width Latin capital A should match 'A' under NFKC
        m = self._make(["A"], norm="NFKC", whole_word=False)
        counts = m.count(text="\uff21", keywords=["A"])
        assert counts == [1]

    def test_unicode_nfc_fullwidth_not_matched(self):
        # Full-width Latin capital A should NOT match 'A' under NFC
        m = self._make(["A"], norm="NFC", whole_word=False)
        counts = m.count(text="\uff21", keywords=["A"])
        assert counts == [0]

    def test_canonical_keyword_case_insensitive(self):
        m = self._make(["Contract"])
        # Both "contract" and "CONTRACT" should have the same canonical key
        assert m.canonical_keyword("contract") == m.canonical_keyword("CONTRACT")

    def test_canonical_keyword_case_sensitive_differs(self):
        m = self._make(["Contract"], case_sensitive=True)
        assert m.canonical_keyword("contract") != m.canonical_keyword("CONTRACT")


# ===========================================================================
# StemMatcher
# ===========================================================================


class TestStemMatcher:
    def _make(self, keywords, *, language="english", norm="NFC", overlapping=False):
        return StemMatcher(
            keywords=keywords,
            language=language,
            unicode_normalization=norm,
            allow_overlapping=overlapping,
        )

    def test_inflections_match(self):
        # spec: "He runs and ran while running" with keyword "running" counts 2
        # (runs and running share a stem; ran does not)
        m = self._make(["running"])
        counts = m.count(text="He runs and ran while running", keywords=["running"])
        assert counts == [2]

    def test_whitespace_insensitive_phrase(self):
        # "machine   learning" should match "machine learning" phrase
        m = self._make(["machine learning"])
        counts = m.count(text="machine   learning", keywords=["machine learning"])
        assert counts == [1]

    def test_punctuation_significant(self):
        # "machine-learning" should NOT match "machine learning"
        m = self._make(["machine learning"])
        counts = m.count(text="machine-learning", keywords=["machine learning"])
        assert counts == [0]

    def test_parenthesized_keyword(self):
        # "(draft)." → tokens: '(', 'draft', ')', '.' — keyword "(draft)" → same
        m = self._make(["(draft)"])
        counts = m.count(text="(draft).", keywords=["(draft)"])
        assert counts == [1]

    def test_symbol_keyword_cxx(self):
        # "C++," → tokens: 'C', '+', '+', ',' — keyword "C++" → 'c', '+', '+'
        m = self._make(["C++"])
        counts = m.count(text="C++,", keywords=["C++"])
        assert counts == [1]

    def test_overlapping_tokens(self):
        # "go go" overlapping in "go go go" → 2 matches
        m = self._make(["go go"], overlapping=True)
        counts = m.count(text="go go go", keywords=["go go"])
        assert counts == [2]

    def test_non_overlapping_tokens(self):
        m = self._make(["go go"])
        counts = m.count(text="go go go", keywords=["go go"])
        assert counts == [1]

    def test_canonical_keyword_collision_stems(self):
        m = self._make(["run", "runs"])
        # Both should produce the same canonical key (same stem)
        assert m.canonical_keyword("run") == m.canonical_keyword("runs")

    def test_stem_cleanup(self):
        m = self._make(["run"])
        m.count(text="running", keywords=["run"])
        assert len(m._stem_cache) > 0
        m.cleanup()
        assert len(m._stem_cache) == 0

    def test_empty_text(self):
        m = self._make(["run"])
        counts = m.count(text="", keywords=["run"])
        assert counts == [0]


# ===========================================================================
# LemmaMatcher — tested via mock pipeline (no real spaCy model installed)
# ===========================================================================


def _make_mock_spacy(identity_lemmas: bool = True):
    """Create a mock spaCy module that produces a minimal nlp object.

    The mock nlp callable tokenizes by whitespace and optionally assigns
    identity lemmas (token.lemma_ == token.text).

    Args:
        identity_lemmas: When True, each token's lemma equals its surface text.

    Returns:
        Mock spaCy module and a factory function for nlp().
    """

    class FakeToken:
        def __init__(self, text, lemma=""):
            self.text = text
            self.lemma_ = lemma or text
            self.is_space = text.strip() == ""

    class FakeDoc:
        def __init__(self, tokens):
            self._tokens = tokens

        def __iter__(self):
            return iter(self._tokens)

    class FakeNlp:
        max_length = 1_000_000

        def __call__(self, text):
            # Minimal tokenization: split by whitespace, then split punctuation
            import re as _re

            raw = _re.findall(r"\w+|[^\w\s]|\s+", text)
            tokens = []
            for t in raw:
                tokens.append(FakeToken(text=t, lemma=t))
            return FakeDoc(tokens)

    return FakeNlp()


def _patch_spacy_and_entry_points(fake_nlp, model_name="en_test"):
    """Create context managers that replace spaCy and entry-points.

    Args:
        fake_nlp: The mock nlp object to return from load_model_from_package.
        model_name: The model name to report as installed.

    Returns:
        Tuple of two context managers (spacy_ctx, ep_ctx).
    """
    mock_spacy = MagicMock()
    mock_spacy.util.load_model_from_package.return_value = fake_nlp

    mock_ep = MagicMock()
    mock_ep.name = model_name

    spacy_ctx = patch.dict(sys.modules, {"spacy": mock_spacy, "spacy.util": mock_spacy.util})
    ep_ctx = patch(
        "docpipe.core.operators.functional.keyword_normalization._installed_spacy_model_names",
        return_value={model_name},
    )
    return spacy_ctx, ep_ctx


class TestLemmaMatcher:
    """Tests for LemmaMatcher using a controlled mock pipeline."""

    def _make(self, keywords, model_name="en_test", fake_nlp=None, norm="NFC", overlapping=False):
        from docpipe.core.operators.functional.keyword_normalization import LemmaMatcher

        if fake_nlp is None:
            fake_nlp = _make_mock_spacy()

        spacy_ctx, ep_ctx = _patch_spacy_and_entry_points(fake_nlp, model_name)
        with spacy_ctx, ep_ctx:
            return LemmaMatcher(
                keywords=keywords,
                lemmatizer_model=model_name,
                unicode_normalization=norm,
                allow_overlapping=overlapping,
            )

    def test_basic_match(self):
        # Identity lemmas: "run" matches "run"
        m = self._make(["run"])
        fake_nlp = _make_mock_spacy()
        spacy_ctx, ep_ctx = _patch_spacy_and_entry_points(fake_nlp)
        with spacy_ctx, ep_ctx:
            counts = m.count(text="run walk run", keywords=["run"])
        assert counts == [2]

    def test_cleanup_releases_pipeline(self):
        m = self._make(["run"])
        assert m._nlp is not None
        m.cleanup()
        assert m._nlp is None

    def test_cleanup_idempotent(self):
        m = self._make(["run"])
        m.cleanup()
        m.cleanup()  # second call must not raise

    def test_overlapping_tokens(self):
        m = self._make(["go go"], overlapping=True)
        fake_nlp = _make_mock_spacy()
        spacy_ctx, ep_ctx = _patch_spacy_and_entry_points(fake_nlp)
        with spacy_ctx, ep_ctx:
            counts = m.count(text="go go go", keywords=["go go"])
        assert counts == [2]

    def test_invalid_model_identifier_rejected(self):
        from docpipe.core.operators.functional.keyword_normalization import LemmaMatcher

        fake_nlp = _make_mock_spacy()
        spacy_ctx, ep_ctx = _patch_spacy_and_entry_points(fake_nlp)
        with spacy_ctx, ep_ctx, pytest.raises(ValueError, match="plain Python identifier"):
            LemmaMatcher(
                keywords=["run"],
                lemmatizer_model="./models/en",
                unicode_normalization="NFC",
                allow_overlapping=False,
            )

    def test_uninstalled_model_rejected(self):
        from docpipe.core.operators.functional.keyword_normalization import LemmaMatcher

        fake_nlp = _make_mock_spacy()
        spacy_ctx, ep_ctx = _patch_spacy_and_entry_points(fake_nlp, model_name="en_actual")
        with spacy_ctx, ep_ctx, pytest.raises(ValueError, match="not installed"):
            LemmaMatcher(
                keywords=["run"],
                lemmatizer_model="en_other_model",
                unicode_normalization="NFC",
                allow_overlapping=False,
            )


# ===========================================================================
# _is_valid_model_identifier
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("en_core_web_sm", True),
        ("my_model_123", True),
        ("_private", True),
        ("./models/en", False),
        ("http://example.com", False),
        ("blank:en", False),
        ("some.package.name", False),
        ("", False),
        ("123abc", False),
    ],
)
def test_is_valid_model_identifier(name, expected):
    assert _is_valid_model_identifier(name) is expected
