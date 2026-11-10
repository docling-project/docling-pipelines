# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the temporary credential file utility."""

import json
import stat

from docpipe.utils.infrastructure.temp_credentials import temporary_credential_file


def test_temporary_credential_file_str() -> None:
    content = "my-secret-credentials"
    with temporary_credential_file(content, suffix=".txt") as file_path:
        assert file_path.exists()
        assert file_path.name == "credentials.txt"

        # Verify content
        assert file_path.read_text(encoding="utf-8") == content

        # Verify file permissions are 0600 (owner-only read/write)
        mode = file_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

        # Verify parent directory permissions are 0700 (owner-only read/write/execute)
        parent_mode = file_path.parent.stat().st_mode
        assert stat.S_IMODE(parent_mode) == 0o700

    # Verify cleanup on exit
    assert not file_path.exists()
    assert not file_path.parent.exists()


def test_temporary_credential_file_bytes() -> None:
    content = b"my-binary-credentials"
    with temporary_credential_file(content, suffix=".bin") as file_path:
        assert file_path.exists()
        assert file_path.name == "credentials.bin"

        # Verify content
        assert file_path.read_bytes() == content

        # Verify file permissions
        mode = file_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    # Verify cleanup on exit
    assert not file_path.exists()


def test_temporary_credential_file_dict() -> None:
    content = {"client_id": "foo", "client_secret": "bar"}
    with temporary_credential_file(content) as file_path:
        assert file_path.exists()
        assert file_path.name == "credentials.json"

        # Verify content parses back as JSON and matches
        parsed = json.loads(file_path.read_text(encoding="utf-8"))
        assert parsed == content

        # Verify file permissions
        mode = file_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    # Verify cleanup on exit
    assert not file_path.exists()
