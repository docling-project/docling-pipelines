"""Shared AWS S3 utility functions."""

from typing import Any

import boto3
from botocore.exceptions import ClientError

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


def resolve_aws_account_id(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
    region: str | None = None,
    endpoint_url: str | None = None,
    strict: bool = False,
) -> str | None:
    """Resolve AWS account ID from credentials via STS GetCallerIdentity.

    Used to populate ExpectedBucketOwner on S3 API calls, preventing
    confused-deputy / bucket-hijacking attacks (SonarQube security finding).

    Skipped automatically for S3-compatible storage (endpoint_url present).

    Args:
        access_key: AWS access key ID. If None, uses boto3 default credential chain.
        secret_key: AWS secret access key. If None, uses boto3 default credential chain.
        region: Optional AWS region.
        endpoint_url: Custom S3 endpoint (non-None means S3-compatible storage, skip STS).
        strict: When True, any failure to resolve the account ID raises an exception
            rather than returning None. Use when verify_expected_bucket_owner is set.

    Returns:
        AWS account ID string (e.g. "123456789012"), or None if unavailable (strict=False only).

    Raises:
        RuntimeError: If strict=True and the account ID cannot be resolved.
    """
    if endpoint_url:
        # S3-compatible storage (IBM COS, MinIO, etc.) - STS not applicable
        return None

    try:
        sts_kwargs: dict[str, Any] = {}
        if access_key:
            sts_kwargs["aws_access_key_id"] = access_key
        if secret_key:
            sts_kwargs["aws_secret_access_key"] = secret_key
        if region:
            sts_kwargs["region_name"] = region

        sts_client = boto3.client("sts", **sts_kwargs)
        identity = sts_client.get_caller_identity()
        account_id: str = identity["Account"]
        logger.debug("Resolved AWS account ID for ExpectedBucketOwner: %s", account_id)
        return account_id
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if strict:
            raise RuntimeError(
                f"STS GetCallerIdentity failed ({error_code}); cannot enforce ExpectedBucketOwner. "
                "Disable verify_expected_bucket_owner or fix STS permissions."
            ) from e
        logger.warning(
            "STS GetCallerIdentity failed (%s); S3 calls will proceed without ExpectedBucketOwner",
            error_code,
        )
        return None
    except Exception as e:
        if strict:
            raise RuntimeError(
                f"Unable to resolve AWS account ID via STS; cannot enforce ExpectedBucketOwner: {e}. "
                "Disable verify_expected_bucket_owner or fix STS permissions."
            ) from e
        logger.warning(
            "Unable to resolve AWS account ID via STS; S3 calls will proceed without ExpectedBucketOwner: %s",
            e,
        )
        return None
