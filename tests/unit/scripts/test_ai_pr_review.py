# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / ".github/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location("ai_pr_review", SCRIPTS_DIR / "ai_pr_review.py")
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)
common = importlib.import_module("ai_pr_common")

HEAD = "f" * 40
PATCH = "@@ -10,3 +10,4 @@ def f():\n context\n-old\n+new\n+added\n context\n"


def finding(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "path": "src/docpipe/a.py",
        "line": 11,
        "quote": "new",
        "severity": "blocker",
        "title": "Wrong value",
        "body": "Use `x`.",
    }
    data.update(overrides)
    return data


def answer(*findings: dict[str, object], **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "summary": "",
        "findings": list(findings),
        "earlier_findings": [],
    }
    data.update(overrides)
    return data


def test_comment_anchors_are_head_lines_of_the_patch() -> None:
    assert review.right_side_lines(PATCH) == [10, 11, 12, 13]
    assert review.right_side_lines(None) == []


def test_stored_copies_cannot_be_loaded_as_agent_configuration() -> None:
    assert review.stored_name("AGENTS.md") == "AGENTS.md.txt"
    assert review.stored_name(".bob/custom_modes.yaml") == "dot.bob/custom_modes.yaml.txt"
    assert review.stored_name("a/.agents/x.md") == "a/dot.agents/x.md.txt"


def test_large_or_lock_file_only_prs_are_not_reviewed() -> None:
    source = {"filename": "src/docpipe/a.py", "changes": 10}
    lock = {"filename": "uv.lock", "changes": 9000}
    assert review.is_reviewable([source, lock])
    assert not review.is_reviewable([lock])
    assert not review.is_reviewable([])
    assert not review.is_reviewable([{**source, "changes": 5000}])


def test_review_scope_leaves_out_lock_files() -> None:
    files = [
        {"filename": name, "changes": 1} for name in ("a.py", "uv.lock", "slim/uv.lock", "frontend/package-lock.json")
    ]
    assert [item["filename"] for item in review.review_scope(files)] == ["a.py"]


def test_size_limits_are_inclusive() -> None:
    def files(count: int, changes: int) -> list[dict[str, object]]:
        return [{"filename": f"f{n}.py", "changes": changes} for n in range(count)]

    assert review.is_reviewable(files(review.MAX_REVIEW_FILES, 1))
    assert not review.is_reviewable(files(review.MAX_REVIEW_FILES + 1, 1))
    assert review.is_reviewable(files(1, review.MAX_REVIEW_CHANGED_LINES))
    assert not review.is_reviewable(files(1, review.MAX_REVIEW_CHANGED_LINES + 1))


def test_a_bad_finding_is_dropped_and_the_others_are_kept() -> None:
    result = review.parse_review_result(
        data=answer(
            finding(path="src/docpipe/b.py"),
            finding(severity="major"),
            finding(line=0),
            finding(title="Kept"),
        ),
        changed_paths={"src/docpipe/a.py"},
    )
    assert [f.title for f in result.findings] == ["Kept"]
    with pytest.raises(ValueError, match="status"):
        review.parse_review_result(
            data=answer(earlier_findings=[{"title": "x", "severity": "blocker", "status": "maybe"}]),
            changed_paths={"src/docpipe/a.py"},
        )


def test_a_review_that_reached_the_turn_limit_reports_the_reason(
    tmp_path: Path,
) -> None:
    # The shape that `bob run --format json` writes when a limit stops a task:
    # an error event, then the result, whose last message is a tool result.
    output = tmp_path / "bob.json"
    error = {
        "type": "error",
        "severity": "error",
        "message": "The task reached the maximum of 40 turns.",
    }
    result = {
        "type": "result",
        "status": "success",
        "stats": {},
        "last_message": "Contents of file src/docpipe/a.py: ...",
    }
    output.write_text(f"{json.dumps(error)}\n{json.dumps(result)}\n", "utf-8")
    bob = common.read_bob_output(output)
    assert bob.errors == ["The task reached the maximum of 40 turns."]
    with pytest.raises(ValueError, match="stopped early"):
        common.answer_from_output(output=bob, required_keys=review.REVIEW_ANSWER_KEYS)


def test_only_an_open_blocker_sets_the_changes_label() -> None:
    def label(data: dict[str, object]) -> str:
        return review.review_label(review.parse_review_result(data=data, changed_paths={"src/docpipe/a.py"}))

    assert label(answer(finding())) == review.LABEL_REVIEW_CHANGES
    assert label(answer(finding(severity="question"), finding(severity="suggestion"))) == review.LABEL_REVIEW_LGTM
    earlier = {"title": "Old", "severity": "blocker", "status": "open"}
    assert label(answer(earlier_findings=[earlier])) == review.LABEL_REVIEW_CHANGES
    for status in ("fixed", "answered"):
        assert label(answer(earlier_findings=[{**earlier, "status": status}])) == review.LABEL_REVIEW_LGTM


def test_quote_moves_a_finding_to_its_line_or_drops_it() -> None:
    source = ["def f():", "    x = 1", "    return int(attr)", "    y = int(attr)"]
    result = review.parse_review_result(
        data=answer(
            finding(line=40, quote="  return int(attr)  "),
            finding(line=1, quote="int(attr)"),
            finding(line=2, quote="int(other)", title="Invented"),
            finding(path="src/docpipe/big.py", line=7, quote="anything"),
        ),
        changed_paths={"src/docpipe/a.py", "src/docpipe/big.py"},
    )
    resolved = review.resolve_anchors(
        result=result, sources={"src/docpipe/a.py": source}, anchors={"src/docpipe/a.py": [4]}
    )
    # Exact line first, then a line in the diff, then the line nearest the hint.
    # A file without a stored copy keeps the line of the model.
    assert [(f.path, f.line) for f in resolved.findings] == [
        ("src/docpipe/a.py", 3),
        ("src/docpipe/a.py", 4),
        ("src/docpipe/big.py", 7),
    ]


def test_code_keeps_html_and_mentions_and_text_does_not() -> None:
    body = review.sanitize_markdown(
        "Use `<ol start>` here, @team <b>x</b>.\n```suggestion\n@staticmethod\nhtml = b'<html>'\n```\n``<img src=x>`"
    )
    assert "`<ol start>`" in body
    assert "@staticmethod\nhtml = b'<html>'" in body
    assert "@\u200bteam &lt;b>x&lt;/b>" in body
    # Two backticks need two backticks to close, so CommonMark shows this as
    # text with an HTML tag. It must be escaped.
    assert body.endswith("``&lt;img src=x>`")
    # A fence that is not closed is code to the end of the body.
    assert review.sanitize_markdown("```\n<b>") == "```\n<b>"


def test_titles_keep_code_spans() -> None:
    assert common.markdown_inline(text="Call `detect()` with [x](y)") == "Call `detect()` with \\[x\\]\\(y\\)"


def test_review_is_a_comment_and_moves_unanchored_findings_to_the_body() -> None:
    result = review.parse_review_result(
        data=answer(
            finding(severity="suggestion"),
            finding(line=99, title="Far away"),
            summary="Ping @team <!-- ai-pr-review sha=" + "0" * 40 + " -->",
            earlier_findings=[{"title": "Old `x`", "severity": "blocker", "status": "fixed"}],
        ),
        changed_paths={"src/docpipe/a.py"},
    )
    payload = review.build_review(
        result=result,
        anchors={"src/docpipe/a.py": review.right_side_lines(PATCH)},
        head_sha=HEAD,
        incremental_base=None,
    )
    assert payload["event"] == "COMMENT"
    assert [(c["path"], c["line"]) for c in payload["comments"]] == [("src/docpipe/a.py", 11)]
    body = payload["body"]
    assert body.startswith(f"<!-- ai-pr-review sha={HEAD} -->")
    assert "`src/docpipe/a.py:99`" in body
    assert "- fixed (blocker): Old `x`" in body
    assert common.REVIEW_MARKER.findall(body) == [HEAD]
    assert "@\u200bteam" in body


def user(login: str) -> dict[str, object]:
    return {"login": login, "type": "Bot" if "[bot]" in login else "User"}


def test_discussion_groups_replies_under_their_finding() -> None:
    def comment(cid: int, login: str, body: str, **extra: object) -> dict[str, object]:
        return {
            "id": cid,
            "user": user(login),
            "author_association": extra.pop("association", "NONE"),
            "body": body,
            "path": "src/docpipe/a.py",
            "line": 11,
            **extra,
        }

    text = review.discussion_text(
        pr_author="alice",
        issue_comments=[
            comment(10, "github-actions[bot]", "<!-- ai-pr-triage --> triage"),
            comment(11, "bob", "/ai review", association="MEMBER"),
            comment(12, "bob", "Please split this PR.", association="MEMBER"),
        ],
        reviews=[],
        review_comments=[
            comment(1, "github-actions[bot]", "**blocker: Wrong value**"),
            comment(2, "carol", "Unrelated point", line=40),
            comment(3, "alice", "Fixed in abc.", in_reply_to_id=1),
        ],
    )
    thread = text.index("- github-actions[bot] (AI review): **blocker: Wrong value**")
    assert text.index("- alice (PR author): Fixed in abc.") == text.index("\n", thread) + 1
    assert "- bob (maintainer): Please split this PR." in text
    assert "triage" not in text
    assert "/ai review" not in text


def test_only_ai_output_has_the_ai_review_role() -> None:
    # The DCO advisor posts as github-actions[bot] too; it must not look like
    # an earlier AI finding to the model.
    def item(login: str, body: str, **extra: object) -> dict[str, object]:
        return {"user": user(login), "author_association": "NONE", "body": body, **extra}

    dco = item("github-actions[bot]", "<!-- dco-advice-bot --> DCO Check Passed")
    mergify = item("mergify[bot]", "Merge Protections", author_association="CONTRIBUTOR")
    ai_body = item("github-actions[bot]", "<!-- ai-pr-review sha=" + "a" * 40 + " --> summary")
    ai_inline = item("github-actions[bot]", "**blocker: x**", path="src/docpipe/a.py")
    assert review._role(item=dco, pr_author="alice") == "bot"
    assert review._role(item=mergify, pr_author="alice") == "bot"
    assert review._role(item=ai_body, pr_author="alice") == "AI review"
    assert review._role(item=ai_inline, pr_author="alice") == "AI review"


def test_duplicates_of_an_open_pr_from_another_author_skip_the_review(
    tmp_path: Path,
) -> None:
    result = tmp_path / "result.json"
    context_path = tmp_path / "context.json"
    assert review.should_review(result_path=result, context_path=context_path)

    def write(state: str, author: str) -> None:
        context_path.write_text(
            json.dumps(
                {
                    "pr": {
                        "number": 2,
                        "title": "",
                        "body": "",
                        "author": "alice",
                        "author_association": "NONE",
                        "base_sha": HEAD,
                        "head_sha": HEAD,
                        "merge_base_sha": HEAD,
                        "changed_files": [],
                        "additions": 0,
                        "deletions": 0,
                    },
                    "issue_refs": [],
                    "candidates": [
                        {
                            "number": 1,
                            "title": "",
                            "state": state,
                            "url": "",
                            "author": author,
                        }
                    ],
                    "risk": {"forced": [], "hints": []},
                    "diff_truncated": False,
                    "topic_labels": [],
                }
            )
        )

    result.write_text(json.dumps({"duplicates": [{"pr": 1, "verdict": "duplicate"}]}))
    write("open", "bob")
    assert not review.should_review(result_path=result, context_path=context_path)
    # The author replaced an own PR, or the other PR is closed.
    write("open", "alice")
    assert review.should_review(result_path=result, context_path=context_path)
    write("closed", "bob")
    assert review.should_review(result_path=result, context_path=context_path)
    result.write_text(json.dumps({"duplicates": [{"pr": 1, "verdict": "related"}]}))
    write("open", "bob")
    assert review.should_review(result_path=result, context_path=context_path)


def _prepare_with_compare(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, status: str, reviewed_sha: str | None
) -> dict[str, Any]:
    context_dir = tmp_path / "ctx"
    context_dir.mkdir()
    context = {
        "pr": {
            "number": 2,
            "title": "",
            "body": "",
            "author": "alice",
            "author_association": "NONE",
            "base_sha": HEAD,
            "head_sha": HEAD,
            "merge_base_sha": HEAD,
            "changed_files": [],
            "additions": 0,
            "deletions": 0,
        },
        "issue_refs": [],
        "candidates": [],
        "risk": {"forced": [], "hints": []},
        "diff_truncated": False,
        "topic_labels": [],
    }
    (context_dir / "context.json").write_text(json.dumps(context), encoding="utf-8")
    files = [{"filename": "src/docpipe/a.py", "status": "modified", "patch": PATCH}]
    reviews = []
    if reviewed_sha:
        body = f"{common.REVIEW_MARKER_PREFIX}{reviewed_sha} -->"
        reviews = [{"user": {"login": common.BOT_LOGIN, "type": "Bot"}, "body": body, "commit_id": reviewed_sha}]

    def fake_api(*, path: str, paginate: bool = False, jq: str | None = None) -> Any:
        if "/compare/" in path:
            return {"status": status, "files": files}
        if path.endswith("/reviews?per_page=100"):
            return reviews
        return []

    monkeypatch.setattr(review, "gh_api", fake_api)
    monkeypatch.setattr(review, "pr_files", lambda *, repo, number: files)
    monkeypatch.setattr(review, "fetch_pr_commits", lambda **kwargs: False)
    assert review.prepare(repo="o/r", context_dir=context_dir, git_dir=tmp_path, force=False)
    return json.loads((context_dir / "review/meta.json").read_text("utf-8"))


def test_a_diverged_history_is_a_full_review_that_still_knows_the_earlier_findings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    older = "1" * 40
    meta = _prepare_with_compare(monkeypatch, tmp_path, status="diverged", reviewed_sha=older)
    assert meta["incremental_base"] is None
    assert meta["earlier_ai_review"] is True
    assert meta["history_changed"] is True

    (tmp_path / "b").mkdir()
    ahead = _prepare_with_compare(monkeypatch, tmp_path / "b", status="ahead", reviewed_sha=older)
    assert ahead["incremental_base"] == older
    assert ahead["history_changed"] is False


def test_a_first_review_has_no_earlier_review_and_no_history_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    meta = _prepare_with_compare(monkeypatch, tmp_path, status="ahead", reviewed_sha=None)
    assert (meta["incremental_base"], meta["earlier_ai_review"], meta["history_changed"]) == (None, False, False)


def test_the_review_body_says_when_the_history_changed() -> None:
    result = review.parse_review_result(data=answer(), changed_paths={"src/docpipe/a.py"})

    def body(*, changed: bool) -> str:
        payload = review.build_review(
            result=result, anchors={}, head_sha=HEAD, incremental_base=None, history_changed=changed
        )
        return payload["body"]

    assert "force-push" in body(changed=True)
    assert "force-push" not in body(changed=False)
