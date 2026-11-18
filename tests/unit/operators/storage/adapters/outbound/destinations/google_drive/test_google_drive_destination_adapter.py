# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for GoogleDriveDestinationAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.adapter import (
    GoogleDriveDestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.config import (
    GoogleDriveDestinationConfig,
)

_SA_PARAMS = {
    "folder_id": "root_folder_id",
    "service_account_json_path": "/path/to/sa.json",
}


def _make_config(**overrides) -> GoogleDriveDestinationConfig:
    return GoogleDriveDestinationConfig(**{**_SA_PARAMS, **overrides})


def _mock_service(
    *,
    folder_meta: dict | None = None,
    find_folder_files: list | None = None,
    find_file_files: list | None = None,
    create_result: dict | None = None,
) -> MagicMock:
    """Build a minimal mock of the Google Drive service object."""
    service = MagicMock()

    # files().get().execute() — used by validate_destination
    get_execute = MagicMock(
        return_value=folder_meta
        or {"id": "root_folder_id", "name": "Root", "mimeType": "application/vnd.google-apps.folder"}
    )
    service.files.return_value.get.return_value.execute = get_execute

    # files().list().execute() — used for folder/file lookup
    list_execute = MagicMock(return_value={"files": find_folder_files or []})
    service.files.return_value.list.return_value.execute = list_execute

    # files().create().execute() — used for folder creation and file upload
    create_execute = MagicMock(
        return_value=create_result
        or {"id": "new_item_id", "webViewLink": "https://drive.google.com/file/d/new_item_id"}
    )
    service.files.return_value.create.return_value.execute = create_execute

    return service


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterRegistration:
    def test_dest_name_is_google_drive(self):
        assert GoogleDriveDestinationAdapter.DEST_NAME == "google_drive"

    def test_is_registered_in_factory(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
            DestinationAdapterFactory,
        )

        assert DestinationAdapterFactory.is_registered("google_drive")

    def test_get_config_schema_returns_google_drive_config(self):
        adapter = GoogleDriveDestinationAdapter()
        assert adapter.get_config_schema() is GoogleDriveDestinationConfig


# ---------------------------------------------------------------------------
# resolve_destination_path
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterResolveDestinationPath:
    def test_returns_relative_path_unchanged(self):
        adapter = GoogleDriveDestinationAdapter()
        config = _make_config()
        result = adapter.resolve_destination_path(relative_path="sub/report.pdf", config=config)
        assert result == "sub/report.pdf"

    def test_root_level_path_unchanged(self):
        adapter = GoogleDriveDestinationAdapter()
        config = _make_config()
        result = adapter.resolve_destination_path(relative_path="report.pdf", config=config)
        assert result == "report.pdf"


# ---------------------------------------------------------------------------
# ensure_directory (no-op)
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterEnsureDirectory:
    def test_ensure_directory_is_noop(self):
        adapter = GoogleDriveDestinationAdapter()
        # Should not raise
        adapter.ensure_directory(path="some/nested/path")

    def test_ensure_directory_does_not_call_build_service(self):
        adapter = GoogleDriveDestinationAdapter()
        with patch.object(adapter, "_build_service") as mock_build:
            adapter.ensure_directory(path="any/path")
            mock_build.assert_not_called()


# ---------------------------------------------------------------------------
# validate_destination
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterValidateDestination:
    def test_returns_none_when_config_is_none(self):
        adapter = GoogleDriveDestinationAdapter()
        result = adapter.validate_destination(config=None)
        assert result is None

    def test_returns_none_when_folder_accessible(self):
        adapter = GoogleDriveDestinationAdapter()
        service = _mock_service()
        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.validate_destination(config=_make_config())
        assert result is None

    def test_returns_failed_when_target_is_not_a_folder(self):
        adapter = GoogleDriveDestinationAdapter()
        service = _mock_service(folder_meta={"id": "root_folder_id", "name": "file.pdf", "mimeType": "application/pdf"})
        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.validate_destination(config=_make_config())
        assert result is not None
        assert result.success is False
        assert "not a folder" in result.error_message

    def test_returns_failed_on_exception(self):
        adapter = GoogleDriveDestinationAdapter()
        with patch.object(adapter, "_build_service", side_effect=RuntimeError("auth error")):
            result = adapter.validate_destination(config=_make_config())
        assert result is not None
        assert result.success is False
        assert "validation failed" in result.error_message


# ---------------------------------------------------------------------------
# write_document
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterWriteDocumentSuccess:
    def test_successful_upload_returns_write_result(self):
        adapter = GoogleDriveDestinationAdapter()
        service = _mock_service(
            create_result={"id": "file_abc", "webViewLink": "https://drive.google.com/file/d/file_abc"},
        )
        # No existing subfolder — list returns empty, then create returns folder id
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        service.files.return_value.create.return_value.execute.side_effect = [
            {"id": "file_abc", "webViewLink": "https://drive.google.com/file/d/file_abc"},
        ]

        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.write_document(
                content=b"hello world",
                destination_path="report.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is True
        assert result.bytes_written == len(b"hello world")
        assert "drive.google.com" in result.destination_path

    def test_upload_to_nested_path_creates_intermediate_folders(self):
        adapter = GoogleDriveDestinationAdapter()
        service = MagicMock()

        # folder lookup: return empty (folder doesn't exist)
        list_execute = MagicMock(return_value={"files": []})
        service.files.return_value.list.return_value.execute = list_execute

        # folder creation + file upload
        create_call_count = 0

        def create_side_effect():
            nonlocal create_call_count
            create_call_count += 1
            if create_call_count == 1:
                return {"id": "sub_folder_id"}  # folder create
            return {"id": "uploaded_file_id", "webViewLink": "https://drive.google.com/file/d/uploaded_file_id"}

        service.files.return_value.create.return_value.execute = create_side_effect

        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.write_document(
                content=b"data",
                destination_path="subdir/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is True
        # Two create calls: one for the folder, one for the file
        assert create_call_count == 2

    def test_folder_id_cached_across_writes(self):
        """A second write to the same subfolder must NOT trigger another folder lookup."""
        adapter = GoogleDriveDestinationAdapter()
        service = MagicMock()

        list_execute = MagicMock(return_value={"files": []})
        service.files.return_value.list.return_value.execute = list_execute

        side_effects = [
            {"id": "cached_folder_id"},  # first create: folder
            {"id": "file1_id", "webViewLink": "https://drive.google.com/file/d/file1_id"},
            {"id": "file2_id", "webViewLink": "https://drive.google.com/file/d/file2_id"},
        ]
        service.files.return_value.create.return_value.execute = MagicMock(side_effect=side_effects)

        with patch.object(adapter, "_build_service", return_value=service):
            adapter.write_document(
                content=b"a", destination_path="subdir/file1.pdf", overwrite=True, config=_make_config()
            )
            # list should only be called once (folder lookup, then cached)
            list_call_count_after_first = service.files.return_value.list.return_value.execute.call_count

            adapter.write_document(
                content=b"b", destination_path="subdir/file2.pdf", overwrite=True, config=_make_config()
            )
            list_call_count_after_second = service.files.return_value.list.return_value.execute.call_count

        # No additional list call for the second write (folder was cached)
        assert list_call_count_after_second == list_call_count_after_first


class TestGoogleDriveDestinationAdapterOverwriteFalse:
    def test_skips_when_file_exists_and_overwrite_false(self):
        adapter = GoogleDriveDestinationAdapter()
        service = MagicMock()

        # list returns the existing file
        service.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "existing_file_id"}]}

        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.write_document(
                content=b"data",
                destination_path="report.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is False
        assert result.write_status == "skipped"
        # create (upload) must NOT be called
        service.files.return_value.create.assert_not_called()

    def test_uploads_when_file_absent_and_overwrite_false(self):
        adapter = GoogleDriveDestinationAdapter()
        service = MagicMock()

        # list returns no matching file
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "new_id",
            "webViewLink": "https://drive.google.com/file/d/new_id",
        }

        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.write_document(
                content=b"data",
                destination_path="report.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is True


class TestGoogleDriveDestinationAdapterErrorPaths:
    def test_returns_failed_when_config_is_none(self):
        adapter = GoogleDriveDestinationAdapter()
        result = adapter.write_document(content=b"data", destination_path="doc.pdf", config=None)
        assert result.success is False
        assert "GoogleDriveDestinationConfig is required" in result.error_message

    def test_returns_failed_on_exception_during_upload(self):
        adapter = GoogleDriveDestinationAdapter()
        with patch.object(adapter, "_build_service", side_effect=ConnectionError("network down")):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )
        assert result.success is False
        assert "connection failed" in result.error_message
        assert "network down" not in result.error_message

    def test_returns_failed_when_create_dirs_false_and_folder_missing(self):
        adapter = GoogleDriveDestinationAdapter()
        service = MagicMock()
        # folder lookup returns nothing
        service.files.return_value.list.return_value.execute.return_value = {"files": []}

        with patch.object(adapter, "_build_service", return_value=service):
            result = adapter.write_document(
                content=b"data",
                destination_path="missing_dir/doc.pdf",
                overwrite=True,
                config=_make_config(create_dirs=False),
            )

        assert result.success is False
        assert "create_dirs is disabled" in result.error_message


# ---------------------------------------------------------------------------
# build_config_from_operator_params
# ---------------------------------------------------------------------------


class TestGoogleDriveDestinationAdapterBuildConfig:
    def _sa_credentials(self):
        return {"service_account_json_path": "/path/to/sa.json"}

    def _oauth_credentials(self):
        return {"credentials_path": "/path/to/creds.json"}

    def _provider_config(self):
        return {"folder_id": "folder123"}

    def test_builds_config_with_service_account(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config=self._provider_config(),
            credentials=self._sa_credentials(),
        )
        assert isinstance(cfg, GoogleDriveDestinationConfig)
        assert cfg.folder_id == "folder123"
        assert cfg.service_account_json_path == "/path/to/sa.json"

    def test_builds_config_with_oauth_credentials(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config=self._provider_config(),
            credentials=self._oauth_credentials(),
        )
        assert cfg.credentials_path == "/path/to/creds.json"

    def test_optional_token_path_applied(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config=self._provider_config(),
            credentials={**self._oauth_credentials(), "token_path": "/tmp/token.pickle"},
        )
        assert cfg.token_path == "/tmp/token.pickle"

    def test_optional_drive_id_applied(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={**self._provider_config(), "drive_id": "0ABcDeFgHi"},
            credentials=self._sa_credentials(),
        )
        assert cfg.drive_id == "0ABcDeFgHi"

    def test_create_dirs_defaults_to_true(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config=self._provider_config(),
            credentials=self._sa_credentials(),
        )
        assert cfg.create_dirs is True

    def test_create_dirs_false_passed_through(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={**self._provider_config(), "create_dirs": False},
            credentials=self._sa_credentials(),
        )
        assert cfg.create_dirs is False

    def test_missing_folder_id_raises(self):
        adapter = GoogleDriveDestinationAdapter()
        with pytest.raises(ValueError, match="folder_id"):
            adapter.build_config_from_operator_params(
                provider_config={},
                credentials=self._sa_credentials(),
            )

    def test_missing_credentials_raises(self):
        adapter = GoogleDriveDestinationAdapter()
        with pytest.raises(
            ValueError, match=r"service_account_json_path.*credentials_path|credentials_path.*service_account_json_path"
        ):
            adapter.build_config_from_operator_params(
                provider_config=self._provider_config(),
                credentials={},
            )

    def test_chunk_size_mb_passed_through(self):
        adapter = GoogleDriveDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={**self._provider_config(), "chunk_size_mb": 10},
            credentials=self._sa_credentials(),
        )
        assert cfg.chunk_size_mb == 10
