# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for Web Page source adapter."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class WebPageSourceConfig(BaseModel):
    """
    Type-safe configuration for Web Page document source.

    This Pydantic model provides:
    - Automatic validation of configuration values
    - Type safety and IDE autocomplete
    - Clear documentation of required/optional fields
    - URL validation and normalization
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ()

    # URL configuration
    urls: list[str] = Field(
        ...,
        description="List of starting URLs to crawl. For single URL without crawling, provide one URL and set max_depth=0",
        min_length=1,
    )

    # Crawling behavior
    max_depth: int = Field(default=2, description="Maximum recursion depth for crawling", ge=0, le=10)

    prevent_outside: bool = Field(
        default=True,
        description="Prevent following links to external domains. If True, only crawls pages within the same domain.",
    )

    exclude_patterns: list[str] = Field(
        default_factory=list, description="URL patterns to exclude from crawling (e.g., ['/admin', '/login'])"
    )

    timeout: int = Field(default=30, description="Request timeout in seconds", ge=1, le=300)

    extractor: str | None = Field(default=None, description="Custom extractor function for parsing HTML")

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        """Validate URLs are non-empty and properly formatted."""
        if not v:
            raise ValueError("At least one URL must be provided")

        validated_urls = []
        for url in v:
            url = url.strip()
            if not url:
                raise ValueError("URLs cannot be empty strings")

            # Basic URL validation - must start with http:// or https://
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"URL must start with http:// or https://: {url}")

            validated_urls.append(url)

        return validated_urls

    @field_validator("max_depth")
    @classmethod
    def validate_max_depth(cls, v: int) -> int:
        """Validate max_depth is within reasonable bounds."""
        if v < 0:
            raise ValueError("max_depth must be non-negative")
        if v > 10:
            raise ValueError("max_depth cannot exceed 10 (to prevent excessive crawling)")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout is within reasonable bounds."""
        if v < 1:
            raise ValueError("timeout must be at least 1 second")
        if v > 300:
            raise ValueError("timeout cannot exceed 300 seconds (5 minutes)")
        return v

    @field_validator("exclude_patterns")
    @classmethod
    def validate_exclude_patterns(cls, v: list[str]) -> list[str]:
        """Validate exclude patterns are non-empty strings."""
        return [pattern.strip() for pattern in v if pattern.strip()]

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "urls": ["https://example.com", "https://www.iana.org/domains/reserved"],
                "max_depth": 2,
                "prevent_outside": True,
                "exclude_patterns": ["/admin", "/login", "/api"],
                "timeout": 30,
                "extractor": None,
            }
        }
