# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for BoxDestinationAdapter: client creation, listing errors and the missing-SDK fallback."""

import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.box import adapter as box_module
from docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter import BoxDestinationAdapter
from docpipe.core.operators.storage.adapters.outbound.destinations.box.config import BoxDestinationConfig
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    DestinationAdapterFactory,
)


class _FakeFolders:
    """Fake of ``client.folders`` whose listing always fails."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []

    def get_folder_items(self, parent_id: str) -> Any:
        """Fail like an API error would."""
        raise RuntimeError(f"listing failed for {parent_id}")

    def create_folder(self, *, name: str, parent: Any) -> Any:
        """Record the folder and return it with a new id."""
        self.created.append((name, parent.id))
        return SimpleNamespace(id=f"folder_{len(self.created)}")


class _FakeUploads:
    """Fake of ``client.uploads`` that records uploads."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str, bytes]] = []

    def upload_file(self, *, attributes: Any, file: Any) -> Any:
        """Record the upload and return one entry."""
        self.uploaded.append((attributes.name, attributes.parent.id, file.read()))
        return SimpleNamespace(entries=[SimpleNamespace(id="file_1")])


class _FakeBoxClient:
    """In-process stand-in for a box-sdk-gen BoxClient."""

    def __init__(self) -> None:
        self.folders = _FakeFolders()
        self.uploads = _FakeUploads()


def _config(**overrides: Any) -> BoxDestinationConfig:
    return BoxDestinationConfig(**{"credentials_path": "box.json", "folder_id": "root", **overrides})


class TestGetBoxClient:
    """_get_box_client delegates to the shared Box auth helper."""

    def test_uses_credentials_path(self) -> None:
        """The config's credentials_path is passed to get_box_client."""
        config = _config()
        with patch.object(box_module, "get_box_client", return_value="client") as get_client:
            assert BoxDestinationAdapter()._get_box_client(config) == "client"
        get_client.assert_called_once_with(credentials_path=config.credentials_path)


class TestListingErrors:
    """A failing folder listing is logged and treated as 'not found'."""

    def test_subfolder_lookup_error_returns_none(self) -> None:
        """_find_subfolder_id returns None when listing fails."""
        client = _FakeBoxClient()
        assert BoxDestinationAdapter()._find_subfolder_id(client=client, name="a", parent_id="root") is None

    def test_existing_file_lookup_error_returns_none(self) -> None:
        """_find_existing_file returns None when listing fails."""
        client = _FakeBoxClient()
        result = BoxDestinationAdapter()._find_existing_file(client=client, filename="x.md", parent_folder_id="root")
        assert result is None

    def test_write_creates_subfolder_when_lookup_fails(self) -> None:
        """With create_dirs, a failed lookup leads to creating the sub-folder and uploading into it."""
        client = _FakeBoxClient()
        adapter = BoxDestinationAdapter()
        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(content=b"abc", destination_path="sub/doc.md", config=_config())

        assert result.success is True
        assert result.destination_path == "https://app.box.com/file/file_1"
        assert client.folders.created == [("sub", "root")]
        assert client.uploads.uploaded == [("doc.md", "folder_1", b"abc")]


def _load_box_adapter_without_sdk() -> ModuleType:
    """Load a fresh copy of the adapter module while box_sdk_gen cannot be imported."""
    spec = importlib.util.spec_from_file_location("_box_adapter_without_sdk", box_module.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"box_sdk_gen": None}), patch.dict(DestinationAdapterFactory._adapters):
        spec.loader.exec_module(module)
    return module


class TestMissingSdk:
    """Without box-sdk-gen the adapter loads and reports the install hint."""

    @pytest.fixture(scope="class")
    def module(self) -> ModuleType:
        """Return the adapter module loaded without the SDK."""
        return _load_box_adapter_without_sdk()

    def test_sdk_names_are_none(self, module: ModuleType) -> None:
        """The SDK symbols fall back to None and the module flags the SDK as unavailable."""
        assert module._BOX_AVAILABLE is False
        assert module.BoxClient is None
        assert module.UploadFileAttributes is None

    def test_factory_registration_is_unchanged(self) -> None:
        """Loading the fallback copy does not replace the registered adapter."""
        _load_box_adapter_without_sdk()
        assert DestinationAdapterFactory.create("box").__class__ is BoxDestinationAdapter

    def test_validate_and_write_return_install_hint(self, module: ModuleType) -> None:
        """Both entry points fail with the install hint instead of calling Box."""
        adapter = module.BoxDestinationAdapter()

        validation = adapter.validate_destination(config=_config())
        write = adapter.write_document(content=b"x", destination_path="a.md", config=_config())

        assert validation.success is False
        assert "box-sdk-gen is not installed" in validation.error_message
        assert write.success is False
        assert write.doc_name == "a.md"
        assert "box-sdk-gen is not installed" in write.error_message
