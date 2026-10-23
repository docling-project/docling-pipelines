"""S3 source adapter using boto3."""

import asyncio
import fnmatch
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (
    register_source_adapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.integrations.aws.s3_utils import resolve_aws_account_id
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_source_adapter
class S3SourceAdapter(DocumentSourcePort):
    """
    Adapter for ingesting documents from Amazon S3 or S3-compatible storage.

    This adapter uses boto3 to interact with S3 and supports:
    - AWS S3
    - S3-compatible storage (IBM COS, MinIO, etc.)
    - Recursive prefix traversal
    - File filtering by extension and patterns
    - Hidden file exclusion
    - Size-based filtering
    - Parallel downloads with bounded concurrency

    Features:
    - Lazy loading: Documents contain metadata only, no binary content
    - Binary content loaded on-demand by downstream operators
    - Efficient pagination for large buckets
    - Parallel processing with configurable concurrency (default: 20)
    - Metadata preservation (modified time, size, content type)
    - Error handling with detailed logging
    - Support for custom S3 endpoints
    - Cached AWS account ID for security verification

    Authentication:
    - AWS access key and secret key
    - Optional custom endpoint URL for S3-compatible storage
    """

    # Metadata for connector discovery
    SOURCE_NAME = "s3"
    SOURCE_DISPLAY_NAME = "Amazon S3"
    SOURCE_DESCRIPTION = "Ingest documents from Amazon S3 or S3-compatible storage"
    SOURCE_VERSION = "1.0.0"

    def __init__(self):
        """Initialize adapter with cached AWS account ID and reusable S3 clients."""
        self._cached_account_id: str | None = None
        # Cache boto3 clients keyed by (access_key, endpoint_url, region) so that
        # fetch_binary_content() does not re-create a TCP connection per document.
        self._client_cache: dict[tuple, Any] = {}
        # Cache (account_id, strict) keyed by the same tuple so STS is called at
        # most once per unique set of credentials rather than once per document.
        self._account_id_cache: dict[tuple, str | None] = {}

    @staticmethod
    def bind_file_reference(*, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set one S3 object key as the only object to ingest.

        ``file_reference`` is the object key in the bucket already configured
        on the flow, for example ``invoices/TR-INV_001.pdf``. The ``s3`` and
        ``ibm_cos`` providers share this adapter. Bucket, endpoint, and
        credentials stay in ``provider_config`` and are never read from the
        event. ``fetch_documents`` loads and checks that key, so this method
        only validates the reference.
        """
        provider_config["object_key"] = S3SourceConfig.normalize_object_key(file_reference)

    async def fetch_documents(self, config: S3SourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """
        Fetch documents from S3 bucket with batched parallel downloads.

        This method processes S3 objects in batches with bounded concurrency,
        streaming results as they complete. Memory-efficient for large buckets.

        Args:
            config: Validated S3 configuration

        Yields:
            Document: Domain documents from S3

        Raises:
            ClientError: If S3 API calls fail
            BotoCoreError: If boto3 encounters errors
            ValueError: If bucket or credentials are invalid, or a configured object key is unavailable
        """
        try:
            # Create S3 client
            s3_client = self._create_s3_client(config)

            # Cache AWS account ID once for all operations
            self._cached_account_id = self._get_aws_account_id(config)

            if config.object_key:
                yield await self._fetch_single_object(s3_client=s3_client, config=config)
                return

            logger.info(
                "Streaming S3 objects from bucket '%s' with prefix '%s'",
                config.bucket,
                config.prefix,
            )

            # Process in batches to avoid loading all objects into memory
            batch_size = config.max_concurrent_downloads * 5  # Process 5x concurrency at a time
            semaphore = asyncio.Semaphore(config.max_concurrent_downloads)

            async def download_with_semaphore(s3_obj: dict[str, Any]) -> Document | None:
                """Download S3 object with semaphore-bounded concurrency."""
                async with semaphore:
                    try:
                        return await self._download_s3_object(s3_client, config, s3_obj)
                    except Exception as e:
                        logger.exception("Failed to download S3 object %s: %s", s3_obj["Key"], e)
                        return None

            fetched_count = 0
            total_listed = 0
            batch = []

            # Stream objects and process in batches
            async for s3_obj in self._stream_s3_objects(s3_client, config):
                batch.append(s3_obj)
                total_listed += 1

                # Process batch when it reaches batch_size
                if len(batch) >= batch_size:
                    logger.info("Processing batch of %d objects (total listed: %d)", len(batch), total_listed)

                    # Create tasks for this batch
                    tasks = [download_with_semaphore(obj) for obj in batch]

                    # Gather results in order to maintain deterministic ordering
                    documents = await asyncio.gather(*tasks)
                    for document in documents:
                        if document:
                            fetched_count += 1
                            yield document

                    # Clear batch for next iteration
                    batch.clear()

            # Process remaining objects in final batch
            if batch:
                logger.info("Processing final batch of %d objects (total listed: %d)", len(batch), total_listed)
                tasks = [download_with_semaphore(obj) for obj in batch]

                # Gather results in order to maintain deterministic ordering
                documents = await asyncio.gather(*tasks)
                for document in documents:
                    if document:
                        fetched_count += 1
                        yield document

            logger.info(
                "Completed streaming from S3 bucket '%s': listed %d objects, fetched %d documents",
                config.bucket,
                total_listed,
                fetched_count,
            )

        except (ClientError, BotoCoreError) as e:
            logger.exception("S3 error while fetching documents: %s", e)
            raise
        except Exception as e:
            logger.exception("Unexpected error while fetching documents from S3: %s", e)
            raise

    async def test_connection(self, config: S3SourceConfig) -> tuple[bool, str]:
        """
        Test connection to S3 bucket.

        Args:
            config: Validated S3 configuration

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            s3_client = self._create_s3_client(config)

            # Resolve bucket owner for security verification (AWS S3 only)
            account_id = self._get_aws_account_id(config)

            list_kwargs: dict[str, Any] = {"Bucket": config.bucket, "Prefix": config.prefix, "MaxKeys": 1}
            if account_id:
                list_kwargs["ExpectedBucketOwner"] = account_id

            # Test bucket access by listing objects (limit to 1)
            response = s3_client.list_objects_v2(**list_kwargs)

            # Check if we have access
            if "Contents" in response or "KeyCount" in response:
                object_count = response.get("KeyCount", 0)
                return (
                    True,
                    f"Successfully connected to S3 bucket '{config.bucket}'. Found {object_count} object(s) with prefix '{config.prefix}'.",
                )
            return (True, f"Successfully connected to S3 bucket '{config.bucket}', but no objects found.")

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            if error_code == "NoSuchBucket":
                return (False, f"Bucket '{config.bucket}' does not exist.")
            if error_code == "AccessDenied":
                return (False, f"Access denied to bucket '{config.bucket}'. Check credentials and permissions.")
            if error_code == "InvalidAccessKeyId":
                return (False, "Invalid access key ID. Check your credentials.")
            if error_code == "SignatureDoesNotMatch":
                return (False, "Invalid secret key. Check your credentials.")
            return (False, f"S3 error ({error_code}): {error_message}")

        except BotoCoreError as e:
            return (False, f"Boto3 error: {e}")
        except Exception as e:
            return (False, f"Unexpected error: {e}")

    def get_config_schema(self) -> type[S3SourceConfig]:
        """Get the Pydantic configuration model for S3 source."""
        return S3SourceConfig

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> S3SourceConfig:
        """
        Build S3 configuration from operator parameters.

        Args:
            provider_config: All provider-specific parameters including credentials.
            included_extensions: File extensions to include (optional)
            max_files: Maximum number of files to fetch while listing/downloading (optional)

        Returns:
            S3SourceConfig: Validated configuration object

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        access_key = resolve_env_var(provider_config.get("access_key"))
        secret_key = resolve_env_var(provider_config.get("secret_key"))
        bucket = resolve_env_var(value=provider_config.get("bucket"))
        prefix = resolve_env_var(value=provider_config.get("prefix", ""))

        if not access_key:
            raise ValueError("Missing required parameter: 'access_key'")
        if not secret_key:
            raise ValueError("Missing required parameter: 'secret_key'")
        if not bucket:
            raise ValueError("Missing required parameter: 'bucket'")
        # prefix is optional - empty string means scan entire bucket

        # Build configuration
        config_dict = {
            "access_key": access_key,
            "secret_key": secret_key,
            "bucket": bucket,
            "prefix": prefix,
            "endpoint_url": resolve_env_var(value=provider_config.get("endpoint_url")) or None,
            "region": provider_config.get("region"),
            "recursive": provider_config.get("recursive", True),
            "file_extensions": included_extensions or [],
            "exclude_patterns": provider_config.get("exclude_patterns", []),
            "max_file_size_mb": provider_config.get("max_file_size_mb"),
            "skip_hidden_files": provider_config.get("skip_hidden_files", True),
            "skip_empty_files": provider_config.get("skip_empty_files", True),
            "max_concurrent_downloads": provider_config.get("max_concurrent_downloads", 20),
            "download_timeout_seconds": provider_config.get("download_timeout_seconds", 300),
            "max_files": max_files,
            "verify_expected_bucket_owner": provider_config.get("verify_expected_bucket_owner", False),
        }

        # File events set object_key. Leave it unset for a normal bucket scan.
        object_key = provider_config.get("object_key")
        if object_key:
            config_dict["object_key"] = object_key

        return S3SourceConfig(**config_dict)

    def _create_s3_client(self, config: S3SourceConfig) -> Any:
        """
        Create boto3 S3 client with configuration.

        Args:
            config: S3 configuration

        Returns:
            boto3 S3 client
        """
        client_kwargs: dict[str, Any] = {
            "aws_access_key_id": config.access_key,
            "aws_secret_access_key": config.secret_key,
        }

        # Add endpoint URL for S3-compatible storage
        if config.endpoint_url:
            client_kwargs["endpoint_url"] = config.endpoint_url

        # Add region if specified
        if config.region:
            client_kwargs["region_name"] = config.region

        return boto3.client("s3", **client_kwargs)

    def _get_aws_account_id(self, config: S3SourceConfig) -> str | None:
        """
        Retrieve the AWS account ID for the configured credentials via STS GetCallerIdentity.

        Always attempts to resolve the account ID so ExpectedBucketOwner can be injected
        into S3 API calls when possible.

        When verify_expected_bucket_owner is True, any failure raises an error — the
        bucket owner check must be enforced. When False, failures are logged and silently
        ignored so S3 operations still proceed.

        Args:
            config: S3 configuration

        Returns:
            AWS account ID string (e.g. "123456789012"), or None if unavailable and
            verify_expected_bucket_owner is False (or endpoint_url is set).

        Raises:
            RuntimeError: If verify_expected_bucket_owner is True and the account ID
                cannot be resolved via STS.
        """
        return resolve_aws_account_id(
            access_key=config.access_key,
            secret_key=config.secret_key,
            region=config.region,
            endpoint_url=config.endpoint_url,
            strict=config.verify_expected_bucket_owner,
        )

    async def _stream_s3_objects(self, s3_client: Any, config: S3SourceConfig) -> AsyncGenerator[dict[str, Any], None]:
        """
        List S3 objects synchronously with pagination and filtering.

        This method yields S3 object metadata one at a time as pages are received
        from S3, enabling true streaming behavior without loading all into memory.

        Args:
            s3_client: boto3 S3 client
            config: S3 configuration

        Yields:
            S3 object metadata dictionaries (filtered)
        """
        logger.info("Listing S3 objects from bucket '%s' with prefix '%s'", config.bucket, config.prefix)

        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=config.bucket, Prefix=config.prefix)

        total_listed = 0
        total_yielded = 0

        for page_number, page in enumerate(pages, start=1):
            page_contents = page.get("Contents", [])
            total_listed += len(page_contents)

            logger.debug(
                "Received S3 page %d with %d object(s) (total listed: %d, yielded: %d)",
                page_number,
                len(page_contents),
                total_listed,
                total_yielded,
            )

            if not page_contents:
                continue

            for obj in page_contents:
                if self._should_skip_object(obj, config):
                    continue

                total_yielded += 1
                yield obj

        logger.info(
            "Completed listing S3 bucket '%s': listed %d objects, yielded %d after filtering",
            config.bucket,
            total_listed,
            total_yielded,
        )

    def _should_skip_object(self, obj: dict[str, Any], config: S3SourceConfig) -> bool:
        """
        Check if S3 object should be skipped based on filters.

        Args:
            obj: S3 object metadata
            config: S3 configuration

        Returns:
            True if object should be skipped, False otherwise
        """
        key = obj["Key"]
        size = obj.get("Size", 0)

        # Skip directory markers (keys ending with /)
        if key.endswith("/"):
            return True

        # Skip empty files
        if config.skip_empty_files and size == 0:
            return True

        # Skip files exceeding max size
        max_size_bytes = config.get_max_file_size_bytes()
        if max_size_bytes and size > max_size_bytes:
            logger.debug("Skipping %s: size %d exceeds max %s bytes", key, size, max_size_bytes)
            return True

        # Skip hidden files/directories
        if config.skip_hidden_files and self._is_hidden_path(key):
            return True

        # Apply file extension filter
        if config.file_extensions:
            file_ext = Path(key).suffix.lower()
            if file_ext not in config.file_extensions:
                return True

        # Apply exclude patterns
        if config.exclude_patterns:
            filename = Path(key).name
            for pattern in config.exclude_patterns:
                if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(key, pattern):
                    logger.debug("Skipping %s: matches exclude pattern '%s'", key, pattern)
                    return True

        return False

    def _is_hidden_path(self, key: str) -> bool:
        """
        Check if any path component is hidden (starts with .).

        Args:
            key: S3 object key

        Returns:
            True if path contains hidden components
        """
        path_parts = key.split("/")
        return any(part.startswith(".") and part not in [".", ".."] for part in path_parts)

    async def _fetch_single_object(self, *, s3_client: Any, config: S3SourceConfig) -> Document:
        """Fetch the one object named by ``config.object_key``.

        HeadObject addresses that key only, so a configured prefix cannot
        widen the result to other objects. A missing or unreadable key raises
        ``ValueError``. The message and log record the key and error code,
        never credentials or the endpoint.
        """
        key = config.object_key
        if not key:
            raise ValueError("File reference must be a non-empty S3 object key")

        head_kwargs: dict[str, Any] = {"Bucket": config.bucket, "Key": key}
        if self._cached_account_id:
            head_kwargs["ExpectedBucketOwner"] = self._cached_account_id

        logger.info("Fetching single S3 object: key=%s", key)
        try:
            head = s3_client.head_object(**head_kwargs)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            # Drop the client exception. Its text can include the endpoint.
            logger.error("S3 object key is not available: key=%s error_code=%s", key, error_code)
            raise ValueError(f"S3 object key is not available: {key}") from None
        except BotoCoreError:
            logger.error("S3 object key is not available: key=%s", key)
            raise ValueError(f"S3 object key is not available: {key}") from None

        s3_obj = {
            "Key": key,
            "Size": head.get("ContentLength", 0),
            "LastModified": head.get("LastModified"),
            "ETag": head.get("ETag", ""),
            "StorageClass": head.get("StorageClass", "STANDARD"),
        }
        document = await self._download_s3_object(s3_client, config, s3_obj)
        if document is None:
            raise ValueError(f"S3 object key is not available: {key}")
        return document

    async def _download_s3_object(
        self, s3_client: Any, config: S3SourceConfig, s3_obj: dict[str, Any]
    ) -> Document | None:
        """
        Create domain Document from S3 object metadata (lazy loading - no binary download).

        Args:
            s3_client: boto3 S3 client
            config: S3 configuration
            s3_obj: S3 object metadata

        Returns:
            Document with metadata only, or None if processing fails
        """
        key = s3_obj["Key"]

        try:
            # Extract metadata
            last_modified = s3_obj.get("LastModified")
            if isinstance(last_modified, datetime):
                modified_time = last_modified
            else:
                modified_time = None

            size = s3_obj.get("Size", 0)

            # Determine content type from file extension (avoid expensive head_object call)
            content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

            # Build S3 URI
            s3_uri = f"s3://{config.bucket}/{key}"

            # Build HTTP URL for reference
            if config.endpoint_url:
                # S3-compatible storage
                http_url = f"{config.endpoint_url}/{config.bucket}/{key}"
            else:
                # AWS S3
                region = config.region or "us-east-1"
                http_url = f"https://{config.bucket}.s3.{region}.amazonaws.com/{key}"

            # Determine file extension
            extension = Path(key).suffix.lower()

            # Create domain document WITHOUT binary content (lazy loading)
            document = Document(
                id=key,
                name=Path(key).name,
                content=b"",  # Empty - binary loaded on-demand by downstream operators
                source_url=s3_uri,
                modified_time=modified_time,
                mimetype=content_type,
                size=size,
                extension=extension,
                metadata={
                    "bucket": config.bucket,
                    "key": key,
                    "endpoint_url": config.endpoint_url,
                    "region": config.region,
                    "etag": s3_obj.get("ETag", "").strip('"'),
                    "storage_class": s3_obj.get("StorageClass", "STANDARD"),
                    "content_type": content_type,
                    "http_url": http_url,
                },
            )

            logger.debug("Created document metadata for S3 object: %s (%d bytes)", key, size)
            return document

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error("Failed to get metadata for %s: S3 error (%s): %s", key, error_code, e)
            return None
        except Exception as e:
            logger.exception("Failed to process %s: %s", key, e)
            return None

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific S3 object on-demand.

        Args:
            source_id: S3 URI (s3://bucket/key) or S3 key
            provider_config: All provider-specific parameters including credentials.

        Returns:
            bytes | None: Binary content of the S3 object, or None if not found or error occurred
        """
        try:
            access_key = resolve_env_var(provider_config.get("access_key"))
            secret_key = resolve_env_var(provider_config.get("secret_key"))

            if not access_key or not secret_key:
                logger.error("Missing S3 credentials for fetching %s", source_id)
                return None

            # Parse S3 URI to extract bucket and key
            if source_id.startswith("s3://"):
                parts = source_id[5:].split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""
            else:
                bucket_value = resolve_env_var(provider_config.get("bucket"))
                if not bucket_value:
                    logger.error("Cannot determine S3 bucket from source_id or provider_config")
                    return None
                bucket = str(bucket_value)
                key = source_id

            endpoint_url = resolve_env_var(provider_config.get("endpoint_url"))
            region = resolve_env_var(provider_config.get("region"))

            # Reuse cached boto3 client — creating a new client per document causes
            # redundant TCP handshake setup and is the main latency driver here.
            cache_key = (access_key, endpoint_url or "", region or "")
            if cache_key not in self._client_cache:
                client_kwargs: dict[str, Any] = {
                    "aws_access_key_id": access_key,
                    "aws_secret_access_key": secret_key,
                }
                if endpoint_url:
                    client_kwargs["endpoint_url"] = endpoint_url
                if region:
                    client_kwargs["region_name"] = region
                self._client_cache[cache_key] = boto3.client("s3", **client_kwargs)
            s3_client = self._client_cache[cache_key]

            # Reuse cached account_id — STS GetCallerIdentity is a network call and
            # returns the same value for the lifetime of the adapter instance.
            if cache_key not in self._account_id_cache:
                self._account_id_cache[cache_key] = resolve_aws_account_id(
                    access_key=access_key,
                    secret_key=secret_key,
                    region=region,
                    endpoint_url=endpoint_url,
                )
            account_id = self._account_id_cache[cache_key]

            get_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
            if account_id:
                get_kwargs["ExpectedBucketOwner"] = account_id

            logger.info("Downloading binary content from S3: bucket=%s, key=%s", bucket, key)
            response = s3_client.get_object(**get_kwargs)
            content = response["Body"].read()

            logger.info("Successfully downloaded %d bytes from S3: %s", len(content), source_id)
            return content

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error("S3 ClientError (%s) fetching %s: %s", error_code, source_id, e)
            return None
        except BotoCoreError as e:
            logger.error("S3 BotoCoreError fetching %s: %s", source_id, e)
            return None
        except Exception:
            logger.exception("Unexpected error fetching binary content from S3 %s", source_id)
            return None
