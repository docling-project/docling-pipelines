# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WatsonXClient (src/docpipe/integrations/watsonx/client.py)."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.watsonx.client import WatsonXClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_iam_manager(monkeypatch):
    """Patch IAMTokenManager so no real HTTP calls happen."""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.get_token.return_value = "mock-iam-token"
    mock_cls.return_value = mock_instance
    monkeypatch.setattr("docpipe.integrations.watsonx.client.IAMTokenManager", mock_cls)
    return mock_cls


@pytest.fixture
def valid_env(monkeypatch):
    """Set all required environment variables."""
    monkeypatch.setenv("WATSONX_API_KEY", "test-api-key")  # pragma: allowlist secret
    monkeypatch.setenv("WATSONX_CONTAINER_ID", "test-container-id")
    monkeypatch.setenv("WATSONX_API_BASE_URL", "https://us-south.ml.cloud.ibm.com")


@pytest.fixture
def client(mock_iam_manager, valid_env):
    """Return a fully initialised WatsonXClient."""
    return WatsonXClient(model_name="ibm/granite-13b-chat-v2")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestWatsonXClientInit:
    """Tests for __init__ validation and setup."""

    def test_init_success_from_env(self, *, mock_iam_manager, valid_env):
        c = WatsonXClient(model_name="ibm/granite-13b-chat-v2")
        assert c.model_name == "ibm/granite-13b-chat-v2"
        assert c.api_key == "test-api-key"  # pragma: allowlist secret
        assert c.container_id == "test-container-id"
        assert c.api_base == "https://us-south.ml.cloud.ibm.com"
        assert c.container_kind == "project"

    def test_init_success_from_params(self, *, mock_iam_manager):
        c = WatsonXClient(
            model_name="ibm/granite-13b-chat-v2",
            api_key="p-key",  # pragma: allowlist secret
            container_id="p-container",
            api_base="https://custom.ibm.com",
            container_kind="space",
        )
        assert c.api_key == "p-key"  # pragma: allowlist secret
        assert c.container_id == "p-container"
        assert c.container_kind == "space"

    def test_init_missing_api_key_raises(self, *, mock_iam_manager, monkeypatch):
        monkeypatch.delenv("WATSONX_API_KEY", raising=False)
        monkeypatch.setenv("WATSONX_CONTAINER_ID", "cid")
        monkeypatch.setenv("WATSONX_API_BASE_URL", "https://api.ibm.com")
        with pytest.raises(ConfigurationError, match="WATSONX_API_KEY"):
            WatsonXClient(model_name="ibm/granite-13b-chat-v2")

    def test_init_missing_container_id_raises(self, *, mock_iam_manager, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key")  # pragma: allowlist secret
        monkeypatch.delenv("WATSONX_CONTAINER_ID", raising=False)
        monkeypatch.setenv("WATSONX_API_BASE_URL", "https://api.ibm.com")
        with pytest.raises(ConfigurationError, match="WATSONX_CONTAINER_ID"):
            WatsonXClient(model_name="ibm/granite-13b-chat-v2")

    def test_init_missing_api_base_raises(self, *, mock_iam_manager, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key")  # pragma: allowlist secret
        monkeypatch.setenv("WATSONX_CONTAINER_ID", "cid")
        monkeypatch.delenv("WATSONX_API_BASE_URL", raising=False)
        with pytest.raises(ConfigurationError, match="api_base is required"):
            WatsonXClient(model_name="ibm/granite-13b-chat-v2")

    def test_init_invalid_container_kind_raises(self, *, mock_iam_manager, valid_env):
        with pytest.raises(ConfigurationError, match="container_kind must be"):
            WatsonXClient(
                model_name="ibm/granite-13b-chat-v2",
                container_kind="invalid",
            )

    def test_init_space_container_kind(self, *, mock_iam_manager, valid_env):
        c = WatsonXClient(model_name="ibm/granite-13b-chat-v2", container_kind="space")
        assert c.container_kind == "space"


# ---------------------------------------------------------------------------
# _get_access_token
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    """Tests for _get_access_token."""

    def test_returns_token(self, *, client):
        token = client._get_access_token()
        assert token == "mock-iam-token"

    def test_token_failure_raises_external_service_error(self, *, mock_iam_manager, valid_env):
        mock_iam_manager.return_value.get_token.side_effect = RuntimeError("auth failed")
        c = WatsonXClient(model_name="ibm/granite-13b-chat-v2")
        with pytest.raises(ExternalServiceError, match="Failed to authenticate"):
            c._get_access_token()


# ---------------------------------------------------------------------------
# _get_rest_client
# ---------------------------------------------------------------------------


class TestGetRestClient:
    """Tests for _get_rest_client."""

    def test_returns_rest_client(self, *, client):
        with patch("docpipe.integrations.watsonx.client.RestClient") as mock_rest_cls:
            mock_rest_cls.return_value = MagicMock()
            rc = client._get_rest_client()
            assert rc is not None
            mock_rest_cls.assert_called_once()


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


class TestWatsonXClientChat:
    """Tests for chat method."""

    def _mock_rest_client(self, content: str):
        mock_rc = MagicMock()
        mock_rc.call_rest_json.return_value = {"choices": [{"message": {"content": content}}]}
        return mock_rc

    def test_chat_success_user_message(self, *, client, mock_iam_manager):
        mock_rc = self._mock_rest_client("response text")
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            result = client.chat([{"role": "user", "content": "hello"}])
        assert result == "response text"

    def test_chat_success_system_message(self, *, client, mock_iam_manager):
        """System messages use simple string content format."""
        mock_rc = self._mock_rest_client("ack")
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            result = client.chat(
                [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "hi"},
                ]
            )
        assert result == "ack"

    def test_chat_success_space_container_kind(self, *, mock_iam_manager, valid_env):
        """container_kind=space uses space_id in payload."""
        c = WatsonXClient(model_name="ibm/granite-13b-chat-v2", container_kind="space")
        mock_rc = MagicMock()
        mock_rc.call_rest_json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        with patch.object(c, "_get_rest_client", return_value=mock_rc):
            result = c.chat([{"role": "user", "content": "test"}])
        assert result == "hi"
        call_kwargs = mock_rc.call_rest_json.call_args
        payload = call_kwargs.kwargs["json_data"]
        assert "space_id" in payload

    def test_chat_empty_messages_raises(self, *, client):
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.chat([])

    def test_chat_non_list_messages_raises(self, *, client):
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.chat("not a list")  # type: ignore

    def test_chat_no_choices_raises(self, *, client):
        mock_rc = MagicMock()
        mock_rc.call_rest_json.return_value = {"choices": []}
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            with pytest.raises(ExternalServiceError, match="No choices"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_empty_content_raises(self, *, client):
        mock_rc = MagicMock()
        mock_rc.call_rest_json.return_value = {"choices": [{"message": {"content": ""}}]}
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            with pytest.raises(ExternalServiceError, match="Empty content"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_external_service_error_reraises(self, *, client):
        """ExternalServiceError from rest client is re-raised directly."""
        with patch.object(client, "_get_rest_client", side_effect=ExternalServiceError("upstream fail")):
            with pytest.raises(ExternalServiceError, match="upstream fail"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_unexpected_exception_wrapped(self, *, client):
        """Non-ExternalServiceError exceptions are wrapped."""
        with patch.object(client, "_get_rest_client", side_effect=RuntimeError("unexpected")):
            with pytest.raises(ExternalServiceError, match="WatsonX chat failed"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_custom_kwargs_forwarded(self, *, client):
        mock_rc = self._mock_rest_client("ok")
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            result = client.chat(
                [{"role": "user", "content": "hi"}],
                max_tokens=200,
                temperature=0.5,
            )
        assert result == "ok"
        payload = mock_rc.call_rest_json.call_args.kwargs["json_data"]
        assert payload["max_tokens"] == 200
        assert payload["temperature"] == 0.5


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestWatsonXClientGenerate:
    """Tests for generate."""

    def test_generate_delegates_to_chat(self, *, client):
        mock_rc = MagicMock()
        mock_rc.call_rest_json.return_value = {"choices": [{"message": {"content": "generated"}}]}
        with patch.object(client, "_get_rest_client", return_value=mock_rc):
            result = client.generate("tell me a story")
        assert result == "generated"


# ---------------------------------------------------------------------------
# Unsupported methods
# ---------------------------------------------------------------------------


class TestUnsupportedMethods:
    """Tests for methods that raise NotImplementedError."""

    def test_generate_embeddings_raises(self, *, client):
        with pytest.raises(NotImplementedError):
            client.generate_embeddings("text")

    def test_generate_embeddings_batch_raises(self, *, client):
        with pytest.raises(NotImplementedError):
            client.generate_embeddings_batch(["text"])

    def test_get_model_token_limit_raises(self):
        with pytest.raises(NotImplementedError):
            WatsonXClient.get_model_token_limit("ibm/granite-13b-chat-v2")

    def test_get_embedding_dimension_returns_zero(self):
        assert WatsonXClient.get_embedding_dimension("ibm/granite-13b-chat-v2") == 0


# ---------------------------------------------------------------------------
# validate_configuration
# ---------------------------------------------------------------------------


class TestValidateConfiguration:
    """Tests for validate_configuration."""

    def test_validate_passes_with_valid_config(self, *, client):
        client.validate_configuration()  # should not raise

    def test_validate_fails_without_api_key(self, *, client):
        client.api_key = None
        with pytest.raises(ConfigurationError, match="WATSONX_API_KEY"):
            client.validate_configuration()

    def test_validate_fails_without_container_id(self, *, client):
        client.container_id = None
        with pytest.raises(ConfigurationError, match="WATSONX_CONTAINER_ID"):
            client.validate_configuration()

    def test_validate_fails_without_api_base(self, *, client):
        client.api_base = None
        with pytest.raises(ConfigurationError, match="api_base is required"):
            client.validate_configuration()

    def test_validate_fails_with_invalid_container_kind(self, *, client):
        client.container_kind = "invalid"
        with pytest.raises(ConfigurationError, match="container_kind must be"):
            client.validate_configuration()
