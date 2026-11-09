# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for the SharePoint destination adapter."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class SharePointDestinationConfig(BaseModel):
    """Type-safe configuration for the SharePoint destination adapter.

    Uses Azure AD app-only authentication (client credentials flow) to write
    documents to a SharePoint document library via the Microsoft Graph API.

    Mirrors SharePointSourceConfig so that the same provider_config / credentials
    block can be reused across both ingest and storage operators.

    The Graph API upload endpoint used is::

        PUT /drives/{document_library_id}/root:/{folder_path}/{relative_path}:/content
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "client_id",
        "client_secret",
        "tenant_id",
    )

    # Azure AD App Registration credentials (client credentials flow)
    client_id: str = Field(..., description="Azure AD application (client) ID")
    client_secret: str = Field(..., description="Azure AD application client secret")
    tenant_id: str = Field(..., description="Azure AD tenant (directory) ID")

    # SharePoint destination configuration
    drive_id: str = Field(
        ...,
        description=(
            "Microsoft Graph drive ID for the SharePoint document library. "
            "Used in Graph API endpoints: /drives/{drive_id}/..."
        ),
    )
    folder_path: str = Field(
        "",
        description=(
            "Destination folder path within the document library, "
            "e.g. '/Processed Documents'. "
            "Leave empty to write to the drive root."
        ),
    )
    create_dirs: bool = Field(
        True,
        description=(
            "When True (default), intermediate folders are created automatically on upload. "
            "When False, validate_destination checks that folder_path already exists."
        ),
    )

    # Microsoft Graph API configuration
    graph_api_version: str = Field("v1.0", description="Microsoft Graph API version to use (v1.0 or beta)")

    @field_validator("client_id", "client_secret", "tenant_id", "drive_id")
    @classmethod
    def validate_not_empty(cls, v: str, info) -> str:
        """Ensure required fields are not blank."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip()

    @field_validator("graph_api_version")
    @classmethod
    def validate_api_version(cls, v: str) -> str:
        """Validate Graph API version."""
        allowed = ["v1.0", "beta"]
        if v not in allowed:
            raise ValueError(f"graph_api_version must be one of {allowed}")
        return v

    @field_validator("folder_path")
    @classmethod
    def normalise_folder_path(cls, v: str) -> str:
        """Strip trailing slash; ensure leading slash when non-empty."""
        v = v.strip().rstrip("/")
        if v and not v.startswith("/"):
            v = "/" + v
        return v

    class Config:
        json_schema_extra: ClassVar[dict] = {
            "example": {
                "client_id": "${SHAREPOINT_CLIENT_ID}",
                "client_secret": "${SHAREPOINT_CLIENT_SECRET}",  # pragma: allowlist secret
                "tenant_id": "${SHAREPOINT_TENANT_ID}",
                "drive_id": "b!abc123...",
                "folder_path": "/Processed Documents",
                "create_dirs": True,
                "graph_api_version": "v1.0",
            }
        }
