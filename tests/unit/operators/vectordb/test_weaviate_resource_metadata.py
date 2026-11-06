# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WeaviateResourceMetadata (flow enrichment for the Weaviate provider)."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from weaviate.classes.config import DataType, Tokenization, VectorDistances

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.resource_metadata import WeaviateResourceMetadata
from docpipe.core.operators.vectordb.metadata_fetcher import VectorDBMetadataFetcher

VB = OperatorConstants.VectorDB
CLIENT_PATH = "docpipe.core.operators.vectordb.adapters.outbound.weaviate.resource_metadata.WeaviateClient"

FEATURES: dict[str, Any] = {
    "doc_id_hash": {"is_primary": True, "type": "string"},
    "id": {"type": "string"},
    "name": {"type": "string"},
    "content": {"type": "string"},
    "embeddings": {"type": "vector"},
    "sparse_embeddings": {"type": "vector_sparse"},
}
SECRET = "super-secret-key"  # pragma: allowlist secret


def _prop(
    name: str,
    *,
    tokenization: Tokenization = Tokenization.FIELD,
    searchable: bool = True,
    filterable: bool = True,
    data_type: DataType = DataType.TEXT,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=None,
        data_type=data_type,
        tokenization=tokenization,
        index_searchable=searchable,
        index_filterable=filterable,
    )


def _indexed_index(metric: Any = VectorDistances.COSINE) -> SimpleNamespace:
    return SimpleNamespace(skip=False, distance_metric=metric)


def _skipped_index() -> SimpleNamespace:
    return SimpleNamespace(skip=True, distance_metric=VectorDistances.COSINE)


def _vector(index: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(vector_index_config=index)


def _good_props() -> list[SimpleNamespace]:
    return [
        _prop("pk"),
        _prop("document_id"),
        _prop("document_name"),
        _prop("text", tokenization=Tokenization.WORD),
    ]


MAPPINGS = [
    {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
    {"feature_name": "id", "mapped_column_name": "document_id"},
    {"feature_name": "name", "mapped_column_name": "document_name"},
    {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
    {"feature_name": "content", "mapped_column_name": "text"},
]


def _collection(
    *,
    props: list[SimpleNamespace] | None = None,
    vectors: dict[str, SimpleNamespace] | None = None,
    legacy_skip: bool = False,
    stored_vector: dict[str, list[float]] | None = None,
) -> MagicMock:
    collection = MagicMock()
    collection.config.get.return_value = SimpleNamespace(
        properties=_good_props() if props is None else props,
        vector_config=vectors if vectors is not None else {"vector_embeddings": _vector(_indexed_index())},
        vector_index_config=SimpleNamespace(skip=legacy_skip),
    )
    objects = [SimpleNamespace(vector=stored_vector)] if stored_vector is not None else []
    collection.query.fetch_objects.return_value = SimpleNamespace(objects=objects)
    return collection


def _fetch(
    *,
    collection: MagicMock | None = None,
    existing: list[str] | None = None,
    collection_name: str = "Docs",
    operator_config: dict[str, Any] | None = None,
    provider_extra: dict[str, Any] | None = None,
    available_features: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], MagicMock]:
    names = ["Zeta", "Docs", "Alpha"] if existing is None else existing
    sdk_client = MagicMock()
    sdk_client.collections.list_all.return_value = {name: object() for name in names}
    sdk_client.collections.get.return_value = collection
    manager = MagicMock()
    manager.connect.return_value = sdk_client
    provider_config = {
        "host": "localhost",
        "collection_name": collection_name,
        **(provider_extra or {}),
    }
    config = {
        OperatorConstants.Config.PROVIDER_CONFIG: provider_config,
        OperatorConstants.Config.FEATURE_MAPPINGS: MAPPINGS,
        **(operator_config or {}),
    }
    with patch(CLIENT_PATH, return_value=manager):
        result = VectorDBMetadataFetcher().fetch_metadata(
            adapter_name="weaviate",
            operator_config=config,
            available_features=FEATURES if available_features is None else available_features,
        )
    return result, manager


class TestExistingCollection:
    def test_five_keys_with_sampled_dimension_and_distance(self):
        collection = _collection(stored_vector={"vector_embeddings": [0.1] * 384})
        result, manager = _fetch(collection=collection)

        assert set(result) == {
            VB.AVAILABLE_RESOURCES,
            VB.SELECTED_RESOURCE_SCHEMA,
            VB.FEATURE_MAPPINGS_RESPONSE,
            VB.IS_DOCPIPE_SUPPORTED_RESOURCE,
            VB.STORED_RESOURCE_METADATA,
        }
        assert result[VB.AVAILABLE_RESOURCES] == ["Alpha", "Docs", "Zeta"]
        schema = result[VB.SELECTED_RESOURCE_SCHEMA]
        assert schema["vector_embeddings"]["type"] == "VECTOR"
        assert schema["vector_embeddings"]["dimension"] == 384
        assert schema["vector_embeddings"]["index_info"]["metric_type"] == "cosine"
        assert schema["vector_embeddings"]["index_created"] is True
        assert result[VB.STORED_RESOURCE_METADATA] == {"vector_similarity": "cosine", "dimension_size": 384}
        assert result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]["supported"] is True
        manager.close.assert_called_once()

    def test_property_entries_carry_type_primary_and_searchable(self):
        result, _ = _fetch(collection=_collection())
        schema = result[VB.SELECTED_RESOURCE_SCHEMA]

        assert schema["pk"]["type"] == "TEXT"
        assert schema["pk"]["is_primary"] is True
        assert schema["text"]["is_primary"] is False
        assert schema["text"]["index_searchable"] is True
        assert schema["document_id"]["description"] == ""

    def test_dimension_is_none_when_collection_is_empty(self):
        result, _ = _fetch(collection=_collection())
        assert result[VB.SELECTED_RESOURCE_SCHEMA]["vector_embeddings"]["dimension"] is None
        assert result[VB.STORED_RESOURCE_METADATA] == {"vector_similarity": "cosine", "dimension_size": None}

    def test_skipped_vectors_are_not_listed(self):
        collection = _collection(
            vectors={"vector_embeddings": _vector(_indexed_index()), "keyword_only": _vector(_skipped_index())}
        )
        result, _ = _fetch(collection=collection)
        assert "keyword_only" not in result[VB.SELECTED_RESOURCE_SCHEMA]
        assert "vector_embeddings" in result[VB.SELECTED_RESOURCE_SCHEMA]

    @pytest.mark.parametrize(
        ("metric", "expected"),
        [
            (VectorDistances.COSINE, "cosine"),
            (VectorDistances.DOT, "dot"),
            (VectorDistances.L2_SQUARED, "l2-squared"),
            (VectorDistances.MANHATTAN, "manhattan"),
            (VectorDistances.HAMMING, "hamming"),
            ("custom-metric", "custom-metric"),
            (None, None),
        ],
    )
    def test_vector_similarity_is_passed_through(self, metric, expected):
        collection = _collection(vectors={"vector_embeddings": _vector(_indexed_index(metric))})
        result, _ = _fetch(collection=collection)
        assert result[VB.STORED_RESOURCE_METADATA]["vector_similarity"] == expected


class TestSupportedResource:
    def test_empty_name_is_supported(self):
        result, _ = _fetch(collection_name="", collection=None)
        assert result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE] == {"collection_name": "", "supported": True}

    def test_new_name_is_supported_with_default_mappings(self):
        result, _ = _fetch(
            collection_name="Fresh",
            collection=None,
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None},
        )
        assert result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE] == {"collection_name": "Fresh", "supported": True}
        assert result[VB.SELECTED_RESOURCE_SCHEMA] == {}
        assert {"feature_name": "doc_id_hash", "mapped_column_name": "pk"} in result[VB.FEATURE_MAPPINGS_RESPONSE]

    def test_new_name_with_sparse_adds_content_and_sparse_defaults(self):
        result, _ = _fetch(
            collection_name="Fresh",
            collection=None,
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None, VB.ADD_SPARSE_VECTOR: True},
        )
        mappings = result[VB.FEATURE_MAPPINGS_RESPONSE]
        assert {"feature_name": "content", "mapped_column_name": "text"} in mappings
        assert {"feature_name": "sparse_embeddings", "mapped_column_name": "sparse_embeddings"} in mappings

    @pytest.mark.parametrize("add_sparse", [False, True])
    def test_indexed_collection_with_field_tokenized_content_is_unsupported(self, add_sparse):
        props = [*_good_props()[:3], _prop("text", tokenization=Tokenization.FIELD)]
        result, _ = _fetch(
            collection=_collection(props=props),
            operator_config={VB.ADD_SPARSE_VECTOR: add_sparse},
        )
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert "text" in supported["reason"]
        assert supported["sparse_eligible"] is False

    @pytest.mark.parametrize("add_sparse", [False, True])
    def test_indexed_collection_with_word_tokenized_pk_is_unsupported(self, add_sparse):
        props = [_prop("pk", tokenization=Tokenization.WORD), *_good_props()[1:]]
        result, _ = _fetch(
            collection=_collection(props=props),
            operator_config={VB.ADD_SPARSE_VECTOR: add_sparse},
        )
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert "pk" in supported["reason"]

    def test_indexed_collection_is_sparse_eligible_independent_of_flag(self):
        for flag in (False, True):
            result, _ = _fetch(
                collection=_collection(),
                operator_config={VB.ADD_SPARSE_VECTOR: flag},
            )
            supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
            assert supported["supported"] is True
            assert supported["sparse_eligible"] is True

    def test_legacy_indexed_collection_is_unsupported(self):
        result, _ = _fetch(collection=_collection(vectors={}, legacy_skip=False))
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert "legacy" in supported["reason"]


class TestKeywordOnlyCollection:
    @staticmethod
    def _keyword_only_variants() -> list[MagicMock]:
        return [
            _collection(vectors={"keyword_only": _vector(_skipped_index())}),
            _collection(vectors={}, legacy_skip=True),
        ]

    @pytest.mark.parametrize("variant", [0, 1])
    def test_flag_off_is_unsupported_but_sparse_eligible(self, variant):
        collection = self._keyword_only_variants()[variant]
        result, _ = _fetch(collection=collection, operator_config={VB.ADD_SPARSE_VECTOR: False})
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert supported["sparse_eligible"] is True
        assert supported["reason"]

    @pytest.mark.parametrize("variant", [0, 1])
    def test_flag_on_is_supported_with_null_similarity_and_dimension(self, variant):
        collection = self._keyword_only_variants()[variant]
        result, _ = _fetch(collection=collection, operator_config={VB.ADD_SPARSE_VECTOR: True})
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is True
        assert supported["sparse_eligible"] is True
        assert result[VB.STORED_RESOURCE_METADATA] == {"vector_similarity": None, "dimension_size": None}

    @pytest.mark.parametrize("add_sparse", [False, True])
    def test_non_searchable_content_is_ineligible(self, add_sparse):
        props = [*_good_props()[:3], _prop("text", tokenization=Tokenization.WORD, searchable=False)]
        collection = _collection(props=props, vectors={"keyword_only": _vector(_skipped_index())})
        result, _ = _fetch(collection=collection, operator_config={VB.ADD_SPARSE_VECTOR: add_sparse})
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert supported["sparse_eligible"] is False

    @pytest.mark.parametrize("add_sparse", [False, True])
    def test_word_tokenized_pk_is_ineligible(self, add_sparse):
        props = [_prop("pk", tokenization=Tokenization.WORD), *_good_props()[1:]]
        collection = _collection(props=props, vectors={"keyword_only": _vector(_skipped_index())})
        result, _ = _fetch(collection=collection, operator_config={VB.ADD_SPARSE_VECTOR: add_sparse})
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert supported["sparse_eligible"] is False

    def test_missing_content_property_is_ineligible(self):
        props = _good_props()[:3]
        collection = _collection(props=props, vectors={"keyword_only": _vector(_skipped_index())})
        result, _ = _fetch(collection=collection, operator_config={VB.ADD_SPARSE_VECTOR: True})
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert supported["sparse_eligible"] is False


class TestFeatureMappingResolution:
    def test_saved_mappings_win(self):
        saved = [{"feature_name": "content", "mapped_column_name": "body"}]
        result, _ = _fetch(
            collection=_collection(),
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: saved},
        )
        assert result[VB.FEATURE_MAPPINGS_RESPONSE] == saved

    def test_live_schema_is_used_for_existing_collection_without_saved_mappings(self):
        result, _ = _fetch(
            collection=_collection(),
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None},
        )
        mappings = result[VB.FEATURE_MAPPINGS_RESPONSE]
        assert {"feature_name": "doc_id_hash", "mapped_column_name": "pk"} in mappings
        assert {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"} in mappings
        assert {"feature_name": "sparse_embeddings", "mapped_column_name": "sparse_embeddings"} not in mappings

    def test_live_schema_maps_sparse_feature_when_bm25_is_on(self):
        collection = _collection(props=[*_good_props()[:3], _prop("content", tokenization=Tokenization.WORD)])
        result, _ = _fetch(
            collection=collection,
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None, VB.ADD_SPARSE_VECTOR: True},
        )
        mappings = result[VB.FEATURE_MAPPINGS_RESPONSE]
        assert {"feature_name": "content", "mapped_column_name": "content"} in mappings
        assert {"feature_name": "sparse_embeddings", "mapped_column_name": "sparse_embeddings"} in mappings

    def test_defaults_when_live_schema_yields_nothing(self):
        collection = _collection(props=[_prop("unrelated")], vectors={})
        result, _ = _fetch(
            collection=collection,
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None},
        )
        assert {"feature_name": "doc_id_hash", "mapped_column_name": "pk"} in result[VB.FEATURE_MAPPINGS_RESPONSE]

    def test_empty_without_features(self):
        result, _ = _fetch(
            collection=_collection(),
            operator_config={OperatorConstants.Config.FEATURE_MAPPINGS: None},
            available_features={},
        )
        assert result[VB.FEATURE_MAPPINGS_RESPONSE] == []


class TestFailureReporting:
    def test_missing_host_returns_plain_empty_result_without_connecting(self):
        with patch(CLIENT_PATH) as client_cls:
            result = VectorDBMetadataFetcher().fetch_metadata(
                adapter_name="weaviate",
                operator_config={OperatorConstants.Config.PROVIDER_CONFIG: {"collection_name": "Docs"}},
                available_features=FEATURES,
            )
        client_cls.assert_not_called()
        assert result == VectorDBMetadataFetcher._empty_result()
        assert "error" not in result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]

    def test_cloud_without_cluster_url_returns_plain_empty_result(self):
        with patch(CLIENT_PATH) as client_cls:
            result = VectorDBMetadataFetcher().fetch_metadata(
                adapter_name="weaviate",
                operator_config={
                    OperatorConstants.Config.PROVIDER_CONFIG: {"connection_type": "cloud", "host": "ignored"}
                },
                available_features=FEATURES,
            )
        client_cls.assert_not_called()
        assert result == VectorDBMetadataFetcher._empty_result()

    def test_authenticated_plaintext_reports_error_without_connecting(self):
        with patch("weaviate.connect_to_custom") as connect:
            result, _ = self._run_real_client(
                {"host": "localhost", "auth_type": "api_key", "api_key": SECRET, "secure": False}
            )
        connect.assert_not_called()
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert "secure" in supported["error"]
        assert SECRET not in supported["error"]

    def test_connection_error_reports_redacted_error_and_warning(self):
        failure = RuntimeError(f"401 Unauthorized for Bearer {SECRET}")
        with (
            patch("weaviate.connect_to_custom", side_effect=failure),
            patch("docpipe.core.operators.vectordb.adapters.outbound.weaviate.resource_metadata.logger") as log,
        ):
            result, _ = self._run_real_client(
                {"host": "localhost", "auth_type": "api_key", "api_key": SECRET, "secure": True, "grpc_secure": True}
            )
        supported = result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        assert supported["supported"] is False
        assert supported["error"]
        assert SECRET not in supported["error"]
        warning_args = " ".join(str(a) for a in log.warning.call_args[0])
        assert SECRET not in warning_args
        assert result[VB.AVAILABLE_RESOURCES] == []

    def test_listing_failure_reports_error_and_closes_client(self):
        sdk_client = MagicMock()
        sdk_client.collections.list_all.side_effect = RuntimeError("boom")
        manager = MagicMock()
        manager.connect.return_value = sdk_client
        manager._redact.side_effect = lambda text: text
        with patch(CLIENT_PATH, return_value=manager):
            result = WeaviateResourceMetadata().fetch(
                provider_config={"host": "localhost", "collection_name": "Docs"},
                operator_config={},
                available_features=FEATURES,
                normalise_feature_mappings=VectorDBMetadataFetcher._normalise_feature_mappings,
                default_feature_mappings_from_features=VectorDBMetadataFetcher._default_feature_mappings_from_features,
                empty_result=VectorDBMetadataFetcher._empty_result,
            )
        assert result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE] == {"supported": False, "error": "boom"}
        manager.close.assert_called_once()

    def test_reachable_deployment_without_collections_has_no_error(self):
        result, manager = _fetch(existing=[], collection=None, collection_name="Fresh")
        assert result[VB.AVAILABLE_RESOURCES] == []
        assert "error" not in result[VB.IS_DOCPIPE_SUPPORTED_RESOURCE]
        manager.close.assert_called_once()

    @staticmethod
    def _run_real_client(provider_config: dict[str, Any]) -> tuple[dict[str, Any], None]:
        with patch.object(WeaviateClient, "close") as close:
            result = VectorDBMetadataFetcher().fetch_metadata(
                adapter_name="weaviate",
                operator_config={OperatorConstants.Config.PROVIDER_CONFIG: provider_config},
                available_features=FEATURES,
            )
        close.assert_called_once()
        return result, None


class TestClientConstruction:
    def test_provider_config_is_forwarded_to_client(self):
        sdk_client = MagicMock()
        sdk_client.collections.list_all.return_value = {}
        manager = MagicMock()
        manager.connect.return_value = sdk_client
        with patch(CLIENT_PATH, return_value=manager) as client_cls:
            VectorDBMetadataFetcher().fetch_metadata(
                adapter_name="weaviate",
                operator_config={
                    OperatorConstants.Config.PROVIDER_CONFIG: {
                        "host": "wv.local",
                        "port": 9090,
                        "grpc_port": 50099,
                        "collection_name": "Docs",
                        "extra_ignored": "x",
                    }
                },
                available_features=FEATURES,
            )
        kwargs = client_cls.call_args.kwargs
        assert kwargs == {"host": "wv.local", "port": 9090, "grpc_port": 50099}
