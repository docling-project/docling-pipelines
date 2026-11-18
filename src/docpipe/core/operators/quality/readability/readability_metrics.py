"""
Readability metrics implementation using pyphen for syllable counting.
Provides all standard readability formulas using pyphen and basic regex for tokenization.
"""

import math
from pathlib import Path
from typing import Any

import re2 as re
from pyphen import Pyphen

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Text statistics dictionary keys
WORDS = "words"
SENTENCES = "sentences"
SYLLABLES = "syllables"
COMPLEX_WORDS = "complex_words"
CHARACTERS = "characters"
WORD_LIST = "word_list"
DIFFICULT_WORDS = "difficult_words"


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    # RE2 does not support lookbehind; split on sentence-ending punctuation followed by
    # whitespace, then reassemble each sentence with its trailing punctuation mark.
    parts = re.split(r"([.!?])\s+", text.strip())
    sentences = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and parts[i + 1] in ".!?":
            sentences.append(parts[i] + parts[i + 1])
            i += 2
        else:
            if parts[i]:
                sentences.append(parts[i])
            i += 1
    return sentences


# Load easy words list
easy_words_path = Path(__file__).resolve().parent / "easy_words.txt"
with easy_words_path.open() as _f:
    EASY_WORDS: set[str] = {word.strip() for word in _f if word.strip()}


class ReadabilityMetrics:
    """
    Readability metrics calculator using pyphen for syllable counting.
    Implements all major readability formulas.
    """

    def __init__(self, *, lang: str = "en_US") -> None:
        """
        Initialize the readability metrics calculator.

        Args:
            lang: Language code for pyphen (default: "en_US")
        """
        self.dic = Pyphen(lang=lang)
        # Use module-level EASY_WORDS constant (loaded once at import time)
        self.easy_words = EASY_WORDS

    # ==================== Tokenization ====================

    @staticmethod
    def get_words(*, text: str) -> list[str]:
        """Extract words from text using regex."""
        return re.findall(r"\b[a-zA-Z]+\b", text.lower())

    # ==================== Syllable Counting ====================

    def count_syllables(self, *, word: str) -> int:
        """
        Count syllables in a word using pyphen.
        Returns at least 1 syllable per word.
        """
        word = word.lower().strip()
        if not word:
            return 0
        # pyphen.inserted() adds hyphens at syllable boundaries
        # Count hyphens + 1 to get syllable count
        hyphenated = self.dic.inserted(word)
        syllable_count = hyphenated.count("-") + 1
        return max(1, syllable_count)

    def count_syllables_in_text(self, *, words: list[str]) -> int:
        """Count total syllables in a list of words."""
        return sum(self.count_syllables(word=w) for w in words)

    # ==================== Character and Word Counting ====================

    @staticmethod
    def count_characters(*, words: list[str]) -> int:
        """Count total characters in words (excluding spaces)."""
        return sum(len(w) for w in words)

    def count_complex_words(self, *, words: list[str], syllable_threshold: int = 3) -> int:
        """
        Count complex words (words with 3+ syllables by default).

        Args:
            words: List of words
            syllable_threshold: Minimum syllables to be considered complex
        """
        return sum(1 for w in words if self.count_syllables(word=w) >= syllable_threshold)

    def count_difficult_words(self, *, words: list[str]) -> int:
        """
        Count words not in easy word list.
        Used by Dale-Chall, Spache, and Difficult Words metrics.
        """
        return sum(1 for w in words if w.lower() not in self.easy_words)

    # ==================== Text Statistics ====================

    def text_stats(self, *, text: str) -> dict[str, Any]:
        """
        Calculate comprehensive text statistics.

        Returns:
            Dictionary containing:
            - words: word count
            - sentences: sentence count
            - syllables: total syllables
            - complex_words: words with 3+ syllables
            - characters: total character count
            - word_list: list of words
            - difficult_words: count of non-easy words
        """
        words = self.get_words(text=text)
        sentences = split_sentences(text)

        syllables = self.count_syllables_in_text(words=words)
        complex_words = self.count_complex_words(words=words)
        characters = self.count_characters(words=words)
        difficult_words_count = self.count_difficult_words(words=words)

        return {
            WORDS: len(words),
            SENTENCES: max(1, len(sentences)),
            SYLLABLES: syllables,
            COMPLEX_WORDS: complex_words,
            CHARACTERS: characters,
            WORD_LIST: words,
            DIFFICULT_WORDS: difficult_words_count,
        }

    # ==================== Readability Formulas ====================

    @staticmethod
    def flesch_reading_ease(*, stats: dict[str, Any]) -> float:
        """
        Flesch Reading Ease: 206.835 - 1.015(words/sentences) - 84.6(syllables/words)
        Higher scores = easier reading (0-100 scale)
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        syllables_count = stats[SYLLABLES]

        if words_count == 0:
            return 0.0

        return 206.835 - 1.015 * (words_count / sentences_count) - 84.6 * (syllables_count / words_count)

    @staticmethod
    def flesch_kincaid_grade(*, stats: dict[str, Any]) -> float:
        """
        Flesch-Kincaid Grade Level: 0.39(words/sentences) + 11.8(syllables/words) - 15.59
        Returns U.S. grade level
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        syllables_count = stats[SYLLABLES]

        if words_count == 0:
            return 0.0

        return 0.39 * (words_count / sentences_count) + 11.8 * (syllables_count / words_count) - 15.59

    @staticmethod
    def gunning_fog(*, stats: dict[str, Any]) -> float:
        """
        Gunning Fog Index: 0.4((words/sentences) + 100(complex_words/words))
        Returns grade level needed
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        complex_words_count = stats[COMPLEX_WORDS]

        if words_count == 0:
            return 0.0

        return 0.4 * ((words_count / sentences_count) + 100 * (complex_words_count / words_count))

    @staticmethod
    def smog_index(*, stats: dict[str, Any]) -> float:
        """
        SMOG Index: 1.0430 * sqrt(complex_words * (30/sentences)) + 3.1291
        Returns grade level
        """
        complex_words_count = stats[COMPLEX_WORDS]
        sentences_count = stats[SENTENCES]

        if sentences_count == 0:
            return 0.0

        return 1.043 * math.sqrt(complex_words_count * (30 / sentences_count)) + 3.1291

    @staticmethod
    def coleman_liau_index(*, stats: dict[str, Any]) -> float:
        """
        Coleman-Liau Index: 0.0588*letters_per_100 - 0.296*sentences_per_100 - 15.8
        Where letters_per_100 = letters per 100 words, sentences_per_100 = sentences per 100 words
        """
        words_count = stats[WORDS]
        chars_count = stats[CHARACTERS]
        sentences_count = stats[SENTENCES]

        if words_count == 0:
            return 0.0

        letters_per_100 = (chars_count / words_count) * 100
        sentences_per_100 = (sentences_count / words_count) * 100

        return 0.0588 * letters_per_100 - 0.296 * sentences_per_100 - 15.8

    @staticmethod
    def automated_readability_index(*, stats: dict[str, Any]) -> float:
        """
        Automated Readability Index: 4.71(chars/words) + 0.5(words/sentences) - 21.43
        Returns grade level
        """
        chars_count = stats[CHARACTERS]
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]

        if words_count == 0:
            return 0.0

        return 4.71 * (chars_count / words_count) + 0.5 * (words_count / sentences_count) - 21.43

    @staticmethod
    def dale_chall_readability_score(*, stats: dict[str, Any]) -> float:
        """
        Dale-Chall Readability Score: 0.1579(pct_difficult) + 0.0496(avg_sentence_len)
        Where pct_difficult = percentage of difficult words, avg_sentence_len = average sentence length
        If pct_difficult > 5%, add 3.6365
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        difficult_words_count = stats[DIFFICULT_WORDS]

        if words_count == 0:
            return 0.0

        pct_difficult_words = (difficult_words_count / words_count) * 100
        avg_sentence_len = words_count / sentences_count

        score = 0.1579 * pct_difficult_words + 0.0496 * avg_sentence_len

        if pct_difficult_words > 5:
            score += 3.6365

        return score

    @staticmethod
    def difficult_words(*, stats: dict[str, Any]) -> int:
        """
        Return count of difficult words (not in easy word list).
        """
        return stats[DIFFICULT_WORDS]

    def linsear_write_formula(self, *, stats: dict[str, Any]) -> float:
        """
        Linsear Write Formula
        Based on easy words (<3 syllables) vs hard words (>=3 syllables)
        Uses first 100 words
        """
        words = stats[WORD_LIST][:100]
        sentences = stats[SENTENCES]

        if not words:
            return 0.0

        easy = 0
        hard = 0

        for w in words:
            if self.count_syllables(word=w) < 3:
                easy += 1
            else:
                hard += 3

        score = (easy + hard) / max(1, sentences)

        if score > 20:
            score /= 2
        else:
            score = (score / 2) - 1

        return max(0, score)

    @staticmethod
    def text_standard(*, stats: dict[str, Any]) -> float:
        """
        Text Standard: Average of multiple grade-level metrics
        """
        scores = [
            ReadabilityMetrics.flesch_kincaid_grade(stats=stats),
            ReadabilityMetrics.gunning_fog(stats=stats),
            ReadabilityMetrics.smog_index(stats=stats),
            ReadabilityMetrics.coleman_liau_index(stats=stats),
            ReadabilityMetrics.automated_readability_index(stats=stats),
        ]

        avg = sum(scores) / len(scores)
        return round(avg, 1)

    @staticmethod
    def spache_readability(*, stats: dict[str, Any]) -> float:
        """
        Spache Readability Formula: 0.141(avg_sentence_len) + 0.086(pct_difficult) + 0.839
        Where avg_sentence_len = average sentence length, pct_difficult = percentage of difficult words
        For grades 1-4
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        difficult_words_count = stats[DIFFICULT_WORDS]

        if words_count == 0:
            return 0.0

        avg_sentence_len = words_count / sentences_count
        pct_difficult_words = (difficult_words_count / words_count) * 100

        return 0.141 * avg_sentence_len + 0.086 * pct_difficult_words + 0.839

    @staticmethod
    def mcalpine_eflaw(*, stats: dict[str, Any]) -> float:
        """
        McAlpine EFLAW (Easy Listening Formula for Adult Learners)
        Formula: (words + miniwords) / sentences
        Where miniwords are words with 3 or fewer letters
        """
        words_count = stats[WORDS]
        sentences_count = stats[SENTENCES]
        words_list = stats[WORD_LIST]

        if sentences_count == 0:
            return 0.0

        miniwords_count = sum(1 for w in words_list if len(w) <= 3)

        return (words_count + miniwords_count) / sentences_count

    @staticmethod
    def reading_time(*, stats: dict[str, Any], wpm: int = 200) -> float:
        """
        Calculate reading time in minutes.

        Args:
            stats: Text statistics
            wpm: Words per minute (default: 200)

        Returns:
            Reading time in minutes
        """
        words_count = stats[WORDS]
        return words_count / wpm
