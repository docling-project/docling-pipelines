"""Configuration model for SharePoint source adapter."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class SharePointSourceConfig(BaseModel):
    """
    Type-safe configuration for SharePoint document source.

    This Pydantic model provides:
    - Automatic validation of configuration values
    - Type safety and IDE autocomplete
    - Clear documentation of required/optional fields
    - Azure AD app-only authentication (client credentials flow)
    """

    # Azure AD App Registration credentials (app-only authentication)
    client_id: str = Field(..., description="Azure AD application (client) ID", json_schema_extra={"sensitive": True})

    client_secret: str = Field(
        ..., description="Azure AD application client secret", json_schema_extra={"sensitive": True}
    )

    tenant_id: str = Field(..., description="Azure AD tenant (directory) ID", json_schema_extra={"sensitive": True})

    # SharePoint configuration
    document_library_id: str = Field(..., description="SharePoint document library ID (drive ID in Microsoft Graph)")

    folder_path: str | None = Field(
        None, description="Folder path to ingest from (e.g., '/Shared Documents/Reports'). If None, starts from root"
    )

    file_path: str | None = Field(
        None,
        description=(
            "SharePoint item to ingest on its own. A non-URL value is a Microsoft Graph drive item id. "
            "An http(s) value is a SharePoint file URL with an id or sourcedoc query parameter. "
            "If provided, only this file is processed. "
            "File events for the sharepoint provider set this from file_reference."
        ),
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

    # Microsoft Graph API configuration
    graph_api_version: str = Field("v1.0", description="Microsoft Graph API version to use (v1.0 or beta)")

    @field_validator("client_id", "client_secret", "tenant_id", "document_library_id")
    @classmethod
    def validate_required_credentials(cls, v: str, info) -> str:
        """Validate that required credentials are not empty."""
        if not v or not v.strip():
            field_name = info.field_name
            raise ValueError(f"{field_name} cannot be empty")
        return v.strip()

    @field_validator("file_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot."""
        return [ext if ext.startswith(".") else f".{ext}" for ext in v]

    @field_validator("graph_api_version")
    @classmethod
    def validate_api_version(cls, v: str) -> str:
        """Validate Graph API version."""
        allowed_versions = ["v1.0", "beta"]
        if v not in allowed_versions:
            raise ValueError(f"graph_api_version must be one of {allowed_versions}")
        return v

    @field_validator("folder_path")
    @classmethod
    def validate_folder_path(cls, v: str | None) -> str | None:
        """Ensure folder path starts with / if provided."""
        if v and not v.startswith("/"):
            return f"/{v}"
        return v

    class Config:
        """Pydantic configuration."""

        json_schema_extra: ClassVar[dict] = {
            "example": {
                "client_id": "12345678-1234-1234-1234-123456789012",
                "client_secret": "your-client-secret",  # pragma: allowlist secret  # nosec B105 — placeholder value in docstring example, not a real credential
                "tenant_id": "87654321-4321-4321-4321-210987654321",
                "document_library_id": "b!abc123...",
                "folder_path": "/Shared Documents",
                "recursive": True,
                "file_extensions": [".pdf", ".docx", ".txt"],
                "exclude_patterns": ["*.tmp", "~$*"],
                "max_file_size_mb": 100,
                "graph_api_version": "v1.0",
            }
        }
