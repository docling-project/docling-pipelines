# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the capability-scoped PII/HAP ports and detection classification helpers."""

from typing import Any

import pytest
from pydantic import BaseModel

from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionCapability,
    DetectionResult,
    PIIHAPDetectionResponse,
    ProviderSelection,
    filter_detections_by_capability,
    get_detection_capability,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort

_EMAIL = DetectionResult(detection="EmailAddress", detection_type="pii", score=0.9, start=0, end=5)
_HAP = DetectionResult(detection="has_HAP", detection_type="hap", score=0.9, start=6, end=10)
_UNTYPED_HAP = DetectionResult(detection="has_HAP", detection_type="", score=0.9, start=6, end=10)
_UNTYPED_PII = DetectionResult(detection="PhoneNumber", detection_type="", score=0.9, start=0, end=5)


class _RecordingCombinedAdapter(PIIAndHAPDetectionPort):
    """Dual-capability adapter that records payloads and returns PII + HAP detections."""

    ADAPTER_NAME = "recording"
    ADAPTER_DISPLAY_NAME = "Recording"

    def __init__(self) -> None:
        super().__init__(model_id="m", provider_config={})
        self.payloads: list[dict[str, Any]] = []

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        return BaseModel

    def validate(self) -> dict[str, Any]:
        return {"valid": True, "errors": [], "warnings": []}

    def detect(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        self.payloads.append(payload)
        return PIIHAPDetectionResponse(detections=[_EMAIL, _HAP], input_text=payload["input"])


# ---------------------------------------------------------------------------
# Port hierarchy and capability flags
# ---------------------------------------------------------------------------


def test_scoped_ports_share_common_base():
    assert issubclass(PIIDetectionPort, DetectionAdapterPort)
    assert issubclass(HAPDetectionPort, DetectionAdapterPort)


def test_combined_port_inherits_both_scoped_ports():
    assert issubclass(PIIAndHAPDetectionPort, PIIDetectionPort)
    assert issubclass(PIIAndHAPDetectionPort, HAPDetectionPort)
    assert PIIAndHAPDetectionPort.SUPPORTS_PII is True
    assert PIIAndHAPDetectionPort.SUPPORTS_HAP is True


def test_base_port_declares_no_capability_by_default():
    assert DetectionAdapterPort.SUPPORTS_PII is False
    assert DetectionAdapterPort.SUPPORTS_HAP is False
    assert DetectionAdapterPort.REQUIRES_MODEL_ID is True


def test_scoped_ports_expose_only_their_detection_method():
    assert "detect_pii" in PIIDetectionPort.__abstractmethods__
    assert "detect_hap" not in PIIDetectionPort.__abstractmethods__
    assert "detect_hap" in HAPDetectionPort.__abstractmethods__
    assert "detect_pii" not in HAPDetectionPort.__abstractmethods__


def test_get_capabilities_reflects_flags():
    assert _RecordingCombinedAdapter.get_capabilities() == ["pii", "hap"]


# ---------------------------------------------------------------------------
# Combined port: scoped detection derived from detect()
# ---------------------------------------------------------------------------


def test_combined_detect_pii_requests_only_pii_detector_and_filters_hap():
    adapter = _RecordingCombinedAdapter()
    response = adapter.detect_pii(text="hello world", threshold=0.4)
    assert adapter.payloads == [{"input": "hello world", "detectors": {"pii": {"threshold": 0.4}}}]
    assert response.detections == [_EMAIL]
    assert response.input_text == "hello world"


def test_combined_detect_hap_requests_only_hap_detector_and_filters_pii():
    adapter = _RecordingCombinedAdapter()
    response = adapter.detect_hap(text="hello world", threshold=0.9)
    assert adapter.payloads == [{"input": "hello world", "detectors": {"hap": {"threshold": 0.9}}}]
    assert response.detections == [_HAP]


# ---------------------------------------------------------------------------
# validate_provider_config() default implementation
# ---------------------------------------------------------------------------


def test_validate_provider_config_requires_config_when_model_id_required():
    errors = _RecordingCombinedAdapter.validate_provider_config(provider_config={}, config_key="pii_provider_config")
    assert errors == ["pii_provider_config is required for provider 'recording'"]


def test_validate_provider_config_requires_model_id():
    errors = _RecordingCombinedAdapter.validate_provider_config(
        provider_config={"api_key": "x"},  # pragma: allowlist secret
        config_key="provider_config",
    )
    assert errors == ["provider_config.model_id is required and must be a non-empty string"]


def test_validate_provider_config_passes_with_model_id():
    assert _RecordingCombinedAdapter.validate_provider_config(provider_config={"model_id": "m"}, config_key="c") == []


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("detection", "expected"),
    [
        (_EMAIL, DetectionCapability.PII),
        (_HAP, DetectionCapability.HAP),
        (_UNTYPED_HAP, DetectionCapability.HAP),
        (_UNTYPED_PII, DetectionCapability.PII),
        (DetectionResult(detection="x", detection_type="HAP", score=1, start=0, end=1), DetectionCapability.HAP),
    ],
)
def test_get_detection_capability(detection, expected):
    assert get_detection_capability(detection) == expected


def test_filter_detections_by_capability():
    detections = [_EMAIL, _HAP, _UNTYPED_PII, _UNTYPED_HAP]
    assert filter_detections_by_capability(detections=detections, capability=DetectionCapability.PII) == [
        _EMAIL,
        _UNTYPED_PII,
    ]
    assert filter_detections_by_capability(detections=detections, capability=DetectionCapability.HAP) == [
        _HAP,
        _UNTYPED_HAP,
    ]


def test_provider_selection_model_id():
    assert ProviderSelection(provider="litellm", provider_config={"model_id": "m"}).model_id == "m"
    assert ProviderSelection(provider="presidio").model_id == ""
    assert ProviderSelection(provider="x", provider_config={"model_id": 5}).model_id == ""
