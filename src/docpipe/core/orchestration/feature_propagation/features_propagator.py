"""Feature propagator for flow validation.

This module contains the FeaturePropagator class which handles feature
propagation through DAG flows using operator metadata and special case logic.
"""

from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_metadata import OperatorMetadata
from docpipe.core.orchestration.feature_propagation.models import (
    FeatureMetadata,
    FeaturePropagationResult,
    OutputFeaturesToDrop,
)
from docpipe.exceptions.docpipe_exceptions import (
    ErrorCode,
    FlowValidationException,
    ValidationAlert,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


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


class FeaturePropagator:
    """Handles feature propagation through DAG flows.

    The FeaturePropagator is the core engine for tracking data features as they
    flow through a pipeline of operators. It uses operator metadata to automatically
    determine which features are available at each node, enabling validation of
    feature dependencies and requirements.

    Key Responsibilities:
        - Track features through the pipeline (input → operator → output)
        - Merge input features with operator-defined output features
        - Apply operator-specific feature transformation logic
        - Validate mandatory feature preservation
        - Track feature metadata (description, tags, availability flags)
        - Propagate global parameters (e.g., embeddings_model_id)

    Feature Propagation Model:
        For most operators:
            output_features = input_features UNION operator_defined_features

        Special cases (Extract, SQLFilter, Merge):
            - Extract: Conditionally adds/removes entity features
            - SQLFilter: Removes features not in SELECT clause
            - Merge: Combines features from multiple parents

    Operator Metadata Integration:
        The propagator loads operator metadata once during initialization,
        providing O(1) lookup of operator capabilities during propagation.
        Metadata includes:
            - Output features defined by each operator
            - Feature descriptions and tags
            - Availability flags (for_filter, for_vector_db)
            - Feature types (string, list, etc.)

    Thread Safety:
        FeaturePropagator instances are thread-safe for read operations
        (propagate_features) but should not be shared across concurrent
        write operations (metadata updates).

    Example:
        ```python
        propagator = FeaturePropagator()

        # Propagate features through a node
        result = propagator.propagate_features(
            node_id="extract-1",
            operator_short_name="extract_operator",
            operator_config={"entity_extraction": {"provider": "litellm"}},
            input_features={"id": {...}, "content": {...}},
            global_config={},
            parent_results=[]
        )

        # Check output features
        print(f"Available features: {list(result.feature_metadata.keys())}")
        # Output: ['id', 'content', 'text', 'entities', 'document_type']
        ```

    Architecture:
        FeaturePropagator
            ↓ uses
        OperatorMetadata (operator capabilities)
            ↓ produces
        FeaturePropagationResult (per-node feature state)

    See Also:
        - FeaturePropagationResult: Container for propagation results
        - FeatureMetadata: Feature metadata model
        - OperatorMetadata: Operator capability information
        - FlowValidator: Uses propagator for validation
    """

    def __init__(self):
        """Initialize the feature propagator.

        Loads operator metadata once during initialization for efficient
        feature lookups during propagation. Metadata loading failures for
        operators requiring external services are logged but don't prevent
        propagator initialization.
        """
        self.operator_metadata = OperatorMetadata()
        # Load operator metadata once during initialization
        self.operator_metadata.get_operator_metadata(internal_features=True)

    def propagate_features(
        self,
        *,
        node_id: str,
        operator_short_name: str,
        operator_config: dict[str, Any],
        input_features: dict[str, Any],
        global_config: dict[str, Any],
        parent_results: list[FeaturePropagationResult] | None = None,
        source_node_id: str | None = None,
    ) -> FeaturePropagationResult:
        """Generic feature propagation using operator metadata.

        This is the main entry point for feature propagation. It handles all
        operators using a consistent algorithm with special case handling for
        operators that transform features (Extract, SQLFilter, Merge).

        Propagation Algorithm:
            1. Store input features explicitly (for debugging/inspection)
            2. Initialize result with input features and their metadata
            3. Load operator metadata to get operator-defined output features
            4. Merge operator features with input features
            5. Apply special case logic (Extract/SQLFilter/Merge)
            6. Apply output_features_to_drop (generic, any operator)
            7. Propagate global parameters (e.g., embeddings_model_id)
            8. Compute and store output features (new features only)

        Feature Merging Rules:
            - Input features are preserved unless explicitly dropped
            - Operator-defined features override input features (same name)
            - Feature metadata is preserved from upstream or operator definition
            - Availability flags (for_filter, for_vector_db) can be overridden

        Special Case Operators:
            - Extract: Adds/removes entity features based on entity_extraction.provider
            - SQLFilter: Drops explicitly listed features via features_to_drop config key
            - Merge: Combines features from multiple parent nodes
            - VectorDB: Produces no output features (terminal operator)

        Args:
            node_id: Unique identifier for this operator node. Used for tracking
                feature origins and scoping feature names.
            operator_short_name: Operator short name (e.g., 'extract_operator',
                'chunker', 'vectordb'). Must match registered operator name.
            operator_config: Operator-specific configuration dict. Used for:
                - Extract: entity_extraction.provider
                - SQLFilter: features_to_drop (explicit list of column names to remove)
                - Merge: merge_type, column_option
                - Any operator: output_features_to_drop (generic drop applied after special-case logic)
                - Embeddings: model_id
            input_features: Features available from parent operators. Dict mapping
                feature names to feature definition dicts containing:
                - description: str
                - tags: list[str]
                - available_for_filter: bool
                - available_for_vector_db: bool
                - type: str
                - source_node_id: str (optional)
            global_config: Global flow configuration. Used for operator behavior
                and validation settings.
            parent_results: List of FeaturePropagationResult from parent nodes.
                Required for Merge operator to combine features from multiple inputs.

        Returns:
            FeaturePropagationResult containing:
                - feature_metadata: Dict[feature_name, FeatureMetadata] - All available features
                - input_features: Dict[node_id, Dict[feature_name, feature_def]] - Input features
                - output_features: Dict[node_id, Dict[feature_name, feature_def]] - New features
                - global_params: Dict[param_name, param_value] - Global parameters
                - output_features_to_drop: Dict[node_id, OutputFeaturesToDrop] - Dropped features

        Example:
            ```python
            # Propagate through Extract operator with entity extraction enabled
            result = propagator.propagate_features(
                node_id="extract-1",
                operator_short_name="extract_operator",
                operator_config={
                    "entity_extraction": {
                        "provider": "litellm",
                        "provider_config": {"model_id": "openai/llama3.2"},
                    }
                },
                input_features={
                    "id": {
                        "description": "Document ID",
                        "tags": ["mandatory"],
                        "available_for_filter": False,
                        "available_for_vector_db": False,
                        "type": "string",
                    },
                    "content": {
                        "description": "Document content",
                        "tags": ["mandatory"],
                        "available_for_filter": False,
                        "available_for_vector_db": False,
                        "type": "string",
                    },
                },
                global_config={},
                parent_results=[],
            )

            # New features introduced by this node (entity extraction active)
            output_features = result.get_output_features(node_id="extract-1")
            # output_features will contain "entities" and "document_type"
            ```

        Performance:
            - O(1) operator metadata lookup (cached during init)
            - O(n) feature merging where n = number of input features
            - O(m) operator feature addition where m = operator-defined features
            - Special case logic adds minimal overhead

        Thread Safety:
            This method is thread-safe for concurrent calls on the same
            FeaturePropagator instance as it only reads operator metadata.

        See Also:
            - _apply_special_case_logic: Handles Extract/SQLFilter/Merge
            - _propagate_global_params: Tracks global parameters
            - FeaturePropagationResult: Result container
            - OperatorMetadata.get_features: Operator feature lookup
        """
        result = FeaturePropagationResult()
        result.source_node_id = source_node_id if source_node_id is not None else node_id
        parent_results = parent_results or []

        # Store input features explicitly
        result.set_input_features(node_id=node_id, features=input_features.copy())

        input_feature_names = set(input_features.keys())

        # Cache constant keys to avoid repeated attribute lookups
        available_for_filter_key = OperatorConstants.Config.AVAILABLE_FOR_FILTER
        available_for_vector_db_key = OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB

        # Cache constant key to avoid repeated attribute lookups
        mandatory_for_vector_db_key = OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB

        # Start with input features in metadata, preserving upstream metadata shape
        for feature_name, feature_def in input_features.items():
            result.add_feature(
                feature_name=feature_name,
                node_id=feature_def.get("source_node_id", node_id),
                description=feature_def.get(OperatorConstants.Config.DESCRIPTION, ""),
                tags=feature_def.get("tags", []),
                available_for_filter=feature_def.get(available_for_filter_key, False),
                available_for_vector_db=feature_def.get(available_for_vector_db_key, False),
                mandatory_for_vector_db=feature_def.get(mandatory_for_vector_db_key, False),
                type=feature_def.get("type", OperatorConstants.Types.TYPE_STRING),
                is_primary=feature_def.get(OperatorConstants.Misc.IS_PRIMARY, False),
            )

        # Get operator metadata
        operator_features = self.operator_metadata.get_features(short_name=operator_short_name)

        # Add operator-defined output features
        for feature_name, feature_def in operator_features.items():
            # Cache input feature lookup to avoid repeated dict access
            input_feature = input_features.get(feature_name, {})

            result.add_feature(
                feature_name=feature_name,
                node_id=node_id,
                description=feature_def.get(OperatorConstants.Config.DESCRIPTION, ""),
                tags=feature_def.get("tags", []),
                available_for_filter=feature_def.get(
                    available_for_filter_key,
                    input_feature.get(available_for_filter_key, False),
                ),
                available_for_vector_db=feature_def.get(
                    available_for_vector_db_key,
                    input_feature.get(available_for_vector_db_key, False),
                ),
                mandatory_for_vector_db=feature_def.get(
                    mandatory_for_vector_db_key,
                    input_feature.get(mandatory_for_vector_db_key, False),
                ),
                type=self._resolve_feature_type(
                    declared_type=feature_def.get("type"), inherited_type=input_feature.get("type")
                ),
                is_primary=feature_def.get(
                    OperatorConstants.Misc.IS_PRIMARY,
                    input_feature.get(OperatorConstants.Misc.IS_PRIMARY, False),
                ),
            )

        # Apply special case logic for specific operators
        result = self._apply_special_case_logic(
            operator_short_name=operator_short_name,
            operator_config=operator_config,
            result=result,
            node_id=node_id,
            parent_results=parent_results,
        )

        # Serialise output features BEFORE applying output_features_to_drop.
        # output_features represents what this node *introduces* to the pipeline —
        # a dropped feature is still produced here; it just won't reach downstream
        # nodes. Serialising after the pop would incorrectly hide dropped features
        # from the node's own output_features snapshot.
        if operator_short_name == OperatorConstants.Operators.VECTORDB:
            pre_drop_output_features: dict[str, Any] = {}
        else:
            pre_drop_output_features = {
                feature_name: self.feature_metadata_to_dict(feature_meta=result.feature_metadata[feature_name])
                for feature_name in result.feature_metadata
                if feature_name not in input_feature_names
            }

        # Apply output_features_to_drop for any operator — generic, not operator-specific.
        # Drops features from downstream propagation only (feature_metadata is what
        # flows to the next node's input_features).
        output_features_to_drop = operator_config.get(DocpipeConstants.OUTPUT_FEATURES_TO_DROP, [])
        if output_features_to_drop:
            mandatory_features = result.get_mandatory_features()
            dropped_mandatory = [f for f in output_features_to_drop if f in mandatory_features]
            if dropped_mandatory:
                raise FlowValidationException(
                    errors=[
                        ValidationAlert(
                            ErrorCode.FLOW_VALIDATION_FAILED.value,
                            f"Cannot drop mandatory features: {dropped_mandatory} in {operator_short_name} operator",
                            message_code="MANDATORY_FEATURES_DROPPED",
                        )
                    ]
                )
            for feature in output_features_to_drop:
                result.feature_metadata.pop(feature, None)
            output_features_to_drop_obj = OutputFeaturesToDrop()
            output_features_to_drop_obj.add_features(features=output_features_to_drop)
            result.set_output_features_to_drop(node_id=node_id, features_to_drop=output_features_to_drop_obj)

        # Propagate global parameters
        self._propagate_global_params(
            operator_short_name=operator_short_name, operator_config=operator_config, result=result
        )

        # Store the pre-drop snapshot: dropped features still appear in this node's
        # output_features (they were introduced here; they just stop propagating downstream).
        result.set_output_features(node_id=node_id, features=pre_drop_output_features)

        return result

    @staticmethod
    def _apply_extract_special_case(
        *,
        operator_config: dict[str, Any],
        result: FeaturePropagationResult,
        node_id: str,
    ) -> None:
        """Apply entity extraction feature propagation logic for ExtractOperator."""
        entity_mode = (operator_config.get(OperatorConstants.Config.ENTITY_EXTRACTION) or {}).get(
            OperatorConstants.Config.PROVIDER,
            OperatorConstants.ExtractionModes.ENTITY_MODE_NONE,
        )
        if entity_mode == OperatorConstants.ExtractionModes.ENTITY_MODE_NONE:
            result.feature_metadata.pop("entities", None)
            result.feature_metadata.pop(OperatorConstants.Columns.DOCUMENT_TYPE, None)
        else:
            if "entities" not in result.feature_metadata:
                result.add_feature(
                    feature_name="entities",
                    node_id=node_id,
                    description="Extracted entities from document",
                    tags=["entity"],
                    available_for_filter=False,
                    available_for_vector_db=False,
                    type="list",
                )
            if OperatorConstants.Columns.DOCUMENT_TYPE not in result.feature_metadata:
                result.add_feature(
                    feature_name=OperatorConstants.Columns.DOCUMENT_TYPE,
                    node_id=node_id,
                    description="Detected document type",
                    tags=["entity"],
                    available_for_filter=True,
                    available_for_vector_db=False,
                    type=OperatorConstants.Types.TYPE_STRING,
                )

    @staticmethod
    def _resolve_feature_type(*, declared_type: str | None, inherited_type: str | None) -> str:
        """Pick the type of an operator-declared feature that may already exist upstream.

        The declared type wins, except that a plain ``vector`` declaration (e.g. the vectordb
        operator accepting any dense embeddings) must not erase an upstream ``vector_binary``
        type set by embeddings quantization.

        Args:
            declared_type: Type declared by the operator metadata, if any.
            inherited_type: Type carried by the same feature from the parent nodes, if any.

        Returns:
            The resolved feature type, defaulting to string.
        """
        if declared_type == OperatorConstants.Types.TYPE_VECTOR and inherited_type == (
            OperatorConstants.Types.TYPE_VECTOR_BINARY
        ):
            return OperatorConstants.Types.TYPE_VECTOR_BINARY
        return declared_type or inherited_type or OperatorConstants.Types.TYPE_STRING

    @staticmethod
    def _apply_embeddings_special_case(
        *,
        operator_config: dict[str, Any],
        result: FeaturePropagationResult,
    ) -> None:
        """Mark the embeddings feature as a binary vector when the operator quantizes to packed bits."""
        quantization = str(operator_config.get(OperatorConstants.Config.QUANTIZATION, "none")).lower()
        if quantization not in ("binary", "ubinary"):
            return
        embeddings_feature = result.feature_metadata.get(OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT)
        if embeddings_feature is not None:
            embeddings_feature.type = OperatorConstants.Types.TYPE_VECTOR_BINARY

    @staticmethod
    def _apply_sql_filter_special_case(
        *,
        operator_config: dict[str, Any],
        result: FeaturePropagationResult,
        node_id: str,
    ) -> None:
        """Apply features_to_drop logic for SQLFilterOperator."""
        features_to_drop = operator_config.get(OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY, [])
        if not features_to_drop:
            return

        mandatory_features = result.get_mandatory_features()
        dropped_mandatory = [f for f in features_to_drop if f in mandatory_features]
        if dropped_mandatory:
            raise FlowValidationException(
                errors=[
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        f"Cannot drop mandatory features: {dropped_mandatory} in SQLFilter operator",
                        message_code="MANDATORY_FEATURES_DROPPED",
                    )
                ]
            )

        for feature in features_to_drop:
            result.feature_metadata.pop(feature, None)

        features_to_drop_obj = OutputFeaturesToDrop()
        features_to_drop_obj.add_features(features=features_to_drop)
        result.set_output_features_to_drop(node_id=node_id, features_to_drop=features_to_drop_obj)

    def _apply_special_case_logic(
        self,
        *,
        operator_short_name: str,
        operator_config: dict[str, Any],
        result: FeaturePropagationResult,
        node_id: str,
        parent_results: list[FeaturePropagationResult],
    ) -> FeaturePropagationResult:
        """Apply operator-specific feature propagation logic.

        Only four operators need special handling:
        1. Extract: Adds/removes entity features based on entity_extraction.provider
        2. SQLFilter: Drops explicitly listed features via features_to_drop config key
        3. Merge: Combines features from multiple inputs
        4. Embeddings: Types the embeddings feature as vector_binary when quantization is binary/ubinary

        Args:
            operator_short_name: Operator short name
            operator_config: Operator configuration
            result: Current propagation result
            node_id: Node identifier
            parent_results: Parent propagation results (required for Merge)

        Returns:
            Updated FeaturePropagationResult
        """
        if operator_short_name == OperatorConstants.Operators.EXTRACT_OPERATOR:
            self._apply_extract_special_case(operator_config=operator_config, result=result, node_id=node_id)
        elif operator_short_name == OperatorConstants.Operators.EMBEDDINGS:
            self._apply_embeddings_special_case(operator_config=operator_config, result=result)
        elif operator_short_name == OperatorConstants.Operators.SQL_FILTER:
            self._apply_sql_filter_special_case(operator_config=operator_config, result=result, node_id=node_id)
        elif operator_short_name == OperatorConstants.Operators.MERGE and parent_results:
            merge_type = operator_config.get(OperatorConstants.Merge.MERGE_TYPE, OperatorConstants.Merge.ROWS)
            column_option = (
                operator_config.get(OperatorConstants.Merge.COLUMN_OPTION)
                if merge_type == OperatorConstants.Merge.COLUMNS
                else None
            )
            input_links = operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
            node_id_to_link_name: dict[str, str] | None = {
                lnk["node_id_ref"]: lnk[OperatorConstants.Misc.LINK_NAME]
                for lnk in input_links
                if lnk.get("node_id_ref") and lnk.get(OperatorConstants.Misc.LINK_NAME)
            } or None
            result.feature_metadata = self.merge_features(
                parent_results=parent_results,
                merge_type=merge_type,
                column_option=column_option,
                node_id_to_link_name=node_id_to_link_name,
            )

        return result

    def feature_metadata_to_dict(self, *, feature_meta: FeatureMetadata) -> dict[str, Any]:
        """Convert feature metadata object to a debug-friendly dictionary."""
        feature_dict: dict[str, Any] = {
            OperatorConstants.Config.DESCRIPTION: feature_meta.description,
            "tags": feature_meta.tags,
            "type": feature_meta.type,
            OperatorConstants.Config.AVAILABLE_FOR_FILTER: feature_meta.available_for_filter,
            OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: feature_meta.available_for_vector_db,
            OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB: feature_meta.mandatory_for_vector_db,
            OperatorConstants.Misc.IS_PRIMARY: feature_meta.is_primary,
        }

        if feature_meta.node_id:
            feature_dict["source_node_id"] = feature_meta.node_id

        return feature_dict

    def _propagate_global_params(
        self, *, operator_short_name: str, operator_config: dict[str, Any], result: FeaturePropagationResult
    ) -> None:
        """Propagate global parameters like embeddings_model_id.

        Args:
            operator_short_name: Operator short name
            operator_config: Operator configuration
            result: Feature propagation result to update
        """
        if operator_short_name == OperatorConstants.Operators.EMBEDDINGS:
            model_id = operator_config.get(OperatorConstants.Config.MODEL_ID)
            if model_id:
                result.global_params[OperatorConstants.Config.EMBEDDINGS_MODEL_ID] = model_id

    @staticmethod
    def _merge_rows_features(*, parent_results: list[FeaturePropagationResult]) -> dict[str, FeatureMetadata]:
        """Union all parent features in order for ROWS merge."""
        merged_features: dict[str, FeatureMetadata] = {}
        for parent in parent_results:
            merged_features.update(parent.feature_metadata)
        return merged_features

    @staticmethod
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

    @staticmethod
    def _build_parent_disambiguation_items(
        *,
        parent_results: list[FeaturePropagationResult],
        node_id_to_link_name: dict[str, str] | None,
    ) -> list[tuple[str, dict[str, FeatureMetadata]]]:
        """Build suffix and metadata mapping tuples for disambiguation."""
        parent_items: list[tuple[str, dict[str, FeatureMetadata]]] = []
        for index, parent in enumerate(parent_results):
            link_name = (
                node_id_to_link_name.get(parent.source_node_id)
                if node_id_to_link_name and parent.source_node_id
                else None
            )
            suffix = link_name if link_name else str(index)
            parent_items.append((suffix, parent.feature_metadata))
        return parent_items

    def merge_features(
        self,
        *,
        parent_results: list[FeaturePropagationResult],
        merge_type: str,
        column_option: str | None = None,
        node_id_to_link_name: dict[str, str] | None = None,
    ) -> dict[str, FeatureMetadata]:
        """Merge features from multiple parent results using runtime merge semantics.

        Implements feature merging logic for the Merge operator, which combines
        data from multiple parent nodes. The merge behavior depends on merge_type
        and column_option parameters.

        Merge Types:
            - ROWS: Union of all features from all parents (vertical concatenation)
            - COLUMNS: Join-based merge with column handling options (horizontal join)

        Column Options (for COLUMNS merge):
            - INNER_JOIN_DUPLICATE_COLUMN: Keep only common features across all parents
            - FULL_OUTER_JOIN: Keep all features, disambiguate duplicates with suffix

        Args:
            parent_results: List of FeaturePropagationResult from parent nodes.
                Must contain at least one result. Order matters for FULL_OUTER_JOIN
                disambiguation.
            merge_type: Merge strategy - "rows" or "columns"
            column_option: Column handling for COLUMNS merge:
                - "inner_join_duplicate_column": Intersection of features
                - "full_outer_join": Union with disambiguation
                - None: Defaults to union behavior
            node_id_to_link_name: Optional mapping of parent node ID to its link
                name (e.g. {"eb1c423b": "Link_5", "878a7925": "Link_6"}).
                Built from input_links[].{node_id_ref → link_name} by the caller.
                When provided and column_option is FULL_OUTER_JOIN, duplicate
                feature names are suffixed with the link name of the branch they
                came from (e.g. "name_Link_6").
                Falls back to numeric index suffix when absent or when a result
                has no source_node_id / no matching entry in the map.

        Returns:
            Dict mapping feature names to FeatureMetadata objects. The returned
            features represent the merged feature set available after the merge.

        Merge Behavior Details:
            ROWS merge:
                - Combines all features from all parents
                - No disambiguation needed (vertical stack)
                - Result = parent1_features UNION parent2_features UNION ...

            COLUMNS + INNER_JOIN:
                - Keeps only features present in ALL parents
                - Join key (id) is always included
                - Result = parent1_features INTERSECT parent2_features INTERSECT ... UNION {id}

            COLUMNS + FULL_OUTER_JOIN:
                - Keeps all features from all parents
                - Duplicate feature names get suffix: feature_LinkName or feature_N
                - Join key (id) is never duplicated
                - Result = all features with disambiguation

        Example (COLUMNS + FULL_OUTER_JOIN with link names):
            ```python
            result = propagator.merge_features(
                parent_results=[result1, result2],
                merge_type="columns",
                column_option="full_outer",
                node_id_to_link_name={"node-a": "Link_5", "node-b": "Link_6"},
            )
            # Result: {"id": meta1, "name": meta2, "name_Link_6": meta4}
            ```

        Note:
            - The join key is always "id" (OperatorConstants.Columns.ID)
            - Empty parent_results returns empty dict
            - Feature metadata is taken from first parent containing the feature

        See Also:
            - _apply_special_case_logic: Calls this method for Merge operator
            - OperatorConstants.Merge: Merge type and option constants
        """
        if not parent_results:
            return {}

        join_key = OperatorConstants.Columns.ID

        if merge_type == OperatorConstants.Merge.ROWS:
            return self._merge_rows_features(parent_results=parent_results)

        if merge_type == OperatorConstants.Merge.COLUMNS and column_option in (
            OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
            OperatorConstants.Merge.FULL_OUTER_JOIN,
        ):
            output_feature_set = self._compute_column_output_feature_set(
                parent_results=parent_results,
                column_option=column_option,
                join_key=join_key,
            )
            parent_items = self._build_parent_disambiguation_items(
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
