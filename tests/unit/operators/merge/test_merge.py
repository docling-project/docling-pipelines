#!/usr/bin/env python3
"""
Unit tests for MergeOperator.

Tests the operator that combines multiple PyArrow tables using row concatenation
or column joins.
"""

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.merge import MergeOperator
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowExecutionFailedException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_table(*, num_rows: int = 3, id_prefix: str = "", extra_columns=None) -> pa.Table:
    """
    Create a test PyArrow table with standard columns.

    Args:
        num_rows: Number of rows to create
        id_prefix: Prefix for ID values to ensure uniqueness
        extra_columns: dict of additional columns to include
    """
    data = {
        "id": [f"{id_prefix}{i + 1}" for i in range(num_rows)],
        "name": [f"doc_{id_prefix}{i + 1}.txt" for i in range(num_rows)],
        "size": [100 + i for i in range(num_rows)],
    }
    if extra_columns:
        data.update(extra_columns)
    return pa.table(data)


def make_operator(*, config=None) -> MergeOperator:
    """
    Create a MergeOperator with optional config.

    Args:
        config: Configuration dict
    """
    if config is None:
        config = {
            "merge_type": "rows",
            "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
        }
    return MergeOperator(config)


# ---------------------------------------------------------------------------
# 1. Constructor and initialization
# ---------------------------------------------------------------------------


def test_operator_init_with_row_merge():
    """Operator initializes successfully with row merge config."""
    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)
    assert operator is not None
    assert operator.merge_type == "rows"


def test_operator_init_with_column_merge():
    """Operator initializes successfully with column merge config."""
    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)
    assert operator is not None
    assert operator.merge_type == "columns"
    assert operator.column_option == "inner_join"


def test_operator_init_sets_common_log_arguments():
    """Operator initializes common_log_arguments dict."""
    operator = make_operator()
    assert hasattr(operator, "common_log_arguments")
    assert isinstance(operator.common_log_arguments, dict)


def test_operator_init_with_input_links():
    """Operator stores input_links configuration."""
    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "a"}, {"link_name": "b"}],
    }
    operator = MergeOperator(config)
    assert len(operator.input_links) == 2


# ---------------------------------------------------------------------------
# 2. Row merge (concatenation) functionality
# ---------------------------------------------------------------------------


def test_row_merge_concatenates_tables():
    """Row merge concatenates two tables vertically."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert result.num_rows == 4  # 2 + 2
    assert result.num_columns == table1.num_columns


def test_row_merge_preserves_all_rows():
    """Row merge includes all rows from both tables."""
    table1 = make_table(num_rows=3, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert result.num_rows == 5  # 3 + 2


def test_row_merge_detects_duplicate_ids():
    """Row merge raises error when duplicate IDs detected."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="a")  # Same IDs

    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    with pytest.raises(DocpipeException):
        operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})


def test_row_merge_with_three_tables():
    """Row merge works with more than two tables."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")
    table3 = make_table(num_rows=2, id_prefix="c")

    config = {
        "merge_type": "rows",
        "input_links": [
            {"link_name": "branch1"},
            {"link_name": "branch2"},
            {"link_name": "branch3"},
        ],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(
        table=pa.table({}), tables={"branch1": table1, "branch2": table2, "branch3": table3}
    )
    result = result_tables[0]

    assert result.num_rows == 6  # 2 + 2 + 2


# ---------------------------------------------------------------------------
# 3. Column merge (join) functionality
# ---------------------------------------------------------------------------


def test_column_merge_inner_join():
    """Column merge with inner_join combines tables horizontally."""
    table1 = make_table(num_rows=3, id_prefix="")
    table2 = make_table(num_rows=3, id_prefix="")

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    # Should have original columns + suffixed columns from second table
    assert result.num_rows == 3
    assert "name_branch2" in result.column_names
    assert "size_branch2" in result.column_names


def test_column_merge_full_outer_join():
    """Column merge with full_outer join includes all rows."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    config = {
        "merge_type": "columns",
        "column_option": "full_outer",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    # Should have all rows from both tables
    assert result.num_rows == 4  # 2 + 2 (no overlap)


def test_column_merge_preserves_id_column():
    """Column merge preserves the ID column without suffix."""
    table1 = make_table(num_rows=3, id_prefix="")
    table2 = make_table(num_rows=3, id_prefix="")

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert "id" in result.column_names
    assert "id_branch2" not in result.column_names  # ID should not be suffixed


def test_column_merge_adds_suffix_to_other_columns():
    """Column merge adds _branch2 suffix to non-ID columns from second table."""
    table1 = make_table(num_rows=3, id_prefix="")
    table2 = make_table(num_rows=3, id_prefix="")

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    # Original columns from table1
    assert "name" in result.column_names
    assert "size" in result.column_names

    # Suffixed columns from table2
    assert "name_branch2" in result.column_names
    assert "size_branch2" in result.column_names


# ---------------------------------------------------------------------------
# 4. Validation tests
# ---------------------------------------------------------------------------


def test_validation_requires_merge_type():
    """Validation fails when merge_type is missing."""
    config = {
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) > 0
    assert any("merge_type" in str(err).lower() for err in errors)


def test_validation_requires_column_option_for_column_merge():
    """Validation fails when column_option missing for column merge."""
    config = {
        "merge_type": "columns",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) > 0
    assert any("column_option" in str(err).lower() for err in errors)


def test_validation_requires_minimum_two_input_links():
    """Validation fails when fewer than 2 input links provided."""
    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) > 0


def test_validation_rejects_invalid_merge_type():
    """Validation fails for invalid merge_type value."""
    config = {
        "merge_type": "invalid",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) > 0


def test_validation_rejects_invalid_column_option():
    """Validation fails for invalid column_option value."""
    config = {
        "merge_type": "columns",
        "column_option": "invalid",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) > 0


def test_validation_passes_with_valid_row_config():
    """Validation passes with valid row merge configuration."""
    config = {
        "merge_type": "rows",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) == 0


def test_validation_passes_with_valid_column_config():
    """Validation passes with valid column merge configuration."""
    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    errors: list[str] = []
    warnings: list[str] = []
    available_features: list[str] = []
    operator.validate(errors=errors, warnings=warnings, available_features=available_features)
    assert len(errors) == 0


# ---------------------------------------------------------------------------
# 5. Metadata generation
# ---------------------------------------------------------------------------


def test_transform_returns_metadata():
    """transform() returns metadata dictionary when merging tables."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    operator = make_operator()
    _, metadata = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})

    assert isinstance(metadata, dict)


def test_metadata_contains_total_docs():
    """Metadata contains documents_in_scope."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    operator = make_operator()
    _, metadata = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})

    assert Metrics.External.TOTAL_DOCS in metadata
    assert metadata[Metrics.External.TOTAL_DOCS] == 4


def test_metadata_contains_processed_docs():
    """Metadata contains processed_docs count."""
    table1 = make_table(num_rows=2, id_prefix="a")
    table2 = make_table(num_rows=2, id_prefix="b")

    operator = make_operator()
    _, metadata = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})

    assert Metrics.External.PROCESSED_DOCS in metadata
    assert metadata[Metrics.External.PROCESSED_DOCS] == 4


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------


def test_empty_table_handling():
    """Operator handles empty tables gracefully."""
    table1 = pa.table({"id": [], "name": [], "size": []})
    table2 = make_table(num_rows=2, id_prefix="b")

    operator = make_operator()
    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert result.num_rows == 2


def test_single_row_tables():
    """Operator works with single-row tables."""
    table1 = make_table(num_rows=1, id_prefix="a")
    table2 = make_table(num_rows=1, id_prefix="b")

    operator = make_operator()
    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert result.num_rows == 2


def test_tables_with_different_column_counts():
    """Column merge handles tables with different numbers of columns."""
    table1 = make_table(num_rows=2, id_prefix="", extra_columns={"extra1": [1, 2]})
    table2 = make_table(num_rows=2, id_prefix="")

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    assert "extra1" in result.column_names


# ---------------------------------------------------------------------------
# 7. Operator properties
# ---------------------------------------------------------------------------


def test_short_name_matches_constant():
    """short_name matches OperatorConstants.Operators.MERGE."""
    assert MergeOperator.short_name == OperatorConstants.Operators.MERGE


def test_short_name_value():
    """short_name is 'merge'."""
    assert MergeOperator.short_name == "merge"


def test_category_is_functional():
    """Operator category is Functional."""
    from docpipe.core.operators.abstract_operator import OperatorCategory

    assert MergeOperator.category == OperatorCategory.Functional


def test_get_metadata_returns_dict():
    """get_metadata() returns a dictionary."""
    meta = MergeOperator.get_metadata()
    assert isinstance(meta, dict)


def test_get_metadata_contains_required_keys():
    """get_metadata() contains required operator metadata keys."""
    meta = MergeOperator.get_metadata()

    assert OperatorConstants.Misc.IS_OPERATOR_AVAILABLE in meta
    assert OperatorConstants.Misc.LABEL in meta
    assert OperatorConstants.Config.ATTRIBUTES in meta


def test_get_metadata_input_links_attribute():
    """input_links is present, required, and exposes an items schema with link_name property."""
    meta = MergeOperator.get_metadata()
    assert OperatorConstants.Merge.INPUT_LINKS in meta[OperatorConstants.Config.ATTRIBUTES]
    attr = meta[OperatorConstants.Config.ATTRIBUTES][OperatorConstants.Merge.INPUT_LINKS]
    assert attr[OperatorConstants.Config.REQUIRED] is True
    assert OperatorConstants.Config.ITEMS in attr
    properties = attr[OperatorConstants.Config.ITEMS][OperatorConstants.Config.PROPERTIES]
    assert OperatorConstants.Misc.LINK_NAME in properties


def test_get_metadata_column_option_valid_values():
    """column_option exposes inner_join and full_outer as valid_values."""
    meta = MergeOperator.get_metadata()
    attr = meta[OperatorConstants.Config.ATTRIBUTES][OperatorConstants.Merge.COLUMN_OPTION]
    assert OperatorConstants.Config.VALID_VALUES in attr
    assert set(attr[OperatorConstants.Config.VALID_VALUES]) == {
        OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
        OperatorConstants.Merge.FULL_OUTER_JOIN,
    }


# ---------------------------------------------------------------------------
# 8. Complex type handling
# ---------------------------------------------------------------------------


def test_column_merge_with_list_columns():
    """Column merge handles list columns correctly by remapping without suffix."""
    table1 = pa.table(
        {
            "id": ["1", "2"],
            "tags": [[1, 2], [3, 4]],
        }
    )
    table2 = pa.table(
        {
            "id": ["1", "2"],
            "categories": [["a", "b"], ["c", "d"]],
        }
    )

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    # Complex types (lists, structs) are remapped without suffix
    assert "tags" in result.column_names
    assert "categories" in result.column_names
    assert result.num_rows == 2


def test_column_merge_with_struct_columns():
    """Column merge handles struct columns correctly by remapping without suffix."""
    table1 = pa.table(
        {
            "id": ["1", "2"],
            "metadata": [{"key": "value1"}, {"key": "value2"}],
        }
    )
    table2 = pa.table(
        {
            "id": ["1", "2"],
            "info": [{"data": "info1"}, {"data": "info2"}],
        }
    )

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "branch1"}, {"link_name": "branch2"}],
    }
    operator = MergeOperator(config)

    result_tables, _ = operator.transform(table=pa.table({}), tables={"branch1": table1, "branch2": table2})
    result = result_tables[0]

    # Complex types (lists, structs) are remapped without suffix
    assert "metadata" in result.column_names
    assert "info" in result.column_names
    assert result.num_rows == 2


# ---------------------------------------------------------------------------
# 9. Remap correctness — values, not just column presence
# ---------------------------------------------------------------------------


def test_column_merge_unsupported_remap_values_are_correct():
    """pc.take remap produces correct cell values matched to the right row."""
    table1 = pa.table({"id": ["a", "b", "c"], "name": ["doc_a", "doc_b", "doc_c"]})
    table2 = pa.table(
        {
            "id": ["c", "a", "b"],  # deliberately shuffled
            "embeddings": [[3.0, 3.1], [1.0, 1.1], [2.0, 2.1]],
        }
    )

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "t1"}, {"link_name": "t2"}],
    }
    result = MergeOperator(config).transform(table=pa.table({}), tables={"t1": table1, "t2": table2})[0][0]

    # Row order is driven by table1 (left side of join): a, b, c
    assert result.column("id").to_pylist() == ["a", "b", "c"]
    # Embeddings must be matched to correct IDs — not left in source order
    assert result.column("embeddings").to_pylist() == [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]]


def test_column_merge_multiple_unsupported_cols_same_table():
    """Multiple unsupported columns from the same table are all remapped correctly (hoisted ID array path)."""
    table1 = pa.table({"id": ["x", "y", "z"], "score": [10, 20, 30]})
    table2 = pa.table(
        {
            "id": ["z", "x", "y"],  # shuffled
            "embeddings": [[0.3], [0.1], [0.2]],
            "chunks": [["z1", "z2"], ["x1"], ["y1", "y2"]],
        }
    )

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "t1"}, {"link_name": "t2"}],
    }
    result = MergeOperator(config).transform(table=pa.table({}), tables={"t1": table1, "t2": table2})[0][0]

    # Row order: x, y, z (driven by table1)
    assert result.column("id").to_pylist() == ["x", "y", "z"]
    assert result.column("embeddings").to_pylist() == [[0.1], [0.2], [0.3]]
    assert result.column("chunks").to_pylist() == [["x1"], ["y1", "y2"], ["z1", "z2"]]


def test_column_merge_id_column_not_duplicated():
    """The id column appears exactly once in the output and holds correct values."""
    table1 = pa.table({"id": ["1", "2"], "name": ["a", "b"]})
    table2 = pa.table({"id": ["1", "2"], "embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "t1"}, {"link_name": "t2"}],
    }
    result = MergeOperator(config).transform(table=pa.table({}), tables={"t1": table1, "t2": table2})[0][0]

    assert result.column_names.count("id") == 1
    assert result.column("id").to_pylist() == ["1", "2"]


def test_column_merge_full_outer_unsupported_col_fills_none_for_missing_ids():
    """Full-outer join: rows with no match in the unsupported-column source get None."""
    # table1 has id "3" which table2 does not — full outer keeps it with None embedding
    table1 = pa.table({"id": ["1", "2", "3"], "name": ["a", "b", "c"]})
    table2 = pa.table({"id": ["1", "2"], "embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    config = {
        "merge_type": "columns",
        "column_option": "full_outer",
        "input_links": [{"link_name": "t1"}, {"link_name": "t2"}],
    }
    result = MergeOperator(config).transform(table=pa.table({}), tables={"t1": table1, "t2": table2})[0][0]

    emb = result.column("embeddings").to_pylist()
    # id "3" has no match in table2 — its embedding slot must be None
    idx_3 = result.column("id").to_pylist().index("3")
    assert emb[idx_3] is None
    # ids "1" and "2" have correct values
    idx_1 = result.column("id").to_pylist().index("1")
    idx_2 = result.column("id").to_pylist().index("2")
    assert emb[idx_1] == [0.1, 0.2]
    assert emb[idx_2] == [0.3, 0.4]


def test_column_merge_high_dimensional_embeddings_remap_correctly():
    """High-dimensional embedding arrays (1536-d) are remapped to the correct ID without Python materialisation regression."""
    dim = 1536
    n = 50
    ids = [str(i) for i in range(n)]
    # Source table has IDs in reverse order to maximally exercise the remap path.
    # Embedding value at source position p is float(p), paired with id str(n-1-p).
    # So the expected embedding for id k is [float(n-1-k)] * dim.
    source_ids = list(reversed(ids))
    source_embeddings = [[float(p)] * dim for p in range(n)]

    # Build ground truth: id → expected embedding value
    id_to_expected = {source_ids[p]: float(p) for p in range(n)}

    table1 = pa.table({"id": ids, "name": [f"doc_{i}" for i in ids]})
    table2 = pa.table(
        {
            "id": source_ids,
            "embeddings": pa.array(source_embeddings, type=pa.list_(pa.float32())),
        }
    )

    config = {
        "merge_type": "columns",
        "column_option": "inner_join",
        "input_links": [{"link_name": "t1"}, {"link_name": "t2"}],
    }
    result = MergeOperator(config).transform(table=pa.table({}), tables={"t1": table1, "t2": table2})[0][0]

    assert result.num_rows == n
    result_ids = result.column("id").to_pylist()
    result_embeddings = result.column("embeddings").to_pylist()

    for doc_id, embedding in zip(result_ids, result_embeddings, strict=False):
        expected_val = id_to_expected[doc_id]
        assert all(v == pytest.approx(expected_val) for v in embedding), (
            f"Embedding for id={doc_id} was not remapped correctly: expected {expected_val}, got {embedding[0]}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# Flow validation, pass-through and unsupported configurations
# ---------------------------------------------------------------------------

_TWO_LINKS = [{"link_name": "a"}, {"link_name": "b"}]


def test_validate_is_skipped_while_validating_the_flow():
    """During flow validation the link and merge-type checks are deferred to execution."""
    operator = MergeOperator({"validating_flow": True, "input_links": [], "merge_type": None})
    errors: list = []

    operator.validate(errors=errors, warnings=[], available_features=[])

    assert errors == []


def test_transform_requires_two_input_links():
    operator = MergeOperator({"merge_type": "rows", "input_links": [{"link_name": "a"}]})

    with pytest.raises(FlowExecutionFailedException, match="At least two input links are required") as exc:
        operator.transform(make_table())

    assert exc.value.status_code == 400


def test_transform_without_tables_passes_the_input_through():
    table = make_table(num_rows=4)

    tables, metadata = make_operator().transform(table)

    assert tables == [table]
    assert metadata[Metrics.External.PROCESSED_DOCS] == 4


def test_transform_with_only_empty_tables_returns_an_empty_table():
    empty = make_table(num_rows=0)

    tables, metadata = make_operator().transform(empty, tables={"a": empty, "b": empty})

    assert [t.num_rows for t in tables] == [0]
    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_WARNINGS.value
    assert metadata[Metrics.External.PROCESSED_DOCS] == 0


@pytest.mark.parametrize(
    ("merge_type", "column_option"),
    [("zip", None), ("columns", "left_join")],
    ids=["unknown-merge-type", "unknown-column-option"],
)
def test_transform_rejects_unsupported_configuration(merge_type, column_option):
    operator = MergeOperator({"merge_type": merge_type, "column_option": column_option, "input_links": _TWO_LINKS})
    tables = {"a": make_table(id_prefix="a"), "b": make_table(id_prefix="b")}

    with pytest.raises(DocpipeException, match=f"Unsupported merge configuration: {merge_type}, {column_option}"):
        operator.transform(tables["a"], tables=tables)


# ---------------------------------------------------------------------------
# Column merge with columns that cannot be joined (list types)
# ---------------------------------------------------------------------------


def _column_merge() -> MergeOperator:
    return MergeOperator({"merge_type": "columns", "column_option": "inner_join", "input_links": _TWO_LINKS})


def test_column_merge_suffixes_clashing_unsupported_columns():
    left = pa.table({"id": ["1", "2"], "tags": [["x"], ["y"]]})
    right = pa.table({"id": ["2", "1"], "tags": [["b2"], ["b1"]]})

    tables, _ = _column_merge().transform(left, tables={"a": left, "b": right})

    merged = tables[0].sort_by("id")
    assert merged.column("tags").to_pylist() == [["x"], ["y"]]
    assert merged.column("tags_b").to_pylist() == [["b1"], ["b2"]]


def test_column_merge_rejects_duplicate_name_after_suffixing():
    left = pa.table({"id": ["1"], "tags": [["x"]], "tags_b": [["y"]]})
    right = pa.table({"id": ["1"], "tags": [["z"]]})

    with pytest.raises(DocpipeException, match="Duplicate unsupported column after suffixing: tags_b"):
        _column_merge().transform(left, tables={"a": left, "b": right})
