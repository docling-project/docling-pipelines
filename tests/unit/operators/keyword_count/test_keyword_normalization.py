# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for keyword_normalization.py shared utilities."""

import pytest

from docpipe.core.operators.functional.keyword_normalization import (
    count_token_sequences,
    is_whole_word_match,
    normalize_unicode,
)

# ---------------------------------------------------------------------------
# normalize_unicode
# ---------------------------------------------------------------------------


def test_normalize_unicode_nfc():
    # Decomposed "é" (e + combining acute) → precomposed "é"
    decomposed = "e\u0301"
    result = normalize_unicode(decomposed, form="NFC")
    assert result == "\xe9"


def test_normalize_unicode_nfkc():
    # Full-width LATIN CAPITAL LETTER A (fullwidth) normalizes to ASCII 'A'
    result = normalize_unicode("\uff21", form="NFKC")
    assert result == "A"


def test_normalize_unicode_none():
    text = "e\u0301"
    result = normalize_unicode(text, form="none")
    assert result == text


# ---------------------------------------------------------------------------
# is_whole_word_match — boundary edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end", "expected"),
    [
        # exact word at start of string
        ("art party", 0, 3, True),
        # embedded - 'art' inside 'party'
        ("party art", 0, 3, False),  # 'par' — no: start=0, text[0-1] doesn't exist; end=3 → text[3]='t' → word char
        # standalone in the middle
        ("party art", 6, 9, True),
        # adjacent to non-word char
        ("(art)", 1, 4, True),
        # non-ASCII boundary: 'café' in 'cafés café'
        ("cafés café", 6, 10, True),  # second 'café', preceded by space, at end
        ("cafés café", 0, 4, False),  # 'café' in 'cafés' — followed by 's'
        # underscore is word char (Pc)
        ("id_1 id", 5, 7, True),
        ("id_1 id", 0, 2, False),  # 'id' in 'id_1' — followed by '_'
        # digit is word char
        ("id2 id", 4, 6, True),
        ("id2 id", 0, 2, False),  # 'id' in 'id2' — followed by '2'
        # document edges
        ("hello", 0, 5, True),
        # single char at edge
        ("a b", 0, 1, True),
        ("a b", 2, 3, True),
    ],
)
def test_is_whole_word_match(text, start, end, expected):
    assert is_whole_word_match(text=text, start=start, end=end) is expected


# ---------------------------------------------------------------------------
# count_token_sequences — overlap scenarios
# ---------------------------------------------------------------------------


def test_count_token_sequences_simple_match():
    assert (
        count_token_sequences(
            keyword_tokens=["go"],
            document_tokens=["go", "run", "go"],
            allow_overlapping=False,
        )
        == 2
    )


def test_count_token_sequences_no_match():
    assert (
        count_token_sequences(
            keyword_tokens=["run"],
            document_tokens=["walk", "jog"],
            allow_overlapping=False,
        )
        == 0
    )


def test_count_token_sequences_non_overlapping_phrase():
    # 'go go' in 'go go go' — non-overlapping: matches at 0, next start = 2, no room
    assert (
        count_token_sequences(
            keyword_tokens=["go", "go"],
            document_tokens=["go", "go", "go"],
            allow_overlapping=False,
        )
        == 1
    )


def test_count_token_sequences_overlapping_phrase():
    # 'go go' in 'go go go' — overlapping: matches at 0 and 1
    assert (
        count_token_sequences(
            keyword_tokens=["go", "go"],
            document_tokens=["go", "go", "go"],
            allow_overlapping=True,
        )
        == 2
    )


def test_count_token_sequences_empty_keyword():
    assert (
        count_token_sequences(
            keyword_tokens=[],
            document_tokens=["a", "b"],
            allow_overlapping=False,
        )
        == 0
    )


def test_count_token_sequences_keyword_longer_than_doc():
    assert (
        count_token_sequences(
            keyword_tokens=["a", "b", "c"],
            document_tokens=["a", "b"],
            allow_overlapping=False,
        )
        == 0
    )


def test_count_token_sequences_exact_phrase():
    # exact document match
    assert (
        count_token_sequences(
            keyword_tokens=["machine", "learning"],
            document_tokens=["machine", "learning"],
            allow_overlapping=False,
        )
        == 1
    )


def test_count_token_sequences_non_overlapping_aa():
    # 'a a' in 'aa a a' (tokenised): tokens ['a', 'a', 'a', 'a'] — non-overlapping finds 2
    tokens = ["a", "a", "a", "a"]
    assert (
        count_token_sequences(
            keyword_tokens=["a", "a"],
            document_tokens=tokens,
            allow_overlapping=False,
        )
        == 2
    )
