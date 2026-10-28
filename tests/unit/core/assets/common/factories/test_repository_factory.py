# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the generic RepositoryFactory (core/assets/common/factories)."""

from pathlib import Path

import pytest

from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.common.adapters.repositories.postgres_asset_repository import PostgresAssetRepository
from docpipe.core.assets.common.factories.repository_factory import (
    ENV_CONFIG_PATH_KEY,
    RepositoryFactory,
    RepositoryType,
)
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import RepositoryConfigurationException


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch) -> Path:
    """Point the factory at a config file in tmp_path and clear repository env overrides."""
    path = tmp_path / "docling-pipelines-config.yaml"
    monkeypatch.setenv(ENV_CONFIG_PATH_KEY, str(path))
    for name in ("FLOW_REPOSITORY_TYPE", "FLOW_REPOSITORY_BASE_DIR", "DOCUMENTSET_REPOSITORY_TYPE"):
        monkeypatch.delenv(name, raising=False)
    return path


class TestRepositoryConfig:
    """Resolution of type and config from YAML and environment."""

    def test_missing_config_file_falls_back_to_local(self, config_file: Path) -> None:
        assert not config_file.exists()

        assert RepositoryFactory.get_repository_config(asset_type_name="flow") == ("local", {})

    def test_invalid_yaml_falls_back_to_local(self, config_file: Path) -> None:
        config_file.write_text("assets_management: [unclosed", encoding="utf-8")

        assert RepositoryFactory.get_repository_config(asset_type_name="flow") == ("local", {})

    def test_reads_type_and_config_from_yaml(self, config_file: Path) -> None:
        config_file.write_text(
            "assets_management:\n"
            "  documentset_repository:\n"
            "    type: duckdb\n"
            "    config:\n"
            "      database_path: data/sets.duckdb\n",
            encoding="utf-8",
        )

        assert RepositoryFactory.get_repository_config(asset_type_name="documentset") == (
            "duckdb",
            {"database_path": "data/sets.duckdb"},
        )

    def test_environment_overrides_type_and_base_dir(self, config_file: Path, monkeypatch) -> None:
        config_file.write_text(
            "assets_management:\n  flow_repository:\n    type: duckdb\n    config:\n      base_dir: yaml-dir\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("FLOW_REPOSITORY_TYPE", "local")
        monkeypatch.setenv("FLOW_REPOSITORY_BASE_DIR", "env-dir")

        assert RepositoryFactory.get_repository_config(asset_type_name="flow") == ("local", {"base_dir": "env-dir"})


class TestCreateRepository:
    """Repository construction from the resolved configuration."""

    def test_creates_local_repository_with_configured_dir(self, config_file: Path, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("FLOW_REPOSITORY_BASE_DIR", str(tmp_path / "flows"))

        repo = RepositoryFactory.create_repository(asset_type=Flow)

        assert isinstance(repo, LocalAssetRepository)
        assert (tmp_path / "flows").is_dir()

    def test_runtime_overrides_win_over_configuration(self, config_file: Path, tmp_path: Path) -> None:
        config_file.write_text(
            "assets_management:\n  documentset_repository:\n    type: local\n    config:\n      base_dir: unused\n",
            encoding="utf-8",
        )
        database_path = str(tmp_path / "override.duckdb")

        repo = RepositoryFactory.create_repository(
            asset_type=DocumentSet, adapter_name="DUCKDB", config_override={"database_path": database_path}
        )

        assert isinstance(repo, DuckDBAssetRepository)
        assert repo.health_check()["details"]["database_path"] == database_path

    def test_unknown_type_is_rejected(self, config_file: Path) -> None:
        with pytest.raises(RepositoryConfigurationException, match="Invalid repository type: 'tape'"):
            RepositoryFactory.create_repository(asset_type=Flow, adapter_name="tape")

    def test_type_valid_but_missing_from_registry_is_rejected(self, config_file: Path) -> None:
        class InconsistentFactory(RepositoryFactory):
            @classmethod
            def _get_valid_types(cls) -> list[str]:
                return ["local", "remote"]

        with pytest.raises(RepositoryConfigurationException, match="'remote' not found in registry"):
            InconsistentFactory.create_repository(asset_type=Flow, adapter_name="remote")

    def test_construction_error_is_wrapped(self, config_file: Path) -> None:
        with pytest.raises(RepositoryConfigurationException, match="Failed to instantiate repository 'duckdb'") as exc:
            RepositoryFactory.create_repository(asset_type=DocumentSet, adapter_name="duckdb")

        assert exc.value.__cause__ is not None

    def test_configuration_exception_from_repository_passes_through(self, config_file: Path, monkeypatch) -> None:
        original = RepositoryConfigurationException("bad base_dir", repository_type="local", valid_types=["local"])

        def _raise(*, asset_type, config):
            raise original

        monkeypatch.setattr(LocalAssetRepository, "from_config", _raise)

        with pytest.raises(RepositoryConfigurationException) as exc_info:
            RepositoryFactory.create_repository(asset_type=Flow)

        assert exc_info.value is original

    def test_available_types(self) -> None:
        assert RepositoryFactory.get_available_repository_types() == {
            RepositoryType.LOCAL: LocalAssetRepository,
            RepositoryType.DUCKDB: DuckDBAssetRepository,
            RepositoryType.POSTGRES: PostgresAssetRepository,
        }
