# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""ProjectRepositoryFactory — creates a ProjectRepository from config/env.

Resolution order for base_dir (highest priority wins):
1. ``PROJECT_REPOSITORY_BASE_DIR`` environment variable
2. ``projects_management.project_repository.config.base_dir`` in docling-pipelines-config.yaml
3. Built-in default inside LocalProjectRepository (~/Documents/pipeline/projects)

The config file path itself is resolved via ``DOCPIPE_CONFIG_PATH`` env var, falling back
to ``_find_project_root() / "docling-pipelines-config.yaml"``.
"""

import os

from docpipe.core.projects.adapters.repositories.local.local_project_repository import (
    LocalProjectRepository,
)
from docpipe.core.projects.domain.ports.project_repository import ProjectRepository
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Environment variable that overrides the project repository base_dir.
# Mirrors the pattern used for FLOW_REPOSITORY_BASE_DIR in RepositoryFactory.
ENV_PROJECT_REPOSITORY_BASE_DIR = "PROJECT_REPOSITORY_BASE_DIR"


class ProjectRepositoryFactory:
    """Factory for creating ProjectRepository instances.

    Reads storage configuration from the shared docling-pipelines-config.yaml
    under the ``projects_management`` section, with environment variable override
    support — consistent with how RepositoryFactory works for asset repositories.

    YAML configuration (docling-pipelines-config.yaml):

        projects_management:
          project_repository:
            type: local
            config:
              base_dir: /path/to/projects

    Environment variable override:
        PROJECT_REPOSITORY_BASE_DIR=/path/to/projects
    """

    @staticmethod
    def _resolve_base_dir() -> str | None:
        """Resolve base_dir from env var then YAML config.

        Returns:
            Path string if configured, None to use the adapter default.
        """
        # 1. Environment variable wins
        env_val = os.getenv(ENV_PROJECT_REPOSITORY_BASE_DIR)
        if env_val:
            logger.debug("ProjectRepositoryFactory: using base_dir from env var: %s", env_val)
            return env_val

        # 2. YAML config
        cfg = DocpipeConfigLoader.get(key="projects_management", default={})
        base_dir = cfg.get("project_repository", {}).get("config", {}).get("base_dir")
        if base_dir:
            logger.debug("ProjectRepositoryFactory: using base_dir from config: %s", base_dir)
            return base_dir

        # 3. Fall through — adapter uses its own default
        return None

    @classmethod
    def create_repository(cls) -> ProjectRepository:
        """Create and return a configured ProjectRepository.

        Returns:
            LocalProjectRepository pointed at the resolved base_dir.
        """
        base_dir = cls._resolve_base_dir()
        return LocalProjectRepository(base_dir=base_dir) if base_dir else LocalProjectRepository()
