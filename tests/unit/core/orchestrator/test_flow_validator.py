"""Unit tests for flow_validator module."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.orchestration.feature_propagation.models import FeatureMetadata, FeaturePropagationResult
from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
from docpipe.exceptions.docpipe_exceptions import (
    FlowValidationException,
)
from docpipe.exceptions.error_messages import ValidationCodeMessages


class TestValidateStepResults:
    """Test ValidateStepResults class."""

    def test_init(self):
        """Test ValidateStepResults initialization."""
        available_features = {"node1": ["feature1", "feature2"]}
        errors = ["error1"]
        warnings = ["warning1"]

        result = ValidateStepResults(available_features=available_features, errors=errors, warnings=warnings)

        assert result.available_features == available_features
        assert result.errors == errors
        assert result.warnings == warnings


class TestFlowValidator:
    """Test FlowValidator class."""

    def test_init(self):
        """Test FlowValidator initialization."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        assert validator.orchestrator == mock_orchestrator
        assert validator.common_log_arguments == {}

    def test_validate_disabled(self):
        """Test validation when disabled in config."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        flow_def = {
            OperatorConstants.Config.GLOBAL_CONFIG: {OperatorConstants.Config.DISABLE_VALIDATION: True},
            DocpipeConstants.DAG: [],
        }

        # Should return without raising exception
        validator.validate(flow_def=flow_def, params={})

    def test_validate_missing_dag(self):
        """Test validation with missing DAG."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        flow_def: dict = {}

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate(flow_def=flow_def, params={})

        assert len(exc_info.value.errors) > 0

    def test_validate_dag_empty_dag(self):
        """Test validation with empty DAG."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        flow_def: dict = {DocpipeConstants.DAG: []}

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        assert len(exc_info.value.errors) > 0

    def test_validate_dag_unnamed_operators(self):
        """Test validation with unnamed operators."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        mock_orchestrator.enable_custom_operators = True
        mock_orchestrator.custom_operator_packages = None
        mock_orchestrator.prefect_executor = Mock()
        mock_orchestrator.prefect_executor.build_non_execute_flow = Mock(return_value=Mock())

        validator = FlowValidator(orchestrator=mock_orchestrator)

        flow_def = {
            DocpipeConstants.DAG: [
                {
                    "id": "node1",
                    OperatorConstants.Misc.OPERATOR: "test_operator",
                    # Missing NAME
                }
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        # Should have warnings about unnamed operators
        assert len(exc_info.value.warnings) > 0 or len(exc_info.value.errors) > 0

    def test_validate_dag_duplicate_names(self):
        """Test validation with duplicate operator names."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        mock_orchestrator.enable_custom_operators = True
        mock_orchestrator.custom_operator_packages = None
        mock_orchestrator.prefect_executor = Mock()
        mock_orchestrator.prefect_executor.build_non_execute_flow = Mock(return_value=Mock())

        validator = FlowValidator(orchestrator=mock_orchestrator)

        flow_def = {
            DocpipeConstants.DAG: [
                {
                    "id": "node1",
                    OperatorConstants.Columns.NAME: "duplicate_name",
                    OperatorConstants.Misc.OPERATOR: "op1",
                },
                {
                    "id": "node2",
                    OperatorConstants.Columns.NAME: "duplicate_name",
                    OperatorConstants.Misc.OPERATOR: "op2",
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        assert len(exc_info.value.errors) > 0

    def test_get_duplicate_node_names(self):
        """Test getting duplicate node names."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        nodes = ["node1", "node2", "node1", "node3", "node2"]
        result = validator.get_duplicate_node_names(nodes=nodes)

        assert set(result) == {"node1", "node2"}

    def test_get_duplicate_node_names_no_duplicates(self):
        """Test with no duplicate names."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        nodes = ["node1", "node2", "node3"]
        result = validator.get_duplicate_node_names(nodes=nodes)

        assert result == []

    def test_validate_root_operator_valid(self):
        """Test validating first operator when it's an Ingest operator."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        dag = [{"id": "node1", "operator": "ingest_op", DocpipeConstants.OUTPUT_EDGES: []}]
        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        with patch.object(validator, "_validate_operator_category") as mock_validate:
            validator._validate_root_operator(dag=dag, validate_results=validate_results)

            mock_validate.assert_called_once()

    def test_validate_root_operator_ingest_not_first_in_array(self):
        """Test that ingest node listed non-first in JSON array but topological root passes validation."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        # extract is dag[0] but has an incoming edge from ingest — ingest is the true root
        dag = [
            {
                "id": "extract-1",
                "operator": "extract_operator",
                DocpipeConstants.OUTPUT_EDGES: [],
            },
            {
                "id": "ingest-1",
                "operator": "ingest_source",
                DocpipeConstants.OUTPUT_EDGES: [{"node_id_ref": "extract-1"}],
            },
        ]
        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        with patch.object(validator, "_validate_operator_category") as mock_validate:
            validator._validate_root_operator(dag=dag, validate_results=validate_results)

            # Must be called with the ingest node (dag[1]), not dag[0]
            call_args = mock_validate.call_args
            assert call_args.kwargs["op_def"]["id"] == "ingest-1"

    def test_build_graph(self):
        """Test building graph from DAG."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        dag = [
            {"id": "node1", DocpipeConstants.OUTPUT_EDGES: [{"node_id_ref": "node2"}]},
            {"id": "node2", DocpipeConstants.OUTPUT_EDGES: [{"node_id_ref": "node3"}]},
            {"id": "node3", DocpipeConstants.OUTPUT_EDGES: []},
        ]

        result = validator._build_graph(dag=dag)

        assert result["node1"] == ["node2"]
        assert result["node2"] == ["node3"]
        assert result["node3"] == []

    def test_make_undirected_graph(self):
        """Test converting directed graph to undirected."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        graph = {"node1": ["node2"], "node2": ["node3"], "node3": []}

        result = validator._make_undirected_graph(graph)

        assert "node2" in result["node1"]
        assert "node1" in result["node2"]
        assert "node3" in result["node2"]
        assert "node2" in result["node3"]

    def test_find_connected_components_single_component(self):
        """Test finding connected components with single component."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        undirected = {
            "node1": {"node2"},
            "node2": {"node1", "node3"},
            "node3": {"node2"},
        }

        result = validator._find_connected_components(undirected)

        assert len(result) == 1
        assert result[0] == {"node1", "node2", "node3"}

    def test_find_connected_components_multiple_components(self):
        """Test finding connected components with multiple components."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        undirected = {
            "node1": {"node2"},
            "node2": {"node1"},
            "node3": {"node4"},
            "node4": {"node3"},
        }

        result = validator._find_connected_components(undirected)

        assert len(result) == 2

    def test_validate_disjoint_operators_connected(self):
        """Test validation with connected operators."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        dag = [
            {"id": "node1", DocpipeConstants.OUTPUT_EDGES: [{"node_id_ref": "node2"}]},
            {"id": "node2", DocpipeConstants.OUTPUT_EDGES: []},
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        # Should not add errors for connected graph
        validator._validate_disjoint_operators(dag=dag, validate_results=validate_results)

        assert len(validate_results.errors) == 0

    def test_validate_disjoint_operators_disconnected(self):
        """Test validation with disconnected operators."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        dag = [
            {"id": "node1", DocpipeConstants.OUTPUT_EDGES: []},
            {"id": "node2", DocpipeConstants.OUTPUT_EDGES: []},
        ]

        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_disjoint_operators(dag=dag, validate_results=validate_results)

        # Should add error for disconnected graph
        assert len(validate_results.errors) > 0

    def test_check_duplicate_extract_operators(self):
        """Test checking for duplicate extract operators."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        sequence = [
            {"id": "node1", "operator": "extract_op1"},
            {"id": "node2", "operator": "extract_op2"},
        ]

        errors: list = []

        with patch.object(validator, "_get_operator_category") as mock_get_category:
            mock_get_category.return_value = OperatorCategory.Extract

            result = validator._check_duplicate_extract_operators(sequence=sequence, errors=errors)

            assert result == 2
            assert len(errors) > 0  # Should have error for multiple extracts

    def test_validate_operator_category_matches(self):
        """Test validating operator category when it matches."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        op_def = {"id": "node1", "operator": "test_op"}
        alerts: list = []

        with patch.object(validator, "_get_operator_category") as mock_get_category:
            mock_get_category.return_value = OperatorCategory.Ingest

            validator._validate_operator_category(
                op_def=op_def,
                expected_category=OperatorCategory.Ingest,
                error_message=Mock(),
                alerts=alerts,
            )

            assert len(alerts) == 0

    def test_validate_operator_category_mismatch(self):
        """Test validating operator category when it doesn't match."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        op_def = {"id": "node1", "operator": "test_op"}
        alerts: list = []

        with patch.object(validator, "_get_operator_category") as mock_get_category:
            mock_get_category.return_value = OperatorCategory.Extract

            from docpipe.exceptions.error_messages import ValidationMessage

            validator._validate_operator_category(
                op_def=op_def,
                expected_category=OperatorCategory.Ingest,
                error_message=ValidationMessage(message="Category mismatch error"),
                alerts=alerts,
            )

            assert len(alerts) > 0

    def test_get_operator_category_missing_id(self):
        """Test getting operator category with missing ID."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        mock_orchestrator.create_executor = Mock()

        validator = FlowValidator(orchestrator=mock_orchestrator)

        op_def = {"operator": "test_op"}  # Missing ID
        alerts: list = []

        # The method adds alerts but doesn't raise exception for missing ID
        validator._get_operator_category(op_def=op_def, alerts=alerts)

        # Verify that an alert was added for missing ID
        assert len(alerts) > 0
        assert any("MISSING_NODE_ID" in str(alert) or "missing" in str(alert).lower() for alert in alerts)

    def test_get_operator_category_missing_name(self):
        """Test getting operator category with missing name."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        mock_orchestrator.create_executor = Mock()

        validator = FlowValidator(orchestrator=mock_orchestrator)

        op_def = {"id": "node1", "operator": "test_op"}  # Missing NAME
        alerts: list = []

        # The method adds alerts but doesn't raise exception for missing name
        validator._get_operator_category(op_def=op_def, alerts=alerts)

        # Verify that an alert was added for missing name
        assert len(alerts) > 0
        assert any("MISSING_NODE_NAME" in str(alert) or "name" in str(alert).lower() for alert in alerts)

    def test_get_operator_category_success(self):
        """Test successfully getting operator category."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        # Mock the operator metadata to return Ingest category for test_op
        validator.operator_metadata.operator_metadata = {
            "test_op": {OperatorConstants.Misc.CATEGORY: OperatorCategory.Ingest}
        }

        op_def = {
            "id": "node1",
            OperatorConstants.Columns.NAME: "Test Op",
            "operator": "test_op",
        }
        alerts: list = []

        result = validator._get_operator_category(op_def=op_def, alerts=alerts)

        assert result == OperatorCategory.Ingest

    def test_create_validation_alerts(self):
        """Test creating validation alerts."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        op_def = {"id": "node1", "name": "Test"}
        messages = [Mock(), Mock()]
        alerts: list = []

        with patch("docpipe.core.orchestration.flow_validator.add_validation_alert") as mock_add:
            validator.create_validation_alerts(op_def=op_def, messages=messages, alerts=alerts)

            assert mock_add.call_count == 2

    def test_evaluate_node_validation_skip_custom_op(self):
        """Test skipping validation for custom operator."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        mock_factory = Mock()
        mock_factory.operators = {"known_op": Mock()}

        global_config = {DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION: True}

        result = validator._evaluate_node_validation_skip(
            operator="unknown_op",
            operator_factory=mock_factory,
            global_config=global_config,
        )

        assert result is True

    def test_evaluate_node_validation_skip_known_op(self):
        """Test not skipping validation for known operator."""
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}

        validator = FlowValidator(orchestrator=mock_orchestrator)

        mock_factory = Mock()
        mock_factory.operators = {"known_op": Mock()}

        global_config = {DocpipeConstants.SKIP_CUSTOM_OP_VALIDATION: True}

        result = validator._evaluate_node_validation_skip(
            operator="known_op",
            operator_factory=mock_factory,
            global_config=global_config,
        )

        assert result is False

    def test_validate_global_config_doc_format_valid(self):
        """Test global_config with valid doc_format passes validation."""
        validator = FlowValidator.__new__(FlowValidator)
        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_global_config_values(
            global_config={"doc_format": "doclang"}, validate_results=validate_results
        )
        assert len(validate_results.errors) == 0

        validator._validate_global_config_values(
            global_config={"doc_format": "markdown"}, validate_results=validate_results
        )
        assert len(validate_results.errors) == 0

    def test_validate_global_config_doc_format_invalid(self):
        """Test global_config with invalid doc_format adds an error."""
        validator = FlowValidator.__new__(FlowValidator)
        validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_global_config_values(global_config={"doc_format": "xml"}, validate_results=validate_results)
        assert len(validate_results.errors) == 1
        assert "Invalid doc_format 'xml'" in validate_results.errors[0]["message"]


class TestFlowValidatorIntegration:
    """Integration tests for flow validation with real orchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance for testing."""
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        return OrchestratorFactory.create_orchestrator(orchestrator_name="python")

    @pytest.fixture
    def validator(self, orchestrator):
        """Create flow validator instance."""
        return FlowValidator(orchestrator=orchestrator)

    def test_valid_simple_flow_passes_validation(self, validator, fixtures_invoices_dir):
        """Test that a valid simple flow passes validation without errors."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"provider": "filesystem", "provider_config": {"paths": [str(fixtures_invoices_dir)]}},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"text_extraction": {"provider": "docling_library", "doc_column": "content"}},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "vectordb-1"}],
                },
                {
                    "id": "vectordb-1",
                    "name": "store_in_opensearch",
                    "operator": "vectordb",
                    "config": {
                        "provider": "opensearch",
                        "vector_dimension": 384,
                        "doc_id_column": "id",
                        "embeddings_column": "embeddings",
                        "provider_config": {
                            "index_name": "test_index",
                            "host": "localhost",
                            "port": 9200,
                            "use_ssl": False,
                        },
                    },
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [],
                },
            ]
        }
        validator.validate_dag(flow_def=flow_def, global_config={})

    def test_missing_required_features_fails(self, validator, fixtures_invoices_dir):
        """Test that flow with missing required features fails validation."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "chunker-1"}],
                },
                {
                    "id": "chunker-1",
                    "name": "chunk_documents",
                    "operator": "chunker",
                    "config": {"doc_column": "content", "chunk_size": 1000},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        errors = exc_info.value.errors or []
        assert any(ValidationCodeMessages.MISSING_FEATURES.name in str(error.message_code) for error in errors), (
            "Expected MISSING_FEATURES error not found"
        )

    def test_last_operator_not_vectordb_or_storage_warns(self, validator, fixtures_invoices_dir):
        """Test that flow where last operator is not VectorDB or Storage generates warning."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "chunker-1"}],
                },
                {
                    "id": "chunker-1",
                    "name": "chunk_documents",
                    "operator": "chunker",
                    "config": {"doc_column": "content", "chunk_size": 200},
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        warnings = exc_info.value.warnings or []
        assert any(
            ValidationCodeMessages.GENERATE_OUTPUT_MISSING.name in str(warning.message_code) for warning in warnings
        ), "Expected GENERATE_OUTPUT_MISSING warning not found"

    def test_last_operator_storage_does_not_warn(self, validator, fixtures_invoices_dir):
        """Test that flow where last operator is Storage (e.g. document_set) does not warn."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "docset-1"}],
                },
                {
                    "id": "docset-1",
                    "name": "save_document_set",
                    "operator": "document_set",
                    "config": {"name": "test_set"},
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [],
                },
            ]
        }

        # Should validate without raising FlowValidationException or with no GENERATE_OUTPUT_MISSING warning
        try:
            validator.validate_dag(flow_def=flow_def, global_config={})
        except FlowValidationException as exc_info:
            warnings = exc_info.warnings or []
            assert not any(
                ValidationCodeMessages.GENERATE_OUTPUT_MISSING.name in str(warning.message_code) for warning in warnings
            )

    def test_last_operator_not_vectordb_or_storage_warns_for_each_branch(self, validator, fixtures_invoices_dir):
        """Test that a warning is emitted for every branch terminal that is not VectorDB or Storage.

        Flow shape:
            ingest-1 → extract-1 → branching-1 → chunker-a (branch A terminal)
                                               → chunker-b (branch B terminal)
        Both branch terminals miss VectorDB/Storage, so two GENERATE_OUTPUT_MISSING warnings
        are expected — one per terminal node.
        """
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "branching-1"}],
                },
                {
                    "id": "branching-1",
                    "name": "branch_documents",
                    "operator": "branching",
                    "config": {},
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [
                        {"node_id_ref": "chunker-a"},
                        {"node_id_ref": "chunker-b"},
                    ],
                },
                {
                    "id": "chunker-a",
                    "name": "chunk_branch_a",
                    "operator": "chunker",
                    "config": {"doc_column": "content", "chunk_size": 200},
                    "input_edges": [{"node_id_ref": "branching-1"}],
                    "output_edges": [],
                },
                {
                    "id": "chunker-b",
                    "name": "chunk_branch_b",
                    "operator": "chunker",
                    "config": {"doc_column": "content", "chunk_size": 200},
                    "input_edges": [{"node_id_ref": "branching-1"}],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        warnings = exc_info.value.warnings or []
        matching = [w for w in warnings if w.message_code == ValidationCodeMessages.GENERATE_OUTPUT_MISSING.name]
        assert len(matching) == 2, (
            f"Expected 2 GENERATE_OUTPUT_MISSING warnings (one per branch terminal), got {len(matching)}"
        )
        warned_node_ids = {w.node_id for w in matching}
        assert warned_node_ids == {"chunker-a", "chunker-b"}

    def test_first_operator_not_ingest_fails(self, validator, fixtures_invoices_dir):
        """Test that flow where first operator is not Ingest fails."""
        flow_def = {
            "dag": [
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "chunker-1"}],
                },
                {
                    "id": "chunker-1",
                    "name": "chunk_documents",
                    "operator": "chunker",
                    "config": {"doc_column": "content", "chunk_size": 200},
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [{"node_id_ref": "vectordb-1"}],
                },
                {
                    "id": "vectordb-1",
                    "name": "store_in_opensearch",
                    "operator": "vectordb",
                    "config": {
                        "provider": "opensearch",
                        "vector_dimension": 384,
                        "doc_id_column": "id",
                        "embeddings_column": "embeddings",
                        "provider_config": {
                            "index_name": "test_index",
                            "host": "localhost",
                            "port": 9200,
                            "use_ssl": False,
                        },
                    },
                    "input_edges": [{"node_id_ref": "chunker-1"}],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        errors = exc_info.value.errors or []
        assert any(
            ValidationCodeMessages.INGEST_OPERATOR_MISPLACED.name in str(error.message_code) for error in errors
        ), "Expected INGEST_OPERATOR_MISPLACED error not found"

    def test_integration_empty_dag_fails(self, validator):
        """Test that empty DAG fails validation."""
        flow_def: dict = {"dag": []}

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        errors = exc_info.value.errors or []
        assert any(ValidationCodeMessages.DAG_PIPELINE_MISSING.name in str(error.message_code) for error in errors), (
            "Expected DAG_PIPELINE_MISSING error not found"
        )

    def test_integration_duplicate_operator_names_fails(self, validator, fixtures_invoices_dir):
        """Test that duplicate operator names fail validation."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "duplicate_name",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "duplicate_name",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        errors = exc_info.value.errors or []
        assert any(ValidationCodeMessages.OPERATOR_NAME_REPEATED.name in str(error.message_code) for error in errors), (
            "Expected OPERATOR_NAME_REPEATED error not found"
        )

    def test_integration_disjoint_operators_fails(self, validator, fixtures_invoices_dir):
        """Test that disjoint operators fail validation."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [],
                    "output_edges": [],
                },
            ]
        }

        with pytest.raises(FlowValidationException) as exc_info:
            validator.validate_dag(flow_def=flow_def, global_config={})

        errors = exc_info.value.errors or []
        assert any(
            ValidationCodeMessages.DISJOINT_OPERATORS_DETECTED.name in str(error.message_code) for error in errors
        ), "Expected DISJOINT_OPERATORS_DETECTED error not found"

    def test_integration_multiple_extract_operators_warns(self, validator, fixtures_invoices_dir):
        """Test that multiple extract operators generate warnings."""
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest_documents",
                    "operator": "ingest_source",
                    "config": {"paths": str(fixtures_invoices_dir)},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract_documents_1",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "extract-2"}],
                },
                {
                    "id": "extract-2",
                    "name": "extract_documents_2",
                    "operator": "extract_operator",
                    "config": {"doc_column": "content"},
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [],
                },
            ]
        }

        errors: list = []
        extract_count = validator._check_duplicate_extract_operators(sequence=flow_def["dag"], errors=errors)

        assert extract_count == 2, "Expected 2 extract operators"
        assert len(errors) > 0, "Expected error for multiple extract operators"


class TestValidateStorageOutputOperatorPlacement:
    """Tests for validate_storage_output_operator_placement."""

    def _make_validator(self):
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orchestrator)

    def _make_dag(self, *, ingest_op: str, storage_mode: str) -> list:
        """Build a minimal two-node DAG: ingest → storage_output."""
        return [
            {
                "id": "ingest-1",
                "name": "ingest",
                "operator": ingest_op,
                "config": {},
                "input_edges": [],
                "output_edges": [{"node_id_ref": "storage-1"}],
            },
            {
                "id": "storage-1",
                "name": "storage_output",
                "operator": "storage_output",
                "config": {"mode": storage_mode},
                "input_edges": [{"node_id_ref": "ingest-1"}],
                "output_edges": [],
            },
        ]

    def test_refetch_original_with_ingest_source_passes(self):
        validator = self._make_validator()
        dag = self._make_dag(ingest_op="ingest_source", storage_mode="refetch_original")
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert results.errors == []

    def test_comprehensive_export_with_ingest_source_passes(self):
        validator = self._make_validator()
        dag = self._make_dag(ingest_op="ingest_source", storage_mode="comprehensive_export")
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert results.errors == []

    def test_refetch_original_without_ingest_source_fails(self):
        validator = self._make_validator()
        dag = self._make_dag(ingest_op="noop", storage_mode="refetch_original")
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert len(results.errors) == 1
        assert ValidationCodeMessages.STORAGE_OUTPUT_REQUIRES_INGEST_SOURCE.name in str(results.errors[0].message_code)

    def test_comprehensive_export_without_ingest_source_fails(self):
        validator = self._make_validator()
        dag = self._make_dag(ingest_op="noop", storage_mode="comprehensive_export")
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert len(results.errors) == 1
        assert ValidationCodeMessages.STORAGE_OUTPUT_REQUIRES_INGEST_SOURCE.name in str(results.errors[0].message_code)

    def test_processed_content_without_ingest_source_passes(self):
        """processed_content mode does not require ingest_source."""
        validator = self._make_validator()
        dag = self._make_dag(ingest_op="noop", storage_mode="processed_content")
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert results.errors == []

    def test_no_storage_output_nodes_is_noop(self):
        validator = self._make_validator()
        dag = [
            {
                "id": "ingest-1",
                "name": "ingest",
                "operator": "noop",
                "config": {},
                "input_edges": [],
                "output_edges": [],
            }
        ]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        validator._validate_storage_output_operator_placement(dag=dag, validate_results=results)

        assert results.errors == []


class TestMergeParentInputFeatures:
    """Unit tests for FlowValidator._merge_parent_input_features().

    Verifies that duplicate feature keys across merge parents are suffixed
    with the link_name (or numeric index fallback) rather than silently
    overwritten.
    """

    @pytest.fixture
    def validator(self):
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orchestrator)

    def _make_parent(self, *, features: dict, source_node_id: str | None = None) -> FeaturePropagationResult:
        """Build a minimal FeaturePropagationResult with the given features."""
        result = FeaturePropagationResult()
        result.source_node_id = source_node_id
        for name, desc in features.items():
            result.add_feature(
                feature_name=name,
                node_id=source_node_id or "node",
                description=desc,
                available_for_filter=True,
                available_for_vector_db=False,
            )
        return result

    def _make_input_links(self, mapping: dict[str, str]) -> list[dict]:
        """Turn {node_id: link_name} into the input_links list shape."""
        return [{"node_id_ref": nid, "link_name": ln} for nid, ln in mapping.items()]

    def test_non_merge_operator_uses_plain_update(self, validator):
        """Non-merge nodes: plain update, no suffixing."""
        p1 = self._make_parent(features={"id": "d1", "content": "d2"}, source_node_id="n1")
        result = validator._merge_parent_input_features(
            parent_results=[p1],
            operator="chunker",
            operator_config={},
        )
        assert set(result.keys()) == {"id", "content"}

    def test_single_merge_parent_no_suffix(self, validator):
        """Single merge parent: no disambiguation needed."""
        p1 = self._make_parent(features={"id": "d1", "text": "d2"}, source_node_id="n1")
        result = validator._merge_parent_input_features(
            parent_results=[p1],
            operator=OperatorConstants.Operators.MERGE,
            operator_config={"input_links": [{"node_id_ref": "n1", "link_name": "Link_1"}]},
        )
        assert set(result.keys()) == {"id", "text"}

    def test_merge_two_parents_distinct_features(self, validator):
        """Two parents with no overlapping keys: both sets present, no suffix."""
        p1 = self._make_parent(features={"id": "d", "content": "d"}, source_node_id="n1")
        p2 = self._make_parent(features={"id": "d", "size": "d"}, source_node_id="n2")
        config = {"input_links": self._make_input_links({"n1": "Link_1", "n2": "Link_2"})}
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        assert "id" in result
        assert "content" in result
        assert "size" in result
        # no suffixed duplicates
        assert not any("_Link" in k for k in result)

    def test_merge_duplicate_feature_gets_link_name_suffix(self, validator):
        """Duplicate key on second parent gets _<link_name> suffix."""
        p1 = self._make_parent(features={"id": "d", "content": "from-p1"}, source_node_id="n1")
        p2 = self._make_parent(features={"id": "d", "content": "from-p2"}, source_node_id="n2")
        config = {"input_links": self._make_input_links({"n1": "Link_5", "n2": "Link_6"})}
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        assert "content" in result  # first occurrence kept as-is
        assert "content_Link_6" in result  # second occurrence suffixed with p2's link name
        assert result["content"]["description"] == "from-p1"
        assert result["content_Link_6"]["description"] == "from-p2"

    def test_merge_id_is_never_suffixed(self, validator):
        """Primary key 'id' must never be suffixed even when both parents carry it."""
        p1 = self._make_parent(features={"id": "from-p1", "x": "d"}, source_node_id="n1")
        p2 = self._make_parent(features={"id": "from-p2", "x": "d"}, source_node_id="n2")
        config = {"input_links": self._make_input_links({"n1": "Link_A", "n2": "Link_B"})}
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        assert "id" in result
        assert "id_Link_B" not in result  # no suffixed id
        assert result["id"]["description"] == "from-p1"  # first occurrence wins

    def test_merge_fallback_to_numeric_index_when_no_link_name_map(self, validator):
        """When input_links is empty, falls back to numeric index suffix."""
        p1 = self._make_parent(features={"id": "d", "content": "p1"}, source_node_id="n1")
        p2 = self._make_parent(features={"id": "d", "content": "p2"}, source_node_id="n2")
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config={},  # no input_links
        )
        assert "content" in result
        assert "content_1" in result  # numeric index 1 (second parent)

    def test_merge_fallback_to_numeric_when_source_node_id_absent(self, validator):
        """source_node_id=None on a parent: falls back to numeric index."""
        p1 = self._make_parent(features={"id": "d", "content": "p1"}, source_node_id="n1")
        p2 = self._make_parent(features={"id": "d", "content": "p2"}, source_node_id=None)
        config = {"input_links": self._make_input_links({"n1": "Link_1"})}
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        assert "content" in result
        assert "content_1" in result  # numeric index for unresolved parent

    def test_merge_inner_join_excludes_branch_exclusive_features(self, validator):
        """INNER_JOIN gate: features present in only one branch must not appear in input snapshot."""
        p1 = self._make_parent(
            features={"id": "d", "content": "d", "only_p1": "exclusive"},
            source_node_id="n1",
        )
        p2 = self._make_parent(
            features={"id": "d", "content": "d", "only_p2": "exclusive"},
            source_node_id="n2",
        )
        config = {
            "merge_type": OperatorConstants.Merge.COLUMNS,
            "column_option": OperatorConstants.Columns.INNER_JOIN_DUPLICATE_COLUMN,
            "input_links": self._make_input_links({"n1": "Link_5", "n2": "Link_6"}),
        }
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        # Only features common to both branches (plus id) should be in the input snapshot
        assert "id" in result
        assert "content" in result
        assert "only_p1" not in result
        assert "only_p2" not in result

    def test_merge_full_outer_includes_all_features(self, validator):
        """FULL_OUTER gate: all features from all branches appear in input snapshot."""
        p1 = self._make_parent(
            features={"id": "d", "content": "d", "only_p1": "exclusive"},
            source_node_id="n1",
        )
        p2 = self._make_parent(
            features={"id": "d", "content": "d", "only_p2": "exclusive"},
            source_node_id="n2",
        )
        config = {
            "merge_type": OperatorConstants.Merge.COLUMNS,
            "column_option": OperatorConstants.Merge.FULL_OUTER_JOIN,
            "input_links": self._make_input_links({"n1": "Link_5", "n2": "Link_6"}),
        }
        result = validator._merge_parent_input_features(
            parent_results=[p1, p2],
            operator=OperatorConstants.Operators.MERGE,
            operator_config=config,
        )
        assert "id" in result
        assert "content" in result
        assert "only_p1" in result
        assert "only_p2" in result


class TestValidateAclOperatorPlacement:
    """Tests for _validate_acl_operator_placement — covers lines 1006-1098."""

    def _make_validator(self):
        mock_orch = Mock()
        mock_orch.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orch)

    def test_no_acl_node_is_noop(self):
        validator = self._make_validator()
        dag = [{"id": "n1", "name": "ingest", "operator": "ingest_source", "config": {}}]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_acl_operator_placement(dag=dag, validate_results=results)
        assert results.errors == []

    def test_multiple_acl_nodes_raise_error(self):
        validator = self._make_validator()
        dag = [
            {"id": "n1", "name": "n1", "operator": "acl_operator", "config": {}},
            {"id": "n2", "name": "n2", "operator": "acl_operator", "config": {}},
        ]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_acl_operator_placement(dag=dag, validate_results=results)
        assert len(results.errors) >= 1

    def test_acl_with_no_parent_raises_error(self):
        validator = self._make_validator()
        dag = [
            {
                "id": "acl-1",
                "name": "acl",
                "operator": "acl_operator",
                "config": {},
                "output_edges": [],
            }
        ]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_acl_operator_placement(dag=dag, validate_results=results)
        assert len(results.errors) >= 1


class TestValidateNoCycles:
    """Tests for _validate_no_cycles — covers lines 1265-1306."""

    def _make_validator(self):
        mock_orch = Mock()
        mock_orch.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orch)

    def test_acyclic_dag_no_error(self):
        validator = self._make_validator()
        dag = [
            {"id": "n1", "output_edges": [{"node_id_ref": "n2"}]},
            {"id": "n2", "output_edges": []},
        ]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_no_cycles(dag=dag, validate_results=results)
        assert results.errors == []

    def test_cyclic_dag_adds_error(self):
        validator = self._make_validator()
        # n1 -> n2 -> n1 cycle
        dag = [
            {"id": "n1", "name": "n1", "operator": "op", "output_edges": [{"node_id_ref": "n2"}]},
            {"id": "n2", "name": "n2", "operator": "op", "output_edges": [{"node_id_ref": "n1"}]},
        ]
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])
        validator._validate_no_cycles(dag=dag, validate_results=results)
        assert len(results.errors) >= 1


class TestGetRequiredNodeFieldsErrors:
    """Tests for _get_required_node_fields error paths — covers lines 606-630."""

    def _make_validator(self):
        mock_orch = Mock()
        mock_orch.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orch)

    def test_missing_node_id_raises(self):
        validator = self._make_validator()
        with pytest.raises(FlowValidationException):
            validator._get_required_node_fields(op_def={"operator": "ingest_source"})

    def test_empty_node_id_raises(self):
        validator = self._make_validator()
        with pytest.raises(FlowValidationException):
            validator._get_required_node_fields(op_def={"id": "", "operator": "ingest_source"})

    def test_missing_operator_raises(self):
        validator = self._make_validator()
        with pytest.raises(FlowValidationException):
            validator._get_required_node_fields(op_def={"id": "n1"})


class TestValidateDagWithFeatures:
    """Tests for validate_dag_with_features — covers lines 440-488."""

    @pytest.fixture
    def orchestrator(self):
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        return OrchestratorFactory.create_orchestrator(orchestrator_name="python")

    def test_validate_dag_with_features_returns_result(self, orchestrator, fixtures_invoices_dir):
        validator = FlowValidator(orchestrator=orchestrator)
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest",
                    "operator": "ingest_source",
                    "config": {"provider": "filesystem", "provider_config": {"paths": [str(fixtures_invoices_dir)]}},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract",
                    "operator": "extract_operator",
                    "config": {"text_extraction": {"provider": "docling_library", "doc_column": "content"}},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [{"node_id_ref": "vectordb-1"}],
                },
                {
                    "id": "vectordb-1",
                    "name": "vectordb",
                    "operator": "vectordb",
                    "config": {
                        "provider": "opensearch",
                        "vector_dimension": 384,
                        "doc_id_column": "id",
                        "embeddings_column": "embeddings",
                        "provider_config": {"index_name": "idx", "host": "localhost", "port": 9200, "use_ssl": False},
                    },
                    "input_edges": [{"node_id_ref": "extract-1"}],
                    "output_edges": [],
                },
            ]
        }
        from docpipe.core.orchestration.feature_propagation.models import FeaturePropagationResult

        result = validator.validate_dag_with_features(flow_def=flow_def, global_config={})
        assert isinstance(result, FeaturePropagationResult)

    def test_validate_dag_with_features_raises_on_invalid_flow(self, orchestrator, fixtures_invoices_dir):
        validator = FlowValidator(orchestrator=orchestrator)
        flow_def: dict = {"dag": []}
        with pytest.raises(FlowValidationException):
            validator.validate_dag_with_features(flow_def=flow_def, global_config={})


class TestPropagateFeaturesPerNode:
    """Tests for propagate_features_per_node — covers lines 773-841."""

    @pytest.fixture
    def orchestrator(self):
        from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

        return OrchestratorFactory.create_orchestrator(orchestrator_name="python")

    def test_returns_per_node_snapshot(self, orchestrator, fixtures_invoices_dir):
        validator = FlowValidator(orchestrator=orchestrator)
        flow_def = {
            "dag": [
                {
                    "id": "ingest-1",
                    "name": "ingest",
                    "operator": "ingest_source",
                    "config": {},
                    "input_edges": [],
                    "output_edges": [{"node_id_ref": "extract-1"}],
                },
                {
                    "id": "extract-1",
                    "name": "extract",
                    "operator": "extract_operator",
                    "config": {},
                    "input_edges": [{"node_id_ref": "ingest-1"}],
                    "output_edges": [],
                },
            ]
        }
        result = validator.propagate_features_per_node(flow_def=flow_def, global_config={})
        assert "ingest-1" in result
        assert "extract-1" in result
        assert "operator" in result["ingest-1"]


class TestFeatureMetadataIsPrimary:
    """FeatureMetadata.is_primary — model field behaviour."""

    def test_default_is_false(self):
        meta = FeatureMetadata(name="doc_id", node_id="ingest-1")
        assert meta.is_primary is False

    def test_explicit_true(self):
        meta = FeatureMetadata(name="doc_hash", node_id="hash-1", is_primary=True)
        assert meta.is_primary is True

    def test_explicit_false(self):
        meta = FeatureMetadata(name="content", node_id="extract-1", is_primary=False)
        assert meta.is_primary is False


class TestTraverseDag:
    """_traverse_dag works correctly for linear, branching, and out-of-order DAGs."""

    @pytest.fixture
    def validator(self):
        mock_orch = Mock()
        mock_orch.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orch)

    def test_linear_dag(self, validator):
        """Simple A→B→C chain returns results in order."""
        visited = []

        def task(task_name, op_def, prev_result, link_name):
            visited.append(op_def["id"])
            return op_def["id"]

        dag = [
            {"id": "a", "name": "a", "input_edges": [], "output_edges": [{"node_id_ref": "b"}]},
            {
                "id": "b",
                "name": "b",
                "input_edges": [{"node_id_ref": "a", "link_name": "a"}],
                "output_edges": [{"node_id_ref": "c"}],
            },
            {"id": "c", "name": "c", "input_edges": [{"node_id_ref": "b", "link_name": "b"}], "output_edges": []},
        ]
        validator._traverse_dag(dag=dag, task=task)
        assert visited == ["a", "b", "c"]

    def test_branch_merge_dag_in_order(self, validator):
        """A→[B,C]→D: merge node receives a dict of two parent results."""
        received_prev = {}

        def task(task_name, op_def, prev_result, link_name):
            received_prev[op_def["id"]] = prev_result
            return op_def["id"]

        dag = [
            {"id": "a", "name": "a", "input_edges": [], "output_edges": [{"node_id_ref": "b"}, {"node_id_ref": "c"}]},
            {
                "id": "b",
                "name": "b",
                "input_edges": [{"node_id_ref": "a", "link_name": "branch_1"}],
                "output_edges": [{"node_id_ref": "d"}],
            },
            {
                "id": "c",
                "name": "c",
                "input_edges": [{"node_id_ref": "a", "link_name": "branch_2"}],
                "output_edges": [{"node_id_ref": "d"}],
            },
            {
                "id": "d",
                "name": "d",
                "input_edges": [
                    {"node_id_ref": "b", "link_name": "branch_1"},
                    {"node_id_ref": "c", "link_name": "branch_2"},
                ],
                "output_edges": [],
            },
        ]
        validator._traverse_dag(dag=dag, task=task)
        assert received_prev["a"] is None
        assert received_prev["b"] == "a"
        assert received_prev["c"] == "a"
        # merge node gets a dict keyed by link_name
        assert received_prev["d"] == {"branch_1": "b", "branch_2": "c"}

    def test_branch_merge_dag_out_of_order(self, validator):
        """Same branch+merge DAG but nodes shuffled — result must be identical."""
        received_prev = {}

        def task(task_name, op_def, prev_result, link_name):
            received_prev[op_def["id"]] = prev_result
            return op_def["id"]

        # d appears before b and c in the list — deliberately out of topological order
        dag = [
            {
                "id": "d",
                "name": "d",
                "input_edges": [
                    {"node_id_ref": "b", "link_name": "branch_1"},
                    {"node_id_ref": "c", "link_name": "branch_2"},
                ],
                "output_edges": [],
            },
            {
                "id": "c",
                "name": "c",
                "input_edges": [{"node_id_ref": "a", "link_name": "branch_2"}],
                "output_edges": [{"node_id_ref": "d"}],
            },
            {"id": "a", "name": "a", "input_edges": [], "output_edges": [{"node_id_ref": "b"}, {"node_id_ref": "c"}]},
            {
                "id": "b",
                "name": "b",
                "input_edges": [{"node_id_ref": "a", "link_name": "branch_1"}],
                "output_edges": [{"node_id_ref": "d"}],
            },
        ]
        validator._traverse_dag(dag=dag, task=task)
        assert received_prev["a"] is None
        assert received_prev["b"] == "a"
        assert received_prev["c"] == "a"
        assert received_prev["d"] == {"branch_1": "b", "branch_2": "c"}


class TestFeaturePropagationResultAddFeatureIsPrimary:
    """FeaturePropagationResult.add_feature() — is_primary resolution."""

    def test_is_primary_explicit_true(self):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="doc_hash", node_id="hash-1", is_primary=True)
        assert result.feature_metadata["doc_hash"].is_primary is True

    def test_is_primary_explicit_false_no_tag(self):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="content", node_id="extract-1", is_primary=False)
        assert result.feature_metadata["content"].is_primary is False

    def test_is_primary_derived_from_primary_tag(self):
        """is_primary must be True when 'primary' appears in tags even if the flag is False."""
        result = FeaturePropagationResult()
        result.add_feature(feature_name="doc_id", node_id="ingest-1", tags=["primary", "mandatory"], is_primary=False)
        assert result.feature_metadata["doc_id"].is_primary is True

    def test_is_primary_true_overrides_absent_tag(self):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="doc_hash", node_id="hash-1", tags=["mandatory"], is_primary=True)
        assert result.feature_metadata["doc_hash"].is_primary is True

    def test_is_primary_false_with_non_primary_tags(self):
        result = FeaturePropagationResult()
        result.add_feature(
            feature_name="content", node_id="extract-1", tags=["mandatory", "internal"], is_primary=False
        )
        assert result.feature_metadata["content"].is_primary is False

    def test_is_primary_default_when_omitted(self):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="title", node_id="extract-1")
        assert result.feature_metadata["title"].is_primary is False


class TestFlowValidatorFeatureMetadataToDictIsPrimary:
    """FlowValidator._feature_metadata_to_dict() — is_primary included in serialised output."""

    @pytest.fixture
    def validator(self):
        mock_orchestrator = Mock()
        mock_orchestrator.common_log_arguments = {}
        return FlowValidator(orchestrator=mock_orchestrator)

    def test_is_primary_true_included(self, validator):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="doc_hash", node_id="hash-1", is_primary=True)
        output = validator._feature_metadata_to_dict(result=result)
        assert output["doc_hash"]["is_primary"] is True

    def test_is_primary_false_included(self, validator):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="content", node_id="extract-1", is_primary=False)
        output = validator._feature_metadata_to_dict(result=result)
        assert output["content"]["is_primary"] is False

    def test_multiple_features_each_have_is_primary(self, validator):
        result = FeaturePropagationResult()
        result.add_feature(feature_name="doc_hash", node_id="hash-1", is_primary=True)
        result.add_feature(feature_name="content", node_id="extract-1", is_primary=False)
        output = validator._feature_metadata_to_dict(result=result)
        assert output["doc_hash"]["is_primary"] is True
        assert output["content"]["is_primary"] is False


class TestValidationActionTypeMapping:
    """Verify action_type is derived at the API boundary (ValidationAlertDTO) from message_code.

    Core validation models (ValidationMessage, ValidationAlert) carry no action_type.
    The mapping lives entirely in flow_dto.py and is applied by the model_validator
    on ValidationAlertDTO.
    """

    def test_highlight_for_structural_wiring_errors(self):
        """Structural/wiring message codes map to 'highlight'."""
        from docpipe.api.dto.flow_dto import ValidationActionType, ValidationAlertDTO

        for code in [
            "DISJOINT_OPERATORS_DETECTED",
            "OPERATOR_NAME_REPEATED",
            "INGEST_OPERATOR_MISPLACED",
            "GENERATE_OUTPUT_MISSING",
            "CHUNKER_OPERATOR_MISPLACED",
            "CHUNKER_OPERATOR_MISSING",
            "MISSING_FEATURES",
            "CYCLIC_DEPENDENCY_DETECTED",
        ]:
            dto = ValidationAlertDTO(message="test", message_code=code)
            assert dto.action_type == ValidationActionType.HIGHLIGHT, f"Expected highlight for {code}"

    def test_open_properties_for_config_errors(self):
        """Config/property message codes map to 'open_properties'."""
        from docpipe.api.dto.flow_dto import ValidationActionType, ValidationAlertDTO

        for code in [
            "CHUNKER_INVALID_CHUNK_TYPE",
            "CHUNKER_INVALID_CHUNK_SIZE_TYPE",
            "CHUNKER_INVALID_CHUNK_OVERLAP_TYPE",
            "CHUNK_OVERLAP_EXCEEDS_THRESHOLD",
            "MERGE_TYPE_NOT_PROVIDED",
            "INVALID_MERGE_TYPE",
            "SQL_FILTER_INVALID_COLUMN",
            "ACL_INVALID_PROVIDER",
            "OPERATOR_VALIDATION_FAILED",
        ]:
            dto = ValidationAlertDTO(message="test", message_code=code)
            assert dto.action_type == ValidationActionType.OPEN_PROPERTIES, f"Expected open_properties for {code}"

    def test_none_for_flow_level_errors(self):
        """Flow-level structural errors (no navigable node) map to 'none'."""
        from docpipe.api.dto.flow_dto import ValidationActionType, ValidationAlertDTO

        for code in [
            "PIPELINE_NOT_FOUND_ERROR",
            "DAG_PIPELINE_MISSING",
            "INVALID_FLOW_WRAPPER",
            "MISSING_NODE_ID",
            "MISSING_NODE_NAME",
            "MISSING_OPERATOR_NAME",
        ]:
            dto = ValidationAlertDTO(message="test", message_code=code)
            assert dto.action_type == ValidationActionType.NONE, f"Expected none for {code}"

    def test_unknown_code_defaults_to_none(self):
        """Unknown or future message codes default to 'none' rather than erroring."""
        from docpipe.api.dto.flow_dto import ValidationActionType, ValidationAlertDTO

        dto = ValidationAlertDTO(message="test", message_code="SOME_FUTURE_CODE")
        assert dto.action_type == ValidationActionType.NONE

    def test_none_message_code_defaults_to_none(self):
        """Missing message_code defaults to 'none'."""
        from docpipe.api.dto.flow_dto import ValidationActionType, ValidationAlertDTO

        dto = ValidationAlertDTO(message="test", message_code=None)
        assert dto.action_type == ValidationActionType.NONE

    def test_core_validation_alert_has_no_action_type(self):
        """ValidationAlert (core model) carries no action_type field."""
        from docpipe.exceptions.docpipe_exceptions import ValidationAlert

        alert = ValidationAlert(
            code="flow_validation_failed",
            message="Disconnected operator",
            message_code="DISJOINT_OPERATORS_DETECTED",
        )
        assert "action_type" not in alert
        assert not hasattr(alert, "action_type")

    def test_core_validation_message_has_no_action_type(self):
        """ValidationMessage (core model) carries no action_type field."""
        from docpipe.exceptions.error_messages import ValidationMessage

        msg = ValidationMessage.create(message="Invalid chunk type", message_code="CHUNKER_INVALID_CHUNK_TYPE")
        assert not hasattr(msg, "action_type") or msg.model_fields.get("action_type") is None

    def test_dto_action_type_always_set_regardless_of_input(self):
        """action_type is always present on ValidationAlertDTO — never None."""
        from docpipe.api.dto.flow_dto import ValidationAlertDTO

        dto = ValidationAlertDTO(message="some error", message_code="DISJOINT_OPERATORS_DETECTED")
        assert dto.action_type is not None


class TestFlowValidatorStaticMethods:
    """Verify graph utility methods are static and callable without an instance."""

    STATIC_METHODS = (
        "_get_parent_results",
        "_feature_metadata_to_dict",
        "_get_required_node_fields",
        "_traverse_dag",
        "_validate_global_config_values",
        "_build_reverse_graph",
        "_find_terminal_node",
        "_find_all_terminal_nodes",
        "_validate_isolated_nodes",
        "_validate_storage_output_operator_placement",
        "_build_graph",
        "_make_undirected_graph",
        "_find_connected_components",
        "create_validation_alerts",
        "get_duplicate_node_names",
        "_evaluate_node_validation_skip",
    )

    def test_graph_utilities_are_static(self):
        """Every converted graph utility must be a true staticmethod."""
        import inspect

        for method_name in self.STATIC_METHODS:
            assert isinstance(inspect.getattr_static(FlowValidator, method_name), staticmethod), (
                f"{method_name} is not a staticmethod"
            )

    def test_build_graph_class_call(self):
        """Graph construction works when called directly on the class."""
        dag = [
            {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
            {"id": "b", "output_edges": []},
        ]

        graph = FlowValidator._build_graph(dag=dag)

        assert graph == {"a": ["b"], "b": []}

    def test_get_duplicate_node_names_class_call(self):
        """Duplicate detection works when called directly on the class."""
        duplicates = FlowValidator.get_duplicate_node_names(nodes=["a", "b", "a", "c", "b"])

        assert sorted(duplicates) == ["a", "b"]

    def test_find_connected_components_class_call(self):
        """Component detection works when called directly on the class."""
        undirected = {"a": {"b"}, "b": {"a"}, "c": set()}

        components = FlowValidator._find_connected_components(undirected)

        assert len(components) == 2
        assert {"a", "b"} in components
        assert {"c"} in components


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
