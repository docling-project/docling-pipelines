# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ai_pr_leak_check",
    Path(__file__).resolve().parents[3] / ".github/scripts/ai_pr_leak_check.py",
)
assert SPEC is not None and SPEC.loader is not None
leak = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = leak
SPEC.loader.exec_module(leak)

KEY = "bobk_Zx81QmN3-aTe7vUy_P0LrWc9HdSf2Kg"  # pragma: allowlist secret


def _spaced(value: str) -> str:
    return " ".join(value)


@pytest.mark.parametrize(
    "payload",
    [
        KEY,
        KEY[::-1],
        KEY.encode().hex(),
        KEY.encode().hex().upper(),
        base64.b64encode(KEY.encode()).decode(),
        base64.urlsafe_b64encode(KEY.encode()).decode().rstrip("="),
        _spaced(KEY),
        f"{KEY[:12]}\n{KEY[12:]}",
        f"{KEY[:10]} - {KEY[10:20]} - {KEY[20:]}",
    ],
)
def test_plain_and_encoded_copies_are_found(payload: str) -> None:
    assert leak.contains_secret(text=f"Summary: ok. {payload} More text.", key=KEY)


@pytest.mark.parametrize("prefix", ["", "a", "ab", "abc", "Summary: "])
def test_base64_is_found_at_every_alignment(prefix: str) -> None:
    encoded = base64.b64encode(f"{prefix}{KEY}.tail".encode()).decode()
    assert leak.contains_secret(text=encoded, key=KEY)


def test_ordinary_text_and_short_keys_do_not_match() -> None:
    assert not leak.contains_secret(text="The PR fixes the flow validator. See #12.", key=KEY)
    assert not leak.contains_secret(text="short", key="short")
    assert not leak.contains_secret(text="anything", key="")


def test_main_reads_the_key_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text('{"summary": "ok"}', encoding="utf-8")
    monkeypatch.setenv("BOB_API_KEY", KEY)
    assert leak.main(["--file", str(result)]) == 0

    result.write_text('{"summary": "' + base64.b64encode(KEY.encode()).decode() + '"}', encoding="utf-8")
    assert leak.main(["--file", str(result)]) == 1

    # No key (a run without a secret) or no file: nothing to check.
    monkeypatch.delenv("BOB_API_KEY")
    assert leak.main(["--file", str(result)]) == 0
    monkeypatch.setenv("BOB_API_KEY", KEY)
    assert leak.main(["--file", str(tmp_path / "missing.json")]) == 0
