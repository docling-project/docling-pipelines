# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for DoclingServeAdapter.
"""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter import DoclingServeAdapter


class TestDoclingServeAdapter:
    """Test suite for DoclingServeAdapter."""

    @pytest.fixture
    def valid_config(self):
        """Provide valid configuration for adapter initialization."""
        return {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "api_key": "test-key",  # pragma: allowlist secret
                "timeout": 300,
                "poll_interval": 2,
                "max_retries": 3,
                "do_ocr": True,
                "pdf_backend": "dlparse_v2",
            }
        }

    @pytest.fixture
    def adapter(self, valid_config):
        """Create adapter instance with valid config."""
        return DoclingServeAdapter(config=valid_config)

    def test_init_with_valid_config(self, valid_config):
        """Test adapter initialization with valid configuration."""
        adapter = DoclingServeAdapter(config=valid_config)
        assert adapter.base_url == "http://localhost:5001"
        assert adapter.api_key == "test-key"  # pragma: allowlist secret
        assert adapter.timeout == 300
        assert adapter.poll_interval == 2
        assert adapter.max_retries == 3
        assert adapter.processing_options["do_ocr"] is True
        assert adapter.processing_options["pdf_backend"] == "dlparse_v2"

    def test_init_with_default_values(self):
        """Test adapter initialization with default values."""
        config = {"docling_serve_config": {"base_url": "http://0.0.0.0:5001"}}
        adapter = DoclingServeAdapter(config=config)
        assert adapter.base_url == "http://0.0.0.0:5001"
        assert adapter.api_key is None
        assert adapter.timeout == 300
        assert adapter.poll_interval == 2
        assert adapter.max_retries == 3

    def test_init_missing_docling_serve_config(self):
        """Test adapter initialization fails without docling_serve_config."""
        config: dict[str, object] = {}
        with pytest.raises(ValueError, match="docling_serve_config is required"):
            DoclingServeAdapter(config=config)

    def test_adapter_name_constants(self):
        """Test adapter name constants are correctly defined."""
        assert DoclingServeAdapter.ADAPTER_NAME == "docling_serve"
        assert DoclingServeAdapter.ADAPTER_DISPLAY_NAME == "Docling Serve Extractor"

    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.OperatorUtils.extract_text_file"
    )
    def test_extract_single_document_txt_file_routes_to_local_extraction(self, mock_extract_text_file, adapter):
        """Test that .txt files are routed to local extraction method."""
        # Setup
        file_path = "/path/to/document.txt"
        binary_content = b"This is plain text content"
        mock_extract_text_file.return_value = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "This is plain text content",
        }

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        mock_extract_text_file.assert_called_once_with(
            file_path=file_path,
            binary_content=binary_content,
            additional_formats=[],
            doc_format=OperatorConstants.DOC_FORMAT_DEFAULT,
        )
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "This is plain text content"

    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.OperatorUtils.extract_text_file"
    )
    def test_extract_single_document_txt_file_passes_additional_formats(self, mock_extract_text_file, adapter):
        """Test that additional_formats are forwarded to extract_text_file for .txt files."""
        file_path = "/path/to/document.txt"
        binary_content = b"Plain text content"
        mock_extract_text_file.return_value = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "Plain text content",
            OperatorConstants.Columns.CONTENT_HTML: "<html>Plain text content</html>",
        }

        # Create adapter with additional_formats configured
        config_with_formats = {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "timeout": 300,
                "poll_interval": 2,
                "max_retries": 3,
                "do_ocr": True,
                "pdf_backend": "dlparse_v2",
            },
            "additional_formats": ["html"],
        }
        adapter_with_formats = DoclingServeAdapter(config=config_with_formats)

        result = adapter_with_formats.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify additional_formats and doc_format are forwarded to extract_text_file
        mock_extract_text_file.assert_called_once_with(
            file_path=file_path,
            binary_content=binary_content,
            additional_formats=["html"],
            doc_format=OperatorConstants.DOC_FORMAT_DEFAULT,
        )
        assert result[OperatorConstants.Extraction.SUCCESS] is True

    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.OperatorUtils.extract_text_file"
    )
    def test_extract_single_document_txt_file_passes_doc_format_doclang(self, mock_extract_text_file):
        """doc_format=doclang is forwarded to extract_text_file for .txt files."""
        file_path = "/path/to/doc.txt"
        binary_content = b"Plain text content"
        doclang_xml = '<doclang version="0.7"><text>Plain text content</text></doclang>'
        mock_extract_text_file.return_value = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: doclang_xml,
        }

        config = {
            OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG,
            "docling_serve_config": {"base_url": "http://localhost:5001"},
        }
        adapter = DoclingServeAdapter(config=config)
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        mock_extract_text_file.assert_called_once_with(
            file_path=file_path,
            binary_content=binary_content,
            additional_formats=[],
            doc_format=OperatorConstants.DocFormat.DOCLANG,
        )
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == doclang_xml

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_md_file_uses_docling_serve(self, mock_client_class, adapter):
        """Test that .md files are processed through Docling Serve."""
        # Setup
        file_path = "/path/to/document.md"
        binary_content = b"# Markdown content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "# Markdown content"},
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        mock_client_class.assert_called_once_with(
            base_url=adapter.base_url,
            api_key=adapter.api_key,
            timeout=adapter.timeout,
            poll_interval=adapter.poll_interval,
            max_retries=adapter.max_retries,
            verify_ssl=adapter.verify_ssl,
        )
        mock_client_instance.process_document.assert_called_once()
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["binary_content"] == binary_content
        assert call_kwargs["filename"] == "document.md"
        assert result[OperatorConstants.Extraction.SUCCESS] is True

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_filename_extraction_from_path(self, mock_client_class, adapter):
        """Test that filename is correctly extracted from file path."""
        # Setup
        file_path = "/path/to/my_document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Extracted text"},
            "processing_time": 2.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify filename is passed correctly
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "my_document.pdf"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_filename_passing_to_client(self, mock_client_class, adapter):
        """Test that filename is passed to docling_serve_client."""
        # Setup
        file_path = "/path/to/report.docx"
        binary_content = b"DOCX content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Report content"},
            "processing_time": 1.8,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert "filename" in call_kwargs
        assert call_kwargs["filename"] == "report.docx"
        assert call_kwargs["binary_content"] == binary_content

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_binary_content_with_filename_preservation(self, mock_client_class, adapter):
        """Test that filename is preserved when processing binary content."""
        # Setup
        file_path = "/path/to/presentation.pptx"
        binary_content = b"PPTX binary data"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Slide content"},
            "processing_time": 3.2,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify filename preservation
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "presentation.pptx"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_success_with_metadata(self, mock_client_class, adapter):
        """Test successful extraction with metadata including page_count from json_content."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Extracted markdown text",
                "json_content": {
                    "pages": [
                        {"page_no": 1},
                        {"page_no": 2},
                        {"page_no": 3},
                        {"page_no": 4},
                        {"page_no": 5},
                        {"page_no": 6},
                        {"page_no": 7},
                        {"page_no": 8},
                        {"page_no": 9},
                        {"page_no": 10},
                    ]
                },
            },
            "processing_time": 2.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "Extracted markdown text"
        assert OperatorConstants.Metadata.METADATA in result
        assert result[OperatorConstants.Metadata.METADATA]["processing_time"] == 2.5
        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Metadata.PAGE_COUNT] == 10

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_error_handling(self, mock_client_class, adapter):
        """Test error handling during extraction."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.side_effect = Exception("Connection timeout")
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert OperatorConstants.Extraction.ERROR in result
        assert "Connection timeout" in result[OperatorConstants.Extraction.ERROR]
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] is None

    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.OperatorUtils.detect_extension_from_bytes"
    )
    @patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.OperatorUtils.extract_text_file"
    )
    def test_extract_single_document_no_extension_detection(
        self, mock_extract_text_file, mock_detect_extension, adapter
    ):
        """Test extension detection when file has no extension."""
        # Setup
        file_path = "/path/to/document"
        binary_content = b"Text content"
        mock_detect_extension.return_value = ".txt"
        mock_extract_text_file.return_value = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "Text content",
        }

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        mock_detect_extension.assert_called_once_with(binary_content)
        mock_extract_text_file.assert_called_once()
        assert result[OperatorConstants.Extraction.SUCCESS] is True

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_pdf_file(self, mock_client_class, adapter):
        """Test PDF file processing through Docling Serve."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"%PDF-1.4 content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "PDF extracted text"},
            "processing_time": 3.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "document.pdf"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_docx_file(self, mock_client_class, adapter):
        """Test DOCX file processing through Docling Serve."""
        # Setup
        file_path = "/path/to/document.docx"
        binary_content = b"PK\x03\x04 DOCX content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "DOCX extracted text"},
            "processing_time": 2.2,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "document.docx"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_html_file(self, mock_client_class, adapter):
        """Test HTML file processing through Docling Serve."""
        # Setup
        file_path = "/path/to/page.html"
        binary_content = b"<html><body>Content</body></html>"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "HTML extracted text"},
            "processing_time": 1.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "page.html"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_processing_options_passed(self, mock_client_class, adapter):
        """Test that processing options are passed to client."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Text"},
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify processing options are passed
        call_kwargs = mock_client_instance.process_document.call_args.kwargs
        assert "options" in call_kwargs
        assert call_kwargs["options"]["do_ocr"] is True
        assert call_kwargs["options"]["pdf_backend"] == "dlparse_v2"

    def test_extract_single_document_with_optional_config_parameters(self):
        """Test adapter with optional configuration parameters (deprecated flat fields)."""
        config = {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "ocr_engine": "tesseract",  # deprecated — maps to ocr_preset
                "ocr_languages": ["eng", "fra"],
                "table_mode": "accurate",
                "image_export_mode": "embedded",
            }
        }
        adapter = DoclingServeAdapter(config=config)

        # ocr_engine maps to ocr_preset in the backward-compat path
        assert adapter.processing_options["ocr_preset"] == "tesseract"
        assert adapter.processing_options["ocr_languages"] == ["eng", "fra"]
        assert adapter.processing_options["table_mode"] == "accurate"
        assert adapter.processing_options["image_export_mode"] == "embedded"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_from_json_content(self, mock_client_class, adapter):
        """Test page_count extraction from json_content.pages."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Extracted text",
                "json_content": {
                    "pages": [
                        {"page_no": 1, "content": "Page 1"},
                        {"page_no": 2, "content": "Page 2"},
                        {"page_no": 3, "content": "Page 3"},
                    ]
                },
            },
            "processing_time": 2.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Metadata.METADATA in result
        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Metadata.PAGE_COUNT] == 3

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_empty_pages(self, mock_client_class, adapter):
        """Test page_count when json_content.pages is empty."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Extracted text",
                "json_content": {"pages": []},
            },
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify - page_count should not be set when pages is empty
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Metadata.METADATA in result
        assert OperatorConstants.Metadata.PAGE_COUNT not in result[OperatorConstants.Metadata.METADATA]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_missing_json_content(self, mock_client_class, adapter):
        """Test page_count when json_content is missing."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Extracted text"},
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify - page_count should not be set when json_content is missing
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Metadata.METADATA in result
        assert OperatorConstants.Metadata.PAGE_COUNT not in result[OperatorConstants.Metadata.METADATA]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_missing_pages_key(self, mock_client_class, adapter):
        """Test page_count when pages key is missing from json_content."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Extracted text",
                "json_content": {"other_data": "value"},
            },
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify - page_count should not be set when pages key is missing
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Metadata.METADATA in result
        assert OperatorConstants.Metadata.PAGE_COUNT not in result[OperatorConstants.Metadata.METADATA]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_single_page(self, mock_client_class, adapter):
        """Test page_count extraction for single page document."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Single page content",
                "json_content": {"pages": [{"page_no": 1, "content": "Page 1"}]},
            },
            "processing_time": 1.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Metadata.PAGE_COUNT] == 1

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_page_count_large_document(self, mock_client_class, adapter):
        """Test page_count extraction for large multi-page document."""
        # Setup
        file_path = "/path/to/large_document.pdf"
        binary_content = b"PDF content"

        # Create 50 pages
        pages = [{"page_no": i, "content": f"Page {i}"} for i in range(1, 51)]

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "Large document content",
                "json_content": {"pages": pages},
            },
            "processing_time": 5.0,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Metadata.PAGE_COUNT] == 50

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_single_document_verify_ssl_parameter(self, mock_client_class, adapter):
        """Test that verify_ssl parameter is passed to DoclingServeClient."""
        # Setup
        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "Text"},
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        # Execute
        adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        # Verify verify_ssl is passed (default is True)
        mock_client_class.assert_called_once_with(
            base_url=adapter.base_url,
            api_key=adapter.api_key,
            timeout=adapter.timeout,
            poll_interval=adapter.poll_interval,
            max_retries=adapter.max_retries,
            verify_ssl=True,
        )

    def test_init_with_verify_ssl_false(self):
        """Test adapter initialization with verify_ssl set to False."""
        config = {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "verify_ssl": False,
            }
        }
        adapter = DoclingServeAdapter(config=config)
        assert adapter.verify_ssl is False

    def test_init_with_verify_ssl_true(self):
        """Test adapter initialization with verify_ssl set to True."""
        config = {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "verify_ssl": True,
            }
        }
        adapter = DoclingServeAdapter(config=config)
        assert adapter.verify_ssl is True

    def test_init_verify_ssl_default_value(self):
        """Test that verify_ssl defaults to True when not specified."""
        config = {"docling_serve_config": {"base_url": "http://localhost:5001"}}
        adapter = DoclingServeAdapter(config=config)
        assert adapter.verify_ssl is True

    def test_init_with_additional_formats_empty(self):
        """Test adapter initialization with empty additional_formats (markdown-only)."""
        config = {
            "additional_formats": [],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)
        assert adapter.additional_formats == []
        assert "additional_formats" not in adapter.processing_options

    def test_init_with_additional_formats_single(self):
        """Test adapter initialization with single additional format."""
        config = {
            "additional_formats": ["html"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)
        assert adapter.additional_formats == ["html"]
        assert adapter.processing_options["additional_formats"] == ["html"]

    def test_init_with_additional_formats_multiple(self):
        """Test adapter initialization with multiple additional formats."""
        config = {
            "additional_formats": ["html", "json", "text"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)
        assert adapter.additional_formats == ["html", "json", "text"]
        assert adapter.processing_options["additional_formats"] == ["html", "json", "text"]

    def test_init_without_additional_formats_defaults_to_empty(self):
        """Test that additional_formats defaults to empty list when not specified."""
        config = {"docling_serve_config": {"base_url": "http://localhost:5001"}}
        adapter = DoclingServeAdapter(config=config)
        assert adapter.additional_formats == []

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_additional_formats_html(self, mock_client_class):
        """Test extraction with HTML additional format."""
        config = {
            "additional_formats": ["html"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "# Markdown content",
                "html_content": "<h1>HTML content</h1>",
            },
            "processing_time": 2.0,
        }
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown content"
        assert result[OperatorConstants.Columns.CONTENT_HTML] == "<h1>HTML content</h1>"
        assert "html" in result[OperatorConstants.Metadata.METADATA]["formats"]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_additional_formats_multiple(self, mock_client_class):
        """Test extraction with multiple additional formats."""
        config = {
            "additional_formats": ["html", "json", "text"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "# Markdown",
                "html_content": "<h1>HTML</h1>",
                "json_content": {"pages": [{"page_no": 1}]},
                "text_content": "Plain text",
            },
            "processing_time": 2.5,
        }
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown"
        assert result[OperatorConstants.Columns.CONTENT_HTML] == "<h1>HTML</h1>"
        assert result[OperatorConstants.Columns.CONTENT_TEXT] == "Plain text"
        assert OperatorConstants.Columns.CONTENT_JSON in result
        formats = result[OperatorConstants.Metadata.METADATA]["formats"]
        assert "markdown" in formats
        assert "html" in formats
        assert "json" in formats
        assert "text" in formats

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_markdown_only_no_additional_formats(self, mock_client_class):
        """Test extraction with markdown only (no additional formats requested)."""
        config = {"docling_serve_config": {"base_url": "http://localhost:5001"}}
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {"md_content": "# Markdown only"},
            "processing_time": 1.5,
        }
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown only"
        assert OperatorConstants.Columns.CONTENT_HTML not in result
        assert OperatorConstants.Columns.CONTENT_JSON not in result
        assert OperatorConstants.Columns.CONTENT_TEXT not in result
        assert result[OperatorConstants.Metadata.METADATA]["formats"] == ["markdown"]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_doclang_format(self, mock_client_class):
        """Test extraction with doclang additional format."""
        config = {
            "additional_formats": ["doclang"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        mock_client_instance.process_document.return_value = {
            "document": {
                "md_content": "# Markdown",
                "doclang_content": "DocLang formatted content",
            },
            "processing_time": 2.0,
        }
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown"
        assert result[OperatorConstants.Columns.CONTENT_DOCLANG] == "DocLang formatted content"
        assert "doclang" in result[OperatorConstants.Metadata.METADATA]["formats"]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_unsupported_format_error_422(self, mock_client_class):
        """Test that 422 errors for unsupported formats provide clear guidance via error classifier."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException
        from docpipe.exceptions.error_codes import ErrorCode

        config = {
            "additional_formats": ["html", "json"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        # Simulate enhanced 422 error from docling client (enhanced by error classifier)
        enhanced_error_msg = (
            "The docling-serve instance at http://localhost:5001 rejected the requested output formats. "
            "This typically occurs when using an older docling-serve version that does not support "
            "one or more of the requested formats: ['md', 'html', 'json']. "
            "\n\nTo resolve this issue:\n"
            "1. Upgrade docling-serve to the latest version, OR\n"
            "2. Remove unsupported formats from 'text_extraction.provider_config.additional_formats' in your flow configuration.\n"
            "\nOriginal error: Unexpected status code 422"
        )
        mock_client_instance.process_document.side_effect = DocpipeException(
            message=enhanced_error_msg,
            status_code=422,
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
        )
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert OperatorConstants.Extraction.ERROR in result
        error_msg = result[OperatorConstants.Extraction.ERROR]
        # Verify the error message contains helpful guidance (from error classifier)
        assert "docling-serve" in error_msg.lower()
        assert "format" in error_msg.lower()
        assert "upgrade" in error_msg.lower()
        assert "additional_formats" in error_msg.lower()

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_format_compatibility_error_message(self, mock_client_class):
        """Test that format-related error messages trigger compatibility guidance via error classifier."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException
        from docpipe.exceptions.error_codes import ErrorCode

        config = {
            "additional_formats": ["doctags"],
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
            },
        }
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        # Simulate enhanced format-related error from docling client (enhanced by error classifier)
        enhanced_error_msg = (
            "The docling-serve instance at http://localhost:5001 rejected the requested output formats. "
            "This typically occurs when using an older docling-serve version that does not support "
            "one or more of the requested formats: ['md', 'doctags']. "
            "\n\nTo resolve this issue:\n"
            "1. Upgrade docling-serve to the latest version, OR\n"
            "2. Remove unsupported formats from 'text_extraction.provider_config.additional_formats' in your flow configuration.\n"
            "\nOriginal error: Invalid format 'doctags' not supported"
        )
        mock_client_instance.process_document.side_effect = DocpipeException(
            message=enhanced_error_msg,
            status_code=400,
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
        )
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert OperatorConstants.Extraction.ERROR in result
        error_msg = result[OperatorConstants.Extraction.ERROR]
        # Verify helpful guidance is provided (from error classifier)
        assert "additional_formats" in error_msg.lower()
        assert "upgrade" in error_msg.lower()

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_extract_with_non_format_error_passes_through(self, mock_client_class):
        """Test that non-format errors are passed through without modification."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException
        from docpipe.exceptions.error_codes import ErrorCode

        config = {"docling_serve_config": {"base_url": "http://localhost:5001"}}
        adapter = DoclingServeAdapter(config=config)

        file_path = "/path/to/document.pdf"
        binary_content = b"PDF content"

        mock_client_instance = MagicMock()
        # Simulate a different type of error (not format-related)
        mock_client_instance.process_document.side_effect = DocpipeException(
            message="Connection timeout",
            status_code=500,
            error_code=ErrorCode.CONNECTION_ERROR,
        )
        mock_client_class.return_value = mock_client_instance

        result = adapter.extract_single_document(file_path=file_path, binary_content=binary_content)

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert OperatorConstants.Extraction.ERROR in result
        error_msg = result[OperatorConstants.Extraction.ERROR]
        # Should contain original error, not format guidance
        assert "Connection timeout" in error_msg
        assert "upgrade docling-serve" not in error_msg.lower()


# ---------------------------------------------------------------------------
# v1 response + doc_format=doclang incompatibility test
# ---------------------------------------------------------------------------
class TestDoclingServeAdapterV1DoclangIncompatibility:
    """Tests that doc_format=doclang is rejected against v1 servers."""

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_v1_response_with_doclang_format_returns_failure(self, mock_client_class):
        """When doc_format=doclang but server returns a v1 response, result is a clear failure.

        v1 servers only provide md_content — they cannot produce DocLang XML.
        Returning Markdown in a column the pipeline expects to be DocLang XML
        would cause silent corruption downstream; failing clearly is correct.
        """
        config = {
            OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG,
            "docling_serve_config": {"base_url": "http://localhost:5001"},
        }
        adapter = DoclingServeAdapter(config=config)

        # Server returns v1-format response (no "documents" key)
        mock_client_class.return_value.process_document.return_value = {
            "document": {"md_content": "# Extracted markdown"},
            "processing_time": 0.5,
        }

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert "v1" in result[OperatorConstants.Extraction.ERROR].lower()
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] is None


# ---------------------------------------------------------------------------
# v2 response format tests (presigned artifact URIs)
# Missing lines: 296, 297, 299, 303, 305-352
# ---------------------------------------------------------------------------
class TestDoclingServeAdapterV2Response:
    """Tests for the v2 artifact-URI response format from docling-serve."""

    @pytest.fixture
    def adapter(self):
        return DoclingServeAdapter(config={"docling_serve_config": {"base_url": "http://localhost:5001"}})

    @pytest.fixture
    def adapter_with_formats(self):
        config = {
            "additional_formats": ["html", "json"],
            "docling_serve_config": {"base_url": "http://localhost:5001"},
        }
        return DoclingServeAdapter(config=config)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_get(url_to_text: dict[str, str]):
        """Return a requests.get side_effect that maps URL substrings to text."""
        import requests as _requests

        def _side_effect(url, *, timeout=60, verify=True):
            for key, text in url_to_text.items():
                if key in url:
                    resp = MagicMock()
                    resp.text = text
                    resp.raise_for_status = MagicMock()
                    return resp
            raise _requests.RequestException(f"No mock for URL: {url}")

        return _side_effect

    # ------------------------------------------------------------------
    # happy path
    # ------------------------------------------------------------------
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_markdown_only(self, mock_get, mock_client_class, adapter):
        """v2 response with markdown artifact: content is fetched from URI."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [{"artifacts": [{"artifact_type": "markdown", "uri": "http://s3/doc.md"}]}],
            "processing_time": 1.5,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Fetched Markdown"})

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Fetched Markdown"
        assert "markdown" in result[OperatorConstants.Metadata.METADATA]["formats"]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_html_artifact(self, mock_get, mock_client_class, adapter_with_formats):
        """v2 response with html artifact is mapped to content_html column."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                        {"artifact_type": "html", "uri": "http://s3/doc.html"},
                    ]
                }
            ],
            "processing_time": 2.0,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Markdown", "doc.html": "<h1>HTML</h1>"})

        result = adapter_with_formats.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown"
        assert result[OperatorConstants.Columns.CONTENT_HTML] == "<h1>HTML</h1>"
        assert "html" in result[OperatorConstants.Metadata.METADATA]["formats"]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_json_artifact_is_pretty_printed(self, mock_get, mock_client_class, adapter_with_formats):
        """v2 JSON artifact text is re-serialised as pretty-printed JSON."""
        raw_json = '{"pages":[{"page_no":1}],"text":"hello"}'
        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                        {"artifact_type": "json", "uri": "http://s3/doc.json"},
                    ]
                }
            ],
            "processing_time": 1.5,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Markdown", "doc.json": raw_json})

        result = adapter_with_formats.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        import json

        parsed = json.loads(result[OperatorConstants.Columns.CONTENT_JSON])
        assert parsed["text"] == "hello"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_json_invalid_body_kept_as_text(self, mock_get, mock_client_class, adapter_with_formats):
        """v2 JSON artifact that is not valid JSON is kept as raw text."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                        {"artifact_type": "json", "uri": "http://s3/doc.json"},
                    ]
                }
            ],
            "processing_time": 1.0,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Markdown", "doc.json": "not-valid-json{"})

        result = adapter_with_formats.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        # Kept as the raw string rather than crashing
        assert result[OperatorConstants.Columns.CONTENT_JSON] == "not-valid-json{"

    # ------------------------------------------------------------------
    # edge / error cases
    # ------------------------------------------------------------------
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_v2_empty_documents_list(self, mock_client_class, adapter):
        """v2 response with an empty documents list returns empty markdown."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [],
            "processing_time": 0.5,
        }

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == ""

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_artifact_fetch_failure_skipped(self, mock_get, mock_client_class, adapter):
        """Network error when fetching a v2 artifact is logged and skipped; overall result succeeds."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [{"artifacts": [{"artifact_type": "markdown", "uri": "http://s3/doc.md"}]}],
            "processing_time": 1.0,
        }
        mock_get.side_effect = Exception("Timeout")

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        # Fetch failed but the adapter handles it gracefully
        assert result[OperatorConstants.Extraction.SUCCESS] is True
        # Markdown was not populated since the fetch failed
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == ""

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    def test_v2_artifact_missing_uri_not_fetched(self, mock_client_class, adapter):
        """v2 artifact without a URI field is silently skipped."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [{"artifacts": [{"artifact_type": "markdown"}]}],  # no uri key
            "processing_time": 1.0,
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get"
        ) as mock_get:
            result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")
            mock_get.assert_not_called()

        assert result[OperatorConstants.Extraction.SUCCESS] is True

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_unknown_artifact_type_ignored(self, mock_get, mock_client_class, adapter):
        """Unknown artifact types not in ARTIFACT_TYPE_TO_FORMAT are ignored."""
        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                        {"artifact_type": "unknown_format", "uri": "http://s3/unknown"},
                    ]
                }
            ],
            "processing_time": 1.0,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Markdown"})

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == "# Markdown"

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_primary_format_missing_from_artifacts_not_inserted(
        self, mock_get, mock_client_class, adapter_with_formats
    ):
        """If no primary artifact was fetched, primary format is NOT prepended to formats.

        Regression guard for the bug where formats_generated.insert() ran unconditionally
        even when DOC_COLUMN_DEFAULT was None/empty, making a failed fetch look successful.
        With the fix, a missing primary artifact leaves DOC_COLUMN_DEFAULT empty and does NOT
        add the primary format to formats_generated — preventing None content from flowing
        silently downstream.
        """
        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "html", "uri": "http://s3/doc.html"},
                    ]
                }
            ],
            "processing_time": 1.0,
        }
        mock_get.side_effect = self._mock_get({"doc.html": "<h1>HTML only</h1>"})

        result = adapter_with_formats.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        formats = result[OperatorConstants.Metadata.METADATA]["formats"]
        # Primary format (markdown) was never fetched — must NOT appear in formats_generated
        assert OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN not in formats
        # The html artifact that was fetched is still present
        assert "html" in formats
        # DOC_COLUMN_DEFAULT must be empty/falsy — not silently filled with None
        assert not result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_doclang_primary_missing_from_artifacts_not_inserted(self, mock_get, mock_client_class):
        """When doc_format=doclang and doclang artifact fails, it is NOT inserted into formats_generated.

        Regression guard: a v2 server that produces no doclang artifact (e.g., only markdown)
        must not silently pretend doclang was produced. Without this guard a None content column
        would flow downstream into RedactionOperator or VectorDBOperator.
        """
        config = {
            "docling_serve_config": {"base_url": "http://localhost:5001"},
            OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG,
        }
        adapter = DoclingServeAdapter(config=config)

        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        # Server only returns markdown, no doclang artifact at all
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                    ]
                }
            ],
            "processing_time": 0.9,
        }
        mock_get.side_effect = self._mock_get({"doc.md": "# Fallback markdown"})

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        formats = result[OperatorConstants.Metadata.METADATA]["formats"]
        # doclang was never produced — must NOT be inserted
        assert OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG not in formats
        # DOC_COLUMN_DEFAULT must be empty (doclang was the primary, never fetched)
        assert not result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_v2_doclang_primary_format_fetches_and_sets_doc_column(self, mock_get, mock_client_class):
        """When doc_format='doclang', v2 doclang artifact is set on DOC_COLUMN_DEFAULT."""
        doclang_xml = '<doclang version="0.7"><text>Hello DocLang</text></doclang>'
        config = {
            "docling_serve_config": {"base_url": "http://localhost:5001"},
            OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG,
            "global_config": {OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG},
        }
        adapter = DoclingServeAdapter(config=config)

        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "doclang", "uri": "http://s3/doc.xml"},
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                    ]
                }
            ],
            "processing_time": 1.2,
        }
        mock_get.side_effect = self._mock_get({"doc.xml": doclang_xml, "doc.md": "# Ignored MD"})

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == doclang_xml
        formats = result[OperatorConstants.Metadata.METADATA]["formats"]
        assert formats[0] == OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG

    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient")
    @patch("docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.requests.get")
    def test_doclang_format_from_global_config_only_triggers_doclang_request(self, mock_get, mock_client_class):
        """doc_format injected by ExtractOperator lives only in the merged global_config dict.

        Regression guard for the bug where _init_adapter_config read doc_format from the
        adapter-specific 'config' sub-dict instead of self.global_config.  When the key is
        present only at the top-level of the merged config (as ExtractOperator sets it), the
        doclang artifact must still be requested and returned as the primary content column.
        """
        doclang_xml = '<doclang version="0.7"><text>Global config path</text></doclang>'
        # Simulate exactly what TextExtractionAdapterFactory.create_adapter produces:
        # full_config = {**global_config, **adapter_config} where global_config carries
        # DOC_FORMAT_KEY and adapter_config contains the adapter-specific docling_serve_config.
        # There is NO nested "global_config" sub-dict and the key does NOT appear inside
        # docling_serve_config — only at the top level of the merged dict.
        config = {
            OperatorConstants.DOC_FORMAT_KEY: OperatorConstants.DocFormat.DOCLANG,
            "docling_serve_config": {"base_url": "http://localhost:5001"},
        }
        adapter = DoclingServeAdapter(config=config)

        mock_client_class.return_value.process_document.return_value = {
            "documents": [
                {
                    "artifacts": [
                        {"artifact_type": "doclang", "uri": "http://s3/doc.xml"},
                        {"artifact_type": "markdown", "uri": "http://s3/doc.md"},
                    ]
                }
            ],
            "processing_time": 0.8,
        }
        mock_get.side_effect = self._mock_get({"doc.xml": doclang_xml, "doc.md": "# Should not appear"})

        result = adapter.extract_single_document(file_path="/doc.pdf", binary_content=b"pdf")

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert result[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] == doclang_xml
        formats = result[OperatorConstants.Metadata.METADATA]["formats"]
        assert formats[0] == OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG


# ---------------------------------------------------------------------------
# Tests for get_config_schema()
# ---------------------------------------------------------------------------
class TestDoclingServeAdapterConfigSchema:
    """Tests for the get_config_schema() static method and the DoclingServeConfig model."""

    def test_returns_docling_serve_config_class(self):
        """Returns the DoclingServeConfig Pydantic model (not an instance)."""
        from pydantic import BaseModel

        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_config import (
            DoclingServeConfig,
        )

        schema_cls = DoclingServeAdapter.get_config_schema()
        assert schema_cls is DoclingServeConfig
        assert issubclass(schema_cls, BaseModel)

    def test_callable_on_class_without_instance(self):
        """get_config_schema is a @staticmethod — callable without instantiation."""
        result = DoclingServeAdapter.get_config_schema()
        assert result is not None

    def test_schema_has_required_fields(self):
        """DoclingServeConfig contains every documented user-facing field."""
        fields = DoclingServeAdapter.get_config_schema().model_fields
        for name in (
            "base_url",
            "api_key",
            "timeout",
            "poll_interval",
            "max_retries",
            "verify_ssl",
            "do_ocr",
            "pdf_backend",
        ):
            assert name in fields, f"Expected field '{name}' missing from schema"

    def test_defaults_are_sensible(self):
        """DoclingServeConfig instantiates with documented defaults."""
        cfg = DoclingServeAdapter.get_config_schema()()
        assert cfg.base_url == "http://0.0.0.0:5001"
        assert cfg.timeout == 300
        assert cfg.poll_interval == 2
        assert cfg.max_retries == 3
        assert cfg.verify_ssl is True
        assert cfg.do_ocr is True
        assert cfg.pdf_backend == "dlparse_v2"
        assert cfg.api_key is None

    def test_model_json_schema_is_non_empty_dict(self):
        """model_json_schema() returns a dict with at least one property."""
        js = DoclingServeAdapter.get_config_schema().model_json_schema()
        assert isinstance(js, dict)
        assert js.get("properties")

    def test_image_export_mode_default(self):
        cfg = DoclingServeAdapter.get_config_schema()()
        assert cfg.image_export_mode == "placeholder"

    def test_ocr_engine_default_is_none(self):
        cfg = DoclingServeAdapter.get_config_schema()()
        assert cfg.ocr_engine is None

    @pytest.mark.parametrize("value", ["dlparse_v2", "pypdfium2"])
    def test_pdf_backend_valid(self, value):
        cfg = DoclingServeAdapter.get_config_schema()(pdf_backend=value)
        assert cfg.pdf_backend == value

    def test_pdf_backend_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DoclingServeAdapter.get_config_schema()(pdf_backend="unknown_backend")

    @pytest.mark.parametrize("value", ["placeholder", "embedded"])
    def test_image_export_mode_valid(self, value):
        cfg = DoclingServeAdapter.get_config_schema()(image_export_mode=value)
        assert cfg.image_export_mode == value

    def test_image_export_mode_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DoclingServeAdapter.get_config_schema()(image_export_mode="raw")

    def test_ocr_engine_accepts_arbitrary_string(self):
        """ocr_engine is str | None — server-dependent, no enum constraint."""
        cfg = DoclingServeAdapter.get_config_schema()(ocr_engine="tesseract")
        assert cfg.ocr_engine == "tesseract"

    # --- valid_values surfaces in JSON schema ---

    def test_pdf_backend_enum_in_json_schema(self):
        schema = DoclingServeAdapter.get_config_schema().model_json_schema()
        assert "enum" in schema["properties"]["pdf_backend"]

    def test_image_export_mode_enum_in_json_schema(self):
        schema = DoclingServeAdapter.get_config_schema().model_json_schema()
        assert "enum" in schema["properties"]["image_export_mode"]

    def test_ocr_engine_no_enum_in_json_schema(self):
        """ocr_engine is str | None — no enum constraint expected."""
        schema = DoclingServeAdapter.get_config_schema().model_json_schema()
        assert "enum" not in str(schema["properties"]["ocr_engine"])


# ---------------------------------------------------------------------------
# DoclingLibraryConfig.additional_formats — markdown acceptance tests
# ---------------------------------------------------------------------------
class TestDoclingLibraryConfigAdditionalFormats:
    """Tests that DoclingLibraryConfig accepts 'markdown' in additional_formats.

    When doc_format=doclang, users legitimately want to also request markdown
    as a secondary column. The schema must allow it.
    """

    def test_markdown_accepted_in_additional_formats(self):
        """'markdown' is a valid additional_formats value."""
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_library_config import (
            DoclingLibraryConfig,
        )

        cfg = DoclingLibraryConfig(additional_formats=["markdown"])
        assert "markdown" in cfg.additional_formats

    def test_markdown_alongside_doclang_accepted(self):
        """User can request both doclang (primary) and markdown (secondary)."""
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_library_config import (
            DoclingLibraryConfig,
        )

        cfg = DoclingLibraryConfig(additional_formats=["doclang", "markdown"])
        assert "doclang" in cfg.additional_formats
        assert "markdown" in cfg.additional_formats

    def test_invalid_format_still_rejected(self):
        """Unrecognised format strings are still rejected by the schema."""
        from pydantic import ValidationError

        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_library_config import (
            DoclingLibraryConfig,
        )

        with pytest.raises(ValidationError):
            DoclingLibraryConfig(additional_formats=["xml"])
