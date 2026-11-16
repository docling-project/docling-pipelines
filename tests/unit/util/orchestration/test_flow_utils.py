# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for flow_utils — focusing on sort_dag_topologically."""

import pytest

from docpipe.exceptions.docpipe_exceptions import FlowValidationException
from docpipe.utils.orchestration.flow_utils import sort_dag_topologically


class TestSortDagTopologically:
    """Tests for the shared topological sort utility."""

    def test_linear_chain(self):
        """A→B→C returns nodes in dependency order."""
        dag = [
            {"id": "c", "output_edges": []},
            {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
            {"id": "b", "output_edges": [{"node_id_ref": "c"}]},
        ]
        result = sort_dag_topologically(dag=dag)
        ids = [n["id"] for n in result]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_branch_merge(self):
        """A→[B,C]→D: both branch children appear after A, merge appears last."""
        dag = [
            {"id": "d", "output_edges": []},
            {"id": "b", "output_edges": [{"node_id_ref": "d"}]},
            {"id": "c", "output_edges": [{"node_id_ref": "d"}]},
            {"id": "a", "output_edges": [{"node_id_ref": "b"}, {"node_id_ref": "c"}]},
        ]
        result = sort_dag_topologically(dag=dag)
        ids = [n["id"] for n in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_already_sorted_input_unchanged(self):
        """Input already in topological order produces the same order."""
        dag = [
            {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
            {"id": "b", "output_edges": [{"node_id_ref": "c"}]},
            {"id": "c", "output_edges": []},
        ]
        result = sort_dag_topologically(dag=dag)
        assert [n["id"] for n in result] == ["a", "b", "c"]

    def test_single_node(self):
        """Single-node DAG returns that node."""
        dag = [{"id": "only", "output_edges": []}]
        result = sort_dag_topologically(dag=dag)
        assert [n["id"] for n in result] == ["only"]

    def test_no_output_edges_key(self):
        """Nodes without output_edges key are treated as sinks."""
        dag = [
            {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
            {"id": "b"},
        ]
        result = sort_dag_topologically(dag=dag)
        ids = [n["id"] for n in result]
        assert ids.index("a") < ids.index("b")

    def test_returns_same_node_objects(self):
        """Returned list contains the original node dicts, not copies."""
        node_a = {"id": "a", "output_edges": [{"node_id_ref": "b"}]}
        node_b = {"id": "b", "output_edges": []}
        result = sort_dag_topologically(dag=[node_b, node_a])
        assert result[0] is node_a
        assert result[1] is node_b

    def test_cycle_raises_flow_validation_exception(self):
        """A cyclic DAG raises FlowValidationException."""
        dag = [
            {"id": "a", "output_edges": [{"node_id_ref": "b"}]},
            {"id": "b", "output_edges": [{"node_id_ref": "a"}]},
        ]
        with pytest.raises(FlowValidationException) as exc_info:
            sort_dag_topologically(dag=dag)
        assert exc_info.value.errors
        assert any("cycle" in str(e).lower() for e in exc_info.value.errors)

    def test_three_way_branch(self):
        """A→[B,C,D]→E: all three branch children appear after A and before E."""
        dag = [
            {"id": "e", "output_edges": []},
            {"id": "c", "output_edges": [{"node_id_ref": "e"}]},
            {"id": "a", "output_edges": [{"node_id_ref": "b"}, {"node_id_ref": "c"}, {"node_id_ref": "d"}]},
            {"id": "d", "output_edges": [{"node_id_ref": "e"}]},
            {"id": "b", "output_edges": [{"node_id_ref": "e"}]},
        ]
        result = sort_dag_topologically(dag=dag)
        ids = [n["id"] for n in result]
        for branch in ("b", "c", "d"):
            assert ids.index("a") < ids.index(branch)
            assert ids.index(branch) < ids.index("e")

    def test_dangling_edge_raises_flow_validation_exception(self):
        """Edges referencing unknown nodes fail loudly with FlowValidationException."""
        dag = [
            {"id": "a", "output_edges": [{"node_id_ref": "nonexistent_node"}]},
        ]
        with pytest.raises(FlowValidationException) as exc_info:
            sort_dag_topologically(dag=dag)
        assert exc_info.value.errors
        assert any("unknown node" in str(e).lower() for e in exc_info.value.errors)

    def test_deterministic_sibling_order_matches_input_positions(self):
        """Sibling nodes with equal dependency rank preserve their relative order in the input list."""
        dag = [
            {
                "id": "root",
                "output_edges": [{"node_id_ref": "sib_1"}, {"node_id_ref": "sib_2"}, {"node_id_ref": "sib_3"}],
            },
            {"id": "sib_1", "output_edges": []},
            {"id": "sib_2", "output_edges": []},
            {"id": "sib_3", "output_edges": []},
        ]
        result = sort_dag_topologically(dag=dag)
        ids = [n["id"] for n in result]
        assert ids == ["root", "sib_1", "sib_2", "sib_3"]
