"""
Application-level dependency providers for FastAPI.

This module provides dependency injection for job management services,
flow services, project services, and other application-level components.
"""

from functools import lru_cache

from fastapi import Depends

from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.core.assets.common.domain.ports.attachment_repository import AttachmentRepository
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.core.assets.common.factories.repository_factory import RepositoryFactory, RepositoryType
from docpipe.core.assets.document_libraries.application.services.document_library_service import (
    DocumentLibraryService,
)
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.assets.document_sets.domain.ports.data_store import DocumentSetStorage as DocumentSetDataStore
from docpipe.core.assets.document_sets.domain.types import DataStoreConfig
from docpipe.core.assets.document_sets.factories import DataStoreFactory
from docpipe.core.assets.flows.application.services import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.core.event_streaming.factory import EventStreamingFactory
from docpipe.core.event_streaming.mapping_service import EventMappingService
from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
from docpipe.core.job_management.application.services import JobManagementService
from docpipe.core.job_management.domain.ports import JobStatsService
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.ports.project_repository import ProjectRepository
from docpipe.core.projects.factories.project_repository_factory import ProjectRepositoryFactory


@lru_cache(maxsize=1)
def get_job_stats_service() -> JobStatsService:
    """
    Dependency provider for job stats service (singleton).

    Returns:
        JobStatsService: Configured service instance (cached singleton)
    """
    factory = get_default_factory()
    return factory.create_job_stats_service()


@lru_cache(maxsize=1)
def get_flow_repository() -> AssetRepository[Flow]:
    """
    Dependency provider for Flow Repository (singleton).

    Uses RepositoryFactory to create repository based on configuration from
    docling-pipelines-config.yaml. This enables:
    - OSS: LocalAssetRepository[Flow] (filesystem-based)

    Returns:
        AssetRepository[Flow]: Configured flow repository instance (cached singleton)
    """
    return RepositoryFactory.create_repository(asset_type=Flow)


def get_flow_service(
    repository: AssetRepository[Flow] = Depends(get_flow_repository),  # noqa: B008
    job_stats_service: JobStatsService = Depends(get_job_stats_service),  # noqa: B008
) -> FlowService:
    """Dependency provider for flow service.

    Args:
        repository: Injected repository instance
        job_stats_service: Injected job stats service for cascade-deleting job runs on flow delete

    Returns:
        FlowService: Service instance with injected repository and job stats service
    """
    return FlowService(repository=repository, job_stats_service=job_stats_service)


@lru_cache(maxsize=1)
def get_event_mapping_service() -> EventMappingService:
    """Return the process-wide filesystem-backed event mapping service."""
    return EventStreamingFactory.create_event_mapping_service()


@lru_cache(maxsize=1)
def get_job_management_service(flow_service: FlowService = Depends(get_flow_service)) -> JobManagementService:  # noqa: B008
    """
    Dependency provider for job management service (singleton).

    Returns:
        JobManagementService: Configured service instance (cached singleton)
    """
    factory = get_default_factory()
    return factory.create_job_management_service(flow_service=flow_service)


@lru_cache(maxsize=1)
def get_project_repository() -> ProjectRepository:
    """Dependency provider for ProjectRepository (singleton).

    Delegates path resolution to ProjectRepositoryFactory (env var → YAML config → default).

    Returns:
        ProjectRepository: LocalProjectRepository instance (filesystem-backed, cached singleton)
    """
    return ProjectRepositoryFactory.create_repository()


def get_project_service(
    repository: ProjectRepository = Depends(get_project_repository),  # noqa: B008
    flow_repository: AssetRepository[Flow] = Depends(get_flow_repository),  # noqa: B008
    flow_service: FlowService = Depends(get_flow_service),  # noqa: B008
    job_stats_service: JobStatsService = Depends(get_job_stats_service),  # noqa: B008
) -> ProjectService:
    """
    Dependency provider for ProjectService.

    Injects the ProjectRepository, flow repository (for flow_count reads),
    FlowService (for cascade-deletion of flows on project delete), and
    JobStatsService (for job run summary enrichment on project flow lists).

    Args:
        repository: Injected ProjectRepository singleton
        flow_repository: Injected flow repository singleton (read-only)
        flow_service: Injected FlowService for cascade-deleting linked flows
        job_stats_service: Injected JobStatsService for job run summary enrichment

    Returns:
        ProjectService: Service instance with injected dependencies
    """
    return ProjectService(
        repository=repository,
        flow_repository=flow_repository,
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )


@lru_cache(maxsize=1)
def get_document_set_repository() -> AssetRepository[DocumentSet]:
    """
    Dependency provider for DocumentSet Repository (singleton).

    Uses RepositoryFactory to create repository based on configuration from
    docling-pipelines-config.yaml. This enables:
    - DuckDBAssetRepository[DocumentSet] (type: duckdb, single-process)
    - PostgresAssetRepository[DocumentSet] (type: postgres, multi-replica safe)

    Returns:
        AssetRepository[DocumentSet]: Configured document set repository instance (cached singleton)
    """
    return RepositoryFactory.create_repository(asset_type=DocumentSet)


@lru_cache(maxsize=1)
def get_document_set_data_store() -> DocumentSetDataStore:
    """
    Dependency provider for DocumentSet Data Store (singleton).

    Creates the data store for PyArrow table operations. This is separate from
    the metadata repository as it handles document content storage.

    The adapter name and database path are resolved from
    docling-pipelines-config.yaml (assets_management.document_set_repository),
    keeping the API DI provider consistent with the operator's YAML-driven config.
    Falls back to "duckdb" / DOCUMENT_SET_DEFAULT_DB_PATH if not configured.

    Returns:
        DocumentSetDataStore: Configured data store instance (cached singleton)
    """
    from typing import cast

    _, repo_config = RepositoryFactory.get_repository_config(asset_type_name=DocumentSet.get_config_key())
    adapter_name: str = repo_config.get("storage_adapter", RepositoryType.DUCKDB.value)
    database_path: str = repo_config.get("database_path", DocpipeConstants.DOCUMENT_SET_DEFAULT_DB_PATH)
    data_config: DataStoreConfig = {"database_path": database_path}
    data_store = DataStoreFactory.create(adapter_name=adapter_name, config=data_config)
    return cast(DocumentSetDataStore, data_store)


@lru_cache(maxsize=1)
def get_document_set_attachment_repository() -> AttachmentRepository:
    """Dependency provider for DocumentSet AttachmentRepository (singleton).

    Uses the same adapter name and database path resolved for the document set
    repository so that the attachment KV store lives alongside the metadata store.
    Falls back to "duckdb" / DOCUMENT_SET_DEFAULT_DB_PATH if not configured.

    When the document set repository type is ``postgres`` the attachments are
    stored in PostgreSQL as well (same connection config), matching what
    ``DocumentSetOperator`` writes during flow runs.

    Returns:
        AttachmentRepository: Configured attachment repository instance (cached singleton)
    """
    repo_type, repo_config = RepositoryFactory.get_repository_config(asset_type_name=DocumentSet.get_config_key())
    database_path: str = repo_config.get("database_path", DocpipeConstants.DOCUMENT_SET_DEFAULT_DB_PATH)
    if repo_type.lower() == RepositoryType.POSTGRES.value:
        return AttachmentRepositoryFactory.create(
            adapter_name=RepositoryType.POSTGRES.value,
            config={**repo_config, "database_path": database_path},
        )
    adapter_name: str = repo_config.get("storage_adapter", RepositoryType.DUCKDB.value)
    return AttachmentRepositoryFactory.create(
        adapter_name=adapter_name,
        config={"database_path": database_path},
    )


def get_document_set_service(
    repository: AssetRepository[DocumentSet] = Depends(get_document_set_repository),  # noqa: B008
    data_store: DocumentSetDataStore = Depends(get_document_set_data_store),  # noqa: B008
    attachment_repository: AttachmentRepository = Depends(get_document_set_attachment_repository),  # noqa: B008
) -> DocumentSetService:
    """Dependency provider for document set service.

    Args:
        repository: Injected repository instance (metadata operations)
        data_store: Injected data store instance (PyArrow table operations)
        attachment_repository: Injected attachment repository instance

    Returns:
        DocumentSetService: Service instance with injected dependencies
    """
    return DocumentSetService(
        metadata_repository=repository,
        data_store=data_store,
        attachment_repository=attachment_repository,
    )


@lru_cache(maxsize=1)
def get_document_library_repository() -> AssetRepository[DocumentLibrary]:
    """Dependency provider for DocumentLibrary Repository (singleton).

    Uses RepositoryFactory to create repository based on configuration from
    docling-pipelines-config.yaml.

    Returns:
        AssetRepository[DocumentLibrary]: Configured repository instance (cached singleton)
    """
    return RepositoryFactory.create_repository(asset_type=DocumentLibrary)


def get_document_library_service(
    repository: AssetRepository[DocumentLibrary] = Depends(get_document_library_repository),  # noqa: B008
) -> DocumentLibraryService:
    """Dependency provider for document library service.

    Args:
        repository: Injected repository instance

    Returns:
        DocumentLibraryService: Service instance with injected repository
    """
    return DocumentLibraryService(repository=repository)


def get_custom_operator_service() -> CustomOperatorService:
    """Dependency provider for custom operator service.

    Returns:
        CustomOperatorService instance
    """
    return CustomOperatorService()
