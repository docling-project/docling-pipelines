# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the OpenSearch vector store adapter."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "opensearch"


class OpenSearchConfig(BaseModel):
    """User-facing configuration for the OpenSearch vector store adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``opensearch`` provider in a VectorDB operator node.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "host",
        "username",
        "password",
        "jwt_token",
        "aws_region",
    )

    model_config = ConfigDict(extra="ignore")

    index_name: str = Field(
        description="Name of the OpenSearch index to write to.",
    )
    host: str = Field(
        default="localhost",
        description="OpenSearch server hostname or IP address.",
    )
    port: int = Field(
        default=9200,
        description="OpenSearch server port.",
    )
    username: str | None = Field(
        default=None,
        description="Username for basic authentication. Supports $ENV_VAR references.",
    )
    password: str | None = Field(
        default=None,
        description="Password for basic authentication. Supports $ENV_VAR references.",
    )
    use_ssl: bool = Field(
        default=True,
        description="Whether to use an SSL/TLS connection.",
    )
    verify_certs: bool = Field(
        default=True,
        description="Whether to verify SSL certificates.",
    )
    batch_size: int = Field(
        default=100,
        description="Number of documents to index per bulk request.",
    )
    engine: Literal["faiss", "lucene", "nmslib", "jvector"] = Field(
        default="faiss",
        description="KNN engine type.",
    )
    algorithm: Literal["hnsw", "ivf"] = Field(
        default="hnsw",
        description="KNN algorithm.",
    )
    space_type: Literal["l2", "cosine", "inner_product"] = Field(
        default="l2",
        description="Vector similarity metric.",
    )
    engine_parameters: dict | None = Field(
        default=None,
        description="Engine-specific parameters passed directly to the KNN index (e.g. ef_construction, m).",
    )
    index_settings: dict | None = Field(
        default=None,
        description="Additional OpenSearch index settings merged into the index creation request.",
    )
    schema_template_path: str | None = Field(
        default=None,
        description="Optional path to a custom JSON schema template for index creation.",
    )
    aws_auth: bool = Field(
        default=False,
        description="Whether to use AWS IAM authentication.",
    )
    aws_region: str | None = Field(
        default=None,
        description="AWS region for IAM authentication (e.g. us-east-1).",
    )
    jwt_token: str | None = Field(
        default=None,
        description="JWT bearer token for authentication.",
    )
