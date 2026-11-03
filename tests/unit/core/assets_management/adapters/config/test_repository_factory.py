"""Tests for RepositoryFactory.
This test module verifies the repository factory behavior with environment
variables and docpipe.yaml-backed configuration.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from docpipe.core.assets.flows.adapters.config.repository_factory import (
    RepositoryFactory,
    RepositoryType,
)
from docpipe.core.assets.flows.adapters.repositories.local.local_flow_repository import (
    LocalFlowRepository,
)
from docpipe.core.assets.flows.domain.ports.flow_repository import FlowRepository
from docpipe.core.constants import EnvironmentVariables
from docpipe.exceptions.docpipe_exceptions import RepositoryConfigurationException


class TestRepositoryFactory:
    """Test suite for RepositoryFactory."""

    def test_create_default_flow_repository_returns_local_repository(self):
        """Test that create_default_flow_repository returns LocalFlowRepository."""
        repository = RepositoryFactory.create_default_flow_repository()

        assert isinstance(repository, LocalFlowRepository)
        assert isinstance(repository, FlowRepository)

    def test_create_flow_repository_with_no_env_var_uses_default(self):
        """Test that when FLOW_REPOSITORY_TYPE is not set, it defaults to LOCAL."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove FLOW_REPOSITORY_TYPE if it exists
            os.environ.pop("FLOW_REPOSITORY_TYPE", None)

            repository = RepositoryFactory.create_flow_repository()

            assert isinstance(repository, LocalFlowRepository)
            assert isinstance(repository, FlowRepository)

    def test_create_flow_repository_with_local_env_var(self):
        """Test that FLOW_REPOSITORY_TYPE=local creates LocalFlowRepository."""
        with patch.dict(os.environ, {"FLOW_REPOSITORY_TYPE": "local"}):
            repository = RepositoryFactory.create_flow_repository()

            assert isinstance(repository, LocalFlowRepository)
            assert isinstance(repository, FlowRepository)

    def test_create_flow_repository_with_invalid_env_var_raises_error(self):
        """Test that invalid FLOW_REPOSITORY_TYPE raises RepositoryConfigurationException."""
        with patch.dict(os.environ, {"FLOW_REPOSITORY_TYPE": "invalid_type"}):
            with pytest.raises(RepositoryConfigurationException) as exc_info:
                RepositoryFactory.create_flow_repository()

            error = exc_info.value
            error_msg = str(error)
            assert "Invalid repository type" in error_msg
            assert "invalid_type" in error_msg
            assert "local" in error_msg
            assert error.repository_type == "invalid_type"
            assert error.valid_types == ["local"]

    def test_create_flow_repository_with_default_env_fallback(self):
        """Test that create_flow_repository defaults to local when env var is unset."""
        with patch.dict(os.environ, {}, clear=True):
            repository = RepositoryFactory.create_flow_repository()

            assert isinstance(repository, LocalFlowRepository)

    def test_create_flow_repository_with_custom_flows_dir(self, monkeypatch):
        """Test that LocalFlowRepository can be created with custom flows_dir via environment."""
        custom_dir = Path("/tmp/test_flows")

        monkeypatch.setenv("LOCAL_FLOWS_DIR", str(custom_dir))
        repository = LocalFlowRepository()

        assert isinstance(repository, LocalFlowRepository)
        assert repository.flows_dir == custom_dir.resolve()

    def test_create_flow_repository_uses_yaml_base_dir_when_env_not_set(self, tmp_path, monkeypatch):
        """Test that repository factory reads base_dir from docpipe.yaml."""
        custom_dir = tmp_path / "yaml_flows"
        config_path = tmp_path / "docpipe.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "assets_management": {
                        "flow_repository": {
                            "type": "local",
                            "config": {"base_dir": str(custom_dir)},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.delenv("LOCAL_FLOWS_DIR", raising=False)
        monkeypatch.delenv("FLOW_REPOSITORY_TYPE", raising=False)
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(config_path))

        repository = RepositoryFactory.create_flow_repository()

        assert isinstance(repository, LocalFlowRepository)
        assert repository.flows_dir == custom_dir.resolve()

    def test_load_yaml_config_falls_back_on_invalid_yaml(self, tmp_path, monkeypatch):
        """Test that a malformed docpipe.yaml is swallowed and an empty config is returned."""
        config_path = tmp_path / "docpipe.yaml"
        config_path.write_text("assets_management: [unterminated", encoding="utf-8")

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(config_path))

        # Should not raise despite the invalid YAML; falls back to an empty config.
        assert RepositoryFactory._load_yaml_config() == {}

    def test_create_flow_repository_env_base_dir_overrides_yaml(self, tmp_path, monkeypatch):
        """Test that LOCAL_FLOWS_DIR overrides docpipe.yaml base_dir."""
        yaml_dir = tmp_path / "yaml_flows"
        env_dir = tmp_path / "env_flows"
        config_path = tmp_path / "docpipe.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "assets_management": {
                        "flow_repository": {
                            "type": "local",
                            "config": {"base_dir": str(yaml_dir)},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(config_path))
        monkeypatch.setenv("LOCAL_FLOWS_DIR", str(env_dir))
        monkeypatch.delenv("FLOW_REPOSITORY_TYPE", raising=False)

        repository = RepositoryFactory.create_flow_repository()

        assert isinstance(repository, LocalFlowRepository)
        assert repository.flows_dir == env_dir.resolve()

    def test_create_flow_repository_with_flows_dir_as_string(self, monkeypatch):
        """Test that LocalFlowRepository accepts flows_dir as string via environment."""
        custom_dir_str = "/tmp/test_flows_string"

        # Set environment variable and create repository
        monkeypatch.setenv("LOCAL_FLOWS_DIR", custom_dir_str)
        repository = LocalFlowRepository()

        assert isinstance(repository, LocalFlowRepository)
        assert isinstance(repository.flows_dir, Path)
        assert repository.flows_dir == Path(custom_dir_str).resolve()

    def test_env_var_is_case_insensitive(self):
        """Test that FLOW_REPOSITORY_TYPE is case-insensitive."""
        test_cases = ["local", "LOCAL", "Local", "LoCAl"]

        for repo_type in test_cases:
            with patch.dict(os.environ, {"FLOW_REPOSITORY_TYPE": repo_type}):
                repository = RepositoryFactory.create_flow_repository()
                assert isinstance(repository, LocalFlowRepository)

    def test_invalid_env_var_is_not_overridable(self):
        """Test that invalid env configuration raises an error without programmatic override."""
        with patch.dict(os.environ, {"FLOW_REPOSITORY_TYPE": "invalid"}):
            with pytest.raises(RepositoryConfigurationException) as exc_info:
                RepositoryFactory.create_flow_repository()

            error = exc_info.value
            assert error.repository_type == "invalid"
            assert error.valid_types == ["local"]

    def test_repository_type_enum_values(self):
        """Test that RepositoryType enum has expected values."""
        assert RepositoryType.LOCAL.value == "local"
        # Verify only expected types exist
        assert len(list(RepositoryType)) == 1
