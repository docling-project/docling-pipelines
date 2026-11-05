# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib
import json
import string
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / ".github/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
triage = importlib.import_module("ai_pr_triage")
common = importlib.import_module("ai_pr_common")

REPO = "docling-project/docling-pipelines"
HEAD = "b" * 40


def make_context(**overrides: object) -> Any:
    data: dict[str, object] = {
        "pr": {
            "number": 10,
            "title": "fix: x",
            "body": "",
            "author": "someone",
            "author_association": "CONTRIBUTOR",
            "base_sha": "a" * 40,
            "head_sha": HEAD,
            "merge_base_sha": "c" * 40,
            "changed_files": ["src/docpipe/x.py"],
            "additions": 1,
            "deletions": 1,
        },
        "issue_refs": [],
        "candidates": [
            {"number": 7, "title": "fix x too", "state": "open", "url": ""},
        ],
        "risk": {"forced": [], "hints": []},
        "diff_truncated": False,
        "topic_labels": [],
    }
    data.update(overrides)
    return common.TriageContext.from_dict(data)


def answer(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "summary": "The PR fixes x.",
        "duplicates": [{"pr": 7, "verdict": "duplicate", "reason": "Same fix."}],
        "ci_safety": {"verdict": "safe", "concerns": []},
        "topics": [],
    }
    data.update(overrides)
    return data


def parse(data: dict[str, object], allowed: set[int] | None = None) -> Any:
    return triage.parse_triage_result(data, allowed_prs=allowed or {7})


def test_issue_refs_ignore_own_number_other_repos_and_anchors() -> None:
    text = (
        "Fixes #12 and #10. See https://github.com/docling-project/docling-pipelines/issues/34,"
        " https://github.com/docling-project/docling/issues/56 and docs/page#78. Again #12."
    )
    assert triage.extract_issue_refs(text=text, repo=REPO, own_number=10) == [12, 34]


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/scripts/ai_pr_triage.py",
        "tests/conftest.py",
        "tests/sub/conftest.py",
        "conftest.py",
        "pytest.ini",
        "pyproject.toml",
        "slim/pyproject.toml",
        "uv.lock",
        "slim/uv.lock",
        "hatch_build.py",
        "setup.py",
        "Makefile",
        ".pre-commit-config.yaml",
        "scripts/run.py",
        "frontend/lint-hook.sh",
        "docker/all-in-one-deployment/Dockerfile",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/vite.config.ts",
        "CODEOWNERS",
        "evil.pth",
        "sitecustomize.py",
        "AGENTS.md",
        "CLAUDE.md",
        ".agents/x.md",
        ".claude/x.md",
        ".codex/x.md",
        ".bob/custom_modes.yaml",
        "lib/native.so",
    ],
)
def test_sensitive_paths_force_care(path: str) -> None:
    report = triage.assess_risk([{"filename": path, "status": "modified"}])
    assert [f.path for f in report.forced] == [path]


@pytest.mark.parametrize(
    "path",
    [
        "src/docpipe/core/operators/functional/chunker.py",
        "src/docpipe/integrations/litellm/client.py",
        "tests/unit/core/test_x.py",
        "tests/data/sample.json",
        "docs/guides/FOO.md",
        "frontend/src/App.tsx",
        "sample_flows/flow.json",
    ],
)
def test_ordinary_paths_are_not_forced(path: str) -> None:
    assert triage.assess_risk([{"filename": path, "status": "modified"}]).forced == []


def test_a_rename_from_a_sensitive_path_is_forced_and_hints_only_flag_added_lines() -> None:
    files = [
        {
            "filename": "src/docpipe/new.py",
            "status": "renamed",
            "previous_filename": "AGENTS.md",
        },
        {
            "filename": "src/docpipe/core/x.py",
            "status": "modified",
            "patch": "@@ -1,2 +1,2 @@\n-import subprocess\n+x = eval(data)\n context",
        },
    ]
    report = triage.assess_risk(files)
    assert [f.path for f in report.forced] == ["AGENTS.md"]
    assert [(h.path, h.kind) for h in report.hints] == [("src/docpipe/core/x.py", "dynamic code execution")]


def test_overlap_needs_intersecting_hunks_or_many_shared_files() -> None:
    ours = [
        {"filename": "src/docpipe/a.py", "patch": "@@ -10,5 +10,6 @@\n"},
        {"filename": "uv.lock", "patch": "@@ -1,3 +1,3 @@\n"},
    ]
    near = [{"filename": "src/docpipe/a.py", "patch": "@@ -17,2 +17,3 @@\n"}]
    far = [
        {"filename": "src/docpipe/a.py", "patch": "@@ -200,2 +200,3 @@\n"},
        {"filename": "uv.lock", "patch": "@@ -1,3 +1,3 @@\n"},
    ]
    assert triage.compare_files(ours=ours, theirs=near) == (["src/docpipe/a.py"], 1)
    shared, overlaps = triage.compare_files(ours=ours, theirs=far)
    assert (shared, overlaps) == (["src/docpipe/a.py"], 0)
    assert not triage.is_overlap_candidate(shared_files=shared, overlapping_hunks=overlaps)


def test_noise_files_never_count_as_shared() -> None:
    noise = ["uv.lock", "slim/uv.lock", "pyproject.toml", "CHANGELOG.md", "frontend/package-lock.json", "a/__init__.py"]
    files = [{"filename": path, "patch": "@@ -1 +1 @@\n"} for path in noise]
    assert triage.compare_files(ours=files, theirs=files) == ([], 0)


def test_answer_with_unknown_pr_or_verdict_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown PR"):
        parse(answer(duplicates=[{"pr": 99, "verdict": "duplicate"}]))
    with pytest.raises(ValueError, match="ci_safety"):
        parse(answer(ci_safety={"verdict": "approve", "concerns": []}))


def test_answer_is_read_from_fenced_final_message() -> None:
    message = "Done.\n```json\n" + json.dumps(answer()) + "\n```"
    result = parse(common.extract_answer(last_message=message))
    assert result.ci_verdict == "safe"
    assert result.duplicates[0].verdict == "duplicate"


PAYLOADS = (
    "[Approve CI](//evil.example/phish)",
    "\\[Approve\\](//evil.example)",
    "![](https://evil.example/t.png)",
    "~~~ hide the verdict",
    "# Maintainer note: pre-approved",
    "<img src=x> <!-- c -->",
    "a | b | c",
    "see https://evil.example and www.evil.example",
)


def _is_escaped(text: str, index: int) -> bool:
    backslashes = len(text[:index]) - len(text[:index].rstrip("\\"))
    return backslashes % 2 == 1


def test_model_text_is_literal_in_the_comment() -> None:
    text = " ".join(PAYLOADS) + " Ping @maintainers " + string.punctuation
    rendered = common.markdown_text(text)
    for index, char in enumerate(rendered):
        if char in string.punctuation and char != "\\":
            assert _is_escaped(rendered, index), (char, rendered[: index + 1])
    assert "@\u200bmaintainers" in rendered
    assert "https:" not in rendered.replace("\\", "")
    assert "www." not in rendered.replace("\\", "")

    result = parse(
        answer(
            summary="# Approved\n\n[Approve](//evil.example)",
            duplicates=[{"pr": 7, "verdict": "duplicate", "reason": "x | y | z"}],
            ci_safety={
                "verdict": "needs-care",
                "concerns": [{"path": "a`b.py", "reason": "~~~"}],
            },
        )
    )
    comment = triage.render_comment(context=make_context(), result=result, labels={triage.LABEL_CI_NEEDS_CARE})
    lines = comment.splitlines()
    assert "\\# Approved \\[Approve\\]\\(\\/\\/evil\\.example\\)" in lines
    assert "- ``a`b.py``: \\~\\~\\~" in lines
    row = next(line for line in lines if line.startswith("| #7 "))
    assert row.count("|") - row.count("\\|") == 5


def test_model_code_span_cannot_be_closed_early() -> None:
    assert common.markdown_code(text="src/docpipe/a_b.py") == "`src/docpipe/a_b.py`"
    assert common.markdown_code(text="a``b") == "```a``b```"
    assert common.markdown_code(text="`x") == "`` `x ``"


def test_the_answer_is_the_last_complete_object_with_the_answer_keys() -> None:
    draft, final = answer(summary="Draft."), answer(summary="Final.")
    message = f"{json.dumps(draft)}\nOn second thought:\n{json.dumps(final)}\nDone."
    keys = triage.TRIAGE_ANSWER_KEYS
    assert common.extract_answer(last_message=message, required_keys=keys)["summary"] == "Final."
    # A broken answer must not be read from one of its nested objects.
    broken = '{"summary": "x", "ci_safety": {"verdict": "safe", "concerns": []'
    with pytest.raises(ValueError, match="no JSON object"):
        common.extract_answer(last_message=broken, required_keys=keys)


def test_comment_keeps_code_spans_and_table_cells() -> None:
    result = parse(
        answer(
            summary="Fixes `_to_rgb` for [x](//evil.example).",
            duplicates=[{"pr": 7, "verdict": "related", "reason": "Both edit `a | b`."}],
        )
    )
    comment = triage.render_comment(context=make_context(), result=result, labels={triage.LABEL_CI_SAFE})
    lines = comment.splitlines()
    assert "Fixes `_to_rgb` for \\[x\\]\\(\\/\\/evil\\.example\\)\\." in lines
    row = next(line for line in lines if line.startswith("| #7 "))
    assert "`a \\| b`" in row
    assert row.count("|") - row.count("\\|") == 5


def test_review_labels_of_an_older_commit_are_stale() -> None:
    current = {triage.REVIEW_LABELS[0], triage.LABEL_CI_SAFE}
    older = "a" * 40
    assert triage.stale_review_labels(current=current, reviewed_shas=[older, HEAD], head_sha=HEAD) == set()
    stale = triage.stale_review_labels(current=current, reviewed_shas=[HEAD, older], head_sha=HEAD)
    assert stale == {triage.REVIEW_LABELS[0]}
    assert triage.stale_review_labels(current=current, reviewed_shas=[], head_sha=HEAD) == {triage.REVIEW_LABELS[0]}


def test_deterministic_findings_override_a_safe_model_verdict() -> None:
    context = make_context(risk={"forced": [{"path": "uv.lock", "reason": "deps"}], "hints": []})
    result = parse(answer())
    assert triage.decide_labels(context=context, result=result) == {
        triage.LABEL_CI_NEEDS_CARE,
        triage.LABEL_DUPLICATE,
    }
    assert triage.decide_labels(context=make_context(), result=None) == set()


def test_a_closed_candidate_is_never_a_duplicate() -> None:
    context = make_context(candidates=[{"number": 7, "title": "", "state": "closed", "url": ""}])
    result = parse(answer())
    assert triage.effective_verdicts(context=context, result=result) == {7: "related"}
    assert triage.LABEL_DUPLICATE not in triage.decide_labels(context=context, result=result)
    comment = triage.render_comment(context=context, result=result, labels={triage.LABEL_CI_SAFE})
    assert "<details>" in comment
    assert "Possible duplicates" not in comment

    merged = make_context(candidates=[{"number": 7, "title": "", "state": "merged", "url": ""}])
    assert triage.effective_verdicts(context=merged, result=result) == {7: "duplicate"}
    assert triage.effective_verdicts(context=merged, result=None) == {}


def test_stored_result_round_trips_through_validation_in_publish() -> None:
    result = parse(answer(topics=["security"]))
    stored = json.loads(json.dumps(triage.asdict(result)))
    assert parse(triage._result_to_answer(stored)) == result


def test_comment_shows_duplicates_collapses_related_and_hides_unrelated() -> None:
    candidates = [{"number": n, "title": "", "state": "open", "url": ""} for n in (7, 8, 9)]
    result = parse(
        answer(
            duplicates=[
                {"pr": 7, "verdict": "duplicate", "reason": "Same fix."},
                {"pr": 8, "verdict": "related", "reason": "Same file."},
                {"pr": 9, "verdict": "unrelated", "reason": "No."},
            ]
        ),
        {7, 8, 9},
    )
    comment = triage.render_comment(
        context=make_context(candidates=candidates), result=result, labels={triage.LABEL_CI_SAFE}
    )
    assert comment.startswith(common.COMMENT_MARKER)
    visible, collapsed = comment.split("<details>")
    assert "| #7 |" in visible
    assert "| #8 |" in collapsed
    assert "#9" not in comment


def test_comment_states_failed_analysis() -> None:
    comment = triage.render_comment(context=make_context(), result=None, labels=set())
    assert "did not finish" in comment
    assert "| #7 | open |" in comment


def test_model_topics_must_come_from_the_repository_label_set() -> None:
    with pytest.raises(ValueError, match="unknown topic"):
        parse(answer(topics=["priority:high"]))
    with pytest.raises(ValueError, match="unknown topic"):
        parse(answer(topics=["UI required"]))


class FakeGitHub:
    """Record the writes of `publish` and serve canned API answers."""

    def __init__(self, *, comments: list[dict[str, Any]], labels: list[str]) -> None:
        self.comments = comments
        self.pr_labels = labels
        self.writes: list[tuple[str, str, Any]] = []

    def api(self, *, path: str, paginate: bool = False, jq: str | None = None) -> Any:
        if path.endswith("/comments?per_page=100"):
            return self.comments
        if "/labels?per_page=100" in path:
            return [{"name": name} for name in ("bug", "Backend", "python", "security", "enhancement")]
        if path.endswith("/reviews?per_page=100"):
            return []
        return {"head": {"sha": HEAD}, "labels": [{"name": name} for name in self.pr_labels]}

    def write(self, *, method: str, path: str, payload: dict[str, Any] | None = None) -> None:
        self.writes.append((method, path, payload))


def run_publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake: FakeGitHub) -> None:
    context_path = tmp_path / "context.json"
    context = make_context(topic_labels=["bug", "Backend"])
    context_path.write_text(json.dumps(triage.asdict(context)), encoding="utf-8")
    monkeypatch.setattr(triage, "gh_api", fake.api)
    monkeypatch.setattr(triage, "gh_write", fake.write)
    triage.publish(repo=REPO, pr_number=10, context_path=context_path, result_path=None)


def added_labels(fake: FakeGitHub) -> set[str]:
    return {
        label
        for method, path, payload in fake.writes
        if method == "POST" and path.endswith("/labels") and payload
        for label in payload["labels"]
    }


def test_topic_labels_are_added_only_on_the_first_triage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = FakeGitHub(comments=[], labels=[])
    run_publish(monkeypatch, tmp_path, first)
    assert added_labels(first) == {"bug", "Backend"}
    assert first.writes[-1][0] == "POST"

    # A sticky comment exists: a label that a maintainer removed stays removed.
    marker_comment = {"id": 5, "user": {"login": common.BOT_LOGIN}, "body": common.COMMENT_MARKER}
    later = FakeGitHub(comments=[marker_comment], labels=[])
    run_publish(monkeypatch, tmp_path, later)
    assert added_labels(later) == set()
    assert later.writes[-1][0] == "PATCH"


def test_prepare_writes_the_context_and_diffs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pr = {
        "title": "fix(api): handle empty flow",
        "body": "Fixes #5",
        "user": {"login": "alice"},
        "base": {"sha": "a" * 40},
        "head": {"sha": HEAD},
        "additions": 3,
        "deletions": 1,
    }
    files = [
        {"filename": "src/docpipe/api/x.py", "status": "modified", "patch": "@@ -10,2 +10,3 @@\n+x"},
        {"filename": "uv.lock", "status": "modified", "patch": "@@ -1 +1 @@\n+lock-secret"},
    ]
    other_pr = {"number": 7, "title": "other", "state": "open", "html_url": "u", "user": {"login": "bob"}}
    other_files = [{"filename": "src/docpipe/api/x.py", "status": "modified", "patch": "@@ -12,2 +12,3 @@\n+y"}]

    def fake_api(*, path: str, paginate: bool = False, jq: str | None = None) -> Any:
        if jq is not None:
            return "c" * 40
        if path.endswith("/issues/5"):
            return {"number": 5, "title": "issue"}
        if path.endswith("/issues/5/timeline?per_page=100"):
            return []
        if "/pulls?state=open" in path:
            return [other_pr]
        return pr

    def fake_files(*, repo: str, number: int) -> list[dict[str, Any]]:
        return files if number == 10 else other_files

    monkeypatch.setattr(triage, "gh_api", fake_api)
    monkeypatch.setattr(triage, "pr_files", fake_files)
    assert triage.prepare(repo=REPO, pr_number=10, out_dir=tmp_path)

    context = json.loads((tmp_path / "context.json").read_text("utf-8"))
    assert context["issue_refs"] == [5]
    assert [c["number"] for c in context["candidates"]] == [7]
    assert context["topic_labels"] == ["bug", "Backend", "python", "dependencies"]
    assert [f["path"] for f in context["risk"]["forced"]] == ["uv.lock"]
    diff = (tmp_path / "pr.diff").read_text("utf-8")
    assert "lock-secret" not in diff
    assert "src/docpipe/api/x.py" in diff
    assert (tmp_path / "candidates/7.diff").is_file()


def _skip(files: list[dict[str, Any]], association: str = "CONTRIBUTOR", requested: bool = False) -> str:
    return triage.llm_skip_reason(files=files, author_association=association, maintainer_requested=requested)


def test_the_model_skips_github_changes_of_a_non_maintainer() -> None:
    workflow = [{"filename": ".github/workflows/ci.yml"}]
    assert _skip(workflow) == triage.LLM_SKIP_REASON
    assert _skip(workflow, "NONE") == triage.LLM_SKIP_REASON
    # A rename out of .github/ is still a change to it.
    renamed = [{"filename": "docs/ci.yml", "previous_filename": ".github/workflows/ci.yml"}]
    assert _skip(renamed) == triage.LLM_SKIP_REASON


def test_the_model_runs_for_maintainers_requests_and_other_paths() -> None:
    workflow = [{"filename": ".github/workflows/ci.yml"}]
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert _skip(workflow, association) == ""
    assert _skip(workflow, requested=True) == ""
    assert _skip([{"filename": "src/docpipe/x.py"}, {"filename": "docs/.github/x.md"}]) == ""
    assert _skip([{"filename": "github/x.yml"}]) == ""


def test_prepare_skips_the_model_for_a_non_maintainer_github_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pr = {
        "title": "ci: change workflow",
        "body": "",
        "user": {"login": "alice"},
        "author_association": "NONE",
        "base": {"sha": "a" * 40},
        "head": {"sha": HEAD},
    }
    files = [{"filename": ".github/workflows/ci.yml", "status": "modified", "patch": "@@ -1 +1 @@\n+x"}]

    def fake_api(*, path: str, paginate: bool = False, jq: str | None = None) -> Any:
        if jq is not None:
            return "c" * 40
        return [] if "/pulls?state=open" in path else pr

    monkeypatch.setattr(triage, "gh_api", fake_api)
    monkeypatch.setattr(triage, "pr_files", lambda *, repo, number: files)
    assert not triage.prepare(repo=REPO, pr_number=10, out_dir=tmp_path)
    stored = json.loads((tmp_path / "context.json").read_text("utf-8"))
    assert stored["llm_skip_reason"] == triage.LLM_SKIP_REASON
    # The deterministic checks still run and the comment says why.
    assert [f["path"] for f in stored["risk"]["forced"]] == [".github/workflows/ci.yml"]
    context = common.TriageContext.from_dict(stored)
    comment = triage.render_comment(context=context, result=None, labels={triage.LABEL_CI_NEEDS_CARE})
    assert "was skipped" in comment
    assert "did not finish" not in comment

    assert triage.prepare(repo=REPO, pr_number=10, out_dir=tmp_path, maintainer_requested=True)
    assert json.loads((tmp_path / "context.json").read_text("utf-8"))["llm_skip_reason"] == ""


def test_one_unreadable_open_pr_does_not_fail_the_duplicate_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pr = {
        "title": "fix: x",
        "body": "",
        "user": {"login": "alice"},
        "author_association": "CONTRIBUTOR",
        "base": {"sha": "a" * 40},
        "head": {"sha": HEAD},
    }
    files = [{"filename": "src/docpipe/api/x.py", "status": "modified", "patch": "@@ -10,2 +10,3 @@\n+x"}]
    good = {"number": 7, "title": "other", "state": "open", "html_url": "u", "user": {"login": "bob"}}
    bad = {"number": 8, "title": "gone", "state": "open", "html_url": "u", "user": {"login": "eve"}}

    def fake_api(*, path: str, paginate: bool = False, jq: str | None = None) -> Any:
        if jq is not None:
            return "c" * 40
        return [bad, good] if "/pulls?state=open" in path else pr

    def fake_files(*, repo: str, number: int) -> list[dict[str, Any]]:
        if number == 8:
            raise triage.subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404")
        return files

    monkeypatch.setattr(triage, "gh_api", fake_api)
    monkeypatch.setattr(triage, "pr_files", fake_files)
    assert triage.prepare(repo=REPO, pr_number=10, out_dir=tmp_path)
    stored = json.loads((tmp_path / "context.json").read_text("utf-8"))
    assert [c["number"] for c in stored["candidates"]] == [7]


def test_publish_without_a_context_posts_a_notice_and_removes_old_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeGitHub(comments=[], labels=["ai:ci-safe", "ai:review-lgtm", "bug"])
    monkeypatch.setattr(triage, "gh_api", fake.api)
    monkeypatch.setattr(triage, "gh_write", fake.write)
    triage.publish(repo=REPO, pr_number=10, context_path=tmp_path / "missing.json", result_path=None)

    deleted = {path.rsplit("/", 1)[1] for method, path, _ in fake.writes if method == "DELETE"}
    assert deleted == {"ai:ci-safe", "ai:review-lgtm"}
    method, path, payload = fake.writes[-1]
    assert (method, path.endswith("/comments")) == ("POST", True)
    assert common.COMMENT_MARKER in payload["body"]
    assert "did not run" in payload["body"]

    # The notice replaces the sticky comment of an earlier run.
    marker_comment = {"id": 5, "user": {"login": common.BOT_LOGIN}, "body": common.COMMENT_MARKER}
    later = FakeGitHub(comments=[marker_comment], labels=[])
    monkeypatch.setattr(triage, "gh_api", later.api)
    monkeypatch.setattr(triage, "gh_write", later.write)
    triage.publish(repo=REPO, pr_number=10, context_path=tmp_path / "missing.json", result_path=None)
    assert later.writes[-1][0] == "PATCH"


def test_the_workflow_publishes_after_a_failed_prepare_and_has_no_reset_job() -> None:
    root = SCRIPTS_DIR.parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ai-pr-triage.yml").read_text("utf-8"))
    assert "reset-labels" not in workflow["jobs"]
    condition = workflow["jobs"]["publish"]["if"]
    assert "needs.context.outputs.run == 'true'" in condition
    assert "run_llm" not in condition


@pytest.mark.parametrize(
    "path",
    [".skills/docpipe-custom-operator/SKILL.md", ".coveragerc", "frontend/eslint.config.js"],
)
def test_agent_skills_and_ci_tool_configuration_force_care(path: str) -> None:
    report = triage.assess_risk([{"filename": path, "status": "modified", "patch": "@@ -1 +1 @@\n+x"}])
    assert [finding.path for finding in report.forced] == [path]


def test_the_parser_has_the_three_subcommands_without_a_git_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(triage, "prepare", lambda **kwargs: seen.update(kwargs) or True)
    assert triage.main(["prepare", "--repo", REPO, "--pr", "3", "--out", str(tmp_path)]) == 0
    assert seen == {"repo": REPO, "pr_number": 3, "out_dir": tmp_path, "maintainer_requested": False}
    assert triage.main(["prepare", "--repo", REPO, "--pr", "3", "--out", str(tmp_path), "--maintainer-requested"]) == 0
    assert seen["maintainer_requested"] is True
    with pytest.raises(SystemExit):
        triage.main(["prepare", "--repo", REPO, "--pr", "3", "--out", str(tmp_path), "--git-dir", "."])
    with pytest.raises(SystemExit):
        triage.main(["unknown"])


def test_bob_modes_are_read_only_and_named_for_this_repository() -> None:
    root = SCRIPTS_DIR.parents[1]
    modes = yaml.safe_load((root / ".github/ai-triage/custom_modes.yaml").read_text("utf-8"))["customModes"]
    assert {mode["slug"] for mode in modes} == {"docling-pipelines-pr-triage", "docling-pipelines-pr-review"}
    assert all(mode["groups"] == ["read"] for mode in modes)

    workflow = (root / ".github/workflows/ai-pr-triage.yml").read_text("utf-8")
    for mode in modes:
        assert f"mode: {mode['slug']}" in workflow
    for path in (root / ".github/ai-triage").iterdir():
        text = path.read_text("utf-8").lower()
        assert "groundtruth" not in text, path
        assert "docling-core" not in text, path
        assert "docling_core" not in text, path
