# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Configuration model for the Box destination adapter."""

import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class BoxDestinationConfig(BaseModel):
    """Type-safe configuration for the Box destination adapter.

    Uses Box JWT / App Authentication (same mechanism as the Box ingest adapter)
    to write documents to a Box folder via the box-sdk-gen library.

    Example flow config::

        destination_config:
          provider: box
          provider_config:
            folder_id: "${BOX_FOLDER_ID}"
            create_dirs: true
          credentials:
            credentials_json_path: "${BOX_CONFIG_PATH}"
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("credentials_path",)

    # Box JWT / App Authentication
    credentials_path: str = Field(
        ...,
        description=(
            "Path to Box JWT / App config JSON file. Supports environment variable references ($VAR or ${VAR}) and ~/."
        ),
    )

    # Box destination configuration
    folder_id: str = Field(
        "0",
        description=(
            "ID of the target Box folder to write files into. "
            "'0' refers to the authenticated user's root 'All Files' folder."
        ),
    )
    create_dirs: bool = Field(
        True,
        description=(
            "When True (default), intermediate sub-folders are created automatically on upload. "
            "When False, validate_destination checks that folder_id is accessible and "
            "write_document raises FileNotFoundError if a sub-folder is missing."
        ),
    )

    @field_validator("credentials_path")
    @classmethod
    def expand_credentials_path(cls, v: str) -> str:
        """Expand environment variables and user home directory in the credentials path."""
        resolved = os.path.expandvars(v)
        return str(Path(resolved).expanduser())

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, v: str) -> str:
        """Ensure folder_id is not blank."""
        if not v or not v.strip():
            raise ValueError("folder_id cannot be empty")
        return v.strip()

    class Config:
        json_schema_extra: ClassVar[dict] = {
            "example": {
                "credentials_path": "${BOX_CONFIG_PATH}",
                "folder_id": "123456789",
                "create_dirs": True,
            }
        }
