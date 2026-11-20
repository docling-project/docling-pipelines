# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the rendering branches of FlowExecutionReporter (schema, metadata and document lists)."""

from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter


def _render(mock_method) -> list[str]:
    """Return the %-formatted messages passed to a mocked logger method, in call order."""
    rendered = []
    for call in mock_method.call_args_list:
        msg, *args = call.args
        rendered.append(msg % tuple(args) if args else msg)
    return rendered


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


class TestOperatorSummary:
    """print_operator_summary renders optional schema and metadata sections."""

    def test_without_columns_or_metadata_prints_only_the_card(self, reporter, mock_logger):
        """No schema or metadata sections are printed when the stats carry none."""
        reporter.print_operator_summary(step_name="noop", node_stats=_stats())

        info = _render(mock_logger.info)
        assert " Duration: < 1s | Documents: 0 processed, 0 failed, 0 skipped" in info
        assert not any("Data Columns" in line for line in info)
        assert not any("Operator Metrics" in line for line in info)

    def test_metadata_section_is_printed(self, reporter, mock_logger):
        """node_metadata is rendered after the header."""
        reporter.print_operator_summary(step_name="s", node_stats=_stats(node_metadata={"chunks_created": 7}))

        info = _render(mock_logger.info)
        assert " Operator Metrics:" in info
        assert "   Chunks Created: 7" in info


class TestSchemaInfo:
    """_print_schema_info describes added, removed and existing columns."""

    @staticmethod
    def _diff(reporter, *, previous, current):
        """Set up previous/current tables with the given column names."""
        reporter._previous_tables = [pa.table({c: [1] for c in previous})]
        reporter._current_tables = [pa.table({c: [1] for c in current})]

    def test_added_and_removed_columns(self, reporter, mock_logger):
        """Both counts appear in the header and each group is listed."""
        self._diff(reporter, previous=["id", "old"], current=["id", "new"])

        reporter._print_schema_info(col_names=["id", "new"], step_name="s")

        info = _render(mock_logger.info)
        assert " Data Columns: 2 total (1 added, 1 removed by this operator)" in info
        assert info[info.index("   Added (1):") + 1] == "     new"
        removed = info.index("   Removed (1):")
        assert info[removed + 1] == "     old"
        assert info[removed + 2] == ""
        assert "   Existing (1): id" in info

    def test_only_removed_columns(self, reporter, mock_logger):
        """A pure removal is described without an Added section."""
        self._diff(reporter, previous=["id", "old"], current=["id"])

        reporter._print_schema_info(col_names=["id"], step_name="s")

        info = _render(mock_logger.info)
        assert " Data Columns: 1 total (1 removed by this operator)" in info
        assert not any(line.startswith("   Added") for line in info)

    def test_removed_columns_without_existing_ones(self, reporter, mock_logger):
        """When every column is new, the Removed list is not followed by a blank separator."""
        self._diff(reporter, previous=["old"], current=["new"])

        reporter._print_schema_info(col_names=["new"], step_name="s")

        info = _render(mock_logger.info)
        assert info[-2:] == ["   Removed (1):", "     old"]

    def test_unchanged_columns(self, reporter, mock_logger):
        """Without changes only the total and the existing columns are shown."""
        self._diff(reporter, previous=["id"], current=["id"])

        reporter._print_schema_info(col_names=["id"], step_name="s")

        info = _render(mock_logger.info)
        assert " Data Columns: 1 total" in info
        assert "   Existing (1): id" in info

    def test_first_operator_lists_all_columns_as_added(self, reporter, mock_logger):
        """With no previous tables every column is new and nothing follows the Added list."""
        reporter._print_schema_info(col_names=["a", "b"], step_name="s")

        assert _render(mock_logger.info)[-2:] == ["   Added (2):", "     a, b"]

    def test_more_than_ten_existing_columns_are_truncated(self, reporter, mock_logger):
        """Only the first ten existing columns are named."""
        cols = [f"c{i}" for i in range(12)]
        self._diff(reporter, previous=cols, current=cols)

        reporter._print_schema_info(col_names=cols, step_name="s")

        info = _render(mock_logger.info)
        assert f"   Existing (12): {', '.join(cols[:10])}" in info
        assert "      ... and 2 more" in info

    def test_empty_column_list_prints_nothing(self, reporter, mock_logger):
        """An empty schema produces no output."""
        reporter._print_schema_info(col_names=[], step_name="s")

        mock_logger.info.assert_not_called()

    def test_tables_without_schema_fall_back(self, reporter):
        """Objects without column_names give no schema diff: all columns are new, none removed."""
        reporter._previous_tables = [object()]
        reporter._current_tables = [object()]

        assert reporter._get_new_columns(col_names=["a"]) == ["a"]
        assert reporter._get_removed_columns(col_names=["a"]) == []


class TestColumnLayout:
    """Wrapped and grouped column lists."""

    def test_wrapped_empty_list_prints_nothing(self, mock_logger):
        """No columns means no line."""
        FlowExecutionReporter._print_wrapped_columns([], indent="  ")

        mock_logger.info.assert_not_called()

    def test_grouped_empty_list_falls_back_to_wrapped(self, reporter, mock_logger):
        """An empty grouping is delegated to the wrapped printer."""
        with patch.object(FlowExecutionReporter, "_print_wrapped_columns") as wrapped:
            reporter._print_grouped_columns([], indent="  ")

        wrapped.assert_called_once_with([], indent="  ")

    def test_single_columns_per_prefix_go_to_other(self, reporter):
        """Prefixes shared by fewer than two columns are collected under Other."""
        groups = reporter._group_columns_by_prefix(["ml_a", "ml_b", "lang_x", "plain"])

        assert groups == {"ML Features": ["ml_a", "ml_b"], "Other": ["lang_x", "plain"]}


class TestOperatorMetadata:
    """_print_operator_metadata and its per-type renderers."""

    @pytest.mark.parametrize(
        "metadata",
        [{}, {"node_metadata": {}}, {"processed_docs": 3, "node_status": "COMPLETED", "empty": None, "blank": ""}],
        ids=["empty", "empty-wrapped", "only-standard-or-empty"],
    )
    def test_nothing_to_show_prints_nothing(self, reporter, mock_logger, metadata):
        """Empty metadata, an empty wrapped dict, or only standard/empty fields print nothing."""
        reporter._print_operator_metadata(metadata)

        mock_logger.info.assert_not_called()

    def test_dict_fields_without_numeric_get_a_details_header(self, reporter, mock_logger):
        """Dict-only metadata is introduced by an Operator Details header and rendered by shape."""
        metadata = {
            "nested_stats": {"by_lang": {"en": 2, "de": 1}, "total": 3},
            "small_map": {"a": 1, "b": 2},
            "big_map": {f"k{i}": i for i in range(12)},
        }

        reporter._print_operator_metadata(metadata)

        info = _render(mock_logger.info)
        assert " Operator Details:" in info
        assert " Operator Metrics:" not in info
        nested = info.index("   Nested Stats:")
        assert info[nested + 1 : nested + 5] == ["      by_lang:", "         en: 2", "         de: 1", "      total: 3"]
        assert "   Small Map: a=1, b=2" in info
        big = info.index("   Big Map:")
        assert info[big + 1] == "      k0: 0"
        assert info[big + 10] == "      k9: 9"
        assert info[big + 11] == "      ... and 2 more"

    def test_dict_fields_after_numeric_have_no_details_header(self, reporter, mock_logger):
        """When numeric metrics are present the dict fields follow them directly."""
        reporter._print_operator_metadata({"count": 2, "small_map": {"a": 1}})

        info = _render(mock_logger.info)
        assert " Operator Metrics:" in info
        assert " Operator Details:" not in info
        assert "   Small Map: a=1" in info

    def test_other_fields_are_truncated_at_100_characters(self, reporter, mock_logger):
        """Long string values are cut to 97 characters plus an ellipsis; zero is shown as a value."""
        reporter._print_operator_metadata({"model": "x" * 150, "retries": 0})

        info = _render(mock_logger.info)
        assert f"   Model: {'x' * 97}..." in info
        assert "   Retries: 0" in info

    def test_generic_lists_by_length(self, reporter, mock_logger):
        """Empty, short and long lists use their own formats."""
        reporter._print_operator_metadata({"empty_list": [], "short_list": [1, 2], "long_list": list(range(7))})

        info = _render(mock_logger.info)
        assert "   Empty List: []" in info
        assert "   Short List: 1, 2" in info
        assert "   Long List (7 items): 0, 1, 2, ..." in info

    def test_failed_docs_are_logged_at_error_level_with_names(self, reporter, mock_logger):
        """Failed docs go to ERROR, resolving names from the current table, the item, or the id."""
        reporter._current_tables = [pa.table({"id": ["h1"], "name": ["report.pdf"]})]
        failed = [
            {"id": "h1", "reason": "parse error"},
            {"id": "h2", "name": "fallback.docx"},
            {"id": "h3"},
            "plain-entry",
        ]

        reporter._print_operator_metadata({"failed_docs": failed})

        errors = _render(mock_logger.error)
        assert errors == [
            "",
            " FAILED DOCS (4 items):",
            "   - report.pdf: parse error",
            "   - fallback.docx",
            "   - h3",
            "   - plain-entry",
        ]

    def test_skipped_docs_are_logged_at_info_level(self, reporter, mock_logger):
        """Skipped docs stay at INFO; an empty failed list prints nothing."""
        reporter._print_operator_metadata({"skipped_docs": [{"id": "s1", "reason": "duplicate"}], "failed_docs": []})

        assert " SKIPPED DOCS (1 items):" in _render(mock_logger.info)
        assert "   - s1: duplicate" in _render(mock_logger.info)
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
