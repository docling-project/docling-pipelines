# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Select topic labels for a pull request from the repository label set.

Deterministic rules map the conventional-commit title and the changed source
paths to labels. The AI triage can add a few more labels, but only names from
``TOPIC_LABELS``. The workflow only adds topic labels and never removes them,
because maintainers own these labels.
"""

from __future__ import annotations

import fnmatch
import re

# Existing repository labels that describe what a PR changes. Process labels
# (priority, triage, duplicate, wontfix, "UI required", ...) are intentionally
# not here: maintainers apply them by hand.
TOPIC_LABELS: tuple[str, ...] = (
    "bug",
    "enhancement",
    "documentation",
    "dependencies",
    "security",
    "ci",
    "testing",
    "Backend",
    "python",
    "javascript",
)
MAX_MODEL_TOPICS = 3
MAX_TOPICS = 6

TITLE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?!?:")
# There is no performance label, so `perf` maps to `enhancement`.
TYPE_LABELS = {
    "fix": "bug",
    "feat": "enhancement",
    "docs": "documentation",
    "perf": "enhancement",
    "test": "testing",
    "ci": "ci",
    "build": "ci",
    "deps": "dependencies",
    "security": "security",
}
# Keys are lowercase: the scope is lowercased before the lookup.
SCOPE_LABELS = {
    "api": "Backend",
    "operator": "Backend",
    "operators": "Backend",
    "engine": "Backend",
    "core": "Backend",
    "cli": "Backend",
    "backend": "Backend",
    "frontend": "javascript",
    "ui": "javascript",
    "canvas": "javascript",
    "deps": "dependencies",
    "security": "security",
    "ci": "ci",
}
LOCK_FILES = ("uv.lock", "slim/uv.lock", "frontend/package-lock.json")
# fnmatch: `*` also matches `/`. Lock files are matched exactly and only ever
# receive the `dependencies` label (see `deterministic_topics`).
PATH_LABELS: tuple[tuple[str, str], ...] = (
    ("src/docpipe/*", "Backend"),
    ("src/docpipe/*", "python"),
    ("frontend/*", "javascript"),
    ("uv.lock", "dependencies"),
    ("slim/uv.lock", "dependencies"),
    ("frontend/package-lock.json", "dependencies"),
    (".github/*", "ci"),
    (".pre-commit-config.yaml", "ci"),
)
DOC_PATHS = ("docs/*",)
TEST_PATHS = ("tests/*",)


def _matches_any(*, path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_doc_path(*, path: str) -> bool:
    """True for files under docs/ and for Markdown files in the repository root.

    `fnmatch` lets `*` match `/`, so `*.md` alone would also match a README
    inside `src/` or `frontend/`, which is not a documentation-only change.
    """
    return _matches_any(path=path, patterns=DOC_PATHS) or ("/" not in path and path.endswith(".md"))


def deterministic_topics(*, title: str, paths: list[str]) -> list[str]:
    """Return topic labels from the PR title and the changed paths."""
    labels: list[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    match = TITLE.match(title.strip())
    if match:
        if match.group("type") in TYPE_LABELS:
            add(TYPE_LABELS[match.group("type")])
        for scope in re.split(r"[,/ ]+", match.group("scope") or ""):
            if scope.lower() in SCOPE_LABELS:
                add(SCOPE_LABELS[scope.lower()])
    for path in paths:
        for pattern, label in PATH_LABELS:
            if path in LOCK_FILES and label != "dependencies":
                continue
            if fnmatch.fnmatchcase(path, pattern):
                add(label)
    source = [path for path in paths if path not in LOCK_FILES]
    if source and all(_is_doc_path(path=path) for path in source):
        add("documentation")
    if source and all(_matches_any(path=path, patterns=TEST_PATHS) for path in source):
        add("testing")
    return labels


def parse_model_topics(value: object) -> list[str]:
    """Validate the topics of the model answer against the allowlist."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("topics must be a list")
    topics: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in TOPIC_LABELS:
            raise ValueError(f"unknown topic label: {item!r}")
        if item not in topics:
            topics.append(item)
    return topics[:MAX_MODEL_TOPICS]


def select_topics(*, deterministic: list[str], model: list[str], existing: set[str]) -> list[str]:
    """Merge the topics. Only labels that exist in the repository are kept."""
    merged: list[str] = []
    for label in [*deterministic, *model]:
        if label in existing and label not in merged:
            merged.append(label)
    return merged[:MAX_TOPICS]
