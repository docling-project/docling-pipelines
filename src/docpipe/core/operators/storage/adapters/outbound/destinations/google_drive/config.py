# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for the Google Drive destination adapter."""

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


class GoogleDriveDestinationConfig(BaseModel):
    """Type-safe configuration for the Google Drive destination adapter.

    Supports two authentication methods (exactly one must be provided):
    - Service Account (recommended for pipelines): non-interactive, JSON key file.
    - OAuth2 (user access): interactive flow with token caching.

    The adapter uploads files to the specified Google Drive folder using the
    Drive API v3 ``files.create`` endpoint with resumable upload support.

    Example flow config::

        destination_config:
          provider: google_drive
          provider_config:
            folder_id: "${GDRIVE_FOLDER_ID}"
            create_dirs: true
          credentials:
            service_account_json_path: "${GDRIVE_SA_JSON_PATH}"
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "service_account_json_path",
        "credentials_path",
        "token_path",
    )

    # Google Drive destination configuration
    folder_id: str = Field(
        ...,
        description=(
            "ID of the target Google Drive folder to write files into. "
            "Find it in the Drive URL: https://drive.google.com/drive/folders/{folder_id}"
        ),
    )
    drive_id: str | None = Field(
        None,
        description=(
            "Shared Drive (Team Drive) ID. Set to None to use the authenticated user's My Drive. "
            "When set, corpora='drive' and supportsAllDrives=True are added to API calls."
        ),
    )
    create_dirs: bool = Field(
        True,
        description=(
            "When True (default), intermediate folders are created automatically on upload. "
            "When False, validate_destination checks that folder_id is accessible."
        ),
    )

    # Service Account authentication (server-to-server, recommended for pipelines)
    service_account_json_path: str | None = Field(
        None,
        description="Path to Google Service Account JSON key file (alternative to OAuth2).",
    )

    # OAuth2 authentication (user access with token caching)
    credentials_path: str | None = Field(
        None,
        description="Path to Google OAuth2 client secrets JSON file.",
    )
    token_path: str | None = Field(
        None,
        description="Path to cache the OAuth2 token. Defaults to the credentials directory.",
    )

    # Google Drive API configuration
    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/drive"],
        description=(
            "OAuth2 scopes for the Drive API. "
            "drive (default) grants full access to all Drive files, required for "
            "writing to pre-existing folders. Use drive.file to restrict access to "
            "files created by this app only."
        ),
    )
    chunk_size_mb: int = Field(
        5,
        ge=1,
        description="Chunk size in MB for resumable uploads. Minimum 1, default 5.",
    )

    @model_validator(mode="after")
    def validate_auth_method(self) -> "GoogleDriveDestinationConfig":
        """Enforce exactly one of Service Account or OAuth2 credentials."""
        has_sa = bool(self.service_account_json_path)
        has_oauth = bool(self.credentials_path)
        if not has_sa and not has_oauth:
            raise ValueError(
                "Either 'service_account_json_path' (for Service Account) or "
                "'credentials_path' (for OAuth2) must be provided."
            )
        if has_sa and has_oauth:
            raise ValueError(
                "Cannot use both 'service_account_json_path' and 'credentials_path'. "
                "Choose either Service Account or OAuth2 authentication."
            )
        return self

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, v: str) -> str:
        """Ensure folder_id is not blank."""
        if not v or not v.strip():
            raise ValueError("folder_id cannot be empty")
        return v.strip()

    @field_validator("service_account_json_path", "credentials_path")
    @classmethod
    def expand_path(cls, v: str | None) -> str | None:
        """Expand user home directory (~) in file paths."""
        if v is None:
            return None
        return str(Path(v.strip()).expanduser())

    def is_service_account(self) -> bool:
        """Return True when using Service Account authentication."""
        return self.service_account_json_path is not None

    def get_token_path(self) -> str:
        """Return the token path, falling back to the credentials directory."""
        if self.token_path:
            return str(Path(self.token_path).expanduser())
        if self.credentials_path:
            creds_dir = Path(self.credentials_path).expanduser().parent
            return str(creds_dir / "gdrive_token.pickle")
        return ""

    class Config:
        json_schema_extra: ClassVar[dict] = {
            "example": {
                "folder_id": "gdrive_folder_id",
                "drive_id": None,
                "create_dirs": True,
                "service_account_json_path": "${GDRIVE_SA_JSON_PATH}",
                "scopes": ["https://www.googleapis.com/auth/drive.file"],
                "chunk_size_mb": 5,
            }
        }
