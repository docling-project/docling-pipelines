# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for BoxDestinationAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter import (
    BoxDestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.box.config import (
    BoxDestinationConfig,
)

_BASE_PARAMS = {
    "credentials_path": "/tmp/box_config.json",
    "folder_id": "root_folder_id",
}


def _make_config(**overrides) -> BoxDestinationConfig:
    return BoxDestinationConfig(**{**_BASE_PARAMS, **overrides})


def _mock_client(
    *,
    folder_name: str = "DestFolder",
    folder_items: list | None = None,
    upload_file_id: str = "uploaded_file_id",
) -> MagicMock:
    """Build a minimal mock of a Box SDK client."""
    client = MagicMock()

    # folders.get_folder_by_id() — used by validate_destination
    folder_mock = MagicMock()
    folder_mock.name = folder_name
    client.folders.get_folder_by_id.return_value = folder_mock

    # folders.get_folder_items() — used by _find_subfolder_id and _find_existing_file
    items_mock = MagicMock()
    items_mock.entries = folder_items if folder_items is not None else []
    client.folders.get_folder_items.return_value = items_mock

    # folders.create_folder() — used by _create_subfolder
    created_folder = MagicMock()
    created_folder.id = "new_folder_id"
    client.folders.create_folder.return_value = created_folder

    # uploads.upload_file() — used by write_document
    uploaded_file = MagicMock()
    uploaded_file.id = upload_file_id
    upload_result = MagicMock()
    upload_result.entries = [uploaded_file]
    client.uploads.upload_file.return_value = upload_result

    return client


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterRegistration:
    def test_dest_name_is_box(self):
        assert BoxDestinationAdapter.DEST_NAME == "box"

    def test_dest_display_name_is_box(self):
        assert BoxDestinationAdapter.DEST_DISPLAY_NAME == "Box"

    def test_is_registered_in_factory(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
            DestinationAdapterFactory,
        )

        assert DestinationAdapterFactory.is_registered("box")

    def test_get_config_schema_returns_box_destination_config(self):
        adapter = BoxDestinationAdapter()
        assert adapter.get_config_schema() is BoxDestinationConfig


# ---------------------------------------------------------------------------
# resolve_destination_path
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterResolveDestinationPath:
    def test_returns_relative_path_unchanged(self):
        adapter = BoxDestinationAdapter()
        result = adapter.resolve_destination_path(relative_path="sub/report.pdf", config=_make_config())
        assert result == "sub/report.pdf"

    def test_root_level_path_unchanged(self):
        adapter = BoxDestinationAdapter()
        result = adapter.resolve_destination_path(relative_path="report.pdf", config=_make_config())
        assert result == "report.pdf"


# ---------------------------------------------------------------------------
# ensure_directory (no-op)
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterEnsureDirectory:
    def test_ensure_directory_is_noop(self):
        adapter = BoxDestinationAdapter()
        # Should not raise
        adapter.ensure_directory(path="some/nested/path")

    def test_ensure_directory_does_not_call_get_box_client(self):
        adapter = BoxDestinationAdapter()
        with patch.object(adapter, "_get_box_client") as mock_client:
            adapter.ensure_directory(path="any/path")
            mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# validate_destination
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterValidateDestination:
    def test_returns_none_when_config_is_none(self):
        adapter = BoxDestinationAdapter()
        result = adapter.validate_destination(config=None)
        assert result is None

    def test_returns_none_when_folder_accessible(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.validate_destination(config=_make_config())
        assert result is None

    def test_returns_failed_on_exception(self):
        adapter = BoxDestinationAdapter()
        with patch.object(adapter, "_get_box_client", side_effect=RuntimeError("auth error")):
            result = adapter.validate_destination(config=_make_config())
        assert result is not None
        assert result.success is False
        assert "validation failed" in result.error_message

    def test_returns_failed_when_box_sdk_unavailable(self, monkeypatch):
        import docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter as mod

        monkeypatch.setattr(mod, "_BOX_AVAILABLE", False)
        adapter = BoxDestinationAdapter()
        result = adapter.validate_destination(config=_make_config())
        assert result is not None
        assert result.success is False
        assert "box-sdk-gen" in result.error_message


# ---------------------------------------------------------------------------
# write_document — success paths
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterWriteDocumentSuccess:
    def test_successful_upload_returns_write_result(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client(upload_file_id="abc123")

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"hello world",
                destination_path="report.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is True
        assert result.bytes_written == len(b"hello world")
        assert "app.box.com/file/abc123" in result.destination_path

    def test_upload_to_nested_path_creates_intermediate_folders(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        # No existing subfolder found — folders.get_folder_items returns empty entries
        client.folders.get_folder_items.return_value.entries = []

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"data",
                destination_path="subdir/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is True
        # A sub-folder must have been created
        client.folders.create_folder.assert_called_once()

    def test_folder_id_cached_across_writes(self):
        """A second write to the same subfolder must not trigger another folder lookup."""
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        with patch.object(adapter, "_get_box_client", return_value=client):
            adapter.write_document(
                content=b"a", destination_path="subdir/file1.pdf", overwrite=True, config=_make_config()
            )
            list_calls_after_first = client.folders.get_folder_items.call_count

            adapter.write_document(
                content=b"b", destination_path="subdir/file2.pdf", overwrite=True, config=_make_config()
            )
            list_calls_after_second = client.folders.get_folder_items.call_count

        # No additional folder listing for the second write (folder was cached)
        assert list_calls_after_second == list_calls_after_first

    def test_destination_path_is_web_url_with_file_id(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client(upload_file_id="file999")

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"x",
                destination_path="doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.destination_path == "https://app.box.com/file/file999"


# ---------------------------------------------------------------------------
# write_document — overwrite=False paths
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterOverwriteFalse:
    def test_skips_when_file_exists_and_overwrite_false(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        # Existing file returned in folder items
        existing_file = MagicMock()
        existing_file.type = "file"
        existing_file.name = "report.pdf"
        existing_file.id = "existing_file_id"
        client.folders.get_folder_items.return_value.entries = [existing_file]

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"data",
                destination_path="report.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is False
        assert "overwrite disabled" in result.error_message
        # Upload must NOT be called
        client.uploads.upload_file.assert_not_called()

    def test_uploads_when_file_absent_and_overwrite_false(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"data",
                destination_path="report.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is True


# ---------------------------------------------------------------------------
# write_document — error paths
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterErrorPaths:
    def test_returns_failed_when_config_is_none(self):
        adapter = BoxDestinationAdapter()
        result = adapter.write_document(content=b"data", destination_path="doc.pdf", config=None)
        assert result.success is False
        assert "BoxDestinationConfig is required" in result.error_message

    def test_returns_failed_on_exception_during_upload(self):
        adapter = BoxDestinationAdapter()
        with patch.object(adapter, "_get_box_client", side_effect=ConnectionError("network down")):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )
        assert result.success is False
        assert "network down" in result.error_message

    def test_returns_failed_when_create_dirs_false_and_folder_missing(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        # No items in any folder — subfolder lookup will return nothing
        client.folders.get_folder_items.return_value.entries = []

        with patch.object(adapter, "_get_box_client", return_value=client):
            result = adapter.write_document(
                content=b"data",
                destination_path="missing_dir/doc.pdf",
                overwrite=True,
                config=_make_config(create_dirs=False),
            )

        assert result.success is False
        assert "create_dirs is disabled" in result.error_message

    def test_returns_failed_when_box_sdk_unavailable(self, monkeypatch):
        import docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter as mod

        monkeypatch.setattr(mod, "_BOX_AVAILABLE", False)
        adapter = BoxDestinationAdapter()
        result = adapter.write_document(content=b"data", destination_path="doc.pdf", config=_make_config())
        assert result.success is False
        assert "box-sdk-gen" in result.error_message


# ---------------------------------------------------------------------------
# build_config_from_operator_params
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterBuildConfig:
    def test_builds_config_with_credentials_path_in_provider_config(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={
                "folder_id": "123456789",
                "credentials_path": "/tmp/box_config.json",
            },
            credentials={},
        )
        assert isinstance(cfg, BoxDestinationConfig)
        assert cfg.folder_id == "123456789"
        assert cfg.credentials_path == "/tmp/box_config.json"

    def test_builds_config_with_credentials_path_in_credentials(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "123456789"},
            credentials={"credentials_path": "/tmp/box_config.json"},
        )
        assert isinstance(cfg, BoxDestinationConfig)
        assert cfg.folder_id == "123456789"
        assert cfg.credentials_path == "/tmp/box_config.json"

    def test_builds_config_with_legacy_credentials_json_path(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "123456789"},
            credentials={"credentials_json_path": "/tmp/box_config.json"},
        )
        assert isinstance(cfg, BoxDestinationConfig)
        assert cfg.folder_id == "123456789"
        assert cfg.credentials_path == "/tmp/box_config.json"

    def test_missing_credentials_path_raises(self):
        adapter = BoxDestinationAdapter()
        with pytest.raises(ValueError, match="credentials_path"):
            adapter.build_config_from_operator_params(
                provider_config={"folder_id": "123456789"},
                credentials={},
            )

    def test_folder_id_defaults_to_root(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"credentials_path": "/tmp/box_config.json"},
            credentials={},
        )
        assert cfg.folder_id == "0"

    def test_create_dirs_defaults_to_true(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "123", "credentials_path": "/tmp/box_config.json"},
            credentials={},
        )
        assert cfg.create_dirs is True

    def test_create_dirs_false_passed_through(self):
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "123", "credentials_path": "/tmp/box_config.json", "create_dirs": False},
            credentials={},
        )
        assert cfg.create_dirs is False

    def test_env_var_in_credentials_path_resolved(self, monkeypatch):
        monkeypatch.setenv("BOX_TEST_CFG", "/tmp/resolved_box.json")
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "123", "credentials_path": "${BOX_TEST_CFG}"},
            credentials={},
        )
        assert cfg.credentials_path == "/tmp/resolved_box.json"

    def test_env_var_in_folder_id_resolved(self, monkeypatch):
        monkeypatch.setenv("BOX_DEST_FOLDER", "987654321")
        adapter = BoxDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "${BOX_DEST_FOLDER}", "credentials_path": "/tmp/box_config.json"},
            credentials={},
        )
        assert cfg.folder_id == "987654321"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestBoxDestinationAdapterResolveFolderId:
    def test_empty_relative_dir_returns_root(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        result = adapter._resolve_folder_id(
            client=client,
            relative_dir="",
            root_folder_id="root_id",
            create_dirs=True,
        )
        assert result == "root_id"
        client.folders.get_folder_items.assert_not_called()

    def test_existing_subfolder_used_without_create(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        existing_folder = MagicMock()
        existing_folder.type = "folder"
        existing_folder.name = "sub01"
        existing_folder.id = "sub01_id"
        client.folders.get_folder_items.return_value.entries = [existing_folder]

        result = adapter._resolve_folder_id(
            client=client,
            relative_dir="sub01",
            root_folder_id="root_id",
            create_dirs=False,
        )

        assert result == "sub01_id"
        client.folders.create_folder.assert_not_called()

    def test_missing_subfolder_raises_when_create_dirs_false(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        with pytest.raises(FileNotFoundError, match="create_dirs is disabled"):
            adapter._resolve_folder_id(
                client=client,
                relative_dir="missing_sub",
                root_folder_id="root_id",
                create_dirs=False,
            )

    def test_creates_subfolder_when_missing_and_create_dirs_true(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        result = adapter._resolve_folder_id(
            client=client,
            relative_dir="new_sub",
            root_folder_id="root_id",
            create_dirs=True,
        )

        assert result == "new_folder_id"
        client.folders.create_folder.assert_called_once()


class TestBoxDestinationAdapterFindSubfolderId:
    def test_returns_folder_id_when_found(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        folder_entry = MagicMock()
        folder_entry.type = "folder"
        folder_entry.name = "myfolder"
        folder_entry.id = "folder123"
        client.folders.get_folder_items.return_value.entries = [folder_entry]

        result = adapter._find_subfolder_id(client=client, name="myfolder", parent_id="parent_id")
        assert result == "folder123"

    def test_returns_none_when_not_found(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        result = adapter._find_subfolder_id(client=client, name="nothere", parent_id="parent_id")
        assert result is None

    def test_ignores_file_entries(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        file_entry = MagicMock()
        file_entry.type = "file"
        file_entry.name = "samename"
        file_entry.id = "file_id"
        client.folders.get_folder_items.return_value.entries = [file_entry]

        # A file entry with the same name must not be returned
        result = adapter._find_subfolder_id(client=client, name="samename", parent_id="parent_id")
        assert result is None


class TestBoxDestinationAdapterFindExistingFile:
    def test_returns_file_id_when_found(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        file_entry = MagicMock()
        file_entry.type = "file"
        file_entry.name = "report.pdf"
        file_entry.id = "file_abc"
        client.folders.get_folder_items.return_value.entries = [file_entry]

        result = adapter._find_existing_file(client=client, filename="report.pdf", parent_folder_id="parent_id")
        assert result == "file_abc"

    def test_returns_none_when_file_absent(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()
        client.folders.get_folder_items.return_value.entries = []

        result = adapter._find_existing_file(client=client, filename="report.pdf", parent_folder_id="parent_id")
        assert result is None

    def test_ignores_folder_entries(self):
        adapter = BoxDestinationAdapter()
        client = _mock_client()

        folder_entry = MagicMock()
        folder_entry.type = "folder"
        folder_entry.name = "report.pdf"
        folder_entry.id = "folder_id"
        client.folders.get_folder_items.return_value.entries = [folder_entry]

        result = adapter._find_existing_file(client=client, filename="report.pdf", parent_folder_id="parent_id")
        assert result is None
