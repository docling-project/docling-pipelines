# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the WatsonX PII/HAP detection adapter."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "watsonx"


class WatsonxPIIAndHAPConfig(BaseModel):
    """User-facing provider_config for the WatsonX PII/HAP detection adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``watsonx`` provider in the ``pii_and_hap`` operator node.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "api_key",
        "url",
    )

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
