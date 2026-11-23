"""Archive helpers for lazy filesystem ingestion."""

import gzip
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from docpipe.core.constants.operator_constants import OperatorConstants


@dataclass(frozen=True)
class ArchiveEntry:
    """Metadata for one regular file stored in an archive."""

    name: str
    size: int | None


def archive_extension(path_or_name: str | Path) -> str | None:
    """Return the supported archive extension for a path, longest suffix first."""
    name = str(path_or_name).lower()
    return next(
        (extension for extension in OperatorConstants.FileExtensions.ARCHIVE_EXTENSIONS if name.endswith(extension)),
        None,
    )


def is_archive_path(path_or_name: str | Path) -> bool:
    """Return whether a path has a supported archive extension."""
    return archive_extension(path_or_name) is not None


def file_extension(path_or_name: str | Path) -> str:
    """Return a normalized archive or regular file extension."""
    return archive_extension(path_or_name) or Path(path_or_name).suffix.lower()


def build_archive_uri(*, archive_path: Path, entry_name: str) -> str:
    """Build the synthetic URI used to address one archive entry."""
    encoded_path = quote(str(archive_path.absolute()), safe="/")
    encoded_entry = quote(entry_name, safe="/")
    return f"zip://{encoded_path}#{encoded_entry}"


def parse_archive_uri(uri: str) -> tuple[Path, str]:
    """Parse a synthetic archive-entry URI into its archive path and member name."""
    parsed = urlparse(uri)
    if parsed.scheme != "zip" or not parsed.fragment:
        raise ValueError(f"Invalid archive URI: {uri}")

    archive_path = unquote(f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path)
    return Path(archive_path), unquote(parsed.fragment)


def list_archive_entries(archive_path: Path) -> list[ArchiveEntry]:
    """List regular file entries without extracting them to disk."""
    extension = archive_extension(archive_path)
    if extension == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            return [
                ArchiveEntry(name=info.filename, size=info.file_size)
                for info in archive.infolist()
                if not info.is_dir()
            ]

    if extension in {".tar", ".tar.gz", ".tgz"}:
        with tarfile.open(archive_path, mode="r:*") as archive:
            return [
                ArchiveEntry(name=member.name, size=member.size) for member in archive.getmembers() if member.isfile()
            ]

    if extension == ".gz":
        return [ArchiveEntry(name=archive_path.name.removesuffix(".gz"), size=None)]

    raise ValueError(f"Unsupported archive format: {archive_path}")


def read_archive_uri(uri: str) -> bytes:
    """Read one archive member in memory without writing temporary files."""
    archive_path, entry_name = parse_archive_uri(uri)
    extension = archive_extension(archive_path)

    if extension == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            return archive.read(entry_name)

    if extension in {".tar", ".tar.gz", ".tgz"}:
        with tarfile.open(archive_path, mode="r:*") as archive:
            member = archive.getmember(entry_name)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Archive entry is not a regular file: {entry_name}")
            return extracted.read()

    if extension == ".gz":
        expected_name = archive_path.name.removesuffix(".gz")
        if entry_name != expected_name:
            raise KeyError(entry_name)
        with gzip.open(archive_path, mode="rb") as archive:
            return archive.read()

    raise ValueError(f"Unsupported archive format: {archive_path}")
