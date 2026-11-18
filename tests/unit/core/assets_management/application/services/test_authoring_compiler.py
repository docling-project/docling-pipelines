"""Tests for authoring flow compiler."""

import pytest

from docpipe.core.assets.flows.application.services.authoring_compiler import AuthoringCompiler
from docpipe.core.assets.flows.domain.models.authoring_flow import (
    AuthoringFlow,
    AuthoringOperator,
    FlowSource,
)
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException


class TestAuthoringCompiler:
    """Tests for AuthoringCompiler."""

    def test_compile_simple_linear_flow(self):
        """Test compiling a simple linear flow."""
        flow = AuthoringFlow(
            flow_name="test-flow",
            description="Test flow",
            global_config={"doc_column": "content"},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest", config={"paths": "./data"}, depends_on=[]),
                AuthoringOperator(
                    type="extract_operator", name="extract", config={"doc_column": "content"}, depends_on=["ingest"]
                ),
                AuthoringOperator(type="chunker", name="chunk", config={"chunk_size": 512}, depends_on=["extract"]),
            ],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        # Verify structure
        assert runtime_dag["name"] == "test-flow"
        assert runtime_dag["description"] == "Test flow"
        assert runtime_dag["global_config"]["doc_column"] == "content"
        assert len(runtime_dag["dag"]) == 3

        # Verify operators
        dag_nodes = {node["name"]: node for node in runtime_dag["dag"]}
        assert "ingest" in dag_nodes
        assert "extract" in dag_nodes
        assert "chunk" in dag_nodes

        # Verify edges
        ingest_node = dag_nodes["ingest"]
        assert len(ingest_node["input_edges"]) == 0
        assert len(ingest_node["output_edges"]) == 1

        extract_node = dag_nodes["extract"]
        assert len(extract_node["input_edges"]) == 1
        assert len(extract_node["output_edges"]) == 1
        assert extract_node["input_edges"][0]["node_id_ref"] == ingest_node["id"]

        chunk_node = dag_nodes["chunk"]
        assert len(chunk_node["input_edges"]) == 1
        assert len(chunk_node["output_edges"]) == 0
        assert chunk_node["input_edges"][0]["node_id_ref"] == extract_node["id"]

    def test_compile_parallel_dependencies(self):
        """Test compiling a flow with parallel dependencies."""
        flow = AuthoringFlow(
            flow_name="parallel-flow",
            description="Flow with parallel paths",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="extract1", config={}, depends_on=["ingest"]),
                AuthoringOperator(type="extract_operator", name="extract2", config={}, depends_on=["ingest"]),
                AuthoringOperator(type="chunker", name="merge", config={}, depends_on=["extract1", "extract2"]),
            ],
            flow_source=FlowSource.PROGRAMMATIC,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        dag_nodes = {node["name"]: node for node in runtime_dag["dag"]}

        # Verify ingest has two outputs
        ingest_node = dag_nodes["ingest"]
        assert len(ingest_node["output_edges"]) == 2

        # Verify merge has two inputs
        merge_node = dag_nodes["merge"]
        assert len(merge_node["input_edges"]) == 2

    def test_compile_preserves_operator_config(self):
        """Test that operator config is preserved during compilation."""
        flow = AuthoringFlow(
            flow_name="config-test",
            description="Test config preservation",
            global_config={},
            flow=[
                AuthoringOperator(
                    type="ingest_source",
                    name="ingest",
                    config={
                        "paths": "./test-data",
                        "include_filter": "pdf,docx",
                        "max_workers": 4,
                        "nested": {"key": "value"},
                    },
                    depends_on=[],
                )
            ],
            flow_source=FlowSource.API,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        ingest_node = runtime_dag["dag"][0]
        assert ingest_node["config"]["paths"] == "./test-data"
        assert ingest_node["config"]["include_filter"] == "pdf,docx"
        assert ingest_node["config"]["max_workers"] == 4
        assert ingest_node["config"]["nested"]["key"] == "value"

    def test_compile_generates_unique_uuids(self):
        """Test that compilation generates unique UUIDs for each operator."""
        flow = AuthoringFlow(
            flow_name="uuid-test",
            description="Test UUID generation",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="op1", config={}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="op2", config={}, depends_on=["op1"]),
                AuthoringOperator(type="chunker", name="op3", config={}, depends_on=["op2"]),
            ],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        uuids = [node["id"] for node in runtime_dag["dag"]]
        assert len(uuids) == len(set(uuids)), "UUIDs should be unique"

        # Verify UUID format (basic check)
        for uuid in uuids:
            assert isinstance(uuid, str)
            assert len(uuid) > 0
            assert "-" in uuid  # UUIDs contain hyphens

    def test_compile_invalid_flow_raises_exception(self):
        """Test that compiling an invalid flow raises exception."""
        flow = AuthoringFlow(
            flow_name="",  # Invalid: empty name
            description="Test",
            global_config={},
            flow=[AuthoringOperator(type="ingest_source", name="op1", config={}, depends_on=[])],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()

        with pytest.raises(FlowInvalidDataException):
            compiler.compile(authoring_flow=flow)

    def test_compile_with_global_config(self):
        """Test that global config is preserved in runtime DAG."""
        global_config = {"doc_column": "content", "force_ingest": True, "storage": "in-memory", "execute_type": "local"}

        flow = AuthoringFlow(
            flow_name="global-config-test",
            description="Test global config",
            global_config=global_config,
            flow=[AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[])],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        assert runtime_dag["global_config"] == global_config

    def test_compile_operator_without_dependencies(self):
        """Test compiling operators without dependencies (root operators)."""
        flow = AuthoringFlow(
            flow_name="no-deps-test",
            description="Test operators without dependencies",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest1", config={}, depends_on=[]),
                AuthoringOperator(type="ingest_source", name="ingest2", config={}, depends_on=[]),
            ],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        for node in runtime_dag["dag"]:
            assert len(node["input_edges"]) == 0
            assert len(node["output_edges"]) == 0

    def test_compile_complex_dag(self):
        """Test compiling a complex DAG with multiple paths."""
        flow = AuthoringFlow(
            flow_name="complex-dag",
            description="Complex DAG test",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="extract", config={}, depends_on=["ingest"]),
                AuthoringOperator(type="chunker", name="chunk1", config={}, depends_on=["extract"]),
                AuthoringOperator(type="chunker", name="chunk2", config={}, depends_on=["extract"]),
                AuthoringOperator(type="embeddings", name="embed1", config={}, depends_on=["chunk1"]),
                AuthoringOperator(type="embeddings", name="embed2", config={}, depends_on=["chunk2"]),
                AuthoringOperator(type="vectordb", name="store", config={}, depends_on=["embed1", "embed2"]),
            ],
            flow_source=FlowSource.PROGRAMMATIC,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        assert len(runtime_dag["dag"]) == 7

        dag_nodes = {node["name"]: node for node in runtime_dag["dag"]}

        # Verify extract has two outputs
        assert len(dag_nodes["extract"]["output_edges"]) == 2

        # Verify store has two inputs
        assert len(dag_nodes["store"]["input_edges"]) == 2

    def test_compile_preserves_operator_order(self):
        """Test that operator order is preserved in the DAG."""
        flow = AuthoringFlow(
            flow_name="order-test",
            description="Test operator order",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="first", config={}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="second", config={}, depends_on=["first"]),
                AuthoringOperator(type="chunker", name="third", config={}, depends_on=["second"]),
            ],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        names = [node["name"] for node in runtime_dag["dag"]]
        assert names == ["first", "second", "third"]

    def test_compile_with_description(self):
        """Test that flow description is preserved."""
        description = "This is a test flow for document processing"

        flow = AuthoringFlow(
            flow_name="desc-test",
            description=description,
            global_config={},
            flow=[AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[])],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        assert runtime_dag["description"] == description

    def test_compile_without_description(self):
        """Test compiling flow without description."""
        flow = AuthoringFlow(
            flow_name="no-desc-test",
            description=None,
            global_config={},
            flow=[AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[])],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        assert runtime_dag["description"] is None or runtime_dag["description"] == ""

    def test_compile_branch_dependency_adds_link_id(self):
        """Test that operators with single branch dependency get link_id in their definition."""
        flow = AuthoringFlow(
            flow_name="branch-test",
            description="Test branch dependency compilation",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[]),
                AuthoringOperator(
                    type="branching",
                    name="branch",
                    config={
                        "branches": {
                            "low_quality": {
                                "link_name": "Low Quality",
                                "criteria_json": {
                                    "criteria_list": [{"variable": "score", "operator": "<", "value": 50}],
                                    "logical_operator": "AND",
                                },
                            },
                            "high_quality": {
                                "link_name": "High Quality",
                                "criteria_json": {
                                    "criteria_list": [{"variable": "score", "operator": ">=", "value": 50}],
                                    "logical_operator": "AND",
                                },
                            },
                        }
                    },
                    depends_on=["ingest"],
                ),
                AuthoringOperator(
                    type="sql_filter",
                    name="filter_low",
                    config={"criteria_json": {}},
                    depends_on=["branch.low_quality"],
                ),
            ],
            flow_source=FlowSource.CLI,
        )

        compiler = AuthoringCompiler()
        runtime_dag = compiler.compile(authoring_flow=flow)

        dag_nodes = {node["name"]: node for node in runtime_dag["dag"]}
        filter_node = dag_nodes["filter_low"]

        # Verify operator has link_id
        assert "link_id" in filter_node, "Operator with branch dependency should have link_id"
        assert filter_node["link_id"] == "low_quality"

        # Verify input edge has link_name and correct node_id_ref
        assert len(filter_node["input_edges"]) == 1
        assert filter_node["input_edges"][0]["link_name"] == "low_quality"
        assert filter_node["input_edges"][0]["node_id_ref"] == dag_nodes["branch"]["id"]


class TestAuthoringCompilerStaticMethods:
    """Verify compiler helpers are static and callable without an instance."""

    STATIC_METHODS = (
        "_generate_operator_ids",
        "_build_dependency_graph",
        "_build_input_edges",
        "_build_output_edges",
        "_transform_operator_config",
        "_build_merge_input_links",
    )

    def test_compiler_helpers_are_static(self):
        """Every converted compiler helper must be a true staticmethod."""
        import inspect

        for method_name in self.STATIC_METHODS:
            assert isinstance(inspect.getattr_static(AuthoringCompiler, method_name), staticmethod), (
                f"{method_name} is not a staticmethod"
            )

    def test_build_merge_input_links_class_call(self):
        """Merge input_links construction works when called directly on the class."""
        input_edges = [
            {"node_id_ref": "id-1", "link_name": "branch_a"},
            {"node_id_ref": "id-2"},
        ]

        links = AuthoringCompiler._build_merge_input_links(input_edges=input_edges)

        assert links == [
            {"link_name": "branch_a", "node_id_ref": "id-1"},
            {"link_name": "input_2", "node_id_ref": "id-2"},
        ]
