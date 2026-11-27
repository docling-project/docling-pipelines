# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Abstract base class for filesystem-based storage implementations."""

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Any, ClassVar

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.exceptions import StorageValidationError
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AbstractFileSystemStorage(ABC):
    """
    Abstract base for all filesystem storage implementations.

    Provides shared infrastructure:
    - Singleton pattern per base directory (one instance per unique resolved path)
    - Base directory creation on initialisation
    - Collection sub-path and file name validation (path traversal guards)
    - Helper methods for resolving collection directories and file paths

    Defines a consistent set of generic abstract operations that all subclasses
    must implement:
    - write_file:         persist data to a file
    - read_file:          retrieve data from a file
    - list_files:         list all files in a collection
    - file_exists:        check whether a file exists
    - collection_exists:  check whether a collection directory exists

    Subclasses extend this with storage-type-specific logic:
    - KeyValueFileSystemStorage: JSON record storage
    - ContentFileSystemStorage:     Plain-text / CSV file storage

    The I/O-specific parts are isolated in two abstract hook methods that each
    subclass must implement:
    - save_file_content:  write ``data`` to an already-opened file handle
    - load_file_content:  read and return data from an already-opened file handle

    All other write/read logic (directory creation, atomic rename, existence
    checks, error wrapping) lives once here in ``write_file`` / ``read_file``.
    """

    # Subclasses each maintain their own singleton registry
    _instances: ClassVar[dict[str, "AbstractFileSystemStorage"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    _initialized: bool

    def __new__(cls, *, base_dir: str) -> "AbstractFileSystemStorage":
        """
        Singleton pattern — one instance per (subclass, base_dir) pair.

        Args:
            base_dir: Base directory for storage

        Returns:
            Singleton instance for the given subclass and base directory
        """
        normalized_path = str(Path(base_dir).resolve())

        with cls._lock:
            if normalized_path not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[normalized_path] = instance
                instance._initialized = False
            return cls._instances[normalized_path]  # type: ignore[return-value]

    def __init__(self, *, base_dir: str) -> None:
        """
        Initialise filesystem storage.

        Only runs once per base directory due to the singleton pattern.

        Args:
            base_dir: Base directory for storage
        """
        if self._initialized:
            return

        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        logger.info("Initialized %s at: %s", self.__class__.__name__, self.base_dir)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_collection(self, *, collection: str) -> None:
        """Validate the collection sub-path relative to base_dir.

        The collection is a sub-path appended to base_dir to form the storage
        directory (e.g. ``{job_id}/{job_run_id}``). Forward slashes are
        permitted to allow nested sub-directories. Only ``..`` segments and
        backslashes are rejected to prevent path traversal attacks.
        """
        if not collection:
            raise StorageValidationError(message="Collection name cannot be empty")
        if ".." in collection or "\\" in collection:
            raise StorageValidationError(
                message=f"Invalid collection: {collection}. "
                "Collection sub-path cannot contain path traversal characters"
            )

    def _validate_file_name(self, *, file_name: str) -> None:
        """Validate the file_name to prevent path traversal attacks.

        The file_name is the final component of the storage path and may include
        any extension (e.g. ``flow-123.json``, ``job_report_abc.csv``).
        Path separators and ``..`` segments are rejected.
        """
        if not file_name:
            raise StorageValidationError(message="File name cannot be empty")
        if ".." in file_name or "/" in file_name or "\\" in file_name:
            raise StorageValidationError(
                message=f"Invalid file_name: {file_name}. File name cannot contain path traversal characters"
            )

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_collection_dir(self, *, collection: str) -> Path:
        """Return the absolute directory path for a collection sub-path."""
        self._validate_collection(collection=collection)
        return self.base_dir / collection

    def _get_file_path(self, *, collection: str, file_name: str) -> Path:
        """
        Return the absolute file path for a given collection sub-path and file name.

        Args:
            collection: Sub-path relative to base_dir (e.g. ``{job_id}/{job_run_id}``)
            file_name: File name including extension (e.g. ``job_report_abc.csv``)

        Returns:
            Resolved Path object for the file
        """
        self._validate_file_name(file_name=file_name)
        return self._get_collection_dir(collection=collection) / file_name

    # ------------------------------------------------------------------
    # Abstract I/O hooks — subclasses implement only these two methods
    # ------------------------------------------------------------------

    @abstractmethod
    def save_file_content(self, *, file: IO[str], data: Any) -> None:
        """
        Write ``data`` to an open file handle.

        The file is already open for writing when this is called.
        Subclasses must not close the file handle.

        Args:
            file: Open writable text-mode file handle
            data: Data to write (type is subclass-specific)
        """

    @abstractmethod
    def load_file_content(self, *, file: IO[str]) -> Any:
        """
        Read and return data from an open file handle.

        The file is already open for reading when this is called.
        Subclasses must not close the file handle.

        Args:
            file: Open readable text-mode file handle

        Returns:
            Data read from the file (type is subclass-specific)
        """

    # ------------------------------------------------------------------
    # Concrete template methods — shared write/read logic lives here
    # ------------------------------------------------------------------

    def write_file(self, *, collection: str, file_name: str, data: Any) -> str:
        """
        Persist data to a file within the given collection using an atomic write.

        Creates the collection directory if it does not exist, writes to a
        temporary file, then renames atomically.  The actual serialisation is
        delegated to ``save_file_content``.

        Args:
            collection: Sub-path relative to base_dir
            file_name: File name including extension
            data: Data to persist (type is subclass-specific)

        Returns:
            Absolute filesystem path where the data was written
        """
        try:
            collection_dir = self._get_collection_dir(collection=collection)
            collection_dir.mkdir(parents=True, exist_ok=True)

            file_path = self._get_file_path(collection=collection, file_name=file_name)
            temp_path = file_path.with_suffix(file_path.suffix + ".tmp")

            # newline="" keeps line endings as given (csv writes \r\n), without it they get translated twice
            with Path(temp_path).open("w", encoding="utf-8", newline="") as f:
                self.save_file_content(file=f, data=data)

            temp_path.replace(file_path)
            logger.debug("Wrote file: %s/%s", collection, file_name)
            return str(file_path)

        except StorageValidationError:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to write file {collection}/{file_name}: {e}",
                error_code=ErrorCode.STORAGE_ERROR,
            ) from e

    def read_file(self, *, collection: str, file_name: str) -> Any:
        """
        Read data from a file within the given collection.

        Returns the subclass-specific empty value (e.g. ``None`` or ``""``) when
        the file does not exist.  The actual deserialisation is delegated to
        ``load_file_content``.

        Args:
            collection: Sub-path relative to base_dir
            file_name: File name including extension

        Returns:
            Data read from the file (type is subclass-specific),
            or a suitable empty value if the file does not exist
        """
        try:
            file_path = self._get_file_path(collection=collection, file_name=file_name)

            if not file_path.exists():
                logger.debug("File not found: %s/%s", collection, file_name)
                return self._missing_file_value()

            with Path(file_path).open(encoding="utf-8", newline="") as f:
                data = self.load_file_content(file=f)

            logger.debug("Read file: %s/%s", collection, file_name)
            return data

        except StorageValidationError:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to read file {collection}/{file_name}: {e}",
                error_code=ErrorCode.STORAGE_ERROR,
            ) from e

    def _missing_file_value(self) -> Any:
        """
        Return the value to use when a file does not exist.

        Subclasses may override to return a type-appropriate empty value
        (e.g. ``""`` for text, ``None`` for JSON records).
        Defaults to ``None``.
        """
        return None

    @abstractmethod
    def list_files(self, *, collection: str) -> list[Any]:
        """
        List all files in a collection.

        Args:
            collection: Sub-path relative to base_dir

        Returns:
            List of file contents (type is subclass-specific);
            empty list if the collection does not exist
        """

    def file_exists(self, *, collection: str, file_name: str) -> bool:
        """
        Check whether a file exists in the given collection.

        Args:
            collection: Sub-path relative to base_dir
            file_name: File name including extension

        Returns:
            True if the file exists, False otherwise
        """
        return self._get_file_path(collection=collection, file_name=file_name).exists()

    def collection_exists(self, *, collection: str) -> bool:
        """
        Check whether a collection directory exists.

        Args:
            collection: Sub-path relative to base_dir

        Returns:
            True if the collection directory exists, False otherwise
        """
        collection_dir = self._get_collection_dir(collection=collection)
        return collection_dir.exists() and collection_dir.is_dir()

    def delete_file(self, *, collection: str, file_name: str) -> bool:
        """
        Delete a file from the given collection.

        Args:
            collection: Sub-path relative to base_dir
            file_name: File name including extension

        Returns:
            True if the file was deleted, False if it did not exist
        """
        try:
            file_path = self._get_file_path(collection=collection, file_name=file_name)

            if not file_path.exists():
                return False

            file_path.unlink()
            logger.debug("Deleted file: %s/%s", collection, file_name)
            return True

        except StorageValidationError:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to delete file {collection}/{file_name}: {e}",
                error_code=ErrorCode.STORAGE_ERROR,
            ) from e
