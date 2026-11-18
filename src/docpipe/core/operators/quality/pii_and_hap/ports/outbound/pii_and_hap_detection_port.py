# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Combined port for providers that detect both PII and HAP.

Multi-capable providers (WatsonX, LiteLLM) implement this port.  It inherits both
capability-scoped ports and derives ``detect_pii()`` / ``detect_hap()`` from a single
``detect()`` call, so the adapter only has to implement one provider call.  When the
same adapter instance serves both capabilities, ``PIIHAPService`` calls ``detect()``
once per chunk instead of making two scoped calls.
"""

from abc import abstractmethod
from typing import Any, ClassVar

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionCapability,
    PIIHAPDetectionResponse,
    filter_detections_by_capability,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort


class PIIAndHAPDetectionPort(PIIDetectionPort, HAPDetectionPort):
    """Port for adapters that natively detect PII and HAP in one provider call."""

    SUPPORTS_PII: ClassVar[bool] = True
    SUPPORTS_HAP: ClassVar[bool] = True

    @abstractmethod
    def detect(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        """Detect PII and/or HAP in the text carried by payload.

        The caller guarantees that ``payload["input"]`` is a non-empty string.
        Adapters must not duplicate that guard.

        Args:
            payload: Detection request payload containing:
                - input: Non-empty text to analyse
                - detectors: Dict keyed by ``'pii'`` / ``'hap'`` with threshold config.
                  Only the capabilities present in this dict are requested.

        Returns:
            PIIHAPDetectionResponse containing the list of detections.

        Raises:
            DocpipeException: If detection fails at the provider level.
        """
        ...

    def detect_pii(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect PII only, by scoping ``detect()`` to the PII detector."""
        return self._detect_scoped(text=text, threshold=threshold, capability=DetectionCapability.PII)

    def detect_hap(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect HAP only, by scoping ``detect()`` to the HAP detector."""
        return self._detect_scoped(text=text, threshold=threshold, capability=DetectionCapability.HAP)

    def _detect_scoped(
        self, *, text: str, threshold: float, capability: DetectionCapability
    ) -> PIIHAPDetectionResponse:
        """Run ``detect()`` with a single detector and drop detections of the other capability."""
        payload = {
            OperatorConstants.PIIHAP.INPUT_FIELD: text,
            "detectors": {capability.value: {"threshold": threshold}},
        }
        response = self.detect(payload=payload)
        return PIIHAPDetectionResponse(
            detections=filter_detections_by_capability(detections=response.detections, capability=capability),
            input_text=text,
        )
