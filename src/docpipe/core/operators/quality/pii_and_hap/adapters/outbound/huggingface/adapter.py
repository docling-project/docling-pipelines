# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Hugging Face adapter for HAP detection (HAP only, runs locally).

Implements ``HAPDetectionPort`` only, so it can be selected as ``hap_provider`` but is
rejected as ``pii_provider``.  ``HuggingFaceHAPConfig`` resolves the HAP defaults; the
resolved values go to ``LLMAdapterFactory``, which builds the core ``HuggingFaceAdapter``
behind ``TextDetectionPort``.  Nothing here imports ``transformers`` or ``torch``.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import LLMConstants, ProviderConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    register_pii_and_hap_detection_adapter,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface.config import (
    ADAPTER_NAME,
    HuggingFaceHAPConfig,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    PIIHAPDetectionResponse,
    convert_detection_dicts_to_results,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.ports.text_detection_port import TextDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PIIHAP = OperatorConstants.PIIHAP
_VALIDATION = LLMConstants.ValidationKeys
# Pydantic's error type for a key outside the model (extra="forbid")
_EXTRA_FORBIDDEN = "extra_forbidden"


@register_pii_and_hap_detection_adapter
class HuggingFaceHAPAdapter(HAPDetectionPort):
    """HAP detection adapter backed by a local Hugging Face sequence classifier."""

    ADAPTER_NAME = ADAPTER_NAME
    ADAPTER_DISPLAY_NAME = "Hugging Face (HAP only)"
    SUPPORTS_PII = False
    SUPPORTS_HAP = True
    REQUIRES_MODEL_ID = False

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        """Resolve the config and build the core adapter.  No model is loaded here.

        Args:
            model_id: Ignored; the model comes from ``provider_config`` (default model when absent).
            provider_config: ``hap_provider_config`` contents, validated by ``HuggingFaceHAPConfig``.
        """
        super().__init__(model_id=model_id, provider_config=provider_config)
        self._config_errors: list[str] = []
        self._adapter: TextDetectionPort | None = None
        try:
            config = HuggingFaceHAPConfig.model_validate(provider_config or {})
        except ValidationError as exc:
            # Unknown keys are reported here too: flows can run with flow validation disabled.
            problems = HuggingFaceHAPAdapter._unknown_key_errors(error=exc)
            problems.extend(HuggingFaceHAPAdapter._value_errors(error=exc))
            self._config_errors.append(f"Provider config for '{ADAPTER_NAME}' is invalid: {'; '.join(problems)}")
            return
        self._adapter = LLMAdapterFactory.create_text_detection_adapter(
            provider=ProviderConstants.HUGGINGFACE,
            model_id=config.model_id,
            provider_config=config.model_dump(),
        )
        logger.info("Initialised HuggingFaceHAPAdapter (model=%s, revision=%s)", config.model_id, config.revision)

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return HuggingFaceHAPConfig

    @classmethod
    def validate_provider_config(cls, *, provider_config: dict[str, Any], config_key: str) -> list[str]:
        """Check option values and HAP defaults statically, without loading a model.

        Unknown keys are not reported here: ``validate_config_from_metadata`` reports
        them from the published schema, and the annotator covers the shared
        ``provider_config`` fallback.
        """
        try:
            HuggingFaceHAPConfig.model_validate(provider_config or {})
        except ValidationError as exc:
            problems = HuggingFaceHAPAdapter._value_errors(error=exc)
            if problems:
                return [f"{config_key} is invalid for provider '{cls.ADAPTER_NAME}': {'; '.join(problems)}"]
        return []

    def validate(self) -> dict[str, Any]:
        """Report config errors, then load the model and check its labels (fail-fast).

        Calls ``validate_detection()`` explicitly: the consolidated core adapter's
        ``validate()`` resolves to its embedding hook.

        Returns:
            Validation result dict with ``valid``, ``errors`` and ``warnings`` keys.
        """
        if self._adapter is None:
            return {
                _VALIDATION.VALID: False,
                _VALIDATION.ERRORS: list(self._config_errors),
                _VALIDATION.WARNINGS: [],
            }
        return self._adapter.validate_detection()

    def detect_hap(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect HAP sentence spans in ``text``.

        Args:
            text: Non-empty text to analyse (guaranteed by the calling service).
            threshold: Minimum span score (0.0 - 1.0) for a detection to be reported.

        Returns:
            Response with one ``has_HAP`` detection per flagged span.

        Raises:
            DocpipeException: If the config is invalid or scoring fails.  The message
                never contains document text.
        """
        if self._adapter is None:
            raise DocpipeException(message="; ".join(self._config_errors), status_code=400)
        result = self._adapter.detect(
            text=text, detectors={_PIIHAP.HAP_FIELD_NAME: {_PIIHAP.THRESHOLD_FIELD: threshold}}
        )
        if not result.get(_PIIHAP.SUCCESS_FIELD, False):
            error = result.get(_PIIHAP.ERROR_FIELD) or "Unknown error"
            raise DocpipeException(message=f"Hugging Face HAP detection failed: {error}", status_code=500)
        return PIIHAPDetectionResponse(
            detections=convert_detection_dicts_to_results(result.get(_PIIHAP.DETECTIONS_FIELD, [])),
            input_text=text,
        )

    @staticmethod
    def _unknown_key_errors(*, error: ValidationError) -> list[str]:
        """Return one message listing unknown keys and the accepted keys, if there are any."""
        unknown = sorted(str(item["loc"][0]) for item in error.errors() if item["type"] == _EXTRA_FORBIDDEN)
        if not unknown:
            return []
        return [f"unknown key(s) {unknown}; accepted keys: {sorted(HuggingFaceHAPConfig.model_fields)}"]

    @staticmethod
    def _value_errors(*, error: ValidationError) -> list[str]:
        """Return ``<field>: <message>`` for every error other than an unknown key."""
        return [
            f"{'.'.join(str(part) for part in item['loc']) or 'config'}: {item['msg']}"
            for item in error.errors()
            if item["type"] != _EXTRA_FORBIDDEN
        ]
