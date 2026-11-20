# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for operator-owned feature propagation hooks and the shared drop helper."""

from typing import Any, ClassVar
from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.extract.extract_operator import ExtractOperator
from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator
from docpipe.core.operators.functional.merge import MergeOperator
from docpipe.core.operators.quality.sql_filter import SQLFilterOperator
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.core.orchestration.feature_propagation.features_propagator import FeaturePropagator
from docpipe.core.orchestration.feature_propagation.models import FeaturePropagationResult
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
from docpipe.core.orchestration.operator_loader.untrusted_descriptor import build_untrusted_descriptor
from docpipe.exceptions.docpipe_exceptions import FlowValidationException


def _result(*, node_id: str = "n", features: dict[str, dict[str, Any]] | None = None) -> FeaturePropagationResult:
    result = FeaturePropagationResult()
    for name, kwargs in (features or {}).items():
        result.add_feature(feature_name=name, node_id=node_id, **kwargs)
    return result


def _propagator_with_classes(
    *, classes: dict[str, type[AbstractOperator]], features: dict[str, Any]
) -> FeaturePropagator:
    with patch.object(FeaturePropagator, "__init__", lambda x: None):
        prop = FeaturePropagator()
    prop.operator_metadata = Mock()
    prop.operator_metadata.get_operator_class = lambda *, short_name: classes.get(short_name)
    prop.operator_metadata.get_features = lambda *, short_name, purpose=None: features if short_name in classes else {}
    return prop


class TestDefaultHooks:
    """AbstractOperator hooks are inert so operators and custom operators need no change."""

    def test_propagate_features_default_leaves_result_untouched(self):
        result = _result(features={"a": {}})

        AbstractOperator.propagate_features(operator_config={"x": 1}, result=result, node_id="n", parent_results=[])

        assert list(result.feature_metadata) == ["a"]
        assert result.output_features_to_drop == {}

    def test_get_global_params_default_is_empty(self):
        assert AbstractOperator.get_global_params(operator_config={"model_id": "m"}) == {}

    def test_produces_output_features_defaults_to_true(self):
        assert AbstractOperator.produces_output_features is True

    def test_only_vectordb_is_terminal(self):
        assert VectorDBOperator.produces_output_features is False
        for op in (ExtractOperator, EmbeddingsOperator, MergeOperator, SQLFilterOperator):
            assert op.produces_output_features is True


class TestDropFeatures:
    """FeaturePropagationResult.drop_features keeps error text and bookkeeping identical to the old inline code."""

    def test_drops_and_records_features(self):
        result = _result(features={"id": {"tags": ["mandatory"]}, "a": {}, "b": {}})

        result.drop_features(node_id="n", features=["a"], operator_label="x")

        assert set(result.feature_metadata) == {"id", "b"}
        assert result.get_output_features_to_drop(node_id="n").get_features_to_drop() == {"a"}

    def test_empty_list_is_noop(self):
        result = _result(features={"a": {}})

        result.drop_features(node_id="n", features=[], operator_label="x")

        assert "a" in result.feature_metadata
        assert result.output_features_to_drop == {}

    @pytest.mark.parametrize("label", ["SQLFilter", "chunker"])
    def test_mandatory_feature_raises_with_label_in_message(self, label):
        result = _result(features={"id": {"tags": ["mandatory"]}})

        with pytest.raises(FlowValidationException) as exc_info:
            result.drop_features(node_id="n", features=["id"], operator_label=label)

        alert = exc_info.value.errors[0]
        assert f"Cannot drop mandatory features: ['id'] in {label} operator" in str(alert.message)
        assert alert.message_code == "MANDATORY_FEATURES_DROPPED"
        assert "id" in result.feature_metadata


class TestSQLFilterHook:
    def test_drops_listed_feature(self):
        result = _result(features={"id": {"tags": ["mandatory"]}, "a": {}})

        SQLFilterOperator.propagate_features(
            operator_config={OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["a"]},
            result=result,
            node_id="n",
            parent_results=[],
        )

        assert "a" not in result.feature_metadata
        assert result.get_output_features_to_drop(node_id="n").should_drop(feature="a")

    def test_no_list_keeps_everything(self):
        result = _result(features={"a": {}})

        SQLFilterOperator.propagate_features(operator_config={}, result=result, node_id="n", parent_results=[])

        assert "a" in result.feature_metadata

    def test_mandatory_feature_rejected_with_sqlfilter_label(self):
        result = _result(features={"id": {"tags": ["mandatory"]}})

        with pytest.raises(FlowValidationException) as exc_info:
            SQLFilterOperator.propagate_features(
                operator_config={OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: ["id"]},
                result=result,
                node_id="n",
                parent_results=[],
            )

        assert "in SQLFilter operator" in str(exc_info.value.errors[0].message)


class TestEmbeddingsHooks:
    _COL = OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT

    @pytest.mark.parametrize("quantization", ["binary", "ubinary", "BINARY"])
    def test_binary_quantization_types_feature_as_vector_binary(self, quantization):
        result = _result(features={self._COL: {"type": "vector"}})

        EmbeddingsOperator.propagate_features(
            operator_config={OperatorConstants.Config.QUANTIZATION: quantization},
            result=result,
            node_id="n",
            parent_results=[],
        )

        feature = result.feature_metadata[self._COL]
        assert feature.type == OperatorConstants.Types.TYPE_VECTOR_BINARY
        assert feature.description == "Binary vector embeddings for similarity search"

    @pytest.mark.parametrize("config", [{}, {OperatorConstants.Config.QUANTIZATION: "none"}])
    def test_no_quantization_keeps_dense_type(self, config):
        result = _result(features={self._COL: {"type": "vector"}})

        EmbeddingsOperator.propagate_features(operator_config=config, result=result, node_id="n", parent_results=[])

        feature = result.feature_metadata[self._COL]
        assert feature.type == "vector"
        assert feature.description == "Dense vector embeddings for similarity search"

    def test_missing_embeddings_feature_is_tolerated(self):
        result = _result()

        EmbeddingsOperator.propagate_features(
            operator_config={OperatorConstants.Config.QUANTIZATION: "binary"},
            result=result,
            node_id="n",
            parent_results=[],
        )

        assert result.feature_metadata == {}

    def test_model_id_published_as_global_param(self):
        params = EmbeddingsOperator.get_global_params(operator_config={OperatorConstants.Config.MODEL_ID: "m1"})

        assert params == {OperatorConstants.Config.EMBEDDINGS_MODEL_ID: "m1"}

    def test_no_model_id_publishes_nothing(self):
        assert EmbeddingsOperator.get_global_params(operator_config={}) == {}


class TestExtractHook:
    @staticmethod
    def _config(provider: str | None) -> dict[str, Any]:
        if provider is None:
            return {}
        return {OperatorConstants.Config.ENTITY_EXTRACTION: {OperatorConstants.Config.PROVIDER: provider}}

    @pytest.mark.parametrize("provider", [None, OperatorConstants.ExtractionModes.ENTITY_MODE_NONE])
    def test_entity_features_removed_when_disabled(self, provider):
        result = _result(
            features={"entities": {"type": "list"}, OperatorConstants.Columns.DOCUMENT_TYPE: {}, "content": {}}
        )

        ExtractOperator.propagate_features(
            operator_config=self._config(provider), result=result, node_id="n", parent_results=[]
        )

        assert set(result.feature_metadata) == {"content"}

    def test_entity_features_added_when_enabled(self):
        result = _result(features={"content": {}})

        ExtractOperator.propagate_features(
            operator_config=self._config("litellm"), result=result, node_id="n", parent_results=[]
        )

        assert result.feature_metadata["entities"].type == "list"
        document_type = result.feature_metadata[OperatorConstants.Columns.DOCUMENT_TYPE]
        assert document_type.type == OperatorConstants.Types.TYPE_STRING
        assert document_type.available_for_filter is True

    def test_existing_entity_features_are_kept(self):
        result = _result(features={"entities": {"description": "keep me", "type": "list"}})

        ExtractOperator.propagate_features(
            operator_config=self._config("litellm"), result=result, node_id="n", parent_results=[]
        )

        assert result.feature_metadata["entities"].description == "keep me"


class TestMergeHook:
    @staticmethod
    def _parents() -> list[FeaturePropagationResult]:
        first = _result(node_id="a", features={"id": {}, "name": {}, "only_a": {}})
        first.source_node_id = "a"
        second = _result(node_id="b", features={"id": {}, "name": {}, "only_b": {}})
        second.source_node_id = "b"
        return [first, second]

    def test_rows_merge_is_union(self):
        result = _result()

        MergeOperator.propagate_features(
            operator_config={OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.ROWS},
            result=result,
            node_id="m",
            parent_results=self._parents(),
        )

        assert set(result.feature_metadata) == {"id", "name", "only_a", "only_b"}

    def test_inner_join_keeps_common_features_and_id(self):
        result = _result()

        MergeOperator.propagate_features(
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.COLUMNS,
                OperatorConstants.Merge.COLUMN_OPTION: OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
            },
            result=result,
            node_id="m",
            parent_results=self._parents(),
        )

        # common features: plain first occurrence plus a suffixed copy for the second branch;
        # branch-exclusive features are excluded
        assert set(result.feature_metadata) == {"id", "name", "name_1"}

    def test_full_outer_join_suffixes_duplicates_with_link_name(self):
        result = _result()

        MergeOperator.propagate_features(
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.COLUMNS,
                OperatorConstants.Merge.COLUMN_OPTION: OperatorConstants.Merge.FULL_OUTER_JOIN,
                OperatorConstants.Merge.INPUT_LINKS: [
                    {"node_id_ref": "a", OperatorConstants.Misc.LINK_NAME: "Link_5"},
                    {"node_id_ref": "b", OperatorConstants.Misc.LINK_NAME: "Link_6"},
                ],
            },
            result=result,
            node_id="m",
            parent_results=self._parents(),
        )

        assert set(result.feature_metadata) == {"id", "name", "name_Link_6", "only_a", "only_b"}

    def test_full_outer_join_falls_back_to_branch_index(self):
        result = _result()

        MergeOperator.propagate_features(
            operator_config={
                OperatorConstants.Merge.MERGE_TYPE: OperatorConstants.Merge.COLUMNS,
                OperatorConstants.Merge.COLUMN_OPTION: OperatorConstants.Merge.FULL_OUTER_JOIN,
            },
            result=result,
            node_id="m",
            parent_results=self._parents(),
        )

        assert "name_1" in result.feature_metadata
        assert "id_1" not in result.feature_metadata

    def test_no_parents_leaves_features_unchanged(self):
        result = _result(features={"x": {}})

        MergeOperator.propagate_features(operator_config={}, result=result, node_id="m", parent_results=[])

        assert list(result.feature_metadata) == ["x"]


class TestPropagatorUsesOperatorHooks:
    """The propagator is operator-agnostic: a new operator needs no change to it."""

    class _DummyOp(AbstractOperator):
        short_name = "dummy_op"
        category = OperatorCategory.Functional
        owner = "tests"

        @classmethod
        def propagate_features(cls, *, operator_config, result, node_id, parent_results):
            result.feature_metadata.pop("secret", None)

        @classmethod
        def get_global_params(cls, *, operator_config):
            return {"dummy_param": operator_config.get("value")}

    class _TerminalOp(AbstractOperator):
        short_name = "terminal_op"
        category = OperatorCategory.Functional
        owner = "tests"
        produces_output_features = False

    _FEATURES: ClassVar[dict[str, Any]] = {"secret": {"type": "string"}, "extra": {"type": "string"}}
    _INPUT: ClassVar[dict[str, Any]] = {"id": {"tags": ["mandatory"]}}

    def _propagate(self, *, name: str):
        prop = _propagator_with_classes(
            classes={"dummy_op": self._DummyOp, "terminal_op": self._TerminalOp}, features=self._FEATURES
        )
        return prop.propagate_features(
            node_id="n",
            operator_short_name=name,
            operator_config={"value": 7},
            input_features=self._INPUT,
            global_config={},
            parent_results=[],
        )

    def test_custom_hook_adjusts_features_and_publishes_params(self):
        result = self._propagate(name="dummy_op")

        assert "secret" not in result.feature_metadata
        assert "extra" in result.feature_metadata
        assert result.global_params == {"dummy_param": 7}
        assert set(result.get_output_features(node_id="n")) == {"extra"}

    def test_terminal_operator_reports_no_output_features(self):
        result = self._propagate(name="terminal_op")

        assert result.get_output_features(node_id="n") == {}
        assert "extra" in result.feature_metadata

    def test_unknown_operator_adds_nothing_and_does_not_fail(self):
        result = self._propagate(name="not_registered")

        assert set(result.feature_metadata) == {"id"}
        assert result.global_params == {}


class TestUntrustedDescriptorIsNeverRun:
    def test_propagation_uses_static_metadata_without_importing_source(self, tmp_path):
        marker = tmp_path / "executed"
        source = tmp_path / "evil_op.py"
        source.write_text(f"open({str(marker)!r}, 'w').write('x')\n")
        descriptor = build_untrusted_descriptor(
            operator_info=OperatorInfo(
                name="EvilOp",
                short_name="evil_op",
                module_path=str(source),
                category="Functional",
                source_location=str(source),
                source_file=str(source),
                static_metadata={OperatorConstants.Config.FEATURES: {"x": {"type": "string"}}},
            )
        )
        prop = _propagator_with_classes(classes={"evil_op": descriptor}, features={"x": {"type": "string"}})

        result = prop.propagate_features(
            node_id="n",
            operator_short_name="evil_op",
            operator_config={},
            input_features={"id": {"tags": ["mandatory"]}},
            global_config={},
            parent_results=[],
        )

        assert set(result.feature_metadata) == {"id", "x"}
        assert not marker.exists()


class TestOperatorMetadataClassLookup:
    def test_returns_class_from_the_same_factory_as_metadata(self):
        from docpipe.core.operators.operator_metadata import OperatorMetadata

        metadata = OperatorMetadata()
        assert metadata.get_operator_class(short_name="merge") is None  # not loaded yet

        metadata.get_operator_metadata(internal_features=True)

        factory = OperatorFactoryProvider.get_operator_factory(orchestrator=OrchestratorType.PYTHON)
        assert metadata.get_operator_class(short_name="merge") is MergeOperator
        assert metadata.get_operator_class(short_name="merge") is factory.get_operator(operator_name="merge")
        assert metadata.get_operator_class(short_name="no_such_operator") is None
