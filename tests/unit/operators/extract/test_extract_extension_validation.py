#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for ExtractOperator extension validation.

Tests the extension validation functionality that validates file extensions
before extraction, similar to DocumentClassifierOperator.
"""

from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.extract_operator import ExtractOperator


@pytest.fixture
def mock_table_with_extensions():
    """Create a mock PyArrow table with various file extensions."""
    return pa.table(
        {
            "id": ["doc1", "doc2", "doc3", "doc4", "doc5", "doc6"],
            "name": [
                "document.pdf",  # Supported
                "image.png",  # Supported
                "audio.mp3",  # Supported only with ASR
                "video.mp4",  # Supported only with ASR
                "unsupported.xyz",  # Unsupported
                "text.txt",  # Supported
            ],
            "path": [
                "/path/to/document.pdf",
                "/path/to/image.png",
                "/path/to/audio.mp3",
                "/path/to/video.mp4",
                "/path/to/unsupported.xyz",
                "/path/to/text.txt",
            ],
        }
    )


@pytest.fixture
def docling_library_config():
    """Configuration for docling_library mode."""
    return {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "max_workers": 2,
    }


@pytest.fixture
def docling_serve_config():
    """Configuration for docling_serve mode."""
    return {
        "text_extraction": {
            "provider": "docling_serve",
            "doc_column": "doc_content",
            "provider_config": {
                "base_url": "http://localhost:5001",
            },
        },
        "max_workers": 2,
    }


class TestExtractOperatorExtensionValidation:
    """Test suite for ExtractOperator extension validation."""

    def test_get_supported_extensions_docling_library_without_asr(self, docling_library_config):
        """Test _get_supported_extensions for docling_library mode without ASR."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
            operator = ExtractOperator(config=docling_library_config)
            extensions = operator._get_supported_extensions()

            # Should include base extensions
            assert ".pdf" in extensions
            assert ".docx" in extensions
            assert ".png" in extensions
            assert ".txt" in extensions
            assert ".md" in extensions

            # Audio is gated by ASR; supported video extensions remain eligible
            assert ".mp3" not in extensions
            assert ".mp4" in extensions
            assert ".wav" not in extensions

    def test_get_supported_extensions_docling_library_with_asr(self, docling_library_config):
        """Test _get_supported_extensions for docling_library mode with ASR."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=True):
            operator = ExtractOperator(config=docling_library_config)
            extensions = operator._get_supported_extensions()

            # Should include base extensions
            assert ".pdf" in extensions
            assert ".docx" in extensions

            # Should include audio/video with ASR
            assert ".mp3" in extensions
            assert ".mp4" in extensions
            assert ".wav" in extensions
            assert ".avi" in extensions

    def test_get_supported_extensions_docling_serve(self, docling_serve_config):
        """Test _get_supported_extensions for docling_serve mode (no audio/video)."""
        operator = ExtractOperator(config=docling_serve_config)
        extensions = operator._get_supported_extensions()

        # Should include base extensions
        assert ".pdf" in extensions
        assert ".docx" in extensions
        assert ".png" in extensions
        assert ".txt" in extensions

        # Should NOT include audio/video (Docling Serve doesn't support them)
        assert ".mp3" not in extensions
        assert ".mp4" not in extensions
        assert ".wav" not in extensions

    def test_validate_extensions_skips_unsupported_files(self, docling_library_config, mock_table_with_extensions):
        """Test that _validate_extensions skips files with unsupported extensions."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
            operator = ExtractOperator(config=docling_library_config)
            metadata = operator.create_base_metadata(total_docs_count=mock_table_with_extensions.num_rows)

            skipped_indices = operator._validate_extensions(table=mock_table_with_extensions, metadata=metadata)

            # Should skip audio without ASR and unsupported extensions
            assert len(skipped_indices) == 2  # .mp3, .xyz
            assert 2 in skipped_indices  # audio.mp3
            assert 3 not in skipped_indices  # video.mp4
            assert 4 in skipped_indices  # unsupported.xyz

            # Should NOT skip supported files
            assert 0 not in skipped_indices  # document.pdf
            assert 1 not in skipped_indices  # image.png
            assert 5 not in skipped_indices  # text.txt

    def test_validate_extensions_with_asr_allows_audio_video(self, docling_library_config, mock_table_with_extensions):
        """Test that audio/video files are allowed when ASR is available."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=True):
            operator = ExtractOperator(config=docling_library_config)
            metadata = operator.create_base_metadata(total_docs_count=mock_table_with_extensions.num_rows)

            skipped_indices = operator._validate_extensions(table=mock_table_with_extensions, metadata=metadata)

            # Should only skip unsupported extension
            assert len(skipped_indices) == 1
            assert 4 in skipped_indices  # unsupported.xyz

            # Audio/video should NOT be skipped with ASR
            assert 2 not in skipped_indices  # audio.mp3
            assert 3 not in skipped_indices  # video.mp4

    def test_validate_extensions_records_skipped_documents(self, docling_library_config, mock_table_with_extensions):
        """Test that skipped documents are recorded in metadata."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
            operator = ExtractOperator(config=docling_library_config)
            metadata = operator.create_base_metadata(total_docs_count=mock_table_with_extensions.num_rows)

            operator._validate_extensions(table=mock_table_with_extensions, metadata=metadata)

            # Check that skipped documents are recorded
            assert "skipped_docs" in metadata
            skipped_docs = metadata["skipped_docs"]

            # Should have 2 skipped documents
            assert len(skipped_docs) == 2

            # Verify skipped document details
            skipped_names = [doc["name"] for doc in skipped_docs]
            assert "audio.mp3" in skipped_names
            assert "video.mp4" not in skipped_names
            assert "unsupported.xyz" in skipped_names

    def test_validate_extensions_with_missing_name_column(self, docling_library_config):
        """Test that validation handles tables without name column gracefully."""
        table = pa.table(
            {
                "id": ["doc1", "doc2"],
                "path": ["/path/to/doc1", "/path/to/doc2"],
            }
        )

        operator = ExtractOperator(config=docling_library_config)
        metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

        skipped_indices = operator._validate_extensions(table=table, metadata=metadata)

        # Should return empty set when name column is missing
        assert len(skipped_indices) == 0

    def test_validate_extensions_fallback_to_document_format_for_url_names(self, docling_library_config):
        """Test that document_format column is used when name is a URL without a file extension.

        This covers cloud sources like Box and OneDrive where the 'name' column
        is set to the source URL (e.g. https://app.box.com/file/12345) which has
        no file extension.
        """
        table = pa.table(
            {
                "id": ["doc1", "doc2"],
                "name": [
                    "https://app.box.com/file/2350816183103",  # URL — no suffix
                    "https://app.box.com/file/9999999999999",  # URL — no suffix, unsupported format
                ],
                "path": [
                    "https://app.box.com/file/2350816183103",
                    "https://app.box.com/file/9999999999999",
                ],
                "document_format": ["pdf", "xyz"],
            }
        )

        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
            operator = ExtractOperator(config=docling_library_config)
            metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

            skipped_indices = operator._validate_extensions(table=table, metadata=metadata)

            # pdf should be accepted via document_format fallback
            assert 0 not in skipped_indices
            # xyz is unsupported even via document_format fallback
            assert 1 in skipped_indices

    def test_validate_extensions_error_message_includes_mode(self, docling_library_config, mock_table_with_extensions):
        """Test that error messages include the extraction mode."""
        with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
            operator = ExtractOperator(config=docling_library_config)
            metadata = operator.create_base_metadata(total_docs_count=mock_table_with_extensions.num_rows)

            operator._validate_extensions(table=mock_table_with_extensions, metadata=metadata)

            # Check that error messages include mode
            skipped_docs = metadata["skipped_docs"]
            for doc in skipped_docs:
                assert "docling_library" in doc["reason"].lower()
                assert "unsupported file extension" in doc["reason"].lower()


class TestEntityExtractionExtensionValidation:
    """Test suite for entity extraction extension validation."""

    def test_entity_extraction_supported_extensions(self):
        """Test that entity extraction supports PDF, office formats, and image formats."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        entity_extensions = set(OperatorConstants.FileExtensions.DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY)

        # Should include PDF
        assert ".pdf" in entity_extensions

        # Should include image formats
        assert ".png" in entity_extensions
        assert ".jpg" in entity_extensions
        assert ".jpeg" in entity_extensions
        assert ".tiff" in entity_extensions
        assert ".tif" in entity_extensions
        assert ".bmp" in entity_extensions
        assert ".gif" in entity_extensions
        assert ".jfif" in entity_extensions

        # Should NOT include text formats
        assert ".txt" not in entity_extensions
        assert ".md" not in entity_extensions
        assert ".html" not in entity_extensions

        # Should NOT include office formats
        assert ".docx" not in entity_extensions
        assert ".pptx" not in entity_extensions
        assert ".xlsx" not in entity_extensions


class TestOperatorUtilsExtensionValidation:
    """Test suite for OperatorUtils.prepare_document_content_fetch extension validation."""

    def test_prepare_document_content_fetch_with_supported_extensions(self):
        """Test that prepare_document_content_fetch validates extensions."""
        from docpipe.core.operators.operator_utils import OperatorUtils

        table = pa.table(
            {
                "id": ["doc1", "doc2", "doc3"],
                "name": ["document.pdf", "image.png", "unsupported.xyz"],
                "path": ["/path/to/document.pdf", "/path/to/image.png", "/path/to/unsupported.xyz"],
            }
        )

        supported_extensions = {".pdf", ".png"}

        with patch("docpipe.utils.operators.binary_content_fetcher.get_binary_content") as mock_get_binary:
            # Mock successful binary content fetch
            mock_get_binary.return_value = b"fake binary content"

            doc_tasks = OperatorUtils.prepare_document_content_fetch(
                table=table, global_config={}, supported_extensions=supported_extensions
            )

            # Should have 3 tasks (2 valid, 1 with error)
            assert len(doc_tasks) == 3

            # First two should be valid
            assert "error" not in doc_tasks[0]
            assert "error" not in doc_tasks[1]

        # Third should have error
        assert "error" in doc_tasks[2]
        assert "skip_reason" in doc_tasks[2]
        assert doc_tasks[2]["skip_reason"] == "unsupported_extension"
        assert ".xyz" in doc_tasks[2]["error"]

    def test_prepare_document_content_fetch_without_extension_validation(self):
        """Test that prepare_document_content_fetch works without extension validation."""
        from docpipe.core.operators.operator_utils import OperatorUtils

        table = pa.table(
            {
                "id": ["doc1", "doc2"],
                "name": ["document.pdf", "unsupported.xyz"],
                "path": ["/path/to/document.pdf", "/path/to/unsupported.xyz"],
            }
        )

        with patch("docpipe.utils.operators.binary_content_fetcher.get_binary_content") as mock_get_binary:
            # Mock successful binary content fetch
            mock_get_binary.return_value = b"fake binary content"

            # No supported_extensions parameter - should not validate
            doc_tasks = OperatorUtils.prepare_document_content_fetch(table=table, global_config={})

            # Both tasks should be valid (no validation)
            assert len(doc_tasks) == 2
            assert "error" not in doc_tasks[0]
            assert "error" not in doc_tasks[1]


class TestExtensionConstants:
    """Test suite for extension constants."""

    def test_docling_library_base_extensions_defined(self):
        """Test that DOCLING_LIBRARY_BASE_EXTENSIONS is properly defined."""
        extensions = OperatorConstants.FileExtensions.DOCLING_LIBRARY_BASE_EXTENSIONS

        assert isinstance(extensions, list)
        assert len(extensions) > 0
        assert ".pdf" in extensions
        assert ".docx" in extensions
        assert ".png" in extensions

    def test_docling_library_audio_video_extensions_defined(self):
        """Test that DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS is properly defined."""
        extensions = OperatorConstants.FileExtensions.DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS

        assert isinstance(extensions, list)
        assert len(extensions) > 0
        assert ".mp3" in extensions
        assert ".mp4" in extensions
        assert ".wav" in extensions

    def test_docling_serve_extensions_defined(self):
        """Test that DOCLING_SERVE_EXTENSIONS is properly defined."""
        extensions = OperatorConstants.FileExtensions.DOCLING_SERVE_EXTENSIONS

        assert isinstance(extensions, list)
        assert len(extensions) > 0
        assert ".pdf" in extensions
        assert ".docx" in extensions

        # Docling Serve should NOT include audio/video
        # (They're in BASE_EXTENSIONS, but Serve doesn't support them)

    def test_docling_entity_extensions_pdf_image_only_defined(self):
        """Test that DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY is properly defined."""
        extensions = OperatorConstants.FileExtensions.DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY

        assert isinstance(extensions, list)
        assert len(extensions) > 0
        assert ".pdf" in extensions
        assert ".png" in extensions

        # Should NOT include other formats
        assert ".docx" not in extensions
        assert ".pptx" not in extensions
        assert ".html" not in extensions
        assert ".txt" not in extensions
        assert ".md" not in extensions


@pytest.mark.parametrize("provider, expected_skips", [("docling_library", set()), ("docling_serve", set(range(22)))])
def test_new_formats_respect_extraction_provider(provider, expected_skips):
    """New document formats are local-library only."""
    extensions = "csv epub eml msg tex latex adoc asciidoc asc vtt htm xhtml mhtml mht markdown text qmd rmd pptm xlsm xltx xltm".split()
    table = pa.table({"id": [str(i) for i in range(len(extensions))], "name": [f"sample.{ext}" for ext in extensions]})
    config = {"text_extraction": {"provider": provider, "provider_config": {"base_url": "http://localhost:5001"}}}
    operator = ExtractOperator(config=config)
    metadata = operator.create_base_metadata(total_docs_count=len(extensions))
    assert operator._validate_extensions(table=table, metadata=metadata) == expected_skips
    constants = OperatorConstants.FileExtensions
    assert {f".{ext}" for ext in extensions} <= set(constants.DOCLING_LIBRARY_BASE_EXTENSIONS)
    assert {".mkv", ".webm"} <= set(constants.DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS)
    assert not ({f".{ext}" for ext in extensions} | {".mkv", ".webm"}) & set(constants.DOCLING_SERVE_EXTENSIONS)


def test_supported_video_remains_eligible_without_asr(docling_library_config):
    with patch("docpipe.core.operators.operator_utils.is_asr_available", return_value=False):
        extensions = ExtractOperator(config=docling_library_config)._get_supported_extensions()
    assert ".mp3" not in extensions
    assert {".mp4", ".avi", ".mov", ".mkv", ".webm"} <= extensions


def test_document_format_precedes_filename_and_is_normalized(docling_library_config):
    table = pa.table(
        {
            "id": ["1", "2", "3"],
            "name": ["extensionless", "wrong.xyz", "file.pdf"],
            "document_format": [".CSV", "CSV", "xyz"],
        }
    )
    operator = ExtractOperator(config=docling_library_config)
    metadata = operator.create_base_metadata(total_docs_count=3)
    assert operator._validate_extensions(table=table, metadata=metadata) == {2}


@pytest.mark.parametrize("extension", ["dotx", "docm", "dotm", "potx", "ppsx", "potm", "ppsm"])
def test_unreadable_office_variants_are_skipped(extension, docling_library_config):
    table = pa.table({"id": ["1"], "name": [f"sample.{extension}"]})
    operator = ExtractOperator(config=docling_library_config)
    metadata = operator.create_base_metadata(total_docs_count=1)
    assert operator._validate_extensions(table=table, metadata=metadata) == {0}
    assert metadata["skipped_docs_count"] == 1


@pytest.mark.parametrize("extension", ["mkv", "webm"])
@pytest.mark.parametrize("provider,expected", [("docling_library", set()), ("docling_serve", {0})])
def test_new_video_formats_follow_provider_support(extension, provider, expected):
    table = pa.table({"id": ["1"], "name": [f"sample.{extension}"]})
    config = {"text_extraction": {"provider": provider, "provider_config": {"base_url": "http://localhost:5001"}}}
    operator = ExtractOperator(config=config)
    metadata = operator.create_base_metadata(total_docs_count=1)
    assert operator._validate_extensions(table=table, metadata=metadata) == expected
    assert metadata["skipped_docs_count"] == len(expected)
