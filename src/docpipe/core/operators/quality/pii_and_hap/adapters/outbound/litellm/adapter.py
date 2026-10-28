# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""LiteLLM adapter for PII and HAP detection."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    register_pii_and_hap_detection_adapter,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.litellm.config import (
    ADAPTER_NAME,
    LiteLLMPIIAndHAPConfig,
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
from docpipe.utils.llm import PromptManager, parse_llm_json_response

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "pii_prompt_examples.json"


@register_pii_and_hap_detection_adapter
class LiteLLMPIIAndHAPAdapter(PIIAndHAPDetectionPort):
    """PII/HAP detection adapter backed by any LiteLLM-compatible inference endpoint.

    Uses prompt-based detection via ``LLMInferencePort.chat()``, supporting
    Ollama, OpenAI-compatible APIs, and any other LiteLLM provider.  Dual-capability:
    implements both ``PIIDetectionPort`` and ``HAPDetectionPort`` through
    ``PIIAndHAPDetectionPort``.
    """

    ADAPTER_NAME = ADAPTER_NAME
    ADAPTER_DISPLAY_NAME = "LiteLLM"
    SUPPORTS_PII = True
    SUPPORTS_HAP = True

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        """Initialise the LiteLLM PII/HAP adapter.

        Args:
            model_id: Model identifier in LiteLLM format (e.g. 'openai/granite4').
            provider_config: Provider-specific config (api_base, api_key, etc.).
        """
        super().__init__(model_id=model_id, provider_config=provider_config)
        self._adapter = LLMAdapterFactory.create_inference_adapter(
            provider="litellm",
            model_id=model_id,
            provider_config=provider_config,
        )
        self._prompt_manager = PromptManager(_PROMPT_PATH)
        logger.info("Initialised LiteLLMPIIAndHAPAdapter")

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return LiteLLMPIIAndHAPConfig

    def validate(self) -> dict[str, Any]:
        """Validate LiteLLM adapter configuration.

        Returns:
            Validation result dict with ``valid``, ``errors``, and ``warnings`` keys.
        """
        return self._adapter.validate()

    def detect(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        """Detect PII/HAP using prompt-based LLM inference.

        Args:
            payload: Dict with ``input`` (str) and ``detectors`` (dict).
                ``input`` is guaranteed non-empty by the calling service.

        Returns:
            PIIHAPDetectionResponse with all detected items.

        Raises:
            DocpipeException: If LLM inference fails.
        """
        text = payload.get(OperatorConstants.PIIHAP.INPUT_FIELD, "")
        detectors = payload.get("detectors", {})
        hap_threshold = detectors.get("hap", {}).get("threshold", 0.8)
        pii_threshold = detectors.get("pii", {}).get("threshold", 0.5)

        static_prompt = self._prompt_manager.load_prompt()
        dynamic_prompt = (
            f"Now analyze the following text, applying thresholds "
            f"hap={hap_threshold} and pii={pii_threshold}:\n\n"
            f"{self._build_scope_instruction(detectors=detectors)}"
            f'"""{text}"""\n'
        )
        full_prompt = static_prompt + dynamic_prompt

        try:
            raw_response = self._adapter.chat(
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.0,
            )
        except DocpipeException:
            raise
        except Exception as exc:
            logger.error("Unexpected error during LLM inference: %s", exc)
            raise DocpipeException(
                message=f"LLM inference failed: {exc!s}",
                status_code=500,
            ) from exc

        if not raw_response or not raw_response.strip():
            return PIIHAPDetectionResponse(detections=[], input_text=text)

        result_dict = parse_llm_json_response(raw_response, log_on_error=True, log_level="debug")
        detection_results = convert_detection_dicts_to_results(result_dict.get("detections", []))
        return PIIHAPDetectionResponse(detections=detection_results, input_text=text)

    @staticmethod
    def _build_scope_instruction(*, detectors: dict[str, Any]) -> str:
        """Return a prompt line restricting output to one capability, or '' for both.

        When the service requests a single capability (e.g. only PII because HAP is
        served by another provider), the model is told not to report the other one.
        Results are additionally filtered by ``PIIAndHAPDetectionPort._detect_scoped``.
        """
        pii_key = OperatorConstants.PIIHAP.PII_FIELD_NAME
        hap_key = OperatorConstants.PIIHAP.HAP_FIELD_NAME
        if pii_key in detectors and hap_key not in detectors:
            return "Report ONLY PII detections (detection_type 'pii'); do not report HAP.\n\n"
        if hap_key in detectors and pii_key not in detectors:
            return "Report ONLY HAP detections (detection_type 'hap'); do not report PII.\n\n"
        return ""
