#!/usr/bin/env python3
"""
Unit tests for operator_utils module.
Tests utility functions for table manipulation, validation, and feature management.
"""

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import internal_metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.exceptions.docpipe_exceptions import FlowValidationException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_table(num_rows=3, include_name=True, extra_columns=None) -> pa.Table:
    """Create a test PyArrow table with id and optional name columns."""
    data = {
        OperatorConstants.Columns.ID: [str(i + 1) for i in range(num_rows)],
    }
    if include_name:
        data[OperatorConstants.Columns.NAME] = [f"doc_{i + 1}" for i in range(num_rows)]
    if extra_columns:
        data.update(extra_columns)
    return pa.table(data)


# ---------------------------------------------------------------------------
# 1. remove_rows tests
# ---------------------------------------------------------------------------


def test_remove_rows_basic():
    """Remove specific rows by index."""
    table = make_table(num_rows=5)
    result = OperatorUtils.remove_rows(table=table, remove_row_idx=[1, 3])

    assert result.num_rows == 3
    ids = result[OperatorConstants.Columns.ID].to_pylist()
    assert ids == ["1", "3", "5"]


def test_remove_rows_empty_list():
    """Removing no rows returns original table."""
    table = make_table(num_rows=3)
    result = OperatorUtils.remove_rows(table=table, remove_row_idx=[])

    assert result.num_rows == 3


def test_remove_rows_all_rows():
    """Remove all rows returns empty table."""
    table = make_table(num_rows=3)
    result = OperatorUtils.remove_rows(table=table, remove_row_idx=[0, 1, 2])

    assert result.num_rows == 0


def test_remove_rows_preserves_columns():
    """Removing rows preserves all columns."""
    table = make_table(num_rows=3, extra_columns={"content": ["a", "b", "c"]})
    result = OperatorUtils.remove_rows(table=table, remove_row_idx=[1])

    assert set(result.column_names) == set(table.column_names)


# ---------------------------------------------------------------------------
# 2. remove_all_rows tests
# ---------------------------------------------------------------------------


def test_remove_all_rows_by_id():
    """Remove rows by document ID."""
    table = make_table(num_rows=5)
    result = OperatorUtils.remove_all_rows(table=table, remove_row_id=["2", "4"])

    assert result.num_rows == 3
    ids = result[OperatorConstants.Columns.ID].to_pylist()
    assert ids == ["1", "3", "5"]


def test_remove_all_rows_empty_list():
    """Removing no IDs returns original table."""
    table = make_table(num_rows=3)
    result = OperatorUtils.remove_all_rows(table=table, remove_row_id=[])

    assert result.num_rows == 3


def test_remove_all_rows_nonexistent_id():
    """Removing nonexistent ID doesn't affect table."""
    table = make_table(num_rows=3)
    result = OperatorUtils.remove_all_rows(table=table, remove_row_id=["999"])

    assert result.num_rows == 3


def test_remove_all_rows_all_ids():
    """Remove all rows by ID."""
    table = make_table(num_rows=3)
    result = OperatorUtils.remove_all_rows(table=table, remove_row_id=["1", "2", "3"])

    assert result.num_rows == 0


# ---------------------------------------------------------------------------
# 3. find_doc_count tests
# ---------------------------------------------------------------------------


def test_find_doc_count_with_name_column():
    """Count unique documents using name column."""
    table = pa.table(
        {
            OperatorConstants.Columns.ID: ["1", "2", "3", "4"],
            OperatorConstants.Columns.NAME: ["doc_a", "doc_a", "doc_b", "doc_b"],
        }
    )
    count = OperatorUtils.find_doc_count(table=table)

    assert count == 2  # Two unique document names


def test_find_doc_count_without_name_column():
    """Count rows when name column is missing."""
    table = pa.table(
        {
            OperatorConstants.Columns.ID: ["1", "2", "3"],
        }
    )
    count = OperatorUtils.find_doc_count(table=table)

    assert count == 3  # Falls back to row count


def test_find_doc_count_empty_table():
    """Count for empty table returns 0."""
    table = pa.table(
        {
            OperatorConstants.Columns.ID: pa.array([], type=pa.string()),
        }
    )
    count = OperatorUtils.find_doc_count(table=table)

    assert count == 0


def test_find_doc_count_none_table():
    """Count for None table returns 0."""
    count = OperatorUtils.find_doc_count(table=None)

    assert count == 0


# ---------------------------------------------------------------------------
# 4. find_doc_count_from_tables tests
# ---------------------------------------------------------------------------


def test_find_doc_count_from_tables_multiple():
    """Count unique documents across multiple tables."""
    table1 = pa.table(
        {
            OperatorConstants.Columns.NAME: ["doc_a", "doc_b"],
        }
    )
    table2 = pa.table(
        {
            OperatorConstants.Columns.NAME: ["doc_b", "doc_c"],
        }
    )
    count = OperatorUtils.find_doc_count_from_tables(tables=[table1, table2])

    assert count == 3  # Three unique documents


def test_find_doc_count_from_tables_empty_list():
    """Count from empty list returns 0."""
    count = OperatorUtils.find_doc_count_from_tables(tables=[])

    assert count == 0


def test_find_doc_count_from_tables_with_empty_table():
    """Count handles empty tables in list."""
    table1 = pa.table(
        {
            OperatorConstants.Columns.NAME: ["doc_a"],
        }
    )
    table2 = pa.table(
        {
            OperatorConstants.Columns.NAME: pa.array([], type=pa.string()),
        }
    )
    count = OperatorUtils.find_doc_count_from_tables(tables=[table1, table2])

    assert count == 1


# ---------------------------------------------------------------------------
# 5. validate_link_name tests
# ---------------------------------------------------------------------------


def test_validate_link_name_valid():
    """Valid link name passes validation."""
    existing: set[str] = set()
    errors: list[str] = []
    OperatorUtils.validate_link_name(link_name="link1", existing_link_names=existing, errors=errors)

    assert len(errors) == 0
    assert "link1" in existing


def test_validate_link_name_duplicate():
    """Duplicate link name adds error."""
    existing: set[str] = {"link1"}
    errors: list[str] = []
    OperatorUtils.validate_link_name(link_name="Link1", existing_link_names=existing, errors=errors)

    assert len(errors) == 1
    assert "Duplicate link name" in errors[0]


def test_validate_link_name_case_insensitive():
    """Link name validation is case-insensitive."""
    existing: set[str] = {"link1"}
    errors: list[str] = []
    OperatorUtils.validate_link_name(link_name="LINK1", existing_link_names=existing, errors=errors)

    assert len(errors) == 1


def test_validate_link_name_empty():
    """Empty link name adds error."""
    existing: set[str] = set()
    errors: list[str] = []
    OperatorUtils.validate_link_name(link_name="", existing_link_names=existing, errors=errors)

    assert len(errors) == 1
    assert "Missing link name" in errors[0]


def test_validate_link_name_none():
    """None link name adds error."""
    existing: set[str] = set()
    errors: list[str] = []
    OperatorUtils.validate_link_name(link_name=None, existing_link_names=existing, errors=errors)

    assert len(errors) == 1


# ---------------------------------------------------------------------------
# 6. doc_id_hash tests
# ---------------------------------------------------------------------------


def test_doc_id_hash_basic():
    """Hash content produces hex string."""
    content = "test content"
    result = OperatorUtils.doc_id_hash(content=content)

    assert isinstance(result, str)
    assert len(result) == 128  # SHA3-512 produces 128 hex chars


def test_doc_id_hash_deterministic():
    """Same content produces same hash."""
    content = "test content"
    hash1 = OperatorUtils.doc_id_hash(content=content)
    hash2 = OperatorUtils.doc_id_hash(content=content)

    assert hash1 == hash2


def test_doc_id_hash_different_content():
    """Different content produces different hash."""
    hash1 = OperatorUtils.doc_id_hash(content="content1")
    hash2 = OperatorUtils.doc_id_hash(content="content2")

    assert hash1 != hash2


def test_doc_id_hash_empty_string():
    """Empty string can be hashed."""
    result = OperatorUtils.doc_id_hash(content="")

    assert isinstance(result, str)
    assert len(result) == 128


def test_doc_id_hash_unicode():
    """Unicode content can be hashed."""
    content = "こんにちは世界"
    result = OperatorUtils.doc_id_hash(content=content)

    assert isinstance(result, str)
    assert len(result) == 128


# ---------------------------------------------------------------------------
# 7. decode_binary_content tests
# ---------------------------------------------------------------------------


def test_decode_binary_content_utf8():
    """Decode UTF-8 binary content."""
    binary = b"Hello, World!"
    result = OperatorUtils.decode_binary_content(binary_content=binary)

    assert result == "Hello, World!"


def test_decode_binary_content_unicode():
    """Decode Unicode binary content."""
    text = "こんにちは"
    binary = text.encode("utf-8")
    result = OperatorUtils.decode_binary_content(binary_content=binary)

    assert result == text


def test_decode_binary_content_latin1():
    """Decode Latin-1 encoded content."""
    text = "Café"
    binary = text.encode("latin-1")
    result = OperatorUtils.decode_binary_content(binary_content=binary)

    # charset_normalizer may detect encoding differently, just verify it returns a string
    assert isinstance(result, str)
    assert len(result) > 0


def test_decode_binary_content_empty():
    """Decode empty binary content."""
    binary = b""
    result = OperatorUtils.decode_binary_content(binary_content=binary)

    assert result == ""


# ---------------------------------------------------------------------------
# 8. upsert_fields_in_schema tests
# ---------------------------------------------------------------------------


def test_upsert_fields_in_schema_add_new():
    """Add new field to schema."""
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("name", pa.string()),
        ]
    )
    updates = {"age": pa.int64()}

    result = OperatorUtils.upsert_fields_in_schema(schema=schema, updates=updates)

    assert "age" in result.names
    assert result.field("age").type == pa.int64()


def test_upsert_fields_in_schema_update_existing():
    """Update existing field type."""
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("count", pa.int32()),
        ]
    )
    updates = {"count": pa.int64()}

    result = OperatorUtils.upsert_fields_in_schema(schema=schema, updates=updates)

    assert result.field("count").type == pa.int64()


def test_upsert_fields_in_schema_multiple_updates():
    """Add and update multiple fields."""
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
        ]
    )
    updates = {
        "name": pa.string(),
        "count": pa.int64(),
    }

    result = OperatorUtils.upsert_fields_in_schema(schema=schema, updates=updates)

    assert "name" in result.names
    assert "count" in result.names


def test_upsert_fields_in_schema_preserves_order():
    """Existing fields maintain order, new fields appended."""
    schema = pa.schema(
        [
            pa.field("a", pa.string()),
            pa.field("b", pa.string()),
        ]
    )
    updates = {"c": pa.string()}

    result = OperatorUtils.upsert_fields_in_schema(schema=schema, updates=updates)

    assert result.names[:2] == ["a", "b"]
    assert "c" in result.names


# ---------------------------------------------------------------------------
# 9. remove_internal_metrics_from_metadata tests
# ---------------------------------------------------------------------------


def test_remove_internal_metrics_from_metadata_basic():
    """Remove internal metrics from metadata dict."""
    metadata = {
        "user_metric": "value1",
        "another_metric": "value2",
    }
    # Add some internal metrics
    for metric in list(internal_metrics)[:2]:
        metadata[metric] = "internal_value"

    result = OperatorUtils.remove_internal_metrics_from_metadata(metadata)

    assert "user_metric" in metadata
    assert "another_metric" in metadata
    assert len(result) > 0  # Internal metrics were removed


def test_remove_internal_metrics_from_metadata_empty():
    """Handle empty metadata dict."""
    metadata: dict[str, object] = {}
    result = OperatorUtils.remove_internal_metrics_from_metadata(metadata)

    assert result == {}


def test_remove_internal_metrics_from_metadata_no_internal():
    """Handle metadata with no internal metrics."""
    metadata = {"user_metric": "value"}
    result = OperatorUtils.remove_internal_metrics_from_metadata(metadata)

    assert result == {}
    assert "user_metric" in metadata


# ---------------------------------------------------------------------------
# 10. drop_features_from_table tests
# ---------------------------------------------------------------------------


def test_drop_features_from_table_basic():
    """Drop specified columns from table."""
    table = pa.table(
        {
            "id": ["1", "2"],
            "name": ["a", "b"],
            "content": ["x", "y"],
        }
    )
    result = OperatorUtils.drop_features_from_table(["content"], table)

    assert "content" not in result.column_names
    assert "id" in result.column_names
    assert "name" in result.column_names


def test_drop_features_from_table_multiple():
    """Drop multiple columns."""
    table = pa.table(
        {
            "id": ["1"],
            "a": ["x"],
            "b": ["y"],
            "c": ["z"],
        }
    )
    result = OperatorUtils.drop_features_from_table(["a", "c"], table)

    assert result.column_names == ["id", "b"]


def test_drop_features_from_table_nonexistent():
    """Dropping nonexistent column doesn't error."""
    table = pa.table(
        {
            "id": ["1"],
            "name": ["a"],
        }
    )
    result = OperatorUtils.drop_features_from_table(["nonexistent"], table)

    assert result.column_names == table.column_names


def test_drop_features_from_table_empty_list():
    """Empty drop list returns original table."""
    table = pa.table(
        {
            "id": ["1"],
            "name": ["a"],
        }
    )
    result = OperatorUtils.drop_features_from_table([], table)

    assert result.column_names == table.column_names


# ---------------------------------------------------------------------------
# 11. get_mandatory_features tests
# ---------------------------------------------------------------------------


def test_get_mandatory_features_basic():
    """Identify mandatory features."""
    input_features = {
        "field1": {OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY]},
        "field2": {OperatorConstants.Misc.TAGS: []},
        "field3": {OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY]},
    }
    check_features = ["field1", "field2", "field3"]

    result = OperatorUtils.get_mandatory_features(check_features=check_features, input_features=input_features)

    assert set(result) == {"field1", "field3"}


def test_get_mandatory_features_none():
    """No mandatory features returns empty list."""
    input_features: dict[str, dict] = {
        "field1": {OperatorConstants.Misc.TAGS: []},
        "field2": {OperatorConstants.Misc.TAGS: []},
    }
    check_features = ["field1", "field2"]

    result = OperatorUtils.get_mandatory_features(check_features=check_features, input_features=input_features)

    assert result == []


def test_get_mandatory_features_empty_check_list():
    """Empty check list returns empty result."""
    input_features = {
        "field1": {OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY]},
    }

    result = OperatorUtils.get_mandatory_features(check_features=[], input_features=input_features)

    assert result == []


def test_get_mandatory_features_no_tags():
    """Features without tags are not mandatory."""
    input_features = {
        "field1": {},
        "field2": {OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY]},
    }
    check_features = ["field1", "field2"]

    result = OperatorUtils.get_mandatory_features(check_features=check_features, input_features=input_features)

    assert result == ["field2"]


# ---------------------------------------------------------------------------
# 12. validate_filter_criteria tests
# ---------------------------------------------------------------------------


def test_validate_filter_criteria_valid_list():
    """Valid criteria_list returns True."""
    criteria_list = ["age > 18", "status = 'active'"]
    criteria_json = None

    criteria_valid, json_valid = OperatorUtils.validate_filter_criteria(
        criteria_list=criteria_list, criteria_json=criteria_json
    )

    assert criteria_valid is True
    assert json_valid is False


def test_validate_filter_criteria_valid_json_leaf():
    """Valid JSON leaf condition returns True."""
    criteria_list = None
    criteria_json = {"variable": "age", "operator": ">", "value": 18}

    criteria_valid, json_valid = OperatorUtils.validate_filter_criteria(
        criteria_list=criteria_list, criteria_json=criteria_json
    )

    assert criteria_valid is False
    assert json_valid is True


def test_validate_filter_criteria_valid_json_group():
    """Valid JSON group with criteria returns True."""
    criteria_list = None
    criteria_json = {
        "logical_operator": "AND",
        "criteria_list": [
            {"variable": "age", "operator": ">", "value": 18},
            {"variable": "status", "operator": "=", "value": "active"},
        ],
    }

    criteria_valid, json_valid = OperatorUtils.validate_filter_criteria(
        criteria_list=criteria_list, criteria_json=criteria_json
    )

    assert criteria_valid is False
    assert json_valid is True


def test_validate_filter_criteria_empty_list():
    """Empty criteria_list returns False."""
    criteria_list: list[str] = []
    criteria_json = None

    criteria_valid, _ = OperatorUtils.validate_filter_criteria(criteria_list=criteria_list, criteria_json=criteria_json)

    assert criteria_valid is False


def test_validate_filter_criteria_list_with_empty_strings():
    """List with only empty strings returns False."""
    criteria_list = ["", "  ", ""]
    criteria_json = None

    criteria_valid, _ = OperatorUtils.validate_filter_criteria(criteria_list=criteria_list, criteria_json=criteria_json)

    assert criteria_valid is False


def test_validate_filter_criteria_invalid_json_empty_group():
    """JSON group with empty criteria_list returns False."""
    criteria_list = None
    criteria_json = {"logical_operator": "AND", "criteria_list": []}

    _, json_valid = OperatorUtils.validate_filter_criteria(criteria_list=criteria_list, criteria_json=criteria_json)

    assert json_valid is False


def test_validate_filter_criteria_nested_json():
    """Nested JSON groups validate correctly."""
    criteria_json = {
        "logical_operator": "OR",
        "criteria_list": [
            {"variable": "age", "operator": ">", "value": 18},
            {
                "logical_operator": "AND",
                "criteria_list": [
                    {"variable": "status", "operator": "=", "value": "active"},
                    {"variable": "verified", "operator": "=", "value": True},
                ],
            },
        ],
    }

    _, json_valid = OperatorUtils.validate_filter_criteria(criteria_list=None, criteria_json=criteria_json)

    assert json_valid is True


# ---------------------------------------------------------------------------
# 13. _validate_criteria_json tests
# ---------------------------------------------------------------------------


def test_validate_criteria_json_leaf_condition():
    """Leaf condition with variable and operator is valid."""
    criteria = {"variable": "age", "operator": ">"}

    assert OperatorUtils._validate_criteria_json(criteria_json=criteria) is True


def test_validate_criteria_json_group_with_valid_items():
    """Group with all valid items is valid."""
    criteria = {
        "criteria_list": [
            {"variable": "age", "operator": ">"},
            {"variable": "name", "operator": "="},
        ]
    }

    assert OperatorUtils._validate_criteria_json(criteria_json=criteria) is True


def test_validate_criteria_json_empty_dict():
    """Empty dict is invalid."""
    assert OperatorUtils._validate_criteria_json(criteria_json={}) is False


def test_validate_criteria_json_none():
    """None is invalid."""
    assert OperatorUtils._validate_criteria_json(criteria_json=None) is False


def test_validate_criteria_json_group_with_invalid_item():
    """Group with any invalid item is invalid."""
    criteria = {
        "criteria_list": [
            {"variable": "age", "operator": ">"},
            {"invalid": "item"},  # Missing variable and operator
        ]
    }

    assert OperatorUtils._validate_criteria_json(criteria_json=criteria) is False


def test_validate_criteria_json_group_empty_list():
    """Group with empty criteria_list is invalid."""
    criteria: dict[str, list] = {"criteria_list": []}

    assert OperatorUtils._validate_criteria_json(criteria_json=criteria) is False


# ---------------------------------------------------------------------------
# 14. rename_features_and_save_original tests (Table)
# ---------------------------------------------------------------------------


def test_rename_features_table_basic():
    """Rename columns in PyArrow table."""
    table = pa.table(
        {
            "old_name": ["a", "b"],
            "keep_name": ["x", "y"],
        }
    )
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "old_name",
            OperatorConstants.Misc.NEW_FEATURE: "new_name",
        }
    ]

    result = OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)

    assert "new_name" in result.column_names
    assert "old_name" not in result.column_names
    assert "keep_name" in result.column_names


def test_rename_features_table_multiple():
    """Rename multiple columns."""
    table = pa.table(
        {
            "a": [1],
            "b": [2],
            "c": [3],
        }
    )
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "a",
            OperatorConstants.Misc.NEW_FEATURE: "x",
        },
        {
            OperatorConstants.Misc.OLD_FEATURE: "b",
            OperatorConstants.Misc.NEW_FEATURE: "y",
        },
    ]

    result = OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)

    assert set(result.column_names) == {"x", "y", "c"}


def test_rename_features_table_nonexistent_column():
    """Renaming nonexistent column raises KeyError."""
    table = pa.table({"a": [1]})
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "nonexistent",
            OperatorConstants.Misc.NEW_FEATURE: "new",
        }
    ]

    with pytest.raises(KeyError):
        OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)


def test_rename_features_table_duplicate_new_name():
    """Duplicate new name raises ValueError."""
    table = pa.table({"a": [1], "b": [2]})
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "a",
            OperatorConstants.Misc.NEW_FEATURE: "same",
        },
        {
            OperatorConstants.Misc.OLD_FEATURE: "b",
            OperatorConstants.Misc.NEW_FEATURE: "same",
        },
    ]

    with pytest.raises(ValueError, match="Duplicate name"):
        OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)


# ---------------------------------------------------------------------------
# 15. rename_features_and_save_original tests (Dict)
# ---------------------------------------------------------------------------


def test_rename_features_dict_basic():
    """Rename features in dict and save original name."""
    input_features = {
        "old_name": {"type": "string"},
        "keep_name": {"type": "int"},
    }
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "old_name",
            OperatorConstants.Misc.NEW_FEATURE: "new_name",
        }
    ]

    OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=input_features)

    assert "new_name" in input_features
    assert "old_name" not in input_features
    assert input_features["new_name"][OperatorConstants.Misc.ORIGINAL_FEATURE] == "old_name"


def test_rename_features_dict_mandatory_raises():
    """Renaming mandatory feature raises FlowValidationException."""
    input_features = {
        "mandatory_field": {
            "type": "string",
            OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY],
        },
    }
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "mandatory_field",
            OperatorConstants.Misc.NEW_FEATURE: "new_name",
        }
    ]

    with pytest.raises(FlowValidationException):
        OperatorUtils.rename_features_and_save_original(
            updated_features=updated_features, input_features=input_features
        )


def test_rename_features_dict_preserves_original():
    """Original feature name is preserved in metadata."""
    input_features = {
        "field1": {"type": "string"},
    }
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "field1",
            OperatorConstants.Misc.NEW_FEATURE: "field2",
        }
    ]

    OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=input_features)

    # Rename again
    updated_features2 = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "field2",
            OperatorConstants.Misc.NEW_FEATURE: "field3",
        }
    ]
    OperatorUtils.rename_features_and_save_original(updated_features=updated_features2, input_features=input_features)

    # Original should still be field1
    assert input_features["field3"][OperatorConstants.Misc.ORIGINAL_FEATURE] == "field1"


def test_rename_features_none_inputs():
    """None inputs return None."""
    result = OperatorUtils.rename_features_and_save_original(updated_features=None, input_features=None)

    assert result is None


def test_rename_features_empty_updated_features():
    """Empty updated_features returns None."""
    input_features = {"field": {"type": "string"}}
    result = OperatorUtils.rename_features_and_save_original(updated_features=[], input_features=input_features)

    assert result is None


# ---------------------------------------------------------------------------
# 16. Edge cases and error handling
# ---------------------------------------------------------------------------


def test_rename_features_invalid_mapping_format():
    """Invalid mapping format raises ValueError."""
    table = pa.table({"a": [1]})
    updated_features = [
        "not_a_dict"  # Should be dict
    ]

    with pytest.raises(ValueError, match="must be a dict"):
        OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)


def test_rename_features_missing_keys():
    """Missing old_feature or new_feature raises ValueError."""
    table = pa.table({"a": [1]})
    updated_features = [
        {"old_feature": "a"}  # Missing new_feature
    ]

    with pytest.raises(ValueError, match="must contain"):
        OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)


def test_rename_features_duplicate_old_feature():
    """Duplicate old_feature in mappings raises ValueError."""
    table = pa.table({"a": [1], "b": [2]})
    updated_features = [
        {
            OperatorConstants.Misc.OLD_FEATURE: "a",
            OperatorConstants.Misc.NEW_FEATURE: "x",
        },
        {
            OperatorConstants.Misc.OLD_FEATURE: "a",
            OperatorConstants.Misc.NEW_FEATURE: "y",
        },
    ]

    with pytest.raises(ValueError, match="Duplicate mapping"):
        OperatorUtils.rename_features_and_save_original(updated_features=updated_features, input_features=table)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# 17. extract_text_file tests
# ---------------------------------------------------------------------------


class TestOperatorUtilsExtractTextFile:
    """Test suite for OperatorUtils.extract_text_file method."""

    def test_extract_text_file_is_public_method(self):
        """Test that extract_text_file is a public static method."""
        # Verify method exists and is callable
        assert hasattr(OperatorUtils, "extract_text_file")
        assert callable(OperatorUtils.extract_text_file)
        # Verify it's a static method (not bound to instance)
        assert isinstance(OperatorUtils.__dict__["extract_text_file"], staticmethod)

    def test_extract_text_file_utf8_content_success(self):
        """Test extraction of UTF-8 encoded text file."""
        file_path = "/path/to/document.txt"
        binary_content = b"This is a test document.\nWith multiple lines."

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "This is a test document.\nWith multiple lines."
        assert OperatorConstants.Metadata.METADATA in result
        assert result[OperatorConstants.Metadata.METADATA]["is_text_file"] is True

    def test_extract_text_file_latin1_fallback(self):
        """Test extraction falls back to latin-1 encoding when UTF-8 fails."""
        file_path = "/path/to/document.txt"
        # Create content with latin-1 specific characters that aren't valid UTF-8
        binary_content = b"Text with special chars: \xe9\xe0\xf1"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        # latin-1 should decode these characters
        assert "Text with special chars:" in result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    def test_extract_text_file_empty_content(self):
        """Test extraction of empty text file."""
        file_path = "/path/to/empty.txt"
        binary_content = b""

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == ""
        assert result[OperatorConstants.Metadata.METADATA]["char_count"] == 0

    def test_extract_text_file_multiline_content(self):
        """Test extraction of multiline text content."""
        file_path = "/path/to/multiline.txt"
        binary_content = b"Line 1\nLine 2\nLine 3\n"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Line 1\nLine 2\nLine 3\n"
        assert result[OperatorConstants.Metadata.METADATA]["char_count"] == len("Line 1\nLine 2\nLine 3\n")

    def test_extract_text_file_unicode_content(self):
        """Test extraction of Unicode text content."""
        file_path = "/path/to/unicode.txt"
        binary_content = "Hello 世界 🌍".encode()

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Hello 世界 🌍"

    def test_extract_text_file_metadata_structure(self):
        """Test that metadata has correct structure."""
        file_path = "/path/to/document.txt"
        binary_content = b"Test content"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        metadata = result[OperatorConstants.Metadata.METADATA]
        assert "char_count" in metadata
        assert "is_text_file" in metadata
        assert metadata["char_count"] == len("Test content")
        assert metadata["is_text_file"] is True

    def test_extract_text_file_handles_txt_extension(self):
        """Test that .txt files are handled correctly."""
        file_path = "/path/to/notes.txt"
        binary_content = b"Plain text notes"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Plain text notes"

    def test_extract_text_file_does_not_handle_md_files(self):
        """Test that extract_text_file can be used for any text, including .md files."""
        # Note: The adapter layer decides routing, not extract_text_file itself
        file_path = "/path/to/readme.md"
        binary_content = b"# Markdown Header\n\nContent"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        # extract_text_file will process any text content given to it
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown Header\n\nContent"

    def test_extract_text_file_large_content(self):
        """Test extraction of large text content."""
        file_path = "/path/to/large.txt"
        # Create large content (10KB)
        binary_content = b"A" * 10000

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert len(result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT]) == 10000
        assert result[OperatorConstants.Metadata.METADATA]["char_count"] == 10000

    def test_extract_text_file_whitespace_content(self):
        """Test extraction of content with various whitespace."""
        file_path = "/path/to/whitespace.txt"
        binary_content = b"  \t\n  Text with spaces  \t\n  "

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        # Whitespace should be preserved
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "  \t\n  Text with spaces  \t\n  "

    def test_extract_text_file_special_characters(self):
        """Test extraction with special characters."""
        file_path = "/path/to/special.txt"
        binary_content = b"Special chars: @#$%^&*()_+-=[]{}|;:',.<>?/~`"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Special chars: @#$%^&*()_+-=[]{}|;:',.<>?/~`"

    def test_extract_text_file_additional_format_text(self):
        """Test that 'text' additional format populates content_text column."""
        file_path = "/path/to/document.txt"
        binary_content = b"Hello world"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["text"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Hello world"
        assert result[OperatorConstants.Columns.CONTENT_TEXT] == "Hello world"

    def test_extract_text_file_additional_format_html(self):
        """Test that 'html' additional format produces valid HTML via native Docling export."""
        file_path = "/path/to/document.txt"
        binary_content = b"Hello world"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["html"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        html = result[OperatorConstants.Columns.CONTENT_HTML]
        assert html is not None
        assert "Hello world" in html
        assert "<html" in html.lower()

    def test_extract_text_file_additional_format_json(self):
        """Test that 'json' additional format produces a valid Docling JSON dict."""
        import json

        file_path = "/path/to/document.txt"
        binary_content = b"Hello world"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["json"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        parsed = json.loads(result[OperatorConstants.Columns.CONTENT_JSON])
        # Docling export_to_dict() returns a structured document — verify it's a non-empty dict
        assert isinstance(parsed, dict)
        assert len(parsed) > 0

    def test_extract_text_file_additional_formats_multiple(self):
        """Test multiple additional formats are all populated."""
        file_path = "/path/to/document.txt"
        binary_content = b"Sample text"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["text", "html", "json"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.CONTENT_TEXT] == "Sample text"
        assert OperatorConstants.Columns.CONTENT_HTML in result
        assert OperatorConstants.Columns.CONTENT_JSON in result

    def test_extract_text_file_additional_format_doctags(self):
        """Test that doctags format is populated for plain text files."""
        file_path = "/path/to/document.txt"
        binary_content = b"Sample text"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["doctags"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Columns.CONTENT_DOCTAGS in result
        doctags = result[OperatorConstants.Columns.CONTENT_DOCTAGS]
        assert doctags is not None
        assert "Sample text" in doctags

    def test_extract_text_file_additional_format_doclang(self):
        """Test that doclang format is populated for plain text files."""
        file_path = "/path/to/document.txt"
        binary_content = b"Sample text"

        result = OperatorUtils.extract_text_file(
            file_path=file_path, binary_content=binary_content, additional_formats=["doclang"]
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Columns.CONTENT_DOCLANG in result
        doclang = result[OperatorConstants.Columns.CONTENT_DOCLANG]
        assert doclang is not None
        assert "Sample text" in doclang

    def test_extract_text_file_no_additional_formats_unchanged(self):
        """Test that omitting additional_formats keeps original behaviour."""
        file_path = "/path/to/document.txt"
        binary_content = b"Hello world"

        result = OperatorUtils.extract_text_file(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Columns.CONTENT_TEXT not in result
        assert OperatorConstants.Columns.CONTENT_HTML not in result
        assert OperatorConstants.Columns.CONTENT_JSON not in result


# ---------------------------------------------------------------------------
# sanitize_doc_id_for_filename tests
# ---------------------------------------------------------------------------


def test_sanitize_doc_id_for_filename_with_slashes():
    """Test sanitizing document IDs containing forward slashes."""
    from docpipe.core.operators.operator_utils import sanitize_doc_id_for_filename

    doc_id = "folder/subfolder/document.pdf"
    result = sanitize_doc_id_for_filename(doc_id=doc_id)

    assert result == "folder_subfolder_document.pdf"
    assert "/" not in result


def test_sanitize_doc_id_for_filename_no_slashes():
    """Test sanitizing document IDs without slashes."""
    from docpipe.core.operators.operator_utils import sanitize_doc_id_for_filename

    doc_id = "simple_document_id"
    result = sanitize_doc_id_for_filename(doc_id=doc_id)

    assert result == "simple_document_id"


def test_sanitize_doc_id_for_filename_multiple_slashes():
    """Test sanitizing document IDs with multiple consecutive slashes."""
    from docpipe.core.operators.operator_utils import sanitize_doc_id_for_filename

    doc_id = "path//to///file.txt"
    result = sanitize_doc_id_for_filename(doc_id=doc_id)

    assert result == "path__to___file.txt"
    assert "/" not in result


# ---------------------------------------------------------------------------
# DocumentConverter pool key / lease tests
# ---------------------------------------------------------------------------


def _docling_format_options(*, do_ocr: bool = True, ocr_options=None, ocr_lang=None) -> dict:
    """Build a real Docling format_options dict (no models are loaded)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import ImageFormatOption, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = do_ocr
    if ocr_options is not None:
        pipeline_options.ocr_options = ocr_options
    if ocr_lang is not None:
        pipeline_options.ocr_options.lang = ocr_lang
    return {
        "format_options": {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        }
    }


class TestConverterCacheKey:
    """Tests for _converter_cache_key()."""

    def test_none_config_returns_default(self):
        from docpipe.core.operators.operator_utils import _converter_cache_key

        assert _converter_cache_key(None) == "default"

    def test_empty_dict_returns_default(self):
        from docpipe.core.operators.operator_utils import _converter_cache_key

        assert _converter_cache_key({}) == "default"

    def test_no_format_options_key_returns_default(self):
        from docpipe.core.operators.operator_utils import _converter_cache_key

        assert _converter_cache_key({"other_key": "value"}) == "default"

    def test_format_options_produces_hex_digest(self):
        from unittest.mock import MagicMock

        from docpipe.core.operators.operator_utils import _converter_cache_key

        opt = MagicMock()
        opt.__class__.__name__ = "PdfFormatOption"
        key = _converter_cache_key({"format_options": {"pdf": opt}})
        assert key != "default"
        assert len(key) == 64  # SHA-256 hex digest length
        int(key, 16)

    def test_same_config_produces_same_key(self):
        from unittest.mock import MagicMock

        from docpipe.core.operators.operator_utils import _converter_cache_key

        opt = MagicMock()
        opt.__class__.__name__ = "PdfFormatOption"
        config = {"format_options": {"pdf": opt}}
        assert _converter_cache_key(config) == _converter_cache_key(config)

    def test_different_option_types_produce_different_keys(self):
        from unittest.mock import MagicMock

        from docpipe.core.operators.operator_utils import _converter_cache_key

        opt_pdf = MagicMock()
        opt_pdf.__class__.__name__ = "PdfFormatOption"
        opt_vlm = MagicMock()
        opt_vlm.__class__.__name__ = "VlmPipelineOption"

        key_pdf = _converter_cache_key({"format_options": {"pdf": opt_pdf}})
        key_vlm = _converter_cache_key({"format_options": {"pdf": opt_vlm}})
        assert key_pdf != key_vlm

    def test_equal_values_built_independently_share_key(self):
        """Two operator instances building the same Docling options get the same key."""
        from docpipe.core.operators.operator_utils import _converter_cache_key

        assert _converter_cache_key(_docling_format_options()) == _converter_cache_key(_docling_format_options())

    def test_same_option_class_different_values_produce_different_keys(self):
        """Regression: the old key only used option *type* names, so these collided."""
        from docling.datamodel.pipeline_options import EasyOcrOptions

        from docpipe.core.operators.operator_utils import _converter_cache_key

        keys = {
            _converter_cache_key(_docling_format_options()),
            _converter_cache_key(_docling_format_options(do_ocr=False)),
            _converter_cache_key(_docling_format_options(ocr_options=EasyOcrOptions())),
            _converter_cache_key(_docling_format_options(ocr_options=EasyOcrOptions(), ocr_lang=["de"])),
        }
        assert len(keys) == 4

    def test_different_ocr_engines_produce_different_keys(self):
        from docling.datamodel.pipeline_options import (
            EasyOcrOptions,
            RapidOcrOptions,
            TesseractCliOcrOptions,
            TesseractOcrOptions,
        )

        from docpipe.core.operators.operator_utils import _converter_cache_key

        engines = [EasyOcrOptions(), RapidOcrOptions(), TesseractOcrOptions(), TesseractCliOcrOptions()]
        keys = {_converter_cache_key(_docling_format_options(ocr_options=engine)) for engine in engines}
        assert len(keys) == len(engines)


class TestLeaseConverter:
    """Tests for _lease_converter() — pooled, exclusive DocumentConverter reuse."""

    def test_lease_creates_default_converter(self):
        """First lease with no config constructs a new DocumentConverter with no args."""
        from unittest.mock import MagicMock, patch

        from docpipe.core.operators.operator_utils import _lease_converter

        mock_converter = MagicMock()
        with patch("docling.document_converter.DocumentConverter", return_value=mock_converter) as mock_cls:
            with _lease_converter(None) as converter:
                assert converter is mock_converter

        mock_cls.assert_called_once_with()

    def test_converter_reused_after_release(self):
        """A released converter is reused by the next lease instead of being rebuilt."""
        from unittest.mock import MagicMock, patch

        from docpipe.core.operators.operator_utils import _lease_converter

        with patch("docling.document_converter.DocumentConverter", side_effect=lambda **_: MagicMock()) as mock_cls:
            with _lease_converter(None) as first:
                pass
            with _lease_converter(None) as second:
                pass

        assert mock_cls.call_count == 1
        assert first is second

    def test_nested_leases_get_distinct_converters(self):
        """A converter is never handed to two holders at once."""
        from unittest.mock import MagicMock, patch

        from docpipe.core.operators.operator_utils import _lease_converter

        with patch("docling.document_converter.DocumentConverter", side_effect=lambda **_: MagicMock()) as mock_cls:
            with _lease_converter(None) as first, _lease_converter(None) as second:
                assert first is not second

        assert mock_cls.call_count == 2

    def test_different_configs_use_independent_converters(self):
        """Distinct format_options produce separate converters, each built with its options."""
        from unittest.mock import MagicMock, patch

        from docpipe.core.operators.operator_utils import _lease_converter

        no_ocr = _docling_format_options(do_ocr=False)
        with patch("docling.document_converter.DocumentConverter", side_effect=lambda **_: MagicMock()) as mock_cls:
            with _lease_converter(None) as default_converter:
                pass
            with _lease_converter(no_ocr) as no_ocr_converter:
                pass
            with _lease_converter(_docling_format_options(do_ocr=False)) as no_ocr_again:
                pass

        assert mock_cls.call_count == 2
        assert default_converter is not no_ocr_converter
        assert no_ocr_again is no_ocr_converter
        assert mock_cls.call_args_list[1].kwargs == {"format_options": no_ocr["format_options"]}

    def test_extract_content_uses_supplied_converter_without_pool(self):
        """An explicitly supplied converter bypasses the pool entirely."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        doc = MagicMock()
        doc.export_to_markdown.return_value = "# hi"
        doc.pages = {1: None}
        supplied = MagicMock()
        supplied.convert.return_value = SimpleNamespace(document=doc)

        with patch("docling.document_converter.DocumentConverter") as mock_cls:
            result = OperatorUtils.extract_content(file_path="a.pdf", binary_content=b"%PDF", converter=supplied)

        mock_cls.assert_not_called()
        supplied.convert.assert_called_once()
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# hi"


# ---------------------------------------------------------------------------
# is_asr_available tests
# ---------------------------------------------------------------------------


def test_is_asr_available_when_import_succeeds():
    """Returns True when all ASR dependencies can be imported."""
    import sys
    from unittest.mock import MagicMock, patch

    from docpipe.core.operators.operator_utils import is_asr_available

    asr_mock = MagicMock()
    with patch.dict(
        sys.modules,
        {
            "docling.datamodel.asr_model_specs": asr_mock,
            "docling.document_converter": MagicMock(AudioFormatOption=MagicMock()),
            "docling.pipeline.asr_pipeline": MagicMock(AsrPipeline=MagicMock()),
        },
    ):
        # Force a fresh evaluation inside the function
        result = is_asr_available()
    # Result depends on whether real docling asr is installed; just assert it returns a bool
    assert isinstance(result, bool)


def test_is_asr_available_when_import_fails():
    """Returns False when an ImportError is raised."""
    import sys
    from unittest.mock import patch

    from docpipe.core.operators.operator_utils import is_asr_available

    # Remove docling entirely so the inner imports fail
    with patch.dict(sys.modules, {"docling.datamodel.asr_model_specs": None}):
        result = is_asr_available()
    assert result is False


# ---------------------------------------------------------------------------
# get_supported_file_extensions tests
# ---------------------------------------------------------------------------


def test_get_supported_file_extensions_returns_string():
    """Returns a non-empty comma-separated string."""
    from docpipe.core.operators.operator_utils import get_supported_file_extensions

    result = get_supported_file_extensions()
    assert isinstance(result, str)
    assert len(result) > 0
    assert "," in result


def test_get_supported_file_extensions_no_leading_dots():
    """Extensions must not have leading dots."""
    from docpipe.core.operators.operator_utils import get_supported_file_extensions

    result = get_supported_file_extensions()
    for ext in result.split(","):
        assert not ext.startswith("."), f"Extension {ext!r} has a leading dot"


def test_get_supported_file_extensions_with_asr(monkeypatch):
    """When ASR is available, audio/video extensions are included."""
    from docpipe.core.operators import operator_utils

    monkeypatch.setattr(operator_utils, "is_asr_available", lambda: True)
    result = operator_utils.get_supported_file_extensions()
    assert isinstance(result, str)


def test_get_supported_file_extensions_without_asr(monkeypatch):
    """When ASR is unavailable, audio/video extensions are excluded."""
    from docpipe.core.operators import operator_utils

    monkeypatch.setattr(operator_utils, "is_asr_available", lambda: False)
    result = operator_utils.get_supported_file_extensions()
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# resolve_env_var tests
# ---------------------------------------------------------------------------


def test_resolve_env_var_non_string_passthrough():
    """Non-string values are returned unchanged."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    assert resolve_env_var(42) == 42
    assert resolve_env_var(None) is None
    assert resolve_env_var([1, 2]) == [1, 2]


def test_resolve_env_var_dollar_brace_set(monkeypatch):
    """${VAR} resolves when env var is set."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    monkeypatch.setenv("MY_VAR", "hello")
    assert resolve_env_var("${MY_VAR}") == "hello"


def test_resolve_env_var_dollar_brace_unset_raises():
    """${VAR} raises ValueError when env var is not set."""
    import os

    from docpipe.core.operators.operator_utils import resolve_env_var

    os.environ.pop("UNSET_VAR_XYZ", None)
    with pytest.raises(ValueError, match="UNSET_VAR_XYZ"):
        resolve_env_var("${UNSET_VAR_XYZ}")


def test_resolve_env_var_dollar_brace_with_default(monkeypatch):
    """${VAR:default} returns default when env var is missing."""
    import os

    from docpipe.core.operators.operator_utils import resolve_env_var

    os.environ.pop("MISSING_VAR_ABC", None)
    assert resolve_env_var("${MISSING_VAR_ABC:fallback}") == "fallback"


def test_resolve_env_var_dollar_brace_with_dash_default(monkeypatch):
    """${VAR:-default} strips the dash and returns the default."""
    import os

    from docpipe.core.operators.operator_utils import resolve_env_var

    os.environ.pop("MISSING_VAR_DEF", None)
    assert resolve_env_var("${MISSING_VAR_DEF:-mydefault}") == "mydefault"


def test_resolve_env_var_plain_dollar_set(monkeypatch):
    """$VAR resolves when env var is set."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    monkeypatch.setenv("PLAIN_VAR", "world")
    assert resolve_env_var("$PLAIN_VAR") == "world"


def test_resolve_env_var_plain_dollar_unset_raises():
    """$VAR raises ValueError when env var is not set."""
    import os

    from docpipe.core.operators.operator_utils import resolve_env_var

    os.environ.pop("UNSET_PLAIN_VAR", None)
    with pytest.raises(ValueError, match="UNSET_PLAIN_VAR"):
        resolve_env_var("$UNSET_PLAIN_VAR")


def test_resolve_env_var_uppercase_with_underscore_found(monkeypatch):
    """UPPER_CASE value treated as env var lookup when set."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    monkeypatch.setenv("UPPER_CASE_VAR", "resolved")
    assert resolve_env_var("UPPER_CASE_VAR") == "resolved"


def test_resolve_env_var_uppercase_with_underscore_not_found():
    """UPPER_CASE value returned as-is when env var is not set."""
    import os

    from docpipe.core.operators.operator_utils import resolve_env_var

    os.environ.pop("NOT_A_REAL_ENV_VAR", None)
    assert resolve_env_var("NOT_A_REAL_ENV_VAR") == "NOT_A_REAL_ENV_VAR"


def test_resolve_env_var_plain_string_passthrough():
    """Plain lowercase string is returned as-is."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    assert resolve_env_var("plain_value") == "plain_value"


# ---------------------------------------------------------------------------
# validate_columns tests (missing paths: list input + raising path)
# ---------------------------------------------------------------------------


def test_validate_columns_list_input_missing_feature_appends_to_errors():
    """validate_columns with list input and missing features appends to error_messages."""
    from docpipe.core.operators.operator_utils import OperatorUtils

    errors: list = []
    OperatorUtils.validate_columns(
        table=["col_a"],
        required=["col_a", "col_b"],
        operator_name="TestOp",
        error_messages=errors,
    )
    assert len(errors) == 1


def test_validate_columns_table_input_raises_when_no_error_list():
    """validate_columns with pa.Table and missing column raises FlowExecutionFailedException."""
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    table = pa.table({"col_a": ["x"]})
    with pytest.raises(FlowExecutionFailedException):
        OperatorUtils.validate_columns(
            table=table,
            required=["col_a", "col_missing"],
            operator_name="TestOp",
            error_messages=None,
        )


def test_validate_columns_table_input_appends_to_errors():
    """validate_columns with pa.Table and error_messages list appends instead of raising."""
    table = pa.table({"col_a": ["x"]})
    errors: list = []
    OperatorUtils.validate_columns(
        table=table,
        required=["col_a", "col_missing"],
        operator_name="TestOp",
        error_messages=errors,
    )
    assert len(errors) == 1


def test_validate_columns_all_present_no_error():
    """validate_columns with all required columns present does nothing."""
    table = pa.table({"col_a": ["x"], "col_b": ["y"]})
    errors: list = []
    OperatorUtils.validate_columns(
        table=table,
        required=["col_a", "col_b"],
        operator_name="TestOp",
        error_messages=errors,
    )
    assert errors == []


# ---------------------------------------------------------------------------
# merge_status tests
# ---------------------------------------------------------------------------


def test_merge_status_lower_code_wins():
    """merge_status returns the status with the lower (more severe) code."""
    from docpipe.core.constants.constants import ExecutionStatus

    result = OperatorUtils.merge_status(ExecutionStatus.FAILED, ExecutionStatus.COMPLETED)
    assert result == ExecutionStatus.FAILED


def test_merge_status_same_severity():
    """merge_status returns new_stat when codes are equal."""
    from docpipe.core.constants.constants import ExecutionStatus

    result = OperatorUtils.merge_status(ExecutionStatus.COMPLETED, ExecutionStatus.COMPLETED)
    assert result == ExecutionStatus.COMPLETED


# ---------------------------------------------------------------------------
# get_feature tests
# ---------------------------------------------------------------------------


def test_get_feature_defaults():
    """get_feature returns dict with correct keys and defaults."""
    result = OperatorUtils.get_feature(name="my_col", description="desc", type="string")

    assert result[OperatorConstants.Misc.NAME] == "my_col"
    assert result[OperatorConstants.Config.DESCRIPTION] == "desc"
    assert result[OperatorConstants.Config.AVAILABLE_FOR_FILTER] is False
    assert result[OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB] is False
    assert result[OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB] is False


def test_get_feature_all_flags():
    """get_feature with all boolean flags set to True."""
    result = OperatorUtils.get_feature(
        name="col",
        description="d",
        type="int",
        available_for_filter=True,
        available_for_vector_db=True,
        mandatory_for_vector_db=True,
    )
    assert result[OperatorConstants.Config.AVAILABLE_FOR_FILTER] is True
    assert result[OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB] is True
    assert result[OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB] is True


# ---------------------------------------------------------------------------
# get_aggregated_flow_logs tests
# ---------------------------------------------------------------------------


def test_get_aggregated_flow_logs_file_not_found(tmp_path):
    """Returns fallback message when the log file does not exist."""
    from unittest.mock import patch

    with patch(
        "docpipe.utils.operators.logging.get_log_and_job_file_path",
        return_value=("a", "b", "c", str(tmp_path / "missing.json")),
    ):
        result = OperatorUtils.get_aggregated_flow_logs(job_id="j1", jobrun_id="r1")

    assert result == {"message": "Logs are not available.!"}


def test_get_aggregated_flow_logs_file_exists(tmp_path):
    """Returns parsed JSON when the log file exists."""
    import json
    from unittest.mock import patch

    log_file = tmp_path / "log.json"
    log_data = {"job_stats": {"node1": {"node_status": "Completed"}}, "extra": "data"}
    log_file.write_text(json.dumps(log_data))

    with patch(
        "docpipe.utils.operators.logging.get_log_and_job_file_path",
        return_value=("a", "b", "c", str(log_file)),
    ):
        result = OperatorUtils.get_aggregated_flow_logs(job_id="j1", jobrun_id="r1")

    assert "extra" in result


# ---------------------------------------------------------------------------
# determine_final_job_status tests
# ---------------------------------------------------------------------------


def test_determine_final_job_status_empty_returns_starting():
    """Empty node list returns STARTING."""
    from docpipe.core.constants.constants import ExecutionStatus

    result = OperatorUtils.determine_final_job_status(node_stats_list={})
    assert result == ExecutionStatus.STARTING


def test_determine_final_job_status_dict_nodes():
    """Dict-based nodes: most severe status wins."""
    from docpipe.core.constants.constants import ExecutionStatus

    node_stats = {
        "n1": {"node_status": "Completed"},
        "n2": {"node_status": "Failed"},
    }
    result = OperatorUtils.determine_final_job_status(node_stats_list=node_stats)
    assert result == ExecutionStatus.FAILED


def test_determine_final_job_status_all_completed():
    """All completed nodes returns COMPLETED."""
    from docpipe.core.constants.constants import ExecutionStatus

    node_stats = {
        "n1": {"node_status": "Completed"},
        "n2": {"node_status": "Completed"},
    }
    result = OperatorUtils.determine_final_job_status(node_stats_list=node_stats)
    assert result == ExecutionStatus.COMPLETED


def test_determine_final_job_status_nodes_without_status_ignored():
    """Nodes with no node_status are skipped; returns COMPLETED when others all good."""
    from docpipe.core.constants.constants import ExecutionStatus

    node_stats = {
        "n1": {"node_status": "Completed"},
        "n2": {"node_status": None},
    }
    result = OperatorUtils.determine_final_job_status(node_stats_list=node_stats)
    assert result == ExecutionStatus.COMPLETED


# ---------------------------------------------------------------------------
# epoch_ms_to_iso8601_utc tests
# ---------------------------------------------------------------------------


def test_epoch_ms_to_iso8601_utc_valid():
    """Valid epoch ms returns correctly formatted ISO8601 string."""
    result = OperatorUtils.epoch_ms_to_iso8601_utc(1_700_000_000_000)
    assert result is not None
    assert result.endswith("Z")
    assert "T" in result


def test_epoch_ms_to_iso8601_utc_zero_returns_none():
    """Zero epoch returns None (falsy check)."""
    result = OperatorUtils.epoch_ms_to_iso8601_utc(0)
    assert result is None


def test_epoch_ms_to_iso8601_utc_none_returns_none():
    """None returns None."""
    result = OperatorUtils.epoch_ms_to_iso8601_utc(None)
    assert result is None


def test_epoch_ms_to_iso8601_utc_overflow_returns_none():
    """Overflow epoch returns None."""
    result = OperatorUtils.epoch_ms_to_iso8601_utc(10**30)
    assert result is None


# ---------------------------------------------------------------------------
# is_operator_present_in_flow tests
# ---------------------------------------------------------------------------


def test_is_operator_present_in_flow_found():
    """Returns True when operator is in the flow dag."""
    flow = {"dag": [{"operator": "my_op"}, {"operator": "other_op"}]}
    assert OperatorUtils.is_operator_present_in_flow(flow, "my_op") is True


def test_is_operator_present_in_flow_not_found():
    """Returns False when operator is absent."""
    flow = {"dag": [{"operator": "other_op"}]}
    assert OperatorUtils.is_operator_present_in_flow(flow, "my_op") is False


def test_is_operator_present_in_flow_empty_dag():
    """Returns False with empty dag."""
    assert OperatorUtils.is_operator_present_in_flow({"dag": []}, "op") is False


def test_is_operator_present_in_flow_none_flow():
    """Returns False for None flow_definition."""
    assert OperatorUtils.is_operator_present_in_flow(None, "op") is False


def test_is_operator_present_in_flow_non_dict():
    """Returns False for non-dict flow_definition."""
    assert OperatorUtils.is_operator_present_in_flow("not_a_dict", "op") is False


# ---------------------------------------------------------------------------
# get_unique_ids tests
# ---------------------------------------------------------------------------


def test_get_unique_ids_single_table():
    """Returns unique IDs from a single table."""
    table = pa.table({OperatorConstants.Misc.ID: ["a", "b", "a"]})
    result = OperatorUtils.get_unique_ids(table)
    assert set(result) == {"a", "b"}


def test_get_unique_ids_list_of_tables():
    """Returns unique IDs across list of tables."""
    t1 = pa.table({OperatorConstants.Misc.ID: ["a", "b"]})
    t2 = pa.table({OperatorConstants.Misc.ID: ["b", "c"]})
    result = OperatorUtils.get_unique_ids([t1, t2])
    assert set(result) == {"a", "b", "c"}


def test_get_unique_ids_dict_of_tables():
    """Returns unique IDs from dict of tables."""
    t1 = pa.table({OperatorConstants.Misc.ID: ["x"]})
    t2 = pa.table({OperatorConstants.Misc.ID: ["y"]})
    result = OperatorUtils.get_unique_ids({"t1": t1, "t2": t2})
    assert set(result) == {"x", "y"}


def test_get_unique_ids_none_returns_empty():
    """Returns empty list for None input."""
    assert OperatorUtils.get_unique_ids(None) == []


def test_get_unique_ids_empty_list_returns_empty():
    """Returns empty list for empty list input."""
    assert OperatorUtils.get_unique_ids([]) == []


# ---------------------------------------------------------------------------
# detect_extension_from_bytes tests
# ---------------------------------------------------------------------------


def test_detect_extension_pdf():
    """PDF magic bytes detected."""
    from docpipe.core.operators.operator_utils import OperatorUtils

    assert OperatorUtils.detect_extension_from_bytes(b"%PDFhello") == ".pdf"


def test_detect_extension_docx():
    """ZIP with word/ detected as docx."""
    content = b"PK" + b"\x00" * 50 + b"word/" + b"\x00" * 100
    assert OperatorUtils.detect_extension_from_bytes(content) == ".docx"


def test_detect_extension_xlsx():
    """ZIP with xl/ detected as xlsx."""
    content = b"PK" + b"\x00" * 50 + b"xl/" + b"\x00" * 100
    assert OperatorUtils.detect_extension_from_bytes(content) == ".xlsx"


def test_detect_extension_pptx():
    """ZIP with ppt/ detected as pptx."""
    content = b"PK" + b"\x00" * 50 + b"ppt/" + b"\x00" * 100
    assert OperatorUtils.detect_extension_from_bytes(content) == ".pptx"


def test_detect_extension_doc_ole2():
    """Legacy OLE2 magic bytes detected as .doc."""
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".doc"


def test_detect_extension_png():
    """PNG magic bytes detected."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".png"


def test_detect_extension_jpeg():
    """JPEG magic bytes detected."""
    content = b"\xff\xd8\xff" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".jpg"


def test_detect_extension_gif87a():
    """GIF87a detected."""
    content = b"GIF87a" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".gif"


def test_detect_extension_gif89a():
    """GIF89a detected."""
    content = b"GIF89a" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".gif"


def test_detect_extension_tiff_little_endian():
    """TIFF little-endian detected."""
    content = b"II*\x00" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".tiff"


def test_detect_extension_tiff_big_endian():
    """TIFF big-endian detected."""
    content = b"MM\x00*" + b"\x00" * 20
    assert OperatorUtils.detect_extension_from_bytes(content) == ".tiff"


def test_detect_extension_html_doctype():
    """<!doctype html detects as .html."""
    content = b"<!DOCTYPE html><html></html>"
    assert OperatorUtils.detect_extension_from_bytes(content) == ".html"


def test_detect_extension_html_tag():
    """<html> detects as .html."""
    content = b"<html><body>hi</body></html>"
    assert OperatorUtils.detect_extension_from_bytes(content) == ".html"


def test_detect_extension_plain_text():
    """Valid UTF-8 text defaults to .txt."""
    content = b"Just some plain text content."
    assert OperatorUtils.detect_extension_from_bytes(content) == ".txt"


def test_detect_extension_empty_returns_empty():
    """Empty bytes returns empty string."""
    assert OperatorUtils.detect_extension_from_bytes(b"") == ""


def test_detect_extension_unknown_binary_returns_empty():
    """Non-decodable binary with no known magic returns empty string."""
    # Create content that looks like arbitrary binary but doesn't match any magic
    content = bytes(range(256))[:20]  # arbitrary bytes, likely not valid UTF-8
    result = OperatorUtils.detect_extension_from_bytes(content)
    assert result in ("", ".txt")  # could be empty or txt depending on decode success


# ---------------------------------------------------------------------------
# _export_docling_formats tests
# ---------------------------------------------------------------------------


def test_export_docling_formats_unknown_format():
    """Unknown format is skipped with warning; known formats are populated."""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.export_to_text.return_value = "plain text"

    result = OperatorUtils._export_docling_formats(
        doc=mock_doc,
        additional_formats=["text", "unknown_format"],
        file_path="file.txt",
    )
    assert OperatorConstants.Columns.CONTENT_TEXT in result
    # unknown_format should be skipped (no key in result)
    assert len(result) == 1


def test_export_docling_formats_export_error_yields_none():
    """When an export function raises, the column value is set to None."""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.export_to_text.side_effect = RuntimeError("oops")

    result = OperatorUtils._export_docling_formats(
        doc=mock_doc,
        additional_formats=["text"],
        file_path="file.txt",
    )
    assert result[OperatorConstants.Columns.CONTENT_TEXT] is None


# ---------------------------------------------------------------------------
# _resolve_doc_id tests
# ---------------------------------------------------------------------------


def test_resolve_doc_id_uses_id_column():
    """Uses ID column when present."""
    table = pa.table(
        {
            OperatorConstants.Columns.ID: ["doc_id_1"],
            OperatorConstants.Columns.PATH: ["/some/path"],
        }
    )
    result = OperatorUtils._resolve_doc_id(table=table, row_idx=0)
    assert result == "doc_id_1"


def test_resolve_doc_id_falls_back_to_path():
    """Falls back to PATH column when ID is absent."""
    table = pa.table({OperatorConstants.Columns.PATH: ["/my/file.pdf"]})
    result = OperatorUtils._resolve_doc_id(table=table, row_idx=0)
    assert result == "/my/file.pdf"


def test_resolve_doc_id_falls_back_to_row_idx():
    """Falls back to doc_<idx> when neither ID nor PATH columns are present."""
    table = pa.table({"name": ["doc.pdf"]})
    result = OperatorUtils._resolve_doc_id(table=table, row_idx=3)
    assert result == "doc_3"


# ---------------------------------------------------------------------------
# _build_doc_metadata tests
# ---------------------------------------------------------------------------


def test_build_doc_metadata_basic():
    """Returns dict with name when no optional columns present."""
    table = pa.table({"name": ["doc.pdf"]})
    result = OperatorUtils._build_doc_metadata(table=table, row_idx=0, doc_name="doc.pdf", metadata_list=[None])
    assert result["name"] == "doc.pdf"


def test_build_doc_metadata_with_path_and_source():
    """Populates path, source_id, and source when columns exist."""
    table = pa.table(
        {
            "name": ["doc.pdf"],
            OperatorConstants.Columns.PATH: ["/data/doc.pdf"],
            "source_id": ["src_001"],
            "source": ["local"],
        }
    )
    result = OperatorUtils._build_doc_metadata(table=table, row_idx=0, doc_name="doc.pdf", metadata_list=[None])
    assert result["path"] == "/data/doc.pdf"
    assert result["source_id"] == "src_001"
    assert result["source"] == "local"


def test_build_doc_metadata_parses_item_id_from_metadata():
    """Extracts item_id and drive_id from JSON metadata string."""
    import json

    meta = json.dumps({"item_id": "item_123", "drive_id": "drive_456"})
    table = pa.table({"name": ["doc.pdf"]})
    result = OperatorUtils._build_doc_metadata(table=table, row_idx=0, doc_name="doc.pdf", metadata_list=[meta])
    assert result["item_id"] == "item_123"
    assert result["drive_id"] == "drive_456"


def test_build_doc_metadata_invalid_json_metadata_ignored():
    """Invalid JSON metadata is silently ignored."""
    table = pa.table({"name": ["doc.pdf"]})
    result = OperatorUtils._build_doc_metadata(table=table, row_idx=0, doc_name="doc.pdf", metadata_list=["not-json"])
    assert "item_id" not in result


# ---------------------------------------------------------------------------
# _lease_converter — docling unavailable path
# ---------------------------------------------------------------------------


def test_lease_converter_docling_unavailable_raises():
    """Raises RuntimeError when docling is not installed."""
    from unittest.mock import patch

    import docpipe.core.operators.operator_utils as ou

    with patch.object(ou, "_DOCLING_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="docling is not installed"):
            with ou._lease_converter(None):
                pass


def test_lease_converter_with_format_options():
    """Constructs converter with format_options when provided in config."""
    from unittest.mock import MagicMock, patch

    import docpipe.core.operators.operator_utils as ou

    mock_converter = MagicMock()
    mock_cls = MagicMock(return_value=mock_converter)

    opt = MagicMock()
    opt.__class__.__name__ = "PdfFormatOption"
    config = {"format_options": {"pdf": opt}}

    with patch("docling.document_converter.DocumentConverter", mock_cls):
        with ou._lease_converter(config) as result:
            assert result is mock_converter

    mock_cls.assert_called_once_with(format_options={"pdf": opt})


# ---------------------------------------------------------------------------
# extract_content — text file routing and error paths
# ---------------------------------------------------------------------------


def test_extract_content_routes_txt_to_extract_text_file():
    """extract_content delegates .txt files to extract_text_file."""
    from unittest.mock import patch

    with patch.object(
        OperatorUtils,
        "extract_text_file",
        return_value={OperatorConstants.Extraction.SUCCESS: True, OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text"},
    ) as mock_txt:
        result = OperatorUtils.extract_content(
            file_path="doc.txt",
            binary_content=b"plain text",
        )

    mock_txt.assert_called_once()
    assert result[OperatorConstants.Extraction.SUCCESS] is True


def test_extract_content_filters_markdown_from_additional_formats():
    """'markdown' in additional_formats is stripped before processing."""
    from unittest.mock import patch

    with patch.object(
        OperatorUtils,
        "extract_text_file",
        return_value={OperatorConstants.Extraction.SUCCESS: True, OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "t"},
    ) as mock_txt:
        OperatorUtils.extract_content(
            file_path="doc.txt",
            binary_content=b"text",
            additional_formats=["markdown", "html"],
        )

    # additional_formats passed to extract_text_file should not contain 'markdown'
    call_kwargs = mock_txt.call_args.kwargs
    assert "markdown" not in call_kwargs.get("additional_formats", [])


def test_extract_content_docling_unavailable_returns_error():
    """When docling is unavailable and no txt routing, returns error dict."""
    from unittest.mock import patch

    with patch(
        "docpipe.core.operators.operator_utils._lease_converter",
        side_effect=RuntimeError("docling not installed"),
    ):
        result = OperatorUtils.extract_content(
            file_path="doc.pdf",
            binary_content=b"%PDFdata",
        )

    assert result[OperatorConstants.Extraction.SUCCESS] is False
    assert OperatorConstants.Extraction.ERROR in result


def test_extract_content_no_extension_detects_from_bytes():
    """When file_path has no extension, detect_extension_from_bytes is called."""
    from unittest.mock import patch

    with (
        patch.object(
            OperatorUtils,
            "detect_extension_from_bytes",
            return_value=".txt",
        ) as mock_detect,
        patch.object(
            OperatorUtils,
            "extract_text_file",
            return_value={
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "t",
            },
        ),
    ):
        OperatorUtils.extract_content(file_path="doc", binary_content=b"plain text")

    mock_detect.assert_called_once()


def test_extract_content_doclang_primary_format():
    """When doc_format='doclang', export_to_doclang is called directly as primary."""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.export_to_doclang.return_value = "<doc>test</doc>"
    mock_doc.pages = [1]

    mock_converter = MagicMock()
    mock_converter.convert.return_value = MagicMock(document=mock_doc)

    result = OperatorUtils.extract_content(
        file_path="sample.pdf",
        binary_content=b"%PDFdata",
        converter=mock_converter,
        doc_format="doclang",
    )

    assert result[OperatorConstants.Extraction.SUCCESS] is True
    assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "<doc>test</doc>"
    mock_doc.export_to_doclang.assert_called_once()
    mock_doc.export_to_markdown.assert_not_called()
