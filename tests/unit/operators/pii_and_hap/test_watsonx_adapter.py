# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WatsonxPIIAndHAPAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.adapter import WatsonxPIIAndHAPAdapter
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.config import ADAPTER_NAME
from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_DETECTION_MODULE = (
    "docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.adapter"
    ".LLMAdapterFactory.create_text_detection_adapter"
)

_FULL_CONFIG = {
    "api_key": "test-key",  # pragma: allowlist secret
    "url": "https://test.watsonx.ai",
    "container_kind": "project",
    "container_id": "test-project",
}


@pytest.fixture
def mock_text_detection_adapter():
    mock = MagicMock()
    mock.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    mock.detect.return_value = {"success": True, "detections": []}
    return mock


@pytest.fixture
def adapter(mock_text_detection_adapter):
    with patch(_DETECTION_MODULE, return_value=mock_text_detection_adapter):
        return WatsonxPIIAndHAPAdapter(model_id="ibm/granite-guardian", provider_config=_FULL_CONFIG)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_adapter_name_constant():
    assert ADAPTER_NAME == "watsonx"


def test_adapter_name_attribute():
    assert WatsonxPIIAndHAPAdapter.ADAPTER_NAME == "watsonx"


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_delegates_to_inner_adapter(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    result = adapter.validate()
    assert result["valid"] is True
    mock_text_detection_adapter.validate.assert_called_once()


def test_validate_fails_when_api_key_missing():
    with patch(_DETECTION_MODULE, return_value=MagicMock()):
        inst = WatsonxPIIAndHAPAdapter(model_id="m", provider_config={})
    result = inst.validate()
    assert result["valid"] is False
    assert any("missing required keys" in e for e in result["errors"])


def test_validate_fails_when_url_missing():
    config = {k: v for k, v in _FULL_CONFIG.items() if k != "url"}
    with patch(_DETECTION_MODULE, return_value=MagicMock()):
        inst = WatsonxPIIAndHAPAdapter(model_id="m", provider_config=config)
    result = inst.validate()
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


def test_detect_returns_response_on_success(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.detect.return_value = {
        "success": True,
        "detections": [
            {
                "detection": "EmailAddress",
                "detection_type": "pii",
                "score": 0.95,
                "start": 0,
                "end": 15,
                "text": "test@example.com",
            }
        ],
    }
    response = adapter.detect(payload={"input": "test@example.com", "detectors": {}})
    assert isinstance(response, PIIHAPDetectionResponse)
    assert len(response.detections) == 1
    assert response.detections[0].detection == "EmailAddress"


def test_detect_raises_docpipe_exception_on_api_error(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.detect.return_value = {"success": False, "error": "API failure"}
    with pytest.raises(DocpipeException, match="Text detection failed: API failure"):
        adapter.detect(payload={"input": "some text", "detectors": {}})


def test_detect_empty_detections_returns_empty_response(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.detect.return_value = {"success": True, "detections": []}
    response = adapter.detect(payload={"input": "clean text", "detectors": {}})
    assert response.detections == []
    assert response.input_text == "clean text"


# ---------------------------------------------------------------------------
# Capability-scoped detection (PIIDetectionPort / HAPDetectionPort)
# ---------------------------------------------------------------------------

_MIXED_DETECTIONS = {
    "success": True,
    "detections": [
        {"detection": "EmailAddress", "detection_type": "pii", "score": 0.9, "start": 0, "end": 16},
        {"detection": "has_HAP", "detection_type": "hap", "score": 0.9, "start": 17, "end": 30},
    ],
}


def test_adapter_declares_both_capabilities():
    assert WatsonxPIIAndHAPAdapter.SUPPORTS_PII is True
    assert WatsonxPIIAndHAPAdapter.SUPPORTS_HAP is True


def test_detect_pii_sends_only_pii_detector(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS
    response = adapter.detect_pii(text="some text", threshold=0.6)

    mock_text_detection_adapter.detect.assert_called_once_with(text="some text", detectors={"pii": {"threshold": 0.6}})
    assert [d.detection for d in response.detections] == ["EmailAddress"]


def test_detect_hap_sends_only_hap_detector(adapter, mock_text_detection_adapter):
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS
    response = adapter.detect_hap(text="some text", threshold=0.7)

    mock_text_detection_adapter.detect.assert_called_once_with(text="some text", detectors={"hap": {"threshold": 0.7}})
    assert [d.detection for d in response.detections] == ["has_HAP"]


def test_validate_provider_config_reports_missing_watsonx_keys():
    errors = WatsonxPIIAndHAPAdapter.validate_provider_config(
        provider_config={"model_id": "m", "api_key": "k"},  # pragma: allowlist secret
        config_key="hap_provider_config",
    )
    assert len(errors) == 1
    assert errors[0].startswith(
        "WatsonX provider requires api_key, url, container_kind, container_id in hap_provider_config"
    )
    assert "Missing: url, container_kind, container_id" in errors[0]
