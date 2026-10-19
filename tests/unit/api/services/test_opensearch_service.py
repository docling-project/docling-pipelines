"""Unit tests for OpenSearchConfig and OpenSearchService."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from docpipe.api.services.opensearch_service import (
    OpenSearchConfig,
    OpenSearchService,
    get_opensearch_service,
)

_OPENSEARCH_CLASS = "docpipe.api.services.opensearch_service.OpenSearch"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Keep the machine's OPENSEARCH_* variables and any .env file out of the settings."""
    for name in (
        "OPENSEARCH_HOST",
        "OPENSEARCH_PORT",
        "OPENSEARCH_USE_SSL",
        "OPENSEARCH_VERIFY_CERTS",
        "OPENSEARCH_USERNAME",
        "OPENSEARCH_PASSWORD",
        "OPENSEARCH_DEFAULT_INDEX",
        "OPENSEARCH_TIMEOUT",
        "OPENSEARCH_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def config() -> OpenSearchConfig:
    """Config with explicit credentials and non-default connection settings."""
    return OpenSearchConfig(
        opensearch_host="search.example.com",
        opensearch_port=9443,
        opensearch_use_ssl=True,
        opensearch_verify_certs=True,
        opensearch_username="reader",
        opensearch_password="<test-password>",  # pragma: allowlist secret
        opensearch_timeout=12,
        opensearch_max_retries=5,
    )


@pytest.fixture
def service(config: OpenSearchConfig) -> OpenSearchService:
    """Service with an explicit config, so no environment is read."""
    return OpenSearchService(config=config)


class TestOpenSearchConfig:
    """Credential validation and environment loading."""

    @pytest.mark.parametrize(
        ("username", "password"),
        [("", "<test-password>"), ("reader", ""), ("", "")],
    )
    def test_rejects_missing_credentials(self, username: str, password: str) -> None:
        with pytest.raises(ValidationError, match="OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD"):
            OpenSearchConfig(opensearch_username=username, opensearch_password=password)

    def test_reads_settings_from_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENSEARCH_HOST", "env-host")
        monkeypatch.setenv("OPENSEARCH_PORT", "9201")
        monkeypatch.setenv("OPENSEARCH_USERNAME", "env-user")
        monkeypatch.setenv("OPENSEARCH_PASSWORD", "<env-password>")  # pragma: allowlist secret

        config = OpenSearchConfig()

        assert (config.opensearch_host, config.opensearch_port) == ("env-host", 9201)
        assert config.opensearch_username == "env-user"
        assert config.opensearch_default_index == "documents"

    def test_reads_credentials_from_dotenv_file(self, tmp_path) -> None:
        (tmp_path / ".env").write_text(
            "OPENSEARCH_USERNAME=file-user\nOPENSEARCH_PASSWORD=<file-password>\n",  # pragma: allowlist secret
            encoding="utf-8",
        )

        config = OpenSearchConfig()

        assert config.opensearch_username == "file-user"

    def test_without_credentials_in_environment_raises(self) -> None:
        with pytest.raises(ValidationError):
            OpenSearchConfig()


class TestGetClient:
    """Lazy client creation from the config."""

    def test_creates_client_from_config(self, service: OpenSearchService) -> None:
        with patch(_OPENSEARCH_CLASS) as opensearch_cls:
            client = service.get_client()

        assert client is opensearch_cls.return_value
        opensearch_cls.assert_called_once_with(
            hosts=[{"host": "search.example.com", "port": 9443}],
            http_auth=("reader", "<test-password>"),  # pragma: allowlist secret
            use_ssl=True,
            verify_certs=True,
            ssl_show_warn=False,
            timeout=12,
            max_retries=5,
            retry_on_timeout=True,
        )

    def test_reuses_client_on_later_calls(self, service: OpenSearchService) -> None:
        with patch(_OPENSEARCH_CLASS) as opensearch_cls:
            first = service.get_client()
            second = service.get_client()

        assert first is second
        opensearch_cls.assert_called_once()

    def test_creation_error_propagates_and_next_call_retries(self, service: OpenSearchService) -> None:
        with patch(_OPENSEARCH_CLASS, side_effect=[ValueError("bad host"), MagicMock()]) as opensearch_cls:
            with pytest.raises(ValueError, match="bad host"):
                service.get_client()
            client = service.get_client()

        assert client is not None
        assert opensearch_cls.call_count == 2

    def test_builds_a_real_client_without_connecting(self, service: OpenSearchService) -> None:
        client = service.get_client()

        assert client.transport.hosts == [{"host": "search.example.com", "port": 9443}]
        service.close()


class TestHealthCheck:
    """Cluster health mapping."""

    @pytest.mark.parametrize(("status", "healthy"), [("green", True), ("yellow", True), ("red", False)])
    def test_maps_cluster_status(self, service: OpenSearchService, status: str, healthy: bool) -> None:
        client = MagicMock()
        client.cluster.health.return_value = {"status": status}
        service._client = client

        assert service.health_check() is healthy

    def test_missing_status_is_unhealthy(self, service: OpenSearchService) -> None:
        client = MagicMock()
        client.cluster.health.return_value = {}
        service._client = client

        assert service.health_check() is False

    def test_connection_error_is_unhealthy(self, service: OpenSearchService) -> None:
        client = MagicMock()
        client.cluster.health.side_effect = ConnectionError("cluster unreachable")
        service._client = client

        assert service.health_check() is False

    def test_client_creation_error_is_unhealthy(self, service: OpenSearchService) -> None:
        with patch(_OPENSEARCH_CLASS, side_effect=ValueError("bad host")):
            assert service.health_check() is False


class TestIndexExists:
    """Index existence lookup."""

    @pytest.mark.parametrize("exists", [True, False])
    def test_returns_client_answer(self, service: OpenSearchService, exists: bool) -> None:
        client = MagicMock()
        client.indices.exists.return_value = exists
        service._client = client

        assert service.index_exists(index_name="documents") is exists
        client.indices.exists.assert_called_once_with(index="documents")

    def test_error_returns_false(self, service: OpenSearchService) -> None:
        client = MagicMock()
        client.indices.exists.side_effect = ConnectionError("cluster unreachable")
        service._client = client

        assert service.index_exists(index_name="documents") is False


class TestClose:
    """Releasing the client."""

    def test_closes_and_forgets_client(self, service: OpenSearchService) -> None:
        client = MagicMock()
        service._client = client

        service.close()

        client.close.assert_called_once_with()
        assert service._client is None

    def test_close_error_still_forgets_client(self, service: OpenSearchService) -> None:
        client = MagicMock()
        client.close.side_effect = OSError("socket already closed")
        service._client = client

        service.close()

        assert service._client is None

    def test_close_without_client_is_noop(self, service: OpenSearchService) -> None:
        service.close()

        assert service._client is None

    def test_next_call_after_close_creates_new_client(self, service: OpenSearchService) -> None:
        with patch(_OPENSEARCH_CLASS, side_effect=[MagicMock(), MagicMock()]) as opensearch_cls:
            first = service.get_client()
            service.close()
            second = service.get_client()

        assert first is not second
        assert opensearch_cls.call_count == 2


class TestServiceFromEnvironment:
    """Construction without an explicit config, as used by the FastAPI dependency."""

    def test_dependency_builds_service_from_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENSEARCH_USERNAME", "env-user")
        monkeypatch.setenv("OPENSEARCH_PASSWORD", "<env-password>")  # pragma: allowlist secret
        monkeypatch.setenv("OPENSEARCH_DEFAULT_INDEX", "acl-documents")

        service = get_opensearch_service()

        assert isinstance(service, OpenSearchService)
        assert service.config.opensearch_default_index == "acl-documents"
        assert service._client is None

    def test_dependency_without_credentials_raises(self) -> None:
        with pytest.raises(ValidationError):
            get_opensearch_service()
