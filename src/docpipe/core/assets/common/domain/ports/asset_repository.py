# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Generic repository interface for all asset types.

This module defines the abstract repository interface that all asset repositories
must implement. It provides a consistent API for BASIC CRUD operations across different
storage backends (local filesystem, DuckDB, CAMS, etc.).

Model-specific repositories can extend this interface to add their own operations
(e.g., bulk_delete for FlowRepository).
"""

from abc import ABC, abstractmethod
from typing import Any

from docpipe.core.assets.common.domain.models.asset import Asset


class AssetRepository[T: Asset](ABC):
    """Generic repository interface for all asset types - BASIC CRUD only.

    This interface defines the contract that all asset repositories must implement.
    It is model-agnostic and works with any asset type (Flow, DocumentSet, etc.).

    Only truly generic operations are included here. Model-specific operations
    (bulk_delete, partial_update, junction tables, etc.) should be added in
    model-specific repository interfaces that extend this base.

    Type Parameters:
        T: Asset type (Flow, DocumentSet, DocumentLibrary, etc.)
    """

    # ==================== CRUD Operations ====================

    @abstractmethod
    def save(self, *, asset: T) -> T:
        """Save a new asset to the repository.

        Args:
            asset: Asset instance to save (asset_id will be generated if not present)

        Returns:
            Saved asset with generated asset_id

        Raises:
            Exception: If save fails
        """
        ...

    @abstractmethod
    def find_by_id(self, *, asset_id: str) -> T | None:
        """Retrieve an asset by its unique identifier.

        Args:
            asset_id: Unique identifier of the asset

        Returns:
            Asset instance if found, None otherwise
        """
        ...

    @abstractmethod
    def find_by_name(self, *, name: str) -> T | None:
        """Retrieve an asset by its name.

        Args:
            name: Name of the asset

        Returns:
            Asset instance if found, None otherwise
        """
        ...

    @abstractmethod
    def find_all(self) -> list[T]:
        """Retrieve all assets from the repository.

        Returns:
            List of all assets
        """
        ...

    @abstractmethod
    def update(self, *, asset: T) -> T:
        """Update an existing asset in the repository.

        Args:
            asset: Asset instance with updated data (must have asset_id)

        Returns:
            Updated asset

        Raises:
            Exception: If asset doesn't exist or update fails
        """
        ...

    @abstractmethod
    def partial_update(self, asset: T, updates: dict[str, Any]) -> T:
        """Apply partial updates to an existing asset and persist changes.

        Args:
            existing_asset: Asset entity to update
            updates: Dictionary of field updates to apply

        Returns:
            Updated asset with refreshed timestamp

        Raises:
            ValueError: If validation fails after applying updates
            Exception: If persistence fails
        """
        ...

    @abstractmethod
    def delete(self, *, asset_id: str) -> bool:
        """Delete an asset from the repository.

        Args:
            asset_id: Unique identifier of the asset to delete

        Returns:
            True if asset was deleted, False if asset didn't exist

        Raises:
            Exception: If deletion fails
        """
        ...

    @abstractmethod
    def bulk_delete(self, *, asset_ids: list[str]) -> dict[str, Any]:
        """Delete multiple assets in a single batch operation.

        This method enables efficient bulk deletion at the repository level.
        - LocalAssetRepository: Batch file operations
        - CamsAssetRepository: Single CAMS bulk delete API call
        - DuckDBAssetRepository: Single SQL DELETE with IN clause

        Args:
            asset_ids: List of asset IDs to delete

        Returns:
            Dictionary with deletion results:
            {
                "total_requested": int,  # Number of IDs requested
                "total_deleted": int,    # Number successfully deleted
                "total_failed": int,     # Number that failed
                "deleted": list[str],    # List of deleted asset IDs
                "failed": list[dict]     # List of {asset_id, error} for failures
            }

        Raises:
            Exception: If bulk operation fails catastrophically
        """
        ...

    # ==================== Existence Checks ====================

    @abstractmethod
    def exists(self, *, asset_id: str) -> bool:
        """Check if an asset exists by ID.

        Args:
            asset_id: Unique identifier of the asset

        Returns:
            True if asset exists, False otherwise
        """
        ...

    @abstractmethod
    def exists_by_name(self, *, name: str) -> bool:
        """Check if an asset with the given name exists.

        Args:
            name: Name of the asset

        Returns:
            True if asset with this name exists, False otherwise
        """
        ...

    # ==================== Listing ====================

    @abstractmethod
    def list_all(self, *, limit: int | None = None, offset: int | None = None) -> list[T]:
        """Retrieve all assets with optional pagination, sorted newest-first.

        Args:
            limit: Maximum number of assets to return (None for all)
            offset: Number of assets to skip (None / 0 for none)

        Returns:
            List of assets sorted by creation date newest-first
        """
        ...

    # ==================== Utility Operations ====================

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Check the health of the repository connection.

        Returns:
            Dictionary with health status information
            {
                "status": "healthy" | "unhealthy",
                "message": "Optional message",
                "details": {...}  # Implementation-specific details
            }
        """
        ...
