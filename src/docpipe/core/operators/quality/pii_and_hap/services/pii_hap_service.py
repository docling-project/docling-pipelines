# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PII and HAP detection service.

Composes an optional ``PIIDetectionPort`` and an optional ``HAPDetectionPort``.
Only the capabilities requested in the payload (derived from the operator's
``expected_redactions``) are invoked.  All provider-specific logic lives in the
adapters.
"""

from typing import Any

from docpipe.core.constants.constants import LLMConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.domain.models import DetectionResult, PIIHAPDetectionResponse
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import (
    DEFAULT_HAP_THRESHOLD_VALUE,
    DEFAULT_PII_THRESHOLD_VALUE,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_DETECTORS_FIELD = "detectors"
_THRESHOLD_FIELD = "threshold"


class PIIHAPService:
    """Service for PII and HAP detection over independently injected ports.

    Each adapter is validated once at construction time so credential, dependency
    or configuration errors surface before any documents are processed.  When the
    same dual-capability adapter instance serves both PII and HAP, the service
    issues one combined ``detect()`` call instead of two scoped calls.
    """

    def __init__(
        self,
        *,
        pii_adapter: PIIDetectionPort | None = None,
        hap_adapter: HAPDetectionPort | None = None,
    ) -> None:
        """Initialise the service with pre-built adapters.

        Args:
            pii_adapter: Adapter used for PII detection, or None if PII is not needed.
            hap_adapter: Adapter used for HAP detection, or None if HAP is not needed.

        Raises:
            DocpipeException: If an adapter does not implement the port for the role it
                was injected into, or if adapter validation fails.
        """
        PIIHAPService._check_port(adapter=pii_adapter, port=PIIDetectionPort, role="pii_adapter")
        PIIHAPService._check_port(adapter=hap_adapter, port=HAPDetectionPort, role="hap_adapter")
        self._pii_adapter = pii_adapter
        self._hap_adapter = hap_adapter

        validated: list[DetectionAdapterPort] = []
        for adapter in (pii_adapter, hap_adapter):
            if adapter is None or any(adapter is seen for seen in validated):
                continue
            PIIHAPService._validate_adapter(adapter=adapter)
            validated.append(adapter)

    @property
    def pii_adapter(self) -> PIIDetectionPort | None:
        """Adapter used for PII detection (None when PII is not configured)."""
        return self._pii_adapter

    @property
    def hap_adapter(self) -> HAPDetectionPort | None:
        """Adapter used for HAP detection (None when HAP is not configured)."""
        return self._hap_adapter

    @staticmethod
    def _check_port(*, adapter: object | None, port: type[DetectionAdapterPort], role: str) -> None:
        """Raise when ``adapter`` is set but does not implement ``port``."""
        if adapter is not None and not isinstance(adapter, port):
            raise DocpipeException(
                message=f"{role} must implement {port.__name__}, got {type(adapter).__name__}",
                status_code=400,
            )

    @staticmethod
    def _validate_adapter(*, adapter: DetectionAdapterPort) -> None:
        """Run ``adapter.validate()`` and raise on errors.

        Raises:
            DocpipeException: If validation reports errors.
        """
        result = adapter.validate()

        for warning in result.get(LLMConstants.ValidationKeys.WARNINGS, []):
            logger.warning("Adapter validation warning: %s", warning)

        if not result.get(LLMConstants.ValidationKeys.VALID, True):
            errors = result.get(LLMConstants.ValidationKeys.ERRORS, ["Unknown validation error"])
            raise DocpipeException(
                message=f"Adapter validation failed: {'; '.join(errors)}",
                status_code=400,
            )

    def detect_pii_hap(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        """Detect PII and/or HAP in the text carried by payload.

        Only capabilities present in ``payload["detectors"]`` are invoked; an adapter
        is never called for a capability that was not requested.

        Args:
            payload: Detection request payload containing:
                - input: Text to analyse
                - detectors: Dict keyed by ``'pii'`` / ``'hap'`` with ``threshold`` values

        Returns:
            PIIHAPDetectionResponse with PII detections first, then HAP detections.

        Raises:
            ValueError: If the input is empty or a requested capability has no adapter.
            DocpipeException: If detection fails.
        """
        text = payload.get(OperatorConstants.PIIHAP.INPUT_FIELD, "")
        if not text:
            raise ValueError("Input text cannot be empty")

        detectors = payload.get(_DETECTORS_FIELD) or {}
        pii_settings = detectors.get(OperatorConstants.PIIHAP.PII_FIELD_NAME)
        hap_settings = detectors.get(OperatorConstants.PIIHAP.HAP_FIELD_NAME)
        pii_adapter = self._pii_adapter if pii_settings is not None else None
        hap_adapter = self._hap_adapter if hap_settings is not None else None
        if pii_settings is not None and pii_adapter is None:
            raise ValueError("PII detection was requested but no PII provider is configured")
        if hap_settings is not None and hap_adapter is None:
            raise ValueError("HAP detection was requested but no HAP provider is configured")

        try:
            if (
                pii_adapter is not None
                and pii_adapter is hap_adapter
                and isinstance(pii_adapter, PIIAndHAPDetectionPort)
            ):
                return pii_adapter.detect(payload=payload)

            detections: list[DetectionResult] = []
            if pii_adapter is not None:
                threshold = PIIHAPService._get_threshold(settings=pii_settings, default=DEFAULT_PII_THRESHOLD_VALUE)
                detections.extend(pii_adapter.detect_pii(text=text, threshold=threshold).detections)
            if hap_adapter is not None:
                threshold = PIIHAPService._get_threshold(settings=hap_settings, default=DEFAULT_HAP_THRESHOLD_VALUE)
                detections.extend(hap_adapter.detect_hap(text=text, threshold=threshold).detections)
            return PIIHAPDetectionResponse(detections=detections, input_text=text)
        except (ValueError, DocpipeException):
            raise
        except Exception as exc:
            logger.error("Error during PII/HAP detection: %s", exc)
            raise DocpipeException(message=f"PII/HAP detection failed: {exc!s}", status_code=500) from exc

    @staticmethod
    def _get_threshold(*, settings: Any, default: float) -> float:
        """Read ``threshold`` from a detector settings dict, falling back to ``default``."""
        if isinstance(settings, dict) and settings.get(_THRESHOLD_FIELD) is not None:
            return float(settings[_THRESHOLD_FIELD])
        return default

    def cleanup(self) -> None:
        """Cleanup resources.  No-op; adapters manage their own lifecycle."""
