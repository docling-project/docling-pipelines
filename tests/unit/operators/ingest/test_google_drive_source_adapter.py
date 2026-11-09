#!/usr/bin/env python3

import asyncio
from collections import deque
from datetime import datetime
from unittest.mock import Mock, mock_open, patch

import pytest
from pydantic import ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
    GoogleDriveSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import (
    GoogleDriveSourceConfig,
)
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator


async def collect_async(async_gen):
    return [item async for item in async_gen]


class TestGoogleDriveSourceConfig:
    def test_expands_credentials_path_and_default_token_path(self):
        config = GoogleDriveSourceConfig(
            credentials_path="~/creds.json",
            token_path=None,
            drive_id=None,
            folder_id="folder",
            folder_path=None,
            recursive=True,
            max_file_size_mb=None,
        )
        assert config.credentials_path.endswith("creds.json")
        assert config.get_token_path().endswith("token.json")

    def test_normalizes_extensions_and_validates_size(self):
        config = GoogleDriveSourceConfig(
            credentials_path="/tmp/creds.json",
            token_path=None,
            drive_id=None,
            folder_id=None,
            folder_path=None,
            recursive=True,
            file_extensions=["pdf", ".docx"],
            max_file_size_mb=10,
        )
        assert config.file_extensions == [".pdf", ".docx"]
        assert config.max_file_size_mb == 10

    def test_rejects_invalid_size(self):
        with pytest.raises(ValidationError, match="Input should be greater than or equal to 1"):
            GoogleDriveSourceConfig(
                credentials_path="/tmp/creds.json",
                token_path=None,
                drive_id=None,
                folder_id=None,
                folder_path=None,
                recursive=True,
                max_file_size_mb=-1,
            )


class TestGoogleDriveSourceAdapter:
    def make_config(self):
        return GoogleDriveSourceConfig(
            credentials_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=True,
            file_extensions=[".pdf", ".unknown"],
            max_file_size_mb=None,
        )

    def test_build_config_from_operator_params(self):
        adapter = GoogleDriveSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "folder_id": "folder123",
                "recursive": True,
                "drive_id": "drive1",
                "max_file_size_mb": 4,
                "credentials_path": "/tmp/creds.json",
                "token_path": "/tmp/token.json",
                "scopes": ["scope1"],
            },
            included_extensions=["pdf"],
        )

        config_data = config.model_dump()

        assert type(config).__name__ == "GoogleDriveSourceConfig"
        assert config_data["credentials_path"] == "/tmp/creds.json"
        assert config_data["token_path"] == "/tmp/token.json"
        assert config_data["file_extensions"] == [".pdf"]
        assert config_data["drive_id"] == "drive1"
        assert config_data["max_file_size_mb"] == 4

    def test_get_credentials_from_cached_token(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()
        creds = Mock(valid=True)

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.open", mock_open(read_data='{"token": "data"}')),
            patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_info",
                return_value=creds,
            ),
        ):
            result = adapter._get_credentials(config)

        assert result is creds

    def test_get_credentials_refreshes_expired_token(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()
        creds = Mock(valid=False, expired=True, refresh_token="token")
        creds.to_json.return_value = '{"token": "data"}'

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.open", mock_open(read_data='{"token": "data"}')),
            patch("pathlib.Path.mkdir"),
            patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_info",
                return_value=creds,
            ),
        ):
            result = adapter._get_credentials(config)

        creds.refresh.assert_called_once()
        assert result is creds

    def test_get_credentials_service_account_path_uses_service_account_loader(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            service_account_json_path="/tmp/service-account.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
        )

        with patch.object(adapter, "_load_service_account_credentials", return_value=Mock()) as mock_loader:
            adapter._get_credentials(config)

        mock_loader.assert_called_once_with(config)

    def test_refresh_or_run_oauth_flow_reauths_when_refresh_fails(self):
        creds = Mock(expired=True, refresh_token="token")
        creds.refresh.side_effect = RuntimeError("refresh failed")
        new_creds = Mock()
        new_creds.to_json.return_value = '{"token": "new"}'
        flow_instance = Mock()
        flow_instance.run_local_server.return_value = new_creds

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.open", mock_open()),
            patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                return_value=flow_instance,
            ),
        ):
            result = GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                creds=creds,
                credentials_path=__import__("pathlib").Path("/tmp/credentials.json"),
                token_path=__import__("pathlib").Path("/tmp/token.json"),
                scopes=["scope1"],
            )

        assert result is new_creds
        creds.refresh.assert_called_once()
        flow_instance.run_local_server.assert_called_once_with(port=0)

    def test_refresh_or_run_oauth_flow_raises_when_credentials_path_is_not_file(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=False),
        ):
            with pytest.raises(ValueError, match="Credentials path is not a file"):
                GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                    creds=None,
                    credentials_path=__import__("pathlib").Path("/tmp/credentials.json"),
                    token_path=__import__("pathlib").Path("/tmp/token.json"),
                    scopes=["scope1"],
                )

    def test_get_credentials_missing_credentials_file_raises(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        with patch("pathlib.Path.exists", side_effect=[False, False]):
            with pytest.raises(ValueError, match="Credentials file not found"):
                adapter._get_credentials(config)

    def test_fetch_documents_returns_metadata_only(self):
        """Test that fetch_documents returns documents with empty content (lazy loading)."""
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        # Mock file metadata from Google Drive API
        file_metadata = {
            "id": "doc1",
            "name": "file.pdf",
            "mimeType": "application/pdf",
            "size": "1024",
            "modifiedTime": "2024-01-01T10:00:00Z",
            "webViewLink": "https://drive.google.com/file/d/doc1",
        }

        with (
            patch.object(adapter, "_get_credentials", return_value=Mock()),
            patch.object(adapter, "_list_files_from_drive", return_value=[file_metadata]),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].id == "doc1"
        assert docs[0].name == "file.pdf"
        # Verify lazy loading - content should be empty
        assert docs[0].content == b""
        assert docs[0].size == 1024
        assert docs[0].modified_time == datetime.fromisoformat("2024-01-01T10:00:00+00:00")
        # Verify metadata is stored for lazy loading
        assert docs[0].metadata["file_id"] == "doc1"
        assert docs[0].metadata["credentials_path"] == "/tmp/credentials.json"

    def test_fetch_documents_wraps_errors(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        with patch.object(adapter, "_get_credentials", side_effect=RuntimeError("bad auth")):
            with pytest.raises(ValueError, match="Failed to fetch documents from Google Drive"):
                asyncio.run(collect_async(adapter.fetch_documents(config)))

    def test_test_connection_success_and_failure(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        # Mock the Google Drive API service
        mock_service = Mock()
        mock_files = Mock()
        mock_list = Mock()
        mock_list.execute.return_value = {"files": [{"id": "1", "name": "test1.pdf"}, {"id": "2", "name": "test2.pdf"}]}
        mock_files.list.return_value = mock_list
        mock_service.files.return_value = mock_files

        with (
            patch.object(adapter, "_get_credentials", return_value=Mock()),
            patch(
                "googleapiclient.discovery.build",
                return_value=mock_service,
            ),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is True
            assert "Found 2 document(s)" in message

        with patch.object(adapter, "_get_credentials", side_effect=Exception("Auth failed")):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Connection test failed" in message

    def test_load_service_account_credentials_success(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            service_account_json_path="/tmp/service-account.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
        )
        creds = Mock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file",
                return_value=creds,
            ),
        ):
            result = adapter._load_service_account_credentials(config)

        assert result is creds

    def test_load_service_account_credentials_missing_file_raises(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            service_account_json_path="/tmp/service-account.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
        )

        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(ValueError, match="Failed to load service account credentials"):
                adapter._load_service_account_credentials(config)

    def test_build_drive_query_includes_mime_filters(self):
        adapter = GoogleDriveSourceAdapter()

        query = adapter._build_drive_query(
            folder_id="folder123",
            file_extensions=[".pdf", ".txt"],
        )

        assert "'folder123' in parents" in query
        assert "trashed = false" in query
        assert "mimeType = 'application/pdf'" in query
        assert "mimeType = 'text/plain'" in query
        assert "application/vnd.google-apps.folder" in query

    def test_process_page_items_stops_at_max_files(self):
        adapter = GoogleDriveSourceAdapter()
        all_files: list[dict[str, str]] = []
        folders_to_process: deque[str] = deque()
        items = [
            {"id": "folder1", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "file1", "mimeType": "application/pdf"},
            {"id": "file2", "mimeType": "application/pdf"},
        ]

        reached_limit = adapter._process_page_items(
            items=items,
            all_files=all_files,
            folders_to_process=folders_to_process,
            recursive=True,
            max_files=1,
        )

        assert reached_limit is True
        assert all_files == [{"id": "file1", "mimeType": "application/pdf"}]
        assert list(folders_to_process) == ["folder1"]

    def test_resolve_workspace_extension_returns_expected_mapped_extension(self):
        adapter = GoogleDriveSourceAdapter()

        extension = adapter._resolve_workspace_extension(
            file_ext="",
            file_mime="application/vnd.google-apps.presentation",
        )

        assert extension == ".pptx"

    def test_fetch_folder_pages_returns_true_when_max_files_reached(self):
        adapter = GoogleDriveSourceAdapter()
        service = Mock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "file1", "mimeType": "application/pdf"}],
            "nextPageToken": None,
        }
        config = GoogleDriveSourceConfig(
            credentials_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            max_files=1,
            max_file_size_mb=None,
        )

        reached = adapter._fetch_folder_pages(
            service=service,
            folder_id="folder123",
            config=config,
            all_files=[],
            folders_to_process=deque(),
        )

        assert reached is True

    def test_list_files_from_drive_stops_after_max_files(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            credentials_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            max_files=1,
            max_file_size_mb=None,
        )

        with (
            patch.object(adapter, "_get_credentials", return_value=Mock()),
            patch("googleapiclient.discovery.build", return_value=Mock()),
            patch.object(adapter, "_fetch_folder_pages", return_value=True) as mock_fetch,
        ):
            files = adapter._list_files_from_drive(config=config)

        assert files == []
        mock_fetch.assert_called_once()

    def test_should_skip_file_checks_workspace_extension_and_size(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            credentials_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            drive_id=None,
            folder_id="folder123",
            folder_path=None,
            recursive=False,
            file_extensions=[".docx"],
            max_file_size_mb=1,
        )

        skipped_for_size = adapter._should_skip_file(
            file_metadata={
                "name": "workspace-doc",
                "mimeType": "application/vnd.google-apps.document",
                "size": str(2 * 1024 * 1024),
            },
            config=config,
        )
        skipped_for_extension = adapter._should_skip_file(
            file_metadata={
                "name": "file.pdf",
                "mimeType": "application/pdf",
                "size": "10",
            },
            config=config,
        )

        assert skipped_for_size is True
        assert skipped_for_extension is True

    def test_fetch_binary_content_uses_content_endpoint_when_no_download_url(self):
        adapter = GoogleDriveSourceAdapter()
        mock_service = Mock()
        files_resource = Mock()
        metadata_request = Mock()
        metadata_request.execute.return_value = {
            "mimeType": "application/pdf",
            "name": "file.pdf",
        }
        media_request = Mock()
        files_resource.get.return_value = metadata_request
        files_resource.get_media.return_value = media_request
        mock_service.files.return_value = files_resource

        downloader_instance = Mock()
        downloader_instance.next_chunk.side_effect = [(None, True)]

        with (
            patch.object(adapter, "_get_credentials", return_value=Mock()),
            patch("googleapiclient.discovery.build", return_value=mock_service),
            patch(
                "googleapiclient.http.MediaIoBaseDownload",
                return_value=downloader_instance,
            ),
        ):
            result = adapter.fetch_binary_content(
                source_id="doc123",
                provider_config={"folder_id": "folder123", "credentials_path": "/tmp/credentials.json"},
            )

        assert result == b""
        files_resource.get_media.assert_called_once_with(fileId="doc123")

    def test_fetch_documents_raises_import_error_when_google_client_missing(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        with patch.object(adapter, "_list_files_from_drive", side_effect=ImportError("missing client")):
            with pytest.raises(ImportError, match="Google API client not installed"):
                asyncio.run(collect_async(adapter.fetch_documents(config)))

    def test_test_connection_returns_false_when_google_client_missing(self):
        adapter = GoogleDriveSourceAdapter()
        config = self.make_config()

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "googleapiclient.discovery":
                raise ImportError("missing client")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            success, message = asyncio.run(adapter.test_connection(config))

        assert success is False
        assert "Google API client not installed" in message

    def test_get_config_schema_returns_google_drive_config(self):
        adapter = GoogleDriveSourceAdapter()
        assert adapter.get_config_schema() is GoogleDriveSourceConfig

    def test_build_config_from_operator_params_includes_optional_fields(self):
        adapter = GoogleDriveSourceAdapter()

        config = adapter.build_config_from_operator_params(
            provider_config={
                "folder_id": "folder123",
                "recursive": False,
                "drive_id": "drive1",
                "folder_path": "Docs",
                "file_id": "doc123",
                "max_file_size_mb": 2,
                "service_account_json_path": "/tmp/service.json",
            },
            included_extensions=[".pdf"],
            max_files=7,
        )

        config_data = config.model_dump()
        assert config_data["drive_id"] == "drive1"
        assert config_data["folder_path"] == "Docs"
        assert config_data["file_id"] == "doc123"
        assert config_data["max_file_size_mb"] == 2
        assert config_data["max_files"] == 7
        assert config_data["service_account_json_path"] == "/tmp/service.json"

    def test_fetch_documents_single_file_returns_metadata_only(self):
        adapter = GoogleDriveSourceAdapter()
        config = GoogleDriveSourceConfig(
            credentials_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            drive_id=None,
            file_id="doc123",
            folder_id=None,
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
        )
        file_metadata = {
            "id": "doc123",
            "name": "single.pdf",
            "mimeType": "application/pdf",
            "size": "42",
            "modifiedTime": "2024-01-03T10:00:00Z",
            "webViewLink": "https://drive.google.com/file/d/doc123",
        }

        with patch.object(
            adapter,
            "_fetch_single_gdrive_file",
            return_value=adapter._prepare_document(file_metadata=file_metadata, config=config),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].id == "doc123"
        assert docs[0].content == b""
        assert docs[0].metadata["file_id"] == "doc123"

    def test_fetch_binary_content_returns_none_for_unsupported_workspace_type(self):
        adapter = GoogleDriveSourceAdapter()
        mock_service = Mock()
        files_resource = Mock()
        metadata_request = Mock()
        metadata_request.execute.return_value = {
            "mimeType": "application/vnd.google-apps.form",
            "name": "form-file",
        }
        files_resource.get.return_value = metadata_request
        mock_service.files.return_value = files_resource

        with (
            patch.object(adapter, "_get_credentials", return_value=Mock()),
            patch("googleapiclient.discovery.build", return_value=mock_service),
        ):
            result = adapter.fetch_binary_content(
                source_id="doc123",
                provider_config={"folder_id": "folder123", "credentials_path": "/tmp/credentials.json"},
            )

        assert result is None


class TestBindFileReference:
    """Test GoogleDriveSourceAdapter.bind_file_reference."""

    def test_valid_file_id_sets_file_id(self):
        """A Drive file ID is set as file_id without any Drive API call."""
        provider_config = {"service_account_json_path": "/tmp/sa.json", "folder_id": "folder123"}

        with patch("googleapiclient.discovery.build") as build:
            GoogleDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="doc-123_abc")

        assert provider_config["file_id"] == "doc-123_abc"
        build.assert_not_called()

    def test_bound_file_id_reaches_config(self):
        """The bound file_id ends up in the config, so fetch_documents takes the single-file path."""
        provider_config = {"service_account_json_path": "/tmp/sa.json", "folder_id": "folder123"}

        GoogleDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="doc123")
        config = GoogleDriveSourceAdapter().build_config_from_operator_params(provider_config=provider_config)

        assert config.file_id == "doc123"
        assert config.is_service_account()

    def test_credentials_are_untouched(self):
        """bind_file_reference only adds file_id; it never reads or rewrites credentials."""
        provider_config = {"credentials_path": "/tmp/credentials.json", "token_path": "/tmp/token.json"}

        GoogleDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference="doc123")

        assert provider_config == {
            "credentials_path": "/tmp/credentials.json",
            "token_path": "/tmp/token.json",
            "file_id": "doc123",
        }

    @pytest.mark.parametrize(
        "file_reference",
        [
            "",
            "   ",
            None,
        ],
    )
    def test_invalid_file_reference_raises_value_error(self, file_reference):
        """Empty, blank and None references raise a clear ValueError."""
        provider_config = {"service_account_json_path": "/tmp/sa.json"}

        with pytest.raises(ValueError, match="Google Drive file ID"):
            GoogleDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=file_reference)

        assert "file_id" not in provider_config


@pytest.mark.parametrize("file_reference", ["$DOCPIPE_EVENT_CANARY", "${DOCPIPE_EVENT_CANARY}", "doc123"])
def test_event_file_id_stays_literal_while_provider_settings_resolve(*, file_reference, monkeypatch):
    """An event's file ID is bound after environment resolution, so it is never expanded."""
    monkeypatch.setenv("DOCPIPE_EVENT_CANARY", "worker-canary-value")
    monkeypatch.setenv("DOCPIPE_TEST_FOLDER", "folder123")
    operator = IngestSourceOperator(
        {
            "provider": "google_drive",
            "provider_config": {"service_account_json_path": "/tmp/sa.json", "folder_id": "${DOCPIPE_TEST_FOLDER}"},
            "input_event": {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "event_timestamp": "2026-10-26T00:00:00Z",
                "routing_key": "test-documents",
                "operation": "create",
                "file_reference": file_reference,
            },
        }
    )

    _, config = operator._build_adapter_config("google_drive")

    assert config.file_id == file_reference
    assert config.folder_id == "folder123"
