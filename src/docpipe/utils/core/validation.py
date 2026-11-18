"""Validation utility functions."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID


def to_bool(value: Any) -> bool:
    """
    Return True only for the boolean True or for strings equal to 'true' after trimming surrounding whitespace and lowercasing.
    Returns False for all other inputs (including 'false', '1', 1, objects, None, etc.).

    Args:
        value: Value to convert to boolean

    Returns:
        True if value is boolean True or string "true" (case-insensitive), False otherwise
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() == "true":
        return True
    return False


def is_value_in_range(*, value: int | float, min_value: int | float, max_value: int | float) -> bool:
    """
    Check if a value is within the specified range (inclusive).

    Args:
        value: The value to check.
        min_value: The minimum value of the range (inclusive).
        max_value: The maximum value of the range (inclusive).

    Returns:
        bool: True if value is within [min_value, max_value], False otherwise.
    """
    return min_value <= value <= max_value


def is_date_time_as_per_format(date_time_str: str, date_time_format: str):
    """
    Check if a date string matches the specified format.

    Args:
        date_time_str: Input date in string format.
        date_time_format: date_time format which the input date_time string should follow.

    Returns:
        True - If the input date is a valid date and is as per the date_time_format
        False - If the input date is not a valid date or is not as per the date_time_format
    """
    try:
        datetime.strptime(date_time_str, date_time_format).replace(tzinfo=UTC)
        return True
    except ValueError:
        return False


def validate_uuid_format(value: str | None, field_name: str) -> str | None:
    """Validate that a string is in valid UUID format.

    Used across the application to validate UUID fields like flow_id, container_id,
    and other identifier fields that must conform to UUID standards.

    Args:
        value: The string value to validate (can be None for optional fields)
        field_name: Name of the field being validated (used in error messages)

    Returns:
        The validated UUID string unchanged, or None if input was None

    Raises:
        ValueError: If the value is not a valid UUID format, with a descriptive
            error message including the field name and an example UUID

    Examples:
        >>> validate_uuid_format("550e8400-e29b-41d4-a716-446655440000", "flow_id")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> validate_uuid_format(None, "flow_id")
        None
        >>> validate_uuid_format("invalid", "flow_id")
        ValueError: flow_id must be a valid UUID format, got 'invalid'...
    """
    if value is None:
        return None
    try:
        UUID(value)
        return value
    except (ValueError, AttributeError, TypeError) as e:
        msg = (
            f"{field_name} must be a valid UUID format, got '{value}'. Example: '550e8400-e29b-41d4-a716-446655440000'"
        )
        raise ValueError(msg) from e


def validate_container_kind(value: str | None) -> str | None:
    """Validate that container_kind is either 'project' or 'space'.

    Used to validate IBM Cloud container type fields. Ensures only valid
    container types are accepted for flow metadata.

    Args:
        value: The container kind value to validate (can be None for optional fields)

    Returns:
        The validated container kind unchanged, or None if input was None

    Raises:
        ValueError: If the value is not 'project' or 'space', with a descriptive
            error message explaining valid options

    Examples:
        >>> validate_container_kind("project")
        'project'
        >>> validate_container_kind("space")
        'space'
        >>> validate_container_kind(None)
        None
        >>> validate_container_kind("invalid")
        ValueError: container_kind must be 'project' or 'space', got 'invalid'...
    """
    if value is None:
        return None
    if value not in ["project", "space"]:
        msg = (
            f"container_kind must be 'project' or 'space', got '{value}'. "
            "Provide a valid container type or omit this field."
        )
        raise ValueError(msg)
    return value


def _validate_operator_type_format(operator_type: str) -> None:
    """Validate operator_type is a valid Python class path format.

    Args:
        operator_type: The operator type string to validate

    Raises:
        ValueError: If operator_type format is invalid
    """
    if not operator_type or not isinstance(operator_type, str):
        msg = "operator_type must be a non-empty string"
        raise ValueError(msg)

    # Check for valid Python identifier format (module.path.ClassName or simple_name)
    parts = operator_type.split(".")
    for part in parts:
        if not part or not (part[0].isalpha() or part[0] == "_"):
            msg = (
                f"operator_type '{operator_type}' contains invalid identifier '{part}'. "
                "Must be valid Python class path (e.g., 'ingest_source' or 'core.operators.IngestSource')"
            )
            raise ValueError(msg)


def _validate_single_dag_node(*, node: Any, idx: int, node_ids: set[str]) -> None:
    """Validate a single DAG node's structure and fields."""
    if not isinstance(node, dict):
        msg = f"node at index {idx} must be a dictionary, got {type(node).__name__}"
        raise ValueError(msg)

    if "id" not in node:
        msg = f"node at index {idx} is missing required field 'id'"
        raise ValueError(msg)

    node_id = node["id"]
    if not isinstance(node_id, str) or not node_id:
        msg = f"node at index {idx} has invalid 'id': must be a non-empty string"
        raise ValueError(msg)

    if node_id in node_ids:
        msg = f"duplicate node id '{node_id}' found at index {idx}"
        raise ValueError(msg)
    node_ids.add(node_id)

    operator_field = node.get("operator") or node.get("operator_type")
    if not operator_field:
        msg = f"node '{node_id}' at index {idx} is missing required field 'operator' or 'operator_type'"
        raise ValueError(msg)

    _validate_operator_type_format(operator_field)

    params = node.get("operator_params") or node.get("config")
    if params is not None and not isinstance(params, dict):
        msg = f"node '{node_id}' has invalid 'operator_params'/'config': must be a dictionary"
        raise ValueError(msg)


def _validate_dag_nodes(nodes: list[dict[str, Any]]) -> None:
    """Validate DAG nodes structure.

    Args:
        nodes: List of node dictionaries to validate

    Raises:
        ValueError: If nodes structure is invalid
    """
    if not isinstance(nodes, list):
        msg = f"nodes must be a list, got {type(nodes).__name__}"
        raise ValueError(msg)

    if not nodes:
        msg = "nodes list cannot be empty - at least one node is required"
        raise ValueError(msg)

    node_ids: set[str] = set()
    for idx, node in enumerate(nodes):
        _validate_single_dag_node(node=node, idx=idx, node_ids=node_ids)


def _validate_authoring_format(value: dict[str, Any]) -> None:
    """Validate authoring format structure.

    Performs basic structural validation to ensure the dictionary has the required
    shape for authoring format. Full domain validation happens later when converting
    to AuthoringFlow domain model.

    Args:
        value: The flow definition dictionary to validate

    Raises:
        ValueError: If authoring format structure is invalid
    """
    # Validate required 'flow_name' key
    if "flow_name" not in value:
        msg = (
            "Authoring format definition must contain 'flow_name' key. Example: {'flow_name': 'My Flow', 'flow': [...]}"
        )
        raise ValueError(msg)

    flow_name = value["flow_name"]
    if not isinstance(flow_name, str) or not flow_name.strip():
        msg = "flow_name must be a non-empty string"
        raise ValueError(msg)

    # Validate required 'flow' key (array of operators)
    if "flow" not in value:
        msg = "Authoring format definition must contain 'flow' key. Example: {'flow_name': 'My Flow', 'flow': [...]}"
        raise ValueError(msg)

    flow = value["flow"]
    if not isinstance(flow, list):
        msg = f"flow must be a list, got {type(flow).__name__}"
        raise ValueError(msg)

    if not flow:
        msg = "flow list cannot be empty - at least one operator is required"
        raise ValueError(msg)

    # Basic validation of operator structure
    for idx, operator in enumerate(flow):
        if not isinstance(operator, dict):
            msg = f"flow operator at index {idx} must be a dictionary, got {type(operator).__name__}"
            raise ValueError(msg)

        # Check for required keys (lightweight check)
        required_keys = ["type", "name", "config"]
        for key in required_keys:
            if key not in operator:
                msg = f"flow operator at index {idx} is missing required field '{key}'"
                raise ValueError(msg)


def _validate_elyra_format(value: dict[str, Any]) -> None:
    """Validate legacy Elyra pipeline format structure.

    Args:
        value: The flow definition dictionary to validate

    Raises:
        ValueError: If Elyra format is invalid
    """
    # Validate required Elyra fields
    if "pipelines" not in value:
        msg = (
            "Elyra format definition must contain 'pipelines' key. "
            "Example: {'doc_type': 'pipeline', 'pipelines': [...], 'primary_pipeline': '...'}"
        )
        raise ValueError(msg)

    pipelines = value["pipelines"]
    if not isinstance(pipelines, list):
        msg = f"pipelines must be a list, got {type(pipelines).__name__}"
        raise ValueError(msg)

    if not pipelines:
        msg = "pipelines list cannot be empty"
        raise ValueError(msg)

    # Validate primary_pipeline if present
    if "primary_pipeline" in value:
        primary = value["primary_pipeline"]
        if not isinstance(primary, str) or not primary:
            msg = "primary_pipeline must be a non-empty string"
            raise ValueError(msg)


def validate_flow_definition(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate flow definition structure with comprehensive structural validation.

    Performs deep validation of flow definitions used throughout the docpipe
    framework. This is a shared validator used by Flow domain models, DTOs, and API
    endpoints to ensure consistent validation across all layers.

    Validation includes:
    - Required top-level keys for authoring format (flow_name, flow array)
    - Required top-level keys for Elyra format (doc_type, pipelines)
    - Full validation for both formats

    Supported Formats:
    - Authoring format: {"flow_name": "...", "flow": [...], "global_config": {...}}
    - Elyra format: {"doc_type": "pipeline", "pipelines": [...], "primary_pipeline": "..."}

    Args:
        value: The flow definition dictionary to validate (can be None for optional fields)

    Returns:
        The validated definition dictionary unchanged, or None if input was None

    Raises:
        ValueError: If the definition structure is invalid, with specific error messages for:
            - Missing required keys (flow_name/flow for authoring, doc_type/pipelines for Elyra)
            - Invalid structure for authoring or Elyra formats

    Examples:
        >>> validate_flow_definition({"flow_name": "My Flow", "flow": [...]})
        {'flow_name': 'My Flow', 'flow': [...]}
        >>> validate_flow_definition({"doc_type": "pipeline", "pipelines": [...]})
        {'doc_type': 'pipeline', 'pipelines': [...]}
        >>> validate_flow_definition(None)
        None
        >>> validate_flow_definition({})
        ValueError: definition must contain either 'doc_type' (Elyra format) or 'flow_name' (Authoring format)
    """
    if value is None:
        return None

    if not isinstance(value, dict):
        msg = f"definition must be a dictionary, got {type(value).__name__}"
        raise ValueError(msg)

    # Determine format and validate accordingly
    has_flow_name = "flow_name" in value
    has_doc_type = "doc_type" in value

    if not has_flow_name and not has_doc_type:
        msg = (
            "definition must contain either 'doc_type' (Elyra format) or 'flow_name' (Authoring format). "
            "Examples:\n"
            "  Authoring: {'flow_name': 'My Flow', 'flow': [...]}\n"
            "  Elyra: {'doc_type': 'pipeline', 'pipelines': [...]}"
        )
        raise ValueError(msg)

    if has_flow_name:
        # Authoring format - validate structure
        _validate_authoring_format(value)
    elif has_doc_type:
        _validate_elyra_format(value)

    return value


def deduplicate_tags(value: list[str] | None, allow_none: bool = False) -> list[str] | None:
    """Remove duplicate tags while preserving insertion order.

    Used across the application to normalize tag lists in flow metadata and other
    tagged resources. Ensures tag uniqueness while maintaining the order in which
    tags were first encountered.

    Args:
        value: List of tags to deduplicate (can be None for optional fields)
        allow_none: If True, returns None when input is None. If False, returns empty list.
            Default is False for backward compatibility.

    Returns:
        Deduplicated list of tags preserving first occurrence order, or None/empty list
        based on allow_none parameter

    Raises:
        ValueError: If value is not a list or contains non-string elements, with
            descriptive error messages

    Examples:
        >>> deduplicate_tags(["a", "b", "a", "c"])
        ['a', 'b', 'c']
        >>> deduplicate_tags(None, allow_none=False)
        []
        >>> deduplicate_tags(None, allow_none=True)
        None
        >>> deduplicate_tags(["tag1", 123])
        ValueError: all tags must be strings, got int
    """
    if value is None:
        return None if allow_none else []

    if not isinstance(value, list):
        msg = f"tags must be a list, got {type(value).__name__}"
        raise ValueError(msg)

    seen = set()
    result = []
    for tag in value:
        if not isinstance(tag, str):
            msg = f"all tags must be strings, got {type(tag).__name__}"
            raise ValueError(msg)
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def validate_database_path(path: str, base_dir: str | None = None) -> str:
    """
    Validate database path for security and correctness.

    Ensures the path is safe and doesn't contain path traversal attempts.
    Resolves the path to its absolute form to prevent directory traversal attacks.

    Args:
        path: Database file path to validate
        base_dir: Optional base directory to restrict paths to

    Returns:
        Validated absolute path

    Raises:
        ValueError: If path is invalid or outside allowed directory

    Examples:
        >>> validate_database_path("data/docs.db")
        '/absolute/path/to/data/docs.db'
        >>> validate_database_path(":memory:")
        ':memory:'
        >>> validate_database_path("../../../etc/passwd")
        ValueError: Path traversal patterns (..) are not allowed
    """
    if not path or not isinstance(path, str) or not path.strip():
        msg = "Database path cannot be empty"
        raise ValueError(msg)

    # Allow in-memory databases
    if path == ":memory:":
        return path

    # Check for path traversal attempts before resolving
    if ".." in path:
        msg = "Path traversal patterns (..) are not allowed in database path"
        raise ValueError(msg)

    # Resolve to absolute path
    try:
        resolved_path = Path(path).resolve()
    except (OSError, RuntimeError) as e:
        msg = f"Invalid database path: {e}"
        raise ValueError(msg) from e

    # If base_dir is specified, ensure path is within it
    if base_dir:
        try:
            base_path = Path(base_dir).resolve()
            if not str(resolved_path).startswith(str(base_path)):
                msg = f"Database path must be within {base_dir}"
                raise ValueError(msg)
        except (OSError, RuntimeError) as e:
            msg = f"Invalid base directory: {e}"
            raise ValueError(msg) from e

    return str(resolved_path)
