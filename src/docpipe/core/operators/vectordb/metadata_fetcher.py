"""Fetches live metadata from VectorDB connections for flow enrichment.

Used by FlowEnrichmentService to populate available_resources,
selected_resource_schema, feature_mappings, is_docpipe_supported_resource,
and stored_resource_metadata on vectordb operator nodes during flow enrichment.

All adapter-specific logic lives in the adapter layer:
  - OpenSearch: adapters/outbound/opensearch/resource_metadata.py
"""

from __future__ import annotations

from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import is_dense_or_binary_vector_feature

logger = get_logger()


def compute_default_feature_mappings(
    available_features: dict[str, Any],
    *,
    add_sparse_vector: bool = False,
    content_column: str = OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
) -> list[dict[str, str]]:
    """Compute default feature-to-column mappings when none are provided by the user.

    Returns a canonical list-of-dicts: [{"feature_name": ..., "mapped_column_name": ...}, ...]

    Rules applied in order:

      1. Feature with is_primary=True OR tagged "primary"  → "pk"
      2. "id"                                              → "document_id"
      3. "name"                                            → "document_name"
      4. First feature with type="vector"                  → "vector_embeddings"
      5. [Milvus, add_sparse_vector=True only]
         Feature with type="vector_sparse"                 → "sparse_embeddings"
         content_column                                    → "text"
      6. Remaining mandatory_for_vector_db=True features   → identity mapping
         (safety net: a DB write would fail without a mapping for these)

    Rule 6 is a defensive addition. In practice every mandatory_for_vector_db feature
    is also a primary key (Rule 1) or a vector type (Rule 4), so it will already be
    covered. Rule 6 ensures future features that are mandatory but typed differently
    are never silently omitted.

    Additional non-mandatory features must be explicitly mapped in the flow definition.

    Args:
        available_features: Propagated feature map from the DAG snapshot.
        add_sparse_vector: When True (Milvus only), adds sparse_embeddings and
            content_column to the defaults.
        content_column: Name of the document content column. Defaults to "content".
            Only used when add_sparse_vector=True.

    The primary check handles two formats:
    - Flow JSON config: ``"is_primary": True`` (set directly on the feature dict)
    - Propagator snapshot: ``"primary"`` tag in the ``"tags"`` list
    """
    result: list[dict[str, str]] = []
    covered: set[str] = set()

    # Rule 1 — primary feature → "pk"
    for name, meta in available_features.items():
        is_primary = meta.get(OperatorConstants.Misc.IS_PRIMARY, False) or (
            OperatorConstants.Misc.PRIMARY in meta.get(OperatorConstants.Misc.TAGS, [])
        )
        if is_primary:
            result.append(
                {
                    OperatorConstants.Misc.FEATURE_NAME: name,
                    OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.VectorDB.DEFAULT_PRIMARY_KEY_FIELD,
                }
            )
            covered.add(name)
            break

    # Rule 2 — "id" → "document_id"
    if OperatorConstants.Columns.ID in available_features and OperatorConstants.Columns.ID not in covered:
        result.append(
            {
                OperatorConstants.Misc.FEATURE_NAME: OperatorConstants.Columns.ID,
                OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.VectorDB.DEFAULT_DOCUMENT_ID_FIELD,
            }
        )
        covered.add(OperatorConstants.Columns.ID)

    # Rule 3 — "name" → "document_name"
    if OperatorConstants.Columns.NAME in available_features and OperatorConstants.Columns.NAME not in covered:
        result.append(
            {
                OperatorConstants.Misc.FEATURE_NAME: OperatorConstants.Columns.NAME,
                OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.VectorDB.DEFAULT_DOCUMENT_NAME_FIELD,
            }
        )
        covered.add(OperatorConstants.Columns.NAME)

    # Rule 4 — first feature with type=vector or vector_binary → "vector_embeddings"
    for name, meta in available_features.items():
        if name not in covered and is_dense_or_binary_vector_feature(feature_config=meta):
            result.append(
                {
                    OperatorConstants.Misc.FEATURE_NAME: name,
                    OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.Columns.DENSE_EMBEDDINGS_COLUMN_DEFAULT,
                }
            )
            covered.add(name)
            break

    # Rule 5 — Milvus sparse path (add_sparse_vector=True only)
    if add_sparse_vector:
        for name, meta in available_features.items():
            if (
                name not in covered
                and meta.get(OperatorConstants.Misc.TYPE) == OperatorConstants.Types.TYPE_VECTOR_SPARSE
            ):
                result.append(
                    {
                        OperatorConstants.Misc.FEATURE_NAME: name,
                        OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT,
                    }
                )
                covered.add(name)
                break
        if content_column in available_features and content_column not in covered:
            result.append(
                {
                    OperatorConstants.Misc.FEATURE_NAME: content_column,
                    OperatorConstants.Misc.MAPPED_COLUMN_NAME: OperatorConstants.VectorDB.DEFAULT_TEXT_FIELD_NAME,
                }
            )
            covered.add(content_column)

    # Rule 6 — remaining mandatory_for_vector_db=True → identity mapping
    for name, meta in available_features.items():
        if name not in covered and meta.get(OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB, False):
            result.append({OperatorConstants.Misc.FEATURE_NAME: name, OperatorConstants.Misc.MAPPED_COLUMN_NAME: name})
            covered.add(name)

    return result


class VectorDBMetadataFetcher:
    """Thin router — dispatches metadata fetch requests to adapter-specific fetchers.

    Each adapter's read-only metadata logic lives in its own module:
      - opensearch: adapters/outbound/opensearch/resource_metadata.OpenSearchResourceMetadata

    This class owns only the shared helpers (_normalise_feature_mappings,
    _default_feature_mappings_from_features, _empty_result) and injects them
    into each adapter fetcher so the normalisation logic stays in one place.

    Never raises. All connection failures are caught by the adapter fetcher and
    return the empty-value fallback dict (five keys, all empty/None).
    """

    def fetch_metadata(
        self,
        *,
        adapter_name: str,
        operator_config: dict[str, Any],
        available_features: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch all VectorDB metadata for one operator node.

        Args:
            adapter_name: Value of operator_config["provider"] — e.g. "opensearch".
            operator_config: Full operator config dict from the DAG snapshot.
                Connection parameters are in operator_config["provider_config"].
                Resource name (index_name) is at the top level.
            available_features: Propagated feature map from the DAG snapshot.
                Used as the Source 4 fallback for feature_mappings derivation.

        Returns:
            Dict with five normalised keys. Never raises — returns empty-value
            defaults on any connection failure or unknown adapter.
        """
        provider_config = operator_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        if adapter_name == OperatorConstants.VectorDB.OPENSEARCH:
            from docpipe.core.operators.vectordb.adapters.outbound.opensearch.resource_metadata import (
                OpenSearchResourceMetadata,
            )

            return OpenSearchResourceMetadata().fetch(
                provider_config=provider_config,
                operator_config=operator_config,
                available_features=available_features,
                normalise_feature_mappings=self._normalise_feature_mappings,
                default_feature_mappings_from_features=self._default_feature_mappings_from_features,
                empty_result=self._empty_result,
            )

        if adapter_name == OperatorConstants.VectorDB.MILVUS:
            from docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata import (
                MilvusResourceMetadata,
            )

            return MilvusResourceMetadata().fetch(
                provider_config=provider_config,
                operator_config=operator_config,
                available_features=available_features,
                normalise_feature_mappings=self._normalise_feature_mappings,
                default_feature_mappings_from_features=self._default_feature_mappings_from_features,
                empty_result=self._empty_result,
            )

        logger.warning("No metadata fetcher for VectorDB adapter: %s", adapter_name)
        return self._empty_result()

    # ------------------------------------------------------------------
    # Shared helpers — injected into adapter fetchers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_feature_mappings(raw: Any) -> list[dict[str, str]]:
        """Normalise feature mappings to canonical list-of-dicts format.

        Accepts only list-of-dicts: [{"feature_name": "...", "mapped_column_name": "..."}, ...]
        """
        _fn = OperatorConstants.Misc.FEATURE_NAME
        _mc = OperatorConstants.Misc.MAPPED_COLUMN_NAME
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict) and _fn in item and _mc in item]
        return []

    @staticmethod
    def _default_feature_mappings_from_features(
        available_features: dict[str, Any],
        operator_config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Derive default feature mappings in canonical list-of-dicts format for the API/UI response.

        Delegates to compute_default_feature_mappings().
        Passes add_sparse_vector and content_column from operator_config when present.
        """
        cfg = operator_config or {}
        add_sparse_vector: bool = cfg.get(OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, False)
        content_column: str = cfg.get(
            OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        )
        return compute_default_feature_mappings(
            available_features,
            add_sparse_vector=add_sparse_vector,
            content_column=content_column,
        )

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        """Return safe empty-value defaults for all five metadata keys."""
        return {
            OperatorConstants.VectorDB.AVAILABLE_RESOURCES: [],
            OperatorConstants.VectorDB.SELECTED_RESOURCE_SCHEMA: {},
            OperatorConstants.VectorDB.FEATURE_MAPPINGS_RESPONSE: [],
            OperatorConstants.VectorDB.IS_DOCPIPE_SUPPORTED_RESOURCE: {},
            OperatorConstants.VectorDB.STORED_RESOURCE_METADATA: {
                "vector_similarity": None,
                "dimension_size": None,
            },
        }
