"""Summarization service for chunked content using LLM adapters."""

import re
from typing import Any, Iterator

from docpipe.core.constants import DocpipeConstants, OperatorConstants
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class SummarizationService:
    """Service for generating summaries of chunked content using LLM adapters.

    This service encapsulates all summarization business logic including:
    - Prompt engineering for summarization tasks
    - Response parsing to extract structured summaries
    - Sliding window logic for handling large content
    - Sentence splitting and text chunking

    The service depends on LLMInferencePort for provider-agnostic LLM access.
    """

    def __init__(
        self,
        *,
        llm_adapter: LLMInferencePort,
        max_input_tokens: int = DocpipeConstants.MAX_INPUT_TOKENS_DEFAULT,
        overlap_ratio: float = DocpipeConstants.OVERLAP_RATIO_DEFAULT,
        summary_sentences: int = DocpipeConstants.SUMMARY_SENTENCES_DEFAULT,
        summary_max_words: int = DocpipeConstants.SUMMARY_MAX_WORDS_DEFAULT,
    ):
        """Initialize the summarization service.

        Args:
            llm_adapter: LLM adapter implementing LLMInferencePort interface
            max_input_tokens: Maximum tokens for LLM input (default: 4096)
            overlap_ratio: Overlap ratio for sliding windows (default: 0.1, range: 0.0-0.5)
            summary_sentences: Target number of sentences per summary (default: 3)
            summary_max_words: Maximum words per summary (default: 50)
        """
        self.llm_adapter = llm_adapter
        self.max_input_tokens = max_input_tokens
        self.overlap_ratio = overlap_ratio
        self.summary_sentences = summary_sentences
        self.summary_max_words = summary_max_words

        # Validate adapter configuration
        self._validate_adapter()

    def _validate_adapter(self) -> None:
        """Validate LLM adapter configuration on initialization.

        Raises:
            DocpipeException: If adapter validation fails
        """
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        result = self.llm_adapter.validate()

        # Log warnings
        if result.get("warnings"):
            for warning in result["warnings"]:
                logger.warning("LLM adapter validation warning: %s", warning)

        # Raise error if validation failed
        if not result.get("valid", True):
            errors = result.get("errors", ["Unknown validation error"])
            raise DocpipeException(
                message=f"LLM adapter validation failed: {'; '.join(errors)}",
                status_code=400,
            )

    def generate_summary(self, *, content: str) -> str:
        """Generate one summary for document content.

        Short content is summarized in one request. Long content is split on
        sentence boundaries, summarized window by window, and reduced into a
        single final summary.
        """
        if not content or not content.strip():
            return ""

        if self._estimated_tokens(content=content) <= self.max_input_tokens:
            return self._call_llm_for_document_summary(content=content).strip()

        partial_summaries: list[str] = []
        for window_index, window_text in self._sliding_text_chunks(content=content):
            try:
                summary = self._call_llm_for_document_summary(content=window_text).strip()
            except Exception as exc:
                logger.warning(
                    "Failed to summarize document window %s: %s",
                    window_index,
                    type(exc).__name__,
                )
                continue
            if summary:
                partial_summaries.append(summary)
        if not partial_summaries:
            raise ValueError("Summarization returned no partial summaries")

        combined_summaries = "\n\n".join(partial_summaries)
        while self._estimated_tokens(content=combined_summaries) > self.max_input_tokens:
            reduced_summaries: list[str] = []
            for window_index, window_text in self._sliding_text_chunks(content=combined_summaries):
                try:
                    summary = self._call_llm_for_document_summary(content=window_text).strip()
                except Exception as exc:
                    logger.warning(
                        "Failed to reduce document window %s: %s",
                        window_index,
                        type(exc).__name__,
                    )
                    continue
                if summary:
                    reduced_summaries.append(summary)
            partial_summaries = reduced_summaries
            if not partial_summaries:
                raise ValueError("Summarization returned no reduced summaries")
            combined_summaries = "\n\n".join(partial_summaries)

        return self._call_llm_for_document_summary(content=combined_summaries).strip()

    def generate_summary_for_chunked_content(self, *, chunked_content: list[dict[str, Any]]) -> None:
        """
        Expected format of chunked_content:
        [ {"chunk": "<chunk_content>", "start_index": "<start_index>" },
          {"chunk": "<chunk_content>", "start_index": "<start_index>" },
          ....
        ]

        Result format of chunked_content after the method execution:
        [ {"chunk": "<chunk_content>", "start_index": "<start_index>", "summary": "<summary>" },
          {"chunk": "<chunk_content>", "start_index": "<start_index>", "summary": "<summary>" },
          ....
        ]
        """

        # Annotate paragraphs with sequence numbers (0-based to match list indexing)
        annotated_paragraphs = []
        for seq_num, chunk in enumerate(chunked_content):
            chunk_text = chunk.get(OperatorConstants.Columns.CHUNK) if isinstance(chunk, dict) else str(chunk)
            annotated_paragraphs.append(self._annotate_paragraph(chunk_sequence_number=seq_num, para=str(chunk_text)))

        full_content = "\n\n".join(annotated_paragraphs)

        # Generate summaries using LLM
        summaries = self._generate_summaries(content=full_content)

        # Add summaries back to chunks using 0-based indexing
        for seq_num, chunk in enumerate(chunked_content):
            if isinstance(chunk, dict):
                chunk[OperatorConstants.Columns.SUMMARY] = summaries.get(seq_num, "No summary available")

    @staticmethod
    def _estimated_tokens(*, content: str) -> int:
        """Estimate token usage consistently with the existing windowing logic."""
        return int(len(content.split()) / 0.5)

    def _call_llm_for_document_summary(self, *, content: str) -> str:
        """Call the adapter with a prompt for one document summary."""
        prompt = (
            "Summarize the following document in the same language as the input. "
            f"Write no more than {self.summary_sentences} sentences and "
            f"{self.summary_max_words} words. Return only the summary.\n\n"
            f"Document:\n{content}"
        )
        response = self.llm_adapter.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        if not response or not response.strip():
            raise ValueError("Summarization provider returned an empty response")
        return response

    def _annotate_paragraph(self, *, chunk_sequence_number: int, para: str) -> str:
        """Annotate a paragraph with its sequence number.

        Args:
            chunk_sequence_number: Sequence number of the chunk
            para: Paragraph text

        Returns:
            Annotated paragraph with sequence number marker
        """
        return f"<<< Paragraph {chunk_sequence_number} START >>>\nParagraph {chunk_sequence_number}: {para.strip()}\n<<< Paragraph {chunk_sequence_number} END >>>"

    def _generate_summaries(self, *, content: str) -> dict[int, str]:
        """Generate summaries using LLM adapter with sliding window if needed.

        Args:
            content: Full annotated content to summarize

        Returns:
            Dictionary mapping paragraph numbers to their summaries
        """
        word_count = len(content.split())
        words_per_token = 0.5
        estimated_tokens = int(word_count / words_per_token)

        if estimated_tokens <= self.max_input_tokens:
            response = self._call_llm_for_summary(content=content)
            return self._parse_summaries(text=response)

        all_summaries: dict[int, list[str]] = {}
        for chunk_idx, chunk_text in self._sliding_text_chunks(content=content):
            try:
                response = self._call_llm_for_summary(content=chunk_text)
                chunk_summaries = self._parse_summaries(text=response)
                for para_num, summary in chunk_summaries.items():
                    if para_num not in all_summaries:
                        all_summaries[para_num] = []
                    all_summaries[para_num].append(summary)
            except Exception as e:
                logger.warning("Failed to generate summary for window %s: %s", chunk_idx, type(e).__name__)
                continue

        merged_summaries = {}
        for para_num, summary_list in all_summaries.items():
            merged_summaries[para_num] = " ".join(summary_list)
        return merged_summaries

    def _call_llm_for_summary(self, *, content: str) -> str:
        """Call LLM adapter to generate summaries.

        Args:
            content: Content to summarize

        Returns:
            LLM response text

        Raises:
            DocpipeOperatorException: If LLM call fails
        """
        prompt = self._generate_summary_prompt(content=content)
        response = self.llm_adapter.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        if not response:
            logger.warning("Empty response received from Ollama model")
        return response

    def _generate_summary_prompt(self, *, content: str) -> str:
        """Generate prompt for summarization.

        Args:
            content: Content to summarize

        Returns:
            Formatted prompt for LLM
        """
        task_instruction = (
            f"Your task is to write an abstract for each of these paragraphs in no more than {self.summary_sentences} sentence "
            f"(no more than {self.summary_max_words} words) describing what the paragraph is about.\n"
            "Ensure that each abstract is self-contained and understandable on its own, while maintaining awareness "
            "of the overall context of the document. Include relevant details indicating whether the "
            "paragraph provides an overview, explains specific details, or presents examples."
        )

        output_format = (
            "Your answer should follow this format:\n"
            "[### Paragraph [number]] :\n"
            "[Your abstract goes here]\n"
            "# repeat for each paragraph\n"
            "\n\nDo not output any additional text or commentary. Be brief and precise. Avoid repetition."
        )

        return (
            "You are a sophisticated AI expert in Natural Language Processing (NLP), "
            "with a specialized ability to semantically analyze long text and distill their meaning."
            f"{task_instruction}\n\n"
            f"```\n{content}\n```\n\n"
            "The abstract should contain all the important aspects given in the paragraph."
            f"Ensure that the abstract does not exceed {self.summary_sentences} sentences."
            "Each paragraph abstract should be self-contained and not depend on the previous abstracts."
            "Each abstract must be written in the same language as the input paragraph it summarizes"
            f"{output_format}\n\n"
        )

    def _parse_summaries(self, *, text: str) -> dict[int, str]:
        """Parse LLM response to extract summaries by paragraph number.

        Args:
            text: LLM response text

        Returns:
            Dictionary mapping paragraph numbers to summaries
        """
        if not text or not text.strip():
            return {}

        text = self._normalize_paragraph_markers(text=str(text))
        matches = re.findall(r"(?ms)^Paragraph\s*(\d+)\s*:\s*((?:(?!^Paragraph\s*\d+).)*)", text)

        summaries: dict[int, str] = {}
        for num, content in matches:
            final_summary = self._extract_clean_summary(content=content)
            if final_summary:
                summaries[int(num)] = final_summary

        return summaries

    def _normalize_paragraph_markers(self, *, text: str) -> str:
        """Normalize various paragraph marker formats.

        Args:
            text: Text with paragraph markers

        Returns:
            Normalized text
        """
        # Ensure "Paragraph X:" always starts on a new line
        text = re.sub(r"(?<!\n)(Paragraph\s*\d+\s*:)", r"\n\1", text)
        # Remove numbered list prefixes
        text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
        # Normalize bracket formats
        text = re.sub(r"(?m)^\[[\s#]*Paragraph\b", "Paragraph", text)
        # Normalize markdown headers
        text = re.sub(r"(?m)^#+\s+Paragraph\b", "Paragraph", text)
        # Normalize colons and brackets
        return re.sub(r"Paragraph\s*(\d+)\s*[:\]]+", r"Paragraph \1:", text)

    def _extract_clean_summary(self, *, content: str) -> str:
        """Extract and clean summary content from raw paragraph text.

        Args:
            content: Raw summary content

        Returns:
            Cleaned summary text
        """
        cleaned = content.strip()
        cleaned = re.sub(r"<<<\s*Paragraph\s*\d+\s*(?:START|END)\s*>>>", "", cleaned).replace("```", "")

        summary_lines: list[str] = []
        for line in cleaned.splitlines():
            line = line.strip()
            if not line or self._is_meta_text(text=line):
                continue
            if self._is_word_counting_line(line=line):
                continue
            summary_lines.append(line)

        combined = " ".join(summary_lines).strip()

        # Remove leading colon and whitespace (common artifact from chat models)
        combined = re.sub(r"^\s*:\s*", "", combined)

        sentences = re.split(r"(?<=[.!?])\s+", combined)
        valid_sentences = [s.strip() for s in sentences if s.strip() and not self._is_meta_text(text=s.strip())]
        return " ".join(valid_sentences).strip()

    def _is_word_counting_line(self, *, line: str) -> bool:
        """Check if line is a word-counting artifact.

        Args:
            line: Line to check

        Returns:
            True if line appears to be word counting
        """
        if len(line) >= 50:
            return False
        line_lower = line.lower()
        if "word" not in line_lower and "words" not in line_lower:
            return False
        return any(c.isdigit() for c in line)

    def _is_meta_text(self, *, text: str) -> bool:
        """Detect LLM meta commentary or instruction artifacts.

        Args:
            text: Text to check

        Returns:
            True if text appears to be meta commentary
        """
        return bool(
            re.match(
                r"^(Let's|That's|Good|Provide|Check|Count|Try|Possible|We need|"
                r"assistant|Ensure|Make sure|Return only|Return|No extra)",
                text,
                re.IGNORECASE,
            )
        )

    def _sliding_text_chunks(self, *, content: str) -> Iterator[tuple[int, str]]:
        """Split content into overlapping chunks that fit within token limits.

        Args:
            content: Content to split

        Returns:
            List of text chunks with overlap
        """
        words_per_token = 0.5
        max_words = int(self.max_input_tokens * words_per_token)
        overlap_words = int(max_words * self.overlap_ratio)
        stride_words = max_words - overlap_words

        sentences = self._split_into_sentences(text=content)
        sent_word_counts = [(s, len(s.split())) for s in sentences]
        total_words = sum(wc for _, wc in sent_word_counts)

        if total_words <= max_words:
            yield 0, content.strip()
            return

        chunk_idx = 0
        start_sent_idx = 0

        while start_sent_idx < len(sent_word_counts):
            current_words = 0
            chunk_sentences: list[str] = []
            i = start_sent_idx

            # Build chunk without breaking sentences
            while i < len(sent_word_counts):
                sent, wc = sent_word_counts[i]
                if current_words + wc > max_words:
                    break
                chunk_sentences.append(sent)
                current_words += wc
                i += 1

            if not chunk_sentences:
                # Handle very long single sentence
                chunk_sentences.append(sent_word_counts[i][0])
                i += 1
            chunk_text = " ".join(chunk_sentences)
            yield chunk_idx, chunk_text

            chunk_idx += 1
            # Move start forward based on stride (in words)
            words_moved = 0
            new_start = start_sent_idx

            while new_start < len(sent_word_counts) and words_moved < stride_words:
                words_moved += sent_word_counts[new_start][1]
                new_start += 1

            if new_start <= start_sent_idx:
                break  # Prevent infinite loop

            start_sent_idx = new_start

    def _split_into_sentences(self, *, text: str) -> list[str]:
        """Split text into sentences using punctuation.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s for s in sentences if s]
