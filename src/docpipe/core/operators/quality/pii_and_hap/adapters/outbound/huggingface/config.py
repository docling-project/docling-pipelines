# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the Hugging Face HAP detection adapter.

This is the single place where Hugging Face HAP defaults are resolved.  Choosing a
default HAP classifier is HAP policy, owned by the ``pii_and_hap`` operator; the core
``LLMAdapterFactory`` and ``HuggingFaceAdapter`` receive explicit values only.

Unknown keys are rejected (``extra="forbid"``): a silently dropped misspelling of
``local_files_only`` or ``revision`` would change behavior without notice.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docpipe.core.constants.constants import ProviderConstants, ServiceConstants
from docpipe.core.constants.operator_constants import OperatorConstants

ADAPTER_NAME = ProviderConstants.HUGGINGFACE


class HuggingFaceHAPConfig(BaseModel):
    """User-facing ``hap_provider_config`` for the Hugging Face HAP detection adapter.

    Runs a local Hugging Face sequence-classification model (no API key).  With an
    empty config, the default model is used at a pinned revision with its toxic label.
    Any other model must name its toxic labels in ``toxic_labels``.

    ``revision`` and ``toxic_labels`` default to ``None`` because their defaults apply
    to the default model only; ``resolve_model_defaults`` fills them in.  Static field
    defaults would be wrong for any other model, and the properties panel persists
    schema defaults into the flow.

    ``activation`` and ``device`` use ``Literal`` types, which cannot reference
    constants; tests check them against ``ServiceConstants.HUGGINGFACE_ACTIVATIONS``
    and ``ServiceConstants.HUGGINGFACE_DEVICES``.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(
        default=ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID,
        description=(
            "Hugging Face sequence-classification model used for HAP detection. Must ship a fast "
            "tokenizer (tokenizer.json) and need no custom code. The default model is English-only."
        ),
    )
    revision: str | None = Field(
        default=None,
        description=(
            "Model commit, tag or branch. The default model is pinned to a tested commit; other models "
            "use the Hub's default branch unless set. Pin a commit for reproducible scores."
        ),
    )
    toxic_labels: list[str] | None = Field(
        default=None,
        description=(
            "Class labels whose highest probability is a span's HAP score. Required for any model other "
            f"than the default (which uses {list(ServiceConstants.DEFAULT_HUGGINGFACE_HAP_TOXIC_LABELS)}). "
            f"{ServiceConstants.HUGGINGFACE_HAP_TOXIC_LABELS_HINT}"
        ),
    )
    activation: Literal["softmax", "sigmoid", "auto"] = Field(
        default=ServiceConstants.HUGGINGFACE_ACTIVATION_AUTO,
        description="How logits become probabilities. 'auto' uses sigmoid for multi-label models, else softmax.",
    )
    max_length: int = Field(
        default=ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MAX_LENGTH,
        ge=1,
        strict=True,
        description="Maximum model tokens per scored window; longer sentences are scored in windows.",
    )
    batch_size: int = Field(
        default=ServiceConstants.DEFAULT_HUGGINGFACE_HAP_BATCH_SIZE,
        ge=1,
        strict=True,
        description="Number of sentence windows scored per forward pass.",
    )
    device: Literal["auto", "cpu", "cuda", "mps"] | None = Field(
        default=None,
        description="Inference device. Empty or 'auto' uses CUDA when available, else CPU.",
    )
    local_files_only: bool = Field(
        default=False,
        description=(
            "Load the model only from the local Hugging Face cache (no network). "
            "Pre-fetch it with 'huggingface-cli download <model_id>'."
        ),
    )

    @field_validator(OperatorConstants.Config.MODEL_ID, mode="before")
    @classmethod
    def validate_model_id(cls, value: object) -> object:
        """Treat an empty or blank ``model_id`` as "use the default model"."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID
        return value

    @model_validator(mode="after")
    def resolve_model_defaults(self) -> "HuggingFaceHAPConfig":
        """Apply the pinned revision and default labels to the default model only.

        Raises:
            ValueError: If a non-default model has no ``toxic_labels``.
        """
        if self.model_id == ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID:
            if self.revision is None:
                self.revision = ServiceConstants.DEFAULT_HUGGINGFACE_HAP_REVISION
            if not self.toxic_labels:
                self.toxic_labels = list(ServiceConstants.DEFAULT_HUGGINGFACE_HAP_TOXIC_LABELS)
        elif not self.toxic_labels:
            msg = (
                f"{OperatorConstants.Config.TOXIC_LABELS} is required for model '{self.model_id}'. "
                f"{ServiceConstants.HUGGINGFACE_HAP_TOXIC_LABELS_HINT}"
            )
            raise ValueError(msg)
        return self
