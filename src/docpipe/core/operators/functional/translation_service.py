
"""Provider-agnostic service for translating document text."""

import re

from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class TranslationService:
    """Translate text through the common LLM inference port."""

    def __init__(
        self,
        *,
        llm_adapter: LLMInferencePort,
        source_language: str = "auto",
        target_language: str,
        preserve_markdown: bool = True,
        max_input_tokens: int = 4096,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.source_language = source_language
        self.target_language = target_language
        self.preserve_markdown = preserve_markdown
        # Estimate four characters per token without another dependency.
        self.max_chunk_chars = max_input_tokens * 4

    def translate(self, *, content: str) -> str:
        """Translate ordered chunks while retaining paragraph separators."""
        if not content or not content.strip():
            return content

        chunks = self._split_text(content=content)
        translated_parts: list[str] = []

        for chunk in chunks:
            if not chunk.strip():
                translated_parts.append(chunk)
                continue

            translated_parts.append(
                self._translate_chunk(content=chunk)
            )

        return "".join(translated_parts)

    def _translate_chunk(self, *, content: str) -> str:
        """Translate one chunk without logging its contents."""
        prompt = self._build_prompt(content=content)
        response = self.llm_adapter.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )

        if not isinstance(response, str) or not response.strip():
            logger.warning("Translation provider returned an empty response")
            raise ValueError("Translation provider returned an empty response")

        return response

    def _split_text(self, *, content: str) -> list[str]:
        """Split near paragraph boundaries, retaining separators separately."""
        limit = self.max_chunk_chars

        if len(content) <= limit:
            return [content]

        parts = re.split(r"(\n\s*\n)", content)
        chunks: list[str] = []

        for part in parts:
            if not part:
                continue

            if not part.strip():
                chunks.append(part)
                continue

            start = 0
            while start < len(part):
                end = min(start + limit, len(part))

                if end < len(part):
                    candidates = [
                        part.rfind(". ", start, end),
                        part.rfind("! ", start, end),
                        part.rfind("? ", start, end),
                        part.rfind(" ", start, end),
                    ]
                    boundary = max(candidates)

                    if boundary > start:
                        end = boundary + (
                            2 if part[boundary:boundary + 2]
                            in {". ", "! ", "? "}
                            else 1
                        )

                if end <= start:
                    end = min(start + limit, len(part))

                chunks.append(part[start:end])
                start = end

        return chunks

    def _build_prompt(self, *, content: str) -> str:
        """Build a translation prompt without logging document content."""
        markdown_instruction = (
            "Preserve all Markdown formatting, links, code blocks, and structure."
            if self.preserve_markdown
            else "Translate the text naturally while preserving its meaning."
        )

        return (
            "You are a professional document translator. Translate the supplied "
            "text faithfully. Return only the translation, without commentary.\n"
            f"Source language: {self.source_language}\n"
            f"Target language: {self.target_language}\n"
            f"{markdown_instruction}\n\n"
            "<text_to_translate>\n"
            f"{content}\n"
            "</text_to_translate>"
        )
