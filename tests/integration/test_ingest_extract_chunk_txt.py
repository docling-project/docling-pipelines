#!/usr/bin/env python3
"""
Integration test for Ingest -> Extract -> Chunking with .txt files
Tests the complete flow from file ingestion to content extraction to chunking for text files
"""

from pathlib import Path

import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.operators.extract.extract_operator import ExtractOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator


class TestIngestExtractChunkTxtIntegration:
    """Integration tests for IngestSource (filesystem) -> Extract -> Chunk sequence with .txt files"""

    @pytest.fixture
    def txt_fixtures_dir(self):
        """Get the customer support docs directory with .txt files"""
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "customer_support_docs"
        if not fixtures_path.exists():
            pytest.skip(f"Fixtures directory not found: {fixtures_path}")
        return str(fixtures_path)

    def test_txt_ingest_extract_chunk_sequence(self, txt_fixtures_dir):
        """Test the complete sequence: IngestSource (filesystem) -> ExtractOperator -> ChunkerOperator for .txt files"""

        # Step 1: Ingest .txt files
        print("\n=== Step 1: Ingesting .txt files ===")
        ingest_config = {
            "provider": "filesystem",
            "provider_config": {"paths": [txt_fixtures_dir]},
            "include_filter": "txt",
            "max_files": 5,
            "force_ingest": True,
        }

        ingest_operator = IngestSourceOperator(config=ingest_config)
        ingest_tables, ingest_metadata = ingest_operator.transform(None)
        ingest_table = ingest_tables[0]

        # Verify ingest output
        assert ingest_table.num_rows > 0, "Should have ingested .txt files"
        assert "path" in ingest_table.column_names, "Should have path column"
        assert "binary_content" not in ingest_table.column_names
        assert "doc_content" not in ingest_table.column_names, "Should NOT have doc_content yet"

        print(f"Ingested {ingest_table.num_rows} .txt files")
        print(f"Ingest metadata: {ingest_metadata}")

        # Step 2: Extract content using unified ExtractOperator (docling_library mode)
        print("\n=== Step 2: Extracting content from .txt files ===")
        extract_config = {
            "text_extraction": {"provider": "docling_library", "doc_column": "doc_content"},
            "entity_extraction": {"provider": "none"},
        }

        extract_operator = ExtractOperator(config=extract_config)
        extract_tables, extract_metadata = extract_operator.transform(ingest_table)
        extract_table = extract_tables[0]

        # Verify extract output
        assert extract_table.num_rows > 0, "Should have extracted content"
        assert "doc_content" in extract_table.column_names, "Should have doc_content column"
        assert "doc_id_hash" in extract_table.column_names, "Should have doc_id_hash column"
        assert "pages_processed" in extract_table.column_names, "Should have pages_processed column"
        assert "docling_document" not in extract_table.column_names, (
            "Should NOT have docling_document column (created in chunker now)"
        )

        # Verify content was actually extracted from .txt files
        content_count = 0
        for idx in range(extract_table.num_rows):
            content = extract_table["doc_content"][idx].as_py()
            if content and len(content) > 0:
                content_count += 1
                print(f"  File {idx}: Content length = {len(content)} chars")

        assert content_count > 0, "Should have extracted content from at least one .txt file"
        assert extract_metadata.get("processed_docs", 0) > 0, "Should have processed documents"
        assert "page_type_stats" in extract_metadata, "Should have page_type_stats in metadata"
        assert "total_pages_converted" in extract_metadata, "Should have total_pages_converted in metadata"
        assert isinstance(extract_metadata["page_type_stats"], dict), "page_type_stats should be a dict"

        print(f"Extracted content from {content_count} .txt files")
        print(f"Extract metadata: {extract_metadata}")

        # Step 3: Chunk the extracted content
        print("\n=== Step 3: Chunking .txt file content ===")
        chunk_config = {
            "chunk_type": "hybrid",
            "doc_column": "doc_content",
            "chunk_size": 256,  # Smaller chunks for testing
            "chunk_overlap": 50,
            "retain_original_content": False,
        }

        chunker_operator = ChunkerOperator(config=chunk_config)
        chunk_tables, chunk_metadata = chunker_operator.transform(extract_table)
        chunk_table = chunk_tables[0]

        # Verify chunking output
        assert chunk_table.num_rows > 0, "Should have chunked content"
        assert "chunked_content" in chunk_table.column_names, "Should have chunked_content column"
        assert "doc_id_hash" in chunk_table.column_names, "Should have doc_id_hash column"

        # Verify chunks were created
        total_chunks = 0
        for idx in range(chunk_table.num_rows):
            chunked_content = chunk_table["chunked_content"][idx].as_py()
            if chunked_content:
                # chunked_content is already a list, not a JSON string
                chunks = chunked_content
                total_chunks += len(chunks)
                print(f"  File {idx}: {len(chunks)} chunks created")

                # Verify chunk structure
                if len(chunks) > 0:
                    first_chunk = chunks[0]
                    assert "chunk" in first_chunk, "Chunk should have 'chunk' field"
                    assert len(first_chunk["chunk"]) > 0, "Chunk text should not be empty"

        assert total_chunks > 0, "Should have created at least one chunk"
        assert chunk_metadata.get(Metrics.External.TOTAL_CHUNKS, 0) > 0, "Metadata should report chunks created"

        print(f"Created {total_chunks} total chunks from .txt files")
        print(f"Chunk metadata: {chunk_metadata}")

        # Verify docling_document column is not present (never created in extract, only used internally in chunker)
        assert "docling_document" not in chunk_table.column_names, "docling_document should not be in final output"

        print("\n=== Integration test completed successfully! ===")

    def test_mixed_files_ingest_extract_chunk(self, txt_fixtures_dir):
        """Test with mixed .txt and .pdf files to ensure both work"""

        # Get parent directory that has both txt and pdf files
        parent_dir = Path(txt_fixtures_dir).parent

        print("\n=== Testing mixed file types (.txt and .pdf) ===")

        # Step 1: Ingest both .txt and .pdf files
        ingest_config = {
            "provider": "filesystem",
            "provider_config": {"paths": [str(parent_dir)]},
            "include_filter": "txt,pdf",
            "max_files": 5,
            "force_ingest": True,
        }

        ingest_operator = IngestSourceOperator(config=ingest_config)
        ingest_tables, _ingest_metadata = ingest_operator.transform(None)
        ingest_table = ingest_tables[0]

        if ingest_table.num_rows == 0:
            pytest.skip("No mixed files found for testing")

        print(f"Ingested {ingest_table.num_rows} files (mixed .txt and .pdf)")
        # Step 2: Extract content using unified ExtractOperator
        extract_config = {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "doc_content",
            },
            "entity_extraction": {"provider": "none"},
        }

        extract_operator = ExtractOperator(config=extract_config)
        extract_tables, extract_metadata = extract_operator.transform(ingest_table)
        extract_table = extract_tables[0]

        # Verify all files were processed
        assert extract_metadata.get("processed_docs", 0) > 0, "Should have processed documents"
        assert "page_type_stats" in extract_metadata, "Should have page_type_stats in metadata"
        assert "total_pages_converted" in extract_metadata, "Should have total_pages_converted in metadata"
        assert "pages_processed" in extract_table.column_names, "Should have pages_processed column"
        print(f"Extracted content from {extract_metadata.get('processed_docs', 0)} files")

        # Step 3: Chunk the content
        chunk_config = {
            "chunk_type": "hybrid",
            "doc_column": "doc_content",
            "chunk_size": 256,
            "chunk_overlap": 50,
        }

        chunker_operator = ChunkerOperator(config=chunk_config)
        chunk_tables, chunk_metadata = chunker_operator.transform(extract_table)
        _chunk_table = chunk_tables[0]

        assert chunk_metadata.get(Metrics.External.TOTAL_CHUNKS, 0) > 0, "Should have created chunks"
        print(f"Created {chunk_metadata.get(Metrics.External.TOTAL_CHUNKS, 0)} total chunks from mixed files")

        print("\n=== Mixed file type test completed successfully! ===")


def test_basic_txt_integration():
    """Basic integration test for .txt files without fixtures"""
    txt_dir = Path(__file__).parent.parent / "fixtures" / "customer_support_docs"

    if not txt_dir.exists():
        pytest.skip(f"Fixtures directory not found: {txt_dir}")

    ingest_config = {
        "provider": "filesystem",
        "provider_config": {"paths": [str(txt_dir)]},
        "include_filter": "txt",
        "max_files": 2,
        "force_ingest": True,
    }

    ingest_op = IngestSourceOperator(config=ingest_config)
    ingest_tables, _ = ingest_op.transform(None)

    extract_config = {
        "text_extraction": {"provider": "docling_library", "doc_column": "doc_content"},
        "entity_extraction": {"provider": "none"},
    }

    extract_op = ExtractOperator(config=extract_config)
    extract_tables, _ = extract_op.transform(ingest_tables[0])

    chunk_config = {
        "chunk_type": "hybrid",
        "doc_column": "doc_content",
        "chunk_size": 256,
    }

    chunk_op = ChunkerOperator(config=chunk_config)
    chunk_tables, chunk_metadata = chunk_op.transform(extract_tables[0])

    assert chunk_tables[0].num_rows > 0
    assert "chunked_content" in chunk_tables[0].column_names
    assert chunk_metadata.get(Metrics.External.TOTAL_CHUNKS, 0) > 0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
