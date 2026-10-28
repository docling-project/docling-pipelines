"""Tests for file extension validation in ingestion operators."""

import pytest

from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator


def _filesystem_config(tmp_path, **kwargs) -> dict:
    """Build an IngestSourceOperator config for the filesystem provider."""
    config = {
        "provider": "filesystem",
        "connection_params": {"paths": [str(tmp_path)]},
    }
    config.update(kwargs)
    return config


class TestIngestSourceFilesystemExtensionValidation:
    """Test extension validation for IngestSourceOperator with filesystem provider."""

    def test_unsupported_include_extension_raises_error(self, tmp_path):
        """Test that unsupported extensions in include_filter raise ValueError."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        config = _filesystem_config(tmp_path, include_filter=".xyz,.abc")

        with pytest.raises(ValueError, match="Unsupported file extensions in include_filter"):
            IngestSourceOperator(config)

    def test_unsupported_exclude_extension_raises_error(self, tmp_path):
        """Test that unsupported extensions in exclude_filter raise ValueError."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        config = _filesystem_config(tmp_path, exclude_filter=".xyz,.abc")

        with pytest.raises(ValueError, match="Unsupported file extensions in exclude_filter"):
            IngestSourceOperator(config)

    def test_supported_extensions_accepted(self, tmp_path):
        """Test that supported extensions are accepted."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        config = _filesystem_config(tmp_path, include_filter=".pdf,.docx,.txt")

        # Should not raise
        operator = IngestSourceOperator(config)
        assert operator.included_extensions == [".pdf", ".docx", ".txt"]

    def test_no_include_filter_defaults_to_supported(self, tmp_path):
        """Test that no include_filter defaults to all supported extensions."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        config = _filesystem_config(tmp_path)

        operator = IngestSourceOperator(config)
        assert operator.included_extensions is not None
        assert ".pdf" in operator.included_extensions
        assert ".docx" in operator.included_extensions
        assert ".zip" in operator.included_extensions
        assert ".tar.gz" in operator.included_extensions

    def test_archive_extensions_are_accepted_for_filesystem(self, tmp_path):
        operator = IngestSourceOperator(_filesystem_config(tmp_path, include_filter=".zip,.tar,.tar.gz,.tgz,.gz"))

        assert operator.included_extensions == [".zip", ".tar", ".tar.gz", ".tgz", ".gz"]


class TestIngestSourceExtensionValidation:
    """Test extension validation for IngestSourceOperator with cloud providers."""

    def test_unsupported_include_extension_raises_error(self):
        """Test that unsupported extensions in include_filter raise ValueError."""
        config = {
            "provider": "s3",
            "connection_params": {"bucket": "test-bucket"},
            "credentials": {"access_key": "", "secret_key": ""},
            "include_filter": ".xyz,.abc",
        }

        with pytest.raises(ValueError, match="Unsupported file extensions in include_filter"):
            IngestSourceOperator(config)

    def test_unsupported_exclude_extension_raises_error(self):
        """Test that unsupported extensions in exclude_filter raise ValueError."""
        config = {
            "provider": "s3",
            "connection_params": {"bucket": "test-bucket"},
            "credentials": {"access_key": "", "secret_key": ""},
            "exclude_filter": ".xyz,.abc",
        }

        with pytest.raises(ValueError, match="Unsupported file extensions in exclude_filter"):
            IngestSourceOperator(config)

    def test_supported_extensions_accepted(self):
        """Test that supported extensions are accepted."""
        config = {
            "provider": "s3",
            "connection_params": {"bucket": "test-bucket"},
            "credentials": {"access_key": "", "secret_key": ""},
            "include_filter": ".pdf,.docx,.txt",
        }

        operator = IngestSourceOperator(config)
        assert operator.included_extensions == [".pdf", ".docx", ".txt"]

    def test_no_include_filter_defaults_to_supported(self):
        """Test that no include_filter defaults to all supported extensions."""
        config = {
            "provider": "s3",
            "connection_params": {"bucket": "test-bucket"},
            "credentials": {"access_key": "", "secret_key": ""},
        }

        operator = IngestSourceOperator(config)
        assert operator.included_extensions is not None
        assert ".pdf" in operator.included_extensions
        assert ".docx" in operator.included_extensions

    def test_mixed_supported_and_unsupported_raises_error(self):
        """Test that mixing supported and unsupported extensions raises error."""
        config = {
            "provider": "s3",
            "connection_params": {"bucket": "test-bucket"},
            "credentials": {"access_key": "", "secret_key": ""},
            "include_filter": ".pdf,.xyz",
        }

        with pytest.raises(ValueError, match="Unsupported file extensions"):
            IngestSourceOperator(config)
