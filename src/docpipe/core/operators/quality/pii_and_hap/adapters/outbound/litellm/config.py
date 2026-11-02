# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the LiteLLM PII/HAP detection adapter."""

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "litellm"


class LiteLLMPIIAndHAPConfig(BaseModel):
    """User-facing provider_config for the LiteLLM PII/HAP detection adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``litellm`` provider in the ``pii_and_hap`` operator node.
    Ollama can be accessed via this provider using ``api_base='http://localhost:11434/v1'``.
    """

    model_config = ConfigDict(extra="ignore")

    model_id: str | None = Field(
        default=None,
        description="Model identifier in LiteLLM format (e.g. 'openai/granite4', 'ollama/llama3.2').",
    )
    api_base: str | None = Field(
        default=None,
        description="Custom API endpoint URL (e.g. 'http://localhost:11434/v1').",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authentication. Supports $ENV_VAR references.",
    )
