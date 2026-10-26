# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for LiteLLMLLMClient (src/docpipe/integrations/litellm/client.py)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.litellm.client import LiteLLMLLMClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *, model_name: str = "gpt-4", api_key: str = "test-key"
) -> LiteLLMLLMClient:  # pragma: allowlist secret
    """Create a LiteLLMLLMClient with a mocked litellm module."""
    with patch("docpipe.integrations.litellm.client.require_package"):
        with patch("builtins.__import__", side_effect=_import_side_effect):
            return LiteLLMLLMClient(model_name=model_name, api_key=api_key)


def _import_side_effect(name, *args, **kwargs):
    if name == "litellm":
        return MagicMock()
    import builtins

    return builtins.__import__(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestLiteLLMClientInit:
    """Tests for __init__ paths."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_init_with_api_key_param(self, mock_req, *, mock_litellm_module):
        """Init succeeds when api_key is passed directly."""
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="my-key")  # pragma: allowlist secret
        assert client.api_key == "my-key"  # pragma: allowlist secret
        assert client.model_name == "gpt-4"

    @patch("docpipe.integrations.litellm.client.require_package")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"})  # pragma: allowlist secret
    def test_init_with_env_var(self, mock_req, *, mock_litellm_module):
        """Init succeeds when api_key comes from environment."""
        client = LiteLLMLLMClient(model_name="gpt-4")
        assert client.api_key == "env-key"  # pragma: allowlist secret

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_init_sets_api_base_on_litellm(self, mock_req, *, mock_litellm_module):
        """api_base is set on the litellm module when provided."""
        client = LiteLLMLLMClient(
            model_name="gpt-4", api_key="k", api_base="https://custom.api"
        )  # pragma: allowlist secret
        assert client.api_base == "https://custom.api"

    @patch.dict(os.environ, {}, clear=True)
    @patch("docpipe.integrations.litellm.client.require_package")
    def test_init_raises_when_no_api_key(self, mock_req, *, mock_litellm_module):
        """Missing api_key raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="API key required"):
            LiteLLMLLMClient(model_name="gpt-4")

    @patch("docpipe.integrations.litellm.client.require_package")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"})  # pragma: allowlist secret
    def test_init_security_warning_when_env_and_param_differ(self, mock_req, *, mock_litellm_module, caplog):
        """A warning is logged when env var and param api_key differ."""
        import logging

        with caplog.at_level(logging.WARNING, logger="docpipe"):
            LiteLLMLLMClient(model_name="gpt-4", api_key="param-key")  # pragma: allowlist secret
        assert any(
            "security" in r.message.lower() or "environment variable" in r.message.lower() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


class TestProviderDetection:
    """Tests for _get_provider_from_model."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_explicit_provider_prefix(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="anthropic/claude-3", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("anthropic/claude-3") == "anthropic"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_gpt_inferred_as_openai(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("gpt-4") == "openai"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_text_embedding_inferred_as_openai(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("text-embedding-ada-002") == "openai"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_claude_inferred_as_anthropic(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("claude-3-sonnet") == "anthropic"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_command_inferred_as_cohere(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("command-r") == "cohere"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_embed_inferred_as_cohere(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("embed-english-v3.0") == "cohere"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_ollama_prefix_inferred_as_ollama(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("ollama/llama2") == "ollama"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_unknown_model_defaults_to_openai(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        assert client._get_provider_from_model("some-unknown-model") == "openai"


# ---------------------------------------------------------------------------
# _set_provider_api_key
# ---------------------------------------------------------------------------


class TestSetProviderApiKey:
    """Tests for _set_provider_api_key."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_sets_openai_key(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        with patch.dict(os.environ, {}, clear=False):
            client._set_provider_api_key("openai", "new-key")  # pragma: allowlist secret
            assert os.environ["OPENAI_API_KEY"] == "new-key"  # pragma: allowlist secret

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_ignores_unknown_provider(self, mock_req, *, mock_litellm_module):
        """Unknown provider does not crash and does not set anything."""
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        client._set_provider_api_key("bedrock", "some-key")  # pragma: allowlist secret
        # No new key should have been added by this method
        assert os.environ.get("BEDROCK_API_KEY") != "some-key"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# generate_embeddings
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    """Tests for generate_embeddings."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_success_with_object_response(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": [0.1, 0.2, 0.3]}]
        client.litellm.embedding.return_value = mock_resp

        result = client.generate_embeddings("hello world")

        assert result == [0.1, 0.2, 0.3]

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_success_with_dict_response(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        mock_resp = {"data": [{"embedding": [0.4, 0.5]}]}
        # Make hasattr(response, "data") false by returning a plain dict
        client.litellm.embedding.return_value = mock_resp

        result = client.generate_embeddings("hello")

        assert result == [0.4, 0.5]

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_unexpected_response_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        client.litellm.embedding.return_value = "unexpected"

        with pytest.raises(ExternalServiceError, match="Unexpected response format"):
            client.generate_embeddings("hello")

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_api_error_wrapped_as_external_service_error(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        client.litellm.embedding.side_effect = RuntimeError("api down")

        with pytest.raises(ExternalServiceError, match="Failed to generate embeddings"):
            client.generate_embeddings("hello")


# ---------------------------------------------------------------------------
# generate_embeddings_batch
# ---------------------------------------------------------------------------


class TestGenerateEmbeddingsBatch:
    """Tests for generate_embeddings_batch."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_success_batched(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(
            model_name="text-embedding-ada-002", api_key="k", batch_size=2
        )  # pragma: allowlist secret
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": [0.1]}, {"embedding": [0.2]}]
        client.litellm.embedding.return_value = mock_resp

        result = client.generate_embeddings_batch(["a", "b", "c", "d"])

        assert len(result) == 4
        assert client.litellm.embedding.call_count == 2  # 4 texts / batch_size 2

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_dict_response_in_batch(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        mock_resp = {"data": [{"embedding": [0.9, 0.8]}]}
        client.litellm.embedding.return_value = mock_resp

        result = client.generate_embeddings_batch(["text1"])

        assert result == [[0.9, 0.8]]

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_empty_list_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.generate_embeddings_batch([])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_non_list_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.generate_embeddings_batch("not a list")  # type: ignore

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_empty_string_in_list_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        with pytest.raises(ConfigurationError, match="non-empty strings"):
            client.generate_embeddings_batch(["valid", ""])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_unexpected_response_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        client.litellm.embedding.return_value = 42  # unexpected type

        with pytest.raises(ExternalServiceError):
            client.generate_embeddings_batch(["text"])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_api_error_wrapped(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret
        client.litellm.embedding.side_effect = RuntimeError("network error")

        with pytest.raises(ExternalServiceError, match="Failed to generate batch embeddings"):
            client.generate_embeddings_batch(["text"])

    @patch("docpipe.integrations.base_llm_client.time.sleep")
    @patch("docpipe.integrations.litellm.client.require_package")
    def test_retry_resends_only_failed_request(self, mock_req, mock_sleep, *, mock_litellm_module):
        """A transient failure in the second request must not re-send the first one."""
        client = LiteLLMLLMClient(
            model_name="text-embedding-ada-002", api_key="k", batch_size=2
        )  # pragma: allowlist secret
        sent: list[list[str]] = []

        def _embedding(**kwargs):
            sent.append(list(kwargs["input"]))
            if len(sent) == 2:
                raise RuntimeError("transient")
            return {"data": [{"embedding": [float(len(t))]} for t in kwargs["input"]]}

        client.litellm.embedding.side_effect = _embedding

        result = client.generate_embeddings_batch(["a", "bb", "ccc", "dddd"])

        assert result == [[1.0], [2.0], [3.0], [4.0]]
        assert sent == [["a", "bb"], ["ccc", "dddd"], ["ccc", "dddd"]]
        assert mock_sleep.call_count == 1

    @patch("docpipe.integrations.base_llm_client.time.sleep")
    @patch("docpipe.integrations.litellm.client.require_package")
    def test_invalid_input_is_not_retried(self, mock_req, mock_sleep, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="text-embedding-ada-002", api_key="k")  # pragma: allowlist secret

        with pytest.raises(ConfigurationError):
            client.generate_embeddings_batch([])

        mock_sleep.assert_not_called()
        client.litellm.embedding.assert_not_called()


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


class TestChat:
    """Tests for chat."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_success_normal_response(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="hello back"))]
        client.litellm.completion.return_value = mock_resp

        result = client.chat([{"role": "user", "content": "hi"}])

        assert result == "hello back"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_success_dict_response(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        mock_resp = {"choices": [{"message": {"content": "from dict"}}]}
        client.litellm.completion.return_value = mock_resp

        result = client.chat([{"role": "user", "content": "hi"}])

        assert result == "from dict"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_streaming_response(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="hel"))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="lo"))]
        client.litellm.completion.return_value = iter([chunk1, chunk2])

        result = client.chat([{"role": "user", "content": "hi"}], stream=True)

        assert result == "hello"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_streaming_chunk_without_content(self, mock_req, *, mock_litellm_module):
        """Chunks with no content are skipped gracefully."""
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        chunk_no_choices = MagicMock()
        chunk_no_choices.choices = []
        chunk_with_content = MagicMock()
        chunk_with_content.choices = [MagicMock(delta=MagicMock(content="hi"))]
        client.litellm.completion.return_value = iter([chunk_no_choices, chunk_with_content])

        result = client.chat([{"role": "user", "content": "test"}], stream=True)

        assert result == "hi"

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_empty_messages_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.chat([])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_unexpected_response_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        client.litellm.completion.return_value = "unexpected"

        with pytest.raises(ExternalServiceError, match="Unexpected response format"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_empty_content_raises(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=None))]
        client.litellm.completion.return_value = mock_resp

        with pytest.raises(ExternalServiceError, match="Empty response"):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_api_error_wrapped(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        client.litellm.completion.side_effect = RuntimeError("timeout")

        with pytest.raises(ExternalServiceError, match="Failed to generate chat completion"):
            client.chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestGenerate:
    """Tests for generate (delegates to chat)."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_generate_calls_chat(self, mock_req, *, mock_litellm_module):
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="generated"))]
        client.litellm.completion.return_value = mock_resp

        result = client.generate("write a poem")

        assert result == "generated"


# ---------------------------------------------------------------------------
# validate_configuration
# ---------------------------------------------------------------------------


class TestValidateConfiguration:
    """Tests for validate_configuration."""

    @patch("docpipe.integrations.litellm.client.require_package")
    def test_validate_calls_super(self, mock_req, *, mock_litellm_module):
        """validate_configuration runs without error for a valid client."""
        client = LiteLLMLLMClient(model_name="gpt-4", api_key="k")  # pragma: allowlist secret
        # Should not raise
        client.validate_configuration()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_litellm_module(monkeypatch):
    """Patch the litellm import inside client.py so tests are self-contained."""
    mock_module = MagicMock()
    # Patch require_package to no-op and inject mock litellm into the module import
    monkeypatch.setattr("docpipe.integrations.litellm.client.require_package", MagicMock())

    # We need to intercept the `import litellm` inside __init__.
    # The simplest way: patch sys.modules so the inline import gets our mock.
    import sys

    original = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_module
    yield mock_module
    if original is None:
        sys.modules.pop("litellm", None)
    else:
        sys.modules["litellm"] = original
