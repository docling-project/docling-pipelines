# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for FilesystemDestinationAdapter handling of missing directories."""

from pathlib import Path

from docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter import (
    FilesystemDestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.config import (
    FilesystemDestinationConfig,
)


class TestValidateDestination:
    """validate_destination checks the root directory."""

    def test_no_config_is_accepted(self) -> None:
        """Without a config there is nothing to validate."""
        assert FilesystemDestinationAdapter().validate_destination(config=None) is None

    def test_missing_root_fails_when_create_dirs_disabled(self, tmp_path: Path) -> None:
        """A missing root with create_dirs=False is reported with the root path."""
        root = tmp_path / "missing"
        config = FilesystemDestinationConfig(root_path=str(root), create_dirs=False)

        result = FilesystemDestinationAdapter().validate_destination(config=config)

        assert result is not None
        assert result.success is False
        assert "create_dirs is disabled" in result.error_message
        assert str(root) in result.error_message
        assert not root.exists()

    def test_missing_root_is_accepted_when_create_dirs_enabled(self, tmp_path: Path) -> None:
        """A missing root is fine when the adapter may create it; validation creates nothing."""
        root = tmp_path / "missing"
        config = FilesystemDestinationConfig(root_path=str(root), create_dirs=True)

        assert FilesystemDestinationAdapter().validate_destination(config=config) is None
        assert not root.exists()


class TestWriteDocumentMissingParent:
    """write_document with a missing parent directory."""

    def test_missing_parent_fails_when_create_dirs_disabled(self, tmp_path: Path) -> None:
        """No directory is created and nothing is written when create_dirs=False."""
        target = tmp_path / "sub" / "doc.md"
        config = FilesystemDestinationConfig(root_path=str(tmp_path), create_dirs=False)

        result = FilesystemDestinationAdapter().write_document(
            content=b"x", destination_path=str(target), config=config
        )

        assert result.success is False
        assert result.doc_name == "doc.md"
        assert "create_dirs is disabled" in result.error_message
        assert not target.parent.exists()

    def test_missing_parent_created_without_config(self, tmp_path: Path) -> None:
        """Without a config, create_dirs defaults to True."""
        target = tmp_path / "a" / "b" / "doc.md"

        result = FilesystemDestinationAdapter().write_document(content=b"abc", destination_path=str(target))

        assert result.success is True
        assert result.bytes_written == 3
        assert target.read_bytes() == b"abc"
