"""
Unit test to verify VectorDB operator correctly separates document-level and item-level metrics.
"""

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.utils.operators.vectordb_utils import generate_composite_pk


class TestVectorDBMetrics:
    """Test VectorDB operator metrics separation."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter for testing."""
        adapter = MagicMock()
        adapter.detect_vector_dimension.return_value = 2
        adapter.detect_all_vector_dimensions.return_value = {"embeddings": 2}
        adapter.index_exists.return_value = True
        adapter.index_documents.return_value = (4, [])  # 4 items indexed, no failed chunks
        adapter.refresh_index.return_value = None
        adapter.generate_chunk_pk.side_effect = lambda *, file_id, chunk_index, chunk_content: generate_composite_pk(
            file_id=file_id, chunk_content=chunk_content
        )
        return adapter

    @pytest.fixture
    def vectordb_config(self):
        """Create VectorDB operator configuration."""
        return {
            "provider": "opensearch",
            "doc_id_column": "doc_id_hash",
            "embeddings_column": "embeddings",
            "vector_dimension": 2,
            "available_features": {
                "doc_id_hash": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "string",
                    "is_primary": True,
                },
                "embeddings": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "vector",
                },
                "content": {
                    "available_for_vector_db": True,
                    "type": "string",
                },
                "chunked_content": {
                    "available_for_vector_db": True,
                    "type": "string",
                },
            },
            "provider_config": {
                "index_name": "test_index",
                "host": "localhost",
                "port": 9200,
            },
        }

    def test_document_count_with_chunked_embeddings(self, *, vectordb_config, mock_adapter):
        """
        Test that processed_docs tracks document count, not chunk count.

        Scenario:
        - 3 input documents (table rows)
        - Document 1 has 2 chunks -> creates 2 index items
        - Document 2 has 1 chunk -> creates 1 index item
        - Document 3 has 1 chunk -> creates 1 index item
        - Total: 3 documents -> 4 items to index

        Expected:
        - processed_docs = 3 (document count)
        - items_indexed = 4 (chunk/item count)
        """
        # Create test table with chunked embeddings
        table = pa.table(
            {
                "doc_id_hash": ["doc1", "doc2", "doc3"],
                "content": ["Document 1", "Document 2", "Document 3"],
                "embeddings": [
                    [[0.1, 0.2], [0.3, 0.4]],  # doc1: 2 chunks
                    [[0.5, 0.6]],  # doc2: 1 chunk (wrapped in list)
                    [[0.7, 0.8]],  # doc3: 1 chunk (wrapped in list)
                ],
                "chunked_content": [
                    [{"chunk": "Chunk 1 of doc1"}, {"chunk": "Chunk 2 of doc1"}],  # doc1: 2 chunks
                    [{"chunk": "Chunk 1 of doc2"}],  # doc2: 1 chunk
                    [{"chunk": "Chunk 1 of doc3"}],  # doc3: 1 chunk
                ],
            }
        )

        # Patch the adapter factory to return our mock
        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(config=vectordb_config)
            _, metadata = operator.transform(table=table)

        # Verify document-level metrics
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3, "Should track 3 documents, not 4 chunks"
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0, "No documents should fail"

        # Verify item-level metrics
        assert metadata[Metrics.External.TOTAL_CHUNKS_TO_INDEX] == 4, "Should prepare 4 items (2+1+1 chunks)"
        assert metadata[Metrics.External.CHUNKS_INDEXED_SUCCESSFULLY] == 4, "Should index 4 items"
        assert metadata[Metrics.External.CHUNKS_FAILED_TO_INDEX] == 0, "No items should fail"

    def test_document_count_with_single_embeddings(self, *, vectordb_config, mock_adapter):
        """
        Test that processed_docs equals items_indexed when no chunking.

        Scenario:
        - 3 input documents with single embeddings
        - Total: 3 documents -> 3 items to index

        Expected:
        - processed_docs = 3
        - items_indexed = 3
        """
        # Mock adapter to return 3 indexed items
        mock_adapter.index_documents.return_value = (3, [])

        # Create test table with single embeddings
        table = pa.table(
            {
                "doc_id_hash": ["doc1", "doc2", "doc3"],
                "content": ["Document 1", "Document 2", "Document 3"],
                "embeddings": [
                    [0.1, 0.2],  # doc1: single embedding
                    [0.3, 0.4],  # doc2: single embedding
                    [0.5, 0.6],  # doc3: single embedding
                ],
            }
        )

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(config=vectordb_config)
            _, metadata = operator.transform(table=table)

        # Both metrics should be equal when no chunking
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3
        assert metadata[Metrics.External.CHUNKS_INDEXED_SUCCESSFULLY] == 3
        assert metadata[Metrics.External.TOTAL_CHUNKS_TO_INDEX] == 3

    def test_document_count_with_failed_items(self, *, vectordb_config, mock_adapter):
        """
        Test that document count remains correct even when items fail to index.

        Scenario:
        - 3 input documents
        - 1 document has 2 chunks -> 2 items
        - 2 documents have single embeddings -> 2 items
        - 1 item fails to index
        - Total: 3 documents, 4 items prepared, 3 items indexed, 1 item failed

        Expected:
        - processed_docs = 3 (all documents processed successfully)
        - items_indexed = 3
        - items_failed_to_index = 1
        """
        # Mock adapter: 3 items indexed, 1 failed
        failed_item = {"index": {"_id": "doc1_chunk_1", "error": {"reason": "Test failure"}}}
        mock_adapter.index_documents.return_value = (3, [failed_item])

        table = pa.table(
            {
                "doc_id_hash": ["doc1", "doc2", "doc3"],
                "content": ["Document 1", "Document 2", "Document 3"],
                "embeddings": [
                    [[0.1, 0.2], [0.3, 0.4]],  # doc1: 2 chunks
                    [[0.5, 0.6]],  # doc2: 1 chunk
                    [[0.7, 0.8]],  # doc3: 1 chunk
                ],
                "chunked_content": [
                    [{"chunk": "Chunk 1 of doc1"}, {"chunk": "Chunk 2 of doc1"}],  # doc1: 2 chunks
                    [{"chunk": "Chunk 1 of doc2"}],  # doc2: 1 chunk
                    [{"chunk": "Chunk 1 of doc3"}],  # doc3: 1 chunk
                ],
            }
        )

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(config=vectordb_config)
            _, metadata = operator.transform(table=table)

        # Document with failed chunk should be marked as failed (following docling-pipelines-api pattern)
        # 1 document had a chunk failure, so it's counted as failed
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2  # Only 2 docs fully succeeded
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1  # 1 doc had chunk failure
        assert metadata[Metrics.External.CHUNKS_INDEXED_SUCCESSFULLY] == 3
        assert metadata[Metrics.External.CHUNKS_FAILED_TO_INDEX] == 1
        assert metadata[Metrics.External.TOTAL_CHUNKS_TO_INDEX] == 4

    def test_partial_chunk_failure_for_single_document(self, *, vectordb_config, mock_adapter):
        """
        Test behavior when one chunk of a multi-chunk document fails to index.

        Scenario:
        - 1 document with 3 chunks
        - 2 chunks index successfully, 1 chunk fails

        Expected behavior (following docling-pipelines-api pattern):
        - processed_docs = 0 (document with any chunk failure is marked as failed)
        - failed_docs_count = 1 (entire document is failed)
        - items_indexed = 2 (chunk-level success count)
        - items_failed_to_index = 1 (chunk-level failure count)

        This ensures consistency with docling-pipelines-api where if ANY chunk of a document
        fails, the entire document is counted as failed.
        """
        # Compute the composite PK the operator will generate for the first chunk of doc1.
        # file_id = "doc1" (no 'id' column in the table, so falls back to doc_id_hash value).
        # chunk_content = "Chunk 1 of doc1" (chunked_content[0]["chunk"]).
        chunk1_pk = generate_composite_pk(file_id="doc1", chunk_content="Chunk 1 of doc1")
        # Mock adapter: 2 items indexed, 1 failed (first chunk of doc1)
        failed_item = {"index": {"_id": chunk1_pk, "error": {"reason": "Indexing error"}}}
        mock_adapter.index_documents.return_value = (2, [failed_item])

        # Create table with 1 document having 3 chunks
        table = pa.table(
            {
                "doc_id_hash": ["doc1"],
                "content": ["Document 1 with three chunks"],
                "embeddings": [
                    [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]  # 3 chunks
                ],
                "chunked_content": [
                    [
                        {"chunk": "Chunk 1 of doc1"},
                        {"chunk": "Chunk 2 of doc1"},
                        {"chunk": "Chunk 3 of doc1"},
                    ]
                ],
            }
        )

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_adapter,
        ):
            operator = VectorDBOperator(config=vectordb_config)
            _, metadata = operator.transform(table=table)

        # Document-level: entire document marked as failed due to partial chunk failure
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0  # No documents fully succeeded
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1  # 1 doc had chunk failure

        # Item-level: 2 chunks indexed, 1 failed
        assert metadata[Metrics.External.CHUNKS_INDEXED_SUCCESSFULLY] == 2
        assert metadata[Metrics.External.CHUNKS_FAILED_TO_INDEX] == 1
        assert metadata[Metrics.External.TOTAL_CHUNKS_TO_INDEX] == 3

        # Verify failed document was recorded
        assert len(metadata[Metrics.External.FAILED_DOCS]) == 1
        assert metadata[Metrics.External.FAILED_DOCS][0]["id"] == "doc1"
        assert "One or more chunks failed to index" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
