"""Domain models for the simplified flow authoring format.

This module defines the user-friendly authoring model that allows users to define
flows without managing UUIDs, edges, and low-level DAG details.

Exception Handling:
The validate() method collects all validation errors and raises a single
FlowInvalidDataException containing all errors.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException


class FlowSource(StrEnum):
    """Source of flow creation.

    Indicates where the authoring flow was created from, which can be useful
    for tracking, analytics, and applying source-specific validation or processing.
    """

    API = "api"
    CLI = "cli"
    PROGRAMMATIC = "programmatic"
    UI = "ui"


@dataclass
class AuthoringOperator:
    """Domain model for an operator in the authoring format.

    Attributes:
        type: Operator type (e.g., 'ingest_source', 'extract_operator')
        name: Optional unique name for this operator instance
        depends_on: List of operator names this operator depends on
                   Supports dot notation for branch references (e.g., 'branch_op.branch_name')
        config: Operator-specific configuration parameters
    """

    type: str
    name: str | None = None
    depends_on: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, all_operator_names: set[str], operator_map: dict[str, "AuthoringOperator"]) -> list[str]:
        """Validate operator configuration.

        Args:
            all_operator_names: Set of all operator names in the flow for dependency validation
            operator_map: Dictionary mapping operator names to AuthoringOperator instances

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Validate type
        if not self.type or not self.type.strip():
            errors.append(f"Operator type cannot be empty (operator: {self.name or 'unnamed'})")

        # Validate name format (no branch separator or spaces)
        if self.name:
            if " " in self.name:
                errors.append(f"Operator name '{self.name}' cannot contain spaces")
            if not self.name.strip():
                errors.append("Operator name cannot be empty or whitespace")
            if OperatorConstants.Misc.BRANCH_SEPARATOR in self.name:
                errors.append(f"Operator name '{self.name}' cannot contain '{OperatorConstants.Misc.BRANCH_SEPARATOR}'")

        # Validate config is a dictionary
        if not isinstance(self.config, dict):
            errors.append(f"Operator config must be a dictionary (operator: {self.name or 'unnamed'})")

        # Validate dependencies
        for dep in self.depends_on:
            if not dep or not dep.strip():
                errors.append(f"Empty dependency in operator '{self.name or 'unnamed'}'")
                continue

            # Handle branch references (operator.branch)
            if OperatorConstants.Misc.BRANCH_SEPARATOR in dep:
                errors.extend(
                    self._validate_branch_reference(
                        dep=dep, all_operator_names=all_operator_names, operator_map=operator_map
                    )
                )
            else:
                # Regular operator dependency
                if dep not in all_operator_names:
                    errors.append(f"Dependency '{dep}' not found in flow (referenced in '{self.name or 'unnamed'}')")

        # Operator-specific validations
        errors.extend(self._validate_branching_operator())
        errors.extend(self._validate_merge_operator())

        return errors

    def _validate_branch_reference(
        self, *, dep: str, all_operator_names: set[str], operator_map: dict[str, "AuthoringOperator"]
    ) -> list[str]:
        """Validate a branch reference dependency (operator.branch)."""
        errors = []
        parts = dep.split(OperatorConstants.Misc.BRANCH_SEPARATOR, 1)
        if len(parts) != 2:
            errors.append(f"Invalid branch reference '{dep}' in operator '{self.name or 'unnamed'}'")
            return errors

        operator_name, branch_name = parts

        # Validate operator exists
        if operator_name not in all_operator_names:
            errors.append(f"Dependency '{operator_name}' not found in flow (referenced in '{self.name or 'unnamed'}')")
            return errors

        # Validate branch name is not empty
        if not branch_name.strip():
            errors.append(f"Branch name cannot be empty in reference '{dep}'")
            return errors

        # Validate that the referenced operator is actually a branching operator
        referenced_op = operator_map.get(operator_name)
        if referenced_op and referenced_op.type != OperatorConstants.Operators.BRANCHING:
            errors.append(
                f"Operator '{operator_name}' is not a branching operator, "
                f"cannot reference branch '{branch_name}' (in operator '{self.name or 'unnamed'}')"
            )
            return errors

        # Validate that the branch exists in the branching operator
        if referenced_op:
            if not isinstance(referenced_op.config, dict):
                return errors
            branches = referenced_op.config.get(OperatorConstants.Misc.BRANCHES, {})
            if not isinstance(branches, dict):
                # Branching-operator validation already reports non-dict branches.
                return errors
            if branch_name not in branches:
                available_branches = list(branches.keys())
                errors.append(
                    f"Branch '{branch_name}' not found in branching operator '{operator_name}'. "
                    f"Available branches: {available_branches} (referenced in '{self.name or 'unnamed'}')"
                )

        return errors

    def _validate_branching_operator(self) -> list[str]:
        """Validate branching operator specific requirements."""
        errors: list[str] = []
        if self.type != OperatorConstants.Operators.BRANCHING:
            return errors

        if not isinstance(self.config, dict):
            return errors

        branches = self.config.get(OperatorConstants.Misc.BRANCHES, {})
        if not isinstance(branches, dict):
            errors.append(
                f"Branching operator '{self.name}' must have '{OperatorConstants.Misc.BRANCHES}' as a dictionary"
            )
            return errors

        if not branches:
            errors.append(f"Branching operator '{self.name}' must define at least one branch")
            return errors

        # Validate each branch
        for branch_name, branch_config in branches.items():
            errors.extend(self._validate_branch(branch_name=branch_name, branch_config=branch_config))

        return errors

    def _validate_branch(self, *, branch_name: str, branch_config: Any) -> list[str]:
        """Validate a single branch configuration."""
        errors = []

        # Validate branch name format
        if " " in branch_name:
            errors.append(f"Branch name '{branch_name}' cannot contain spaces (operator: {self.name})")
        if not branch_name.strip():
            errors.append(f"Branch name cannot be empty (operator: {self.name})")
        if OperatorConstants.Misc.BRANCH_SEPARATOR in branch_name:
            errors.append(
                f"Branch name '{branch_name}' cannot contain '{OperatorConstants.Misc.BRANCH_SEPARATOR}' "
                f"(operator: {self.name})"
            )

        return errors

    def _validate_merge_operator(self) -> list[str]:
        """Validate merge operator specific requirements."""
        errors = []
        if self.type == OperatorConstants.Operators.MERGE:
            if len(self.depends_on) < 2:
                errors.append(f"Merge operator '{self.name}' must have at least 2 inputs in depends_on")
        return errors


@dataclass
class AuthoringFlow:
    """Domain model for the simplified flow authoring format.

    This represents the user-friendly format that will be compiled into
    the runtime DAG format.

    Attributes:
        flow_name: Name of the flow
        flow: Ordered list of operators
        description: Optional flow description
        global_config: Global configuration parameters
        flow_source: Source of flow creation (cli, programmatic, api, ui)
        flow_id: Optional user-provided flow identifier. When set, the compiler
                 preserves this value in the runtime DAG instead of generating
                 a new UUID.
    """

    flow_name: str
    flow: list[AuthoringOperator]
    description: str | None = None
    global_config: dict[str, Any] = field(default_factory=dict)
    flow_source: FlowSource = FlowSource.CLI
    flow_id: str | None = None

    def _validate_global_fields(self, *, errors: list[str]) -> None:
        """Validate flow_source, flow_name, description, and global_config fields."""
        if self.flow_source not in FlowSource:
            valid_sources = ", ".join([s.value for s in FlowSource])
            errors.append(f"Invalid flow_source '{self.flow_source}'. Must be one of: {valid_sources}")

        if not self.flow_name or not self.flow_name.strip():
            errors.append("Flow name cannot be empty")
        elif len(self.flow_name) > 255:
            errors.append("Flow name cannot exceed 255 characters")

        if self.description and len(self.description) > 2000:
            errors.append("Flow description cannot exceed 2000 characters")

        if OperatorConstants.Config.DISABLE_VALIDATION in self.global_config:
            disable_val = self.global_config[OperatorConstants.Config.DISABLE_VALIDATION]
            if not isinstance(disable_val, bool):
                errors.append(
                    f"global_config.disable_validation must be a boolean (true/false), "
                    f"got {type(disable_val).__name__}: {disable_val}"
                )

    def _collect_operator_map(self, *, errors: list[str]) -> tuple[set[str], dict[str, "AuthoringOperator"]]:
        """Build operator name set and map, appending errors for missing or duplicate names."""
        operator_names: set[str] = set()
        operator_map: dict[str, AuthoringOperator] = {}

        for idx, operator in enumerate(self.flow):
            if not operator.name:
                errors.append(f"Operator at position {idx} must have a name")
            elif operator.name in operator_names:
                errors.append(f"Duplicate operator name '{operator.name}' at position {idx}")
            else:
                operator_names.add(operator.name)
                operator_map[operator.name] = operator

        return operator_names, operator_map

    def validate(self) -> None:
        """Validate the entire authoring flow.

        Raises:
            FlowInvalidDataException: If validation fails. Contains all validation
                errors in the message for better user experience.
        """
        errors: list[str] = []

        self._validate_global_fields(errors=errors)

        # Validate flow is not empty
        if not self.flow or len(self.flow) == 0:
            raise FlowInvalidDataException(
                message="Flow must contain at least one operator", field_name=DocpipeConstants.FLOW
            )

        operator_names, operator_map = self._collect_operator_map(errors=errors)

        # Validate each operator
        for operator in self.flow:
            errors.extend(operator.validate(all_operator_names=operator_names, operator_map=operator_map))

        # Ensure at least one operator has no dependencies (entry point)
        if not any(len(op.depends_on) == 0 for op in self.flow):
            errors.append("Flow must have at least one operator with no dependencies (entry point)")

        errors.extend(self._check_circular_dependencies())

        if errors:
            error_message = "Authoring flow validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
            raise FlowInvalidDataException(message=error_message, field_name="flow")

    def _build_dependency_graph(self) -> dict[str, set[str]]:
        """Build a dependency graph mapping each operator name to its direct dependencies."""
        dependencies: dict[str, set[str]] = {}
        for operator in self.flow:
            if operator.name:
                deps = set()
                for dep in operator.depends_on:
                    if OperatorConstants.Misc.BRANCH_SEPARATOR in dep:
                        dep = dep.split(OperatorConstants.Misc.BRANCH_SEPARATOR, 1)[0]
                    deps.add(dep)
                dependencies[operator.name] = deps
        return dependencies

    @staticmethod
    def _has_cycle(*, node: str, dependencies: dict[str, set[str]], visited: set[str], rec_stack: set[str]) -> bool:
        """DFS-based cycle detection. Returns True if a cycle is reachable from node."""
        visited.add(node)
        rec_stack.add(node)

        for neighbor in dependencies.get(node, set()):
            if neighbor not in visited:
                if AuthoringFlow._has_cycle(
                    node=neighbor, dependencies=dependencies, visited=visited, rec_stack=rec_stack
                ):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    def _check_circular_dependencies(self) -> list[str]:
        """Check for circular dependencies in the flow.

        Returns:
            List of error messages for circular dependencies
        """
        errors: list[str] = []
        dependencies = self._build_dependency_graph()

        # Check for self-dependencies
        for op_name, deps in dependencies.items():
            if op_name in deps:
                errors.append(f"Operator '{op_name}' cannot depend on itself")

        visited: set[str] = set()
        for op_name in dependencies:
            if op_name not in visited:
                if AuthoringFlow._has_cycle(node=op_name, dependencies=dependencies, visited=visited, rec_stack=set()):
                    errors.append(f"Circular dependency detected involving operator '{op_name}'")
                    break

        return errors

    def get_operator_by_name(self, *, name: str) -> AuthoringOperator | None:
        """Get an operator by its name.

        Args:
            name: Name of the operator to find

        Returns:
            AuthoringOperator if found, None otherwise
        """
        for operator in self.flow:
            if operator.name == name:
                return operator
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert authoring flow to dictionary representation.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            DocpipeConstants.FLOW_NAME: self.flow_name,
            DocpipeConstants.DESCRIPTION: self.description,
            DocpipeConstants.FLOW_SOURCE: self.flow_source,
            DocpipeConstants.FLOW: [
                {
                    OperatorConstants.Misc.NAME: op.name,
                    OperatorConstants.Misc.TYPE: op.type,
                    OperatorConstants.Misc.DEPENDS_ON: op.depends_on,
                    OperatorConstants.Config.CONFIG: op.config,
                }
                for op in self.flow
            ],
            OperatorConstants.Config.GLOBAL_CONFIG: self.global_config,
        }

    @classmethod
    def from_dict(cls, *, data: dict[str, Any]) -> "AuthoringFlow":
        """Create AuthoringFlow from dictionary representation.

        Args:
            data: Dictionary containing authoring flow data

        Returns:
            AuthoringFlow instance
        """
        operators = []
        for i, op_data in enumerate(data.get(DocpipeConstants.FLOW, [])):
            if OperatorConstants.Misc.TYPE not in op_data:
                raise FlowInvalidDataException(
                    message=f"Operator at index {i} is missing required field 'type'.",
                    field_name=f"flow[{i}].type",
                )
            operators.append(
                AuthoringOperator(
                    type=op_data[OperatorConstants.Misc.TYPE],
                    name=op_data.get(OperatorConstants.Misc.NAME),
                    depends_on=op_data.get(OperatorConstants.Misc.DEPENDS_ON, []),
                    config=op_data.get(OperatorConstants.Config.CONFIG, {}),
                )
            )

        if DocpipeConstants.FLOW_NAME not in data:
            raise FlowInvalidDataException(
                message="Missing required field 'flow_name' in flow definition.",
                field_name=DocpipeConstants.FLOW_NAME,
            )

        # Parse flow_source, defaulting to CLI if not provided
        flow_source_str = data.get(DocpipeConstants.FLOW_SOURCE, FlowSource.CLI.value)
        flow_source = FlowSource(flow_source_str) if isinstance(flow_source_str, str) else flow_source_str

        return cls(
            flow_name=data[DocpipeConstants.FLOW_NAME],
            flow=operators,
            description=data.get(DocpipeConstants.DESCRIPTION),
            global_config=data.get(OperatorConstants.Config.GLOBAL_CONFIG, {}),
            flow_source=flow_source,
            flow_id=data.get(DocpipeConstants.FLOW_ID),
        )
