# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for ElyraConverter edge cases.

Complements tests/unit/util/orchestration/test_elyra_converter.py. Tests cover:
- Operator metadata load failure and missing flow_id
- Flow name / global_config lookup order and primary pipeline selection
- Link validation (unknown port), merge input links, malformed branching criteria
- DAG validation guards (node limit, no starting node)
- Reverse layout for branching, merge, diamond and unreachable nodes
- Category-based descriptions and branching target resolution in the reverse conversion
"""

from unittest.mock import patch

import networkx as nx
import pytest

from docpipe.exceptions.docpipe_exceptions import FlowValidationException
from docpipe.utils.orchestration.elyra_converter import MAX_NODES, ElyraConverter


@pytest.fixture
def converter():
    """Return a converter with empty operator metadata."""
    with patch.object(ElyraConverter, "_load_operator_metadata", lambda self: None):
        conv = ElyraConverter()
    conv.metadata = {}
    return conv


def _node(node_id, op="noop", *, links=None, label=None, parameters=None):
    """Build an Elyra node with one input port (holding links) and one output port."""
    node = {
        "id": node_id,
        "op": op,
        "app_data": {"ui_data": {"label": label or node_id}},
        "outputs": [{"id": f"{node_id}-out"}],
        "inputs": [{"id": f"{node_id}-in", "links": links or []}],
    }
    if parameters is not None:
        node["parameters"] = parameters
    return node


def _link(source):
    """Build an Elyra link from the output port of ``source``."""
    return {"node_id_ref": source, "port_id_ref": f"{source}-out"}


def _pipeline(nodes, **app_data):
    """Wrap nodes into a single-pipeline Elyra document."""
    return {"pipelines": [{"id": "p1", "nodes": nodes, "app_data": app_data}]}


def _dag_node(node_id, operator="noop", *, inputs=(), outputs=(), config=None, link_id=None):
    """Build an internal DAG node."""
    return {
        "id": node_id,
        "name": node_id,
        "operator": operator,
        "config": config or {},
        "input_edges": [{"node_id_ref": i} for i in inputs],
        "output_edges": [{"node_id_ref": o} for o in outputs],
        "link_id": link_id,
    }


class TestMetadataLoading:
    """Test operator metadata loading."""

    def test_metadata_load_failure_falls_back_to_empty_metadata(self):
        """If OperatorMetadata raises, the converter still works with empty metadata."""
        with patch(
            "docpipe.core.operators.operator_metadata.OperatorMetadata",
            side_effect=RuntimeError("registry unavailable"),
        ):
            conv = ElyraConverter()

        assert conv.metadata == {}


class TestElyraToInternal:
    """Test transform_elyra_to_internal edge cases."""

    def test_flow_id_none_is_rejected(self, converter):
        """A missing flow_id raises a validation error before any parsing."""
        with pytest.raises(FlowValidationException) as exc_info:
            converter.transform_elyra_to_internal(elyra_json=_pipeline([_node("a")]), flow_id=None)  # type: ignore[arg-type]

        assert "flow_id is required" in exc_info.value.errors[0].message

    def test_ui_data_name_and_properties_take_precedence_over_ds_flow(self, converter):
        """Name/description from ui_data and global_config from properties win over ds_flow."""
        elyra = _pipeline(
            [_node("a")],
            ui_data={"name": "UI Name", "description": "UI desc"},
            properties={"storage": "in-memory"},
            ds_flow={"name": "Legacy", "description": "legacy", "global_config": {"storage": "duckdb"}},
        )

        flow = converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")["flow"]

        assert flow["name"] == "UI Name"
        assert flow["description"] == "UI desc"
        assert flow["global_config"] == {"storage": "in-memory"}

    def test_properties_kept_when_name_comes_from_ds_flow(self, converter):
        """Without a ui_data name, ds_flow supplies the name but properties still provide global_config."""
        elyra = _pipeline(
            [_node("a")],
            properties={"storage": "in-memory"},
            ds_flow={"name": "Legacy", "description": "legacy", "global_config": {"storage": "duckdb"}},
        )

        flow = converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")["flow"]

        assert flow["name"] == "Legacy"
        assert flow["description"] == "legacy"
        assert flow["global_config"] == {"storage": "in-memory"}

    def test_unknown_port_reference_is_rejected(self, converter):
        """A link pointing to an existing node but a non-existent port raises."""
        bad_link = {"node_id_ref": "a", "port_id_ref": "no-such-port"}
        elyra = _pipeline([_node("a"), _node("b", links=[bad_link])])

        with pytest.raises(FlowValidationException) as exc_info:
            converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")

        assert "port_id_ref 'no-such-port'" in exc_info.value.errors[0].message

    def test_merge_node_receives_input_links_in_config(self, converter):
        """A merge node gets its input edges copied into config['input_links']."""
        elyra = _pipeline(
            [
                _node("a"),
                _node("b", links=[_link("a")]),
                _node("c", links=[_link("a")]),
                _node("m", "merge", links=[_link("b"), _link("c")], parameters={"strategy": "union"}),
            ]
        )

        dag = converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")["flow"]["dag"]

        merge = next(node for node in dag if node["id"] == "m")
        assert merge["config"]["strategy"] == "union"
        assert merge["config"]["input_links"] == [
            {"node_id_ref": "b", "link_name": None},
            {"node_id_ref": "c", "link_name": None},
        ]

    def test_branching_criteria_json_that_is_not_a_dict_gets_default(self, converter):
        """Non-dict criteria_json is replaced by an empty AND criteria structure."""
        parameters = {
            "link_conditions": [
                {
                    "link_id": "l1",
                    "link_name": "first",
                    "target_node_id": "b",
                    "condition": {"criteria_json": ["unexpected"], "logical_operator": "OR"},
                }
            ]
        }
        elyra = _pipeline([_node("a", "branching", parameters=parameters), _node("b", links=[_link("a")])])

        dag = converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")["flow"]["dag"]

        branching = next(node for node in dag if node["id"] == "a")
        assert "link_conditions" not in branching["config"]
        assert branching["config"]["branches"] == [
            {
                "criteria_list": [],
                "criteria_json": {"logical_operator": "AND", "criteria_list": []},
                "logical_operator": "OR",
                "link_id": "l1",
                "link_name": "first",
            }
        ]

    def test_multiple_starting_nodes_are_allowed(self, converter):
        """Disconnected starting nodes only produce a warning; all nodes are converted."""
        elyra = _pipeline([_node("a"), _node("b"), _node("c", links=[_link("a")])])

        dag = converter.transform_elyra_to_internal(elyra_json=elyra, flow_id="f1")["flow"]["dag"]

        assert [node["id"] for node in dag] == ["a", "b", "c"]

    def test_more_than_max_nodes_is_rejected(self, converter):
        """A linear flow with MAX_NODES + 1 nodes exceeds the node limit."""
        nodes = [_node("n0")] + [_node(f"n{i}", links=[_link(f"n{i - 1}")]) for i in range(1, MAX_NODES + 1)]

        with pytest.raises(FlowValidationException) as exc_info:
            converter.transform_elyra_to_internal(elyra_json=_pipeline(nodes), flow_id="f1")

        assert f"more than {MAX_NODES} nodes" in exc_info.value.errors[0].message

    def test_exactly_max_nodes_is_accepted(self, converter):
        """A flow with exactly MAX_NODES nodes is still valid."""
        nodes = [_node("n0")] + [_node(f"n{i}", links=[_link(f"n{i - 1}")]) for i in range(1, MAX_NODES)]

        dag = converter.transform_elyra_to_internal(elyra_json=_pipeline(nodes), flow_id="f1")["flow"]["dag"]

        assert len(dag) == MAX_NODES


class TestPrimaryPipelineSelection:
    """Test _get_primary_pipeline via get_global_config_from_elyra."""

    @staticmethod
    def _doc(primary):
        """Two pipelines with distinct global configs."""
        return {
            "primary_pipeline": primary,
            "pipelines": [
                {"id": "p1", "app_data": {"properties": {"which": "first"}}},
                {"id": "p2", "app_data": {"properties": {"which": "second"}}},
            ],
        }

    def test_primary_pipeline_is_found_after_other_pipelines(self, converter):
        """The pipeline referenced by primary_pipeline is used even when it is not first."""
        assert converter.get_global_config_from_elyra(elyra_json=self._doc("p2")) == {"which": "second"}

    def test_unknown_primary_pipeline_falls_back_to_first(self, converter):
        """An unknown primary_pipeline id falls back to the first pipeline."""
        assert converter.get_global_config_from_elyra(elyra_json=self._doc("missing")) == {"which": "first"}


class TestValidateDag:
    """Test _validate_dag guards that cannot be reached through a well-formed conversion."""

    def test_no_starting_node_is_rejected(self, converter):
        """An acyclic graph without any starting node is rejected."""
        graph = nx.DiGraph()
        graph.add_edge("a", "b")

        with pytest.raises(FlowValidationException) as exc_info:
            converter._validate_dag(graph=graph, first_nodes=[], node_count=2)

        assert "No starting node found" in exc_info.value.errors[0].message


class TestGenerateNodeLayout:
    """Test the reverse-conversion layout for branching, merge and diamond shapes."""

    def test_branching_layout_with_unmatched_branches_and_children(self, converter):
        """Branches without link_id or without a matching child are skipped; unmatched children go last."""
        dag = [
            _dag_node(
                "b",
                "branching",
                outputs=("x", "y"),
                config={"branches": [{"link_id": None}, {"link_id": "l-x"}, {"link_id": "l-none"}]},
            ),
            _dag_node("x", inputs=("b",), link_id="l-x"),
            _dag_node("y", inputs=("b",)),
        ]

        positions = converter._generate_node_layout(dag=dag, spacing_x=10, spacing_y=50)

        assert positions["b"] == (100, 100)
        # x belongs to branch index 1 -> shifted 280 right and one row down
        assert positions["x"] == (380, 150)
        # y matches no branch and is placed after the laid-out tree
        assert positions["y"] == (380, 100)

    def test_branch_child_already_positioned_is_not_moved(self, converter):
        """A branch target already laid out from another root keeps its position."""
        dag = [
            _dag_node("r", outputs=("x",)),
            _dag_node("b", "branching", outputs=("x",), config={"branches": [{"link_id": "l-x"}]}),
            _dag_node("x", inputs=("r", "b"), link_id="l-x"),
        ]

        positions = converter._generate_node_layout(dag=dag, spacing_x=10, spacing_y=50)

        assert positions["r"] == (100, 100)
        assert positions["x"] == (110, 100)
        assert positions["b"] == (120, 100)

    def test_merge_stops_subtree_and_children_are_placed_afterwards(self, converter):
        """The subtree walk stops at a merge node; its descendants are placed by the fallback pass."""
        dag = [
            _dag_node("a", outputs=("m",)),
            _dag_node("m", "merge", inputs=("a",), outputs=("c",)),
            _dag_node("c", inputs=("m",)),
        ]

        positions = converter._generate_node_layout(dag=dag, spacing_x=10, spacing_y=50)

        assert positions == {"a": (100, 100), "m": (110, 100), "c": (120, 100)}

    def test_diamond_positions_shared_child_once(self, converter):
        """In a diamond, the shared child is positioned via the first parent only."""
        dag = [
            _dag_node("a", outputs=("b", "c")),
            _dag_node("b", inputs=("a",), outputs=("d",)),
            _dag_node("c", inputs=("a",), outputs=("d",)),
            _dag_node("d", inputs=("b", "c")),
        ]

        positions = converter._generate_node_layout(dag=dag, spacing_x=10, spacing_y=50)

        assert positions == {"a": (100, 100), "b": (110, 100), "d": (120, 100), "c": (130, 100)}

    def test_duplicate_root_entry_is_positioned_once(self, converter):
        """A root listed twice keeps its first position."""
        dag = [_dag_node("a"), _dag_node("a")]

        assert converter._generate_node_layout(dag=dag, spacing_x=10, spacing_y=50) == {"a": (100, 100)}

    def test_position_subtree_returns_start_for_positioned_node(self):
        """Positioning an already positioned node changes nothing and returns start_x."""
        positions = {"a": (1, 2)}

        result = ElyraConverter._position_subtree(
            node_id="a",
            start_x=500,
            start_y=0,
            spacing_x=10,
            spacing_y=10,
            node_by_id={"a": _dag_node("a")},
            children_map={},
            positions=positions,
            positioned={"a"},
        )

        assert result == 500
        assert positions == {"a": (1, 2)}


class TestInternalToElyra:
    """Test transform_internal_to_elyra details."""

    def test_unknown_category_uses_generic_description(self, converter):
        """Operators whose metadata category is not an OperatorCategory get the generic card."""
        internal = {"flow": {"name": "f", "dag": [_dag_node("a", "custom_op")]}}

        elyra = converter.transform_internal_to_elyra(
            internal_json=internal, metadata={"custom_op": {"category": "Unknown", "description": "Custom thing"}}
        )

        react = elyra["pipelines"][0]["nodes"][0]["app_data"]["react_nodes_data"]
        assert react == {"color": "#000000", "cardDescription": "Custom operator"}
        assert elyra["pipelines"][0]["nodes"][0]["app_data"]["ui_data"]["description"] == "Custom thing"

    def test_branch_without_matching_target_has_no_target_ids(self, converter):
        """A branch whose link_id matches no DAG node keeps its link condition without targets."""
        dag = [
            _dag_node(
                "b",
                "branching",
                outputs=("x",),
                config={"branches": [{"link_id": "l-x", "link_name": "x"}, {"link_id": "l-gone", "link_name": "g"}]},
            ),
            _dag_node("x", inputs=("b",), link_id="l-x"),
        ]

        elyra = converter.transform_internal_to_elyra(internal_json={"flow": {"dag": dag}}, metadata={})

        conditions = elyra["pipelines"][0]["nodes"][0]["parameters"]["link_conditions"]
        assert conditions[0]["target_node_id"] == "x"
        assert conditions[0]["target_port_id"] == "noop_inPort"
        assert conditions[1]["link_id"] == "l-gone"
        assert "target_node_id" not in conditions[1]


class TestAddLinksForSingleNode:
    """Test _add_links_for_single_node guards for nodes built outside the normal conversion."""

    def test_node_without_input_ports_gets_no_links(self):
        """Input edges are ignored when the Elyra node has no input port to attach them to."""
        elyra_node: dict = {"id": "b"}

        ElyraConverter._add_links_for_single_node(
            dag_node=_dag_node("b", inputs=("a",)), elyra_node=elyra_node, port_mappings={}
        )

        assert elyra_node == {"id": "b"}

    def test_existing_links_are_kept_and_extended(self):
        """Links already present on the input port are kept; new ones are appended."""
        existing = {"id": "l0", "node_id_ref": "z", "port_id_ref": "z_out"}
        elyra_node: dict = {"id": "b", "inputs": [{"id": "b_in", "links": [existing]}]}
        port_mappings = {"a": {"output_ports": [{"id": "a_out"}]}}

        ElyraConverter._add_links_for_single_node(
            dag_node=_dag_node("b", inputs=("a",), link_id="l1"), elyra_node=elyra_node, port_mappings=port_mappings
        )

        assert elyra_node["inputs"][0]["links"] == [existing, {"id": "l1", "node_id_ref": "a", "port_id_ref": "a_out"}]
