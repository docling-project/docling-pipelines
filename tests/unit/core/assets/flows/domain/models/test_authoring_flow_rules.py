# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the validation rules of AuthoringOperator and AuthoringFlow.

Covers the individual rule branches that the broader authoring-flow tests do not
reach: name/dependency format checks, branch reference resolution, branching and
merge operator constraints, global field checks, cycle detection traversal and
the small lookup/serialisation helpers.
"""

import pytest

from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow, AuthoringOperator, FlowSource
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException


def _op(name, op_type="noop", depends_on=None, config=None):
    """Build an AuthoringOperator with sensible defaults."""
    return AuthoringOperator(type=op_type, name=name, depends_on=depends_on or [], config=config or {})


def _validate_op(operator, *, names=None, operator_map=None):
    """Run AuthoringOperator.validate with explicit name set and operator map."""
    names = set(names) if names is not None else set()
    return operator.validate(all_operator_names=names, operator_map=operator_map or {})


def _flow_errors(flow):
    """Return the error message raised by AuthoringFlow.validate()."""
    with pytest.raises(FlowInvalidDataException) as exc_info:
        flow.validate()
    return str(exc_info.value)


class TestOperatorNameAndDependencyRules:
    """Tests for name format and dependency checks in AuthoringOperator.validate."""

    def test_whitespace_only_name_reports_spaces_and_empty(self):
        """A whitespace-only name is reported both as containing spaces and as empty."""
        errors = _validate_op(_op("   "))

        assert "Operator name '   ' cannot contain spaces" in errors
        assert "Operator name cannot be empty or whitespace" in errors

    def test_blank_dependency_is_reported_and_skipped(self):
        """Empty and whitespace-only dependency entries are reported without further lookup."""
        errors = _validate_op(_op("b", depends_on=["", "  "]), names={"b"})

        assert errors == ["Empty dependency in operator 'b'", "Empty dependency in operator 'b'"]

    def test_blank_dependency_on_unnamed_operator_uses_placeholder(self):
        """The error for an unnamed operator falls back to 'unnamed'."""
        errors = _validate_op(AuthoringOperator(type="noop", depends_on=[""]))

        assert errors == ["Empty dependency in operator 'unnamed'"]

    def test_valid_regular_dependency_produces_no_error(self):
        """A dependency on an existing operator name is accepted."""
        assert _validate_op(_op("b", depends_on=["a"]), names={"a", "b"}) == []


class TestBranchReferenceRules:
    """Tests for 'operator.branch' dependency resolution."""

    def test_unknown_operator_in_branch_reference(self):
        """A branch reference to an operator that is not in the flow is rejected."""
        errors = _validate_op(_op("b", depends_on=["missing.left"]), names={"b"})

        assert errors == ["Dependency 'missing' not found in flow (referenced in 'b')"]

    def test_empty_branch_name_in_reference(self):
        """A branch reference with an empty branch part is rejected."""
        branching = _op("br", op_type="branching", config={"branches": {"left": {}}})
        errors = _validate_op(_op("b", depends_on=["br. "]), names={"br", "b"}, operator_map={"br": branching})

        assert errors == ["Branch name cannot be empty in reference 'br. '"]

    def test_reference_to_non_branching_operator(self):
        """Referencing a branch on an operator that is not a branching operator is rejected."""
        source = _op("src", op_type="noop")
        errors = _validate_op(_op("b", depends_on=["src.left"]), names={"src", "b"}, operator_map={"src": source})

        assert errors == [
            "Operator 'src' is not a branching operator, cannot reference branch 'left' (in operator 'b')"
        ]

    def test_unknown_branch_lists_available_branches(self):
        """Referencing a branch the branching operator does not define lists the available ones."""
        branching = _op("br", op_type="branching", config={"branches": {"left": {}, "right": {}}})
        errors = _validate_op(_op("b", depends_on=["br.middle"]), names={"br", "b"}, operator_map={"br": branching})

        assert errors == [
            "Branch 'middle' not found in branching operator 'br'. "
            "Available branches: ['left', 'right'] (referenced in 'b')"
        ]

    def test_known_branch_is_accepted(self):
        """Referencing an existing branch produces no error."""
        branching = _op("br", op_type="branching", config={"branches": {"left": {}}})

        assert _validate_op(_op("b", depends_on=["br.left"]), names={"br", "b"}, operator_map={"br": branching}) == []

    def test_branching_operator_with_non_dict_config_is_not_inspected(self):
        """When the referenced branching operator's config is not a dict, branch lookup is skipped."""
        branching = AuthoringOperator(type="branching", name="br", config=["not", "a", "dict"])  # type: ignore[arg-type]

        errors = _validate_op(_op("b", depends_on=["br.left"]), names={"br", "b"}, operator_map={"br": branching})

        assert errors == []

    def test_branching_operator_with_non_dict_branches_is_not_inspected(self):
        """Non-dict branches are reported by the branching operator itself, not by the referencing operator."""
        branching = _op("br", op_type="branching", config={"branches": ["left"]})

        errors = _validate_op(_op("b", depends_on=["br.left"]), names={"br", "b"}, operator_map={"br": branching})

        assert errors == []

    def test_operator_known_by_name_but_missing_from_map_is_accepted(self):
        """If the name set knows the operator but the map does not, no type/branch check is possible."""
        assert _validate_op(_op("b", depends_on=["br.left"]), names={"br", "b"}, operator_map={}) == []


class TestBranchingAndMergeOperatorRules:
    """Tests for branching- and merge-operator specific constraints."""

    def test_branching_operator_with_non_dict_config_has_no_branching_errors(self):
        """A branching operator whose config is not a dict only gets the generic config error."""
        operator = AuthoringOperator(type="branching", name="br", config="oops")  # type: ignore[arg-type]

        assert _validate_op(operator, names={"br"}) == ["Operator config must be a dictionary (operator: br)"]

    def test_branching_operator_without_branches(self):
        """A branching operator must define at least one branch."""
        errors = _validate_op(_op("br", op_type="branching", config={"branches": {}}), names={"br"})

        assert errors == ["Branching operator 'br' must define at least one branch"]

    def test_branching_operator_with_non_dict_branches(self):
        """Branches given as a list are rejected."""
        errors = _validate_op(_op("br", op_type="branching", config={"branches": ["a"]}), names={"br"})

        assert errors == ["Branching operator 'br' must have 'branches' as a dictionary"]

    @pytest.mark.parametrize(
        ("branch_name", "expected"),
        [
            ("has space", ["Branch name 'has space' cannot contain spaces (operator: br)"]),
            ("", ["Branch name cannot be empty (operator: br)"]),
            ("a.b", ["Branch name 'a.b' cannot contain '.' (operator: br)"]),
            ("ok_name", []),
        ],
    )
    def test_branch_name_format(self, branch_name, expected):
        """Branch names must be non-empty and contain neither spaces nor the branch separator."""
        operator = _op("br", op_type="branching", config={"branches": {branch_name: {}}})

        assert _validate_op(operator, names={"br"}) == expected

    def test_merge_operator_needs_two_inputs(self):
        """A merge operator with fewer than two inputs is rejected."""
        errors = _validate_op(_op("m", op_type="merge", depends_on=["a"]), names={"a", "m"})

        assert errors == ["Merge operator 'm' must have at least 2 inputs in depends_on"]

    def test_merge_operator_with_two_inputs_is_accepted(self):
        """A merge operator with two inputs passes the merge check."""
        assert _validate_op(_op("m", op_type="merge", depends_on=["a", "b"]), names={"a", "b", "m"}) == []


class TestFlowGlobalFieldRules:
    """Tests for flow-level field validation in AuthoringFlow.validate."""

    def test_invalid_flow_source_is_reported(self):
        """A flow_source outside the FlowSource enum is reported with the valid choices."""
        flow = AuthoringFlow(flow_name="f", flow=[_op("a")], flow_source="bogus")  # type: ignore[arg-type]

        message = _flow_errors(flow)

        assert "Invalid flow_source 'bogus'. Must be one of: api, cli, programmatic, ui" in message

    def test_flow_name_too_long(self):
        """Flow names longer than 255 characters are rejected."""
        message = _flow_errors(AuthoringFlow(flow_name="x" * 256, flow=[_op("a")]))

        assert "Flow name cannot exceed 255 characters" in message

    def test_flow_name_at_limit_is_accepted(self):
        """A flow name of exactly 255 characters is accepted."""
        AuthoringFlow(flow_name="x" * 255, flow=[_op("a")]).validate()

    def test_description_too_long(self):
        """Descriptions longer than 2000 characters are rejected."""
        message = _flow_errors(AuthoringFlow(flow_name="f", flow=[_op("a")], description="d" * 2001))

        assert "Flow description cannot exceed 2000 characters" in message

    def test_disable_validation_must_be_boolean(self):
        """global_config.disable_validation given as a string is rejected with its type."""
        flow = AuthoringFlow(flow_name="f", flow=[_op("a")], global_config={"disable_validation": "true"})

        message = _flow_errors(flow)

        assert "global_config.disable_validation must be a boolean (true/false), got str: true" in message

    def test_disable_validation_boolean_is_accepted(self):
        """A boolean disable_validation flag is accepted."""
        AuthoringFlow(flow_name="f", flow=[_op("a")], global_config={"disable_validation": True}).validate()


class TestFlowCycleDetection:
    """Tests for the DFS traversal in AuthoringFlow cycle detection."""

    def test_operator_already_visited_via_dependency_is_not_revisited(self):
        """An operator listed after its dependent is reached through the DFS and skipped later."""
        flow = AuthoringFlow(flow_name="f", flow=[_op("b", depends_on=["a"]), _op("a")])

        assert flow._check_circular_dependencies() == []
        flow.validate()

    def test_cycle_behind_branch_reference_is_detected(self):
        """Branch references are resolved to their operator when building the dependency graph."""
        flow = AuthoringFlow(
            flow_name="f",
            flow=[
                _op("root"),
                _op("br", op_type="branching", depends_on=["x"], config={"branches": {"left": {}}}),
                _op("x", depends_on=["br.left"]),
            ],
        )

        errors = flow._check_circular_dependencies()

        assert len(errors) == 1
        assert errors[0].startswith("Circular dependency detected involving operator")


class TestFlowHelpers:
    """Tests for AuthoringFlow lookup and serialisation helpers."""

    def test_get_operator_by_name_returns_match(self):
        """get_operator_by_name returns the operator with the given name."""
        second = _op("b")
        flow = AuthoringFlow(flow_name="f", flow=[_op("a"), second])

        assert flow.get_operator_by_name(name="b") is second

    def test_get_operator_by_name_returns_none_when_missing(self):
        """get_operator_by_name returns None for an unknown name."""
        flow = AuthoringFlow(flow_name="f", flow=[_op("a")])

        assert flow.get_operator_by_name(name="zzz") is None

    def test_to_dict_round_trips_through_from_dict(self):
        """to_dict produces the authoring format that from_dict reads back."""
        flow = AuthoringFlow(
            flow_name="f",
            flow=[_op("a", config={"k": 1}), _op("b", depends_on=["a"])],
            description="desc",
            global_config={"doc_column": "content"},
            flow_source=FlowSource.API,
        )

        data = flow.to_dict()

        assert data == {
            "flow_name": "f",
            "description": "desc",
            "flow_source": FlowSource.API,
            "flow": [
                {"name": "a", "type": "noop", "depends_on": [], "config": {"k": 1}},
                {"name": "b", "type": "noop", "depends_on": ["a"], "config": {}},
            ],
            "global_config": {"doc_column": "content"},
        }
        assert AuthoringFlow.from_dict(data=data) == flow

    def test_from_dict_keeps_non_string_flow_source(self):
        """A FlowSource member passed in from_dict is used as-is."""
        flow = AuthoringFlow.from_dict(data={"flow_name": "f", "flow": [], "flow_source": FlowSource.UI})

        assert flow.flow_source is FlowSource.UI
