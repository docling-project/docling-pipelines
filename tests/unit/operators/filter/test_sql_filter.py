#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for SQLFilterOperator.
Tests filtering rows from a PyArrow table using SQL WHERE clause criteria.
"""

from unittest.mock import MagicMock, patch

import duckdb
import pyarrow as pa
import pytest

from docpipe.core.constants.constants import (
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import (
    OperatorConstants,
)
from docpipe.core.operators.quality.sql_filter import (
    FILTER_LOGICAL_OPERATOR_AND,
    FILTER_LOGICAL_OPERATOR_OR,
    SQLFilterOperator,
    convert_operator,
    format_value,
    json_to_sql_where,
    process_condition,
)
from docpipe.exceptions.docpipe_exceptions import (
    DocpipeException,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_table(num_rows: int = 5) -> pa.Table:
    """
    Create a standard test PyArrow table.
    Includes 'name' column required by OperatorUtils.find_skipped_docs.
    """
    return pa.table(
        {
            "id": [str(i) for i in range(1, num_rows + 1)],
            "name": [f"doc_{i}.txt" for i in range(1, num_rows + 1)],
            "content": [f"Document content {i}" for i in range(1, num_rows + 1)],
            "score": [float(i * 2) for i in range(1, num_rows + 1)],
            "language": ["en", "fr", "en", "de", "en"][:num_rows],
            "word_count": [100, 200, 50, 300, 150][:num_rows],
        }
    )


def make_operator(config: dict) -> SQLFilterOperator:
    return SQLFilterOperator(config)


# ---------------------------------------------------------------------------
# 1. Basic filtering
# ---------------------------------------------------------------------------


def test_basic_filter_greater_than():
    """Filter rows where score > 5 keeps only rows with score 6, 8, 10."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 3, f"Expected 3 rows, got {result.num_rows}"
    scores = result["score"].to_pylist()
    assert all(s > 5 for s in scores), f"All scores should be > 5, got {scores}"


def test_basic_filter_equals():
    """Filter rows where language = 'en'."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["language = 'en'"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 3
    languages = result["language"].to_pylist()
    assert all(lang == "en" for lang in languages)


def test_basic_filter_less_than_or_equal():
    """Filter rows where word_count <= 150."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["word_count <= 150"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    word_counts = result["word_count"].to_pylist()
    assert all(wc <= 150 for wc in word_counts)


# ---------------------------------------------------------------------------
# 2. AND logical operator
# ---------------------------------------------------------------------------


def test_and_logical_operator():
    """Multiple criteria with AND: score > 2 AND language = 'en'."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [
                "score > 2",
                "language = 'en'",
            ],
            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: FILTER_LOGICAL_OPERATOR_AND,
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    for row_idx in range(result.num_rows):
        score = result["score"][row_idx].as_py()
        lang = result["language"][row_idx].as_py()
        assert score > 2, f"score should be > 2, got {score}"
        assert lang == "en", f"language should be 'en', got {lang}"


def test_and_logical_operator_no_match():
    """AND criteria that cannot both be satisfied returns empty table."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [
                "score > 8",
                "score < 2",
            ],
            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: FILTER_LOGICAL_OPERATOR_AND,
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 0


# ---------------------------------------------------------------------------
# 3. OR logical operator
# ---------------------------------------------------------------------------


def test_or_logical_operator():
    """Multiple criteria with OR: language = 'fr' OR language = 'de'."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [
                "language = 'fr'",
                "language = 'de'",
            ],
            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: FILTER_LOGICAL_OPERATOR_OR,
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 2
    languages = result["language"].to_pylist()
    assert set(languages) == {"fr", "de"}


def test_or_logical_operator_broader_match():
    """OR criteria: score < 3 OR score > 8 — picks rows at both ends."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [
                "score < 3",
                "score > 8",
            ],
            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: FILTER_LOGICAL_OPERATOR_OR,
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    scores = result["score"].to_pylist()
    assert all(s < 3 or s > 8 for s in scores)


# ---------------------------------------------------------------------------
# 4. JSON criteria
# ---------------------------------------------------------------------------


def test_filter_criteria_json_simple():
    """Filter using filter_criteria_json dict with a single condition."""
    table = make_table()
    criteria_json = {
        "variable": "score",
        "operator": ">",
        "value": 5,
    }
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_JSON: criteria_json})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    scores = result["score"].to_pylist()
    assert all(s > 5 for s in scores)


def test_filter_criteria_json_nested_and():
    """Filter using filter_criteria_json with nested AND conditions."""
    table = make_table()
    criteria_json = {
        "logical_operator": "AND",
        "criteria_list": [
            {"variable": "score", "operator": ">", "value": 2},
            {"variable": "language", "operator": "=", "value": "en"},
        ],
    }
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_JSON: criteria_json})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    for row_idx in range(result.num_rows):
        score = result["score"][row_idx].as_py()
        lang = result["language"][row_idx].as_py()
        assert score > 2
        assert lang == "en"


def test_filter_criteria_json_nested_or():
    """Filter using filter_criteria_json with nested OR conditions."""
    table = make_table()
    criteria_json = {
        "logical_operator": "OR",
        "criteria_list": [
            {"variable": "language", "operator": "=", "value": "fr"},
            {"variable": "language", "operator": "=", "value": "de"},
        ],
    }
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_JSON: criteria_json})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 2
    languages = result["language"].to_pylist()
    assert set(languages) == {"fr", "de"}


# ---------------------------------------------------------------------------
# 5. Features to drop
# ---------------------------------------------------------------------------


def test_features_to_drop_removes_column():
    """features_to_drop removes specified columns from output."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"],
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["language"],
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert "language" not in result.column_names
    assert "score" in result.column_names
    assert "content" in result.column_names


def test_features_to_drop_multiple_columns():
    """features_to_drop removes multiple columns."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"],
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [
                "language",
                "word_count",
            ],
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert "language" not in result.column_names
    assert "word_count" not in result.column_names
    assert "score" in result.column_names


def test_features_to_drop_without_filter():
    """features_to_drop works even without filter criteria (no WHERE clause)."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["language"],
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert "language" not in result.column_names
    assert result.num_rows == table.num_rows


# ---------------------------------------------------------------------------
# 6. Empty result
# ---------------------------------------------------------------------------


def test_filter_returns_empty_table():
    """Filter that matches no rows returns an empty table."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 9999"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 0
    # Schema should still be intact
    assert set(result.column_names) == set(table.column_names)


# ---------------------------------------------------------------------------
# 7. All rows pass
# ---------------------------------------------------------------------------


def test_filter_all_rows_pass():
    """Filter that matches all rows returns the full table."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == table.num_rows


def test_no_filter_criteria_returns_full_table():
    """No filter criteria at all returns the full table unchanged."""
    table = make_table()
    operator = make_operator({})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == table.num_rows


# ---------------------------------------------------------------------------
# 8. Validation errors — protected columns
# ---------------------------------------------------------------------------


def test_validate_rejects_drop_of_id_column():
    """Dropping the protected 'id' column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.Columns.ID],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count"]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for dropping 'id'"


def test_validate_rejects_drop_of_content_column():
    """Dropping the protected 'content' column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.Columns.DOC_COLUMN_DEFAULT],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count"]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for dropping 'content'"


def test_validate_rejects_drop_of_pages_processed_column():
    """Dropping the protected 'pages_processed' column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.Columns.PAGES_PROCESSED_COLUMN],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = [
        "id",
        "name",
        "content",
        "score",
        "language",
        "word_count",
        "pages_processed",
    ]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for dropping 'pages_processed'"


def test_validate_rejects_drop_of_allowed_users_column():
    """Dropping the protected 'allowed_users' column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.ACL.ALLOWED_USERS_COLUMN],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count", "allowed_users"]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for dropping 'allowed_users'"


def test_validate_rejects_drop_of_chunked_content_column():
    """Dropping the protected 'chunked_content' column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.Columns.CHUNKED_CONTENT],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count", "chunked_content"]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for dropping 'chunked_content'"


def test_transform_raises_on_drop_of_allowed_users_column():
    """Attempting to drop the protected 'allowed_users' column at runtime raises DocpipeException."""
    table = pa.table(
        {
            "id": ["1", "2"],
            "name": ["doc_1.txt", "doc_2.txt"],
            "content": ["Document content 1", "Document content 2"],
            "score": [2.0, 4.0],
            "allowed_users": [["user_a"], ["user_b"]],
        }
    )
    operator = make_operator(
        {OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.ACL.ALLOWED_USERS_COLUMN]}
    )
    with pytest.raises(DocpipeException):
        operator._dpk_transform(table=table, metadata={})


def test_transform_raises_on_drop_of_chunked_content_column():
    """Attempting to drop the protected 'chunked_content' column at runtime raises DocpipeException."""
    table = pa.table(
        {
            "id": ["1", "2"],
            "name": ["doc_1.txt", "doc_2.txt"],
            "content": ["Document content 1", "Document content 2"],
            "score": [2.0, 4.0],
            "chunked_content": [None, None],
        }
    )
    operator = make_operator(
        {OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: [OperatorConstants.Columns.CHUNKED_CONTENT]}
    )
    with pytest.raises(DocpipeException):
        operator._dpk_transform(table=table, metadata={})


# ---------------------------------------------------------------------------
# 9. Column not found
# ---------------------------------------------------------------------------


def test_validate_rejects_filter_on_nonexistent_column():
    """Filtering on a non-existent column should add a validation error."""
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["nonexistent_col > 5"],
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count"]
    operator.validate(errors, warnings, available_features)

    assert len(errors) > 0, "Expected a validation error for non-existent column"
    # The error message should mention the invalid feature
    error_messages = [str(e) for e in errors]
    assert any("nonexistent_col" in msg for msg in error_messages)


def test_validate_warns_when_no_criteria_provided():
    """No filter criteria at all should produce a warning."""
    operator = make_operator({})
    errors: list[str] = []
    warnings: list[str] = []
    available_features = ["id", "name", "content", "score", "language", "word_count"]
    operator.validate(errors, warnings, available_features)

    assert len(warnings) > 0, "Expected a warning when no filter criteria is provided"


def test_invalid_column_in_transform_returns_original_table():
    """
    When filter criteria references a column not in the table,
    has_invalid_columns returns True and the original table is returned.
    """
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["nonexistent_col > 5"],
        }
    )
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    # Original table is returned unchanged
    assert result.num_rows == table.num_rows


# ---------------------------------------------------------------------------
# 10. get_metadata()
# ---------------------------------------------------------------------------


def test_get_metadata_is_operator_available():
    """get_metadata() returns IS_OPERATOR_AVAILABLE: True."""
    operator = make_operator({})
    meta = operator.get_metadata()

    assert meta[OperatorConstants.Misc.IS_OPERATOR_AVAILABLE] is True


def test_get_metadata_structure():
    """get_metadata() returns expected keys."""
    operator = make_operator({})
    meta = operator.get_metadata()

    assert OperatorConstants.Misc.CATEGORY in meta
    assert OperatorConstants.Misc.LABEL in meta
    assert OperatorConstants.Config.ATTRIBUTES in meta
    assert meta[OperatorConstants.Misc.LABEL] == "Annotation Filter"


def test_get_metadata_attributes_keys():
    """get_metadata() attributes contain all expected operator parameters."""
    operator = make_operator({})
    meta = operator.get_metadata()
    attrs = meta[OperatorConstants.Config.ATTRIBUTES]

    assert OperatorConstants.Filtering.FILTER_CRITERIA_LIST in attrs
    assert OperatorConstants.Filtering.FILTER_CRITERIA_JSON in attrs
    assert OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY in attrs
    assert OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY in attrs


# ---------------------------------------------------------------------------
# 11. Helper functions
# ---------------------------------------------------------------------------


class TestConvertOperator:
    def test_equals(self):
        assert convert_operator("=") == "="

    def test_double_equals(self):
        assert convert_operator("==") == "="

    def test_not_equals(self):
        assert convert_operator("!=") == "!="

    def test_greater_than(self):
        assert convert_operator(">") == ">"

    def test_less_than(self):
        assert convert_operator("<") == "<"

    def test_greater_than_or_equal(self):
        assert convert_operator(">=") == ">="

    def test_less_than_or_equal(self):
        assert convert_operator("<=") == "<="

    def test_in_operator(self):
        assert convert_operator("in") == "IN"

    def test_not_in_operator(self):
        assert convert_operator("not in") == "NOT IN"

    def test_like_operator(self):
        assert convert_operator("like") == "LIKE"

    def test_is_null(self):
        assert convert_operator("is null") == "IS NULL"

    def test_is_not_null(self):
        assert convert_operator("is not null") == "IS NOT NULL"

    def test_between(self):
        assert convert_operator("between") == "BETWEEN"

    def test_case_insensitive(self):
        assert convert_operator("IN") == "IN"
        assert convert_operator("Like") == "LIKE"

    def test_unknown_operator_raises(self):
        with pytest.raises(DocpipeException):
            convert_operator("UNKNOWN_OP")

    def test_non_string_raises(self):
        with pytest.raises(DocpipeException):
            convert_operator(123)


class TestFormatValue:
    def test_none_returns_null(self):
        assert format_value(None) == "NULL"

    def test_integer(self):
        assert format_value(42) == "42"

    def test_float(self):
        assert format_value(3.14) == "3.14"

    def test_string_number_int(self):
        assert format_value("10") == "10"

    def test_string_number_float(self):
        assert format_value("3.14") == "3.14"

    def test_string_text(self):
        assert format_value("hello") == "'hello'"

    def test_string_with_single_quote(self):
        # Single quotes in strings should be escaped
        result = format_value("it's")
        assert "it''s" in result

    def test_list_of_ints(self):
        result = format_value([1, 2, 3])
        assert result == "(1, 2, 3)"

    def test_list_of_strings(self):
        result = format_value(["a", "b"])
        assert result == "('a', 'b')"

    def test_zero(self):
        assert format_value(0) == "0"

    def test_negative_number(self):
        assert format_value(-5) == "-5"


class TestProcessCondition:
    def test_simple_equals(self):
        condition = {"variable": "score", "operator": "=", "value": 5}
        result = process_condition(condition)
        assert result == "score = 5"

    def test_greater_than(self):
        condition = {"variable": "score", "operator": ">", "value": 3}
        result = process_condition(condition)
        assert result == "score > 3"

    def test_string_value(self):
        condition = {"variable": "language", "operator": "=", "value": "en"}
        result = process_condition(condition)
        assert result == "language = 'en'"

    def test_is_null(self):
        condition = {"variable": "score", "operator": "is null"}
        result = process_condition(condition)
        assert result == "score IS NULL"

    def test_is_not_null(self):
        condition = {"variable": "score", "operator": "is not null"}
        result = process_condition(condition)
        assert result == "score IS NOT NULL"

    def test_between_list(self):
        condition = {"variable": "score", "operator": "between", "value": [1, 10]}
        result = process_condition(condition)
        assert result == "score BETWEEN 1 AND 10"

    def test_between_string(self):
        condition = {"variable": "score", "operator": "between", "value": "1, 10"}
        result = process_condition(condition)
        assert result == "score BETWEEN 1 AND 10"

    def test_in_list(self):
        condition = {"variable": "language", "operator": "in", "value": ["en", "fr"]}
        result = process_condition(condition)
        assert "language IN" in result
        assert "'en'" in result
        assert "'fr'" in result

    def test_in_string(self):
        condition = {"variable": "language", "operator": "in", "value": "en, fr"}
        result = process_condition(condition)
        assert "language IN" in result

    def test_missing_variable_raises(self):
        condition = {"operator": "=", "value": 5}
        with pytest.raises(DocpipeException):
            process_condition(condition)

    def test_missing_operator_raises(self):
        condition = {"variable": "score", "value": 5}
        with pytest.raises(DocpipeException):
            process_condition(condition)


class TestJsonToSqlWhere:
    def test_empty_dict_returns_empty(self):
        result = json_to_sql_where({})
        assert result == ""

    def test_none_returns_empty(self):
        result = json_to_sql_where(None)
        assert result == ""

    def test_simple_condition(self):
        condition = {"variable": "score", "operator": ">", "value": 5}
        result = json_to_sql_where(condition)
        assert result.startswith("WHERE")
        assert "score > 5" in result

    def test_nested_and_group(self):
        group = {
            "logical_operator": "AND",
            "criteria_list": [
                {"variable": "score", "operator": ">", "value": 2},
                {"variable": "language", "operator": "=", "value": "en"},
            ],
        }
        result = json_to_sql_where(group)
        assert result.startswith("WHERE")
        assert "AND" in result
        assert "score > 2" in result
        assert "language = 'en'" in result

    def test_nested_or_group(self):
        group = {
            "logical_operator": "OR",
            "criteria_list": [
                {"variable": "language", "operator": "=", "value": "fr"},
                {"variable": "language", "operator": "=", "value": "de"},
            ],
        }
        result = json_to_sql_where(group)
        assert result.startswith("WHERE")
        assert "OR" in result


# ---------------------------------------------------------------------------
# 12. Metadata structure from transform
# ---------------------------------------------------------------------------


def test_transform_metadata_contains_processed_docs():
    """transform() metadata contains processed_docs key."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"]})
    _, metadata = operator.transform(table)

    assert Metrics.External.PROCESSED_DOCS in metadata
    assert metadata[Metrics.External.PROCESSED_DOCS] == table.num_rows


def test_transform_metadata_contains_total_docs():
    """transform() metadata contains documents_in_scope key."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"]})
    _, metadata = operator.transform(table)

    assert Metrics.External.TOTAL_DOCS in metadata
    assert metadata[Metrics.External.TOTAL_DOCS] == table.num_rows


def test_transform_metadata_docs_after_filter():
    """transform() metadata contains docs_after_filter key."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})
    _, metadata = operator.transform(table)

    assert "docs_after_filter" in metadata
    assert metadata["docs_after_filter"] == 3


def test_transform_metadata_filter_stats_per_criterion():
    """transform() metadata contains per-criterion filter stats."""
    table = make_table()
    criterion = "score > 5"
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [criterion]})
    _, metadata = operator.transform(table)

    key = f"docs_filtered_out_by '{criterion}'"
    assert key in metadata
    assert metadata[key] == 2  # 5 rows total, 3 pass, 2 filtered


def test_metadata_after_values_not_greater_than_before():
    """Test that after-filter metrics are never greater than before-filter metrics."""
    table = make_table()

    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"],
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["language"],
        }
    )
    _, metadata = operator.transform(table)

    # Verify all before/after metrics exist
    assert Metrics.External.DOCS_BEFORE_FILTER in metadata
    assert Metrics.External.DOCS_AFTER_FILTER in metadata
    assert Metrics.External.BYTES_BEFORE_FILTER in metadata
    assert Metrics.External.BYTES_AFTER_FILTER in metadata
    assert Metrics.External.COLUMNS_BEFORE_FILTER in metadata
    assert Metrics.External.COLUMNS_AFTER_FILTER in metadata

    # Verify logical consistency: after <= before
    assert metadata[Metrics.External.DOCS_AFTER_FILTER] <= metadata[Metrics.External.DOCS_BEFORE_FILTER]
    assert metadata[Metrics.External.BYTES_AFTER_FILTER] <= metadata[Metrics.External.BYTES_BEFORE_FILTER]
    assert metadata[Metrics.External.COLUMNS_AFTER_FILTER] <= metadata[Metrics.External.COLUMNS_BEFORE_FILTER]


def test_metadata_no_filtering_before_equals_after():
    """Test that before/after metrics are equal when no rows are filtered."""
    table = make_table()

    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 0"]})
    _, metadata = operator.transform(table)

    assert metadata[Metrics.External.DOCS_BEFORE_FILTER] == metadata[Metrics.External.DOCS_AFTER_FILTER]
    assert metadata[Metrics.External.COLUMNS_BEFORE_FILTER] == metadata[Metrics.External.COLUMNS_AFTER_FILTER]


# ---------------------------------------------------------------------------
# 13. short_name
# ---------------------------------------------------------------------------


def test_short_name():
    """short_name matches OperatorConstants.Operators.SQL_FILTER."""
    assert SQLFilterOperator.short_name == OperatorConstants.Operators.SQL_FILTER


# ---------------------------------------------------------------------------
# 14. Edge cases
# ---------------------------------------------------------------------------


def test_filter_with_single_row_table():
    """Filter works correctly on a single-row table."""
    table = pa.table(
        {
            "id": ["1"],
            "name": ["doc_1.txt"],
            "content": ["hello"],
            "score": [5.0],
            "language": ["en"],
            "word_count": [10],
        }
    )
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 3"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 1


def test_filter_with_single_row_table_no_match():
    """Filter on single-row table that doesn't match returns empty table."""
    table = pa.table(
        {
            "id": ["1"],
            "name": ["doc_1.txt"],
            "content": ["hello"],
            "score": [1.0],
            "language": ["en"],
            "word_count": [10],
        }
    )

    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 3"]})
    result_tables, _metadata = operator.transform(table)
    result = result_tables[0]

    assert result.num_rows == 0


def test_filter_preserves_column_names():
    """Filtered table preserves all column names from input."""
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    assert set(result.column_names) == set(table.column_names)


def test_filter_and_drop_combined():
    """Filter criteria and features_to_drop can be combined."""
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"],
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["language"],
        }
    )
    result_tables, _ = operator.transform(table)
    result = result_tables[0]

    # Filtered rows
    assert result.num_rows == 3
    # Dropped column
    assert "language" not in result.column_names
    # Other columns still present
    assert "score" in result.column_names
    assert "content" in result.column_names


# ---------------------------------------------------------------------------
# 15. Error handling tests
# ---------------------------------------------------------------------------


def test_duckdb_execution_failure():
    """
    Test when DuckDB raises an exception during query execution.
    Verify that the operator catches the exception, metadata contains FAILED status,
    all documents are recorded as failed, and the original table is returned.
    """
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    # Mock duckdb.connect() to return a connection that raises an exception on execute
    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        mock_con.execute.side_effect = duckdb.BinderException("Mocked DuckDB error")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_con)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table should be returned unchanged
        assert result.num_rows == table.num_rows
        assert result.column_names == table.column_names

        # Metadata should contain FAILED status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # Error should be recorded in metadata
        assert OperatorConstants.Extraction.ERROR in metadata
        assert "Mocked DuckDB error" in metadata[OperatorConstants.Extraction.ERROR]

        # All documents should be recorded as failed
        assert Metrics.External.FAILED_DOCS in metadata
        assert len(metadata[Metrics.External.FAILED_DOCS]) == table.num_rows

        # Verify each document has proper error reason
        for doc_info in metadata[Metrics.External.FAILED_DOCS]:
            assert "reason" in doc_info
            assert "Mocked DuckDB error" in doc_info["reason"]


def test_duckdb_conversion_exception():
    """
    Test when DuckDB raises a ConversionException (type mismatch).
    """
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        mock_con.execute.side_effect = duckdb.ConversionException("Type conversion error")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_con)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table returned
        assert result.num_rows == table.num_rows

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # Error should be recorded
        assert OperatorConstants.Extraction.ERROR in metadata
        assert "Type conversion error" in metadata[OperatorConstants.Extraction.ERROR]


def test_duckdb_catalog_exception():
    """
    Test when DuckDB raises a CatalogException (e.g., table not found).
    """
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        mock_con.execute.side_effect = duckdb.CatalogException("Table not found")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_con)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table returned
        assert result.num_rows == table.num_rows

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # Error recorded
        assert OperatorConstants.Extraction.ERROR in metadata
        assert "Table not found" in metadata[OperatorConstants.Extraction.ERROR]


def test_transform_general_exception():
    """
    Test when transform() encounters an unexpected error.
    Verify proper error handling and metadata recording.
    """
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    # Mock duckdb.connect() to raise a general exception
    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_connect.side_effect = RuntimeError("Unexpected runtime error")

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table should be returned
        assert result.num_rows == table.num_rows

        # Metadata should contain FAILED status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # Error should be recorded
        assert OperatorConstants.Extraction.ERROR in metadata
        assert "Unexpected runtime error" in metadata[OperatorConstants.Extraction.ERROR]

        # All documents should be marked as failed
        assert Metrics.External.FAILED_DOCS in metadata
        assert len(metadata[Metrics.External.FAILED_DOCS]) == table.num_rows


def test_docpipe_exception_in_json_to_sql_where():
    """
    Test when a DocpipeException is raised during JSON to SQL conversion.
    """
    table = make_table()
    # Invalid JSON criteria that will cause an error
    invalid_criteria_json = {
        "variable": "score",
        # Missing operator - should raise DocpipeException
        "value": 5,
    }
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_JSON: invalid_criteria_json})

    result_tables, metadata = operator.transform(table)
    result = result_tables[0]

    # Original table should be returned
    assert result.num_rows == table.num_rows

    # Metadata should contain FAILED status
    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

    # Error should be recorded
    assert OperatorConstants.Extraction.ERROR in metadata

    # All documents should be marked as failed
    assert Metrics.External.FAILED_DOCS in metadata
    assert len(metadata[Metrics.External.FAILED_DOCS]) == table.num_rows


def test_error_handling_with_filter_criteria_per_criterion():
    """
    Test error handling when processing individual filter criteria.
    """
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [
                "score > 5",
                "language = 'en'",
            ]
        }
    )

    # Mock to fail on the second criterion
    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        call_count = [0]

        def execute_side_effect(sql):
            call_count[0] += 1
            if call_count[0] == 2:  # Fail on second call
                raise duckdb.BinderException("Error on second criterion")
            # First call succeeds
            mock_result = MagicMock()
            mock_result.arrow.return_value = table
            return mock_result

        mock_con.execute.side_effect = execute_side_effect
        mock_connect.return_value = mock_con

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table returned
        assert result.num_rows == table.num_rows

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value


def test_error_with_features_to_drop():
    """
    Test error handling when both filtering and dropping features.
    """
    table = make_table()
    operator = make_operator(
        {
            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"],
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["language"],
        }
    )

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        mock_con.execute.side_effect = Exception("Unexpected error during filtering")
        mock_connect.return_value = mock_con

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table returned (with all columns intact)
        assert result.num_rows == table.num_rows
        assert "language" in result.column_names  # Column not dropped due to error

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value


def test_error_handling_preserves_table_structure():
    """
    Test that error handling preserves the original table structure completely.
    """
    table = make_table()
    original_schema = table.schema
    original_num_rows = table.num_rows

    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_connect.side_effect = Exception("Critical error")

        result_tables, _metadata = operator.transform(table)
        result = result_tables[0]

        # Verify table structure is completely preserved
        assert result.schema == original_schema
        assert result.num_rows == original_num_rows
        assert result.column_names == table.column_names

        # Verify all data is intact
        for col_name in table.column_names:
            assert result[col_name].to_pylist() == table[col_name].to_pylist()


def test_failed_docs_metadata_structure():
    """
    Test that failed_docs metadata has the correct structure.
    """
    table = make_table()
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_connect.side_effect = Exception("Test error")

        _result_tables, metadata = operator.transform(table)

        # Verify failed_docs structure
        assert Metrics.External.FAILED_DOCS in metadata
        failed_docs = metadata[Metrics.External.FAILED_DOCS]

        # Should have entries for all documents
        assert len(failed_docs) == table.num_rows

        # Each entry should have proper structure (it's a list of dicts)
        for doc_info in failed_docs:
            assert "name" in doc_info
            assert "reason" in doc_info
            assert doc_info["reason"] == "Test error"


def test_error_with_empty_table():
    """
    Test error handling with an empty input table.
    """
    empty_table = pa.table(
        {
            "id": [],
            "name": [],
            "content": [],
            "score": [],
            "language": [],
            "word_count": [],
        }
    )

    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_connect.side_effect = Exception("Error with empty table")

        result_tables, metadata = operator.transform(empty_table)
        result = result_tables[0]

        # Empty table returned
        assert result.num_rows == 0

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # No failed docs since table is empty
        assert Metrics.External.FAILED_DOCS in metadata
        assert len(metadata[Metrics.External.FAILED_DOCS]) == 0


def test_error_handling_with_json_criteria():
    """
    Test error handling when using JSON criteria format.
    """
    table = make_table()
    criteria_json = {
        "logical_operator": "AND",
        "criteria_list": [
            {"variable": "score", "operator": ">", "value": 2},
            {"variable": "language", "operator": "=", "value": "en"},
        ],
    }
    operator = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_JSON: criteria_json})

    with patch("docpipe.core.operators.quality.sql_filter.duckdb.connect") as mock_connect:
        mock_con = MagicMock()
        mock_con.execute.side_effect = duckdb.BinderException("JSON criteria error")
        mock_connect.return_value = mock_con

        result_tables, metadata = operator.transform(table)
        result = result_tables[0]

        # Original table returned
        assert result.num_rows == table.num_rows

        # Failed status
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

        # Error recorded
        assert OperatorConstants.Extraction.ERROR in metadata


@pytest.mark.parametrize(
    "malicious_criterion",
    [
        "EXISTS (SELECT 1 FROM read_text('pyproject.toml'))",
        "EXISTS (SELECT 1 FROM read_csv('pyproject.toml'))",
    ],
)
def test_external_access_disabled_when_auth_enabled(monkeypatch, malicious_criterion):
    """When DOCPIPE_AUTH_ENABLED=true, DuckDB blocks read_text/read_csv while allowing table queries."""
    monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
    table = make_table()

    # Normal query on input_table still works when auth is enabled
    safe_op = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 5"]})
    safe_tables, safe_meta = safe_op.transform(table)
    assert safe_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value
    assert safe_tables[0].num_rows == 3

    # External file access via read_text / read_csv is blocked
    blocked_op = make_operator({OperatorConstants.Filtering.FILTER_CRITERIA_LIST: [malicious_criterion]})
    _result_tables, blocked_meta = blocked_op.transform(table)
    assert blocked_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert "disabled by configuration" in blocked_meta.get(OperatorConstants.Extraction.ERROR, "").lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
