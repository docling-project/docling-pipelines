"""Unit tests for VectorDB metadata fetcher.

Covers:
- compute_default_feature_mappings() — all 5 enterprise mapping rules
- VectorDBMetadataFetcher._normalise_feature_mappings() — three input formats
- VectorDBMetadataFetcher._default_feature_mappings_from_features() — wraps compute_
- VectorDBMetadataFetcher._empty_result() — five-key fallback
- VectorDBMetadataFetcher.fetch_metadata() — routing: opensearch delegates, unknown warns
- OpenSearchResourceMetadata._is_supported() — four logic branches
- OpenSearchResourceMetadata._stored_metadata() — _meta priority chain
- OpenSearchResourceMetadata._resolve_feature_mappings() — four sources priority chain
"""

from unittest.mock import MagicMock, patch

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.resource_metadata import (
    OpenSearchResourceMetadata,
)
from docpipe.core.operators.vectordb.metadata_fetcher import (
    VectorDBMetadataFetcher,
    compute_default_feature_mappings,
)
from docpipe.utils.operators.vectordb_utils import feature_mapping_lookup


def _lookup(result: list[dict], key: str) -> str | None:
    """Helper: look up a feature_name in the returned list-of-dicts."""
    return feature_mapping_lookup(result, key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feature(
    *,
    available_for_vector_db: bool = True,
    is_primary: bool = False,
    mandatory_for_vector_db: bool = False,
    tags: list[str] | None = None,
    type_: str = "string",
) -> dict:
    f: dict = {
        OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: available_for_vector_db,
        OperatorConstants.Misc.IS_PRIMARY: is_primary,
        OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB: mandatory_for_vector_db,
        OperatorConstants.Misc.TAGS: tags or [],
        OperatorConstants.Misc.TYPE: type_,
    }
    return f


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 1: primary → "pk"
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule1Primary:
    """Rule 1: is_primary=True → "pk" (flow JSON format)."""

    def test_is_primary_true_maps_to_pk(self):
        feats = {"doc_hash": _feature(is_primary=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "doc_hash") == "pk"

    def test_primary_tag_maps_to_pk(self):
        """Propagator snapshot format: 'primary' in tags list."""
        feats = {"doc_hash": _feature(tags=["primary"])}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "doc_hash") == "pk"

    def test_only_first_primary_is_mapped(self):
        """Only one feature should get the 'pk' mapping even if two are marked primary."""
        feats = {
            "a": _feature(is_primary=True),
            "b": _feature(is_primary=True),
        }
        pk_values = [
            e["mapped_column_name"] for e in compute_default_feature_mappings(feats) if e["mapped_column_name"] == "pk"
        ]
        assert len(pk_values) == 1

    def test_non_primary_not_mapped_to_pk(self):
        feats = {"content": _feature()}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "content") != "pk"


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 2: "id" → "document_id"
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule2Id:
    """Rule 2: feature named 'id' → 'document_id'."""

    def test_id_feature_maps_to_document_id(self):
        feats = {OperatorConstants.Columns.ID: _feature()}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, OperatorConstants.Columns.ID) == "document_id"

    def test_id_already_primary_skips_document_id(self):
        """If 'id' is also the primary feature, it is already consumed by Rule 1."""
        feats = {OperatorConstants.Columns.ID: _feature(is_primary=True)}
        result = compute_default_feature_mappings(feats)
        # Rule 1 maps it to "pk"; Rule 2 must NOT override to "document_id"
        assert _lookup(result, OperatorConstants.Columns.ID) == "pk"


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 3: "name" → "document_name"
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule3Name:
    """Rule 3: feature named 'name' → 'document_name'."""

    def test_name_feature_maps_to_document_name(self):
        feats = {OperatorConstants.Columns.NAME: _feature()}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, OperatorConstants.Columns.NAME) == "document_name"

    def test_name_already_primary_skips_document_name(self):
        feats = {OperatorConstants.Columns.NAME: _feature(is_primary=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, OperatorConstants.Columns.NAME) == "pk"


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 4: first vector → "vector_embeddings"
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule4Vector:
    """Rule 4: first feature with type=vector → 'vector_embeddings'."""

    def test_vector_feature_maps_to_vector_embeddings(self):
        feats = {"embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "embeddings") == "vector_embeddings"

    def test_only_first_vector_feature_gets_special_mapping(self):
        feats = {
            "vec1": _feature(type_=OperatorConstants.Types.TYPE_VECTOR),
            "vec2": _feature(type_=OperatorConstants.Types.TYPE_VECTOR),
        }
        result = compute_default_feature_mappings(feats)
        vec_embedding_values = [e["feature_name"] for e in result if e["mapped_column_name"] == "vector_embeddings"]
        assert len(vec_embedding_values) == 1

    def test_non_vector_type_not_mapped_to_vector_embeddings(self):
        feats = {"content": _feature(type_="string")}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "content") != "vector_embeddings"


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 5: Milvus sparse path
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule5Sparse:
    """Rule 5: Milvus-only sparse path — only fires when add_sparse_vector=True."""

    def test_sparse_feature_maps_to_sparse_embeddings(self):
        feats = {"sparse_embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR_SPARSE)}
        result = compute_default_feature_mappings(feats, add_sparse_vector=True)
        assert _lookup(result, "sparse_embeddings") == OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT

    def test_content_maps_to_text_when_sparse(self):
        feats = {"content": _feature(type_="string")}
        result = compute_default_feature_mappings(feats, add_sparse_vector=True)
        assert _lookup(result, "content") == "text"

    def test_custom_content_column_maps_to_text(self):
        feats = {"my_text": _feature(type_="string")}
        result = compute_default_feature_mappings(feats, add_sparse_vector=True, content_column="my_text")
        assert _lookup(result, "my_text") == "text"

    def test_sparse_path_skipped_when_add_sparse_vector_false(self):
        feats = {
            "sparse_embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR_SPARSE),
            "content": _feature(type_="string"),
        }
        result = compute_default_feature_mappings(feats, add_sparse_vector=False)
        assert _lookup(result, "sparse_embeddings") is None
        assert _lookup(result, "content") is None

    def test_content_not_duplicated_if_already_covered(self):
        # If content is also a primary key (unlikely but defensive), Rule 1 owns it
        feats = {"content": _feature(is_primary=True)}
        result = compute_default_feature_mappings(feats, add_sparse_vector=True)
        assert _lookup(result, "content") == "pk"
        assert [e["mapped_column_name"] for e in result].count("text") == 0


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — Rule 6: mandatory_for_vector_db safety net
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsRule6Mandatory:
    """Rule 6: mandatory_for_vector_db=True features are always included via identity mapping.

    available_for_vector_db=True alone is NOT enough — users must add those explicitly.
    """

    def test_mandatory_feature_maps_to_itself(self):
        feats = {"custom_required": _feature(mandatory_for_vector_db=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "custom_required") == "custom_required"

    def test_available_for_vector_db_only_feature_not_included(self):
        feats = {"title": _feature(available_for_vector_db=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "title") is None

    def test_mandatory_already_covered_by_rule1_not_duplicated(self):
        # primary key is already Rule 1; Rule 5 must not re-add it under its own name
        feats = {"doc_hash": _feature(is_primary=True, mandatory_for_vector_db=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "doc_hash") == "pk"
        assert [e["mapped_column_name"] for e in result].count("doc_hash") == 0

    def test_mandatory_already_covered_by_rule4_not_duplicated(self):
        # vector type is already Rule 4; Rule 5 must not re-add it as identity
        feats = {"embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR, mandatory_for_vector_db=True)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "embeddings") == "vector_embeddings"

    def test_empty_features_returns_empty_list(self):
        assert compute_default_feature_mappings({}) == []


# ---------------------------------------------------------------------------
# compute_default_feature_mappings — combined scenarios
# ---------------------------------------------------------------------------


class TestComputeDefaultFeatureMappingsCombined:
    """Full feature set exercises all six rules."""

    def test_full_feature_set_all_rules_applied(self):
        feats = {
            "doc_hash": _feature(is_primary=True, available_for_vector_db=True, mandatory_for_vector_db=True),
            OperatorConstants.Columns.ID: _feature(available_for_vector_db=True),
            OperatorConstants.Columns.NAME: _feature(available_for_vector_db=True),
            "embeddings": _feature(
                type_=OperatorConstants.Types.TYPE_VECTOR, available_for_vector_db=True, mandatory_for_vector_db=True
            ),
            "content": _feature(available_for_vector_db=True),
        }
        result = compute_default_feature_mappings(feats)

        assert _lookup(result, "doc_hash") == "pk"
        assert _lookup(result, OperatorConstants.Columns.ID) == "document_id"
        assert _lookup(result, OperatorConstants.Columns.NAME) == "document_name"
        assert _lookup(result, "embeddings") == "vector_embeddings"
        assert _lookup(result, "content") is None

    def test_full_milvus_sparse_feature_set(self):
        feats = {
            "doc_hash": _feature(is_primary=True, mandatory_for_vector_db=True),
            OperatorConstants.Columns.ID: _feature(available_for_vector_db=True),
            OperatorConstants.Columns.NAME: _feature(available_for_vector_db=True),
            "embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR, mandatory_for_vector_db=True),
            "sparse_embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR_SPARSE),
            "content": _feature(type_="string"),
        }
        result = compute_default_feature_mappings(feats, add_sparse_vector=True)

        assert _lookup(result, "doc_hash") == "pk"
        assert _lookup(result, OperatorConstants.Columns.ID) == "document_id"
        assert _lookup(result, OperatorConstants.Columns.NAME) == "document_name"
        assert _lookup(result, "embeddings") == "vector_embeddings"
        assert _lookup(result, "sparse_embeddings") == OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT
        assert _lookup(result, "content") == "text"

    def test_non_typed_mandatory_feature_included_via_rule6(self):
        # A hypothetical future mandatory feature that is neither primary nor vector
        feats = {
            "doc_hash": _feature(is_primary=True, mandatory_for_vector_db=True),
            "embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR, mandatory_for_vector_db=True),
            "acl_field": _feature(mandatory_for_vector_db=True),
        }
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "doc_hash") == "pk"
        assert _lookup(result, "embeddings") == "vector_embeddings"
        assert _lookup(result, "acl_field") == "acl_field"


# ---------------------------------------------------------------------------
# VectorDBMetadataFetcher._normalise_feature_mappings
# ---------------------------------------------------------------------------


class TestNormaliseFeatureMappings:
    """_normalise_feature_mappings accepts only canonical list-of-dicts."""

    def test_list_of_dicts_with_both_keys_passed_through(self):
        raw = [
            {"feature_name": "feat_a", "mapped_column_name": "col_a"},
            {"feature_name": "feat_b", "mapped_column_name": "col_b"},
        ]
        result = VectorDBMetadataFetcher._normalise_feature_mappings(raw)
        assert result == raw

    def test_list_of_dicts_missing_mapped_column_name_filtered(self):
        raw = [{"feature_name": "feat_a"}]
        result = VectorDBMetadataFetcher._normalise_feature_mappings(raw)
        assert result == []

    def test_list_of_dicts_missing_feature_name_filtered(self):
        raw = [{"mapped_column_name": "col_a"}]
        result = VectorDBMetadataFetcher._normalise_feature_mappings(raw)
        assert result == []

    def test_empty_list_returns_empty_list(self):
        assert VectorDBMetadataFetcher._normalise_feature_mappings([]) == []

    def test_non_list_returns_empty_list(self):
        assert VectorDBMetadataFetcher._normalise_feature_mappings(None) == []

    def test_mixed_list_filters_invalid_entries(self):
        raw = [
            {"feature_name": "feat_a", "mapped_column_name": "col_a"},
            {"feature_name": "feat_b"},  # missing mapped_column_name
        ]
        result = VectorDBMetadataFetcher._normalise_feature_mappings(raw)
        assert result == [{"feature_name": "feat_a", "mapped_column_name": "col_a"}]


# ---------------------------------------------------------------------------
# VectorDBMetadataFetcher._empty_result
# ---------------------------------------------------------------------------


class TestEmptyResult:
    """_empty_result returns five-key fallback dict."""

    def test_empty_result_has_all_five_keys(self):
        result = VectorDBMetadataFetcher._empty_result()
        assert OperatorConstants.VectorDB.AVAILABLE_RESOURCES in result
        assert OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA in result
        assert OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE in result
        assert OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE in result
        assert OperatorConstants.VectorDB.STORED_RESOURCE_METADATA in result

    def test_empty_result_defaults_are_empty_or_none(self):
        result = VectorDBMetadataFetcher._empty_result()
        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == []
        assert result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA] == {}
        assert result[OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE] == []
        assert result[OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE] == {}
        stored = result[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA]
        assert stored["vector_similarity"] is None
        assert stored["dimension_size"] is None


# ---------------------------------------------------------------------------
# VectorDBMetadataFetcher.fetch_metadata — routing
# ---------------------------------------------------------------------------


class TestFetchMetadataRouting:
    """fetch_metadata delegates to the right adapter or falls back on unknown."""

    def test_unknown_adapter_returns_empty_result(self):
        fetcher = VectorDBMetadataFetcher()
        result = fetcher.fetch_metadata(
            adapter_name="unknown_db",
            operator_config={},
            available_features={},
        )
        assert result == VectorDBMetadataFetcher._empty_result()

    def test_opensearch_delegates_to_opensearch_resource_metadata(self):
        fetcher = VectorDBMetadataFetcher()
        expected = VectorDBMetadataFetcher._empty_result()

        # OpenSearchResourceMetadata is lazy-imported inside fetch_metadata; patch it
        # at its definition location (not the metadata_fetcher module).
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.opensearch.resource_metadata.OpenSearchResourceMetadata"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance.fetch.return_value = expected
            mock_cls.return_value = mock_instance

            result = fetcher.fetch_metadata(
                adapter_name=OperatorConstants.VectorDB.OPENSEARCH,
                operator_config={OperatorConstants.Config.PROVIDER_CONFIG: {"host": "localhost"}},
                available_features={},
            )

        assert result is expected
        mock_instance.fetch.assert_called_once()

    def test_unknown_adapter_logs_warning(self):
        fetcher = VectorDBMetadataFetcher()
        with patch("docpipe.core.operators.vectordb.metadata_fetcher.logger") as mock_logger:
            fetcher.fetch_metadata(
                adapter_name="unsupported_db",
                operator_config={},
                available_features={},
            )
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert any("unsupported_db" in str(a) for a in call_args)

    def test_milvus_delegates_to_milvus_resource_metadata(self):
        fetcher = VectorDBMetadataFetcher()
        expected = VectorDBMetadataFetcher._empty_result()

        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata.MilvusResourceMetadata"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance.fetch.return_value = expected
            mock_cls.return_value = mock_instance

            result = fetcher.fetch_metadata(
                adapter_name=OperatorConstants.VectorDB.MILVUS,
                operator_config={
                    OperatorConstants.Config.PROVIDER_CONFIG: {"host": "localhost", "auth_type": "standalone"}
                },
                available_features={},
            )

        assert result is expected
        mock_instance.fetch.assert_called_once()

    def test_milvus_constant_equals_expected_string(self):
        assert OperatorConstants.VectorDB.MILVUS == "milvus"

    def test_fetch_passes_provider_config_to_adapter(self):
        """fetch_metadata extracts provider_config from operator_config and forwards it."""
        fetcher = VectorDBMetadataFetcher()
        provider_cfg = {"host": "localhost", "port": 9200}
        op_cfg = {OperatorConstants.Config.PROVIDER_CONFIG: provider_cfg}

        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.opensearch.resource_metadata.OpenSearchResourceMetadata"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance.fetch.return_value = VectorDBMetadataFetcher._empty_result()
            mock_cls.return_value = mock_instance

            fetcher.fetch_metadata(
                adapter_name=OperatorConstants.VectorDB.OPENSEARCH,
                operator_config=op_cfg,
                available_features={},
            )

        call_kwargs = mock_instance.fetch.call_args.kwargs
        assert call_kwargs["provider_config"] == provider_cfg
        assert call_kwargs["operator_config"] is op_cfg


# ---------------------------------------------------------------------------
# OpenSearchResourceMetadata.fetch()
# ---------------------------------------------------------------------------


class TestOpenSearchResourceMetadataFetch:
    """Tests for OpenSearchResourceMetadata.fetch() — the full connection path."""

    def _make_injected(self):
        """Return the four callable injections used by fetch()."""
        fetcher = VectorDBMetadataFetcher()
        return {
            "normalise_feature_mappings": fetcher._normalise_feature_mappings,
            "default_feature_mappings_from_features": fetcher._default_feature_mappings_from_features,
            "empty_result": fetcher._empty_result,
        }

    def _call(self, *, provider_config, operator_config=None, available_features=None):
        inj = self._make_injected()
        return OpenSearchResourceMetadata().fetch(
            provider_config=provider_config,
            operator_config=operator_config or {},
            available_features=available_features or {},
            normalise_feature_mappings=inj["normalise_feature_mappings"],
            default_feature_mappings_from_features=inj["default_feature_mappings_from_features"],
            empty_result=inj["empty_result"],
        )

    def test_returns_empty_result_when_host_absent(self):
        """No host in provider_config → returns empty_result immediately."""
        result = self._call(provider_config={})
        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == []
        assert result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA] == {}
        assert result[OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE] == {}

    def test_returns_empty_result_on_connection_failure(self):
        """Exception during client construction → returns empty_result."""
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.side_effect = Exception("connection refused")
            result = self._call(provider_config={"host": "localhost"})
        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == []

    def test_happy_path_no_index_configured(self):
        """Connected, no index_name → resources listed, empty schema."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = [
            {"index": "my-index"},
            {"index": ".system-index"},  # dot-prefixed must be filtered
        ]
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost"})

        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == ["my-index"]
        assert result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA] == {}
        assert result[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA] == {
            "vector_similarity": None,
            "dimension_size": None,
        }
        mock_client.indices.get_mapping.assert_not_called()

    def test_happy_path_index_present_fetches_schema_and_stored_metadata(self):
        """index_name in available resources → mapping fetched, schema populated."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = [{"index": "docs-index"}]
        mock_client.indices.get_mapping.return_value = {
            "docs-index": {
                "mappings": {
                    "_meta": {"vector_similarity": "cosine", "dimension_size": 768},
                    "properties": {
                        "embedding": {"type": "knn_vector", "dimension": 768},
                        "content": {"type": "text"},
                    },
                }
            }
        }
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost", "index_name": "docs-index"})

        assert "embedding" in result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA]
        assert result[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA]["vector_similarity"] == "cosine"
        assert result[OperatorConstants.VectorDB.STORED_RESOURCE_METADATA]["dimension_size"] == 768
        assert result[OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE]["supported"] is True
        mock_client.indices.get_mapping.assert_called_once_with(index="docs-index")

    def test_index_not_in_resources_skips_mapping_call(self):
        """index_name not present in cluster → no get_mapping call, empty schema."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = [{"index": "other-index"}]
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost", "index_name": "missing-index"})

        assert result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA] == {}
        assert result[OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE]["supported"] is True
        mock_client.indices.get_mapping.assert_not_called()

    def test_system_indices_filtered_from_available_resources(self):
        """Dot-prefixed system indices are excluded from available_resources."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = [
            {"index": "user-index"},
            {"index": ".kibana"},
            {"index": ".opensearch-dashboards"},
            {"index": "another-index"},
        ]
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost"})

        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == ["user-index", "another-index"]

    def test_all_five_keys_present_in_result(self):
        """fetch() always returns all five expected keys."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = []
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost"})

        expected_keys = {
            OperatorConstants.VectorDB.AVAILABLE_RESOURCES,
            OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA,
            OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE,
            OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE,
            OperatorConstants.VectorDB.STORED_RESOURCE_METADATA,
        }
        assert expected_keys == set(result.keys())

    def test_get_mapping_called_only_once(self):
        """Mapping is fetched once and reused — no redundant network calls."""
        mock_client = MagicMock()
        mock_client.cat.indices.return_value = [{"index": "docs-index"}]
        mock_client.indices.get_mapping.return_value = {"docs-index": {"mappings": {"properties": {}}}}
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearchClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            self._call(provider_config={"host": "localhost", "index_name": "docs-index"})

        mock_client.indices.get_mapping.assert_called_once()


# ---------------------------------------------------------------------------
# OpenSearchResourceMetadata._is_supported
# ---------------------------------------------------------------------------


class TestIsSupported:
    """_is_supported uses the pre-fetched mapping dict — no additional network call."""

    def test_empty_index_name_is_supported(self):
        result = OpenSearchResourceMetadata._is_supported(index_name="", available_resources=[], mapping={})
        assert result["supported"] is True

    def test_index_not_in_resources_is_supported(self):
        result = OpenSearchResourceMetadata._is_supported(
            index_name="new_index", available_resources=["other_index"], mapping={}
        )
        assert result["supported"] is True
        assert result["index_name"] == "new_index"

    def test_existing_index_with_knn_vector_is_supported(self):
        mapping = {
            "my_index": {
                "mappings": {
                    "properties": {"vector_embeddings": {"type": OperatorConstants.VectorDB.SCHEMA_KEY_KNN_VECTOR}}
                }
            }
        }
        result = OpenSearchResourceMetadata._is_supported(
            index_name="my_index", available_resources=["my_index"], mapping=mapping
        )
        assert result["supported"] is True

    def test_existing_index_without_knn_vector_is_not_supported(self):
        mapping = {"my_index": {"mappings": {"properties": {"title": {"type": "text"}}}}}
        result = OpenSearchResourceMetadata._is_supported(
            index_name="my_index", available_resources=["my_index"], mapping=mapping
        )
        assert result["supported"] is False
        assert "reason" in result

    def test_empty_mapping_for_existing_index_returns_unsupported(self):
        """mapping={} for an index that is in available_resources → no knn field → unsupported."""
        result = OpenSearchResourceMetadata._is_supported(
            index_name="my_index", available_resources=["my_index"], mapping={}
        )
        assert result["supported"] is False


# ---------------------------------------------------------------------------
# OpenSearchResourceMetadata._stored_metadata
# ---------------------------------------------------------------------------


class TestStoredMetadata:
    """_stored_metadata reads from _meta first, falls back to knn_vector field."""

    def test_reads_from_meta_block_when_present(self):
        mapping = {
            "idx": {
                "mappings": {
                    "_meta": {"vector_similarity": "cosine", "dimension_size": 768},
                    "properties": {},
                }
            }
        }
        result = OpenSearchResourceMetadata._stored_metadata(index_name="idx", mapping=mapping)
        assert result["vector_similarity"] == "cosine"
        assert result["dimension_size"] == 768

    def test_falls_back_to_knn_vector_field_when_meta_absent(self):
        mapping = {
            "idx": {
                "mappings": {
                    "properties": {
                        "vec": {
                            "type": OperatorConstants.VectorDB.SCHEMA_KEY_KNN_VECTOR,
                            "dimension": 512,
                            "method": {"space_type": "l2"},
                        }
                    }
                }
            }
        }
        result = OpenSearchResourceMetadata._stored_metadata(index_name="idx", mapping=mapping)
        assert result["vector_similarity"] == "l2"
        assert result["dimension_size"] == 512

    def test_returns_none_when_neither_source_present(self):
        mapping: dict = {"idx": {"mappings": {"properties": {}}}}
        result = OpenSearchResourceMetadata._stored_metadata(index_name="idx", mapping=mapping)
        assert result["vector_similarity"] is None
        assert result["dimension_size"] is None


# ---------------------------------------------------------------------------
# OpenSearchResourceMetadata._resolve_feature_mappings — priority chain
# ---------------------------------------------------------------------------


class TestResolveFeatureMappings:
    """_resolve_feature_mappings follows the four-source priority chain."""

    def _call(
        self,
        *,
        operator_config: dict | None = None,
        available_features: dict | None = None,
        index_name: str = "",
        available_resources: list | None = None,
        mapping: dict | None = None,
    ) -> list:
        return OpenSearchResourceMetadata._resolve_feature_mappings(
            operator_config=operator_config or {},
            available_features=available_features or {},
            index_name=index_name,
            available_resources=available_resources or [],
            mapping=mapping or {},
            normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
            default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
        )

    def test_source1_opensearch_feature_mappings_takes_priority(self):
        saved = [{"feature_name": "feat", "mapped_column_name": "col"}]
        config = {
            OperatorConstants.VectorDB.OPENSEARCH_FEATURE_MAPPINGS: saved,
            OperatorConstants.Config.FEATURE_MAPPINGS: [{"feature_name": "other", "mapped_column_name": "other_col"}],
        }
        result = self._call(operator_config=config)
        assert result == saved

    def test_source2_generic_feature_mappings_fallback(self):
        saved = [{"feature_name": "feat", "mapped_column_name": "col"}]
        config = {OperatorConstants.Config.FEATURE_MAPPINGS: saved}
        result = self._call(operator_config=config)
        assert result == saved

    def test_source3_meta_stored_mappings_used_when_index_exists(self):
        stored = [{"feature_name": "feat", "mapped_column_name": "col"}]
        mapping = {"my_index": {"mappings": {"_meta": {OperatorConstants.Config.FEATURE_MAPPINGS: stored}}}}
        result = self._call(
            index_name="my_index",
            available_resources=["my_index"],
            mapping=mapping,
        )
        assert result == stored

    def test_source4_defaults_from_available_features_when_no_saved(self):
        feats = {OperatorConstants.Columns.ID: _feature(available_for_vector_db=True)}
        result = self._call(available_features=feats)
        assert any(d["mapped_column_name"] == "document_id" for d in result)

    def test_empty_fallback_when_no_features_and_no_config(self):
        result = self._call()
        assert result == []


# ---------------------------------------------------------------------------
# MilvusResourceMetadata
# ---------------------------------------------------------------------------


class TestMilvusResourceMetadata:
    """Tests for MilvusResourceMetadata — mirrors the spec's TestMilvus class."""

    from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import (
        MilvusResourceMetadata,
    )

    # helpers shared across tests
    def _fetcher(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        return MilvusResourceMetadata()

    def _call(self, provider_config: dict, operator_config: dict | None = None, available_features: dict | None = None):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        return MilvusResourceMetadata().fetch(
            provider_config=provider_config,
            operator_config=operator_config or {},
            available_features=available_features or {},
            normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
            default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
            empty_result=VectorDBMetadataFetcher._empty_result,
        )

    # ------------------------------------------------------------------
    # Guard checks — skip fetch when connection info is absent
    # ------------------------------------------------------------------

    def test_returns_empty_result_when_no_host_or_uri(self):
        result = self._call(provider_config={})
        assert result == VectorDBMetadataFetcher._empty_result()

    def test_returns_empty_result_on_connection_failure(self):
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as mock_cls:
            mock_cls.return_value.get_client.side_effect = Exception("connection refused")
            result = self._call(provider_config={"host": "bad-host", "auth_type": "standalone"})
        assert result == VectorDBMetadataFetcher._empty_result()

    def test_uri_accepted_in_place_of_host(self):
        """fetch() must proceed to connect when only uri is provided (no host)."""
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as mock_cls:
            mock_cls.return_value.get_client.side_effect = Exception("stop after connect attempt")
            self._call(
                provider_config={
                    "uri": "https://user:key@milvus.host:19530",  # pragma: allowlist secret
                    "auth_type": "uri",
                }
            )
        mock_cls.assert_called_once()

    # ------------------------------------------------------------------
    # available_resources — all collections returned
    # ------------------------------------------------------------------

    def test_available_resources_returns_all_collections(self):
        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["col_a", "col_b", "col_c"]
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(provider_config={"host": "localhost", "auth_type": "standalone"})
        assert result[OperatorConstants.VectorDB.AVAILABLE_RESOURCES] == ["col_a", "col_b", "col_c"]

    # ------------------------------------------------------------------
    # selected_resource_schema — collection column extraction
    # ------------------------------------------------------------------

    def test_selected_resource_schema_empty_when_collection_absent(self):
        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["other_col"]
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(
                provider_config={"host": "localhost", "auth_type": "standalone", "collection_name": "missing_col"}
            )
        assert result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA] == {}

    def test_selected_resource_schema_populated_for_configured_collection(self):
        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["col_a"]
        mock_client.describe_collection.return_value = {
            "fields": [
                {"name": "pk", "dtype": "Int64", "is_primary": True, "description": "primary key"},
                {
                    "name": "vector",
                    "dtype": "FLOAT_VECTOR",
                    "is_primary": False,
                    "description": "",
                    "params": {"dim": 384},
                    "indexes": [{"index_name": "idx", "index_type": "IVF_FLAT", "metric_type": "L2"}],
                },
                {"name": "text", "dtype": "VarChar", "is_primary": False, "description": ""},
            ]
        }
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient") as mock_cls:
            mock_cls.return_value.get_client.return_value = mock_client
            result = self._call(
                provider_config={"host": "localhost", "auth_type": "standalone", "collection_name": "col_a"}
            )
        schema = result[OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA]
        assert "pk" in schema
        assert schema["pk"]["is_primary"] is True
        assert "vector" in schema
        assert schema["vector"]["dimension"] == 384
        assert schema["vector"]["index_created"] is True
        assert schema["vector"]["index_info"]["metric_type"] == "L2"
        assert "text" in schema

    # ------------------------------------------------------------------
    # _stored_metadata
    # ------------------------------------------------------------------

    def test_stored_metadata_from_float_vector_field_with_index(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {
            "pk": {"type": "Int64", "is_primary": True},
            "vector": {
                "type": "FLOAT_VECTOR",
                "dimension": 384,
                "index_info": {"index_name": "idx", "index_type": "IVF_FLAT", "metric_type": "L2"},
                "index_created": True,
            },
        }
        meta = MilvusResourceMetadata._stored_metadata(schema)
        assert meta == {"vector_similarity": "L2", "dimension_size": 384}

    def test_stored_metadata_returns_none_when_no_vector_field(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {"pk": {"type": "Int64", "is_primary": True}}
        meta = MilvusResourceMetadata._stored_metadata(schema)
        assert meta == {"vector_similarity": None, "dimension_size": None}

    def test_stored_metadata_vector_similarity_none_when_no_index(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {"vector": {"type": "FLOAT_VECTOR", "dimension": 512}}
        meta = MilvusResourceMetadata._stored_metadata(schema)
        assert meta["dimension_size"] == 512
        assert meta["vector_similarity"] is None

    # ------------------------------------------------------------------
    # _is_supported
    # ------------------------------------------------------------------

    def test_is_supported_empty_collection_name(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        result = MilvusResourceMetadata._is_supported(collection_name="", available_resources=[], schema={})
        assert result["supported"] is True

    def test_is_supported_collection_not_in_available(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        result = MilvusResourceMetadata._is_supported(collection_name="new_col", available_resources=[], schema={})
        assert result["supported"] is True
        assert result["collection_name"] == "new_col"

    def test_is_supported_no_float_vector_field(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {"pk": {"type": "INT64", "is_primary": True}}
        result = MilvusResourceMetadata._is_supported(collection_name="col", available_resources=["col"], schema=schema)
        assert result["supported"] is False
        assert "FLOAT_VECTOR" in result["reason"]

    def test_is_supported_float_vector_without_index(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {"vector": {"type": "FLOAT_VECTOR", "dimension": 384}}
        result = MilvusResourceMetadata._is_supported(collection_name="col", available_resources=["col"], schema=schema)
        assert result["supported"] is False
        assert "index" in result["reason"]

    def test_is_supported_float_vector_with_index(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        schema = {"vector": {"type": "FLOAT_VECTOR", "dimension": 384, "index_created": True}}
        result = MilvusResourceMetadata._is_supported(collection_name="col", available_resources=["col"], schema=schema)
        assert result["supported"] is True

    # ------------------------------------------------------------------
    # _resolve_feature_mappings — priority chain
    # ------------------------------------------------------------------

    def test_feature_mappings_source1_feature_mappings_key(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        saved = [{"feature_name": "feat", "mapped_column_name": "col"}]
        operator_config = {OperatorConstants.Config.FEATURE_MAPPINGS: saved}
        result = MilvusResourceMetadata._resolve_feature_mappings(
            operator_config=operator_config,
            available_features={},
            selected_resource_schema={},
            normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
            default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
        )
        assert result == saved

    def test_feature_mappings_source3_defaults_new_collection(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        feats = {OperatorConstants.Columns.ID: _feature(available_for_vector_db=True)}
        result = MilvusResourceMetadata._resolve_feature_mappings(
            operator_config={},
            available_features=feats,
            selected_resource_schema={},
            normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
            default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
        )
        assert any(d["mapped_column_name"] == "document_id" for d in result)

    def test_feature_mappings_empty_fallback(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        result = MilvusResourceMetadata._resolve_feature_mappings(
            operator_config={},
            available_features={},
            selected_resource_schema={},
            normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
            default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
        )
        assert result == []


# ---------------------------------------------------------------------------
# MilvusResourceMetadata._dtype_name — enum vs plain string
# ---------------------------------------------------------------------------


class TestMilvusDtypeName:
    """_dtype_name must normalise both pymilvus DataType enums and plain strings.

    Root cause of the original 'no FLOAT_VECTOR field' bug:
    str(DataType.FLOAT_VECTOR) == "101", not "FLOAT_VECTOR".
    _dtype_name() uses .name when the object has that attribute.
    """

    def test_datatype_enum_float_vector_resolved_to_name(self):
        from pymilvus import DataType

        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        assert MilvusResourceMetadata._dtype_name(DataType.FLOAT_VECTOR) == "FLOAT_VECTOR"

    def test_datatype_enum_int64_resolved_to_name(self):
        from pymilvus import DataType

        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        assert MilvusResourceMetadata._dtype_name(DataType.INT64) == "INT64"

    def test_datatype_enum_varchar_resolved_to_name(self):
        from pymilvus import DataType

        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        assert MilvusResourceMetadata._dtype_name(DataType.VARCHAR) == "VARCHAR"

    def test_plain_string_uppercased(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        assert MilvusResourceMetadata._dtype_name("float_vector") == "FLOAT_VECTOR"

    def test_raw_integer_does_not_produce_float_vector(self):
        """Regression: if we used str() on the enum value, 101 → '101', not 'FLOAT_VECTOR'."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        assert "FLOAT_VECTOR" not in MilvusResourceMetadata._dtype_name(101)

    def test_collection_columns_with_datatype_enum_sets_dimension(self):
        """End-to-end: describe_collection fields with real DataType enums are handled."""
        from pymilvus import DataType

        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        desc = {
            "fields": [
                {"name": "pk", "dtype": DataType.INT64, "is_primary": True, "description": ""},
                {
                    "name": "vector",
                    "dtype": DataType.FLOAT_VECTOR,
                    "is_primary": False,
                    "description": "",
                    "params": {"dim": 768},
                    "indexes": [{"index_name": "idx", "index_type": "IVF_FLAT", "metric_type": "COSINE"}],
                },
            ]
        }
        schema = MilvusResourceMetadata._collection_columns(desc)
        assert schema["vector"]["type"] == "FLOAT_VECTOR"
        assert schema["vector"]["dimension"] == 768
        assert schema["vector"]["index_created"] is True
        assert schema["vector"]["index_info"]["metric_type"] == "COSINE"


# ---------------------------------------------------------------------------
# MilvusResourceMetadata._apply_index_info
# ---------------------------------------------------------------------------


class TestMilvusApplyIndexInfo:
    """_apply_index_info enriches FLOAT_VECTOR fields via list_indexes + describe_index.

    This is the fallback for existing Milvus collections where describe_collection
    returns an empty 'indexes' list even though the index exists.
    """

    def _schema_with_vector(self, index_created: bool = False) -> dict:
        entry: dict = {"type": "FLOAT_VECTOR", "is_primary": False, "dimension": 384, "description": ""}
        if index_created:
            entry["index_created"] = True
            entry["index_info"] = {"index_name": "idx", "index_type": "IVF_FLAT", "metric_type": "L2"}
        return {"pk": {"type": "VARCHAR", "is_primary": True}, "vector": entry}

    def test_sets_index_created_when_index_found_on_vector_field(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = ["vector_idx"]
        mock_client.describe_index.return_value = {
            "field_name": "vector",
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
        }
        schema = self._schema_with_vector()
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert schema["vector"]["index_created"] is True
        assert schema["vector"]["index_info"]["metric_type"] == "COSINE"

    def test_does_nothing_when_no_indexes_exist(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = []
        schema = self._schema_with_vector()
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert "index_created" not in schema["vector"]
        mock_client.describe_index.assert_not_called()

    def test_skips_field_when_index_not_on_that_field(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = ["other_idx"]
        mock_client.describe_index.return_value = {"field_name": "other_field"}
        schema = self._schema_with_vector()
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert "index_created" not in schema["vector"]

    def test_skips_non_vector_fields(self):
        """Fields without 'dimension' (non FLOAT_VECTOR) must not be touched."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = ["idx"]
        mock_client.describe_index.return_value = {"field_name": "pk"}
        schema = {"pk": {"type": "VARCHAR", "is_primary": True}}  # no 'dimension' key
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert "index_created" not in schema["pk"]

    def test_does_not_overwrite_already_set_index_created(self):
        """If _collection_columns already set index_created via embedded indexes, skip."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = ["idx"]
        schema = self._schema_with_vector(index_created=True)
        original_info = schema["vector"]["index_info"].copy()
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        mock_client.describe_index.assert_not_called()
        assert schema["vector"]["index_info"] == original_info

    def test_list_indexes_failure_is_silently_ignored(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.side_effect = Exception("network error")
        schema = self._schema_with_vector()
        # Must not raise
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert "index_created" not in schema["vector"]

    def test_describe_index_failure_on_one_index_continues_to_next(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import MilvusResourceMetadata

        mock_client = MagicMock()
        mock_client.list_indexes.return_value = ["bad_idx", "good_idx"]
        mock_client.describe_index.side_effect = [
            Exception("timeout"),  # bad_idx fails
            {"field_name": "vector", "index_type": "IVF_FLAT", "metric_type": "IP"},  # good_idx succeeds
        ]
        schema = self._schema_with_vector()
        MilvusResourceMetadata._apply_index_info(client=mock_client, collection_name="col", schema=schema)
        assert schema["vector"]["index_created"] is True
        assert schema["vector"]["index_info"]["metric_type"] == "IP"


class TestComputeDefaultFeatureMappingsBinaryVector:
    """Rule 4 also maps a packed-bit (vector_binary) feature to vector_embeddings."""

    def test_vector_binary_feature_maps_to_vector_embeddings(self):
        feats = {"embeddings": _feature(type_=OperatorConstants.Types.TYPE_VECTOR_BINARY)}
        result = compute_default_feature_mappings(feats)
        assert _lookup(result, "embeddings") == "vector_embeddings"
