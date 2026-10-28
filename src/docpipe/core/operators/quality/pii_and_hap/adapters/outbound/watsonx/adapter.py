# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""WatsonX adapter for PII and HAP detection."""

from typing import Any

from pydantic import BaseModel

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import LLMConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    register_pii_and_hap_detection_adapter,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.config import (
    ADAPTER_NAME,
    WatsonxPIIAndHAPConfig,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    PIIHAPDetectionResponse,
    convert_detection_dicts_to_results,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_pii_and_hap_detection_adapter
class WatsonxPIIAndHAPAdapter(PIIAndHAPDetectionPort):
    """PII/HAP detection adapter backed by the WatsonX specialised detection API.

    Uses ``TextDetectionPort`` (``/ml/v1/text/detection``) for native PII and HAP
    detection - no prompt engineering required.  Dual-capability: implements both
    ``PIIDetectionPort`` and ``HAPDetectionPort`` through ``PIIAndHAPDetectionPort``.
    """

    ADAPTER_NAME = ADAPTER_NAME
    ADAPTER_DISPLAY_NAME = "WatsonX"
    SUPPORTS_PII = True
    SUPPORTS_HAP = True

    _REQUIRED_CONFIG_KEYS = ("api_key", "url", "container_kind", "container_id")

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        """Initialise the WatsonX PII/HAP adapter.

        Args:
            model_id: WatsonX model identifier.
            provider_config: Provider-specific config (api_key, url, container_kind, container_id, timeout).
        """
        super().__init__(model_id=model_id, provider_config=provider_config)
        self._adapter = LLMAdapterFactory.create_text_detection_adapter(
            provider="watsonx",
            model_id=model_id,
            provider_config=provider_config,
        )
        logger.info("Initialised WatsonxPIIAndHAPAdapter")

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return WatsonxPIIAndHAPConfig

    @classmethod
    def validate_provider_config(cls, *, provider_config: dict[str, Any], config_key: str) -> list[str]:
        """Check ``model_id`` plus the WatsonX credential keys without instantiating the adapter."""
        errors = super().validate_provider_config(provider_config=provider_config, config_key=config_key)
        if not provider_config:
            return errors
        missing_keys = [key for key in cls._REQUIRED_CONFIG_KEYS if key not in provider_config]
        if missing_keys:
            errors.append(
                f"WatsonX provider requires {', '.join(cls._REQUIRED_CONFIG_KEYS)} in {config_key}. "
                f"Missing: {', '.join(missing_keys)}"
            )
        return errors

    def validate(self) -> dict[str, Any]:
        """Validate WatsonX credentials and configuration.

        Returns:
            Validation result dict with ``valid``, ``errors``, and ``warnings`` keys.
        """
        missing = [k for k in self._REQUIRED_CONFIG_KEYS if not self._provider_config.get(k)]
        if missing:
            return {
                LLMConstants.ValidationKeys.VALID: False,
                LLMConstants.ValidationKeys.ERRORS: [
                    f"WatsonX provider_config is missing required keys: {', '.join(missing)}"
                ],
                LLMConstants.ValidationKeys.WARNINGS: [],
            }
        return self._adapter.validate()

    def detect(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        """Detect PII/HAP using the WatsonX native text detection API.

        Args:
            payload: Dict with ``input`` (str) and ``detectors`` (dict).
                ``input`` is guaranteed non-empty by the calling service.

        Returns:
            PIIHAPDetectionResponse with all detected items.

        Raises:
            DocpipeException: If the WatsonX API call fails.
        """
        text = payload.get(OperatorConstants.PIIHAP.INPUT_FIELD, "")
        detectors = payload.get("detectors")
        result_dict = self._adapter.detect(text=text, detectors=detectors)

        if not result_dict.get("success", False):
            error_msg = result_dict.get("error", "Unknown error")
            raise DocpipeException(message=f"Text detection failed: {error_msg}", status_code=500)

        detection_results = convert_detection_dicts_to_results(result_dict.get("detections", []))
        return PIIHAPDetectionResponse(detections=detection_results, input_text=text)
