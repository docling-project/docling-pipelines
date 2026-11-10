# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for FlowEnrichmentService."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import docpipe.core.operators.vectordb.metadata_fetcher as _mf_mod
from docpipe.core.assets.flows.application.services.flow_enrichment_service import FlowEnrichmentService
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.feature_propagation.features_propagator import FeaturePropagator
from docpipe.core.orchestration.feature_propagation.models import FeaturePropagationResult
from docpipe.exceptions.docpipe_exceptions import FlowValidationException
from docpipe.integrations.secrets.secret_provider import (
    ProviderUnreachableError,
    SecretProvider,
    clear_providers,
    register_provider,
)
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feature(*, source_node_id: str = "node-1", type_: str = "string") -> dict[str, Any]:
    """Return a minimal raw feature dict as produced by FeaturePropagator."""
    return {
        "description": "",
        "available_for_filter": True,
        "available_for_vector_db": False,
        "type": type_,
        "source_node_id": source_node_id,
        "tags": [],
    }


def _make_node_feature_result(
    *,
    available: dict | None = None,
    inputs: dict | None = None,
    outputs: dict | None = None,
    operator_config: dict | None = None,
) -> dict[str, Any]:
    """Return a per-node feature result dict as returned by propagate_features_per_node."""
    result: dict[str, Any] = {
        OperatorConstants.Config.AVAILABLE_FEATURES: available or {},
        OperatorConstants.Config.INPUT_FEATURES: inputs or {},
        OperatorConstants.Config.OUTPUT_FEATURES: outputs or {},
        "dropped_features": [],
    }
    if operator_config is not None:
        result["operator_config"] = operator_config
    return result


def _make_service(node_features: dict[str, Any]) -> FlowEnrichmentService:
    """Return a FlowEnrichmentService whose validator returns ``node_features``."""
    mock_validator = MagicMock()
    mock_validator.propagate_features_per_node.return_value = node_features

    with patch(
        "docpipe.core.assets.flows.application.services.flow_enrichment_service.ValidationService"
    ) as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs._convert_to_dag_flow.return_value = {
            "dag": [],
            OperatorConstants.Config.GLOBAL_CONFIG: {},
        }
        mock_vs_cls.return_value = mock_vs
        service = FlowEnrichmentService(validator_factory=lambda: mock_validator)

    return service  # noqa: RET504


def _minimal_elyra_flow(*node_ids_and_ops: tuple[str, str]) -> dict[str, Any]:
    """Build a minimal Elyra JSON with the given (node_id, op) pairs."""
    nodes = [{"id": node_id, "op": op, "parameters": {}} for node_id, op in node_ids_and_ops]
    return {
        "doc_type": "pipeline",
        "version": "3.0",
        "pipelines": [
            {
                "nodes": nodes,
                "app_data": {"ds_flow": {"name": "Test Flow", "global_config": {}}},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests: enrich_flow_with_features — guard clauses
# ---------------------------------------------------------------------------


class TestEnrichFlowWithFeaturesGuards:
    """Tests for input validation in enrich_flow_with_features."""

    def test_raises_value_error_for_empty_dict(self):
        """Empty dict raises ValueError."""
        service = _make_service({})
        with pytest.raises(ValueError, match="flow_definition is required"):
            service.enrich_flow_with_features(flow_definition={})

    def test_raises_value_error_for_none(self):
        """None raises ValueError."""
        service = _make_service({})
        with pytest.raises(ValueError, match="flow_definition is required"):
            service.enrich_flow_with_features(flow_definition=None)  # type: ignore[arg-type]

    def test_propagates_flow_validation_exception(self):
        """FlowValidationException from the validator bubbles up unchanged."""
        mock_validator = MagicMock()
        mock_validator.propagate_features_per_node.side_effect = FlowValidationException(
            errors=[{"code": "CYCLE_DETECTED", "message": "Cycle in DAG"}]
        )

        with patch(
            "docpipe.core.assets.flows.application.services.flow_enrichment_service.ValidationService"
        ) as mock_vs_cls:
            mock_vs = MagicMock()
            mock_vs._convert_to_dag_flow.return_value = {"dag": [], "global_config": {}}
            mock_vs_cls.return_value = mock_vs
            service = FlowEnrichmentService(validator_factory=lambda: mock_validator)

        with pytest.raises(FlowValidationException):
            service.enrich_flow_with_features(flow_definition=_minimal_elyra_flow(("node-1", "ingest_source")))


# ---------------------------------------------------------------------------
# Tests: enrich_flow_with_features — metadata injection
# ---------------------------------------------------------------------------


class TestEnrichFlowWithFeaturesMetadataInjection:
    """Tests for feature metadata injection into node parameters."""

    def test_injects_metadata_into_matched_node(self):
        """Node with a matching ID gets input/output/available_features injected."""
        feature = _make_feature(source_node_id="node-1")
        node_features = {
            "node-1": _make_node_feature_result(
                inputs={"content": feature},
                outputs={"chunk": feature},
            )
        }
        service = _make_service(node_features)
        flow = _minimal_elyra_flow(("node-1", "chunker"))

        result = service.enrich_flow_with_features(flow_definition=flow)

        node_params = result["pipelines"][0]["nodes"][0]["parameters"]
        assert "input_features" in node_params
        assert "output_features" in node_params
        assert "available_features" in node_params
        assert "content" in node_params["input_features"]
        assert "chunk" in node_params["output_features"]

    def test_does_not_inject_into_unmatched_node(self):
        """Node absent from node_features is left untouched."""
        service = _make_service({})  # no features for any node
        flow = _minimal_elyra_flow(("node-unknown", "chunker"))

        result = service.enrich_flow_with_features(flow_definition=flow)

        node_params = result["pipelines"][0]["nodes"][0]["parameters"]
        assert "input_features" not in node_params
        assert "output_features" not in node_params

    def test_does_not_mutate_original_flow(self):
        """The original flow_definition dict is not modified."""
        feature = _make_feature()
        node_features = {"node-1": _make_node_feature_result(inputs={"content": feature})}
        service = _make_service(node_features)
        flow = _minimal_elyra_flow(("node-1", "chunker"))

        import copy

        original = copy.deepcopy(flow)
        service.enrich_flow_with_features(flow_definition=flow)

        assert flow == original

    def test_normalises_feature_shape(self):
        """Raw feature dict is normalised to the expected feature shape."""
        feature = {
            "description": "The document content",
            "available_for_filter": True,
            "available_for_vector_db": True,
            "type": "int64",
            "source_node_id": "node-0",
            "tags": ["mandatory"],
        }
        node_features = {"node-1": _make_node_feature_result(inputs={"content": feature})}
        service = _make_service(node_features)
        flow = _minimal_elyra_flow(("node-1", "chunker"))

        result = service.enrich_flow_with_features(flow_definition=flow)
        normalised = result["pipelines"][0]["nodes"][0]["parameters"]["input_features"]["content"]

        assert normalised["name"] == "content"
        assert normalised["description"] == "The document content"
        assert normalised["available_for_filter"] is True
        assert normalised["available_for_vector_db"] is True
        assert normalised["type"] == "int64"
        assert normalised["node_id"] == "node-0"
        assert normalised["tags"] == ["mandatory"]

    def test_falls_back_to_node_id_when_source_node_id_missing(self):
        """node_id falls back to the Elyra node ID when source_node_id is absent."""
        feature = {
            "description": "",
            "available_for_filter": True,
            "available_for_vector_db": False,
            "type": "string",
            "tags": [],
        }
        node_features = {"node-1": _make_node_feature_result(inputs={"content": feature})}
        service = _make_service(node_features)
        flow = _minimal_elyra_flow(("node-1", "chunker"))

        result = service.enrich_flow_with_features(flow_definition=flow)
        normalised = result["pipelines"][0]["nodes"][0]["parameters"]["input_features"]["content"]

        assert normalised["node_id"] == "node-1"

    def test_merges_into_existing_parameters(self):
        """Existing node parameters are preserved; metadata keys are added."""
        node_features = {"node-1": _make_node_feature_result(outputs={"chunk": _make_feature()})}
        service = _make_service(node_features)
        flow = {
            "doc_type": "pipeline",
            "pipelines": [
                {
                    "nodes": [{"id": "node-1", "op": "chunker", "parameters": {"chunk_size": 512}}],
                    "app_data": {},
                }
            ],
        }

        result = service.enrich_flow_with_features(flow_definition=flow)
        node_params = result["pipelines"][0]["nodes"][0]["parameters"]

        assert node_params["chunk_size"] == 512
        assert "output_features" in node_params

    def test_handles_multiple_nodes_across_pipelines(self):
        """Metadata is injected into all matching nodes across multiple pipelines."""
        node_features = {
            "node-1": _make_node_feature_result(outputs={"id": _make_feature()}),
            "node-2": _make_node_feature_result(inputs={"id": _make_feature()}),
        }

        with patch(
            "docpipe.core.assets.flows.application.services.flow_enrichment_service.ValidationService"
        ) as mock_vs_cls:
            mock_vs = MagicMock()
            mock_vs._convert_to_dag_flow.return_value = {"dag": [], "global_config": {}}
            mock_vs_cls.return_value = mock_vs
            mock_validator = MagicMock()
            mock_validator.propagate_features_per_node.return_value = node_features
            service = FlowEnrichmentService(validator_factory=lambda: mock_validator)

        flow = {
            "doc_type": "pipeline",
            "pipelines": [
                {"nodes": [{"id": "node-1", "op": "ingest_source", "parameters": {}}], "app_data": {}},
                {"nodes": [{"id": "node-2", "op": "chunker", "parameters": {}}], "app_data": {}},
            ],
        }

        result = service.enrich_flow_with_features(flow_definition=flow)

        assert "output_features" in result["pipelines"][0]["nodes"][0]["parameters"]
        assert "input_features" in result["pipelines"][1]["nodes"][0]["parameters"]


# ---------------------------------------------------------------------------
# Tests: _build_node_feature_metadata — available_features rules
# ---------------------------------------------------------------------------


class TestBuildNodeFeatureMetadataAvailableFeatures:
    """Tests for operator-specific available_features population rules."""

    def _build(
        self,
        operator_type: str,
        available: dict | None = None,
        inputs: dict | None = None,
    ) -> dict[str, Any]:
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        return service._build_node_feature_metadata(
            node_id="node-x",
            node_feature_result=_make_node_feature_result(
                available=available or {},
                inputs=inputs or {},
            ),
            operator_type=operator_type,
        )

    def test_sql_filter_populates_available_features_from_input_features(self):
        """sql_filter available_features comes from input_feature_map, not available_feature_map.

        All upstream features where available_for_filter=True are included so the UI
        can populate the criteria/column dropdowns correctly.
        """
        inputs = {"content": _make_feature(), "doc_id": _make_feature()}
        result = self._build(OperatorConstants.Operators.SQL_FILTER, inputs=inputs)
        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        assert "content" in af
        assert "doc_id" in af

    def test_sql_filter_excludes_non_filterable_input_features(self):
        """sql_filter available_features excludes features with available_for_filter=False.

        Features like vector_embeddings should not appear in the criteria dropdown.
        """
        filterable = _make_feature()  # available_for_filter=True by default
        non_filterable = {**_make_feature(), "available_for_filter": False}
        inputs = {"doc_id": filterable, "vector_embeddings": non_filterable}
        result = self._build(OperatorConstants.Operators.SQL_FILTER, inputs=inputs)
        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        assert "doc_id" in af
        assert "vector_embeddings" not in af

    def test_sql_filter_ignores_available_feature_map(self):
        """sql_filter available_features is built from input_features, not the propagator's
        available_feature_map (the post-propagation snapshot, which may already have had
        features dropped)."""
        # Populate available but leave inputs empty — available_features must be empty too.
        available = {"content": _make_feature()}
        result = self._build(OperatorConstants.Operators.SQL_FILTER, available=available)
        assert result[OperatorConstants.Config.AVAILABLE_FEATURES] == {}

    def test_vectordb_populates_available_features(self):
        """vectordb returns available_features from the snapshot."""
        available = {"content": _make_feature(), "embeddings": _make_feature()}
        result = self._build(OperatorConstants.Operators.VECTORDB, available=available)
        assert "content" in result[OperatorConstants.Config.AVAILABLE_FEATURES]
        assert "embeddings" in result[OperatorConstants.Config.AVAILABLE_FEATURES]

    def test_merge_populates_available_features(self):
        """merge returns available_features from the snapshot (flat dict, current behaviour)."""
        available = {"id": _make_feature()}
        result = self._build(OperatorConstants.Operators.MERGE, available=available)
        assert "id" in result[OperatorConstants.Config.AVAILABLE_FEATURES]

    def test_other_operators_return_empty_available_features(self):
        """All operators other than sql_filter, vectordb, merge return empty available_features."""
        for op in (
            OperatorConstants.Operators.CHUNKER,
            OperatorConstants.Operators.EMBEDDINGS,
            OperatorConstants.Operators.INGEST_SOURCE,
            OperatorConstants.Operators.EXTRACT_OPERATOR,
            OperatorConstants.Operators.LANG_DETECT,
        ):
            result = self._build(op, available={"content": _make_feature()})
            assert result[OperatorConstants.Config.AVAILABLE_FEATURES] == {}, (
                f"Expected empty available_features for operator '{op}'"
            )

    def test_unknown_operator_returns_empty_available_features(self):
        """Unrecognised operator type returns empty available_features."""
        result = self._build("some_future_operator", available={"content": _make_feature()})
        assert result[OperatorConstants.Config.AVAILABLE_FEATURES] == {}

    def test_input_and_output_always_populated(self):
        """input_features and output_features are always populated regardless of operator type."""
        inputs = {"content": _make_feature()}
        outputs = {"chunk": _make_feature()}
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        result = service._build_node_feature_metadata(
            node_id="node-x",
            node_feature_result=_make_node_feature_result(inputs=inputs, outputs=outputs),
            operator_type="noop",
        )
        assert "content" in result[OperatorConstants.Config.INPUT_FEATURES]
        assert "chunk" in result[OperatorConstants.Config.OUTPUT_FEATURES]

    def test_empty_feature_maps_produce_empty_dicts(self):
        """Empty snapshot maps produce empty output dicts."""
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        result = service._build_node_feature_metadata(
            node_id="node-x",
            node_feature_result=_make_node_feature_result(),
            operator_type="chunker",
        )
        assert result[OperatorConstants.Config.AVAILABLE_FEATURES] == {}
        assert result[OperatorConstants.Config.INPUT_FEATURES] == {}
        assert result[OperatorConstants.Config.OUTPUT_FEATURES] == {}


# ---------------------------------------------------------------------------
# Tests: _build_node_feature_metadata — merge three-strategy nested dict (P4)
# ---------------------------------------------------------------------------


def _make_parent_result(
    features: dict[str, tuple[str, bool, bool]],
    source_node_id: str = "upstream-node",
) -> FeaturePropagationResult:
    """Build a FeaturePropagationResult from {name: (description, filter, vector_db)}."""
    result = FeaturePropagationResult()
    result.source_node_id = source_node_id
    for name, (desc, for_filter, for_vdb) in features.items():
        result.add_feature(
            feature_name=name,
            node_id=source_node_id,
            description=desc,
            available_for_filter=for_filter,
            available_for_vector_db=for_vdb,
        )
    return result


def _build_merge_result(
    parent_results: list,
    available: dict | None = None,
    operator_config: dict | None = None,
) -> dict:
    """Call _build_node_feature_metadata for a merge node.

    FeaturePropagator.__init__ is bypassed via patch to avoid loading the
    full operator registry (which requires the optional 're2' native library).
    A real FeaturePropagator instance (via __new__) is assigned so that
    feature_metadata_to_dict() and merge_features() work normally.
    """
    with patch.object(FeaturePropagator, "__init__", lambda self: None):
        propagator = FeaturePropagator()
        service = _make_service(node_features={})
        service._propagator = propagator

    node_feature_result = _make_node_feature_result(available=available or {})
    node_feature_result["parent_results"] = parent_results
    if operator_config is not None:
        node_feature_result["operator_config"] = operator_config
    return service._build_node_feature_metadata(
        node_id="merge-node",
        node_feature_result=node_feature_result,
        operator_type=OperatorConstants.Operators.MERGE,
    )


class TestMergeAvailableFeaturesThreeStrategy:
    """Tests for P4: merge available_features returns nested dict with three strategy keys."""

    def test_three_strategy_keys_present(self):
        """Three strategy keys are present when parent_results are provided."""
        p1 = _make_parent_result({"id": ("ID", True, False), "content": ("Content", False, True)})
        p2 = _make_parent_result({"id": ("ID", True, False), "title": ("Title", True, False)})

        result = _build_merge_result([p1, p2])
        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]

        assert OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION in af
        assert OperatorConstants.Misc.MERGE_STRATEGY_INNER_JOIN in af
        assert OperatorConstants.Misc.MERGE_STRATEGY_FULL_OUTER_JOIN in af

    def test_concatenation_is_union_of_all_features(self):
        """concatenation_with_different_schema contains the union of all parent features."""
        p1 = _make_parent_result({"id": ("", True, False), "content": ("", False, True)})
        p2 = _make_parent_result({"id": ("", True, False), "title": ("", True, False)})

        result = _build_merge_result([p1, p2])
        concat = result[OperatorConstants.Config.AVAILABLE_FEATURES][
            OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION
        ]

        assert "id" in concat
        assert "content" in concat
        assert "title" in concat

    def test_inner_join_contains_only_common_features(self):
        """inner_join_with_duplicate_columns contains only features present in ALL parents."""
        p1 = _make_parent_result({"id": ("", True, False), "content": ("", False, True), "only_p1": ("", True, False)})
        p2 = _make_parent_result({"id": ("", True, False), "content": ("", False, True), "only_p2": ("", True, False)})

        result = _build_merge_result([p1, p2])
        inner = result[OperatorConstants.Config.AVAILABLE_FEATURES][OperatorConstants.Misc.MERGE_STRATEGY_INNER_JOIN]

        assert "id" in inner
        assert "content" in inner
        assert "only_p1" not in inner
        assert "only_p2" not in inner

    def test_full_outer_join_contains_all_features_with_disambiguation(self):
        """full_outer_join: first occurrence keeps plain key, 2nd+ gets link-name suffix."""
        p1 = _make_parent_result({"id": ("", True, False), "name": ("Name", True, False)}, source_node_id="node-a")
        p2 = _make_parent_result({"id": ("", True, False), "name": ("Name", True, False)}, source_node_id="node-b")
        op_cfg = {
            OperatorConstants.Merge.INPUT_LINKS: [
                {"node_id_ref": "node-a", OperatorConstants.Misc.LINK_NAME: "Link_5"},
                {"node_id_ref": "node-b", OperatorConstants.Misc.LINK_NAME: "Link_6"},
            ]
        }

        result = _build_merge_result([p1, p2], operator_config=op_cfg)
        outer = result[OperatorConstants.Config.AVAILABLE_FEATURES][
            OperatorConstants.Misc.MERGE_STRATEGY_FULL_OUTER_JOIN
        ]

        assert "id" in outer
        assert "name" in outer  # first occurrence: plain key
        assert "name_Link_6" in outer  # second occurrence: suffixed with branch 2 link name
        assert "name_Link_5" not in outer  # first occurrence is never suffixed

    def test_single_parent_inner_join_contains_all_its_features(self):
        """With a single parent, inner join returns all features from that parent."""
        p1 = _make_parent_result({"id": ("", True, False), "content": ("", False, True)})

        result = _build_merge_result([p1])
        inner = result[OperatorConstants.Config.AVAILABLE_FEATURES][OperatorConstants.Misc.MERGE_STRATEGY_INNER_JOIN]

        assert "id" in inner
        assert "content" in inner

    def test_fallback_to_flat_dict_when_no_parent_results(self):
        """When parent_results is absent/empty, falls back to flat dict from available_feature_map."""
        service = _make_service(node_features={})
        available = {"id": _make_feature()}
        node_feature_result = _make_node_feature_result(available=available)
        # no "parent_results" key

        result = service._build_node_feature_metadata(
            node_id="merge-node",
            node_feature_result=node_feature_result,
            operator_type=OperatorConstants.Operators.MERGE,
        )

        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        # flat dict fallback — NOT a three-key nested structure
        assert "id" in af
        assert OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION not in af

    def test_each_strategy_entry_has_normalised_feature_shape(self):
        """Each feature inside a strategy dict has the expected normalised keys."""
        p1 = _make_parent_result({"id": ("The ID", True, True)})

        result = _build_merge_result([p1])
        concat_features = result[OperatorConstants.Config.AVAILABLE_FEATURES][
            OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION
        ]
        id_meta = concat_features["id"]

        assert "name" in id_meta
        assert "description" in id_meta
        assert "available_for_filter" in id_meta
        assert "available_for_vector_db" in id_meta
        assert "type" in id_meta
        assert "node_id" in id_meta
        assert "tags" in id_meta


# ---------------------------------------------------------------------------
# Tests: _build_node_feature_metadata — output_features for merge node
# ---------------------------------------------------------------------------


class TestMergeOutputFeaturesSelection:
    """output_features on a merge node must equal the active strategy bucket
    selected by merge_type / column_option from operator_config."""

    def _two_parent_config(self, merge_type: str, column_option: str | None = None) -> dict:
        return {
            OperatorConstants.Merge.MERGE_TYPE: merge_type,
            OperatorConstants.Merge.COLUMN_OPTION: column_option,
            OperatorConstants.Merge.INPUT_LINKS: [
                {"node_id_ref": "node-a", OperatorConstants.Misc.LINK_NAME: "Link_5"},
                {"node_id_ref": "node-b", OperatorConstants.Misc.LINK_NAME: "Link_6"},
            ],
        }

    def test_rows_output_equals_concatenation_bucket(self):
        """merge_type=rows → output_features == concatenation_with_different_schema."""
        p1 = _make_parent_result({"id": ("", True, False), "content": ("", True, True)}, source_node_id="node-a")
        p2 = _make_parent_result({"id": ("", True, False), "size": ("", True, False)}, source_node_id="node-b")

        result = _build_merge_result([p1, p2], operator_config=self._two_parent_config(OperatorConstants.Merge.ROWS))

        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        of = result[OperatorConstants.Config.OUTPUT_FEATURES]

        assert set(of.keys()) == set(af[OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION].keys())

    def test_columns_full_outer_output_equals_full_outer_bucket(self):
        """merge_type=columns + column_option=full_outer → output_features == full_outer_join."""
        p1 = _make_parent_result({"id": ("", True, False), "content": ("", True, True)}, source_node_id="node-a")
        p2 = _make_parent_result({"id": ("", True, False), "content": ("", True, True)}, source_node_id="node-b")

        result = _build_merge_result(
            [p1, p2],
            operator_config=self._two_parent_config(
                OperatorConstants.Merge.COLUMNS, OperatorConstants.Merge.FULL_OUTER_JOIN
            ),
        )

        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        of = result[OperatorConstants.Config.OUTPUT_FEATURES]

        assert set(of.keys()) == set(af[OperatorConstants.Misc.MERGE_STRATEGY_FULL_OUTER_JOIN].keys())

    def test_columns_inner_join_output_equals_inner_join_bucket(self):
        """merge_type=columns + column_option=inner_join → output_features == inner_join_with_duplicate_columns."""
        p1 = _make_parent_result(
            {"id": ("", True, False), "content": ("", True, True), "only_a": ("", True, False)},
            source_node_id="node-a",
        )
        p2 = _make_parent_result(
            {"id": ("", True, False), "content": ("", True, True), "only_b": ("", True, False)},
            source_node_id="node-b",
        )

        result = _build_merge_result(
            [p1, p2],
            operator_config=self._two_parent_config(
                OperatorConstants.Merge.COLUMNS, OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN
            ),
        )

        af = result[OperatorConstants.Config.AVAILABLE_FEATURES]
        of = result[OperatorConstants.Config.OUTPUT_FEATURES]

        # output_features matches inner_join bucket (no unique-only-branch features)
        assert set(of.keys()) == set(af[OperatorConstants.Misc.MERGE_STRATEGY_INNER_JOIN].keys())
        assert "only_a" not in of
        assert "only_b" not in of

    def test_output_features_contain_link_name_suffixes_for_column_merge(self):
        """Suffixed duplicate keys appear in output_features for column merge types."""
        p1 = _make_parent_result({"id": ("", True, False), "name": ("", True, False)}, source_node_id="node-a")
        p2 = _make_parent_result({"id": ("", True, False), "name": ("", True, False)}, source_node_id="node-b")

        result = _build_merge_result(
            [p1, p2],
            operator_config=self._two_parent_config(
                OperatorConstants.Merge.COLUMNS, OperatorConstants.Merge.FULL_OUTER_JOIN
            ),
        )

        of = result[OperatorConstants.Config.OUTPUT_FEATURES]
        assert "name" in of  # first occurrence: plain key
        assert "name_Link_6" in of  # second occurrence: suffixed
        assert "id" in of
        assert "id_Link_6" not in of  # primary key never suffixed

    def test_no_parent_results_falls_back_to_propagator_output(self):
        """Without parent_results, output_features uses the propagator-computed map."""
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        outputs = {"chunk": _make_feature()}
        node_feature_result = _make_node_feature_result(outputs=outputs)
        # no "parent_results" key → merge_output_features stays None
        result = service._build_node_feature_metadata(
            node_id="merge-node",
            node_feature_result=node_feature_result,
            operator_type=OperatorConstants.Operators.MERGE,
        )
        assert "chunk" in result[OperatorConstants.Config.OUTPUT_FEATURES]


# ---------------------------------------------------------------------------
# Tests: _fetch_vectordb_metadata
# ---------------------------------------------------------------------------


class TestFetchVectordbMetadata:
    """_fetch_vectordb_metadata returns None when no provider_config, or a five-key dict."""

    def _call_fetch(self, *, node_feature_result: dict) -> Any:
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        return service._fetch_vectordb_metadata(node_feature_result=node_feature_result)

    def test_returns_none_when_provider_config_absent(self):
        """UI distinguishes 'not configured' from 'configured but empty'."""
        result = self._call_fetch(node_feature_result={"operator_config": {}})
        assert result is None

    def test_returns_none_when_operator_config_missing(self):
        result = self._call_fetch(node_feature_result={})
        assert result is None

    def test_returns_dict_with_five_keys_when_provider_config_present(self):
        expected = _mf_mod.VectorDBMetadataFetcher._empty_result()
        node_result = {
            "operator_config": {
                OperatorConstants.Config.PROVIDER: OperatorConstants.VectorDB.OPENSEARCH,
                OperatorConstants.Config.PROVIDER_CONFIG: {"host": "localhost"},
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {},
        }

        # VectorDBMetadataFetcher is lazy-imported inside _fetch_vectordb_metadata;
        # patch it at the module where it lives (the import target).
        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_metadata.return_value = expected
            mock_cls.return_value = mock_fetcher

            result = self._call_fetch(node_feature_result=node_result)

        assert result is expected
        assert OperatorConstants.VectorDB.AVAILABLE_RESOURCES in result
        assert OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE in result

    def test_passes_available_features_to_fetcher(self):
        """available_features from propagator snapshot (not operator_config) is forwarded."""
        node_result = {
            "operator_config": {
                OperatorConstants.Config.PROVIDER: OperatorConstants.VectorDB.OPENSEARCH,
                OperatorConstants.Config.PROVIDER_CONFIG: {"host": "localhost"},
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {"content": {"type": "string"}},
        }

        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_metadata.return_value = {}
            mock_cls.return_value = mock_fetcher

            self._call_fetch(node_feature_result=node_result)

        call_kwargs = mock_fetcher.fetch_metadata.call_args.kwargs
        assert call_kwargs["available_features"] == {"content": {"type": "string"}}

    def test_defaults_adapter_name_to_opensearch_when_provider_absent(self):
        """If operator_config has no 'provider' key, adapter defaults to 'opensearch'."""
        node_result = {
            "operator_config": {
                OperatorConstants.Config.PROVIDER_CONFIG: {"host": "localhost"},
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {},
        }

        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_metadata.return_value = {}
            mock_cls.return_value = mock_fetcher

            self._call_fetch(node_feature_result=node_result)

        call_kwargs = mock_fetcher.fetch_metadata.call_args.kwargs
        assert call_kwargs["adapter_name"] == OperatorConstants.VectorDB.OPENSEARCH


# ---------------------------------------------------------------------------
# Tests: _build_node_feature_metadata — VECTORDB branch key presence/absence
# ---------------------------------------------------------------------------


class TestBuildNodeFeatureMetadataVectorDB:
    """End-to-end tests for the VECTORDB branch of _build_node_feature_metadata.

    Verifies that VDB keys are present/absent based on provider_config state
    and that VectorDBMetadataFetcher is called with the right arguments.
    """

    def _build(self, node_feature_result: dict[str, Any]) -> dict[str, Any]:
        service = FlowEnrichmentService.__new__(FlowEnrichmentService)
        return service._build_node_feature_metadata(
            node_id="node-vdb",
            node_feature_result=node_feature_result,
            operator_type=OperatorConstants.Operators.VECTORDB,
        )

    def test_vdb_keys_absent_when_no_provider_config(self):
        """VDB keys must be omitted entirely when provider_config is not set."""
        nfr = _make_node_feature_result(
            operator_config={"provider": "opensearch", "index_name": "x"},
        )
        block = self._build(nfr)
        assert OperatorConstants.VectorDB.AVAILABLE_RESOURCES not in block
        assert OperatorConstants.VectorDB.STORED_RESOURCE_METADATA not in block
        assert OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA not in block
        assert OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE not in block
        assert OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE not in block

    def test_vdb_keys_absent_when_operator_config_missing_entirely(self):
        """VDB keys must be omitted when the node has no operator_config at all."""
        nfr = _make_node_feature_result()
        block = self._build(nfr)
        assert OperatorConstants.VectorDB.AVAILABLE_RESOURCES not in block

    def test_all_five_vdb_keys_present_when_fetcher_returns_data(self):
        fake_result = {
            OperatorConstants.VectorDB.AVAILABLE_RESOURCES: ["my-docs"],
            OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA: {"doc_id": {"type": "keyword"}},
            OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE: [
                {"feature_name": "doc_id", "mapped_column_name": "doc_id"}
            ],
            OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE: {"index_name": "my-docs", "supported": True},
            OperatorConstants.VectorDB.STORED_RESOURCE_METADATA: {"vector_similarity": "l2", "dimension_size": 384},
        }
        nfr = _make_node_feature_result(
            operator_config={
                "provider": "opensearch",
                "provider_config": {"host": "localhost", "port": 9200},
            }
        )
        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_cls.return_value.fetch_metadata.return_value = fake_result
            block = self._build(nfr)

        assert block[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == ["my-docs"]
        assert block[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA] == {
            "vector_similarity": "l2",
            "dimension_size": 384,
        }
        assert block[OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE] == [
            {"feature_name": "doc_id", "mapped_column_name": "doc_id"}
        ]

    def test_vdb_keys_with_empty_values_on_connection_failure(self):
        """When fetcher returns empty-value fallback, all five keys still appear."""
        empty = _mf_mod.VectorDBMetadataFetcher._empty_result()
        nfr = _make_node_feature_result(
            operator_config={"provider": "opensearch", "provider_config": {"host": "bad-host"}},
        )
        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_cls.return_value.fetch_metadata.return_value = empty
            block = self._build(nfr)

        assert block[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == []
        assert block[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA] == {
            "vector_similarity": None,
            "dimension_size": None,
        }

    def test_fetcher_called_with_correct_adapter_and_config(self):
        """fetch_metadata receives adapter_name, operator_config, and available_features."""
        op_cfg = {
            "provider": "milvus",
            "provider_config": {"host": "milvus-host", "port": 19530, "auth_type": "standalone"},
        }
        nfr = _make_node_feature_result(
            available={"content": _make_feature()},
            operator_config=op_cfg,
        )
        with patch.object(_mf_mod, "VectorDBMetadataFetcher") as mock_cls:
            mock_cls.return_value.fetch_metadata.return_value = _mf_mod.VectorDBMetadataFetcher._empty_result()
            self._build(nfr)

        call_kwargs = mock_cls.return_value.fetch_metadata.call_args.kwargs
        assert call_kwargs["adapter_name"] == OperatorConstants.VectorDB.MILVUS
        assert call_kwargs["operator_config"] == op_cfg

    def test_non_vectordb_nodes_have_no_vdb_keys(self):
        """Non-vectordb operators must never have VDB keys in their response."""
        for op in ("ingest_local", "chunker", "sql_filter", "merge", "embeddings"):
            nfr = _make_node_feature_result(
                operator_config={"provider_config": {"host": "localhost"}},
            )
            service = FlowEnrichmentService.__new__(FlowEnrichmentService)
            block = service._build_node_feature_metadata(
                node_id="n",
                node_feature_result=nfr,
                operator_type=op,
            )
            assert OperatorConstants.VectorDB.AVAILABLE_RESOURCES not in block, f"VDB key leaked into {op}"
            assert OperatorConstants.VectorDB.STORED_RESOURCE_METADATA not in block, f"VDB key leaked into {op}"


# ---------------------------------------------------------------------------
# Tests: _expand_dag_env_vars
# ---------------------------------------------------------------------------


class TestExpandDagEnvVars:
    """_expand_dag_env_vars expands ${ENV_VAR} placeholders in place and nothing else."""

    def _call(self, dag_nodes: list[dict[str, Any]]) -> None:
        FlowEnrichmentService._expand_dag_env_vars(internal_dag={"dag": dag_nodes})

    def test_expands_env_var_placeholder_in_string_value(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("OPENSEARCH_USERNAME", "admin")
        node: dict[str, Any] = {"id": "n1", "config": {"username": "${OPENSEARCH_USERNAME}", "host": "localhost"}}
        self._call([node])
        assert node["config"]["username"] == "admin"
        assert node["config"]["host"] == "localhost"

    def test_expands_nested_env_var_placeholder(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("OS_PASS", "s3cr3t")  # pragma: allowlist secret
        node: dict[str, Any] = {"id": "n1", "config": {"provider_config": {"password": "${OS_PASS}"}}}
        self._call([node])
        # pragma: allowlist nextline secret
        assert node["config"]["provider_config"]["password"] == "s3cr3t"

    def test_unset_env_var_left_as_is(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("UNSET_VAR", raising=False)
        node: dict[str, Any] = {"id": "n1", "config": {"key": "${UNSET_VAR}"}}
        self._call([node])
        assert node["config"]["key"] == "${UNSET_VAR}"

    def test_vault_reference_is_left_unresolved(self, provider: "_FakeProvider") -> None:
        """No reference is resolved here, and no provider is asked for anything."""
        ref = _ref("s3/creds")
        node: dict[str, Any] = {"id": "n1", "config": {"credentials": ref}}
        self._call([node])
        assert node["config"]["credentials"] == ref
        assert provider.requests == []

    def test_skips_nodes_with_non_dict_config(self) -> None:
        node: dict[str, Any] = {"id": "n1", "config": None}
        self._call([node])
        assert node["config"] is None

    def test_skips_nodes_with_no_config_key(self) -> None:
        node: dict[str, Any] = {"id": "n1"}
        self._call([node])
        assert "config" not in node

    def test_multiple_nodes_env_vars_resolved_independently(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("HOST_A", "host-a")
        monkeypatch.setenv("HOST_B", "host-b")
        nodes: list[dict[str, Any]] = [
            {"id": "n1", "config": {"host": "${HOST_A}"}},
            {"id": "n2", "config": {"host": "${HOST_B}"}},
        ]
        self._call(nodes)
        assert nodes[0]["config"]["host"] == "host-a"
        assert nodes[1]["config"]["host"] == "host-b"

    def test_empty_dag_does_not_raise(self) -> None:
        self._call([])


# ---------------------------------------------------------------------------
# Tests: secret references during enrichment (spec: secret-management)
# ---------------------------------------------------------------------------

CANARY = "CANARY-7c2e"
_PROVIDER = "hashicorp"


def _ref(name: str) -> str:
    return f"vault://{_PROVIDER}/{name}#value"


class _FakeProvider(SecretProvider):
    """Serves a fixed value, or fails, and records every request."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[str] = []

    def authenticate(self) -> None:
        """Not used."""

    def is_available(self) -> bool:
        """Always available."""
        return True

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        """Record the request; fail like an unreachable Vault, or return the canary."""
        self.requests.append(path)
        if self.fail:
            raise ProviderUnreachableError("vault down")
        return CANARY


@pytest.fixture
def provider() -> Iterator[_FakeProvider]:
    clear_providers()
    fake = _FakeProvider()
    register_provider(name=_PROVIDER, provider=fake)
    DocpipeConfigLoader._config = {
        "secrets": {"vault": {"allowed_paths": [f"{_PROVIDER}:**"], "allowed_destinations": ["milvus.example.com"]}}
    }
    yield fake
    clear_providers()
    DocpipeConfigLoader.reset()


def _milvus_node_result(*, token: str) -> dict[str, Any]:
    return _make_node_feature_result(
        operator_config={
            "name": "vdb",
            "provider": "milvus",
            "provider_config": {
                "auth_type": "token",
                "collection_name": "docs",
                "host": "milvus.example.com",
                "token": token,
            },
        }
    )


def _fetch(*, node_result: dict[str, Any]) -> Any:
    service = FlowEnrichmentService.__new__(FlowEnrichmentService)
    return service._fetch_vectordb_metadata(node_feature_result=node_result)


class TestVectorDbSecretResolutionDuringEnrichment:
    """A connecting node resolves its own references; a failure never reaches a client."""

    def test_unresolvable_token_returns_empty_result_and_never_connects(
        self, provider: _FakeProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider.fail = True
        node_result = _milvus_node_result(token=_ref("milvus/token"))
        with (
            patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as client_cls,
            caplog.at_level("WARNING"),
        ):
            result = _fetch(node_result=node_result)

        assert result == _mf_mod.VectorDBMetadataFetcher._empty_result()
        assert set(result) == {
            OperatorConstants.VectorDB.AVAILABLE_RESOURCES,
            OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA,
            OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE,
            OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE,
            OperatorConstants.VectorDB.STORED_RESOURCE_METADATA,
        }
        client_cls.assert_not_called()
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("provider_config.token" in w and _PROVIDER in w for w in warnings)
        assert CANARY not in caplog.text
        assert "milvus/token" not in caplog.text

    def test_unresolved_reference_is_never_passed_to_the_adapter_fetcher(self, provider: _FakeProvider) -> None:
        provider.fail = True
        node_result = _milvus_node_result(token=_ref("milvus/token"))
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch"
        ) as fetch:
            _fetch(node_result=node_result)
        fetch.assert_not_called()

    def test_successful_resolution_connects_with_resolved_values(self, provider: _FakeProvider) -> None:
        node_result = _milvus_node_result(token=_ref("milvus/token"))
        expected = {"marker": "from-adapter"}
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value=expected,
        ) as fetch:
            result = _fetch(node_result=node_result)

        assert result == expected
        assert fetch.call_args.kwargs["provider_config"]["token"] == CANARY
        assert provider.requests == ["milvus/token"]

    def test_resolution_does_not_mutate_the_snapshot_config(self, provider: _FakeProvider) -> None:
        node_result = _milvus_node_result(token=_ref("milvus/token"))
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value={},
        ):
            _fetch(node_result=node_result)
        assert node_result["operator_config"]["provider_config"]["token"] == _ref("milvus/token")

    def test_literal_credentials_are_unchanged_and_ask_no_provider(self, provider: _FakeProvider) -> None:
        node_result = _milvus_node_result(token="literal-token")  # pragma: allowlist secret
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value={},
        ) as fetch:
            _fetch(node_result=node_result)
        assert fetch.call_args.kwargs["provider_config"]["token"] == "literal-token"  # pragma: allowlist secret
        assert provider.requests == []

    def test_adapter_failure_log_carries_no_exception_text(self, caplog: pytest.LogCaptureFixture) -> None:
        """A client error that echoes its inputs is reduced to a category before logging."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        class _EchoingError(ConnectionError):
            pass

        with (
            patch(
                "docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient",
                side_effect=_EchoingError(f"cannot reach https://u:{CANARY}@milvus.example.com"),
            ),
            caplog.at_level("WARNING"),
        ):
            result = MilvusResourceMetadata().fetch(
                provider_config={"host": "milvus.example.com", "token": CANARY},
                operator_config={},
                available_features={},
                normalise_feature_mappings=lambda raw: raw,
                default_feature_mappings_from_features=lambda *a, **k: [],
                empty_result=_mf_mod.VectorDBMetadataFetcher._empty_result,
            )
        assert result == _mf_mod.VectorDBMetadataFetcher._empty_result()
        assert CANARY not in caplog.text


def _enrich(
    *, nodes: list[dict[str, Any]], node_features: dict[str, Any], op_by_id: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run enrich_flow_with_features with a real DAG conversion and a stub propagator."""
    captured: dict[str, Any] = {}

    def fake_propagate(*, flow_def: dict[str, Any], global_config: dict) -> dict:
        import copy

        captured["dag"] = copy.deepcopy(flow_def)
        return node_features

    mock_validator = MagicMock()
    mock_validator.propagate_features_per_node.side_effect = fake_propagate
    service = FlowEnrichmentService(validator_factory=lambda: mock_validator)
    flow = {
        "doc_type": "pipeline",
        "version": "3.0",
        "pipelines": [
            {
                "nodes": [{"id": n["id"], "op": op_by_id[n["id"]], "parameters": n["parameters"]} for n in nodes],
                "app_data": {"ds_flow": {"name": "Test Flow", "global_config": {}}},
            }
        ],
    }
    import copy

    request = copy.deepcopy(flow)
    response = service.enrich_flow_with_features(flow_definition=flow)
    assert flow == request, "the request body must not be mutated"
    return response, captured


class TestEnrichFlowSecretHandling:
    """Whole-flow behavior: which nodes resolve, and what the response may carry."""

    def _two_node_flow(self) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
        token = _ref("milvus/token")
        nodes: list[dict[str, Any]] = [
            {"id": "ing", "parameters": {"provider": "s3", "credentials": _ref("s3/creds")}},
            {
                "id": "vdb",
                "parameters": {
                    "provider": "milvus",
                    "provider_config": {
                        "auth_type": "token",
                        "collection_name": "docs",
                        "host": "milvus.example.com",
                        "token": token,
                    },
                },
            },
        ]
        node_features = {
            "ing": _make_node_feature_result(operator_config=nodes[0]["parameters"]),
            "vdb": _make_node_feature_result(operator_config=_milvus_node_result(token=token)["operator_config"]),
        }
        return nodes, node_features, {"ing": "ingest_source", "vdb": "vectordb"}

    def test_only_the_connecting_node_resolves(self, provider: _FakeProvider) -> None:
        nodes, node_features, ops = self._two_node_flow()
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value=_mf_mod.VectorDBMetadataFetcher._empty_result(),
        ):
            _enrich(nodes=nodes, node_features=node_features, op_by_id=ops)
        assert provider.requests == ["milvus/token"], "the ingest node's reference must not be resolved"

    def test_dag_given_to_the_propagator_holds_no_resolved_value(self, provider: _FakeProvider) -> None:
        nodes, node_features, ops = self._two_node_flow()
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value=_mf_mod.VectorDBMetadataFetcher._empty_result(),
        ):
            _, captured = _enrich(nodes=nodes, node_features=node_features, op_by_id=ops)
        assert CANARY not in json.dumps(captured["dag"], default=str)

    def test_response_carries_reference_text_and_no_resolved_value(self, provider: _FakeProvider) -> None:
        nodes, node_features, ops = self._two_node_flow()
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata.fetch",
            return_value=_mf_mod.VectorDBMetadataFetcher._empty_result(),
        ):
            response, _ = _enrich(nodes=nodes, node_features=node_features, op_by_id=ops)
        text = json.dumps(response, default=str)
        assert CANARY not in text
        assert _ref("milvus/token") in text
        assert _ref("s3/creds") in text

    def test_failed_node_returns_empty_result_others_still_enriched_and_no_marker(
        self, provider: _FakeProvider
    ) -> None:
        provider.fail = True
        nodes, node_features, ops = self._two_node_flow()
        node_features["ing"][OperatorConstants.Config.OUTPUT_FEATURES] = {"content": _make_feature()}
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as client_cls:
            response, _ = _enrich(nodes=nodes, node_features=node_features, op_by_id=ops)

        client_cls.assert_not_called()
        by_id = {n["id"]: n["parameters"] for n in response["pipelines"][0]["nodes"]}
        assert by_id["vdb"][OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == []
        assert by_id["vdb"][OperatorConstants.VectorDB.STORED_RESOURCE_METADATA] == {
            "vector_similarity": None,
            "dimension_size": None,
        }
        assert "content" in by_id["ing"][OperatorConstants.Config.OUTPUT_FEATURES]
        text = json.dumps(response, default=str).lower()
        for marker in ("resolution_failed", "secret_failed", "unresolved", "_secret"):
            assert marker not in text


# ---------------------------------------------------------------------------
# Tests: enrich_flow_with_features — env expansion wiring
# ---------------------------------------------------------------------------


class TestEnrichFlowWithFeaturesEnvWiring:
    """${ENV_VAR} placeholders are expanded before propagation (step 2)."""

    def test_env_var_expanded_before_propagation(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("TEST_HOST", "resolved-host")

        captured_dag: dict[str, Any] = {}

        def fake_propagate(*, flow_def: dict[str, Any], global_config: dict) -> dict:
            import copy

            captured_dag.update(copy.deepcopy(flow_def))
            return {}

        mock_validator = MagicMock()
        mock_validator.propagate_features_per_node.side_effect = fake_propagate

        with patch(
            "docpipe.core.assets.flows.application.services.flow_enrichment_service.ValidationService"
        ) as mock_vs_cls:
            mock_vs = MagicMock()
            mock_vs._convert_to_dag_flow.return_value = {
                "dag": [{"id": "n1", "name": "vectordb", "config": {"host": "${TEST_HOST}"}}],
                OperatorConstants.Config.GLOBAL_CONFIG: {},
            }
            mock_vs_cls.return_value = mock_vs
            service = FlowEnrichmentService(validator_factory=lambda: mock_validator)

        service.enrich_flow_with_features(flow_definition=_minimal_elyra_flow(("n1", "vectordb")))

        assert captured_dag["dag"][0]["config"]["host"] == "resolved-host"
