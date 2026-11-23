# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the temporary credential file utility."""

import json
import os
import stat

import pytest

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


class _FakeOs:
    """Stand-in for the ``os`` module inside the helper that records ``close`` and fails ``fdopen``/``write``."""

    def __init__(self, *, fdopen_error: OSError | None = None, write_error: OSError | None = None) -> None:
        self.closed: list[int] = []
        self._fdopen_error = fdopen_error
        self._write_error = write_error

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)

    def close(self, fd: int) -> None:
        self.closed.append(fd)
        os.close(fd)

    def fdopen(self, fd: int, mode: str) -> object:
        if self._fdopen_error is not None:
            raise self._fdopen_error
        return _FailingHandle(fd=fd, fake=self, error=self._write_error)


class _FailingHandle:
    """File-object stand-in: owns the descriptor, closes it on exit, optionally fails on write."""

    def __init__(self, *, fd: int, fake: "_FakeOs", error: OSError | None) -> None:
        self._fd = fd
        self._fake = fake
        self._error = error

    def write(self, data: bytes) -> int:
        if self._error is not None:
            raise self._error
        return len(data)

    def __enter__(self) -> "_FailingHandle":
        return self

    def __exit__(self, *exc_info: object) -> None:
        os.close(self._fd)
        self._fake.closed.append(self._fd)


def test_failed_write_closes_the_descriptor_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeOs(write_error=OSError("disk full"))
    monkeypatch.setattr("docpipe.utils.infrastructure.temp_credentials.os", fake)

    with pytest.raises(OSError, match="disk full"):
        with temporary_credential_file("secret"):
            pass

    # Only the file object closes it; the helper itself must not close it a second time.
    assert len(fake.closed) == 1


def test_failed_fdopen_closes_the_descriptor_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeOs(fdopen_error=OSError("fdopen failed"))
    monkeypatch.setattr("docpipe.utils.infrastructure.temp_credentials.os", fake)

    with pytest.raises(OSError, match="fdopen failed"):
        with temporary_credential_file("secret"):
            pass

    assert len(fake.closed) == 1
