# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""ReDoS vulnerability tests for LLM JSON parser regex pattern."""

import time

from docpipe.utils.llm.json_parser import parse_llm_json_response


class TestJsonParserReDoS:
    """Verify no exponential backtracking on adversarial/malformed inputs."""

    _REDOS_TIMEOUT_SECONDS = 1.0

    def test_redos_pathological_input_with_many_backticks(self):
        """Verify no exponential backtracking with malformed backtick sequences."""
        # Adversarial: many backtick runs without a closing ``` — previously caused ReDoS
        malformed = "```" * 100 + "json" + "``" * 100
        start = time.monotonic()
        try:
            parse_llm_json_response(malformed)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        assert elapsed < self._REDOS_TIMEOUT_SECONDS, f"Regex took {elapsed:.2f}s — possible ReDoS backtracking"

    def test_redos_pathological_input_with_whitespace_and_newlines(self):
        """Verify no exponential backtracking on whitespace/newline combinations."""
        malformed = "```json" + " \n" * 200 + "```" + "\n " * 200
        start = time.monotonic()
        try:
            parse_llm_json_response(malformed)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        assert elapsed < self._REDOS_TIMEOUT_SECONDS, f"Regex took {elapsed:.2f}s — possible ReDoS backtracking"

    def test_redos_pathological_input_missing_closing_backticks(self):
        """Verify no exponential backtracking on unclosed code blocks."""
        malformed = "```json\n" + "x" * 10_000  # no closing ```
        start = time.monotonic()
        try:
            parse_llm_json_response(malformed)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        assert elapsed < self._REDOS_TIMEOUT_SECONDS, f"Regex took {elapsed:.2f}s — possible ReDoS backtracking"

    def test_valid_markdown_still_works_after_fix(self):
        """Ensure valid markdown code blocks still parse correctly after the ReDoS fix."""
        response = '```json\n{"key": "value", "number": 42}\n```'
        result = parse_llm_json_response(response)
        assert result == {"key": "value", "number": 42}

    def test_markdown_with_crlf_line_endings(self):
        """Verify Windows-style CRLF line endings are handled correctly."""
        response = '```json\r\n{"key": "value"}\r\n```'
        result = parse_llm_json_response(response)
        assert result == {"key": "value"}

    def test_markdown_with_tabs_before_json(self):
        """Verify tab characters before JSON content are handled correctly."""
        response = '```json\t\n{"key": "value"}\n```'
        result = parse_llm_json_response(response)
        assert result == {"key": "value"}
