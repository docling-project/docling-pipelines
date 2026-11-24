# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the filesystem archive helpers.

Archive-entry URIs are written as ``zip:<posix path>#<entry>`` here: parse_archive_uri accepts
that form and it resolves to the same file on every OS, unlike the ``zip://`` form whose
drive letter would land in the URI authority on Windows.
"""

import gzip
import io
import tarfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest

from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.archive import (
    ArchiveEntry,
    build_archive_uri,
    file_extension,
    is_archive_path,
    list_archive_entries,
    parse_archive_uri,
    read_archive_uri,
)


def _uri(archive_path: Path, entry_name: str) -> str:
    """Build an OS-neutral archive-entry URI for ``archive_path``."""
    return f"zip:{quote(archive_path.as_posix(), safe='/')}#{quote(entry_name, safe='/')}"


def _write_tar_with_directory(path: Path) -> None:
    """Write a TAR containing a directory member and one regular file."""
    with tarfile.open(path, mode="w") as archive:
        folder = tarfile.TarInfo("folder")
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        content = b"data"
        info = tarfile.TarInfo("folder/a.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))


class TestExtensionHelpers:
    """archive_extension based helpers."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a.TAR.GZ", ".tar.gz"), ("a.tgz", ".tgz"), ("a.txt.gz", ".gz"), ("Report.PDF", ".pdf"), ("README", "")],
    )
    def test_file_extension_prefers_longest_archive_suffix(self, name, expected):
        """Archive suffixes win (longest first); other files fall back to the lowercased suffix."""
        assert file_extension(name) == expected

    def test_is_archive_path(self):
        """Only supported archive suffixes count as archives."""
        assert is_archive_path("bundle.zip") is True
        assert is_archive_path("bundle.rar") is False


class TestBuildArchiveUri:
    """build_archive_uri encoding."""

    def test_encodes_path_and_entry(self, tmp_path: Path):
        """The absolute archive path and the entry name are percent-encoded into a zip:// URI."""
        uri = build_archive_uri(archive_path=tmp_path / "my bundle.zip", entry_name="sub dir/a#1.txt")

        assert uri.startswith("zip://")
        assert uri.endswith("my%20bundle.zip#sub%20dir/a%231.txt")


class TestParseArchiveUri:
    """parse_archive_uri validation."""

    @pytest.mark.parametrize("uri", ["file:///tmp/a.zip#entry", "zip:///tmp/a.zip"], ids=["scheme", "no-fragment"])
    def test_rejects_non_archive_uris(self, uri):
        """Only zip: URIs with an entry fragment are accepted."""
        with pytest.raises(ValueError, match="Invalid archive URI"):
            parse_archive_uri(uri)

    def test_decodes_path_and_entry(self, tmp_path: Path):
        """Percent-encoded path and entry name are decoded."""
        archive_path = tmp_path / "my bundle.zip"

        assert parse_archive_uri(_uri(archive_path, "sub dir/a b.txt")) == (archive_path, "sub dir/a b.txt")


class TestListArchiveEntries:
    """list_archive_entries per format."""

    def test_gzip_lists_single_member_without_size(self, tmp_path: Path):
        """A .gz file has one member named after the file without the suffix."""
        archive_path = tmp_path / "notes.txt.gz"
        archive_path.write_bytes(gzip.compress(b"notes"))

        assert list_archive_entries(archive_path) == [ArchiveEntry(name="notes.txt", size=None)]

    def test_tar_skips_directories(self, tmp_path: Path):
        """Directory members of a TAR are not listed."""
        archive_path = tmp_path / "bundle.tar"
        _write_tar_with_directory(archive_path)

        assert list_archive_entries(archive_path) == [ArchiveEntry(name="folder/a.txt", size=4)]

    def test_unsupported_extension_raises(self, tmp_path: Path):
        """A path without an archive extension is rejected."""
        with pytest.raises(ValueError, match="Unsupported archive format"):
            list_archive_entries(tmp_path / "plain.txt")


class TestListZipEntries:
    """list_archive_entries for ZIP files."""

    def test_zip_skips_directories(self, tmp_path: Path):
        """Directory entries of a ZIP are not listed."""
        archive_path = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            archive.writestr("folder/", b"")
            archive.writestr("folder/a.txt", b"abc")

        assert list_archive_entries(archive_path) == [ArchiveEntry(name="folder/a.txt", size=3)]


class TestReadArchiveUri:
    """read_archive_uri per format."""

    def test_reads_zip_member(self, tmp_path: Path):
        """A ZIP member is read into memory."""
        archive_path = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            archive.writestr("folder/a.txt", b"zip-data")

        assert read_archive_uri(_uri(archive_path, "folder/a.txt")) == b"zip-data"

    def test_reads_tar_member(self, tmp_path: Path):
        """A regular TAR member is read into memory."""
        archive_path = tmp_path / "bundle.tar"
        _write_tar_with_directory(archive_path)

        assert read_archive_uri(_uri(archive_path, "folder/a.txt")) == b"data"

    def test_tar_directory_member_raises(self, tmp_path: Path):
        """A TAR member that is not a regular file cannot be read."""
        archive_path = tmp_path / "bundle.tar"
        _write_tar_with_directory(archive_path)

        with pytest.raises(ValueError, match="Archive entry is not a regular file: folder"):
            read_archive_uri(_uri(archive_path, "folder"))

    def test_reads_gzip_member(self, tmp_path: Path):
        """The single member of a .gz file is decompressed."""
        archive_path = tmp_path / "notes.txt.gz"
        archive_path.write_bytes(gzip.compress(b"notes"))

        assert read_archive_uri(_uri(archive_path, "notes.txt")) == b"notes"

    def test_gzip_wrong_member_name_raises_key_error(self, tmp_path: Path):
        """Asking a .gz file for a member other than its own name raises KeyError."""
        archive_path = tmp_path / "notes.txt.gz"
        archive_path.write_bytes(gzip.compress(b"notes"))

        with pytest.raises(KeyError, match=r"other\.txt"):
            read_archive_uri(_uri(archive_path, "other.txt"))

    def test_unsupported_extension_raises(self, tmp_path: Path):
        """A URI pointing at a non-archive file is rejected."""
        with pytest.raises(ValueError, match="Unsupported archive format"):
            read_archive_uri(_uri(tmp_path / "plain.txt", "entry"))
