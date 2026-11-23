# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for local PII and HAP detection module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect import (
    _load_static_prompt,
    detect_pii_hap_litellm,
    detect_pii_hap_ollama,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestLoadStaticPrompt:
    """Test suite for _load_static_prompt."""

    def test_load_static_prompt_delegates_to_prompt_manager(self):
        with patch(
            "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._prompt_manager.load_prompt",
            return_value="mock prompt",
        ) as mock_load:
            result = _load_static_prompt()
            assert result == "mock prompt"
            mock_load.assert_called_once()


class TestDetectPiiHapOllama:
    """Test suite for detect_pii_hap_ollama."""

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect.OllamaClient")
    def test_detect_pii_hap_ollama_success(self, mock_ollama_client_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.run_json.return_value = {
            "detections": [{"detection": "email", "detection_type": "pii", "score": 0.95, "start": 0, "end": 10}]
        }
        mock_ollama_client_cls.return_value = mock_instance

        request_data = {
            "input": "test@example.com",
            "detectors": {
                "hap": {"threshold": 0.85},
                "pii": {"threshold": 0.65},
            },
        }
        result = detect_pii_hap_ollama(request_data, model_name="granite4")

        assert "detections" in result
        assert len(result["detections"]) == 1
        mock_prompt.assert_called_once()
        mock_instance.run_json.assert_called_once()
        called_prompt = mock_instance.run_json.call_args[1]["prompt"]
        assert "STATIC_PROMPT:" in called_prompt
        assert "test@example.com" in called_prompt
        assert "hap=0.85" in called_prompt
        assert "pii=0.65" in called_prompt

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect.OllamaClient")
    def test_detect_pii_hap_ollama_default_thresholds(self, mock_ollama_client_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.run_json.return_value = {"detections": []}
        mock_ollama_client_cls.return_value = mock_instance

        request_data = {"input": "clean text"}
        result = detect_pii_hap_ollama(request_data)

        assert result == {"detections": []}
        mock_prompt.assert_called_once()
        called_prompt = mock_instance.run_json.call_args[1]["prompt"]
        assert "hap=0.8" in called_prompt
        assert "pii=0.5" in called_prompt

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect.OllamaClient")
    def test_detect_pii_hap_ollama_json_decode_error(self, mock_ollama_client_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.run_json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
        mock_ollama_client_cls.return_value = mock_instance

        request_data = {"input": "sample text"}
        with pytest.raises(DocpipeException) as exc_info:
            detect_pii_hap_ollama(request_data)

        assert exc_info.value.status_code == 500
        assert "Failed to parse JSON from model" in str(exc_info.value)
        mock_prompt.assert_called_once()


class TestDetectPiiHapLitellm:
    """Test suite for detect_pii_hap_litellm."""

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.integrations.litellm.client.LiteLLMLLMClient")
    def test_detect_pii_hap_litellm_success(self, mock_litellm_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.chat.return_value = '{"detections": [{"detection": "phone", "detection_type": "pii"}]}'
        mock_litellm_cls.return_value = mock_instance

        request_data = {
            "input": "Call 555-1234",
            "detectors": {
                "hap": {"threshold": 0.9},
                "pii": {"threshold": 0.7},
            },
        }
        result = detect_pii_hap_litellm(
            request_data,
            model_name="gpt-4",
            api_key="test-key",
            api_base="https://api.example.com",
            temperature_override=0.1,
        )

        assert "detections" in result
        assert len(result["detections"]) == 1
        mock_prompt.assert_called_once()
        mock_litellm_cls.assert_called_once_with(
            model_name="gpt-4",
            api_key="test-key",
            api_base="https://api.example.com",
            temperature_override=0.1,
        )
        mock_instance.chat.assert_called_once()

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.integrations.litellm.client.LiteLLMLLMClient")
    def test_detect_pii_hap_litellm_empty_response_raises(self, mock_litellm_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.chat.return_value = ""
        mock_litellm_cls.return_value = mock_instance

        request_data = {"input": "sample text"}
        with pytest.raises(DocpipeException) as exc_info:
            detect_pii_hap_litellm(request_data, model_name="gpt-4")

        assert exc_info.value.status_code == 500
        assert "Model returned empty response" in str(exc_info.value)
        mock_prompt.assert_called_once()

    @patch(
        "docpipe.core.operators.quality.pii_and_hap.local_pii_hap_detect._load_static_prompt",
        return_value="STATIC_PROMPT: ",
    )
    @patch("docpipe.integrations.litellm.client.LiteLLMLLMClient")
    def test_detect_pii_hap_litellm_generic_exception_wrapped(self, mock_litellm_cls, mock_prompt):
        mock_instance = MagicMock()
        mock_instance.chat.side_effect = RuntimeError("Connection timeout")
        mock_litellm_cls.return_value = mock_instance

        request_data = {"input": "sample text"}
        with pytest.raises(DocpipeException) as exc_info:
            detect_pii_hap_litellm(request_data, model_name="gpt-4")

        assert exc_info.value.status_code == 500
        assert "Error calling LiteLLM API" in str(exc_info.value)
        mock_prompt.assert_called_once()

    def test_detect_pii_hap_litellm_import_error(self):
        with patch.dict("sys.modules", {"docpipe.integrations.litellm.client": None}):
            with pytest.raises(DocpipeException) as exc_info:
                detect_pii_hap_litellm({"input": "text"}, model_name="gpt-4")

            assert exc_info.value.status_code == 500
            assert "litellm package not installed" in str(exc_info.value)
