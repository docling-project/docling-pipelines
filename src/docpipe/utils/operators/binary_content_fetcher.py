"""Utility functions for fetching binary content from documents on-demand.

This module provides functions to fetch binary content on-demand, supporting both:
1. Cloud sources (S3, SharePoint, Google Drive, etc.) via source adapters
2. Local filesystem sources

The on-demand fetching strategy allows operators to defer binary content fetching until
it's actually needed, reducing memory usage and improving performance.

Adapter instances are cached at module level keyed by provider name so that a single
authenticated client is reused across all documents in a batch, avoiding a new auth
round-trip per document.
"""

from pathlib import Path
from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (
    SourceAdapterFactory,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.archive import read_archive_uri
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Module-level cache: provider name → adapter instance.
# Adapter instances hold their own per-session auth caches (tokens, Drive services,
# Box clients) so reusing them across documents eliminates repeated auth round-trips.
_adapter_cache: dict[str, DocumentSourcePort] = {}


def get_binary_content(
    *,
    doc_metadata: dict[str, Any],
    global_config: dict[str, Any],
) -> bytes | None:
    """
    Fetch binary content for a document using on-demand fetching strategy.

    This function determines whether to fetch content from a cloud source (using adapters)
    or from the local filesystem, based on the presence of ingest_source configuration.

    Strategy:
    1. If global_config contains ingest_source: Use cloud provider adapter to fetch on-demand
    2. Otherwise: Read from local file path

    Args:
        doc_metadata: Document metadata containing 'path', 'source_id', 'source', etc.
            Expected keys:
            - 'path': Local file path (for filesystem sources)
            - 'source_id': Source identifier (for cloud sources)
            - 'source': Source URL or path
        global_config: Global configuration that may contain ingest_source parameters
            Expected structure (if present):
            {
                OperatorConstants.Config.INGEST_SOURCE: {
                    OperatorConstants.Config.PROVIDER: "s3",  # or "sharepoint", "google_drive", etc.
                    OperatorConstants.Config.PROVIDER_CONFIG: {...}
                }
            }

    Returns:
        Binary content as bytes, or None if unavailable or error occurred

    Examples:
        >>> # Cloud source (S3)
        >>> config = {
        ...     OperatorConstants.Config.INGEST_SOURCE: {
        ...         OperatorConstants.Config.PROVIDER: "s3",
        ...         OperatorConstants.Config.PROVIDER_CONFIG: {
        ...             "bucket": "my-bucket",
        ...             "prefix": "docs/",
        ...             "access_key": "...",
        ...             "secret_key": "..."
        ...         }
        ...     }
        ... }
        >>> metadata = {"source_id": "docs/file.pdf", "name": "file.pdf"}
        >>> content = get_binary_content(doc_metadata=metadata, global_config=config)

        >>> # Local filesystem
        >>> metadata = {"path": "/path/to/file.pdf"}
        >>> content = get_binary_content(doc_metadata=metadata, global_config={})
    """
    # Check if ingest_source configuration exists
    ingest_source = global_config.get(OperatorConstants.Config.INGEST_SOURCE)

    doc_name = doc_metadata.get("name") or doc_metadata.get("source_id") or doc_metadata.get("path", "unknown")
    logger.debug(
        "get_binary_content called for '%s': ingest_source_present=%s",
        doc_name,
        ingest_source is not None,
    )

    if ingest_source:
        logger.debug(
            "Using cloud source adapter for '%s', provider=%s",
            doc_name,
            ingest_source.get(OperatorConstants.Config.PROVIDER),
        )
        return _fetch_from_cloud_source(
            doc_metadata=doc_metadata,
            ingest_source=ingest_source,
        )
    logger.debug("Using local filesystem for '%s'", doc_name)
    return _read_from_local_file(doc_metadata=doc_metadata)


def get_adapter_for_provider(
    *,
    provider: str,
) -> DocumentSourcePort | None:
    """
    Create source adapter instance for the given provider.

    This function uses the SourceAdapterFactory to instantiate the appropriate
    adapter based on the provider name. The adapter can then be used to fetch
    binary content from the cloud source.

    Args:
        provider: Provider name (e.g., "s3", "sharepoint", "google_drive", "onedrive", "box", "web")

    Returns:
        Adapter instance for fetching binary content, or None if provider not found

    Raises:
        ValueError: If provider is not registered or configuration is invalid
    """
    try:
        if not SourceAdapterFactory.is_registered(provider):
            available = ", ".join(SourceAdapterFactory.get_registered_names())
            logger.error("Provider '%s' is not registered. Available providers: %s", provider, available)
            return None

        return SourceAdapterFactory.create(provider)

    except Exception as e:
        logger.exception("Failed to create adapter for provider '%s': %s", provider, e)
        return None


def _fetch_from_cloud_source(
    *,
    doc_metadata: dict[str, Any],
    ingest_source: dict[str, Any],
) -> bytes | None:
    """
    Fetch binary content from cloud source using dynamic adapter lookup.

    This function uses the SourceAdapterFactory to get the appropriate adapter
    and calls its fetch_binary_content() method to download the file.

    Args:
        doc_metadata: Document metadata with source_id or path
        ingest_source: Ingest source configuration with provider and provider_config

    Returns:
        Binary content as bytes, or None if not found or error occurred
    """
    from docpipe.core.operators.operator_utils import resolve_env_var

    provider = ingest_source.get(OperatorConstants.Config.PROVIDER)
    provider_config: dict[str, Any] = dict(ingest_source.get(OperatorConstants.Config.PROVIDER_CONFIG) or {})

    if not provider:
        logger.error("Missing '%s' in ingest_source configuration", OperatorConstants.Config.PROVIDER)
        return None

    # Get source identifier
    source_id = doc_metadata.get("source_id") or doc_metadata.get("source") or doc_metadata.get("path")
    if not source_id:
        logger.error("Document metadata missing 'source_id', 'source', or 'path'")
        return None

    # Resolve environment variables in provider_config values
    resolved_provider_config: dict[str, Any] = {}
    for key, value in provider_config.items():
        resolved_provider_config[key] = resolve_env_var(value) if isinstance(value, str) else value

    # For OneDrive/SharePoint: inject item_id and drive_id from document metadata
    # so the adapter can use the correct drive and item IDs when source_id is a web URL.
    if "item_id" in doc_metadata:
        resolved_provider_config["item_id"] = doc_metadata["item_id"]
        logger.debug("Injected item_id into provider_config: %s", doc_metadata["item_id"])
    if "drive_id" in doc_metadata:
        resolved_provider_config["drive_id"] = doc_metadata["drive_id"]
        logger.debug("Injected drive_id into provider_config: %s", doc_metadata["drive_id"])
    else:
        logger.debug("drive_id not found in doc_metadata. Available keys: %s", list(doc_metadata.keys()))

    if not SourceAdapterFactory.is_registered(provider):
        logger.error("No adapter registered for provider: %s", provider)
        return None

    # Reuse cached adapter instance so its internal auth caches (tokens, Drive
    # services, Box clients) persist across all documents in a batch.
    if provider not in _adapter_cache:
        _adapter_cache[provider] = SourceAdapterFactory.create(provider)
    adapter = _adapter_cache[provider]

    # Let exceptions propagate so callers can record the real error reason.
    return adapter.fetch_binary_content(
        source_id=source_id,
        provider_config=resolved_provider_config,
    )


def _read_from_local_file(
    *,
    doc_metadata: dict[str, Any],
) -> bytes | None:
    """
    Read binary content from local filesystem.

    This is an internal helper function that handles local file reading,
    matching the existing IngestSource filesystem behavior.

    Args:
        doc_metadata: Document metadata containing 'path' or 'source' key

    Returns:
        Binary content as bytes, or None if file not found or error occurred
    """
    from urllib.parse import unquote, urlparse

    # Try to get file path from various metadata fields
    file_path = doc_metadata.get("path") or doc_metadata.get("source") or doc_metadata.get("source_id")

    if not file_path:
        raise ValueError("Document metadata missing 'path', 'source', or 'source_id' for local file reading")

    if isinstance(file_path, str) and file_path.startswith("zip://"):
        return read_archive_uri(file_path)

    # Parse file:// URLs to extract actual path
    if isinstance(file_path, str) and file_path.startswith("file://"):
        parsed = urlparse(file_path)
        file_path = unquote(parsed.path)

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Local file not found: {file_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")

    # Read binary content — let OS errors (PermissionError, etc.) propagate
    with Path(path).open("rb") as f:
        return f.read()
