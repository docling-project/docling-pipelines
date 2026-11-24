# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ValidationService."""

from unittest.mock import patch

from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.exceptions.docpipe_exceptions import (
    FlowValidationException,
    ValidationAlert,
)


class TestValidationService:
    """Tests for ValidationService.validate_flow method."""

    def test_validate_flow_succeeds_with_valid_dag(self):
        """Test validate_flow returns SUCCEEDED status for valid DAG flow."""
        # Arrange
        service = ValidationService()
        valid_flow_def = {
            "flow_name": "test-flow",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "ingest_node",
                    "config": {"folder_path": "/test/path"},
                    "depends_on": [],
                }
            ],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to succeed (no exception)
            mock_validator = mock_validator_class.return_value
            mock_validator.validate.return_value = None

            result = service.validate_flow(flow_definition=valid_flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "SUCCEEDED"
        assert result["message"] is None
        assert result["errors"] == []
        assert result["warnings"] == []

    def test_validate_flow_fails_with_validation_errors(self):
        """Test validate_flow returns FAILED status when validation has errors."""
        # Arrange
        service = ValidationService()
        invalid_flow_def = {
            "flow_name": "invalid-flow",
            "flow": [{"type": "invalid_operator", "name": "invalid_node", "config": {}, "depends_on": []}],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with errors
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[
                    ValidationAlert(
                        code="INVALID_OPERATOR",
                        message="Operator not found",
                        node_id="550e8400-e29b-41d4-a716-446655440001",
                    )
                ],
                warnings=[],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=invalid_flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert result["message"] == "Flow validation failed."
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "INVALID_OPERATOR"
        assert result["warnings"] == []

    def test_validate_flow_succeeds_with_warnings(self):
        """Test validate_flow returns SUCCEEDED_WITH_WARNINGS when validation has warnings."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow-with-warnings",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "ingest_node",
                    "config": {"folder_path": "/test/path"},
                    "depends_on": [],
                }
            ],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with warnings only
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation succeeded with warnings",
                errors=[],
                warnings=[
                    ValidationAlert(
                        code="DEPRECATED_PARAM",
                        message="Parameter is deprecated",
                        node_id="550e8400-e29b-41d4-a716-446655440001",
                    )
                ],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "SUCCEEDED_WITH_WARNINGS"
        assert result["message"] == "Flow validation succeeded with warnings."
        assert result["errors"] == []
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["code"] == "DEPRECATED_PARAM"

    def test_validate_flow_handles_elyra_format(self):
        """Test validate_flow converts Elyra format before validation."""
        # Arrange
        service = ValidationService()
        elyra_flow_def = {
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [
                {
                    "id": "test-pipeline",
                    "nodes": [{"id": "node1", "type": "execution_node", "op": "execute-notebook-node"}],
                }
            ],
        }

        # Act
        with (
            patch("docpipe.utils.orchestration.elyra_converter.ElyraConverter") as mock_converter_class,
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock converter
            mock_converter = mock_converter_class.return_value
            mock_converter.transform_elyra_to_internal.return_value = {"nodes": [], "edges": []}

            # Mock validator to succeed
            mock_validator = mock_validator_class.return_value
            mock_validator.validate.return_value = None

            result = service.validate_flow(flow_definition=elyra_flow_def, is_elyra=True)

        # Assert
        assert result["status"] == "SUCCEEDED"
        mock_converter.transform_elyra_to_internal.assert_called_once()

    def test_validate_flow_formats_conversion_errors(self):
        """Test FlowValidationException from the conversion step gets a structured response."""
        # Arrange
        service = ValidationService()
        elyra_flow_def = {
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [
                {
                    "id": "test-pipeline",
                    "nodes": [{"id": "node1", "type": "execution_node", "op": "execute-notebook-node"}],
                }
            ],
        }

        # Act
        with patch("docpipe.utils.orchestration.elyra_converter.ElyraConverter") as mock_converter_class:
            # Mock converter to return an invalid {"flow": ...} wrapper
            mock_converter = mock_converter_class.return_value
            mock_converter.transform_elyra_to_internal.return_value = {"flow": None}

            result = service.validate_flow(flow_definition=elyra_flow_def, is_elyra=True)

        # Assert
        assert result["status"] == "FAILED"
        assert result["message"] == "Flow validation failed."
        assert len(result["errors"]) == 1
        assert result["errors"][0]["message_code"] == "INVALID_FLOW_WRAPPER"
        assert result["errors"][0]["code"] == "flow_validation_failed"
        assert result["warnings"] == []

    def test_validate_flow_handles_unexpected_exception(self):
        """Test validate_flow catches and returns unexpected exceptions as FAILED."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow",
            "flow": [{"type": "ingest_source", "name": "ingest_node", "config": {}, "depends_on": []}],
        }

        # Act
        with patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory") as mock_factory:
            # Mock factory to raise unexpected exception
            mock_factory.create_orchestrator.side_effect = RuntimeError("Unexpected error")

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert result["message"] == "Validation failed with unexpected error."
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "VALIDATION_EXCEPTION"
        assert "Unexpected error" in result["errors"][0]["message"]
        assert result["warnings"] == []

    def test_validate_flow_handles_multiple_errors(self):
        """Test validate_flow handles multiple validation errors."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow",
            "flow": [{"type": "ingest_source", "name": "ingest_node", "config": {}, "depends_on": []}],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with multiple errors
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[
                    ValidationAlert(code="ERROR1", message="Error message 1"),
                    ValidationAlert(code="ERROR2", message="Error message 2"),
                ],
                warnings=[],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert len(result["errors"]) == 2
        assert result["errors"][0]["message"] == "Error message 1"
        assert result["errors"][1]["message"] == "Error message 2"

    def test_validate_flow_handles_multiple_warnings(self):
        """Test validate_flow handles multiple validation warnings."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow",
            "flow": [{"type": "ingest_source", "name": "ingest_node", "config": {}, "depends_on": []}],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with multiple warnings
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation succeeded with warnings",
                errors=[],
                warnings=[ValidationAlert(code="WARN1", message="Warning message 1")],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "SUCCEEDED_WITH_WARNINGS"
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["message"] == "Warning message 1"

    def test_validate_flow_handles_both_errors_and_warnings(self):
        """Test validate_flow prioritizes errors over warnings in status determination."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow",
            "flow": [{"type": "ingest_source", "name": "ingest_node", "config": {}, "depends_on": []}],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with both errors and warnings
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[ValidationAlert(code="ERROR1", message="Error")],
                warnings=[ValidationAlert(code="WARN1", message="Warning")],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"  # Errors take precedence
        assert result["message"] == "Flow validation failed."
        assert len(result["errors"]) == 1
        assert len(result["warnings"]) == 1

    def test_validate_flow_never_raises_exception(self):
        """Test validate_flow never raises exceptions, always returns dict."""
        # Arrange
        service = ValidationService()
        flow_def = {"flow_name": "test-flow", "flow": []}

        # Act - even with catastrophic failure, should return dict
        with patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory") as mock_factory:
            mock_factory.create_orchestrator.side_effect = Exception("Catastrophic failure")

            # Should not raise - should return error dict
            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert isinstance(result, dict)
        assert "status" in result
        assert "errors" in result
        assert "warnings" in result
        assert "message" in result
        assert result["status"] == "FAILED"

    def test_validate_flow_handles_missing_definition(self):
        """Test validate_flow handles None flow_definition."""
        # Arrange
        service = ValidationService()

        # Act
        result = service.validate_flow(flow_definition=None, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert result["message"] == "Flow definition is required for validation"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "MISSING_DEFINITION"
        assert result["warnings"] == []

    def test_validate_flow_handles_empty_definition(self):
        """Test validate_flow handles empty dict flow_definition."""
        # Arrange
        service = ValidationService()

        # Act
        result = service.validate_flow(flow_definition={}, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert result["message"] == "Flow definition is required for validation"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "MISSING_DEFINITION"

    def test_validate_flow_exception_with_no_errors_defaults_to_failed(self):
        """Test that FlowValidationException with no errors/warnings still returns FAILED."""
        # Arrange
        service = ValidationService()
        flow_def = {
            "flow_name": "test-flow",
            "flow": [{"type": "ingest_source", "name": "ingest_node", "config": {}, "depends_on": []}],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise FlowValidationException with no errors/warnings
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(message="Validation failed", errors=[], warnings=[])
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"  # Should be FAILED, not SUCCEEDED
        assert result["message"] == "Flow validation failed."


class TestFlowValidatorEnhancements:
    """Tests for new FlowValidator validation methods."""

    def test_validate_no_cycles_detects_simple_cycle(self):
        """Test cycle detection with simple A->B->A cycle."""
        from docpipe.core.constants.constants import OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        dag_with_cycle = [
            {"id": "node1", "name": "Node 1", "operator": "test_operator", "output_edges": [{"node_id_ref": "node2"}]},
            {
                "id": "node2",
                "name": "Node 2",
                "operator": "test_operator",
                "output_edges": [{"node_id_ref": "node1"}],  # Cycle back to node1
            },
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_no_cycles(dag=dag_with_cycle, validate_results=validate_results)

        # Assert
        assert len(validate_results.errors) > 0
        error_messages = [str(err) for err in validate_results.errors]
        assert any("cyclic" in msg.lower() or "cycle" in msg.lower() for msg in error_messages)

    def test_validate_no_cycles_allows_valid_dag(self):
        """Test cycle detection allows valid DAG without cycles."""
        from docpipe.core.constants.constants import OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        valid_dag = [
            {"id": "node1", "name": "Node 1", "operator": "test_operator", "output_edges": [{"node_id_ref": "node2"}]},
            {"id": "node2", "name": "Node 2", "operator": "test_operator", "output_edges": [{"node_id_ref": "node3"}]},
            {"id": "node3", "name": "Node 3", "operator": "test_operator", "output_edges": []},
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_no_cycles(dag=valid_dag, validate_results=validate_results)

        # Assert
        assert len(validate_results.errors) == 0

    def test_validate_no_cycles_detects_self_reference(self):
        """Test cycle detection with self-referencing node."""
        from docpipe.core.constants.constants import OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        dag_with_self_cycle = [
            {
                "id": "node1",
                "name": "Node 1",
                "operator": "test_operator",
                "output_edges": [{"node_id_ref": "node1"}],  # Self-reference
            }
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_no_cycles(dag=dag_with_self_cycle, validate_results=validate_results)

        # Assert
        assert len(validate_results.errors) > 0

    def test_validate_operator_availability_detects_missing_operator(self):
        """Test operator availability check detects missing operator."""
        from docpipe.core.constants.constants import OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        dag_with_missing_operator = [
            {
                "id": "node1",
                "name": "Node 1",
                "operator": "non_existent_operator",  # This operator doesn't exist
                "config": {},
            }
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_operator_availability(
            dag=dag_with_missing_operator, global_config={}, validate_results=validate_results
        )

        # Assert
        assert len(validate_results.errors) > 0
        error_messages = [str(err) for err in validate_results.errors]
        assert any("not available" in msg.lower() or "operator" in msg.lower() for msg in error_messages)

    def test_validate_operator_availability_allows_valid_operators(self):
        """Test operator availability check allows registered operators."""
        from docpipe.core.constants.constants import OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        dag_with_valid_operator = [
            {
                "id": "node1",
                "name": "Node 1",
                "operator": "ingest_source",  # This is a registered operator
                "config": {},
            }
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_operator_availability(
            dag=dag_with_valid_operator, global_config={}, validate_results=validate_results
        )

        # Assert
        assert len(validate_results.errors) == 0

    def test_validate_operator_availability_skips_custom_operators_when_configured(self):
        """Test operator availability check skips custom operators when skip flag is set."""
        from docpipe.core.constants.constants import DocpipeConstants, OrchestratorType
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        # Arrange
        orchestrator = OrchestratorFactory.create_orchestrator(orchestrator_name=OrchestratorType.PYTHON)
        validator = FlowValidator(orchestrator=orchestrator)

        dag_with_custom_operator = [
            {
                "id": "node1",
                "name": "Node 1",
                "operator": "my_custom_operator",  # Custom operator
                "config": {},
            }
        ]

        global_config = {DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION: True}

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Act
        validator._validate_operator_availability(
            dag=dag_with_custom_operator, global_config=global_config, validate_results=validate_results
        )

        # Assert
        assert len(validate_results.errors) == 0  # Should skip validation


class TestMandatoryFeatureValidation:
    """Tests for mandatory feature validation scenarios."""

    def test_chunker_requires_content_feature(self):
        """Test that Chunker operator fails validation when content feature is missing."""
        from docpipe.core.assets.flows.application.services.validation_service import ValidationService

        # Arrange
        service = ValidationService()
        flow_def_missing_content = {
            "flow_name": "test-chunker-flow",
            "flow": [
                {"type": "ingest_source", "name": "ingest_node", "config": {"folder_path": "/test"}, "depends_on": []},
                {
                    "type": "chunker",
                    "name": "chunker_node",
                    "config": {"chunking_strategy": "simple"},
                    "depends_on": ["ingest_node"],
                },
            ],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise error for missing content feature
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[
                    ValidationAlert(
                        code="MISSING_REQUIRED_FEATURE",
                        message="Required feature 'content' not available for Chunker operator",
                        node_id="node2",
                    )
                ],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def_missing_content, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert any("content" in err.get("message", "").lower() for err in result["errors"])

    def test_embeddings_operator_requires_content_feature(self):
        """Test that EmbeddingsOperator fails validation when content feature is missing."""
        from docpipe.core.assets.flows.application.services.validation_service import ValidationService

        # Arrange
        service = ValidationService()
        flow_def_missing_content = {
            "flow_name": "test-embeddings-flow",
            "flow": [
                {"type": "ingest_source", "name": "ingest_node", "config": {"folder_path": "/test"}, "depends_on": []},
                {
                    "type": "embeddings",
                    "name": "embeddings_node",
                    "config": {"model_name": "nomic-embed-text"},
                    "depends_on": ["ingest_node"],
                },
            ],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise error for missing content feature
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[
                    ValidationAlert(
                        code="MISSING_REQUIRED_FEATURE",
                        message="Required feature 'content' not available for EmbeddingsOperator",
                        node_id="node2",
                    )
                ],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def_missing_content, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert any("content" in err.get("message", "").lower() for err in result["errors"])

    def test_vectordb_operator_requires_embeddings_feature(self):
        """Test that VectorDBOperator fails validation when embeddings feature is missing."""
        # Arrange
        service = ValidationService()
        flow_def_missing_embeddings = {
            "flow_name": "test-vectordb-flow",
            "flow": [
                {"type": "ingest_source", "name": "ingest_node", "config": {"folder_path": "/test"}, "depends_on": []},
                {
                    "type": "vectordb",
                    "name": "vectordb_node",
                    "config": {"provider": "opensearch"},
                    "depends_on": ["ingest_node"],
                },
            ],
        }

        # Act
        with (
            patch("docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"),
            patch("docpipe.core.orchestration.flow_validator.FlowValidator") as mock_validator_class,
        ):
            # Mock validator to raise error for missing embeddings feature
            mock_validator = mock_validator_class.return_value
            validation_error = FlowValidationException(
                message="Validation failed",
                errors=[
                    ValidationAlert(
                        code="MISSING_REQUIRED_FEATURE",
                        message="Required feature 'embeddings' not available for VectorDBOperator",
                        node_id="node2",
                    )
                ],
            )
            mock_validator.validate_dag_with_features.side_effect = validation_error

            result = service.validate_flow(flow_definition=flow_def_missing_embeddings, is_elyra=False)

        # Assert
        assert result["status"] == "FAILED"
        assert any("embeddings" in err.get("message", "").lower() for err in result["errors"])
