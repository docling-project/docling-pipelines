# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for OperatorUtils.doclang_to_markdown and strip_doclang_column."""

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_utils import OperatorUtils

DOCLANG = OperatorConstants.DocFormat.DOCLANG
MARKDOWN = OperatorConstants.DocFormat.MARKDOWN

# Real DocLang XML produced by DoclingDocument.export_to_doclang()
_DOCLANG_PARA = '<doclang version="0.7">\n  <text>The quick brown fox jumps over the lazy dog.</text>\n</doclang>'
_DOCLANG_NESTED = (
    '<doclang version="0.7">\n  <heading level="2">My Title</heading>\n  <text>Body text here.</text>\n</doclang>'
)

# ---------------------------------------------------------------------------
# doclang_to_markdown
# ---------------------------------------------------------------------------


def test_doclang_to_markdown_plain_text_unchanged():
    """Non-XML string passes through without modification."""
    text = "Hello world"
    assert OperatorUtils.doclang_to_markdown(text) == text


def test_doclang_to_markdown_markdown_unchanged():
    """Markdown string (starts with '#') is returned as-is."""
    text = "# Heading\n\nSome paragraph text."
    assert OperatorUtils.doclang_to_markdown(text) == text


def test_doclang_to_markdown_empty_string():
    """Empty string returns empty string."""
    assert OperatorUtils.doclang_to_markdown("") == ""


def test_doclang_to_markdown_paragraph():
    """Real DocLang paragraph XML is converted to plain markdown text."""
    result = OperatorUtils.doclang_to_markdown(_DOCLANG_PARA)
    assert result == "The quick brown fox jumps over the lazy dog."


def test_doclang_to_markdown_heading_and_paragraph():
    """DocLang with a heading and paragraph produces markdown with heading markers."""
    result = OperatorUtils.doclang_to_markdown(_DOCLANG_NESTED)
    assert "My Title" in result
    assert "Body text here." in result
    assert "<" not in result


def test_doclang_to_markdown_malformed_xml_falls_back_to_regex():
    """Input that fails DocLangDocDeserializer falls back to regex tag stripping."""
    # Use content that looks like XML but is genuinely malformed at the parser level
    malformed = "<<<not valid xml at all>>> some text <tag>"
    result = OperatorUtils.doclang_to_markdown(malformed)
    assert "some text" in result


def test_doclang_to_markdown_no_xml_in_output():
    """Output from real DocLang XML contains no XML angle brackets."""
    result = OperatorUtils.doclang_to_markdown(_DOCLANG_NESTED)
    assert "<" not in result
    assert ">" not in result


def test_doclang_to_markdown_import_error_falls_back_to_regex():
    """When docling_core is unavailable (slim without [extract]), an ImportError
    is caught and a regex tag strip is used as fallback."""
    import sys
    from unittest.mock import patch

    # Temporarily make the module unimportable by patching the import machinery
    with patch.dict(sys.modules, {"docling_core.transforms.deserializer.doclang": None}):
        xml = '<doclang version="0.7"><text>Hello slim world</text></doclang>'
        result = OperatorUtils.doclang_to_markdown(xml)

    assert "Hello slim world" in result
    assert "<" not in result


# ---------------------------------------------------------------------------
# strip_doclang_column
# ---------------------------------------------------------------------------


def test_strip_doclang_column_doclang_strips_named_column():
    """strip_doclang_column converts DocLang XML in the named column to markdown."""
    import pyarrow as pa

    hello_xml = '<doclang version="0.7">\n  <text>Hello</text>\n</doclang>'
    world_xml = '<doclang version="0.7">\n  <text>World</text>\n</doclang>'
    table = pa.table({"id": ["0", "1"], "content": [hello_xml, world_xml]})
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=DOCLANG)
    values = result["content"].to_pylist()
    assert all("<" not in v for v in values)
    assert "Hello" in values[0]
    assert "World" in values[1]


def test_strip_doclang_column_markdown_is_noop():
    """strip_doclang_column is a no-op when doc_format=markdown."""
    import pyarrow as pa

    xml = "<doc><p>Unchanged</p></doc>"
    table = pa.table({"id": ["0"], "content": [xml]})
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=MARKDOWN)
    assert result["content"][0].as_py() == xml


def test_strip_doclang_column_missing_column_is_noop():
    """strip_doclang_column is a no-op when the named column does not exist."""
    import pyarrow as pa

    table = pa.table({"id": ["0"], "other": ["value"]})
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=DOCLANG)
    assert result is table  # same object returned unchanged


def test_strip_doclang_column_returns_new_table_when_stripped():
    """strip_doclang_column returns a new table, not mutating the original."""
    import pyarrow as pa

    table = pa.table({"id": ["0"], "content": [_DOCLANG_PARA]})
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=DOCLANG)
    # Original still contains XML tags
    assert "<" in table["content"][0].as_py()
    # Result has no XML tags
    assert "<" not in result["content"][0].as_py()


def test_strip_doclang_column_handles_none_values():
    """strip_doclang_column converts None values to empty strings without error."""
    import pyarrow as pa

    text_xml = '<doclang version="0.7">\n  <text>Text</text>\n</doclang>'
    table = pa.table({"id": ["0", "1"], "content": pa.array([None, text_xml], type=pa.string())})
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=DOCLANG)
    assert result["content"][0].as_py() == ""
    assert "Text" in result["content"][1].as_py()


def test_strip_doclang_column_reuses_content_markdown_when_present():
    """strip_doclang_column reuses content_markdown without deserializing DocLang XML."""
    import pyarrow as pa

    xml = '<doclang version="0.7">\n  <text>From DocLang</text>\n</doclang>'
    markdown_text = "From Existing Markdown"
    table = pa.table(
        {
            "id": ["0"],
            "content": [xml],
            OperatorConstants.Columns.CONTENT_MARKDOWN: [markdown_text],
        }
    )
    result = OperatorUtils.strip_doclang_column(table, col_name="content", doc_format=DOCLANG)
    assert result["content"][0].as_py() == markdown_text


# ---------------------------------------------------------------------------
# DocFormat constants
# ---------------------------------------------------------------------------


def test_get_markdown_content_col_reuses_content_markdown():
    """get_markdown_content_col returns content_markdown directly when present."""
    import pyarrow as pa

    table = pa.table(
        {
            "id": ["0"],
            "content": ['<doclang version="0.7"><text>DocLang</text></doclang>'],
            OperatorConstants.Columns.CONTENT_MARKDOWN: ["Markdown Text"],
        }
    )
    res = OperatorUtils.get_markdown_content_col(table=table, col_name="content", doc_format=DOCLANG)
    assert res == ["Markdown Text"]


def test_get_markdown_content_col_converts_doclang_when_no_content_markdown():
    """get_markdown_content_col converts DocLang to markdown when content_markdown is absent."""
    import pyarrow as pa

    hello_xml = '<doclang version="0.7">\n  <text>Hello World</text>\n</doclang>'
    table = pa.table({"id": ["0"], "content": [hello_xml]})
    res = OperatorUtils.get_markdown_content_col(table=table, col_name="content", doc_format=DOCLANG)
    assert len(res) == 1
    assert "<" not in res[0]
    assert "Hello World" in res[0]


def test_get_markdown_content_col_returns_raw_content_when_markdown_format():
    """get_markdown_content_col returns raw column list when doc_format is markdown."""
    import pyarrow as pa

    table = pa.table({"id": ["0"], "content": ["Plain Markdown Content"]})
    res = OperatorUtils.get_markdown_content_col(table=table, col_name="content", doc_format=MARKDOWN)
    assert res == ["Plain Markdown Content"]


def test_get_markdown_content_col_returns_empty_when_column_missing():
    """get_markdown_content_col returns empty list when column is missing."""
    import pyarrow as pa

    table = pa.table({"id": ["0"]})
    res = OperatorUtils.get_markdown_content_col(table=table, col_name="content", doc_format=DOCLANG)
    assert res == []


def test_doc_format_constants_values():
    """DocFormat enum members have the expected string values."""
    assert OperatorConstants.DocFormat.MARKDOWN == "markdown"
    assert OperatorConstants.DocFormat.DOCLANG == "doclang"
    assert OperatorConstants.DOC_FORMAT_KEY == "doc_format"
    assert OperatorConstants.DOC_FORMAT_DEFAULT == "markdown"


def test_doc_format_valid_values_contains_both():
    """All valid format values are present when iterating the enum."""
    values = [m.value for m in OperatorConstants.DocFormat]
    assert "markdown" in values
    assert "doclang" in values


# ---------------------------------------------------------------------------
# get_doclang_deserializer: created on first use, once, and tolerant of a slim install
# ---------------------------------------------------------------------------


def _reset_deserializer_state(monkeypatch):
    from docpipe.core.operators import operator_utils

    monkeypatch.setattr(operator_utils, "_DOCLANG_DESERIALIZER", None)
    monkeypatch.setattr(operator_utils, "_DOCLANG_DESERIALIZER_LOADED", False)
    return operator_utils


def test_get_doclang_deserializer_returns_one_shared_instance(monkeypatch):
    """Concurrent first calls create exactly one deserializer."""
    from concurrent.futures import ThreadPoolExecutor

    _reset_deserializer_state(monkeypatch)
    with ThreadPoolExecutor(max_workers=8) as pool:
        instances = list(pool.map(lambda _: OperatorUtils.get_doclang_deserializer(), range(16)))
    assert instances[0] is not None
    assert all(instance is instances[0] for instance in instances)


def test_get_doclang_deserializer_is_none_when_docling_core_is_absent(monkeypatch):
    """A slim install without docling_core gets None, and the absence is remembered."""
    import builtins

    _reset_deserializer_state(monkeypatch)
    real_import = builtins.__import__
    calls: list[str] = []

    def blocked(name, *args, **kwargs):
        if name.startswith("docling_core"):
            calls.append(name)
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert OperatorUtils.get_doclang_deserializer() is None
    assert OperatorUtils.get_doclang_deserializer() is None
    assert len(calls) == 1
