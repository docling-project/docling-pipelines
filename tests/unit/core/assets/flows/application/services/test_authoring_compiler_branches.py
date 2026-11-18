# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for AuthoringCompiler branch-reference handling and defensive paths."""

import pytest

from docpipe.core.assets.flows.application.services.authoring_compiler import AuthoringCompiler
from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow, AuthoringOperator


def _branching_flow(*, tail):
    """Build ingest -> branching(left, right) followed by the given tail operators."""
    return AuthoringFlow(
        flow_name="branch-flow",
        flow=[
            AuthoringOperator(type="ingest_source", name="ingest"),
            AuthoringOperator(
                type="branching",
                name="br",
                depends_on=["ingest"],
                config={"branches": {"left": {"condition": "a"}, "right": {"condition": "b"}}},
            ),
            *tail,
        ],
    )


def _nodes_by_name(runtime_flow):
    """Index compiled DAG nodes by operator name."""
    return {node["name"]: node for node in runtime_flow["dag"]}


class TestBranchReferences:
    """Tests for compiling operators that depend on branching outputs."""

    def test_single_branch_dependency_sets_link_id_and_branch_edges(self):
        """An operator depending on exactly one branch gets link_id and a named output edge from the brancher."""
        flow = _branching_flow(tail=[AuthoringOperator(type="noop", name="x", depends_on=["br.left"])])

        nodes = _nodes_by_name(AuthoringCompiler().compile(authoring_flow=flow))

        assert nodes["x"]["link_id"] == "left"
        assert nodes["x"]["input_edges"] == [{"node_id_ref": nodes["br"]["id"], "link_name": "left"}]
        assert nodes["br"]["output_edges"] == [{"node_id_ref": nodes["x"]["id"], "link_name": "left"}]
        assert nodes["br"]["config"]["branches"] == [
            {"link_id": "left", "link_name": "left", "condition": "a"},
            {"link_id": "right", "link_name": "right", "condition": "b"},
        ]

    def test_multiple_branch_dependencies_do_not_set_link_id(self):
        """A merge over two branches gets one input edge and input link per branch, but no link_id."""
        flow = _branching_flow(
            tail=[AuthoringOperator(type="merge", name="m", depends_on=["br.left", "br.right"])],
        )

        nodes = _nodes_by_name(AuthoringCompiler().compile(authoring_flow=flow))
        merge = nodes["m"]
        br_id = nodes["br"]["id"]

        assert "link_id" not in merge
        assert merge["input_edges"] == [
            {"node_id_ref": br_id, "link_name": "left"},
            {"node_id_ref": br_id, "link_name": "right"},
        ]
        assert merge["config"]["input_links"] == [
            {"link_name": "left", "node_id_ref": br_id},
            {"link_name": "right", "node_id_ref": br_id},
        ]


class TestDefensivePaths:
    """Tests for guards that validation normally makes unreachable through compile()."""

    def test_compile_operator_rejects_unnamed_operator(self):
        """_compile_operator refuses an operator without a name."""
        with pytest.raises(ValueError, match="Operator name cannot be None"):
            AuthoringCompiler()._compile_operator(
                operator=AuthoringOperator(type="noop"), operator_ids={}, dependency_graph={}
            )

    def test_branching_config_with_non_dict_branches_is_left_unchanged(self):
        """Branches that are already in list form are passed through untouched."""
        branches = [{"link_id": "left"}]
        operator = AuthoringOperator(type="branching", name="br", config={"branches": branches})

        config = AuthoringCompiler._transform_operator_config(operator=operator)

        assert config == {"branches": branches}
        assert config is not operator.config
