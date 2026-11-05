# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Advisory AI triage for pull requests before a maintainer approves CI.

The workflow runs three steps, each in its own job:

* ``prepare`` (read-only token): collects PR data with the GitHub API, finds
  possible duplicate PRs, and applies deterministic CI-safety rules. It never
  checks out or runs PR code.
* ``extract`` (no GitHub token): validates the JSON answer of the Bob Shell run.
* ``publish`` (write token, no LLM): applies an allowlist of labels and updates
  one sticky comment.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_pr_common import (
    BOT_LOGIN,
    COMMENT_MARKER,
    REVIEW_LABELS,
    Candidate,
    PullRequestInfo,
    RiskFinding,
    RiskHint,
    RiskReport,
    TriageContext,
    ai_reviewed_shas,
    answer_from_output,
    build_diff,
    clean_text,
    gh_api,
    gh_write,
    markdown_code,
    markdown_inline,
    matches_any,
    pr_files,
    read_bob_output,
)
from ai_pr_event import MAINTAINER_ASSOCIATIONS
from pr_topic_labels import deterministic_topics, parse_model_topics, select_topics

LABEL_DUPLICATE = "ai:possible-duplicate"
LABEL_CI_SAFE = "ai:ci-safe"
LABEL_CI_NEEDS_CARE = "ai:ci-needs-care"
MANAGED_LABELS = (LABEL_DUPLICATE, LABEL_CI_SAFE, LABEL_CI_NEEDS_CARE)
TRIAGE_ANSWER_KEYS = ("ci_safety",)

# The AI model does not read a PR from an author without maintainer rights when
# the PR changes these paths. The model runs with a secret in its environment,
# and a change here is the most likely way to steer it or to run code in CI.
LLM_PROTECTED_PREFIXES = (".github/",)
LLM_SKIP_REASON = "the PR changes `.github/` and its author is not a maintainer"

MAX_ISSUE_REFS = 5
MAX_OPEN_PRS_SCANNED = 30
MAX_CANDIDATES = 5
MAX_PR_DIFF_CHARS = 120_000
MAX_CANDIDATE_DIFF_CHARS = 20_000
MAX_RISK_HINTS = 30
MAX_BODY_CHARS = 6_000
HUNK_SLACK_LINES = 3

# Changes in these paths can alter what CI executes or what AI tools read. A
# match always requires maintainer care, whatever the model says. `fnmatch`
# lets `*` match `/`, so `scripts/*` also covers nested files.
SENSITIVE_PATHS: tuple[tuple[str, str], ...] = (
    (".github/*", "changes CI workflows, actions, or CI scripts"),
    ("conftest.py", "pytest runs this file at collection"),
    ("*/conftest.py", "pytest runs this file at collection"),
    ("pytest.ini", "changes pytest plugins, options, and timeouts"),
    ("pyproject.toml", "changes build, dependency, or tool configuration"),
    ("slim/pyproject.toml", "changes the slim package build and dependencies"),
    ("uv.lock", "changes locked dependencies"),
    ("slim/uv.lock", "changes locked dependencies of the slim package"),
    ("hatch_build.py", "runs the frontend build during wheel creation"),
    ("setup.py", "runs at install time"),
    ("setup.cfg", "changes install configuration"),
    ("Makefile", "changes local and CI commands"),
    ("*/Makefile", "changes local and CI commands"),
    (".pre-commit-config.yaml", "changes hooks that CI runs"),
    ("scripts/*", "changes maintenance scripts"),
    ("*.sh", "adds or changes a shell script"),
    ("docker/*", "changes container builds and deployment files"),
    ("frontend/package.json", "changes frontend dependencies and npm scripts"),
    ("frontend/package-lock.json", "changes locked frontend dependencies"),
    ("frontend/vite.config.ts", "changes the frontend build and test configuration"),
    ("frontend/lint-hook.sh", "changes a hook that runs frontend checks"),
    ("CODEOWNERS", "changes who must review code"),
    ("*.pth", "Python runs .pth files at startup"),
    ("sitecustomize.py", "Python runs this file at startup"),
    ("*/sitecustomize.py", "Python runs this file at startup"),
    ("AGENTS.md", "changes instructions for AI agents"),
    ("CLAUDE.md", "changes instructions for AI agents"),
    (".agents/*", "changes instructions for AI agents"),
    (".claude/*", "changes instructions for AI agents"),
    (".codex/*", "changes instructions for AI agents"),
    (".bob/*", "changes instructions for AI agents"),
    (".skills/*", "changes instructions for AI agents"),
    (".coveragerc", "changes how CI measures coverage"),
    ("frontend/eslint.config.js", "changes the frontend lint configuration"),
)
BINARY_SUFFIXES = frozenset({".so", ".dll", ".dylib", ".exe", ".whl", ".pyc", ".pyd", ".bin", ".jar"})
# Added lines that match these patterns are shown to the model as hints. They
# do not force a verdict, because docpipe code legitimately uses some of them.
RISK_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "process execution",
        re.compile(r"\b(subprocess|os\.system|os\.popen|os\.exec\w*|pty\.spawn)\b"),
    ),
    ("dynamic code execution", re.compile(r"\b(eval|exec|__import__)\s*\(")),
    (
        "network access",
        re.compile(r"\b(urllib\.request|requests\.(get|post|put)|httpx\.|socket\.)|\b(curl|wget)\s"),
    ),
    (
        "encoded payload",
        re.compile(r"base64\.b64decode|bytes\.fromhex|[A-Za-z0-9+/]{200,}={0,2}"),
    ),
    (
        "environment or secret access",
        re.compile(r"(environ|getenv).*(TOKEN|SECRET|KEY|PASSWORD)|\bGITHUB_|\bACTIONS_"),
    ),
    (
        "unsafe deserialization",
        re.compile(r"\b(pickle|marshal|dill)\.loads?\b|yaml\.load\("),
    ),
)
# These files change in many unrelated PRs, so they do not count as overlap.
OVERLAP_NOISE_PATHS = (
    "uv.lock",
    "slim/uv.lock",
    "pyproject.toml",
    "slim/pyproject.toml",
    "CHANGELOG.md",
    "*/__init__.py",
    "frontend/package-lock.json",
)
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.MULTILINE)


# ---------------------------------------------------------------------------
# The model answer


@dataclass(slots=True)
class DuplicateVerdict:
    pr: int
    verdict: str
    reason: str


@dataclass(slots=True)
class SafetyConcern:
    path: str
    reason: str


@dataclass(slots=True)
class TriageResult:
    summary: str
    duplicates: list[DuplicateVerdict]
    ci_verdict: str
    ci_concerns: list[SafetyConcern]
    topics: list[str]


DUPLICATE_VERDICTS = frozenset({"duplicate", "related", "unrelated"})
CI_VERDICTS = frozenset({"safe", "needs-care"})


def parse_triage_result(data: Any, *, allowed_prs: set[int]) -> TriageResult:
    """Validate the model answer. Unknown values are errors, not defaults."""
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    duplicates: list[DuplicateVerdict] = []
    for item in _require_list(data=data, key="duplicates"):
        pr = item.get("pr") if isinstance(item, dict) else None
        verdict = item.get("verdict") if isinstance(item, dict) else None
        if not isinstance(pr, int) or pr not in allowed_prs:
            raise ValueError(f"duplicate entry names an unknown PR: {pr!r}")
        if verdict not in DUPLICATE_VERDICTS:
            raise ValueError(f"invalid duplicate verdict: {verdict!r}")
        duplicates.append(DuplicateVerdict(pr, verdict, _model_text(data=item, key="reason")))

    safety = data.get("ci_safety")
    if not isinstance(safety, dict) or safety.get("verdict") not in CI_VERDICTS:
        raise ValueError("ci_safety.verdict must be 'safe' or 'needs-care'")
    concerns = [
        SafetyConcern(_model_text(data=item, key="path"), _model_text(data=item, key="reason"))
        for item in _require_list(data=safety, key="concerns")
        if isinstance(item, dict)
    ]

    return TriageResult(
        summary=_model_text(data=data, key="summary"),
        duplicates=duplicates,
        ci_verdict=safety["verdict"],
        ci_concerns=concerns,
        topics=parse_model_topics(data.get("topics")),
    )


def _require_list(*, data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _model_text(*, data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    return clean_text(text=value if isinstance(value, str) else str(value))


# ---------------------------------------------------------------------------
# Deterministic analysis


def extract_issue_refs(*, text: str, repo: str, own_number: int) -> list[int]:
    repo_url = re.escape(f"github.com/{repo}/")
    pattern = re.compile(rf"(?:{repo_url}(?:issues|pull)/|(?<![\w/])#)(\d+)\b")
    refs: list[int] = []
    for match in pattern.finditer(text):
        number = int(match.group(1))
        if number != own_number and number not in refs:
            refs.append(number)
    return refs[:MAX_ISSUE_REFS]


def llm_skip_reason(*, files: list[dict[str, Any]], author_association: str, maintainer_requested: bool) -> str:
    """Return why the AI model must not read this PR, or "" when it may.

    A maintainer who asks (`/ai` command or manual run) accepts the risk, so
    the request lifts the skip. A rename out of a protected path counts as a
    change to it.
    """
    if maintainer_requested or author_association in MAINTAINER_ASSOCIATIONS:
        return ""
    for item in files:
        for path in (item["filename"], item.get("previous_filename")):
            if path and path.startswith(LLM_PROTECTED_PREFIXES):
                return LLM_SKIP_REASON
    return ""


def assess_risk(files: list[dict[str, Any]]) -> RiskReport:
    report = RiskReport()
    for item in files:
        paths = [item["filename"]]
        if item.get("previous_filename"):
            paths.append(item["previous_filename"])
        for path in paths:
            for pattern, reason in SENSITIVE_PATHS:
                if fnmatch.fnmatchcase(path, pattern):
                    report.forced.append(RiskFinding(path, reason))
                    break
            if Path(path).suffix.lower() in BINARY_SUFFIXES:
                report.forced.append(RiskFinding(path, "adds or changes a binary file"))

        path = item["filename"]
        if len(report.hints) >= MAX_RISK_HINTS:
            continue
        for line in (item.get("patch") or "").splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            for kind, hint_pattern in RISK_HINT_PATTERNS:
                if hint_pattern.search(line):
                    report.hints.append(RiskHint(path, kind, line[1:].strip()[:200]))
                    break
            if len(report.hints) >= MAX_RISK_HINTS:
                break
    return report


def hunk_ranges(patch: str | None) -> list[tuple[int, int]]:
    """Return the changed line ranges in the old file of a unified patch."""
    ranges: list[tuple[int, int]] = []
    for match in HUNK_HEADER.finditer(patch or ""):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        ranges.append((start, start + max(count, 1) - 1))
    return ranges


def count_overlapping_hunks(*, ours: list[tuple[int, int]], theirs: list[tuple[int, int]]) -> int:
    return sum(
        1
        for a_start, a_end in ours
        if any(a_start <= b_end + HUNK_SLACK_LINES and b_start <= a_end + HUNK_SLACK_LINES for b_start, b_end in theirs)
    )


def compare_files(*, ours: list[dict[str, Any]], theirs: list[dict[str, Any]]) -> tuple[list[str], int]:
    """Return the shared relevant files and the count of overlapping hunks."""
    their_patches = {item["filename"]: item.get("patch") for item in theirs}
    shared: list[str] = []
    overlaps = 0
    for item in ours:
        path = item["filename"]
        if path not in their_patches or matches_any(path=path, patterns=OVERLAP_NOISE_PATHS):
            continue
        shared.append(path)
        overlaps += count_overlapping_hunks(
            ours=hunk_ranges(item.get("patch")),
            theirs=hunk_ranges(their_patches[path]),
        )
    return shared, overlaps


def is_overlap_candidate(*, shared_files: list[str], overlapping_hunks: int) -> bool:
    return overlapping_hunks > 0 or len(shared_files) >= 3


# ---------------------------------------------------------------------------
# Jobs


def _pr_files_or_none(*, repo: str, number: int) -> list[dict[str, Any]] | None:
    """Return the files of another PR, or None when the API call fails.

    One PR that cannot be read (deleted, rate limit) must not remove the
    deterministic checks of the PR under triage.
    """
    try:
        return pr_files(repo=repo, number=number)
    except subprocess.CalledProcessError as exc:
        detail = clean_text(text=str(exc.stderr or ""), limit=200)
        print(f"::warning::PR #{number} is skipped in the duplicate scan: {detail or 'the API call failed'}")
        return None


def find_candidates(
    *,
    repo: str,
    pr_number: int,
    refs: list[int],
    files: list[dict[str, Any]],
) -> list[tuple[Candidate, list[dict[str, Any]]]]:
    found: dict[int, Candidate] = {}

    def add(item: dict[str, Any], signal: str) -> Candidate:
        number = int(item["number"])
        candidate = found.get(number)
        if candidate is None:
            merged = (item.get("pull_request") or {}).get("merged_at") or item.get("merged_at")
            state = "merged" if merged else str(item.get("state", "unknown"))
            candidate = Candidate(
                number=number,
                title=str(item.get("title", "")),
                state=state,
                url=str(item.get("html_url", "")),
                author=str((item.get("user") or {}).get("login", "")),
            )
            found[number] = candidate
        if signal not in candidate.signals:
            candidate.signals.append(signal)
            candidate.score += 10
        return candidate

    for ref in refs:
        issue = gh_api(path=f"repos/{repo}/issues/{ref}")
        if "pull_request" in issue:
            add(issue, f"referenced as #{ref}")
            continue
        events = gh_api(path=f"repos/{repo}/issues/{ref}/timeline?per_page=100", paginate=True)
        for event in events:
            source = (event.get("source") or {}).get("issue") or {}
            source_repo = (source.get("repository") or {}).get("full_name")
            if (
                event.get("event") == "cross-referenced"
                and "pull_request" in source
                and source_repo == repo
                and source.get("number") != pr_number
            ):
                add(source, f"also references issue #{ref}")

    open_prs = gh_api(path=f"repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page={MAX_OPEN_PRS_SCANNED}")
    files_by_pr: dict[int, list[dict[str, Any]]] = {}
    for other in open_prs:
        number = int(other["number"])
        if number == pr_number:
            continue
        other_files = _pr_files_or_none(repo=repo, number=number)
        if other_files is None:
            continue
        files_by_pr[number] = other_files
        shared, overlaps = compare_files(ours=files, theirs=other_files)
        if is_overlap_candidate(shared_files=shared, overlapping_hunks=overlaps):
            candidate = add(other, "changes the same code")
        elif number in found:
            candidate = found[number]
        else:
            continue
        candidate.shared_files = shared
        candidate.overlapping_hunks = overlaps
        candidate.score += 2 * overlaps + len(shared)

    ranked = sorted(found.values(), key=lambda c: (-c.score, -c.number))
    selected = ranked[:MAX_CANDIDATES]
    result: list[tuple[Candidate, list[dict[str, Any]]]] = []
    for candidate in selected:
        candidate_files = files_by_pr.get(candidate.number)
        if candidate_files is None:
            candidate_files = _pr_files_or_none(repo=repo, number=candidate.number) or []
            candidate.shared_files, candidate.overlapping_hunks = compare_files(ours=files, theirs=candidate_files)
        result.append((candidate, candidate_files))
    return result


def prepare(*, repo: str, pr_number: int, out_dir: Path, maintainer_requested: bool = False) -> bool:
    """Write the triage inputs. Return True when the AI model may run."""
    pr = gh_api(path=f"repos/{repo}/pulls/{pr_number}")
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    merge_base = gh_api(path=f"repos/{repo}/compare/{base_sha}...{head_sha}", jq=".merge_base_commit.sha")
    files = pr_files(repo=repo, number=pr_number)
    body = pr.get("body") or ""
    info = PullRequestInfo(
        number=pr_number,
        title=pr["title"],
        body=body[:MAX_BODY_CHARS],
        author=pr["user"]["login"],
        author_association=pr.get("author_association", ""),
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base,
        changed_files=[item["filename"] for item in files],
        additions=int(pr.get("additions", 0)),
        deletions=int(pr.get("deletions", 0)),
    )
    skip_reason = llm_skip_reason(
        files=files,
        author_association=info.author_association,
        maintainer_requested=maintainer_requested,
    )
    if skip_reason:
        print(f"The AI analysis is skipped: {skip_reason}.")
    refs = extract_issue_refs(text=f"{pr['title']}\n{body}", repo=repo, own_number=pr_number)
    candidates = find_candidates(repo=repo, pr_number=pr_number, refs=refs, files=files)
    diff, truncated = build_diff(files=files, max_chars=MAX_PR_DIFF_CHARS)
    context = TriageContext(
        pr=info,
        issue_refs=refs,
        candidates=[candidate for candidate, _ in candidates],
        risk=assess_risk(files),
        diff_truncated=truncated,
        topic_labels=deterministic_topics(title=pr["title"], paths=[item["filename"] for item in files]),
        llm_skip_reason=skip_reason,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "context.json").write_text(json.dumps(asdict(context), indent=2), encoding="utf-8")
    (out_dir / "pr.diff").write_text(diff, encoding="utf-8")
    candidates_dir = out_dir / "candidates"
    candidates_dir.mkdir(exist_ok=True)
    for candidate, candidate_files in candidates:
        only = set(candidate.shared_files) or None
        candidate_diff, _ = build_diff(files=candidate_files, max_chars=MAX_CANDIDATE_DIFF_CHARS, only=only)
        (candidates_dir / f"{candidate.number}.diff").write_text(candidate_diff, encoding="utf-8")
    return bool(files) and not skip_reason


def extract(*, bob_output: Path, context_path: Path, out_path: Path) -> None:
    context = TriageContext.from_dict(json.loads(context_path.read_text("utf-8")))
    answer = answer_from_output(output=read_bob_output(bob_output), required_keys=TRIAGE_ANSWER_KEYS)
    allowed = {candidate.number for candidate in context.candidates}
    result = parse_triage_result(answer, allowed_prs=allowed)
    out_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")


def effective_verdicts(*, context: TriageContext, result: TriageResult | None) -> dict[int, str]:
    """Return the verdict of each assessed candidate.

    A closed PR that was not merged is at most related, whatever the model says.
    """
    if result is None:
        return {}
    states = {candidate.number: candidate.state for candidate in context.candidates}
    return {
        d.pr: "related" if d.verdict == "duplicate" and states.get(d.pr) == "closed" else d.verdict
        for d in result.duplicates
    }


def decide_labels(*, context: TriageContext, result: TriageResult | None) -> set[str]:
    labels: set[str] = set()
    if context.risk.forced or (result is not None and result.ci_verdict != "safe"):
        labels.add(LABEL_CI_NEEDS_CARE)
    elif result is not None:
        labels.add(LABEL_CI_SAFE)
    if "duplicate" in effective_verdicts(context=context, result=result).values():
        labels.add(LABEL_DUPLICATE)
    return labels


def render_comment(
    *,
    context: TriageContext,
    result: TriageResult | None,
    labels: set[str],
    added_topics: list[str] | None = None,
) -> str:
    head = context.pr.head_sha[:10]
    lines = [
        COMMENT_MARKER,
        "### AI triage (advisory)",
        "",
        f"Checked commit `{head}`. The analysis read the diff only. It did not run code from this pull request.",
        "",
    ]
    if result is None and context.llm_skip_reason:
        lines += [
            "> [!NOTE]",
            f"> The AI analysis was skipped: {context.llm_skip_reason}. Only the deterministic checks are shown.",
            "> A maintainer can comment `/ai triage` or `/ai review` to run it.",
            "",
        ]
    elif result is None:
        lines += [
            "> [!WARNING]",
            "> The AI analysis did not finish. Only the deterministic checks are shown.",
            "",
        ]
    elif result.summary:
        lines += [markdown_inline(text=result.summary), ""]
    if added_topics:
        names = ", ".join(f"`{topic}`" for topic in added_topics)
        lines += [f"Topic labels added: {names}.", ""]

    if LABEL_CI_NEEDS_CARE in labels:
        lines.append("**CI safety: needs maintainer care** before you approve CI.")
    elif LABEL_CI_SAFE in labels:
        lines.append("**CI safety: no concern found.** A maintainer must still approve CI.")
    else:
        lines.append("**CI safety: not assessed.**")
    for finding in context.risk.forced:
        lines.append(f"- {markdown_code(text=finding.path)}: {finding.reason}")
    if result is not None:
        for concern in result.ci_concerns:
            path = f"{markdown_code(text=concern.path)}: " if concern.path else ""
            lines.append(f"- {path}{markdown_inline(text=concern.reason)}")
    lines.append("")

    verdicts = effective_verdicts(context=context, result=result)
    reasons = {d.pr: d.reason for d in result.duplicates} if result else {}
    # Duplicates and unassessed candidates stay visible. Related PRs are
    # collapsed, and unrelated PRs are hidden.
    main = [c for c in context.candidates if verdicts.get(c.number) in (None, "duplicate")]
    related = [c for c in context.candidates if verdicts.get(c.number) == "related"]
    if main:
        title = "Possible duplicates" if result else "Possibly related pull requests"
        lines += [f"**{title}**", ""]
        lines += _candidate_table(candidates=main, verdicts=verdicts, reasons=reasons)
        lines.append("")
    if related:
        lines += [
            "<details>",
            f"<summary>{len(related)} related pull request(s) in the same code</summary>",
            "",
        ]
        lines += _candidate_table(candidates=related, verdicts=verdicts, reasons=reasons)
        lines += ["", "</details>", ""]

    lines.append("<sub>The `ai:*` labels are advisory. They do not approve CI. A new push runs this check again.</sub>")
    return "\n".join(lines)


def _candidate_table(*, candidates: list[Candidate], verdicts: dict[int, str], reasons: dict[int, str]) -> list[str]:
    rows = ["| PR | State | Signal | Assessment |", "|---|---|---|---|"]
    for candidate in candidates:
        verdict = verdicts.get(candidate.number)
        assessment = (
            f"{verdict}: {markdown_inline(text=reasons[candidate.number], in_table=True)}"
            if verdict
            else "not assessed"
        )
        signals = "; ".join(candidate.signals)
        rows.append(f"| #{candidate.number} | {candidate.state} | {signals} | {assessment} |")
    return rows


def stale_review_labels(*, current: set[str], reviewed_shas: list[str], head_sha: str) -> set[str]:
    """Return the AI review labels that describe an older commit.

    A review label belongs to the commit of the last AI review. After a push,
    a manual run, or /ai triage, the head can be newer than that review, and
    the review can be skipped for the new head. A review of the head in the
    same run sets its label again after this.
    """
    if reviewed_shas and reviewed_shas[-1] == head_sha:
        return set()
    return current & set(REVIEW_LABELS)


def _find_sticky_comment(*, repo: str, pr_number: int) -> dict[str, Any] | None:
    comments = gh_api(path=f"repos/{repo}/issues/{pr_number}/comments?per_page=100", paginate=True)
    return next(
        (
            comment
            for comment in comments
            if comment["user"]["login"] == BOT_LOGIN and COMMENT_MARKER in comment["body"]
        ),
        None,
    )


def _write_sticky_comment(*, repo: str, pr_number: int, existing: dict[str, Any] | None, body: str) -> None:
    if existing is None:
        gh_write(method="POST", path=f"repos/{repo}/issues/{pr_number}/comments", payload={"body": body})
    else:
        gh_write(method="PATCH", path=f"repos/{repo}/issues/comments/{existing['id']}", payload={"body": body})


def render_failure_comment() -> str:
    return "\n".join(
        [
            COMMENT_MARKER,
            "### AI triage (advisory)",
            "",
            "> [!WARNING]",
            "> The AI triage did not run for this commit. The collection of the PR data failed, so no checks,"
            " labels, or review are shown. Do not read the missing result as a clean result.",
            "> A maintainer can comment `/ai triage` to run it again. See the workflow run for the error.",
            "",
            "<sub>The `ai:*` labels are advisory. They do not approve CI.</sub>",
        ]
    )


def publish_failure(*, repo: str, pr_number: int) -> None:
    """Tell maintainers that the triage did not run, instead of staying silent.

    The labels of an earlier commit are removed, so that they do not look like
    a result for this commit.
    """
    pr = gh_api(path=f"repos/{repo}/pulls/{pr_number}")
    stale = {label["name"] for label in pr["labels"]} & {*MANAGED_LABELS, *REVIEW_LABELS}
    for label in sorted(stale):
        gh_write(method="DELETE", path=f"repos/{repo}/issues/{pr_number}/labels/{label}")
    existing = _find_sticky_comment(repo=repo, pr_number=pr_number)
    _write_sticky_comment(repo=repo, pr_number=pr_number, existing=existing, body=render_failure_comment())


def publish(*, repo: str, pr_number: int, context_path: Path, result_path: Path | None) -> None:
    if not context_path.is_file():
        print("::warning::No triage context. The collection of the PR data failed.")
        publish_failure(repo=repo, pr_number=pr_number)
        return
    context = TriageContext.from_dict(json.loads(context_path.read_text("utf-8")))
    pr = gh_api(path=f"repos/{repo}/pulls/{pr_number}")
    if pr["head"]["sha"] != context.pr.head_sha:
        print("The PR has a newer commit. The newer run publishes the result.")
        return

    result: TriageResult | None = None
    if result_path is not None and result_path.is_file():
        allowed = {candidate.number for candidate in context.candidates}
        try:
            data = json.loads(result_path.read_text("utf-8"))
            result = parse_triage_result(_result_to_answer(data), allowed_prs=allowed)
        except (ValueError, KeyError, TypeError) as exc:
            print(f"Ignoring an invalid analysis result: {exc}")

    existing = _find_sticky_comment(repo=repo, pr_number=pr_number)

    labels = decide_labels(context=context, result=result)
    # Topic labels are set only on the first triage of a PR, so a label that a
    # maintainer removed is not added again after the next push.
    topics: list[str] = []
    if existing is None:
        repo_labels = gh_api(path=f"repos/{repo}/labels?per_page=100", paginate=True)
        topics = select_topics(
            deterministic=context.topic_labels,
            model=result.topics if result is not None else [],
            existing={label["name"] for label in repo_labels},
        )
    current = {label["name"] for label in pr["labels"]}
    stale = (current & set(MANAGED_LABELS)) - labels
    if current & set(REVIEW_LABELS):
        reviews = gh_api(path=f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100", paginate=True)
        stale |= stale_review_labels(
            current=current,
            reviewed_shas=ai_reviewed_shas(reviews),
            head_sha=context.pr.head_sha,
        )
    for label in sorted(stale):
        gh_write(method="DELETE", path=f"repos/{repo}/issues/{pr_number}/labels/{label}")
    to_add = (labels | set(topics)) - current
    if to_add:
        gh_write(
            method="POST",
            path=f"repos/{repo}/issues/{pr_number}/labels",
            payload={"labels": sorted(to_add)},
        )

    body = render_comment(
        context=context,
        result=result,
        labels=labels,
        added_topics=[t for t in topics if t not in current],
    )
    _write_sticky_comment(repo=repo, pr_number=pr_number, existing=existing, body=body)


def _result_to_answer(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored TriageResult back to the answer shape for re-validation."""
    return {
        "summary": data["summary"],
        "duplicates": data["duplicates"],
        "ci_safety": {"verdict": data["ci_verdict"], "concerns": data["ci_concerns"]},
        "topics": data["topics"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare")
    prep.add_argument("--repo", required=True)
    prep.add_argument("--pr", type=int, required=True)
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument(
        "--maintainer-requested",
        action="store_true",
        help="A maintainer started this run, so the AI model may read a PR that is otherwise skipped.",
    )

    ext = sub.add_parser("extract")
    ext.add_argument("--bob-output", type=Path, required=True)
    ext.add_argument("--context", type=Path, required=True)
    ext.add_argument("--out", type=Path, required=True)

    pub = sub.add_parser("publish")
    pub.add_argument("--repo", required=True)
    pub.add_argument("--pr", type=int, required=True)
    pub.add_argument("--context", type=Path, required=True)
    pub.add_argument("--result", type=Path)

    args = parser.parse_args(argv)
    if args.command == "prepare":
        has_changes = prepare(
            repo=args.repo,
            pr_number=args.pr,
            out_dir=args.out,
            maintainer_requested=args.maintainer_requested,
        )
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with Path(github_output).open("a", encoding="utf-8") as handle:
                handle.write(f"run_llm={'true' if has_changes else 'false'}\n")
    elif args.command == "extract":
        try:
            extract(bob_output=args.bob_output, context_path=args.context, out_path=args.out)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"::warning::The Bob Shell answer is not valid: {exc}")
            return 1
    else:
        publish(repo=args.repo, pr_number=args.pr, context_path=args.context, result_path=args.result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
