# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for LLM clients.

Tests cover base client functionality, retry logic, and provider-specific implementations.
"""

import importlib.util
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, DependencyError, ExternalServiceError
from docpipe.integrations.base_llm_client import BaseLLMClient, require_package, retry_with_backoff
from docpipe.integrations.huggingface.client import HuggingFaceLLMClient
from docpipe.integrations.litellm.client import LiteLLMLLMClient

# Check for optional dependencies
HAS_SENTENCE_TRANSFORMERS = importlib.util.find_spec("sentence_transformers") is not None
HAS_LITELLM = importlib.util.find_spec("litellm") is not None


class TestRetryWithBackoff:
    """Test retry decorator functionality."""

    def test_retry_success_first_attempt(self):
        """Test successful execution on first attempt."""
        mock_func = Mock(return_value="success")
        decorated = retry_with_backoff(max_retries=3)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_success_after_failures(self):
        """Test successful execution after retries."""
        mock_func = Mock(
            __name__="test_func",
            side_effect=[Exception("fail"), Exception("fail"), "success"],
        )
        decorated = retry_with_backoff(max_retries=3, initial_delay=0.01)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 3

    def test_retry_all_attempts_fail(self):
        """Test failure after all retry attempts."""
        mock_func = Mock(__name__="test_func", side_effect=Exception("persistent failure"))
        decorated = retry_with_backoff(max_retries=3, initial_delay=0.01)(mock_func)

        with pytest.raises(Exception, match="persistent failure"):
            decorated()

        assert mock_func.call_count == 3

    def test_retry_without_jitter_sleeps_exact_delay(self):
        """Test that the default backoff sleeps the exact exponential delay."""
        mock_func = Mock(__name__="test_func", side_effect=Exception("fail"))
        decorated = retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)(mock_func)

        with (
            patch("docpipe.integrations.base_llm_client.time.sleep") as sleep,
            patch("docpipe.integrations.base_llm_client.random.uniform") as uniform,
        ):
            with pytest.raises(Exception, match="fail"):
                decorated()

        assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]
        uniform.assert_not_called()

    def test_retry_with_jitter_sleeps_random_share_of_delay(self):
        """Test that jitter sleeps a random duration between 0 and the capped exponential delay."""
        mock_func = Mock(__name__="test_func", side_effect=Exception("fail"))
        decorated = retry_with_backoff(
            max_retries=4, initial_delay=1.0, backoff_factor=2.0, max_delay=3.0, jitter=True
        )(mock_func)

        with (
            patch("docpipe.integrations.base_llm_client.time.sleep") as sleep,
            patch("docpipe.integrations.base_llm_client.random.uniform", side_effect=lambda a, b: b / 2) as uniform,
        ):
            with pytest.raises(Exception, match="fail"):
                decorated()

        assert [c.args for c in uniform.call_args_list] == [(0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
        assert [c.args[0] for c in sleep.call_args_list] == [0.5, 1.0, 1.5]
        assert mock_func.call_count == 4


class TestBaseLLMClient:
    """Test base LLM client functionality."""

    def test_abstract_methods_raise_not_implemented(self):
        """Test that abstract methods must be implemented."""

        class TestClient(BaseLLMClient):
            def generate_embeddings(self, text: str):
                return [0.1, 0.2]

            def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @staticmethod
            def get_model_token_limit(model_name: str) -> int:
                return 1000

            @staticmethod
            def get_embedding_dimension(model_name: str) -> int:
                return 768

        client = TestClient(model_name="test-model")
        embeddings = client.generate_embeddings("test")
        assert embeddings == [0.1, 0.2]

    def test_generate_not_supported(self):
        """Test that generate raises NotImplementedError by default."""

        class TestClient(BaseLLMClient):
            def generate_embeddings(self, text: str):
                return [0.1, 0.2]

            def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @staticmethod
            def get_model_token_limit(model_name: str) -> int:
                return 1000

            @staticmethod
            def get_embedding_dimension(model_name: str) -> int:
                return 768

        client = TestClient(model_name="test-model")

        with pytest.raises(NotImplementedError, match="does not support text generation"):
            client.generate("test prompt")

    def test_chat_not_supported(self):
        """Test that chat raises NotImplementedError by default."""

        class TestClient(BaseLLMClient):
            def generate_embeddings(self, text: str):
                return [0.1, 0.2]

            def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @staticmethod
            def get_model_token_limit(model_name: str) -> int:
                return 1000

            @staticmethod
            def get_embedding_dimension(model_name: str) -> int:
                return 768

        client = TestClient(model_name="test-model")

        with pytest.raises(NotImplementedError, match="does not support chat"):
            client.chat([{"role": "user", "content": "test"}])

    def test_validate_text_input(self):
        """Test text input validation."""

        class TestClient(BaseLLMClient):
            def generate_embeddings(self, text: str):
                self._validate_text_input(text)
                return [0.1, 0.2]

            def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @staticmethod
            def get_model_token_limit(model_name: str) -> int:
                return 1000

            @staticmethod
            def get_embedding_dimension(model_name: str) -> int:
                return 768

        client = TestClient(model_name="test-model")

        with pytest.raises(ConfigurationError, match="must be a non-empty string"):
            client.generate_embeddings("")

        with pytest.raises(ConfigurationError, match="must be a non-empty string"):
            client.generate_embeddings(None)  # type: ignore

    def test_validate_configuration_and_embeddings_output(self):
        """Test model name and embeddings output validation."""

        class TestClient(BaseLLMClient):
            def generate_embeddings(self, text: str):
                return [0.1, 0.2]

            def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @staticmethod
            def get_model_token_limit(model_name: str) -> int:
                return 1000

            @staticmethod
            def get_embedding_dimension(model_name: str) -> int:
                return 768

        TestClient(model_name="test-model").validate_configuration()
        with pytest.raises(ConfigurationError, match="model_name is required"):
            TestClient(model_name="").validate_configuration()

        client = TestClient(model_name="test-model")
        client._validate_embeddings_output([0.1, 2])
        with pytest.raises(ExternalServiceError, match="expected non-empty list"):
            client._validate_embeddings_output([])
        with pytest.raises(ExternalServiceError, match="all elements must be numeric"):
            client._validate_embeddings_output([0.1, "x"])  # type: ignore[list-item]

    def test_sanitize_config_redacts_sensitive_keys(self):
        """Test that sensitive configuration values are masked."""
        sanitized = BaseLLMClient.sanitize_config(
            {"model": "m", "api_key": "k", "IAM_Token": "t"}  # pragma: allowlist secret
        )

        assert sanitized == {"model": "m", "api_key": "***REDACTED***", "IAM_Token": "***REDACTED***"}

    def test_require_package_raises_for_missing_package(self):
        """Test that a missing optional package raises DependencyError with the install hint."""
        require_package("json", "pip install json")

        with pytest.raises(DependencyError, match="pip install not-a-real-package"):
            require_package("not_a_real_package_xyz", "pip install not-a-real-package")


@pytest.mark.skipif(not HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers package not installed")
class TestHuggingFaceLLMClient:
    """Test HuggingFace LLM client."""

    @patch("sentence_transformers.SentenceTransformer")
    def test_initialization_local_mode(self, mock_st):
        """Test client initialization in local mode."""
        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)

        assert client.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert client.use_local is True
        mock_st.assert_called_once()

    @patch("sentence_transformers.SentenceTransformer")
    def test_initialization_local_uses_cached_model(self, mock_st):
        """Test that a second client with the same model uses the cached instance."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2])
        mock_st.return_value = mock_model

        HuggingFaceLLMClient._loaded_models.clear()
        # Load once — populates cache
        HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)
        # Load again — should reuse cache, not call SentenceTransformer again
        HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)

        assert mock_st.call_count == 1

    def test_initialization_api_mode_without_token_raises_error(self):
        """Test that API mode without token raises ConfigurationError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="HuggingFace API token required"):
                HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=False)

    def test_initialization_api_mode_with_token(self):
        """Test API mode initializes InferenceClient when token is present."""
        with patch("huggingface_hub.InferenceClient") as mock_client_cls:
            client = HuggingFaceLLMClient(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                use_local=False,
                api_token="fake-token",  # pragma: allowlist secret
            )
            assert client.use_local is False
            mock_client_cls.assert_called_once_with(token="fake-token")  # pragma: allowlist secret

    @patch("sentence_transformers.SentenceTransformer")
    def test_generate_embeddings_local(self, mock_st):
        """Test local embeddings generation."""
        import numpy as np

        # Clear the model cache before test
        HuggingFaceLLMClient._loaded_models.clear()

        mock_model = MagicMock()
        # Create a proper numpy array mock
        mock_array = np.array([0.1, 0.2, 0.3])
        mock_model.encode.return_value = mock_array
        mock_st.return_value = mock_model

        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)

        embeddings = client.generate_embeddings("test text")

        assert embeddings == [0.1, 0.2, 0.3]
        mock_model.encode.assert_called_once()

    @patch("sentence_transformers.SentenceTransformer")
    def test_generate_embeddings_local_model_none_raises(self, mock_st):
        """Test that generate_embeddings raises when local model is None."""
        HuggingFaceLLMClient._loaded_models.clear()
        mock_st.return_value = MagicMock()
        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)
        client.model = None  # force model to None

        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        with pytest.raises(ExternalServiceError):
            client.generate_embeddings("test")

    def test_generate_embeddings_api(self):
        """Test API-mode single embedding generation."""
        with patch("huggingface_hub.InferenceClient") as mock_client_cls:
            mock_hf_client = MagicMock()
            mock_hf_client.feature_extraction.return_value = [0.1, 0.2, 0.3]
            mock_client_cls.return_value = mock_hf_client

            client = HuggingFaceLLMClient(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                use_local=False,
                api_token="fake-token",  # pragma: allowlist secret
            )
            embeddings = client.generate_embeddings("hello")

        assert embeddings == [0.1, 0.2, 0.3]

    @patch("sentence_transformers.SentenceTransformer")
    def test_generate_embeddings_batch_local(self, mock_st):
        """Test local batch embedding generation."""
        import numpy as np

        HuggingFaceLLMClient._loaded_models.clear()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_st.return_value = mock_model

        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)
        result = client.generate_embeddings_batch(["text one", "text two"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch("sentence_transformers.SentenceTransformer")
    def test_generate_embeddings_batch_empty_raises(self, mock_st):
        """Test that empty batch raises ConfigurationError."""
        HuggingFaceLLMClient._loaded_models.clear()
        mock_st.return_value = MagicMock()
        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)

        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.generate_embeddings_batch([])

    @patch("sentence_transformers.SentenceTransformer")
    def test_generate_embeddings_batch_invalid_text_raises(self, mock_st):
        """Test that a batch with empty strings raises ConfigurationError."""
        HuggingFaceLLMClient._loaded_models.clear()
        mock_st.return_value = MagicMock()
        client = HuggingFaceLLMClient(model_name="sentence-transformers/all-MiniLM-L6-v2", use_local=True)

        with pytest.raises(ConfigurationError, match="non-empty strings"):
            client.generate_embeddings_batch(["valid", ""])

    def test_generate_embeddings_batch_api(self):
        """Test API-mode batch embedding generation."""
        with patch("huggingface_hub.InferenceClient") as mock_client_cls:
            mock_hf_client = MagicMock()
            mock_hf_client.feature_extraction.side_effect = [
                [0.1, 0.2],
                [0.3, 0.4],
            ]
            mock_client_cls.return_value = mock_hf_client

            client = HuggingFaceLLMClient(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                use_local=False,
                api_token="fake-token",  # pragma: allowlist secret
                batch_size=2,
            )
            result = client.generate_embeddings_batch(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_parse_feature_extraction_response_numpy(self):
        """Test _parse_feature_extraction_response with numpy-like object."""
        import numpy as np

        arr = np.array([0.1, 0.2, 0.3])
        result = HuggingFaceLLMClient._parse_feature_extraction_response(arr)
        assert result == [0.1, 0.2, 0.3]

    def test_parse_feature_extraction_response_nested_numpy(self):
        """Test _parse_feature_extraction_response with nested numpy array."""
        import numpy as np

        arr = np.array([[0.1, 0.2, 0.3]])
        result = HuggingFaceLLMClient._parse_feature_extraction_response(arr)
        assert result == [0.1, 0.2, 0.3]

    def test_parse_feature_extraction_response_flat_list(self):
        """Test _parse_feature_extraction_response with a flat list."""
        result = HuggingFaceLLMClient._parse_feature_extraction_response([0.1, 0.2, 0.3])
        assert result == [0.1, 0.2, 0.3]

    def test_parse_feature_extraction_response_nested_list(self):
        """Test _parse_feature_extraction_response with a nested list."""
        result = HuggingFaceLLMClient._parse_feature_extraction_response([[0.1, 0.2, 0.3]])
        assert result == [0.1, 0.2, 0.3]

    def test_parse_feature_extraction_response_unexpected_type_raises(self):
        """Test _parse_feature_extraction_response raises on unexpected type."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        with pytest.raises(ExternalServiceError, match="Unexpected response format"):
            HuggingFaceLLMClient._parse_feature_extraction_response("not-a-list")

    def test_validate_configuration_api_without_token_raises(self):
        """Test validate_configuration raises when API mode has no token."""
        with patch("huggingface_hub.InferenceClient"):
            with patch.dict(os.environ, {}, clear=True):
                # Inject a client with use_local=False and no api_token
                with pytest.raises(ConfigurationError, match="HuggingFace API token required"):
                    HuggingFaceLLMClient(model_name="m", use_local=False)

    def test_get_model_token_limit(self):
        """Test token limit retrieval."""
        assert HuggingFaceLLMClient.get_model_token_limit("sentence-transformers/all-MiniLM-L6-v2") == 512
        assert HuggingFaceLLMClient.get_model_token_limit("unknown-model") == 512

    def test_get_embedding_dimension(self):
        """Test embedding dimension retrieval."""
        assert HuggingFaceLLMClient.get_embedding_dimension("sentence-transformers/all-MiniLM-L6-v2") == 384
        assert HuggingFaceLLMClient.get_embedding_dimension("unknown-model") == 384


@pytest.mark.skipif(not HAS_LITELLM, reason="litellm package not installed")
class TestLiteLLMLLMClient:
    """Test LiteLLM client."""

    @patch("litellm.embedding")
    @patch("litellm.completion")
    def test_initialization(self, mock_completion, mock_embedding):
        """Test client initialization."""
        with patch("litellm.api_base", None):
            client = LiteLLMLLMClient(
                model_name="gpt-4",
                api_key="test-key",  # pragma: allowlist secret
            )

            assert client.model_name == "gpt-4"
            assert client.api_key == "test-key"  # pragma: allowlist secret

    @patch("litellm.embedding")
    def test_initialization_with_api_base_sets_litellm(self, mock_embedding):
        """Test that api_base is applied to litellm when provided."""
        import litellm

        client = LiteLLMLLMClient(
            model_name="text-embedding-ada-002",
            api_base="http://localhost:8080",
        )
        assert client.api_base == "http://localhost:8080"
        assert litellm.api_base == "http://localhost:8080"

    @patch("litellm.embedding")
    def test_initialization_sets_provider_api_key(self, mock_embedding):
        """Test that api_key parameter sets the provider env var."""
        client = LiteLLMLLMClient(
            model_name="text-embedding-ada-002",
            api_key="explicit-key",  # pragma: allowlist secret
        )
        assert client.api_key == "explicit-key"  # pragma: allowlist secret
        assert os.environ.get("OPENAI_API_KEY") == "explicit-key"  # pragma: allowlist secret

    @patch("litellm.embedding")
    def test_generate_embeddings(self, mock_embedding):
        """Test embeddings generation."""
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1, 0.2, 0.3]}]
        mock_embedding.return_value = mock_response

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")

        embeddings = client.generate_embeddings("test text")

        assert embeddings == [0.1, 0.2, 0.3]
        mock_embedding.assert_called_once()

    @patch("litellm.embedding")
    def test_generate_embeddings_dict_response(self, mock_embedding):
        """Test embeddings generation with dict-style response."""
        mock_embedding.return_value = {"data": [{"embedding": [0.4, 0.5]}]}

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        embeddings = client.generate_embeddings("test")

        assert embeddings == [0.4, 0.5]

    @patch("litellm.embedding")
    def test_generate_embeddings_unexpected_response_raises(self, mock_embedding):
        """Test that unexpected response format raises ExternalServiceError."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        mock_embedding.return_value = "bad-response"

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        with pytest.raises(ExternalServiceError):
            client.generate_embeddings("test")

    @patch("litellm.embedding")
    def test_generate_embeddings_batch(self, mock_embedding):
        """Test batch embeddings generation."""
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]
        mock_embedding.return_value = mock_response

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", batch_size=10)
        result = client.generate_embeddings_batch(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch("litellm.embedding")
    def test_generate_embeddings_batch_dict_response(self, mock_embedding):
        """Test batch embeddings with dict-style response."""
        mock_embedding.return_value = {"data": [{"embedding": [0.9, 0.8]}]}

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        result = client.generate_embeddings_batch(["hello"])

        assert result == [[0.9, 0.8]]

    @patch("litellm.embedding")
    def test_generate_embeddings_batch_unexpected_response_raises(self, mock_embedding):
        """Test that batch with unexpected response format raises ExternalServiceError."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        mock_embedding.return_value = "bad-response"

        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        with pytest.raises(ExternalServiceError):
            client.generate_embeddings_batch(["text"])

    @patch("litellm.embedding")
    def test_generate_embeddings_batch_empty_raises(self, mock_embedding):
        """Test that empty batch raises ConfigurationError."""
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.generate_embeddings_batch([])

    @patch("litellm.embedding")
    def test_generate_embeddings_batch_invalid_text_raises(self, mock_embedding):
        """Test that batch with empty string raises ConfigurationError."""
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        with pytest.raises(ConfigurationError, match="non-empty strings"):
            client.generate_embeddings_batch(["ok", ""])

    @patch("litellm.completion")
    def test_chat(self, mock_completion):
        """Test chat completion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="response text"))]
        mock_completion.return_value = mock_response

        client = LiteLLMLLMClient(model_name="gpt-4")

        messages = [{"role": "user", "content": "test"}]
        response = client.chat(messages)

        assert response == "response text"
        mock_completion.assert_called_once()

    @patch("litellm.completion")
    def test_chat_streaming(self, mock_completion):
        """Test chat completion with streaming response."""
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="hello "))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="world"))]
        mock_completion.return_value = iter([chunk1, chunk2])

        client = LiteLLMLLMClient(model_name="gpt-4")
        response = client.chat([{"role": "user", "content": "hi"}], stream=True)

        assert response == "hello world"

    @patch("litellm.completion")
    def test_chat_non_streaming_dict_response(self, mock_completion):
        """Test chat with dict-style non-streaming response."""
        mock_completion.return_value = {"choices": [{"message": {"content": "dict reply"}}]}

        client = LiteLLMLLMClient(model_name="gpt-4")
        response = client.chat([{"role": "user", "content": "hi"}])

        assert response == "dict reply"

    @patch("litellm.completion")
    def test_chat_non_streaming_unexpected_response_raises(self, mock_completion):
        """Test that unexpected non-streaming response raises ExternalServiceError."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        mock_completion.return_value = "bad"

        client = LiteLLMLLMClient(model_name="gpt-4")
        with pytest.raises(ExternalServiceError):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("litellm.completion")
    def test_chat_empty_messages_raises(self, mock_completion):
        """Test that empty messages list raises ConfigurationError."""
        client = LiteLLMLLMClient(model_name="gpt-4")
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.chat([])

    @patch("litellm.completion")
    def test_chat_empty_response_raises(self, mock_completion):
        """Test that empty content in response raises ExternalServiceError."""
        from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=""))]
        mock_completion.return_value = mock_response

        client = LiteLLMLLMClient(model_name="gpt-4")
        with pytest.raises(ExternalServiceError, match="Empty response"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("litellm.completion")
    def test_generate(self, mock_completion):
        """Test generate delegates to chat."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="generated"))]
        mock_completion.return_value = mock_response

        client = LiteLLMLLMClient(model_name="gpt-4")
        result = client.generate("my prompt")

        assert result == "generated"

    @patch("litellm.embedding")
    def test_validate_configuration(self, mock_embedding):
        """Test validate_configuration runs without error for a valid client."""
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002")
        client.validate_configuration()  # should not raise

    def test_get_embedding_dimension_returns_zero(self):
        """Test that get_embedding_dimension always returns 0 (runtime-determined)."""
        assert LiteLLMLLMClient.get_embedding_dimension("any-model") == 0

    def test_get_model_token_limit(self):
        """Test token limit retrieval."""
        assert LiteLLMLLMClient.get_model_token_limit("gpt-4") == 8192
        assert LiteLLMLLMClient.get_model_token_limit("unknown-model") == 8191


class TestLiteLLMAPIKeyValidation:
    """Test API key validation for LiteLLM client."""

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="API key required"):
            LiteLLMLLMClient(model_name="text-embedding-3-small")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret
    @patch("litellm.embedding")
    def test_env_var_api_key_works(self, mock_embedding):
        """Test that environment variable API key works."""
        client = LiteLLMLLMClient(model_name="text-embedding-3-small")
        assert client is not None
        assert client.model_name == "text-embedding-3-small"

    @patch("litellm.embedding")
    def test_param_api_key_works(self, mock_embedding):
        """Test that parameter API key works (with security warning logged)."""
        client = LiteLLMLLMClient(
            model_name="text-embedding-3-small",
            api_key="test-key",  # pragma: allowlist secret
        )
        assert client is not None
        assert client.api_key == "test-key"  # pragma: allowlist secret

    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"})  # pragma: allowlist secret
    @patch("litellm.embedding")
    def test_env_var_with_param_works(self, mock_embedding):
        """Test that providing both env var and param works (param shows warning)."""
        client = LiteLLMLLMClient(
            model_name="text-embedding-3-small",
            api_key="param-key",  # pragma: allowlist secret
        )
        assert client is not None
        assert client.api_key == "param-key"  # pragma: allowlist secret

    @patch.dict(os.environ, {"COHERE_API_KEY": "test-key"})  # pragma: allowlist secret
    @patch("litellm.embedding")
    def test_cohere_provider_validation(self, mock_embedding):
        """Test validation for Cohere provider."""
        client = LiteLLMLLMClient(model_name="embed-english-v3.0")
        assert client is not None

    @patch.dict(os.environ, {}, clear=True)
    def test_cohere_missing_key_raises_error(self):
        """Test that missing Cohere API key raises error."""
        with pytest.raises(ConfigurationError, match="COHERE_API_KEY"):
            LiteLLMLLMClient(model_name="embed-english-v3.0")

    @patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "test-key"},  # pragma: allowlist secret
    )
    @patch("litellm.completion")
    def test_anthropic_provider_validation(self, mock_completion):
        """Test validation for Anthropic provider."""
        client = LiteLLMLLMClient(model_name="claude-3-opus")
        assert client is not None

    @patch.dict(os.environ, {}, clear=True)
    def test_anthropic_missing_key_raises_error(self):
        """Test that missing Anthropic API key raises error."""
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            LiteLLMLLMClient(model_name="claude-3-opus")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret
    @patch("litellm.embedding")
    def test_provider_prefix_extraction(self, mock_embedding):
        """Test provider extraction from model name with prefix."""
        client = LiteLLMLLMClient(model_name="openai/text-embedding-3-small")
        assert client is not None
