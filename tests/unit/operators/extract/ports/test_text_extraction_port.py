# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for page_count functionality in TextExtractionPort.
Tests the _process_extraction_result method's page count calculation logic.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.ports.outbound.text_extraction import TextExtractionPort


class MockTextExtractionAdapter(TextExtractionPort):
    """Mock adapter for testing TextExtractionPort page_count logic."""

    ADAPTER_NAME = "mock_adapter"
    ADAPTER_DISPLAY_NAME = "Mock Adapter"

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return a no-op config schema for testing."""
        return BaseModel

    def extract_single_document(self, *, file_path: str, binary_content: bytes, **kwargs) -> dict:
        """Mock implementation."""
        return {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "test content",
        }


class TestTextExtractionPageCount:
    """Test suite for page_count calculation in TextExtractionPort."""

    @pytest.fixture
    def adapter(self):
        """Create mock adapter instance."""
        config = {"doc_column": "content"}
        return MockTextExtractionAdapter(config=config)

    @pytest.fixture
    def base_result(self):
        """Provide base extraction result."""
        return {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "Test content",
            OperatorConstants.Metadata.METADATA: {},
        }

    @pytest.fixture
    def base_task(self):
        """Provide base task dictionary."""
        return {"doc_id": "doc1", "doc_name": "test.pdf"}

    def test_page_count_uses_native_page_count_from_metadata(self, adapter, base_result, base_task):
        """Test that native page_count from metadata is used when available."""
        # Setup
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": 5}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify
        assert doc_pages_processed[0] == 5

    def test_page_count_uses_native_float_page_count(self, adapter, base_result, base_task):
        """Test that native page_count is converted to int when it's a float."""
        # Setup
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": 7.0}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify
        assert doc_pages_processed[0] == 7
        assert isinstance(doc_pages_processed[0], int)

    def test_page_count_fallback_to_character_based_calculation(self, adapter, base_result, base_task):
        """Test fallback to character-based calculation when native page_count is missing."""
        # Setup - 6000 characters should result in 2 pages (3000 chars per page)
        content = "a" * 6000
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {}  # No page_count
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - 6000 chars / 3000 chars per page = 2 pages
        assert doc_pages_processed[0] == 2

    def test_page_count_fallback_minimum_one_page(self, adapter, base_result, base_task):
        """Test that fallback calculation ensures minimum of 1 page."""
        # Setup - very short content
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = "Short"
        base_result[OperatorConstants.Metadata.METADATA] = {}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - minimum 1 page
        assert doc_pages_processed[0] == 1

    def test_page_count_fallback_empty_content(self, adapter, base_result, base_task):
        """Test fallback calculation with empty content."""
        # Setup
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = ""
        base_result[OperatorConstants.Metadata.METADATA] = {}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - minimum 1 page even for empty content
        assert doc_pages_processed[0] == 1

    def test_page_count_fallback_none_content(self, adapter, base_result, base_task):
        """Test fallback calculation when content is None."""
        # Setup
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = None
        base_result[OperatorConstants.Metadata.METADATA] = {}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - minimum 1 page
        assert doc_pages_processed[0] == 1

    def test_page_count_ignores_zero_native_page_count(self, adapter, base_result, base_task):
        """Test that zero native page_count falls back to character-based calculation."""
        # Setup
        content = "a" * 3000  # Should be 1 page
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": 0}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - falls back to character-based calculation
        assert doc_pages_processed[0] == 1

    def test_page_count_ignores_negative_native_page_count(self, adapter, base_result, base_task):
        """Test that negative native page_count falls back to character-based calculation."""
        # Setup
        content = "a" * 6000  # Should be 2 pages
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": -5}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - falls back to character-based calculation
        assert doc_pages_processed[0] == 2

    def test_page_count_ignores_invalid_type_native_page_count(self, adapter, base_result, base_task):
        """Test that invalid type native page_count falls back to character-based calculation."""
        # Setup
        content = "a" * 9000  # Should be 3 pages
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": "invalid"}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - falls back to character-based calculation
        assert doc_pages_processed[0] == 3

    def test_page_count_ignores_none_native_page_count(self, adapter, base_result, base_task):
        """Test that None native page_count falls back to character-based calculation."""
        # Setup
        content = "a" * 4500  # Should be 2 pages (4500 / 3000 = 1.5, rounds up to 2)
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": None}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - falls back to character-based calculation
        assert doc_pages_processed[0] == 2

    def test_page_count_character_based_rounding_up(self, adapter, base_result, base_task):
        """Test that character-based calculation rounds up correctly."""
        # Setup - 3001 characters should round up to 2 pages
        content = "a" * 3001
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - rounds up to 2 pages
        assert doc_pages_processed[0] == 2

    def test_page_count_large_document(self, adapter, base_result, base_task):
        """Test page_count calculation for large document."""
        # Setup - 30000 characters = 10 pages
        content = "a" * 30000
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify
        assert doc_pages_processed[0] == 10

    def test_page_count_prefers_native_over_character_based(self, adapter, base_result, base_task):
        """Test that native page_count is preferred even when content suggests different count."""
        # Setup - 30000 characters would be 10 pages, but native says 15
        content = "a" * 30000
        base_result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
        base_result[OperatorConstants.Metadata.METADATA] = {"page_count": 15}
        doc_contents = [""]
        doc_metadata_list: list[dict[str, Any]] = [{}]
        format_lists: dict[str, list[Any]] = {}
        doc_pages_processed = [0]
        remove_row_idx: list[int] = []
        metadata = {Metrics.External.PROCESSED_DOCS: 0}

        # Execute
        adapter._process_extraction_result(
            result=base_result,
            task=base_task,
            idx=0,
            doc_contents=doc_contents,
            doc_metadata_list=doc_metadata_list,
            format_lists=format_lists,
            doc_pages_processed=doc_pages_processed,
            remove_row_idx=remove_row_idx,
            metadata=metadata,
            non_recoverable_doc_ids=[],
        )

        # Verify - uses native page_count (15) not character-based (10)
        assert doc_pages_processed[0] == 15
