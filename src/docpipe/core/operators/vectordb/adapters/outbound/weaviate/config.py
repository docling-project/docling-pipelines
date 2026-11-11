# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model and error formatting for the Weaviate vector store adapter."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from docpipe.core.constants import OperatorConstants
from docpipe.core.operators.operator_utils import resolve_env_var

ADAPTER_NAME = "weaviate"

_ON_PREM = OperatorConstants.VectorDB.CONNECTION_TYPE_ON_PREM
_CLOUD = OperatorConstants.VectorDB.CONNECTION_TYPE_CLOUD

COLLECTION_NAME_REGEX = re.compile(r"^[A-Z][_0-9A-Za-z]*$")


class WeaviateConfig(BaseModel):
    """User-facing configuration for the Weaviate vector store adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``weaviate`` provider in a VectorDB operator node.
    """

    model_config = ConfigDict(extra="ignore")

    collection_name: str = Field(
        description="Name of the Weaviate collection to write to.",
    )
    connection_type: Literal["on-prem", "cloud"] = Field(
        default=_ON_PREM,
        description="Connection type: 'on-prem' for self-hosted or 'cloud' for Weaviate Cloud.",
    )
    host: str = Field(
        default="localhost",
        description="Weaviate server hostname or IP address.",
    )
    port: int = Field(
        default=8080,
        description="Weaviate HTTP REST port.",
    )
    secure: bool = Field(
        default=False,
        description="Whether to use TLS/HTTPS for the HTTP connection.",
    )
    grpc_host: str | None = Field(
        default=None,
        description="Weaviate gRPC hostname. Defaults to host if not specified.",
    )
    grpc_port: int = Field(
        default=50051,
        description="Weaviate gRPC port.",
    )
    grpc_secure: bool | None = Field(
        default=None,
        description="Whether to use TLS for the gRPC connection. Defaults to secure if not specified.",
    )
    cluster_url: str | None = Field(
        default=None,
        description="Weaviate Cloud cluster URL (e.g. https://xxx.weaviate.cloud). Required when connection_type is 'cloud'.",
    )
    auth_type: Literal["none", "api_key", "bearer_token", "client_password"] = Field(
        default="none",
        description="Authentication method.",
    )
    api_key: str | None = Field(
        default=None,
        json_schema_extra={"sensitive": True},
        description="API key for Weaviate authentication.",
    )
    bearer_token: str | None = Field(
        default=None,
        json_schema_extra={"sensitive": True},
        description="Bearer token for Weaviate authentication.",
    )
    username: str | None = Field(
        default=None,
        description="Username for client_password authentication.",
    )
    password: str | None = Field(
        default=None,
        json_schema_extra={"sensitive": True},
        description="Password for client_password authentication.",
    )
    timeout_init: int = Field(
        default=30,
        ge=1,
        description="Timeout in seconds for establishing connection to Weaviate.",
    )
    timeout_query: int = Field(
        default=60,
        ge=1,
        description="Timeout in seconds for queries to Weaviate.",
    )
    timeout_insert: int = Field(
        default=120,
        ge=1,
        description="Timeout in seconds for batch inserts to Weaviate.",
    )
    skip_init_checks: bool = Field(
        default=False,
        description="Whether to skip initial connectivity and version checks.",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="Number of documents to insert per batch.",
    )
    index_type: Literal["hnsw", "flat", "dynamic"] = Field(
        default="hnsw",
        description="Vector index type. Note: dynamic index is experimental and requires async indexing on the server.",
    )
    distance_metric: Literal["cosine", "dot", "l2-squared", "manhattan", "hamming"] = Field(
        default="cosine",
        description="Distance metric for vector search.",
    )
    index_parameters: dict = Field(
        default_factory=dict,
        description="Index-specific configuration parameters.",
    )
    add_sparse_vector: bool = Field(
        default=False,
        description="Enable BM25 sparse vector indexing.",
    )

    @field_validator("collection_name")
    @classmethod
    def _validate_collection_name(cls, v: str) -> str:
        if not COLLECTION_NAME_REGEX.match(v):
            raise ValueError(
                "collection_name must start with an uppercase ASCII letter and contain only ASCII letters, digits, and underscores"
            )
        return v

    @model_validator(mode="after")
    def _validate_cross_field(self) -> "WeaviateConfig":
        if self.connection_type == _CLOUD:
            if not self.cluster_url:
                raise ValueError("cluster_url is required when connection_type is 'cloud'")

        effective_grpc_secure = self.secure if self.grpc_secure is None else self.grpc_secure

        if self.connection_type == _ON_PREM and self.auth_type != "none":
            if not (self.secure and effective_grpc_secure):
                raise ValueError(
                    "secure and grpc_secure must both be true when auth_type is not 'none'; "
                    "credentials must not be sent over an unencrypted connection"
                )

        if self.auth_type == "api_key":
            if not self.api_key:
                raise ValueError("api_key is required when auth_type is 'api_key'")
            resolve_env_var(self.api_key)
        elif self.auth_type == "bearer_token":
            if not self.bearer_token:
                raise ValueError("bearer_token is required when auth_type is 'bearer_token'")
            resolve_env_var(self.bearer_token)
        elif self.auth_type == "client_password":
            if not self.username or not self.password:
                raise ValueError("username and password are required when auth_type is 'client_password'")
            resolve_env_var(self.username)
            resolve_env_var(self.password)

        return self


def format_config_errors(exc: ValidationError) -> list[str]:
    """Format Pydantic ValidationError into user-facing error messages without disclosing input values."""
    errors: list[str] = []
    for error in exc.errors():
        field_name = ".".join(str(loc) for loc in error["loc"])
        if error["type"] == "missing":
            errors.append(f"{field_name} is not provided")
        else:
            errors.append(error["msg"])
    return errors
