#!/usr/bin/env python3

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter import S3SourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig

# Configure pytest-asyncio
pytestmark = pytest.mark.asyncio


async def collect_async(async_gen):
    """Helper to collect async generator results."""
    return [item async for item in async_gen]


class TestS3SourceConfig:
    """Test S3SourceConfig validation and normalization."""

    def test_strips_credentials_and_normalizes_fields(self):
        """Test that credentials are stripped and fields are normalized."""
        config = S3SourceConfig(
            access_key=" AKIAIOSFODNN7EXAMPLE ",  # pragma: allowlist secret
            secret_key=" wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY ",  # pragma: allowlist secret
            bucket=" my-bucket ",
            prefix="/documents/",
            endpoint_url=" https://s3.example.com/ ",
            region="us-east-1",
            recursive=True,
            file_extensions=["pdf", ".txt", ".DOCX"],
            max_file_size_mb=100,
        )
        assert config.access_key == "AKIAIOSFODNN7EXAMPLE"
        assert config.secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
        assert config.bucket == "my-bucket"
        assert config.prefix == "documents/"  # Leading slash removed, trailing slash added
        assert config.endpoint_url == "https://s3.example.com"  # Trailing slash removed
        assert config.file_extensions == [
            ".pdf",
            ".txt",
            ".docx",
        ]  # Normalized to lowercase with dots

    def test_rejects_empty_credentials(self):
        """Test that empty credentials are rejected."""
        with pytest.raises(ValidationError, match="access_key cannot be empty"):
            S3SourceConfig(
                access_key=" ",
                secret_key="secret",  # pragma: allowlist secret
                bucket="bucket",
            )

    def test_rejects_empty_bucket(self):
        """Test that empty bucket name is rejected."""
        with pytest.raises(ValidationError, match="bucket cannot be empty"):
            S3SourceConfig(
                access_key="key",
                secret_key="secret",  # pragma: allowlist secret
                bucket=" ",
            )

    def test_rejects_invalid_endpoint_url(self):
        """Test that invalid endpoint URL is rejected."""
        with pytest.raises(ValidationError, match="endpoint_url must start with"):
            S3SourceConfig(
                access_key="key",
                secret_key="secret",  # pragma: allowlist secret
                bucket="bucket",
                endpoint_url="ftp://invalid.com",
            )

    def test_rejects_negative_max_file_size(self):
        """Test that negative max file size is rejected."""
        with pytest.raises(ValidationError, match="Input should be greater than or equal to 1"):
            S3SourceConfig(
                access_key="key",
                secret_key="secret",  # pragma: allowlist secret
                bucket="bucket",
                max_file_size_mb=-1,
            )

    def test_is_s3_compatible(self):
        """Test is_s3_compatible method."""
        # AWS S3
        config_aws = S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="bucket",
        )
        assert not config_aws.is_s3_compatible()

        # S3-compatible storage
        config_compatible = S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="bucket",
            endpoint_url="https://s3.example.com",
        )
        assert config_compatible.is_s3_compatible()

    def test_get_max_file_size_bytes(self):
        """Test get_max_file_size_bytes method."""
        config = S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="bucket",
            max_file_size_mb=10,
        )
        assert config.get_max_file_size_bytes() == 10 * 1024 * 1024

        config_no_limit = S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="bucket",
        )
        assert config_no_limit.get_max_file_size_bytes() is None


class TestS3SourceAdapter:
    """Test S3SourceAdapter functionality."""

    @pytest.fixture
    def adapter(self):
        """Create S3SourceAdapter instance."""
        return S3SourceAdapter()

    @pytest.fixture
    def config(self):
        """Create test S3SourceConfig."""
        return S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            prefix="documents/",
            recursive=True,
            file_extensions=[".pdf", ".txt"],
            skip_hidden_files=True,
            skip_empty_files=True,
        )

    def test_adapter_metadata(self, adapter):
        """Test adapter metadata."""
        assert adapter.SOURCE_NAME == "s3"
        assert adapter.SOURCE_DISPLAY_NAME == "Amazon S3"
        assert "S3" in adapter.SOURCE_DESCRIPTION

    def test_get_config_schema(self, adapter):
        """Test get_config_schema returns correct type."""
        schema = adapter.get_config_schema()
        # Check class name and module to avoid import identity issues in CI
        assert schema.__name__ == "S3SourceConfig"
        assert schema.__module__ == "docpipe.core.operators.ingest.adapters.outbound.sources.s3.config"

    def test_build_config_from_operator_params(self, adapter):
        """Test building config from operator parameters."""
        provider_config = {
            "bucket": "my-bucket",
            "prefix": "docs/",
            "endpoint_url": "https://s3.example.com",
            "region": "us-west-2",
            "recursive": False,
            "max_file_size_mb": 50,
            "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
        }
        included_extensions = [".pdf", ".docx"]

        config = adapter.build_config_from_operator_params(
            provider_config=provider_config,
            included_extensions=included_extensions,
        )

        assert config.bucket == "my-bucket"
        assert config.prefix == "docs/"
        assert config.endpoint_url == "https://s3.example.com"
        assert config.region == "us-west-2"
        assert config.recursive is False
        assert config.file_extensions == [".pdf", ".docx"]
        assert config.max_file_size_mb == 50

    def test_build_config_missing_credentials(self, adapter):
        """Test that missing credentials raise ValueError."""
        with pytest.raises(ValueError, match="Missing required parameter: 'access_key'"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "bucket", "secret_key": "secret"},  # pragma: allowlist secret
            )

    def test_build_config_missing_bucket(self, adapter):
        """Test that missing bucket raises ValueError."""
        with pytest.raises(ValueError, match="Missing required parameter: 'bucket'"):
            adapter.build_config_from_operator_params(
                provider_config={
                    "access_key": "key",
                    "secret_key": "secret",  # pragma: allowlist secret
                },
            )

    def test_build_config_with_null_credentials(self, adapter):
        """Null credentials from UI defaults must not raise AttributeError."""
        with pytest.raises(ValueError, match="Missing required parameter: 'access_key'"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "my-bucket"},
            )

    @pytest.mark.asyncio
    async def test_test_connection_success(self, adapter, config):
        """Test successful connection test."""
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {
            "KeyCount": 5,
            "Contents": [{"Key": "test.pdf"}],
        }

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, message = await adapter.test_connection(config)

        assert success is True
        assert "Successfully connected" in message
        assert "5 object(s)" in message
        mock_client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="documents/", MaxKeys=1)

    @pytest.mark.asyncio
    async def test_test_connection_no_such_bucket(self, adapter, config):
        """Test connection test with non-existent bucket."""
        mock_client = Mock()
        error_response = {
            "Error": {
                "Code": "NoSuchBucket",
                "Message": "The specified bucket does not exist",
            }
        }
        mock_client.list_objects_v2.side_effect = ClientError(error_response, "ListObjectsV2")  # type: ignore[arg-type]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, message = await adapter.test_connection(config)

        assert success is False
        assert "does not exist" in message

    @pytest.mark.asyncio
    async def test_test_connection_access_denied(self, adapter, config):
        """Test connection test with access denied."""
        mock_client = Mock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_client.list_objects_v2.side_effect = ClientError(error_response, "ListObjectsV2")  # type: ignore[arg-type]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, message = await adapter.test_connection(config)

        assert success is False
        assert "Access denied" in message

    def test_should_skip_object_directory_marker(self, adapter, config):
        """Test that directory markers are skipped."""
        obj = {"Key": "documents/folder/", "Size": 0}
        assert adapter._should_skip_object(obj, config) is True

    def test_should_skip_object_empty_file(self, adapter, config):
        """Test that empty files are skipped when configured."""
        obj = {"Key": "documents/empty.txt", "Size": 0}
        assert adapter._should_skip_object(obj, config) is True

    def test_should_skip_object_hidden_file(self, adapter, config):
        """Test that hidden files are skipped when configured."""
        obj = {"Key": "documents/.hidden.txt", "Size": 100}
        assert adapter._should_skip_object(obj, config) is True

    def test_should_skip_object_wrong_extension(self, adapter, config):
        """Test that files with wrong extension are skipped."""
        obj = {"Key": "documents/file.docx", "Size": 100}
        assert adapter._should_skip_object(obj, config) is True

    def test_should_skip_object_exceeds_max_size(self, adapter):
        """Test that files exceeding max size are skipped."""
        config = S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="bucket",
            max_file_size_mb=1,  # 1 MB limit
        )
        obj = {"Key": "large.pdf", "Size": 2 * 1024 * 1024}  # 2 MB
        assert adapter._should_skip_object(obj, config) is True

    def test_should_not_skip_valid_object(self, adapter, config):
        """Test that valid objects are not skipped."""
        obj = {"Key": "documents/report.pdf", "Size": 1024}
        assert adapter._should_skip_object(obj, config) is False

    def test_is_hidden_path(self, adapter):
        """Test hidden path detection."""
        assert adapter._is_hidden_path("documents/.hidden.txt") is True
        assert adapter._is_hidden_path(".hidden/file.txt") is True
        assert adapter._is_hidden_path("documents/folder/.DS_Store") is True
        assert adapter._is_hidden_path("documents/normal.txt") is False
        assert adapter._is_hidden_path("documents/folder/file.txt") is False

    @pytest.mark.asyncio
    async def test_fetch_documents(self, adapter, config):
        """Test fetching documents from S3 with lazy loading (no binary download)."""
        # Mock S3 client
        mock_client = Mock()

        # Mock list_objects_v2 paginator
        mock_paginator = Mock()
        mock_client.get_paginator.return_value = mock_paginator

        # Mock pages with S3 objects
        mock_pages = [
            {
                "Contents": [
                    {
                        "Key": "documents/file1.pdf",
                        "Size": 1024,
                        "LastModified": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                        "ETag": '"abc123"',
                        "StorageClass": "STANDARD",
                    },
                    {
                        "Key": "documents/file2.txt",
                        "Size": 512,
                        "LastModified": datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                        "ETag": '"def456"',
                        "StorageClass": "STANDARD",
                    },
                ]
            }
        ]
        mock_paginator.paginate.return_value = mock_pages

        # Note: head_object no longer called - content type determined from file extension
        # This is an optimization to reduce API calls

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                documents = await collect_async(adapter.fetch_documents(config))

        assert len(documents) == 2
        # Check that all documents are Document instances by class name and module
        # (avoids import identity issues in CI)
        for doc in documents:
            assert doc.__class__.__name__ == "Document"
            assert doc.__class__.__module__ == "docpipe.core.operators.ingest.domain.models"
        assert documents[0].name == "file1.pdf"
        assert documents[1].name == "file2.txt"
        # Verify lazy loading: content should be empty
        assert documents[0].content == b""
        assert documents[1].content == b""
        assert documents[0].metadata["bucket"] == "test-bucket"
        assert documents[0].metadata["key"] == "documents/file1.pdf"
        # Verify get_object was NOT called (lazy loading)
        mock_client.get_object.assert_not_called()


class TestResolveAwsAccountId:
    """Tests for _get_aws_account_id gated by verify_expected_bucket_owner."""

    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    @pytest.fixture
    def aws_config(self):
        """AWS S3 config with owner verification enabled."""
        return S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            region="us-east-1",
            verify_expected_bucket_owner=True,
        )

    @pytest.fixture
    def aws_config_no_verify(self):
        """AWS S3 config with owner verification disabled (default)."""
        return S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            region="us-east-1",
        )

    @pytest.fixture
    def cos_config(self):
        """S3-compatible (IBM COS) config — STS must be skipped."""
        return S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            endpoint_url="https://s3.us-south.cloud-object-storage.appdomain.cloud",
            verify_expected_bucket_owner=True,
        )

    def test_returns_account_id_when_verify_disabled_and_sts_succeeds(self, adapter, aws_config_no_verify):
        """STS is still called when verify is False; account ID returned on success."""
        mock_sts = Mock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}

        with patch("docpipe.integrations.aws.s3_utils.boto3.client", return_value=mock_sts):
            account_id = adapter._get_aws_account_id(aws_config_no_verify)

        assert account_id == "123456789012"

    def test_returns_account_id_for_aws_when_verify_enabled(self, adapter, aws_config):
        """STS GetCallerIdentity is called and account ID is returned when verify is True."""
        mock_sts = Mock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}

        with patch("docpipe.integrations.aws.s3_utils.boto3.client", return_value=mock_sts) as mock_boto:
            account_id = adapter._get_aws_account_id(aws_config)

        assert account_id == "123456789012"
        mock_boto.assert_called_once_with(
            "sts",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            region_name="us-east-1",
        )

    def test_skips_sts_for_s3_compatible_storage(self, adapter, cos_config):
        """No STS call is made when endpoint_url is set (S3-compatible storage)."""
        with patch("docpipe.integrations.aws.s3_utils.boto3.client") as mock_boto:
            account_id = adapter._get_aws_account_id(cos_config)

        assert account_id is None
        mock_boto.assert_not_called()

    def test_raises_on_sts_client_error_when_verify_enabled(self, adapter, aws_config):
        """Raises RuntimeError when STS returns a ClientError and verify_expected_bucket_owner is True."""
        mock_sts = Mock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Not authorized"}}
        mock_sts.get_caller_identity.side_effect = ClientError(error_response, "GetCallerIdentity")  # type: ignore[arg-type]

        with patch("docpipe.integrations.aws.s3_utils.boto3.client", return_value=mock_sts):
            with pytest.raises(RuntimeError, match="STS GetCallerIdentity failed"):
                adapter._get_aws_account_id(aws_config)

    def test_raises_on_unexpected_exception_when_verify_enabled(self, adapter, aws_config):
        """Raises RuntimeError on any unexpected error when verify_expected_bucket_owner is True."""
        with patch("docpipe.integrations.aws.s3_utils.boto3.client", side_effect=RuntimeError("network error")):
            with pytest.raises(RuntimeError, match="Unable to resolve AWS account ID"):
                adapter._get_aws_account_id(aws_config)

    def test_returns_none_on_sts_client_error_when_verify_disabled(self, adapter, aws_config_no_verify):
        """Gracefully returns None when STS returns a ClientError and verify is False."""
        mock_sts = Mock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Not authorized"}}
        mock_sts.get_caller_identity.side_effect = ClientError(error_response, "GetCallerIdentity")  # type: ignore[arg-type]

        with patch("docpipe.integrations.aws.s3_utils.boto3.client", return_value=mock_sts):
            account_id = adapter._get_aws_account_id(aws_config_no_verify)

        assert account_id is None

    def test_returns_none_on_unexpected_exception_when_verify_disabled(self, adapter, aws_config_no_verify):
        """Gracefully returns None on any unexpected error when verify is False."""
        with patch("docpipe.integrations.aws.s3_utils.boto3.client", side_effect=RuntimeError("network error")):
            account_id = adapter._get_aws_account_id(aws_config_no_verify)

        assert account_id is None

    def test_resolve_without_region(self, adapter):
        """region_name is omitted from STS kwargs when config.region is None."""
        config = S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            verify_expected_bucket_owner=True,
        )
        mock_sts = Mock()
        mock_sts.get_caller_identity.return_value = {"Account": "999888777666"}

        with patch("docpipe.integrations.aws.s3_utils.boto3.client", return_value=mock_sts) as mock_boto:
            account_id = adapter._get_aws_account_id(config)

        assert account_id == "999888777666"
        mock_boto.assert_called_once_with(
            "sts",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
        )


class TestExpectedBucketOwnerPropagation:
    """Tests that ExpectedBucketOwner is passed to S3 API calls when account ID is resolved."""

    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    @pytest.fixture
    def config(self):
        return S3SourceConfig(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            bucket="test-bucket",
            prefix="docs/",
        )

    @pytest.mark.asyncio
    async def test_test_connection_passes_expected_bucket_owner(self, adapter, config):
        """list_objects_v2 receives ExpectedBucketOwner when account ID is resolved."""
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {"KeyCount": 1, "Contents": [{"Key": "docs/a.pdf"}]}

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value="123456789012"):
                await adapter.test_connection(config)

        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="test-bucket", Prefix="docs/", MaxKeys=1, ExpectedBucketOwner="123456789012"
        )

    @pytest.mark.asyncio
    async def test_test_connection_omits_expected_bucket_owner_when_none(self, adapter, config):
        """list_objects_v2 does NOT receive ExpectedBucketOwner when account ID is None."""
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {"KeyCount": 0}

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                await adapter.test_connection(config)

        call_kwargs = mock_client.list_objects_v2.call_args[1]
        assert "ExpectedBucketOwner" not in call_kwargs

    @pytest.mark.asyncio
    async def test_fetch_documents_uses_mimetypes_for_content_type(self, adapter, config):
        """Content type is determined from file extension using mimetypes (no head_object call)."""
        mock_client = Mock()
        mock_paginator = Mock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "docs/file.pdf",
                        "Size": 1024,
                        "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
                        "ETag": '"abc"',
                        "StorageClass": "STANDARD",
                    }
                ]
            }
        ]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value="123456789012"):
                documents = await collect_async(adapter.fetch_documents(config))

        # Verify head_object was NOT called (optimization)
        mock_client.head_object.assert_not_called()

        # Verify content type was determined from extension
        assert len(documents) == 1
        assert documents[0].mimetype == "application/pdf"

    @pytest.mark.asyncio
    async def test_fetch_binary_content_passes_expected_bucket_owner(self, adapter):
        """get_object receives ExpectedBucketOwner when account ID is resolved."""
        mock_client = Mock()
        mock_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"data"))}

        provider_config = {
            "bucket": "test-bucket",
            "region": "us-east-1",
            "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            "secret_key": "secret",  # pragma: allowlist secret
        }

        with patch("boto3.client", return_value=mock_client):
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value="123456789012",
            ):
                result = adapter.fetch_binary_content(
                    source_id="s3://test-bucket/docs/file.pdf",
                    provider_config=provider_config,
                )

        assert result == b"data"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="docs/file.pdf", ExpectedBucketOwner="123456789012"
        )

    @pytest.mark.asyncio
    async def test_fetch_binary_content_omits_expected_bucket_owner_for_cos(self, adapter):
        """get_object does NOT include ExpectedBucketOwner for S3-compatible storage."""
        mock_client = Mock()
        mock_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"data"))}

        provider_config = {
            "bucket": "test-bucket",
            "endpoint_url": "https://s3.us-south.cloud-object-storage.appdomain.cloud",
            "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            "secret_key": "secret",  # pragma: allowlist secret
        }

        with patch("boto3.client", return_value=mock_client):
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value=None,
            ):
                result = adapter.fetch_binary_content(
                    source_id="s3://test-bucket/docs/file.pdf",
                    provider_config=provider_config,
                )

        assert result == b"data"
        call_kwargs = mock_client.get_object.call_args[1]
        assert "ExpectedBucketOwner" not in call_kwargs


# ---------------------------------------------------------------------------
# _create_s3_client
# ---------------------------------------------------------------------------


class TestS3CreateClient:
    """Test _create_s3_client builds boto3 clients with correct kwargs."""

    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    def _base_config(self, **kwargs):
        defaults = {
            "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            "bucket": "test-bucket",
        }
        defaults.update(kwargs)
        return S3SourceConfig(**defaults)

    def test_creates_client_without_optional_params(self, adapter):
        config = self._base_config()
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = Mock()
            adapter._create_s3_client(config)

        call_kwargs = mock_boto.call_args
        assert call_kwargs[0][0] == "s3"
        assert "endpoint_url" not in call_kwargs[1]
        assert "region_name" not in call_kwargs[1]

    def test_creates_client_with_endpoint_url(self, adapter):
        config = self._base_config(endpoint_url="https://s3.example.com")
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = Mock()
            adapter._create_s3_client(config)

        call_kwargs = mock_boto.call_args[1]
        assert call_kwargs["endpoint_url"] == "https://s3.example.com"

    def test_creates_client_with_region(self, adapter):
        config = self._base_config(region="eu-west-1")
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = Mock()
            adapter._create_s3_client(config)

        call_kwargs = mock_boto.call_args[1]
        assert call_kwargs["region_name"] == "eu-west-1"


# ---------------------------------------------------------------------------
# _should_skip_object — exclude_patterns branch
# ---------------------------------------------------------------------------


class TestS3ShouldSkipObjectExcludePatterns:
    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    def _config(self, **kwargs):
        defaults = {
            "access_key": "key",
            "secret_key": "secret",  # pragma: allowlist secret
            "bucket": "bucket",
            "skip_hidden_files": False,
            "skip_empty_files": False,
        }
        defaults.update(kwargs)
        return S3SourceConfig(**defaults)

    def test_skips_file_matching_exclude_pattern(self, adapter):
        config = self._config(exclude_patterns=["*.tmp"])
        obj = {"Key": "documents/file.tmp", "Size": 100}
        assert adapter._should_skip_object(obj, config) is True

    def test_skips_file_matching_full_path_pattern(self, adapter):
        config = self._config(exclude_patterns=["Trash/*"])
        obj = {"Key": "Trash/old_file.pdf", "Size": 100}
        assert adapter._should_skip_object(obj, config) is True

    def test_does_not_skip_non_matching_pattern(self, adapter):
        config = self._config(exclude_patterns=["*.tmp"])
        obj = {"Key": "documents/report.pdf", "Size": 100}
        assert adapter._should_skip_object(obj, config) is False


# ---------------------------------------------------------------------------
# test_connection — BotoCoreError and generic error paths
# ---------------------------------------------------------------------------


class TestS3TestConnectionErrorPaths:
    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    @pytest.fixture
    def config(self):
        return S3SourceConfig(
            access_key="key",
            secret_key="secret",  # pragma: allowlist secret
            bucket="test-bucket",
        )

    @pytest.mark.asyncio
    async def test_botocore_error_returns_false(self, adapter, config):
        from botocore.exceptions import BotoCoreError

        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = BotoCoreError()

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, msg = await adapter.test_connection(config)

        assert success is False
        assert "Boto3 error" in msg

    @pytest.mark.asyncio
    async def test_generic_exception_returns_false(self, adapter, config):
        mock_client = Mock()
        mock_client.list_objects_v2.side_effect = RuntimeError("network error")

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, msg = await adapter.test_connection(config)

        assert success is False
        assert "Unexpected error" in msg

    @pytest.mark.asyncio
    async def test_invalid_access_key_returns_false(self, adapter, config):
        from botocore.exceptions import ClientError

        mock_client = Mock()
        error_response = {
            "Error": {"Code": "InvalidAccessKeyId", "Message": "The Access Key Id you provided does not exist"}
        }
        mock_client.list_objects_v2.side_effect = ClientError(error_response, "ListObjectsV2")  # type: ignore[arg-type]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, msg = await adapter.test_connection(config)

        assert success is False
        assert "Invalid access key" in msg

    @pytest.mark.asyncio
    async def test_signature_mismatch_returns_false(self, adapter, config):
        from botocore.exceptions import ClientError

        mock_client = Mock()
        error_response = {"Error": {"Code": "SignatureDoesNotMatch", "Message": "Invalid secret key"}}
        mock_client.list_objects_v2.side_effect = ClientError(error_response, "ListObjectsV2")  # type: ignore[arg-type]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, msg = await adapter.test_connection(config)

        assert success is False
        assert "Invalid secret key" in msg

    @pytest.mark.asyncio
    async def test_generic_client_error_returns_false(self, adapter, config):
        from botocore.exceptions import ClientError

        mock_client = Mock()
        error_response = {"Error": {"Code": "SomeOtherError", "Message": "something bad"}}
        mock_client.list_objects_v2.side_effect = ClientError(error_response, "ListObjectsV2")  # type: ignore[arg-type]

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, _msg = await adapter.test_connection(config)

        assert success is False

    @pytest.mark.asyncio
    async def test_connection_returns_true_with_no_objects(self, adapter, config):
        mock_client = Mock()
        mock_client.list_objects_v2.return_value = {"KeyCount": 0}

        with patch.object(adapter, "_create_s3_client", return_value=mock_client):
            with patch.object(adapter, "_get_aws_account_id", return_value=None):
                success, msg = await adapter.test_connection(config)

        assert success is True
        assert "no objects found" in msg or "Successfully connected" in msg


# ---------------------------------------------------------------------------
# fetch_binary_content — error paths not yet covered
# ---------------------------------------------------------------------------


class TestS3FetchBinaryContentErrors:
    @pytest.fixture
    def adapter(self):
        return S3SourceAdapter()

    def test_returns_none_for_missing_access_key(self, adapter):
        result = adapter.fetch_binary_content(
            source_id="s3://bucket/key.pdf",
            provider_config={"secret_key": "secret"},  # pragma: allowlist secret
        )
        assert result is None

    def test_returns_none_for_missing_secret_key(self, adapter):
        result = adapter.fetch_binary_content(
            source_id="s3://bucket/key.pdf",
            provider_config={"access_key": "key"},
        )
        assert result is None

    def test_returns_none_for_missing_bucket_without_s3_uri(self, adapter):
        result = adapter.fetch_binary_content(
            source_id="just-a-key.pdf",
            provider_config={"access_key": "key", "secret_key": "secret"},  # pragma: allowlist secret  # no bucket
        )
        assert result is None

    def test_uses_bucket_from_connection_params_for_plain_key(self, adapter):
        mock_client = Mock()
        mock_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"bytes"))}

        with patch("boto3.client", return_value=mock_client):
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value=None,
            ):
                result = adapter.fetch_binary_content(
                    source_id="folder/file.pdf",
                    provider_config={
                        "bucket": "my-bucket",
                        "access_key": "key",
                        "secret_key": "secret",  # pragma: allowlist secret
                    },
                )
        assert result == b"bytes"

    def test_returns_none_on_botocore_error(self, adapter):
        from botocore.exceptions import BotoCoreError

        mock_client = Mock()
        mock_client.get_object.side_effect = BotoCoreError()

        with patch("boto3.client", return_value=mock_client):
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value=None,
            ):
                result = adapter.fetch_binary_content(
                    source_id="s3://bucket/file.pdf",
                    provider_config={"access_key": "key", "secret_key": "secret"},  # pragma: allowlist secret
                )
        assert result is None

    def test_returns_none_on_unexpected_exception(self, adapter):
        mock_client = Mock()
        mock_client.get_object.side_effect = RuntimeError("disk error")

        with patch("boto3.client", return_value=mock_client):
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value=None,
            ):
                result = adapter.fetch_binary_content(
                    source_id="s3://bucket/file.pdf",
                    provider_config={"access_key": "key", "secret_key": "secret"},  # pragma: allowlist secret
                )
        assert result is None

    def test_client_is_cached_across_calls(self, adapter):
        """Second call with same creds reuses the cached boto3 client."""
        mock_client = Mock()
        mock_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"x"))}

        provider_config = {"access_key": "key", "secret_key": "secret"}  # pragma: allowlist secret

        with patch("boto3.client", return_value=mock_client) as mock_boto:
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.resolve_aws_account_id",
                return_value=None,
            ):
                adapter.fetch_binary_content(
                    source_id="s3://b/k1.pdf",
                    provider_config=provider_config,
                )
                adapter.fetch_binary_content(
                    source_id="s3://b/k2.pdf",
                    provider_config=provider_config,
                )

        # boto3.client should only have been called once (cached on second call)
        mock_boto.assert_called_once()
