# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for LocalProjectRepository.

These tests use a real temporary directory — no mocking — to verify
the JSON file-per-project storage behaviour end-to-end.
"""

import json

import portalocker
import pytest

from docpipe.core.projects.adapters.repositories.local import local_project_repository
from docpipe.core.projects.adapters.repositories.local.local_project_repository import (
    LocalProjectRepository,
)
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions import LockTimeoutError


@pytest.fixture
def repo(tmp_path) -> LocalProjectRepository:
    """A LocalProjectRepository pointing at a fresh temp directory."""
    return LocalProjectRepository(base_dir=tmp_path)


@pytest.fixture
def saved_project(repo) -> Project:
    """A Project already persisted via the repository."""
    project = Project(project_id="p-001", name="Saved Project", created_by="tester")
    return repo.save(project=project)


class TestLocalProjectRepositorySave:
    """Tests for the save() method."""

    def test_save_creates_json_file(self, repo, tmp_path):
        """save() writes a JSON file named <project_id>.json."""
        project = Project(project_id="abc-123", name="My Project")
        repo.save(project=project)

        assert (tmp_path / "abc-123.json").exists()

    def test_save_returns_same_project(self, repo):
        """save() returns the project instance passed in."""
        project = Project(project_id="r-001", name="Return Test")
        result = repo.save(project=project)
        assert result.project_id == "r-001"

    def test_save_persists_all_fields(self, repo, tmp_path):
        """All non-computed fields are written to disk."""
        project = Project(
            project_id="f-001",
            name="Field Test",
            description="Full data",
            tags=["a", "b"],
            created_by="alice",
            modified_by="bob",
            href="/api/v1/projects/f-001",
        )
        repo.save(project=project)

        raw = json.loads((tmp_path / "f-001.json").read_text())
        assert raw["name"] == "Field Test"
        assert raw["description"] == "Full data"
        assert raw["tags"] == ["a", "b"]
        assert raw["created_by"] == "alice"
        assert raw["modified_by"] == "bob"
        assert raw["href"] == "/api/v1/projects/f-001"

    def test_save_excludes_flow_count(self, repo, tmp_path):
        """flow_count is a computed field and must NOT appear in the JSON file."""
        project = Project(project_id="fc-001", name="Flow Count Test")
        project.flow_count = 42  # artificially set
        repo.save(project=project)

        raw = json.loads((tmp_path / "fc-001.json").read_text())
        assert "flow_count" not in raw

    def test_save_overwrites_existing_file(self, repo, tmp_path):
        """Calling save() twice on the same project replaces the file."""
        project = Project(project_id="ow-001", name="Original Name")
        repo.save(project=project)

        project.name = "Updated Name"
        repo.save(project=project)

        raw = json.loads((tmp_path / "ow-001.json").read_text())
        assert raw["name"] == "Updated Name"

    def test_save_raises_lock_timeout_error_when_lock_held(self, repo, tmp_path, monkeypatch):
        """A lock timeout surfaces as LockTimeoutError, not a raw portalocker exception."""
        monkeypatch.setattr(local_project_repository, "_LOCK_TIMEOUT_SECONDS", 0.2)
        project = Project(project_id="lk-001", name="Locked")

        with portalocker.Lock(
            str(tmp_path / "lk-001.json") + ".lock",
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            timeout=1.0,
        ):
            with pytest.raises(LockTimeoutError) as exc_info:
                repo.save(project=project)

        assert "lk-001" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, portalocker.exceptions.LockException)
        assert not (tmp_path / "lk-001.json").exists()


class TestLocalProjectRepositoryGet:
    """Tests for the get() method."""

    def test_get_returns_project(self, repo, saved_project):
        """get() loads and returns the correct project."""
        result = repo.get(project_id=saved_project.project_id)
        assert result is not None
        assert result.project_id == saved_project.project_id
        assert result.name == saved_project.name

    def test_get_returns_none_for_missing_id(self, repo):
        """get() returns None when no file exists for that ID."""
        result = repo.get(project_id="nonexistent")
        assert result is None

    def test_get_preserves_timestamps(self, repo, saved_project):
        """Timestamps survive a round-trip through the JSON file."""
        result = repo.get(project_id=saved_project.project_id)
        assert result is not None
        assert result.created_on == saved_project.created_on
        assert result.modified_on == saved_project.modified_on

    def test_get_flow_count_defaults_to_zero(self, repo, saved_project):
        """flow_count is not stored; it defaults to 0 on load."""
        result = repo.get(project_id=saved_project.project_id)
        assert result is not None
        assert result.flow_count == 0


class TestLocalProjectRepositoryFindAll:
    """Tests for the find_all() method."""

    def test_find_all_empty_directory(self, repo):
        """find_all() returns an empty list when nothing is stored."""
        assert repo.find_all() == []

    def test_find_all_returns_all_saved_projects(self, repo):
        """find_all() returns one entry per saved project file."""
        for i in range(3):
            repo.save(project=Project(project_id=f"p-{i}", name=f"Project {i}"))

        results = repo.find_all()
        assert len(results) == 3

    def test_find_all_skips_unreadable_files(self, repo, tmp_path):
        """Corrupt JSON files are skipped with a warning, not raised."""
        (tmp_path / "corrupt.json").write_text("{invalid json", encoding="utf-8")
        repo.save(project=Project(project_id="good-1", name="Good Project"))

        results = repo.find_all()

        # Only the valid project comes back
        assert len(results) == 1
        assert results[0].project_id == "good-1"


class TestLocalProjectRepositoryUpdate:
    """Tests for the update() method (delegates to save)."""

    def test_update_overwrites_project(self, repo, saved_project):
        """update() persists new field values."""
        saved_project.name = "Renamed"
        repo.update(project=saved_project)

        reloaded = repo.get(project_id=saved_project.project_id)
        assert reloaded is not None
        assert reloaded.name == "Renamed"


class TestLocalProjectRepositoryDelete:
    """Tests for the delete() method."""

    def test_delete_existing_project(self, repo, saved_project, tmp_path):
        """delete() removes the JSON file and returns True."""
        result = repo.delete(project_id=saved_project.project_id)

        assert result is True
        assert not (tmp_path / f"{saved_project.project_id}.json").exists()

    def test_delete_nonexistent_project_returns_false(self, repo):
        """delete() returns False when the project file does not exist."""
        result = repo.delete(project_id="ghost-id")
        assert result is False

    def test_deleted_project_not_returned_by_get(self, repo, saved_project):
        """After deletion, get() returns None."""
        repo.delete(project_id=saved_project.project_id)
        assert repo.get(project_id=saved_project.project_id) is None

    def test_deleted_project_excluded_from_find_all(self, repo, saved_project):
        """After deletion, find_all() does not include the deleted project."""
        repo.save(project=Project(project_id="keep-1", name="Keep Me"))
        repo.delete(project_id=saved_project.project_id)

        results = repo.find_all()
        ids = [p.project_id for p in results]
        assert saved_project.project_id not in ids
        assert "keep-1" in ids


class TestLocalProjectRepositoryExists:
    """Tests for the exists() method."""

    def test_exists_returns_true_for_saved_project(self, repo, saved_project):
        """exists() returns True when the JSON file is present."""
        assert repo.exists(project_id=saved_project.project_id) is True

    def test_exists_returns_false_for_missing_project(self, repo):
        """exists() returns False when no file exists."""
        assert repo.exists(project_id="no-file") is False

    def test_exists_returns_false_after_delete(self, repo, saved_project):
        """exists() returns False after the project has been deleted."""
        repo.delete(project_id=saved_project.project_id)
        assert repo.exists(project_id=saved_project.project_id) is False


class TestLocalProjectRepositoryExistsByName:
    """Tests for the exists_by_name() method."""

    def test_exists_by_name_returns_true(self, repo, saved_project):
        """exists_by_name() returns True when a project with that name exists."""
        assert repo.exists_by_name(name=saved_project.name) is True

    def test_exists_by_name_returns_false_for_unknown_name(self, repo):
        """exists_by_name() returns False when no matching project is found."""
        assert repo.exists_by_name(name="No Such Name") is False

    def test_exists_by_name_case_sensitive(self, repo, saved_project):
        """Name matching is case-sensitive (mirrors model storage)."""
        assert repo.exists_by_name(name=saved_project.name.lower()) is False


class TestLocalProjectRepositoryDefaultPath:
    """Tests for the default base_dir behaviour."""

    def test_custom_base_dir_is_used(self, tmp_path):
        """Passing base_dir uses that directory for storage."""
        repo = LocalProjectRepository(base_dir=tmp_path / "custom")
        project = Project(project_id="custom-1", name="Custom Dir Test")
        repo.save(project=project)

        assert (tmp_path / "custom" / "custom-1.json").exists()

    def test_directory_is_created_if_missing(self, tmp_path):
        """Nested base_dir is created automatically."""
        deep = tmp_path / "a" / "b" / "c"
        LocalProjectRepository(base_dir=deep)
        assert deep.exists()
