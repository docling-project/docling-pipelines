"""Type definitions for document set domain.

This module defines TypedDict classes for type-safe configuration and responses
used throughout the document set domain layer.
"""

from typing import Any, TypedDict


class HealthCheckResult(TypedDict):
    """Health check result for repository and data store components.

    Attributes:
        healthy: Whether the component is healthy and operational
        message: Human-readable status message
        details: Optional additional details about the health status
    """

    healthy: bool
    message: str
    details: dict[str, Any] | None


class DataStoreConfig(TypedDict, total=False):
    """Configuration for data store adapters.

    Attributes:
        storage_path: Path to the storage directory or database file (deprecated, use database_path)
        database_path: Path to the database file (preferred for DuckDB and similar adapters)
        connection_string: Connection string for remote data stores
        timeout: Connection timeout in seconds
        pool_size: Connection pool size for database connections
        compression: Compression algorithm to use (e.g., 'zstd', 'gzip')
        additional_params: Additional adapter-specific parameters
    """

    storage_path: str
    database_path: str
    connection_string: str
    timeout: int
    pool_size: int
    compression: str
    additional_params: dict[str, Any]
