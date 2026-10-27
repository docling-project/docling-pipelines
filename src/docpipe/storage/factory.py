# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory for creating storage instances."""

from typing import Any, ClassVar

from docpipe.storage.duck_db.duckdb_key_value_storage import DuckDBKeyValueStorage
from docpipe.storage.duck_db.duckdb_table_storage import DuckDBTableStorage
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class StorageFactory:
    """Factory for creating storage instances.

    Provides methods to create key-value and table storage implementations
    with validation and clear error messages.
    """

    # Supported storage types
    SUPPORTED_KEY_VALUE_TYPES: ClassVar[list[str]] = ["filesystem", "duckdb"]
    SUPPORTED_TABLE_TYPES: ClassVar[list[str]] = ["duckdb"]

    @staticmethod
    def create_key_value_storage(*, storage_type: str, **config: Any) -> KeyValueStoragePort:
        """Create a key-value storage instance.

        Args:
            storage_type: Type of storage ("filesystem", "duckdb")
            **config: Storage-specific configuration

        Returns:
            KeyValueStoragePort instance

        Raises:
            ValueError: If storage_type is not supported

        Example:
            storage = StorageFactory.create_key_value_storage(
                storage_type="duckdb",
                database_path="data/assets.db"
            )
        """
        logger.debug("Creating key-value storage: %s", storage_type)

        if storage_type == "filesystem":
            return KeyValueFileSystemStorage(**config)
        if storage_type == "duckdb":
            return DuckDBKeyValueStorage(**config)
        raise ValueError(
            f"Unsupported key-value storage type: '{storage_type}'. "
            f"Supported types: {', '.join(StorageFactory.SUPPORTED_KEY_VALUE_TYPES)}"
        )

    @staticmethod
    def create_table_storage(*, storage_type: str, **config: Any) -> TableStoragePort:
        """Create a table storage instance.

        Args:
            storage_type: Type of storage ("duckdb")
            **config: Storage-specific configuration

        Returns:
            TableStoragePort instance

        Raises:
            ValueError: If storage_type is not supported

        Example:
            storage = StorageFactory.create_table_storage(
                storage_type="duckdb",
                database_path="data/tables.db"
            )
        """
        logger.debug("Creating table storage: %s", storage_type)

        if storage_type == "duckdb":
            return DuckDBTableStorage(**config)
        raise ValueError(
            f"Unsupported table storage type: '{storage_type}'. "
            f"Supported types: {', '.join(StorageFactory.SUPPORTED_TABLE_TYPES)}"
        )
