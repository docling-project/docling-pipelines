# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
JobManagementFactory - Dependency injection and wiring

This factory creates and wires together all components of the job management
system following hexagonal architecture principles.

Configuration:
- Supports multiple storage backends (in-memory, pickle, PostgreSQL, etc.)
- Supports multiple framework adapters (default, Kubernetes, Nomad, etc.)
- Environment-based configuration via YAML or environment variables
"""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from docpipe.core.assets.flows.application.services import FlowService
from docpipe.core.constants import DocpipeConfigKeys, EnvironmentVariables
from docpipe.core.job_management.adapters.frameworks import DefaultJobRunManager
from docpipe.core.job_management.adapters.services import JobTrackerService
from docpipe.core.job_management.adapters.stores import (
    InMemoryJobStatsStore,
    JsonJobStatsStore,
)
from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore
from docpipe.core.job_management.adapters.stores.postgres.database import (
    get_postgres_connection_string,
    run_migrations,
)
from docpipe.core.job_management.application.services import (
    JobManagementService,
    NodeStatsAggregator,
)
from docpipe.core.job_management.domain.ports import (
    JobRunManager,
    JobStatsService,
    JobStatsStore,
)
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class StorageBackend(StrEnum):
    """Supported storage backends."""

    IN_MEMORY = "inmemory"
    FILESYSTEM = "filesystem"
    POSTGRESQL = "postgresql"
    DUCKDB = "duckdb"


class FrameworkType(StrEnum):
    """Supported job execution frameworks."""

    DEFAULT = "default"
    # User can add there custom framework here


ENV_JOB_STATS_BASE_DIR_KEY = EnvironmentVariables.DOCPIPE_JOB_STATS_BASE_DIR


class JobManagementFactory:
    """
    Factory for creating job management components with dependency injection.

    This factory handles:
    - Creating storage adapters based on configuration
    - Creating framework adapters based on configuration
    - Wiring dependencies between components
    - Providing singleton instances where appropriate

    Usage:
        # Create factory with configuration
        factory = JobManagementFactory(
            storage_backend=StorageBackend.IN_MEMORY,
            framework_type=FrameworkType.DEFAULT
        )

        # Get fully wired service
        job_stats_service = factory.create_job_stats_service()
        job_management_service = factory.create_job_management_service()
    """

    def __init__(
        self,
        storage_backend: StorageBackend = StorageBackend.IN_MEMORY,
        framework_type: FrameworkType = FrameworkType.DEFAULT,
        config: dict[str, Any] | None = None,
    ):
        """
        Initialize factory with configuration.

        Args:
            storage_backend: Storage backend to use
            framework_type: Framework type to use
            config: Optional configuration dictionary
        """
        self.storage_backend = storage_backend
        self.framework_type = framework_type
        self.config = config or {}

        # Singleton instances
        self._job_stats_store: JobStatsStore | None = None
        self._job_run_manager: JobRunManager | None = None
        self._node_stats_aggregator: NodeStatsAggregator | None = None
        self._job_stats_service: JobStatsService | None = None
        self._job_management_service: JobManagementService | None = None

        logger.info("JobManagementFactory initialized: storage=%s, framework=%s", storage_backend, framework_type)

    def initialize_storage(self) -> None:
        """
        Run one-time storage initialization for the configured backend.

        Currently this applies PostgreSQL schema migrations when PostgreSQL
        job stats storage is selected. Safe to call repeatedly.
        """
        if self.storage_backend != StorageBackend.POSTGRESQL:
            return

        if self.config.get(DocpipeConfigKeys.STORAGE_INITIALIZED, False):
            logger.debug("PostgreSQL job stats storage already initialized; skipping")
            return

        connection_string = get_postgres_connection_string(config=self.config)
        if not connection_string:
            logger.warning(
                "Skipping PostgreSQL job stats store initialization because connection settings are incomplete"
            )
            self.config[DocpipeConfigKeys.STORAGE_INITIALIZED] = True
            return

        should_run_migrations = self.config.get(DocpipeConfigKeys.RUN_MIGRATIONS, True)
        if should_run_migrations:
            logger.info("Running database migrations for PostgreSQL job stats store...")
            run_migrations(connection_string=connection_string, config=self.config)
            logger.info("Database migrations completed for PostgreSQL job stats store")
        else:
            logger.info("Skipping database migrations for PostgreSQL job stats store (run_migrations=False)")

        self.config[DocpipeConfigKeys.STORAGE_INITIALIZED] = True

    def _resolve_filesystem_base_dir(self) -> str | None:
        """
        Resolve the filesystem base directory for worker env propagation.
        Returns:
            Resolved absolute path string, or None if not configured.
        """
        base_dir_override = os.getenv(ENV_JOB_STATS_BASE_DIR_KEY)
        if base_dir_override:
            return base_dir_override

        configured_base_dir = self.config.get(DocpipeConfigKeys.BASE_DIR)
        if configured_base_dir:
            configured_path = Path(configured_base_dir)
            return str(configured_path if configured_path.is_absolute() else configured_path.resolve())

        return None

    def resolve_worker_env(self) -> dict[str, str]:
        """
        Resolve environment variables that need to be propagated to workers.

        Returns:
            Dictionary of environment variables
        """
        env: dict[str, str] = {
            EnvironmentVariables.DOCPIPE_STORAGE_BACKEND: self.storage_backend.value,
            EnvironmentVariables.DOCPIPE_FRAMEWORK_TYPE: self.framework_type.value,
        }

        if self.storage_backend == StorageBackend.FILESYSTEM:
            resolved_base_dir = self._resolve_filesystem_base_dir()
            if resolved_base_dir:
                env[EnvironmentVariables.DOCPIPE_JOB_STATS_BASE_DIR] = resolved_base_dir

        if self.storage_backend == StorageBackend.POSTGRESQL:
            postgres_config_mapping = {
                EnvironmentVariables.DOCPIPE_POSTGRES_HOST: DocpipeConfigKeys.HOST,
                EnvironmentVariables.DOCPIPE_POSTGRES_PORT: DocpipeConfigKeys.PORT,
                EnvironmentVariables.DOCPIPE_POSTGRES_DB: DocpipeConfigKeys.DATABASE,
                EnvironmentVariables.DOCPIPE_POSTGRES_USER: DocpipeConfigKeys.USER,
                EnvironmentVariables.DOCPIPE_POSTGRES_PASSWORD: DocpipeConfigKeys.PASSWORD,  # pragma: allowlist secret
            }

            for env_key, config_key in postgres_config_mapping.items():
                # Use environment variable if set, otherwise fallback to config
                postgres_config = self.config.get(DocpipeConfigKeys.POSTGRES, {})
                val = os.getenv(env_key) or postgres_config.get(config_key)
                if val:
                    env[env_key] = str(val)

        return env

    def create_job_stats_store(self) -> JobStatsStore:
        """
        Create storage adapter based on configuration.

        Supports:
        - IN_MEMORY: Fast in-memory storage (testing/development)
        - FILESYSTEM: Persistent filesystem storage (restart recovery)
        - POSTGRESQL: PostgreSQL database storage (production)
        - DUCKDB: DuckDB embedded database storage (production, no server required)

        Returns:
            JobStatsStore implementation
        """
        if self._job_stats_store is not None:
            return self._job_stats_store

        match self.storage_backend:
            case StorageBackend.IN_MEMORY:
                self._job_stats_store = InMemoryJobStatsStore()
                logger.info("Created InMemoryJobStatsStore")

            case StorageBackend.FILESYSTEM:
                lock_timeout = self.config.get(DocpipeConfigKeys.LOCK_TIMEOUT, 30.0)
                base_dir_override = os.getenv(ENV_JOB_STATS_BASE_DIR_KEY)
                configured_base_dir = self.config.get(DocpipeConfigKeys.BASE_DIR)
                resolved_base_dir = None

                if base_dir_override:
                    resolved_base_dir = Path(base_dir_override)
                elif configured_base_dir:
                    configured_base_dir_path = Path(configured_base_dir)
                    resolved_base_dir = (
                        configured_base_dir_path
                        if configured_base_dir_path.is_absolute()
                        else configured_base_dir_path.resolve()
                    )

                if resolved_base_dir:
                    resolved_base_dir.mkdir(parents=True, exist_ok=True)

                self._job_stats_store = JsonJobStatsStore(
                    base_dir=resolved_base_dir,
                    lock_timeout=lock_timeout,
                )
                logger.info(
                    "Created JsonJobStatsStore: base_dir=%s, base_dir_source=%s, lock_timeout=%ss",
                    resolved_base_dir,
                    "env" if base_dir_override else "config" if configured_base_dir else "default",
                    lock_timeout,
                )

            case StorageBackend.POSTGRESQL:
                self.initialize_storage()
                self._job_stats_store = PostgresJobStatsStore(config=self.config)
                logger.info("Created PostgresJobStatsStore")

            case StorageBackend.DUCKDB:
                from docpipe.core.job_management.adapters.stores.duckdb import DuckDBJobStatsStore

                self._job_stats_store = DuckDBJobStatsStore(config=self.config)
                logger.info("Created DuckDBJobStatsStore")

            case _:
                raise ValueError(f"Unknown storage backend: {self.storage_backend}")

        if self._job_stats_store is None:  # defensive: all branches above either assign or raise
            raise RuntimeError("Job stats store must be initialized")
        return self._job_stats_store

    def create_job_run_manager(self) -> JobRunManager:
        """
        Create framework adapter based on configuration.

        Returns:
            JobRunManager implementation
        """
        if self._job_run_manager is not None:
            return self._job_run_manager

        # Get job_stats_service first (needed by all framework adapters)
        job_stats_service = self.create_job_stats_service()

        match self.framework_type:
            case FrameworkType.DEFAULT:
                self._job_run_manager = DefaultJobRunManager(job_stats_service=job_stats_service)
                logger.info("Created DefaultJobRunManager with JobStatsService")

            case _:
                raise ValueError(f"Unknown framework type: {self.framework_type}")

        return self._job_run_manager

    def create_node_stats_aggregator(self) -> NodeStatsAggregator:
        """
        Create node stats aggregator with dependencies.

        Returns:
            NodeStatsAggregator instance
        """
        if self._node_stats_aggregator is not None:
            return self._node_stats_aggregator

        job_stats_store = self.create_job_stats_store()
        self._node_stats_aggregator = NodeStatsAggregator(job_stats_store=job_stats_store)

        logger.info("Created NodeStatsAggregator")
        return self._node_stats_aggregator

    def create_job_stats_service(self) -> JobStatsService:
        """
        Create job stats service with dependencies.

        Returns:
            JobStatsService implementation
        """
        if self._job_stats_service is not None:
            return self._job_stats_service

        job_stats_store = self.create_job_stats_store()
        node_stats_aggregator = self.create_node_stats_aggregator()

        self._job_stats_service = JobTrackerService(
            job_stats_store=job_stats_store, node_stats_aggregator=node_stats_aggregator
        )

        logger.info("Created JobTrackerService")
        return self._job_stats_service

    def create_job_management_service(self, flow_service: FlowService) -> JobManagementService:
        """
        Create job management service with dependencies.

        Returns:
            JobManagementService instance
        """
        if self._job_management_service is not None:
            return self._job_management_service

        job_stats_service = self.create_job_stats_service()
        job_run_manager = self.create_job_run_manager()

        self._job_management_service = JobManagementService(
            job_stats_service=job_stats_service, job_run_manager=job_run_manager, flow_service=flow_service
        )

        logger.info("Created JobManagementService")
        return self._job_management_service

    @classmethod
    def create_default_factory(cls) -> "JobManagementFactory":
        # Job stats default to in-memory when nothing is configured (unchanged from before DocpipeConfigLoader)
        storage_type, storage_config = DocpipeConfigLoader.get_storage(
            key=DocpipeConfigKeys.JOB_MANAGEMENT, default_type=StorageBackend.IN_MEMORY.value
        )
        job_mgmt_config = DocpipeConfigLoader.get(key=DocpipeConfigKeys.JOB_MANAGEMENT, default={})
        framework_config = job_mgmt_config.get(DocpipeConfigKeys.FRAMEWORK, {})

        try:
            storage_backend = StorageBackend(storage_type)
        except ValueError:
            # Fail fast on invalid backend
            supported = [e.value for e in StorageBackend]
            raise ValueError(
                f"Invalid storage backend '{storage_type}' for job management. Supported backends: {supported}"
            ) from None
        framework_str = framework_config.get(
            DocpipeConfigKeys.TYPE,
            job_mgmt_config.get(DocpipeConfigKeys.FRAMEWORK_TYPE, FrameworkType.DEFAULT.value),
        )
        try:
            framework_type = FrameworkType(framework_str)
        except ValueError as e:
            raise ValueError(
                f"Invalid framework type: {framework_str}. Supported: {[e.value for e in FrameworkType]}"
            ) from e

        # Keep storage settings flat: the store factories read base_dir, lock_timeout and postgres
        # from the top level of self.config.
        merged_config: dict[str, Any] = dict(storage_config or {})
        if DocpipeConfigKeys.POSTGRES in job_mgmt_config:
            merged_config[DocpipeConfigKeys.POSTGRES] = job_mgmt_config[DocpipeConfigKeys.POSTGRES]
        merged_config.update(job_mgmt_config.get(DocpipeConfigKeys.FRAMEWORK_CONFIG, {}) or {})
        merged_config.update(framework_config.get(DocpipeConfigKeys.CONFIG, {}) or {})

        return cls(storage_backend=storage_backend, framework_type=framework_type, config=merged_config)


# Singleton factory instance for convenience
_default_factory: JobManagementFactory | None = None


def get_default_factory() -> JobManagementFactory:
    """
    Get default factory instance (singleton).

    Returns:
        JobManagementFactory instance
    """
    global _default_factory

    if _default_factory is None:
        _default_factory = JobManagementFactory.create_default_factory()

    return _default_factory


def reset_default_factory() -> None:
    """
    Reset default factory instance (useful for testing).
    """
    global _default_factory
    _default_factory = None
