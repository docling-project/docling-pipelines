"""OpenSearch adapter for vector database operations.

This adapter implements the VectorStorePort interface.
"""

from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import register_vector_store
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor import OpenSearchBatchProcessor
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.client import OpenSearchClient
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.config import OpenSearchConfig
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.index_manager import OpenSearchIndexManager
from docpipe.core.operators.vectordb.ports.outbound.vector_store import VectorStorePort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import (
    detect_all_vector_dimensions,
    detect_vector_dimension,
    generate_positional_pk,
    is_binary_vector_feature,
)

logger = get_logger(__name__)

# OpenSearch adapter default values
DEFAULT_ENGINE = "faiss"
DEFAULT_ALGORITHM = "hnsw"
DEFAULT_SPACE_TYPE = "l2"


@register_vector_store
class OpenSearchAdapter(VectorStorePort):
    """Adapter for OpenSearch vector database.

    This adapter wraps the existing OpenSearch components and provides a unified
    interface for vector database operations. It delegates to:
    - OpenSearchClient: Connection management
    - OpenSearchIndexManager: Index operations
    - OpenSearchBatchProcessor: Bulk operations

    The adapter pattern allows the VectorDBOperator to work with OpenSearch
    without being tightly coupled to OpenSearch-specific implementation details.
    """

    ADAPTER_NAME = "opensearch"
    ADAPTER_DISPLAY_NAME = "OpenSearch"

    def __init__(self, **adapter_config: Any) -> None:
        """Initialize OpenSearch adapter.

        All parameters are extracted from adapter_config, which is the provider_config
        dict passed directly from VectorDBOperator.

        Args:
            **adapter_config: Configuration dictionary (from provider_config) containing:
                Resource configuration:
                - index_name: Name of the index (required)
                - vector_dimension: Dimension of vector embeddings
                - embeddings_column: Name of embeddings column
                - available_features: Feature configuration
                - feature_mappings: Column to field mappings

                Connection and provider-specific parameters:
                - host: OpenSearch server host (default: localhost)
                - port: OpenSearch server port (default: 9200)
                - username: Username for basic authentication (optional)
                - password: Password for basic authentication (optional)
                - use_ssl: Use SSL connection (default: True)
                - verify_certs: Verify SSL certificates (default: True)
                - batch_size: Batch size for bulk operations (default: 100)
                - engine: KNN engine type (faiss, lucene, nmslib, jvector)
                - algorithm: KNN algorithm type (hnsw, ivf)
                - space_type: Vector similarity metric (l2, cosine, inner_product)
                - engine_parameters: Engine-specific parameters
                - index_settings: Index settings
                - aws_auth: Use AWS IAM authentication
                - aws_region: AWS region for authentication
                - jwt_token: JWT token for authentication
        """
        # Extract operator-level parameters (added by VectorDBOperator)
        self.index_name = adapter_config.get(OperatorConstants.VectorDB.INDEX_NAME)
        if not self.index_name:
            raise ValueError("index_name is required for the OpenSearch adapter")
        available_features = adapter_config.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
        feature_mappings: list[dict[str, str]] = adapter_config.get(OperatorConstants.Config.FEATURE_MAPPINGS, [])

        # Extract connection parameters from adapter_config (from provider_config)
        host = adapter_config.get(OperatorConstants.VectorDB.HOST, "localhost")
        port = adapter_config.get(OperatorConstants.VectorDB.PORT, 9200)
        username = resolve_env_var(adapter_config.get(OperatorConstants.VectorDB.USERNAME))
        password = resolve_env_var(adapter_config.get(OperatorConstants.VectorDB.PASSWORD))
        use_ssl = adapter_config.get(OperatorConstants.VectorDB.USE_SSL, True)
        verify_certs = adapter_config.get(OperatorConstants.VectorDB.VERIFY_CERTS, True)
        batch_size = adapter_config.get(OperatorConstants.Config.BATCH_SIZE, 100)

        # Extract OpenSearch-specific parameters from adapter_config (from provider_config)
        engine = adapter_config.get(OperatorConstants.VectorDB.ENGINE, DEFAULT_ENGINE)
        algorithm = adapter_config.get(OperatorConstants.VectorDB.ALGORITHM, DEFAULT_ALGORITHM)
        space_type = adapter_config.get(OperatorConstants.VectorDB.SPACE_TYPE, DEFAULT_SPACE_TYPE)
        engine_parameters = adapter_config.get(OperatorConstants.VectorDB.ENGINE_PARAMETERS)
        index_settings = adapter_config.get(OperatorConstants.VectorDB.INDEX_SETTINGS)
        schema_template_path = adapter_config.get("schema_template_path")
        aws_auth = adapter_config.get(OperatorConstants.VectorDB.AWS_AUTH, False)
        aws_region = adapter_config.get(OperatorConstants.VectorDB.AWS_REGION)
        jwt_token = adapter_config.get(OperatorConstants.VectorDB.JWT_TOKEN)

        # Initialize OpenSearch client
        self.client_manager = OpenSearchClient(
            host=host,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            aws_auth=aws_auth,
            aws_region=aws_region,
            jwt_token=jwt_token,
        )

        # Get the OpenSearch client
        client = self.client_manager.get_client()

        # Initialize index manager
        self.index_manager = OpenSearchIndexManager(
            client=client,
            index_name=self.index_name or "",
            engine=engine,
            algorithm=algorithm,
            space_type=space_type,
            engine_parameters=engine_parameters or {},
            index_settings=index_settings,
            available_features=available_features,
            feature_mappings=feature_mappings,
            schema_template_path=schema_template_path,
        )

        # Initialize batch processor
        self.batch_processor = OpenSearchBatchProcessor(
            client=client,
            index_name=self.index_name or "",
            batch_size=batch_size,
            available_features=available_features,
            feature_mappings=feature_mappings,
        )

        logger.info(
            "Initialized OpenSearchAdapter for index: %s (host: %s:%s, engine: %s, algorithm: %s)",
            self.index_name,
            host,
            port,
            engine,
            algorithm,
        )

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return OpenSearchConfig

    def index_documents(self, documents: list[tuple[str, dict[str, Any]]]) -> tuple[int, list[dict[str, Any]]]:
        """Index documents in OpenSearch.

        Args:
            documents: List of (doc_id, document_dict) tuples to index

        Returns:
            Tuple of (success_count, failed_items)
        """
        # Create batches
        batches = self.batch_processor.create_batches(documents)

        # Process batches
        success_count, failed_items = self.batch_processor.process_batches(batches)

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
        return self.batch_processor.query_by_doc_names(doc_names, fields)

    def delete_documents_by_ids(self, doc_ids: list[str]) -> tuple[int, int]:
        """Delete documents by their IDs.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Tuple of (success_count, failed_count)
        """
        return self.batch_processor.delete_documents_by_ids(doc_ids)

    def get_document_count(self) -> int:
        """Get total document count in the index.

        Returns:
            Number of documents in the index
        """
        return self.batch_processor.get_document_count()

    def create_index(self, *, dimension_mapping: dict[str, int]) -> None:
        """Create the OpenSearch index if it doesn't exist.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their dimensions
        """
        self.index_manager.create_index(dimension_mapping=dimension_mapping)
        logger.info("Created index: %s with dimension mapping: %s", self.index_name, dimension_mapping)

    def refresh_index(self) -> None:
        """Refresh the index to make recent changes visible."""
        self.index_manager.refresh_index()

    def validate_existing_schema(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate existing OpenSearch index schema against runtime vector dimensions."""
        self.index_manager.validate_existing_index(dimension_mapping=dimension_mapping)

    def validate_vector_feature_types(self, *, feature_types: dict[str, str | None]) -> None:
        """Reject binary vector features, which the OpenSearch adapter cannot index.

        Args:
            feature_types: Mapping of input feature name to its propagated feature type.

        Raises:
            DocpipeException: An upstream operator emits a binary vector feature.
        """
        binary_features = sorted(
            name for name, ftype in feature_types.items() if is_binary_vector_feature(feature_config={"type": ftype})
        )
        if binary_features:
            raise DocpipeException(
                message=(
                    f"OpenSearch Error: Binary vector features are not supported (found: {', '.join(binary_features)}). "
                    "Remove 'quantization' from the embeddings operator or use a provider that supports binary vectors "
                    "(e.g. Milvus)."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

    def index_exists(self) -> bool:
        """Check if the OpenSearch index exists.

        Returns:
            True if index exists, False otherwise
        """
        return self.index_manager.index_exists()

    def detect_vector_dimension(self, *, table: pa.Table, column_name: str | None = None) -> int | None:
        """Detect vector dimension from embeddings data.

        Args:
            table: PyArrow table containing embeddings
            column_name: Optional specific column to detect dimension for

        Returns:
            Detected dimension or None if detection fails
        """
        if column_name is None:
            raise ValueError("column_name parameter is required for detect_vector_dimension")
        return detect_vector_dimension(table=table, embeddings_column=column_name)

    def detect_all_vector_dimensions(self, table: pa.Table, *, vector_columns: list[str]) -> dict[str, int]:
        """Detect dimensions for all specified vector columns.

        Args:
            table: PyArrow table containing embeddings
            vector_columns: List of column names to detect dimensions for

        Returns:
            Dictionary mapping column names to their detected dimensions
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

    def generate_chunk_pk(self, *, file_id: str, chunk_index: int, chunk_content: str) -> str:
        """Generate a positional primary key for this chunk.

        OpenSearch uses positional PKs so the same chunk position always maps
        to the same document, enabling native in-place upserts on re-ingest.

        Args:
            file_id: The file identifier.
            chunk_index: Zero-based position of the chunk within the document.
            chunk_content: The text content of the chunk (unused by this strategy).

        Returns:
            Positional PK string in the format ``{file_hash}_chunk_{chunk_index}``.
        """
        return generate_positional_pk(file_id=file_id, chunk_index=chunk_index)
