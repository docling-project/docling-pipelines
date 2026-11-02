"""Generic DuckDB-based repository for all asset types using KeyValueStoragePort.

This module provides a unified DuckDB implementation that works for any asset type
(DocumentSet, DocumentLibrary, etc.) using the KeyValueStoragePort abstraction layer.
"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from docpipe.core.assets.common.domain.models.asset import Asset
from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.exceptions.docpipe_exceptions import (
    AssetAlreadyExistsException,
    AssetInvalidDataException,
    AssetNotFoundException,
    DocpipeException,
)
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.utils.infrastructure.logging import get_logger

T = TypeVar("T", bound=Asset)

logger = get_logger(__name__)


class DuckDBAssetRepository[T: Asset](AssetRepository[T]):
    """Generic DuckDB-based repository using KeyValueStoragePort for all asset types.

    This repository provides a unified implementation for storing and retrieving
    any asset type (DocumentSet, DocumentLibrary, etc.) using DuckDB's KeyValueStoragePort implementation.

    The repository is completely generic - it works with any Asset subclass that
    implements to_dict() and from_dict() methods.

    Attributes:
        _asset_type: The asset type class (DocumentSet, DocumentLibrary, etc.)
        _storage: KeyValueStoragePort backend for database operations
        _collection: Collection name derived from asset type
        _database_path: Path to database for health check reporting

    Usage:
        storage = DuckDBKeyValueStorage(database_path="data/duckdb/assets.duckdb")
        repo = DuckDBAssetRepository(
            asset_type=DocumentSet,
            key_value_storage=storage,
            database_path="data/duckdb/assets.duckdb"
        )
        doc_set = DocumentSet(name="my_set", ...)
        saved = repo.save(asset=doc_set)
    """

    def __init__(
        self,
        *,
        asset_type: type[T],
        key_value_storage: KeyValueStoragePort,
        database_path: str,
    ) -> None:
        """Initialize the DuckDB asset repository with injected storage.

        Args:
            asset_type: The asset type class (DocumentSet, DocumentLibrary, etc.)
            key_value_storage: KeyValueStoragePort implementation (DuckDB-based)
            database_path: Path to DuckDB database file (for health check reporting)
        """
        self._asset_type = asset_type
        self._storage = key_value_storage
        # Every Asset subclass defines get_collection_name(). Subclasses or factories may
        # still override _collection after construction for backward compatibility.
        self._collection = asset_type.get_collection_name()
        self._database_path = database_path
        logger.info(
            "DuckDBAssetRepository initialized for %s with collection '%s'",
            asset_type.__name__,
            self._collection,
        )

    def save(self, *, asset: T) -> T:
        """Save a new asset to the repository.

        Args:
            asset: The asset to save

        Returns:
            The saved asset with timestamps set

        Raises:
            AssetAlreadyExistsException: If an asset with the same ID or name already exists
            AssetInvalidDataException: If asset validation fails
            DocpipeException: If the repository is not accessible or configured
        """
        # Validate the asset
        asset.validate()

        # Ensure ID is set
        if not asset.asset_id:
            raise AssetInvalidDataException(f"{self._asset_type.__name__} asset_id cannot be None")

        try:
            # Check if asset already exists by ID
            if self._storage.record_exists(collection=self._collection, key=asset.asset_id):
                raise AssetAlreadyExistsException(
                    f"{self._asset_type.__name__} with ID '{asset.asset_id}' already exists",
                    asset_id=asset.asset_id,
                    asset_type=self._asset_type.__name__,
                )

            # Check if name already exists
            all_records = self._storage.list_records(collection=self._collection)
            for record in all_records:
                if record.get("name") == asset.name:
                    raise AssetAlreadyExistsException(
                        f"{self._asset_type.__name__} with name '{asset.name}' already exists",
                        asset_name=asset.name,
                        asset_type=self._asset_type.__name__,
                    )

            # Convert to dict and save
            data = asset.to_dict()
            self._storage.save_record(collection=self._collection, key=asset.asset_id, data=data)

            logger.info("Saved %s: %s (name: %s)", self._asset_type.__name__, asset.asset_id, asset.name)
            return asset

        except (AssetAlreadyExistsException, AssetInvalidDataException):
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to save {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_by_id(self, *, asset_id: str) -> T | None:
        """Retrieve an asset by its unique identifier.

        Args:
            asset_id: The unique identifier of the asset

        Returns:
            The asset with the specified ID, or None if not found

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            data = self._storage.get_record(collection=self._collection, key=asset_id)

            if data is None:
                return None

            # Convert dict to Asset using from_dict class method
            asset = self._asset_type.from_dict(data=data)
            logger.debug("Retrieved %s: %s", self._asset_type.__name__, asset_id)
            return asset  # type: ignore[return-value]

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to retrieve {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_by_name(self, *, name: str) -> T | None:
        """Retrieve an asset by its name.

        Args:
            name: The name of the asset

        Returns:
            The asset with the specified name, or None if not found

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            # List all records and find by name
            all_records = self._storage.list_records(collection=self._collection)

            for data in all_records:
                if data.get("name") == name:
                    asset = self._asset_type.from_dict(data=data)
                    logger.debug("Retrieved %s by name: %s", self._asset_type.__name__, name)
                    return asset  # type: ignore[return-value]

            return None

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to retrieve {self._asset_type.__name__} by name: {e!s}",
                status_code=500,
            ) from e

    def update(self, *, asset: T) -> T:
        """Update an existing asset in the repository.

        Args:
            asset: The asset with updated fields

        Returns:
            The updated asset

        Raises:
            AssetNotFoundException: If the asset does not exist
            AssetInvalidDataException: If the update would violate constraints
            DocpipeException: If the repository is not accessible
        """
        # Validate the asset
        asset.validate()

        # Ensure ID is set
        if not asset.asset_id:
            raise AssetInvalidDataException(f"{self._asset_type.__name__} asset_id cannot be None")

        try:
            # Check if asset exists
            if not self._storage.record_exists(collection=self._collection, key=asset.asset_id):
                raise AssetNotFoundException(
                    f"{self._asset_type.__name__} not found: {asset.asset_id}",
                    asset_id=asset.asset_id,
                    asset_type=self._asset_type.__name__,
                )

            # Check if name conflicts with another asset
            all_records = self._storage.list_records(collection=self._collection)
            for record in all_records:
                record_id = record.get("asset_id")
                if record.get("name") == asset.name and record_id != asset.asset_id:
                    raise AssetInvalidDataException(
                        f"Update would violate constraints: name '{asset.name}' already exists"
                    )

            # Update timestamp
            asset.update_timestamp()

            # Convert to dict and save (upsert)
            data = asset.to_dict()
            self._storage.save_record(collection=self._collection, key=asset.asset_id, data=data)

            logger.info("Updated %s: %s", self._asset_type.__name__, asset.asset_id)
            return asset

        except (AssetNotFoundException, AssetInvalidDataException):
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to update {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def delete(self, *, asset_id: str) -> bool:
        """Delete an asset from the repository.

        Args:
            asset_id: The unique identifier of the asset to delete

        Returns:
            True if the asset was deleted, False if it did not exist

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            deleted = self._storage.delete_record(collection=self._collection, key=asset_id)

            if deleted:
                logger.info("Deleted %s: %s", self._asset_type.__name__, asset_id)
            else:
                logger.info("%s not found for deletion: %s", self._asset_type.__name__, asset_id)

            return deleted

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to delete {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_all(self) -> list[T]:
        """List all assets in the repository.

        Returns:
            A list of all assets, empty list if none exist

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            all_records = self._storage.list_records(collection=self._collection)

            # Convert dicts to Asset objects
            assets: list[T] = [self._asset_type.from_dict(data=record) for record in all_records]  # type: ignore[misc]

            assets.sort(key=lambda a: a.get_created_at() or datetime.min.replace(tzinfo=UTC), reverse=True)

            logger.debug("Retrieved %d %s assets", len(assets), self._asset_type.__name__)
            return assets

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to list {self._asset_type.__name__} assets: {e!s}",
                status_code=500,
            ) from e

    def list_all(self, *, limit: int | None = None, offset: int | None = None) -> list[T]:
        """Retrieve all assets with optional pagination, sorted newest-first.

        Args:
            limit: Maximum number of assets to return (None for all)
            offset: Number of assets to skip (None / 0 for none)

        Returns:
            List of assets sorted by creation date newest-first
        """
        assets = self.find_all()
        if offset:
            assets = assets[offset:]
        if limit is not None:
            assets = assets[:limit]
        return assets

    def exists(self, *, asset_id: str) -> bool:
        """Check if an asset exists.

        Args:
            asset_id: The unique identifier to check

        Returns:
            True if an asset with the given ID exists, False otherwise

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            return self._storage.record_exists(collection=self._collection, key=asset_id)
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to check {self._asset_type.__name__} existence: {e!s}",
                status_code=500,
            ) from e

    def exists_by_name(self, *, name: str) -> bool:
        """Check if an asset with the given name exists.

        Args:
            name: The name to check

        Returns:
            True if an asset with this name exists, False otherwise

        Raises:
            DocpipeException: If the repository is not accessible
        """
        return self.find_by_name(name=name) is not None

    def partial_update(self, asset: T, updates: dict[str, Any]) -> T:
        """Apply partial updates to an existing asset.

        Args:
            asset: Asset entity to update
            updates: Dictionary of field updates to apply

        Returns:
            Updated asset with refreshed timestamp

        Raises:
            AssetInvalidDataException: If validation fails after applying updates
            DocpipeException: If persistence fails
        """
        # Apply updates
        for field, value in updates.items():
            if hasattr(asset, field):
                setattr(asset, field, value)

        # Validate and persist
        asset.validate()
        asset.update_timestamp()
        return self.update(asset=asset)

    def bulk_delete(self, *, asset_ids: list[str]) -> dict[str, Any]:
        """Delete multiple assets in a batch operation.

        Args:
            asset_ids: List of asset IDs to delete

        Returns:
            Dictionary with deletion results
        """
        deleted = []
        failed = []

        for asset_id in asset_ids:
            try:
                if self.delete(asset_id=asset_id):
                    deleted.append(asset_id)
                else:
                    failed.append({"asset_id": asset_id, "error": self._asset_type.__name__ + " not found"})
            except Exception as e:
                failed.append({"asset_id": asset_id, "error": str(e)})
                logger.warning("Failed to delete %s %s: %s", self._asset_type.__name__, asset_id, e)

        return {
            "total_requested": len(asset_ids),
            "total_deleted": len(deleted),
            "total_failed": len(failed),
            "deleted": deleted,
            "failed": failed,
        }

    @classmethod
    def from_config(cls, *, asset_type: type[T], config: dict[str, Any]) -> "DuckDBAssetRepository[T]":
        """Create a DuckDBAssetRepository from a config dict.

        Validates config, creates the KeyValueStoragePort, and pins _collection
        via asset_type.get_collection_name().

        Args:
            asset_type: The asset model class (DocumentSet, DocumentLibrary, etc.)
            config: Must contain ``database_path``. Optional ``storage_adapter``
                    key selects the storage backend (default: ``"duckdb"``).

        Returns:
            Configured DuckDBAssetRepository instance

        Raises:
            DocpipeException: If config is invalid or storage creation fails
        """
        from docpipe.exceptions.error_codes import ErrorCode
        from docpipe.storage import StorageFactory

        errors = cls.validate_config(config=config)
        if errors:
            raise DocpipeException(
                message=f"Invalid config for {asset_type.__name__} repository: {'; '.join(errors)}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        storage_type = config.get("storage_adapter", "duckdb")
        database_path = config["database_path"]

        try:
            key_value_storage = StorageFactory.create_key_value_storage(
                storage_type=storage_type,
                database_path=database_path,
            )
        except Exception as e:
            raise DocpipeException(
                message=f"Failed to create storage for {asset_type.__name__} repository: {e!s}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            ) from e

        return cls(
            asset_type=asset_type,
            key_value_storage=key_value_storage,
            database_path=database_path,
        )

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate repository configuration.

        Checks that ``database_path`` is present, a non-empty string.
        Subclasses can override to add asset-specific validation.

        Args:
            config: Configuration dictionary to validate

        Returns:
            List of validation error strings (empty = valid)
        """
        errors = []
        if "database_path" not in config:
            errors.append("Missing required configuration: 'database_path'")
        elif not isinstance(config["database_path"], str):
            errors.append("Configuration 'database_path' must be a string")
        elif not config["database_path"]:
            errors.append("Configuration 'database_path' cannot be empty")
        return errors

    def health_check(self) -> dict[str, Any]:
        """Check the health status of the repository.

        Returns:
            A dictionary containing health status information
        """
        try:
            # Test storage connectivity by checking if collection exists
            exists = self._storage.collection_exists(collection=self._collection)

            return {
                "status": "healthy",
                "message": "Repository is healthy",
                "details": {
                    "database_path": self._database_path,
                    "collection": self._collection,
                    "collection_exists": exists,
                    "asset_type": self._asset_type.__name__,
                },
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {e}",
                "details": {
                    "database_path": self._database_path,
                    "collection": self._collection,
                    "asset_type": self._asset_type.__name__,
                    "error": str(e),
                },
            }
