# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for validation utility functions."""

import pytest

from docpipe.utils.core.validation import (
    _validate_dag_nodes,
    _validate_operator_type_format,
    deduplicate_tags,
    is_date_time_as_per_format,
    is_value_in_range,
    to_bool,
    validate_container_kind,
    validate_database_path,
    validate_flow_definition,
    validate_uuid_format,
)


class TestValidateUuidFormat:
    """Tests for validate_uuid_format function."""

    def test_valid_uuid(self):
        """Test validation passes for valid UUID."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        result = validate_uuid_format(uuid_str, "test_field")
        assert result == uuid_str

    def test_none_value(self):
        """Test None value returns None."""
        result = validate_uuid_format(None, "test_field")
        assert result is None

    def test_invalid_uuid_format(self):
        """Test invalid UUID format raises ValueError."""
        with pytest.raises(ValueError, match="test_field must be a valid UUID format") as exc_info:
            validate_uuid_format("invalid-uuid", "test_field")
        assert "550e8400-e29b-41d4-a716-446655440000" in str(exc_info.value)

    def test_empty_string(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="test_field must be a valid UUID format"):
            validate_uuid_format("", "test_field")

    def test_partial_uuid(self):
        """Test partial UUID raises ValueError."""
        with pytest.raises(ValueError, match="test_field must be a valid UUID format"):
            validate_uuid_format("550e8400-e29b", "test_field")

    def test_uuid_with_extra_characters(self):
        """Test UUID with extra characters raises ValueError."""
        with pytest.raises(ValueError, match="test_field must be a valid UUID format"):
            validate_uuid_format("550e8400-e29b-41d4-a716-446655440000-extra", "test_field")

    def test_different_field_names(self):
        """Test error message includes correct field name."""
        with pytest.raises(ValueError, match="container_id must be a valid UUID format"):
            validate_uuid_format("invalid", "container_id")

        with pytest.raises(ValueError, match="job_id must be a valid UUID format"):
            validate_uuid_format("invalid", "job_id")


class TestValidateContainerKind:
    """Tests for validate_container_kind function."""

    def test_valid_project(self):
        """Test 'project' is valid."""
        result = validate_container_kind("project")
        assert result == "project"

    def test_valid_space(self):
        """Test 'space' is valid."""
        result = validate_container_kind("space")
        assert result == "space"

    def test_none_value(self):
        """Test None value returns None."""
        result = validate_container_kind(None)
        assert result is None

    def test_invalid_value(self):
        """Test invalid container kind raises ValueError."""
        with pytest.raises(ValueError, match="container_kind must be 'project' or 'space'") as exc_info:
            validate_container_kind("invalid")
        assert "got 'invalid'" in str(exc_info.value)

    def test_case_sensitive(self):
        """Test validation is case-sensitive."""
        with pytest.raises(ValueError, match="container_kind must be 'project' or 'space'"):
            validate_container_kind("Project")
        with pytest.raises(ValueError, match="container_kind must be 'project' or 'space'"):
            validate_container_kind("SPACE")

    def test_empty_string(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="container_kind must be 'project' or 'space'"):
            validate_container_kind("")


class TestValidateFlowDefinition:
    """Tests for validate_flow_definition function."""

    # Basic format tests
    def test_none_value(self):
        """Test None value returns None."""
        result = validate_flow_definition(None)
        assert result is None

    def test_invalid_not_dict(self):
        """Test non-dict value raises ValueError."""
        with pytest.raises(ValueError, match="definition must be a dictionary") as exc_info:
            validate_flow_definition("not a dict")
        assert "got str" in str(exc_info.value)

    def test_invalid_list(self):
        """Test list value raises ValueError."""
        with pytest.raises(ValueError, match="definition must be a dictionary") as exc_info:
            validate_flow_definition([])
        assert "got list" in str(exc_info.value)

    def test_empty_dict(self):
        """Test empty dict raises ValueError."""
        with pytest.raises(ValueError, match="definition must contain either 'doc_type'") as exc_info:
            validate_flow_definition({})
        assert "or 'flow_name'" in str(exc_info.value)

    def test_missing_required_keys(self):
        """Test dict without required keys raises ValueError."""
        with pytest.raises(ValueError, match="definition must contain either 'doc_type'"):
            validate_flow_definition({"other_key": "value"})

    # Elyra format tests
    def test_valid_elyra_format_minimal(self):
        """Test valid minimal Elyra format."""
        definition = {"doc_type": "pipeline", "pipelines": [{"id": "pipeline1"}]}
        result = validate_flow_definition(definition)
        assert result == definition

    def test_valid_elyra_format_with_primary(self):
        """Test valid Elyra format with primary_pipeline."""
        definition = {
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [{"id": "pipeline1"}],
            "primary_pipeline": "pipeline1",
        }
        result = validate_flow_definition(definition)
        assert result == definition

    def test_elyra_missing_pipelines(self):
        """Test Elyra format missing pipelines raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'pipelines' key"):
            validate_flow_definition({"doc_type": "pipeline"})

    def test_elyra_pipelines_not_list(self):
        """Test Elyra pipelines not being a list raises ValueError."""
        with pytest.raises(ValueError, match="pipelines must be a list"):
            validate_flow_definition({"doc_type": "pipeline", "pipelines": "not a list"})

    def test_elyra_empty_pipelines(self):
        """Test Elyra empty pipelines raises ValueError."""
        with pytest.raises(ValueError, match="pipelines list cannot be empty"):
            validate_flow_definition({"doc_type": "pipeline", "pipelines": []})

    def test_elyra_invalid_primary_pipeline(self):
        """Test Elyra invalid primary_pipeline raises ValueError."""
        with pytest.raises(ValueError, match="primary_pipeline must be a non-empty string"):
            validate_flow_definition(
                {
                    "doc_type": "pipeline",
                    "pipelines": [{"id": "pipeline1"}],
                    "primary_pipeline": "",
                }
            )


class TestDeduplicateTags:
    """Tests for deduplicate_tags function."""

    def test_no_duplicates(self):
        """Test list with no duplicates remains unchanged."""
        tags = ["tag1", "tag2", "tag3"]
        result = deduplicate_tags(tags)
        assert result == tags

    def test_with_duplicates(self):
        """Test duplicates are removed while preserving order."""
        tags = ["tag1", "tag2", "tag1", "tag3", "tag2"]
        result = deduplicate_tags(tags)
        assert result == ["tag1", "tag2", "tag3"]

    def test_empty_list(self):
        """Test empty list returns empty list."""
        result = deduplicate_tags([])
        assert result == []

    def test_single_tag(self):
        """Test single tag list."""
        result = deduplicate_tags(["tag1"])
        assert result == ["tag1"]

    def test_all_duplicates(self):
        """Test list with all duplicates."""
        tags = ["tag1", "tag1", "tag1"]
        result = deduplicate_tags(tags)
        assert result == ["tag1"]

    def test_none_with_allow_none_false(self):
        """Test None returns empty list when allow_none=False."""
        result = deduplicate_tags(None, allow_none=False)
        assert result == []

    def test_none_with_allow_none_true(self):
        """Test None returns None when allow_none=True."""
        result = deduplicate_tags(None, allow_none=True)
        assert result is None

    def test_invalid_not_list(self):
        """Test non-list value raises ValueError."""
        with pytest.raises(ValueError, match="tags must be a list") as exc_info:
            deduplicate_tags("not a list")
        assert "got str" in str(exc_info.value)

    def test_invalid_dict(self):
        """Test dict value raises ValueError."""
        with pytest.raises(ValueError, match="tags must be a list") as exc_info:
            deduplicate_tags({"key": "value"})
        assert "got dict" in str(exc_info.value)

    def test_non_string_element(self):
        """Test list with non-string element raises ValueError."""
        with pytest.raises(ValueError, match="all tags must be strings") as exc_info:
            deduplicate_tags(["tag1", 123, "tag2"])
        assert "got int" in str(exc_info.value)

    def test_mixed_non_string_elements(self):
        """Test list with various non-string elements raises ValueError."""
        with pytest.raises(ValueError, match="all tags must be strings"):
            deduplicate_tags(["tag1", None])

        with pytest.raises(ValueError, match="all tags must be strings"):
            deduplicate_tags(["tag1", ["nested"]])

    def test_preserves_order(self):
        """Test that order is preserved when deduplicating."""
        tags = ["z", "a", "m", "a", "z", "b"]
        result = deduplicate_tags(tags)
        assert result == ["z", "a", "m", "b"]

    def test_case_sensitive(self):
        """Test deduplication is case-sensitive."""
        tags = ["Tag", "tag", "TAG"]
        result = deduplicate_tags(tags)
        assert result == ["Tag", "tag", "TAG"]

    def test_whitespace_preserved(self):
        """Test tags with whitespace are treated as distinct."""
        tags = ["tag", " tag", "tag ", " tag "]
        result = deduplicate_tags(tags)
        assert result == ["tag", " tag", "tag ", " tag "]


class TestToBool:
    def test_true_bool(self):
        assert to_bool(True) is True

    def test_false_bool(self):
        assert to_bool(False) is False

    def test_string_true(self):
        assert to_bool("true") is True

    def test_string_true_case_insensitive(self):
        assert to_bool("  TRUE  ") is True

    def test_string_false_returns_false(self):
        assert to_bool("false") is False

    def test_non_bool_returns_false(self):
        assert to_bool(1) is False
        assert to_bool(None) is False
        assert to_bool("1") is False


class TestIsValueInRange:
    def test_within_range(self):
        assert is_value_in_range(value=5, min_value=1, max_value=10) is True

    def test_at_boundaries(self):
        assert is_value_in_range(value=1, min_value=1, max_value=10) is True
        assert is_value_in_range(value=10, min_value=1, max_value=10) is True

    def test_out_of_range(self):
        assert is_value_in_range(value=0, min_value=1, max_value=10) is False
        assert is_value_in_range(value=11, min_value=1, max_value=10) is False


class TestIsDateTimeAsPerFormat:
    def test_valid_date(self):
        assert is_date_time_as_per_format("2024-01-15", "%Y-%m-%d") is True

    def test_invalid_date(self):
        assert is_date_time_as_per_format("not-a-date", "%Y-%m-%d") is False

    def test_wrong_format(self):
        assert is_date_time_as_per_format("15-01-2024", "%Y-%m-%d") is False


class TestValidateOperatorTypeFormat:
    def test_valid_simple_name(self):
        _validate_operator_type_format("ingest_source")  # no raise

    def test_valid_dotted_path(self):
        _validate_operator_type_format("core.operators.MyOp")  # no raise

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_operator_type_format("")

    def test_leading_dot_raises(self):
        with pytest.raises(ValueError, match="invalid identifier"):
            _validate_operator_type_format(".bad")

    def test_digit_start_raises(self):
        with pytest.raises(ValueError, match="invalid identifier"):
            _validate_operator_type_format("valid.1bad")


class TestValidateDagNodes:
    def test_valid_nodes(self):
        _validate_dag_nodes([{"id": "n1", "operator": "ingest_source"}])  # no raise

    def test_not_a_list_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            _validate_dag_nodes({"id": "x"})

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_dag_nodes([])

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing required field 'id'"):
            _validate_dag_nodes([{"operator": "ingest_source"}])

    def test_duplicate_ids_raises(self):
        nodes = [{"id": "n1", "operator": "a"}, {"id": "n1", "operator": "b"}]
        with pytest.raises(ValueError, match="duplicate node id"):
            _validate_dag_nodes(nodes)

    def test_missing_operator_raises(self):
        with pytest.raises(ValueError, match="missing required field 'operator'"):
            _validate_dag_nodes([{"id": "n1"}])

    def test_invalid_params_type_raises(self):
        with pytest.raises(ValueError, match="invalid 'operator_params'"):
            _validate_dag_nodes([{"id": "n1", "operator": "op", "config": "bad"}])


class TestValidateFlowDefinitionExtraCases:
    def test_authoring_empty_flow_name_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            validate_flow_definition({"flow_name": "  ", "flow": []})

    def test_authoring_missing_flow_key_raises(self):
        with pytest.raises(ValueError, match="must contain 'flow' key"):
            validate_flow_definition({"flow_name": "My Flow"})

    def test_authoring_empty_flow_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_flow_definition({"flow_name": "My Flow", "flow": []})

    def test_authoring_operator_missing_key_raises(self):
        with pytest.raises(ValueError, match="missing required field"):
            validate_flow_definition({"flow_name": "My Flow", "flow": [{"type": "ingest", "name": "n"}]})


class TestValidateDatabasePath:
    def test_in_memory(self):
        assert validate_database_path(":memory:") == ":memory:"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_database_path("")

    def test_traversal_raises(self):
        with pytest.raises(ValueError, match="Path traversal"):
            validate_database_path("../../etc/passwd")

    def test_absolute_path_returned(self, tmp_path):
        p = str(tmp_path / "test.db")
        assert validate_database_path(p) == p

    def test_base_dir_outside_raises(self, tmp_path):
        other = str(tmp_path.parent / "other.db")
        with pytest.raises(ValueError, match="must be within"):
            validate_database_path(other, base_dir=str(tmp_path))

    def test_base_dir_within_allowed(self, tmp_path):
        direct = tmp_path / "test.db"
        nested = tmp_path / "subdir" / "test.db"
        assert validate_database_path(str(direct), base_dir=str(tmp_path)) == str(direct.resolve())
        assert validate_database_path(str(nested), base_dir=str(tmp_path)) == str(nested.resolve())

    def test_base_dir_shared_prefix_outside_raises(self, tmp_path):
        sibling = tmp_path.parent / f"{tmp_path.name}_evil" / "test.db"
        with pytest.raises(ValueError, match="must be within"):
            validate_database_path(str(sibling), base_dir=str(tmp_path))
