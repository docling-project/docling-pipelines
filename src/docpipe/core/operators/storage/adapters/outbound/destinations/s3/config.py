# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for the S3 destination adapter."""

import mimetypes
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class S3DestinationConfig(BaseModel):
    """Type-safe configuration for the S3 destination adapter.

    Supports both AWS S3 and S3-compatible storage (IBM COS, MinIO, etc.).
    Credentials are expected to be resolved from environment variables before
    constructing this model (see build_config_from_operator_params).
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "access_key",
        "secret_key",
        "endpoint_url",
    )

    # AWS credentials
    access_key: str = Field(..., description="AWS access key ID or S3-compatible access key")
    secret_key: str = Field(..., description="AWS secret access key or S3-compatible secret key")

    # S3 destination configuration
    bucket: str = Field(..., description="Target S3 bucket name")
    key_prefix: str = Field(
        "",
        description=(
            "Base key prefix prepended to every object key written. Equivalent to root_path for the filesystem adapter."
        ),
    )
    create_dirs: bool = Field(
        True,
        description=(
            "When True (default), write to the prefix even if no objects exist under it yet. "
            "When False, validate_destination checks that at least one object already exists "
            "under the prefix; if none are found the write is refused."
        ),
    )

    # S3-compatible storage (optional)
    endpoint_url: str | None = Field(
        None,
        description="Custom S3 endpoint URL for S3-compatible storage (e.g., IBM COS, MinIO). Leave None for AWS S3.",
    )
    region: str | None = Field(
        None,
        description="AWS region (e.g., 'us-east-1'). Optional for S3-compatible storage.",
    )

    # Security
    verify_expected_bucket_owner: bool = Field(
        False,
        description=(
            "When True, verifies the bucket owner matches the caller's AWS account via STS. "
            "Has no effect for S3-compatible storage (endpoint_url set)."
        ),
    )

    # Content type hints
    content_type_map: dict[str, str] = Field(
        default_factory=lambda: {
            "md": "text/markdown",  # stdlib returns text/x-markdown or None depending on platform
        },
        description=(
            "Mapping of file extension to MIME Content-Type for S3 object metadata. "
            "Entries here take precedence over stdlib mimetypes.guess_type() resolution. "
            "Only override extensions where the stdlib guess is wrong or absent."
        ),
    )

    @field_validator("access_key", "secret_key", "bucket")
    @classmethod
    def validate_not_empty(cls, v: str, info) -> str:
        """Ensure required string fields are not blank."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip()

    @field_validator("key_prefix")
    @classmethod
    def normalise_key_prefix(cls, v: str) -> str:
        """Strip leading slash; ensure trailing slash when non-empty."""
        v = v.lstrip("/")
        if v and not v.endswith("/"):
            v = v + "/"
        return v

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str | None) -> str | None:
        """Validate endpoint URL format for S3-compatible storage."""
        if v:
            v = v.strip()
            if not v.startswith(("http://", "https://")):
                raise ValueError("endpoint_url must start with http:// or https://")
            v = v.rstrip("/")
        return v

    def get_content_type(self, *, extension: str) -> str | None:
        """Return the Content-Type for a given file extension, or None if unknown.

        Resolution order:
        1. Explicit override in content_type_map.
        2. stdlib mimetypes.guess_type() for everything else.
        3. None if the extension is genuinely unrecognised.
        """
        ext = extension.lstrip(".").lower()
        if ext in self.content_type_map:
            return self.content_type_map[ext]
        mime, _ = mimetypes.guess_type(f"file.{ext}")
        return mime

    def is_s3_compatible(self) -> bool:
        """True when configured against S3-compatible storage (not AWS S3)."""
        return self.endpoint_url is not None

    class Config:
        json_schema_extra: ClassVar[dict] = {
            "example": {
                "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
                "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
                "bucket": "my-export-bucket",
                "key_prefix": "exports/documents/",
                "endpoint_url": None,
                "region": "us-east-1",
                "verify_expected_bucket_owner": False,
            }
        }
