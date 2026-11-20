# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for DAG, flow-definition and database-path validation in docpipe.utils.core.validation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe.utils.core.validation import (
    _validate_dag_nodes,
    validate_database_path,
    validate_flow_definition,
)


class TestValidateDagNodeFields:
    """Tests for per-node checks in _validate_dag_nodes."""

    @pytest.mark.parametrize("node", ["n1", ["n1"], None])
    def test_non_dict_node_raises(self, node):
        """Every node must be a dictionary; the error names the index and actual type."""
        with pytest.raises(ValueError, match=rf"node at index 1 must be a dictionary, got {type(node).__name__}"):
            _validate_dag_nodes([{"id": "ok", "operator": "op"}, node])

    @pytest.mark.parametrize("node_id", ["", 5, None])
    def test_invalid_node_id_raises(self, node_id):
        """Node ids must be non-empty strings."""
        with pytest.raises(ValueError, match="invalid 'id': must be a non-empty string"):
            _validate_dag_nodes([{"id": node_id, "operator": "op"}])

    def test_operator_type_alias_and_dict_params_are_accepted(self):
        """'operator_type' is accepted instead of 'operator' and dict params pass."""
        _validate_dag_nodes([{"id": "n1", "operator_type": "core.ops.Ingest", "operator_params": {"a": 1}}])


class TestValidateFlowDefinitionAuthoring:
    """Tests for authoring-format validation via validate_flow_definition."""

    def test_valid_definition_is_returned_unchanged(self):
        """A structurally valid authoring definition is returned as the same object."""
        definition = {
            "flow_name": "My Flow",
            "flow": [
                {"type": "ingest_source", "name": "a", "config": {}},
                {"type": "chunker", "name": "b", "config": {}, "depends_on": ["a"]},
            ],
        }
        assert validate_flow_definition(definition) is definition

    def test_doc_type_with_flow_name_uses_authoring_rules(self):
        """When both keys are present, the authoring format takes precedence."""
        with pytest.raises(ValueError, match="must contain 'flow' key"):
            validate_flow_definition({"flow_name": "F", "doc_type": "pipeline", "pipelines": [{}]})

    @pytest.mark.parametrize("flow", [{"type": "x"}, "ingest", 3])
    def test_flow_must_be_a_list(self, flow):
        """The 'flow' value must be a list."""
        with pytest.raises(ValueError, match=rf"flow must be a list, got {type(flow).__name__}"):
            validate_flow_definition({"flow_name": "F", "flow": flow})

    def test_flow_operator_must_be_a_dict(self):
        """Each flow operator entry must be a dictionary."""
        with pytest.raises(ValueError, match="flow operator at index 1 must be a dictionary, got str"):
            validate_flow_definition({"flow_name": "F", "flow": [{"type": "t", "name": "n", "config": {}}, "op"]})

    def test_missing_flow_name_message(self):
        """The authoring validator explains the required 'flow_name' key."""
        from docpipe.utils.core.validation import _validate_authoring_format

        with pytest.raises(ValueError, match="must contain 'flow_name' key"):
            _validate_authoring_format({"flow": []})


class TestValidateDatabasePathErrors:
    """Tests for error handling and base-dir checks in validate_database_path."""

    def test_path_inside_base_dir_is_accepted(self, tmp_path):
        """A path inside base_dir is resolved and returned."""
        target = tmp_path / "db" / "docs.duckdb"
        assert validate_database_path(str(target), base_dir=str(tmp_path)) == str(target.resolve())

    def test_unresolvable_path_raises_value_error(self, tmp_path):
        """OS errors while resolving the path are reported as ValueError."""
        with (
            patch.object(Path, "resolve", side_effect=OSError("boom")),
            pytest.raises(ValueError, match="Invalid database path: boom"),
        ):
            validate_database_path(str(tmp_path / "docs.db"))

    def test_unresolvable_base_dir_raises_value_error(self, tmp_path):
        """OS errors while resolving base_dir are reported as ValueError."""
        real_resolve = Path.resolve
        target = tmp_path / "docs.db"

        def _resolve(self, *args, **kwargs):
            if self == tmp_path:
                raise RuntimeError("loop")
            return real_resolve(self, *args, **kwargs)

        with (
            patch.object(Path, "resolve", _resolve),
            pytest.raises(ValueError, match="Invalid base directory: loop"),
        ):
            validate_database_path(str(target), base_dir=str(tmp_path))
