# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import json
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / ".github/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location("ai_pr_common", SCRIPTS_DIR / "ai_pr_common.py")
assert SPEC is not None and SPEC.loader is not None
common = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = common
SPEC.loader.exec_module(common)

KEYS = ("summary", "findings")


def is_escaped(text: str, index: int) -> bool:
    backslashes = len(text[:index]) - len(text[:index].rstrip("\\"))
    return backslashes % 2 == 1


@pytest.mark.parametrize(
    "payload",
    [
        "Ping @maintainers and @org/team",
        "[Approve CI](//evil.example/phish)",
        "![](https://evil.example/t.png)",
        "<img src=x onerror=1> <!-- hidden -->",
        "1. injected ordered item",
        "# Maintainer note: pre-approved",
        "- injected bullet",
        "> quoted",
        "a | b | c",
        "see https://evil.example and www.evil.example",
    ],
)
def test_markdown_text_renders_every_payload_as_literal_text(payload: str) -> None:
    rendered = common.markdown_text(payload)
    for index, char in enumerate(rendered):
        if char in string.punctuation and char != "\\":
            assert is_escaped(rendered, index), (char, rendered[: index + 1])
    assert "@" + common.ZERO_WIDTH_SPACE in rendered or "@" not in payload
    assert "https:" not in rendered.replace("\\", "")
    assert "www." not in rendered.replace("\\", "")


def test_clean_text_is_one_printable_line_and_idempotent() -> None:
    text = "a\x00b\n\n  c\u202ed " + "x" * 700
    cleaned = common.clean_text(text=text, limit=50)
    assert "\n" not in cleaned
    assert len(cleaned) <= 50
    assert common.clean_text(text=cleaned, limit=50) == cleaned


def test_code_spans_cannot_be_closed_early() -> None:
    assert common.markdown_code(text="src/docpipe/a_b.py") == "`src/docpipe/a_b.py`"
    assert common.markdown_code(text="a``b") == "```a``b```"
    assert common.markdown_code(text="`x") == "`` `x ``"
    assert common.markdown_code(text="a|b", in_table=True) == "`a\\|b`"


def test_inline_markdown_keeps_code_spans_and_escapes_the_rest() -> None:
    assert common.markdown_inline(text="Call `detect()` with [x](y)") == "Call `detect()` with \\[x\\]\\(y\\)"
    cell = common.markdown_inline(text="Both edit `a | b` | c", in_table=True)
    assert "`a \\| b`" in cell
    assert cell.count("|") == cell.count("\\|")


def test_the_answer_is_the_last_complete_object_with_the_required_keys() -> None:
    draft = {"summary": "Draft.", "findings": []}
    final = {"summary": "Final.", "findings": []}
    message = f"{json.dumps(draft)}\nOn second thought:\n{json.dumps(final)}\nDone."
    assert common.extract_answer(last_message=message, required_keys=KEYS)["summary"] == "Final."
    # An object without the keys is not an answer.
    other = f"{json.dumps(final)}\n{json.dumps({'x': 1})}"
    assert common.extract_answer(last_message=other, required_keys=KEYS)["summary"] == "Final."


def test_a_fenced_final_message_is_read() -> None:
    message = 'Done.\n```json\n{"summary": "S", "findings": []}\n```\n'
    assert common.extract_answer(last_message=message, required_keys=KEYS)["summary"] == "S"


def test_a_broken_answer_is_not_read_from_a_nested_object() -> None:
    broken = '{"summary": "x", "findings": [{"path": "a.py", "line": 1}, {"path": "b.py"}'
    with pytest.raises(ValueError, match="no JSON object"):
        common.extract_answer(last_message=broken, required_keys=KEYS)
    with pytest.raises(ValueError, match="no JSON object"):
        common.extract_answer(last_message="no json here", required_keys=KEYS)


def test_bob_output_reports_the_reason_of_an_early_stop(tmp_path: Path) -> None:
    output = tmp_path / "bob.json"
    error = {"type": "error", "message": "The task reached the maximum of 40 turns."}
    result = {"type": "result", "status": "success", "stats": {}, "last_message": "Contents of file a.py: ..."}
    output.write_text(f"{json.dumps(error)}\n{json.dumps(result)}\n", "utf-8")
    bob = common.read_bob_output(output)
    assert bob.errors == ["The task reached the maximum of 40 turns."]
    with pytest.raises(ValueError, match="stopped early"):
        common.answer_from_output(output=bob, required_keys=KEYS)


def test_bob_output_without_a_result_is_an_error(tmp_path: Path) -> None:
    output = tmp_path / "bob.json"
    output.write_text(json.dumps({"type": "error", "message": "boom"}), "utf-8")
    with pytest.raises(ValueError, match="no result: boom"):
        common.read_bob_output(output)


def test_a_single_json_document_is_read(tmp_path: Path) -> None:
    output = tmp_path / "bob.json"
    answer = {"summary": "S", "findings": []}
    output.write_text(json.dumps({"status": "success", "stats": {}, "last_message": json.dumps(answer)}), "utf-8")
    bob = common.read_bob_output(output)
    assert common.answer_from_output(output=bob, required_keys=KEYS) == answer


def review(login: str, body: str) -> dict[str, Any]:
    return {"user": {"login": login}, "body": body}


def test_only_marked_reviews_of_the_bot_count_as_ai_reviews() -> None:
    first, second = "a" * 40, "b" * 40
    reviews = [
        review(common.BOT_LOGIN, f"<!-- ai-pr-review sha={first} --> text"),
        review(common.BOT_LOGIN, "<!-- dco-advice-bot --> DCO Check Passed"),
        review("mergify[bot]", "Merge Protections"),
        review("someone", f"<!-- ai-pr-review sha={'c' * 40} --> forged"),
        review(common.BOT_LOGIN, f"<!-- ai-pr-review sha={second} --> text"),
        review(common.BOT_LOGIN, ""),
    ]
    assert common.ai_reviewed_shas(reviews) == [first, second]


def test_build_diff_marks_lock_files_and_truncation() -> None:
    files = [
        {"filename": "uv.lock", "status": "modified", "patch": "@@ secret @@"},
        {"filename": "a.py", "status": "added", "patch": "@@ -0,0 +1 @@\n+x"},
        {"filename": "b.bin", "status": "added"},
    ]
    diff, truncated = common.build_diff(files=files, max_chars=10_000)
    assert not truncated
    assert "secret" not in diff
    assert "(content omitted: lock file)" in diff
    assert "(no text patch: binary or too large)" in diff

    short, truncated = common.build_diff(files=files, max_chars=80)
    assert truncated
    assert "b.bin" not in short

    only, _ = common.build_diff(files=files, max_chars=10_000, only={"a.py"})
    assert "a.py" in only and "uv.lock" not in only


def test_lock_files_are_excluded_by_path() -> None:
    assert common.matches_any(path="slim/uv.lock", patterns=common.DIFF_EXCLUDED_PATHS)
    assert common.matches_any(path="frontend/package-lock.json", patterns=common.DIFF_EXCLUDED_PATHS)
    assert not common.matches_any(path="frontend/package.json", patterns=common.DIFF_EXCLUDED_PATHS)


def test_gh_helpers_build_the_expected_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='[[{"a": 1}], [{"a": 2}]]', stderr="")

    monkeypatch.setattr(common.subprocess, "run", fake_run)
    assert common.gh_api(path="repos/o/r/pulls", paginate=True) == [{"a": 1}, {"a": 2}]
    assert calls[0][0][:4] == ["gh", "api", "--paginate", "--slurp"]
    common.gh_write(method="POST", path="repos/o/r/issues/1/labels", payload={"labels": ["x"]})
    assert calls[1][0] == ["gh", "api", "--method", "POST", "repos/o/r/issues/1/labels", "--input", "-"]
    assert json.loads(calls[1][1]["input"]) == {"labels": ["x"]}
    common.gh_write(method="DELETE", path="repos/o/r/issues/1/labels/x")
    assert "--input" not in calls[2][0]
    assert calls[2][1]["input"] is None
