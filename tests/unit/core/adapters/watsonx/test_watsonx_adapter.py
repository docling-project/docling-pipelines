# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for WatsonX unified adapter (inference, embeddings, and text detection)."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters import WatsonXAdapter
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.core.ports.text_detection_port import TextDetectionPort


class TestWatsonXInferenceAdapter:
    """Test suite for WatsonX inference capabilities."""

    @pytest.fixture
    def mock_watsonx_client(self):
        """Create a mock WatsonX client."""
        with patch("docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def adapter(self, mock_watsonx_client):
        """Create a WatsonX inference adapter instance."""
        return WatsonXAdapter(
            model_name="test-model",
            api_key="watsonx-test-credential",  # pragma: allowlist secret
            container_id="test-container",
            api_base="https://test.watsonx.ai",
            timeout=60,
        )

    def test_implements_llm_inference_port(self, adapter):
        """Test that adapter implements LLMInferencePort interface."""
        assert isinstance(adapter, LLMInferencePort)

    def test_initialization(self, mock_watsonx_client):
        """Test adapter initialization with all parameters."""
        adapter = WatsonXAdapter(
            model_name="granite-13b",
            api_key="watsonx-test-credential",  # pragma: allowlist secret
            container_id="test-project-id",
            api_base="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            timeout=120,
        )

        assert adapter.model_name == "granite-13b"
        assert adapter.client == mock_watsonx_client

    def test_initialization_minimal_params(self, mock_watsonx_client):
        """Test adapter initialization with minimal parameters."""
        adapter = WatsonXAdapter(model_name="test-model")

        assert adapter.model_name == "test-model"
        assert adapter.client == mock_watsonx_client

    def test_chat_success(self, adapter, mock_watsonx_client):
        """Test successful chat completion."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        expected_response = "Hi there! How can I help you today?"

        mock_watsonx_client.chat.return_value = expected_response

        result = adapter.chat(messages=messages)

        assert result == expected_response
        mock_watsonx_client.chat.assert_called_once_with(messages=messages)

    def test_chat_with_kwargs(self, adapter, mock_watsonx_client):
        """Test chat completion with additional parameters."""
        messages = [{"role": "user", "content": "Test"}]
        expected_response = "Response"

        mock_watsonx_client.chat.return_value = expected_response

        result = adapter.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=100,
            top_p=0.9,
        )

        assert result == expected_response
        mock_watsonx_client.chat.assert_called_once_with(
            messages=messages,
            temperature=0.7,
            max_tokens=100,
            top_p=0.9,
        )

    def test_chat_error_handling(self, adapter, mock_watsonx_client):
        """Test chat error handling."""
        messages = [{"role": "user", "content": "Test"}]
        mock_watsonx_client.chat.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            adapter.chat(messages=messages)

    def test_generate_success(self, adapter, mock_watsonx_client):
        """Test successful text generation."""
        prompt = "Write a short poem about AI"
        expected_response = "AI so bright, learning day and night"

        mock_watsonx_client.generate.return_value = expected_response

        result = adapter.generate(prompt=prompt)

        assert result == expected_response
        mock_watsonx_client.generate.assert_called_once_with(prompt=prompt)

    def test_generate_with_kwargs(self, adapter, mock_watsonx_client):
        """Test text generation with additional parameters."""
        prompt = "Test prompt"
        expected_response = "Generated text"

        mock_watsonx_client.generate.return_value = expected_response

        result = adapter.generate(
            prompt=prompt,
            temperature=0.5,
            max_tokens=200,
            stop_sequences=["END"],
        )

        assert result == expected_response
        mock_watsonx_client.generate.assert_called_once_with(
            prompt=prompt,
            temperature=0.5,
            max_tokens=200,
            stop_sequences=["END"],
        )

    def test_generate_error_handling(self, adapter, mock_watsonx_client):
        """Test generate error handling."""
        prompt = "Test"
        mock_watsonx_client.generate.side_effect = Exception("Generation failed")

        with pytest.raises(Exception, match="Generation failed"):
            adapter.generate(prompt=prompt)

    def test_chat_empty_messages(self, adapter, mock_watsonx_client):
        """Test chat with empty messages list."""
        messages: list[dict[str, str]] = []
        mock_watsonx_client.chat.return_value = ""

        result = adapter.chat(messages=messages)

        assert result == ""
        mock_watsonx_client.chat.assert_called_once_with(messages=messages)

    def test_generate_empty_prompt(self, adapter, mock_watsonx_client):
        """Test generate with empty prompt."""
        prompt = ""
        mock_watsonx_client.generate.return_value = ""

        result = adapter.generate(prompt=prompt)

        assert result == ""
        mock_watsonx_client.generate.assert_called_once_with(prompt=prompt)

    def test_multiple_chat_calls(self, adapter, mock_watsonx_client):
        """Test multiple sequential chat calls."""
        messages1 = [{"role": "user", "content": "First"}]
        messages2 = [{"role": "user", "content": "Second"}]

        mock_watsonx_client.chat.side_effect = ["Response 1", "Response 2"]

        result1 = adapter.chat(messages=messages1)
        result2 = adapter.chat(messages=messages2)

        assert result1 == "Response 1"
        assert result2 == "Response 2"
        assert mock_watsonx_client.chat.call_count == 2

    def test_multiple_generate_calls(self, adapter, mock_watsonx_client):
        """Test multiple sequential generate calls."""
        mock_watsonx_client.generate.side_effect = ["Gen 1", "Gen 2", "Gen 3"]

        result1 = adapter.generate(prompt="Prompt 1")
        result2 = adapter.generate(prompt="Prompt 2")
        result3 = adapter.generate(prompt="Prompt 3")

        assert result1 == "Gen 1"
        assert result2 == "Gen 2"
        assert result3 == "Gen 3"
        assert mock_watsonx_client.generate.call_count == 3

    def test_client_initialization_parameters(self):
        """Test that client is initialized with correct parameters."""
        with patch("docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient") as mock_client_class:
            WatsonXAdapter(
                model_name="test-model",
                api_key="watsonx-test-credential",  # pragma: allowlist secret
                container_id="test-container-id",
                api_base="https://api.test.com",
                container_kind="space",
                timeout=90,
            )

            mock_client_class.assert_called_once_with(
                model_name="test-model",
                api_key="watsonx-test-credential",  # pragma: allowlist secret
                container_id="test-container-id",
                api_base="https://api.test.com",
                container_kind="space",
                timeout=90,
            )

    def test_adapter_preserves_model_name(self, adapter):
        """Test that adapter preserves the model name."""
        assert adapter.model_name == "test-model"

    @pytest.mark.parametrize(
        ("messages", "expected_call_count"),
        [
            ([{"role": "user", "content": "Hi"}], 1),
            ([{"role": "system", "content": "System"}, {"role": "user", "content": "User"}], 1),
            ([], 1),
        ],
    )
    def test_chat_various_message_formats(self, adapter, mock_watsonx_client, messages, expected_call_count):
        """Test chat with various message formats."""
        mock_watsonx_client.chat.return_value = "Response"

        adapter.chat(messages=messages)

        assert mock_watsonx_client.chat.call_count == expected_call_count
        mock_watsonx_client.chat.assert_called_with(messages=messages)

    @pytest.mark.parametrize(
        ("prompt", "expected_call_count"),
        [
            ("Short prompt", 1),
            ("A" * 1000, 1),  # Long prompt
            ("", 1),  # Empty prompt
        ],
    )
    def test_generate_various_prompt_lengths(self, adapter, mock_watsonx_client, prompt, expected_call_count):
        """Test generate with various prompt lengths."""
        mock_watsonx_client.generate.return_value = "Response"

        adapter.generate(prompt=prompt)

        assert mock_watsonx_client.generate.call_count == expected_call_count
        mock_watsonx_client.generate.assert_called_with(prompt=prompt)


class TestWatsonXTextDetection:
    """Test suite for WatsonX text detection capabilities."""

    @pytest.fixture
    def mock_rest_client(self):
        """Create a mock REST client."""
        with patch("docpipe.integrations.watsonx.detection_client.RestClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_iam_token(self):
        """Mock IAM token retrieval."""
        with patch(
            "docpipe.integrations.watsonx.detection_client.WatsonxPipelineOptionsProvider._get_iam_access_token"
        ) as mock_token:
            mock_token.return_value = "test-access-token"
            yield mock_token

    @pytest.fixture
    def adapter(self, mock_iam_token):
        """Create a WatsonX adapter instance for text detection."""
        with patch("docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"):
            return WatsonXAdapter(
                model_name="test-model",
                api_key="watsonx-test-credential",  # pragma: allowlist secret
                container_id="test-project-id",
                api_base="https://us-south.ml.cloud.ibm.com",
                container_kind="project",
                timeout=120,
            )

    def test_implements_text_detection_port(self, adapter):
        """Test that adapter implements TextDetectionPort interface."""
        assert isinstance(adapter, TextDetectionPort)

    def test_detect_success(self, adapter, mock_rest_client):
        """Test successful text detection."""
        text = "My email is john@example.com"
        mock_detections = [
            {
                "detection": "EMAIL",
                "score": 0.95,
                "start": 12,
                "end": 29,
                "text": "john@example.com",
            }
        ]

        mock_rest_client.call_rest_json.return_value = {"detections": mock_detections}

        result = adapter.detect(text=text)

        assert result["success"] is True
        assert result["detections"] == mock_detections
        assert result["error"] is None
        mock_rest_client.call_rest_json.assert_called_once()

    def test_detect_with_custom_detectors(self, adapter, mock_rest_client):
        """Test detection with custom detector configuration."""
        text = "Test text"
        custom_detectors = {
            "pii": {"threshold": 0.7},
            "hap": {"threshold": 0.9},
        }

        mock_rest_client.call_rest_json.return_value = {"detections": []}

        result = adapter.detect(text=text, detectors=custom_detectors)

        assert result["success"] is True
        call_args = mock_rest_client.call_rest_json.call_args
        assert call_args[1]["json_data"]["detectors"] == custom_detectors

    def test_detect_empty_text_raises_error(self, adapter):
        """Test that empty text raises ValueError."""
        with pytest.raises(ValueError, match="Input text cannot be empty"):
            adapter.detect(text="")

        with pytest.raises(ValueError, match="Input text cannot be empty"):
            adapter.detect(text="   ")

    def test_detect_api_error_handling(self, adapter, mock_rest_client):
        """Test error handling when API call fails."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        text = "Test text"
        mock_rest_client.call_rest_json.side_effect = ExternalServiceError(message="API Error", status_code=500)

        result = adapter.detect(text=text)

        assert result["success"] is False
        assert result["detections"] == []
        assert "API Error" in result["error"]

    def test_detect_entities_success(self, adapter, mock_rest_client):
        """Test successful entity detection."""
        text = "My SSN is 123-45-6789"
        prompt = "Detect PII in the text"

        mock_detections = [
            {
                "detection": "SSN",
                "score": 0.98,
                "start": 11,
                "end": 22,
                "text": "123-45-6789",
            }
        ]
        mock_rest_client.call_rest_json.return_value = {"detections": mock_detections}

        result = adapter.detect_entities(text=text, prompt=prompt)

        assert result["detected"] is True
        assert result["entities"] == mock_detections
        assert result["confidence"] == 1.0
        assert "raw_response" in result

    def test_detect_entities_no_detections(self, adapter, mock_rest_client):
        """Test entity detection with no detections found."""
        text = "Clean text with no PII"
        prompt = "Detect PII"

        mock_rest_client.call_rest_json.return_value = {"detections": []}

        result = adapter.detect_entities(text=text, prompt=prompt)

        assert result["detected"] is False
        assert result["entities"] == []
        assert result["confidence"] == 0.0

    def test_detect_entities_empty_text_raises_error(self, adapter):
        """Test that empty text raises ValueError."""
        with pytest.raises(ValueError, match="Input text cannot be empty"):
            adapter.detect_entities(text="", prompt="Test prompt")

    def test_detect_entities_empty_prompt_raises_error(self, adapter):
        """Test that empty prompt raises ValueError."""
        with pytest.raises(ValueError, match="Detection prompt cannot be empty"):
            adapter.detect_entities(text="Test text", prompt="")

    def test_detect_entities_batch_success(self, adapter, mock_rest_client):
        """Test successful batch entity detection."""
        texts = ["Text with email@test.com", "Text with phone 555-1234"]
        prompt = "Detect PII"

        mock_rest_client.call_rest_json.side_effect = [
            {"detections": [{"detection": "EMAIL", "score": 0.9}]},
            {"detections": [{"detection": "PHONE", "score": 0.85}]},
        ]

        results = adapter.detect_entities_batch(texts=texts, prompt=prompt)

        assert len(results) == 2
        assert results[0]["detected"] is True
        assert results[1]["detected"] is True
        assert mock_rest_client.call_rest_json.call_count == 2

    def test_detect_entities_batch_partial_failure(self, adapter, mock_rest_client):
        """Test batch detection with partial failures."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        texts = ["Text 1", "Text 2", "Text 3"]
        prompt = "Detect PII"

        mock_rest_client.call_rest_json.side_effect = [
            {"detections": [{"detection": "EMAIL"}]},
            DocpipeException(message="API Error", status_code=500),
            {"detections": []},
        ]

        results = adapter.detect_entities_batch(texts=texts, prompt=prompt)

        assert len(results) == 3
        assert results[0]["detected"] is True
        assert results[1]["detected"] is False
        assert "error" in results[1]
        assert results[2]["detected"] is False

    def test_detect_entities_batch_empty_list_raises_error(self, adapter):
        """Test that empty texts list raises ValueError."""
        with pytest.raises(ValueError, match="Input texts list cannot be empty"):
            adapter.detect_entities_batch(texts=[], prompt="Test prompt")

    def test_detect_default_detectors(self, adapter, mock_rest_client):
        """Test that default detectors are used when not provided."""
        text = "Test text"
        mock_rest_client.call_rest_json.return_value = {"detections": []}

        adapter.detect(text=text)

        call_args = mock_rest_client.call_rest_json.call_args
        payload = call_args[1]["json_data"]
        assert "detectors" in payload
        assert "pii" in payload["detectors"]
        assert "hap" in payload["detectors"]
        assert payload["detectors"]["pii"]["threshold"] == 0.5
        assert payload["detectors"]["hap"]["threshold"] == 0.8

    def test_detect_api_url_construction(self, adapter, mock_rest_client):
        """Test that detection API URL is correctly constructed."""
        text = "Test text"
        mock_rest_client.call_rest_json.return_value = {"detections": []}

        adapter.detect(text=text)

        call_args = mock_rest_client.call_rest_json.call_args
        endpoint = call_args[1]["url"]
        assert "/ml/v1/text/detection" in endpoint

    def test_detect_includes_container_id(self, adapter, mock_rest_client):
        """Test that container_id is included in the request payload."""
        text = "Test text"
        mock_rest_client.call_rest_json.return_value = {"detections": []}

        adapter.detect(text=text)

        call_args = mock_rest_client.call_rest_json.call_args
        payload = call_args[1]["json_data"]
        assert "project_id" in payload
        assert payload["project_id"] == "test-project-id"

    def test_detect_token_refresh_on_auth_error(self, adapter, mock_rest_client, mock_iam_token):
        """Test that access token is refreshed on authentication errors."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        text = "Test text"
        mock_rest_client.call_rest_json.side_effect = [
            ExternalServiceError(message="Unauthorized", status_code=401),
            {"detections": []},
        ]

        result = adapter.detect(text=text)

        assert result["success"] is False
        assert mock_iam_token.call_count == 1

        # Token was cleared by the 401, so the next call fetches a new one
        result = adapter.detect(text=text)

        assert result["success"] is True
        assert mock_iam_token.call_count == 2

    def test_construction_makes_no_network_call(self, mock_rest_client, mock_iam_token):
        """Constructing the adapter must not request an IAM token or call the detection API."""
        with patch("docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"):
            WatsonXAdapter(
                model_name="test-model",
                api_key="watsonx-test-credential",  # pragma: allowlist secret
                container_id="test-project-id",
                api_base="https://us-south.ml.cloud.ibm.com",
                container_kind="project",
            )

        mock_iam_token.assert_not_called()
        mock_rest_client.call_rest_json.assert_not_called()
