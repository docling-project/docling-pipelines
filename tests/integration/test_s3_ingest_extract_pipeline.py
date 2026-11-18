#!/usr/bin/env python3
"""
Integration tests for S3 ingest to extract pipeline.
Tests the complete flow from S3 ingestion through extraction,
verifying that binary_content column is properly handled.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pyarrow as pa
import pytest


@pytest.mark.integration
class TestS3IngestExtractPipeline:
    """Integration tests for S3 ingest followed by extract operator."""

    @pytest.fixture
    def mock_s3_documents(self):
        """Fixture providing mock S3 documents."""
        from docpipe.core.operators.ingest.domain.models import Document

        return [
            Document(
                id="test-doc-1.pdf",
                name="test-doc-1.pdf",
                content=b"%PDF-1.4 Mock PDF content for testing",
                source_url="s3://test-bucket/documents/test-doc-1.pdf",
                modified_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                metadata={
                    "bucket": "test-bucket",
                    "key": "documents/test-doc-1.pdf",
                    "size": 1024,
                    "content_type": "application/pdf",
                },
            ),
            Document(
                id="test-doc-2.pdf",
                name="test-doc-2.pdf",
                content=b"%PDF-1.4 Another mock PDF for testing",
                source_url="s3://test-bucket/documents/test-doc-2.pdf",
                modified_time=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                metadata={
                    "bucket": "test-bucket",
                    "key": "documents/test-doc-2.pdf",
                    "size": 2048,
                    "content_type": "application/pdf",
                },
            ),
        ]

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_s3_ingest_creates_binary_content_column(
        self,
        mock_fetch_documents,
        mock_get_service,
        mock_s3_documents,
    ):
        """Test that S3 ingest operator sets has_binary_content metadata flag (lazy loading)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            for doc in mock_s3_documents:
                yield doc

        mock_fetch_documents.return_value = mock_async_gen()

        # Configure S3 ingest operator
        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "documents/",
                "access_key": "test-access-key",
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        # Create empty input table (trigger)
        empty_table = pa.Table.from_arrays([])

        # Execute ingest
        operator = IngestSourceOperator(config)
        result_tables, _metadata = operator.transform(empty_table)
        result_table = result_tables[0]

        # Verify binary_content column does NOT exist (lazy loading)
        assert "binary_content" not in result_table.column_names, (
            "binary_content column should NOT exist with lazy loading"
        )
        assert result_table.num_rows == 2, "Should have 2 documents"

        # Verify has_binary_content flag is set in metadata
        assert "metadata" in result_table.column_names
        metadata_list = result_table["metadata"].to_pylist()
        for metadata_json in metadata_list:
            import json

            metadata_dict = json.loads(metadata_json)
            assert metadata_dict.get("has_binary_content") is True, "has_binary_content flag should be True in metadata"

        # Verify other expected columns
        assert "id" in result_table.column_names
        assert "name" in result_table.column_names
        assert "path" in result_table.column_names

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_binary_content")
    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.DoclingAdapter.extract_single_document"
    )
    def test_extract_operator_drops_binary_content_column(
        self,
        mock_extract_single,
        mock_fetch_binary,
        mock_fetch_documents,
        mock_get_service,
        mock_s3_documents,
    ):
        """Test that extract operator works with lazy loading (no binary_content column)."""
        from docpipe.core.operators.extract.extract_operator import ExtractOperator
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            for doc in mock_s3_documents:
                yield doc

        mock_fetch_documents.return_value = mock_async_gen()

        # Mock fetch_binary_content to return binary content from mock documents
        def mock_fetch_binary_side_effect(*, source_id, provider_config):
            # Find the matching document by source_id
            for doc in mock_s3_documents:
                if source_id == doc.source_url or source_id.endswith(doc.id):
                    return doc.content
            return None

        mock_fetch_binary.side_effect = mock_fetch_binary_side_effect

        # Mock DoclingAdapter.extract_single_document
        mock_extract_single.return_value = {
            "success": True,
            "content": "# Extracted Content\n\nThis is extracted text from PDF.",
            "pages_processed": 1,
            "format": "pdf",
        }

        # Step 1: S3 Ingest
        ingest_config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "documents/",
                "access_key": "test-access-key",
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        empty_table = pa.Table.from_arrays([])
        ingest_operator = IngestSourceOperator(ingest_config)
        ingest_result_tables, _ingest_metadata = ingest_operator.transform(empty_table)
        ingest_result_table = ingest_result_tables[0]

        # Verify binary_content does NOT exist after ingest (lazy loading)
        assert "binary_content" not in ingest_result_table.column_names, (
            "binary_content should NOT exist with lazy loading"
        )

        # Step 2: Extract
        # Include ingest_source in config so ExtractOperator can fetch binary content on-demand
        extract_config = {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "content",
                "provider_config": {"max_workers": 2},
            },
            "entity_extraction": {"provider": "none"},
            "ingest_source": {
                "provider": "s3",
                "provider_config": {
                    "bucket": "test-bucket",
                    "prefix": "documents/",
                    "access_key": "test-access-key",
                    "secret_key": "test-secret-key",  # pragma: allowlist secret
                },
            },
        }

        extract_operator = ExtractOperator(config=extract_config)
        extract_result_tables, extract_metadata = extract_operator.transform(ingest_result_table)
        extract_result_table = extract_result_tables[0]

        # Verify binary_content still does not exist after extraction
        assert "binary_content" not in extract_result_table.column_names, (
            "binary_content column should not exist (lazy loading)"
        )

        # Verify extraction succeeded
        assert "content" in extract_result_table.column_names, "Content column should exist after extraction"
        assert extract_result_table.num_rows == 2, "Should have 2 documents after extraction"
        assert extract_metadata["processed_docs"] == 2, "Should have processed 2 documents"

        # Verify extracted content is not empty
        contents = extract_result_table["content"].to_pylist()
        assert all(content is not None for content in contents), "All content values should be non-null"
        assert all(len(content) > 0 for content in contents), "All content values should be non-empty"

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_binary_content")
    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.DoclingAdapter.extract_single_document"
    )
    def test_complete_s3_to_extract_pipeline_with_binary_content_handling(
        self,
        mock_extract_single,
        mock_fetch_binary,
        mock_fetch_documents,
        mock_get_service,
        mock_s3_documents,
    ):
        """Test complete pipeline: S3 ingest → Extract, verifying lazy loading behavior."""
        from docpipe.core.operators.extract.extract_operator import ExtractOperator
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            for doc in mock_s3_documents:
                yield doc

        mock_fetch_documents.return_value = mock_async_gen()

        # Mock fetch_binary_content to return binary content from mock documents
        def mock_fetch_binary_side_effect(*, source_id, provider_config):
            # Find the matching document by source_id
            for doc in mock_s3_documents:
                if source_id == doc.source_url or source_id.endswith(doc.id):
                    return doc.content
            return None

        mock_fetch_binary.side_effect = mock_fetch_binary_side_effect

        # Mock DoclingAdapter.extract_single_document
        mock_extract_single.return_value = {
            "success": True,
            "content": "# Test Document\n\nExtracted content.",
            "pages_processed": 1,
            "format": "pdf",
        }

        # Configure operators
        ingest_config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "documents/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "include_filter": "pdf",
            "max_files": 2,
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        extract_config = {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "content",
                "max_workers": 2,
            },
            "entity_extraction": {"provider": "none"},
            "ingest_source": {
                "provider": "s3",
                "provider_config": {
                    "bucket": "test-bucket",
                    "prefix": "documents/",
                    "access_key": "test-access-key",
                    "secret_key": "test-secret-key",  # pragma: allowlist secret
                },
            },
        }

        # Execute pipeline
        empty_table = pa.Table.from_arrays([])

        # Stage 1: Ingest from S3
        ingest_operator = IngestSourceOperator(ingest_config)
        ingest_tables, ingest_meta = ingest_operator.transform(empty_table)
        ingest_table = ingest_tables[0]

        # Verify Stage 1: binary_content NOT present (lazy loading)
        assert "binary_content" not in ingest_table.column_names, "binary_content should NOT exist with lazy loading"
        assert ingest_table.num_rows == 2
        assert ingest_meta["processed_docs"] == 2

        # Verify has_binary_content flag in metadata
        import json

        metadata_list = ingest_table["metadata"].to_pylist()
        for metadata_json in metadata_list:
            metadata_dict = json.loads(metadata_json)
            assert metadata_dict.get("has_binary_content") is True

        # Stage 2: Extract
        extract_operator = ExtractOperator(config=extract_config)
        extract_tables, extract_meta = extract_operator.transform(ingest_table)
        extract_table = extract_tables[0]

        # Verify Stage 2: binary_content still not present, content added
        assert "binary_content" not in extract_table.column_names, "binary_content should not exist (lazy loading)"
        assert "content" in extract_table.column_names, "content should be present"
        assert extract_table.num_rows == 2
        assert extract_meta["processed_docs"] == 2

        # Verify data integrity
        assert "id" in extract_table.column_names
        assert "name" in extract_table.column_names
        assert "doc_id_hash" in extract_table.column_names

        # Verify columns are preserved (no binary_content to exclude)
        for col in ingest_table.column_names:
            if col not in ["content", "doc_id_hash", "pages_processed"]:  # These are added/modified by extract
                assert col in extract_table.column_names, f"Column {col} should be preserved"

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_s3_ingest_with_empty_result_handles_binary_content(
        self,
        mock_fetch_documents,
        mock_get_service,
    ):
        """Test that empty S3 ingest result has correct schema (no binary_content with lazy loading)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock empty async generator
        async def mock_async_gen():
            if False:
                yield

        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "nonexistent/",
                "access_key": "test-key",
                "secret_key": "test-secret",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        empty_table = pa.Table.from_arrays([])
        operator = IngestSourceOperator(config)
        result_tables, _metadata = operator.transform(empty_table)
        result_table = result_tables[0]

        # Verify schema does NOT include binary_content (lazy loading)
        assert result_table.num_rows == 0
        assert "binary_content" not in result_table.column_names, "binary_content should NOT exist with lazy loading"
        # Verify expected columns exist
        assert "id" in result_table.column_names
        assert "name" in result_table.column_names
        assert "metadata" in result_table.column_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
