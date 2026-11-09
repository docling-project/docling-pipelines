# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for filesystem source adapter."""

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class FilesystemSourceConfig(BaseModel):
    """
    Type-safe configuration for filesystem document source.

    This Pydantic model provides:
    - Automatic validation of configuration values
    - Type safety and IDE autocomplete
    - Clear documentation of required/optional fields
    - Default values where appropriate
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ()

    # Required fields
    paths: list[str] = Field(
        ...,
        description="List of root directory or file paths to ingest documents from.",
    )

    # Optional fields with defaults
    recursive: bool = Field(True, description="Whether to recursively traverse subdirectories")

    file_extensions: list[str] = Field(
        default_factory=list,
        description="List of file extensions to include (e.g., ['.pdf', '.txt']). Empty list means all files.",
    )

    exclude_patterns: list[str] = Field(
        default_factory=list, description="List of glob patterns to exclude (e.g., ['*.tmp', '__pycache__/*'])"
    )

    max_file_size_mb: int | None = Field(
        None, description="Maximum file size in MB to process. None means no limit.", ge=1
    )

    follow_symlinks: bool = Field(False, description="Whether to follow symbolic links")

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, v: list[str]) -> list[str]:
        """Validate that all root paths exist (can be file or directory)."""
        if not v:
            raise ValueError("paths must contain at least one path")
        validated: list[str] = []
        for path in v:
            expanded = Path(path).expanduser()
            if not expanded.exists():
                raise ValueError(f"Root path does not exist: {path}")
            validated.append(str(expanded))
        return validated

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot."""
        return [ext if ext.startswith(".") else f".{ext}" for ext in v]

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "paths": ["/path/to/documents", "/another/path"],
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", "__pycache__/*"],
                "max_file_size_mb": 100,
                "follow_symlinks": False,
            }
        }
