# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Data models for feature propagation.

This module contains the core data structures used to track features
as they propagate through a DAG flow during validation.
"""

from typing import Any

from pydantic import BaseModel, Field

from docpipe.exceptions.docpipe_exceptions import (
    ErrorCode,
    FlowValidationException,
    ValidationAlert,
)


class FeatureMetadata(BaseModel):
    """Metadata for a single feature in the flow.

    Tracks comprehensive information about each feature including its origin,
    purpose, and availability for different operations.
    """

    name: str = Field(..., description="Feature name")
    description: str = Field(default="", description="Human-readable description of the feature")
    node_id: str = Field(..., description="ID of the operator that added this feature")
    tags: list[str] = Field(default_factory=list, description="Tags like 'mandatory', 'internal', etc.")
    available_for_filter: bool = Field(default=False, description="Whether feature can be used in SQL filters")
    available_for_vector_db: bool = Field(default=False, description="Whether feature can be stored in vector DB")
    mandatory_for_vector_db: bool = Field(
        default=False,
        description="Whether a vector DB operator must have a mapping for this feature to write correctly",
    )
    type: str = Field(default="string", description="Data type of the feature")
    is_primary: bool = Field(default=False, description="Whether this feature is the primary key for vector DB storage")


class OutputFeaturesToDrop:
    """Tracks features to be dropped after operator execution.

    Used by operators like SQLFilter and Merge to remove features
    that should not propagate to downstream operators.
    """

    def __init__(self):
        self.features_to_drop: set[str] = set()

    def add_feature(self, *, feature: str) -> None:
        """Add a feature to the drop list.

        Args:
            feature: Feature name to drop
        """
        self.features_to_drop.add(feature)

    def add_features(self, *, features: list[str]) -> None:
        """Add multiple features to the drop list.

        Args:
            features: List of feature names to drop
        """
        self.features_to_drop.update(features)

    def should_drop(self, *, feature: str) -> bool:
        """Check if a feature should be dropped.

        Args:
            feature: Feature name to check

        Returns:
            True if feature should be dropped, False otherwise
        """
        return feature in self.features_to_drop

    def get_features_to_drop(self) -> set[str]:
        """Get all features marked for dropping.

        Returns:
            Set of feature names to drop
        """
        return self.features_to_drop.copy()


class FeaturePropagationResult:
    """Tracks feature propagation state through the DAG.

    Maintains feature dictionaries for different purposes:
    - input_features: Features received by each node from parent nodes
    - output_features: Features produced/added by each node
    - available_features: All features available at each node (input + output)
    - opensearch_features: Features specifically for OpenSearch storage
    - output_features_to_drop: Features to remove after operator execution
    - feature_metadata: Comprehensive metadata for each feature
    - global_params: Global parameters passed between operators
    """

    def __init__(self):
        # Maps node_id -> dict of input features (from parent nodes)
        self.input_features: dict[str, dict[str, Any]] = {}

        # Maps node_id -> dict of output features (added by this node)
        self.output_features: dict[str, dict[str, Any]] = {}

        # Maps node_id -> list of available features (input + output)
        self.available_features: dict[str, list[str]] = {}

        # Maps node_id -> list of OpenSearch-specific features
        self.opensearch_features: dict[str, list[str]] = {}

        # Maps node_id -> OutputFeaturesToDrop instance
        self.output_features_to_drop: dict[str, OutputFeaturesToDrop] = {}

        # Maps feature_name -> FeatureMetadata
        self.feature_metadata: dict[str, FeatureMetadata] = {}

        # Global parameters (e.g., embeddings_model_id)
        self.global_params: dict[str, Any] = {}

        # The DAG node ID that produced this result. Set by FlowValidator after
        # propagation so that merge_features() can look up the link name for
        # this branch using input_links[node_id_ref → link_name].
        self.source_node_id: str | None = None

    def set_input_features(self, *, node_id: str, features: dict[str, Any]) -> None:
        """Set input features for a node (features received from parent nodes).

        Args:
            node_id: Node identifier
            features: Dictionary of input feature definitions
        """
        self.input_features[node_id] = features

    def get_input_features(self, *, node_id: str) -> dict[str, Any]:
        """Get input features for a node.

        Args:
            node_id: Node identifier

        Returns:
            Dictionary of input feature definitions
        """
        return self.input_features.get(node_id, {})

    def set_output_features(self, *, node_id: str, features: dict[str, Any]) -> None:
        """Set output features for a node (features added by this node).

        Args:
            node_id: Node identifier
            features: Dictionary of output feature definitions
        """
        self.output_features[node_id] = features

    def get_output_features(self, *, node_id: str) -> dict[str, Any]:
        """Get output features for a node.

        Args:
            node_id: Node identifier

        Returns:
            Dictionary of output feature definitions
        """
        return self.output_features.get(node_id, {})

    def set_available_features(self, *, node_id: str, features: list[str]) -> None:
        """Set available features for a node (input + output combined).

        Args:
            node_id: Node identifier
            features: List of available feature names
        """
        self.available_features[node_id] = features

    def get_available_features(self, *, node_id: str) -> list[str]:
        """Get available features for a node.

        Args:
            node_id: Node identifier

        Returns:
            List of available feature names
        """
        return self.available_features.get(node_id, [])

    def set_opensearch_features(self, *, node_id: str, features: list[str]) -> None:
        """Set OpenSearch features for a node.

        Args:
            node_id: Node identifier
            features: List of OpenSearch feature names
        """
        self.opensearch_features[node_id] = features

    def get_opensearch_features(self, *, node_id: str) -> list[str]:
        """Get OpenSearch features for a node.

        Args:
            node_id: Node identifier

        Returns:
            List of OpenSearch feature names
        """
        return self.opensearch_features.get(node_id, [])

    def set_output_features_to_drop(self, *, node_id: str, features_to_drop: OutputFeaturesToDrop) -> None:
        """Set features to drop for a node.

        Args:
            node_id: Node identifier
            features_to_drop: OutputFeaturesToDrop instance
        """
        self.output_features_to_drop[node_id] = features_to_drop

    def get_output_features_to_drop(self, *, node_id: str) -> OutputFeaturesToDrop:
        """Get features to drop for a node.

        Args:
            node_id: Node identifier

        Returns:
            OutputFeaturesToDrop instance (empty if not set)
        """
        return self.output_features_to_drop.get(node_id, OutputFeaturesToDrop())

    def add_feature(
        self,
        *,
        feature_name: str,
        node_id: str,
        description: str = "",
        tags: list[str] | None = None,
        available_for_filter: bool = True,
        available_for_vector_db: bool = False,
        mandatory_for_vector_db: bool = False,
        type: str = "string",
        is_primary: bool = False,
    ) -> None:
        """Add a feature with full metadata.

        Args:
            feature_name: Name of the feature
            node_id: ID of the operator that added this feature
            description: Human-readable description
            tags: Tags like 'mandatory', 'internal', etc.
            available_for_filter: Whether feature can be used in SQL filters
            available_for_vector_db: Whether feature can be stored in vector DB
            mandatory_for_vector_db: Whether a VectorDB operator must map this feature
            type: Data type of the feature
            is_primary: Whether this feature is the primary key for vector DB storage
        """
        resolved_tags = tags or []
        self.feature_metadata[feature_name] = FeatureMetadata(
            name=feature_name,
            description=description,
            node_id=node_id,
            tags=resolved_tags,
            available_for_filter=available_for_filter,
            available_for_vector_db=available_for_vector_db,
            mandatory_for_vector_db=mandatory_for_vector_db,
            type=type,
            is_primary=is_primary or ("primary" in resolved_tags),
        )

    def get_mandatory_features(self) -> list[str]:
        """Get list of features marked as mandatory.

        Returns:
            List of mandatory feature names
        """
        return [name for name, meta in self.feature_metadata.items() if "mandatory" in meta.tags]

    def drop_features(self, *, node_id: str, features: list[str], operator_label: str) -> None:
        """Remove features from downstream propagation and record them for the node.

        Args:
            node_id: Node whose output drops the features.
            features: Feature names to drop. An empty list is a no-op.
            operator_label: Operator name used in the error message (e.g. ``SQLFilter``).

        Raises:
            FlowValidationException: If any listed feature is mandatory
                (message code ``MANDATORY_FEATURES_DROPPED``).
        """
        if not features:
            return

        mandatory_features = self.get_mandatory_features()
        dropped_mandatory = [f for f in features if f in mandatory_features]
        if dropped_mandatory:
            raise FlowValidationException(
                errors=[
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        f"Cannot drop mandatory features: {dropped_mandatory} in {operator_label} operator",
                        message_code="MANDATORY_FEATURES_DROPPED",
                    )
                ]
            )

        for feature in features:
            self.feature_metadata.pop(feature, None)

        features_to_drop = OutputFeaturesToDrop()
        features_to_drop.add_features(features=features)
        self.set_output_features_to_drop(node_id=node_id, features_to_drop=features_to_drop)

    def filter_internal_features(self, *, features: list[str]) -> list[str]:
        """Remove internal features from a list.

        Args:
            features: List of feature names to filter

        Returns:
            List of features with internal features removed
        """
        return [
            f
            for f in features
            if "internal" not in self.feature_metadata.get(f, FeatureMetadata(name=f, node_id="")).tags
        ]
