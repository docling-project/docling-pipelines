#!/usr/bin/env python3
"""Unit tests for the Dropbox ingest source adapter.

All Dropbox SDK calls are mocked - these tests never contact the live provider.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from dropbox.exceptions import ApiError, AuthError, HttpError
from dropbox.files import FileMetadata, FolderMetadata

from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.adapter import DropboxSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.config import DropboxSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import SourceAdapterFactory
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

ADAPTER_MODULE = "docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.adapter"


def make_file(
    *,
    name: str,
    path: str,
    file_id: str = "id:file1",
    size: int = 1024,
    modified: datetime | None = None,
) -> FileMetadata:
    """Build a Dropbox FileMetadata entry for tests."""
    timestamp = modified or datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    return FileMetadata(
        name=name,
        id=file_id,
        path_lower=path.lower(),
        path_display=path,
        size=size,
        client_modified=timestamp,
        server_modified=timestamp,
        rev="0123456789abc",
        content_hash="a" * 64,
    )


def make_list_result(entries, *, has_more: bool = False, cursor: str = "cursor-1") -> Mock:
    """Build a mock files_list_folder result."""
    result = Mock()
    result.entries = entries
    result.has_more = has_more
    result.cursor = cursor
    return result


def make_api_error(message: str = "dropbox api error") -> ApiError:
    """Build an ApiError instance without depending on SDK error union internals."""
    return ApiError(request_id="req-1", error=message, user_message_text=None, user_message_locale=None)


async def collect(generator):
    """Collect an async generator into a list."""
    return [item async for item in generator]


def base_config(**overrides) -> DropboxSourceConfig:
    """Build a config with a token and optional overrides."""
    params = {"access_token": "test-token", "folder_path": "/Reports"}  # pragma: allowlist secret
    params.update(overrides)
    return DropboxSourceConfig(**params)


class TestDropboxSourceConfig:
    """Test DropboxSourceConfig validation, defaults and normalization."""

    def test_requires_credentials(self):
        """Config without any credential is rejected with an actionable message."""
        with pytest.raises(ValueError, match="Dropbox credentials missing"):
            DropboxSourceConfig()

    def test_refresh_token_requires_app_key_and_secret(self):
        """Refresh token flow requires the app key and secret."""
        with pytest.raises(ValueError, match="app_key and app_secret"):
            DropboxSourceConfig(refresh_token="refresh")  # pragma: allowlist secret

    def test_refresh_token_flow_accepted(self):
        """Refresh token flow is valid when app credentials are present."""
        config = DropboxSourceConfig(
            refresh_token="refresh",  # pragma: allowlist secret
            app_key="key",
            app_secret="secret",  # pragma: allowlist secret
        )
        assert config.refresh_token == "refresh"
        assert config.access_token is None

    def test_blank_credentials_treated_as_missing(self):
        """Whitespace-only credentials are not accepted as a token."""
        with pytest.raises(ValueError, match="Dropbox credentials missing"):
            DropboxSourceConfig(access_token="   ")

    def test_folder_path_root_is_empty_string(self):
        """Dropbox represents the account root as an empty path."""
        assert base_config(folder_path="/").folder_path == ""
        assert base_config(folder_path="").folder_path == ""

    def test_folder_path_normalized(self):
        """Folder paths gain a leading slash and lose trailing slashes."""
        assert base_config(folder_path="Reports/2026/").folder_path == "/Reports/2026"

    def test_file_path_normalized_and_file_id_preserved(self):
        """File paths are normalized while Dropbox file ids are left untouched."""
        assert base_config(file_path="Reports/q1.pdf").file_path == "/Reports/q1.pdf"
        assert base_config(file_path="id:abc123").file_path == "id:abc123"

    def test_extensions_normalized(self):
        """Extensions are lowercased and prefixed with a dot."""
        config = base_config(file_extensions=["PDF", ".DocX", "txt"])
        assert config.file_extensions == [".pdf", ".docx", ".txt"]

    def test_validates_max_file_size(self):
        """max_file_size_mb must be positive."""
        with pytest.raises(ValueError, match="max_file_size_mb must be positive"):
            base_config(max_file_size_mb=0)

    def test_validates_max_files(self):
        """max_files must be positive."""
        with pytest.raises(ValueError, match="max_files must be positive"):
            base_config(max_files=-3)

    def test_secrets_hidden_from_repr(self):
        """Credentials must not leak through the model repr."""
        config = base_config(access_token="super-secret-token")  # pragma: allowlist secret
        assert "super-secret-token" not in repr(config)


class TestDropboxAdapterMetadata:
    """Test adapter identity, schema and factory registration."""

    def test_source_metadata(self):
        """Adapter exposes the discovery metadata used by the UI."""
        metadata = DropboxSourceAdapter().get_metadata()
        assert metadata["name"] == "dropbox"
        assert metadata["display_name"] == "Dropbox"
        assert metadata["config_schema"] is not None

    def test_get_config_schema(self):
        """Adapter returns its Pydantic config class."""
        assert DropboxSourceAdapter().get_config_schema() is DropboxSourceConfig

    def test_registered_with_factory(self):
        """Adapter is discoverable by SOURCE_NAME through the factory."""
        assert SourceAdapterFactory.is_registered("dropbox")
        assert isinstance(SourceAdapterFactory.create("dropbox"), DropboxSourceAdapter)


class TestBuildConfigFromOperatorParams:
    """Test mapping of operator parameters onto the provider config."""

    def test_maps_connection_params_and_credentials(self):
        """Operator parameters are mapped onto the Dropbox config."""
        config = DropboxSourceAdapter().build_config_from_operator_params(
            provider_config={
                "folder_path": "Reports",
                "recursive": False,
                "exclude_patterns": ["*.tmp"],
                "max_file_size_mb": 50,
                "access_token": "token-value",  # pragma: allowlist secret
            },
            included_extensions=["pdf", "docx"],
            max_files=25,
        )

        assert isinstance(config, DropboxSourceConfig)
        assert config.folder_path == "/Reports"
        assert config.recursive is False
        assert config.exclude_patterns == ["*.tmp"]
        assert config.max_file_size_mb == 50
        assert config.file_extensions == [".pdf", ".docx"]
        assert config.max_files == 25

    def test_defaults_to_root_and_recursive(self):
        """Missing connection params fall back to a recursive root ingestion."""
        config = DropboxSourceAdapter().build_config_from_operator_params(
            provider_config={"access_token": "token-value"},  # pragma: allowlist secret
        )
        assert config.folder_path == ""
        assert config.recursive is True
        assert config.max_files is None

    def test_resolves_environment_variables(self, monkeypatch):
        """Credential and path environment references are resolved."""
        monkeypatch.setenv("DROPBOX_TEST_TOKEN", "resolved-token")
        monkeypatch.setenv("DROPBOX_TEST_FOLDER", "/Env/Folder")

        config = DropboxSourceAdapter().build_config_from_operator_params(
            provider_config={
                "folder_path": "${DROPBOX_TEST_FOLDER}",
                "access_token": "${DROPBOX_TEST_TOKEN}",
            },  # pragma: allowlist secret
        )

        assert config.access_token == "resolved-token"
        assert config.folder_path == "/Env/Folder"

    def test_missing_credentials_raise_value_error(self):
        """A flow without Dropbox credentials fails with an actionable error."""
        with pytest.raises(ValueError, match="Dropbox credentials missing"):
            DropboxSourceAdapter().build_config_from_operator_params(
                provider_config={"folder_path": "/Reports"},
            )

    def test_single_file_mode_param(self):
        """file_path in connection params enables single-file ingestion."""
        config = DropboxSourceAdapter().build_config_from_operator_params(
            provider_config={"file_path": "Reports/q1.pdf", "access_token": "token-value"},  # pragma: allowlist secret
        )
        assert config.file_path == "/Reports/q1.pdf"


class TestTestConnection:
    """Test the connection check behavior."""

    @pytest.mark.asyncio
    async def test_connection_success(self):
        """A successful account lookup reports the account display name."""
        client = Mock()
        client.users_get_current_account.return_value.name.display_name = "Test User"

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            success, message = await DropboxSourceAdapter().test_connection(base_config())

        assert success is True
        assert "Test User" in message
        client.files_get_metadata.assert_called_once_with("/Reports")

    @pytest.mark.asyncio
    async def test_connection_skips_folder_check_at_root(self):
        """Root ingestion does not need an extra metadata call."""
        client = Mock()
        client.users_get_current_account.return_value.name.display_name = "Test User"

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            success, _ = await DropboxSourceAdapter().test_connection(base_config(folder_path=""))

        assert success is True
        client.files_get_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_auth_failure(self):
        """Authentication failures return an actionable message."""
        client = Mock()
        client.users_get_current_account.side_effect = AuthError("req-1", "invalid_access_token")

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            success, message = await DropboxSourceAdapter().test_connection(base_config())

        assert success is False
        assert "authentication failed" in message.lower()

    @pytest.mark.asyncio
    async def test_connection_missing_folder(self):
        """A missing folder is reported rather than raised."""
        client = Mock()
        client.users_get_current_account.return_value.name.display_name = "Test User"
        client.files_get_metadata.side_effect = make_api_error("path/not_found")

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            success, message = await DropboxSourceAdapter().test_connection(base_config())

        assert success is False
        assert "/Reports" in message

    @pytest.mark.asyncio
    async def test_connection_network_failure(self):
        """Transport errors are reported as a failed connection."""
        client = Mock()
        client.users_get_current_account.side_effect = HttpError("req-1", 503, "service unavailable")

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            success, message = await DropboxSourceAdapter().test_connection(base_config())

        assert success is False
        assert "Dropbox API" in message


class TestFetchDocuments:
    """Test document listing, filtering, pagination and mapping."""

    @pytest.mark.asyncio
    async def test_yields_documents_with_domain_metadata(self):
        """Listed files are mapped to fully populated domain documents."""
        entry = make_file(name="q1.pdf", path="/Reports/2026/q1.pdf", file_id="id:abc123", size=2048)
        client = Mock()
        client.files_list_folder.return_value = make_list_result([entry])

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(base_config()))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "id:abc123"
        assert doc.name == "q1.pdf"
        assert doc.content == b""
        assert doc.size == 2048
        assert doc.extension == "pdf"
        assert doc.mimetype == "application/pdf"
        assert doc.modified_time == datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert doc.source_url == "https://www.dropbox.com/home/Reports/2026/q1.pdf"
        assert doc.metadata["source_id"] == "id:abc123"
        assert doc.metadata["path"] == "/Reports/2026/q1.pdf"
        assert doc.metadata["relative_path"] == "2026/q1.pdf"
        assert doc.metadata["rev"] == "0123456789abc"
        client.files_list_folder.assert_called_once_with(path="/Reports", recursive=True)

    @pytest.mark.asyncio
    async def test_follows_pagination_cursor(self):
        """Additional pages are fetched with the continuation cursor."""
        page_one = make_list_result(
            [make_file(name="a.pdf", path="/Reports/a.pdf", file_id="id:a")],
            has_more=True,
            cursor="cursor-1",
        )
        page_two = make_list_result([make_file(name="b.pdf", path="/Reports/b.pdf", file_id="id:b")])

        client = Mock()
        client.files_list_folder.return_value = page_one
        client.files_list_folder_continue.return_value = page_two

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(base_config()))

        assert [doc.name for doc in docs] == ["a.pdf", "b.pdf"]
        client.files_list_folder_continue.assert_called_once_with("cursor-1")

    @pytest.mark.asyncio
    async def test_skips_folders_and_applies_extension_filter(self):
        """Folder entries are ignored and extension filters are enforced."""
        entries = [
            FolderMetadata(name="sub", id="id:folder", path_lower="/reports/sub", path_display="/Reports/sub"),
            make_file(name="keep.pdf", path="/Reports/keep.pdf", file_id="id:keep"),
            make_file(name="skip.png", path="/Reports/skip.png", file_id="id:skip"),
        ]
        client = Mock()
        client.files_list_folder.return_value = make_list_result(entries)

        config = base_config(file_extensions=["pdf"])
        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(config))

        assert [doc.name for doc in docs] == ["keep.pdf"]

    @pytest.mark.asyncio
    async def test_applies_size_and_exclude_filters(self):
        """Oversized files and excluded paths are filtered out."""
        entries = [
            make_file(name="small.pdf", path="/Reports/small.pdf", file_id="id:small", size=1024),
            make_file(name="huge.pdf", path="/Reports/huge.pdf", file_id="id:huge", size=5 * 1024 * 1024),
            make_file(name="old.pdf", path="/Reports/Archive/old.pdf", file_id="id:old", size=1024),
        ]
        client = Mock()
        client.files_list_folder.return_value = make_list_result(entries)

        config = base_config(max_file_size_mb=1, exclude_patterns=["*/Archive/*"])
        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(config))

        assert [doc.name for doc in docs] == ["small.pdf"]

    @pytest.mark.asyncio
    async def test_respects_max_files(self):
        """Listing stops once max_files documents have been produced."""
        entries = [make_file(name=f"f{i}.pdf", path=f"/Reports/f{i}.pdf", file_id=f"id:{i}") for i in range(5)]
        client = Mock()
        client.files_list_folder.return_value = make_list_result(entries)

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(base_config(max_files=2)))

        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_non_recursive_listing(self):
        """recursive=False is forwarded to the Dropbox API."""
        client = Mock()
        client.files_list_folder.return_value = make_list_result([])

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(base_config(recursive=False)))

        assert docs == []
        client.files_list_folder.assert_called_once_with(path="/Reports", recursive=False)

    @pytest.mark.asyncio
    async def test_single_file_mode(self):
        """A configured file_path fetches exactly one document."""
        client = Mock()
        client.files_get_metadata.return_value = make_file(name="q1.pdf", path="/Reports/q1.pdf", file_id="id:single")

        config = base_config(file_path="/Reports/q1.pdf")
        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            docs = await collect(DropboxSourceAdapter().fetch_documents(config))

        assert [doc.id for doc in docs] == ["id:single"]
        client.files_list_folder.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_file_mode_rejects_folder(self):
        """Pointing file_path at a folder raises a clear error."""
        client = Mock()
        client.files_get_metadata.return_value = FolderMetadata(
            name="sub", id="id:folder", path_lower="/reports/sub", path_display="/Reports/sub"
        )

        config = base_config(file_path="/Reports/sub")
        with (
            patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client),
            pytest.raises(ValueError, match="not a file"),
        ):
            await collect(DropboxSourceAdapter().fetch_documents(config))

    @pytest.mark.asyncio
    async def test_auth_error_is_raised(self):
        """Authentication failures abort the listing with a clear error."""
        client = Mock()
        client.files_list_folder.side_effect = AuthError("req-1", "invalid_access_token")

        with (
            patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client),
            pytest.raises(ValueError, match="authentication failed"),
        ):
            await collect(DropboxSourceAdapter().fetch_documents(base_config()))

    @pytest.mark.asyncio
    async def test_api_error_is_raised(self):
        """API errors during listing surface as a ValueError."""
        client = Mock()
        client.files_list_folder.side_effect = make_api_error()

        with (
            patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client),
            pytest.raises(ValueError, match="Failed to fetch documents from Dropbox"),
        ):
            await collect(DropboxSourceAdapter().fetch_documents(base_config()))


class TestFetchBinaryContent:
    """Test on-demand binary retrieval."""

    def test_downloads_by_file_id(self):
        """A stored Dropbox file id is passed through unchanged."""
        response = Mock()
        response.content = b"PDF-bytes"
        client = Mock()
        client.files_download.return_value = (None, response)

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            content = DropboxSourceAdapter().fetch_binary_content(
                source_id="id:abc123",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

        assert content == b"PDF-bytes"
        client.files_download.assert_called_once_with("id:abc123")

    def test_downloads_by_path(self):
        """A bare path is normalized to a Dropbox path."""
        response = Mock()
        response.content = b"bytes"
        client = Mock()
        client.files_download.return_value = (None, response)

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            DropboxSourceAdapter().fetch_binary_content(
                source_id="Reports/q1.pdf",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

        client.files_download.assert_called_once_with("/Reports/q1.pdf")

    def test_downloads_by_web_url(self):
        """A Dropbox web URL is converted back to a Dropbox path."""
        response = Mock()
        response.content = b"bytes"
        client = Mock()
        client.files_download.return_value = (None, response)

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            DropboxSourceAdapter().fetch_binary_content(
                source_id="https://www.dropbox.com/home/Reports/q1.pdf",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

        client.files_download.assert_called_once_with("/Reports/q1.pdf")

    def test_returns_none_when_file_missing(self):
        """A missing file yields None so the pipeline can record the failure."""
        client = Mock()
        client.files_download.side_effect = make_api_error("path/not_found")

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            content = DropboxSourceAdapter().fetch_binary_content(
                source_id="id:missing",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

        assert content is None

    def test_returns_none_on_auth_error(self):
        """Authentication failures during download yield None."""
        client = Mock()
        client.files_download.side_effect = AuthError("req-1", "invalid_access_token")

        with patch.object(DropboxSourceAdapter, "_get_dropbox_client", return_value=client):
            content = DropboxSourceAdapter().fetch_binary_content(
                source_id="id:abc123",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

        assert content is None

    def test_empty_source_id_raises(self):
        """An empty source_id is a configuration error, not a missing file."""
        with pytest.raises(ValueError, match="Missing source_id"):
            DropboxSourceAdapter().fetch_binary_content(
                source_id="",
                provider_config={"access_token": "token-value"},  # pragma: allowlist secret
            )

    def test_missing_credentials_raise(self):
        """Missing credentials stop processing with an actionable error."""
        with pytest.raises(ValueError, match="Dropbox credentials missing"):
            DropboxSourceAdapter().fetch_binary_content(
                source_id="id:abc123",
                provider_config={},
            )


class TestClientCaching:
    """Test that a single authenticated client is reused per credential set."""

    def test_client_is_cached_per_credentials(self):
        """The SDK client is constructed once and reused for the same token."""
        adapter = DropboxSourceAdapter()
        config = base_config()

        with patch(f"{ADAPTER_MODULE}.Dropbox") as mock_dropbox:
            first = adapter._get_dropbox_client(config=config)
            second = adapter._get_dropbox_client(config=config)

        assert first is second
        assert mock_dropbox.call_count == 1

    def test_refresh_token_client_construction(self):
        """Refresh token credentials are passed to the SDK client."""
        adapter = DropboxSourceAdapter()
        config = DropboxSourceConfig(
            refresh_token="refresh",  # pragma: allowlist secret
            app_key="key",
            app_secret="secret",  # pragma: allowlist secret
        )

        with patch(f"{ADAPTER_MODULE}.Dropbox") as mock_dropbox:
            adapter._get_dropbox_client(config=config)

        kwargs = mock_dropbox.call_args.kwargs
        assert kwargs["oauth2_refresh_token"] == "refresh"
        assert kwargs["app_key"] == "key"


class TestBindFileReference:
    """Test DropboxSourceAdapter.bind_file_reference."""

    def test_valid_path_reference_sets_file_path(self):
        """A non-empty path reference is set as file_path without any Dropbox API call."""
        provider_config = {"access_token": "token-value", "folder_path": "/Reports"}  # pragma: allowlist secret

        DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="/Reports/q1.pdf")

        assert provider_config["file_path"] == "/Reports/q1.pdf"

    def test_valid_id_reference_sets_file_path(self):
        """A Dropbox file id reference is accepted as-is."""
        provider_config = {"access_token": "token-value"}  # pragma: allowlist secret

        DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="id:abc123")

        assert provider_config["file_path"] == "id:abc123"

    def test_credentials_are_untouched(self):
        """bind_file_reference only adds file_path; it never reads or rewrites credentials."""
        provider_config = {"access_token": "token-value"}  # pragma: allowlist secret

        DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="/q1.pdf")

        assert provider_config["access_token"] == "token-value"  # pragma: allowlist secret
        assert "refresh_token" not in provider_config

    def test_empty_file_reference_raises_value_error(self):
        """An empty file_reference raises a clear ValueError."""
        provider_config = {"access_token": "token-value"}  # pragma: allowlist secret

        with pytest.raises(ValueError, match="non-empty Dropbox path or id"):
            DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="")

        assert "file_path" not in provider_config

    def test_blank_file_reference_raises_value_error(self):
        """A whitespace-only file_reference raises a clear ValueError."""
        provider_config = {"access_token": "token-value"}  # pragma: allowlist secret

        with pytest.raises(ValueError, match="non-empty Dropbox path or id"):
            DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="   ")

        assert "file_path" not in provider_config

    def test_none_file_reference_raises_value_error(self):
        """A None file_reference raises a clear ValueError, not an AttributeError."""
        provider_config = {"access_token": "token-value"}  # pragma: allowlist secret

        with pytest.raises(ValueError, match="non-empty Dropbox path or id"):
            DropboxSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=None)

        assert "file_path" not in provider_config


@pytest.fixture
def dropbox_ingest_config(monkeypatch):
    """Configure real operator binding with isolated worker and credential variables."""
    monkeypatch.setenv("DOCPIPE_EVENT_CANARY", "worker-canary-value")
    monkeypatch.setenv("DOCPIPE_EVENT_EMPTY", "")
    monkeypatch.delenv("DOCPIPE_EVENT_UNSET", raising=False)
    monkeypatch.setenv("DOCPIPE_TEST_TOKEN", "resolved-test-token")
    return {
        "provider": "dropbox",
        "provider_config": {"access_token": "${DOCPIPE_TEST_TOKEN}", "folder_path": "/Reports"},
        "include_filter": ".pdf",
        "input_event": {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "event_timestamp": "2026-10-26T00:00:00Z",
            "routing_key": "test-documents",
            "operation": "create",
            "file_reference": "DOCPIPE_EVENT_CANARY",
        },
    }


@pytest.mark.parametrize(
    ("file_reference", "expected_path"),
    [
        ("$DOCPIPE_EVENT_CANARY", "/$DOCPIPE_EVENT_CANARY"),
        ("${DOCPIPE_EVENT_CANARY}", "/${DOCPIPE_EVENT_CANARY}"),
        ("DOCPIPE_EVENT_CANARY", "/DOCPIPE_EVENT_CANARY"),
        ("${DOCPIPE_EVENT_UNSET}", "/${DOCPIPE_EVENT_UNSET}"),
        ("${DOCPIPE_EVENT_UNSET:fallback}", "/${DOCPIPE_EVENT_UNSET:fallback}"),
        ("DOCPIPE_EVENT_EMPTY", "/DOCPIPE_EVENT_EMPTY"),
        ("Reports/q1.pdf", "/Reports/q1.pdf"),
        ("id:ABC_DEF", "id:ABC_DEF"),
    ],
)
async def test_event_reference_stays_literal(*, dropbox_ingest_config, file_reference, expected_path):
    """Event references reach the SDK literally while trusted credential variables resolve."""
    dropbox_ingest_config["input_event"]["file_reference"] = file_reference
    original_provider_config = dict(dropbox_ingest_config["provider_config"])
    operator = IngestSourceOperator(dropbox_ingest_config)
    adapter, config = operator._build_adapter_config("dropbox")
    client = Mock()
    client.files_get_metadata.return_value = make_file(name="q1.pdf", path="/Reports/q1.pdf")

    with patch.object(adapter, "_get_dropbox_client", return_value=client), patch(f"{ADAPTER_MODULE}.logger") as log:
        documents = await collect(adapter.fetch_documents(config))

    client.files_get_metadata.assert_called_once_with(expected_path)
    client.files_list_folder.assert_not_called()
    assert len(documents) == 1
    assert config.file_path == expected_path
    assert config.access_token == "resolved-test-token"  # pragma: allowlist secret
    assert operator.provider_config == original_provider_config
    assert dropbox_ingest_config["provider_config"] == original_provider_config
    assert "worker-canary-value" not in repr(log.mock_calls)


async def test_event_reference_does_not_expose_environment_in_errors(dropbox_ingest_config):
    """A failed provider lookup reports the literal reference without disclosing worker values."""
    operator = IngestSourceOperator(dropbox_ingest_config)
    adapter, config = operator._build_adapter_config("dropbox")
    client = Mock()
    client.files_get_metadata.return_value = FolderMetadata(name="folder", id="id:folder")

    with patch.object(adapter, "_get_dropbox_client", return_value=client), patch(f"{ADAPTER_MODULE}.logger") as log:
        with pytest.raises(ValueError, match="Dropbox path is not a file") as exc:
            await collect(adapter.fetch_documents(config))

    client.files_get_metadata.assert_called_once_with("/DOCPIPE_EVENT_CANARY")
    assert "/DOCPIPE_EVENT_CANARY" in str(exc.value)
    assert "worker-canary-value" not in str(exc.value)
    assert "worker-canary-value" not in repr(log.mock_calls)


def test_trusted_file_reference_still_resolves_without_event(*, dropbox_ingest_config, monkeypatch):
    """Batch runs retain environment resolution for trusted file settings and credentials."""
    dropbox_ingest_config.pop("input_event")
    dropbox_ingest_config["provider_config"]["file_path"] = "${DOCPIPE_TRUSTED_FILE}"
    monkeypatch.setenv("DOCPIPE_TRUSTED_FILE", "/Reports/q1.pdf")
    operator = IngestSourceOperator(dropbox_ingest_config)

    _, config = operator._build_adapter_config("dropbox")

    assert config.file_path == "/Reports/q1.pdf"
    assert config.access_token == "resolved-test-token"  # pragma: allowlist secret
    assert operator.provider_config["file_path"] == "${DOCPIPE_TRUSTED_FILE}"
