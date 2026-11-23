# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for the Google Drive source adapter.

The Drive API is replaced by an in-process fake service (``FakeDriveService``); Google auth
classes are patched at the adapter module, so no test contacts Google.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive import adapter as gd_module
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import GoogleDriveSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import GoogleDriveSourceConfig

FOLDER_MIME = "application/vnd.google-apps.folder"
SA_INFO = {"type": "service_account", "client_email": "svc@example.iam.gserviceaccount.com"}


class FakeRequest:
    """Drive API request whose ``execute`` returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        """Return the canned payload."""
        return self.payload


class FakeFiles:
    """Fake ``service.files()`` resource.

    ``pages`` maps a folder id to the list of pages returned for it, in order.
    """

    def __init__(self, *, pages=None, metadata=None):
        self.pages = {folder: list(folder_pages) for folder, folder_pages in (pages or {}).items()}
        self.metadata = metadata or {}
        self.list_calls: list[dict] = []
        self.media_calls: list[tuple[str, dict]] = []

    def list(self, **kwargs):
        """Return the next page for the folder named in the query."""
        self.list_calls.append(kwargs)
        folder_id = kwargs["q"].split("'")[1]
        return FakeRequest(self.pages[folder_id].pop(0))

    def get(self, *, fileId, fields):  # noqa: N803 - mirrors the Drive API keyword
        """Return metadata for ``fileId``."""
        return FakeRequest(self.metadata[fileId])

    def get_media(self, *, fileId):  # noqa: N803 - mirrors the Drive API keyword
        """Return a marker for a binary download request."""
        self.media_calls.append(("get_media", {"fileId": fileId}))
        return ("get_media", fileId)

    def export_media(self, *, fileId, mimeType):  # noqa: N803 - mirrors the Drive API keywords
        """Return a marker for a Workspace export request."""
        self.media_calls.append(("export_media", {"fileId": fileId, "mimeType": mimeType}))
        return ("export_media", fileId, mimeType)


class FakeDriveService:
    """Fake Drive v3 service exposing ``files()``."""

    def __init__(self, files: FakeFiles):
        self._files = files

    def files(self):
        """Return the fake files resource."""
        return self._files


class FakeDownloader:
    """Fake MediaIoBaseDownload writing two chunks and reporting progress once."""

    def __init__(self, buffer, request):
        self.buffer = buffer
        self.request = request
        self.chunks = [(Mock(progress=Mock(return_value=0.5)), False, b"he"), (None, True, b"llo")]

    def next_chunk(self):
        """Write the next chunk and return (status, done)."""
        status, done, data = self.chunks.pop(0)
        self.buffer.write(data)
        return status, done


def _file(file_id: str, name: str, **extra) -> dict:
    """Build a Drive file metadata dict."""
    return {"id": file_id, "name": name, "mimeType": extra.pop("mimeType", "application/pdf"), **extra}


def _folder(folder_id: str) -> dict:
    """Build a Drive folder metadata dict."""
    return {"id": folder_id, "name": folder_id, "mimeType": FOLDER_MIME}


def _sa_config(**overrides) -> GoogleDriveSourceConfig:
    """Build a service-account config for folder ``root-folder``."""
    params = {"service_account_json": SA_INFO, "folder_id": "root-folder"}
    params.update(overrides)
    return GoogleDriveSourceConfig(**params)


def _adapter_with_service(service) -> GoogleDriveSourceAdapter:
    """Return an adapter whose Drive service lookup yields ``service``."""
    adapter = GoogleDriveSourceAdapter()
    adapter._get_drive_service = Mock(return_value=service)  # type: ignore[method-assign]
    return adapter


async def _collect(generator):
    """Collect an async generator into a list."""
    return [item async for item in generator]


class TestConfigAuthValidation:
    """GoogleDriveSourceConfig auth-method validation."""

    def test_rejects_service_account_and_oauth_together(self):
        """Configuring both auth methods is rejected."""
        with pytest.raises(ValueError, match="Cannot use both Service Account and OAuth"):
            GoogleDriveSourceConfig(service_account_json=SA_INFO, credentials_json={"installed": {}})


class TestCredentialsCacheKey:
    """_credentials_cache_key for inline JSON credentials."""

    def test_dict_and_equivalent_text_produce_different_but_stable_keys(self):
        """Inline JSON is part of the key; identical inputs give identical keys."""
        key_dict = GoogleDriveSourceAdapter._credentials_cache_key(_sa_config())
        key_dict_again = GoogleDriveSourceAdapter._credentials_cache_key(_sa_config())
        key_text = GoogleDriveSourceAdapter._credentials_cache_key(_sa_config(service_account_json=json.dumps(SA_INFO)))

        assert key_dict == key_dict_again
        assert key_dict != key_text

    def test_oauth_json_changes_the_key(self):
        """Different inline OAuth client JSON (dict or text) yields different keys."""
        key_a = GoogleDriveSourceAdapter._credentials_cache_key(
            GoogleDriveSourceConfig(credentials_json={"installed": {"client_id": "a"}})
        )
        key_b = GoogleDriveSourceAdapter._credentials_cache_key(
            GoogleDriveSourceConfig(credentials_json='{"installed": {"client_id": "b"}}')
        )

        assert key_a != key_b


class TestLoadServiceAccountCredentials:
    """_load_service_account_credentials error handling."""

    def test_inline_json_text_is_parsed(self):
        """Inline JSON text is decoded before being passed to google-auth."""
        with patch.object(gd_module.ServiceAccountCredentials, "from_service_account_info") as from_info:
            GoogleDriveSourceAdapter._load_service_account_credentials(
                _sa_config(service_account_json=json.dumps(SA_INFO))
            )

        from_info.assert_called_once_with(SA_INFO, scopes=["https://www.googleapis.com/auth/drive.readonly"])

    def test_invalid_inline_json_raises_value_error(self):
        """Inline JSON that cannot be decoded raises a ValueError naming the inline source."""
        with pytest.raises(ValueError, match="from inline service_account_json"):
            GoogleDriveSourceAdapter._load_service_account_credentials(_sa_config(service_account_json="{not json"))

    def test_missing_json_and_path_raises_value_error(self):
        """A config without any service account source is rejected."""
        oauth_config = GoogleDriveSourceConfig(credentials_json={"installed": {}})

        with pytest.raises(ValueError, match="Service account JSON or path must be provided"):
            GoogleDriveSourceAdapter._load_service_account_credentials(oauth_config)

    def test_directory_path_raises_value_error(self, tmp_path: Path):
        """A service account path that is a directory is rejected."""
        config = GoogleDriveSourceConfig(service_account_json_path=str(tmp_path))

        with pytest.raises(ValueError, match="Service account path is not a file"):
            GoogleDriveSourceAdapter._load_service_account_credentials(config)

    def test_permission_error_is_reraised_as_permission_error(self, tmp_path: Path):
        """A PermissionError while reading the key file stays a PermissionError with context."""
        key_file = tmp_path / "sa.json"
        key_file.write_text("{}")
        config = GoogleDriveSourceConfig(service_account_json_path=str(key_file))

        with (
            patch.object(
                gd_module.ServiceAccountCredentials,
                "from_service_account_file",
                side_effect=PermissionError("denied"),
            ),
            pytest.raises(PermissionError, match="Permission denied accessing service account file"),
        ):
            GoogleDriveSourceAdapter._load_service_account_credentials(config)


class TestRefreshOrRunOAuthFlow:
    """_refresh_or_run_oauth_flow branches."""

    def _fake_flow(self):
        """Return an InstalledAppFlow double whose local server yields serializable credentials."""
        creds = Mock()
        creds.to_json.return_value = '{"token": "new"}'
        flow = Mock()
        flow.run_local_server.return_value = creds
        return flow, creds

    def test_inline_client_json_text_runs_flow_and_caches_token(self, tmp_path: Path):
        """Inline client JSON text starts the installed-app flow and the token is written."""
        flow, creds = self._fake_flow()
        token_path = tmp_path / "cache" / "token.json"

        with patch.object(gd_module.InstalledAppFlow, "from_client_config", return_value=flow) as from_config:
            result = GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                creds=None,
                credentials_json='{"installed": {"client_id": "x"}}',
                token_path=token_path,
                scopes=["scope"],
            )

        assert result is creds
        from_config.assert_called_once_with({"installed": {"client_id": "x"}}, scopes=["scope"])
        assert token_path.read_text() == '{"token": "new"}'

    def test_missing_credentials_file_raises_value_error(self, tmp_path: Path):
        """A credentials path that does not exist is reported as a load failure."""
        with pytest.raises(ValueError, match="Credentials file not found"):
            GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                creds=None,
                credentials_path=tmp_path / "missing.json",
                token_path=tmp_path / "token.json",
                scopes=["scope"],
            )

    def test_no_client_source_raises_value_error(self, tmp_path: Path):
        """Without client JSON or a credentials path the flow cannot start."""
        with pytest.raises(ValueError, match="Either credentials_json or credentials_path must be provided"):
            GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                creds=None, token_path=tmp_path / "token.json", scopes=["scope"]
            )

    def test_permission_error_keeps_type_and_mentions_path(self, tmp_path: Path):
        """A PermissionError while reading client secrets is re-raised as PermissionError."""
        client_file = tmp_path / "client.json"
        client_file.write_text("{}")

        with (
            patch.object(gd_module.InstalledAppFlow, "from_client_secrets_file", side_effect=PermissionError("denied")),
            pytest.raises(PermissionError, match="Permission denied accessing credentials"),
        ):
            GoogleDriveSourceAdapter._refresh_or_run_oauth_flow(
                creds=None, credentials_path=client_file, token_path=tmp_path / "token.json", scopes=["scope"]
            )


class TestGetCredentials:
    """_get_credentials OAuth branches."""

    def test_unvalidated_config_without_oauth_source_raises(self):
        """A config bypassing validation with no credentials at all is rejected."""
        config = GoogleDriveSourceConfig.model_construct(
            service_account_json=None,
            service_account_json_path=None,
            credentials_json=None,
            credentials_path=None,
        )

        with pytest.raises(ValueError, match="OAuth credentials_json or credentials_path is required"):
            GoogleDriveSourceAdapter()._get_credentials(config)

    def test_corrupt_cached_token_triggers_reauthentication(self, tmp_path: Path):
        """An unreadable cached token is ignored and the OAuth flow is run."""
        token_path = tmp_path / "token.json"
        token_path.write_text("{corrupt")
        config = GoogleDriveSourceConfig(credentials_json={"installed": {}}, token_path=str(token_path))
        fresh = Mock()

        with patch.object(GoogleDriveSourceAdapter, "_refresh_or_run_oauth_flow", return_value=fresh) as run_flow:
            result = GoogleDriveSourceAdapter()._get_credentials(config)

        assert result is fresh
        assert run_flow.call_args.kwargs["creds"] is None
        assert run_flow.call_args.kwargs["token_path"] == token_path


class TestPrepareDocument:
    """_prepare_document metadata mapping."""

    def test_missing_modified_time_and_workspace_extension(self):
        """Workspace files get an extension from their MIME type; no modifiedTime leaves it None."""
        doc = GoogleDriveSourceAdapter()._prepare_document(
            file_metadata={
                "id": "doc-1",
                "name": "Quarterly plan",
                "mimeType": OperatorConstants.MimeTypes.GOOGLE_APPS_SPREADSHEET,
            },
            config=_sa_config(),
        )

        assert doc.modified_time is None
        assert doc.extension == ".xlsx"
        assert doc.source_url == "https://drive.google.com/file/d/doc-1"
        assert doc.size == 0

    def test_unparseable_modified_time_is_ignored(self):
        """An invalid modifiedTime string does not fail document creation."""
        doc = GoogleDriveSourceAdapter()._prepare_document(
            file_metadata={"id": "f", "name": "a.pdf", "modifiedTime": "yesterday", "size": "12"},
            config=_sa_config(),
        )

        assert doc.modified_time is None
        assert doc.size == 12

    def test_unknown_workspace_type_keeps_empty_extension(self):
        """A Workspace type without a mapping (e.g. a form) keeps an empty extension."""
        doc = GoogleDriveSourceAdapter()._prepare_document(
            file_metadata={"id": "f", "name": "Survey", "mimeType": "application/vnd.google-apps.form"},
            config=_sa_config(),
        )

        assert doc.extension == ""


class TestBuildDriveQuery:
    """_build_drive_query MIME filter handling."""

    def test_extensions_without_mime_mapping_add_no_filter(self):
        """Extensions the query cannot express as MIME types leave only folder and trash filters."""
        query = GoogleDriveSourceAdapter()._build_drive_query(folder_id="f1", file_extensions=[".md", ".csv"])

        assert query == "'f1' in parents and trashed = false"


class TestListFilesFromDrive:
    """Folder traversal through _list_files_from_drive and _fetch_folder_pages."""

    def test_follows_page_tokens_and_subfolders_without_limit(self):
        """All pages and sub-folders are visited when max_files is not set."""
        files = FakeFiles(
            pages={
                "root-folder": [
                    {"files": [_file("a", "a.pdf"), _folder("sub")], "nextPageToken": "p2"},
                    {"files": [_file("b", "b.pdf")]},
                ],
                "sub": [{"files": [_file("c", "c.pdf")]}],
            }
        )
        adapter = _adapter_with_service(FakeDriveService(files))

        result = adapter._list_files_from_drive(config=_sa_config(recursive=True))

        assert [item["id"] for item in result] == ["a", "b", "c"]
        assert [call["pageToken"] for call in files.list_calls] == [None, "p2", None]
        assert all(call["pageSize"] == 100 for call in files.list_calls)

    def test_subfolders_are_ignored_when_not_recursive(self):
        """With recursive=False folders found in a listing are not traversed."""
        files = FakeFiles(pages={"root-folder": [{"files": [_folder("sub"), _file("a", "a.pdf")]}]})
        adapter = _adapter_with_service(FakeDriveService(files))

        result = adapter._list_files_from_drive(config=_sa_config(recursive=False))

        assert [item["id"] for item in result] == ["a"]
        assert len(files.list_calls) == 1

    def test_limit_reached_on_page_boundary_stops_before_next_request(self):
        """When a page fills max_files exactly, no further page is requested."""
        files = FakeFiles(
            pages={"root-folder": [{"files": [_file("a", "a.pdf"), _file("b", "b.pdf")], "nextPageToken": "p2"}]}
        )
        adapter = _adapter_with_service(FakeDriveService(files))

        result = adapter._list_files_from_drive(config=_sa_config(max_files=2))

        assert [item["id"] for item in result] == ["a", "b"]
        assert files.list_calls[0]["pageSize"] == 2
        assert len(files.list_calls) == 1

    def test_fetch_folder_pages_returns_immediately_when_already_full(self):
        """A folder is not listed when the collected files already reach max_files."""
        files = FakeFiles()
        all_files = [_file("a", "a.pdf")]

        reached = GoogleDriveSourceAdapter()._fetch_folder_pages(
            service=FakeDriveService(files),
            folder_id="other",
            config=_sa_config(max_files=1),
            all_files=all_files,
            folders_to_process=Mock(),
        )

        assert reached is True
        assert files.list_calls == []

    def test_no_folder_id_lists_nothing(self):
        """Without a folder id there is nothing to traverse."""
        files = FakeFiles()
        adapter = _adapter_with_service(FakeDriveService(files))

        assert adapter._list_files_from_drive(config=_sa_config(folder_id=None)) == []
        assert files.list_calls == []


class TestGetDriveService:
    """_get_drive_service caching and import handling."""

    def test_service_is_built_once_per_credentials(self):
        """Repeated lookups with the same credentials reuse the built service."""
        adapter = GoogleDriveSourceAdapter()
        service = object()

        with (
            patch.object(adapter, "_get_credentials", return_value="creds") as get_creds,
            patch("googleapiclient.discovery.build", return_value=service) as build,
        ):
            first = adapter._get_drive_service(config=_sa_config())
            second = adapter._get_drive_service(config=_sa_config())

        assert first is service
        assert second is service
        get_creds.assert_called_once()
        build.assert_called_once_with("drive", "v3", credentials="creds")

    def test_missing_google_client_raises_import_error(self):
        """A missing google-api-python-client is reported with an install hint."""
        with (
            patch.dict(sys.modules, {"googleapiclient.discovery": None}),
            pytest.raises(ImportError, match="pip install google-api-python-client"),
        ):
            GoogleDriveSourceAdapter()._get_drive_service(config=_sa_config())


class TestShouldSkipFile:
    """_should_skip_file size filter."""

    def test_file_within_size_limit_is_kept(self):
        """A file below max_file_size_mb passes the filter."""
        config = _sa_config(max_file_size_mb=1)

        assert (
            GoogleDriveSourceAdapter()._should_skip_file(file_metadata=_file("a", "a.pdf", size="1024"), config=config)
            is False
        )


class TestFetchDocuments:
    """fetch_documents folder and single-file modes."""

    def test_filtered_files_are_skipped_and_breakdown_logged(self):
        """Files rejected by the extension filter are not yielded."""
        files = FakeFiles(pages={"root-folder": [{"files": [_file("a", "a.pdf"), _file("b", "b.exe")]}]})
        adapter = _adapter_with_service(FakeDriveService(files))

        docs = asyncio.run(_collect(adapter.fetch_documents(_sa_config(file_extensions=[".pdf"]))))

        assert [doc.id for doc in docs] == ["a"]
        assert docs[0].metadata["source_id"] == "a"

    def test_empty_folder_yields_nothing(self):
        """An empty folder produces no documents."""
        files = FakeFiles(pages={"root-folder": [{"files": []}]})
        adapter = _adapter_with_service(FakeDriveService(files))

        assert asyncio.run(_collect(adapter.fetch_documents(_sa_config()))) == []

    def test_max_files_caps_yielded_documents(self):
        """fetch_documents stops yielding once max_files documents were produced."""
        config = _sa_config(max_files=1)
        adapter = GoogleDriveSourceAdapter()
        docs = [
            adapter._prepare_document(file_metadata=_file("a", "a.pdf"), config=config),
            adapter._prepare_document(file_metadata=_file("b", "b.pdf"), config=config),
        ]

        with patch.object(adapter, "_iter_documents", return_value=docs):
            result = asyncio.run(_collect(adapter.fetch_documents(config)))

        assert [doc.id for doc in result] == ["a"]

    def test_single_file_mode_fetches_metadata_by_id(self):
        """With file_id set only that file's metadata is fetched."""
        files = FakeFiles(metadata={"file-1": _file("file-1", "one.pdf", webViewLink="https://drive/one")})
        adapter = _adapter_with_service(FakeDriveService(files))

        docs = asyncio.run(_collect(adapter.fetch_documents(_sa_config(file_id="file-1"))))

        assert [(doc.id, doc.source_url) for doc in docs] == [("file-1", "https://drive/one")]
        assert files.list_calls == []


class TestFetchBinaryContent:
    """fetch_binary_content download and export paths."""

    @pytest.fixture(autouse=True)
    def _fake_downloader(self):
        """Replace MediaIoBaseDownload with the in-process fake."""
        with patch("googleapiclient.http.MediaIoBaseDownload", FakeDownloader):
            yield

    def _fetch(self, *, files: FakeFiles, provider_config: dict) -> tuple[bytes | None, Mock]:
        """Run fetch_binary_content against a fake service and return (content, service lookup mock)."""
        adapter = GoogleDriveSourceAdapter()
        get_service = Mock(return_value=FakeDriveService(files))
        with patch.object(adapter, "_get_drive_service", get_service):
            content = adapter.fetch_binary_content(source_id="file-1", provider_config=provider_config)
        return content, get_service

    def test_regular_file_is_downloaded_with_service_account_json(self):
        """A regular file is downloaded in chunks using inline service account credentials."""
        files = FakeFiles(metadata={"file-1": {"mimeType": "application/pdf", "name": "a.pdf"}})

        content, get_service = self._fetch(files=files, provider_config={"service_account_json": SA_INFO})

        assert content == b"hello"
        assert files.media_calls == [("get_media", {"fileId": "file-1"})]
        used_config = get_service.call_args.kwargs["config"]
        assert used_config.service_account_json == SA_INFO
        assert used_config.folder_id == "root"

    def test_workspace_document_is_exported_as_pdf(self):
        """Google Docs are exported as PDF using the service account key file path."""
        files = FakeFiles(
            metadata={"file-1": {"mimeType": OperatorConstants.MimeTypes.GOOGLE_APPS_DOCUMENT, "name": "Doc"}}
        )

        content, get_service = self._fetch(files=files, provider_config={"service_account_json_path": "/keys/sa.json"})

        assert content == b"hello"
        assert files.media_calls == [
            ("export_media", {"fileId": "file-1", "mimeType": OperatorConstants.MimeTypes.PDF})
        ]
        assert get_service.call_args.kwargs["config"].service_account_json_path is not None

    def test_oauth_client_json_uses_default_token_path(self):
        """Inline OAuth client JSON is used with the default token path when none is given."""
        files = FakeFiles(metadata={"file-1": {"mimeType": "text/plain", "name": "a.txt"}})

        content, get_service = self._fetch(files=files, provider_config={"credentials_json": {"installed": {}}})

        assert content == b"hello"
        used_config = get_service.call_args.kwargs["config"]
        assert used_config.credentials_json == {"installed": {}}
        assert used_config.token_path == "~/.docpipe/google_drive_token.json"

    def test_missing_credentials_return_none(self):
        """Without any credentials the temporary config is invalid and None is returned."""
        files = FakeFiles(metadata={})

        content, get_service = self._fetch(files=files, provider_config={})

        assert content is None
        get_service.assert_not_called()

    def test_api_error_returns_none(self):
        """Errors from the Drive API are logged and reported as None."""
        files = FakeFiles(metadata={})  # unknown fileId -> KeyError from the fake

        content, _ = self._fetch(files=files, provider_config={"service_account_json": SA_INFO})

        assert content is None


class TestBuildConfigInlineCredentials:
    """build_config_from_operator_params with inline JSON credentials."""

    def test_inline_oauth_json_is_passed_through(self):
        """Inline OAuth client JSON ends up in the config."""
        config = GoogleDriveSourceAdapter().build_config_from_operator_params(
            provider_config={"folder_id": "f", "credentials_json": {"installed": {}}}
        )

        assert config.credentials_json == {"installed": {}}
        assert config.is_service_account() is False

    def test_inline_service_account_json_is_passed_through(self):
        """Inline service account JSON ends up in the config."""
        config = GoogleDriveSourceAdapter().build_config_from_operator_params(
            provider_config={"folder_id": "f", "service_account_json": SA_INFO}
        )

        assert config.service_account_json == SA_INFO
        assert config.is_service_account() is True
