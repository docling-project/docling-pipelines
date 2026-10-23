"""Configuration model for S3 source adapter."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator

# S3 rejects object keys longer than 1024 bytes.
_MAX_OBJECT_KEY_BYTES = 1024


class S3SourceConfig(BaseModel):
    """
    Type-safe configuration for Amazon S3 document source.

    This Pydantic model provides:
    - Automatic validation of configuration values
    - Type safety and IDE autocomplete
    - Clear documentation of required/optional fields
    - Support for both AWS S3 and S3-compatible storage (e.g., IBM COS, MinIO)
    """

    # AWS credentials
    access_key: str = Field(
        ..., description="AWS access key ID or S3-compatible access key", json_schema_extra={"sensitive": True}
    )

    secret_key: str = Field(
        ..., description="AWS secret access key or S3-compatible secret key", json_schema_extra={"sensitive": True}
    )

    # S3 bucket configuration
    bucket: str = Field(..., description="S3 bucket name")

    prefix: str = Field(
        "",
        description="S3 key prefix to filter objects. Use 'documents/reports/' for directory or 'documents/report.pdf' for exact file",
    )

    object_key: str | None = Field(
        None,
        description=(
            "Object key to ingest on its own, for example 'invoices/report.pdf'. "
            "When set, only this object is fetched from the configured bucket. "
            "File events for the s3 and ibm_cos providers set this from file_reference. "
            "The value is a key, not an s3:// URI."
        ),
    )

    # S3-compatible storage configuration (optional)
    endpoint_url: str | None = Field(
        None,
        description="Custom S3 endpoint URL for S3-compatible storage (e.g., IBM COS, MinIO). Leave None for AWS S3.",
    )

    region: str | None = Field(None, description="AWS region (e.g., 'us-east-1'). Optional for S3-compatible storage.")

    # Behavior configuration
    recursive: bool = Field(True, description="Whether to recursively traverse subdirectories (prefixes)")

    file_extensions: list[str] = Field(
        default_factory=list,
        description="List of file extensions to include (e.g., ['.pdf', '.docx']). Empty list means all files.",
    )

    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="List of glob patterns to exclude (e.g., ['*.tmp', '.DS_Store'])",
    )

    max_file_size_mb: int | None = Field(
        None, description="Maximum file size in MB to process. None means no limit.", ge=1
    )

    skip_hidden_files: bool = Field(
        True, description="Whether to skip hidden files and directories (starting with '.')"
    )

    skip_empty_files: bool = Field(True, description="Whether to skip files with zero size")

    # Security configuration
    verify_expected_bucket_owner: bool = Field(
        False,
        description=(
            "Whether to verify the S3 bucket owner matches the caller's AWS account. "
            "When True, an error is raised if the bucket owner does not match (AWS S3 only). "
            "When False (default), owner verification is skipped silently. "
            "Has no effect for S3-compatible storage (endpoint_url set)."
        ),
    )

    # Performance configuration
    max_concurrent_downloads: int = Field(100, description="Maximum number of concurrent S3 downloads", ge=1, le=100)

    download_timeout_seconds: int = Field(120, description="Timeout for downloading a single file in seconds", ge=30)

    max_files: int | None = Field(
        None, description="Maximum number of files to fetch. None means no limit. Helps optimize performance."
    )

    @field_validator("access_key", "secret_key", "bucket")
    @classmethod
    def validate_required_fields(cls, v: str, info) -> str:
        """Validate that required fields are not empty."""
        if not v or not v.strip():
            field_name = info.field_name
            raise ValueError(f"{field_name} cannot be empty")
        return v.strip()

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot and are lowercase."""
        return [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in v]

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        """Normalize prefix - remove leading slash, ensure trailing slash if not empty."""
        if not v:
            return ""
        # Remove leading slash
        return v.lstrip("/")

    @staticmethod
    def normalize_object_key(file_reference: str) -> str:
        """Return one S3 object key, or reject an empty or unsupported reference.

        The reference is the key inside the bucket already configured on the flow.
        URIs are rejected so an event cannot select another bucket or endpoint.
        """
        if not isinstance(file_reference, str) or not file_reference.strip():
            raise ValueError("File reference must be a non-empty S3 object key")

        reference = file_reference.strip()
        lowered = reference.lower()
        if lowered.startswith(("s3://", "http://", "https://", "cos://")) or "://" in reference:
            raise ValueError("File reference must be an S3 object key in the configured bucket, not a URI")

        key = reference.lstrip("/")
        if not key or key.endswith("/") or any(separator in key for separator in ("\x00", "\n", "\r")):
            raise ValueError(f"File reference is not an S3 object key: {reference}")

        if len(key.encode("utf-8")) > _MAX_OBJECT_KEY_BYTES:
            raise ValueError("File reference exceeds the maximum S3 object key length of 1024 bytes")

        return key

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str | None) -> str | None:
        """Normalize a single-object key supplied on the configuration."""
        if value is None:
            return None
        return cls.normalize_object_key(value)

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str | None) -> str | None:
        """Validate endpoint URL format."""
        if v:
            v = v.strip()
            if not v.startswith(("http://", "https://")):
                raise ValueError("endpoint_url must start with http:// or https://")
            # Remove trailing slash
            v = v.rstrip("/")
        return v

    def is_s3_compatible(self) -> bool:
        """Check if this is S3-compatible storage (not AWS S3)."""
        return self.endpoint_url is not None

    def get_max_file_size_bytes(self) -> int | None:
        """Get max file size in bytes."""
        if self.max_file_size_mb is None:
            return None
        return self.max_file_size_mb * 1024 * 1024

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret  # nosec B105 — example AWS key format in docstring, not a real credential
                "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret  # nosec B105 — example AWS key format in docstring, not a real credential
                "bucket": "my-documents-bucket",
                "prefix": "documents/reports/",  # Directory prefix with trailing slash, or "documents/report.pdf" for exact file
                "endpoint_url": None,
                "region": "us-east-1",
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", ".DS_Store", "~$*"],
                "max_file_size_mb": 100,
                "skip_hidden_files": True,
                "skip_empty_files": True,
                "max_concurrent_downloads": 20,
                "download_timeout_seconds": 300,
            }
        }
