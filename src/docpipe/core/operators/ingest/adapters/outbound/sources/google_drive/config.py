# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for Google Drive source adapter."""

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


class GoogleDriveSourceConfig(BaseModel):
    """
    Type-safe configuration for Google Drive document source.

    This Pydantic model provides:
    - Automatic validation of configuration values
    - Type safety and IDE autocomplete
    - Clear documentation of required/optional fields
    - OAuth or Service Account credential management
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "service_account_json",
        "service_account_json_path",
        "credentials_json",
        "credentials_path",
        "token_path",
    )

    # Service Account credentials (inline JSON or dict is primary; file path is secondary)
    service_account_json: dict | str | None = Field(
        None,
        description="Inline Google Service Account JSON string or dictionary (primary server-to-server auth)",
        json_schema_extra={"sensitive": True},
    )

    service_account_json_path: str | None = Field(
        None,
        description="Path to Google Service Account JSON file (secondary/fallback server-to-server auth)",
        json_schema_extra={"sensitive": True},
    )

    # OAuth credentials (inline client secrets JSON or dict is primary; file path is secondary)
    credentials_json: dict | str | None = Field(
        None,
        description="Inline Google OAuth client secrets JSON string or dictionary (primary OAuth flow)",
        json_schema_extra={"sensitive": True},
    )

    credentials_path: str | None = Field(
        None,
        description="Path to Google OAuth credentials JSON file (secondary/fallback OAuth flow)",
        json_schema_extra={"sensitive": True},
    )

    token_path: str | None = Field(
        None,
        description="Path to store OAuth token. If None, uses credentials_path directory or default",
        json_schema_extra={"sensitive": True},
    )

    # Drive configuration
    drive_id: str | None = Field(None, description="Specific Google Drive ID. If None, uses user's My Drive")

    folder_id: str | None = Field(None, description="Specific folder ID to ingest from. If None, starts from root")

    folder_path: str | None = Field(None, description="Folder path to ingest from (alternative to folder_id)")

    file_id: str | None = Field(
        None,
        description="Specific Google Drive file ID to ingest. If provided, only this file is processed (ignores folder_id, folder_path, recursive, and filter settings).",
    )

    # Behavior configuration
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

    # OAuth scopes
    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/drive.readonly"],
        description="OAuth scopes for Google Drive API",
    )

    max_files: int | None = Field(
        None, description="Maximum number of files to fetch. None means no limit. Helps optimize performance."
    )

    @model_validator(mode="after")
    def validate_auth_method(self) -> "GoogleDriveSourceConfig":
        """Ensure either OAuth or Service Account credentials are provided."""
        has_sa = bool(self.service_account_json or self.service_account_json_path)
        has_oauth = bool(self.credentials_json or self.credentials_path)

        if not has_sa and not has_oauth:
            raise ValueError(
                "Either Service Account credentials ('service_account_json' or 'service_account_json_path') "
                "or OAuth credentials ('credentials_json' or 'credentials_path') must be provided"
            )
        if has_sa and has_oauth:
            raise ValueError(
                "Cannot use both Service Account and OAuth authentication. "
                "Choose either Service Account or OAuth authentication"
            )
        return self

    @field_validator("credentials_path", "service_account_json_path")
    @classmethod
    def validate_credentials_path(cls, v: str | None) -> str | None:
        """Validate and expand credentials file path."""
        if v is None:
            return None
        # Only expand user home directory (~), don't make relative paths absolute
        # This allows the path to be resolved relative to where the command is run
        return str(Path(v).expanduser())

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot."""
        return [ext if ext.startswith(".") else f".{ext}" for ext in v]

    def get_token_path(self) -> str:
        """Get the token path, using credentials directory if not specified."""
        if self.token_path:
            return str(Path(self.token_path).expanduser())

        # Use same directory as credentials (only for OAuth)
        if self.credentials_path:
            return str(Path(self.credentials_path).expanduser().parent / "token.json")

        # For service account, token path is not used
        return ""

    def is_service_account(self) -> bool:
        """Check if using service account authentication."""
        return self.service_account_json is not None or self.service_account_json_path is not None

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "credentials_path": "~/.config/google/credentials.json",
                "token_path": "~/.config/google/token.json",
                "drive_id": None,
                "folder_path": "/Documents",
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", "Trash/*"],
                "max_file_size_mb": 100,
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            }
        }
