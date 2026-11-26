# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Domain layer for operator metadata extraction and management.

This module provides the core functionality for discovering and extracting metadata
from all registered operators in the system. It dynamically instantiates operators
and retrieves their configuration, features, and requirements.

Architecture:
    This is the domain layer that contains the business logic for operator metadata
    extraction. It is wrapped by the application service layer
    (OperatorMetadataService) which handles exception translation and logging.

Usage:
    >>> metadata = OperatorMetadata()
    >>> all_metadata = metadata.get_operator_metadata(internal_features=False)
    >>> features = metadata.get_features(short_name="extract_operator")
    >>> required = metadata.required_feature_names(short_name="chunker")

Note:
    This class caches metadata after first retrieval. Subsequent calls return
    cached data unless explicitly refreshed.
"""

from collections import defaultdict
from typing import Any

from docpipe.core.constants.constants import OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.models.session_info import get_session_info
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OperatorMetadata:
    """Manages operator metadata extraction and caching.

    This class is responsible for:
    - Discovering all registered operators via OperatorFactoryProvider
    - Instantiating operators and extracting their metadata
    - Filtering internal features based on configuration
    - Caching metadata for performance
    - Providing utility methods for feature queries

    Attributes:
        session_info: Current session information
        operator_metadata: Cached metadata dictionary mapping operator short names
                          to their metadata dictionaries

    Thread Safety:
        This class is not thread-safe. Create separate instances for concurrent use.
    """

    def __init__(self, *, orchestrator: Any = None) -> None:
        """Initialize operator metadata manager with empty cache.

        Args:
            orchestrator: Optional orchestrator instance to get custom operator settings from.
                         If provided, will use orchestrator's custom operator configuration.
        """
        self.session_info = get_session_info()
        self.operator_metadata: dict[str, dict[str, Any]] = {}
        self._operator_classes: dict[str, type[AbstractOperator]] = {}
        self.orchestrator = orchestrator

    @staticmethod
    def _extract_config_values(*, short_name: str, cls: Any, operator_factory: Any) -> tuple[dict[str, Any], list[str]]:
        """Extract config_values and required_features from an operator class.

        Falls back to instantiating the operator when get_metadata() is not static.
        """
        try:
            config_values = cls.get_metadata()
            required_features = cls.get_required_features()
        except TypeError as e:
            logger.debug(
                "Operator '%s' has non-static get_metadata(), instantiating for backward compatibility", short_name
            )
            op = operator_factory.get_operator(operator_name=short_name)
            if op is None:
                raise ValueError(f"Failed to instantiate operator '{short_name}'") from e
            config_values = op.get_metadata()
            required_features = op.get_required_features()
        return config_values, required_features

    @staticmethod
    def _filter_internal_features(*, config_values: dict[str, Any]) -> None:
        """Remove features tagged as 'internal' from config_values in-place."""
        features = config_values.get(OperatorConstants.Config.FEATURES, {})
        config_values[OperatorConstants.Config.FEATURES] = {
            k: v
            for k, v in features.items()
            if OperatorConstants.Misc.INTERNAL_FEATURE not in v.get(OperatorConstants.Misc.TAGS, [])
        }

    @staticmethod
    def _log_failed_operators(*, failed_operator_list: dict[str, Exception], operator_factory: Any) -> None:
        """Warn for operators that claim to be available but failed to load metadata."""
        available_failed = [
            op_name
            for op_name, _exc in failed_operator_list.items()
            if (op := operator_factory.get_operator(operator_name=op_name)) is not None and op.is_available()
        ]
        if available_failed:
            logger.warning("Metadata missing for available operators: %s", available_failed)

    def get_operator_metadata(self, *, internal_features: bool = False) -> dict[str, dict[str, Any]]:
        """Extract and return metadata for all registered operators.

        This method:
        1. Discovers all operators via OperatorFactoryProvider
        2. Instantiates each operator with empty config
        3. Calls get_metadata() and get_required_features() on each
        4. Filters internal features if requested
        5. Handles initialization failures gracefully
        6. Caches results for subsequent calls

        Args:
            internal_features: If False (default), filters out features tagged as
                             'internal'. If True, includes all features including
                             internal ones like doc_id_hash.

        Returns:
            Dictionary mapping operator short names (e.g., 'extract_operator') to
            their metadata dictionaries containing:
            - label: Human-readable operator name
            - category: Operator category (Extract, Ingest, Functional, Quality, VectorDB)
            - description: Operator description
            - features: Dict of feature definitions
            - required_features: List of required input feature names

        Note:
            - Operators that fail to initialize return empty metadata dict
            - Failed operators are logged as warnings if they claim to be available
            - Results are cached in self.operator_metadata
        """
        refresh_operator_metadata: dict[str, dict[str, Any]] = {}
        failed_operator_list: dict[str, Exception] = {}

        if self.orchestrator is not None:
            operator_factory = OperatorFactoryProvider.get_operator_factory(
                orchestrator=OrchestratorType.PYTHON,
                package_names=self.orchestrator.custom_operator_packages,
                enable_custom_operators=self.orchestrator.enable_custom_operators,
            )
        else:
            operator_factory = OperatorFactoryProvider.get_operator_factory(orchestrator=OrchestratorType.PYTHON)
        logger.info("Discovering operators: %s", list(operator_factory.operators.keys()))

        for short_name, cls in operator_factory.operators.items():
            try:
                config_values, required_features = self._extract_config_values(
                    short_name=short_name, cls=cls, operator_factory=operator_factory
                )
                config_values["required_features"] = required_features
                config_values["owner"] = getattr(cls, "owner", "docpipe")

                if not internal_features:
                    self._filter_internal_features(config_values=config_values)

                refresh_operator_metadata[short_name] = config_values

            except Exception as e:
                refresh_operator_metadata[short_name] = {}
                failed_operator_list[short_name] = e
                logger.debug("Operator '%s' failed to initialize: %s", short_name, e, exc_info=True)

        self.operator_metadata.update(refresh_operator_metadata)
        self._operator_classes = dict(operator_factory.operators)

        if failed_operator_list:
            self._log_failed_operators(failed_operator_list=failed_operator_list, operator_factory=operator_factory)

        return self.operator_metadata

    def get_operator_class(self, *, short_name: str) -> type[AbstractOperator] | None:
        """Return the operator class registered under ``short_name``.

        The class comes from the same factory that supplied the cached metadata, so priority and owner
        resolution and custom-operator settings apply to both identically. The class is returned without
        being instantiated, which keeps untrusted operators from being imported during validation.

        Args:
            short_name: Operator short name (e.g., 'extract_operator').

        Returns:
            The operator class, or None if metadata has not been loaded or the name is unknown.
        """
        return self._operator_classes.get(short_name)

    def get_features(self, *, short_name: str, purpose: str | None = None) -> dict[str, Any]:
        """Get features from a specific operator, optionally filtered by purpose.

        Args:
            short_name: Operator short name (e.g., 'extract_operator', 'chunker')
            purpose: Optional purpose filter. Valid values:
                    - OperatorConstants.Config.AVAILABLE_FOR_FILTER: Features usable in SQL filters
                    - OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: Features storable in vector DBs
                    - OperatorConstants.Config.AVAILABLE_FOR_OPENSEARCH: Features storable in OpenSearch
                    - None: Return all features (default)

        Returns:
            Dictionary of features matching the criteria. Each feature contains:
            - type: Data type (string, int64, double, boolean, list)
            - description: Feature description
            - required: Whether feature is required
            - default: Default value
            - available_for_filter: Can be used in SQL WHERE clauses
            - available_for_vector_db: Can be stored in vector databases
            - available_for_opensearch: Can be stored in OpenSearch

        Example:
            >>> metadata = OperatorMetadata()
            >>> metadata.get_operator_metadata()
            >>> # Get all features
            >>> all_features = metadata.get_features(short_name="extract_operator")
            >>> # Get only filterable features
            >>> filterable = metadata.get_features(
            ...     short_name="extract_operator",
            ...     purpose=OperatorConstants.Config.AVAILABLE_FOR_FILTER
            ... )

        Note:
            Returns empty dict if operator not found or has no features.
        """
        # Check if operator exists and has features
        operator_meta = self.operator_metadata.get(short_name)
        if operator_meta is not None:
            features_data = operator_meta.get(OperatorConstants.Config.FEATURES)
            if features_data is not None:
                features: dict[str, Any] = features_data

                if purpose is None:
                    # Return all features
                    return dict(features.items())
                # Filter by purpose (e.g., available_for_filter, available_for_vector_db)
                return {k: v for k, v in features.items() if v.get(purpose, False)}

        return {}

    def get_features_from_input_output_features(
        self,
        *,
        purpose: str | None = None,
        input_features: dict[str, Any] | None = None,
        output_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge and filter features from input and output feature dictionaries.

        This utility method combines input and output features (with output taking
        precedence for duplicate keys) and optionally filters by purpose.

        Args:
            purpose: Optional purpose filter (same as get_features)
            input_features: Dictionary of input features
            output_features: Dictionary of output features (overrides input on conflict)

        Returns:
            Merged and filtered feature dictionary

        Example:
            >>> metadata = OperatorMetadata()
            >>> input_feats = {"doc_id": {"type": "string"}}
            >>> output_feats = {"content": {"type": "string"}}
            >>> merged = metadata.get_features_from_input_output_features(
            ...     input_features=input_feats,
            ...     output_features=output_feats
            ... )
            >>> print(list(merged.keys()))
            ['doc_id', 'content']

        Note:
            Output features override input features for duplicate keys.
        """
        features: dict[str, Any] = {}

        # Start with input features
        if input_features:
            features = input_features.copy()

        # Merge output features (overrides input on conflict)
        if output_features:
            features.update(output_features)

        # Apply purpose filter if specified
        if len(features) > 0:
            if purpose is None:
                return dict(features.items())
            return {k: v for k, v in features.items() if v.get(purpose, False)}
        return features

    def required_feature_names(self, *, short_name: str) -> list[str]:
        """Get list of required input feature names for an operator.

        Args:
            short_name: Operator short name (e.g., 'chunker', 'embeddings')

        Returns:
            List of required feature names. Empty list if operator not found
            or has no requirements.

        Example:
            >>> metadata = OperatorMetadata()
            >>> metadata.get_operator_metadata()
            >>> required = metadata.required_feature_names(short_name="chunker")
            >>> print(required)
            ['content']  # Chunker requires 'content' feature as input

        Note:
            This is used during flow validation to ensure operators receive
            required inputs from previous operators in the pipeline.
        """
        return self.operator_metadata.get(short_name, {}).get("required_features", [])

    def get_feature_operators_map(self) -> dict[str, list[str]]:
        """Build reverse mapping from features to operators that produce them.

        This creates a dictionary mapping each feature name to a list of operator
        labels that produce that feature. Useful for discovering which operators
        can provide a specific feature.

        Returns:
            Dictionary mapping feature names to lists of operator labels

        Example:
            >>> metadata = OperatorMetadata()
            >>> feature_map = metadata.get_feature_operators_map()
            >>> print(feature_map['content'])
            ['Extract Docling', 'Extract Entities (Ollama)']
            >>> print(feature_map['embeddings'])
            ['Embeddings Operator']

        Note:
            - Automatically calls get_operator_metadata(internal_features=True)
            - Only includes operators that have a label defined
            - Multiple operators may produce the same feature
        """
        # Ensure metadata is loaded (with internal features)
        _ = self.get_operator_metadata(internal_features=True)

        operator_short_names = list(self.operator_metadata.keys())
        feature_operators_map: dict[str, list[str]] = defaultdict(list)

        # Build reverse mapping: feature -> [operator labels]
        for short_name in operator_short_names:
            op_features = list(self.get_features(short_name=short_name).keys())

            for feature in op_features:
                operator_meta = self.operator_metadata.get(short_name)
                if operator_meta is not None:
                    label = operator_meta.get(OperatorConstants.Misc.LABEL, None)
                    if label:
                        feature_operators_map[feature].append(label)

        return feature_operators_map
