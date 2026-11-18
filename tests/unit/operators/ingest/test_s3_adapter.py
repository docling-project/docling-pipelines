"""Unit tests for S3SourceAdapter."""

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter import S3SourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig


def _run(coro):
    """Run coroutine in a fresh event loop (avoids no-current-loop in threaded pytest workers)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_TEST_ACCESS_KEY = os.environ.get("TEST_AWS_ACCESS_KEY", "test-access-key-id")
_TEST_SECRET_KEY = os.environ.get("TEST_AWS_SECRET_KEY", "test-secret-access-key")


def make_config(**kwargs):
    defaults = {
        "access_key": _TEST_ACCESS_KEY,
        "secret_key": _TEST_SECRET_KEY,
        "bucket": "test-bucket",
        "prefix": "",
    }
    defaults.update(kwargs)
    return S3SourceConfig(**defaults)


def make_client_error(code="NoSuchBucket", message="Not found"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "operation")


@pytest.fixture
def adapter():
    return S3SourceAdapter()


@pytest.mark.unit
class TestBuildConfigFromOperatorParams:
    def test_success(self, adapter):
        config = adapter.build_config_from_operator_params(
            provider_config={
                "bucket": "my-bucket",
                "prefix": "docs/",
                "access_key": "AKID",
                "secret_key": "SAK",  # pragma: allowlist secret
            },
        )
        assert config.bucket == "my-bucket"
        assert config.access_key == "AKID"

    def test_missing_access_key_raises(self, adapter):
        with pytest.raises(ValueError, match="access_key"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b", "secret_key": "SAK"},  # pragma: allowlist secret
            )

    def test_missing_secret_key_raises(self, adapter):
        with pytest.raises(ValueError, match="secret_key"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b", "access_key": "AKID"},  # pragma: allowlist secret
            )

    def test_missing_bucket_raises(self, adapter):
        with pytest.raises(ValueError, match="bucket"):
            adapter.build_config_from_operator_params(
                provider_config={"access_key": "AKID", "secret_key": "SAK"},  # pragma: allowlist secret
            )

    def test_with_extensions_and_max_files(self, adapter):
        config = adapter.build_config_from_operator_params(
            provider_config={"bucket": "b", "access_key": "AKID", "secret_key": "SAK"},  # pragma: allowlist secret
            included_extensions=[".pdf", ".txt"],
            max_files=100,
        )
        assert ".pdf" in config.file_extensions
        assert config.max_files == 100

    def test_optional_endpoint_url(self, adapter):
        config = adapter.build_config_from_operator_params(
            provider_config={
                "bucket": "b",
                "endpoint_url": "http://minio:9000",
                "region": "us-east-1",
                "access_key": "AKID",
                "secret_key": "SAK",  # pragma: allowlist secret
            },
        )
        assert config.endpoint_url == "http://minio:9000"
        assert config.region == "us-east-1"


@pytest.mark.unit
class TestGetConfigSchema:
    def test_returns_s3_source_config(self, adapter):
        assert adapter.get_config_schema() is S3SourceConfig


@pytest.mark.unit
class TestCreateS3Client:
    def test_basic_client_creation(self, adapter):
        config = make_config()
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_client = Mock()
            mock_boto3.client.return_value = mock_client
            result = adapter._create_s3_client(config)
            assert result is mock_client
            mock_boto3.client.assert_called_once()
            call_kwargs = mock_boto3.client.call_args[1]
            assert call_kwargs["aws_access_key_id"] == _TEST_ACCESS_KEY

    def test_client_with_endpoint_url(self, adapter):
        config = make_config(endpoint_url="http://minio:9000")
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_boto3.client.return_value = Mock()
            adapter._create_s3_client(config)
            call_kwargs = mock_boto3.client.call_args[1]
            assert call_kwargs["endpoint_url"] == "http://minio:9000"

    def test_client_with_region(self, adapter):
        config = make_config(region="eu-west-1")
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_boto3.client.return_value = Mock()
            adapter._create_s3_client(config)
            call_kwargs = mock_boto3.client.call_args[1]
            assert call_kwargs["region_name"] == "eu-west-1"


@pytest.mark.unit
class TestShouldSkipObject:
    def test_skip_directory_marker(self, adapter):
        config = make_config()
        assert adapter._should_skip_object({"Key": "folder/", "Size": 0}, config) is True

    def test_skip_empty_file(self, adapter):
        config = make_config(skip_empty_files=True)
        assert adapter._should_skip_object({"Key": "file.txt", "Size": 0}, config) is True

    def test_keep_empty_file_when_disabled(self, adapter):
        config = make_config(skip_empty_files=False)
        assert adapter._should_skip_object({"Key": "file.txt", "Size": 0}, config) is False

    def test_skip_file_exceeding_max_size(self, adapter):
        config = make_config(max_file_size_mb=1)  # 1 MB = 1,048,576 bytes
        assert adapter._should_skip_object({"Key": "big.pdf", "Size": 2 * 1024 * 1024}, config) is True

    def test_keep_file_under_max_size(self, adapter):
        config = make_config(max_file_size_mb=10)
        assert adapter._should_skip_object({"Key": "small.pdf", "Size": 1024}, config) is False

    def test_skip_hidden_file(self, adapter):
        config = make_config(skip_hidden_files=True)
        assert adapter._should_skip_object({"Key": ".hidden/file.txt", "Size": 100}, config) is True

    def test_skip_file_by_extension(self, adapter):
        config = make_config(file_extensions=[".pdf"])
        assert adapter._should_skip_object({"Key": "file.txt", "Size": 100}, config) is True

    def test_keep_file_matching_extension(self, adapter):
        config = make_config(file_extensions=[".pdf"])
        assert adapter._should_skip_object({"Key": "file.pdf", "Size": 100}, config) is False

    def test_skip_file_matching_exclude_pattern(self, adapter):
        config = make_config(exclude_patterns=["*.tmp"])
        assert adapter._should_skip_object({"Key": "temp/file.tmp", "Size": 100}, config) is True

    def test_keep_file_not_matching_exclude_pattern(self, adapter):
        config = make_config(exclude_patterns=["*.tmp"])
        assert adapter._should_skip_object({"Key": "document.pdf", "Size": 100}, config) is False

    def test_normal_file_not_skipped(self, adapter):
        config = make_config()
        assert adapter._should_skip_object({"Key": "docs/file.pdf", "Size": 1024}, config) is False


@pytest.mark.unit
class TestIsHiddenPath:
    def test_hidden_root_file(self, adapter):
        assert adapter._is_hidden_path(".hidden") is True

    def test_hidden_directory_component(self, adapter):
        assert adapter._is_hidden_path("docs/.hidden/file.txt") is True

    def test_normal_path(self, adapter):
        assert adapter._is_hidden_path("docs/file.txt") is False

    def test_single_dot_not_hidden(self, adapter):
        assert adapter._is_hidden_path(".") is False

    def test_double_dot_not_hidden(self, adapter):
        assert adapter._is_hidden_path("..") is False


@pytest.mark.unit
class TestTestConnection:
    def test_success_with_contents(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {"Contents": [{"Key": "file.pdf"}], "KeyCount": 1}
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is True
        assert "test-bucket" in msg

    def test_success_no_contents(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {}
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is True
        assert "no objects" in msg.lower()

    def test_no_such_bucket(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = make_client_error("NoSuchBucket")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "does not exist" in msg

    def test_access_denied(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = make_client_error("AccessDenied")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "Access denied" in msg

    def test_invalid_access_key(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = make_client_error("InvalidAccessKeyId")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "Invalid access key" in msg

    def test_signature_mismatch(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = make_client_error("SignatureDoesNotMatch")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "secret key" in msg.lower()

    def test_other_client_error(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = make_client_error("OtherCode", "Some message")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "OtherCode" in msg

    def test_boto_core_error(self, adapter):
        config = make_config()

        class FakeBotoCoreError(BotoCoreError):
            fmt = "boto error"

        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = FakeBotoCoreError()
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, _msg = _run(adapter.test_connection(config))
        assert success is False

    def test_unexpected_error(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = RuntimeError("unexpected")
        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            success, msg = _run(adapter.test_connection(config))
        assert success is False
        assert "unexpected" in msg.lower()


@pytest.mark.unit
class TestFetchBinaryContent:
    def _make_provider_config(self, **extra):
        base = {"access_key": "AKID", "secret_key": "SAK"}  # pragma: allowlist secret
        base.update(extra)
        return base

    def test_fetch_by_s3_uri(self, adapter):
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"content"))}
            result = adapter.fetch_binary_content(
                source_id="s3://my-bucket/path/to/file.pdf",
                provider_config=self._make_provider_config(),
            )
        assert result == b"content"

    def test_fetch_by_key_without_uri(self, adapter):
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"data"))}
            result = adapter.fetch_binary_content(
                source_id="path/to/file.pdf",
                provider_config=self._make_provider_config(bucket="my-bucket"),
            )
        assert result == b"data"

    def test_missing_credentials_returns_none(self, adapter):
        result = adapter.fetch_binary_content(
            source_id="s3://b/k",
            provider_config={},
        )
        assert result is None

    def test_client_error_returns_none(self, adapter):
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.side_effect = make_client_error("NoSuchKey")
            result = adapter.fetch_binary_content(
                source_id="s3://b/k",
                provider_config=self._make_provider_config(),
            )
        assert result is None

    def test_boto_core_error_returns_none(self, adapter):

        class FakeBotoCoreError(BotoCoreError):
            fmt = "boto error"

        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.side_effect = FakeBotoCoreError()
            result = adapter.fetch_binary_content(
                source_id="s3://b/k",
                provider_config=self._make_provider_config(),
            )
        assert result is None

    def test_unexpected_error_returns_none(self, adapter):
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.side_effect = RuntimeError("boom")
            result = adapter.fetch_binary_content(
                source_id="s3://b/k",
                provider_config=self._make_provider_config(),
            )
        assert result is None

    def test_missing_bucket_in_key_mode_returns_none(self, adapter):
        result = adapter.fetch_binary_content(
            source_id="path/to/file.pdf",
            provider_config=self._make_provider_config(),  # no bucket
        )
        assert result is None

    def test_fetch_with_endpoint_and_region(self, adapter):
        with patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.boto3") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.client.return_value = mock_s3
            mock_s3.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"ok"))}
            result = adapter.fetch_binary_content(
                source_id="s3://b/k",
                provider_config=self._make_provider_config(endpoint_url="http://minio:9000", region="us-east-1"),
            )
        assert result == b"ok"
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://minio:9000"
        assert call_kwargs["region_name"] == "us-east-1"


@pytest.mark.unit
class TestDownloadS3Object:
    def test_creates_document_from_metadata(self, adapter):
        config = make_config(endpoint_url="http://minio:9000")
        mock_client = Mock()
        mock_client.head_object.return_value = {"ContentType": "application/pdf"}
        s3_obj = {
            "Key": "docs/file.pdf",
            "Size": 1024,
            "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
            "ETag": '"abc123"',
            "StorageClass": "STANDARD",
        }
        result = _run(adapter._download_s3_object(mock_client, config, s3_obj))
        assert result is not None
        assert result.name == "file.pdf"
        assert result.size == 1024
        assert result.metadata["bucket"] == "test-bucket"
        assert result.metadata["http_url"] == "http://minio:9000/test-bucket/docs/file.pdf"

    def test_creates_document_aws_url_when_no_endpoint(self, adapter):
        config = make_config(region="us-west-2")
        mock_client = Mock()
        mock_client.head_object.return_value = {"ContentType": "text/plain"}
        s3_obj = {"Key": "file.txt", "Size": 512, "LastModified": None}
        result = _run(adapter._download_s3_object(mock_client, config, s3_obj))
        assert result is not None
        assert "amazonaws.com" in result.metadata["http_url"]

    def test_head_object_exception_uses_default_content_type(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.head_object.side_effect = Exception("head error")
        s3_obj = {"Key": "file.txt", "Size": 100, "LastModified": None}
        result = _run(adapter._download_s3_object(mock_client, config, s3_obj))
        assert result is not None
        assert result.mimetype == "text/plain"

    def test_client_error_returns_none(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.head_object.side_effect = make_client_error("AccessDenied")
        s3_obj = {"Key": "file.txt", "Size": 100, "LastModified": None}
        # Patch to simulate downstream ClientError during Document creation
        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.Document",
            side_effect=make_client_error("Error"),
        ):
            result = _run(adapter._download_s3_object(mock_client, config, s3_obj))
        assert result is None

    def test_exception_returns_none(self, adapter):
        config = make_config()
        mock_client = Mock()
        mock_client.head_object.return_value = {"ContentType": "text/plain"}
        s3_obj = {"Key": "file.txt", "Size": 100, "LastModified": None}
        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.Document",
            side_effect=RuntimeError("processing error"),
        ):
            result = _run(adapter._download_s3_object(mock_client, config, s3_obj))
        assert result is None
