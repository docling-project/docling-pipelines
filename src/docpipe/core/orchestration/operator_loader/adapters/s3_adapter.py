"""S3 adapter for loading custom operators from S3 buckets."""

from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

try:
    import boto3

    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover - boto3 is a core dependency; this only runs in a broken install
    _BOTO3_AVAILABLE = False

from docpipe.core.orchestration.operator_loader.adapters.factories.operator_source_factory import (
    register_operator_source,
)
from docpipe.core.orchestration.operator_loader.adapters.filesystem_adapter import FilesystemAdapter
from docpipe.core.orchestration.operator_loader.ports.operator_source import (
    OperatorInfo,
    OperatorSourcePort,
    ValidationResult,
)
from docpipe.integrations.aws.s3_utils import resolve_aws_account_id
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_operator_source
class S3Adapter(OperatorSourcePort):
    """Adapter for loading operators from S3 buckets.

    Downloads operator files from S3 to local cache and delegates to
    FilesystemAdapter for loading. Uses boto3's default credential chain
    for authentication.

    Attributes:
        ADAPTER_NAME: Unique identifier for this adapter
        ADAPTER_DISPLAY_NAME: Human-readable name
    """

    ADAPTER_NAME = "s3"
    ADAPTER_DISPLAY_NAME = "Amazon S3"

    def __init__(self, uri: str, cache_dir: str | None = None):
        """Initialize S3 adapter.

        Args:
            uri: S3 URI in format s3://bucket-name/path/to/operators
            cache_dir: Optional custom cache directory. Defaults to ~/.docpipe/custom_operators_cache

        Raises:
            ImportError: If boto3 is not available
            ValueError: If URI format is invalid
        """
        if not _BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for S3 adapter. Install with: uv pip install boto3 or uv sync --extra aws"
            )

        self.uri = uri
        self._parse_s3_uri()

        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            home = Path.home()
            self.cache_dir = home / ".docpipe" / "custom_operators_cache" / self.bucket

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize S3 client using boto3's default credential chain:
        # 1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        # 2. Shared credentials file (~/.aws/credentials)
        # 3. IAM roles (for EC2/ECS/Lambda instances)
        self.s3_client = boto3.client("s3")

        # Resolve AWS account ID for ExpectedBucketOwner security parameter
        self._aws_account_id = resolve_aws_account_id()

        # Download operators to cache
        self._download_operators()

        # Delegate to filesystem adapter for actual loading
        # Type checker has issues with decorator type inference
        self.filesystem_adapter = FilesystemAdapter(str(self.cache_dir / self.prefix))  # type: ignore[call-arg]

        logger.info("Initialized S3 adapter for %s, cache: %s", self.uri, self.cache_dir)

    def _parse_s3_uri(self) -> None:
        """Parse S3 URI into bucket and prefix.

        Raises:
            ValueError: If URI format is invalid
        """
        parsed = urlparse(self.uri)

        if parsed.scheme != "s3":
            raise ValueError(f"Invalid S3 URI scheme. Expected 's3://', got: {parsed.scheme}")

        if not parsed.netloc:
            raise ValueError(f"Invalid S3 URI. Missing bucket name: {self.uri}")

        self.bucket = parsed.netloc
        self.prefix = parsed.path.lstrip("/")

        logger.debug("Parsed S3 URI - bucket: %s, prefix: %s", self.bucket, self.prefix)

    def _build_aws_kwargs(self) -> dict:
        """Build kwargs dict with ExpectedBucketOwner when an account ID is available."""
        if self._aws_account_id:
            return {"ExpectedBucketOwner": self._aws_account_id}
        return {}

    def _download_single_file(self, *, key: str) -> None:
        """Download a single operator file from S3 to the local cache.

        Args:
            key: S3 object key to download
        """
        relative_path = key[len(self.prefix) :].lstrip("/")
        local_path = self.cache_dir / self.prefix / relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Downloading %s to %s", key, local_path)
        extra_args = self._build_aws_kwargs()
        self.s3_client.download_file(self.bucket, key, str(local_path), ExtraArgs=extra_args or None)

    def _is_operator_file(self, *, key: str) -> bool:
        """Return True if the S3 key refers to a downloadable operator file."""
        if not key.endswith(".py"):
            return False
        return not Path(key).name.startswith("_")

    def _download_operators(self) -> None:
        """Download operator files from S3 to local cache.

        Raises:
            Exception: If S3 download fails
        """
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            list_kwargs: dict = {"Bucket": self.bucket, "Prefix": self.prefix}
            list_kwargs.update(self._build_aws_kwargs())
            pages = paginator.paginate(**list_kwargs)

            downloaded_count = 0
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not self._is_operator_file(key=key):
                        continue
                    self._download_single_file(key=key)
                    downloaded_count += 1

            logger.info("Downloaded %s operator files from S3", downloaded_count)

        except Exception as e:
            raise Exception(f"Failed to download operators from S3: {e}") from e

    def list_operators(self) -> list[OperatorInfo]:
        """Discover all operators from S3 (via cached files).

        Returns:
            List of OperatorInfo for discovered operators
        """
        operators = self.filesystem_adapter.list_operators()

        # Update source_location to reflect S3 origin
        for op in operators:
            op.source_location = f"{self.ADAPTER_NAME}:{self.uri}"

        return operators

    def load_operator(self, *, operator_info: OperatorInfo) -> ModuleType:
        """Load operator module from cached S3 files.

        Args:
            operator_info: Metadata about the operator to load

        Returns:
            Loaded Python module
        """
        return self.filesystem_adapter.load_operator(operator_info=operator_info)

    def validate_operator(self, *, module: ModuleType, operator_info: OperatorInfo) -> ValidationResult:
        """Validate operator implementation.

        Args:
            module: Loaded operator module
            operator_info: Metadata about the operator

        Returns:
            ValidationResult with validation status and messages
        """
        return self.filesystem_adapter.validate_operator(module=module, operator_info=operator_info)

    def clear_cache(self) -> None:
        """Clear the local cache directory and module cache.

        Clears both the downloaded files and loaded Python modules.
        Useful for forcing a re-download and reload of operators from S3.
        """
        import shutil

        # Clear module cache first
        self.filesystem_adapter.clear_cache()

        # Then clear file cache
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            logger.info("Cleared S3 cache: %s", self.cache_dir)
