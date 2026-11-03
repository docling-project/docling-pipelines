#!/usr/bin/env python3

# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

import asyncio
import logging
from typing import cast
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest
from pydantic import ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive import adapter as onedrive_adapter_module
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import (
    OneDriveSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import (
    OneDriveSourceConfig,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter import (
    SharePointSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.config import (
    SharePointSourceConfig,
)
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator


async def collect_async(async_gen):
    return [item async for item in async_gen]


class TestOneDriveSourceConfig:
    def test_strips_credentials_and_normalizes_fields(self):
        config = OneDriveSourceConfig(
            client_id=" client ",
            client_secret=" secret ",  # pragma: allowlist secret
            tenant_id=" tenant ",
            drive_id="test_drive_id",
            folder_path="Documents",
            recursive=True,
            file_extensions=["pdf", ".txt"],
            max_file_size_mb=None,
            graph_api_version="v1.0",
        )
        assert config.client_id == "client"
        assert config.client_secret == "secret"  # pragma: allowlist secret
        assert config.tenant_id == "tenant"
        assert config.folder_path == "/Documents"
        assert config.file_extensions == [".pdf", ".txt"]

    def test_rejects_empty_credentials(self):
        with pytest.raises(ValidationError, match="client_id cannot be empty"):
            OneDriveSourceConfig(
                client_id=" ",
                client_secret="secret",  # pragma: allowlist secret
                tenant_id="tenant",
                drive_id="test_drive_id",
                folder_path=None,
                recursive=True,
                max_file_size_mb=None,
                graph_api_version="v1.0",
            )

    def test_rejects_invalid_graph_api_version(self):
        with pytest.raises(ValidationError, match="graph_api_version must be one of"):
            OneDriveSourceConfig(
                client_id="client",
                client_secret="secret",  # pragma: allowlist secret
                tenant_id="tenant",
                drive_id="test_drive_id",
                folder_path=None,
                recursive=True,
                max_file_size_mb=None,
                graph_api_version="v2",
            )


class TestSharePointSourceConfig:
    def test_normalizes_fields(self):
        config = SharePointSourceConfig(
            client_id=" client ",
            client_secret=" secret ",  # pragma: allowlist secret
            tenant_id=" tenant ",
            document_library_id=" lib ",
            folder_path="Shared Documents",
            recursive=True,
            file_extensions=["pdf"],
            max_file_size_mb=None,
            graph_api_version="v1.0",
        )
        assert config.client_id == "client"
        assert config.client_secret == "secret"  # pragma: allowlist secret
        assert config.tenant_id == "tenant"
        assert config.document_library_id == "lib"
        assert config.folder_path == "/Shared Documents"
        assert config.file_extensions == [".pdf"]

    def test_rejects_invalid_graph_api_version(self):
        with pytest.raises(ValidationError, match="graph_api_version must be one of"):
            SharePointSourceConfig(
                client_id="client",
                client_secret="secret",  # pragma: allowlist secret
                tenant_id="tenant",
                document_library_id="lib",
                folder_path=None,
                recursive=True,
                max_file_size_mb=None,
                graph_api_version="v2",
            )


class TestOneDriveSourceAdapter:
    def make_config(self):
        return OneDriveSourceConfig(
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            drive_id="drive1",
            folder_path="/Docs",
            recursive=True,
            file_extensions=[".txt"],
            max_file_size_mb=1,
            graph_api_version="v1.0",
        )

    def test_build_config_from_operator_params(self):
        adapter = OneDriveSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "drive_id": "drive1",
                "folder_path": "Docs",
                "recursive": False,
                "client_id": "client",
                "client_secret": "secret",  # pragma: allowlist secret
                "tenant_id": "tenant",
            },
            included_extensions=["txt"],
        )

        config_data = config.model_dump()

        assert type(config).__name__ == "OneDriveSourceConfig"
        assert config_data["drive_id"] == "drive1"
        assert config_data["folder_path"] == "/Docs"
        assert config_data["recursive"] is False
        assert config_data["file_extensions"] == [".txt"]

    def test_fetch_documents_returns_metadata_only(self):
        """Test that fetch_documents returns documents with empty content (lazy loading)."""
        adapter = OneDriveSourceAdapter()
        config = self.make_config()

        # Mock file metadata from Graph API
        file1 = {
            "id": "1",
            "name": "file1.txt",
            "size": 1024,
            "lastModifiedDateTime": "2024-01-01T10:00:00Z",
            "createdDateTime": "2024-01-01T09:00:00Z",
            "webUrl": "https://example/1",
            "file": {"mimeType": "text/plain"},
        }

        file2 = {
            "id": "2",
            "name": "file2.txt",
            "size": 2048,
            "lastModifiedDateTime": "2024-01-02T10:00:00Z",
            "createdDateTime": "2024-01-02T09:00:00Z",
            "webUrl": "https://example/2",
            "file": {"mimeType": "text/plain"},
        }

        loader_instance = Mock()
        loader_instance._get_token.return_value = "mock_token"
        loader_instance._rest_client = Mock()
        loader_instance._list_files.return_value = [file1, file2]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 2
        # Verify lazy loading - content should be empty
        assert docs[0].content == b""
        assert docs[1].content == b""
        # Verify metadata is stored
        assert docs[0].id == "1"
        assert docs[0].name == "file1.txt"
        assert docs[0].size == 1024
        assert docs[0].metadata["item_id"] == "1"
        assert docs[0].metadata["client_id"] == "client"
        assert docs[1].id == "2"

    def test_fetch_documents_filters_extension_and_size(self):
        """Test that file extension and size filters work correctly."""
        adapter = OneDriveSourceAdapter()
        config = self.make_config()

        # File with wrong extension (should be skipped)
        skipped_ext = {
            "id": "1",
            "name": "file.pdf",
            "size": 100,
            "file": {"mimeType": "application/pdf"},
        }

        # File too large (should be skipped)
        skipped_size = {
            "id": "2",
            "name": "file.txt",
            "size": 2 * 1024 * 1024,  # 2MB, config max is 1MB
            "file": {"mimeType": "text/plain"},
        }

        loader_instance = Mock()
        loader_instance._get_token.return_value = "mock_token"
        loader_instance._rest_client = Mock()
        loader_instance._list_files.return_value = [skipped_ext, skipped_size]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert docs == []

    def test_test_connection_variants(self):
        adapter = OneDriveSourceAdapter()
        config = self.make_config()

        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance.lazy_load.return_value = [Mock(), Mock()]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is True
            assert "Found 2 document(s)" in message

        loader_instance._get_token.return_value = None
        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert message == "Failed to acquire access token"

    def test_resolve_onedrive_item_id_returns_direct_path(self):
        adapter = OneDriveSourceAdapter()
        item_id, drive_id = adapter._resolve_onedrive_item_id(
            file_path="item123",
            drive_id="drive1",
            loader=Mock(),
            token="token",
        )

        assert item_id == "item123"
        assert drive_id == "drive1"

    def test_resolve_onedrive_item_id_raises_for_invalid_url(self):
        adapter = OneDriveSourceAdapter()

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.extract_msgraph_file_id_from_url",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="Could not extract file ID"):
                adapter._resolve_onedrive_item_id(
                    file_path="https://example/invalid",
                    drive_id="drive1",
                    loader=Mock(),
                    token="token",
                )

    def test_resolve_folder_item_id_returns_id(self):
        loader = Mock()
        loader._rest_client.call_rest_json.return_value = {"id": "folder123"}

        folder_id = OneDriveSourceAdapter._resolve_folder_item_id(
            loader=loader,
            drive_id="drive1",
            folder_path="/Docs",
            headers={"Authorization": "Bearer token"},
        )

        assert folder_id == "folder123"

    def test_resolve_folder_item_id_raises_value_error_on_missing_folder(self):
        loader = Mock()
        loader._rest_client.call_rest_json.side_effect = RuntimeError("not found")

        with pytest.raises(ValueError, match="Folder path '/Docs' not found"):
            OneDriveSourceAdapter._resolve_folder_item_id(
                loader=loader,
                drive_id="drive1",
                folder_path="/Docs",
                headers={"Authorization": "Bearer token"},
            )

    def test_fetch_binary_content_returns_none_when_missing_required_params(self):
        adapter = OneDriveSourceAdapter()

        result = adapter.fetch_binary_content(
            source_id="item123",
            provider_config={"drive_id": "drive1", "client_id": "client"},
        )

        assert result is None

    def test_fetch_binary_content_uses_content_endpoint_without_download_url(self):
        adapter = OneDriveSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {}
        response = MagicMock()
        response.content = b"payload"
        loader_instance._rest_client.call_rest.return_value = response

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            result = adapter.fetch_binary_content(
                source_id="item123",
                provider_config={
                    "drive_id": "drive1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                },
            )

        assert result == b"payload"
        loader_instance._rest_client.call_rest.assert_called_once()

    def test_fetch_documents_single_file_uses_resolved_drive_id(self):
        adapter = OneDriveSourceAdapter()
        config = OneDriveSourceConfig(
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            drive_id="drive1",
            file_path="https://example/file/123",
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
            graph_api_version="v1.0",
        )
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "id": "item123",
            "name": "single.txt",
            "size": 99,
            "webUrl": "https://example/single.txt",
            "file": {"mimeType": "text/plain"},
        }

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
                return_value=loader_instance,
            ),
            patch.object(adapter, "_resolve_onedrive_item_id", return_value=("item123", "resolved-drive")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].metadata["drive_id"] == "resolved-drive"
        assert "source_id" not in docs[0].metadata
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url="/drives/resolved-drive/items/item123",
            headers={"Authorization": "Bearer token"},
        )

    def test_resolve_onedrive_item_id_resolves_url_to_item_and_drive(self):
        adapter = OneDriveSourceAdapter()
        loader = Mock()
        loader._rest_client = Mock()

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.extract_msgraph_file_id_from_url",
                return_value="file123",
            ),
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.resolve_msgraph_file_id_to_item_id",
                return_value=("item123", "resolved-drive"),
            ),
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.handle_msgraph_resolution_result",
                return_value=("item123", "resolved-drive"),
            ) as mock_handle,
        ):
            item_id, drive_id = adapter._resolve_onedrive_item_id(
                file_path="https://example/file/123",
                drive_id="drive1",
                loader=loader,
                token="token",
            )

        assert item_id == "item123"
        assert drive_id == "resolved-drive"
        mock_handle.assert_called_once_with(
            file_id="file123",
            item_id="item123",
            actual_drive_id="resolved-drive",
            fallback_drive_id="drive1",
            allow_guid_fallback=False,
            original_url="https://example/file/123",
        )

    def test_fetch_documents_wraps_folder_errors(self):
        adapter = OneDriveSourceAdapter()
        config = self.make_config()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client = Mock()

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
                return_value=loader_instance,
            ),
            patch.object(adapter, "_resolve_folder_item_id", side_effect=RuntimeError("bad folder")),
        ):
            with pytest.raises(ValueError, match="Failed to fetch documents from OneDrive"):
                asyncio.run(collect_async(adapter.fetch_documents(config)))

    def test_test_connection_covers_import_value_and_generic_errors(self):
        adapter = OneDriveSourceAdapter()
        config = self.make_config()

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            side_effect=ImportError,
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "dependencies not installed" in message

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            side_effect=ValueError("bad config"),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Configuration error" in message

        loader_instance = Mock()
        loader_instance._get_token.side_effect = RuntimeError("boom")
        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Connection test failed" in message

    def test_fetch_binary_content_uses_download_url_when_available(self):
        adapter = OneDriveSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "@microsoft.graph.downloadUrl": "https://download.example/file"
        }
        response = MagicMock()
        response.content = b"payload"

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
                return_value=loader_instance,
            ),
            patch("docpipe.integrations.rest_client.RestClient") as mock_rest_client,
        ):
            mock_rest_client.return_value.call_rest.return_value = response
            result = adapter.fetch_binary_content(
                source_id="item123",
                provider_config={
                    "drive_id": "drive1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                },
            )

        assert result == b"payload"
        mock_rest_client.return_value.call_rest.assert_called_once_with(
            method=ANY,
            url="https://download.example/file",
        )

    def test_fetch_binary_content_extracts_item_id_from_web_url(self):
        adapter = OneDriveSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {}
        response = MagicMock()
        response.content = b"payload"
        loader_instance._rest_client.call_rest.return_value = response

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            result = adapter.fetch_binary_content(
                source_id="https://example/item/123",
                provider_config={
                    "drive_id": "drive1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                    "item_id": "item123",
                },
            )

        assert result == b"payload"
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url="/drives/drive1/items/item123",
            headers={"Authorization": "Bearer token"},
        )


class TestSharePointSourceAdapter:
    def make_config(self):
        return SharePointSourceConfig(
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            document_library_id="lib1",
            folder_path="/Docs",
            recursive=True,
            file_extensions=[".txt"],
            max_file_size_mb=1,
            graph_api_version="v1.0",
        )

    def test_build_config_from_operator_params(self):
        adapter = SharePointSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "document_library_id": "lib1",
                "folder_path": "Docs",
                "recursive": False,
                "client_id": "client",
                "client_secret": "secret",  # pragma: allowlist secret
                "tenant_id": "tenant",
            },
            included_extensions=["txt"],
        )

        config_data = config.model_dump()

        assert type(config).__name__ == "SharePointSourceConfig"
        assert config_data["document_library_id"] == "lib1"
        assert config_data["folder_path"] == "/Docs"
        assert config_data["recursive"] is False
        assert config_data["file_extensions"] == [".txt"]

    def test_fetch_documents_returns_metadata_only(self):
        """Test that fetch_documents returns documents with empty content (lazy loading)."""
        adapter = SharePointSourceAdapter()
        config = self.make_config()

        # Mock file metadata from Graph API
        file1 = {
            "id": "1",
            "name": "file1.txt",
            "size": 1024,
            "lastModifiedDateTime": "2024-01-01T10:00:00Z",
            "createdDateTime": "2024-01-01T09:00:00Z",
            "webUrl": "https://example/1",
            "file": {"mimeType": "text/plain"},
        }

        loader_instance = Mock()
        loader_instance._get_token.return_value = "mock_token"
        loader_instance._rest_client = Mock()
        loader_instance._list_files.return_value = [file1]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        # Verify lazy loading - content should be empty
        assert docs[0].content == b""
        # Verify metadata is stored
        assert docs[0].metadata["document_library_id"] == "lib1"
        assert docs[0].metadata["item_id"] == "1"
        assert docs[0].source_url == "https://example/1"
        assert docs[0].size == 1024

    def test_test_connection_error_paths(self):
        adapter = SharePointSourceAdapter()
        config = self.make_config()

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            side_effect=ImportError,
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "dependencies not installed" in message

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            side_effect=ValueError("bad config"),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Configuration error" in message

    def test_resolve_sharepoint_item_id_returns_direct_path(self):
        adapter = SharePointSourceAdapter()
        item_id, document_library_id = adapter._resolve_sharepoint_item_id(
            file_path="item123",
            document_library_id="lib1",
            loader=Mock(),
            token="token",
        )

        assert item_id == "item123"
        assert document_library_id == "lib1"

    def test_resolve_sharepoint_item_id_raises_for_invalid_url(self):
        adapter = SharePointSourceAdapter()

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.extract_msgraph_file_id_from_url",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="Could not extract file ID"):
                adapter._resolve_sharepoint_item_id(
                    file_path="https://example/invalid",
                    document_library_id="lib1",
                    loader=Mock(),
                    token="token",
                )

    def test_resolve_sharepoint_folder_item_id_returns_id(self):
        loader = Mock()
        loader._rest_client.call_rest_json.return_value = {"id": "folder123"}

        folder_id = SharePointSourceAdapter._resolve_sharepoint_folder_item_id(
            loader=loader,
            document_library_id="lib1",
            folder_path="/Docs",
            headers={"Authorization": "Bearer token"},
        )

        assert folder_id == "folder123"

    def test_resolve_sharepoint_folder_item_id_raises_value_error_on_missing_folder(self):
        loader = Mock()
        loader._rest_client.call_rest_json.side_effect = RuntimeError("not found")

        with pytest.raises(ValueError, match="Folder path '/Docs' not found"):
            SharePointSourceAdapter._resolve_sharepoint_folder_item_id(
                loader=loader,
                document_library_id="lib1",
                folder_path="/Docs",
                headers={"Authorization": "Bearer token"},
            )

    def test_fetch_binary_content_returns_none_when_missing_required_params(self):
        adapter = SharePointSourceAdapter()

        result = adapter.fetch_binary_content(
            source_id="item123",
            provider_config={"document_library_id": "lib1", "client_id": "client"},
        )

        assert result is None

    def test_fetch_binary_content_uses_content_endpoint_without_download_url(self):
        adapter = SharePointSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {}
        response = MagicMock()
        response.content = b"payload"
        loader_instance._rest_client.call_rest.return_value = response

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            result = adapter.fetch_binary_content(
                source_id="item123",
                provider_config={
                    "document_library_id": "lib1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                },
            )

        assert result == b"payload"
        loader_instance._rest_client.call_rest.assert_called_once()

    def test_fetch_documents_single_file_uses_resolved_document_library_id(self):
        adapter = SharePointSourceAdapter()
        config = SharePointSourceConfig(
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            document_library_id="lib1",
            file_path="https://example/file/123",
            folder_path=None,
            recursive=False,
            max_file_size_mb=None,
            graph_api_version="v1.0",
        )
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "id": "item123",
            "name": "single.txt",
            "size": 99,
            "webUrl": "https://example/single.txt",
            "file": {"mimeType": "text/plain"},
        }

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
                return_value=loader_instance,
            ),
            patch.object(adapter, "_resolve_sharepoint_item_id", return_value=("item123", "resolved-lib")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].metadata["document_library_id"] == "resolved-lib"
        assert "source_id" not in docs[0].metadata
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url="/drives/resolved-lib/items/item123",
            headers={"Authorization": "Bearer token"},
        )

    def test_resolve_sharepoint_item_id_resolves_url_to_item_and_library(self):
        adapter = SharePointSourceAdapter()
        loader = Mock()
        loader._rest_client = Mock()

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.extract_msgraph_file_id_from_url",
                return_value="file123",
            ),
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.resolve_msgraph_file_id_to_item_id",
                return_value=("item123", "resolved-lib"),
            ),
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.handle_msgraph_resolution_result",
                return_value=("item123", "resolved-lib"),
            ) as mock_handle,
        ):
            item_id, document_library_id = adapter._resolve_sharepoint_item_id(
                file_path="https://example/file/123",
                document_library_id="lib1",
                loader=loader,
                token="token",
            )

        assert item_id == "item123"
        assert document_library_id == "resolved-lib"
        mock_handle.assert_called_once_with(
            file_id="file123",
            item_id="item123",
            actual_drive_id="resolved-lib",
            fallback_drive_id="lib1",
            allow_guid_fallback=True,
            original_url="https://example/file/123",
        )

    def test_fetch_documents_filters_sharepoint_items(self):
        adapter = SharePointSourceAdapter()
        config = self.make_config()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client = Mock()
        loader_instance._list_files.return_value = [
            {
                "id": "1",
                "name": "skip.pdf",
                "size": 10,
                "file": {"mimeType": "application/pdf"},
            },
            {
                "id": "2",
                "name": "keep.txt",
                "size": 20,
                "lastModifiedDateTime": "2024-01-01T10:00:00Z",
                "createdDateTime": "2024-01-01T09:00:00Z",
                "webUrl": "https://example/2",
                "file": {"mimeType": "text/plain"},
            },
        ]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].id == "2"

    def test_test_connection_success(self):
        adapter = SharePointSourceAdapter()
        config = self.make_config()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance.lazy_load.return_value = [Mock(), Mock()]

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            success, message = asyncio.run(adapter.test_connection(config))

        assert success is True
        assert "Found 2 document(s)" in message

    def test_fetch_binary_content_uses_download_url_when_available(self):
        adapter = SharePointSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "@microsoft.graph.downloadUrl": "https://download.example/file"
        }
        response = MagicMock()
        response.content = b"payload"

        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
                return_value=loader_instance,
            ),
            patch("docpipe.integrations.rest_client.RestClient") as mock_rest_client,
        ):
            mock_rest_client.return_value.call_rest.return_value = response
            result = adapter.fetch_binary_content(
                source_id="item123",
                provider_config={
                    "document_library_id": "lib1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                },
            )

        assert result == b"payload"
        mock_rest_client.return_value.call_rest.assert_called_once_with(
            method=ANY,
            url="https://download.example/file",
        )

    def test_fetch_binary_content_extracts_item_id_from_web_url(self):
        adapter = SharePointSourceAdapter()
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {}
        response = MagicMock()
        response.content = b"payload"
        loader_instance._rest_client.call_rest.return_value = response

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            result = adapter.fetch_binary_content(
                source_id="https://example/item/123",
                provider_config={
                    "document_library_id": "lib1",
                    "client_id": "client",
                    "client_secret": "secret",  # pragma: allowlist secret
                    "tenant_id": "tenant",
                    "item_id": "item123",
                },
            )

        assert result == b"payload"
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url="/drives/lib1/items/item123",
            headers={"Authorization": "Bearer token"},
        )


# ---------------------------------------------------------------------------
# bind_file_reference
# ---------------------------------------------------------------------------

_SHAREPOINT_SECRET = "test-client-secret"  # pragma: allowlist secret
_SHAREPOINT_ITEM_ID = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SHAREPOINT_FILE_URL = "https://contoso.sharepoint.com/?id=/sites/team/Shared%20Documents/Reports/q1.pdf"
_SHAREPOINT_SOURCEDOC_URL = (
    "https://contoso.sharepoint.com/:b:/r/sites/team/_layouts/15/Doc.aspx"
    "?sourcedoc={AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
)


def _sharepoint_provider_config() -> dict[str, str]:
    """Return SharePoint connection settings that must stay out of events and errors."""
    return {
        "client_id": "client-id",
        "client_secret": _SHAREPOINT_SECRET,
        "tenant_id": "tenant-id",
        "document_library_id": "library-id",
        "folder_path": "/Shared Documents",
    }


def _sharepoint_input_event(*, operation: str, file_reference: str) -> dict[str, str]:
    """Build a five-field file event for operator wiring tests."""
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440002",
        "event_timestamp": "2026-10-12T12:00:00Z",
        "routing_key": "invoices",
        "operation": operation,
        "file_reference": file_reference,
    }


def _assert_sharepoint_secrets_absent(message: str) -> None:
    """Credentials and connection details must not appear in a failure message."""
    assert _SHAREPOINT_SECRET not in message
    assert "client-id" not in message
    assert "tenant-id" not in message
    assert "library-id" not in message


class TestSharePointBindFileReference:
    """File-event binding for the SharePoint ingest provider."""

    @pytest.mark.parametrize(
        ("file_reference", "expected"),
        [
            (_SHAREPOINT_ITEM_ID, _SHAREPOINT_ITEM_ID),
            (f"  {_SHAREPOINT_ITEM_ID}  ", _SHAREPOINT_ITEM_ID),
            (_SHAREPOINT_FILE_URL, _SHAREPOINT_FILE_URL),
            (_SHAREPOINT_SOURCEDOC_URL, _SHAREPOINT_SOURCEDOC_URL),
        ],
    )
    def test_valid_file_reference_sets_file_path(self, *, file_reference: str, expected: str) -> None:
        """A valid item id or SharePoint URL is stored as file_path without a Graph call."""
        provider_config = _sharepoint_provider_config()

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader"
        ) as loader:
            SharePointSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=file_reference)

        loader.assert_not_called()
        assert provider_config["file_path"] == expected
        assert provider_config["folder_path"] == "/Shared Documents"
        assert provider_config["client_secret"] == _SHAREPOINT_SECRET  # pragma: allowlist secret
        assert provider_config["document_library_id"] == "library-id"

    def test_update_rebinds_the_same_or_a_new_reference(self) -> None:
        """A later event replaces file_path and leaves credentials in place."""
        provider_config = _sharepoint_provider_config()

        SharePointSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=_SHAREPOINT_ITEM_ID)
        SharePointSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=_SHAREPOINT_ITEM_ID)
        assert provider_config["file_path"] == _SHAREPOINT_ITEM_ID

        SharePointSourceAdapter.bind_file_reference(
            provider_config=provider_config, file_reference=_SHAREPOINT_FILE_URL
        )

        assert provider_config["file_path"] == _SHAREPOINT_FILE_URL
        assert provider_config["client_secret"] == _SHAREPOINT_SECRET  # pragma: allowlist secret
        assert provider_config["document_library_id"] == "library-id"

    @pytest.mark.parametrize(
        ("file_reference", "match"),
        [
            ("", "non-empty SharePoint item id or file URL"),
            ("   ", "non-empty SharePoint item id or file URL"),
            (None, "non-empty SharePoint item id or file URL"),
            (123, "non-empty SharePoint item id or file URL"),
            ("s3://other-bucket/invoices/a.pdf", "not a URI"),
            ("file:///tmp/invoice.pdf", "not a URI"),
            ("https://contoso.sharepoint.com/sites/team/Shared%20Documents/Reports/q1.pdf", "id or sourcedoc"),
            ("http://contoso.sharepoint.com/sites/team/q1.pdf?web=1", "id or sourcedoc"),
        ],
    )
    def test_invalid_file_reference_raises_value_error(
        self, *, file_reference: object, match: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unsupported references fail before file_path or connection settings change."""
        provider_config = _sharepoint_provider_config()
        caplog.set_level(logging.DEBUG)

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader"
        ) as loader:
            with pytest.raises(ValueError, match=match) as exc_info:
                SharePointSourceAdapter.bind_file_reference(
                    provider_config=provider_config,
                    file_reference=cast(str, file_reference),
                )

        loader.assert_not_called()
        assert "file_path" not in provider_config
        assert provider_config["client_secret"] == _SHAREPOINT_SECRET  # pragma: allowlist secret
        _assert_sharepoint_secrets_absent(str(exc_info.value))
        _assert_sharepoint_secrets_absent(caplog.text)

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_input_event_binds_file_path_and_forces_reingest(self, operation: str) -> None:
        """create and update events ingest that item even when force_ingest was off."""
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": _sharepoint_provider_config(),
                "force_ingest": False,
                "input_event": _sharepoint_input_event(
                    operation=operation, file_reference=f"  {_SHAREPOINT_ITEM_ID}  "
                ),
            }
        )

        assert operator.force_ingest is True
        adapter, config = operator._build_adapter_config(operator.provider)

        assert isinstance(adapter, SharePointSourceAdapter)
        assert config.file_path == _SHAREPOINT_ITEM_ID
        assert config.folder_path == "/Shared Documents"
        assert config.document_library_id == "library-id"
        assert config.client_secret == _SHAREPOINT_SECRET  # pragma: allowlist secret
        assert "file_path" not in operator.provider_config

        incremental = Mock()
        incremental.get_all_processed_docs.return_value = {"already-ingested": {"modified_time": 999}}
        with (
            patch(
                "docpipe.core.operators.ingest.ingest_source.get_incremental_update_service",
                return_value=incremental,
            ),
            patch.object(operator, "process_documents", return_value=[]),
        ):
            operator.transform(None)

        assert operator.previously_processed_docs_dict is None
        incremental.get_all_processed_docs.assert_not_called()

    def test_bound_reference_fetches_only_that_item(self) -> None:
        """A create event fetches the referenced item and does not scan the library."""
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": _sharepoint_provider_config(),
                "input_event": _sharepoint_input_event(operation="create", file_reference=_SHAREPOINT_ITEM_ID),
            }
        )
        adapter, config = operator._build_adapter_config(operator.provider)
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "id": _SHAREPOINT_ITEM_ID,
            "name": "q1.pdf",
            "size": 128,
            "webUrl": "https://contoso.sharepoint.com/q1.pdf",
            "file": {"mimeType": "application/pdf"},
            "lastModifiedDateTime": "2026-01-15T12:00:00Z",
        }

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader",
            return_value=loader_instance,
        ):
            documents = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(documents) == 1
        assert documents[0].id == _SHAREPOINT_ITEM_ID
        assert documents[0].name == "q1.pdf"
        assert documents[0].content == b""
        assert documents[0].metadata["document_library_id"] == "library-id"
        loader_instance._list_files.assert_not_called()
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url=f"/drives/library-id/items/{_SHAREPOINT_ITEM_ID}",
            headers={"Authorization": "Bearer token"},
        )

    def test_event_reference_stays_literal_while_credentials_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Event references are not expanded, and trusted credential variables still resolve."""
        monkeypatch.setenv("DOCPIPE_EVENT_CANARY", "worker-canary-value")
        monkeypatch.setenv("DOCPIPE_TEST_SECRET", "resolved-test-secret")
        provider_config = _sharepoint_provider_config()
        provider_config["client_secret"] = "${DOCPIPE_TEST_SECRET}"
        original_provider_config = dict(provider_config)
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": provider_config,
                "input_event": _sharepoint_input_event(operation="create", file_reference="${DOCPIPE_EVENT_CANARY}"),
            }
        )

        _, config = operator._build_adapter_config(operator.provider)

        assert config.file_path == "${DOCPIPE_EVENT_CANARY}"
        assert config.client_secret == "resolved-test-secret"  # pragma: allowlist secret
        assert "worker-canary-value" not in (config.file_path or "")
        assert operator.provider_config == original_provider_config

    def test_flow_without_input_event_keeps_library_scan(self) -> None:
        """A flow with no file event does not set file_path or force re-ingest."""
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": _sharepoint_provider_config(),
                "force_ingest": False,
            }
        )

        assert operator.force_ingest is False
        _, config = operator._build_adapter_config(operator.provider)

        assert config.file_path is None
        assert config.folder_path == "/Shared Documents"
        assert config.document_library_id == "library-id"
        assert "file_path" not in operator.provider_config

        incremental = Mock()
        incremental.get_all_processed_docs.return_value = {"already-ingested": {"modified_time": 1}}
        with (
            patch(
                "docpipe.core.operators.ingest.ingest_source.get_incremental_update_service",
                return_value=incremental,
            ),
            patch.object(operator, "process_documents", return_value=[]),
        ):
            operator.transform(None)

        assert operator.previously_processed_docs_dict == {"already-ingested": {"modified_time": 1}}
        incremental.get_all_processed_docs.assert_called_once()

    def test_flow_without_input_event_preserves_configured_file_path(self) -> None:
        """An explicit file_path on the flow is left unchanged when there is no event."""
        provider_config = _sharepoint_provider_config()
        provider_config["file_path"] = _SHAREPOINT_ITEM_ID
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": provider_config,
                "force_ingest": False,
            }
        )

        _, config = operator._build_adapter_config(operator.provider)

        assert operator.force_ingest is False
        assert config.file_path == _SHAREPOINT_ITEM_ID
        assert operator.provider_config["file_path"] == _SHAREPOINT_ITEM_ID

    def test_invalid_input_event_fails_without_leaking_credentials(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unsupported file_reference fails config build and leaves the flow config unchanged."""
        provider_config = _sharepoint_provider_config()
        operator = IngestSourceOperator(
            {
                "provider": "sharepoint",
                "provider_config": provider_config,
                "input_event": _sharepoint_input_event(
                    operation="create",
                    file_reference="https://contoso.sharepoint.com/sites/team/Shared%20Documents/Reports/q1.pdf",
                ),
            }
        )
        caplog.set_level(logging.DEBUG)

        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader"
        ) as loader:
            with pytest.raises(ValueError, match="id or sourcedoc") as exc_info:
                operator._build_adapter_config(operator.provider)

        loader.assert_not_called()
        assert "file_path" not in operator.provider_config
        assert operator.provider_config["client_secret"] == _SHAREPOINT_SECRET  # pragma: allowlist secret
        _assert_sharepoint_secrets_absent(str(exc_info.value))
        _assert_sharepoint_secrets_absent(caplog.text)


# ---------------------------------------------------------------------------
# OneDrive bind_file_reference
# ---------------------------------------------------------------------------

_ONEDRIVE_SECRET = "test-onedrive-secret"  # pragma: allowlist secret
_ONEDRIVE_ITEM_ID = "01QRSTUVWXYZABCDEFGHIJKLMN"
_ONEDRIVE_FILE_URL = "https://contoso-my.sharepoint.com/?id=/personal/ana_contoso_com/Documents/Reports/q1.pdf"
_ONEDRIVE_SOURCEDOC_URL = (
    "https://contoso-my.sharepoint.com/:w:/r/personal/ana_contoso_com/_layouts/15/Doc.aspx"
    "?sourcedoc={AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
)


def _onedrive_provider_config() -> dict[str, str]:
    """Return OneDrive connection settings that must stay out of events and errors."""
    return {
        "client_id": "onedrive-client-id",
        "client_secret": _ONEDRIVE_SECRET,
        "tenant_id": "onedrive-tenant-id",
        "drive_id": "onedrive-drive-id",
        "folder_path": "/Documents",
    }


def _onedrive_input_event(*, operation: str, file_reference: str) -> dict[str, str]:
    """Build a five-field file event for operator wiring tests."""
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440003",
        "event_timestamp": "2026-10-28T12:00:00Z",
        "routing_key": "invoices",
        "operation": operation,
        "file_reference": file_reference,
    }


def _assert_onedrive_secrets_absent(message: str) -> None:
    """Credentials and connection details must not appear in a failure message."""
    assert _ONEDRIVE_SECRET not in message
    assert "onedrive-client-id" not in message
    assert "onedrive-tenant-id" not in message
    assert "onedrive-drive-id" not in message


class TestOneDriveBindFileReference:
    """File-event binding for the OneDrive ingest provider."""

    @pytest.mark.parametrize(
        ("file_reference", "expected"),
        [
            (_ONEDRIVE_ITEM_ID, _ONEDRIVE_ITEM_ID),
            (f"  {_ONEDRIVE_ITEM_ID}  ", _ONEDRIVE_ITEM_ID),
            (_ONEDRIVE_FILE_URL, _ONEDRIVE_FILE_URL),
            (_ONEDRIVE_SOURCEDOC_URL, _ONEDRIVE_SOURCEDOC_URL),
        ],
    )
    def test_valid_file_reference_sets_file_path(self, *, file_reference: str, expected: str) -> None:
        """A valid item id or file URL is stored as file_path without a Graph call."""
        provider_config = _onedrive_provider_config()

        with patch.object(onedrive_adapter_module, "MicrosoftGraphLoader") as loader:
            OneDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=file_reference)

        loader.assert_not_called()
        assert provider_config["file_path"] == expected
        assert provider_config["folder_path"] == "/Documents"
        assert provider_config["client_secret"] == _ONEDRIVE_SECRET  # pragma: allowlist secret
        assert provider_config["drive_id"] == "onedrive-drive-id"

    def test_update_rebinds_the_same_or_a_new_reference(self) -> None:
        """A later event replaces file_path and leaves credentials in place."""
        provider_config = _onedrive_provider_config()

        OneDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=_ONEDRIVE_ITEM_ID)
        OneDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=_ONEDRIVE_ITEM_ID)
        assert provider_config["file_path"] == _ONEDRIVE_ITEM_ID

        OneDriveSourceAdapter.bind_file_reference(provider_config=provider_config, file_reference=_ONEDRIVE_FILE_URL)

        assert provider_config["file_path"] == _ONEDRIVE_FILE_URL
        assert provider_config["client_secret"] == _ONEDRIVE_SECRET  # pragma: allowlist secret
        assert provider_config["drive_id"] == "onedrive-drive-id"

    @pytest.mark.parametrize(
        ("file_reference", "match"),
        [
            ("", "non-empty OneDrive item id or file URL"),
            ("   ", "non-empty OneDrive item id or file URL"),
            (None, "non-empty OneDrive item id or file URL"),
            (123, "non-empty OneDrive item id or file URL"),
            ("s3://other-bucket/invoices/a.pdf", "not a URI"),
            ("file:///tmp/invoice.pdf", "not a URI"),
            ("https://contoso-my.sharepoint.com/personal/ana_contoso_com/Documents/q1.pdf", "id or sourcedoc"),
            ("http://onedrive.live.com/view.aspx?resid=ABC", "id or sourcedoc"),
        ],
    )
    def test_invalid_file_reference_raises_value_error(
        self, *, file_reference: object, match: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unsupported references fail before file_path or connection settings change."""
        provider_config = _onedrive_provider_config()
        caplog.set_level(logging.DEBUG)

        with patch.object(onedrive_adapter_module, "MicrosoftGraphLoader") as loader:
            with pytest.raises(ValueError, match=match) as exc_info:
                OneDriveSourceAdapter.bind_file_reference(
                    provider_config=provider_config,
                    file_reference=cast(str, file_reference),
                )

        loader.assert_not_called()
        assert "file_path" not in provider_config
        assert provider_config["client_secret"] == _ONEDRIVE_SECRET  # pragma: allowlist secret
        _assert_onedrive_secrets_absent(str(exc_info.value))
        _assert_onedrive_secrets_absent(caplog.text)

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_input_event_binds_file_path_and_forces_reingest(self, operation: str) -> None:
        """create and update events ingest that item even when force_ingest was off."""
        operator = IngestSourceOperator(
            {
                "provider": "onedrive",
                "provider_config": _onedrive_provider_config(),
                "force_ingest": False,
                "input_event": _onedrive_input_event(operation=operation, file_reference=f"  {_ONEDRIVE_ITEM_ID}  "),
            }
        )

        assert operator.force_ingest is True
        adapter, config = operator._build_adapter_config(operator.provider)

        assert isinstance(adapter, OneDriveSourceAdapter)
        assert config.file_path == _ONEDRIVE_ITEM_ID
        assert config.folder_path == "/Documents"
        assert config.drive_id == "onedrive-drive-id"
        assert config.client_secret == _ONEDRIVE_SECRET  # pragma: allowlist secret
        assert "file_path" not in operator.provider_config

        incremental = Mock()
        incremental.get_all_processed_docs.return_value = {"already-ingested": {"modified_time": 999}}
        with (
            patch(
                "docpipe.core.operators.ingest.ingest_source.get_incremental_update_service",
                return_value=incremental,
            ),
            patch.object(operator, "process_documents", return_value=[]),
        ):
            operator.transform(None)

        assert operator.previously_processed_docs_dict is None
        incremental.get_all_processed_docs.assert_not_called()

    def test_bound_reference_fetches_only_that_item(self) -> None:
        """A create event fetches the referenced item and does not list the drive."""
        operator = IngestSourceOperator(
            {
                "provider": "onedrive",
                "provider_config": _onedrive_provider_config(),
                "input_event": _onedrive_input_event(operation="create", file_reference=_ONEDRIVE_ITEM_ID),
            }
        )
        adapter, config = operator._build_adapter_config(operator.provider)
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {
            "id": _ONEDRIVE_ITEM_ID,
            "name": "q1.pdf",
            "size": 128,
            "webUrl": "https://contoso-my.sharepoint.com/q1.pdf",
            "file": {"mimeType": "application/pdf"},
            "lastModifiedDateTime": "2026-01-15T12:00:00Z",
        }

        with patch.object(onedrive_adapter_module, "MicrosoftGraphLoader", return_value=loader_instance):
            documents = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(documents) == 1
        assert documents[0].id == _ONEDRIVE_ITEM_ID
        assert documents[0].name == "q1.pdf"
        assert documents[0].content == b""
        assert documents[0].metadata["drive_id"] == "onedrive-drive-id"
        loader_instance._list_files.assert_not_called()
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url=f"/drives/onedrive-drive-id/items/{_ONEDRIVE_ITEM_ID}",
            headers={"Authorization": "Bearer token"},
        )

    def test_url_scheme_is_matched_case_insensitively_when_fetching(self) -> None:
        """A URL that binding accepts is resolved as a URL, and an id is never mistaken for one."""
        adapter = OneDriveSourceAdapter()

        with patch.object(onedrive_adapter_module, "extract_msgraph_file_id_from_url", return_value=None):
            with pytest.raises(ValueError, match="Could not extract file ID"):
                adapter._resolve_onedrive_item_id(
                    file_path="HTTPS://contoso-my.sharepoint.com/?id=/q1.pdf",
                    drive_id="drive1",
                    loader=Mock(),
                    token="token",
                )

        item_id, drive_id = adapter._resolve_onedrive_item_id(
            file_path="httpitem123", drive_id="drive1", loader=Mock(), token="token"
        )
        assert (item_id, drive_id) == ("httpitem123", "drive1")

    def test_binary_fetch_matches_url_scheme_case_insensitively(self) -> None:
        """A web URL source id with an uppercase scheme uses the item id, not the URL."""
        loader_instance = Mock()
        loader_instance._get_token.return_value = "token"
        loader_instance._rest_client.call_rest_json.return_value = {}
        response = MagicMock()
        response.content = b"payload"
        loader_instance._rest_client.call_rest.return_value = response
        provider_config = {**_onedrive_provider_config(), "item_id": _ONEDRIVE_ITEM_ID}

        with patch.object(onedrive_adapter_module, "MicrosoftGraphLoader", return_value=loader_instance):
            result = OneDriveSourceAdapter().fetch_binary_content(
                source_id="HTTPS://contoso-my.sharepoint.com/q1.pdf", provider_config=provider_config
            )

        assert result == b"payload"
        loader_instance._rest_client.call_rest_json.assert_called_once_with(
            method=ANY,
            url=f"/drives/onedrive-drive-id/items/{_ONEDRIVE_ITEM_ID}",
            headers={"Authorization": "Bearer token"},
        )

    def test_event_reference_stays_literal_while_credentials_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Event references are not expanded, and trusted credential variables still resolve."""
        monkeypatch.setenv("DOCPIPE_EVENT_CANARY", "worker-canary-value")
        monkeypatch.setenv("DOCPIPE_TEST_SECRET", "resolved-onedrive-secret")
        provider_config = _onedrive_provider_config()
        provider_config["client_secret"] = "${DOCPIPE_TEST_SECRET}"
        original_provider_config = dict(provider_config)
        operator = IngestSourceOperator(
            {
                "provider": "onedrive",
                "provider_config": provider_config,
                "input_event": _onedrive_input_event(operation="create", file_reference="${DOCPIPE_EVENT_CANARY}"),
            }
        )

        _, config = operator._build_adapter_config(operator.provider)

        assert config.file_path == "${DOCPIPE_EVENT_CANARY}"
        assert config.client_secret == "resolved-onedrive-secret"  # pragma: allowlist secret
        assert operator.provider_config == original_provider_config

    def test_flow_without_input_event_keeps_drive_scan(self) -> None:
        """A flow with no file event does not set file_path or force re-ingest."""
        operator = IngestSourceOperator(
            {
                "provider": "onedrive",
                "provider_config": _onedrive_provider_config(),
                "force_ingest": False,
            }
        )

        assert operator.force_ingest is False
        _, config = operator._build_adapter_config(operator.provider)

        assert config.file_path is None
        assert config.folder_path == "/Documents"
        assert "file_path" not in operator.provider_config

        incremental = Mock()
        incremental.get_all_processed_docs.return_value = {"already-ingested": {"modified_time": 1}}
        with (
            patch(
                "docpipe.core.operators.ingest.ingest_source.get_incremental_update_service",
                return_value=incremental,
            ),
            patch.object(operator, "process_documents", return_value=[]),
        ):
            operator.transform(None)

        assert operator.previously_processed_docs_dict == {"already-ingested": {"modified_time": 1}}
        incremental.get_all_processed_docs.assert_called_once()

    def test_invalid_input_event_fails_without_leaking_credentials(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unsupported file_reference fails config build and leaves the flow config unchanged."""
        operator = IngestSourceOperator(
            {
                "provider": "onedrive",
                "provider_config": _onedrive_provider_config(),
                "input_event": _onedrive_input_event(
                    operation="create",
                    file_reference="https://contoso-my.sharepoint.com/personal/ana_contoso_com/Documents/q1.pdf",
                ),
            }
        )
        caplog.set_level(logging.DEBUG)

        with patch.object(onedrive_adapter_module, "MicrosoftGraphLoader") as loader:
            with pytest.raises(ValueError, match="id or sourcedoc") as exc_info:
                operator._build_adapter_config(operator.provider)

        loader.assert_not_called()
        assert "file_path" not in operator.provider_config
        assert operator.provider_config["client_secret"] == _ONEDRIVE_SECRET  # pragma: allowlist secret
        _assert_onedrive_secrets_absent(str(exc_info.value))
        _assert_onedrive_secrets_absent(caplog.text)
