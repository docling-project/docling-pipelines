# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic models for authentication."""

from pydantic import BaseModel, Field

from .roles import Role


class LoginRequest(BaseModel):
    """Login request model."""

    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")


class TokenResponse(BaseModel):
    """Token response model."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")


class User(BaseModel):
    """User model."""

    username: str = Field(..., description="Username")
    email: str = Field(default="", description="User email address")
    full_name: str = Field(default="", description="User full name")
    roles: list[Role] = Field(default_factory=lambda: [Role.VIEWER], description="Roles held by the user")
