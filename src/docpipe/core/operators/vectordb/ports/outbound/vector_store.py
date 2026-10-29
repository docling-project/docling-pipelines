# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port interface for vector database services.

This port defines the contract that all vector database adapters must implement.
"""

from abc import ABC, abstractmethod
from typing import Any

import pyarrow as pa
from pydantic import BaseModel


class VectorStorePort(ABC):
    """Port interface for vector database services.

    This interface defines the contract for vector database operations.
    Adapters implementing this port handle provider-specific details while
    the operator depends only on this abstraction.

    Attributes:
        ADAPTER_NAME: Unique identifier for the adapter (e.g., 'opensearch')
        ADAPTER_DISPLAY_NAME: Human-readable name for UI display
    """

    ADAPTER_NAME: str
    ADAPTER_DISPLAY_NAME: str

    def resolve_source_chunks(self, *, doc_ids: list[str]) -> dict[str, set[str]]:
        """Strict, complete source-ID lookup; errors must never mean successful absence."""
        raise NotImplementedError("Vector adapter does not support authoritative source cleanup")

    @staticmethod
    @abstractmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        ...

    @abstractmethod
    def index_documents(self, documents: list[tuple[str, dict[str, Any]]]) -> tuple[int, list[dict[str, Any]]]:
        """Index documents in the vector database.

        Args:
            documents: List of (doc_id, document_dict) tuples to index

        Returns:
            Tuple of (success_count, failed_items)

        Raises:
            Exception: If indexing operation fails
        """
        ...

    @abstractmethod
    def query_by_doc_names(self, doc_names: list[str], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Query documents by their names.

        Args:
            doc_names: List of document names to query
            fields: Optional list of fields to return

        Returns:
            List of matching documents

        Raises:
            Exception: If query operation fails
        """
        ...

    @abstractmethod
    def delete_documents_by_ids(self, doc_ids: list[str]) -> tuple[int, int]:
        """Delete documents by their IDs.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Tuple of (success_count, failed_count)

        Raises:
            Exception: If delete operation fails
        """
        ...

    @abstractmethod
    def get_document_count(self) -> int:
        """Get total document count in the index.

        Returns:
            Number of documents in the index

        Raises:
            Exception: If count operation fails
        """
        ...

    @abstractmethod
    def create_index(self, *, dimension_mapping: dict[str, int]) -> None:
        """Create the vector database index if it doesn't exist.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their dimensions

        Raises:
            Exception: If index creation fails
        """
        ...

    @abstractmethod
    def refresh_index(self) -> None:
        """Refresh the index to make recent changes visible.

        Raises:
            Exception: If refresh operation fails
        """
        ...

    @abstractmethod
    def validate_existing_schema(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate an existing vector store schema against runtime vector dimensions.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their runtime dimensions

        Raises:
            Exception: If the existing schema is incompatible with the current run
        """
        ...

    @abstractmethod
    def index_exists(self) -> bool:
        """Check if the vector database index already exists.

        Returns:
            True if index exists, False otherwise
        """
        ...

    @abstractmethod
    def detect_vector_dimension(self, *, table: pa.Table, column_name: str | None = None) -> int | None:
        """Detect vector dimension from embeddings data.

        Args:
            table: PyArrow table containing embeddings
            column_name: Optional specific column to detect dimension for.
                        If None, uses default embeddings column.

        Returns:
            Detected dimension or None if detection fails
        """
        ...

    @abstractmethod
    def detect_all_vector_dimensions(self, table: pa.Table, *, vector_columns: list[str]) -> dict[str, int]:
        """Detect dimensions for all specified vector columns.

        Args:
            table: PyArrow table containing embeddings
            vector_columns: List of column names to detect dimensions for

        Returns:
            Dictionary mapping column names to their detected dimensions
        """
        ...

    def close(self) -> None:
        """Release any resources held by the adapter (connections, file locks).

        Called by the operator after transform completes or on failure.
        Adapters that hold persistent connections or file locks must override this.
        The default implementation is a no-op so existing adapters are unaffected.
        """

    @abstractmethod
    def get_chunk_ids_for_documents(self, doc_ids: list[str]) -> dict[str, set[str]]:
        """Return all existing chunk PKs for the given document IDs.

        Queries the vector store for every chunk currently indexed under each
        of the supplied doc IDs and groups the PKs by their parent doc ID.
        Used by the operator to compute stale PKs before a new insert.

        Args:
            doc_ids: List of document IDs (values of the doc_id_hash column)
                     to look up.

        Returns:
            Mapping of doc_id -> set of existing chunk PKs currently in the
            store for that document. Doc IDs with no indexed chunks are omitted.
        """
        ...

    @abstractmethod
    def generate_chunk_pk(self, *, file_id: str, chunk_index: int, chunk_content: str) -> str:
        """Generate a stable primary key for a chunk of this document.

        Adapters choose the strategy: positional (OpenSearch) or content-hash (Milvus).

        Args:
            file_id: The file identifier (e.g. file path from the id column).
            chunk_index: Zero-based position of the chunk within the document.
            chunk_content: The text content of the chunk.

        Returns:
            A stable string primary key for the chunk.
        """
        ...
