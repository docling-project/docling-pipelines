"""Filesystem source adapter implementation."""

import mimetypes
import os
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, AsyncGenerator, Generator
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort

from .config import FilesystemSourceConfig


@register_source_adapter
class FilesystemSourceAdapter(DocumentSourcePort[FilesystemSourceConfig]):
    """
    Adapter for ingesting documents from local filesystem.

    This adapter implements the DocumentSourcePort interface for local file access.
    It demonstrates the hexagonal architecture pattern where:
    - The adapter depends on the port interface (inversion of control)
    - Business logic is separated from infrastructure concerns
    - The adapter can be easily swapped or mocked for testing
    """

    # Metadata for connector discovery
    SOURCE_NAME = "filesystem"
    SOURCE_DISPLAY_NAME = "Local Filesystem"
    SOURCE_DESCRIPTION = "Ingest documents from local filesystem directories"
    SOURCE_VERSION = "1.0.0"

    async def fetch_documents(self, config: FilesystemSourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """
        Fetch documents from filesystem.

        Args:
            config: Validated filesystem configuration

        Yields:
            Document: Domain documents from filesystem
        """
        for root_path in self._iter_root_paths(config):
            # Single file mode - if root_path is a file
            if root_path.is_file():
                try:
                    # Get file metadata to check size and populate Document fields
                    stat = root_path.stat()

                    # Check file size limit
                    if config.max_file_size_mb:
                        file_size_mb = stat.st_size / (1024 * 1024)
                        if file_size_mb > config.max_file_size_mb:
                            print(
                                f"Skipping file {root_path}: size {file_size_mb:.2f}MB exceeds limit {config.max_file_size_mb}MB"
                            )
                            continue

                    mimetype, _ = mimetypes.guess_type(str(root_path))

                    # Create domain document with empty content (lazy loading)
                    # Binary content is fetched on-demand via fetch_binary_content()
                    document = Document(
                        id=str(root_path.absolute()),
                        name=root_path.name,
                        content=b"",
                        source_url=f"file://{root_path.absolute()}",
                        modified_time=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                        created_time=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                        mimetype=mimetype,
                        size=stat.st_size,
                        extension=root_path.suffix.lower(),
                        metadata={
                            "absolute_path": str(root_path.absolute()),
                            "parent_directory": str(root_path.parent),
                        },
                    )

                    yield document

                except Exception as e:
                    print(f"Error processing file {root_path}: {e}")
                    raise

            else:
                # Directory mode - walk through directory tree
                for file_path in self._walk_directory(root_path, config):
                    try:
                        # Get file metadata to check size and populate Document fields
                        stat = file_path.stat()

                        # Check file size limit
                        if config.max_file_size_mb:
                            file_size_mb = stat.st_size / (1024 * 1024)
                            if file_size_mb > config.max_file_size_mb:
                                continue

                        mimetype, _ = mimetypes.guess_type(str(file_path))

                        # Create domain document with empty content (lazy loading)
                        document = Document(
                            id=str(file_path.absolute()),
                            name=file_path.name,
                            content=b"",
                            source_url=f"file://{file_path.absolute()}",
                            modified_time=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                            created_time=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                            mimetype=mimetype,
                            size=stat.st_size,
                            extension=file_path.suffix.lower(),
                            metadata={
                                "relative_path": str(file_path.relative_to(root_path)),
                                "absolute_path": str(file_path.absolute()),
                                "parent_directory": str(file_path.parent),
                            },
                        )

                        yield document

                    except Exception as e:
                        # Log error but continue processing other files
                        print(f"Error processing file {file_path}: {e}")
                        continue

    @classmethod
    def bind_file_reference(cls, *, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set filesystem ``paths`` to one canonical file."""
        file_path = Path(file_reference)
        try:
            file_path = file_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"File reference does not exist: {file_reference}") from exc
        if not file_path.is_file() or not os.access(file_path, os.R_OK):
            raise ValueError(f"File reference is not a readable regular file: {file_reference}")

        provider_config["paths"] = [str(file_path)]

    async def test_connection(self, config: FilesystemSourceConfig) -> tuple[bool, str]:
        """
        Test filesystem access.

        Args:
            config: Validated filesystem configuration

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            failed: list[str] = []
            for root_path in self._iter_root_paths(config):
                if not root_path.exists():
                    failed.append(f"Path does not exist: {root_path}")
                    continue
                if not os.access(root_path, os.R_OK):
                    failed.append(f"Path is not readable: {root_path}")
                    continue
                # For directories, verify we can list contents
                if root_path.is_dir():
                    try:
                        list(root_path.iterdir())
                    except PermissionError:
                        failed.append(f"Permission denied: {root_path}")
                # For files, verify it's a regular file
                elif not root_path.is_file():
                    failed.append(f"Path is not a file: {root_path}")

            if failed:
                return False, "; ".join(failed)
            paths_str = ", ".join(str(p) for p in self._iter_root_paths(config))
            return True, f"Successfully connected to {paths_str}"

        except Exception as e:
            return False, f"Connection test failed: {e!s}"

    def get_config_schema(self) -> type[BaseModel]:
        """Get the configuration schema for this adapter."""
        return FilesystemSourceConfig

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> FilesystemSourceConfig:
        """
        Build Filesystem configuration from operator parameters.

        Args:
            provider_config: All provider-specific parameters.
            included_extensions: File extensions to include (optional)
            max_files: Not used by the filesystem adapter.

        Returns:
            FilesystemSourceConfig: Validated configuration object

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        config_dict = {
            "paths": provider_config.get("paths"),
            "recursive": provider_config.get("recursive", True),
            "file_extensions": included_extensions or [],
            "exclude_patterns": provider_config.get("exclude_patterns", []),
            "follow_symlinks": provider_config.get("follow_symlinks", False),
        }

        # Add optional fields only if they exist
        if "max_file_size_mb" in provider_config:
            config_dict["max_file_size_mb"] = provider_config["max_file_size_mb"]

        return FilesystemSourceConfig(**config_dict)

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific file on-demand.

        Args:
            source_id: File path (absolute or relative to paths)
            provider_config: All provider-specific parameters (used for fallback path resolution).

        Returns:
            bytes | None: Binary content of the file, or None if not found or error occurred
        """
        try:
            parsed_source = urlparse(source_id)
            if parsed_source.scheme == "file":
                file_path = Path(unquote(parsed_source.path))
            else:
                file_path = Path(source_id)

                # If path is not absolute, try relative to paths
                if not file_path.is_absolute():
                    first_path = provider_config.get("paths", [None])[0] if provider_config.get("paths") else None
                    if first_path:
                        file_path = Path(first_path) / file_path

            # Check if file exists
            if not file_path.exists():
                print(f"File not found: {file_path}")
                return None

            # Check if it's a file (not directory)
            if not file_path.is_file():
                print(f"Path is not a file: {file_path}")
                return None

            # Read and return file content
            with Path(file_path).open("rb") as f:
                content = f.read()

            print(f"Successfully read {len(content)} bytes from: {file_path}")
            return content

        except PermissionError as e:
            print(f"Permission denied reading file {source_id}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error reading file {source_id}: {e}")
            return None

    def _iter_root_paths(self, config: FilesystemSourceConfig) -> Generator[Path, None, None]:
        """
        Yield each root path from config as a Path object.

        Args:
            config: Filesystem configuration

        Yields:
            Path: Each root path
        """
        for p in config.paths:
            yield Path(p)

    def _walk_directory(self, root_path: Path, config: FilesystemSourceConfig) -> Generator[Path, None, None]:
        """
        Walk through directory tree and yield file paths.

        Args:
            root_path: Root directory to walk
            config: Configuration with filters

        Yields:
            Path: File paths matching criteria
        """
        if config.recursive:
            # Recursive walk
            for dirpath, dirnames, filenames in os.walk(root_path, followlinks=config.follow_symlinks):
                # Filter out excluded directories
                dirnames[:] = [d for d in dirnames if not self._is_excluded(str(Path(dirpath) / d), config)]

                for filename in filenames:
                    file_path = Path(dirpath) / filename

                    # Apply filters
                    if self._should_include_file(file_path, config):
                        yield file_path
        else:
            # Non-recursive - only top level
            for item in root_path.iterdir():
                if item.is_file() and self._should_include_file(item, config):
                    yield item

    def _should_include_file(self, file_path: Path, config: FilesystemSourceConfig) -> bool:
        """
        Check if file should be included based on filters.

        Args:
            file_path: Path to check
            config: Configuration with filters

        Returns:
            bool: True if file should be included
        """
        # Check if excluded by pattern
        if self._is_excluded(str(file_path), config):
            return False

        # Check file extension filter
        if config.file_extensions:
            if file_path.suffix.lower() not in config.file_extensions:
                return False

        return True

    def _is_excluded(self, path: str, config: FilesystemSourceConfig) -> bool:
        """
        Check if path matches any exclude pattern.

        Args:
            path: Path to check
            config: Configuration with exclude patterns

        Returns:
            bool: True if path should be excluded
        """
        for pattern in config.exclude_patterns:
            if fnmatch(path, pattern):
                return True
        return False
