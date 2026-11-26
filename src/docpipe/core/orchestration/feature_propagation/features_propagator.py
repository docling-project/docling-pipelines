# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Feature propagator for flow validation.

This module contains the FeaturePropagator class which handles feature
propagation through DAG flows using operator metadata and operator-declared propagation hooks.
"""

from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_metadata import OperatorMetadata
from docpipe.core.orchestration.feature_propagation.feature_merge import (
    disambiguate_features,
)
from docpipe.core.orchestration.feature_propagation.feature_merge import merge_features as _merge_features
from docpipe.core.orchestration.feature_propagation.models import (
    FeatureMetadata,
    FeaturePropagationResult,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

__all__ = ["FeaturePropagator", "disambiguate_features"]


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

        Operator-specific behavior lives on the operators themselves, via
        ``AbstractOperator.propagate_features`` (feature adjustments),
        ``AbstractOperator.get_global_params`` (flow-wide parameters) and
        ``AbstractOperator.produces_output_features`` (terminal operators). This class
        contains no operator names, so a new operator needs no change here.

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

    def __init__(self, *, orchestrator: Any = None):
        """Initialize the feature propagator.

        Loads operator metadata once during initialization for efficient
        feature lookups during propagation. Metadata loading failures for
        operators requiring external services are logged but don't prevent
        propagator initialization.

        Args:
            orchestrator: Optional orchestrator whose custom operator packages and
                enable_custom_operators setting decide which operators (and so which
                output features) are known. Without it, only the environment-resolved
                setting applies, so an opt-in passed as a Python argument is lost.
        """
        self.operator_metadata = OperatorMetadata(orchestrator=orchestrator)
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
        operators using a consistent algorithm and delegates operator-specific
        adjustments to the operator class hooks.

        Propagation Algorithm:
            1. Store input features explicitly (for debugging/inspection)
            2. Initialize result with input features and their metadata
            3. Load operator metadata to get operator-defined output features
            4. Merge operator features with input features
            5. Call the operator's propagate_features hook (e.g. Extract, SQLFilter, Merge)
            6. Apply output_features_to_drop (generic, any operator)
            7. Propagate global parameters (e.g., embeddings_model_id)
            8. Compute and store output features (new features only)

        Feature Merging Rules:
            - Input features are preserved unless explicitly dropped
            - Operator-defined features override input features (same name)
            - Feature metadata is preserved from upstream or operator definition
            - Availability flags (for_filter, for_vector_db) can be overridden

        Operators with their own propagation behavior (implemented on the operator class):
            - Extract: Adds/removes entity features based on entity_extraction.provider
            - Embeddings: Types the embeddings feature from quantization; publishes embeddings_model_id
            - SQLFilter: Drops explicitly listed features via features_to_drop config key
            - Merge: Combines features from multiple parent nodes
            - VectorDB: Produces no output features (produces_output_features is False)

        Args:
            node_id: Unique identifier for this operator node. Used for tracking
                feature origins and scoping feature names.
            operator_short_name: Operator short name (e.g., 'extract_operator',
                'chunker', 'vectordb'). Must match registered operator name.
            operator_config: Operator-specific configuration dict. Used for:
                - Extract: entity_extraction.provider
                - SQLFilter: features_to_drop (explicit list of column names to remove)
                - Merge: merge_type, column_option
                - Any operator: output_features_to_drop (generic drop applied after the operator hook)
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
            - Operator hook adds minimal overhead

        Thread Safety:
            This method is thread-safe for concurrent calls on the same
            FeaturePropagator instance as it only reads operator metadata.

        See Also:
            - AbstractOperator.propagate_features: Per-operator feature adjustments
            - AbstractOperator.get_global_params: Per-operator global parameters
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
                description=input_feature.get(OperatorConstants.Config.DESCRIPTION)
                or feature_def.get(OperatorConstants.Config.DESCRIPTION, ""),
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

        # Let the operator adjust its own features (entities, quantization, drops, merge, ...).
        # Unknown operators have no class and therefore no operator-specific behavior.
        operator_class = self.operator_metadata.get_operator_class(short_name=operator_short_name)
        if operator_class is not None:
            operator_class.propagate_features(
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
        if operator_class is not None and not operator_class.produces_output_features:
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
        result.drop_features(
            node_id=node_id,
            features=operator_config.get(DocpipeConstants.OUTPUT_FEATURES_TO_DROP, []),
            operator_label=operator_short_name,
        )

        # Propagate global parameters published by the operator
        if operator_class is not None:
            result.global_params.update(operator_class.get_global_params(operator_config=operator_config))

        # Store the pre-drop snapshot: dropped features still appear in this node's
        # output_features (they were introduced here; they just stop propagating downstream).
        result.set_output_features(node_id=node_id, features=pre_drop_output_features)

        return result

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

    def merge_features(
        self,
        *,
        parent_results: list[FeaturePropagationResult],
        merge_type: str,
        column_option: str | None = None,
        node_id_to_link_name: dict[str, str] | None = None,
    ) -> dict[str, FeatureMetadata]:
        """Merge features from multiple parent results using runtime merge semantics.

        Thin delegate to :func:`~docpipe.core.orchestration.feature_propagation.feature_merge.merge_features`, kept so existing callers
        (``FlowEnrichmentService``) continue to work. See that function for the merge rules.

        Args:
            parent_results: FeaturePropagationResult from each parent node (order matters for disambiguation).
            merge_type: Merge strategy - "rows" or "columns".
            column_option: Column handling for COLUMNS merge (inner join or full outer join).
            node_id_to_link_name: Optional parent node ID to link name mapping used as duplicate suffix.

        Returns:
            Dict mapping feature names to FeatureMetadata after the merge.
        """
        return _merge_features(
            parent_results=parent_results,
            merge_type=merge_type,
            column_option=column_option,
            node_id_to_link_name=node_id_to_link_name,
        )
