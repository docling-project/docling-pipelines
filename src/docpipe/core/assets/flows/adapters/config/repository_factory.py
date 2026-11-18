"""Factory for creating repository instances.

Provides centralized repository creation based on environment configuration.
Supports multiple repository types through the Abstract Factory pattern.
"""

import logging
import os
from enum import Enum
from pathlib import Path

import yaml

from docpipe.core.assets.flows.adapters.repositories.local.local_flow_repository import LocalFlowRepository
from docpipe.core.assets.flows.domain.ports.flow_repository import FlowRepository
from docpipe.core.constants import EnvironmentVariables
from docpipe.exceptions.docpipe_exceptions import RepositoryConfigurationException
from docpipe.utils.infrastructure.config_utils import DEFAULT_CONFIG_PATH

logger = logging.getLogger(__name__)


class RepositoryType(Enum):
    """Enumeration of available repository types."""

    LOCAL = "local"


class RepositoryFactory:
    """Factory for creating FlowRepository instances.

    Enables switching between repository implementations via environment
    configuration. Follows the Abstract Factory pattern for extensibility.

    Configuration precedence:
        1. Environment variables
        2. docling-pipelines-config.yaml
        3. Built-in defaults

    Environment Variables:
        FLOW_REPOSITORY_TYPE: Repository type (default: "local")
                             Valid values: "local"
        LOCAL_FLOWS_DIR: Directory for local repository storage
                        Overrides yaml/base default when set
    """

    @staticmethod
    def _get_valid_types() -> list[str]:
        """Get list of valid repository type values.

        Returns:
            List of valid repository type strings from RepositoryType enum
        """
        return [t.value for t in RepositoryType]

    @staticmethod
    def _load_yaml_config() -> dict:
        """Load and return the raw YAML configuration dict from the config file.

        Returns:
            Parsed YAML contents, or an empty dict when the file is absent or unreadable.
        """
        config_path = Path(os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(DEFAULT_CONFIG_PATH)))
        if not config_path.exists():
            return {}

        try:
            with config_path.open() as file:
                yaml_config = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            logger.warning("Invalid repository YAML configuration at %s: %s", config_path, exc)
            return {}

        return yaml_config or {}

    @staticmethod
    def _get_repository_config() -> tuple[str, dict]:
        """Resolve repository type and config from YAML and environment variables.

        Returns:
            Tuple of (repository_type_string, config_dict).
        """
        yaml_config = RepositoryFactory._load_yaml_config()
        assets_config = yaml_config.get("assets_management", {}) or {}
        repo_config = assets_config.get("flow_repository", {}) or {}

        repo_type_str = os.getenv("FLOW_REPOSITORY_TYPE", repo_config.get("type", RepositoryType.LOCAL.value))
        resolved_config = repo_config.get("config", {}) or {}

        return repo_type_str, resolved_config

    @staticmethod
    def create_flow_repository() -> FlowRepository:
        """Create a flow repository based on environment configuration and docling-pipelines-config.yaml.

        Returns:
            FlowRepository: Configured repository instance

        Raises:
            RepositoryConfigurationException: If repository type is invalid
                                             or not yet implemented
        """
        repo_type_str, repository_config = RepositoryFactory._get_repository_config()
        valid_types = RepositoryFactory._get_valid_types()

        logger.info("Creating flow repository of type: '%s'", repo_type_str)

        if repo_type_str.lower() not in valid_types:
            logger.info("Invalid repository type: '%s'. Must be one of: %s", repo_type_str, ", ".join(valid_types))
            raise RepositoryConfigurationException(
                f"Invalid repository type: '{repo_type_str}'. Must be one of: {', '.join(valid_types)}",
                repository_type=repo_type_str,
                valid_types=valid_types,
            )

        repository_type = RepositoryType(repo_type_str.lower())

        match repository_type:
            case RepositoryType.LOCAL:
                enable_locking = repository_config.get("enable_locking", True)
                return LocalFlowRepository(enable_locking=enable_locking)
            case _:
                raise RepositoryConfigurationException(
                    f"Repository type '{repository_type.value}' is not yet implemented",
                    repository_type=repository_type.value,
                    valid_types=valid_types,
                )

    @staticmethod
    def create_default_flow_repository() -> FlowRepository:
        """Create a FlowRepository with default configuration sources."""
        logger.info("Creating default FlowRepository")
        return RepositoryFactory.create_flow_repository()
