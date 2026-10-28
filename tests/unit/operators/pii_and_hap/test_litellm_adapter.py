# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for LiteLLMPIIAndHAPAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.litellm.adapter import LiteLLMPIIAndHAPAdapter
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.litellm.config import ADAPTER_NAME
from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_INFERENCE_MODULE = (
    "docpipe.core.operators.quality.pii_and_hap.adapters.outbound.litellm.adapter"
    ".LLMAdapterFactory.create_inference_adapter"
)

_LITELLM_CONFIG = {
    "api_key": "test-key",  # pragma: allowlist secret
    "api_base": "http://localhost:11434/v1",
}


@pytest.fixture
def mock_llm_adapter():
    mock = MagicMock()
    mock.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    mock.chat.return_value = '{"detections": []}'
    return mock


@pytest.fixture
def adapter(mock_llm_adapter):
    with patch(_INFERENCE_MODULE, return_value=mock_llm_adapter):
        return LiteLLMPIIAndHAPAdapter(model_id="openai/granite4", provider_config=_LITELLM_CONFIG)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_adapter_name_constant():
    assert ADAPTER_NAME == "litellm"


def test_adapter_name_attribute():
    assert LiteLLMPIIAndHAPAdapter.ADAPTER_NAME == "litellm"


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_delegates_to_inner_adapter(adapter, mock_llm_adapter):
    mock_llm_adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    result = adapter.validate()
    assert result["valid"] is True
    mock_llm_adapter.validate.assert_called_once()


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


def test_detect_returns_empty_response_on_empty_llm_reply(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = ""
    response = adapter.detect(payload={"input": "some text", "detectors": {}})
    assert isinstance(response, PIIHAPDetectionResponse)
    assert response.detections == []


def test_detect_returns_empty_response_on_whitespace_llm_reply(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = "   "
    response = adapter.detect(payload={"input": "some text", "detectors": {}})
    assert response.detections == []


def test_detect_parses_detections_from_llm_response(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = (
        '{"detections": [{"detection": "EmailAddress", "detection_type": "pii",'
        ' "score": 0.9, "start": 0, "end": 15, "text": "test@example.com"}]}'
    )
    response = adapter.detect(payload={"input": "test@example.com", "detectors": {}})
    assert len(response.detections) == 1
    assert response.detections[0].detection == "EmailAddress"


def test_detect_wraps_unexpected_llm_exception(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.side_effect = RuntimeError("network error")
    with pytest.raises(DocpipeException, match="LLM inference failed"):
        adapter.detect(payload={"input": "some text", "detectors": {}})


def test_detect_passes_thresholds_in_prompt(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = '{"detections": []}'
    adapter.detect(
        payload={
            "input": "some text",
            "detectors": {"pii": {"threshold": 0.7}, "hap": {"threshold": 0.9}},
        }
    )
    call_args = mock_llm_adapter.chat.call_args
    prompt = call_args[1]["messages"][0]["content"]
    assert "hap=0.9" in prompt
    assert "pii=0.7" in prompt
    assert "Report ONLY" not in prompt


# ---------------------------------------------------------------------------
# Capability-scoped detection (PIIDetectionPort / HAPDetectionPort)
# ---------------------------------------------------------------------------

_MIXED_RESPONSE = (
    '{"detections": ['
    '{"detection": "EmailAddress", "detection_type": "pii", "score": 0.9, "start": 0, "end": 16, "text": "t@e.com"},'
    '{"detection": "has_HAP", "detection_type": "hap", "score": 0.9, "start": 17, "end": 30, "text": "insult"}'
    "]}"
)


def test_adapter_declares_both_capabilities():
    assert LiteLLMPIIAndHAPAdapter.SUPPORTS_PII is True
    assert LiteLLMPIIAndHAPAdapter.SUPPORTS_HAP is True


def test_detect_pii_scopes_prompt_and_filters_hap(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = _MIXED_RESPONSE
    response = adapter.detect_pii(text="some text", threshold=0.6)

    prompt = mock_llm_adapter.chat.call_args[1]["messages"][0]["content"]
    assert "Report ONLY PII detections" in prompt
    assert "pii=0.6" in prompt
    assert [d.detection for d in response.detections] == ["EmailAddress"]


def test_detect_hap_scopes_prompt_and_filters_pii(adapter, mock_llm_adapter):
    mock_llm_adapter.chat.return_value = _MIXED_RESPONSE
    response = adapter.detect_hap(text="some text", threshold=0.85)

    prompt = mock_llm_adapter.chat.call_args[1]["messages"][0]["content"]
    assert "Report ONLY HAP detections" in prompt
    assert "hap=0.85" in prompt
    assert [d.detection for d in response.detections] == ["has_HAP"]
