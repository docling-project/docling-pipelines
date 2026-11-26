# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Matching engines and shared utilities for the keyword-count operator.

This module provides three matching engines:
- LiteralMatcher: RE2-backed literal search with Unicode normalization
- StemMatcher: Snowball stem tokenization with NLTK RegexpTokenizer
- LemmaMatcher: spaCy pipeline-based lemmatization

Shared utilities (pure functions without state) are @staticmethods on the
matcher base class and module-level helpers.

No imports from docpipe internals are needed; this module is fully testable
in isolation.
"""

import re
import unicodedata
from abc import ABC, abstractmethod
from typing import Any

# ---------------------------------------------------------------------------
# Pure shared utilities
# ---------------------------------------------------------------------------


def normalize_unicode(text: str, *, form: str) -> str:
    """Apply Unicode normalization to text.

    Args:
        text: Input text to normalize.
        form: Normalization form - "NFC", "NFKC", or "none".

    Returns:
        Normalized text, or the original text when form is "none".
    """
    if form == "none":
        return text
    # form is validated to be "NFC", "NFKC", or "none" by the operator config check.
    # Cast to satisfy mypy's Literal constraint.
    from typing import Literal, cast

    nf = cast(Literal["NFC", "NFD", "NFKC", "NFKD"], form)
    return unicodedata.normalize(nf, text)


def _is_word_char(ch: str) -> bool:
    """Return True when the character is a Unicode word character.

    Word characters are those with Unicode general category:
        - Letter (L*)
        - Mark / combining mark (M*)
        - Number (N*)
        - Connector punctuation (Pc, e.g. underscore)

    Args:
        ch: Single character to test.

    Returns:
        True if ch is a word character.
    """
    cat = unicodedata.category(ch)
    return cat.startswith(("L", "M", "N")) or cat == "Pc"


def is_whole_word_match(*, text: str, start: int, end: int) -> bool:
    """Test whether a code-point range in text satisfies whole-word boundaries.

    A match satisfies whole-word boundaries when:
    - The character immediately before ``start`` (if any) is not a word character.
    - The character immediately at ``end`` (if any) is not a word character.
    - Document start and end always satisfy the boundary condition.

    Args:
        text: Full document text (Unicode string).
        start: Start index (code-point offset, inclusive).
        end: End index (code-point offset, exclusive).

    Returns:
        True if the match satisfies whole-word boundaries.
    """
    if start > 0 and _is_word_char(text[start - 1]):
        return False
    if end < len(text) and _is_word_char(text[end]):
        return False
    return True


def count_token_sequences(
    *,
    keyword_tokens: list[str],
    document_tokens: list[str],
    allow_overlapping: bool,
) -> int:
    """Count how many times a keyword token sequence appears in a document token sequence.

    Non-overlapping mode advances past the matched span after each hit.
    Overlapping mode advances one token after each hit start.

    Args:
        keyword_tokens: Canonical tokens for the keyword.
        document_tokens: Canonical tokens for the document.
        allow_overlapping: When True, advance one token after each match start
            instead of advancing past the entire matched span.

    Returns:
        Number of non-overlapping or overlapping occurrences.
    """
    klen = len(keyword_tokens)
    dlen = len(document_tokens)
    if klen == 0 or dlen < klen:
        return 0

    count = 0
    pos = 0
    while pos <= dlen - klen:
        if document_tokens[pos : pos + klen] == keyword_tokens:
            count += 1
            pos = pos + 1 if allow_overlapping else pos + klen
        else:
            pos += 1
    return count


# ---------------------------------------------------------------------------
# Tokenizer regex shared between stem and lemma modes
# ---------------------------------------------------------------------------
_WORD_OR_NONSPACE: re.Pattern[str] = re.compile(r"\w+|[^\w\s]")


def _split_lemma_token(token_text: str) -> list[str]:
    """Split a lemma surface form with the shared tokenizer, case-folded.

    Used for tokens that contain word characters. Purely symbolic / punctuation-only
    tokens are handled separately by the caller.

    Args:
        token_text: Lemma surface text to split.

    Returns:
        List of lowercased sub-tokens.
    """
    return [m.casefold() for m in _WORD_OR_NONSPACE.findall(token_text)]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class _BaseMatcher(ABC):
    """Abstract base for all three matching engines."""

    def __init__(self, *, keywords: list[str], unicode_normalization: str, allow_overlapping: bool) -> None:
        self._unicode_form = unicode_normalization
        self._allow_overlapping = allow_overlapping
        # Canonical key for each configured keyword (populated by subclasses)
        self._canonical_keys: list = []

    @abstractmethod
    def canonical_keyword(self, text: str) -> object:
        """Return the canonical key for a keyword text.

        Used for collision detection; two keywords are equivalent if their
        canonical keys compare equal.

        Args:
            text: Keyword text (after Unicode normalization).

        Returns:
            Hashable canonical key.
        """

    @abstractmethod
    def count(self, *, text: str, keywords: list[str]) -> list[int]:
        """Return per-keyword match counts for a document.

        Args:
            text: Normalized document text.
            keywords: Configured keyword strings (in configuration order).

        Returns:
            List of counts in the same order as ``keywords``.
        """

    def cleanup(self) -> None:
        """Release resources held by this matcher.

        Subclasses override to drop model references. This method must
        be idempotent and tolerate partial initialization.
        """


# ---------------------------------------------------------------------------
# LiteralMatcher
# ---------------------------------------------------------------------------


class LiteralMatcher(_BaseMatcher):
    """RE2-backed literal-text matcher.

    Uses ``re2.Options(literal=True)`` so keyword text is never interpreted
    as pattern syntax. Case folding is delegated to RE2 (simple Unicode
    folding; multi-character folds such as ``straße`` → ``STRASSE`` are not
    applied).
    """

    def __init__(
        self,
        *,
        keywords: list[str],
        case_sensitive: bool,
        whole_word: bool,
        unicode_normalization: str,
        allow_overlapping: bool,
    ) -> None:
        import re2  # deferred to avoid hard dependency for other modes

        super().__init__(
            keywords=keywords,
            unicode_normalization=unicode_normalization,
            allow_overlapping=allow_overlapping,
        )
        self._case_sensitive = case_sensitive
        self._whole_word = whole_word

        opts = re2.Options()
        opts.literal = True
        opts.case_sensitive = case_sensitive

        self._patterns: list[re2.Pattern] = []
        self._normalized_keywords: list[str] = []

        for kw in keywords:
            norm_kw = normalize_unicode(kw, form=unicode_normalization)
            self._normalized_keywords.append(norm_kw)
            self._patterns.append(re2.compile(norm_kw.encode("utf-8"), opts))

        self._canonical_keys = [kw.casefold() if not case_sensitive else kw for kw in self._normalized_keywords]

    def canonical_keyword(self, text: str) -> str:
        norm = normalize_unicode(text, form=self._unicode_form)
        return norm.casefold() if not self._case_sensitive else norm

    def count(self, *, text: str, keywords: list[str]) -> list[int]:
        norm_text = normalize_unicode(text, form=self._unicode_form)
        counts: list[int] = []

        for pattern in self._patterns:
            counts.append(self._count_one(pattern=pattern, text=norm_text))

        return counts

    def _count_one(self, *, pattern: Any, text: str) -> int:
        """Count occurrences of one compiled pattern in text.

        Uses ``finditer`` only when no post-match filtering is needed
        (no whole-word check, non-overlapping). All other cases iterate
        over the encoded bytes for linear performance.

        Args:
            pattern: Compiled RE2 pattern.
            text: Normalized document text.

        Returns:
            Number of matches.
        """
        # Fast path: no filtering needed → use finditer on str
        if not self._whole_word and not self._allow_overlapping:
            return sum(1 for _ in pattern.finditer(text))

        # Filtered or overlapping path: search over UTF-8 bytes
        encoded = text.encode("utf-8")
        count = 0
        pos = 0
        encoded_len = len(encoded)

        while pos < encoded_len:
            m = pattern.search(encoded, pos)
            if m is None:
                break

            byte_start, byte_end = m.start(), m.end()

            # Decode byte positions back to code-point positions
            cp_start = len(encoded[:byte_start].decode("utf-8"))
            cp_end = cp_start + len(encoded[byte_start:byte_end].decode("utf-8"))

            if not self._whole_word or is_whole_word_match(text=text, start=cp_start, end=cp_end):
                count += 1
                pos = byte_start + 1 if self._allow_overlapping else byte_end
            else:
                pos = byte_start + 1

        return count


# ---------------------------------------------------------------------------
# StemMatcher
# ---------------------------------------------------------------------------

_SNOWBALL_LANGUAGES: frozenset[str] = frozenset(
    [
        "arabic",
        "danish",
        "dutch",
        "english",
        "finnish",
        "french",
        "german",
        "hungarian",
        "italian",
        "norwegian",
        "portuguese",
        "romanian",
        "russian",
        "spanish",
        "swedish",
    ]
)


class StemMatcher(_BaseMatcher):
    """Snowball stemmer-based matcher using NLTK.

    Tokenizes with ``r"\\w+|[^\\w\\s]"`` (no corpora), case-folds and stems
    word tokens, retains non-word non-space characters as individual tokens,
    then counts contiguous keyword token sequences.
    """

    def __init__(
        self,
        *,
        keywords: list[str],
        language: str,
        unicode_normalization: str,
        allow_overlapping: bool,
    ) -> None:
        from nltk.stem import SnowballStemmer  # deferred
        from nltk.tokenize import RegexpTokenizer  # deferred

        super().__init__(
            keywords=keywords,
            unicode_normalization=unicode_normalization,
            allow_overlapping=allow_overlapping,
        )
        self._stemmer = SnowballStemmer(language)
        self._tokenizer = RegexpTokenizer(r"\w+|[^\w\s]")
        self._stem_cache: dict[str, str] = {}

        self._keyword_tokens: list[list[str]] = [
            self._tokenize_text(normalize_unicode(kw, form=unicode_normalization)) for kw in keywords
        ]
        self._canonical_keys = [tuple(tks) for tks in self._keyword_tokens]

    def _stem(self, word: str) -> str:
        """Stem a word, caching results.

        Args:
            word: Lowercase word token.

        Returns:
            Stemmed form.
        """
        cached = self._stem_cache.get(word)
        if cached is not None:
            return cached
        stemmed = self._stemmer.stem(word)
        self._stem_cache[word] = stemmed
        return stemmed

    def _tokenize_text(self, text: str) -> list[str]:
        """Tokenize text into canonical stem tokens.

        Word tokens are case-folded and stemmed; non-word non-space chars are
        kept verbatim as single-character tokens.

        Args:
            text: Normalized text to tokenize.

        Returns:
            List of canonical tokens.
        """
        raw_tokens: list[str] = self._tokenizer.tokenize(text)
        result: list[str] = []
        for tok in raw_tokens:
            if re.match(r"^\w+$", tok):
                result.append(self._stem(tok.casefold()))
            else:
                result.append(tok)
        return result

    def canonical_keyword(self, text: str) -> tuple[str, ...]:
        norm = normalize_unicode(text, form=self._unicode_form)
        return tuple(self._tokenize_text(norm))

    def count(self, *, text: str, keywords: list[str]) -> list[int]:
        norm_text = normalize_unicode(text, form=self._unicode_form)
        doc_tokens = self._tokenize_text(norm_text)
        return [
            count_token_sequences(
                keyword_tokens=kw_tokens,
                document_tokens=doc_tokens,
                allow_overlapping=self._allow_overlapping,
            )
            for kw_tokens in self._keyword_tokens
        ]

    def cleanup(self) -> None:
        self._stem_cache.clear()
        super().cleanup()


# ---------------------------------------------------------------------------
# LemmaMatcher
# ---------------------------------------------------------------------------


def _is_valid_model_identifier(name: str) -> bool:
    """Return True when name is a plain Python identifier (no path/URL/special chars).

    Args:
        name: Model name to validate.

    Returns:
        True if name matches the allow pattern ``^[A-Za-z_][A-Za-z0-9_]*$``.
    """
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def _installed_spacy_model_names() -> set[str]:
    """Return the set of installed spaCy model package names from entry-points.

    Uses ``importlib.metadata.entry_points`` to find packages in the
    ``spacy_models`` group, without loading any package code.

    Returns:
        Set of registered package names.
    """
    from importlib.metadata import entry_points

    eps = entry_points(group="spacy_models")
    return {ep.name for ep in eps}


class LemmaMatcher(_BaseMatcher):
    """spaCy pipeline-based lemmatizer.

    Loads the pipeline eagerly in ``__init__`` so that validation-time failures
    surface during flow validation. Each instance owns a distinct pipeline so
    concurrent micro-batches are fully isolated.

    Call ``cleanup()`` to release the pipeline and any retained Doc objects.
    """

    def __init__(
        self,
        *,
        keywords: list[str],
        lemmatizer_model: str,
        unicode_normalization: str,
        allow_overlapping: bool,
    ) -> None:
        import spacy  # deferred — do not pay import cost in literal/stem flows
        import spacy.util

        super().__init__(
            keywords=keywords,
            unicode_normalization=unicode_normalization,
            allow_overlapping=allow_overlapping,
        )
        self._nlp = None  # set before first use so cleanup() tolerates failures

        if not _is_valid_model_identifier(lemmatizer_model):
            raise ValueError(
                "lemmatizer_model must be a plain Python identifier (no paths or URLs); got index-0 value rejected"
            )

        installed = _installed_spacy_model_names()
        if lemmatizer_model not in installed:
            raise ValueError(
                f"lemmatizer_model '{lemmatizer_model}' is not installed as a spaCy model package; install it and retry"
            )

        try:
            nlp = spacy.util.load_model_from_package(lemmatizer_model, disable=["ner", "parser"])
        except Exception as exc:
            raise ValueError(f"Failed to load spaCy model '{lemmatizer_model}': {exc}") from exc

        nlp.max_length = 1_000_000
        self._nlp = nlp

        # Self-check with the first keyword
        norm_kw0 = normalize_unicode(keywords[0], form=unicode_normalization)
        check_tokens = self._lemmatize_text(norm_kw0)
        if not check_tokens:
            self.cleanup()
            raise ValueError(f"lemmatizer_model '{lemmatizer_model}' does not provide usable lemmas")

        self._keyword_tokens: list[list[str]] = [
            self._lemmatize_text(normalize_unicode(kw, form=unicode_normalization)) for kw in keywords
        ]
        self._canonical_keys = [tuple(tks) for tks in self._keyword_tokens]

    def _lemmatize_text(self, text: str) -> list[str]:
        """Run the spaCy pipeline and produce a canonical token list.

        Rules:
        - Exclude space tokens.
        - For tokens with no word characters (punctuation/symbol-only): split
          the surface text into individual characters.
        - For tokens containing word characters: case-fold the lemma and split
          with the shared tokenizer.

        Args:
            text: Normalized text to process.

        Returns:
            List of canonical tokens.
        """
        assert self._nlp is not None, "_nlp must be set before calling _lemmatize_text"
        doc = self._nlp(text)
        result: list[str] = []
        for token in doc:
            if token.is_space:
                continue
            surface = token.text
            lemma = token.lemma_
            # Determine if token contains any word character
            if re.search(r"\w", surface):
                # Use lemma, case-fold, then re-split
                result.extend(_split_lemma_token(lemma))
            else:
                # Punctuation/symbol-only: use individual characters
                result.extend(list(surface))
        return result

    def canonical_keyword(self, text: str) -> tuple[str, ...]:
        norm = normalize_unicode(text, form=self._unicode_form)
        return tuple(self._lemmatize_text(norm))

    def count(self, *, text: str, keywords: list[str]) -> list[int]:
        norm_text = normalize_unicode(text, form=self._unicode_form)
        doc_tokens = self._lemmatize_text(norm_text)
        return [
            count_token_sequences(
                keyword_tokens=kw_tokens,
                document_tokens=doc_tokens,
                allow_overlapping=self._allow_overlapping,
            )
            for kw_tokens in self._keyword_tokens
        ]

    def cleanup(self) -> None:
        """Release the spaCy pipeline and any retained Doc objects."""
        self._nlp = None
        super().cleanup()
