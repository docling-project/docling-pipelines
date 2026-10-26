#!/usr/bin/env python3
"""
Unit tests for MilvusBatchProcessor
"""

from unittest.mock import MagicMock

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor import (
    DEFAULT_BATCH_SIZE,
    MilvusBatchProcessor,
)


@pytest.fixture
def mock_client():
    """Mock Milvus client"""
    return MagicMock()


@pytest.fixture
def basic_features():
    """Basic feature configuration"""
    return {
        "doc_id": {
            "name": "Document ID",
            "available_for_vector_db": True,
            "type": "string",
            "is_primary": True,
        },
        "content": {
            "name": "Content",
            "available_for_vector_db": True,
            "type": "string",
        },
        "embeddings": {
            "name": "Embeddings",
            "available_for_vector_db": True,
            "type": "vector",
        },
        "metadata": {
            "name": "Metadata",
            "available_for_vector_db": True,
            "type": "object",
        },
    }


@pytest.fixture
def feature_mappings():
    """Feature mappings"""
    return [
        {"feature_name": "doc_id", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
        {"feature_name": "metadata", "mapped_column_name": "meta"},
    ]


class TestBatchProcessorInitialization:
    """Test batch processor initialization"""

    def test_basic_initialization(self, mock_client):
        """Test basic initialization with default parameters"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )

        assert processor.client == mock_client
        assert processor.collection_name == "test_collection"
        assert processor.batch_size == DEFAULT_BATCH_SIZE
        assert processor.primary_key_field == "pk"

    def test_initialization_with_custom_batch_size(self, mock_client):
        """Test initialization with custom batch size"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            batch_size=500,
        )

        assert processor.batch_size == 500

    def test_initialization_with_features(self, mock_client, basic_features, feature_mappings):
        """Test initialization with feature configuration"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        assert processor.available_features == basic_features
        assert processor.feature_mappings == feature_mappings

    def test_initialization_with_custom_primary_key(self, mock_client):
        """Test initialization with custom primary key field"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            primary_key_field="id",
        )

        assert processor.primary_key_field == "id"


class TestDocumentPreparation:
    """Test document preparation"""

    def test_prepare_simple_document(self, mock_client, basic_features, feature_mappings):
        """Test preparing a simple document"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": [0.1, 0.2, 0.3],
        }

        doc = processor.prepare_document(row_data=row_data)

        assert doc["pk"] == "doc1"
        assert doc["text"] == "Test content"
        assert doc["vector_embeddings"] == [0.1, 0.2, 0.3]

    def test_prepare_document_with_metadata(self, mock_client, basic_features, feature_mappings):
        """Test preparing document with metadata"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": [0.1, 0.2, 0.3],
            "metadata": {"source": "test", "page": 1},
        }

        doc = processor.prepare_document(row_data=row_data)

        assert doc["meta"] == {"source": "test", "page": 1}

    def test_prepare_document_skips_none_values(self, mock_client, basic_features, feature_mappings):
        """Test that None values are skipped"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": None,
            "embeddings": [0.1, 0.2, 0.3],
        }

        doc = processor.prepare_document(row_data=row_data)

        assert "text" not in doc
        assert "pk" in doc
        assert "vector_embeddings" in doc

    def test_prepare_document_skips_binary_data(self, mock_client, basic_features, feature_mappings):
        """Test that binary data is skipped"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": b"binary content",
            "embeddings": [0.1, 0.2, 0.3],
        }

        doc = processor.prepare_document(row_data=row_data)

        assert "text" not in doc

    def test_prepare_document_with_binary_vector(self, mock_client):
        """Test that binary vector bytes are preserved for vector fields."""
        features = {
            "doc_id": {"name": "Document ID", "available_for_vector_db": True, "type": "string"},
            "binary_embeddings": {
                "name": "Binary Embeddings",
                "available_for_vector_db": True,
                "type": "binary_vector",
            },
        }
        mappings = [
            {"feature_name": "doc_id", "mapped_column_name": "pk"},
            {"feature_name": "binary_embeddings", "mapped_column_name": "vector_embeddings"},
        ]
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=features,
            feature_mappings=mappings,
            embeddings_column="binary_embeddings",
        )

        binary_data = b"\x01\x02\x03\x04"
        row_data = {
            "doc_id": "doc1",
            "binary_embeddings": binary_data,
        }

        doc = processor.prepare_document(row_data=row_data)

        assert doc["pk"] == "doc1"
        assert doc["vector_embeddings"] == binary_data
        assert isinstance(doc["vector_embeddings"], bytes)

    def test_prepare_document_converts_numpy_arrays(self, mock_client, basic_features, feature_mappings):
        """Test that numpy arrays are converted to lists"""
        import numpy as np

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": np.array([0.1, 0.2, 0.3]),
        }

        doc = processor.prepare_document(row_data=row_data)

        assert isinstance(doc["vector_embeddings"], list)
        assert doc["vector_embeddings"] == [0.1, 0.2, 0.3]

    def test_prepare_document_parses_json_strings(self, mock_client, basic_features, feature_mappings):
        """Test that JSON strings are parsed for object types"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": [0.1, 0.2, 0.3],
            "metadata": '{"source": "test", "page": 1}',
        }

        doc = processor.prepare_document(row_data=row_data)

        assert isinstance(doc["meta"], dict)
        assert doc["meta"]["source"] == "test"
        assert doc["meta"]["page"] == 1

    def test_prepare_document_handles_invalid_json(self, mock_client, basic_features, feature_mappings):
        """Test that invalid JSON is kept as string"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": [0.1, 0.2, 0.3],
            "metadata": "invalid json {",
        }

        doc = processor.prepare_document(row_data=row_data)

        assert isinstance(doc["meta"], str)
        assert doc["meta"] == "invalid json {"

    def test_prepare_document_only_mapped_features(self, mock_client, basic_features, feature_mappings):
        """Test that only mapped features are included"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test content",
            "embeddings": [0.1, 0.2, 0.3],
            "unmapped_field": "should not appear",
        }

        doc = processor.prepare_document(row_data=row_data)

        assert "unmapped_field" not in doc
        assert len(doc) == 3  # pk, text, vector_embeddings


class TestBatchSizeCalculation:
    """Test batch size calculation"""

    def test_calculate_batch_size_bytes(self, mock_client):
        """Test calculating batch size in bytes using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        documents = [
            {"pk": "doc1", "text": "content1"},
            {"pk": "doc2", "text": "content2"},
        ]

        size = calculate_batch_size_bytes(documents=documents)
        assert size > 0
        assert isinstance(size, int)

    def test_calculate_batch_size_empty_list(self, mock_client):
        """Test calculating size of empty list using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        size = calculate_batch_size_bytes(documents=[])
        assert size >= 0

    def test_calculate_batch_size_with_vectors(self, mock_client):
        """Test calculating size with vector embeddings using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        documents = [
            {"pk": "doc1", "vector": [0.1] * 384},
            {"pk": "doc2", "vector": [0.2] * 384},
        ]

        size = calculate_batch_size_bytes(documents=documents)
        assert size > 1000  # Should be substantial with vectors


class TestBatchCreation:
    """Test batch creation"""

    def test_create_batches_by_count(self, mock_client, basic_features, feature_mappings):
        """Test creating batches based on count limit"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            batch_size=2,
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        documents = [
            ("doc1", {"doc_id": "doc1", "content": "text1", "embeddings": [0.1, 0.2]}),
            ("doc2", {"doc_id": "doc2", "content": "text2", "embeddings": [0.3, 0.4]}),
            ("doc3", {"doc_id": "doc3", "content": "text3", "embeddings": [0.5, 0.6]}),
        ]

        batches = processor.create_batches(documents=documents)

        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

    def test_create_batches_single_batch(self, mock_client, basic_features, feature_mappings):
        """Test creating single batch when all fit"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            batch_size=10,
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        documents = [
            ("doc1", {"doc_id": "doc1", "content": "text1", "embeddings": [0.1, 0.2]}),
            ("doc2", {"doc_id": "doc2", "content": "text2", "embeddings": [0.3, 0.4]}),
        ]

        batches = processor.create_batches(documents=documents)

        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_create_batches_empty_documents(self, mock_client):
        """Test creating batches with empty document list"""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )

        batches = processor.create_batches(documents=[])

        assert len(batches) == 0


class TestBulkOperations:
    """Test bulk operations"""

    def test_process_batches_success(self, mock_client, basic_features, feature_mappings):
        """Test successful batch processing"""
        mock_client.insert.return_value = {"insert_count": 2}

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        # Create batches
        batch1 = [
            {"pk": "doc1", "text": "text1", "vector_embeddings": [0.1, 0.2]},
            {"pk": "doc2", "text": "text2", "vector_embeddings": [0.3, 0.4]},
        ]
        batches = [batch1]

        success_count, failed_items = processor.process_batches(batches=batches)

        assert success_count == 2
        assert len(failed_items) == 0
        mock_client.insert.assert_called_once()

    def test_delete_documents_success(self, mock_client):
        """Test successful document deletion"""
        mock_client.delete.return_value = {"delete_count": 3}

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )

        doc_ids = ["doc1", "doc2", "doc3"]
        success_count, failed_count = processor.delete_documents_by_ids(doc_ids=doc_ids)

        assert success_count == 3
        assert failed_count == 0
        mock_client.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Additional tests to reach 80% coverage
# ---------------------------------------------------------------------------


class TestDocumentPreparationEdgeCases:
    """Additional prepare_document branches not covered above."""

    def test_prepare_document_skips_sparse_embeddings_in_sparse_mode(self, mock_client):
        """sparse_embeddings feature is skipped when add_sparse_vector=True (BM25 auto-generates it)."""
        features = {
            "sparse_embeddings": {"available_for_vector_db": True, "type": "vector_sparse"},
            "content": {"available_for_vector_db": True, "type": "string"},
        }
        mappings = [
            {"feature_name": "sparse_embeddings", "mapped_column_name": "sparse_vector"},
            {"feature_name": "content", "mapped_column_name": "text"},
        ]
        from docpipe.core.constants.operator_constants import OperatorConstants

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=features,
            feature_mappings=mappings,
            add_sparse_vector=True,
        )
        row_data = {
            OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT: [0.1, 0.2],
            "content": "hello world",
        }
        doc = processor.prepare_document(row_data=row_data)
        assert "sparse_vector" not in doc
        assert doc["text"] == "hello world"

    def test_prepare_document_skips_unavailable_for_vector_db(self, mock_client):
        """Fields with available_for_vector_db=False are excluded from the document."""
        features = {
            "secret": {"available_for_vector_db": False, "type": "string"},
            "content": {"available_for_vector_db": True, "type": "string"},
        }
        mappings = [
            {"feature_name": "secret", "mapped_column_name": "secret_field"},
            {"feature_name": "content", "mapped_column_name": "text"},
        ]
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=features,
            feature_mappings=mappings,
        )
        doc = processor.prepare_document(row_data={"secret": "hidden", "content": "visible"})
        assert "secret_field" not in doc
        assert doc["text"] == "visible"

    def test_prepare_document_bytearray_is_skipped(self, mock_client, basic_features, feature_mappings):
        """bytearray values (not just bytes) are also skipped."""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )
        doc = processor.prepare_document(row_data={"doc_id": "d1", "content": bytearray(b"raw"), "embeddings": [0.1]})
        assert "text" not in doc


class TestProcessBatchesEdgeCases:
    """Branches in process_batches not previously exercised."""

    def test_process_batches_non_dict_result_counts_batch_length(self, mock_client):
        """When insert() returns a non-dict (e.g. None), success_count = len(batch)."""
        mock_client.insert.return_value = None

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        batch = [{"pk": "a"}, {"pk": "b"}]
        success, failed = processor.process_batches(batches=[batch])

        assert success == 2
        assert failed == []

    def test_process_batches_insert_raises_records_all_as_failed(self, mock_client):
        """An exception during insert marks every doc in the batch as failed."""
        mock_client.insert.side_effect = RuntimeError("connection lost")

        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        batch = [{"pk": "a"}, {"pk": "b"}, {"pk": "c"}]
        success, failed = processor.process_batches(batches=[batch])

        assert success == 0
        assert len(failed) == 3
        assert all("error" in item for item in failed)

    def test_process_batches_empty_batches_returns_zero(self, mock_client):
        """No batches → success=0, failed=[]."""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        success, failed = processor.process_batches(batches=[])
        assert success == 0
        assert failed == []

    def test_process_batches_multiple_batches_accumulates(self, mock_client):
        """Success counts from multiple batches are accumulated correctly."""
        mock_client.insert.side_effect = [
            {"insert_count": 2},
            {"insert_count": 3},
        ]
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        success, failed = processor.process_batches(
            batches=[[{"pk": "a"}, {"pk": "b"}], [{"pk": "c"}, {"pk": "d"}, {"pk": "e"}]]
        )
        assert success == 5
        assert failed == []


class TestQueryAndDeleteEdgeCases:
    """Branches in query/delete not previously exercised."""

    def test_query_by_doc_names_returns_empty_on_exception(self, mock_client):
        """query_by_doc_names returns [] when client.query raises."""
        mock_client.query.side_effect = Exception("query error")
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        result = processor.query_by_doc_names(doc_names=["doc1"])
        assert result == []

    def test_delete_documents_empty_list_returns_zeros(self, mock_client):
        """Deleting an empty id list immediately returns (0, 0) without calling client."""
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        success, failed = processor.delete_documents_by_ids(doc_ids=[])
        assert (success, failed) == (0, 0)
        mock_client.delete.assert_not_called()

    def test_delete_documents_non_dict_result_counts_batch(self, mock_client):
        """When delete() returns non-dict, deleted count = len(batch)."""
        mock_client.delete.return_value = None
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        success, failed = processor.delete_documents_by_ids(doc_ids=["a", "b"])
        assert success == 2
        assert failed == 0

    def test_delete_documents_batch_exception_increments_failed(self, mock_client):
        """Exception in one delete batch increments failed_count."""
        mock_client.delete.side_effect = Exception("delete failed")
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        success, failed = processor.delete_documents_by_ids(doc_ids=["a", "b"])
        assert success == 0
        assert failed == 2

    def test_get_document_count_returns_row_count(self, mock_client):
        """get_document_count returns stats row_count."""
        mock_client.get_collection_stats.return_value = {"row_count": 42}
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        assert processor.get_document_count() == 42

    def test_get_document_count_returns_zero_on_exception(self, mock_client):
        """get_document_count returns 0 when client raises."""
        mock_client.get_collection_stats.side_effect = Exception("stats error")
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
        )
        assert processor.get_document_count() == 0

    def test_create_batches_size_split_on_mb_limit(self, mock_client):
        """Batch is flushed when accumulated size exceeds MAX_BATCH_SIZE_MB."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor import MAX_BATCH_SIZE_MB

        # Build a document large enough that 2 of them exceed the byte limit
        big_text = "x" * (MAX_BATCH_SIZE_MB * 1024 * 1024 // 2 + 1)
        features = {"content": {"available_for_vector_db": True, "type": "string"}}
        mappings = [{"feature_name": "content", "mapped_column_name": "text"}]
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            batch_size=1000,
            available_features=features,
            feature_mappings=mappings,
        )
        documents = [
            ("d1", {"content": big_text}),
            ("d2", {"content": big_text}),
            ("d3", {"content": big_text}),
        ]
        batches = processor.create_batches(documents=documents)
        # Each oversized doc should be in its own batch
        assert len(batches) >= 2


class TestQueryPksByDocIds:
    """Tests for MilvusBatchProcessor.get_chunk_ids_for_documents()."""

    def test_returns_empty_dict_for_empty_input(self, mock_client) -> None:
        """Empty doc_ids list must return {} without calling the client."""
        processor = MilvusBatchProcessor(client=mock_client, collection_name="test_collection")
        result = processor.get_chunk_ids_for_documents(doc_ids=[])
        assert result == {}
        mock_client.query.assert_not_called()

    def test_returns_pks_grouped_by_doc_id(self, mock_client) -> None:
        """Rows returned by each per-doc prefix query must be grouped by file_id."""
        import hashlib

        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        hash_b = hashlib.sha3_512(b"doc_b").hexdigest()

        # query is called once per doc_id — return different rows for each call
        mock_client.query.side_effect = [
            [{"pk": f"{hash_a}_c1"}, {"pk": f"{hash_a}_c2"}],  # doc_a
            [{"pk": f"{hash_b}_c1"}],  # doc_b
        ]
        processor = MilvusBatchProcessor(client=mock_client, collection_name="test_collection")
        result = processor.get_chunk_ids_for_documents(doc_ids=["doc_a", "doc_b"])
        assert result == {
            "doc_a": {f"{hash_a}_c1", f"{hash_a}_c2"},
            "doc_b": {f"{hash_b}_c1"},
        }

    def test_uses_pk_prefix_filter(self, mock_client) -> None:
        """Filter expression must be a pk like query using the sha3_512 prefix of the file_id."""
        import hashlib

        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        mock_client.query.return_value = [{"pk": f"{hash_a}_c1"}]
        processor = MilvusBatchProcessor(client=mock_client, collection_name="test_collection")
        processor.get_chunk_ids_for_documents(doc_ids=["doc_a"])
        call_kwargs = mock_client.query.call_args[1]
        assert call_kwargs["filter"] == f'pk like "{hash_a}_%"'

    def test_skips_rows_with_empty_pk(self, mock_client) -> None:
        """Rows with an empty PK value must be excluded from the result."""
        mock_client.query.return_value = [
            {"pk": "", "doc_id_hash": "doc_a"},
            {"pk": "pk_valid", "doc_id_hash": "doc_a"},
        ]
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            feature_mappings=[{"feature_name": "doc_id_hash", "mapped_column_name": "doc_id_hash"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=["doc_a"])
        assert result == {"doc_a": {"pk_valid"}}

    def test_returns_empty_dict_on_exception(self, mock_client) -> None:
        """A client exception must be swallowed and return {}."""
        mock_client.query.side_effect = Exception("timeout")
        processor = MilvusBatchProcessor(
            client=mock_client,
            collection_name="test_collection",
            feature_mappings=[{"feature_name": "doc_id_hash", "mapped_column_name": "doc_id_hash"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=["doc_a"])
        assert result == {}
