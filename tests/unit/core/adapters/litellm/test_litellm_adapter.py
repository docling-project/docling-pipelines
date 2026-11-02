"""Tests for LiteLLM unified adapter (inference, embeddings, and validation)."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters.litellm import LiteLLMAdapter
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.llm_inference_port import LLMInferencePort


class TestLiteLLMInferenceAdapter:
    """Test suite for LiteLLMInferenceAdapter."""

    @pytest.fixture
    def mock_litellm_client(self):
        """Create a mock LiteLLM client."""
        with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def adapter(self, mock_litellm_client):
        """Create a LiteLLM inference adapter instance."""
        return LiteLLMAdapter(
            model_name="gpt-4",
            api_key="test-key",  # pragma: allowlist secret
            api_base="https://api.openai.com/v1",
        )

    @pytest.fixture
    def ollama_adapter(self, mock_litellm_client):
        """Create a LiteLLM adapter configured for Ollama."""
        return LiteLLMAdapter(
            model_name="openai/llama2",
            api_key="ollama",  # pragma: allowlist secret
            api_base="http://localhost:11434/v1",
        )

    def test_implements_llm_inference_port(self, adapter):
        """Test that adapter implements LLMInferencePort interface."""
        assert isinstance(adapter, LLMInferencePort)

    def test_initialization_with_all_params(self, mock_litellm_client):
        """Test adapter initialization with all parameters."""
        adapter = LiteLLMAdapter(
            model_name="gpt-4-turbo",
            api_key="test-api-key",  # pragma: allowlist secret
            api_base="https://api.openai.com/v1",
        )

        assert adapter.model_name == "gpt-4-turbo"
        assert adapter.client == mock_litellm_client
        assert not hasattr(adapter, "default_response_format")

    def test_initialization_minimal_params(self, mock_litellm_client):
        """Test adapter initialization with minimal parameters."""
        adapter = LiteLLMAdapter(model_name="gpt-3.5-turbo")

        assert adapter.model_name == "gpt-3.5-turbo"
        assert adapter.client == mock_litellm_client

    def test_initialization_ollama(self, mock_litellm_client):
        """Test adapter initialization for Ollama."""
        adapter = LiteLLMAdapter(
            model_name="openai/llama2",
            api_key="ollama",  # pragma: allowlist secret
            api_base="http://localhost:11434/v1",
        )

        assert adapter.model_name == "openai/llama2"
        assert adapter.client == mock_litellm_client

    def test_chat_success(self, adapter, mock_litellm_client):
        """Test successful chat completion."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        expected_response = '{"response": "Hi there!"}'

        mock_litellm_client.chat.return_value = expected_response

        result = adapter.chat(messages=messages)

        assert result == expected_response
        mock_litellm_client.chat.assert_called_once()
        call_kwargs = mock_litellm_client.chat.call_args[1]
        assert call_kwargs["messages"] == messages
        assert "response_format" not in call_kwargs

    def test_chat_with_custom_response_format(self, adapter, mock_litellm_client):
        """Test chat with custom response format overrides default."""
        messages = [{"role": "user", "content": "Test"}]
        custom_format = {"type": "text"}
        expected_response = "Plain text response"

        mock_litellm_client.chat.return_value = expected_response

        result = adapter.chat(messages=messages, response_format=custom_format)

        assert result == expected_response
        call_kwargs = mock_litellm_client.chat.call_args[1]
        assert call_kwargs["response_format"] == custom_format

    def test_chat_with_additional_kwargs(self, adapter, mock_litellm_client):
        """Test chat with additional parameters."""
        messages = [{"role": "user", "content": "Test"}]
        expected_response = '{"result": "success"}'

        mock_litellm_client.chat.return_value = expected_response

        result = adapter.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=100,
            top_p=0.9,
        )

        assert result == expected_response
        call_kwargs = mock_litellm_client.chat.call_args[1]
        assert call_kwargs["temperature"] == pytest.approx(0.7)
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["top_p"] == pytest.approx(0.9)

    def test_chat_error_handling(self, adapter, mock_litellm_client):
        """Test chat error handling."""
        messages = [{"role": "user", "content": "Test"}]
        mock_litellm_client.chat.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            adapter.chat(messages=messages)

    def test_generate_success(self, adapter, mock_litellm_client):
        """Test successful text generation."""
        prompt = "Write a poem"
        expected_response = '{"poem": "Roses are red"}'

        mock_litellm_client.generate.return_value = expected_response

        result = adapter.generate(prompt=prompt)

        assert result == expected_response
        mock_litellm_client.generate.assert_called_once()
        call_kwargs = mock_litellm_client.generate.call_args[1]
        assert call_kwargs["prompt"] == prompt
        assert "response_format" not in call_kwargs

    def test_generate_with_custom_response_format(self, adapter, mock_litellm_client):
        """Test generate with custom response format."""
        prompt = "Test"
        custom_format = {"type": "text"}
        expected_response = "Plain response"

        mock_litellm_client.generate.return_value = expected_response

        result = adapter.generate(prompt=prompt, response_format=custom_format)

        assert result == expected_response
        call_kwargs = mock_litellm_client.generate.call_args[1]
        assert call_kwargs["response_format"] == custom_format

    def test_generate_with_additional_kwargs(self, adapter, mock_litellm_client):
        """Test generate with additional parameters."""
        prompt = "Test prompt"
        expected_response = '{"output": "generated"}'

        mock_litellm_client.generate.return_value = expected_response

        result = adapter.generate(
            prompt=prompt,
            temperature=0.5,
            max_tokens=200,
            stop=["END"],
        )

        assert result == expected_response
        call_kwargs = mock_litellm_client.generate.call_args[1]
        assert call_kwargs["temperature"] == pytest.approx(0.5)
        assert call_kwargs["max_tokens"] == 200
        assert call_kwargs["stop"] == ["END"]

    def test_generate_error_handling(self, adapter, mock_litellm_client):
        """Test generate error handling."""
        prompt = "Test"
        mock_litellm_client.generate.side_effect = Exception("Generation failed")

        with pytest.raises(Exception, match="Generation failed"):
            adapter.generate(prompt=prompt)

    def test_default_json_response_format(self, adapter):
        """Test that default response format is JSON."""
        assert not hasattr(adapter, "default_response_format")

    def test_ollama_chat(self, ollama_adapter, mock_litellm_client):
        """Test chat with Ollama configuration."""
        messages = [{"role": "user", "content": "Hello Ollama"}]
        expected_response = '{"response": "Hello from Ollama"}'

        mock_litellm_client.chat.return_value = expected_response

        result = ollama_adapter.chat(messages=messages)

        assert result == expected_response
        mock_litellm_client.chat.assert_called_once()

    def test_ollama_generate(self, ollama_adapter, mock_litellm_client):
        """Test generate with Ollama configuration."""
        prompt = "Generate with Ollama"
        expected_response = '{"output": "Generated by Ollama"}'

        mock_litellm_client.generate.return_value = expected_response

        result = ollama_adapter.generate(prompt=prompt)

        assert result == expected_response
        mock_litellm_client.generate.assert_called_once()

    def test_client_initialization_parameters(self):
        """Test that client is initialized with correct parameters."""
        with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_client_class:
            LiteLLMAdapter(
                model_name="gpt-4",
                api_key="test-api-key",  # pragma: allowlist secret
                api_base="https://api.test.com",
            )

            mock_client_class.assert_called_once_with(
                model_name="gpt-4",
                api_key="test-api-key",  # pragma: allowlist secret
                api_base="https://api.test.com",
                batch_size=32,
            )

    def test_multiple_chat_calls(self, adapter, mock_litellm_client):
        """Test multiple sequential chat calls."""
        messages1 = [{"role": "user", "content": "First"}]
        messages2 = [{"role": "user", "content": "Second"}]

        mock_litellm_client.chat.side_effect = ['{"r": "1"}', '{"r": "2"}']

        result1 = adapter.chat(messages=messages1)
        result2 = adapter.chat(messages=messages2)

        assert result1 == '{"r": "1"}'
        assert result2 == '{"r": "2"}'
        assert mock_litellm_client.chat.call_count == 2

    def test_multiple_generate_calls(self, adapter, mock_litellm_client):
        """Test multiple sequential generate calls."""
        mock_litellm_client.generate.side_effect = ['{"g": "1"}', '{"g": "2"}', '{"g": "3"}']

        result1 = adapter.generate(prompt="P1")
        result2 = adapter.generate(prompt="P2")
        result3 = adapter.generate(prompt="P3")

        assert result1 == '{"g": "1"}'
        assert result2 == '{"g": "2"}'
        assert result3 == '{"g": "3"}'
        assert mock_litellm_client.generate.call_count == 3

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-4",
            "gpt-3.5-turbo",
            "claude-2",
            "openai/llama2",
            "anthropic/claude-instant-1",
        ],
    )
    def test_various_model_names(self, mock_litellm_client, model_name):
        """Test initialization with various model names."""
        adapter = LiteLLMAdapter(model_name=model_name)
        assert adapter.model_name == model_name

    def test_chat_empty_messages(self, adapter, mock_litellm_client):
        """Test chat with empty messages list."""
        messages: list[dict[str, str]] = []
        mock_litellm_client.chat.return_value = "{}"

        result = adapter.chat(messages=messages)

        assert result == "{}"
        mock_litellm_client.chat.assert_called_once()

    def test_generate_empty_prompt(self, adapter, mock_litellm_client):
        """Test generate with empty prompt."""
        prompt = ""
        mock_litellm_client.generate.return_value = "{}"

        result = adapter.generate(prompt=prompt)

        assert result == "{}"
        mock_litellm_client.generate.assert_called_once()

    def test_adapter_preserves_model_name(self, adapter):
        """Test that adapter preserves the model name."""
        assert adapter.model_name == "gpt-4"

    def test_json_format_injection_in_chat(self, adapter, mock_litellm_client):
        """Test that JSON format is automatically injected in chat."""
        messages = [{"role": "user", "content": "Test"}]
        mock_litellm_client.chat.return_value = "{}"

        adapter.chat(messages=messages, response_format={"type": "json_object"})

        call_kwargs = mock_litellm_client.chat.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_json_format_injection_in_generate(self, adapter, mock_litellm_client):
        """Test that JSON format is automatically injected in generate."""
        prompt = "Test"
        mock_litellm_client.generate.return_value = "{}"

        adapter.generate(prompt=prompt, response_format={"type": "json_object"})

        call_kwargs = mock_litellm_client.generate.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}


class TestLiteLLMEmbeddingAdapter:
    """Test suite for LiteLLMAdapter embedding capabilities."""

    @pytest.fixture
    def mock_litellm_client(self):
        """Create a mock LiteLLM client whose model matches the adapter default."""
        with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_client_class:
            mock_client = Mock()
            mock_client.model_name = "openai/text-embedding-3-small"
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def adapter(self, mock_litellm_client):
        """Create a LiteLLM adapter configured for embeddings."""
        return LiteLLMAdapter(
            model_name="openai/text-embedding-3-small",
            api_key="test-key",  # pragma: allowlist secret
            batch_size=16,
            max_concurrent_requests=3,
        )

    def test_implements_llm_embedding_port(self, adapter):
        """Test that adapter implements LLMEmbeddingPort interface."""
        assert isinstance(adapter, LLMEmbeddingPort)

    def test_generate_embeddings_uses_default_model(self, adapter, mock_litellm_client):
        """Single-text embedding delegates to the client without switching model."""
        mock_litellm_client.generate_embeddings.return_value = [0.1, 0.2]

        result = adapter.generate_embeddings(text="hello")

        assert result == [0.1, 0.2]
        assert mock_litellm_client.model_name == "openai/text-embedding-3-small"
        mock_litellm_client.generate_embeddings.assert_called_once_with(text="hello")

    def test_generate_embeddings_overrides_model(self, adapter, mock_litellm_client):
        """An explicit model_name is applied to the client before embedding."""
        mock_litellm_client.generate_embeddings.return_value = [0.5]

        result = adapter.generate_embeddings(model_name="openai/nomic-embed-text", text="hello")

        assert result == [0.5]
        assert mock_litellm_client.model_name == "openai/nomic-embed-text"
        mock_litellm_client.generate_embeddings.assert_called_once_with(text="hello")

    def test_generate_embeddings_batch_uses_default_model(self, adapter, mock_litellm_client):
        """Batch embedding delegates to the client without switching model."""
        mock_litellm_client.generate_embeddings_batch.return_value = [[0.1], [0.2]]

        result = adapter.generate_embeddings_batch(texts=["a", "b"])

        assert result == [[0.1], [0.2]]
        assert mock_litellm_client.model_name == "openai/text-embedding-3-small"
        mock_litellm_client.generate_embeddings_batch.assert_called_once_with(texts=["a", "b"])

    def test_generate_embeddings_batch_overrides_model(self, adapter, mock_litellm_client):
        """An explicit model_name is applied to the client before batch embedding."""
        mock_litellm_client.generate_embeddings_batch.return_value = [[1.0]]

        adapter.generate_embeddings_batch(model_name="openai/other-embed", texts=["a"])

        assert mock_litellm_client.model_name == "openai/other-embed"
        mock_litellm_client.generate_embeddings_batch.assert_called_once_with(texts=["a"])

    def test_generate_embeddings_batch_propagates_errors(self, adapter, mock_litellm_client):
        """Client errors during batch embedding are propagated."""
        mock_litellm_client.generate_embeddings_batch.side_effect = RuntimeError("rate limited")

        with pytest.raises(RuntimeError, match="rate limited"):
            adapter.generate_embeddings_batch(texts=["a"])

    def test_batch_size_and_concurrency(self, adapter, mock_litellm_client):
        """Batch size comes from the client; concurrency from the constructor."""
        mock_litellm_client.batch_size = 16

        assert adapter.get_embedding_batch_size() == 16
        assert adapter.get_max_concurrent_requests() == 3

    def test_get_embedding_dimension_is_detected_and_cached(self, adapter, mock_litellm_client):
        """Dimension is detected from a sample embedding once and then cached."""
        mock_litellm_client.generate_embeddings.return_value = [0.0] * 768

        assert adapter.get_embedding_dimension() == 768
        assert adapter.get_embedding_dimension() == 768
        mock_litellm_client.generate_embeddings.assert_called_once_with(text="test")


class TestLiteLLMValidation:
    """Test suite for LiteLLMAdapter configuration validation."""

    @pytest.fixture
    def mock_litellm_client(self):
        """Create a mock LiteLLM client with provider detection."""
        with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_client_class:
            mock_client = Mock()
            mock_client._get_provider_from_model.return_value = "openai"
            mock_client_class.return_value = mock_client
            yield mock_client

    def test_validate_inference_valid(self, mock_litellm_client):
        """Valid configuration yields no errors and reports the provider."""
        adapter = LiteLLMAdapter(model_name="gpt-4", api_key="test-key")  # pragma: allowlist secret

        result = adapter.validate_inference()

        assert result == {
            "valid": True,
            "context": "inference",
            "provider": "openai",
            "errors": [],
            "warnings": [],
        }
        mock_litellm_client._get_provider_from_model.assert_called_once_with("gpt-4")

    def test_validate_embedding_valid(self, mock_litellm_client):
        """Embedding validation uses the embedding context."""
        adapter = LiteLLMAdapter(model_name="openai/text-embedding-3-small")

        result = adapter.validate_embedding()

        assert result["valid"] is True
        assert result["context"] == "embedding"

    @pytest.mark.parametrize("model_name", ["", "   "])
    def test_validate_missing_model_name(self, mock_litellm_client, model_name):
        """Blank model names are reported as a validation error."""
        adapter = LiteLLMAdapter(model_name=model_name)

        result = adapter.validate_embedding()

        assert result["valid"] is False
        assert result["errors"] == ["model_name is required"]

    def test_validate_api_key_error_is_reported(self, mock_litellm_client):
        """API key validation failures from the client are surfaced as errors."""
        mock_litellm_client._validate_api_key.side_effect = ValueError("API key not found for provider")
        adapter = LiteLLMAdapter(model_name="gpt-4")

        result = adapter.validate_inference()

        assert result["valid"] is False
        assert result["errors"] == ["API key validation failed: API key not found for provider"]

    def test_validate_ignores_unrelated_client_errors(self, mock_litellm_client):
        """Client errors unrelated to the API key do not invalidate the config."""
        mock_litellm_client._validate_api_key.side_effect = RuntimeError("network unavailable")
        adapter = LiteLLMAdapter(model_name="gpt-4")

        result = adapter.validate_inference()

        assert result["valid"] is True
        assert result["errors"] == []
