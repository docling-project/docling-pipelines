# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for the deleted rows tracker.

Tests cover:
- Combining cumulative deleted rows with differing schemas
- Detecting deleted rows from single tables, lists and dicts of tables
- Dropping heavy columns (including config-renamed ones) and tagging the step
- Graceful fallbacks when detection, column filtering or tagging fail
"""

from queue import Queue
from types import SimpleNamespace

import pyarrow as pa

from docpipe.utils.orchestration.deleted_rows_tracker import combine_cumulative_deleted_rows, update_deleted_rows


def _op(**config):
    """Return a minimal operator stand-in with id, name and config."""
    return SimpleNamespace(id="n1", name="filter", config=config)


class TestCombineCumulativeDeletedRows:
    """Test combine_cumulative_deleted_rows."""

    def test_none_returns_empty_table(self):
        """A missing queue yields an empty table."""
        assert combine_cumulative_deleted_rows(None).num_rows == 0  # type: ignore[arg-type]

    def test_empty_queue_returns_empty_table(self):
        """An empty queue yields an empty table."""
        result = combine_cumulative_deleted_rows(Queue())

        assert result.num_rows == 0
        assert result.num_columns == 0

    def test_combines_tables_with_different_columns(self):
        """Tables are aligned to the union of all columns, missing values become null."""
        queue: Queue[pa.Table] = Queue()
        queue.put(pa.table({"id": ["a"], "reason": ["dup"]}))
        queue.put(pa.table({"id": ["b"], "deleted_at_step": ["n2_x"]}))

        result = combine_cumulative_deleted_rows(queue)

        assert sorted(result.column_names) == ["deleted_at_step", "id", "reason"]
        rows = sorted(result.to_pylist(), key=lambda r: r["id"])
        assert rows == [
            {"deleted_at_step": None, "id": "a", "reason": "dup"},
            {"deleted_at_step": "n2_x", "id": "b", "reason": None},
        ]
        # The queue is read, not drained
        assert queue.qsize() == 2

    def test_incompatible_types_return_empty_table(self):
        """When the tables cannot be concatenated, an empty table is returned."""
        queue: Queue[pa.Table] = Queue()
        queue.put(pa.table({"id": pa.array([1], type=pa.int64())}))
        queue.put(pa.table({"id": pa.array([[1]], type=pa.list_(pa.int64()))}))

        result = combine_cumulative_deleted_rows(queue)

        assert result.num_rows == 0


class TestUpdateDeletedRows:
    """Test update_deleted_rows."""

    def test_equal_row_counts_return_empty_table(self):
        """Same total rows before and after means nothing was deleted."""
        prev = pa.table({"id": ["a", "b"]})

        assert update_deleted_rows(prev, [pa.table({"id": ["c", "d"]})], [], _op()).num_rows == 0

    def test_single_table_detects_deleted_rows_and_tags_step(self):
        """Rows missing from the current step are returned, heavy columns dropped, step tagged."""
        prev = pa.table({"id": ["a", "b", "c"], "content": ["x", "y", "z"], "title": ["A", "B", "C"]})
        current = [pa.table({"id": ["a"], "content": ["x"], "title": ["A"]})]

        result = update_deleted_rows(prev, current, ["content"], _op())

        assert result.column_names == ["id", "title", "deleted_at_step"]
        assert result.to_pylist() == [
            {"id": "b", "title": "B", "deleted_at_step": "n1_filter"},
            {"id": "c", "title": "C", "deleted_at_step": "n1_filter"},
        ]

    def test_skip_columns_are_resolved_through_operator_config(self):
        """A skip column name is looked up in the operator config first (renamed doc column)."""
        prev = pa.table({"id": ["a", "b"], "body": ["x", "y"]})
        current = [pa.table({"id": ["a"], "body": ["x"]})]

        result = update_deleted_rows(prev, current, ["doc_column"], _op(doc_column="body"))

        assert result.column_names == ["id", "deleted_at_step"]
        assert result.column("id").to_pylist() == ["b"]

    def test_list_of_previous_tables_is_combined(self):
        """Previous tables given as a list are concatenated before comparison."""
        prev = [pa.table({"id": ["a"]}), pa.table({"id": ["b"]})]

        result = update_deleted_rows(prev, [pa.table({"id": ["b"]})], [], _op())

        assert result.column("id").to_pylist() == ["a"]

    def test_dict_of_previous_tables_is_combined(self):
        """Previous tables given as a dict are concatenated before comparison."""
        prev = {"branch_a": pa.table({"id": ["a"]}), "branch_b": pa.table({"id": ["b"]})}

        result = update_deleted_rows(prev, [pa.table({"id": ["a"]})], [], _op())

        assert result.column("id").to_pylist() == ["b"]

    def test_no_previous_tables_return_empty_table(self):
        """Without previous tables there is nothing that could have been deleted."""
        assert update_deleted_rows(None, [pa.table({"id": ["a"]})], [], _op()).num_rows == 0

    def test_added_rows_only_return_empty_table(self):
        """More rows than before, but none missing, yields no deleted rows."""
        prev = pa.table({"id": ["a"]})

        assert update_deleted_rows(prev, [pa.table({"id": ["a", "b"]})], [], _op()).num_rows == 0

    def test_missing_id_column_returns_empty_table(self):
        """If the id column is missing, detection fails gracefully with an empty table."""
        prev = pa.table({"name": ["a", "b"]})

        assert update_deleted_rows(prev, [pa.table({"name": ["a"]})], [], _op()).num_rows == 0

    def test_column_filter_failure_keeps_all_columns(self):
        """If the operator config cannot resolve skip columns, the rows are still tagged with all columns."""
        prev = pa.table({"id": ["a", "b"], "content": ["x", "y"]})
        op = SimpleNamespace(id="n1", name="filter", config=None)

        result = update_deleted_rows(prev, [pa.table({"id": ["a"], "content": ["x"]})], ["content"], op)

        assert result.column_names == ["content", "id", "deleted_at_step"]
        assert result.to_pylist() == [{"content": "y", "id": "b", "deleted_at_step": "n1_filter"}]

    def test_operator_without_id_returns_empty_table(self):
        """If the step tag cannot be built, an empty table is returned."""
        prev = pa.table({"id": ["a", "b"]})
        op = SimpleNamespace(name="filter", config={})

        assert update_deleted_rows(prev, [pa.table({"id": ["a"]})], [], op).num_rows == 0
