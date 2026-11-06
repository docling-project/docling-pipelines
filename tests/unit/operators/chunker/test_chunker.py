import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pyarrow as pa
import pytest

# Mock langchain_experimental before any imports that might use it
if "langchain_experimental" not in sys.modules:
    sys.modules["langchain_experimental"] = Mock()
    sys.modules["langchain_experimental.text_splitter"] = Mock()

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.chunker import (
    CHUNK_MAX_SIZE,
    CHUNK_MIN_SIZE,
    CHUNK_OVERLAP_MAX_SIZE,
    BreakpointThresholdType,
    ChunkerOperator,
    ChunkType,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestChunkerOperator(unittest.TestCase):
    """Test ChunkerOperator initialization and basic functionality"""

    def test_init(self):
        """Test operator initialization with simple chunking config"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        self.assertIsNotNone(operator, "Chunker Operator is not None")
        self.assertEqual(operator.chunk_type, ChunkType.SIMPLE.value)
        self.assertEqual(operator.chunk_size, 1000)
        self.assertEqual(operator.chunk_overlap, 200)
        self.assertFalse(operator.retain_original_content)

    def test_init_without_chunk_type_uses_default(self):
        """Test operator initialization without chunk_type uses default 'simple'"""
        config = {
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        self.assertIsNotNone(operator, "Chunker Operator is not None")
        self.assertEqual(operator.chunk_type, ChunkType.SIMPLE.value, "Should default to 'simple' chunk type")
        self.assertEqual(operator.chunk_size, 1000)
        self.assertEqual(operator.chunk_overlap, 200)

    def test_init_semantic_chunking(self):
        """Test operator initialization with semantic chunking config"""
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "granite4",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "breakpoint_threshold_amount": 95.0,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        self.assertIsNotNone(operator)
        self.assertEqual(operator.chunk_type, ChunkType.SEMANTIC.value)
        self.assertEqual(operator.semantic_embeddings_model, "granite4")
        self.assertEqual(operator.breakpoint_threshold_type, BreakpointThresholdType.PERCENTILE.value)

    def test_simple_chunking_transform(self):
        """Test simple chunking with a PyArrow table"""
        # 1. Create a PyArrow table with sample content
        content = [
            "This is the first sentence. This is the second sentence. "
            "This is the third sentence. This is the fourth sentence."
        ]
        doc_ids = ["doc1"]
        names = ["Document 1"]

        data = {
            OperatorConstants.Columns.ID: doc_ids,
            OperatorConstants.Columns.NAME: names,
            "content": content,
        }
        input_table = pa.table(data)

        # 2. Create operator with simple chunking config
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        # 3. Transform the table
        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # 4. Perform assertions
        self.assertEqual(result_table.num_rows, 1)
        self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)
        self.assertNotIn("content", result_table.column_names)

        # Check that chunks were created
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertIsNotNone(chunked_content)
        self.assertGreater(len(chunked_content), 0)

    def test_simple_chunking_long_text(self):
        """Test simple chunking with long text that requires multiple chunks"""
        # Create long text
        long_text = ". ".join([f"This is sentence number {i}" for i in range(100)])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Long Document"],
            "content": [long_text],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 500,
            "chunk_overlap": 100,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Should create multiple chunks
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertGreater(len(chunked_content), 1, "Long text should create multiple chunks")

    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_chunking_transform(self, mock_ollama_client_class, mock_semantic_chunker_class):
        """Test semantic chunking with fully mocked Ollama client and SemanticChunker"""
        # Mock the OllamaClient to avoid any real API calls
        mock_client = MagicMock()
        # Mock generate_embeddings to return different embeddings for each call
        # This simulates semantic differences between sentences
        mock_client.generate_embeddings.side_effect = lambda text: np.random.rand(384).tolist()
        mock_ollama_client_class.return_value = mock_client

        # Mock SemanticChunker to return mock chunks
        mock_chunker = MagicMock()
        from langchain_core.documents import Document as LCDocument

        mock_chunks = [
            LCDocument(
                page_content="First topic sentence. Another first topic sentence.",
                metadata={"start_index": 0},
            ),
            LCDocument(
                page_content="Second topic sentence. Another second topic sentence.",
                metadata={"start_index": 52},
            ),
        ]
        mock_chunker.create_documents.return_value = mock_chunks
        mock_semantic_chunker_class.return_value = mock_chunker

        # Create test data
        content = [
            "First topic sentence. Another first topic sentence. Second topic sentence. Another second topic sentence."
        ]
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)

        # Create operator with semantic chunking
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "granite4",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
        }

        operator = ChunkerOperator(config)

        # Transform
        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Assertions
        self.assertEqual(result_table.num_rows, 1)
        self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)

        # Check that chunks were created
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertIsNotNone(chunked_content)
        self.assertGreater(len(chunked_content), 0)

        # Verify mocks were used (no real Ollama calls or SemanticChunker)
        mock_ollama_client_class.assert_called_once()
        mock_semantic_chunker_class.assert_called_once()

    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_chunker_provider_config_host(self, mock_ollama_client_class):
        """Test that host in the provider_config is passed to OllamaClient."""

        mock_client_instance = MagicMock()
        mock_ollama_client_class.return_value = mock_client_instance

        config = {
            "chunk_type": "semantic",
            "semantic_embeddings_model": "nomic-embed-text",
            "provider_config": {
                "host": "http://test.server.com:11434",
            },
        }
        operator = ChunkerOperator(config)
        operator._get_ollama_client()

        mock_ollama_client_class.assert_called_once()
        call_kwargs = mock_ollama_client_class.call_args.kwargs
        assert call_kwargs["model_name"] == "nomic-embed-text", "Model name mismatch"
        assert call_kwargs["host"] == "http://test.server.com:11434", "Host not passed correctly"


def test_operator_metadata():
    """Test that operator returns correct metadata"""
    operator = ChunkerOperator({})

    operator_metadata = operator.get_metadata()

    # Check that metadata has required keys
    assert OperatorConstants.Misc.CATEGORY in operator_metadata
    assert OperatorConstants.Config.FEATURES in operator_metadata
    assert OperatorConstants.Config.ATTRIBUTES in operator_metadata
    assert operator_metadata[OperatorConstants.Misc.IS_OPERATOR_AVAILABLE] is True


class TestChunkerValidation(unittest.TestCase):
    """Test configuration validation"""

    def test_validate_chunk_size_in_range(self):
        """Test validation accepts valid chunk sizes"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertEqual(len(errors), 0, "Valid chunk size should not produce errors")

    def test_validate_chunk_size_too_small(self):
        """Test validation rejects chunk size below minimum"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": CHUNK_MIN_SIZE - 1,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk size below minimum should produce errors")

    def test_validate_chunk_size_too_large(self):
        """Test validation rejects chunk size above maximum"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": CHUNK_MAX_SIZE + 1,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk size above maximum should produce errors")

    def test_validate_chunk_overlap_too_large(self):
        """Test validation rejects chunk overlap above maximum"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_overlap": CHUNK_OVERLAP_MAX_SIZE + 1,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk overlap above maximum should produce errors")

    def test_validate_invalid_chunk_type(self):
        """Test validation rejects invalid chunk type"""
        config = {
            "chunk_type": "invalid_type",
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Invalid chunk type should produce errors")

    def test_validate_chunk_size_string_type(self):
        """Test validation rejects chunk_size with string type"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": "1000",  # String instead of int
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "String type for chunk_size should produce errors")
        # Check that the error message mentions the type issue
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("Invalid type for chunk_size" in msg for msg in error_messages),
            f"Expected type error for chunk_size, got: {error_messages}",
        )

    def test_validate_chunk_overlap_string_type(self):
        """Test validation rejects chunk_overlap with string type"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap": "200",  # String instead of int
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "String type for chunk_overlap should produce errors")
        # Check that the error message mentions the type issue
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("Invalid type for chunk_overlap" in msg for msg in error_messages),
            f"Expected type error for chunk_overlap, got: {error_messages}",
        )

    def test_validate_retain_original_content_string_type(self):
        """Test validation rejects retain_original_content with string type"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "retain_original_content": "true",  # String instead of bool
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "String type for retain_original_content should produce errors")
        # Check that the error message mentions the type issue
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("Invalid type for retain_original_content" in msg for msg in error_messages),
            f"Expected type error for retain_original_content, got: {error_messages}",
        )

    def test_validate_multiple_errors_collected(self):
        """Test that multiple validation errors are collected without early return"""
        config = {
            "chunk_type": "invalid_type",  # Invalid chunk_type
            "chunk_size": 1000,
            "chunk_overlap": -1,  # Invalid: negative
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        # Should have at least 2 errors: one for chunk_overlap and one for chunk_type
        self.assertGreaterEqual(len(errors), 2, f"Should collect multiple errors, got {len(errors)}: {errors}")

        # Verify both error types are present
        error_messages = " ".join(str(e) for e in errors)
        self.assertIn("chunk_overlap", error_messages.lower(), "Should have chunk_overlap error")
        self.assertIn("chunk_type", error_messages.lower(), "Should have chunk_type error")

    def test_validate_semantic_percentile_threshold_invalid(self):
        """Test validation rejects invalid percentile threshold"""
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "breakpoint_threshold_amount": 150.0,  # Invalid: > 100
            "semantic_embeddings_model": "granite4",
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Invalid percentile should produce errors")

    def test_validate_semantic_std_dev_threshold_negative(self):
        """Test validation rejects negative standard deviation threshold"""
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "breakpoint_threshold_type": BreakpointThresholdType.STANDARD_DEVIATION.value,
            "breakpoint_threshold_amount": -1.0,  # Invalid: negative
            "semantic_embeddings_model": "granite4",
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Negative std dev should produce errors")

    def test_validate_semantic_missing_embeddings_model(self):
        """Test validation rejects semantic chunking without embeddings model"""
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "doc_column": "content",
            # Missing semantic_embeddings_model
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Semantic chunking without embeddings model should produce errors")
        # Verify the error message mentions the missing model
        error_messages = " ".join(errors)
        self.assertIn("semantic_embeddings_model", error_messages.lower())

    def test_validate_semantic_multiple_errors(self):
        """Test validation collects multiple semantic chunking errors at once"""
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "doc_column": "content",
            # Missing semantic_embeddings_model
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "breakpoint_threshold_amount": 150,  # Invalid: must be 0-100 for percentile
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        # Should catch both errors: missing model AND invalid threshold
        self.assertEqual(len(errors), 2, "Should catch both missing model and invalid threshold errors")
        error_messages = " ".join(errors)
        self.assertIn("semantic_embeddings_model", error_messages.lower())
        self.assertIn("percentile", error_messages.lower())

    def test_validate_chunk_overlap_percentage_default(self):
        """Test that chunk_overlap_percentage defaults to 20 and produces no errors or warnings"""
        config = {"chunk_type": ChunkType.SIMPLE.value, "chunk_size": 1000, "doc_column": "content"}
        operator = ChunkerOperator(config)
        self.assertEqual(operator.chunk_overlap_percentage, 20)
        errors: list = []
        warnings: list = []
        operator.validate(errors, warnings, ["content"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 0)


@pytest.mark.parametrize("percentage", [0, 15, 20])
def test_validate_chunk_overlap_percentage_valid_no_warning(percentage):
    """chunk_overlap_percentage within range and <= 20 produces no errors or warnings"""
    operator = ChunkerOperator(
        {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap_percentage": percentage,
            "doc_column": "content",
        }
    )
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])
    assert errors == []
    assert warnings == []


@pytest.mark.parametrize("percentage", [21, 30, 40])
def test_validate_chunk_overlap_percentage_above_threshold_warns(percentage):
    """chunk_overlap_percentage above 20 but within [0, 40] produces a warning, not an error"""
    operator = ChunkerOperator(
        {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap_percentage": percentage,
            "doc_column": "content",
        }
    )
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])
    assert errors == []
    assert len(warnings) == 1
    assert "chunk_overlap_percentage" in str(warnings[0])


@pytest.mark.parametrize("percentage", [-1, 41, 100])
def test_validate_chunk_overlap_percentage_out_of_range_errors(percentage):
    """chunk_overlap_percentage outside [0, 40] produces an error"""
    operator = ChunkerOperator(
        {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "chunk_overlap_percentage": percentage,
            "doc_column": "content",
        }
    )
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])
    assert len(errors) == 1
    assert "chunk_overlap_percentage" in str(errors[0])


def test_validate_chunk_overlap_percentage_ignored_for_semantic():
    """chunk_overlap_percentage is not validated for semantic chunk type — it has no meaning there"""
    operator = ChunkerOperator(
        {
            "chunk_type": ChunkType.SEMANTIC.value,
            "chunk_overlap_percentage": 99,  # Out of range — would error if validated
            "semantic_embeddings_model": "granite4",
            "doc_column": "content",
        }
    )
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])
    overlap_errors = [e for e in errors if "chunk_overlap_percentage" in str(e)]
    assert overlap_errors == [], (
        f"chunk_overlap_percentage should not be validated for semantic chunking, got: {overlap_errors}"
    )


class TestChunkerEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def test_empty_table(self):
        """Test chunking with an empty table"""
        data: dict[str, list] = {
            OperatorConstants.Columns.ID: [],
            OperatorConstants.Columns.NAME: [],
            "content": [],
        }
        empty_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, metadata = operator.transform(empty_table)

        # Should return empty table
        self.assertEqual(result_tables[0].num_rows, 0)
        self.assertEqual(metadata["documents_in_scope"], 0)

    def test_multiple_documents(self):
        """Test chunking with multiple documents"""
        content = [
            "First document with some content.",
            "Second document with different content.",
            "Third document with unique text.",
        ]
        data = {
            OperatorConstants.Columns.ID: ["doc1", "doc2", "doc3"],
            OperatorConstants.Columns.NAME: ["Doc 1", "Doc 2", "Doc 3"],
            "content": content,
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Should process all documents
        self.assertEqual(result_table.num_rows, 3)
        self.assertEqual(metadata["documents_in_scope"], 3)

    def test_default_removes_original_content(self):
        """Test that original content is removed by default"""
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content for chunking."],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        self.assertNotIn("content", result_table.column_names)

    def test_retain_original_content(self):
        """Test that original content is retained when configured"""
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content for chunking."],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "retain_original_content": True,
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        self.assertIn("content", result_table.column_names)
        original_content = result_table["content"][0].as_py()
        self.assertEqual(original_content, "Test content for chunking.")

    def test_missing_content_column_records_failed_documents(self):
        """A missing content column reports each document instead of aborting finalization."""
        input_table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1", "doc2"],
                OperatorConstants.Columns.NAME: ["Document 1", "Document 2"],
                "body": ["First document", "Second document"],
            }
        )
        for retain_original_content in (False, True):
            with self.subTest(retain_original_content=retain_original_content):
                operator = ChunkerOperator(
                    {
                        "chunk_type": ChunkType.SIMPLE.value,
                        "retain_original_content": retain_original_content,
                    }
                )

                result_tables, metadata = operator.transform(input_table)
                result_table = result_tables[0]

                self.assertEqual(result_table.num_rows, 0)
                self.assertEqual(result_table.column_names, input_table.column_names)
                self.assertEqual(metadata["failed_docs_count"], 2)
                self.assertEqual(len(metadata["failed_docs"]), 2)
                self.assertTrue(
                    all("column 'content' was not found" in doc["reason"] for doc in metadata["failed_docs"])
                )

    def test_mixed_successful_and_failed_documents_preserve_schema(self):
        """Failed rows are removed while successful rows keep the configured schema behavior."""
        input_table = pa.table(
            {
                OperatorConstants.Columns.ID: ["success", "failure"],
                OperatorConstants.Columns.NAME: ["Successful document", "Failed document"],
                "content": ["Content that can be chunked.", None],
            }
        )
        for retain_original_content in (False, True):
            with self.subTest(retain_original_content=retain_original_content):
                operator = ChunkerOperator(
                    {
                        "chunk_type": ChunkType.SIMPLE.value,
                        "chunk_size": 1000,
                        "retain_original_content": retain_original_content,
                    }
                )

                result_tables, metadata = operator.transform(input_table)
                result_table = result_tables[0]

                self.assertEqual(result_table.num_rows, 1)
                self.assertEqual(result_table[OperatorConstants.Columns.ID].to_pylist(), ["success"])
                self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)
                self.assertEqual("content" in result_table.column_names, retain_original_content)
                self.assertEqual(metadata["processed_docs"], 1)
                self.assertEqual(metadata["failed_docs_count"], 1)

    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_chunker_different_breakpoint_types(self, mock_ollama_client_class, mock_semantic_chunker_class):
        """Test semantic chunking with different breakpoint types - fully mocked"""
        # Mock the OllamaClient to avoid any real API calls
        mock_client = MagicMock()
        # Mock generate_embeddings to return different embeddings for each call
        mock_client.generate_embeddings.side_effect = lambda text: np.random.rand(384).tolist()
        mock_ollama_client_class.return_value = mock_client

        # Mock SemanticChunker to return mock chunks
        mock_chunker = MagicMock()
        from langchain_core.documents import Document as LCDocument

        mock_chunks = [
            LCDocument(
                page_content="Test content with multiple sentences.",
                metadata={"start_index": 0},
            ),
            LCDocument(page_content="Another sentence here.", metadata={"start_index": 38}),
        ]
        mock_chunker.create_documents.return_value = mock_chunks
        mock_semantic_chunker_class.return_value = mock_chunker

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content with multiple sentences. Another sentence here."],
        }
        input_table = pa.table(data)

        breakpoint_types = [
            BreakpointThresholdType.PERCENTILE.value,
            BreakpointThresholdType.STANDARD_DEVIATION.value,
            BreakpointThresholdType.INTERQUARTILE.value,
            BreakpointThresholdType.GRADIENT.value,
        ]

        for breakpoint_type in breakpoint_types:
            config = {
                "chunk_type": ChunkType.SEMANTIC.value,
                "semantic_embeddings_model": "granite4",
                "breakpoint_threshold_type": breakpoint_type,
                "doc_column": "content",
            }
            operator = ChunkerOperator(config)

            result_tables, _metadata = operator.transform(input_table)
            result_table = result_tables[0]

            # Should successfully process with any breakpoint type
            self.assertEqual(result_table.num_rows, 1)
            self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)

        # Verify mocks were used for all breakpoint types (no real Ollama calls)
        self.assertEqual(mock_ollama_client_class.call_count, len(breakpoint_types))
        self.assertEqual(mock_semantic_chunker_class.call_count, len(breakpoint_types))


class TestSplitterLazyInit(unittest.TestCase):
    """Test lazy initialisation and caching of simple and semantic splitters"""

    def test_simple_splitter_is_cached(self):
        """_get_simple_splitter returns the same instance on repeated calls"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 500,
            "chunk_overlap": 50,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        splitter_first = operator._get_simple_splitter()
        splitter_second = operator._get_simple_splitter()

        self.assertIs(splitter_first, splitter_second, "_get_simple_splitter must return the cached instance")

    def test_simple_splitter_none_before_first_call(self):
        """_simple_splitter attribute is None until _get_simple_splitter is called"""
        config = {"chunk_type": ChunkType.SIMPLE.value, "doc_column": "content"}
        operator = ChunkerOperator(config)

        self.assertIsNone(operator._simple_splitter)
        operator._get_simple_splitter()
        self.assertIsNotNone(operator._simple_splitter)

    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_splitter_is_cached(self, mock_ollama_client_class, mock_semantic_chunker_class):
        """_get_semantic_splitter returns the same instance on repeated calls"""
        mock_ollama_client_class.return_value = MagicMock()
        mock_chunker_instance = MagicMock()
        mock_semantic_chunker_class.return_value = mock_chunker_instance

        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "nomic-embed-text",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        splitter_first = operator._get_semantic_splitter()
        splitter_second = operator._get_semantic_splitter()

        self.assertIs(splitter_first, splitter_second, "_get_semantic_splitter must return the cached instance")
        # SemanticChunker constructor called exactly once, not twice
        mock_semantic_chunker_class.assert_called_once()

    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_splitter_none_before_first_call(self, mock_ollama_client_class, mock_semantic_chunker_class):
        """_semantic_splitter attribute is None until _get_semantic_splitter is called"""
        mock_ollama_client_class.return_value = MagicMock()
        mock_semantic_chunker_class.return_value = MagicMock()

        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "nomic-embed-text",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        self.assertIsNone(operator._semantic_splitter)
        operator._get_semantic_splitter()
        self.assertIsNotNone(operator._semantic_splitter)

    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_splitter_wraps_generic_exception(self, mock_ollama_client_class):
        """Non-DocpipeException errors during SemanticChunker init are wrapped in DocpipeException"""
        mock_ollama_client_class.return_value = MagicMock()

        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "nomic-embed-text",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        with patch(
            "langchain_experimental.text_splitter.SemanticChunker", side_effect=RuntimeError("model load failed")
        ):
            with self.assertRaises(DocpipeException) as ctx:
                operator._get_semantic_splitter()

        self.assertIn("Failed to initialize SemanticChunker", str(ctx.exception))
        self.assertIn("model load failed", str(ctx.exception))

    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_splitter_passes_through_docpipe_exception(self, mock_ollama_client_class):
        """DocpipeException from _get_ollama_client is re-raised unchanged"""
        mock_ollama_client_class.side_effect = DocpipeException("Ollama unavailable")

        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "semantic_embeddings_model": "nomic-embed-text",
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        with self.assertRaises(DocpipeException) as ctx:
            operator._get_semantic_splitter()

        # Must preserve the original message, not double-wrap it
        self.assertIn("Ollama unavailable", str(ctx.exception))
        self.assertNotIn("Failed to initialize SemanticChunker", str(ctx.exception))


class TestDoclingChunking(unittest.TestCase):
    """Test Docling chunking functionality integrated into ChunkerOperator"""

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_chunking_initialization(self, mock_hybrid_chunker_class):
        """Test operator initialization with docling chunking config"""
        # Mock the HybridChunker
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "docling_tokenizer": "sentence-transformers/all-MiniLM-L6-v2",
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        self.assertIsNotNone(operator)
        self.assertEqual(operator.chunk_type, ChunkType.HYBRID.value)
        self.assertEqual(operator.chunk_size, 512)
        self.assertEqual(operator.docling_tokenizer, "sentence-transformers/all-MiniLM-L6-v2")

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_chunking_transform(self, mock_hybrid_chunker_class):
        """Test docling chunking with a PyArrow table"""
        # Mock the HybridChunker and its chunk method
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        # Create mock chunks
        mock_chunk1 = MagicMock()
        mock_chunk1.text = "First chunk of text."
        mock_chunk1.start_index = 0

        mock_chunk2 = MagicMock()
        mock_chunk2.text = "Second chunk of text."
        mock_chunk2.start_index = 100

        mock_chunker.chunk.return_value = iter([mock_chunk1, mock_chunk2])

        # Create test data
        content = ["This is a test document with some content. It has multiple sentences. This helps test chunking."]
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)

        # Create operator with docling chunking
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "docling_tokenizer": "sentence-transformers/all-MiniLM-L6-v2",
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        # Transform
        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Assertions
        self.assertEqual(result_table.num_rows, 1)
        self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)

        # Check that chunks were created
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertIsNotNone(chunked_content)
        self.assertGreater(len(chunked_content), 0)

    def test_docling_validation_chunk_size_valid(self):
        """Test validation accepts valid chunk size for docling"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertEqual(len(errors), 0, "Valid chunk size should not produce errors")

    def test_docling_validation_chunk_size_too_small(self):
        """Test validation rejects chunk size below minimum for hybrid chunking (100 tokens)"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 50,  # Below DOCLING_CHUNK_SIZE_MIN (100)
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk size below minimum should produce errors")

    def test_docling_validation_chunk_size_too_large(self):
        """Test validation rejects chunk size above maximum for docling (2048 tokens)"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 3000,  # Above DOCLING_CHUNK_SIZE_MAX (2048)
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk size above maximum should produce errors")

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_multiple_documents(self, mock_hybrid_chunker_class):
        """Test docling chunking with multiple documents"""
        # Mock the HybridChunker
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        # Create mock chunks
        mock_chunk1 = MagicMock()
        mock_chunk1.text = "Chunk text."
        mock_chunk1.start_index = 0

        mock_chunker.chunk.return_value = iter([mock_chunk1])

        content = [
            "First document with short content.",
            "Second document with different content.",
            "Third document with unique text.",
        ]
        data = {
            OperatorConstants.Columns.ID: ["doc1", "doc2", "doc3"],
            OperatorConstants.Columns.NAME: ["Doc 1", "Doc 2", "Doc 3"],
            "content": content,
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Should process all documents
        self.assertEqual(result_table.num_rows, 3)
        self.assertEqual(metadata["documents_in_scope"], 3)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_default_removes_original_content(self, mock_hybrid_chunker_class):
        """Test that original content is removed by default for docling"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk text."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content for chunking."],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        self.assertNotIn("content", result_table.column_names)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_retain_original_content(self, mock_hybrid_chunker_class):
        """Test that original content is retained when configured for docling"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk text."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content for chunking."],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
            "retain_original_content": True,
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Original content column should exist
        self.assertIn("content", result_table.column_names)
        original_content = result_table["content"][0].as_py()
        self.assertEqual(original_content, "Test content for chunking.")

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_remove_original_content(self, mock_hybrid_chunker_class):
        """Test that original content is removed when configured for docling"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk text."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content for chunking."],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
            "retain_original_content": False,
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Original content column should be removed
        self.assertNotIn("content", result_table.column_names)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_empty_content(self, mock_hybrid_chunker_class):
        """Test docling handles empty content gracefully"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker
        mock_chunker.chunk.return_value = iter([])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Empty Document"],
            "content": [""],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        _result_tables, metadata = operator.transform(input_table)

        # Should record as failed document
        self.assertGreater(metadata.get("failed_docs_count", 0), 0)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_long_document(self, mock_hybrid_chunker_class):
        """Test docling with long document requiring multiple chunks"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        # Create multiple mock chunks
        mock_chunks = []
        for i in range(5):
            mock_chunk = MagicMock()
            mock_chunk.text = f"Chunk {i} text."
            mock_chunk.start_index = i * 100
            mock_chunks.append(mock_chunk)

        mock_chunker.chunk.return_value = iter(mock_chunks)

        long_text = "This is a sentence. " * 200  # ~4000 chars
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Long Document"],
            "content": [long_text],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Check that multiple chunks were created
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertGreater(len(chunked_content), 1, "Long document should create multiple chunks")

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_preserves_all_columns(self, mock_hybrid_chunker_class):
        """Test docling preserves all original columns"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk text."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": ["Test content"],
            "extra_col1": ["value1"],
            "extra_col2": [42],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # All original columns should be preserved
        self.assertIn("extra_col1", result_table.column_names)
        self.assertIn("extra_col2", result_table.column_names)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_with_special_characters(self, mock_hybrid_chunker_class):
        """Test docling handles special characters in content"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Special chars chunk."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Special Doc"],
            "content": ["Content with special chars: @#$%^&*()_+-=[]{}|;':\",./<>?"],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        _result_tables, metadata = operator.transform(input_table)

        # Should process successfully
        self.assertEqual(metadata["documents_in_scope"], 1)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_with_unicode(self, mock_hybrid_chunker_class):
        """Test docling handles Unicode characters"""
        mock_chunker = MagicMock()
        mock_hybrid_chunker_class.return_value = mock_chunker

        mock_chunk = MagicMock()
        mock_chunk.text = "Unicode chunk."
        mock_chunk.start_index = 0
        mock_chunker.chunk.return_value = iter([mock_chunk])

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Unicode Doc"],
            "content": ["Content with Unicode: 你好世界 مرحبا العالم Привет мир"],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)

        _result_tables, metadata = operator.transform(input_table)

        # Should process successfully
        self.assertEqual(metadata["documents_in_scope"], 1)

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_docling_markdown_produces_structured_document(self, mock_hybrid_chunker_class):
        """Verifies that _create_docling_document_from_markdown uses MarkdownDocumentBackend
        so the DoclingDocument passed to HybridChunker.chunk() contains typed heading nodes
        (title / section_header), not a flat list of plain TEXT nodes.
        """
        captured_docs: list = []

        def capture_and_return_chunks(dl_doc):
            captured_docs.append(dl_doc)
            # Return one mock chunk so the operator produces output
            mock_chunk = MagicMock()
            mock_chunk.text = "chunk text"
            mock_chunk.start_index = 0
            return iter([mock_chunk])

        mock_chunker = MagicMock()
        mock_chunker.chunk.side_effect = capture_and_return_chunks
        mock_hybrid_chunker_class.return_value = mock_chunker

        markdown_content = (
            "# Introduction\n\n"
            "First paragraph of the document.\n\n"
            "## Section One\n\n"
            "Content of section one.\n\n"
            "## Section Two\n\n"
            "Content of section two.\n"
        )
        data: dict[str, list] = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["structured.md"],
            "content": [markdown_content],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        operator.transform(input_table)

        # HybridChunker.chunk must have been called with a DoclingDocument
        self.assertEqual(len(captured_docs), 1, "HybridChunker.chunk should be called once")
        docling_doc = captured_docs[0]

        # Collect all item labels from the DoclingDocument
        labels = [str(item.label) for item, _ in docling_doc.iterate_items()]

        # The document must contain at least one heading node (title or section_header).
        # A flat TEXT-only document would have no such labels — that was the pre-fix behaviour.
        heading_labels = {"title", "section_header"}
        found_headings = [lbl for lbl in labels if lbl in heading_labels]
        self.assertGreater(
            len(found_headings),
            0,
            f"Expected heading nodes in DoclingDocument but only found: {labels}",
        )

        # Must also contain text body nodes (not just headings)
        self.assertIn("text", labels, "Expected text body nodes in DoclingDocument")

    def test_docling_validation_chunk_overlap_negative(self):
        """Test validation rejects negative chunk overlap for docling"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "chunk_overlap": -10,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Negative chunk overlap should produce errors")

    def test_docling_validation_chunk_overlap_exceeds_size(self):
        """Test validation rejects chunk overlap >= chunk_size for docling"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "chunk_overlap": 512,
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        self.assertGreater(len(errors), 0, "Chunk overlap >= chunk_size should produce errors")

    def test_docling_validation_empty_tokenizer(self):
        """Test validation rejects empty tokenizer and negative chunk_overlap for docling"""
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "chunk_overlap": -1,  # Invalid: negative
            "docling_tokenizer": "",  # Invalid: empty
            "doc_column": "content",
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])

        # Should have exactly 2 errors:
        # 1. chunk_overlap must be non-negative (from common validation)
        # 2. docling_tokenizer cannot be empty for hybrid chunking
        self.assertEqual(len(errors), 2, f"Should have exactly 2 errors, got {len(errors)}: {errors}")

        # Verify both types of errors are present
        error_messages = " ".join(errors)
        self.assertIn("docling_tokenizer", error_messages.lower())
        self.assertIn("chunk_overlap", error_messages.lower())


class TestChunkerSummarization(unittest.TestCase):
    """Test Chunker summarization functionality with multi-provider support"""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_initialization_litellm(self, mock_factory):
        """Test operator initialization with LiteLLM summarization config"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "llama3.2:3b",
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "<api-key>",
                },
            },
        }
        operator = ChunkerOperator(config)

        self.assertTrue(operator.enable_summarization)
        self.assertEqual(operator.summarization_provider, "litellm")
        self.assertEqual(operator.summarization_model, "openai/llama3.2:3b")

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_initialization_watsonx(self, mock_factory):
        """Test operator initialization with WatsonX summarization config (nested structure)"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {
                "provider": "watsonx",
                "provider_config": {
                    "model_id": "ibm/granite-13b-chat-v2",
                    "api_key": "<api-key>",
                    "project_id": "test_project",
                },
            },
        }
        operator = ChunkerOperator(config)

        self.assertTrue(operator.enable_summarization)
        self.assertEqual(operator.summarization_provider, "watsonx")
        self.assertEqual(operator.summarization_model, "ibm/granite-13b-chat-v2")

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_initialization_flat_config_backward_compat(self, mock_factory):
        """Test backward compatibility with flat config structure"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        # Nested structure is now the only supported format
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "llama3.2:3b",
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "<api-key>",
                },
            },
        }
        operator = ChunkerOperator(config)

        self.assertTrue(operator.enable_summarization)
        self.assertEqual(operator.summarization_provider, "litellm")
        self.assertEqual(operator.summarization_model, "openai/llama3.2:3b")

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_backward_compatibility(self, mock_factory):
        """Test auto-configuration when provider_config is empty"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        # Config with enabled but empty provider_config triggers auto-configuration
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {
                "provider": "litellm",
                "provider_config": {},  # Empty dict triggers auto-config
            },
        }
        operator = ChunkerOperator(config)

        # Should auto-configure with Ollama defaults
        self.assertTrue(operator.enable_summarization)
        self.assertEqual(operator.summarization_provider, "litellm")
        self.assertEqual(operator.summarization_model, "openai/granite4")  # Default model with prefix
        self.assertEqual(operator.summarization_provider_config["api_base"], "http://localhost:11434/v1")
        self.assertEqual(operator.summarization_provider_config["api_key"], "<ollama>")

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_model_auto_prefix(self, mock_factory):
        """Test automatic prefixing of model names with 'openai/' for LiteLLM"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        # Model without prefix
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "model_id": "granite4"},
        }
        operator = ChunkerOperator(config)
        self.assertEqual(operator.summarization_model, "openai/granite4")

        # Model already with prefix
        config["summarization"]["model_id"] = "openai/granite4"
        operator = ChunkerOperator(config)
        self.assertEqual(operator.summarization_model, "openai/granite4")

    def test_summarization_disabled_by_default(self):
        """Test that summarization is disabled by default"""
        config = {"chunk_type": ChunkType.SIMPLE.value, "chunk_size": 1000, "doc_column": "content"}
        operator = ChunkerOperator(config)

        self.assertFalse(operator.enable_summarization)
        self.assertIsNone(operator._summarization_service)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_lazy_initialization(self, mock_factory):
        """Test that summarization service is lazily initialized during transform() when summarization is enabled"""
        mock_adapter = MagicMock()
        mock_adapter.chat.return_value = "Summary text."
        mock_factory.create_inference_adapter.return_value = mock_adapter

        # Summarization disabled - service should not be created
        config = {"chunk_type": ChunkType.SIMPLE.value, "doc_column": "content", "summarization": {}}
        operator = ChunkerOperator(config)
        self.assertIsNone(operator._summarization_service)
        mock_factory.create_inference_adapter.assert_not_called()

        # Summarization enabled - service should be lazily created during transform()
        config["summarization"]["provider"] = "litellm"
        config["summarization"]["model_id"] = "granite4"
        operator = ChunkerOperator(config)
        # Service is NOT created during __init__ - it's lazy
        self.assertIsNone(operator._summarization_service)
        mock_factory.create_inference_adapter.assert_not_called()

        # Now call transform() to trigger lazy initialization
        content = ["This is a test document with some content."]
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)
        operator.transform(input_table)

        # After transform(), service should be initialized
        self.assertIsNotNone(operator._summarization_service)
        mock_factory.create_inference_adapter.assert_called_once()

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_with_chunking(self, mock_factory):
        """Test summarization integrated with chunking"""
        mock_adapter = MagicMock()
        mock_adapter.chat.return_value = "This is a summary of the chunk."
        mock_factory.create_inference_adapter.return_value = mock_adapter

        content = ["This is a test document. " * 50]  # Long enough to create chunks
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 500,
            "chunk_overlap": 100,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "model_id": "granite4"},
        }
        operator = ChunkerOperator(config)

        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Should have chunks with summaries
        self.assertEqual(result_table.num_rows, 1)
        chunked_content = result_table[OperatorConstants.Columns.CHUNKED_CONTENT][0].as_py()
        self.assertGreater(len(chunked_content), 0)

        # Verify LLM was called for summarization
        self.assertGreater(mock_adapter.chat.call_count, 0)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_parameters(self, mock_factory):
        """Test summarization with custom parameters"""
        mock_adapter = MagicMock()
        mock_adapter.chat.return_value = "Summary text."
        mock_factory.create_inference_adapter.return_value = mock_adapter

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {
                "provider": "litellm",
                "provider_config": {"model_id": "granite4"},
                "max_input_tokens": 4000,
                "overlap_ratio": 0.3,
                "summary_sentences": 3,
                "summary_max_words": 30,
            },
        }
        operator = ChunkerOperator(config)

        self.assertEqual(operator.max_length, 4000)
        self.assertEqual(operator.overlap_ratio, 0.3)
        self.assertEqual(operator.summary_sentences, 3)
        self.assertEqual(operator.summary_max_words, 30)

    def test_summarization_validation_max_input_tokens(self):
        """Test validation of max_input_tokens parameter"""
        # Valid range
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "max_input_tokens": 8000},
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])
        self.assertEqual(len(errors), 0)

        # Below minimum
        config["summarization"]["max_input_tokens"] = 500
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

        # Above maximum
        config["summarization"]["max_input_tokens"] = 40000
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

    def test_summarization_validation_summary_sentences(self):
        """Test validation of summary_sentences parameter"""
        # Valid range
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "summary_sentences": 3},
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])
        self.assertEqual(len(errors), 0)

        # Below minimum
        config["summarization"]["summary_sentences"] = 0
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

        # Above maximum
        config["summarization"]["summary_sentences"] = 10
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

    def test_summarization_validation_summary_max_words(self):
        """Test validation of summary_max_words parameter"""
        # Valid range
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "summary_max_words": 50},
        }
        operator = ChunkerOperator(config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, ["content"])
        self.assertEqual(len(errors), 0)

        # Below minimum
        config["summarization"]["summary_max_words"] = 5
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

        # Above maximum
        config["summary_max_words"] = 150
        operator = ChunkerOperator(config)
        errors = []
        warnings = []
        operator.validate(errors, warnings, ["content"])
        self.assertGreater(len(errors), 0)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_graceful_failure(self, mock_factory):
        """Test that summarization failures are handled gracefully"""
        mock_adapter = MagicMock()
        mock_adapter.chat.side_effect = Exception("LLM service unavailable")
        mock_factory.create_inference_adapter.return_value = mock_adapter

        content = ["This is a test document with some content."]
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 1000,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "model_id": "granite4"},
        }
        operator = ChunkerOperator(config)

        # Should not raise exception, but handle gracefully
        result_tables, _metadata = operator.transform(input_table)
        result_table = result_tables[0]

        # Should still produce chunks even if summarization fails
        self.assertEqual(result_table.num_rows, 1)
        self.assertIn(OperatorConstants.Columns.CHUNKED_CONTENT, result_table.column_names)

    def test_summarization_metadata(self):
        """Test that summarization parameters are included in metadata"""
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {
                "provider": "litellm",
                "provider_config": {"model_id": "granite4"},
            },
        }
        operator = ChunkerOperator(config)
        metadata = operator.get_metadata()

        # Check that summarization attributes are in metadata
        # attributes is a dict, not a list
        attributes = metadata["attributes"]
        self.assertIsInstance(attributes, dict)

        # Check that summarization nested structure is present
        self.assertIn("summarization", attributes)
        summarization = attributes["summarization"]
        self.assertIn("properties", summarization)

        # Check nested properties
        props = summarization["properties"]
        self.assertIn("provider", props)
        self.assertIn("provider_config", props)
        self.assertIn("max_input_tokens", props)
        self.assertIn("summary_sentences", props)
        self.assertIn("summary_max_words", props)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory")
    def test_summarization_empty_document(self, mock_factory):
        """Test summarization with empty document"""
        mock_adapter = MagicMock()
        mock_factory.create_inference_adapter.return_value = mock_adapter

        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Empty Document"],
            "content": [""],
        }
        input_table = pa.table(data)

        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "doc_column": "content",
            "summarization": {"provider": "litellm", "model_id": "granite4"},
        }
        operator = ChunkerOperator(config)

        _result_tables, metadata = operator.transform(input_table)

        # Should handle empty content gracefully
        self.assertEqual(metadata["documents_in_scope"], 1)
        # LLM should not be called for empty content

    def test_summarization_service_validation_called_on_init(self):
        """Test that validate() is called during summarization service initialization."""
        from docpipe.core.operators.functional.summarization_service import SummarizationService

        mock_adapter = MagicMock()
        mock_adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}

        _ = SummarizationService(llm_adapter=mock_adapter)

        # Verify adapter was validated
        mock_adapter.validate.assert_called_once()

    def test_summarization_service_validation_failure_raises_error(self):
        """Test that validation failures raise DocpipeException."""
        from docpipe.core.operators.functional.summarization_service import SummarizationService

        mock_adapter = MagicMock()
        mock_adapter.validate.return_value = {"valid": False, "errors": ["API key is required"], "warnings": []}

        with self.assertRaises(DocpipeException) as context:
            SummarizationService(llm_adapter=mock_adapter)

        self.assertIn("API key is required", str(context.exception))

    def test_summarization_service_validation_with_warnings(self):
        """Test that warnings don't block service initialization."""
        from docpipe.core.operators.functional.summarization_service import SummarizationService

        mock_adapter = MagicMock()
        mock_adapter.validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": ["Consider setting api_base for better performance"],
        }

        service = SummarizationService(llm_adapter=mock_adapter)

        # Service should be created successfully
        self.assertIsNotNone(service)
        mock_adapter.chat.assert_not_called()

    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_semantic_chunking_missing_embeddings_model(self, mock_ollama_client_class):
        """Test that semantic chunking provides clear error when semantic_embeddings_model is missing"""
        # Create test data
        content = ["Test content for semantic chunking."]
        data = {
            OperatorConstants.Columns.ID: ["doc1"],
            OperatorConstants.Columns.NAME: ["Document 1"],
            "content": content,
        }
        input_table = pa.table(data)

        # Create operator with semantic chunking but WITHOUT semantic_embeddings_model
        config = {
            "chunk_type": ChunkType.SEMANTIC.value,
            "breakpoint_threshold_type": BreakpointThresholdType.PERCENTILE.value,
            "doc_column": "content",
            # Note: semantic_embeddings_model is intentionally missing
        }

        operator = ChunkerOperator(config)

        # Transform should handle the error gracefully and record it in metadata
        _, metadata = operator.transform(input_table)

        # Verify the error was recorded in failed documents
        self.assertIn("failed_docs", metadata)
        failed_docs = metadata["failed_docs"]
        self.assertEqual(len(failed_docs), 1)

        # Verify the error message is clear and mentions semantic_embeddings_model
        error_reason = failed_docs[0]["reason"]
        self.assertIn("semantic_embeddings_model", error_reason.lower())
        self.assertIn("required", error_reason.lower())
        self.assertIn("semantic chunking", error_reason.lower())

        # Verify that OllamaClient was never instantiated (error caught before that)
        mock_ollama_client_class.assert_not_called()


class TestDoclingServeValidation:
    """Tests for validate() with provider='docling_serve'."""

    def _make_operator(self, provider_config: dict) -> ChunkerOperator:
        config = {
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "provider": "docling_serve",
            "provider_config": provider_config,
            "doc_column": "content",
        }
        return ChunkerOperator(config)

    def test_validate_missing_api_base_produces_error(self):
        op = self._make_operator({})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("API base URL is required" in str(e) for e in errors)

    def test_validate_negative_timeout_produces_error(self):
        op = self._make_operator({"api_base": "http://localhost:5001", "timeout": -1})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("Timeout must be positive" in str(e) for e in errors)

    def test_validate_zero_timeout_produces_error(self):
        op = self._make_operator({"api_base": "http://localhost:5001", "timeout": 0})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("Timeout must be positive" in str(e) for e in errors)

    def test_validate_negative_poll_interval_produces_error(self):
        op = self._make_operator({"api_base": "http://localhost:5001", "poll_interval": -1})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("Poll interval must be positive" in str(e) for e in errors)

    def test_validate_negative_max_retries_produces_error(self):
        op = self._make_operator({"api_base": "http://localhost:5001", "max_retries": -1})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("Max retries must be non-negative" in str(e) for e in errors)

    def test_validate_zero_max_retries_is_valid(self):
        op = self._make_operator({"api_base": "http://localhost:5001", "max_retries": 0})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert not any("Max retries" in str(e) for e in errors)

    def test_validate_non_hybrid_chunk_type_produces_warning(self):
        config = {
            "chunk_type": ChunkType.SIMPLE.value,
            "chunk_size": 512,
            "provider": "docling_serve",
            "provider_config": {"api_base": "http://localhost:5001"},
            "doc_column": "content",
        }
        op = ChunkerOperator(config)
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert any("chunk_type" in str(w) for w in warnings)

    def test_validate_valid_docling_serve_config_no_errors(self):
        op = self._make_operator({"api_base": "http://localhost:5001"})
        errors: list = []
        warnings: list = []
        op.validate(errors, warnings, ["content"])
        assert errors == []
        assert warnings == []


class TestDoclingServeClient:
    """Tests for _get_docling_serve_client lazy initialization."""

    @patch("docpipe.integrations.rest_client.RestClient")
    @patch("docpipe.integrations.rest_client.RestClientConfig")
    def test_client_initialized_with_correct_params(self, mock_config_cls, mock_client_cls):
        mock_rest = MagicMock()
        mock_client_cls.return_value = mock_rest

        config = {
            "provider": "docling_serve",
            "provider_config": {
                "api_base": "http://localhost:5001",
                "timeout": 60,
                "max_retries": 2,
                "verify_ssl": False,
            },
        }
        op = ChunkerOperator(config)
        client = op._get_docling_serve_client()

        assert client is mock_rest
        mock_config_cls.assert_called_once_with(timeout=60, max_retries=2, verify_ssl=False)

    @patch("docpipe.integrations.rest_client.RestClient")
    @patch("docpipe.integrations.rest_client.RestClientConfig")
    def test_client_cached_on_second_call(self, mock_config_cls, mock_client_cls):
        mock_rest = MagicMock()
        mock_client_cls.return_value = mock_rest

        config = {
            "provider": "docling_serve",
            "provider_config": {"api_base": "http://localhost:5001"},
        }
        op = ChunkerOperator(config)
        client1 = op._get_docling_serve_client()
        client2 = op._get_docling_serve_client()

        assert client1 is client2
        assert mock_client_cls.call_count == 1

    def test_client_initialization_failure_raises_docpipe_exception(self):
        config = {
            "provider": "docling_serve",
            "provider_config": {"api_base": "http://localhost:5001"},
        }
        op = ChunkerOperator(config)

        with patch("docpipe.integrations.rest_client.RestClientConfig", side_effect=RuntimeError("network")):
            with pytest.raises(DocpipeException, match="Failed to initialize docling-serve HTTP client"):
                op._get_docling_serve_client()


class TestDoclingServeSplitText:
    """Tests for _docling_serve_split_text."""

    def _make_op(self) -> ChunkerOperator:
        return ChunkerOperator(
            {
                "provider": "docling_serve",
                "chunk_type": ChunkType.HYBRID.value,
                "chunk_size": 512,
                "provider_config": {"api_base": "http://localhost:5001"},
            }
        )

    def test_returns_documents_from_valid_response(self):
        op = self._make_op()
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = {
            "chunks": [
                {"text": "First chunk.", "start_index": 0},
                {"text": "Second chunk.", "start_index": 50},
            ]
        }
        op._remote_chunking_client = mock_client

        docs = op._docling_serve_split_text(content="some content", doc_name="doc.md")
        assert len(docs) == 2
        assert docs[0].page_content == "First chunk."
        assert docs[1].page_content == "Second chunk."

    @pytest.mark.parametrize(
        ("doc_name", "expected_filename"),
        [("report.pdf", "report.md"), ("notes.md", "notes.md"), ("notes", "notes.md"), (None, "document.md")],
    )
    def test_markdown_payload_uses_markdown_filename(self, doc_name: str | None, expected_filename: str) -> None:
        op = self._make_op()
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = {"chunks": [{"text": "A chunk"}]}
        op._remote_chunking_client = mock_client

        docs = op._docling_serve_split_text(content="# Heading", doc_name=doc_name)

        payload = mock_client.call_rest_json.call_args.kwargs["json_data"]
        assert payload["sources"][0]["filename"] == expected_filename
        assert payload["convert_options"]["from_formats"] == ["md"]
        assert docs[0].metadata["doc_name"] == doc_name

    def test_returns_empty_list_when_no_chunks(self):
        op = self._make_op()
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = {"chunks": []}
        op._remote_chunking_client = mock_client

        docs = op._docling_serve_split_text(content="content", doc_name=None)
        assert docs == []

    def test_invalid_response_type_raises_docpipe_exception(self):
        op = self._make_op()
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = "not a dict"
        op._remote_chunking_client = mock_client

        with pytest.raises(DocpipeException, match="Docling-serve chunking failed"):
            op._docling_serve_split_text(content="content")

    def test_api_key_included_in_headers_when_present(self):
        config = {
            "provider": "docling_serve",
            "chunk_type": ChunkType.HYBRID.value,
            "chunk_size": 512,
            "provider_config": {
                "api_base": "http://localhost:5001",
                "api_key": "my-secret-key",  # pragma: allowlist secret
            },
        }
        op = ChunkerOperator(config)
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = {"chunks": [{"text": "chunk"}]}
        op._remote_chunking_client = mock_client

        op._docling_serve_split_text(content="data")

        call_kwargs = mock_client.call_rest_json.call_args.kwargs
        assert call_kwargs["headers"].get("X-Api-Key") == "my-secret-key"

    def test_string_chunk_content_is_handled(self):
        op = self._make_op()
        mock_client = MagicMock()
        mock_client.call_rest_json.return_value = {"chunks": ["raw string chunk"]}
        op._remote_chunking_client = mock_client

        docs = op._docling_serve_split_text(content="content")
        assert len(docs) == 1
        assert docs[0].page_content == "raw string chunk"


class TestSummarizationProviderSchemas:
    """Test that _get_summarization_provider_schemas returns correct structure."""

    def test_returns_litellm_and_watsonx_schemas(self):
        schemas = ChunkerOperator._get_summarization_provider_schemas()
        assert "litellm" in schemas
        assert "watsonx" in schemas

    def test_schemas_have_properties(self):
        schemas = ChunkerOperator._get_summarization_provider_schemas()
        for provider_name, schema in schemas.items():
            assert "properties" in schema, f"Schema for {provider_name} should have 'properties' key"
