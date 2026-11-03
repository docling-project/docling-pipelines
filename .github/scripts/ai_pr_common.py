# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Helpers shared by the AI PR triage and AI PR review scripts.

This module holds the data models, the untrusted-text rendering, the Bob Shell
output parsing, and the GitHub and git access. It uses only the standard
library. It never checks out or runs PR code.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COMMENT_MARKER = "<!-- ai-pr-triage -->"
MAX_MODEL_TEXT_CHARS = 600
# Written into untrusted text to stop GitHub from linking or notifying.
ZERO_WIDTH_SPACE = "\u200b"
BOT_LOGIN = "github-actions[bot]"
REVIEW_MARKER_PREFIX = "<!-- ai-pr-review sha="
REVIEW_MARKER = re.compile(r"<!-- ai-pr-review sha=([0-9a-f]{40}) -->")
LABEL_REVIEW_LGTM = "ai:review-lgtm"
LABEL_REVIEW_CHANGES = "ai:review-changes"
REVIEW_LABELS = (LABEL_REVIEW_LGTM, LABEL_REVIEW_CHANGES)
DIFF_EXCLUDED_PATHS = ("uv.lock", "slim/uv.lock", "frontend/package-lock.json")


# ---------------------------------------------------------------------------
# Data models shared by the jobs


@dataclass(slots=True)
class PullRequestInfo:
    number: int
    title: str
    body: str
    author: str
    author_association: str
    base_sha: str
    head_sha: str
    merge_base_sha: str
    changed_files: list[str]
    additions: int
    deletions: int


@dataclass(slots=True)
class Candidate:
    number: int
    title: str
    state: str
    url: str
    author: str = ""
    signals: list[str] = field(default_factory=list)
    shared_files: list[str] = field(default_factory=list)
    overlapping_hunks: int = 0
    score: int = 0


@dataclass(slots=True)
class RiskFinding:
    path: str
    reason: str


@dataclass(slots=True)
class RiskHint:
    path: str
    kind: str
    line: str


@dataclass(slots=True)
class RiskReport:
    forced: list[RiskFinding] = field(default_factory=list)
    hints: list[RiskHint] = field(default_factory=list)


@dataclass(slots=True)
class TriageContext:
    pr: PullRequestInfo
    issue_refs: list[int]
    candidates: list[Candidate]
    risk: RiskReport
    diff_truncated: bool
    topic_labels: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriageContext:
        risk = data["risk"]
        return cls(
            pr=PullRequestInfo(**data["pr"]),
            issue_refs=list(data["issue_refs"]),
            candidates=[Candidate(**item) for item in data["candidates"]],
            risk=RiskReport(
                forced=[RiskFinding(**item) for item in risk["forced"]],
                hints=[RiskHint(**item) for item in risk["hints"]],
            ),
            diff_truncated=data["diff_truncated"],
            topic_labels=list(data["topic_labels"]),
        )


# ---------------------------------------------------------------------------
# Untrusted text


def clean_text(*, text: str, limit: int = MAX_MODEL_TEXT_CHARS) -> str:
    """Reduce untrusted text to one line of printable characters.

    This does not escape Markdown. The publish step validates a stored result
    again, so this must give the same text when it runs twice. Escape with
    `markdown_text` or `markdown_code` where the text goes into a comment.
    """
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def markdown_text(text: str) -> str:
    """Render untrusted text as literal text in a Markdown line or table cell.

    The model answer can be steered by text in the pull request, and the bot
    signs the comment. So the text must not add links, images, HTML,
    headings, lists, code blocks, table cells, or mentions. CommonMark
    renders a backslash before any ASCII punctuation character as that
    character, so escaping all of them covers every Markdown construct.
    """
    text = clean_text(text=text, limit=len(text))
    # GitHub links a bare URL and notifies a mention by itself, also after an
    # escape, so break them with a zero-width space.
    text = re.sub(r"(?i)\b(https?|ftps?|mailto|www)(?=[:.])", rf"\1{ZERO_WIDTH_SPACE}", text)
    text = re.sub(r"@(?=[\w-])", f"@{ZERO_WIDTH_SPACE}", text)
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", text)


def markdown_code(*, text: str, in_table: bool = False) -> str:
    """Render untrusted text as one inline code span.

    Markdown has no syntax inside a code span. The fence is longer than any
    run of backticks in the text, so the text cannot close it.
    """
    text = clean_text(text=text, limit=len(text))
    if in_table:
        # GitHub splits a table cell at a pipe, also inside a code span.
        text = text.replace("|", "\\|")
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _closing_run(*, text: str, start: int, stop: int, length: int) -> int | None:
    """Return the end of the next run of exactly ``length`` backticks."""
    index = start
    while index < stop:
        if text[index] != "`":
            index += 1
            continue
        end = index
        while end < stop and text[end] == "`":
            end += 1
        if end - index == length:
            return end
        index = end
    return None


def code_segments(text: str) -> list[tuple[bool, str]]:
    """Split Markdown into text and code, as ``(is_code, part)`` pairs.

    The split is conservative. A part is code only when CommonMark also reads
    it as code: a fenced block (open to the end when it is not closed), or a
    code span that closes on the same line. Text that CommonMark reads as code
    but this function does not only gets escaped once too often.
    """
    segments: list[tuple[bool, str]] = []
    start = index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char != "`":
            index += 1
            continue
        run_end = index
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        run = run_end - index
        line_start = text.rfind("\n", 0, index) + 1
        line_end = text.find("\n", run_end)
        line_end = len(text) if line_end < 0 else line_end
        is_fence = (
            run >= 3
            and index - line_start <= 3
            and not text[line_start:index].strip(" ")
            and "`" not in text[run_end:line_end]
        )
        end: int | None
        if is_fence:
            closing = re.compile(rf"^ {{0,3}}`{{{run},}}[ \t]*$", re.MULTILINE)
            match = closing.search(text, line_end)
            end = match.end() if match else len(text)
        else:
            end = _closing_run(text=text, start=run_end, stop=line_end, length=run)
        if end is None:
            index = run_end
            continue
        segments.append((False, text[start:index]))
        segments.append((True, text[index:end]))
        start = index = end
    segments.append((False, text[start:]))
    return [(is_code, part) for is_code, part in segments if part]


def _markdown_text_part(part: str) -> str:
    """Escape a text part and keep its spaces next to the code spans."""
    stripped = part.strip()
    if not stripped:
        return part
    lead = part[: len(part) - len(part.lstrip())]
    trail = part[len(part.rstrip()) :]
    return f"{lead}{markdown_text(stripped)}{trail}"


def markdown_inline(*, text: str, in_table: bool = False) -> str:
    """Render one line of untrusted text as literal text with code spans.

    The model writes identifiers in code spans. A code span has no Markdown
    syntax, so it can stay; everything outside it is escaped.
    """
    return "".join(
        markdown_code(text=part.strip("`").strip(), in_table=in_table) if is_code else _markdown_text_part(part)
        for is_code, part in code_segments(clean_text(text=text, limit=len(text)))
    )


def ai_reviewed_shas(reviews: list[dict[str, Any]]) -> list[str]:
    """Return the commits of the earlier AI reviews, oldest first."""
    shas: list[str] = []
    for review in reviews:
        if review["user"]["login"] != BOT_LOGIN:
            continue
        match = REVIEW_MARKER.search(review.get("body") or "")
        if match:
            shas.append(match.group(1))
    return shas


@dataclass(slots=True)
class BobOutput:
    status: str | None
    stats: Any
    last_message: str | None
    errors: list[str]


def read_bob_output(path: Path) -> BobOutput:
    """Read the output of ``bob run --format json``.

    Bob Shell writes one JSON event per line. When a task reaches its turn or
    cost limit, an error event comes before the result event. The last
    message is then often a tool result, not the answer.
    """
    text = path.read_text("utf-8")
    try:
        events = [json.loads(text)]
    except json.JSONDecodeError:
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
    events = [event for event in events if isinstance(event, dict)]
    errors = [str(e.get("message", "")) for e in events if e.get("type") == "error"]
    results = [e for e in events if e.get("type", "result") == "result"]
    if not results:
        reason = f": {'; '.join(errors)}" if errors else ""
        raise ValueError(f"Bob Shell output has no result{reason}")
    result = results[-1]
    last_message = result.get("last_message")
    return BobOutput(
        status=result.get("status"),
        stats=result.get("stats"),
        last_message=last_message if isinstance(last_message, str) else None,
        errors=errors,
    )


def answer_from_output(*, output: BobOutput, required_keys: Collection[str]) -> Any:
    """Return the answer in the final message, or say why there is none."""
    print(f"Bob Shell status: {output.status}; stats: {json.dumps(output.stats)}")
    for error in output.errors:
        print(f"::warning::Bob Shell stopped early: {error}")
    try:
        if output.last_message is None:
            raise ValueError("Bob Shell output has no final message")
        return extract_answer(last_message=output.last_message, required_keys=required_keys)
    except ValueError as exc:
        if output.errors:
            raise ValueError(f"{exc} (Bob Shell stopped early)") from exc
        raise


def extract_answer(*, last_message: str, required_keys: Collection[str] = ()) -> Any:
    """Return the answer object in the final model message.

    The model sometimes writes a draft object before the answer, or text after
    it. So take the last top-level JSON object that has all `required_keys`.
    A nested object, for example one finding of a broken answer, does not
    count, so a broken answer is not read as an empty one.
    """

    def is_answer(value: object) -> bool:
        return isinstance(value, dict) and all(key in value for key in required_keys)

    for block in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", last_message, re.DOTALL)):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if is_answer(value):
            return value
    decoder = json.JSONDecoder()
    answer: dict[str, Any] | None = None
    index = last_message.find("{")
    while index >= 0:
        try:
            value, end = decoder.raw_decode(last_message, index)
        except json.JSONDecodeError:
            index = last_message.find("{", index + 1)
            continue
        if is_answer(value):
            answer = value
        index = last_message.find("{", end)
    if answer is None:
        raise ValueError("final message contains no JSON object")
    return answer


def matches_any(*, path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def build_diff(*, files: list[dict[str, Any]], max_chars: int, only: set[str] | None = None) -> tuple[str, bool]:
    parts: list[str] = []
    size = 0
    truncated = False
    for item in files:
        path = item["filename"]
        if only is not None and path not in only:
            continue
        if matches_any(path=path, patterns=DIFF_EXCLUDED_PATHS):
            body = "(content omitted: lock file)\n"
        else:
            body = item.get("patch") or "(no text patch: binary or too large)\n"
        part = f"diff --git a/{path} b/{path}\nstatus: {item.get('status')}\n{body}\n"
        if size + len(part) > max_chars:
            truncated = True
            break
        parts.append(part)
        size += len(part)
    return "".join(parts), truncated


# ---------------------------------------------------------------------------
# GitHub and git access


def gh_api(*, path: str, paginate: bool = False, jq: str | None = None) -> Any:
    command = ["gh", "api", "-H", "Accept: application/vnd.github+json", path]
    if paginate:
        command[2:2] = ["--paginate", "--slurp"]
    if jq is not None:
        command += ["--jq", jq]
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    if jq is not None:
        return output.strip()
    data = json.loads(output)
    if paginate:
        return [item for page in data for item in page]
    return data


def gh_write(*, method: str, path: str, payload: dict[str, Any] | None = None) -> None:
    command = ["gh", "api", "--method", method, path]
    if payload is not None:
        command += ["--input", "-"]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(payload) if payload is not None else None,
    )


def pr_files(*, repo: str, number: int) -> list[dict[str, Any]]:
    return gh_api(path=f"repos/{repo}/pulls/{number}/files?per_page=100", paginate=True)


def git(*, git_dir: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(git_dir), *args], capture_output=True, check=False)


def fetch_pr_commits(*, git_dir: Path, pr_number: int, merge_base: str) -> bool:
    """Fetch the merge base and the PR head without blobs and without checkout.

    `git show` then loads each blob on demand, so the job never downloads
    every file of the PR. Nothing from the PR is checked out or run.
    """
    fetch = git(
        git_dir=git_dir,
        args=[
            "fetch",
            "--no-tags",
            "--depth=1",
            "--filter=blob:none",
            "origin",
            merge_base,
            f"pull/{pr_number}/head",
        ],
    )
    return fetch.returncode == 0


def read_blob(*, git_dir: Path, commit: str, path: str) -> bytes | None:
    result = git(git_dir=git_dir, args=["show", f"{commit}:{path}"])
    return result.stdout if result.returncode == 0 else None
