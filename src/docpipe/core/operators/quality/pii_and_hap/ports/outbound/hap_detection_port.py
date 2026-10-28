# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port interface for HAP (Hate, Abuse and Profanity) detection adapters."""

from abc import abstractmethod

from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort


class HAPDetectionPort(DetectionAdapterPort):
    """Contract for adapters that detect Hate, Abuse and Profanity content.

    Implementations must set ``SUPPORTS_HAP = True``.  HAP-only providers (for
    example Detoxify or Perspective) implement this port alone; multi-capable
    providers implement it together with ``PIIDetectionPort``.
    """

    @abstractmethod
    def detect_hap(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect HAP content in ``text``.

        The caller (``PIIHAPService``) guarantees ``text`` is a non-empty string.

        Args:
            text: Text to analyse.
            threshold: Minimum confidence score (0.0 - 1.0) for a detection to be reported.

        Returns:
            Response whose detections all have ``detection_type == 'hap'`` and a
            ``detection`` label containing ``'HAP'`` (conventionally ``'has_HAP'``).

        Raises:
            DocpipeException: If detection fails at the provider level.
        """
        ...
