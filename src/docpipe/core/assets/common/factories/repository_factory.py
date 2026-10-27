"""Factory for creating repository instances for all asset types.

Provides centralized repository creation based on environment configuration.
Supports multiple repository types through the Abstract Factory pattern with
registry-based extensibility.

This factory bridges the gap between configuration-based repository selection
(from docling-pipelines-config.yaml) and the unified asset architecture's
dependency injection pattern.

Architecture:
    - AbstractRepositoryType: Base enum for all repository types
    - RepositoryType: Concrete repository types (LOCAL, DUCKDB, POSTGRES)
    - get_available_repository_types(): Registry mapping types to implementation classes
    - create_repository(): Generic factory method using registry pattern


"""

import os
from enum import Enum
from pathlib import Path
from typing import TypeVar

import yaml

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.common.domain.models.asset import Asset
from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.core.constants.constants import _find_project_root
from docpipe.exceptions.docpipe_exceptions import RepositoryConfigurationException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=Asset)


class AbstractRepositoryType(Enum):
    """Base enumeration for repository types.

    Empty base class that allows different implementations to define their own
    repository types without conflicts. Can be extended to add custom repository
    types in derived implementations.
    """


class RepositoryType(AbstractRepositoryType):
    """Enumeration of available repository types in OSS."""

    LOCAL = "local"
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"
ENV_CONFIG_PATH_KEY = "DOCPIPE_CONFIG_PATH"


class RepositoryFactory:
    """Factory for creating AssetRepository instances for any asset type.

    Enables switching between repository implementations via environment
    configuration. Follows the Abstract Factory pattern for extensibility.

    Configuration precedence:
        1. Environment variables
        2. docling-pipelines-config.yaml
        3. Built-in defaults

    YAML Configuration (docling-pipelines-config.yaml):
        assets_management:
          flow_repository:
            type: local
            config:
              base_dir: sample_flows
          documentset_repository:
            type: postgres
            config:
              postgres:            # falls back to DOCPIPE_POSTGRES_* env vars
                host: localhost
                database: docpipe

    Environment Variables:
        FLOW_REPOSITORY_TYPE: Repository type for flows (default: "local")
        FLOW_REPOSITORY_BASE_DIR: Directory for local flow storage
        DOCUMENTSET_REPOSITORY_TYPE / DOCUMENTLIBRARY_REPOSITORY_TYPE: e.g. "duckdb" or "postgres"
    """

    @classmethod
    def get_available_repository_types(cls) -> dict[AbstractRepositoryType, type]:
        """Get available repository types and their implementation classes.

        Returns a mapping of repository type enums to their corresponding
        AssetRepository implementation classes. This enables dynamic repository
        instantiation and allows extended implementations to add additional
        repository types by overriding this method.

        Note:
            This is a classmethod (not staticmethod) to support inheritance.
            When a subclass overrides this method, other methods in the class
            will automatically use the subclass's version via the cls parameter.

        Returns:
            Dictionary mapping AbstractRepositoryType to repository class

        Example:
            {
                RepositoryType.LOCAL:    LocalAssetRepository,
                RepositoryType.DUCKDB:   DuckDBAssetRepository,
                RepositoryType.POSTGRES: PostgresAssetRepository,
            }
        """
        from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
        from docpipe.core.assets.common.adapters.repositories.postgres_asset_repository import (
            PostgresAssetRepository,
        )

        return {
            RepositoryType.LOCAL: LocalAssetRepository,
            RepositoryType.DUCKDB: DuckDBAssetRepository,
            RepositoryType.POSTGRES: PostgresAssetRepository,
        }

    @classmethod
    def _get_valid_types(cls) -> list[str]:
        """Get list of valid repository type values.

        Note:
            Uses cls.get_available_repository_types() instead of
            RepositoryFactory.get_available_repository_types() to ensure
            subclass overrides are respected.

        Returns:
            List of valid repository type strings from available repository types
        """
        available_types = cls.get_available_repository_types()
        return [repo_type.value for repo_type in available_types.keys()]

    @staticmethod
    def _load_yaml_config() -> dict:
        """Load configuration from YAML file.

        Returns:
            Dictionary containing YAML configuration, or empty dict if file not found
        """
        config_path = Path(os.getenv(ENV_CONFIG_PATH_KEY, str(DEFAULT_CONFIG_PATH)))
        if not config_path.exists():
            return {}

        try:
            with Path(config_path).open() as file:
                yaml_config = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            logger.warning("Invalid repository YAML configuration at %s: %s", config_path, exc)
            return {}

        return yaml_config or {}

    @staticmethod
    def get_repository_config(*, asset_type_name: str) -> tuple[str, dict]:
        """Get repository configuration from environment and YAML for a specific asset type.

        Args:
            asset_type_name: Name of asset type (e.g., "flow", "document_set")

        Returns:
            Tuple of (repository_type_string, config_dict)
        """
        yaml_config = RepositoryFactory._load_yaml_config()
        assets_config = yaml_config.get("assets_management", {}) or {}
        repo_config = assets_config.get(f"{asset_type_name}_repository", {}) or {}

        # Environment variable pattern: FLOW_REPOSITORY_TYPE, DOCUMENT_SET_REPOSITORY_TYPE, etc.
        env_type_key = f"{asset_type_name.upper()}_REPOSITORY_TYPE"
        env_base_dir_key = f"{asset_type_name.upper()}_REPOSITORY_BASE_DIR"

        repo_type_str = os.getenv(env_type_key, repo_config.get("type", RepositoryType.LOCAL.value))
        resolved_config = repo_config.get("config", {}) or {}

        # Allow environment variable to override base_dir
        if env_base_dir_key in os.environ:
            resolved_config["base_dir"] = os.environ[env_base_dir_key]

        return repo_type_str, resolved_config

    @classmethod
    def create_repository(
        cls,
        *,
        asset_type: type[T],
        adapter_name: str | None = None,
        config_override: dict | None = None,
    ) -> AssetRepository[T]:
        """Create a repository for the specified asset type based on configuration.

        Uses a registry pattern to dynamically instantiate repository implementations.
        Each repository class implements from_config() to handle its own construction.

        Args:
            asset_type: The asset type class (Flow, DocumentSet, DocumentLibrary, etc.)
            adapter_name: Optional runtime override for the adapter/repository type.
                          When supplied it takes precedence over YAML/env config.
                          Use this when the caller has a runtime value (e.g.
                          global_config.metadata_storage_type from a flow).
            config_override: Optional dict of config values that are merged on top of
                             the YAML/env resolved config. Individual keys in this dict
                             take precedence over YAML. Use this when the caller has
                             runtime config values (e.g. database_path from an operator).

        Note:
            This is a classmethod to support inheritance. When called on a subclass,
            it will use the subclass's get_available_repository_types() registry.

        Returns:
            AssetRepository[T]: Configured repository instance for the asset type

        Raises:
            RepositoryConfigurationException: If repository type is invalid
                                             or not yet implemented

        Example:
            from docpipe.core.assets.flows.domain.models.flow import Flow
            flow_repo = RepositoryFactory.create_repository(asset_type=Flow)

            # With runtime override:
            repo = RepositoryFactory.create_repository(
                asset_type=DocumentSet, adapter_name=metadata_storage_type
            )
        """
        config_key = asset_type.get_config_key()
        repo_type_str, repository_config = cls.get_repository_config(asset_type_name=config_key)

        # Runtime override wins over YAML/env
        if adapter_name is not None:
            repo_type_str = adapter_name

        # Merge caller-supplied config on top of YAML/env resolved config
        if config_override:
            repository_config = {**repository_config, **config_override}

        available_types = cls.get_available_repository_types()
        valid_types = cls._get_valid_types()

        logger.info("Creating %s repository of type: '%s'", config_key, repo_type_str)

        if repo_type_str.lower() not in valid_types:
            logger.error("Invalid repository type: '%s'. Must be one of: %s", repo_type_str, ", ".join(valid_types))
            raise RepositoryConfigurationException(
                f"Invalid repository type: '{repo_type_str}'. Must be one of: {', '.join(valid_types)}",
                repository_type=repo_type_str,
                valid_types=valid_types,
            )

        # Find matching repository type enum from registry
        repository_type = None
        for repo_enum in available_types.keys():
            if repo_enum.value == repo_type_str.lower():
                repository_type = repo_enum
                break

        if not repository_type:
            raise RepositoryConfigurationException(
                f"Repository type '{repo_type_str}' not found in registry",
                repository_type=repo_type_str,
                valid_types=valid_types,
            )

        repository_class = available_types[repository_type]

        try:
            return repository_class.from_config(asset_type=asset_type, config=repository_config)  # type: ignore[attr-defined]
        except RepositoryConfigurationException:
            raise
        except Exception as e:
            raise RepositoryConfigurationException(
                f"Failed to instantiate repository '{repository_type.value}' for {config_key}: {e}",
                repository_type=repository_type.value,
                valid_types=valid_types,
            ) from e
