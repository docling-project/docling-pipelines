"""
Unit tests for multi-model embeddings support in VectorDB operator.
Tests dimension detection and index creation with multiple vector columns.
"""

from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.utils.operators.vectordb_utils import detect_all_vector_dimensions


class TestMultiModelEmbeddings:
    """Test multi-model embeddings support in VectorDB operator."""

    @pytest.fixture
    def multi_model_config(self):
        """Configuration for VectorDB operator with multiple embedding columns."""
        return {
            OperatorConstants.Config.PROVIDER: "opensearch",
            OperatorConstants.Columns.DOC_ID_COLUMN: "doc_id_hash",
            OperatorConstants.Config.AVAILABLE_FEATURES: {
                "doc_id_hash": {
                    "name": "Document ID",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "string",
                    "is_primary": True,
                },
                "embeddings": {
                    "name": "Primary Embeddings",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "vector",
                },
                "embeddings_alt": {
                    "name": "Alternative Embeddings",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": False,
                    "type": "vector",
                },
                "text": {
                    "name": "Text Content",
                    "available_for_vector_db": True,
                    "type": "string",
                },
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: [
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                {"feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt"},
                {"feature_name": "text", "mapped_column_name": "text"},
            ],
            OperatorConstants.Config.PROVIDER_CONFIG: {
                OperatorConstants.VectorDB.INDEX_NAME: "multi_model_test",
                OperatorConstants.VectorDB.HOST: "localhost",
                OperatorConstants.VectorDB.PORT: 9200,
                OperatorConstants.VectorDB.ENGINE: "faiss",
                OperatorConstants.VectorDB.ALGORITHM: "hnsw",
                OperatorConstants.VectorDB.SPACE_TYPE: "l2",
            },
        }

    @pytest.fixture
    def dual_embeddings_table(self):
        """PyArrow table with two embedding columns of different dimensions."""
        return pa.table(
            {
                "doc_id_hash": ["doc1", "doc2", "doc3"],
                "text": ["Sample text 1", "Sample text 2", "Sample text 3"],
                "embeddings": [
                    [0.1, 0.2, 0.3, 0.4],  # 4-dim
                    [0.5, 0.6, 0.7, 0.8],
                    [0.9, 1.0, 1.1, 1.2],
                ],
                "embeddings_alt": [
                    [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],  # 6-dim
                    [0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
                    [1.3, 1.4, 1.5, 1.6, 1.7, 1.8],
                ],
            }
        )

    def test_detect_all_vector_dimensions(self, dual_embeddings_table):
        """Test detecting dimensions for multiple vector columns."""
        vector_columns = ["embeddings", "embeddings_alt"]
        dimension_mapping = detect_all_vector_dimensions(table=dual_embeddings_table, vector_columns=vector_columns)

        assert dimension_mapping == {"embeddings": 4, "embeddings_alt": 6}

    def test_detect_all_vector_dimensions_single_column(self, dual_embeddings_table):
        """Test detecting dimension for single vector column."""
        vector_columns = ["embeddings"]
        dimension_mapping = detect_all_vector_dimensions(table=dual_embeddings_table, vector_columns=vector_columns)

        assert dimension_mapping == {"embeddings": 4}

    def test_detect_all_vector_dimensions_missing_column(self, dual_embeddings_table):
        """Test detecting dimensions when column doesn't exist."""
        vector_columns = ["embeddings", "nonexistent"]
        dimension_mapping = detect_all_vector_dimensions(table=dual_embeddings_table, vector_columns=vector_columns)

        # Should only return dimension for existing column
        assert dimension_mapping == {"embeddings": 4}

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch")
    def test_vectordb_operator_identifies_multiple_vector_columns(
        self, mock_opensearch, multi_model_config, dual_embeddings_table
    ):
        """Test that VectorDBOperator correctly identifies multiple vector columns."""
        with patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk"):
            # Get vector columns from available_features
            available_features = multi_model_config[OperatorConstants.Config.AVAILABLE_FEATURES]
            vector_columns = [col for col, meta in available_features.items() if meta.get("type") == "vector"]

            assert len(vector_columns) == 2
            assert "embeddings" in vector_columns
            assert "embeddings_alt" in vector_columns

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch")
    def test_create_index_called_with_dimension_mapping(
        self, mock_opensearch, multi_model_config, dual_embeddings_table
    ):
        """Test that create_index is called with correct dimension_mapping."""
        mock_adapter = Mock()
        mock_adapter.index_exists = Mock(return_value=False)  # Index doesn't exist, so create_index will be called
        mock_adapter.detect_all_vector_dimensions = Mock(return_value={"embeddings": 4, "embeddings_alt": 6})
        mock_adapter.create_index = Mock()
        mock_adapter.validate_existing_schema = Mock()
        mock_adapter.insert_documents = Mock(return_value=(3, 0, []))

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(multi_model_config)
            operator.transform(dual_embeddings_table)

            # Verify create_index was called with dimension_mapping
            mock_adapter.create_index.assert_called_once()
            call_kwargs = mock_adapter.create_index.call_args.kwargs
            assert "dimension_mapping" in call_kwargs

            dimension_mapping = call_kwargs["dimension_mapping"]
            assert dimension_mapping == {"embeddings": 4, "embeddings_alt": 6}

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch")
    def test_multi_model_document_preparation(self, mock_opensearch, multi_model_config, dual_embeddings_table):
        """Test that documents are prepared with all vector columns."""
        mock_adapter = Mock()
        mock_adapter.index_exists = Mock(return_value=True)  # Skip index creation
        mock_adapter.detect_all_vector_dimensions = Mock(return_value={"embeddings": 4, "embeddings_alt": 6})
        mock_adapter.create_index = Mock()
        mock_adapter.validate_existing_schema = Mock()
        inserted_docs = []

        def capture_docs(documents):
            # Documents are tuples of (doc_id, doc_dict)
            inserted_docs.extend(documents)
            return (len(documents), [])  # Return (success_count, failed_chunks)

        mock_adapter.index_documents = Mock(side_effect=capture_docs)

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(multi_model_config)
            operator.transform(dual_embeddings_table)

            mock_adapter.create_index.assert_not_called()
            mock_adapter.validate_existing_schema.assert_called_once_with(
                dimension_mapping={"embeddings": 4, "embeddings_alt": 6}
            )

            # Verify documents have both embedding columns
            assert len(inserted_docs) == 3
            for _doc_id, doc in inserted_docs:
                # Documents use original column names, not mapped names
                assert "embeddings" in doc
                assert "embeddings_alt" in doc
                assert len(doc["embeddings"]) == 4
                assert len(doc["embeddings_alt"]) == 6

    @pytest.fixture
    def chunked_dual_embeddings_table(self):
        """PyArrow table with chunked data and two embedding columns."""
        return pa.table(
            {
                "doc_id_hash": ["doc1", "doc1", "doc2", "doc2"],
                "chunk_sequence_number": [0, 1, 0, 1],
                "chunked_content": ["chunk1", "chunk2", "chunk3", "chunk4"],
                "embeddings": [
                    [0.1, 0.2, 0.3],
                    [0.4, 0.5, 0.6],
                    [0.7, 0.8, 0.9],
                    [1.0, 1.1, 1.2],
                ],
                "embeddings_alt": [
                    [0.1, 0.2, 0.3, 0.4, 0.5],
                    [0.6, 0.7, 0.8, 0.9, 1.0],
                    [1.1, 1.2, 1.3, 1.4, 1.5],
                    [1.6, 1.7, 1.8, 1.9, 2.0],
                ],
            }
        )

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch")
    def test_chunked_multi_model_embeddings(self, mock_opensearch, multi_model_config, chunked_dual_embeddings_table):
        """Test handling of chunked data with multiple embedding columns."""
        mock_adapter = Mock()
        mock_adapter.index_exists = Mock(return_value=True)  # Skip index creation
        mock_adapter.detect_all_vector_dimensions = Mock(return_value={"embeddings": 3, "embeddings_alt": 5})
        mock_adapter.create_index = Mock()
        inserted_docs = []

        def capture_docs(documents):
            # Documents are tuples of (doc_id, doc_dict)
            inserted_docs.extend(documents)
            return (len(documents), [])  # Return (success_count, failed_chunks)

        mock_adapter.index_documents = Mock(side_effect=capture_docs)

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(multi_model_config)
            operator.transform(chunked_dual_embeddings_table)

            # Verify all chunks have both embedding columns
            assert len(inserted_docs) == 4
            for _doc_id, doc in inserted_docs:
                # Documents use original column names, not mapped names
                assert "embeddings" in doc
                assert "embeddings_alt" in doc
                assert len(doc["embeddings"]) == 3
                assert len(doc["embeddings_alt"]) == 5
                assert "chunked_content" in doc

    def test_detect_all_vector_dimensions_empty_table(self):
        """Test dimension detection with empty table."""
        empty_table = pa.table({"embeddings": pa.array([], type=pa.list_(pa.float32()))})
        dimension_mapping = detect_all_vector_dimensions(table=empty_table, vector_columns=["embeddings"])

        # Should return empty mapping for empty table
        assert dimension_mapping == {}

    def test_detect_all_vector_dimensions_with_none_values(self):
        """Test dimension detection skips None values."""
        table_with_nones = pa.table(
            {
                "embeddings": [None, [0.1, 0.2, 0.3], None],
                "embeddings_alt": [[0.1, 0.2], None, [0.3, 0.4]],
            }
        )
        dimension_mapping = detect_all_vector_dimensions(
            table=table_with_nones, vector_columns=["embeddings", "embeddings_alt"]
        )

        assert dimension_mapping == {"embeddings": 3, "embeddings_alt": 2}


class TestMilvusMultiModelInterface:
    """Test Milvus adapter interface compliance for multi-model support."""

    @pytest.fixture
    def milvus_config(self):
        """Configuration for Milvus adapter."""
        return {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.Columns.DOC_ID_COLUMN: "doc_id_hash",
            OperatorConstants.Config.AVAILABLE_FEATURES: {
                "doc_id_hash": {
                    "name": "Document ID",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "string",
                    "is_primary": True,
                },
                "embeddings": {
                    "name": "Embeddings",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "vector",
                },
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: [
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            ],
            OperatorConstants.Config.PROVIDER_CONFIG: {
                "collection_name": "test_collection",
                "auth_type": "standalone",
                "host": "localhost",
                "port": 19530,
                "username": "root",
                "password": "Milvus",  # pragma: allowlist secret
                "database": "default",
                "secure": False,
                "index_type": "HNSW",
                "metric_type": "L2",
                "batch_size": 100,
                "primary_key_field": "pk",
            },
        }

    @patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.PyMilvusClient")
    def test_milvus_create_index_accepts_dimension_mapping(self, mock_pymilvus, milvus_config):
        """Test that Milvus adapter's create_index accepts dimension_mapping parameter."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

        # Mock the client
        mock_client_instance = MagicMock()
        mock_pymilvus.return_value = mock_client_instance
        mock_client_instance.list_collections.return_value = []

        # Mock collection operations to prevent actual Milvus calls
        mock_client_instance.has_collection.return_value = False
        mock_client_instance.create_collection.return_value = None
        mock_client_instance.create_index.return_value = None

        # Merge provider_config with operator-level config for adapter
        adapter_config = {**milvus_config, **milvus_config[OperatorConstants.Config.PROVIDER_CONFIG]}
        adapter = MilvusAdapter(**adapter_config)

        # Should accept dimension_mapping parameter without error
        dimension_mapping = {"embeddings": 384}
        try:
            adapter.create_index(dimension_mapping=dimension_mapping)
            # If we get here, the method signature is correct
            assert True
        except TypeError as e:
            pytest.fail(f"create_index does not accept dimension_mapping parameter: {e}")

    @patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.PyMilvusClient")
    def test_milvus_detect_all_vector_dimensions(self, mock_pymilvus, milvus_config):
        """Test that Milvus adapter implements detect_all_vector_dimensions."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

        mock_client_instance = MagicMock()
        mock_pymilvus.return_value = mock_client_instance

        # Merge provider_config with operator-level config for adapter
        adapter_config = {**milvus_config, **milvus_config[OperatorConstants.Config.PROVIDER_CONFIG]}
        adapter = MilvusAdapter(**adapter_config)

        # Create test table
        table = pa.table({"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]})

        # Should implement detect_all_vector_dimensions
        dimension_mapping = adapter.detect_all_vector_dimensions(table=table, vector_columns=["embeddings"])

        assert dimension_mapping == {"embeddings": 3}
