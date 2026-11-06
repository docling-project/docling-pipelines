# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WeaviateClient."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestWeaviateClient:
    """Test suite for WeaviateClient connection, authentication, and error handling."""

    @patch("weaviate.connect_to_custom")
    def test_custom_connection_none_auth(self, mock_connect: MagicMock) -> None:
        """Verify custom connection with auth_type='none'."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="wv-host",
            port=8080,
            secure=False,
            grpc_port=50051,
            auth_type="none",
        )
        sdk_client = client.connect()

        assert sdk_client == mock_instance
        mock_connect.assert_called_once()
        kwargs = mock_connect.call_args.kwargs
        assert kwargs["http_host"] == "wv-host"
        assert kwargs["http_port"] == 8080
        assert kwargs["http_secure"] is False
        assert kwargs["grpc_host"] == "wv-host"
        assert kwargs["grpc_port"] == 50051
        assert kwargs["grpc_secure"] is False
        assert kwargs["auth_credentials"] is None

    @patch("weaviate.connect_to_weaviate_cloud")
    def test_cloud_connection_api_key(self, mock_connect: MagicMock) -> None:
        """Verify cloud connection with api_key auth."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="cloud",
            cluster_url="https://test.weaviate.cloud",
            auth_type="api_key",
            api_key="my-api-key",  # pragma: allowlist secret
        )
        sdk_client = client.connect()

        assert sdk_client == mock_instance
        mock_connect.assert_called_once()
        kwargs = mock_connect.call_args.kwargs
        assert kwargs["cluster_url"] == "https://test.weaviate.cloud"
        assert kwargs["auth_credentials"] is not None

    @patch("weaviate.connect_to_custom")
    def test_custom_connection_bearer_token(self, mock_connect: MagicMock) -> None:
        """Verify custom connection with bearer_token auth."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="wv-host",
            port=8080,
            secure=True,
            grpc_secure=True,
            auth_type="bearer_token",
            bearer_token="my-token",
        )
        client.connect()
        mock_connect.assert_called_once()
        assert mock_connect.call_args.kwargs["auth_credentials"] is not None

    @patch("weaviate.connect_to_custom")
    def test_custom_connection_client_password(self, mock_connect: MagicMock) -> None:
        """Verify custom connection with client_password auth."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="wv-host",
            port=8080,
            secure=True,
            grpc_secure=True,
            auth_type="client_password",
            username="admin",
            password="secret-password",  # pragma: allowlist secret
        )
        client.connect()
        mock_connect.assert_called_once()
        assert mock_connect.call_args.kwargs["auth_credentials"] is not None

    def test_plaintext_guard_custom_auth(self) -> None:
        """Verify plaintext guard rejects authenticated custom connections without calling connect."""
        client = WeaviateClient(
            connection_type="custom",
            host="localhost",
            port=8080,
            secure=False,
            auth_type="api_key",
            api_key="secret",  # pragma: allowlist secret
        )
        with patch("weaviate.connect_to_custom") as mock_connect:
            with pytest.raises(DocpipeException) as exc_info:
                client.connect()
            assert exc_info.value.status_code == 400
            assert "secure and grpc_secure must both be true" in str(exc_info.value)
            mock_connect.assert_not_called()

    @patch("weaviate.connect_to_custom")
    def test_env_var_resolution_in_client(
        self,
        mock_connect: MagicMock,
        *,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify environment variable expansion for credentials."""
        monkeypatch.setenv("TEST_WV_KEY", "actual-secret-key-123")
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="wv-host",
            secure=True,
            grpc_secure=True,
            auth_type="api_key",
            api_key="${TEST_WV_KEY}",
        )
        client.connect()
        mock_connect.assert_called_once()

    def test_unset_env_var_raises_exception(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify unset environment variable raises DocpipeException with 400 status."""
        monkeypatch.delenv("UNSET_KEY_XYZ", raising=False)
        client = WeaviateClient(
            connection_type="custom",
            host="wv-host",
            secure=True,
            grpc_secure=True,
            auth_type="api_key",
            api_key="${UNSET_KEY_XYZ}",
        )
        with pytest.raises(DocpipeException) as exc_info:
            client.connect()
        assert exc_info.value.status_code == 400
        assert "UNSET_KEY_XYZ is not set" in str(exc_info.value)

    @patch("weaviate.connect_to_custom")
    def test_not_ready_closes_client_and_raises_503(self, mock_connect: MagicMock) -> None:
        """Verify client.is_ready() False closes SDK client and raises 503."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = False
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="localhost",
            port=8080,
            secure=False,
            auth_type="none",
        )
        with pytest.raises(DocpipeException) as exc_info:
            client.connect()

        assert exc_info.value.status_code == 503
        assert "is not ready" in str(exc_info.value)
        mock_instance.close.assert_called_once()
        assert client._client is None

    @patch("weaviate.connect_to_custom")
    def test_exception_after_connect_closes_client(self, mock_connect: MagicMock) -> None:
        """Verify an error during readiness check closes SDK client and raises 503."""
        mock_instance = MagicMock()
        mock_instance.is_ready.side_effect = RuntimeError("Readiness probe crashed")
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="localhost",
            port=8080,
            secure=False,
            auth_type="none",
        )
        with pytest.raises(DocpipeException) as exc_info:
            client.connect()

        assert exc_info.value.status_code == 503
        mock_instance.close.assert_called_once()
        assert client._client is None

    @patch("weaviate.connect_to_custom")
    def test_secret_redaction_in_exceptions_and_logs(
        self,
        mock_connect: MagicMock,
        *,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify configured secrets and Authorization headers are redacted in exceptions and logs."""
        secret = "super_confidential_key_999"  # pragma: allowlist secret
        mock_connect.side_effect = Exception(f"Connection failed: invalid auth for Bearer {secret} and token {secret}")

        client = WeaviateClient(
            connection_type="custom",
            host="localhost",
            port=8080,
            secure=True,
            grpc_secure=True,
            auth_type="api_key",
            api_key=secret,
        )

        with caplog.at_level(logging.INFO):
            with pytest.raises(DocpipeException) as exc_info:
                client.connect()

        err_msg = str(exc_info.value)
        assert secret not in err_msg
        assert "***" in err_msg

        # Also check caplog text
        assert secret not in caplog.text

    @patch("weaviate.connect_to_custom")
    def test_idempotent_close(self, mock_connect: MagicMock) -> None:
        """Verify close is idempotent and does not fail on multiple calls."""
        mock_instance = MagicMock()
        mock_instance.is_ready.return_value = True
        mock_connect.return_value = mock_instance

        client = WeaviateClient(
            connection_type="custom",
            host="localhost",
            port=8080,
            secure=False,
            auth_type="none",
        )
        client.connect()
        assert client._client is not None

        client.close()
        mock_instance.close.assert_called_once()
        assert client._client is None

        # Second close should be a no-op
        client.close()
        assert mock_instance.close.call_count == 1
