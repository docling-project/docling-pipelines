# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the secret-handling AST guard (add-secret-management, task B.5)."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_secret_reveal.py"
OPERATORS = "src/docpipe/core/operators"


@pytest.fixture(scope="module")
def guard() -> Any:
    spec = importlib.util.spec_from_file_location("check_secret_reveal", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check(guard: Any, tmp_path: Path, *, rel: str, source: str) -> list[str]:
    """Write ``source`` under a fake repo-relative path and run the guard on it."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    secret_fields = guard._load_secret_fields()
    # Report findings under the fake relative path.
    original = guard._relative
    guard._relative = lambda path: rel
    try:
        return guard.check_file(path=target, is_credential_looking=secret_fields.is_credential_looking)
    finally:
        guard._relative = original


ADAPTER = f"{OPERATORS}/ingest/adapters/outbound/sources/x/adapter.py"
OPERATOR = f"{OPERATORS}/functional/some_operator.py"
CONFIG = f"{OPERATORS}/ingest/adapters/outbound/sources/x/config.py"
IMPORT = "from docpipe.integrations.secrets.secret_value import reveal_value\n"


class TestRevealOnlyInAdapters:
    def test_adapter_module_may_reveal(self, guard, tmp_path):
        assert _check(guard, tmp_path, rel=ADAPTER, source=IMPORT + "def f(c):\n    return reveal_value(c)\n") == []

    def test_method_call_in_adapter_is_allowed(self, guard, tmp_path):
        assert _check(guard, tmp_path, rel=ADAPTER, source="def f(v):\n    return v.reveal()\n") == []

    def test_operator_module_calling_reveal_value_fails(self, guard, tmp_path):
        findings = _check(guard, tmp_path, rel=OPERATOR, source=IMPORT + "def f(c):\n    return reveal_value(c)\n")
        assert any("imported outside an adapter module" in f for f in findings)
        assert any("called outside an adapter module" in f for f in findings)

    def test_operator_module_calling_reveal_method_fails(self, guard, tmp_path):
        findings = _check(guard, tmp_path, rel=OPERATOR, source="def f(v):\n    return v.reveal()\n")
        assert len(findings) == 1
        assert "called outside an adapter module" in findings[0]

    @pytest.mark.parametrize("rel", [ADAPTER, OPERATOR])
    def test_getattr_lookup_fails_everywhere(self, guard, tmp_path, rel):
        findings = _check(guard, tmp_path, rel=rel, source='def f(v):\n    return getattr(v, "reveal")()\n')
        assert any("looked up by name" in f for f in findings)

    @pytest.mark.parametrize("rel", [ADAPTER, OPERATOR])
    def test_methodcaller_lookup_fails_everywhere(self, guard, tmp_path, rel):
        source = 'import operator\n\ndef f(v):\n    return operator.methodcaller("reveal")(v)\n'
        assert any("looked up by name" in f for f in _check(guard, tmp_path, rel=rel, source=source))

    def test_aliased_import_fails_even_in_an_adapter(self, guard, tmp_path):
        source = "from docpipe.integrations.secrets.secret_value import reveal_value as rv\n"
        findings = _check(guard, tmp_path, rel=ADAPTER, source=source)
        assert any("another name" in f for f in findings)

    @pytest.mark.parametrize("source", ["alias = reveal_value\n", "alias = value.reveal\n"])
    def test_rebinding_fails_even_in_an_adapter(self, guard, tmp_path, source):
        assert any("bound to another name" in f for f in _check(guard, tmp_path, rel=ADAPTER, source=source))

    def test_allow_listed_seam_may_reveal(self, guard, tmp_path):
        rel = "src/docpipe/integrations/secrets/resolver.py"
        assert _check(guard, tmp_path, rel=rel, source="def f(v):\n    return v.reveal()\n") == []

    def test_reveal_named_constants_do_not_trip_the_check(self, guard, tmp_path):
        source = 'DECLARED_FIELDS_KEY = "secret_fields"\nDECLARED_BY_PROVIDER_KEY = "secret_fields_by_provider"\n'
        assert _check(guard, tmp_path, rel=OPERATOR, source=source) == []


class TestCredentialLookingFieldsAreDeclared:
    def test_undeclared_credential_field_fails(self, guard, tmp_path):
        source = "class C:\n    api_key: str | None = None\n"
        findings = _check(guard, tmp_path, rel=CONFIG, source=source)
        assert len(findings) == 1
        assert "'api_key'" in findings[0]

    @pytest.mark.parametrize(
        "source",
        [
            'class C:\n    SECRET_FIELDS = ("api_key",)\n    api_key: str | None = None\n',
            'class C:\n    NO_REFERENCES = ("api_key",)\n    api_key: str | None = None\n',
            'class C:\n    SECRET_FIELD_ALIASES = ("api_key",)\n    api_key: str | None = None\n',
            'class C:\n    api_key: str = Field(..., json_schema_extra={"sensitive": True})\n',
        ],
    )
    def test_declared_credential_field_passes(self, guard, tmp_path, source):
        assert _check(guard, tmp_path, rel=CONFIG, source=source) == []

    def test_non_credential_field_passes(self, guard, tmp_path):
        assert _check(guard, tmp_path, rel=CONFIG, source="class C:\n    bucket: str | None = None\n") == []

    def test_dotted_declaration_covers_its_root(self, guard, tmp_path):
        source = 'class C:\n    SECRET_FIELDS = ("credentials.token",)\n    credentials: dict | None = None\n'
        assert _check(guard, tmp_path, rel=CONFIG, source=source) == []


def test_repository_passes_the_guard(guard):
    """The checked-in source tree has no finding (this is what the pre-commit hook and CI step run)."""
    assert guard.main([]) == 0
