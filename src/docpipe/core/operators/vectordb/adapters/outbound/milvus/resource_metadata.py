"""Milvus-specific resource metadata fetcher for flow enrichment.

Fetches live collection metadata from a Milvus connection: available collections,
field schema, feature mappings, support check, and stored vector metadata.

Called by VectorDBMetadataFetcher when adapter_name == "milvus".
All Milvus imports are lazy so pymilvus is not required at import time.
"""

from __future__ import annotations

from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class MilvusResourceMetadata:
    """Fetches read-only resource metadata from a live Milvus connection.

    Used exclusively for flow enrichment (enrich_flow_features endpoint).
    Not involved in the write path — uses MilvusClient directly rather than
    MilvusAdapter, which is write-path only.

    All helper methods are stateless and receive the raw PyMilvusClient so the
    connection is established once by fetch() and reused across calls.
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
        """Fetch all five metadata keys for one Milvus vectordb node.

        Args:
            provider_config: Connection parameters (host, port, auth_type, …).
                collection_name is also read from here (moved under provider_config).
            operator_config: Full operator config dict from the DAG snapshot.
            available_features: Propagated feature map from the DAG snapshot.
                Used as Source 3 fallback for feature_mappings when no saved
                mappings exist.
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
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.client import MilvusClient

        has_host = bool(provider_config.get(OperatorConstants.VectorDB.HOST))
        has_uri = bool(provider_config.get(OperatorConstants.VectorDB.URI))
        if not (has_host or has_uri):
            logger.debug("Milvus provider_config missing host/uri - skipping metadata fetch")
            return empty_result()

        try:
            client_manager = MilvusClient(
                host=provider_config.get(OperatorConstants.VectorDB.HOST),
                port=int(provider_config.get(OperatorConstants.VectorDB.PORT, 19530)),
                uri=provider_config.get(OperatorConstants.VectorDB.URI),
                token=provider_config.get(OperatorConstants.VectorDB.TOKEN),
                username=provider_config.get(OperatorConstants.VectorDB.USERNAME),
                password=provider_config.get(OperatorConstants.VectorDB.PASSWORD),
                database=provider_config.get(OperatorConstants.VectorDB.DATABASE, "default"),
                auth_type=provider_config.get(OperatorConstants.VectorDB.AUTH_TYPE),
                secure=provider_config.get(OperatorConstants.VectorDB.SECURE, False),
            )
            client = client_manager.get_client()

            available_resources: list[str] = client.list_collections()

            collection_name: str = provider_config.get(OperatorConstants.VectorDB.COLLECTION_NAME, "")
            selected_resource_schema: dict[str, Any] = {}
            stored_resource_metadata: dict[str, Any] = {"vector_similarity": None, "dimension_size": None}

            if collection_name and collection_name in available_resources:
                desc = client.describe_collection(collection_name)
                selected_resource_schema = self._collection_columns(desc)
                # describe_collection does not reliably embed index info inside field
                # entries for existing collections — call list_indexes() separately and
                # mark any FLOAT_VECTOR field that has an index as index_created=True.
                self._apply_index_info(
                    client=client,
                    collection_name=collection_name,
                    schema=selected_resource_schema,
                )
                stored_resource_metadata = self._stored_metadata(selected_resource_schema)

            is_supported = self._is_supported(
                collection_name=collection_name,
                available_resources=available_resources,
                schema=selected_resource_schema,
            )
            feature_mappings = self._resolve_feature_mappings(
                operator_config=operator_config,
                available_features=available_features,
                selected_resource_schema=selected_resource_schema,
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
            logger.warning("Failed to fetch Milvus metadata: %s", exc)
            return empty_result()

    @staticmethod
    def _dtype_name(raw: Any) -> str:
        """Return a normalised uppercase string for a pymilvus dtype value.

        pymilvus returns DataType enum objects whose str() is their integer value
        (e.g. str(DataType.FLOAT_VECTOR) == "101").  Use .name when available so
        comparisons against "FLOAT_VECTOR" work correctly.
        """
        if hasattr(raw, "name"):
            return raw.name.upper()
        return str(raw).upper()

    @staticmethod
    def _collection_columns(desc: dict[str, Any]) -> dict[str, Any]:
        """Build a field-name → schema-entry dict from describe_collection output.

        FLOAT_VECTOR fields additionally carry dimension and index_info so the
        UI can render dimension and metric_type without a separate API call.
        """
        schema: dict[str, Any] = {}
        for field in desc.get("fields", []):
            name = field.get("name")
            if not name:
                continue
            raw_dtype = field.get("dtype", field.get("type", ""))
            dtype = MilvusResourceMetadata._dtype_name(raw_dtype)
            entry: dict[str, Any] = {
                "type": dtype,
                "is_primary": field.get("is_primary", False),
                "description": field.get("description", ""),
            }
            if "FLOAT_VECTOR" in dtype:
                params = field.get("params", {})
                entry["dimension"] = params.get("dim")
                indexes = field.get("indexes", [])
                if indexes:
                    idx = indexes[0]
                    entry["index_info"] = {
                        "index_name": idx.get("index_name"),
                        "index_type": idx.get("index_type"),
                        "metric_type": idx.get("metric_type"),
                    }
                    entry["index_created"] = True
            schema[name] = entry
        return schema

    @staticmethod
    def _apply_index_info(
        *,
        client: Any,
        collection_name: str,
        schema: dict[str, Any],
    ) -> None:
        """Enrich FLOAT_VECTOR fields with index_created=True using list_indexes().

        describe_collection() does not reliably embed index information inside
        field entries for existing collections — the 'indexes' list is often empty
        even when an index exists. This method queries list_indexes() separately
        and marks the corresponding vector field in-place.

        Mutates schema in-place. Silently ignores any errors from list_indexes().
        """
        try:
            index_names: list[str] = client.list_indexes(collection_name)
        except Exception as exc:
            logger.debug("Could not list indexes for collection '%s': %s", collection_name, exc)
            return

        if not index_names:
            return

        for field_name, field_meta in schema.items():
            if "dimension" not in field_meta:
                # Only FLOAT_VECTOR fields have 'dimension' set by _collection_columns
                continue
            if field_meta.get("index_created"):
                # Already marked via embedded indexes list — nothing to do
                continue
            # Check if any index exists on this field by trying describe_index
            for idx_name in index_names:
                try:
                    idx_desc = client.describe_index(collection_name, idx_name)
                    if idx_desc.get("field_name") == field_name:
                        field_meta["index_created"] = True
                        field_meta.setdefault(
                            "index_info",
                            {
                                "index_name": idx_name,
                                "index_type": idx_desc.get("index_type"),
                                "metric_type": idx_desc.get("metric_type"),
                            },
                        )
                        break
                except Exception:  # nosec B112
                    continue

    @staticmethod
    def _stored_metadata(schema: dict[str, Any]) -> dict[str, Any]:
        """Derive vector_similarity and dimension_size from the FLOAT_VECTOR field.

        Scans schema for the first field that carries a 'dimension' key (set by
        _collection_columns for FLOAT_VECTOR fields) and reads metric_type from
        its index_info.
        """
        for field_meta in schema.values():
            if "dimension" in field_meta:
                metric_type = field_meta.get("index_info", {}).get("metric_type")
                return {
                    "vector_similarity": metric_type,
                    "dimension_size": field_meta["dimension"],
                }
        return {"vector_similarity": None, "dimension_size": None}

    @staticmethod
    def _is_supported(
        *,
        collection_name: str,
        available_resources: list[str],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Check whether the configured collection is supported by docpipe.

        Mirrors enterprise is_docpipe_supported_collection logic:
          - empty name           → supported=True (new collection, will be created)
          - not in available     → supported=True (will be created)
          - no FLOAT_VECTOR      → supported=False
          - FLOAT_VECTOR present but no index → supported=False
          - FLOAT_VECTOR with index → supported=True
        """
        if not collection_name:
            return {"collection_name": "", "supported": True}
        if collection_name not in available_resources:
            return {"collection_name": collection_name, "supported": True}

        # "type" is always a normalised uppercase string produced by _dtype_name()
        has_float_vector = any("FLOAT_VECTOR" in f.get("type", "") for f in schema.values())
        if not has_float_vector:
            return {
                "collection_name": collection_name,
                "supported": False,
                "reason": "no FLOAT_VECTOR field",
            }

        has_index = any(f.get("index_created", False) for f in schema.values() if "FLOAT_VECTOR" in f.get("type", ""))
        if not has_index:
            return {
                "collection_name": collection_name,
                "supported": False,
                "reason": "no index on FLOAT_VECTOR field",
            }

        return {"collection_name": collection_name, "supported": True}

    @staticmethod
    def _resolve_feature_mappings(
        *,
        operator_config: dict[str, Any],
        available_features: dict[str, Any],
        selected_resource_schema: dict[str, Any],
        normalise_feature_mappings: Any,
        default_feature_mappings_from_features: Any,
    ) -> list[dict[str, str]]:
        """Resolve feature mappings using the priority chain.

        Milvus has no _meta storage for feature_mappings (unlike OpenSearch), so
        Source 2 derives mappings directly from the live collection schema
        (field type/flag matching) instead of reading stored data.
        selected_resource_schema is non-empty only when the collection already exists.

        Resolution order:
          1. operator_config["feature_mappings"]         — user-saved mappings
          2. live collection schema (existing collection) — non-empty selected_resource_schema:
               - primary field       → feature where is_primary=True or "primary" tag
               - FLOAT_VECTOR field  → feature where type="vector"
               - SPARSE_FLOAT_VECTOR → feature where type="vector_sparse" (add_sparse only)
               - field name matches a feature name → identity mapping
               - any other field     → skipped
          3. defaults from propagated available_features — new collection fallback
          4. []                                          — fallback
        """
        # Source 1 — user-saved mappings
        saved_generic = operator_config.get(OperatorConstants.Config.FEATURE_MAPPINGS)
        if saved_generic:
            return normalise_feature_mappings(saved_generic)

        # Source 2 — existing collection: derive from live schema (no _meta in Milvus).
        # selected_resource_schema is only non-empty when the collection exists.
        if selected_resource_schema and available_features:
            add_sparse = operator_config.get(OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, False)

            primary_feature = next(
                (
                    n
                    for n, m in available_features.items()
                    if m.get(OperatorConstants.Misc.IS_PRIMARY)
                    or OperatorConstants.Misc.PRIMARY in m.get(OperatorConstants.Misc.TAGS, [])
                ),
                None,
            )
            vector_feature = next(
                (
                    n
                    for n, m in available_features.items()
                    if m.get(OperatorConstants.Misc.TYPE) == OperatorConstants.Types.TYPE_VECTOR
                ),
                None,
            )
            sparse_feature = (
                next(
                    (
                        n
                        for n, m in available_features.items()
                        if m.get(OperatorConstants.Misc.TYPE) == OperatorConstants.Types.TYPE_VECTOR_SPARSE
                    ),
                    None,
                )
                if add_sparse
                else None
            )

            result: list[dict[str, str]] = []
            covered: set[str] = set()

            for field_name, field_meta in selected_resource_schema.items():
                field_type: str = field_meta.get("type", "").upper()
                if field_meta.get("is_primary") and primary_feature and primary_feature not in covered:
                    result.append({"feature_name": primary_feature, "mapped_column_name": field_name})
                    covered.add(primary_feature)
                elif "SPARSE_FLOAT_VECTOR" in field_type and sparse_feature and sparse_feature not in covered:
                    result.append({"feature_name": sparse_feature, "mapped_column_name": field_name})
                    covered.add(sparse_feature)
                elif "FLOAT_VECTOR" in field_type and vector_feature and vector_feature not in covered:
                    result.append({"feature_name": vector_feature, "mapped_column_name": field_name})
                    covered.add(vector_feature)
                elif field_name in available_features and field_name not in covered:
                    result.append({"feature_name": field_name, "mapped_column_name": field_name})
                    covered.add(field_name)

            if result:
                return result

        # Source 3 — new collection: derive defaults from propagated available_features
        if available_features:
            return default_feature_mappings_from_features(available_features, operator_config)

        return []
