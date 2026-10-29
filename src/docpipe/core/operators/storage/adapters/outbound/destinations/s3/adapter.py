"""S3 destination adapter implementation."""

from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    register_destination_adapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.s3.config import (
    S3DestinationConfig,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort
from docpipe.integrations.aws.s3_utils import resolve_aws_account_id
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_destination_adapter
class S3DestinationAdapter(DestinationAdapterPort[S3DestinationConfig]):
    """Write documents to an Amazon S3 or S3-compatible destination."""

    DEST_NAME = "s3"
    DEST_DISPLAY_NAME = "Amazon S3"
    DEST_VERSION = "1.0.0"

    def __init__(self) -> None:
        # Caches keyed by (access_key, secret_key, region, endpoint_url).
        # Populated lazily on first use and reused for every document in the batch.
        # Safe because the factory creates a new adapter instance per transform() call.
        self._s3_client_cache: dict[tuple[str | None, ...], Any] = {}
        self._account_id_cache: dict[tuple[str | None, ...], str | None] = {}

    @staticmethod
    def is_available() -> bool:
        """Return True as boto3 is a core dependency."""
        return True

    def validate_destination(
        self,
        *,
        config: S3DestinationConfig | None = None,
    ) -> WriteResult | None:
        """Check that the target bucket (and prefix path) is accessible before fetching any content.

        When config.create_dirs is False, also verifies that at least one object already exists
        under config.key_prefix. If the prefix is empty in the bucket the write is refused with
        the same error pattern used by the filesystem adapter for missing directories.
        """
        if config is None:
            return None

        try:
            s3_client = self._create_s3_client(config)
            account_id = self._get_aws_account_id(config)
            head_kwargs: dict[str, Any] = {"Bucket": config.bucket}
            if account_id:
                head_kwargs["ExpectedBucketOwner"] = account_id
            s3_client.head_bucket(**head_kwargs)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            msg = f"S3 destination bucket '{config.bucket}' is not accessible ({error_code}): {e}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)
        except BotoCoreError as e:
            msg = f"S3 destination bucket '{config.bucket}' is not accessible: {e}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        if not config.create_dirs and config.key_prefix:
            # Verify at least one object exists under the prefix so we honour the
            # "do not create new paths" semantics, mirroring the filesystem adapter behaviour.
            try:
                list_kwargs: dict[str, Any] = {
                    "Bucket": config.bucket,
                    "Prefix": config.key_prefix,
                    "MaxKeys": 1,
                }
                if account_id:
                    list_kwargs["ExpectedBucketOwner"] = account_id
                response = s3_client.list_objects_v2(**list_kwargs)
                if response.get("KeyCount", 0) == 0:
                    msg = (
                        f"destination prefix path does not exist and create_dirs is disabled: "
                        f"s3://{config.bucket}/{config.key_prefix}"
                    )
                    logger.error(msg)
                    return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                msg = f"S3 prefix check failed for 's3://{config.bucket}/{config.key_prefix}' ({error_code}): {e}"
                logger.error(msg)
                return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        return None

    def write_document(
        self,
        *,
        content: bytes,
        destination_path: str,
        overwrite: bool = True,
        config: S3DestinationConfig | None = None,
    ) -> WriteResult:
        """Upload bytes to S3 at destination_path (treated as an S3 object key).

        When config.key_prefix is set the full object key is
        ``key_prefix + destination_path``; pass a bare key when key_prefix is
        already baked into destination_path.
        """
        if config is None:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message="S3DestinationConfig is required",
            )

        key = destination_path
        bucket = config.bucket

        try:
            s3_client = self._create_s3_client(config)
            account_id = self._get_aws_account_id(config)

            if not overwrite:
                # head_object raises ClientError(NoSuchKey / 404) when absent
                try:
                    head_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
                    if account_id:
                        head_kwargs["ExpectedBucketOwner"] = account_id
                    s3_client.head_object(**head_kwargs)
                    # Object exists and overwrite is disabled — skip
                    return WriteResult(
                        doc_id="",
                        doc_name=key,
                        success=False,
                        error_message="file exists, overwrite disabled",
                    )
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
                        raise

            ext = key.rsplit(".", 1)[-1] if "." in key else ""
            content_type = config.get_content_type(extension=ext) if config else None

            put_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": content}
            if content_type:
                put_kwargs["ContentType"] = content_type
            if account_id:
                put_kwargs["ExpectedBucketOwner"] = account_id

            logger.info("Uploading binary content to S3: bucket=%s, key=%s", bucket, key)
            s3_client.put_object(**put_kwargs)

            logger.info("Successfully uploaded %d bytes to S3: s3://%s/%s", len(content), bucket, key)
            return WriteResult(
                doc_id="",
                doc_name=key,
                success=True,
                destination_path=f"s3://{bucket}/{key}",
                bytes_written=len(content),
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            msg = f"S3 ClientError ({error_code}) writing {key}: {e}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name=key, success=False, error_message=msg)
        except BotoCoreError as e:
            msg = f"S3 BotoCoreError writing {key}: {e}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name=key, success=False, error_message=msg)
        except Exception as e:
            msg = f"Unexpected error writing to S3 {key}: {e}"
            logger.exception("Unexpected error writing to S3 %s: %s", key, e)
            return WriteResult(doc_id="", doc_name=key, success=False, error_message=msg)

    def ensure_directory(self, *, path: str) -> None:
        """No-op — S3 has no directory primitives."""

    def resolve_destination_path(
        self,
        *,
        relative_path: str,
        config: S3DestinationConfig,
    ) -> str:
        """Prepend key_prefix to the relative path to form the full S3 object key."""
        return config.key_prefix + relative_path

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> S3DestinationConfig:
        """Build S3DestinationConfig from operator flow params.

        Resolves environment variable references in credential values.
        """
        access_key = resolve_env_var(credentials.get("access_key"))
        secret_key = resolve_env_var(credentials.get("secret_key"))

        if not access_key:
            raise ValueError("Missing required S3 credential: 'access_key'")
        if not secret_key:
            raise ValueError("Missing required S3 credential: 'secret_key'")

        bucket = resolve_env_var(provider_config.get("bucket"))
        if not bucket:
            raise ValueError("Missing required S3 connection parameter: 'bucket'")

        # A destination path is mandatory — writing to the bucket root is not permitted.
        raw_prefix = provider_config.get("prefix") or provider_config.get("key_prefix")
        if not raw_prefix or not str(raw_prefix).strip():
            raise ValueError(
                "Missing required S3 destination path: set 'key_prefix' in "
                "provider_config. Writing to the bucket root is not permitted."
            )

        return S3DestinationConfig(
            access_key=access_key,
            secret_key=secret_key,
            bucket=bucket,
            key_prefix=raw_prefix,
            create_dirs=provider_config.get("create_dirs", True),
            endpoint_url=resolve_env_var(provider_config.get("endpoint_url")),
            region=resolve_env_var(provider_config.get("region")),
            verify_expected_bucket_owner=provider_config.get("verify_expected_bucket_owner", False),
        )

    def get_config_schema(self) -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return S3DestinationConfig

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cache_key(self, config: S3DestinationConfig) -> tuple[str | None, ...]:
        return (config.access_key, config.secret_key, config.region, config.endpoint_url)

    def _create_s3_client(self, config: S3DestinationConfig) -> Any:
        """Return a cached boto3 S3 client, creating it once per unique credential set."""
        key = self._cache_key(config)
        if key not in self._s3_client_cache:
            client_kwargs: dict[str, Any] = {
                "aws_access_key_id": config.access_key,
                "aws_secret_access_key": config.secret_key,
            }
            if config.endpoint_url:
                client_kwargs["endpoint_url"] = config.endpoint_url
            if config.region:
                client_kwargs["region_name"] = config.region
            self._s3_client_cache[key] = boto3.client("s3", **client_kwargs)
        return self._s3_client_cache[key]

    def _get_aws_account_id(self, config: S3DestinationConfig) -> str | None:
        """Return a cached AWS account ID, resolving via STS once per unique credential set."""
        key = self._cache_key(config)
        if key not in self._account_id_cache:
            self._account_id_cache[key] = resolve_aws_account_id(
                access_key=config.access_key,
                secret_key=config.secret_key,
                region=config.region,
                endpoint_url=config.endpoint_url,
                strict=config.verify_expected_bucket_owner,
            )
        return self._account_id_cache[key]
