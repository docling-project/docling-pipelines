# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""AST-based static validation for custom operator source files."""

import ast
import enum
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.exceptions.docpipe_exceptions import CustomOperatorInvalidDataException

# Names an operator file may use inside ``get_metadata()`` that are resolved by reading our own constants, never by
# running the uploaded file. Anything else is treated as not statically known.
_RESOLVABLE_CONSTANT_ROOTS: dict[str, Any] = {
    "OperatorConstants": OperatorConstants,
    "AttributeDataTypes": AttributeDataTypes,
    "OperatorCategory": OperatorCategory,
    "DocpipeConstants": DocpipeConstants,
}

_UNRESOLVED: Any = object()


def _resolve_attribute_chain(*, node: ast.Attribute) -> Any:
    """Resolve ``Root.a.b`` against an allowlisted constants class; ``_UNRESOLVED`` if it is anything else."""
    names: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        names.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id not in _RESOLVABLE_CONSTANT_ROOTS:
        return _UNRESOLVED
    value: Any = _RESOLVABLE_CONSTANT_ROOTS[current.id]
    for name in reversed(names):
        if name.startswith("_"):
            return _UNRESOLVED
        try:
            value = getattr(value, name)
        except AttributeError:
            return _UNRESOLVED
    if isinstance(value, enum.Enum):
        value = value.value
    return value if isinstance(value, (str, int, float, bool)) or value is None else _UNRESOLVED


def _resolve_static_value(*, node: ast.expr) -> Any:
    """Evaluate a literal-only expression without executing anything; ``_UNRESOLVED`` if it is not one.

    Supports constants, lists, tuples, sets, dicts (entries that cannot be resolved are dropped) and attribute chains
    on a small allowlist of docpipe constants classes.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Attribute):
        return _resolve_attribute_chain(node=node)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        items = [_resolve_static_value(node=element) for element in node.elts]
        return _UNRESOLVED if any(item is _UNRESOLVED for item in items) else items
    if isinstance(node, ast.Dict):
        resolved: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            if key_node is None:  # ``**other`` cannot be expanded statically
                continue
            key = _resolve_static_value(node=key_node)
            value = _resolve_static_value(node=value_node)
            if key is _UNRESOLVED or value is _UNRESOLVED or not isinstance(key, str):
                continue
            resolved[key] = value
        return resolved
    return _UNRESOLVED


def _extract_static_metadata(*, function: ast.FunctionDef) -> dict[str, Any]:
    """Read the dict literal returned by ``get_metadata()``; entries that are not statically known are omitted."""
    returned = [
        stmt.value for stmt in ast.walk(function) if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict)
    ]
    if not returned:
        return {}
    resolved = _resolve_static_value(node=returned[-1])
    return resolved if isinstance(resolved, dict) else {}


class ASTOperatorValidator(ast.NodeVisitor):
    """Static AST visitor to validate custom operator source files without executing them."""

    def __init__(self) -> None:
        self.operator_classes: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Inspect class definitions in the AST."""
        # Check if the class inherits from AbstractOperator (by name or attribute)
        is_abstract_operator_subclass = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "AbstractOperator":
                is_abstract_operator_subclass = True
                break
            if isinstance(base, ast.Attribute) and base.attr == "AbstractOperator":
                is_abstract_operator_subclass = True
                break

        if not is_abstract_operator_subclass:
            self.generic_visit(node)
            return

        class_info: dict[str, Any] = {
            "name": node.name,
            "has_transform": False,
            "has_get_metadata_static": False,
            "short_name": None,
            "category": None,
            "owner": None,
            "metadata": {},
        }

        # Inspect class body
        for stmt in node.body:
            # Check class attributes (short_name, category, owner)
            # Handles both plain assignments (`x = ...`) and annotated assignments (`x: T = ...`)
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                if isinstance(stmt, ast.Assign):
                    targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
                    value: ast.expr = stmt.value
                else:  # ast.AnnAssign
                    if stmt.value is None or not isinstance(stmt.target, ast.Name):
                        continue
                    targets = [stmt.target]
                    value = stmt.value

                for target in targets:
                    if target.id == "short_name":
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            class_info["short_name"] = value.value
                        else:
                            raise CustomOperatorInvalidDataException(
                                message="short_name must be a string literal",
                                field_name="short_name",
                            )
                    elif target.id == "category":
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            class_info["category"] = value.value
                        elif isinstance(value, ast.Attribute):
                            class_info["category"] = value.attr
                        else:
                            raise CustomOperatorInvalidDataException(
                                message="category must be a string literal or OperatorCategory enum member",
                                field_name="category",
                            )
                    elif target.id == DocpipeConstants.OWNER_ATTRIBUTE:
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            class_info["owner"] = value.value
                        elif isinstance(value, ast.Attribute) and value.attr == "OWNER_CUSTOM":
                            class_info["owner"] = DocpipeConstants.OWNER_CUSTOM
                        else:
                            raise CustomOperatorInvalidDataException(
                                message=f"owner must be '{DocpipeConstants.OWNER_CUSTOM}'",
                                field_name="owner",
                            )

            # Check functions (transform, get_metadata)
            elif isinstance(stmt, ast.FunctionDef):
                if stmt.name == "transform":
                    class_info["has_transform"] = True
                elif stmt.name == "get_metadata":
                    class_info["metadata"] = _extract_static_metadata(function=stmt)
                    # Check for @staticmethod decorator
                    has_staticmethod = any(
                        (isinstance(dec, ast.Name) and dec.id == "staticmethod")
                        or (isinstance(dec, ast.Attribute) and dec.attr == "staticmethod")
                        for dec in stmt.decorator_list
                    )
                    if has_staticmethod:
                        class_info["has_get_metadata_static"] = True

        self.operator_classes.append(class_info)
        self.generic_visit(node)


def validate_operator_file(*, operator_file_path: Path) -> dict[str, Any]:
    """Validate a custom operator Python file statically using AST.

    Args:
        operator_file_path: Path to the Python file to validate

    Returns:
        Dictionary containing extracted metadata: {"short_name": ..., "category": ..., "class_name": ...}

    Raises:
        CustomOperatorInvalidDataException: If the operator file does not meet contract requirements
    """
    described = describe_operator_file(operator_file_path=operator_file_path)
    return {
        "short_name": described["short_name"],
        "category": described["category"],
        "class_name": described["class_name"],
    }


def describe_operator_file(*, operator_file_path: Path) -> dict[str, Any]:
    """Validate an operator file with AST and return the descriptor of its operator class, without importing it.

    The descriptor is what the platform registers for an untrusted operator instead of the imported class.

    Args:
        operator_file_path: Path to the Python file to describe

    Returns:
        ``{"short_name", "category", "class_name", "metadata"}``. ``metadata`` is the dict literal returned by
        ``get_metadata()`` restricted to the entries that are statically known (for example the declared
        ``secret_fields``); it is empty when ``get_metadata()`` builds its result dynamically.

    Raises:
        CustomOperatorInvalidDataException: If the operator file does not meet contract requirements
    """
    if not operator_file_path.exists():
        raise CustomOperatorInvalidDataException(
            message=f"Operator file does not exist: {operator_file_path}",
            field_name="operator_file",
        )

    try:
        source_code = operator_file_path.read_text(encoding="utf-8")
        tree = ast.parse(source_code, filename=operator_file_path.name)
    except SyntaxError as e:
        raise CustomOperatorInvalidDataException(
            message=f"Syntax error in operator file: {e.msg} (line {e.lineno})",
            field_name="operator_file",
        ) from e
    except Exception as e:
        raise CustomOperatorInvalidDataException(
            message=f"Failed to read or parse operator file: {e}",
            field_name="operator_file",
        ) from e

    validator = ASTOperatorValidator()
    validator.visit(tree)

    if not validator.operator_classes:
        raise CustomOperatorInvalidDataException(
            message="No class inheriting from AbstractOperator found in operator file",
            field_name="operator_file",
        )

    if len(validator.operator_classes) > 1:
        class_names = [c["name"] for c in validator.operator_classes]
        raise CustomOperatorInvalidDataException(
            message=f"Multiple operator classes found ({', '.join(class_names)}). Exactly one is allowed.",
            field_name="operator_file",
        )

    op_info = validator.operator_classes[0]

    # Validate short_name
    if not op_info["short_name"]:
        raise CustomOperatorInvalidDataException(
            message=f"Operator class '{op_info['name']}' must define 'short_name' as a non-empty string literal",
            field_name="short_name",
        )

    # Validate category
    if not op_info["category"]:
        raise CustomOperatorInvalidDataException(
            message=f"Operator class '{op_info['name']}' must define 'category' class attribute",
            field_name="category",
        )

    # Validate category value against OperatorCategory
    valid_categories = {c.value for c in OperatorCategory}
    if op_info["category"] not in valid_categories and op_info["category"] not in [c.name for c in OperatorCategory]:
        raise CustomOperatorInvalidDataException(
            message=f"Invalid category '{op_info['category']}'. Must be one of: {', '.join(sorted(valid_categories))}",
            field_name="category",
        )

    # Normalize category value
    category_val = (
        op_info["category"]
        if op_info["category"] in valid_categories
        else getattr(OperatorCategory, op_info["category"]).value
    )

    # Validate owner
    if op_info["owner"] != DocpipeConstants.OWNER_CUSTOM:
        raise CustomOperatorInvalidDataException(
            message=(
                f"Operator class '{op_info['name']}' must set owner='{DocpipeConstants.OWNER_CUSTOM}', "
                f"got '{op_info['owner']}'"
            ),
            field_name="owner",
        )

    # Validate required methods
    if not op_info["has_transform"]:
        raise CustomOperatorInvalidDataException(
            message=f"Operator class '{op_info['name']}' must implement 'transform' method",
            field_name="transform",
        )

    if not op_info["has_get_metadata_static"]:
        raise CustomOperatorInvalidDataException(
            message=f"Operator class '{op_info['name']}' must implement 'get_metadata' as a @staticmethod",
            field_name="get_metadata",
        )

    return {
        "short_name": op_info["short_name"],
        "category": category_val,
        "class_name": op_info["name"],
        "metadata": op_info["metadata"],
    }
