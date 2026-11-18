# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for the Dropbox source adapter."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


class DropboxSourceConfig(BaseModel):
    """
    Type-safe configuration for the Dropbox document source.

    Two authentication modes are supported:
    - Short-lived / legacy token: provide ``access_token``.
    - Long-lived refresh flow: provide ``refresh_token``, ``app_key`` and ``app_secret``.
      The SDK then refreshes the access token automatically.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "access_token",
        "refresh_token",
        "app_key",
        "app_secret",
    )

    # Credentials (never included in repr to keep secrets out of logs and tracebacks)
    access_token: str | None = Field(
        None,
        repr=False,
        description="Dropbox OAuth2 access token (short-lived or legacy long-lived token)",
        json_schema_extra={"sensitive": True},
    )

    refresh_token: str | None = Field(
        None,
        repr=False,
        description="Dropbox OAuth2 refresh token. Requires app_key and app_secret.",
        json_schema_extra={"sensitive": True},
    )

    app_key: str | None = Field(
        None,
        repr=False,
        description="Dropbox app key, required when using refresh_token",
        json_schema_extra={"sensitive": True},
    )

    app_secret: str | None = Field(
        None,
        repr=False,
        description="Dropbox app secret, required when using refresh_token",
        json_schema_extra={"sensitive": True},
    )

    # Dropbox location configuration
    folder_path: str = Field(
        "",
        description="Dropbox folder path to ingest from (e.g. '/Reports'). Empty string means the account root.",
    )

    file_path: str | None = Field(
        None,
        description=(
            "Specific Dropbox file path (e.g. '/Reports/q1.pdf') or file id (e.g. 'id:abc123') to ingest. "
            "If provided, only this file is processed (ignores folder_path, recursive and filter settings)."
        ),
    )

    # Behavior configuration
    recursive: bool = Field(True, description="Whether to recursively traverse subfolders")

    file_extensions: list[str] = Field(
        default_factory=list,
        description="List of file extensions to include (e.g., ['.pdf', '.docx']). Empty list means all files.",
    )

    exclude_patterns: list[str] = Field(
        default_factory=list, description="List of glob patterns to exclude (e.g., ['*.tmp', '*/Archive/*'])"
    )

    max_file_size_mb: int | None = Field(None, description="Maximum file size in MB to process. None means no limit.")

    max_files: int | None = Field(None, description="Maximum number of files to fetch. None means no limit.")

    @field_validator("access_token", "refresh_token", "app_key", "app_secret")
    @classmethod
    def normalize_optional_credential(cls, v: str | None) -> str | None:
        """Treat blank credential strings as not provided."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("folder_path")
    @classmethod
    def validate_folder_path(cls, v: str) -> str:
        """Normalize the folder path to Dropbox API conventions (root is an empty string)."""
        path = (v or "").strip()
        if path in ("", "/"):
            return ""
        if not path.startswith("/"):
            path = f"/{path}"
        return path.rstrip("/")

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: str | None) -> str | None:
        """Normalize a single-file path, leaving Dropbox file ids untouched."""
        if v is None:
            return None
        path = v.strip()
        if not path:
            return None
        if path.startswith(("id:", "rev:", "ns:")):
            return path
        return path if path.startswith("/") else f"/{path}"

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions are lowercase and start with a dot."""
        return [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in v]

    @field_validator("max_file_size_mb")
    @classmethod
    def validate_max_file_size(cls, v: int | None) -> int | None:
        """Validate max file size is positive."""
        if v is not None and v <= 0:
            raise ValueError("max_file_size_mb must be positive")
        return v

    @field_validator("max_files")
    @classmethod
    def validate_max_files(cls, v: int | None) -> int | None:
        """Validate max files is positive."""
        if v is not None and v <= 0:
            raise ValueError("max_files must be positive")
        return v

    @model_validator(mode="after")
    def validate_credentials(self) -> "DropboxSourceConfig":
        """Ensure a usable authentication mode is configured."""
        if self.access_token:
            return self

        if self.refresh_token:
            missing = [name for name in ("app_key", "app_secret") if not getattr(self, name)]
            if missing:
                raise ValueError(f"refresh_token authentication requires {' and '.join(missing)}")
            return self

        raise ValueError(
            "Dropbox credentials missing: provide 'access_token', or 'refresh_token' together with "
            "'app_key' and 'app_secret'"
        )

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "access_token": "${DROPBOX_ACCESS_TOKEN}",  # pragma: allowlist secret  # nosec B105 - env var reference in a schema example, not a credential
                "folder_path": "/Reports",
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", "*/Archive/*"],
                "max_file_size_mb": 100,
                "max_files": 100,
            }
        }
