# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port interface for PII detection adapters."""

from abc import abstractmethod

from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort


class PIIDetectionPort(DetectionAdapterPort):
    """Contract for adapters that detect Personally Identifiable Information.

    Implementations must set ``SUPPORTS_PII = True``.  PII-only providers (for
    example Presidio) implement this port alone; multi-capable providers
    implement it together with ``HAPDetectionPort``.
    """

    @abstractmethod
    def detect_pii(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect PII in ``text``.

        The caller (``PIIHAPService``) guarantees ``text`` is a non-empty string.

        Args:
            text: Text to analyse.
            threshold: Minimum confidence score (0.0 - 1.0) for a detection to be reported.

        Returns:
            Response whose detections all have ``detection_type == 'pii'`` and a
            ``detection`` label from the operator PII vocabulary (e.g. ``'EmailAddress'``).

        Raises:
            DocpipeException: If detection fails at the provider level.
        """
        ...
