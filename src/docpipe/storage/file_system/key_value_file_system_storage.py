"""Filesystem key-value storage implementation."""

import json
from pathlib import Path
from typing import IO, Any, ClassVar

from docpipe.core.job_management.adapters.config.flow_definition_snapshot_storage_factory import (
    register_flow_definition_snapshot_storage,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.exceptions import StorageValidationError
from docpipe.storage.file_system.abstract_file_system_storage import AbstractFileSystemStorage
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_flow_definition_snapshot_storage
class KeyValueFileSystemStorage(AbstractFileSystemStorage, KeyValueStoragePort):
    """
    Thread-safe singleton filesystem storage for JSON-serializable records.

    Stores records as JSON files: {base_dir}/{collection}/{key}.json

    Implements the singleton pattern per base directory to ensure only one
    instance exists for each unique directory.

    Example:
        storage = KeyValueFileSystemStorage(base_dir="data/assets")
        storage.save_record(
            collection="flows",
            key="flow-123",
            data={"name": "my_flow", "id": "flow-123"}
        )
        # Creates: data/assets/flows/flow-123.json
    """

    STORE_BACKEND = "filesystem"

    # Each subclass of AbstractFileSystemStorage has its own singleton registry
    _instances: ClassVar[dict[str, "KeyValueFileSystemStorage"]] = {}

    def _validate_key(self, *, key: str) -> None:
        """Validate that the record key is non-empty and contains no path traversal characters."""
        if not key:
            raise StorageValidationError(message="Key cannot be empty")
        if ".." in key or "/" in key or "\\" in key:
            raise StorageValidationError(message=f"Invalid key: {key}. Keys cannot contain path traversal characters")

    # ------------------------------------------------------------------
    # AbstractFileSystemStorage I/O hooks
    # ------------------------------------------------------------------

    def save_file_content(self, *, file: IO[str], data: Any) -> None:
        """Serialise ``data`` as JSON into ``file``."""
        json.dump(data, file, indent=2, default=str)

    def load_file_content(self, *, file: IO[str]) -> Any:
        """Deserialise JSON from ``file`` and return the parsed object.

        Raises:
            DocpipeException: If the file contains invalid JSON.
        """
        try:
            return json.load(file)
        except json.JSONDecodeError as e:
            raise DocpipeException(
                f"Corrupted JSON file: {e}",
                error_code=ErrorCode.STORAGE_ERROR,
            ) from e

    def _missing_file_value(self) -> None:
        """Return ``None`` when a JSON record file does not exist."""
        return

    def list_files(self, *, collection: str) -> list[Any]:
        """
        List all JSON files in a collection, returning their parsed contents.

        Returns:
            List of parsed dicts; empty list if the collection does not exist
        """
        try:
            collection_dir = self._get_collection_dir(collection=collection)

            if not collection_dir.exists():
                return []

            records = []
            for record_file in collection_dir.glob("*.json"):
                try:
                    with Path(record_file).open(encoding="utf-8") as f:
                        records.append(json.load(f))
                except Exception as e:
                    logger.warning("Failed to read %s: %s", record_file.name, e)
                    continue

            logger.debug("Listed %s files from %s", len(records), collection)
            return records

        except Exception as e:
            raise DocpipeException(
                f"Failed to list files in {collection}: {e}",
                error_code=ErrorCode.STORAGE_ERROR,
            ) from e

    # ------------------------------------------------------------------
    # KeyValueStoragePort implementation — delegates to generic operations
    # ------------------------------------------------------------------

    def save_record(self, *, collection: str, key: str, data: dict[str, Any]) -> None:
        """Save a record to a collection."""
        self._validate_key(key=key)
        self.write_file(collection=collection, file_name=f"{key}.json", data=data)
        logger.debug("Saved record: %s/%s", collection, key)

    def get_record(self, *, collection: str, key: str) -> dict[str, Any] | None:
        """Retrieve a record by key."""
        self._validate_key(key=key)
        return self.read_file(collection=collection, file_name=f"{key}.json")

    def list_records(self, *, collection: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """List all records in a collection."""
        return self.list_files(collection=collection)

    def delete_record(self, *, collection: str, key: str) -> bool:
        """Delete a record by key. Delegates to base delete_file."""
        self._validate_key(key=key)
        return super().delete_file(collection=collection, file_name=f"{key}.json")

    def record_exists(self, *, collection: str, key: str) -> bool:
        """Check if a record exists."""
        self._validate_key(key=key)
        return self.file_exists(collection=collection, file_name=f"{key}.json")
