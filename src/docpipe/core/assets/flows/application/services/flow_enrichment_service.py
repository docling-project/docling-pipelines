# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Service for enriching flow definitions with per-operator feature metadata."""

from __future__ import annotations

from typing import Any, Callable

from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.feature_propagation.features_propagator import FeaturePropagator
from docpipe.core.orchestration.flow_validator import FlowValidator
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.elyra_converter import ElyraConstants

logger = get_logger()


def _default_validator_factory(
    feature_propagator: FeaturePropagator | None = None,
) -> FlowValidator:
    """Create a FlowValidator backed by a fresh Python orchestrator.

    Constructs a Python-mode orchestrator and wraps it in a FlowValidator
    ready for feature propagation.

    Args:
        feature_propagator: Optional shared FeaturePropagator instance to inject
            into the validator, avoiding a redundant operator-metadata load.

    Returns:
        FlowValidator: A fully initialised validator instance.
    """
    from docpipe.core.constants.constants import OrchestratorType
    from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

    orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
    return FlowValidator(orchestrator=orchestrator, feature_propagator=feature_propagator)


class FlowEnrichmentService:
    """Enriches Elyra flow definitions with per-operator feature metadata.

    Uses FlowValidator.propagate_features_per_node() to run the DAG traversal
    without raising on validation warnings, enabling enrichment for flows
    that are still under construction.

    Metadata is injected into each Elyra node's top-level `parameters` key
    rather than `app_data`.

    Reuses ValidationService._convert_to_dag_flow() for Elyra-to-DAG
    conversion to avoid duplicating that logic.

    Args:
        validator_factory: Zero-argument callable returning a ready-to-use
            FlowValidator. Defaults to _default_validator_factory (production).
            Override in tests to inject a mock validator directly.
    """

    def __init__(
        self,
        validator_factory: Callable[[], FlowValidator] | None = None,
    ) -> None:
        """Initialise the service with an optional validator factory.

        Args:
            validator_factory: Zero-argument callable that returns a ready-to-use
                FlowValidator. Defaults to a closure over _default_validator_factory
                that injects ``self._propagator`` so operator metadata is loaded only
                once per service instance. Override in tests to inject a mock validator
                without touching the orchestrator stack.
        """
        self._validation_service = ValidationService()
        # Shared propagator used both by _build_node_feature_metadata() (three-strategy
        # merge dict) and, when using the default factory, by the FlowValidator — so
        # operator metadata is loaded exactly once per FlowEnrichmentService instance.
        self._propagator = FeaturePropagator()
        self._validator_factory = validator_factory or (lambda: _default_validator_factory(self._propagator))

    def enrich_flow_with_features(
        self,
        *,
        flow_definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich a flow definition with per-operator feature metadata.

        Args:
            flow_definition: Flow definition in Elyra format.

        Returns:
            Deep copy of the input flow with metadata injected into each
            node's top-level `parameters` key.

        Raises:
            ValueError: If flow_definition is missing or empty.
            FlowValidationException: If the flow structure is critically invalid
                (e.g., missing node IDs, cycles).
        """
        if not flow_definition:
            raise ValueError("flow_definition is required")

        # 1. Convert Elyra JSON to internal DAG (reuses ValidationService logic)
        internal_dag = self._validation_service._convert_to_dag_flow(flow_definition=flow_definition, is_elyra=True)

        # 2. Expand ${ENV_VAR} placeholders. vault:// references stay as written: only
        # a node that connects during enrichment resolves its own (see
        # VectorDBMetadataFetcher.fetch_metadata), so no resolved value is ever held
        # in the DAG or the propagator snapshot.
        self._expand_dag_env_vars(internal_dag=internal_dag)

        # 3. Run feature propagation without raising on warnings
        validator = self._validator_factory()
        logger.debug("Running feature propagation for flow enrichment")
        node_features = validator.propagate_features_per_node(
            flow_def=internal_dag, global_config=internal_dag.get(OperatorConstants.Config.GLOBAL_CONFIG, {})
        )
        logger.debug("Feature propagation complete: %d nodes", len(node_features))

        # 4. Inject metadata back into each Elyra node's parameters
        return self._inject_node_metadata(
            original_flow=flow_definition,
            node_features=node_features,
        )

    def _inject_node_metadata(
        self,
        *,
        original_flow: dict[str, Any],
        node_features: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Deep-copy an Elyra flow and inject feature metadata into every node.

        Iterates over all pipelines and nodes in the Elyra JSON. For each node
        whose ID has a corresponding entry in ``node_features``, builds a
        metadata block via _build_node_feature_metadata() and merges it into
        the node's top-level ``parameters`` dict. Nodes absent from
        ``node_features`` (e.g. nodes skipped by the propagator) are left
        untouched.

        Metadata is written to ``node.parameters``, never to ``node.app_data``,
        to avoid coupling to the Elyra-specific app_data nesting.

        Args:
            original_flow: The original Elyra pipeline JSON. Not mutated.
            node_features: Mapping of node ID to per-node feature result dict as
                returned by FlowValidator.propagate_features_per_node(). Each
                entry contains ``available_features``, ``input_features``,
                ``output_features``, and ``dropped_features`` keys.

        Returns:
            A deep copy of ``original_flow`` with metadata merged into each
            matched node's ``parameters`` dict.
        """
        import copy

        enriched_flow = copy.deepcopy(original_flow)
        for pipeline in enriched_flow.get("pipelines", []):
            for node in pipeline.get("nodes", []):
                node_id = node.get(OperatorConstants.Misc.ID, "")
                node_feature_result = node_features.get(node_id)
                if node_feature_result is None:
                    continue
                operator_name = node.get(ElyraConstants.OP, "")
                node_params = node.setdefault(OperatorConstants.Config.PARAMETERS, {})
                node_params.update(
                    self._build_node_feature_metadata(
                        node_id=node_id,
                        node_feature_result=node_feature_result,
                        operator_type=operator_name,
                    )
                )
        return enriched_flow

    @staticmethod
    def _normalise_feature_map(
        *,
        feature_map: dict[str, Any],
        fallback_node_id: str,
    ) -> dict[str, Any]:
        """Convert a raw feature map to the normalised shape expected by the API response.

        Args:
            feature_map: Mapping of feature name to raw feature attribute dict.
            fallback_node_id: Used as ``node_id`` for features that have no
                ``source_node_id`` stored in their attribute dict.

        Returns:
            Mapping of feature name to normalised attribute dict.
        """
        return {
            feature_name: {
                OperatorConstants.Misc.FEATURE_ATTR_NAME: feature_name,
                OperatorConstants.Misc.FEATURE_ATTR_DESCRIPTION: feature_meta.get(
                    OperatorConstants.Misc.FEATURE_ATTR_DESCRIPTION, ""
                ),
                OperatorConstants.Misc.FEATURE_ATTR_AVAILABLE_FOR_FILTER: feature_meta.get(
                    OperatorConstants.Misc.FEATURE_ATTR_AVAILABLE_FOR_FILTER, False
                ),
                OperatorConstants.Misc.FEATURE_ATTR_AVAILABLE_FOR_VECTOR_DB: feature_meta.get(
                    OperatorConstants.Misc.FEATURE_ATTR_AVAILABLE_FOR_VECTOR_DB, False
                ),
                OperatorConstants.Misc.FEATURE_ATTR_MANDATORY_FOR_VECTOR_DB: feature_meta.get(
                    OperatorConstants.Misc.FEATURE_ATTR_MANDATORY_FOR_VECTOR_DB, False
                ),
                OperatorConstants.Misc.TYPE: feature_meta.get(OperatorConstants.Misc.TYPE, "string"),
                OperatorConstants.Misc.FEATURE_ATTR_NODE_ID: feature_meta.get("source_node_id", fallback_node_id),
                OperatorConstants.Misc.TAGS: feature_meta.get(OperatorConstants.Misc.TAGS, []),
            }
            for feature_name, feature_meta in feature_map.items()
        }

    def _build_merge_available_features(
        self,
        *,
        node_id: str,
        node_feature_result: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Build the three-strategy ``available_features`` dict for a merge node.

        Called only when ``operator_type == MERGE``.

        Args:
            node_id: Elyra node ID used as the fallback ``node_id`` on feature entries.
            node_feature_result: Per-node snapshot from
                ``FlowValidator.propagate_features_per_node()``.  Must contain
                ``parent_results`` and ``operator_config`` when the node has upstream
                parents wired; falls back to a flat dict otherwise.

        Returns:
            A ``(available_features, merge_output_features)`` pair where:

            - ``available_features`` is the three-strategy nested dict (or flat
              fallback when no parents are wired).
            - ``merge_output_features`` is the strategy bucket selected by
              ``merge_type``/``column_option``, or ``None`` when no parents are
              wired.
        """
        parent_results = node_feature_result.get("parent_results")
        if not parent_results:
            # No upstream nodes wired yet — return the flat available_feature_map
            # from the propagator snapshot as a best-effort fallback.
            flat_map = node_feature_result.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
            return self._normalise_feature_map(feature_map=flat_map, fallback_node_id=node_id), None

        operator_config = node_feature_result.get("operator_config", {})
        input_links = operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
        node_id_to_link_name: dict[str, str] | None = {
            lnk["node_id_ref"]: lnk[OperatorConstants.Misc.LINK_NAME]
            for lnk in input_links
            if lnk.get("node_id_ref") and lnk.get(OperatorConstants.Misc.LINK_NAME)
        } or None

        def _to_normalised(features: dict) -> dict[str, Any]:
            return self._normalise_feature_map(
                feature_map={k: self._propagator.feature_metadata_to_dict(feature_meta=v) for k, v in features.items()},
                fallback_node_id=node_id,
            )

        concat_normalised = _to_normalised(
            self._propagator.merge_features(
                parent_results=parent_results,
                merge_type=OperatorConstants.Merge.ROWS,
            )
        )
        inner_normalised = _to_normalised(
            self._propagator.merge_features(
                parent_results=parent_results,
                merge_type=OperatorConstants.Merge.COLUMNS,
                column_option=OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
                node_id_to_link_name=node_id_to_link_name,
            )
        )
        outer_normalised = _to_normalised(
            self._propagator.merge_features(
                parent_results=parent_results,
                merge_type=OperatorConstants.Merge.COLUMNS,
                column_option=OperatorConstants.Merge.FULL_OUTER_JOIN,
                node_id_to_link_name=node_id_to_link_name,
            )
        )

        available_features = {
            OperatorConstants.Misc.MERGE_STRATEGY_CONCATENATION: concat_normalised,
            OperatorConstants.Misc.MERGE_STRATEGY_INNER_JOIN: inner_normalised,
            OperatorConstants.Misc.MERGE_STRATEGY_FULL_OUTER_JOIN: outer_normalised,
        }

        # Select the output strategy bucket from the operator config.
        # merge_type=rows → concatenation  (vertical stack, no schema constraint)
        # merge_type=columns, full_outer    → full_outer_join  (all columns)
        # merge_type=columns, inner_join    → inner_join_with_duplicate_columns
        merge_type = operator_config.get(OperatorConstants.Merge.MERGE_TYPE, OperatorConstants.Merge.ROWS)
        column_option = operator_config.get(OperatorConstants.Merge.COLUMN_OPTION)
        if merge_type == OperatorConstants.Merge.COLUMNS and column_option == OperatorConstants.Merge.FULL_OUTER_JOIN:
            merge_output_features: dict[str, Any] = outer_normalised
        elif (
            merge_type == OperatorConstants.Merge.COLUMNS
            and column_option == OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN
        ):
            merge_output_features = inner_normalised
        else:
            merge_output_features = concat_normalised

        return available_features, merge_output_features

    def _build_node_feature_metadata(
        self,
        *,
        node_id: str,
        node_feature_result: dict[str, Any],
        operator_type: str,
    ) -> dict[str, Any]:
        """Build the feature metadata dict to merge into a single node's ``parameters``.

        Converts raw feature maps from the propagator snapshot into the
        normalised shape expected by the enrichment response and applies
        operator-specific rules.

        Args:
            node_id: Elyra node ID — used as the fallback ``node_id`` on
                feature entries whose ``source_node_id`` is absent.
            node_feature_result: Per-node snapshot returned by
                FlowValidator.propagate_features_per_node(). Relevant keys:

                - ``available_features``: flat feature map (post special-case logic)
                - ``input_features``: features arriving from upstream nodes
                - ``output_features``: new features introduced by this node
                - ``parent_results``: list of FeaturePropagationResult objects —
                  present only for merge nodes; used to build the three-strategy dict
                - ``operator_config``: raw operator config dict — present only for
                  merge nodes; used to select the active output strategy

            operator_type: The Elyra ``op`` field (e.g. ``"merge"``,
                ``"sql_filter"``, ``"chunker"``). Controls which
                ``available_features`` rule applies and whether
                ``output_features`` is overridden.

        Returns:
            Dict with three keys to be merged into ``node.parameters``:

            - ``available_features``: three-strategy nested dict for ``merge``;
              flat feature map for ``sql_filter`` and ``vectordb``; ``{}`` for
              all other operators.
            - ``input_features``: normalised union of features from upstream nodes.
            - ``output_features``: for merge nodes, the strategy bucket selected
              by ``merge_type``/``column_option``; for all other nodes, the
              features newly introduced by this node.

        Note:
            ``OperatorConstants.Operators.VECTORDB`` is ``"vectordb"``, not
            ``"vectordb_operator"``. This must match the ``op`` set by
            ElyraConverter on VectorDB nodes.
        """
        available_feature_map = node_feature_result.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
        input_feature_map = node_feature_result.get(OperatorConstants.Config.INPUT_FEATURES, {})
        output_feature_map = node_feature_result.get(OperatorConstants.Config.OUTPUT_FEATURES, {})

        # Holds the output_features for merge nodes (active strategy bucket).
        # Stays None for all other operators, which use the propagator snapshot.
        merge_output_features: dict[str, Any] | None = None
        # Holds live VectorDB metadata; None for all non-vectordb operators so the
        # five VDB keys are omitted entirely from non-vectordb node responses.
        vdb_meta: dict[str, Any] | None = None

        if operator_type == OperatorConstants.Operators.SQL_FILTER:
            # available_features for sql_filter = the features the UI should surface in
            # criteria/column dropdowns: all upstream features where available_for_filter=True.
            # Source: input_feature_map (the full set of features arriving at this node),
            # not available_feature_map (the post-propagation snapshot, which may already
            # have had features dropped by features_to_drop or output_features_to_drop).
            # Only features explicitly marked available_for_filter=True are included.
            filterable_features = {
                k: v
                for k, v in input_feature_map.items()
                if v.get(OperatorConstants.Config.AVAILABLE_FOR_FILTER, False)
            }
            available_features = self._normalise_feature_map(feature_map=filterable_features, fallback_node_id=node_id)
        elif operator_type == OperatorConstants.Operators.VECTORDB:
            available_features = self._normalise_feature_map(
                feature_map=available_feature_map, fallback_node_id=node_id
            )
            vdb_meta = self._fetch_vectordb_metadata(node_feature_result=node_feature_result)
        elif operator_type == OperatorConstants.Operators.MERGE:
            available_features, merge_output_features = self._build_merge_available_features(
                node_id=node_id,
                node_feature_result=node_feature_result,
            )
        else:
            available_features = {}

        result: dict[str, Any] = {
            OperatorConstants.Config.AVAILABLE_FEATURES: available_features,
            OperatorConstants.Config.INPUT_FEATURES: self._normalise_feature_map(
                feature_map=input_feature_map, fallback_node_id=node_id
            ),
            OperatorConstants.Config.OUTPUT_FEATURES: (
                # Merge nodes: use the strategy bucket matching the configured merge_type.
                # All other nodes: use the propagator snapshot (features new to this node).
                merge_output_features
                if merge_output_features is not None
                else self._normalise_feature_map(feature_map=output_feature_map, fallback_node_id=node_id)
            ),
        }
        if vdb_meta is not None:
            result.update(vdb_meta)
        return result

    @staticmethod
    def _expand_dag_env_vars(*, internal_dag: dict[str, Any]) -> None:
        """Expand ``${ENV_VAR}`` placeholders in every operator config of the DAG, in place.

        Uses ``os.path.expandvars`` on every string value recursively, which reads the
        server process environment, the same scope the execution path uses. Unset
        variables are left unchanged. This is the only change enrichment makes to the
        DAG configs: ``vault://`` references are never resolved here. A node that
        connects during enrichment (``vectordb``) resolves its own references inside
        ``VectorDBMetadataFetcher.fetch_metadata``, into local variables, and falls back
        to the empty result when it cannot. Every other node keeps its reference text.

        Args:
            internal_dag: Unwrapped internal DAG dict as returned by
                ``_convert_to_dag_flow``. Its ``dag`` list is iterated.
        """
        import os

        from docpipe.core.constants.constants import DocpipeConstants

        def _expand(value: Any) -> Any:
            if isinstance(value, str):
                return os.path.expandvars(value)
            if isinstance(value, dict):
                return {k: _expand(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_expand(item) for item in value]
            return value

        for node in internal_dag.get(DocpipeConstants.DAG, []):
            config = node.get(OperatorConstants.Config.CONFIG)
            if isinstance(config, dict):
                node[OperatorConstants.Config.CONFIG] = _expand(config)

    def _fetch_vectordb_metadata(
        self,
        *,
        node_feature_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Attempt a live VectorDB metadata fetch for a vectordb operator node.

        Returns a dict with five keys when provider_config is present, or None
        when provider_config is absent (caller omits all VDB keys from the response,
        allowing the UI to distinguish "not configured" from "configured but empty").

        Never raises. Connection failures return the empty-value fallback dict.

        Args:
            node_feature_result: Per-node snapshot from propagate_features_per_node().
                                 Must contain "operator_config" key.
        """
        from docpipe.core.operators.vectordb.metadata_fetcher import VectorDBMetadataFetcher

        operator_config = node_feature_result.get("operator_config", {})
        provider_config = operator_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        if not provider_config:
            return None

        adapter_name: str = operator_config.get(
            OperatorConstants.Config.PROVIDER,
            OperatorConstants.VectorDB.OPENSEARCH,
        )
        # available_features lives in the propagator snapshot, not in operator_config.
        # Pass it explicitly so the fetcher can derive default feature_mappings for new indices.
        available_features: dict = node_feature_result.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
        return VectorDBMetadataFetcher().fetch_metadata(
            adapter_name=adapter_name,
            operator_config=operator_config,
            available_features=available_features,
        )
