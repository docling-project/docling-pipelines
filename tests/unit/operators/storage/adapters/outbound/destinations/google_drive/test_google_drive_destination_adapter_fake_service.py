# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for GoogleDriveDestinationAdapter against an in-process fake Drive v3 service."""

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive import adapter as gdrive_module
from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.adapter import (
    GoogleDriveDestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.config import (
    GoogleDriveDestinationConfig,
)

_FOLDER_MIME = "application/vnd.google-apps.folder"
_ROOT = "root_folder_id"
_SHARED_DRIVE = "shared_drive_id"


def _clause(pattern: str, query: str) -> str:
    """Return the first group of ``pattern`` in the query; the adapter always sends these clauses."""
    match = re.search(pattern, query)
    assert match is not None, query
    return match.group(1)


class _Request:
    """Deferred API call, like googleapiclient's HttpRequest."""

    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> Any:
        """Return the prepared result."""
        return self._result


class _FakeFiles:
    """Fake of ``service.files()`` that keeps items in memory and records every call."""

    def __init__(self, drive: "_FakeDrive") -> None:
        self._drive = drive

    def get(self, **kwargs: Any) -> _Request:
        """Return the metadata of one item."""
        self._drive.calls.append(("get", kwargs))
        return _Request(self._drive.items[kwargs["fileId"]])

    def list(self, **kwargs: Any) -> _Request:
        """Return the items matching the name / mimeType / parent clauses of ``q``."""
        self._drive.calls.append(("list", kwargs))
        query = kwargs["q"]
        name = _clause(r"name='((?:[^'\\]|\\.)*)'", query).replace("\\'", "'")
        parent = _clause(r"'([^']+)' in parents", query)
        folders_only = f"mimeType='{_FOLDER_MIME}'" in query
        matches = [
            {"id": item_id}
            for item_id, item in self._drive.items.items()
            if item["name"] == name
            and parent in item.get("parents", [])
            and (not folders_only or item["mimeType"] == _FOLDER_MIME)
        ]
        return _Request({"files": matches[: kwargs["pageSize"]]})

    def create(self, **kwargs: Any) -> _Request:
        """Store a new folder or file and return its id (and link for files)."""
        self._drive.calls.append(("create", kwargs))
        body = kwargs["body"]
        item_id = f"id_{len(self._drive.items)}"
        media = kwargs.get("media_body")
        self._drive.items[item_id] = {
            "name": body["name"],
            "mimeType": media.mimetype() if media else body["mimeType"],
            "parents": body["parents"],
            "content": media.getbytes(0, media.size()) if media else None,
        }
        return _Request({"id": item_id, "webViewLink": f"https://drive.example/{item_id}"})


class _FakeDrive:
    """In-process stand-in for the Drive v3 service object."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {_ROOT: {"name": "Root", "mimeType": _FOLDER_MIME, "parents": []}}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def files(self) -> _FakeFiles:
        """Return the files resource."""
        return _FakeFiles(self)

    def add(self, *, item_id: str, name: str, parent: str, folder: bool) -> None:
        """Seed an existing item."""
        mime = _FOLDER_MIME if folder else "text/plain"
        self.items[item_id] = {"name": name, "mimeType": mime, "parents": [parent]}

    def calls_of(self, method: str) -> list[dict[str, Any]]:
        """Return the kwargs of every call of ``method``."""
        return [kwargs for name, kwargs in self.calls if name == method]


def _config(**overrides: Any) -> GoogleDriveDestinationConfig:
    params: dict[str, Any] = {"folder_id": _ROOT, "service_account_json_path": "sa.json"}
    return GoogleDriveDestinationConfig(**{**params, **overrides})


@pytest.fixture
def drive() -> _FakeDrive:
    """Return an empty fake drive."""
    return _FakeDrive()


@pytest.fixture
def adapter(drive: _FakeDrive) -> GoogleDriveDestinationAdapter:
    """Return an adapter whose service is the fake drive."""
    instance = GoogleDriveDestinationAdapter()
    with patch.object(GoogleDriveDestinationAdapter, "_build_service", return_value=drive):
        yield instance


class TestSharedDrive:
    """With drive_id set, every Drive call targets the shared drive."""

    def test_validate_passes_drive_id(self, adapter: GoogleDriveDestinationAdapter, drive: _FakeDrive) -> None:
        """validate_destination sends driveId with the folder lookup."""
        assert adapter.validate_destination(config=_config(drive_id=_SHARED_DRIVE)) is None
        assert drive.calls_of("get")[0]["driveId"] == _SHARED_DRIVE

    def test_nested_upload_reuses_existing_folder_and_creates_missing_one(
        self, adapter: GoogleDriveDestinationAdapter, drive: _FakeDrive
    ) -> None:
        """An existing folder is found, a missing one is created, and all calls carry the shared drive."""
        drive.add(item_id="existing_a", name="a", parent=_ROOT, folder=True)

        result = adapter.write_document(
            content=b"hello", destination_path="a/b/doc.txt", config=_config(drive_id=_SHARED_DRIVE)
        )

        assert result.success is True
        assert result.bytes_written == 5
        folder_creates = [c for c in drive.calls_of("create") if c.get("media_body") is None]
        assert [c["body"]["name"] for c in folder_creates] == ["b"]
        assert folder_creates[0]["body"]["parents"] == ["existing_a"]
        assert folder_creates[0]["body"]["driveId"] == _SHARED_DRIVE
        assert folder_creates[0]["supportsAllDrives"] is True
        upload = next(c for c in drive.calls_of("create") if c.get("media_body") is not None)
        assert upload["body"]["driveId"] == _SHARED_DRIVE
        assert upload["supportsAllDrives"] is True
        created_b = next(item_id for item_id, item in drive.items.items() if item["name"] == "b")
        assert upload["body"]["parents"] == [created_b]
        for listing in drive.calls_of("list"):
            assert listing["driveId"] == _SHARED_DRIVE
            assert listing["corpora"] == "drive"
            assert listing["includeItemsFromAllDrives"] is True
        uploaded = [item for item in drive.items.values() if item["name"] == "doc.txt"]
        assert uploaded[0]["content"] == b"hello"
        assert uploaded[0]["mimeType"] == "text/plain"

    def test_existing_folder_is_cached(self, adapter: GoogleDriveDestinationAdapter, drive: _FakeDrive) -> None:
        """A found folder is looked up once across writes."""
        drive.add(item_id="existing_a", name="a", parent=_ROOT, folder=True)
        config = _config()

        adapter.write_document(content=b"1", destination_path="a/one.txt", config=config)
        adapter.write_document(content=b"2", destination_path="a/two.txt", config=config)

        folder_lookups = [c for c in drive.calls_of("list") if _FOLDER_MIME in c["q"]]
        assert len(folder_lookups) == 1
        assert all(item["parents"] == ["existing_a"] for item in drive.items.values() if item["name"].endswith(".txt"))

    def test_overwrite_disabled_checks_shared_drive(
        self, adapter: GoogleDriveDestinationAdapter, drive: _FakeDrive
    ) -> None:
        """The existence check runs against the shared drive and blocks the upload."""
        drive.add(item_id="f1", name="it's.txt", parent=_ROOT, folder=False)

        result = adapter.write_document(
            content=b"x", destination_path="it's.txt", overwrite=False, config=_config(drive_id=_SHARED_DRIVE)
        )

        assert result.success is False
        assert result.error_message == "file exists, overwrite disabled"
        listing = drive.calls_of("list")[0]
        assert "name='it\\'s.txt'" in listing["q"]
        assert listing["driveId"] == _SHARED_DRIVE
        assert not [c for c in drive.calls_of("create") if c.get("media_body") is not None]

    def test_unknown_extension_uploads_as_octet_stream(
        self, adapter: GoogleDriveDestinationAdapter, drive: _FakeDrive
    ) -> None:
        """Files without a known extension use application/octet-stream."""
        adapter.write_document(content=b"x", destination_path="blob.unknownext", config=_config())

        upload = drive.calls_of("create")[0]
        assert upload["media_body"].mimetype() == "application/octet-stream"
        assert "supportsAllDrives" not in upload
        assert "driveId" not in upload["body"]


class TestBuildService:
    """_build_service reuses the ingest adapter's credential logic."""

    def _build(self, config: GoogleDriveDestinationConfig) -> tuple[Any, Any, Any]:
        with (
            patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter."
                "GoogleDriveSourceAdapter._get_credentials",
                return_value="creds",
            ) as get_credentials,
            patch.object(gdrive_module, "_gdrive_build", return_value="service") as build,
        ):
            service = GoogleDriveDestinationAdapter()._build_service(config)
        return service, get_credentials.call_args.args[0], build

    def test_service_account(self) -> None:
        """A service account config is passed on as service_account_json_path."""
        service, source_config, build = self._build(_config(scopes=["scope-a"]))

        assert service == "service"
        build.assert_called_once_with("drive", "v3", credentials="creds")
        assert source_config.folder_id == _ROOT
        assert source_config.scopes == ["scope-a"]
        assert source_config.recursive is False
        assert source_config.service_account_json_path == "sa.json"
        assert source_config.credentials_path is None

    def test_oauth_passes_token_path(self, tmp_path: Path) -> None:
        """An OAuth config is passed on with credentials_path and the derived token path."""
        creds = str(tmp_path / "client.json")
        _, source_config, _ = self._build(GoogleDriveDestinationConfig(folder_id=_ROOT, credentials_path=creds))

        assert source_config.credentials_path == creds
        assert source_config.service_account_json_path is None
        assert source_config.token_path == str(tmp_path / "gdrive_token.pickle")

    def test_oauth_without_token_path(self, tmp_path: Path) -> None:
        """When no token path can be determined, none is passed on."""
        config = GoogleDriveDestinationConfig(folder_id=_ROOT, credentials_path=str(tmp_path / "client.json"))
        with patch.object(GoogleDriveDestinationConfig, "get_token_path", return_value=""):
            _, source_config, _ = self._build(config)

        assert source_config.credentials_path == str(tmp_path / "client.json")
        assert source_config.token_path is None


class TestConfigExplicitNone:
    """Explicit None for a credential path is kept as None."""

    def test_explicit_none_credentials_path(self) -> None:
        """expand_path returns None unchanged, and the token path stays empty for a service account."""
        config = GoogleDriveDestinationConfig(
            folder_id=_ROOT, service_account_json_path="sa.json", credentials_path=None
        )

        assert config.credentials_path is None
        assert config.is_service_account() is True
        assert config.get_token_path() == ""
