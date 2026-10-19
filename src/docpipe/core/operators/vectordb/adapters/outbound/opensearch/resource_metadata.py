"""OpenSearch-specific resource metadata fetcher for flow enrichment.

Fetches live index metadata from an OpenSearch connection: available indices,
field schema, feature mappings, support check, and stored vector metadata.

Called by VectorDBMetadataFetcher when adapter_name == "opensearch".
All OpenSearch imports are lazy so opensearch-py is not required at import time.
"""

from __future__ import annotations

from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OpenSearchResourceMetadata:
    """Fetches read-only resource metadata from a live OpenSearch connection.

    Used exclusively for flow enrichment (enrich_flow_features endpoint).
    Not involved in the write path — uses OpenSearchClient directly rather
    than OpenSearchAdapter, which is write-path only and requires index_name
    and available_features at construction time.

    All helper methods are stateless and accept the already-fetched mapping
    dict so get_mapping() is called at most once per fetch() invocation.
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
        """Fetch all five metadata keys for one OpenSearch vectordb node.

        Args:
            provider_config: Connection parameters (host, port, username, …).
                index_name is also read from here (moved under provider_config).
            operator_config: Full operator config dict from the DAG snapshot.
            available_features: Propagated feature map from the DAG snapshot.
                Used as Source 4 fallback for feature_mappings when no saved
                or stored mappings exist.
            normalise_feature_mappings: Callable — converts raw mappings to
                list[dict] format. Injected by VectorDBMetadataFetcher.
            default_feature_mappings_from_features: Callable — computes
                enterprise-style defaults from available_features. Injected
                by VectorDBMetadataFetcher.
            empty_result: Callable — returns the five-key empty fallback dict.
                Injected by VectorDBMetadataFetcher.

        Returns:
            Dict with five normalised keys. Never raises — returns empty_result()
            on any connection failure.
        """
        from docpipe.core.operators.vectordb.adapters.outbound.opensearch.client import OpenSearchClient

        if not provider_config.get(OperatorConstants.VectorDB.HOST):
            logger.debug("OpenSearch provider_config missing host - skipping metadata fetch")
            return empty_result()

        try:
            client_manager = OpenSearchClient(
                host=provider_config.get(OperatorConstants.VectorDB.HOST, "localhost"),
                port=int(provider_config.get(OperatorConstants.VectorDB.PORT, 9200)),
                username=provider_config.get(OperatorConstants.VectorDB.USERNAME),
                password=provider_config.get(OperatorConstants.VectorDB.PASSWORD),
                use_ssl=provider_config.get(OperatorConstants.VectorDB.USE_SSL, False),
                verify_certs=provider_config.get(OperatorConstants.VectorDB.VERIFY_CERTS, False),
                aws_auth=provider_config.get(OperatorConstants.VectorDB.AWS_AUTH, False),
                aws_region=provider_config.get(OperatorConstants.VectorDB.AWS_REGION),
                jwt_token=provider_config.get(OperatorConstants.VectorDB.JWT_TOKEN),
            )
            client = client_manager.get_client()

            # List all non-system indices (filter out dot-prefixed system indices)
            cat_response = client.cat.indices(format="json", h="index")
            available_resources: list[str] = [e["index"] for e in cat_response if not e["index"].startswith(".")]

            index_name: str = provider_config.get(OperatorConstants.VectorDB.INDEX_NAME, "")
            selected_resource_schema: dict[str, Any] = {}
            stored_resource_metadata: dict[str, Any] = {"vector_similarity": None, "dimension_size": None}
            # Fetch mapping once and reuse across schema, stored_metadata,
            # is_supported, and feature_mappings — avoids 3 redundant network calls.
            mapping: dict[str, Any] = {}

            if index_name and index_name in available_resources:
                mapping = client.indices.get_mapping(index=index_name)
                idx_mapping = mapping.get(index_name, {}).get(OperatorConstants.VectorDB.SCHEMA_KEY_MAPPINGS, {})
                selected_resource_schema = idx_mapping.get(OperatorConstants.VectorDB.SCHEMA_KEY_PROPERTIES, {})
                stored_resource_metadata = self._stored_metadata(index_name=index_name, mapping=mapping)

            is_supported = self._is_supported(
                index_name=index_name,
                available_resources=available_resources,
                mapping=mapping,
            )
            feature_mappings = self._resolve_feature_mappings(
                operator_config=operator_config,
                available_features=available_features,
                index_name=index_name,
                available_resources=available_resources,
                mapping=mapping,
                normalise_feature_mappings=normalise_feature_mappings,
                default_feature_mappings_from_features=default_feature_mappings_from_features,
            )

            return {
                OperatorConstants.VectorDB.AVAILABLE_RESOURCES: available_resources,
                OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA: selected_resource_schema,
                OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE: feature_mappings,
                OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE: is_supported,
                OperatorConstants.VectorDB.STORED_RESOURCE_METADATA: stored_resource_metadata,
            }
        except Exception as exc:
            logger.warning("Failed to fetch OpenSearch metadata: %s", exc)
            return empty_result()

    @staticmethod
    def _is_supported(
        *,
        index_name: str,
        available_resources: list[str],
        mapping: dict[str, Any],
    ) -> dict[str, Any]:
        """Check whether the configured index is supported by docpipe.

        Uses the already-fetched mapping dict — no additional network call.

        Logic:
          - empty name  → supported=True  (new index, will be created)
          - not in list → supported=True  (will be created)
          - exists but no knn_vector field → supported=False
          - exists with knn_vector field   → supported=True
        """
        if not index_name:
            return {"index_name": "", "supported": True}
        if index_name not in available_resources:
            return {"index_name": index_name, "supported": True}

        props: dict[str, Any] = (
            mapping.get(index_name, {})
            .get(OperatorConstants.VectorDB.SCHEMA_KEY_MAPPINGS, {})
            .get(OperatorConstants.VectorDB.SCHEMA_KEY_PROPERTIES, {})
        )
        has_knn = any(f.get("type") == OperatorConstants.VectorDB.SCHEMA_KEY_KNN_VECTOR for f in props.values())
        if not has_knn:
            return {
                "index_name": index_name,
                "supported": False,
                "reason": "no knn_vector field found",
            }
        return {"index_name": index_name, "supported": True}

    @staticmethod
    def _stored_metadata(
        *,
        index_name: str,
        mapping: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract vector_similarity and dimension_size from index _meta.

        Resolution priority:
          1. mappings._meta.vector_similarity / dimension_size (written by docpipe)
          2. First knn_vector field's method.space_type / dimension (fallback)
        """
        idx = mapping.get(index_name, {}).get(OperatorConstants.VectorDB.SCHEMA_KEY_MAPPINGS, {})
        meta = idx.get(OperatorConstants.VectorDB.SCHEMA_KEY_META, {})
        vector_similarity = meta.get(OperatorConstants.VectorDB.VECTOR_SIMILARITY_KEY)
        dimension_size = meta.get("dimension_size")

        if vector_similarity is None or dimension_size is None:
            props = idx.get(OperatorConstants.VectorDB.SCHEMA_KEY_PROPERTIES, {})
            for field_def in props.values():
                if field_def.get("type") == OperatorConstants.VectorDB.SCHEMA_KEY_KNN_VECTOR:
                    if vector_similarity is None:
                        vector_similarity = field_def.get("method", {}).get("space_type")
                    if dimension_size is None:
                        dimension_size = field_def.get("dimension")
                    break

        return {"vector_similarity": vector_similarity, "dimension_size": dimension_size}

    @staticmethod
    def _resolve_feature_mappings(
        *,
        operator_config: dict[str, Any],
        available_features: dict[str, Any],
        index_name: str,
        available_resources: list[str],
        mapping: dict[str, Any],
        normalise_feature_mappings: Any,
        default_feature_mappings_from_features: Any,
    ) -> list[dict[str, str]]:
        """Resolve feature mappings using the priority chain.

        Uses the already-fetched mapping dict for Source 3 — no additional
        network call.

        Resolution order:
          1. operator_config["opensearch_feature_mappings"] — user-saved, highest priority
          2. operator_config["feature_mappings"]            — saved mappings key
          3. mappings._meta.feature_mappings                — stored in index by docpipe
          4. defaults computed from propagated available_features
          5. []                                             — fallback
        """
        # Source 1 — adapter-specific saved key
        saved = operator_config.get(OperatorConstants.VectorDB.OPENSEARCH_FEATURE_MAPPINGS)
        if saved:
            return normalise_feature_mappings(saved)

        # Source 2 — generic backward-compat key
        saved_generic = operator_config.get(OperatorConstants.Config.FEATURE_MAPPINGS)
        if saved_generic:
            return normalise_feature_mappings(saved_generic)

        # Source 3 — stored in index _meta (existing index path)
        if index_name and index_name in available_resources:
            stored = (
                mapping.get(index_name, {})
                .get(OperatorConstants.VectorDB.SCHEMA_KEY_MAPPINGS, {})
                .get(OperatorConstants.VectorDB.SCHEMA_KEY_META, {})
                .get(OperatorConstants.Config.FEATURE_MAPPINGS)
            )
            if stored:
                return normalise_feature_mappings(stored)

        # Source 4 — derive defaults from propagated available_features
        if available_features:
            return default_feature_mappings_from_features(available_features, operator_config)

        return []
