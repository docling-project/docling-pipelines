# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Weaviate-specific resource metadata fetcher for flow enrichment.

Fetches live collection metadata from a Weaviate deployment: available collections,
property and vector schema, feature mappings, support check, and stored vector metadata.

Called by VectorDBMetadataFetcher when adapter_name == "weaviate".
"""

from __future__ import annotations

from typing import Any

from weaviate.classes.config import Tokenization

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient, redact_secrets
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.index_manager import CONTENT_NAMES, tokenization_for
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_VECTOR_TYPE = "VECTOR"
_PK = OperatorConstants.VectorDB.DEFAULT_PRIMARY_KEY_FIELD
_CLIENT_KWARG_KEYS: dict[str, str] = {
    "connection_type": OperatorConstants.VectorDB.CONNECTION_TYPE,
    "host": OperatorConstants.VectorDB.HOST,
    "port": OperatorConstants.VectorDB.PORT,
    "secure": OperatorConstants.VectorDB.SECURE,
    "grpc_host": OperatorConstants.VectorDB.GRPC_HOST,
    "grpc_port": OperatorConstants.VectorDB.GRPC_PORT,
    "grpc_secure": OperatorConstants.VectorDB.GRPC_SECURE,
    "cluster_url": OperatorConstants.VectorDB.CLUSTER_URL,
    "auth_type": OperatorConstants.VectorDB.AUTH_TYPE,
    "api_key": OperatorConstants.Config.API_KEY,
    "bearer_token": OperatorConstants.VectorDB.BEARER_TOKEN,
    "username": OperatorConstants.VectorDB.USERNAME,
    "password": OperatorConstants.VectorDB.PASSWORD,
    "timeout_init": OperatorConstants.VectorDB.TIMEOUT_INIT,
    "timeout_query": OperatorConstants.VectorDB.TIMEOUT_QUERY,
    "timeout_insert": OperatorConstants.VectorDB.TIMEOUT_INSERT,
    "skip_init_checks": OperatorConstants.VectorDB.SKIP_INIT_CHECKS,
}


class WeaviateResourceMetadata:
    """Fetches read-only resource metadata from a live Weaviate deployment.

    Used exclusively for flow enrichment. Not involved in the write path.
    """

    def fetch(
        self,
        *,
        provider_config: dict[str, Any],
        operator_config: dict[str, Any],
        available_features: dict[str, Any],
        normalise_feature_mappings: Any,
        default_feature_mappings_from_features: Any,
        empty_result: Any,
    ) -> dict[str, Any]:
        """Fetch all five metadata keys for one Weaviate vectordb node.

        Args:
            provider_config: Connection parameters; collection_name is read from here.
            operator_config: Full operator config dict from the DAG snapshot.
            available_features: Propagated feature map from the DAG snapshot.
            normalise_feature_mappings: Injected by VectorDBMetadataFetcher.
            default_feature_mappings_from_features: Injected by VectorDBMetadataFetcher.
            empty_result: Injected by VectorDBMetadataFetcher; returns the five-key empty dict.

        Returns:
            Dict with five normalised keys. Never raises. A missing host or cluster URL
            returns the plain empty result; any other failure returns it with
            is_docpipe_supported_resource set to ``{"supported": False, "error": <redacted>}``.
        """
        is_cloud = (
            provider_config.get(OperatorConstants.VectorDB.CONNECTION_TYPE)
            == OperatorConstants.VectorDB.CONNECTION_TYPE_CLOUD
        )
        endpoint_key = OperatorConstants.VectorDB.CLUSTER_URL if is_cloud else OperatorConstants.VectorDB.HOST
        if not provider_config.get(endpoint_key):
            logger.debug("Weaviate provider_config missing host/cluster_url - skipping metadata fetch")
            return empty_result()

        client_kwargs = {
            kwarg: provider_config[key]
            for kwarg, key in _CLIENT_KWARG_KEYS.items()
            if provider_config.get(key) is not None
        }
        client_manager = WeaviateClient(**client_kwargs)
        try:
            client = client_manager.connect()
            available_resources = sorted(client.collections.list_all(simple=True))

            collection_name: str = provider_config.get(OperatorConstants.VectorDB.COLLECTION_NAME, "")
            add_sparse = bool(operator_config.get(OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, False))
            schema: dict[str, Any] = {}
            stored: dict[str, Any] = {"vector_similarity": None, "dimension_size": None}
            keyword_only = False
            legacy_indexed = False
            props: dict[str, Any] = {}

            if collection_name and collection_name in available_resources:
                collection = client.collections.get(collection_name)
                cfg = collection.config.get()
                props = {p.name: p for p in (cfg.properties or [])}
                indexed_vectors = {
                    name: vc
                    for name, vc in (cfg.vector_config or {}).items()
                    if not getattr(vc.vector_index_config, "skip", False)
                }
                legacy_skipped = bool(getattr(cfg.vector_index_config, "skip", False))
                keyword_only = not indexed_vectors and (bool(cfg.vector_config) or legacy_skipped)
                legacy_indexed = not indexed_vectors and not keyword_only
                dimensions = self._sample_dimensions(collection=collection, vector_names=list(indexed_vectors))
                schema = self._build_schema(props=props, indexed_vectors=indexed_vectors, dimensions=dimensions)
                stored = self._stored_metadata(schema)

            feature_mappings = self._resolve_feature_mappings(
                operator_config=operator_config,
                available_features=available_features,
                selected_resource_schema=schema,
                props=props,
                normalise_feature_mappings=normalise_feature_mappings,
                default_feature_mappings_from_features=default_feature_mappings_from_features,
            )
            is_supported = self._is_supported(
                collection_name=collection_name,
                available_resources=available_resources,
                props=props,
                has_indexed_vector=any(v.get("type") == _VECTOR_TYPE for v in schema.values()),
                keyword_only=keyword_only,
                legacy_indexed=legacy_indexed,
                add_sparse=add_sparse,
                feature_mappings=feature_mappings,
                available_features=available_features,
            )
            return {
                OperatorConstants.VectorDB.AVAILABLE_RESOURCES: available_resources,
                OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA: schema,
                OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE: feature_mappings,
                OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE: is_supported,
                OperatorConstants.VectorDB.STORED_RESOURCE_METADATA: stored,
            }
        except Exception as exc:
            reason = redact_secrets(text=str(exc), secrets=client_manager.resolved_secrets)
            logger.warning("Failed to fetch Weaviate metadata: %s", reason)
            result = empty_result()
            result[OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE] = {"supported": False, "error": reason}
            return result
        finally:
            client_manager.close()

    @staticmethod
    def _sample_dimensions(*, collection: Any, vector_names: list[str]) -> dict[str, int | None]:
        """Return the dimension of each named vector from one stored object, or None when unknown."""
        dimensions: dict[str, int | None] = dict.fromkeys(vector_names)
        if not vector_names:
            return dimensions
        try:
            objects = collection.query.fetch_objects(limit=1, include_vector=vector_names).objects
            if objects and objects[0].vector:
                for name in vector_names:
                    vector = objects[0].vector.get(name)
                    if vector is not None:
                        dimensions[name] = len(vector)
        except Exception as exc:
            logger.debug("Could not sample vector dimensions: %s", exc)
        return dimensions

    @staticmethod
    def _build_schema(
        *,
        props: dict[str, Any],
        indexed_vectors: dict[str, Any],
        dimensions: dict[str, int | None],
    ) -> dict[str, Any]:
        """Build a name -> schema-entry dict from properties and indexed named vectors."""
        schema: dict[str, Any] = {}
        for name, prop in props.items():
            schema[name] = {
                "type": str(getattr(prop.data_type, "value", prop.data_type)).upper(),
                "is_primary": name == _PK,
                "description": prop.description or "",
                "index_searchable": bool(prop.index_searchable),
            }
        for name, vector_config in indexed_vectors.items():
            index_cfg = vector_config.vector_index_config
            metric = getattr(index_cfg, "distance_metric", None)
            schema[name] = {
                "type": _VECTOR_TYPE,
                "dimension": dimensions.get(name),
                "index_info": {
                    "index_type": type(index_cfg).__name__.removeprefix("_VectorIndexConfig").lower(),
                    "metric_type": getattr(metric, "value", metric),
                },
                "index_created": True,
            }
        return schema

    @staticmethod
    def _stored_metadata(schema: dict[str, Any]) -> dict[str, Any]:
        """Derive vector_similarity and dimension_size from the first indexed vector."""
        for entry in schema.values():
            if entry.get("type") == _VECTOR_TYPE:
                return {
                    "vector_similarity": entry["index_info"]["metric_type"],
                    "dimension_size": entry["dimension"],
                }
        return {"vector_similarity": None, "dimension_size": None}

    @staticmethod
    def _content_property(*, props: dict[str, Any], feature_mappings: list[dict[str, str]]) -> Any:
        """Return the existing property that holds the mapped content, or None."""
        candidates: list[str] = []
        for entry in feature_mappings:
            feature = entry.get(OperatorConstants.Misc.FEATURE_NAME)
            column = entry.get(OperatorConstants.Misc.MAPPED_COLUMN_NAME)
            if column and (feature in CONTENT_NAMES or column in CONTENT_NAMES):
                candidates.append(column)
        candidates.extend(CONTENT_NAMES)
        return next((props[name] for name in candidates if name in props), None)

    @staticmethod
    def _identity_columns(
        *,
        feature_mappings: list[dict[str, str]],
        available_features: dict[str, Any],
    ) -> list[str]:
        """Return columns the runtime creates with field tokenization, in addition to pk."""
        columns: list[str] = []
        for entry in feature_mappings:
            feature = entry.get(OperatorConstants.Misc.FEATURE_NAME)
            column = entry.get(OperatorConstants.Misc.MAPPED_COLUMN_NAME)
            if not feature or not column or column == _PK or feature in CONTENT_NAMES or column in CONTENT_NAMES:
                continue
            meta = available_features.get(feature, {})
            feature_type = meta.get(OperatorConstants.Misc.TYPE) if isinstance(meta, dict) else None
            if (
                tokenization_for(feature_name=feature, column_name=column, feature_type=feature_type)
                == Tokenization.FIELD
            ):
                columns.append(column)
        return columns

    @staticmethod
    def _scalar_problem(
        *,
        props: dict[str, Any],
        identity_columns: list[str],
        content_prop: Any,
        require_content: bool,
    ) -> str | None:
        """Return the first reason the existing scalar properties would be rejected at run time."""
        for column in [_PK, *identity_columns]:
            prop = props.get(column)
            if prop is not None and (prop.tokenization != Tokenization.FIELD or not prop.index_filterable):
                return f"identity property '{column}' must be field-tokenized and filterable"
        if content_prop is None:
            return "no searchable content property" if require_content else None
        if content_prop.tokenization != Tokenization.WORD or not content_prop.index_searchable:
            return f"content property '{content_prop.name}' must be searchable and word-tokenized"
        return None

    @staticmethod
    def _is_supported(
        *,
        collection_name: str,
        available_resources: list[str],
        props: dict[str, Any],
        has_indexed_vector: bool,
        keyword_only: bool,
        legacy_indexed: bool,
        add_sparse: bool,
        feature_mappings: list[dict[str, str]],
        available_features: dict[str, Any],
    ) -> dict[str, Any]:
        """Check whether the configured collection is usable by docpipe.

        An empty or new name is supported. An existing collection is supported when it
        has an indexed vector and passes the scalar checks, or when it is keyword-only,
        BM25 is enabled, and it is BM25-eligible. ``sparse_eligible`` is independent of
        the current flag so the UI can offer the control that makes the collection supported.
        """
        if not collection_name or collection_name not in available_resources:
            return {"collection_name": collection_name, "supported": True}

        result: dict[str, Any] = {"collection_name": collection_name}
        if legacy_indexed:
            return {
                **result,
                "supported": False,
                "reason": "legacy collection with no named vector configurations",
                "sparse_eligible": False,
            }

        identity_columns = WeaviateResourceMetadata._identity_columns(
            feature_mappings=feature_mappings, available_features=available_features
        )
        content_prop = WeaviateResourceMetadata._content_property(props=props, feature_mappings=feature_mappings)
        scalar_problem = WeaviateResourceMetadata._scalar_problem(
            props=props,
            identity_columns=identity_columns,
            content_prop=content_prop,
            require_content=keyword_only,
        )
        bm25_problem = WeaviateResourceMetadata._scalar_problem(
            props=props,
            identity_columns=identity_columns,
            content_prop=content_prop,
            require_content=True,
        )
        result["sparse_eligible"] = (keyword_only or has_indexed_vector) and bm25_problem is None

        if scalar_problem:
            return {**result, "supported": False, "reason": scalar_problem}
        if keyword_only and not add_sparse:
            return {
                **result,
                "supported": False,
                "reason": "keyword-only collection with no indexed vector; enable BM25 sparse retrieval to use it",
            }
        return {**result, "supported": True}

    @staticmethod
    def _resolve_feature_mappings(
        *,
        operator_config: dict[str, Any],
        available_features: dict[str, Any],
        selected_resource_schema: dict[str, Any],
        props: dict[str, Any],
        normalise_feature_mappings: Any,
        default_feature_mappings_from_features: Any,
    ) -> list[dict[str, str]]:
        """Resolve feature mappings: saved mappings, then the live schema, then defaults.

        The live-schema step applies only to an existing collection (non-empty schema):
        pk -> primary feature, first indexed vector -> first vector feature, properties named
        like a feature -> identity, and in BM25 mode the content property and the sparse feature.
        """
        saved = operator_config.get(OperatorConstants.Config.FEATURE_MAPPINGS)
        if saved:
            return normalise_feature_mappings(saved)

        if selected_resource_schema and available_features:
            add_sparse = operator_config.get(OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, False)
            type_key = OperatorConstants.Misc.TYPE

            def _first_feature(feature_type: str) -> str | None:
                return next((n for n, m in available_features.items() if m.get(type_key) == feature_type), None)

            primary_feature = next(
                (
                    n
                    for n, m in available_features.items()
                    if m.get(OperatorConstants.Misc.IS_PRIMARY)
                    or OperatorConstants.Misc.PRIMARY in m.get(OperatorConstants.Misc.TAGS, [])
                ),
                None,
            )
            vector_feature = _first_feature(OperatorConstants.Types.TYPE_VECTOR)
            result: list[dict[str, str]] = []
            covered: set[str] = set()

            def _map(*, feature: str | None, column: str) -> None:
                if feature and feature not in covered:
                    result.append(
                        {
                            OperatorConstants.Misc.FEATURE_NAME: feature,
                            OperatorConstants.Misc.MAPPED_COLUMN_NAME: column,
                        }
                    )
                    covered.add(feature)

            for name, entry in selected_resource_schema.items():
                if entry.get("is_primary"):
                    _map(feature=primary_feature, column=name)
                elif entry.get("type") == _VECTOR_TYPE:
                    _map(feature=vector_feature, column=name)
                elif name in available_features:
                    _map(feature=name, column=name)

            if add_sparse:
                content_prop = next((props[n] for n in CONTENT_NAMES if n in props), None)
                if content_prop is not None and content_prop.index_searchable:
                    content_feature = operator_config.get(
                        OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
                    )
                    if content_feature in available_features:
                        _map(feature=content_feature, column=content_prop.name)
                    _map(
                        feature=_first_feature(OperatorConstants.Types.TYPE_VECTOR_SPARSE),
                        column=OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT,
                    )

            if result:
                return result

        if available_features:
            return default_feature_mappings_from_features(available_features, operator_config)

        return []
