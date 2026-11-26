# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pure feature-merge algorithm shared by the Merge operator, propagator and validator.

This is a leaf module: it depends only on the propagation models and operator constants, so operators,
``FeaturePropagator``, ``FlowValidator`` and ``FlowEnrichmentService`` can all use it without import cycles.
"""

from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.feature_propagation.models import (
    FeatureMetadata,
    FeaturePropagationResult,
)


def disambiguate_features(
    *,
    parent_items: list[tuple[str, Any]],
    output_feature_set: set[str],
    join_key: str,
) -> dict[str, Any]:
    """Merge per-parent feature sequences with join-key protection and suffix disambiguation.

    Shared by :class:`FeaturePropagator` (operating on ``FeatureMetadata`` objects) and
    :class:`FlowValidator` (operating on plain feature-definition dicts).  The value type
    is generic (``Any``) so the same routine serves both call sites.

    Algorithm:
        - ``join_key`` is inserted with ``setdefault``; only the first occurrence is kept,
          and it is never suffixed.
        - Any feature not in ``output_feature_set`` is skipped entirely.
        - The first occurrence of every other key is inserted plain.
        - A second (or later) occurrence of the same key is inserted as ``key_<suffix>``
          where *suffix* is the first element of the ``(suffix, feature_dict)`` pair.

    Args:
        parent_items: Ordered list of ``(suffix, feature_dict)`` pairs — one per parent
            branch.  ``suffix`` is used only when disambiguating duplicates.
        output_feature_set: Gate set — only features whose key is in this set are emitted.
            Pass ``set(all_keys)`` for FULL_OUTER_JOIN; pass the intersection for
            INNER_JOIN (though inner-join callers should use plain ``update()`` instead).
        join_key: Primary-key column (always ``"id"``).  Protected from suffixing and
            de-duplicated by first-occurrence-wins.

    Returns:
        Merged dict preserving insertion order (Python 3.7+).
    """
    result: dict[str, Any] = {}
    for suffix, feature_dict in parent_items:
        for feature, value in feature_dict.items():
            if feature not in output_feature_set:
                continue
            if feature == join_key:
                result.setdefault(feature, value)
            elif feature in result:
                result[f"{feature}_{suffix}"] = value
            else:
                result[feature] = value
    return result


def _merge_rows_features(*, parent_results: list[FeaturePropagationResult]) -> dict[str, FeatureMetadata]:
    """Union all parent features in order for ROWS merge."""
    merged_features: dict[str, FeatureMetadata] = {}
    for parent in parent_results:
        merged_features.update(parent.feature_metadata)
    return merged_features


def _compute_column_output_feature_set(
    *,
    parent_results: list[FeaturePropagationResult],
    column_option: str | None,
    join_key: str,
) -> set[str]:
    """Compute the target set of features based on column_option."""
    if column_option == OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN:
        common_features: set[str] = set(parent_results[0].feature_metadata.keys())
        for parent in parent_results[1:]:
            common_features.intersection_update(parent.feature_metadata.keys())
        common_features.add(join_key)
        return common_features

    return {feature for parent in parent_results for feature in parent.feature_metadata}


def _build_parent_disambiguation_items(
    *,
    parent_results: list[FeaturePropagationResult],
    node_id_to_link_name: dict[str, str] | None,
) -> list[tuple[str, dict[str, FeatureMetadata]]]:
    """Build suffix and metadata mapping tuples for disambiguation."""
    parent_items: list[tuple[str, dict[str, FeatureMetadata]]] = []
    for index, parent in enumerate(parent_results):
        link_name = (
            node_id_to_link_name.get(parent.source_node_id) if node_id_to_link_name and parent.source_node_id else None
        )
        suffix = link_name if link_name else str(index)
        parent_items.append((suffix, parent.feature_metadata))
    return parent_items


def merge_features(
    *,
    parent_results: list[FeaturePropagationResult],
    merge_type: str,
    column_option: str | None = None,
    node_id_to_link_name: dict[str, str] | None = None,
) -> dict[str, FeatureMetadata]:
    """Merge features from multiple parent results using runtime merge semantics.

    Merge Types:
        - ROWS: Union of all features from all parents (vertical concatenation)
        - COLUMNS: Join-based merge with column handling options (horizontal join)

    Column Options (for COLUMNS merge):
        - INNER_JOIN_DUPLICATE_COLUMN: Keep only common features across all parents
        - FULL_OUTER_JOIN: Keep all features, disambiguate duplicates with suffix

    Args:
        parent_results: List of FeaturePropagationResult from parent nodes. Order matters
            for FULL_OUTER_JOIN disambiguation. An empty list returns an empty dict.
        merge_type: Merge strategy - "rows" or "columns"
        column_option: Column handling for COLUMNS merge:
            - "inner_join_duplicate_column": Intersection of features
            - "full_outer_join": Union with disambiguation
            - None: Defaults to union behavior
        node_id_to_link_name: Optional mapping of parent node ID to its link name
            (e.g. {"eb1c423b": "Link_5"}), built from input_links[].{node_id_ref -> link_name}.
            When provided and column_option is FULL_OUTER_JOIN, duplicate feature names are
            suffixed with the link name of the branch they came from (e.g. "name_Link_6").
            Falls back to a numeric index suffix when absent or when a result has no
            source_node_id / no matching entry in the map.

    Returns:
        Dict mapping feature names to FeatureMetadata objects available after the merge.

    Merge Behavior Details:
        ROWS merge:
            - Result = parent1_features UNION parent2_features UNION ...
        COLUMNS + INNER_JOIN:
            - Result = parent1_features INTERSECT parent2_features INTERSECT ... UNION {id}
        COLUMNS + FULL_OUTER_JOIN:
            - Keeps all features; duplicate names get suffix feature_LinkName or feature_N
            - Join key (id) is never duplicated

    Note:
        - The join key is always "id" (OperatorConstants.Columns.ID)
        - Feature metadata is taken from the first parent containing the feature
    """
    if not parent_results:
        return {}

    join_key = OperatorConstants.Columns.ID

    if merge_type == OperatorConstants.Merge.ROWS:
        return _merge_rows_features(parent_results=parent_results)

    if merge_type == OperatorConstants.Merge.COLUMNS and column_option in (
        OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
        OperatorConstants.Merge.FULL_OUTER_JOIN,
    ):
        output_feature_set = _compute_column_output_feature_set(
            parent_results=parent_results,
            column_option=column_option,
            join_key=join_key,
        )
        parent_items = _build_parent_disambiguation_items(
            parent_results=parent_results,
            node_id_to_link_name=node_id_to_link_name,
        )
        return disambiguate_features(
            parent_items=parent_items,
            output_feature_set=output_feature_set,
            join_key=join_key,
        )

    # Unrecognised merge_type/column_option combination — return plain union
    fallback_merged_features: dict[str, FeatureMetadata] = {}
    for parent in parent_results:
        fallback_merged_features.update(parent.feature_metadata)
    return fallback_merged_features
