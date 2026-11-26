# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for the Dropbox source adapter and config.

The Dropbox SDK client is replaced by an in-process fake, so no test contacts Dropbox.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from dropbox.exceptions import BadInputError, HttpError
from dropbox.files import FileMetadata

from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.adapter import DropboxSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.config import DropboxSourceConfig

TOKEN_CONFIG = {"access_token": "test-token"}  # pragma: allowlist secret


class FakeDropboxClient:
    """Fake Dropbox client whose calls raise a configured error or return canned values."""

    def __init__(self, *, error: Exception | None = None, account=None):
        self.error = error
        self.account = account

    def users_get_current_account(self):
        """Return the account or raise the configured error."""
        if self.error:
            raise self.error
        return self.account

    def files_download(self, path):
        """Raise the configured error."""
        assert self.error is not None
        raise self.error


def _entry(path: str) -> FileMetadata:
    """Build a Dropbox file entry at ``path``."""
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return FileMetadata(
        name=path.rsplit("/", 1)[-1],
        id="id:1",
        path_lower=path.lower(),
        path_display=path,
        size=1,
        client_modified=timestamp,
        server_modified=timestamp,
        rev="0123456789abc",
    )


def _adapter_with_client(client: FakeDropboxClient) -> DropboxSourceAdapter:
    """Return an adapter whose client lookup yields ``client``."""
    adapter = DropboxSourceAdapter()
    adapter._get_dropbox_client = lambda *, config: client  # type: ignore[method-assign]
    return adapter


class TestConfigFilePath:
    """DropboxSourceConfig.file_path normalization."""

    def test_explicit_none_stays_none(self):
        """An explicit None file_path stays None."""
        assert DropboxSourceConfig(**TOKEN_CONFIG, file_path=None).file_path is None

    def test_blank_file_path_becomes_none(self):
        """A whitespace-only file_path is treated as not set (folder mode)."""
        assert DropboxSourceConfig(**TOKEN_CONFIG, file_path="   ").file_path is None


class TestComputeRelativePath:
    """_compute_relative_path against the configured root."""

    def test_root_folder_returns_full_relative_path(self):
        """Without a folder_path the path is only stripped of its leading slash."""
        relative = DropboxSourceAdapter()._compute_relative_path(entry=_entry("/Reports/q1.pdf"), folder_path="")

        assert relative == "Reports/q1.pdf"

    def test_entry_equal_to_root_returns_its_name(self):
        """An entry whose path is the configured folder itself is reduced to its name."""
        relative = DropboxSourceAdapter()._compute_relative_path(entry=_entry("/Reports"), folder_path="/reports")

        assert relative == "Reports"

    def test_entry_outside_root_keeps_its_path(self):
        """An entry that is not below the configured folder keeps its full relative path."""
        relative = DropboxSourceAdapter()._compute_relative_path(entry=_entry("/Other/q1.pdf"), folder_path="/Reports")

        assert relative == "Other/q1.pdf"


class TestTestConnection:
    """test_connection error reporting."""

    def test_bad_input_error_is_reported(self):
        """A BadInputError (malformed token) is reported as invalid credentials."""
        adapter = _adapter_with_client(FakeDropboxClient(error=BadInputError("req-1", "malformed token")))

        ok, message = asyncio.run(adapter.test_connection(DropboxSourceConfig(**TOKEN_CONFIG)))

        assert ok is False
        assert message.startswith("Invalid Dropbox credentials or request:")

    def test_unexpected_error_is_reported_not_raised(self):
        """Any other exception is turned into a failed connection result."""
        adapter = _adapter_with_client(FakeDropboxClient(error=RuntimeError("socket closed")))

        ok, message = asyncio.run(adapter.test_connection(DropboxSourceConfig(**TOKEN_CONFIG)))

        assert (ok, message) == (False, "Connection test failed: socket closed")


class TestFetchBinaryContentErrors:
    """fetch_binary_content transport errors."""

    @pytest.mark.parametrize(
        "error",
        [BadInputError("req-1", "bad path"), HttpError("req-1", 500, "server error")],
        ids=["bad-input", "http"],
    )
    def test_transport_errors_return_none(self, error):
        """BadInputError and HttpError while downloading return None."""
        adapter = _adapter_with_client(FakeDropboxClient(error=error))

        assert adapter.fetch_binary_content(source_id="id:1", provider_config=dict(TOKEN_CONFIG)) is None
