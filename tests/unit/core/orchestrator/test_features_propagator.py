"""Unit tests for FeaturePropagator."""

from typing import ClassVar
from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.feature_propagation.features_propagator import FeaturePropagator
from docpipe.core.orchestration.feature_propagation.models import (
    FeaturePropagationResult,
)
from docpipe.exceptions.docpipe_exceptions import FlowValidationException

# ---------------------------------------------------------------------------
# Module-level helpers — shared across all test classes
# ---------------------------------------------------------------------------


def _make_feature_def(
    description: str = "",
    tags: list[str] | None = None,
    available_for_filter: bool = False,
    available_for_vector_db: bool = False,
    type_: str = "string",
) -> dict:
    """Return a minimal feature definition dict as used in input_features."""
    return {
        "description": description,
        "tags": tags if tags is not None else [],
        "available_for_filter": available_for_filter,
        "available_for_vector_db": available_for_vector_db,
        "type": type_,
    }


def _make_parent_result(
    features: dict[str, dict],
    source_node_id: str = "parent-node",
) -> FeaturePropagationResult:
    """Build a FeaturePropagationResult from {feature_name: feature_def_dict}."""
    result = FeaturePropagationResult()
    result.source_node_id = source_node_id
    for name, fdef in features.items():
        result.add_feature(
            feature_name=name,
            node_id=source_node_id,
            description=fdef.get("description", ""),
            tags=fdef.get("tags", []),
            available_for_filter=fdef.get("available_for_filter", False),
            available_for_vector_db=fdef.get("available_for_vector_db", False),
            type=fdef.get("type", "string"),
        )
    return result


class TestFeaturePropagator:
    """Tests for FeaturePropagator class."""

    @pytest.fixture
    def propagator(self):
        """Create FeaturePropagator instance."""
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    def test_init_loads_operator_metadata(self):
        """Test that __init__ loads operator metadata."""
        propagator = FeaturePropagator()

        # Verify operator_metadata is initialized
        assert propagator.operator_metadata is not None
        assert hasattr(propagator.operator_metadata, "get_operator_metadata")
        assert hasattr(propagator.operator_metadata, "get_features")

    def test_propagate_features_preserves_input_features(self, propagator):
        """Test that input features are preserved in output."""
        input_features = {
            "id": _make_feature_def(description="Document ID", tags=["mandatory"]),
            "content": _make_feature_def(
                description="Document content", tags=["mandatory"], available_for_filter=False
            ),
        }

        result = propagator.propagate_features(
            node_id="test-node",
            operator_short_name="test_operator",
            operator_config={},
            input_features=input_features,
            global_config={},
            parent_results=[],
        )

        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata
        assert result.feature_metadata["id"].description == "Document ID"

    def test_propagate_features_adds_operator_features(self, propagator):
        """Test that operator-defined features are added."""
        propagator.operator_metadata.get_features = Mock(
            return_value={"new_feature": _make_feature_def(description="New feature from operator", tags=["operator"])}
        )

        result = propagator.propagate_features(
            node_id="test-node",
            operator_short_name="test_operator",
            operator_config={},
            input_features={"id": _make_feature_def()},
            global_config={},
            parent_results=[],
        )

        assert "new_feature" in result.feature_metadata
        assert result.feature_metadata["new_feature"].description == "New feature from operator"

    def test_propagate_features_stores_input_features_explicitly(self, propagator):
        """Test that input features are stored separately for inspection."""
        result = propagator.propagate_features(
            node_id="test-node",
            operator_short_name="test_operator",
            operator_config={},
            input_features={"id": _make_feature_def(), "content": _make_feature_def(available_for_filter=False)},
            global_config={},
            parent_results=[],
        )

        stored_input = result.get_input_features(node_id="test-node")
        assert "id" in stored_input
        assert "content" in stored_input

    def test_propagate_features_computes_output_features(self, propagator):
        """Test that output features (new features only) are computed."""
        propagator.operator_metadata.get_features = Mock(
            return_value={"new_feature": _make_feature_def(description="New")}
        )

        result = propagator.propagate_features(
            node_id="test-node",
            operator_short_name="test_operator",
            operator_config={},
            input_features={"id": _make_feature_def()},
            global_config={},
            parent_results=[],
        )

        output = result.get_output_features(node_id="test-node")
        assert "new_feature" in output
        assert "id" not in output  # Input feature should not be in output

    def test_propagate_features_vectordb_produces_no_output(self, propagator):
        """Test that VectorDB operator produces no output features."""
        result = propagator.propagate_features(
            node_id="vectordb-node",
            operator_short_name=OperatorConstants.Operators.VECTORDB,
            operator_config={},
            input_features={
                "id": _make_feature_def(),
                "embeddings": _make_feature_def(available_for_filter=False, available_for_vector_db=True, type_="list"),
            },
            global_config={},
            parent_results=[],
        )

        assert len(result.get_output_features(node_id="vectordb-node")) == 0


class TestExtractOperatorSpecialCase:
    """Tests for Extract operator special case handling."""

    @pytest.fixture
    def propagator(self):
        """Create FeaturePropagator instance."""
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(
                return_value={
                    "text": _make_feature_def(description="Extracted text", available_for_filter=False),
                    "entities": _make_feature_def(
                        description="Entities", tags=["entity"], available_for_filter=False, type_="list"
                    ),
                    OperatorConstants.Columns.DOCUMENT_TYPE: _make_feature_def(description="Doc type", tags=["entity"]),
                }
            )
            return prop

    _BASE_FEATURES: ClassVar[dict] = {
        "id": _make_feature_def(),
        "content": _make_feature_def(available_for_filter=False),
    }

    def test_extract_with_entity_mode_none_removes_entity_features(self, propagator):
        """entity_extraction_mode=none removes entity features; text survives."""
        result = propagator.propagate_features(
            node_id="extract-node",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={OperatorConstants.Config.PROVIDER: OperatorConstants.ExtractionModes.ENTITY_MODE_NONE},
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "entities" not in result.feature_metadata
        assert OperatorConstants.Columns.DOCUMENT_TYPE not in result.feature_metadata
        assert "text" in result.feature_metadata

    def test_extract_with_entity_mode_ollama_adds_entity_features(self, propagator):
        """entity_extraction.provider=litellm adds entities and document_type."""
        result = propagator.propagate_features(
            node_id="extract-node",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={
                OperatorConstants.Config.ENTITY_EXTRACTION: {OperatorConstants.Config.PROVIDER: "litellm"}
            },
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "entities" in result.feature_metadata
        assert OperatorConstants.Columns.DOCUMENT_TYPE in result.feature_metadata


class TestSQLFilterSpecialCase:
    """Tests for SQLFilter operator special case handling.

    SQLFilter filters rows only — it never modifies the column schema.
    Feature propagation mirrors this: all input features pass through unchanged
    unless the operator config contains an explicit features_to_drop list.
    """

    @pytest.fixture
    def propagator(self):
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    _THREE_FEATURES: ClassVar[dict] = {
        "id": _make_feature_def(tags=["mandatory"]),
        "content": _make_feature_def(available_for_filter=False),
        "metadata": _make_feature_def(),
    }

    def test_sql_filter_passes_all_features_through(self, propagator):
        """sql_filter passes every input feature downstream unchanged (no SELECT pruning)."""
        result = propagator.propagate_features(
            node_id="filter-node",
            operator_short_name=OperatorConstants.Operators.SQL_FILTER,
            operator_config={"sql_query": "SELECT id, content FROM table WHERE lang='en'"},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        # All three features survive — the SELECT clause is irrelevant for propagation
        assert {"id", "content", "metadata"} <= result.feature_metadata.keys()

    def test_sql_filter_with_no_config_keeps_all_features(self, propagator):
        """sql_filter with no features_to_drop config keeps everything."""
        result = propagator.propagate_features(
            node_id="filter-node",
            operator_short_name=OperatorConstants.Operators.SQL_FILTER,
            operator_config={},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert {"id", "content", "metadata"} <= result.feature_metadata.keys()

    def test_sql_filter_explicit_features_to_drop_removes_feature(self, propagator):
        """Explicit features_to_drop list in operator config drops the named features."""
        result = propagator.propagate_features(
            node_id="filter-node",
            operator_short_name=OperatorConstants.Operators.SQL_FILTER,
            operator_config={"features_to_drop": ["metadata"]},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata
        assert "metadata" not in result.feature_metadata

    def test_sql_filter_explicit_features_to_drop_is_tracked(self, propagator):
        """Features dropped via features_to_drop are recorded in output_features_to_drop."""
        result = propagator.propagate_features(
            node_id="filter-node",
            operator_short_name=OperatorConstants.Operators.SQL_FILTER,
            operator_config={"features_to_drop": ["metadata"]},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "metadata" in result.get_output_features_to_drop(node_id="filter-node").get_features_to_drop()

    def test_sql_filter_cannot_drop_mandatory_features(self, propagator):
        """SQLFilter raises FlowValidationException when features_to_drop targets a mandatory feature."""
        with pytest.raises(FlowValidationException) as exc_info:
            propagator.propagate_features(
                node_id="filter-node",
                operator_short_name=OperatorConstants.Operators.SQL_FILTER,
                operator_config={"features_to_drop": ["content"]},
                input_features={
                    "id": _make_feature_def(tags=["mandatory"]),
                    "content": _make_feature_def(tags=["mandatory"], available_for_filter=False),
                },
                global_config={},
                parent_results=[],
            )

        errors = exc_info.value.errors or []
        assert len(errors) > 0
        assert "mandatory" in str(errors[0]).lower()


class TestOutputFeaturesToDrop:
    """output_features_to_drop is a generic config key — works on any operator.

    Distinct from features_to_drop (sql_filter-specific). Applied after special-case
    logic at the end of every propagation step, for every operator type.
    """

    @pytest.fixture
    def propagator(self):
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    _THREE_FEATURES: ClassVar[dict] = {
        "id": _make_feature_def(tags=["mandatory"]),
        "content": _make_feature_def(),
        "metadata": _make_feature_def(),
    }

    def test_removes_feature_on_any_operator(self, propagator):
        """output_features_to_drop drops a feature on a generic operator (lang_detect)."""
        result = propagator.propagate_features(
            node_id="lang-node",
            operator_short_name="lang_detect",
            operator_config={"output_features_to_drop": ["metadata"]},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "metadata" not in result.feature_metadata
        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata

    def test_dropped_features_are_tracked(self, propagator):
        """Features dropped via output_features_to_drop are recorded in output_features_to_drop."""
        result = propagator.propagate_features(
            node_id="lang-node",
            operator_short_name="lang_detect",
            operator_config={"output_features_to_drop": ["metadata"]},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "metadata" in result.get_output_features_to_drop(node_id="lang-node").get_features_to_drop()

    def test_cannot_drop_mandatory_features(self, propagator):
        """output_features_to_drop raises FlowValidationException on mandatory features."""
        with pytest.raises(FlowValidationException) as exc_info:
            propagator.propagate_features(
                node_id="lang-node",
                operator_short_name="lang_detect",
                operator_config={"output_features_to_drop": ["id"]},
                input_features=self._THREE_FEATURES,
                global_config={},
                parent_results=[],
            )

        errors = exc_info.value.errors or []
        assert len(errors) > 0
        assert "mandatory" in str(errors[0]).lower()

    def test_works_on_sql_filter(self, propagator):
        """output_features_to_drop is distinct from features_to_drop and also works on sql_filter."""
        result = propagator.propagate_features(
            node_id="filter-node",
            operator_short_name=OperatorConstants.Operators.SQL_FILTER,
            operator_config={"output_features_to_drop": ["metadata"]},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert "metadata" not in result.feature_metadata
        assert "metadata" in result.get_output_features_to_drop(node_id="filter-node").get_features_to_drop()

    def test_empty_list_is_noop(self, propagator):
        """output_features_to_drop: [] leaves all features intact."""
        result = propagator.propagate_features(
            node_id="lang-node",
            operator_short_name="lang_detect",
            operator_config={"output_features_to_drop": []},
            input_features=self._THREE_FEATURES,
            global_config={},
            parent_results=[],
        )

        assert {"id", "content", "metadata"} <= result.feature_metadata.keys()


class TestMergeOperatorSpecialCase:
    """Tests for Merge operator special case handling."""

    @pytest.fixture
    def propagator(self):
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    def test_merge_rows_combines_all_features(self, propagator):
        """ROWS merge produces the union of all parent features."""
        p1 = _make_parent_result({"id": _make_feature_def(), "content": _make_feature_def(available_for_filter=False)})
        p2 = _make_parent_result({"id": _make_feature_def(), "metadata": _make_feature_def()})

        result = propagator.propagate_features(
            node_id="merge-node",
            operator_short_name=OperatorConstants.Operators.MERGE,
            operator_config={OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.ROWS},
            input_features={},
            global_config={},
            parent_results=[p1, p2],
        )

        assert {"id", "content", "metadata"} <= result.feature_metadata.keys()

    def test_merge_columns_inner_join_keeps_common_features(self, propagator):
        """COLUMNS + INNER_JOIN retains only features present in all parents.

        Common features appear as plain key (first occurrence) plus a suffixed copy
        for the second branch.  Features unique to one parent are dropped entirely.
        """
        p1 = _make_parent_result(
            {"id": _make_feature_def(), "content": _make_feature_def(), "title": _make_feature_def()},
            source_node_id="node-a",
        )
        p2 = _make_parent_result(
            {"id": _make_feature_def(), "content": _make_feature_def(), "author": _make_feature_def()},
            source_node_id="node-b",
        )

        result = propagator.propagate_features(
            node_id="merge-node",
            operator_short_name=OperatorConstants.Operators.MERGE,
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.COLUMNS,
                OperatorConstants.Merge.COLUMN_OPTION: OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
                OperatorConstants.Merge.INPUT_LINKS: [
                    {"node_id_ref": "node-a", OperatorConstants.Misc.LINK_NAME: "Link_5"},
                    {"node_id_ref": "node-b", OperatorConstants.Misc.LINK_NAME: "Link_6"},
                ],
            },
            input_features={},
            global_config={},
            parent_results=[p1, p2],
        )

        # id is never suffixed; first occurrence of common feature plain, second suffixed
        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata  # first occurrence: plain key
        assert "content_Link_6" in result.feature_metadata  # second occurrence: suffixed
        # features unique to one branch are excluded entirely
        assert "title" not in result.feature_metadata
        assert "author" not in result.feature_metadata

    def test_merge_columns_full_outer_join_disambiguates_duplicates(self, propagator):
        """COLUMNS + FULL_OUTER_JOIN: first occurrence plain, 2nd+ suffixed with link name."""
        p1 = _make_parent_result({"id": _make_feature_def(), "content": _make_feature_def()}, source_node_id="node-a")
        p2 = _make_parent_result({"id": _make_feature_def(), "content": _make_feature_def()}, source_node_id="node-b")

        result = propagator.propagate_features(
            node_id="merge-node",
            operator_short_name=OperatorConstants.Operators.MERGE,
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.COLUMNS,
                OperatorConstants.Merge.COLUMN_OPTION: OperatorConstants.Merge.FULL_OUTER_JOIN,
                OperatorConstants.Merge.INPUT_LINKS: [
                    {"node_id_ref": "node-a", OperatorConstants.Misc.LINK_NAME: "Link_5"},
                    {"node_id_ref": "node-b", OperatorConstants.Misc.LINK_NAME: "Link_6"},
                ],
            },
            input_features={},
            global_config={},
            parent_results=[p1, p2],
        )

        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata  # first occurrence: plain key
        assert "content_Link_6" in result.feature_metadata  # second occurrence: suffixed
        assert "content_Link_5" not in result.feature_metadata  # first is never suffixed

    def test_merge_with_output_features_to_drop_config(self, propagator):
        """output_features_to_drop (generic key) removes named features after merging."""
        p1 = _make_parent_result(
            {"id": _make_feature_def(), "content": _make_feature_def(), "metadata": _make_feature_def()}
        )

        result = propagator.propagate_features(
            node_id="merge-node",
            operator_short_name=OperatorConstants.Operators.MERGE,
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.ROWS,
                "output_features_to_drop": ["metadata"],
            },
            input_features={},
            global_config={},
            parent_results=[p1],
        )

        assert "id" in result.feature_metadata
        assert "content" in result.feature_metadata
        assert "metadata" not in result.feature_metadata


class TestGlobalParameterPropagation:
    """Tests for global parameter propagation."""

    @pytest.fixture
    def propagator(self):
        """Create FeaturePropagator instance."""
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    def test_embeddings_operator_propagates_model_id(self, propagator):
        """Test that Embeddings operator propagates model_id as global parameter."""
        result = propagator.propagate_features(
            node_id="embeddings-node",
            operator_short_name=OperatorConstants.Operators.EMBEDDINGS,
            operator_config={OperatorConstants.Config.MODEL_ID: "nomic-embed-text"},
            input_features={},
            global_config={},
            parent_results=[],
        )

        assert OperatorConstants.Config.EMBEDDINGS_MODEL_ID in result.global_params
        assert result.global_params[OperatorConstants.Config.EMBEDDINGS_MODEL_ID] == "nomic-embed-text"


class TestMergeFeaturesMethod:
    """Tests for merge_features method."""

    @pytest.fixture
    def propagator(self):
        """Create FeaturePropagator instance."""
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            return FeaturePropagator()

    def test_merge_features_empty_parents_returns_empty(self, propagator):
        """Test that empty parent_results returns empty dict."""
        result = propagator.merge_features(
            parent_results=[], merge_type=OperatorConstants.Merge.ROWS, column_option=None
        )

        assert result == {}

    def test_merge_features_rows_type(self, propagator):
        """Test ROWS merge type combines all features."""
        parent1 = FeaturePropagationResult()
        parent1.add_feature(
            feature_name="feat1",
            node_id="p1",
            description="F1",
            tags=[],
            available_for_filter=True,
            available_for_vector_db=False,
            type="string",
        )

        parent2 = FeaturePropagationResult()
        parent2.add_feature(
            feature_name="feat2",
            node_id="p2",
            description="F2",
            tags=[],
            available_for_filter=True,
            available_for_vector_db=False,
            type="string",
        )

        result = propagator.merge_features(
            parent_results=[parent1, parent2], merge_type=OperatorConstants.Merge.ROWS, column_option=None
        )

        assert "feat1" in result
        assert "feat2" in result


class TestExtractOperatorEntityMode:
    """Tests for the P3 fix: entity mode detection reads entity_extraction.provider."""

    @pytest.fixture
    def propagator(self):
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(return_value={})
            return prop

    # Class-level constant — avoids re-constructing the same dict in every test
    _BASE_FEATURES: ClassVar[dict] = {
        "id": _make_feature_def(tags=["mandatory"]),
        "content": _make_feature_def(tags=["mandatory"], available_for_filter=False),
    }

    def test_entity_features_added_when_provider_nested(self, propagator):
        """entity_extraction.provider=litellm → entities and document_type added."""
        result = propagator.propagate_features(
            node_id="extract-1",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={"entity_extraction": {"provider": "litellm"}},
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )
        assert "entities" in result.feature_metadata
        assert OperatorConstants.Columns.DOCUMENT_TYPE in result.feature_metadata

    def test_entity_features_absent_when_no_entity_extraction_key(self, propagator):
        """Missing entity_extraction key → provider defaults to 'none' → no entity features."""
        result = propagator.propagate_features(
            node_id="extract-1",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={},
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )
        assert "entities" not in result.feature_metadata
        assert OperatorConstants.Columns.DOCUMENT_TYPE not in result.feature_metadata

    def test_entity_features_absent_when_provider_is_none_string(self, propagator):
        """entity_extraction.provider='none' → no entity features."""
        result = propagator.propagate_features(
            node_id="extract-1",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={"entity_extraction": {"provider": "none"}},
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )
        assert "entities" not in result.feature_metadata

    def test_top_level_provider_key_no_longer_triggers_entity_mode(self, propagator):
        """Old (buggy) top-level 'provider' key is ignored — no entity features produced."""
        result = propagator.propagate_features(
            node_id="extract-1",
            operator_short_name=OperatorConstants.Operators.EXTRACT_OPERATOR,
            operator_config={"provider": "litellm"},  # wrong key — should be nested
            input_features=self._BASE_FEATURES,
            global_config={},
            parent_results=[],
        )
        assert "entities" not in result.feature_metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestEmbeddingsQuantizationSpecialCase:
    """Embeddings feature is typed vector_binary only when quantization packs bits."""

    @pytest.fixture
    def propagator(self):
        """Create FeaturePropagator whose embeddings operator exposes a float `vector` feature."""
        with patch.object(FeaturePropagator, "__init__", lambda x: None):
            prop = FeaturePropagator()
            prop.operator_metadata = Mock()
            prop.operator_metadata.get_features = Mock(
                return_value={
                    OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT: _make_feature_def(
                        description="Embeddings",
                        available_for_vector_db=True,
                        type_=OperatorConstants.Types.TYPE_VECTOR,
                    ),
                }
            )
            return prop

    def _propagate(self, propagator, operator_config: dict):
        return propagator.propagate_features(
            node_id="embed-node",
            operator_short_name=OperatorConstants.Operators.EMBEDDINGS,
            operator_config=operator_config,
            input_features={"content": _make_feature_def()},
            global_config={},
            parent_results=[],
        )

    @pytest.mark.parametrize("quantization", ["binary", "ubinary", "BINARY"])
    def test_binary_quantization_types_embeddings_as_vector_binary(self, propagator, quantization):
        result = self._propagate(propagator, {OperatorConstants.Config.QUANTIZATION: quantization})
        feature = result.feature_metadata[OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT]
        assert feature.type == OperatorConstants.Types.TYPE_VECTOR_BINARY

    @pytest.mark.parametrize("config", [{}, {OperatorConstants.Config.QUANTIZATION: "none"}])
    def test_no_quantization_keeps_dense_vector_type(self, propagator, config):
        result = self._propagate(propagator, config)
        feature = result.feature_metadata[OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT]
        assert feature.type == OperatorConstants.Types.TYPE_VECTOR

    def test_downstream_node_declaring_plain_vector_keeps_upstream_binary_type(self, propagator):
        """A consumer (e.g. vectordb) declaring `vector` must not erase an upstream `vector_binary`."""
        input_features = {
            OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT: _make_feature_def(
                description="Embeddings",
                available_for_vector_db=True,
                type_=OperatorConstants.Types.TYPE_VECTOR_BINARY,
            ),
        }
        result = propagator.propagate_features(
            node_id="vectordb-node",
            operator_short_name=OperatorConstants.Operators.VECTORDB,
            operator_config={},
            input_features=input_features,
            global_config={},
            parent_results=[],
        )
        feature = result.feature_metadata[OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT]
        assert feature.type == OperatorConstants.Types.TYPE_VECTOR_BINARY

    def test_downstream_node_declaring_plain_vector_keeps_dense_type(self, propagator):
        input_features = {
            OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT: _make_feature_def(
                description="Embeddings",
                available_for_vector_db=True,
                type_=OperatorConstants.Types.TYPE_VECTOR,
            ),
        }
        result = propagator.propagate_features(
            node_id="vectordb-node",
            operator_short_name=OperatorConstants.Operators.VECTORDB,
            operator_config={},
            input_features=input_features,
            global_config={},
            parent_results=[],
        )
        feature = result.feature_metadata[OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT]
        assert feature.type == OperatorConstants.Types.TYPE_VECTOR
