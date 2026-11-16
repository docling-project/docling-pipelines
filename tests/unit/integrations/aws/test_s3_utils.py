"""Unit tests for resolve_aws_account_id in s3_utils."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from docpipe.integrations.aws import s3_utils
from docpipe.integrations.aws.s3_utils import resolve_aws_account_id


class TestResolveAwsAccountId:
    """resolve_aws_account_id STS caller identity resolution and error handling."""

    def test_endpoint_url_skips_sts_even_when_strict(self):
        """S3-compatible storage never needs STS."""
        assert resolve_aws_account_id(endpoint_url="http://localhost:9000", strict=True) is None

    def test_resolve_success_default_args(self):
        """STS GetCallerIdentity succeeds with default credentials."""
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}

        with patch.object(s3_utils.boto3, "client", return_value=mock_sts) as mock_boto_client:
            result = resolve_aws_account_id()

        assert result == "123456789012"
        mock_boto_client.assert_called_once_with("sts")

    def test_resolve_success_with_explicit_credentials_and_region(self):
        """STS kwargs include access_key, secret_key, and region when provided."""
        access_key = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
        secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
        region = "us-east-1"

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "987654321098"}

        with patch.object(s3_utils.boto3, "client", return_value=mock_sts) as mock_boto_client:
            result = resolve_aws_account_id(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
            )

        assert result == "987654321098"
        mock_boto_client.assert_called_once_with(
            "sts",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def test_client_error_not_strict_returns_none(self):
        """When STS raises ClientError and strict=False, returns None gracefully."""
        mock_sts = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_sts.get_caller_identity.side_effect = ClientError(error_response, "GetCallerIdentity")  # type: ignore[arg-type]

        with patch.object(s3_utils.boto3, "client", return_value=mock_sts):
            assert resolve_aws_account_id(strict=False) is None

    def test_client_error_strict_raises_runtime_error(self):
        """When STS raises ClientError and strict=True, raises RuntimeError."""
        mock_sts = MagicMock()
        error_response = {"Error": {"Code": "InvalidClientTokenId", "Message": "Invalid token"}}
        mock_sts.get_caller_identity.side_effect = ClientError(error_response, "GetCallerIdentity")  # type: ignore[arg-type]

        with patch.object(s3_utils.boto3, "client", return_value=mock_sts):
            with pytest.raises(RuntimeError, match=r"STS GetCallerIdentity failed \(InvalidClientTokenId\)"):
                resolve_aws_account_id(strict=True)

    def test_client_error_missing_code_defaults_to_unknown(self):
        """When ClientError response lacks an error code, defaults to 'Unknown'."""
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = ClientError({}, "GetCallerIdentity")  # type: ignore[arg-type]

        with patch.object(s3_utils.boto3, "client", return_value=mock_sts):
            with pytest.raises(RuntimeError, match=r"STS GetCallerIdentity failed \(Unknown\)"):
                resolve_aws_account_id(strict=True)

    def test_unexpected_exception_not_strict_returns_none(self):
        """When unexpected Exception occurs and strict=False, returns None gracefully."""
        with patch.object(s3_utils.boto3, "client", side_effect=ValueError("connection timed out")):
            assert resolve_aws_account_id(strict=False) is None

    def test_unexpected_exception_strict_raises_runtime_error(self):
        """When unexpected Exception occurs and strict=True, raises RuntimeError."""
        with patch.object(s3_utils.boto3, "client", side_effect=ValueError("connection timed out")):
            with pytest.raises(RuntimeError, match="Unable to resolve AWS account ID via STS"):
                resolve_aws_account_id(strict=True)
