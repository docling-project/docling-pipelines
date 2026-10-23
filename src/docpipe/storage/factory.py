"""Factory for creating storage instances."""

from typing import Any, ClassVar

from docpipe.storage.duck_db.duckdb_key_value_storage import DuckDBKeyValueStorage
from docpipe.storage.duck_db.duckdb_table_storage import DuckDBTableStorage
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.storage.postgres.postgres_table_storage import PostgresTableStorage
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class StorageFactory:
    """Factory for creating storage instances.

    Provides methods to create key-value and table storage implementations
    with validation and clear error messages.
    """

    # Supported storage types
    SUPPORTED_KEY_VALUE_TYPES: ClassVar[list[str]] = ["filesystem", "duckdb"]
    SUPPORTED_TABLE_TYPES: ClassVar[list[str]] = ["duckdb", "postgres"]

    # Settings each table storage backend takes. Callers pass one storage block with
    # the settings of any backend, and each backend receives only its own.
    TABLE_STORAGE_SETTINGS: ClassVar[dict[str, tuple[str, ...]]] = {
        "duckdb": ("database_path",),
        "postgres": ("schema", "postgres"),
    }

    @staticmethod
    def create_key_value_storage(*, storage_type: str, **config: Any) -> KeyValueStoragePort:
        """Create a key-value storage instance.

        Args:
            storage_type: Type of storage ("filesystem", "duckdb")
            **config: Storage-specific configuration

        Returns:
            KeyValueStorage instance

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

        Every backend takes the same flat settings, so a caller can pass one storage
        block and let ``storage_type`` choose the backend. Settings of the other
        backends are ignored; ``None`` values are left to the backend defaults.

        Args:
            storage_type: Type of storage ("duckdb" or "postgres")
            **config: Storage settings: ``database_path`` (duckdb), ``schema`` and
                ``postgres`` connection settings (postgres)

        Returns:
            TableStorage instance

        Raises:
            ValueError: If storage_type is not supported or a setting is unknown

        Example:
            storage = StorageFactory.create_table_storage(
                storage_type="duckdb",
                database_path="data/tables.db"
            )
        """
        logger.debug("Creating table storage: %s", storage_type)

        if storage_type not in StorageFactory.TABLE_STORAGE_SETTINGS:
            raise ValueError(
                f"Unsupported table storage type: '{storage_type}'. "
                f"Supported types: {', '.join(StorageFactory.SUPPORTED_TABLE_TYPES)}"
            )

        known_settings = {name for names in StorageFactory.TABLE_STORAGE_SETTINGS.values() for name in names}
        unknown_settings = sorted(set(config) - known_settings)
        if unknown_settings:
            raise ValueError(f"Unknown table storage settings: {', '.join(unknown_settings)}")

        settings = {
            name: config[name]
            for name in StorageFactory.TABLE_STORAGE_SETTINGS[storage_type]
            if config.get(name) is not None
        }
        if storage_type == "duckdb":
            return DuckDBTableStorage(**settings)
        return PostgresTableStorage(**settings)
