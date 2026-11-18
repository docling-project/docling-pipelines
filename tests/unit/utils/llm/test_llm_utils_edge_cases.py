# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for docpipe.utils.llm.prompt_manager and docpipe.utils.llm.json_parser."""

import json
from unittest.mock import patch

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.llm.json_parser import _try_extract_from_markdown, parse_llm_json_response
from docpipe.utils.llm.prompt_manager import PromptManager


class TestPromptManagerEdgeCases:
    """Tests for PromptManager argument and format-string validation."""

    @pytest.mark.parametrize("prompt_file", [None, ""])
    def test_empty_prompt_file_is_rejected(self, prompt_file):
        """A missing prompt file path is rejected at construction time."""
        with pytest.raises(ValueError, match="prompt_file cannot be None or empty"):
            PromptManager(prompt_file)

    def test_invalid_format_string_raises_value_error(self, tmp_path):
        """A template with an unbalanced brace raises a descriptive ValueError."""
        prompt_file = tmp_path / "prompt.json"
        prompt_file.write_text(json.dumps({"description": "Score {threshold} and then {"}), encoding="utf-8")
        manager = PromptManager(prompt_file)

        with pytest.raises(ValueError, match="Invalid format string in prompt template") as exc_info:
            manager.format_prompt(threshold=0.5)

        assert isinstance(exc_info.value.__cause__, ValueError)


class TestParseLlmJsonResponseEdgeCases:
    """Tests for json_parser fallbacks not exercised elsewhere."""

    def test_markdown_block_with_json_null_is_skipped(self):
        """A block that parses to null is neither a result nor an error; later blocks are tried."""
        response = '```json\nnull\n```\ntext\n```json\n{"answer": 42}\n```'
        assert _try_extract_from_markdown(response) == ({"answer": 42}, None)

    def test_failure_without_logging_still_raises(self):
        """With log_on_error=False nothing is logged but the parse error is still raised."""
        with (
            patch("docpipe.utils.llm.json_parser.logger") as mock_logger,
            pytest.raises(DocpipeException, match="Failed to parse JSON from model"),
        ):
            parse_llm_json_response("no json here {", log_on_error=False)

        assert mock_logger.method_calls == []
