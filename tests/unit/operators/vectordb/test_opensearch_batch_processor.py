#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for OpenSearchBatchProcessor
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter import OpenSearchAdapter
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor import (
    BULK_DELETE_BATCH_SIZE,
    BULK_INSERT_TIMEOUT,
    DEFAULT_BATCH_SIZE,
    OpenSearchBatchProcessor,
)


@pytest.fixture
def mock_client():
    """Mock OpenSearch client"""
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
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        assert processor.client == mock_client
        assert processor.index_name == "test_index"
        assert processor.batch_size == DEFAULT_BATCH_SIZE

    def test_initialization_with_custom_batch_size(self, mock_client):
        """Test initialization with custom batch size"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            batch_size=500,
        )

        assert processor.batch_size == 500

    def test_initialization_with_features(self, mock_client, basic_features, feature_mappings):
        """Test initialization with feature configuration"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        assert processor.available_features == basic_features
        assert processor.feature_mappings == feature_mappings


class TestDocumentPreparation:
    """Test document preparation"""

    def test_prepare_basic_document(self, mock_client, basic_features, feature_mappings):
        """Test preparing basic document"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
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

    def test_prepare_document_with_none_values(self, mock_client, basic_features, feature_mappings):
        """Test preparing document with None values"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": None,
            "embeddings": [0.1, 0.2, 0.3],
        }

        doc = processor.prepare_document(row_data=row_data)

        assert doc["pk"] == "doc1"
        assert "text" not in doc  # None values should be excluded
        assert doc["vector_embeddings"] == [0.1, 0.2, 0.3]

    def test_prepare_document_with_numpy_array(self, mock_client, basic_features, feature_mappings):
        """Test preparing document with numpy array"""
        import numpy as np

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test",
            "embeddings": np.array([0.1, 0.2, 0.3]),
        }

        doc = processor.prepare_document(row_data=row_data)

        assert isinstance(doc["vector_embeddings"], list)
        assert doc["vector_embeddings"] == [0.1, 0.2, 0.3]

    def test_prepare_document_with_json_string(self, mock_client, basic_features, feature_mappings):
        """Test preparing document with JSON string for object type"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        metadata_dict = {"key": "value", "count": 42}
        row_data = {
            "doc_id": "doc1",
            "content": "Test",
            "embeddings": [0.1, 0.2],
            "metadata": json.dumps(metadata_dict),
        }

        doc = processor.prepare_document(row_data=row_data)

        assert doc["meta"] == metadata_dict

    def test_prepare_document_with_invalid_json(self, mock_client, basic_features, feature_mappings):
        """Test preparing document with invalid JSON string"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        row_data = {
            "doc_id": "doc1",
            "content": "Test",
            "embeddings": [0.1, 0.2],
            "metadata": "invalid json {",
        }

        doc = processor.prepare_document(row_data=row_data)

        # Should keep as string if JSON parsing fails
        assert doc["meta"] == "invalid json {"

    def test_prepare_document_excludes_unavailable_features(self, mock_client):
        """Test that unavailable features are excluded"""
        features = {
            "included": {"available_for_vector_db": True, "type": "string"},
            "excluded": {"available_for_vector_db": False, "type": "string"},
        }

        # feature_mappings defines which fields to include
        mappings = [
            {"feature_name": "included", "mapped_column_name": "included"},
            {"feature_name": "excluded", "mapped_column_name": "excluded"},
        ]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=features,
            feature_mappings=mappings,
        )

        row_data = {
            "included": "value1",
            "excluded": "value2",
        }

        doc = processor.prepare_document(row_data=row_data)

        assert "included" in doc
        assert "excluded" not in doc


class TestBatchSizeCalculation:
    """Test batch size calculation"""

    def test_calculate_batch_size_bytes(self, mock_client):
        """Test calculating batch size in bytes using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        documents = [
            {"id": "doc1", "content": "test"},
            {"id": "doc2", "content": "test2"},
        ]

        size = calculate_batch_size_bytes(documents=documents)

        assert size > 0
        assert isinstance(size, int)

    def test_calculate_batch_size_empty_list(self, mock_client):
        """Test calculating batch size for empty list using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        size = calculate_batch_size_bytes(documents=[])

        assert size >= 0

    def test_calculate_batch_size_handles_error(self, mock_client):
        """Test batch size calculation handles errors using shared utility"""
        from docpipe.utils.operators.vectordb_utils import calculate_batch_size_bytes

        # Non-serializable object
        documents = [{"obj": object()}]

        size = calculate_batch_size_bytes(documents=documents)

        assert size == 0


class TestBatchCreation:
    """Test batch creation logic"""

    def test_create_batches_single_batch(self, mock_client):
        """Test creating single batch when documents fit"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            batch_size=100,
        )

        documents = [
            ("doc1", {"content": "test1"}),
            ("doc2", {"content": "test2"}),
            ("doc3", {"content": "test3"}),
        ]

        batches = processor.create_batches(documents)

        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_create_batches_multiple_batches_by_count(self, mock_client):
        """Test creating multiple batches based on count limit"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            batch_size=2,
        )

        documents = [
            ("doc1", {"content": "test1"}),
            ("doc2", {"content": "test2"}),
            ("doc3", {"content": "test3"}),
        ]

        batches = processor.create_batches(documents)

        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

    def test_create_batches_multiple_batches_by_size(self, mock_client):
        """Test creating multiple batches based on size limit"""
        # Define features so documents aren't filtered out
        features = {"content": {"available_for_vector_db": True, "type": "string"}}
        mappings = [{"feature_name": "content", "mapped_column_name": "content"}]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            batch_size=1000,
            available_features=features,
            feature_mappings=mappings,
        )

        # Create large documents that exceed 3MB when combined
        large_content = "x" * (2 * 1024 * 1024)  # 2MB per document
        documents = [
            ("doc1", {"content": large_content}),
            ("doc2", {"content": large_content}),
        ]

        batches = processor.create_batches(documents)

        # Should split into separate batches due to size
        assert len(batches) >= 2

    def test_create_batches_action_structure(self, mock_client):
        """Test batch action structure uses native upsert format."""
        # Define features so documents aren't filtered out
        features = {"content": {"available_for_vector_db": True, "type": "string"}}
        mappings = [{"feature_name": "content", "mapped_column_name": "content"}]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            available_features=features,
            feature_mappings=mappings,
        )

        documents = [("doc1", {"content": "test"})]

        batches = processor.create_batches(documents)

        action = batches[0][0]
        assert action["_op_type"] == "update"
        assert action["_index"] == "test_index"
        assert action["_id"] == "doc1"
        assert action["doc"] == {"content": "test"}
        assert action["doc_as_upsert"] is True
        assert "_source" not in action

    def test_create_batches_uses_update_op_type(self, mock_client):
        """All actions produced by create_batches must have _op_type 'update'."""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )
        documents = [("doc1", {"content": "a"}), ("doc2", {"content": "b"})]
        batches = processor.create_batches(documents)
        for batch in batches:
            for action in batch:
                assert action["_op_type"] == "update"

    def test_create_batches_doc_as_upsert_is_true(self, mock_client):
        """All actions must carry doc_as_upsert=True."""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )
        documents = [("doc1", {"content": "a"}), ("doc2", {"content": "b"})]
        batches = processor.create_batches(documents)
        for batch in batches:
            for action in batch:
                assert action["doc_as_upsert"] is True

    def test_create_batches_no_source_key(self, mock_client):
        """The legacy '_source' key must be absent from all upsert actions."""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )
        documents = [("doc1", {"content": "a"})]
        batches = processor.create_batches(documents)
        for batch in batches:
            for action in batch:
                assert "_source" not in action

    def test_create_batches_empty_documents(self, mock_client):
        """Test creating batches with empty document list"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        batches = processor.create_batches([])

        assert len(batches) == 0


class TestBulkIndexing:
    """Test bulk indexing operations"""

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_bulk_index_success(self, mock_bulk, mock_client):
        """Test successful bulk indexing"""
        mock_bulk.return_value = (3, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        actions = [
            {"_index": "test_index", "_id": "doc1", "_source": {"content": "test1"}},
            {"_index": "test_index", "_id": "doc2", "_source": {"content": "test2"}},
            {"_index": "test_index", "_id": "doc3", "_source": {"content": "test3"}},
        ]

        success, failed = processor.bulk_index(actions)

        assert success == 3
        assert len(failed) == 0
        mock_bulk.assert_called_once()

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_bulk_index_with_failures(self, mock_bulk, mock_client):
        """Test bulk indexing with some failures"""
        failed_items = [{"_id": "doc2", "error": "version conflict"}]
        mock_bulk.return_value = (2, failed_items)

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        actions = [
            {"_index": "test_index", "_id": "doc1", "_source": {"content": "test1"}},
            {"_index": "test_index", "_id": "doc2", "_source": {"content": "test2"}},
            {"_index": "test_index", "_id": "doc3", "_source": {"content": "test3"}},
        ]

        success, failed = processor.bulk_index(actions)

        assert success == 2
        assert len(failed) == 1

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_bulk_index_error(self, mock_bulk, mock_client):
        """Test bulk indexing handles errors"""
        mock_bulk.side_effect = Exception("Bulk error")

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        actions = [{"_index": "test_index", "_id": "doc1", "_source": {"content": "test"}}]

        success, failed = processor.bulk_index(actions)

        assert success == 0
        assert len(failed) == 1

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_bulk_index_timeout_parameter(self, mock_bulk, mock_client):
        """Test bulk indexing uses correct timeout"""
        mock_bulk.return_value = (1, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        actions = [{"_index": "test_index", "_id": "doc1", "_source": {"content": "test"}}]

        processor.bulk_index(actions)

        call_kwargs = mock_bulk.call_args[1]
        assert call_kwargs["request_timeout"] == BULK_INSERT_TIMEOUT


class TestBatchProcessing:
    """Test batch processing"""

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_process_batches_single_batch(self, mock_bulk, mock_client):
        """Test processing single batch"""
        mock_bulk.return_value = (3, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        batches = [
            [
                {
                    "_index": "test_index",
                    "_id": "doc1",
                    "_source": {"content": "test1"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc2",
                    "_source": {"content": "test2"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc3",
                    "_source": {"content": "test3"},
                },
            ]
        ]

        success, failed = processor.process_batches(batches)

        assert success == 3
        assert len(failed) == 0

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_process_batches_multiple_batches(self, mock_bulk, mock_client):
        """Test processing multiple batches"""
        mock_bulk.side_effect = [(2, []), (3, [])]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        batches = [
            [
                {
                    "_index": "test_index",
                    "_id": "doc1",
                    "_source": {"content": "test1"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc2",
                    "_source": {"content": "test2"},
                },
            ],
            [
                {
                    "_index": "test_index",
                    "_id": "doc3",
                    "_source": {"content": "test3"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc4",
                    "_source": {"content": "test4"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc5",
                    "_source": {"content": "test5"},
                },
            ],
        ]

        success, failed = processor.process_batches(batches)

        assert success == 5
        assert len(failed) == 0

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_process_batches_with_failures(self, mock_bulk, mock_client):
        """Test processing batches with failures"""
        failed_items = [{"_id": "doc2", "error": "error"}]
        mock_bulk.side_effect = [(1, failed_items), (2, [])]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        batches = [
            [
                {
                    "_index": "test_index",
                    "_id": "doc1",
                    "_source": {"content": "test1"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc2",
                    "_source": {"content": "test2"},
                },
            ],
            [
                {
                    "_index": "test_index",
                    "_id": "doc3",
                    "_source": {"content": "test3"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc4",
                    "_source": {"content": "test4"},
                },
            ],
        ]

        success, failed = processor.process_batches(batches)

        assert success == 3
        assert len(failed) == 1

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_process_batches_batch_error(self, mock_bulk, mock_client):
        """Test processing batches when one batch fails"""
        mock_bulk.side_effect = [Exception("Batch error"), (2, [])]

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        batches = [
            [{"_index": "test_index", "_id": "doc1", "_source": {"content": "test1"}}],
            [
                {
                    "_index": "test_index",
                    "_id": "doc2",
                    "_source": {"content": "test2"},
                },
                {
                    "_index": "test_index",
                    "_id": "doc3",
                    "_source": {"content": "test3"},
                },
            ],
        ]

        success, failed = processor.process_batches(batches)

        assert success == 2
        assert len(failed) == 1


class TestQueryOperations:
    """Test query operations"""

    def test_query_by_doc_names_success(self, mock_client):
        """Test querying documents by names"""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"name": "doc1", "content": "test1"}},
                    {"_source": {"name": "doc2", "content": "test2"}},
                ]
            }
        }

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        docs = processor.query_by_doc_names(["doc1", "doc2"])

        assert len(docs) == 2
        assert docs[0]["name"] == "doc1"
        assert docs[1]["name"] == "doc2"

    def test_query_by_doc_names_with_fields(self, mock_client):
        """Test querying with specific fields"""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"name": "doc1"}},
                ]
            }
        }

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        processor.query_by_doc_names(["doc1"], fields=["name"])

        call_kwargs = mock_client.search.call_args[1]
        assert "_source" in call_kwargs["body"]
        assert call_kwargs["body"]["_source"] == ["name"]

    def test_query_by_doc_names_empty_list(self, mock_client):
        """Test querying with empty list"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        docs = processor.query_by_doc_names([])

        assert len(docs) == 0
        mock_client.search.assert_not_called()

    def test_query_by_doc_names_error(self, mock_client):
        """Test query handles errors"""
        mock_client.search.side_effect = Exception("Search error")

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        docs = processor.query_by_doc_names(["doc1"])

        assert len(docs) == 0

    def test_query_constructs_correct_query(self, mock_client):
        """Test query construction"""
        mock_client.search.return_value = {"hits": {"hits": []}}

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        processor.query_by_doc_names(["doc1", "doc2"])

        call_kwargs = mock_client.search.call_args[1]
        query = call_kwargs["body"]["query"]
        assert "terms" in query
        assert "name.keyword" in query["terms"]
        assert query["terms"]["name.keyword"] == ["doc1", "doc2"]


class TestDeleteOperations:
    """Test delete operations"""

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_by_ids_success(self, mock_bulk, mock_client):
        """Test successful document deletion"""
        mock_bulk.return_value = (3, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        success, failed = processor.delete_documents_by_ids(["doc1", "doc2", "doc3"])

        assert success == 3
        assert failed == 0

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_by_ids_with_failures(self, mock_bulk, mock_client):
        """Test document deletion with failures"""
        failed_items = [{"_id": "doc2"}]
        mock_bulk.return_value = (2, failed_items)

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        success, failed = processor.delete_documents_by_ids(["doc1", "doc2", "doc3"])

        assert success == 2
        assert failed == 1

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_empty_list(self, mock_bulk, mock_client):
        """Test deleting with empty list"""
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        success, failed = processor.delete_documents_by_ids([])

        assert success == 0
        assert failed == 0
        mock_bulk.assert_not_called()

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_large_batch(self, mock_bulk, mock_client):
        """Test deleting large batch splits into multiple requests"""
        mock_bulk.return_value = (BULK_DELETE_BATCH_SIZE, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        # Create more IDs than batch size
        doc_ids = [f"doc{i}" for i in range(BULK_DELETE_BATCH_SIZE + 100)]

        processor.delete_documents_by_ids(doc_ids)

        # Should be called twice (one full batch + one partial)
        assert mock_bulk.call_count == 2

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_action_structure(self, mock_bulk, mock_client):
        """Test delete action structure"""
        mock_bulk.return_value = (1, [])

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        processor.delete_documents_by_ids(["doc1"])

        call_args = mock_bulk.call_args[0]
        actions = call_args[1]
        action = actions[0]

        assert action["_op_type"] == "delete"
        assert action["_index"] == "test_index"
        assert action["_id"] == "doc1"

    @patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor.helpers.bulk")
    def test_delete_documents_error(self, mock_bulk, mock_client):
        """Test delete handles errors"""
        mock_bulk.side_effect = Exception("Delete error")

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        success, failed = processor.delete_documents_by_ids(["doc1", "doc2"])

        assert success == 0
        assert failed == 2


class TestDocumentCount:
    """Test document count operations"""

    def test_get_document_count_success(self, mock_client):
        """Test getting document count"""
        mock_client.count.return_value = {"count": 100}

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        count = processor.get_document_count()

        assert count == 100
        mock_client.count.assert_called_once_with(index="test_index")

    def test_get_document_count_zero(self, mock_client):
        """Test getting zero document count"""
        mock_client.count.return_value = {"count": 0}

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        count = processor.get_document_count()

        assert count == 0

    def test_get_document_count_error(self, mock_client):
        """Test document count handles errors"""
        mock_client.count.side_effect = Exception("Count error")

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        count = processor.get_document_count()

        assert count == 0

    def test_get_document_count_missing_key(self, mock_client):
        """Test document count with missing count key"""
        mock_client.count.return_value = {}

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
        )

        count = processor.get_document_count()

        assert count == 0


class TestQueryPksByDocIds:
    """Tests for OpenSearchBatchProcessor.get_chunk_ids_for_documents().

    The method issues a ``terms`` query against the stored ``id`` field (the raw
    file ID, resolved through feature_mappings), collects ``_id`` values from each
    hit, and returns the result keyed by the same file_id that was passed in.
    This aligns with both the Milvus adapter (prefix-scan keyed by file_id) and
    the operator's ``new_pks_by_file`` dict — ensuring the set difference is correct.
    """

    def test_returns_empty_dict_for_empty_input(self, mock_client) -> None:
        """Empty doc_ids list must return {} without calling the client."""
        processor = OpenSearchBatchProcessor(client=mock_client, index_name="test_index")
        result = processor.get_chunk_ids_for_documents(doc_ids=[])
        assert result == {}
        mock_client.search.assert_not_called()

    def test_returns_pks_grouped_by_file_id(self, mock_client) -> None:
        """Hits must be grouped by their stored id field value (the file_id)."""
        file_id_a = "e59b1248c0d408e98689ccdc4cb98db5"
        file_id_b = "d8cb09ffbbf9414d7e7de6e069d750ad"
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_id": "pk_a1", "sort": ["pk_a1"], "_source": {"id": file_id_a}},
                    {"_id": "pk_a2", "sort": ["pk_a2"], "_source": {"id": file_id_a}},
                    {"_id": "pk_b1", "sort": ["pk_b1"], "_source": {"id": file_id_b}},
                ]
            }
        }
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "id"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id_a, file_id_b])
        assert result == {file_id_a: {"pk_a1", "pk_a2"}, file_id_b: {"pk_b1"}}

    def test_reconstructs_chunk_pks_from_positional_ids(self, mock_client) -> None:
        """Positional ``_id`` values must be captured verbatim and keyed by file_id.

        Verifies end-to-end: given a file_id, the method returns the stored positional
        chunk PKs under that same key so the operator can compute the stale-PK set diff.
        """
        import hashlib

        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        file_hash = hashlib.sha3_512(file_id.encode()).hexdigest()
        pk0 = f"{file_hash}_chunk_0"
        pk1 = f"{file_hash}_chunk_1"

        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_id": pk0, "sort": [pk0], "_source": {"document_id": file_id}},
                    {"_id": pk1, "sort": [pk1], "_source": {"document_id": file_id}},
                ]
            }
        }
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "document_id"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id])

        # Result must be keyed by the file_id that was passed in
        assert result == {file_id: {pk0, pk1}}

    def test_issues_terms_query_on_id_field(self, mock_client) -> None:
        """The query must use a terms filter on the stored id field."""
        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        mock_client.search.return_value = {"hits": {"hits": []}}

        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "document_id"}],
        )
        processor.get_chunk_ids_for_documents(doc_ids=[file_id])

        query_body = mock_client.search.call_args[1]["body"]
        assert "terms" in query_body["query"]
        assert "document_id" in query_body["query"]["terms"]
        assert file_id in query_body["query"]["terms"]["document_id"]

    def test_paginates_until_partial_page(self, mock_client) -> None:
        """When the first page is exactly 1000 hits a second request must be made."""
        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        page1_hits = [{"_id": f"pk_{i}", "sort": [f"pk_{i}"], "_source": {"document_id": file_id}} for i in range(1000)]
        page2_hits = [{"_id": "pk_last", "sort": ["pk_last"], "_source": {"document_id": file_id}}]
        mock_client.search.side_effect = [
            {"hits": {"hits": page1_hits}},
            {"hits": {"hits": page2_hits}},
        ]
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "document_id"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id])
        assert len(result[file_id]) == 1001
        assert mock_client.search.call_count == 2

    def test_stops_on_empty_page(self, mock_client) -> None:
        """An empty page terminates pagination and returns an empty result."""
        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        mock_client.search.return_value = {"hits": {"hits": []}}
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "document_id"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id])
        assert result == {}
        assert mock_client.search.call_count == 1

    def test_uses_feature_mapping_for_id_field_name(self, mock_client) -> None:
        """An overridden feature mapping for 'id' must be used as the query field."""
        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        mock_client.search.return_value = {
            "hits": {"hits": [{"_id": "pk1", "sort": ["pk1"], "_source": {"file_ref": file_id}}]}
        }
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "file_ref"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id])
        assert result == {file_id: {"pk1"}}
        query_body = mock_client.search.call_args[1]["body"]
        assert "file_ref" in query_body["query"]["terms"]

    def test_returns_empty_dict_on_exception(self, mock_client) -> None:
        """A client exception must be swallowed and return {}."""
        file_id = "e59b1248c0d408e98689ccdc4cb98db5"
        mock_client.search.side_effect = Exception("connection refused")
        processor = OpenSearchBatchProcessor(
            client=mock_client,
            index_name="test_index",
            feature_mappings=[{"feature_name": "id", "mapped_column_name": "document_id"}],
        )
        result = processor.get_chunk_ids_for_documents(doc_ids=[file_id])
        assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_opensearch_strict_failure_does_not_become_absence():
    client = Mock()
    client.search.side_effect = ConnectionError("unreachable")
    processor = OpenSearchBatchProcessor(client=client, index_name="test")
    with pytest.raises(ConnectionError):
        processor.get_chunk_ids_for_documents(doc_ids=["file"], strict=True)
    assert processor.get_chunk_ids_for_documents(doc_ids=["file"]) == {}


def test_opensearch_pages_all_chunks_and_uses_mapped_identity():
    client = Mock()
    hits = [{"_id": f"chunk-{i}", "_source": {"original_id": "file"}, "sort": [i]} for i in range(1000)]
    client.search.return_value = {"_scroll_id": "first", "hits": {"hits": hits}}
    client.scroll.side_effect = [
        {"_scroll_id": "second", "hits": {"hits": [{"_id": "last", "_source": {"original_id": "file"}}]}},
        {"_scroll_id": "second", "hits": {"hits": []}},
    ]
    processor = OpenSearchBatchProcessor(
        client=client, index_name="test", feature_mappings=[{"feature_name": "id", "mapped_column_name": "original_id"}]
    )
    assert len(processor.get_chunk_ids_for_documents(doc_ids=["file"], strict=True)["file"]) == 1001
    query = client.search.call_args.kwargs["body"]
    assert query["query"]["terms"] == {"original_id": ["file"]}
    assert query["sort"] == "_doc"
    assert client.scroll.call_count == 2
    client.clear_scroll.assert_called_once_with(body={"scroll_id": ["second"]})


@pytest.mark.parametrize("failure", [{"timed_out": True}, {"_shards": {"failed": 1}}, {"terminated_early": True}])
def test_opensearch_partial_results_are_not_absence(failure):
    client = Mock()
    client.search.return_value = {"_scroll_id": "cursor", "hits": {"hits": []}, **failure}
    processor = OpenSearchBatchProcessor(client=client, index_name="test")
    with pytest.raises(RuntimeError, match="Incomplete"):
        processor.get_chunk_ids_for_documents(doc_ids=["file"], strict=True)
    client.clear_scroll.assert_called_once()


def test_opensearch_bounds_terms_requests_and_checks_missing_index():
    adapter = object.__new__(OpenSearchAdapter)
    adapter.client_manager = Mock()
    adapter.index_name = "test"
    adapter.batch_processor = Mock()
    adapter.batch_processor._mapping_dict = {"id": "original_id"}
    adapter.batch_processor.get_chunk_ids_for_documents.return_value = {}
    adapter.client_manager.get_client.return_value.indices.exists.return_value = True
    adapter.resolve_source_chunks(doc_ids=[str(i) for i in range(1200)])
    assert [
        len(call.kwargs["doc_ids"]) for call in adapter.batch_processor.get_chunk_ids_for_documents.call_args_list
    ] == [500, 500, 200]
    adapter.client_manager.get_client.return_value.indices.exists.return_value = False
    assert adapter.resolve_source_chunks(doc_ids=["file"]) == {}
    adapter.client_manager.get_client.return_value.indices.exists.side_effect = ConnectionError("failed")
    with pytest.raises(ConnectionError):
        adapter.resolve_source_chunks(doc_ids=["file"])


def test_opensearch_missing_identity_mapping_cannot_acknowledge_absence():
    adapter = object.__new__(OpenSearchAdapter)
    adapter.client_manager = Mock()
    adapter.index_name = "test"
    adapter.batch_processor = Mock()
    adapter.batch_processor._mapping_dict = {}
    adapter.client_manager.get_client.return_value.indices.exists.return_value = True
    with pytest.raises(ValueError, match="original ingest id"):
        adapter.resolve_source_chunks(doc_ids=["file"])
