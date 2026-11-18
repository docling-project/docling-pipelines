"""Regression coverage for imports used by ExtractOperator hot paths."""

import ast
from pathlib import Path

SOURCE = Path(__file__).parents[4] / "src" / "docpipe" / "core" / "operators" / "extract" / "extract_operator.py"
HOT_PATH_METHODS = {
    "_write_streaming_progress",
    "_run_streaming_pipeline",
    "transform",
}


def _imported_modules(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.ImportFrom):
        return {node.module or ""}
    return {alias.name for alias in node.names}


def test_extract_hot_paths_do_not_repeat_imports() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    extract_operator = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExtractOperator"
    )
    methods = {
        node.name: node
        for node in extract_operator.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HOT_PATH_METHODS
    }

    assert methods.keys() == HOT_PATH_METHODS
    for method_name, method in methods.items():
        repeated_imports = [node for node in ast.walk(method) if isinstance(node, (ast.Import, ast.ImportFrom))]
        assert not repeated_imports, f"{method_name} repeats imports in its hot path"


def test_extract_operator_keeps_docling_imports_lazy_for_slim_installs() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    module_imports = {
        module
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for module in _imported_modules(node)
    }

    assert not {module for module in module_imports if module == "docling" or module.startswith("docling.")}
