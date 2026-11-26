# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the rendering branches of FlowExecutionReporter (schema, metadata and document lists).

Output is checked on the stripped log lines, so the tests pin wording and order but not the exact indentation.
"""

import re
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter


def _render(mock_method) -> list[str]:
    """Return the %-formatted, stripped messages passed to a mocked logger method, in call order."""
    rendered = []
    for call in mock_method.call_args_list:
        msg, *args = call.args
        rendered.append((msg % tuple(args) if args else msg).strip())
    return rendered


def _index(lines: list[str], pattern: str) -> int:
    """Return the index of the first line matching the regex ``pattern``."""
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            return i
    raise AssertionError(f"no line matches {pattern!r} in {lines!r}")


def _has(lines: list[str], pattern: str) -> bool:
    """Return whether any line matches the regex ``pattern``."""
    return any(re.search(pattern, line) for line in lines)


@pytest.fixture
def reporter():
    """Create a fresh reporter."""
    return FlowExecutionReporter()


@pytest.fixture
def mock_logger():
    """Patch the reporter module logger."""
    with patch("docpipe.utils.infrastructure.flow_execution_reporter.logger") as mock:
        yield mock


def _stats(**kwargs) -> NodeStats:
    """Build NodeStats with sensible defaults."""
    defaults = {"id": "node-1", "name": "step", "node_status": ExecutionStatus.COMPLETED.value}
    defaults.update(kwargs)
    return NodeStats(**defaults)


def _table(columns) -> pa.Table:
    """Build a one-row table with the given column names."""
    return pa.table({c: [1] for c in columns})


def _run_two_operators(reporter, mock_logger, *, previous_tables, current_tables, col_names) -> list[str]:
    """Report two operators in a row and return the INFO lines of the second summary only.

    The first summary hands its tables over as the previous tables of the second one, which is how the
    reporter computes the schema diff.
    """
    reporter.print_operator_summary(step_name="first", node_stats=_stats(), tables=previous_tables)
    mock_logger.reset_mock()
    reporter.print_operator_summary(step_name="second", node_stats=_stats(col_names=col_names), tables=current_tables)
    return _render(mock_logger.info)


def _metadata_lines(reporter, mock_logger, metadata) -> list[str]:
    """Report one operator carrying ``metadata`` and return its INFO lines."""
    reporter.print_operator_summary(step_name="s", node_stats=_stats(node_metadata=metadata))
    return _render(mock_logger.info)


class TestOperatorSummary:
    """print_operator_summary renders optional schema and metadata sections."""

    def test_without_columns_or_metadata_prints_only_the_card(self, reporter, mock_logger):
        """No schema or metadata sections are printed when the stats carry none."""
        reporter.print_operator_summary(step_name="noop", node_stats=_stats())

        info = _render(mock_logger.info)
        assert "Duration: < 1s | Documents: 0 processed, 0 failed, 0 skipped" in info
        assert not _has(info, "Data Columns")
        assert not _has(info, "Operator Metrics")

    def test_metadata_section_is_printed_after_the_header(self, reporter, mock_logger):
        """node_metadata is rendered after the step header and the duration line."""
        info = _metadata_lines(reporter, mock_logger, {"chunks_created": 7})

        header = info.index(f"s ({ExecutionStatus.COMPLETED.value})")
        duration = _index(info, r"^Duration: ")
        metrics = info.index("Operator Metrics:")
        assert header < duration < metrics
        assert info[metrics + 1] == "Chunks Created: 7"


class TestSchemaInfo:
    """The schema section describes added, removed and existing columns relative to the previous operator."""

    def test_added_and_removed_columns(self, reporter, mock_logger):
        """Both counts appear in the header and each group is listed, separated by blank lines."""
        info = _run_two_operators(
            reporter,
            mock_logger,
            previous_tables=[_table(["id", "old"])],
            current_tables=[_table(["id", "new"])],
            col_names=["id", "new"],
        )

        assert _has(info, r"Data Columns: 2 total \(1 added, 1 removed by this operator\)")
        added = info.index("Added (1):")
        assert info[added + 1 : added + 3] == ["new", ""]
        removed = info.index("Removed (1):")
        assert info[removed + 1 : removed + 3] == ["old", ""]
        assert info[removed + 3] == "Existing (1): id"

    def test_only_removed_columns(self, reporter, mock_logger):
        """A pure removal is described without an Added section."""
        info = _run_two_operators(
            reporter,
            mock_logger,
            previous_tables=[_table(["id", "old"])],
            current_tables=[_table(["id"])],
            col_names=["id"],
        )

        assert _has(info, r"Data Columns: 1 total \(1 removed by this operator\)")
        assert not _has(info, r"^Added")

    def test_removed_columns_without_existing_ones(self, reporter, mock_logger):
        """When every column is new, the Removed list is not followed by a blank separator."""
        info = _run_two_operators(
            reporter,
            mock_logger,
            previous_tables=[_table(["old"])],
            current_tables=[_table(["new"])],
            col_names=["new"],
        )

        removed = info.index("Removed (1):")
        assert info[removed + 1] == "old"
        assert info[removed + 2] == "=" * 80

    def test_unchanged_columns(self, reporter, mock_logger):
        """Without changes only the total and the existing columns are shown."""
        info = _run_two_operators(
            reporter, mock_logger, previous_tables=[_table(["id"])], current_tables=[_table(["id"])], col_names=["id"]
        )

        assert "Data Columns: 1 total" in info
        assert "Existing (1): id" in info

    def test_first_operator_lists_all_columns_as_added(self, reporter, mock_logger):
        """With no previous tables every column is new and nothing follows the Added list."""
        reporter.print_operator_summary(step_name="s", node_stats=_stats(col_names=["a", "b"]), tables=[_table("ab")])

        info = _render(mock_logger.info)
        added = info.index("Added (2):")
        assert info[added + 1 : added + 3] == ["a, b", "=" * 80]

    def test_more_than_ten_existing_columns_are_truncated(self, reporter, mock_logger):
        """Only the first ten existing columns are named."""
        cols = [f"c{i}" for i in range(12)]

        info = _run_two_operators(
            reporter, mock_logger, previous_tables=[_table(cols)], current_tables=[_table(cols)], col_names=cols
        )

        assert f"Existing (12): {', '.join(cols[:10])}" in info
        assert _has(info, r"\.\.\. and 2 more")

    def test_tables_without_schema_give_no_diff(self, reporter, mock_logger):
        """Objects without column_names give no schema diff: all columns are new, none removed."""
        info = _run_two_operators(
            reporter, mock_logger, previous_tables=[object()], current_tables=[object()], col_names=["a"]
        )

        assert _has(info, r"Data Columns: 1 total \(1 added by this operator\)")
        assert not _has(info, r"^Removed")


class TestColumnLayout:
    """Wrapped and grouped column lists."""

    def test_wrapped_list_without_trailing_empty_line(self, reporter, mock_logger):
        """An empty last column name after a flushed long line does not produce an empty column line."""
        long_name = "x" * 75
        cols = [f"c{i}" for i in range(10)] + [long_name, ""]

        reporter.print_operator_summary(step_name="s", node_stats=_stats(col_names=cols))

        info = _render(mock_logger.info)
        added = info.index("Added (12):")
        assert info[added + 1 : added + 4] == [", ".join(cols[:10]), long_name, "=" * 80]

    def test_single_columns_per_prefix_go_to_other(self, reporter):
        """Prefixes shared by fewer than two columns are collected under Other."""
        groups = reporter._group_columns_by_prefix(["ml_a", "ml_b", "lang_x", "plain"])

        assert groups == {"ML Features": ["ml_a", "ml_b"], "Other": ["lang_x", "plain"]}


class TestOperatorMetadata:
    """The metadata section and its per-type renderers."""

    @pytest.mark.parametrize(
        "metadata",
        [{"node_metadata": {}}, {"processed_docs": 3, "node_status": "COMPLETED", "empty": None, "blank": ""}],
        ids=["empty-wrapped", "only-standard-or-empty"],
    )
    def test_nothing_to_show_prints_no_section(self, reporter, mock_logger, metadata):
        """An empty wrapped dict, or only standard/empty fields, add nothing after the duration line."""
        info = _metadata_lines(reporter, mock_logger, metadata)

        duration = _index(info, r"^Duration: ")
        assert info[duration + 1 :] == ["=" * 80, ""]

    def test_dict_fields_without_numeric_get_a_details_header(self, reporter, mock_logger):
        """Dict-only metadata is introduced by an Operator Details header and rendered by shape."""
        metadata = {
            "nested_stats": {"by_lang": {"en": 2, "de": 1}, "total": 3},
            "small_map": {"a": 1, "b": 2},
        }

        info = _metadata_lines(reporter, mock_logger, metadata)

        assert "Operator Details:" in info
        assert "Operator Metrics:" not in info
        nested = info.index("Nested Stats:")
        assert info[nested + 1 : nested + 5] == ["by_lang:", "en: 2", "de: 1", "total: 3"]
        assert "Small Map: a=1, b=2" in info

    @pytest.mark.parametrize("size", [10, 11])
    def test_flat_dict_inline_up_to_ten_entries(self, reporter, mock_logger, size):
        """Up to ten entries are shown inline; from eleven on the first ten are listed, then a remainder line."""
        big_map = {f"k{i}": i for i in range(size)}

        info = _metadata_lines(reporter, mock_logger, {"big_map": big_map})

        if size <= 10:
            assert f"Big Map: {', '.join(f'k{i}={i}' for i in range(size))}" in info
            assert not _has(info, r"\.\.\. and \d+ more")
        else:
            big = info.index("Big Map:")
            assert info[big + 1 : big + 11] == [f"k{i}: {i}" for i in range(10)]
            assert info[big + 11] == "... and 1 more"

    def test_dict_fields_after_numeric_have_no_details_header(self, reporter, mock_logger):
        """When numeric metrics are present the dict fields follow them directly."""
        info = _metadata_lines(reporter, mock_logger, {"count": 2, "small_map": {"a": 1}})

        assert "Operator Metrics:" in info
        assert "Operator Details:" not in info
        assert "Small Map: a=1" in info

    def test_other_fields_are_truncated_at_100_characters(self, reporter, mock_logger):
        """Long string values are cut to 97 characters plus an ellipsis; zero is shown as a value."""
        info = _metadata_lines(reporter, mock_logger, {"model": "x" * 150, "retries": 0})

        assert f"Model: {'x' * 97}..." in info
        assert "Retries: 0" in info

    def test_empty_list(self, reporter, mock_logger):
        """An empty list is shown as []."""
        assert "Empty List: []" in _metadata_lines(reporter, mock_logger, {"empty_list": []})

    @pytest.mark.parametrize(
        ("size", "expected"),
        [(5, "Ids: 0, 1, 2, 3, 4"), (6, "Ids (6 items): 0, 1, 2, ...")],
        ids=["five-inline", "six-preview"],
    )
    def test_generic_list_boundary(self, reporter, mock_logger, size, expected):
        """Up to five items are listed inline; longer lists show a count and a three-item preview."""
        assert expected in _metadata_lines(reporter, mock_logger, {"ids": list(range(size))})

    def test_failed_docs_are_logged_at_error_level_with_names(self, reporter, mock_logger):
        """Failed docs go to ERROR, resolving names from the current table, the item, or the id."""
        failed = [
            {"id": "h1", "reason": "parse error"},
            {"id": "h2", "name": "fallback.docx"},
            {"id": "h3"},
            "plain-entry",
        ]

        reporter.print_operator_summary(
            step_name="s",
            node_stats=_stats(node_metadata={"failed_docs": failed}),
            tables=[pa.table({"id": ["h1"], "name": ["report.pdf"]})],
        )

        errors = _render(mock_logger.error)
        listed = _index(errors, r"^FAILED DOCS \(4 ")
        assert errors[listed - 1] == ""
        assert errors[listed + 1 :] == ["- report.pdf: parse error", "- fallback.docx", "- h3", "- plain-entry"]

    def test_skipped_docs_are_logged_at_info_level(self, reporter, mock_logger):
        """Skipped docs stay at INFO; an empty failed list prints nothing."""
        info = _metadata_lines(
            reporter, mock_logger, {"skipped_docs": [{"id": "s1", "reason": "duplicate"}], "failed_docs": []}
        )

        skipped = _index(info, r"^SKIPPED DOCS \(1 ")
        assert info[skipped + 1] == "- s1: duplicate"
        mock_logger.error.assert_not_called()


class TestDocumentNameLookup:
    """Resolving a display name from the id/name/path columns."""

    def test_name_equal_to_id_falls_back_to_path(self, reporter):
        """A name column that only repeats the id is skipped in favour of the path."""
        reporter._current_tables = [pa.table({"id": ["h1"], "name": ["h1"], "path": ["/docs/a.pdf"]})]

        assert reporter._lookup_doc_name_from_table("h1") == "/docs/a.pdf"

    def test_row_without_usable_name_returns_none(self, reporter):
        """Empty name and missing path yield no display name."""
        reporter._current_tables = [pa.table({"id": ["h1"], "name": [""]})]

        assert reporter._lookup_doc_name_from_table("h1") is None

    def test_empty_doc_id_returns_none(self, reporter):
        """A falsy id is not looked up."""
        reporter._current_tables = [pa.table({"id": [""], "name": ["x"]})]

        assert reporter._lookup_doc_name_from_table("") is None

    def test_none_tables_are_skipped(self, reporter):
        """None entries in the table list are ignored."""
        reporter._current_tables = [None, pa.table({"id": ["h1"], "name": ["a.pdf"]})]

        assert reporter._lookup_doc_name_from_table("h1") == "a.pdf"
