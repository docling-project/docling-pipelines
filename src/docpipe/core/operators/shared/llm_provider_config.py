"""Shared Pydantic config models for LLM-based providers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docpipe.core.constants.constants import ServiceConstants


class LLMProviderConfig(BaseModel):
    """User-facing provider_config for LiteLLM-backed providers.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``litellm`` provider in EmbeddingsOperator or
    DocumentClassifierOperator.
    """

    model_config = ConfigDict(extra="allow")

    model_id: str | None = Field(
        default=None,
        description="Model identifier in LiteLLM format (e.g., 'openai/text-embedding-3-small', 'ollama/llama3.2').",
    )
    api_base: str | None = Field(
        default=None,
        description="Custom API endpoint URL (e.g., 'http://localhost:11434/v1').",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authentication. Supports $ENV_VAR references.",
    )


class WatsonxProviderConfig(LLMProviderConfig):
    """User-facing provider_config for IBM watsonx-backed providers.

    Extends LLMProviderConfig with watsonx-specific fields. Used when selecting
    the ``watsonx`` provider in EmbeddingsOperator or DocumentClassifierOperator.
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = Field(
        default=None,
        description="Watsonx.ai API endpoint URL. Accepts either 'url' or 'api_base'.",
    )
    container_kind: Literal["project", "space"] = Field(
        default="project",
        description="Container type: 'project' or 'space'.",
    )
    container_id: str | None = Field(
        default=None,
        description="Container ID (project_id or space_id). Can be set via WATSONX_CONTAINER_ID env var.",
    )


class LLMEmbeddingProviderConfig(LLMProviderConfig):
    """User-facing provider_config for the ``litellm`` provider of EmbeddingsOperator.

    Extends LLMProviderConfig with the request-shaping options that only embedding
    adapters honour, so they are not offered by operators that use the base schema
    for inference (e.g. ChunkerOperator, DocumentClassifierOperator).
    """

    batch_size: int = Field(
        default=ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
        ge=1,
        description="Texts per embedding request; texts from several documents are packed into the same request.",
    )
    max_concurrent_requests: int = Field(
        default=ServiceConstants.DEFAULT_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
        ge=1,
        description=(
            "Embedding requests kept in flight at once. Lower it if the provider returns rate-limit (HTTP 429) errors."
        ),
    )


class WatsonxEmbeddingProviderConfig(WatsonxProviderConfig):
    """User-facing provider_config for the ``watsonx`` provider of EmbeddingsOperator.

    Extends WatsonxProviderConfig with the request-shaping options that only the
    watsonx embedding adapter honours.
    """

    batch_size: int = Field(
        default=ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_BATCH_SIZE,
        ge=1,
        description="Texts per embedding request; texts from several documents are packed into the same request.",
    )
    max_concurrent_requests: int = Field(
        default=ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
        ge=1,
        description="Embedding requests kept in flight at once (watsonx.ai allows 8 requests per second per instance).",
    )
