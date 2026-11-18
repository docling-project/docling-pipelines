"""Outbound port interfaces for PII and HAP detection."""

from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort

__all__ = [
    "DetectionAdapterPort",
    "HAPDetectionPort",
    "PIIAndHAPDetectionPort",
    "PIIDetectionPort",
]
