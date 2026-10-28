# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the WatsonX PII/HAP detection adapter."""

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "watsonx"


class WatsonxPIIAndHAPConfig(BaseModel):
    """User-facing provider_config for the WatsonX PII/HAP detection adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``watsonx`` provider in the ``pii_and_hap`` operator node.
    """

    model_config = ConfigDict(extra="ignore")

    model_id: str | None = Field(
        default=None,
        description="WatsonX model identifier (e.g. 'ibm/granite-guardian-3-8b').",
    )
    api_key: str | None = Field(
        default=None,
        description="WatsonX API key. Supports $ENV_VAR references.",
    )
    url: str | None = Field(
        default=None,
        description="WatsonX API endpoint URL.",
    )
    container_kind: str = Field(
        default="project",
        description="Container type: 'project' or 'space'.",
    )
    container_id: str | None = Field(
        default=None,
        description="Project ID or space ID.",
    )
    timeout: int = Field(
        default=300,
        description="Request timeout in seconds.",
    )
