# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config models for LLM-based entity extraction adapters."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMEntityConfig(BaseModel):
    """User-facing provider_config for the litellm entity extraction provider.

    Describes the fields the user writes inside ``entity_extraction.provider_config``
    when selecting the ``litellm`` provider in an Extract operator node.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "api_key",
        "api_base",
    )

    model_config = ConfigDict(extra="ignore")

    model_id: str | None = Field(
        default=None,
        description="LLM model identifier (e.g., 'ollama/llama3.2', 'openai/gpt-4o', 'ibm/granite-3-8b-instruct').",
    )
    api_base: str | None = Field(
        default=None,
        description="Base URL for the LLM API endpoint (e.g., 'http://localhost:11434/v1').",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authenticating with the LLM provider.",
    )
    temperature: float = Field(
        default=0,
        description="Sampling temperature for the LLM (0.0-1.0). Lower values produce more deterministic output.",
    )
    max_tokens: int = Field(
        default=2000,
        description="Maximum number of tokens to generate in the LLM response.",
    )


class WatsonxEntityConfig(LLMEntityConfig):
    """User-facing provider_config for the watsonx entity extraction provider.

    Extends LLMEntityConfig with IBM watsonx-specific fields. Describes the fields
    the user writes inside ``entity_extraction.provider_config`` when selecting the
    ``watsonx`` provider in an Extract operator node.

    Note: ``api_base`` from the parent class is not used for watsonx — use ``url``
    instead. ``temperature`` and ``max_tokens`` are read by the entity extraction
    factory, not by WatsonXAdapter directly.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "api_key",
        "api_base",
        "url",
    )

    model_config = ConfigDict(extra="ignore")

    url: str | None = Field(
        default=None,
        description="Watsonx.ai API endpoint URL (e.g., 'https://us-south.ml.cloud.ibm.com').",
    )
    container_kind: Literal["project", "space"] = Field(
        default="project",
        description="Container type: 'project' or 'space'.",
    )
    container_id: str | None = Field(
        default=None,
        description="Container ID for the watsonx project or space.",
    )
    project_id: str | None = Field(
        default=None,
        description="Watsonx project ID. Accepted alias for container_id when container_kind is 'project'.",
    )
