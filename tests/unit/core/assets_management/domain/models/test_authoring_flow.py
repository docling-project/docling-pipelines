"""Tests for authoring flow domain models and validation."""

import pytest

from docpipe.core.assets.flows.domain.models.authoring_flow import (
    AuthoringFlow,
    AuthoringOperator,
    FlowSource,
)
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

# ---------------------------------------------------------------------------
# Helpers for cycle detection tests
# ---------------------------------------------------------------------------


def _linear_chain(n: int) -> AuthoringFlow:
    """Build a valid linear chain: op_0 -> op_1 -> ... -> op_{n-1}."""
    operators = [AuthoringOperator(type="noop", name="op_0", depends_on=[])]
    for i in range(1, n):
        operators.append(AuthoringOperator(type="noop", name=f"op_{i}", depends_on=[f"op_{i - 1}"]))
    return AuthoringFlow(flow_name="linear-chain", flow=operators)


def _flow_with_cycle(*, cycle_back_to: int, n: int) -> AuthoringFlow:
    """Build a chain of length n and close a cycle.

    A cycle is created by making op_{cycle_back_to} also depend on the last node
    op_{n-1}, so the DFS will encounter:
    op_{cycle_back_to} -> ... -> op_{n-1} -> op_{cycle_back_to}.
    """
    operators = [AuthoringOperator(type="noop", name="op_0", depends_on=[])]
    for i in range(1, n):
        operators.append(AuthoringOperator(type="noop", name=f"op_{i}", depends_on=[f"op_{i - 1}"]))
    # Close the cycle: op_{cycle_back_to} gains an additional dependency on the last node,
    # creating: op_{cycle_back_to} -> op_{n-1} -> ... -> op_{cycle_back_to}
    operators[cycle_back_to].depends_on.append(f"op_{n - 1}")
    return AuthoringFlow(flow_name="cycle-flow", flow=operators)


def _invoke_cycle_check(flow: AuthoringFlow) -> list[str]:
    """Call _check_circular_dependencies directly (bypasses full validate())."""
    return flow._check_circular_dependencies()


class TestAuthoringOperator:
    """Tests for AuthoringOperator validation."""

    def test_valid_operator(self):
        """Test creating a valid operator."""
        op = AuthoringOperator(type="ingest_source", name="ingest_docs", config={"paths": "./data"}, depends_on=[])

        errors = op.validate(all_operator_names={"ingest_docs"}, operator_map={"ingest_docs": op})

        assert len(errors) == 0

    def test_empty_operator_type(self):
        """Test validation fails for empty operator type."""
        op = AuthoringOperator(type="", name="test_op", config={}, depends_on=[])

        errors = op.validate(all_operator_names={"test_op"}, operator_map={"test_op": op})

        assert len(errors) == 1
        assert "type cannot be empty" in errors[0]

    def test_operator_name_with_spaces(self):
        """Test validation fails for operator name with spaces."""
        op = AuthoringOperator(type="ingest_source", name="test op", config={}, depends_on=[])

        errors = op.validate(all_operator_names={"test op"}, operator_map={"test op": op})

        assert len(errors) == 1
        assert "cannot contain spaces" in errors[0]

    def test_operator_name_with_branch_separator(self):
        """Test validation fails for operator name with branch separator."""
        op = AuthoringOperator(type="ingest_source", name="test.op", config={}, depends_on=[])

        errors = op.validate(all_operator_names={"test.op"}, operator_map={"test.op": op})

        assert len(errors) == 1
        assert "cannot contain '.'" in errors[0]

    def test_invalid_config_type(self):
        """Test validation fails for non-dict config."""
        op = AuthoringOperator(
            type="ingest_source",
            name="test_op",
            config="invalid",  # type: ignore
            depends_on=[],
        )

        errors = op.validate(all_operator_names={"test_op"}, operator_map={"test_op": op})

        assert len(errors) == 1
        assert "config must be a dictionary" in errors[0]

    def test_nonexistent_dependency(self):
        """Test validation fails for nonexistent dependency."""
        op = AuthoringOperator(type="extract_operator", name="extract", config={}, depends_on=["nonexistent"])

        errors = op.validate(all_operator_names={"extract"}, operator_map={"extract": op})

        assert len(errors) == 1
        assert "not found in flow" in errors[0]

    def test_circular_dependency(self):
        """Test that circular dependencies are detected at flow level."""
        # Create operators with circular dependency: op1 -> op2 -> op1
        op1 = AuthoringOperator(type="test_op", name="op1", depends_on=["op2"])
        op2 = AuthoringOperator(type="test_op", name="op2", depends_on=["op1"])

        # Circular dependency is detected at flow level, not operator level
        flow = AuthoringFlow(flow_name="test_flow", flow=[op1, op2], flow_source=FlowSource.CLI)

        # Flow validation should detect circular dependency
        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "Circular dependency" in str(exc_info.value)


class TestAuthoringFlow:
    """Tests for AuthoringFlow validation."""

    def test_valid_flow(self):
        """Test creating a valid flow."""
        flow = AuthoringFlow(
            flow_name="test-flow",
            description="Test flow",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="ingest", config={"paths": "./data"}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="extract", config={}, depends_on=["ingest"]),
            ],
            flow_source=FlowSource.CLI,
        )

        flow.validate()  # Should not raise

    def test_empty_flow_name(self):
        """Test validation fails for empty flow name."""
        flow = AuthoringFlow(
            flow_name="",
            description="Test",
            global_config={},
            flow=[AuthoringOperator(type="ingest_source", name="ingest", config={}, depends_on=[])],
            flow_source=FlowSource.CLI,
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "Flow name cannot be empty" in str(exc_info.value)

    def test_empty_flow_array(self):
        """Test validation fails for empty flow array."""
        flow = AuthoringFlow(
            flow_name="test-flow", description="Test", global_config={}, flow=[], flow_source=FlowSource.CLI
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "must contain at least one operator" in str(exc_info.value)

    def test_duplicate_operator_names(self):
        """Test validation fails for duplicate operator names."""
        flow = AuthoringFlow(
            flow_name="test-flow",
            description="Test",
            global_config={},
            flow=[
                AuthoringOperator(type="ingest_source", name="duplicate", config={}, depends_on=[]),
                AuthoringOperator(type="extract_operator", name="duplicate", config={}, depends_on=[]),
            ],
            flow_source=FlowSource.CLI,
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "Duplicate operator name" in str(exc_info.value)

    def test_operator_without_name(self):
        """Test validation fails for operator without name."""
        flow = AuthoringFlow(
            flow_name="test-flow",
            description="Test",
            global_config={},
            flow=[
                AuthoringOperator(
                    type="ingest_source",
                    name=None,  # type: ignore
                    config={},
                    depends_on=[],
                )
            ],
            flow_source=FlowSource.CLI,
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "must have a name" in str(exc_info.value)

    def test_multiple_validation_errors(self):
        """Test that all validation errors are collected."""
        flow = AuthoringFlow(
            flow_name="test-flow",  # Valid name
            description="Test",
            global_config={},
            flow=[
                AuthoringOperator(
                    type="",  # Invalid: empty type
                    name="op1",
                    config={},
                    depends_on=[],
                ),
                AuthoringOperator(
                    type="extract_operator",
                    name="op2",
                    config={},
                    depends_on=["nonexistent"],  # Invalid: nonexistent dependency
                ),
            ],
            flow_source=FlowSource.CLI,
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        error_msg = str(exc_info.value)
        # Should contain multiple errors
        assert "type cannot be empty" in error_msg
        assert "not found in flow" in error_msg

    def test_flow_source_enum(self):
        """Test FlowSource enum values."""
        assert FlowSource.API == "api"
        assert FlowSource.CLI == "cli"
        assert FlowSource.PROGRAMMATIC == "programmatic"
        assert FlowSource.UI == "ui"

    def test_valid_branch_dependency(self):
        """Test validation passes for valid branch dependency."""
        flow = AuthoringFlow(
            flow_name="test-flow",
            description="Test",
            global_config={},
            flow=[
                AuthoringOperator(
                    type="branching",
                    name="branch_op",
                    config={"branches": {"branch_a": {}, "branch_b": {}}},
                    depends_on=[],
                ),
                AuthoringOperator(
                    type="extract_operator",
                    name="extract",
                    config={},
                    depends_on=["branch_op.branch_a"],  # Branch reference
                ),
            ],
            flow_source=FlowSource.CLI,
        )

        flow.validate()  # Should not raise

    def test_branching_non_dict_config_raises_flow_invalid_data(self):
        """A branching operator whose config is not a dict fails validation."""
        flow = AuthoringFlow.from_dict(
            data={
                "flow_name": "x",
                "flow": [
                    {"type": "ingest_source", "name": "a"},
                    {"type": "branching", "name": "b", "depends_on": ["a"], "config": []},
                ],
            }
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        assert "config must be a dictionary" in str(exc_info.value)
        assert "operator: b" in str(exc_info.value)

    def test_branch_reference_to_non_dict_branching_config_collects_errors(self):
        """A branch reference into a non-dict branching config is a validation error."""
        flow = AuthoringFlow.from_dict(
            data={
                "flow_name": "x",
                "flow": [
                    {"type": "ingest_source", "name": "a"},
                    {"type": "branching", "name": "b", "depends_on": ["a"], "config": "not-a-dict"},
                    {"type": "noop", "name": "c", "depends_on": ["b.left"]},
                ],
            }
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        message = str(exc_info.value)
        assert "config must be a dictionary" in message
        assert "operator: b" in message

    def test_branch_reference_to_non_dict_branches_collects_errors(self):
        """A branch reference when branches is not a dict fails validation without crashing."""
        flow = AuthoringFlow.from_dict(
            data={
                "flow_name": "x",
                "flow": [
                    {"type": "ingest_source", "name": "a"},
                    {
                        "type": "branching",
                        "name": "b",
                        "depends_on": ["a"],
                        "config": {"branches": ["left", "right"]},
                    },
                    {"type": "noop", "name": "c", "depends_on": ["b.left"]},
                ],
            }
        )

        with pytest.raises(FlowInvalidDataException) as exc_info:
            flow.validate()

        message = str(exc_info.value)
        assert "branches" in message.lower()
        assert "dictionary" in message.lower()


class TestAuthoringFlowFromDict:
    """Tests for AuthoringFlow.from_dict()."""

    def test_from_dict_valid(self):
        """Happy path: from_dict constructs an AuthoringFlow from a complete dict."""
        data = {
            "flow_name": "my-flow",
            "flow": [
                {"type": "ingest_source", "name": "ingest", "depends_on": [], "config": {}},
            ],
            "global_config": {},
        }
        flow = AuthoringFlow.from_dict(data=data)
        assert flow.flow_name == "my-flow"
        assert len(flow.flow) == 1
        assert flow.flow[0].type == "ingest_source"

    def test_from_dict_missing_flow_name_raises_flow_invalid_data_exception(self):
        """Missing 'flow_name' must raise FlowInvalidDataException, not KeyError."""
        data = {
            "flow": [{"type": "ingest_source", "name": "ingest", "depends_on": [], "config": {}}],
        }
        with pytest.raises(FlowInvalidDataException) as exc_info:
            AuthoringFlow.from_dict(data=data)

        assert "flow_name" in str(exc_info.value)

    def test_from_dict_operator_missing_type_raises_flow_invalid_data_exception(self):
        """An operator dict without 'type' must raise FlowInvalidDataException, not KeyError."""
        data = {
            "flow_name": "my-flow",
            "flow": [
                {"name": "ingest"},  # 'type' is absent
            ],
        }
        with pytest.raises(FlowInvalidDataException) as exc_info:
            AuthoringFlow.from_dict(data=data)

        assert "type" in str(exc_info.value)
        assert "0" in str(exc_info.value)  # index reported in message


# ---------------------------------------------------------------------------
# Cycle detection correctness tests
# ---------------------------------------------------------------------------


class TestCycleDetectionCorrectness:
    """Verify that _check_circular_dependencies returns the right result for known graphs."""

    def test_linear_chain_has_no_cycle(self) -> None:
        flow = _linear_chain(5)
        errors = _invoke_cycle_check(flow)
        assert errors == []

    def test_single_operator_has_no_cycle(self) -> None:
        flow = AuthoringFlow(
            flow_name="single",
            flow=[AuthoringOperator(type="noop", name="op_0", depends_on=[])],
        )
        errors = _invoke_cycle_check(flow)
        assert errors == []

    def test_self_dependency_detected(self) -> None:
        flow = AuthoringFlow(
            flow_name="self-dep",
            flow=[AuthoringOperator(type="noop", name="op_0", depends_on=["op_0"])],
        )
        errors = _invoke_cycle_check(flow)
        assert any("op_0" in err for err in errors)

    def test_two_node_cycle_detected(self) -> None:
        """op_0 depends on op_1 and op_1 depends on op_0 -- a direct cycle."""
        flow = AuthoringFlow(
            flow_name="two-cycle",
            flow=[
                AuthoringOperator(type="noop", name="op_0", depends_on=["op_1"]),
                AuthoringOperator(type="noop", name="op_1", depends_on=["op_0"]),
            ],
        )
        errors = _invoke_cycle_check(flow)
        assert len(errors) >= 1

    def test_back_edge_cycle_detected_in_longer_chain(self) -> None:
        """Chain of 10 with a back edge from op_0 to op_9."""
        flow = _flow_with_cycle(cycle_back_to=0, n=10)
        errors = _invoke_cycle_check(flow)
        assert len(errors) >= 1

    def test_back_edge_to_middle_detected(self) -> None:
        """Chain of 8 with a back edge from op_3 to op_7."""
        flow = _flow_with_cycle(cycle_back_to=3, n=8)
        errors = _invoke_cycle_check(flow)
        assert len(errors) >= 1

    def test_no_false_positive_on_diamond(self) -> None:
        """Diamond DAG (shared ancestor, not a cycle) must not raise errors."""
        #   op_0
        #  /    \
        # op_1  op_2
        #  \    /
        #   op_3
        flow = AuthoringFlow(
            flow_name="diamond",
            flow=[
                AuthoringOperator(type="noop", name="op_0", depends_on=[]),
                AuthoringOperator(type="noop", name="op_1", depends_on=["op_0"]),
                AuthoringOperator(type="noop", name="op_2", depends_on=["op_0"]),
                AuthoringOperator(type="noop", name="op_3", depends_on=["op_1", "op_2"]),
            ],
        )
        errors = _invoke_cycle_check(flow)
        assert errors == []

    def test_no_false_positive_on_wide_dag(self) -> None:
        """A wide DAG (many nodes, no cycles) returns no errors."""
        # op_0 is root; every other node depends on op_0 only
        operators = [AuthoringOperator(type="noop", name="op_0", depends_on=[])]
        for i in range(1, 30):
            operators.append(AuthoringOperator(type="noop", name=f"op_{i}", depends_on=["op_0"]))
        flow = AuthoringFlow(flow_name="wide-dag", flow=operators)
        errors = _invoke_cycle_check(flow)
        assert errors == []

    def test_validate_raises_on_cyclic_flow(self) -> None:
        """Full validate() raises FlowInvalidDataException when a cycle exists."""
        flow = _flow_with_cycle(cycle_back_to=0, n=5)
        with pytest.raises(FlowInvalidDataException):
            flow.validate()

    def test_validate_passes_on_acyclic_flow(self) -> None:
        """Full validate() does not raise for a well-formed linear flow."""
        flow = _linear_chain(5)
        flow.validate()  # must not raise
