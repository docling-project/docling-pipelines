"""Unit tests for src/docpipe/api/dependencies.py.

Each provider function is tested in isolation by patching its direct
collaborators (factories, services). No real DB, HTTP, or filesystem I/O.
"""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.api.dependencies import (
    get_document_library_repository,
    get_document_library_service,
    get_document_set_attachment_repository,
    get_document_set_data_store,
    get_document_set_repository,
    get_document_set_service,
    get_flow_repository,
    get_flow_service,
    get_job_management_service,
    get_job_stats_service,
    get_project_repository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_lru_caches() -> None:
    """Clear all @lru_cache caches in the dependencies module so each test
    starts from a clean state."""
    get_job_stats_service.cache_clear()
    get_flow_repository.cache_clear()
    get_job_management_service.cache_clear()
    get_project_repository.cache_clear()
    get_document_set_repository.cache_clear()
    get_document_set_data_store.cache_clear()
    get_document_set_attachment_repository.cache_clear()
    get_document_library_repository.cache_clear()


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all dependency lru_caches before and after every test."""
    _clear_lru_caches()
    yield
    _clear_lru_caches()


# ---------------------------------------------------------------------------
# get_job_stats_service
# ---------------------------------------------------------------------------


class TestGetJobStatsService:
    """get_job_stats_service delegates to the default factory."""

    def test_returns_job_stats_service(self):
        mock_service = MagicMock()
        mock_factory = MagicMock()
        mock_factory.create_job_stats_service.return_value = mock_service

        with patch("docpipe.api.dependencies.get_default_factory", return_value=mock_factory):
            result = get_job_stats_service()

        assert result is mock_service
        mock_factory.create_job_stats_service.assert_called_once()

    def test_is_cached_singleton(self):
        mock_factory = MagicMock()
        mock_factory.create_job_stats_service.return_value = MagicMock()

        with patch("docpipe.api.dependencies.get_default_factory", return_value=mock_factory):
            r1 = get_job_stats_service()
            r2 = get_job_stats_service()

        assert r1 is r2
        mock_factory.create_job_stats_service.assert_called_once()


# ---------------------------------------------------------------------------
# get_flow_repository
# ---------------------------------------------------------------------------


class TestGetFlowRepository:
    """get_flow_repository delegates to RepositoryFactory."""

    def test_returns_repository(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.RepositoryFactory.create_repository", return_value=mock_repo):
            result = get_flow_repository()

        assert result is mock_repo

    def test_is_cached_singleton(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.RepositoryFactory.create_repository", return_value=mock_repo):
            r1 = get_flow_repository()
            r2 = get_flow_repository()

        assert r1 is r2


# ---------------------------------------------------------------------------
# get_flow_service
# ---------------------------------------------------------------------------


class TestGetFlowService:
    """get_flow_service wraps a repository in FlowService."""

    def test_returns_flow_service_with_injected_repository(self):
        from docpipe.core.assets.flows.application.services.flow_service import FlowService

        mock_repo = MagicMock()

        result = get_flow_service(repository=mock_repo)

        assert isinstance(result, FlowService)
        assert result._repository is mock_repo


# ---------------------------------------------------------------------------
# get_project_repository
# ---------------------------------------------------------------------------


class TestGetProjectRepository:
    """get_project_repository delegates to ProjectRepositoryFactory."""

    def test_returns_repository(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.ProjectRepositoryFactory.create_repository", return_value=mock_repo):
            result = get_project_repository()

        assert result is mock_repo

    def test_is_cached_singleton(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.ProjectRepositoryFactory.create_repository", return_value=mock_repo):
            r1 = get_project_repository()
            r2 = get_project_repository()

        assert r1 is r2


# ---------------------------------------------------------------------------
# get_document_set_repository
# ---------------------------------------------------------------------------


class TestGetDocumentSetRepository:
    """get_document_set_repository delegates to RepositoryFactory."""

    def test_returns_repository(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.RepositoryFactory.create_repository", return_value=mock_repo):
            result = get_document_set_repository()

        assert result is mock_repo


# ---------------------------------------------------------------------------
# get_document_set_data_store
# ---------------------------------------------------------------------------


class TestGetDocumentSetDataStore:
    """get_document_set_data_store reads config via get_repository_config
    and creates a data store through DataStoreFactory."""

    def test_returns_data_store_with_defaults_when_config_is_empty(self):
        """When get_repository_config returns an empty config dict the function
        falls back to RepositoryType.DUCKDB and DOCUMENT_SET_DEFAULT_DB_PATH."""
        mock_store = MagicMock()

        with (
            patch("docpipe.api.dependencies.RepositoryFactory.get_repository_config", return_value=("duckdb", {})),
            patch("docpipe.api.dependencies.DataStoreFactory.create", return_value=mock_store) as mock_create,
        ):
            result = get_document_set_data_store()

        assert result is mock_store
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["adapter_name"] == "duckdb"
        assert call_kwargs["config"]["database_path"].endswith("document_sets.duckdb")

    def test_uses_storage_adapter_and_database_path_from_config(self):
        """Explicit values in repo_config are forwarded to DataStoreFactory."""
        mock_store = MagicMock()
        repo_config = {"storage_adapter": "duckdb", "database_path": "/custom/path/ds.duckdb"}

        with (
            patch(
                "docpipe.api.dependencies.RepositoryFactory.get_repository_config",
                return_value=("duckdb", repo_config),
            ),
            patch("docpipe.api.dependencies.DataStoreFactory.create", return_value=mock_store) as mock_create,
        ):
            result = get_document_set_data_store()

        assert result is mock_store
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["adapter_name"] == "duckdb"
        assert call_kwargs["config"]["database_path"] == "/custom/path/ds.duckdb"


# ---------------------------------------------------------------------------
# get_document_set_attachment_repository
# ---------------------------------------------------------------------------


class TestGetDocumentSetAttachmentRepository:
    """get_document_set_attachment_repository mirrors data store config resolution."""

    def test_returns_attachment_repo_with_defaults_when_config_is_empty(self):
        mock_repo = MagicMock()

        with (
            patch("docpipe.api.dependencies.RepositoryFactory.get_repository_config", return_value=("duckdb", {})),
            patch("docpipe.api.dependencies.AttachmentRepositoryFactory.create", return_value=mock_repo) as mock_create,
        ):
            result = get_document_set_attachment_repository()

        assert result is mock_repo
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["adapter_name"] == "duckdb"
        assert call_kwargs["config"]["database_path"].endswith("document_sets.duckdb")

    def test_uses_storage_adapter_and_database_path_from_config(self):
        mock_repo = MagicMock()
        repo_config = {"storage_adapter": "duckdb", "database_path": "/custom/path/ds.duckdb"}

        with (
            patch(
                "docpipe.api.dependencies.RepositoryFactory.get_repository_config",
                return_value=("duckdb", repo_config),
            ),
            patch("docpipe.api.dependencies.AttachmentRepositoryFactory.create", return_value=mock_repo) as mock_create,
        ):
            result = get_document_set_attachment_repository()

        assert result is mock_repo
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["adapter_name"] == "duckdb"
        assert call_kwargs["config"]["database_path"] == "/custom/path/ds.duckdb"

    def test_postgres_repository_type_stores_attachments_in_postgres(self):
        """type: postgres co-locates attachments with metadata, like DocumentSetOperator does."""
        mock_repo = MagicMock()
        repo_config = {"postgres": {"host": "db", "schema": "assets"}}

        with (
            patch(
                "docpipe.api.dependencies.RepositoryFactory.get_repository_config",
                return_value=("Postgres", repo_config),
            ),
            patch("docpipe.api.dependencies.AttachmentRepositoryFactory.create", return_value=mock_repo) as mock_create,
        ):
            result = get_document_set_attachment_repository()

        assert result is mock_repo
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["adapter_name"] == "postgres"
        assert call_kwargs["config"]["postgres"] == {"host": "db", "schema": "assets"}
        assert call_kwargs["config"]["database_path"].endswith("document_sets.duckdb")


# ---------------------------------------------------------------------------
# get_document_set_service
# ---------------------------------------------------------------------------


class TestGetDocumentSetService:
    """get_document_set_service composes DocumentSetService from its three deps."""

    def test_returns_document_set_service_with_injected_dependencies(self):
        from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService

        mock_repo = MagicMock()
        mock_data_store = MagicMock()
        mock_attachment_repo = MagicMock()

        result = get_document_set_service(
            repository=mock_repo,
            data_store=mock_data_store,
            attachment_repository=mock_attachment_repo,
        )

        assert isinstance(result, DocumentSetService)


# ---------------------------------------------------------------------------
# get_document_library_repository
# ---------------------------------------------------------------------------


class TestGetDocumentLibraryRepository:
    """get_document_library_repository delegates to RepositoryFactory."""

    def test_returns_repository(self):
        mock_repo = MagicMock()

        with patch("docpipe.api.dependencies.RepositoryFactory.create_repository", return_value=mock_repo):
            result = get_document_library_repository()

        assert result is mock_repo


# ---------------------------------------------------------------------------
# get_document_library_service
# ---------------------------------------------------------------------------


class TestGetDocumentLibraryService:
    """get_document_library_service wraps a repository in DocumentLibraryService."""

    def test_returns_document_library_service_with_injected_repository(self):
        from docpipe.core.assets.document_libraries.application.services.document_library_service import (
            DocumentLibraryService,
        )

        mock_repo = MagicMock()

        result = get_document_library_service(repository=mock_repo)

        assert isinstance(result, DocumentLibraryService)
