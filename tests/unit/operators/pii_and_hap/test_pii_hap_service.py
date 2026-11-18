# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for PIIHAPService - independent PII/HAP port injection and composition."""

from unittest.mock import MagicMock

import pytest

from docpipe.core.constants.constants import LLMConstants
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionResult,
    PIIHAPDetectionResponse,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.core.operators.quality.pii_and_hap.services.pii_hap_service import PIIHAPService
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_VALID = {
    LLMConstants.ValidationKeys.VALID: True,
    LLMConstants.ValidationKeys.ERRORS: [],
    LLMConstants.ValidationKeys.WARNINGS: [],
}

_PII_DETECTION = DetectionResult(detection="EmailAddress", detection_type="pii", score=0.9, start=0, end=16)
_HAP_DETECTION = DetectionResult(detection="has_HAP", detection_type="hap", score=0.95, start=0, end=16)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(spec: type) -> MagicMock:
    """Return a mock adapter implementing ``spec`` that passes validation."""
    mock = MagicMock(spec=spec)
    mock.validate.return_value = dict(_VALID)
    if issubclass(spec, PIIDetectionPort):
        mock.detect_pii.return_value = PIIHAPDetectionResponse(detections=[_PII_DETECTION])
    if issubclass(spec, HAPDetectionPort):
        mock.detect_hap.return_value = PIIHAPDetectionResponse(detections=[_HAP_DETECTION])
    if issubclass(spec, PIIAndHAPDetectionPort):
        mock.detect.return_value = PIIHAPDetectionResponse(detections=[_PII_DETECTION, _HAP_DETECTION])
    return mock


def _payload(*, pii: float | None = None, hap: float | None = None, text: str = "test@example.com") -> dict:
    detectors: dict = {}
    if pii is not None:
        detectors["pii"] = {"threshold": pii}
    if hap is not None:
        detectors["hap"] = {"threshold": hap}
    return {"input": text, "detectors": detectors}


# ---------------------------------------------------------------------------
# __init__ / validation
# ---------------------------------------------------------------------------


def test_init_validates_each_adapter_once():
    pii_adapter = _make_adapter(PIIDetectionPort)
    hap_adapter = _make_adapter(HAPDetectionPort)
    PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)
    pii_adapter.validate.assert_called_once()
    hap_adapter.validate.assert_called_once()


def test_init_validates_shared_adapter_only_once():
    adapter = _make_adapter(PIIAndHAPDetectionPort)
    PIIHAPService(pii_adapter=adapter, hap_adapter=adapter)
    adapter.validate.assert_called_once()


def test_init_without_adapters_is_allowed():
    service = PIIHAPService()
    assert service.pii_adapter is None
    assert service.hap_adapter is None


def test_init_logs_warnings_without_raising():
    adapter = _make_adapter(PIIDetectionPort)
    adapter.validate.return_value = {**_VALID, LLMConstants.ValidationKeys.WARNINGS: ["Missing optional field"]}
    service = PIIHAPService(pii_adapter=adapter)
    assert service.pii_adapter is adapter


def test_init_raises_docpipe_exception_when_validation_fails():
    adapter = _make_adapter(HAPDetectionPort)
    adapter.validate.return_value = {
        LLMConstants.ValidationKeys.VALID: False,
        LLMConstants.ValidationKeys.ERRORS: ["bad api key"],
        LLMConstants.ValidationKeys.WARNINGS: [],
    }
    with pytest.raises(DocpipeException, match="Adapter validation failed: bad api key"):
        PIIHAPService(hap_adapter=adapter)


def test_init_rejects_pii_only_adapter_in_hap_role():
    pii_only = _make_adapter(PIIDetectionPort)
    with pytest.raises(DocpipeException, match="hap_adapter must implement HAPDetectionPort"):
        PIIHAPService(hap_adapter=pii_only)  # type: ignore[arg-type]


def test_init_rejects_hap_only_adapter_in_pii_role():
    hap_only = _make_adapter(HAPDetectionPort)
    with pytest.raises(DocpipeException, match="pii_adapter must implement PIIDetectionPort"):
        PIIHAPService(pii_adapter=hap_only)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# detect_pii_hap() - input guards
# ---------------------------------------------------------------------------


def test_detect_raises_on_empty_input():
    service = PIIHAPService(pii_adapter=_make_adapter(PIIDetectionPort))
    with pytest.raises(ValueError, match="Input text cannot be empty"):
        service.detect_pii_hap(payload={"input": "", "detectors": {"pii": {}}})


def test_detect_raises_on_missing_input():
    service = PIIHAPService(pii_adapter=_make_adapter(PIIDetectionPort))
    with pytest.raises(ValueError, match="Input text cannot be empty"):
        service.detect_pii_hap(payload={})


def test_detect_raises_when_requested_capability_has_no_adapter():
    service = PIIHAPService(pii_adapter=_make_adapter(PIIDetectionPort))
    with pytest.raises(ValueError, match="HAP detection was requested but no HAP provider is configured"):
        service.detect_pii_hap(payload=_payload(hap=0.8))


def test_detect_with_no_detectors_returns_empty_and_calls_nothing():
    pii_adapter = _make_adapter(PIIDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter)
    response = service.detect_pii_hap(payload=_payload())
    assert response.detections == []
    pii_adapter.detect_pii.assert_not_called()


# ---------------------------------------------------------------------------
# detect_pii_hap() - conditional invocation and composition
# ---------------------------------------------------------------------------


def test_pii_only_request_does_not_call_hap_adapter():
    pii_adapter = _make_adapter(PIIDetectionPort)
    hap_adapter = _make_adapter(HAPDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)

    response = service.detect_pii_hap(payload=_payload(pii=0.6))

    pii_adapter.detect_pii.assert_called_once_with(text="test@example.com", threshold=0.6)
    hap_adapter.detect_hap.assert_not_called()
    assert response.detections == [_PII_DETECTION]


def test_hap_only_request_does_not_call_pii_adapter():
    pii_adapter = _make_adapter(PIIDetectionPort)
    hap_adapter = _make_adapter(HAPDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)

    response = service.detect_pii_hap(payload=_payload(hap=0.7))

    hap_adapter.detect_hap.assert_called_once_with(text="test@example.com", threshold=0.7)
    pii_adapter.detect_pii.assert_not_called()
    assert response.detections == [_HAP_DETECTION]


def test_independent_adapters_results_are_composed_pii_first():
    pii_adapter = _make_adapter(PIIDetectionPort)
    hap_adapter = _make_adapter(HAPDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)

    response = service.detect_pii_hap(payload=_payload(pii=0.5, hap=0.8))

    assert response.detections == [_PII_DETECTION, _HAP_DETECTION]
    assert response.input_text == "test@example.com"


def test_shared_dual_capability_adapter_uses_single_combined_call():
    adapter = _make_adapter(PIIAndHAPDetectionPort)
    service = PIIHAPService(pii_adapter=adapter, hap_adapter=adapter)
    payload = _payload(pii=0.5, hap=0.8)

    response = service.detect_pii_hap(payload=payload)

    adapter.detect.assert_called_once_with(payload=payload)
    adapter.detect_pii.assert_not_called()
    adapter.detect_hap.assert_not_called()
    assert len(response.detections) == 2


def test_distinct_dual_capability_adapters_use_scoped_calls():
    pii_adapter = _make_adapter(PIIAndHAPDetectionPort)
    hap_adapter = _make_adapter(PIIAndHAPDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)

    service.detect_pii_hap(payload=_payload(pii=0.5, hap=0.8))

    pii_adapter.detect_pii.assert_called_once()
    hap_adapter.detect_hap.assert_called_once()
    pii_adapter.detect.assert_not_called()
    hap_adapter.detect.assert_not_called()


def test_default_thresholds_used_when_missing():
    pii_adapter = _make_adapter(PIIDetectionPort)
    hap_adapter = _make_adapter(HAPDetectionPort)
    service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)

    service.detect_pii_hap(payload={"input": "text", "detectors": {"pii": {}, "hap": {}}})

    assert pii_adapter.detect_pii.call_args.kwargs["threshold"] == 0.5
    assert hap_adapter.detect_hap.call_args.kwargs["threshold"] == 0.8


# ---------------------------------------------------------------------------
# detect_pii_hap() - error handling
# ---------------------------------------------------------------------------


def test_detect_re_raises_docpipe_exception():
    adapter = _make_adapter(PIIDetectionPort)
    adapter.detect_pii.side_effect = DocpipeException(message="provider error", status_code=500)
    service = PIIHAPService(pii_adapter=adapter)
    with pytest.raises(DocpipeException, match="provider error"):
        service.detect_pii_hap(payload=_payload(pii=0.5))


def test_detect_wraps_unexpected_exception():
    adapter = _make_adapter(HAPDetectionPort)
    adapter.detect_hap.side_effect = RuntimeError("invalid")
    service = PIIHAPService(hap_adapter=adapter)
    with pytest.raises(DocpipeException, match="PII/HAP detection failed"):
        service.detect_pii_hap(payload=_payload(hap=0.8))


# ---------------------------------------------------------------------------
# cleanup()
# ---------------------------------------------------------------------------


def test_cleanup_is_noop():
    PIIHAPService().cleanup()  # should not raise
