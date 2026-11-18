# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for sliding-window summarization and summary cleaning in docpipe.utils.summarization_util."""

from typing import Any
from unittest.mock import MagicMock

from docpipe.utils.summarization_util import SummarizationUtil

# Three sentences of 3, 3 and 7 words; with max_words=5 the last one alone exceeds a window.
LONG_CONTENT = "One two three. Four five six. Seven eight nine ten eleven twelve thirteen."


def make_util(*, responses=None, overlap_ratio: float = 0.2) -> SummarizationUtil:
    """Create a util with a 5-word window (max_length=5, words_per_token=1.0) and a mock client."""
    client = MagicMock()
    if responses is not None:
        client.run.side_effect = responses
    return SummarizationUtil(
        client=client,
        max_length=5,
        words_per_token=1.0,
        overlap_ratio=overlap_ratio,
        task_instruction="Summarise.",
        summary_sentences=1,
        output_format="",
    )


class TestSlidingTextChunks:
    """Tests for _sliding_text_chunks window construction."""

    def test_windows_respect_sentence_boundaries_and_oversized_sentences(self):
        """Sentences are never split; a sentence longer than a window becomes its own window."""
        util = make_util()
        assert list(util._sliding_text_chunks(content=LONG_CONTENT)) == [
            (0, "One two three."),
            (1, "Seven eight nine ten eleven twelve thirteen."),
        ]

    def test_full_overlap_stops_after_first_window(self):
        """With overlap_ratio=1.0 the stride is zero, so iteration stops instead of looping forever."""
        util = make_util(overlap_ratio=1.0)
        assert list(util._sliding_text_chunks(content=LONG_CONTENT)) == [(0, "One two three.")]


class TestGenerateSummariesSlidingWindow:
    """Tests for _generate_summaries when content exceeds max_length."""

    def test_summaries_from_all_windows_are_merged_per_paragraph(self):
        """Each window is summarised separately and summaries of the same paragraph are joined."""
        util = make_util(responses=["Paragraph 0: Alpha.\nParagraph 1: Beta.", "Paragraph 1: Gamma."])

        assert util._generate_summaries(content=LONG_CONTENT) == {0: "Alpha.", 1: "Beta. Gamma."}
        assert util.client.run.call_count == 2

    def test_failing_window_is_skipped(self):
        """A model error for one window is logged and the remaining windows still contribute."""
        util = make_util(responses=[RuntimeError("model down"), "Paragraph 1: Gamma."])

        assert util._generate_summaries(content=LONG_CONTENT) == {1: "Gamma."}


class TestChunkedContentWithNonDictChunks:
    """Tests for generate_summary_for_chunked_content with mixed chunk types."""

    def test_non_dict_chunks_are_summarised_but_not_annotated(self):
        """Plain-string chunks are included in the prompt; only dict chunks receive a summary key."""
        client = MagicMock()
        client.run.return_value = "Paragraph 0: First.\nParagraph 1: Second."
        util = SummarizationUtil(
            client=client,
            max_length=500,
            words_per_token=1.0,
            overlap_ratio=0.1,
            task_instruction="",
            summary_sentences=1,
            output_format="",
        )
        chunks: list[Any] = [{"chunk": "dict chunk"}, "plain chunk"]

        util.generate_summary_for_chunked_content(chunked_content=chunks)

        assert chunks == [{"chunk": "dict chunk", "summary": "First."}, "plain chunk"]
        assert "Paragraph 1: plain chunk" in client.run.call_args.kwargs["prompt"]


class TestSummaryCleaning:
    """Tests for _parse_summaries and _extract_clean_summary filtering."""

    def test_meta_empty_and_word_count_lines_are_dropped(self):
        """Blank lines, meta commentary and short word-count artifacts are removed."""
        util = make_util()
        content = "Let's count the words.\n\n12 words\nThe report covers revenue."
        assert util._extract_clean_summary(content=content) == "The report covers revenue."

    def test_long_lines_mentioning_words_are_kept(self):
        """Lines of 50+ characters are kept even if they mention words and digits."""
        util = make_util()
        line = "The 2024 report lists 300 words of new terms for the glossary."
        assert len(line) >= 50
        assert util._extract_clean_summary(content=line) == line

    def test_paragraph_with_only_meta_text_is_omitted(self):
        """A paragraph whose content is pure meta text produces no summary entry."""
        util = make_util()
        text = "Paragraph 0: Return only the summary.\nParagraph 1: Real summary."
        assert util._parse_summaries(text=text) == {1: "Real summary."}
