# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import fnmatch
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("pr_topic_labels", ROOT / ".github/scripts/pr_topic_labels.py")
assert SPEC is not None and SPEC.loader is not None
topics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = topics
SPEC.loader.exec_module(topics)


def test_title_type_scope_and_paths_give_labels() -> None:
    labels = topics.deterministic_topics(
        title="fix(api, operators): keep rows",
        paths=[
            "src/docpipe/api/routes/flows.py",
            "tests/unit/api/test_flows.py",
        ],
    )
    assert labels == ["bug", "Backend", "python"]


def test_perf_and_test_titles_map_to_existing_labels() -> None:
    assert topics.deterministic_topics(title="perf: faster merge", paths=[]) == ["enhancement"]
    assert topics.deterministic_topics(title="test: add cases", paths=[]) == ["testing"]


def test_frontend_paths_and_scopes_give_javascript_not_ui_required() -> None:
    labels = topics.deterministic_topics(title="feat(canvas): zoom", paths=["frontend/src/App.tsx"])
    assert labels == ["enhancement", "javascript"]
    assert "UI required" not in topics.TOPIC_LABELS


def test_lock_files_only_give_dependencies() -> None:
    for path in ("uv.lock", "slim/uv.lock", "frontend/package-lock.json"):
        assert topics.deterministic_topics(title="chore: bump", paths=[path]) == ["dependencies"]
    labels = topics.deterministic_topics(
        title="chore: bump", paths=["frontend/package-lock.json", "frontend/package.json"]
    )
    assert labels == ["dependencies", "javascript"]


def test_ci_paths_give_ci() -> None:
    labels = topics.deterministic_topics(
        title="chore: x", paths=[".github/workflows/ci.yml", ".pre-commit-config.yaml"]
    )
    assert labels == ["ci"]


def test_testing_label_only_when_all_source_changes_are_tests() -> None:
    assert topics.deterministic_topics(title="chore: x", paths=["tests/unit/a.py", "tests/unit/b.py"]) == ["testing"]
    assert "testing" not in topics.deterministic_topics(title="chore: x", paths=["tests/unit/a.py", "src/docpipe/a.py"])


def test_documentation_label_only_when_all_source_changes_are_docs() -> None:
    labels = topics.deterministic_topics(title="chore: update guide", paths=["docs/guides/X.md", "README.md"])
    assert labels == ["documentation"]
    labels = topics.deterministic_topics(
        title="chore: update", paths=["docs/guides/X.md", "src/docpipe/cli/docpipe_cli.py"]
    )
    assert "documentation" not in labels
    # A lock file does not count as source.
    labels = topics.deterministic_topics(title="chore: update", paths=["docs/guides/X.md", "uv.lock"])
    assert labels == ["dependencies", "documentation"]


def test_unknown_title_types_and_scopes_add_nothing() -> None:
    assert topics.deterministic_topics(title="chore(release): 2.0", paths=[]) == []
    assert topics.deterministic_topics(title="Not a conventional title", paths=[]) == []
    assert topics.deterministic_topics(title="feat(unknown): x", paths=[]) == ["enhancement"]


def test_model_topics_are_validated_and_limited() -> None:
    with pytest.raises(ValueError, match="unknown topic"):
        topics.parse_model_topics(["wontfix"])
    with pytest.raises(ValueError, match="unknown topic"):
        topics.parse_model_topics(["UI required"])
    with pytest.raises(ValueError, match="list"):
        topics.parse_model_topics("bug")
    assert topics.parse_model_topics(None) == []
    assert topics.parse_model_topics(["bug", "bug", "security", "ci", "python"]) == ["bug", "security", "ci"]


def test_only_existing_repository_labels_are_selected() -> None:
    selected = topics.select_topics(
        deterministic=["bug", "Backend"], model=["Backend", "security"], existing={"bug", "security"}
    )
    assert selected == ["bug", "security"]


def test_selection_is_capped() -> None:
    labels = list(topics.TOPIC_LABELS)
    assert len(topics.select_topics(deterministic=labels, model=[], existing=set(labels))) == topics.MAX_TOPICS


def test_every_title_and_path_label_is_in_the_allowlist() -> None:
    mapped = {
        *topics.TYPE_LABELS.values(),
        *topics.SCOPE_LABELS.values(),
        *(label for _, label in topics.PATH_LABELS),
    }
    assert mapped <= set(topics.TOPIC_LABELS)


def test_every_path_rule_matches_a_file_in_the_repository() -> None:
    # A renamed directory would silently stop adding its label.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    if not tracked:
        pytest.skip("not a git checkout")
    for pattern, label in topics.PATH_LABELS:
        assert any(fnmatch.fnmatchcase(path, pattern) for path in tracked), (pattern, label)


def test_triage_prompt_lists_exactly_the_allowed_labels() -> None:
    # The model answer is validated against TOPIC_LABELS: a label missing from
    # the prompt is never proposed, an extra one makes the answer invalid.
    prompt = (ROOT / ".github/ai-triage/triage-prompt.md").read_text("utf-8")
    listed = prompt.split("Use only these names:", 1)[1].split(".\n", 1)[0]
    assert set(re.findall(r"`([^`]+)`", listed)) == set(topics.TOPIC_LABELS)
