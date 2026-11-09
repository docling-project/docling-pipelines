# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ProjectRepositoryFactory.

Covers the three resolution paths for base_dir:
  1. PROJECT_REPOSITORY_BASE_DIR environment variable
  2. projects_management.project_repository.config.base_dir in YAML config
  3. Built-in adapter default (neither env var nor YAML configured)
"""

from pathlib import Path

import pytest
import yaml

from docpipe.core.projects.adapters.repositories.local.local_project_repository import (
    LocalProjectRepository,
)
from docpipe.core.projects.factories.project_repository_factory import (
    ENV_PROJECT_REPOSITORY_BASE_DIR,
    ProjectRepositoryFactory,
)
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


@pytest.fixture(autouse=True)
def reset_config_loader():
    """Clear the DocpipeConfigLoader cache before and after each test."""
    DocpipeConfigLoader.reset()
    yield
    DocpipeConfigLoader.reset()


# ── helpers ──────────────────────────────────────────────────────────────


def _write_yaml(path, content: dict) -> None:
    """Write a dict as YAML to *path*."""
    with Path(path).open("w") as fh:
        yaml.safe_dump(content, fh)


# ── env var path ──────────────────────────────────────────────────────────


class TestEnvVarResolution:
    """ENV_PROJECT_REPOSITORY_BASE_DIR takes highest priority."""

    def test_env_var_sets_base_dir(self, tmp_path, monkeypatch):
        """Factory uses the directory from the env var."""
        target = tmp_path / "env-projects"
        target.mkdir()
        monkeypatch.setenv(ENV_PROJECT_REPOSITORY_BASE_DIR, str(target))

        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)
        assert repo._base_dir == target


# ── YAML config path ──────────────────────────────────────────────────────


class TestYAMLConfigResolution:
    """YAML config is used when no env var is set."""

    def test_yaml_config_sets_base_dir(self, tmp_path, monkeypatch):
        """Factory reads base_dir from the YAML config file."""
        yaml_dir = tmp_path / "yaml-projects"
        yaml_dir.mkdir()

        config_path = tmp_path / "config.yaml"
        _write_yaml(
            config_path,
            {"projects_management": {"project_repository": {"config": {"base_dir": str(yaml_dir)}}}},
        )

        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)
        assert repo._base_dir == yaml_dir

    def test_yaml_missing_projects_section_falls_through(self, tmp_path, monkeypatch):
        """YAML without projects_management section → adapter default."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"some_other_section": {}})

        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        repo = ProjectRepositoryFactory.create_repository()

        # Should still be a LocalProjectRepository — just using its own default
        assert isinstance(repo, LocalProjectRepository)

    def test_yaml_config_missing_base_dir_key_falls_through(self, tmp_path, monkeypatch):
        """YAML has the section but no base_dir key → adapter default."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(
            config_path,
            {"projects_management": {"project_repository": {"config": {}}}},
        )

        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)

    def test_invalid_yaml_falls_through_to_default(self, tmp_path, monkeypatch):
        """Malformed YAML does not raise — factory falls through to the adapter default."""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("key: [\n  bad yaml")  # intentionally broken

        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        # Should not raise; malformed YAML is caught and logged internally
        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)

    def test_config_file_not_found_falls_through(self, tmp_path, monkeypatch):
        """Non-existent config file path → adapter default (no exception)."""
        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "nonexistent.yaml"))

        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)

    def test_env_var_overrides_yaml_config(self, tmp_path, monkeypatch):
        """Env var wins over YAML config when both are set."""
        env_dir = tmp_path / "from-env"
        env_dir.mkdir()
        yaml_dir = tmp_path / "from-yaml"
        yaml_dir.mkdir()

        config_path = tmp_path / "config.yaml"
        _write_yaml(
            config_path,
            {"projects_management": {"project_repository": {"config": {"base_dir": str(yaml_dir)}}}},
        )

        monkeypatch.setenv(ENV_PROJECT_REPOSITORY_BASE_DIR, str(env_dir))
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        repo = ProjectRepositoryFactory.create_repository()

        assert repo._base_dir == env_dir


# ── Default fallback ─────────────────────────────────────────────────────


class TestDefaultFallback:
    """When neither env var nor YAML is configured, adapter default is used."""

    def test_no_config_returns_local_repository(self, tmp_path, monkeypatch):
        """Factory returns a LocalProjectRepository when nothing is configured."""
        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        # Point DOCPIPE_CONFIG_PATH at a path that does not exist
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        repo = ProjectRepositoryFactory.create_repository()

        assert isinstance(repo, LocalProjectRepository)

    def test_resolve_base_dir_returns_none_when_unconfigured(self, tmp_path, monkeypatch):
        """_resolve_base_dir() returns None when neither env var nor YAML is set."""
        monkeypatch.delenv(ENV_PROJECT_REPOSITORY_BASE_DIR, raising=False)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        result = ProjectRepositoryFactory._resolve_base_dir()

        assert result is None
