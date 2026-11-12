# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""String manipulation and processing utilities."""

import json
import re


def split_text_into_chunks(*, text, min_size=3000, max_size=4000):
    """
    Split text into chunks based on paragraph boundaries.

    Args:
        text: Text to split
        min_size: Minimum chunk size in characters (default: 3000)
        max_size: Maximum chunk size in characters (default: 4000)

    Returns:
        List of text chunks
    """
    paragraphs = re.split(r"\n\s*\n", text)

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        # Prepare the paragraph with spacing
        if current_chunk:
            candidate = current_chunk + "\n\n" + paragraph
        else:
            candidate = paragraph

        if len(candidate) <= max_size:
            current_chunk = candidate
        else:
            if len(current_chunk) >= min_size:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                # If current_chunk is too small and adding makes it too big,
                # add anyway to avoid fragmenting paragraphs.
                current_chunk = candidate
                chunks.append(current_chunk.strip())
                current_chunk = ""

    # Handle any remaining chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def get_truncated_text(*, text_string: str, n_chars: int = 1000, n_json_entries: int = 4):
    """
    Truncates the input string based on its content:
    1. If it's plain text, returns the first `n_chars` characters.
    2. If it's a JSON list of dicts, returns a truncated JSON string with first `n_json_entries`.
    3. If it's a JSON list of other types, returns the first `n_chars` of the original string.
    4. If it's a single JSON object or invalid JSON, returns the first `n_chars` of the original string.
    5. If input is not a string, returns it as-is.

    Args:
        text_string (str): The input string.
        n_chars (int): The number of characters (for text) or records (for JSON arrays) to return.
        n_json_entries (int): The number of JSON entries to return from an array of JSON objects

    Returns:
        str: A new string containing only the first n_lines or first n_records for JSON arrays.
    """
    if not isinstance(text_string, str):
        return text_string  # Return non-string input as-is

    try:
        parsed = json.loads(text_string)

        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            # Truncate the list and re-serialize to JSON string
            truncated_list = parsed[:n_json_entries]
            return json.dumps(truncated_list)
        # Return original string truncated to n_chars
        return text_string[:n_chars]

    except (json.JSONDecodeError, TypeError):
        return text_string[:n_chars]


def escape_query_value(value: str) -> str:
    """
    Escape special characters in a value for use in Lucene-style search queries.
    Escapes backslashes and quotes, then wraps the value in quotes.

    Args:
        value: The value to escape

    Returns:
        The escaped and quoted value safe for use in search queries

    Example:
        >>> escape_query_value("Flow: Test 2024-01-01T12:00:00Z")
        '"Flow: Test 2024-01-01T12:00:00Z"'
    """
    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped_value}"'


def trim_whitespace_span(*, text: str, start: int, end: int) -> tuple[int, int]:
    """Move a ``[start, end)`` span inward past leading and trailing whitespace.

    The text is never modified, so ``text[new_start:new_end]`` is always a substring
    of ``text[start:end]``.  A whitespace-only span collapses to ``new_start == new_end``.

    Args:
        text: Source text the offsets point into.
        start: Span start offset (inclusive).
        end: Span end offset (exclusive).

    Returns:
        The trimmed ``(start, end)`` offsets.
    """
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def is_null_or_empty(value: str | None) -> bool:
    """
    Mimic Guava Strings.isNullOrEmpty (no trimming).

    Args:
        value: String to check

    Returns:
        True if value is None or empty string, False otherwise
    """
    return value is None or value == ""
