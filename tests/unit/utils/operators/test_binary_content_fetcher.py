"""Unit tests for binary_content_fetcher utility."""

import zipfile
from unittest.mock import MagicMock, patch


class TestGetBinaryContentLocalFile:
    """Tests for get_binary_content using local filesystem path."""

    def test_reads_local_file_via_path(self, tmp_path):
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"PDF content")

        result = get_binary_content(doc_metadata={"path": str(f)}, global_config={})

        assert result == b"PDF content"

    def test_reads_local_file_via_file_url(self, tmp_path):
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        f = tmp_path / "doc.txt"
        f.write_bytes(b"text content")

        result = get_binary_content(
            doc_metadata={"path": f"file://{f}"},
            global_config={},
        )

        assert result == b"text content"

    def test_missing_path_raises(self):
        import pytest

        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        with pytest.raises(ValueError, match="missing 'path'"):
            get_binary_content(doc_metadata={}, global_config={})

    def test_nonexistent_file_raises(self):
        import pytest

        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        with pytest.raises(FileNotFoundError, match="Local file not found"):
            get_binary_content(
                doc_metadata={"path": "/nonexistent/path/file.pdf"},
                global_config={},
            )

    def test_path_is_directory_raises(self, tmp_path):
        import pytest

        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        with pytest.raises(ValueError, match="Path is not a file"):
            get_binary_content(
                doc_metadata={"path": str(tmp_path)},
                global_config={},
            )

    def test_reads_archive_entry_via_zip_uri(self, tmp_path):
        from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.archive import build_archive_uri
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        archive_path = tmp_path / "documents.zip"
        with zipfile.ZipFile(archive_path, mode="w") as archive:
            archive.writestr("folder/doc.txt", b"archived content")
        source_id = build_archive_uri(archive_path=archive_path, entry_name="folder/doc.txt")

        result = get_binary_content(doc_metadata={"source_id": source_id}, global_config={})

        assert result == b"archived content"


class TestGetBinaryContentCloudSource:
    """Tests for get_binary_content with cloud ingest_source config."""

    def test_uses_cloud_adapter_when_ingest_source_present(self, tmp_path):
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        mock_adapter = MagicMock()
        mock_adapter.fetch_binary_content.return_value = b"cloud data"

        ingest_source = {
            OperatorConstants.Config.PROVIDER: "s3",
            OperatorConstants.Config.PROVIDER_CONFIG: {"bucket": "my-bucket", "access_key": "key"},
        }

        with (
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.is_registered",
                return_value=True,
            ),
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.create",
                return_value=mock_adapter,
            ),
            patch(
                "docpipe.core.operators.operator_utils.resolve_env_var",
                side_effect=lambda v: v,
            ),
        ):
            result = get_binary_content(
                doc_metadata={"source_id": "docs/file.pdf", "name": "file.pdf"},
                global_config={OperatorConstants.Config.INGEST_SOURCE: ingest_source},
            )

        assert result == b"cloud data"

    def test_missing_provider_returns_none(self):
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        ingest_source: dict = {
            OperatorConstants.Config.PROVIDER_CONFIG: {},
        }

        result = get_binary_content(
            doc_metadata={"source_id": "file.pdf"},
            global_config={OperatorConstants.Config.INGEST_SOURCE: ingest_source},
        )

        assert result is None

    def test_missing_source_id_returns_none(self):
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        ingest_source = {
            OperatorConstants.Config.PROVIDER: "s3",
            OperatorConstants.Config.PROVIDER_CONFIG: {},
        }

        result = get_binary_content(
            doc_metadata={},
            global_config={OperatorConstants.Config.INGEST_SOURCE: ingest_source},
        )

        assert result is None

    def test_unregistered_provider_returns_none(self):
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.utils.operators.binary_content_fetcher import get_binary_content

        ingest_source = {
            OperatorConstants.Config.PROVIDER: "unknown_provider",
            OperatorConstants.Config.PROVIDER_CONFIG: {},
        }

        with (
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.is_registered",
                return_value=False,
            ),
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.get_registered_names",
                return_value=["s3", "filesystem"],
            ),
        ):
            result = get_binary_content(
                doc_metadata={"source_id": "file.pdf"},
                global_config={OperatorConstants.Config.INGEST_SOURCE: ingest_source},
            )

        assert result is None


class TestGetAdapterForProvider:
    """Tests for get_adapter_for_provider."""

    def test_returns_adapter_for_registered_provider(self):
        from docpipe.utils.operators.binary_content_fetcher import get_adapter_for_provider

        mock_adapter = MagicMock()

        with (
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.is_registered",
                return_value=True,
            ),
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.create",
                return_value=mock_adapter,
            ),
        ):
            result = get_adapter_for_provider(
                provider="s3",
            )

        assert result is mock_adapter

    def test_returns_none_for_unregistered_provider(self):
        from docpipe.utils.operators.binary_content_fetcher import get_adapter_for_provider

        with (
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.is_registered",
                return_value=False,
            ),
            patch(
                "docpipe.utils.operators.binary_content_fetcher.SourceAdapterFactory.get_registered_names",
                return_value=["s3"],
            ),
        ):
            result = get_adapter_for_provider(
                provider="no_such_provider",
            )

        assert result is None
