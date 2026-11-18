# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Reusable JSON parsing utilities for LLM responses.

This module provides utilities for parsing JSON from LLM responses,
handling common issues like markdown formatting, mixed content, and
malformed JSON.
"""

import json
import re
from typing import Any

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Precompiled regex patterns for better performance.
# Fixed ReDoS: replaced `.*?` (backtracking) with `[^`]*` (possessive-safe linear scan)
# to prevent exponential backtracking on malformed/adversarial inputs.
_MARKDOWN_BLOCK_PATTERN = re.compile(r"```(?:json)?[ \t]*\n([^`]*?)```", re.DOTALL)

# Valid JSON escape characters per RFC 8259: " \ / b f n r t and uXXXX
_VALID_ESCAPES = set('"\\/' + "bfnrtu")
_INVALID_ESCAPE_PATTERN = re.compile(r'\\([^"\\\/bfnrtu])')

_LOG_TRUNCATE_CHARS = 5000


def _try_parse_json(text: str) -> tuple[dict[str, Any] | None, json.JSONDecodeError | None]:
    """Try to parse text as JSON, return (result, error)."""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, e


def _try_extract_from_markdown(raw_response: str) -> tuple[dict[str, Any] | None, json.JSONDecodeError | None]:
    """Try to extract JSON from markdown code blocks, iterating all blocks to find valid JSON."""
    last_error: json.JSONDecodeError | None = None
    for match in _MARKDOWN_BLOCK_PATTERN.finditer(raw_response):
        result, error = _try_parse_json(match.group(1).strip())
        if result is not None:
            return result, None
        if error is not None:
            last_error = error
    return None, last_error


def _find_matching_brace(text: str, start: int) -> int:
    """Return the index one past the closing } that matches the { at start.

    Walks the string character-by-character, tracking brace depth while
    skipping over string literals (including escaped quotes inside them).
    Returns -1 if no matching closing brace is found.
    """
    depth = 0
    i = start
    in_string = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2  # skip escaped character
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1


def _try_extract_from_braces(raw_response: str) -> tuple[dict[str, Any] | None, json.JSONDecodeError | None]:
    """Try to extract JSON by finding the first { and its matching closing }."""
    start_idx = raw_response.find("{")
    if start_idx == -1:
        return None, None
    end_idx = _find_matching_brace(raw_response, start_idx)
    if end_idx == -1:
        return None, None
    extracted = raw_response[start_idx:end_idx]
    return _try_parse_json(extracted)


def _sanitize_invalid_escapes(text: str) -> str:
    """Replace invalid JSON escape sequences with their literal characters.

    LLMs sometimes emit raw backslashes inside strings (e.g. Windows paths like
    C:\\IC or address suffixes like l\\IC) that are not valid JSON escape sequences.
    This replaces \\X (where X is not a valid JSON escape character) with just X,
    making the string parseable.
    """
    return _INVALID_ESCAPE_PATTERN.sub(r"\1", text)


def _try_parse_sanitized(raw_response: str) -> tuple[dict[str, Any] | None, json.JSONDecodeError | None]:
    """Try to extract JSON from braces after sanitizing invalid escape sequences."""
    start_idx = raw_response.find("{")
    if start_idx == -1:
        return None, None
    end_idx = _find_matching_brace(raw_response, start_idx)
    if end_idx == -1:
        return None, None
    extracted = raw_response[start_idx:end_idx]
    sanitized = _sanitize_invalid_escapes(extracted)
    return _try_parse_json(sanitized)


def parse_llm_json_response(
    raw_response: str,
    *,
    log_on_error: bool = True,
    log_level: str = "debug",
) -> dict[str, Any]:
    """Parse JSON from LLM response with fallback strategies.

    This function attempts multiple strategies to extract valid JSON from
    LLM responses:
    1. Direct JSON parsing
    2. Extract JSON from markdown code blocks
    3. Extract JSON between first { and last }

    Args:
        raw_response: Raw response string from LLM
        log_on_error: Whether to log the full response on parsing failure
        log_level: Log level to use for error logging ('debug', 'info', 'warning', 'error')

    Returns:
        Parsed JSON dictionary

    Raises:
        DocpipeException: If JSON cannot be parsed after all strategies

    Example:
        >>> response = '```json\\n{"key": "value"}\\n```'
        >>> result = parse_llm_json_response(response)
        >>> result
        {'key': 'value'}
    """
    if not raw_response:
        raise DocpipeException(
            message="LLM inference failed: Model returned empty response",
            status_code=500,
            error_code=ErrorCode.INVALID_RESPONSE,
        )

    # Try parsing strategies in order
    last_json_error = None
    strategies = [
        lambda: _try_parse_json(raw_response),
        lambda: _try_extract_from_markdown(raw_response),
        lambda: _try_extract_from_braces(raw_response),
        lambda: _try_parse_sanitized(raw_response),
    ]

    for strategy in strategies:
        result, error = strategy()
        if result is not None:
            return result
        if error is not None:
            last_json_error = error

    # All strategies failed - log and raise error with original exception details
    if log_on_error:
        log_func = getattr(logger, log_level, logger.debug)
        # Truncate response to avoid excessive logging
        truncated_response = (
            raw_response[:_LOG_TRUNCATE_CHARS] + "..." if len(raw_response) > _LOG_TRUNCATE_CHARS else raw_response
        )
        log_func(
            f"Failed to parse JSON from LLM response. "
            f"Response length: {len(raw_response)} chars. "
            f"Response (truncated): {truncated_response}"
        )

    # Include original error details in exception message
    error_detail = f": {last_json_error!s}" if last_json_error else ""
    raise DocpipeException(
        message=f"Failed to parse JSON from model{error_detail}",
        status_code=500,
        error_code=ErrorCode.INVALID_RESPONSE,
    ) from last_json_error
