# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class BoxSourceConfig(BaseModel):
    """Configuration for Box source."""

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "credentials_json",
        "credentials_path",
        "credentials_json_path",
    )
    SECRET_FIELD_ALIASES: ClassVar[tuple[str, ...]] = ("credentials_json_path",)

    # Credentials (inline JSON or dict is primary; file path is secondary)
    credentials_json: dict | str | None = Field(
        None,
        description="Inline Box JWT / App config JSON string or dictionary (primary auth method)",
        json_schema_extra={"sensitive": True},
    )

    credentials_path: str | None = Field(
        None,
        description="Path to Box app/JWT config file (secondary/fallback auth method)",
        json_schema_extra={"sensitive": True},
    )

    # Box folder configuration
    folder_id: str = Field("0", description="Box folder ID to start ingestion from. Default '0' is root folder.")

    file_id: str | None = Field(
        None,
        description="Specific Box file ID to ingest. If provided, only this file is processed (ignores folder_id and recursive settings).",
    )

    # Optional parameters
    recursive: bool = Field(True, description="Whether to recursively traverse subdirectories")

    file_extensions: list[str] = Field(
        default_factory=list,
        description="List of file extensions to include (e.g., ['.pdf', '.docx']). Empty list means all files.",
    )

    exclude_patterns: list[str] = Field(
        default_factory=list, description="List of glob patterns to exclude (e.g., ['*.tmp', 'Trash/*'])"
    )

    max_file_size_mb: int | None = Field(
        None, description="Maximum file size in MB to process. None means no limit.", ge=1
    )

    max_files: int | None = Field(None, description="Maximum number of files to fetch. None means no limit.")

    @field_validator("credentials_path")
    @classmethod
    def validate_credentials_path(cls, v: str | None) -> str | None:
        """Validate and expand config file path with environment variable resolution.

        Supports:
        - Environment variables: $VAR_NAME or ${VAR_NAME}
        - User home expansion: ~/path
        - Absolute paths: /path/to/file
        """
        if v is None:
            return None
        # First resolve environment variables
        resolved = os.path.expandvars(v)

        # Then expand user home directory
        return str(Path(resolved).expanduser())

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, v: str) -> str:
        """Resolve environment variable references in folder_id (e.g. ${BOX_SOURCE_FOLDER_ID})."""
        return os.path.expandvars(v)

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot."""
        return [ext if ext.startswith(".") else f".{ext}" for ext in v]

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "credentials_path": "~/.config/box/config.json",
                "folder_id": "0",
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", "Trash/*"],
                "max_file_size_mb": 100,
            }
        }
