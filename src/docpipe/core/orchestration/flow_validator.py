# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Flow validation module for docpipe orchestrator.

This module contains the FlowValidator class which handles all flow validation logic
that was previously embedded in AbstractOrchestrator.
"""

from typing import Any

from docpipe.core.constants.constants import DocpipeConstants, OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.models.session_info import get_session_info, set_session_info
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.operators.operator_metadata import OperatorMetadata
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.feature_propagation import (
    FeaturePropagationResult,
    FeaturePropagator,
    disambiguate_features,
)
from docpipe.core.orchestration.operator_factory import OperatorFactory, OperatorFactoryProvider
from docpipe.exceptions.docpipe_exceptions import (
    ErrorCode,
    FlowValidationException,
    ValidationAlert,
)
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage
from docpipe.types import FlowConfig
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.flow_utils import add_validation_alert

logger = get_logger()


class ValidateStepResults:
    """Container for validation results including features, errors, and warnings.

    Separates validation concerns (errors/warnings) from feature propagation state,
    allowing validators to accumulate results during DAG traversal without mixing
    feature tracking with error reporting.

    This class acts as a mutable accumulator that is passed through the validation
    pipeline, collecting errors and warnings from various validation checks while
    also tracking which features are available at each node.

    Attributes:
        available_features: Dict mapping node IDs to lists of available feature names
            at that node. Used for debugging and feature availability checks.
        errors: List of validation errors (ValidationAlert objects or dicts).
            Non-empty list indicates validation failure.
        warnings: List of validation warnings (ValidationAlert objects or dicts).
            Warnings don't fail validation but indicate potential issues.

    Example:
        ```python
        results = ValidateStepResults(
            available_features={},
            errors=[],
            warnings=[]
        )

        # Validators add errors/warnings during traversal
        results.errors.append(ValidationAlert(
            code="OPERATOR_NOT_FOUND",
            message="Operator not found"
        ))

        # Feature tracking
        results.available_features["node-1"] = ["id", "content", "metadata"]
        ```

    Note:
        This is a simple data container without methods. Validators directly
        mutate the lists and dict to accumulate results.
    """

    def __init__(self, *, available_features: dict, errors: list, warnings: list):
        """Initialize validation results container.

        Args:
            available_features: Empty dict to be populated with node_id -> feature list mappings
            errors: Empty list to be populated with validation errors
            warnings: Empty list to be populated with validation warnings
        """
        self.available_features = available_features
        self.errors = errors
        self.warnings = warnings


class FlowValidator:
    """Handles all flow validation logic for the docpipe orchestrator.

    This class encapsulates comprehensive validation logic for DAG-based data
    processing flows, ensuring structural integrity, operator correctness, and
    feature availability throughout the pipeline.

    Validation Responsibilities:
        - DAG Structure: Validates graph connectivity, detects cycles, checks for disjoint nodes
        - Operator Placement: Ensures Ingest operators are first, VectorDB operators are last
        - Operator Availability: Verifies all operators are registered and available
        - Operator Configuration: Validates operator-specific parameters and requirements
        - Feature Propagation: Tracks features through the pipeline and validates availability
        - Node Naming: Checks for unique node names and proper identification

    Architecture:
        FlowValidator works in conjunction with:
        - FeaturePropagator: Handles feature tracking through the DAG
        - OperatorMetadata: Provides operator capability information
        - _traverse_dag: Executes validation traversal (plain Python topological walk)

    Validation Modes:
        1. validate(): Basic structural validation without feature tracking
        2. validate_dag(): Full validation with error accumulation
        3. validate_dag_with_features(): Validation + feature propagation results
        4. propagate_features_per_node(): Per-node feature propagation results

    Thread Safety:
        FlowValidator instances are NOT thread-safe. Each validation request
        should use its own validator instance (created with its own orchestrator).

    Example:
        ```python
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
        from docpipe.core.orchestration.flow_validator import FlowValidator

        # Create orchestrator and validator
        orchestrator = OrchestratorFactory.create_orchestrator("python")
        orchestrator.initialize(job_id="val-job", job_run_id="val-run")
        validator = FlowValidator(orchestrator=orchestrator)

        # Validate flow (internal runtime DAG format)
        # Note: Authoring format is converted to this format before validation
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "Ingest",
                    "operator": "ingest_source",
                    "config": {
                        "provider": "filesystem",
                        "connection_params": {"paths": ["/data/documents"]}
                    },
                    "output_edges": [{"node_id_ref": "extract-1"}]
                },
                {
                    "id": "extract-1",
                    "name": "Extract",
                    "operator": "extract_operator",
                    "config": {},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": []
                }
            ]
        }

        try:
            validator.validate_dag(flow_def=flow_def, global_config={})
            print("Validation passed!")
        except FlowValidationException as e:
            print(f"Validation failed: {e.errors}")
        ```

    See Also:
        - FeaturePropagator: Feature tracking engine
        - ValidationService: API-level validation facade
        - AbstractOrchestrator: Orchestrator interface
    """

    def __init__(
        self,
        *,
        orchestrator: AbstractOrchestrator,
        feature_propagator: FeaturePropagator | None = None,
    ):
        """Initialize the FlowValidator.

        Creates a validator instance tied to a specific orchestrator. The validator
        loads operator metadata once during initialization for efficient validation.

        Args:
            orchestrator: Reference to the AbstractOrchestrator instance. Used to
                resolve custom operator packages and enable_custom_operators settings.
                Does not need flow_engine to be initialized.
            feature_propagator: Optional shared FeaturePropagator instance. When
                provided the validator reuses it instead of constructing a new one,
                avoiding a redundant operator-metadata load (e.g. when called from
                FlowEnrichmentService which already holds a propagator).

        Note:
            Operator metadata loading may fail for operators requiring external services
            (e.g., Ollama, OpenSearch). This is acceptable as validation only needs
            structural information, not runtime capabilities.
        """
        self.orchestrator = orchestrator
        self.logger = get_logger()
        self.common_log_arguments = orchestrator.common_log_arguments
        self.operator_metadata = OperatorMetadata(orchestrator=orchestrator)
        self._node_features_cache: dict[str, dict] | None = None
        # Load operator metadata once during initialization
        # Operators that require external services may fail to load metadata
        # This is acceptable for validation as we only need structural information
        try:
            self.operator_metadata.get_operator_metadata(internal_features=True)
        except Exception as e:
            self.logger.warning(
                "Some operators failed to load metadata (this is normal if external services are unavailable): %s",
                e,
            )
            # Continue with whatever metadata was successfully loaded
        # Use injected propagator when available to avoid a redundant metadata load.
        self.feature_propagator = feature_propagator if feature_propagator is not None else FeaturePropagator()

    def validate(self, *, flow_def: FlowConfig, params: FlowConfig) -> None:
        """Main validation entry point for a flow definition.

        Performs basic structural validation without feature propagation.
        This is the simplest validation mode, suitable for quick checks.

        Args:
            flow_def: The flow definition dictionary containing:
                - dag: List of operator node definitions
                - global_config: Optional global configuration
            params: Additional parameters to merge with global config.
                Typically used to override or extend global_config.

        Raises:
            FlowValidationException: If validation fails with errors.
                Contains errors and warnings lists.

        Note:
            Validation can be disabled by setting disable_validation=True
            in global_config or params.
        """
        global_config = flow_def.get(OperatorConstants.Config.GLOBAL_CONFIG, {}) | params

        # Skip validation if explicitly disabled
        if global_config.get(OperatorConstants.Config.DISABLE_VALIDATION, False):
            return

        if DocpipeConstants.DAG not in flow_def:
            raise FlowValidationException(
                errors=[
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        message=ValidationCodeMessages.PIPELINE_NOT_FOUND_ERROR.value,
                        message_code=ValidationCodeMessages.PIPELINE_NOT_FOUND_ERROR.name,
                    )
                ]
            )
        self.validate_dag(flow_def=flow_def, global_config=global_config)

    @staticmethod
    def _sanitize_vault_refs_for_validation(value: object, *, key: str | None = None) -> object:
        """Replace vault:// references with safe validation mock values.

        Operators receive non-empty mock structures rather than unresolved URIs
        so that required presence checks and dict validation pass cleanly.
        """
        from docpipe.integrations.secrets.secret_provider import is_vault_reference

        if isinstance(value, str) and is_vault_reference(value):
            if key in ("credentials", "credentials_json", "provider_credentials"):
                return {"__vault_mock__": True}
            return DocpipeConstants.VAULT_VALIDATION_PLACEHOLDER
        if isinstance(value, dict):
            return {k: FlowValidator._sanitize_vault_refs_for_validation(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [FlowValidator._sanitize_vault_refs_for_validation(item, key=key) for item in value]
        return value

    @staticmethod
    def _collect_vault_refs(obj: object, *, prefix: str = "") -> list[tuple[str, str]]:
        """Recursively collect (path, vault_uri) pairs from an object."""
        from docpipe.integrations.secrets.secret_provider import is_vault_reference

        if isinstance(obj, str) and is_vault_reference(obj):
            return [(prefix, obj)]
        if isinstance(obj, dict):
            found_dict: list[tuple[str, str]] = []
            for k, v in obj.items():
                found_dict.extend(FlowValidator._collect_vault_refs(v, prefix=f"{prefix}.{k}" if prefix else str(k)))
            return found_dict
        if isinstance(obj, list):
            found_list: list[tuple[str, str]] = []
            for i, item in enumerate(obj):
                found_list.extend(FlowValidator._collect_vault_refs(item, prefix=f"{prefix}[{i}]"))
            return found_list
        return []

    @staticmethod
    def _validate_single_vault_ref(
        *,
        path: str,
        ref: str,
        op_def: dict[str, Any],
        validate_results: ValidateStepResults,
    ) -> None:
        """Validate a single vault reference URI and record any error or warning."""
        from docpipe.integrations.secrets.secret_provider import (
            get_provider,
            parse_vault_reference,
        )

        try:
            provider_name, _, _ = parse_vault_reference(ref)
        except Exception:
            add_validation_alert(
                message=ValidationMessage(
                    message=f"Config key '{path}' contains a malformed vault URI: '{ref}'.",
                    message_code="VAULT_URI_MALFORMED",
                ),
                op_def=op_def,
                alerts=validate_results.errors,
            )
            return

        if not provider_name or get_provider(name=provider_name) is None:
            add_validation_alert(
                message=ValidationMessage(
                    message=(
                        f"Config key '{path}' references vault provider "
                        f"'{provider_name}' which is not currently registered. "
                        "Set DOCPIPE_VAULT_ENABLED=true and ensure "
                        "VAULT_ROLE_ID / VAULT_SECRET_ID are set."
                    ),
                    message_code="VAULT_PROVIDER_NOT_REGISTERED",
                ),
                op_def=op_def,
                alerts=validate_results.warnings,
            )

    def _validate_vault_references(self, *, dag: list, validate_results: ValidateStepResults) -> None:
        """Validate vault reference URIs and warn when referenced provider is not registered."""
        for op_def in dag:
            config = op_def.get(OperatorConstants.Config.CONFIG, {})
            for path, ref in self._collect_vault_refs(config):
                self._validate_single_vault_ref(
                    path=path,
                    ref=ref,
                    op_def=op_def,
                    validate_results=validate_results,
                )

    def validate_dag(self, *, flow_def: FlowConfig, global_config: FlowConfig) -> None:
        """Validate the DAG structure and all nodes.

        Performs comprehensive validation including structure checks, operator
        validation, and feature propagation. This is the standard validation
        method used by most validation workflows.

        Validation Steps:
            1. Check DAG exists and is non-empty
            2. Check for unnamed operators (warning)
            3. Check for duplicate operator names (error)
            4. Validate first operator is Ingest category
            5. Validate no disjoint (disconnected) operators
            6. Validate no cycles in the DAG
            7. Validate all operators are available/registered
            8. Traverse DAG and validate each node
            9. Validate last operator is VectorDB (warning if not)

        Args:
            flow_def: The flow definition dictionary containing:
                - dag: List of operator node definitions (required)
                - global_config: Optional global configuration
            global_config: Global configuration dictionary merged with flow_def config.
                Used for operator configuration and validation settings.

        Raises:
            FlowValidationException: If validation fails with errors or warnings.
                The exception contains:
                - errors: List of validation errors (non-empty means failure)
                - warnings: List of validation warnings (don't fail validation)

        Note:
            This method uses the flow_engine to traverse the DAG in topological
            order, validating each node and propagating features. The traversal
            is non-executing (no actual data processing).
        """
        logger.info("Validating DAG", extra=self.common_log_arguments)
        errors: list[Any] = []
        warnings: list[Any] = []

        dag = flow_def.get(DocpipeConstants.DAG, [])
        if not dag:
            errors.append(
                ValidationAlert(
                    ErrorCode.FLOW_VALIDATION_FAILED.value,
                    message=ValidationCodeMessages.DAG_PIPELINE_MISSING.value,
                    message_code=ValidationCodeMessages.DAG_PIPELINE_MISSING.name,
                )
            )
            raise FlowValidationException(errors=errors)

        unnamed_operators = [
            node[OperatorConstants.Misc.OPERATOR] for node in dag if OperatorConstants.Misc.NAME not in node
        ]
        if unnamed_operators:
            warnings.append(
                ValidationAlert(
                    ErrorCode.FLOW_VALIDATION_FAILED.value,
                    f"The following operators are missing names: {', '.join(unnamed_operators)}",
                )
            )

        # Operator name uniqueness check
        operator_names = [
            op_def[OperatorConstants.Columns.NAME] for op_def in dag if OperatorConstants.Columns.NAME in op_def
        ]
        duplicates = self.get_duplicate_node_names(nodes=operator_names)
        if duplicates:
            errors.append(
                ValidationAlert(
                    ErrorCode.FLOW_VALIDATION_FAILED.value,
                    message=ValidationCodeMessages.OPERATOR_NAME_REPEATED.value.format(operators=", ".join(duplicates)),
                    message_code=ValidationCodeMessages.OPERATOR_NAME_REPEATED.name,
                    operators=duplicates,
                )
            )
            self.logger.error("Duplicate operator names have been found with: %s", ",".join(duplicates))

        validate_results = ValidateStepResults(available_features={}, errors=errors, warnings=warnings)
        session_info = get_session_info()

        self._validate_global_config_values(global_config=global_config, validate_results=validate_results)
        self._validate_root_operator(dag=dag, validate_results=validate_results)
        self._validate_acl_operator_placement(dag=dag, validate_results=validate_results)
        self._validate_storage_output_operator_placement(dag=dag, validate_results=validate_results)
        self._validate_disjoint_operators(dag=dag, validate_results=validate_results)
        self._validate_no_cycles(dag=dag, validate_results=validate_results)
        self._validate_operator_availability(dag=dag, global_config=global_config, validate_results=validate_results)
        self._validate_vault_references(dag=dag, validate_results=validate_results)

        def node_validation_task(task_name, op_def, result=None, link_name=None):
            return self._validate_node(
                op_def=op_def,
                prev_result=result,
                global_config=global_config,
                validate_results=validate_results,
                session_info=session_info,
            )

        self._traverse_dag(dag=dag, task=node_validation_task)

        self.validate_last_operator(dag=dag, validate_results=validate_results)

        if validate_results.warnings:
            self.logger.warning("Validation warnings: %s", validate_results.warnings)
        if validate_results.errors:
            self.logger.error("Validation errors: %s", validate_results.errors)

        # Raise exception if there are errors OR warnings (warnings need to be returned to API)
        if validate_results.errors or validate_results.warnings:
            raise FlowValidationException(errors=validate_results.errors, warnings=validate_results.warnings)

    def validate_dag_with_features(
        self, *, flow_def: FlowConfig, global_config: FlowConfig
    ) -> FeaturePropagationResult:
        """Validate DAG and propagate features through all nodes.

        This method enhances the standard validate_dag() by adding feature propagation
        and returning detailed feature information for each node. It's the most
        comprehensive validation mode, used by the validation API.

        Process:
            1. Run standard validate_dag() - raises if validation fails
            2. Perform separate feature propagation traversal
            3. Collect feature metadata for all nodes
            4. Return FeaturePropagationResult with complete feature information

        The feature propagation traversal tracks:
            - Input features available to each node
            - Output features produced by each node
            - Feature metadata (description, tags, availability flags)
            - Global parameters (e.g., embeddings_model_id)
            - Features dropped by operators (e.g., SQLFilter)

        Args:
            flow_def: The flow definition dictionary containing:
                - dag: List of operator node definitions (required)
                - global_config: Optional global configuration
            global_config: Global configuration dictionary for operators

        Returns:
            FeaturePropagationResult containing:
                - available_features: Dict[node_id, List[feature_names]]
                - opensearch_features: Dict[node_id, List[vector_db_features]]
                - feature_metadata: Dict[feature_name, FeatureMetadata]
                - global_params: Dict[param_name, param_value]
                - output_features_to_drop: Dict[node_id, OutputFeaturesToDrop]

        Raises:
            FlowValidationException: If validation fails (from validate_dag call).
                Feature propagation only runs if validation succeeds.

        Example:
            ```python
            result = validator.validate_dag_with_features(
                flow_def=flow_def,
                global_config={}
            )

            # Check features available at specific node
            node_features = result.available_features.get("node-123", [])
            print(f"Features at node: {node_features}")

            # Check feature metadata
            for feature_name, metadata in result.feature_metadata.items():
                print(f"{feature_name}: {metadata.description}")
            ```

        Note:
            This method performs two DAG traversals: one for validation and one
            for feature propagation. For large DAGs, this may take longer than
            validate_dag() alone.

        See Also:
            - validate_dag: Standard validation without feature propagation
            - propagate_features_per_node: Per-node feature propagation results
            - FeaturePropagator.propagate_features: Core feature tracking logic
        """
        # First, run standard validation (this will raise if validation fails)
        self.validate_dag(flow_def=flow_def, global_config=global_config)

        # If validation passed, perform feature propagation
        logger.info("Performing feature propagation", extra=self.common_log_arguments)

        dag = flow_def.get(DocpipeConstants.DAG, [])
        propagation_result = FeaturePropagationResult()

        def feature_propagation_task(task_name, op_def, prev_result=None, link_name=None):
            """Task function for feature propagation traversal."""
            node_id, operator, operator_config = self._get_required_node_fields(op_def=op_def)
            parent_results = self._get_parent_results(prev_result=prev_result)
            node_result = self._build_node_feature_result(
                node_id=node_id,
                operator=operator,
                operator_config=operator_config,
                parent_results=parent_results,
                global_config=global_config,
            )
            self._merge_node_result_into_propagation_result(
                op_def=op_def,
                node_result=node_result,
                propagation_result=propagation_result,
            )
            return node_result

        self._traverse_dag(dag=dag, task=feature_propagation_task)

        logger.info(
            "Feature propagation complete: %d nodes processed",
            len(propagation_result.available_features),
            extra=self.common_log_arguments,
        )

        return propagation_result

    def _validate_node(
        self,
        *,
        op_def: dict[str, Any],
        prev_result: Any,
        global_config: dict[str, Any],
        validate_results: ValidateStepResults,
        session_info: Any,
    ) -> FeaturePropagationResult:
        """Validate a single DAG node and return its propagation result."""
        if session_info is not None:
            set_session_info(session_info=session_info)

        node_id, operator_name, operator_config = self._get_required_node_fields(op_def=op_def)
        parent_results = self._get_parent_results(prev_result=prev_result)
        node_result = self._build_node_feature_result(
            node_id=node_id,
            operator=operator_name,
            operator_config=operator_config,
            parent_results=parent_results,
            global_config=global_config,
        )

        input_features = list(node_result.get_input_features(node_id=node_id).keys())
        output_features = list(node_result.feature_metadata.keys())
        validate_results.available_features[node_id] = output_features

        operator_factory: OperatorFactory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON,
            package_names=self.orchestrator.custom_operator_packages,
            enable_custom_operators=self.orchestrator.enable_custom_operators,
        )

        # Skip validation if operator should not be validated
        if not self._evaluate_node_validation_skip(
            operator=operator_name,
            operator_factory=operator_factory,
            global_config=global_config,
        ):
            try:
                operator_class = operator_factory.operators.get(operator_name)

                if operator_class is not None:
                    config = (
                        global_config
                        | op_def.get(OperatorConstants.Config.CONFIG, {})
                        | {DocpipeConstants.VALIDATING_FLOW: True}
                    )
                    config = self._sanitize_vault_refs_for_validation(config)
                    operator = operator_class(config=config)
                    operator.name = op_def.get(OperatorConstants.Columns.NAME)
                    operator.id = op_def.get(OperatorConstants.Columns.ID)

                    errors: list[Any] = []
                    warnings: list[Any] = []
                    operator.validate(errors=errors, warnings=warnings, available_features=input_features)

                    self.create_validation_alerts(op_def=op_def, messages=errors, alerts=validate_results.errors)
                    self.create_validation_alerts(op_def=op_def, messages=warnings, alerts=validate_results.warnings)
                else:
                    add_validation_alert(
                        message=ValidationMessage(
                            message=f"Operator '{operator_name}' is not available. Please check operator name and registration.",
                            message_code="OPERATOR_NOT_AVAILABLE",
                        ),
                        op_def=op_def,
                        alerts=validate_results.errors,
                    )
            except FlowValidationException as exc:
                if exc.errors:
                    validate_results.errors.extend(exc.errors)
                if exc.warnings:
                    validate_results.warnings.extend(exc.warnings)
            except Exception as exc:
                add_validation_alert(
                    message=ValidationMessage(
                        message=f"Validation failed for operator '{operator_name}': {exc!s}",
                        message_code="OPERATOR_VALIDATION_FAILED",
                    ),
                    op_def=op_def,
                    alerts=validate_results.errors,
                )

        return node_result

    @staticmethod
    def _get_parent_results(*, prev_result: Any) -> list[FeaturePropagationResult]:
        """Normalize Prefect traversal input into a list of parent propagation results."""
        if isinstance(prev_result, FeaturePropagationResult):
            return [prev_result]
        if isinstance(prev_result, list):
            return [parent for parent in prev_result if isinstance(parent, FeaturePropagationResult)]
        if isinstance(prev_result, dict):
            return [parent for parent in prev_result.values() if isinstance(parent, FeaturePropagationResult)]
        return []

    @staticmethod
    def _feature_metadata_to_dict(*, result: FeaturePropagationResult) -> dict[str, dict[str, Any]]:
        """Convert node feature metadata into plain dictionaries for downstream propagation/debugging."""
        return {
            name: {
                "description": meta.description,
                "tags": meta.tags,
                "available_for_filter": meta.available_for_filter,
                "available_for_vector_db": meta.available_for_vector_db,
                "mandatory_for_vector_db": meta.mandatory_for_vector_db,
                "type": meta.type,
                "is_primary": meta.is_primary,
                **({"source_node_id": meta.node_id} if meta.node_id else {}),
            }
            for name, meta in result.feature_metadata.items()
        }

    @staticmethod
    def _get_required_node_fields(*, op_def: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        """Extract required propagation fields from a DAG node definition."""
        node_id = op_def.get(OperatorConstants.Misc.ID)
        operator = op_def.get(OperatorConstants.Misc.OPERATOR)
        operator_config = op_def.get(OperatorConstants.Config.CONFIG, {})

        if not isinstance(node_id, str) or not node_id:
            raise FlowValidationException(
                errors=[
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        message="Flow node is missing a valid id",
                        message_code="INVALID_FLOW_NODE_ID",
                    )
                ]
            )

        if not isinstance(operator, str) or not operator:
            raise FlowValidationException(
                errors=[
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        message=f"Flow node '{node_id}' is missing a valid operator",
                        message_code="INVALID_FLOW_NODE_OPERATOR",
                    )
                ]
            )

        if not isinstance(operator_config, dict):
            operator_config = {}

        return node_id, operator, operator_config

    def _build_node_feature_result(
        self,
        *,
        node_id: str,
        operator: str,
        operator_config: dict[str, Any],
        parent_results: list[FeaturePropagationResult],
        global_config: dict[str, Any],
    ) -> FeaturePropagationResult:
        """Build propagation state for a single node from its parents.

        Accepts pre-extracted fields so callers that already hold them (e.g.
        ``feature_debug_task``) avoid running ``_get_required_node_fields`` and
        ``_get_parent_results`` a second time.
        """
        input_features = self._merge_parent_input_features(
            parent_results=parent_results,
            operator=operator,
            operator_config=operator_config,
        )

        return self.feature_propagator.propagate_features(
            node_id=node_id,
            operator_short_name=operator,
            operator_config=operator_config,
            input_features=input_features,
            global_config=global_config,
            parent_results=parent_results,
            source_node_id=node_id,
        )

    def _merge_parent_input_features(
        self,
        *,
        parent_results: list[FeaturePropagationResult],
        operator: str,
        operator_config: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Build the flat ``input_features`` dict passed into ``propagate_features()``.

        For non-merge nodes (or a merge with only one upstream branch) a plain
        dict union is sufficient — there are no conflicting keys.

        For a merge node with multiple upstream branches, duplicate feature keys
        must be disambiguated so downstream propagation tracks which branch each
        column originates from.  The second and subsequent occurrences of a key
        are renamed ``<key>_<link_name>``, where the link name is resolved from
        ``operator_config["input_links"]`` via ``node_id_ref → link_name``.
        When a parent's ``source_node_id`` cannot be resolved in that map, the
        parent's numeric index is used as a fallback suffix.

        The join key (``"id"``) is never suffixed — the first occurrence always
        wins, consistent with the disambiguation logic in ``merge_features()``.
        """
        if operator != OperatorConstants.Operators.MERGE or len(parent_results) <= 1:
            input_features: dict[str, dict[str, Any]] = {}
            for parent_result in parent_results:
                input_features.update(self._feature_metadata_to_dict(result=parent_result))
            return input_features

        # Build node_id → link_name lookup from input_links in the operator config.
        input_links = operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
        node_id_to_link_name: dict[str, str] = {
            lnk["node_id_ref"]: lnk[OperatorConstants.Misc.LINK_NAME]
            for lnk in input_links
            if lnk.get("node_id_ref") and lnk.get(OperatorConstants.Misc.LINK_NAME)
        }

        join_key = OperatorConstants.Columns.ID
        merge_type = operator_config.get(OperatorConstants.Merge.MERGE_TYPE, OperatorConstants.Merge.ROWS)
        column_option = operator_config.get(OperatorConstants.Merge.COLUMN_OPTION)

        # For INNER_JOIN use the intersection of all parent feature sets so that
        # the input snapshot only contains features that will actually survive the
        # merge — branch-exclusive keys are excluded here rather than added and
        # then dropped inside _apply_special_case_logic.
        if (
            merge_type == OperatorConstants.Merge.COLUMNS
            and column_option == OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN
        ):
            common_keys: set[str] = set(self._feature_metadata_to_dict(result=parent_results[0]).keys())
            for pr in parent_results[1:]:
                common_keys.intersection_update(self._feature_metadata_to_dict(result=pr).keys())
            common_keys.add(join_key)
            output_feature_set = common_keys
        else:
            # ROWS and FULL_OUTER_JOIN both expose all keys from all parents.
            output_feature_set = {key for pr in parent_results for key in self._feature_metadata_to_dict(result=pr)}

        # Build (suffix, feature_dict) pairs for the shared disambiguation loop.
        parent_items: list[tuple[str, dict[str, Any]]] = []
        for index, parent_result in enumerate(parent_results):
            link_name = (
                node_id_to_link_name.get(parent_result.source_node_id) if parent_result.source_node_id else None
            ) or str(index)
            parent_items.append((link_name, self._feature_metadata_to_dict(result=parent_result)))

        return disambiguate_features(
            parent_items=parent_items,
            output_feature_set=output_feature_set,
            join_key=join_key,
        )

    def _merge_node_result_into_propagation_result(
        self,
        *,
        op_def: dict[str, Any],
        node_result: FeaturePropagationResult,
        propagation_result: FeaturePropagationResult,
    ) -> None:
        """Store per-node propagation output in the aggregate flow result."""
        node_id, _, _ = self._get_required_node_fields(op_def=op_def)
        feature_names = list(node_result.feature_metadata.keys())
        propagation_result.set_available_features(node_id=node_id, features=feature_names)

        opensearch_features = [
            name for name, meta in node_result.feature_metadata.items() if meta.available_for_vector_db
        ]
        if opensearch_features:
            propagation_result.set_opensearch_features(node_id=node_id, features=opensearch_features)

        for feature_name, feature_meta in node_result.feature_metadata.items():
            scoped_feature_name = f"{node_id}.{feature_name}"
            propagation_result.feature_metadata[scoped_feature_name] = feature_meta
            if feature_name not in propagation_result.feature_metadata:
                propagation_result.feature_metadata[feature_name] = feature_meta

        propagation_result.global_params.update(node_result.global_params)

        if node_id in node_result.output_features_to_drop:
            propagation_result.output_features_to_drop[node_id] = node_result.output_features_to_drop[node_id]

    def propagate_features_per_node(
        self, *, flow_def: FlowConfig, global_config: FlowConfig
    ) -> dict[str, dict[str, Any]]:
        """Propagate features through the DAG and return a per-node result dict.

        Unlike validate_dag_with_features(), this method does not raise on validation
        warnings, making it safe to call on in-progress flows. Each node in the DAG
        produces one entry in the returned dict regardless of validation state.

        The result is cached on the instance after the first call. When FlowExecutor
        calls validate() then propagate_features_per_node() on the same validator
        instance, the second DAG traversal is skipped entirely.
        """
        if self._node_features_cache is not None:
            return self._node_features_cache

        normalized_flow_def = flow_def
        if "definition" in normalized_flow_def:
            normalized_flow_def = normalized_flow_def["definition"]
        if "flow" in normalized_flow_def:
            normalized_flow_def = normalized_flow_def["flow"]

        dag = normalized_flow_def.get(DocpipeConstants.DAG, [])
        node_features: dict[str, dict[str, Any]] = {}
        parent_node_map: dict[str, list[str]] = {}

        for node in dag:
            node_id = node.get(OperatorConstants.Misc.ID)
            parent_ids = [edge.get("node_id_ref") for edge in node.get("input_edges", []) if edge.get("node_id_ref")]
            parent_node_map[node_id] = parent_ids

        def feature_debug_task(task_name, op_def, prev_result=None, link_name=None):
            node_id, operator, operator_config = self._get_required_node_fields(op_def=op_def)
            parent_results = self._get_parent_results(prev_result=prev_result)

            # Pass pre-extracted fields to avoid running _get_required_node_fields
            # and _get_parent_results a second time inside _build_node_feature_result.
            node_result = self._build_node_feature_result(
                node_id=node_id,
                operator=operator,
                operator_config=operator_config,
                parent_results=parent_results,
                global_config=global_config,
            )

            snapshot: dict[str, Any] = {
                "node_id": node_id,
                "node_name": op_def.get(OperatorConstants.Misc.NAME),
                "operator": operator,
                "operator_config": operator_config,
                "parent_node_ids": parent_node_map.get(node_id, []),
                "input_features": node_result.get_input_features(node_id=node_id),
                "output_features": node_result.get_output_features(node_id=node_id),
                "available_features": self._feature_metadata_to_dict(result=node_result),
                "dropped_features": sorted(
                    node_result.get_output_features_to_drop(node_id=node_id).get_features_to_drop()
                ),
                "global_params": dict(node_result.global_params),
            }

            # Expose parent FeaturePropagationResult objects for merge strategy
            # computation in FlowEnrichmentService._build_node_feature_metadata().
            if operator == OperatorConstants.Operators.MERGE:
                snapshot["parent_results"] = parent_results

            node_features[node_id] = snapshot

            return node_result

        self._traverse_dag(dag=dag, task=feature_debug_task)
        self._node_features_cache = node_features
        return node_features

    @staticmethod
    def _traverse_dag(*, dag: list, task: Any) -> None:
        """Traverse the DAG in topological order, calling task for each node.

        Replaces the previous Prefect-based traversal. Delegates ordering to
        ``sort_dag_topologically`` (shared utility, Kahn's algorithm) so this
        method is correct for all DAG shapes regardless of input list order,
        including branch+merge flows where the merge node has multiple parents.

        Parent results are resolved from a node-keyed results dict and passed
        into the task function in the same shape the previous Prefect traversal
        used:
        - No parents (root node)   → None
        - Single parent            → the parent result directly
        - Multiple parents (merge) → dict of {link_name: result}

        Args:
            dag: List of DAG node definitions. Order need not be topological.
            task: Callable with signature
                ``task(task_name, op_def, prev_result, link_name) -> Any``.
                The return value is stored and forwarded to downstream nodes.
        """
        from docpipe.utils.orchestration.flow_utils import sort_dag_topologically

        results: dict[str, Any] = {}

        for op_def in sort_dag_topologically(dag=dag):
            node_id = op_def["id"]
            input_edges = op_def.get("input_edges", [])
            link_name = op_def.get(OperatorConstants.Misc.LINK_NAME)
            task_name = op_def.get(OperatorConstants.Columns.NAME, node_id)

            if not input_edges:
                prev_result = None
            elif len(input_edges) == 1:
                prev_result = results.get(input_edges[0]["node_id_ref"])
            else:
                prev_result = {
                    edge.get(OperatorConstants.Misc.LINK_NAME): results.get(edge["node_id_ref"]) for edge in input_edges
                }

            results[node_id] = task(task_name, op_def, prev_result, link_name)

    @staticmethod
    def _validate_global_config_values(*, global_config: dict[str, Any], validate_results: ValidateStepResults) -> None:
        """Validate global configuration values such as doc_format."""
        doc_format = global_config.get(OperatorConstants.DOC_FORMAT_KEY)
        if doc_format is not None:
            valid_formats = [f.value for f in OperatorConstants.DocFormat]
            if doc_format not in valid_formats:
                validate_results.errors.append(
                    ValidationAlert(
                        ErrorCode.FLOW_VALIDATION_FAILED.value,
                        f"Invalid doc_format '{doc_format}'. Supported values are: {', '.join(valid_formats)}",
                    )
                )

    def _validate_root_operator(self, *, dag: list, validate_results: ValidateStepResults):
        """Validate that the root operator of the DAG (no incoming edges) is an Ingest operator.

        Args:
            dag: List of operator definitions
            validate_results: Container for validation results
        """
        # Find the topological root — the node with no incoming edges — regardless of JSON array order.
        reverse_graph = self._build_reverse_graph(dag=dag)
        root_node = next(node for node in dag if not reverse_graph.get(node["id"]))
        self._validate_operator_category(
            op_def=root_node,
            expected_category=OperatorCategory.Ingest,
            error_message=ValidationMessage(
                message=ValidationCodeMessages.INGEST_OPERATOR_MISPLACED.value,
                message_code=ValidationCodeMessages.INGEST_OPERATOR_MISPLACED.name,
            ),
            alerts=validate_results.errors,
        )

    def _validate_disjoint_operators(self, *, dag: list, validate_results: ValidateStepResults):
        """Validate that the DAG does not contain disconnected (disjoint) operators.

        Args:
            dag: List of operator definitions
            validate_results: Container for validation results
        """
        graph = self._build_graph(dag=dag)
        undirected = self._make_undirected_graph(graph)
        components = self._find_connected_components(undirected)

        id_to_index = {n["id"]: i for i, n in enumerate(dag)}
        reported_nodes: set[str] = set()
        reverse_graph: dict[str, list[str]] = self._build_reverse_graph(dag=dag)

        if len(components) > 1:
            self._validate_disconnected_components(
                components=components,
                graph=graph,
                dag=dag,
                id_to_index=id_to_index,
                validate_results=validate_results,
                reported_nodes=reported_nodes,
            )
        # check if any nodes are isolated
        self._validate_isolated_nodes(
            dag=dag,
            graph=graph,
            reverse_graph=reverse_graph,
            reported_nodes=reported_nodes,
            validate_results=validate_results,
        )

    @staticmethod
    def _build_reverse_graph(*, dag: list) -> dict:
        """Build reverse graph to find nodes without inputs."""
        reverse_graph: dict[str, list[str]] = {n["id"]: [] for n in dag}
        for node in dag:
            for edge in node.get("output_edges", []):
                target_node_id = edge.get("node_id_ref")
                if target_node_id and target_node_id in reverse_graph:
                    reverse_graph[target_node_id].append(node["id"])
        return reverse_graph

    def _validate_disconnected_components(
        self,
        *,
        components: list,
        graph: dict,
        dag: list,
        id_to_index: dict,
        validate_results: ValidateStepResults,
        reported_nodes: set,
    ):
        """Validate disconnected components and report terminal nodes that are not VectorDB operators."""
        for component in components:
            terminal_node_id = self._find_terminal_node(component=component, graph=graph)
            if terminal_node_id is None:
                continue

            self._report_non_vectordb_terminal(
                terminal_node_id=terminal_node_id,
                id_to_index=id_to_index,
                dag=dag,
                validate_results=validate_results,
                reported_nodes=reported_nodes,
            )

    @staticmethod
    def _find_terminal_node(*, component: set, graph: dict) -> str | None:
        """Find the terminal node (node with no outgoing edges) in a component."""
        for node_id in component:
            if not graph.get(node_id, []):
                return node_id
        return None

    @staticmethod
    def _find_all_terminal_nodes(graph: dict) -> list[str]:
        """Find all terminal nodes (nodes with no outgoing edges) in a graph."""
        return [node_id for node_id, neighbors in graph.items() if not neighbors]

    def _report_non_vectordb_terminal(
        self,
        *,
        terminal_node_id: str,
        id_to_index: dict,
        dag: list,
        validate_results: ValidateStepResults,
        reported_nodes: set,
    ):
        """Report terminal node if it's not a VectorDB operator."""
        index = id_to_index.get(terminal_node_id)
        if index is None:
            return

        terminal_node = dag[index]
        category = self._get_operator_category(op_def=terminal_node, alerts=validate_results.errors)

        if category != OperatorCategory.VectorDB:
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.DISJOINT_OPERATORS_DETECTED.value,
                    message_code=ValidationCodeMessages.DISJOINT_OPERATORS_DETECTED.name,
                ),
                op_def=terminal_node,
                alerts=validate_results.errors,
            )
            reported_nodes.add(terminal_node_id)

    @staticmethod
    def _validate_isolated_nodes(
        *, dag: list, graph: dict, reverse_graph: dict, reported_nodes: set, validate_results: ValidateStepResults
    ):
        """Check for isolated nodes (nodes with no input AND no output)."""
        for node in dag:
            node_id = node.get("id")
            if not node_id or node_id in reported_nodes:
                continue

            has_output = bool(graph.get(node_id, []))
            has_input = bool(reverse_graph.get(node_id, []))

            if not has_output and not has_input:
                add_validation_alert(
                    message=ValidationMessage(
                        message=ValidationCodeMessages.DISJOINT_OPERATORS_DETECTED.value,
                        message_code=ValidationCodeMessages.DISJOINT_OPERATORS_DETECTED.name,
                    ),
                    op_def=node,
                    alerts=validate_results.errors,
                )

    @staticmethod
    def _find_acl_parent_operators(*, dag: list, acl_node_id: str) -> list[dict]:
        """Find parent operators of the ACL operator from DAG output edges."""
        parent_map: dict[str, list[str]] = {n[OperatorConstants.Misc.ID]: [] for n in dag}
        for node in dag:
            output_edges = node.get(DocpipeConstants.OUTPUT_EDGES, [])
            for edge in output_edges:
                target_id = edge.get("node_id_ref")
                if target_id and target_id in parent_map:
                    parent_map[target_id].append(node[OperatorConstants.Misc.ID])

        parent_ids = parent_map.get(acl_node_id, [])
        return [node for node in dag if node.get(OperatorConstants.Misc.ID) in parent_ids]

    @staticmethod
    def _validate_acl_ingest_provider(
        *, acl_node: dict, ingest_source_parent: dict, validate_results: ValidateStepResults
    ) -> None:
        """Validate that ingest_source parent uses SharePoint provider."""
        provider = ingest_source_parent.get(OperatorConstants.Config.CONFIG, {}).get("provider", "").lower()
        if provider != "sharepoint":
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.ACL_INVALID_PROVIDER.value.format(provider=provider),
                    message_code=ValidationCodeMessages.ACL_INVALID_PROVIDER.name,
                ),
                op_def=acl_node,
                alerts=validate_results.errors,
            )

    def _validate_acl_parent_operator(
        self,
        *,
        acl_node: dict,
        parent_operator: dict,
        validate_results: ValidateStepResults,
    ) -> None:
        """Validate single parent operator of ACL operator."""
        parent_op_name = parent_operator.get(OperatorConstants.Misc.OPERATOR)
        parent_metadata = self.operator_metadata.operator_metadata.get(parent_op_name, {})
        parent_category = parent_metadata.get(OperatorConstants.Misc.CATEGORY)

        if parent_category != OperatorCategory.Ingest:
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.ACL_OPERATOR_MISPLACED.value.format(
                        predecessor_operator=parent_op_name or "unknown"
                    ),
                    message_code=ValidationCodeMessages.ACL_OPERATOR_MISPLACED.name,
                ),
                op_def=acl_node,
                alerts=validate_results.errors,
            )
        elif parent_op_name == OperatorConstants.Operators.INGEST_SOURCE:
            self._validate_acl_ingest_provider(
                acl_node=acl_node,
                ingest_source_parent=parent_operator,
                validate_results=validate_results,
            )

    def _validate_acl_operator_placement(self, *, dag: list, validate_results: ValidateStepResults):
        """Validate ACL operator placement in the DAG.

        ACL operator must be placed immediately after an ingest_source operator.
        Only one ACL operator is allowed per flow.

        Args:
            dag: List of operator definitions
            validate_results: Step results tracking validation errors/warnings
        """
        acl_nodes = [
            node
            for node in dag
            if node.get(OperatorConstants.Misc.OPERATOR) == OperatorConstants.Operators.ACL_OPERATOR
        ]
        if not acl_nodes:
            return

        if len(acl_nodes) > 1:
            for acl_node in acl_nodes:
                add_validation_alert(
                    message=ValidationMessage(
                        message=ValidationCodeMessages.MULTIPLE_ACL_OPERATORS.value,
                        message_code=ValidationCodeMessages.MULTIPLE_ACL_OPERATORS.name,
                    ),
                    op_def=acl_node,
                    alerts=validate_results.errors,
                )
            return

        acl_node = acl_nodes[0]
        acl_node_id = acl_node.get(OperatorConstants.Misc.ID)
        parent_operators = self._find_acl_parent_operators(dag=dag, acl_node_id=acl_node_id)

        if not parent_operators:
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.ACL_OPERATOR_NO_INPUT.value,
                    message_code=ValidationCodeMessages.ACL_OPERATOR_NO_INPUT.name,
                ),
                op_def=acl_node,
                alerts=validate_results.errors,
            )
            return

        if len(parent_operators) > 1:
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.ACL_MULTIPLE_PARENTS.value.format(
                        parent_count=len(parent_operators)
                    ),
                    message_code=ValidationCodeMessages.ACL_MULTIPLE_PARENTS.name,
                ),
                op_def=acl_node,
                alerts=validate_results.errors,
            )
            return

        self._validate_acl_parent_operator(
            acl_node=acl_node,
            parent_operator=parent_operators[0],
            validate_results=validate_results,
        )

    @staticmethod
    def _validate_storage_output_operator_placement(*, dag: list, validate_results: ValidateStepResults):
        """Validate that storage_output operators using refetch_original or comprehensive_export
        have an upstream ingest_source operator in the DAG.

        This check cannot be done inside StorageOutputOperator.validate() because
        the ingest_source config key is only populated in global_config at runtime,
        not during flow validation.
        """
        _modes_requiring_ingest_source = {"refetch_original", "comprehensive_export"}

        storage_nodes = [
            node
            for node in dag
            if node.get(OperatorConstants.Misc.OPERATOR) == OperatorConstants.Operators.STORAGE_OUTPUT
            and node.get(OperatorConstants.Config.CONFIG, {}).get("mode") in _modes_requiring_ingest_source
        ]
        if not storage_nodes:
            return

        # Build a reverse-edge map: node_id -> list of parent node_ids
        parent_map: dict[str, list[str]] = {n[OperatorConstants.Misc.ID]: [] for n in dag}
        for node in dag:
            for edge in node.get(DocpipeConstants.OUTPUT_EDGES, []):
                target_id = edge.get("node_id_ref")
                if target_id and target_id in parent_map:
                    parent_map[target_id].append(node[OperatorConstants.Misc.ID])

        # Map node_id -> operator name for ancestor lookup
        id_to_operator: dict[str, str] = {
            n[OperatorConstants.Misc.ID]: n.get(OperatorConstants.Misc.OPERATOR, "") for n in dag
        }

        def _has_ingest_source_ancestor(node_id: str) -> bool:
            """BFS/DFS walk upward to find any ingest_source ancestor."""
            visited: set[str] = set()
            stack = list(parent_map.get(node_id, []))
            while stack:
                pid = stack.pop()
                if pid in visited:
                    continue
                visited.add(pid)
                if id_to_operator.get(pid) == OperatorConstants.Operators.INGEST_SOURCE:
                    return True
                stack.extend(parent_map.get(pid, []))
            return False

        for node in storage_nodes:
            mode = node.get(OperatorConstants.Config.CONFIG, {}).get("mode", "")
            if not _has_ingest_source_ancestor(node[OperatorConstants.Misc.ID]):
                add_validation_alert(
                    message=ValidationMessage(
                        message=ValidationCodeMessages.STORAGE_OUTPUT_REQUIRES_INGEST_SOURCE.value.format(mode=mode),
                        message_code=ValidationCodeMessages.STORAGE_OUTPUT_REQUIRES_INGEST_SOURCE.name,
                    ),
                    op_def=node,
                    alerts=validate_results.errors,
                )

    @staticmethod
    def _build_graph(*, dag: list) -> dict:
        """Build a directed graph representation from the DAG.

        Args:
            dag: List of operator definitions

        Returns:
            Dictionary mapping node IDs to lists of connected node IDs
        """
        graph: dict[str, list[str]] = {n["id"]: [] for n in dag}
        for node in dag:
            output_edges = node.get(DocpipeConstants.OUTPUT_EDGES, [])
            for edge in output_edges:
                graph[node["id"]].append(edge["node_id_ref"])
        return graph

    @staticmethod
    def _make_undirected_graph(graph: dict) -> dict:
        """Convert a directed graph into an undirected graph for disjoint detection.

        Args:
            graph: Directed graph dictionary

        Returns:
            Undirected graph dictionary
        """
        undirected: dict[str, set[str]] = {n: set() for n in graph}
        for src, outs in graph.items():
            for dst in outs:
                undirected[src].add(dst)
                undirected[dst].add(src)
        return undirected

    @staticmethod
    def _find_connected_components(undirected: dict) -> list:
        """Find connected components in an undirected graph.

        Args:
            undirected: Undirected graph dictionary

        Returns:
            List of sets, each containing node IDs in a connected component
        """
        visited = set()
        components = []

        for node in undirected:
            if node not in visited:
                stack = [node]
                comp = set()
                while stack:
                    x = stack.pop()
                    if x not in visited:
                        visited.add(x)
                        comp.add(x)
                        stack.extend(undirected[x])
                components.append(comp)
        return components

    def _check_duplicate_extract_operators(self, *, sequence, errors):
        """Check for duplicate extract operators in the sequence.

        Args:
            sequence: List of operator definitions
            global_config: Global configuration dictionary
            errors: List to collect error alerts

        Returns:
            Count of extract operators found
        """
        # Get the count of extract operators in the flow.
        extract_operator_count = 0

        for _, op_def in enumerate(sequence):
            category = self._get_operator_category(op_def=op_def, alerts=errors)
            if category == OperatorCategory.Extract:
                extract_operator_count += 1

                if extract_operator_count > 1:
                    add_validation_alert(
                        ValidationMessage(
                            message="Multiple extract operators detected. Ensure they are used correctly",
                            message_code=ValidationCodeMessages.MULTIPLE_EXTRACTED_DETECTED.name,
                        ),
                        op_def=op_def,
                        alerts=errors,
                    )

        return extract_operator_count

    def validate_last_operator(self, *, dag: list, validate_results: ValidateStepResults):
        """Validate that every terminal node in the DAG is a VectorDB or Storage operator.

        A terminal node is any node with no outgoing edges. In a branching flow there
        can be more than one terminal node, so each branch end is checked independently.
        A warning is emitted for every terminal node that is not a VectorDB or Storage operator.
        """
        if not dag:
            return

        graph = self._build_graph(dag=dag)
        id_to_index = {node["id"]: i for i, node in enumerate(dag)}

        for terminal_node_id in self._find_all_terminal_nodes(graph):
            index = id_to_index.get(terminal_node_id)
            if index is None:
                continue
            terminal_node = dag[index]
            category = self._get_operator_category(op_def=terminal_node, alerts=validate_results.errors)
            if category not in (OperatorCategory.VectorDB, OperatorCategory.Storage):
                add_validation_alert(
                    message=ValidationMessage(
                        message=ValidationCodeMessages.GENERATE_OUTPUT_MISSING.value,
                        message_code=ValidationCodeMessages.GENERATE_OUTPUT_MISSING.name,
                    ),
                    op_def=terminal_node,
                    alerts=validate_results.warnings,
                )

    def _validate_no_cycles(self, *, dag: list, validate_results: ValidateStepResults):
        """Validate that the DAG does not contain cycles.

        Uses depth-first search with recursion stack to detect cycles.

        Args:
            dag: List of operator definitions
            validate_results: Container for validation results
        """
        graph = self._build_graph(dag=dag)
        visited = set()
        rec_stack = set()

        def has_cycle(node_id: str) -> bool:
            """DFS helper to detect cycles."""
            visited.add(node_id)
            rec_stack.add(node_id)

            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node_id)
            return False

        # Check each node for cycles
        for node in dag:
            node_id = node.get("id")
            if node_id and node_id not in visited:
                if has_cycle(node_id):
                    add_validation_alert(
                        message=ValidationMessage(
                            message="Cyclic dependency detected in DAG. Flows must be acyclic.",
                            message_code="CYCLIC_DEPENDENCY_DETECTED",
                        ),
                        op_def=node,
                        alerts=validate_results.errors,
                    )
                    break

    def _validate_operator_availability(self, *, dag: list, global_config: dict, validate_results: ValidateStepResults):
        """Validate that all operators in the DAG are available in the operator factory.

        Performs early check before DAG traversal to fail fast with clear error.

        Args:
            dag: List of operator definitions
            global_config: Global configuration dictionary
            validate_results: Container for validation results
        """
        operator_factory: OperatorFactory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON,
            package_names=self.orchestrator.custom_operator_packages,
            enable_custom_operators=self.orchestrator.enable_custom_operators,
        )

        for node in dag:
            operator_name = node.get(OperatorConstants.Misc.OPERATOR)

            # Skip validation for custom operators if configured
            if self._evaluate_node_validation_skip(
                operator=operator_name, operator_factory=operator_factory, global_config=global_config
            ):
                continue

            # Check if operator exists in factory
            if operator_name and operator_name not in operator_factory.operators:
                add_validation_alert(
                    message=ValidationMessage(
                        message=f"Operator '{operator_name}' is not available. Please check operator name and registration.",
                        message_code="OPERATOR_NOT_AVAILABLE",
                    ),
                    op_def=node,
                    alerts=validate_results.errors,
                )

    def _validate_operator_category(
        self,
        *,
        op_def: dict,
        expected_category: str,
        error_message: ValidationMessage,
        alerts: list,
    ):
        """Validate that an operator belongs to the expected category.

        Args:
            op_def: Operator definition dictionary
            expected_category: Expected operator category
            error_message: Error message to add if validation fails
            alerts: List to collect alerts
        """
        category = self._get_operator_category(op_def=op_def, alerts=alerts)
        if category != expected_category:
            add_validation_alert(message=error_message, op_def=op_def, alerts=alerts)

    def _get_operator_category(self, *, op_def: dict, alerts: list):
        """Get the category of an operator.

        Args:
            op_def: Operator definition dictionary
            alerts: List to collect alerts

        Returns:
            Operator category

        Raises:
            FlowValidationException: If operator cannot be created
        """
        if OperatorConstants.Columns.ID not in op_def:
            add_validation_alert(
                ValidationMessage(
                    message=ValidationCodeMessages.MISSING_NODE_ID.value,
                    message_code=ValidationCodeMessages.MISSING_NODE_ID.name,
                ),
                op_def=op_def,
                alerts=alerts,
            )
        if OperatorConstants.Columns.NAME not in op_def:
            add_validation_alert(
                message=ValidationMessage(
                    message=ValidationCodeMessages.MISSING_NODE_NAME.value,
                    message_code=ValidationCodeMessages.MISSING_NODE_NAME.name,
                ),
                op_def=op_def,
                alerts=alerts,
            )
        # Get operator name from definition
        operator_name = op_def.get(OperatorConstants.Misc.OPERATOR)
        if not operator_name:
            add_validation_alert(
                ValidationMessage(
                    message="Operator name is missing from node definition",
                    message_code="MISSING_OPERATOR_NAME",
                ),
                op_def=op_def,
                alerts=alerts,
            )
            return None

        # Look up category from cached metadata (avoids operator instantiation)
        metadata = self.operator_metadata.operator_metadata.get(operator_name, {})
        category = metadata.get(OperatorConstants.Misc.CATEGORY)

        if category is None:
            add_validation_alert(
                ValidationMessage(
                    message=f"Could not determine category for operator '{operator_name}'. Operator may not be registered or metadata is unavailable.",
                    message_code="OPERATOR_CATEGORY_UNKNOWN",
                ),
                op_def=op_def,
                alerts=alerts,
            )
            return None

        return category

    @staticmethod
    def create_validation_alerts(*, op_def: dict, messages: list, alerts: list, **kwargs):
        """Create validation alerts from a list of messages.

        Args:
            op_def: Operator definition dictionary
            messages: List of validation messages
            alerts: List to collect alerts
            **kwargs: Additional keyword arguments for alert creation
        """
        for message in messages:
            add_validation_alert(message=message, op_def=op_def, alerts=alerts, **kwargs)

    @staticmethod
    def get_duplicate_node_names(*, nodes):
        """Get duplicate names of nodes from pipeline.

        Args:
            nodes: List of node names

        Returns:
            List of duplicate node names
        """
        return [item for item in set(nodes) if nodes.count(item) > 1]

    @staticmethod
    def _evaluate_node_validation_skip(
        *, operator: str, operator_factory: OperatorFactory, global_config: dict
    ) -> bool:
        """Evaluate whether to skip validation for a custom operator.

        Args:
            operator: Operator name
            operator_factory: Operator factory instance
            global_config: Global configuration dictionary

        Returns:
            True if validation should be skipped, False otherwise
        """
        if (
            DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION in global_config
            and global_config[DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION]
            and operator not in operator_factory.operators
        ):
            return True
        return False
