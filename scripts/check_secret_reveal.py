#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Static guard for secret handling (add-secret-management, task B.5).

Two rules, both enforced with the ``ast`` module so that renaming or aliasing cannot hide a violation:

1. **Reveal only in adapters.** A resolved secret is a ``SecretValue``. It may be revealed (``.reveal()``,
   ``reveal_value(...)``) only inside an adapter module, at the point where a client is built. The check fails on a
   call or an import of ``reveal`` or ``reveal_value`` outside the allowed modules, on ``getattr(x, "reveal")`` and
   ``operator.methodcaller("reveal")``, and on rebinding the function to another name (``alias = reveal_value``,
   ``from ... import reveal_value as alias``), which is how a re-export or wrapper would start.
2. **Credential-looking fields are declared.** A field of a configuration class whose name looks like a credential
   (``password``, ``*_key``, ``*_secret``, ``*_token``, ``credentials*``) must be listed in the class's
   ``SECRET_FIELDS`` or ``NO_REFERENCES``, or be tagged ``json_schema_extra={"sensitive": True}``. This complements
   the runtime inventory test, which covers operator-level metadata.

Usage::

    python scripts/check_secret_reveal.py [PATH ...]

With no paths, every ``*.py`` file under ``src/docpipe`` is checked.
"""

import ast
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src" / "docpipe"
SECRET_FIELDS_MODULE = SOURCE_ROOT / "core" / "operators" / "secret_fields.py"

REVEAL_NAMES: frozenset[str] = frozenset({"reveal", "reveal_value"})
REVEAL_MODULE_SUFFIX = "secrets.secret_value"

# Modules that may reveal, in addition to any module under an ``adapters`` directory.
#
# * ``secret_value.py`` defines the functions.
# * ``resolver.py`` registers the revealed value with the scrubber the moment it is resolved.
# * ``isolation/proxy.py`` hands the revealed values to an isolated operator's worker over its private pipe.
# * ``chunker.py`` builds its own docling-serve client; it has no adapter layer.
ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "src/docpipe/integrations/secrets/secret_value.py",
        "src/docpipe/integrations/secrets/resolver.py",
        "src/docpipe/core/orchestration/operator_loader/isolation/proxy.py",
        "src/docpipe/core/operators/functional/chunker.py",
    }
)

CONFIG_FILE_SUFFIXES: tuple[str, ...] = ("config.py",)


def _load_secret_fields() -> ModuleType:
    """Load ``secret_fields.py`` by path, so the check needs no installed package and imports nothing heavy."""
    spec = importlib.util.spec_from_file_location("_docpipe_secret_fields", SECRET_FIELDS_MODULE)
    if spec is None or spec.loader is None:
        msg = f"Cannot load {SECRET_FIELDS_MODULE}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _relative(path: Path) -> str:
    """Return the repository-relative POSIX path of ``path``."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_reveal_allowed(*, rel_path: str) -> bool:
    """Return True when a module may call ``reveal``: an adapter module or an allow-listed seam."""
    return rel_path in ALLOWED_FILES or "adapters" in Path(rel_path).parts


def _is_reveal_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in REVEAL_NAMES


def _reveal_findings(*, tree: ast.AST, rel_path: str, allowed: bool) -> list[str]:
    """Return the findings of rule 1 for one module."""
    findings: list[str] = []

    def add(node: ast.AST, message: str) -> None:
        findings.append(f"{rel_path}:{getattr(node, 'lineno', 0)}: {message}")

    for node in ast.walk(tree):
        # Rebinding or re-exporting is flagged everywhere, including adapters.
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(REVEAL_MODULE_SUFFIX):
            for alias in node.names:
                if alias.name not in REVEAL_NAMES:
                    continue
                if alias.asname:
                    add(node, f"'{alias.name}' imported under another name ('{alias.asname}'); import it unaliased")
                elif not allowed:
                    add(node, f"'{alias.name}' imported outside an adapter module")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            if value is not None and (
                _is_reveal_attribute(value) or (isinstance(value, ast.Name) and value.id in REVEAL_NAMES)
            ):
                add(node, "reveal function bound to another name")
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                (isinstance(func, ast.Name) and func.id in {"getattr", "methodcaller"})
                or (isinstance(func, ast.Attribute) and func.attr in {"getattr", "methodcaller"})
            ) and any(isinstance(arg, ast.Constant) and arg.value in REVEAL_NAMES for arg in node.args):
                add(node, "reveal looked up by name; call it directly in an adapter module")
            elif not allowed and (
                (isinstance(func, ast.Name) and func.id in REVEAL_NAMES) or _is_reveal_attribute(func)
            ):
                add(node, "reveal called outside an adapter module")
    return findings


def _literal_names(node: ast.AST | None) -> set[str]:
    """Return the string literals of a tuple, list, or set expression; empty for anything else."""
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _is_sensitive_tagged(node: ast.AnnAssign) -> bool:
    """Return True when a field carries ``json_schema_extra={"sensitive": True}``."""
    value = node.value
    if not isinstance(value, ast.Call):
        return False
    for keyword in value.keywords:
        if keyword.arg == "json_schema_extra" and isinstance(keyword.value, ast.Dict):
            for key, val in zip(keyword.value.keys, keyword.value.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "sensitive"
                    and isinstance(val, ast.Constant)
                    and val.value is True
                ):
                    return True
    return False


def _config_class_findings(*, tree: ast.AST, rel_path: str, is_credential_looking: Callable[..., bool]) -> list[str]:
    """Return the findings of rule 2 for one configuration module."""
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        declared: set[str] = set()
        for stmt in node.body:
            target = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target = stmt.targets[0].id
            if target in {"SECRET_FIELDS", "NO_REFERENCES", "SECRET_FIELD_ALIASES"} and isinstance(
                stmt, ast.AnnAssign | ast.Assign
            ):
                declared |= _literal_names(stmt.value)
        declared_roots = {name.split(".", 1)[0] for name in declared}
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            name = stmt.target.id
            if name.isupper() or name.startswith("_") or not is_credential_looking(name=name):
                continue
            if name in declared_roots or _is_sensitive_tagged(stmt):
                continue
            findings.append(
                f"{rel_path}:{stmt.lineno}: field '{name}' of {node.name} looks like a credential but is neither in "
                "SECRET_FIELDS or NO_REFERENCES nor tagged json_schema_extra={'sensitive': True}"
            )
    return findings


def check_file(*, path: Path, is_credential_looking: Callable[..., bool]) -> list[str]:
    """Return every finding for one Python file."""
    rel_path = _relative(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{rel_path}:{exc.lineno or 0}: cannot parse: {exc.msg}"]
    findings = _reveal_findings(tree=tree, rel_path=rel_path, allowed=is_reveal_allowed(rel_path=rel_path))
    in_config_scope = rel_path.startswith("src/docpipe/core/operators/") and (
        rel_path.endswith(CONFIG_FILE_SUFFIXES) or "adapters" in Path(rel_path).parts
    )
    if in_config_scope:
        findings += _config_class_findings(tree=tree, rel_path=rel_path, is_credential_looking=is_credential_looking)
    return findings


def main(argv: list[str]) -> int:
    """Check the given files, or every module under ``src/docpipe``; return 1 when there is a finding."""
    secret_fields = _load_secret_fields()
    paths = [Path(arg) for arg in argv] or sorted(SOURCE_ROOT.rglob("*.py"))
    findings: list[str] = []
    for path in paths:
        if path.suffix == ".py" and "src/docpipe/" in path.resolve().as_posix():
            findings += check_file(path=path, is_credential_looking=secret_fields.is_credential_looking)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} secret-handling finding(s). See scripts/check_secret_reveal.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
