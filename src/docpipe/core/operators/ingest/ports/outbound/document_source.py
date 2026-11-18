"""Document source port - Interface for fetching documents from external sources."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from docpipe.core.operators.ingest.domain.models import Document

SourceConfig = TypeVar("SourceConfig", bound=BaseModel)


class DocumentSourcePort(ABC, Generic[SourceConfig]):  # noqa: UP046
    """
    Outbound port for document sources.

    This is the primary interface that all document source adapters must implement.
    It defines the contract between the domain layer and external document sources.

    Following Hexagonal Architecture principles:
    - This port is defined in the domain layer
    - Adapters implement this interface
    - The domain depends on this abstraction, not on concrete implementations
    """

    # Metadata for connector discovery and UI display
    SOURCE_NAME: str | None = None  # Unique identifier (e.g., "filesystem", "s3", "google_drive", "web")
    SOURCE_DISPLAY_NAME: str | None = None  # Human-readable name (e.g., "Local Filesystem")
    SOURCE_DESCRIPTION: str | None = None  # Brief description
    SOURCE_VERSION: str = "1.0.0"  # Semantic version

    @classmethod
    def bind_file_reference(cls, *, provider_config: dict[str, Any], file_reference: str) -> None:
        """Update provider settings for a file event, or reject unsupported providers."""
        raise NotImplementedError(f"Source adapter '{cls.SOURCE_NAME or cls.__name__}' does not support file events")

    @abstractmethod
    async def fetch_documents(self, config: Any) -> AsyncGenerator[Document, None]:
        """
        Fetch documents from the source.

        Args:
            config: Type-safe configuration (Pydantic model specific to this source)

        Yields:
            Document: Domain documents one at a time

        Raises:
            ConnectionError: If unable to connect to source
            AuthenticationError: If authentication fails
            ValueError: If configuration is invalid
        """
        ...

    @abstractmethod
    async def test_connection(self, config: SourceConfig) -> tuple[bool, str]:
        """
        Test connection to the document source.

        Args:
            config: Type-safe configuration (Pydantic model specific to this source)

        Returns:
            Tuple[bool, str]: (success, message)
                - success: True if connection successful, False otherwise
                - message: Human-readable status message
        """
        ...

    @abstractmethod
    def get_config_schema(self) -> type[BaseModel]:
        """
        Get the Pydantic configuration model for this source.

        Returns:
            type[BaseModel]: The Pydantic model class for configuration
        """
        ...

    @abstractmethod
    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> SourceConfig:
        """
        Build adapter-specific configuration from operator parameters.

        This method allows each adapter to define how to map operator parameters
        to its specific configuration model, following the Open/Closed Principle.

        Args:
            provider_config: All provider-specific parameters including credentials.
            included_extensions: File extensions to include (optional)
            max_files: Maximum number of files to fetch (optional)

        Returns:
            BaseModel: Adapter-specific configuration object (Pydantic model)

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        ...

    @abstractmethod
    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific document on-demand.

        This method enables lazy loading of document content by fetching
        the actual binary data only when needed, rather than during initial
        document discovery.

        Args:
            source_id: Unique identifier for the document in the source system
                      (e.g., S3 key, file path, document ID)
            provider_config: All provider-specific parameters including credentials.

        Returns:
            bytes | None: Binary content of the document, or None if:
                - Document not found
                - Access denied
                - Download failed
                - Provider doesn't support binary fetching

        Raises:
            ConnectionError: If unable to connect to source
            AuthenticationError: If authentication fails
            ValueError: If source_id is invalid or missing
        """
        ...

    def get_metadata(self) -> dict:
        """
        Get metadata about this source for discovery and UI purposes.

        Returns:
            dict: Metadata including name, display name, description, version
        """
        return {
            "name": self.SOURCE_NAME,
            "display_name": self.SOURCE_DISPLAY_NAME,
            "description": self.SOURCE_DESCRIPTION,
            "version": self.SOURCE_VERSION,
            "config_schema": self.get_config_schema().schema() if self.get_config_schema() else None,
        }
