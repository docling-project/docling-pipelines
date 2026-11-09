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


class AuthProvider(BaseModel):
    """OIDC provider entry exposed to unauthenticated callers (no ids, secrets or endpoints)."""

    name: str = Field(..., description="Provider key, for example google, azure or generic")
    display_name: str = Field(..., description="Human-readable provider name")
    authorize_url: str = Field(..., description="Relative URL that starts the login with this provider")


class AuthConfigResponse(BaseModel):
    """Public discovery of the authentication setup."""

    auth_enabled: bool = Field(..., description="Whether the API requires a session")
    credential_login: bool = Field(..., description="Whether username and password login is available")
    providers: list[AuthProvider] = Field(default_factory=list, description="Configured OIDC providers")


class User(BaseModel):
    """User model."""

    username: str = Field(..., description="Username")
    email: str = Field(default="", description="User email address")
    full_name: str = Field(default="", description="User full name")
    roles: list[Role] = Field(default_factory=lambda: [Role.VIEWER], description="Roles held by the user")


class LoginResponse(TokenResponse):
    """Login response: the token for script clients plus the authenticated user."""

    user: User = Field(..., description="Authenticated user, including roles")
