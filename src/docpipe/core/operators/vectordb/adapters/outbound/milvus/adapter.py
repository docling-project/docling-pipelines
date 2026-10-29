# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Milvus adapter for vector database operations.

This adapter implements the VectorStorePort interface for Milvus.
"""

from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import register_vector_store
from docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor import MilvusBatchProcessor
from docpipe.core.operators.vectordb.adapters.outbound.milvus.client import MilvusClient
from docpipe.core.operators.vectordb.adapters.outbound.milvus.config import MilvusConfig
from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import MilvusIndexManager
from docpipe.core.operators.vectordb.ports.outbound.vector_store import VectorStorePort
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import (
    detect_all_vector_dimensions,
    detect_vector_dimension,
    generate_composite_pk,
)

logger = get_logger(__name__)

# Milvus adapter default values
DEFAULT_INDEX_TYPE = "HNSW"
DEFAULT_METRIC_TYPE = "L2"


@register_vector_store
class MilvusAdapter(VectorStorePort):
    """Adapter for Milvus vector database.

    This adapter wraps the Milvus components and provides a unified
    interface for vector database operations. It delegates to:
    - MilvusClient: Connection management
    - MilvusIndexManager: Collection operations
    - MilvusBatchProcessor: Bulk operations

    The adapter pattern allows the VectorDBOperator to work with Milvus
    without being tightly coupled to Milvus-specific implementation details.

    Supports both standalone Milvus and wx.data deployments.
    """

    ADAPTER_NAME = "milvus"
    ADAPTER_DISPLAY_NAME = "Milvus"

    def __init__(self, **adapter_config: Any) -> None:
        """Initialize Milvus adapter.

        All parameters are extracted from adapter_config, which is the provider_config
        dict passed directly from VectorDBOperator.

        Args:
            **adapter_config: Configuration dictionary (from provider_config) containing:
                Resource configuration:
                - collection_name: Name of the collection (required)
                - vector_dimension: Dimension of vector embeddings
                - embeddings_column: Name of embeddings column
                - available_features: Feature configuration
                - feature_mappings: Column to field mappings

                Connection and provider-specific parameters:
                - host: Milvus server host (default: localhost)
                - port: Milvus server port (default: 19530)
                - uri: Full URI for connection (for wx.data or cloud deployments)
                - token: API token for authentication (for wx.data)
                - username: Username for authentication (optional)
                - password: Password for authentication (optional)
                - database: Database name (default: "default")
                - ssl: Use SSL/TLS connection (optional)
                - ssl_certificate: SSL certificate path (optional)
                - batch_size: Batch size for bulk operations (default: 100)
                - index_type: Vector index algorithm (FLAT, IVF_FLAT, HNSW, etc.)
                - metric_type: Similarity metric (L2, IP, COSINE)
                - index_parameters: Index-specific parameters
        """
        # collection_name is now part of provider_config — read it from config
        self.collection_name = adapter_config.get(OperatorConstants.VectorDB.COLLECTION_NAME)
        if not self.collection_name:
            raise ValueError("collection_name is required for the Milvus adapter")
        self.embeddings_column = adapter_config.get(
            OperatorConstants.Columns.EMBEDDINGS_COLUMN, OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT
        )
        self.vector_dimension = adapter_config.get(
            OperatorConstants.VectorDB.VECTOR_DIMENSION, OperatorConstants.VectorDB.DEFAULT_VECTOR_DIMENSION
        )
        self.add_sparse_vector = adapter_config.get(
            OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, OperatorConstants.VectorDB.ADD_SPARSE_VECTOR_DEFAULT
        )
        available_features = adapter_config.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
        feature_mappings: list[dict[str, str]] = adapter_config.get(OperatorConstants.Config.FEATURE_MAPPINGS, [])

        self.primary_key_field = OperatorConstants.VectorDB.DEFAULT_PRIMARY_KEY_FIELD

        # Extract connection parameters from provider_config in adapter_config
        host = adapter_config.get(OperatorConstants.VectorDB.HOST, "localhost")
        port = adapter_config.get(OperatorConstants.VectorDB.PORT, 19530)
        uri = adapter_config.get(OperatorConstants.VectorDB.URI)
        token = adapter_config.get(OperatorConstants.VectorDB.TOKEN)
        username = adapter_config.get(OperatorConstants.VectorDB.USERNAME)
        password = adapter_config.get(OperatorConstants.VectorDB.PASSWORD)
        database = adapter_config.get(OperatorConstants.VectorDB.DATABASE, "default")
        auth_type = adapter_config.get(OperatorConstants.VectorDB.AUTH_TYPE)
        secure = adapter_config.get(OperatorConstants.VectorDB.SECURE, False)
        batch_size = adapter_config.get(OperatorConstants.Config.BATCH_SIZE, 100)
        is_lite: bool = auth_type == "lite"

        # Extract Milvus-specific parameters from provider_config in adapter_config
        index_type = adapter_config.get(OperatorConstants.VectorDB.INDEX_TYPE, DEFAULT_INDEX_TYPE)
        metric_type = adapter_config.get(OperatorConstants.VectorDB.METRIC_TYPE, DEFAULT_METRIC_TYPE)
        index_parameters = adapter_config.get(OperatorConstants.VectorDB.INDEX_PARAMETERS, {})

        # Note: Sparse vector mode uses hardcoded index configuration in MilvusIndexManager
        # The index_type and metric_type parameters here are only used for dense vectors
        if self.add_sparse_vector:
            logger.info("Sparse vector mode enabled: using hardcoded SPARSE_INVERTED_INDEX with BM25")

        # Initialize Milvus client
        self.client_manager = MilvusClient(
            host=host,
            port=port,
            uri=uri,
            token=token,
            username=username,
            password=password,
            database=database,
            auth_type=auth_type,
            secure=secure,
        )

        # Get the Milvus client
        client = self.client_manager.get_client()

        # Initialize index manager
        self.index_manager = MilvusIndexManager(
            client=client,
            collection_name=self.collection_name or "",
            index_type=index_type,
            metric_type=metric_type,
            index_parameters=index_parameters,
            available_features=available_features,
            feature_mappings=feature_mappings,
            primary_key_field=self.primary_key_field,
            auto_id=False,
            add_sparse_vector=self.add_sparse_vector,
            is_lite=is_lite,
        )

        # Initialize batch processor
        self.batch_processor = MilvusBatchProcessor(
            client=client,
            collection_name=self.collection_name or "",
            batch_size=batch_size,
            available_features=available_features,
            feature_mappings=feature_mappings,
            primary_key_field=self.primary_key_field,
            embeddings_column=self.embeddings_column,
            add_sparse_vector=self.add_sparse_vector,
        )

        logger.info(
            "Initialized MilvusAdapter for collection: %s (index: %s, metric: %s, lite: %s)",
            self.collection_name,
            index_type,
            metric_type,
            is_lite,
        )

    def close(self) -> None:
        """Close the underlying Milvus client connection and release any file locks."""
        self.client_manager.close()

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return MilvusConfig

    def index_documents(self, documents: list[tuple[str, dict[str, Any]]]) -> tuple[int, list[dict[str, Any]]]:
        """Index documents in Milvus.

        Args:
            documents: List of (doc_id, document_dict) tuples to index

        Returns:
            Tuple of (success_count, failed_items)
        """
        # Create batches
        batches = self.batch_processor.create_batches(documents=documents)

        # Process batches
        success_count, failed_items = self.batch_processor.process_batches(batches=batches)

        logger.debug("Indexed %s documents in %s batches, %s failed", success_count, len(batches), len(failed_items))

        return success_count, failed_items

    def query_by_doc_names(self, doc_names: list[str], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Query documents by their names.

        Args:
            doc_names: List of document names to query
            fields: Optional list of fields to return

        Returns:
            List of matching documents
        """
        return self.batch_processor.query_by_doc_names(doc_names=doc_names, fields=fields)

    def delete_documents_by_ids(self, doc_ids: list[str]) -> tuple[int, int]:
        """Delete documents by their IDs.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Tuple of (success_count, failed_count)
        """
        return self.batch_processor.delete_documents_by_ids(doc_ids=doc_ids)

    def get_document_count(self) -> int:
        """Get total document count in the collection.

        Returns:
            Number of documents in the collection
        """
        return self.batch_processor.get_document_count()

    def create_index(self, *, dimension_mapping: dict[str, int]) -> None:
        """Create the Milvus collection if it doesn't exist.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their dimensions
        """
        # Pass the full dimension_mapping to create_collection for multi-model support
        self.index_manager.create_collection(dimension_mapping=dimension_mapping)
        logger.info("Created collection: %s with dimension mapping: %s", self.collection_name, dimension_mapping)

    def refresh_index(self) -> None:
        """Refresh the collection to make recent changes visible.

        Note: Milvus automatically flushes data, but we can explicitly flush if needed.
        """
        try:
            # Milvus client flush is handled automatically, but we can call it explicitly
            # The MilvusClient doesn't expose a direct flush method in the simplified API
            # Data is automatically persisted
            logger.debug("Collection '%s' data is automatically persisted", self.collection_name)
        except Exception as e:
            logger.warning("Error during collection refresh: %s", e)

    def validate_existing_schema(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate existing Milvus collection schema against runtime vector dimensions."""
        self.index_manager.validate_existing_collection(dimension_mapping=dimension_mapping)

    def index_exists(self) -> bool:
        """Check if the Milvus collection already exists.

        Returns:
            True if collection exists, False otherwise
        """
        return self.index_manager.collection_exists()

    def detect_vector_dimension(self, *, table: pa.Table, column_name: str | None = None) -> int | None:
        """Detect vector dimension from embeddings data.

        Args:
            table: PyArrow table containing embeddings
            column_name: Name of the embeddings column to detect dimension for

        Returns:
            Detected dimension or None if detection fails
        """
        col_name = column_name if column_name is not None else self.embeddings_column
        return detect_vector_dimension(table=table, embeddings_column=col_name)

    def detect_all_vector_dimensions(self, table: pa.Table, *, vector_columns: list[str]) -> dict[str, int]:
        """Detect dimensions for all specified vector columns.

        Supports multi-model embeddings by detecting dimensions for all vector columns.

        Args:
            table: PyArrow table containing embeddings
            vector_columns: List of vector column names to detect dimensions for

        Returns:
            Dictionary mapping column names to their dimensions
        """
        return detect_all_vector_dimensions(table=table, vector_columns=vector_columns)

    def get_chunk_ids_for_documents(self, doc_ids: list[str]) -> dict[str, set[str]]:
        """Return all existing chunk PKs grouped by doc ID.

        Args:
            doc_ids: List of doc_id_hash values to look up.

        Returns:
            Mapping of doc_id -> set of chunk PKs.
        """
        return self.batch_processor.get_chunk_ids_for_documents(doc_ids=doc_ids)

    def resolve_source_chunks(self, *, doc_ids: list[str]) -> dict[str, set[str]]:
        """Resolve all chunks, propagating provider errors for retry-safe cleanup."""
        return self.batch_processor.resolve_source_chunks(doc_ids=doc_ids)

    def generate_chunk_pk(self, *, file_id: str, chunk_index: int, chunk_content: str) -> str:
        """Generate a content-hash composite primary key for this chunk.

        Older versions of Milvus do not support native upsert, so modified records
        must be deleted and re-inserted. By tying the PK to chunk content, any change
        to a chunk's text produces a new PK, which causes the stale record to be deleted
        during the cleanup pass and a fresh record to be inserted — effectively an upsert
        without requiring server-side upsert support.

        Args:
            file_id: The file identifier.
            chunk_index: Zero-based position of the chunk (unused by this strategy).
            chunk_content: The text content of the chunk.

        Returns:
            Composite PK string in the format ``{file_hash}_{content_hash}``.
        """
        return generate_composite_pk(file_id=file_id, chunk_content=chunk_content)
