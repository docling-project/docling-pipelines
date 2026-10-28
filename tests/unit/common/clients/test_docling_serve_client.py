# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for DoclingServeClient.
"""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.docling.client import DoclingServeClient


class TestDoclingServeClient:
    """Test suite for DoclingServeClient."""

    def test_init_default_values(self):
        """Test client initialization with default values."""
        client = DoclingServeClient(base_url="http://localhost:5001")
        assert client.base_url == "http://localhost:5001"
        assert client.api_key is None
        assert client.timeout == 300
        assert client.poll_interval == 2
        # max_retries is passed to RestClient but not stored as instance attribute

    def test_init_empty_base_url_validation(self):
        """Test client initialization validates empty base_url."""
        with pytest.raises(ValueError, match="base_url must not be empty"):
            DoclingServeClient(base_url="")

    def test_init_whitespace_base_url_validation(self):
        """Test client initialization validates whitespace-only base_url."""
        with pytest.raises(ValueError, match="base_url must not be empty"):
            DoclingServeClient(base_url="   ")

    def test_init_custom_values(self):
        """Test client initialization with custom values."""
        client = DoclingServeClient(
            base_url="http://localhost:8000",
            api_key="test-key",  # pragma: allowlist secret
            timeout=600,
            poll_interval=5,
            max_retries=5,
        )
        assert client.base_url == "http://localhost:8000"
        assert client.api_key == "test-key"  # pragma: allowlist secret
        assert client.timeout == 600
        assert client.poll_interval == 5
        # max_retries is passed to RestClient but not stored as instance attribute
        assert client.custom_headers["X-API-KEY"] == "test-key"

    def test_build_options_defaults(self):
        """Test default options building."""
        client = DoclingServeClient(base_url="http://localhost:5001")
        options = client._build_options()

        assert options["do_ocr"] is True
        assert options["do_table_structure"] is True
        assert options["pdf_backend"] == "dlparse_v2"
        assert options["images_scale"] == 2.0

    def test_build_options_override(self):
        """Test options override."""
        client = DoclingServeClient(base_url="http://localhost:5001")
        custom_options = {"do_ocr": False, "custom_param": "value"}
        options = client._build_options(custom_options)

        assert options["do_ocr"] is False
        assert options["custom_param"] == "value"
        assert options["do_table_structure"] is True  # Default preserved

    def test_submit_document_validation_error(self):
        """Test submit_document raises error when both params provided."""
        client = DoclingServeClient(base_url="http://localhost:5001")

        with pytest.raises(ValueError, match="Provide exactly one"):
            client.submit_document(file_path="test.pdf", binary_content=b"data")

    def test_submit_document_validation_error_neither(self):
        """Test submit_document raises error when neither param provided."""
        client = DoclingServeClient(base_url="http://localhost:5001")

        with pytest.raises(ValueError, match="Provide exactly one"):
            client.submit_document()

    @patch("docpipe.integrations.docling.client.Path")
    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_with_file_path(self, mock_rest_client_class, mock_path):
        """Test submit_document with file path."""
        # Setup mocks
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.read_bytes.return_value = b"test content"
        mock_path_instance.name = "test.pdf"
        mock_path.return_value = mock_path_instance

        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task-123"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        task_id = client.submit_document(file_path="test.pdf")

        # Verify
        assert task_id == "test-task-123"
        mock_rest_client_instance.call_rest_multipart.assert_called_once()
        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        assert "files" in call_args.kwargs
        assert "form_data" in call_args.kwargs

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_with_binary_content(self, mock_rest_client_class):
        """Test submit_document with binary content."""
        # Setup mock
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task-456"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        binary_data = b"test binary content"
        task_id = client.submit_document(binary_content=binary_data)

        # Verify
        assert task_id == "test-task-456"
        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        assert "files" in call_args.kwargs
        files = call_args.kwargs["files"]
        # Verify the file content is passed correctly
        assert "files" in files
        _, content, _ = files["files"]
        assert content == binary_data

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_with_binary_content_and_filename(self, mock_rest_client_class):
        """Test submit_document with binary content and custom filename."""
        # Setup mock
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task-789"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        binary_data = b"test binary content"
        task_id = client.submit_document(binary_content=binary_data, filename="custom.docx")

        # Verify
        assert task_id == "test-task-789"
        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        filename, content, mime_type = files["files"]
        assert filename == "custom.docx"
        assert content == binary_data
        assert mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_pdf(self, mock_rest_client_class):
        """Test MIME type detection for PDF files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="document.pdf")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "application/pdf"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_docx(self, mock_rest_client_class):
        """Test MIME type detection for DOCX files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="document.docx")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_html(self, mock_rest_client_class):
        """Test MIME type detection for HTML files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="page.html")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "text/html"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_markdown(self, mock_rest_client_class):
        """Test MIME type detection for Markdown files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="readme.md")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "text/markdown"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_txt(self, mock_rest_client_class):
        """Test MIME type detection for TXT files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="notes.txt")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "text/plain"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_xlsx(self, mock_rest_client_class):
        """Test MIME type detection for XLSX files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="spreadsheet.xlsx")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_pptx(self, mock_rest_client_class):
        """Test MIME type detection for PPTX files."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="presentation.pptx")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_mime_type_detection_unknown_extension(self, mock_rest_client_class):
        """Test MIME type detection defaults to octet-stream for unknown extensions."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="file.xyz")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        _, _, mime_type = files["files"]
        assert mime_type == "application/octet-stream"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_filename_preservation_in_binary_content(self, mock_rest_client_class):
        """Test that filename is preserved when using binary_content."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        client.submit_document(binary_content=b"data", filename="important_doc.pdf")

        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        filename, _, _ = files["files"]
        assert filename == "important_doc.pdf"

    @patch("docpipe.integrations.docling.client.RestClient")
    def test_submit_document_filename_optional_backward_compatibility(self, mock_rest_client_class):
        """Test that filename parameter is optional for backward compatibility."""
        mock_rest_client_instance = MagicMock()
        mock_rest_client_instance.call_rest_multipart.return_value = {"task_id": "test-task"}
        mock_rest_client_class.return_value = mock_rest_client_instance

        client = DoclingServeClient(base_url="http://localhost:5001")
        # Should not raise error when filename is not provided
        task_id = client.submit_document(binary_content=b"data")

        assert task_id == "test-task"
        call_args = mock_rest_client_instance.call_rest_multipart.call_args
        files = call_args.kwargs["files"]
        filename, _, _ = files["files"]
        # Should default to "document.pdf"
        assert filename == "document.pdf"

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_multipart")
    def test_submit_document_http_error(self, mock_call_rest_multipart):
        """Test submit_document handles HTTP errors."""
        mock_call_rest_multipart.side_effect = DocpipeException(
            message="Connection failed",
            status_code=503,
            error_code=ErrorCode.CONNECTION_ERROR,
        )

        client = DoclingServeClient(base_url="http://localhost:5001")
        with pytest.raises(DocpipeException, match="Connection failed"):
            client.submit_document(binary_content=b"data")

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_json")
    @patch("docpipe.integrations.docling.client.time.sleep")
    def test_poll_status_success(self, mock_sleep, mock_call_rest_json):
        """Test poll_status with successful completion."""
        # Setup mock responses
        mock_call_rest_json.return_value = {"task_status": "SUCCESS", "progress": 100}

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        status = client.poll_status(task_id="test-task-123")

        # Verify
        assert status["task_status"] == "SUCCESS"
        mock_call_rest_json.assert_called_once()

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_json")
    @patch("docpipe.integrations.docling.client.time.sleep")
    def test_poll_status_pending_then_success(self, mock_sleep, mock_call_rest_json):
        """Test poll_status with pending then success."""

        # Setup mock responses
        mock_call_rest_json.side_effect = [
            {"task_status": "PENDING"},
            {"task_status": "STARTED"},
            {"task_status": "SUCCESS"},
        ]

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        status = client.poll_status(task_id="test-task-123")

        # Verify
        assert status["task_status"] == "SUCCESS"
        assert mock_call_rest_json.call_count == 3

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_json")
    def test_poll_status_failure(self, mock_call_rest_json):
        """Test poll_status with task failure."""
        mock_call_rest_json.return_value = {
            "task_status": "FAILURE",
            "error": "Processing failed",
        }

        client = DoclingServeClient(base_url="http://localhost:5001")
        with pytest.raises(DocpipeException, match="Task test-task-123 failed"):
            client.poll_status(task_id="test-task-123")

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_json")
    def test_get_result_success(self, mock_call_rest_json):
        """Test get_result retrieves document data."""
        mock_call_rest_json.return_value = {"document": "data", "metadata": {}}

        client = DoclingServeClient(base_url="http://localhost:5001")
        result = client.get_result(task_id="test-task-123")

        assert "document" in result
        assert result["document"] == "data"

    @patch("docpipe.integrations.docling.client.RestClient.call_rest_json")
    def test_get_result_http_error(self, mock_call_rest_json):
        """Test get_result handles HTTP errors."""
        mock_call_rest_json.side_effect = DocpipeException(
            message="Network error",
            status_code=503,
            error_code=ErrorCode.CONNECTION_ERROR,
        )

        client = DoclingServeClient(base_url="http://localhost:5001")
        with pytest.raises(DocpipeException, match="Network error"):
            client.get_result(task_id="test-task-123")

    @patch.object(DoclingServeClient, "submit_document")
    @patch.object(DoclingServeClient, "_poll_for_completion")
    @patch.object(DoclingServeClient, "get_result")
    def test_process_document_integration(self, mock_get_result, mock_poll_for_completion, mock_submit):
        """Test process_document integrates all steps."""
        # Setup mocks
        mock_submit.return_value = "test-task-123"
        # Mock _poll_for_completion to return a status dict with lowercase "success"
        mock_poll_for_completion.return_value = {
            "task_status": "success",
            "result": {"document": "processed"},
        }
        mock_get_result.return_value = {"document": "processed"}

        # Execute
        client = DoclingServeClient(base_url="http://localhost:5001")
        result = client.process_document(binary_content=b"data")

        # Verify all methods called
        mock_submit.assert_called_once()
        mock_poll_for_completion.assert_called_once_with(
            task_id="test-task-123", poll_interval=None, timeout=7200, filename=None
        )
        mock_get_result.assert_called_once_with(task_id="test-task-123")
        assert result["document"] == "processed"
