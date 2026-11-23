# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for the OneDrive source adapter.

Microsoft Graph is replaced by an in-process fake loader and REST client, so no test
acquires a token or contacts Graph.
"""

import asyncio
from unittest.mock import patch

import pytest

from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive import adapter as onedrive_module
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import OneDriveSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig

PROVIDER_CONFIG = {
    "drive_id": "drive-1",
    "client_id": "client",
    "client_secret": "secret",  # pragma: allowlist secret
    "tenant_id": "tenant",
}


class FakeRestClient:
    """Fake Graph RestClient answering by URL; exceptions in the mapping are raised."""

    def __init__(self, json_responses=None):
        self.json_responses = json_responses or {}
        self.urls: list[str] = []

    def call_rest_json(self, *, method, url, headers):
        """Return or raise the canned JSON answer for ``url``."""
        self.urls.append(url)
        response = self.json_responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class FakeGraphLoader:
    """Stand-in for MicrosoftGraphLoader with a fixed token and file listing."""

    def __init__(self, *, files=None, rest_client=None, token="tok", token_error=None):
        self.files = files or []
        self._rest_client = rest_client or FakeRestClient()
        self.token = token
        self.token_error = token_error
        self.listed_folders: list[str | None] = []

    def _get_token(self):
        """Return the token or raise the configured error."""
        if self.token_error:
            raise self.token_error
        return self.token

    def _list_files(self, folder_item_id=None):
        """Record the folder and return the canned files."""
        self.listed_folders.append(folder_item_id)
        return self.files


def _config(**overrides) -> OneDriveSourceConfig:
    """Build a OneDrive config for drive-1."""
    params = {**PROVIDER_CONFIG, "folder_path": None, "recursive": True}
    params.update(overrides)
    return OneDriveSourceConfig(**params)


async def _collect(generator):
    """Collect an async generator into a list."""
    return [item async for item in generator]


class TestGetLoader:
    """_get_loader caching."""

    def test_loader_is_cached_per_credentials(self):
        """The same credentials reuse one loader; a rotated secret creates a new one."""
        adapter = OneDriveSourceAdapter()

        with patch.object(onedrive_module, "MicrosoftGraphLoader", side_effect=lambda **_: object()) as loader_cls:
            first = adapter._get_loader(drive_id="d", client_id="c", client_secret="s1", tenant_id="t")
            second = adapter._get_loader(drive_id="d", client_id="c", client_secret="s1", tenant_id="t")
            rotated = adapter._get_loader(drive_id="d", client_id="c", client_secret="s2", tenant_id="t")

        assert first is second
        assert rotated is not first
        assert loader_cls.call_count == 2


class TestBuildDocument:
    """_build_onedrive_document mapping."""

    def test_unparseable_modified_time_is_ignored(self):
        """An invalid lastModifiedDateTime leaves modified_time unset."""
        doc = OneDriveSourceAdapter()._build_onedrive_document(
            item={"id": "i1", "name": "a.txt", "lastModifiedDateTime": "not-a-date"},
            drive_id="drive-1",
            config=_config(),
        )

        assert doc.modified_time is None
        assert doc.source_url == "https://onedrive.live.com/?cid=i1"
        assert doc.metadata["source_id"] == "i1"


class TestFetchDocuments:
    """fetch_documents folder mode and error wrapping."""

    def test_drive_root_is_listed_without_folder_path(self):
        """Without folder_path the drive root is listed and no folder lookup happens."""
        loader = FakeGraphLoader(files=[{"id": "i1", "name": "a.txt", "size": 3}])
        adapter = OneDriveSourceAdapter()

        with patch.object(adapter, "_get_loader", return_value=loader):
            docs = asyncio.run(_collect(adapter.fetch_documents(_config())))

        assert [doc.id for doc in docs] == ["i1"]
        assert loader.listed_folders == [None]
        assert loader._rest_client.urls == []

    def test_missing_dependency_is_reraised_as_import_error(self):
        """An ImportError while talking to Graph is surfaced with an install hint."""
        loader = FakeGraphLoader(token_error=ImportError("msal"))
        adapter = OneDriveSourceAdapter()

        with (
            patch.object(adapter, "_get_loader", return_value=loader),
            pytest.raises(ImportError, match="pip install msal requests"),
        ):
            asyncio.run(_collect(adapter.fetch_documents(_config())))


class TestFetchBinaryContent:
    """fetch_binary_content failure paths."""

    def test_web_url_without_item_id_returns_none(self):
        """A web URL source_id needs an item_id in provider_config; without it nothing is fetched."""
        adapter = OneDriveSourceAdapter()

        with patch.object(adapter, "_get_loader") as get_loader:
            content = adapter.fetch_binary_content(
                source_id="https://contoso-my.sharepoint.com/personal/a.docx", provider_config=PROVIDER_CONFIG
            )

        assert content is None
        get_loader.assert_not_called()

    def test_graph_error_returns_none(self):
        """Errors raised by Graph calls are logged and reported as None."""
        rest = FakeRestClient(json_responses={"/drives/drive-1/items/i1": RuntimeError("503")})
        adapter = OneDriveSourceAdapter()

        with patch.object(adapter, "_get_loader", return_value=FakeGraphLoader(rest_client=rest)):
            content = adapter.fetch_binary_content(source_id="i1", provider_config=PROVIDER_CONFIG)

        assert content is None
        assert rest.urls == ["/drives/drive-1/items/i1"]


class TestBuildConfigOptionalKeys:
    """build_config_from_operator_params optional keys."""

    def test_file_path_and_graph_api_version_are_forwarded(self):
        """file_path and graph_api_version from provider_config reach the config."""
        config = OneDriveSourceAdapter().build_config_from_operator_params(
            provider_config={**PROVIDER_CONFIG, "file_path": "item-42", "graph_api_version": "beta"}
        )

        assert isinstance(config, OneDriveSourceConfig)
        assert config.file_path == "item-42"
        assert config.graph_api_version == "beta"
        assert config.file_extensions == []
