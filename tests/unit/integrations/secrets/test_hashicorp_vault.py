# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for HashiCorp Vault provider (REST API based, no hvac dependency).

All tests are pure unit tests — every HTTP call is intercepted via MagicMock/patch.
No running Vault instance is required. Tests run in any environment without
external dependencies.
"""

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.hashicorp_vault import (
    HashiCorpVaultConfig,
    HashiCorpVaultProvider,
    _read_env_or_file,
)


class TestReadEnvOrFile:
    """Tests for _read_env_or_file helper."""

    def test_reads_from_env_var(self):
        with patch.dict(os.environ, {"TEST_VAR": "env_value"}, clear=False):
            result = _read_env_or_file("TEST_VAR")
            assert result == "env_value"

    def test_reads_from_file_when_file_env_set(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("  file_value  \n")
            f.flush()

            try:
                with patch.dict(
                    os.environ,
                    {"TEST_VAR_FILE": f.name, "TEST_VAR": "should_be_ignored"},
                    clear=False,
                ):
                    result = _read_env_or_file("TEST_VAR")
                    # File takes precedence over direct env var
                    assert result == "file_value"
            finally:
                Path(f.name).unlink()

    def test_file_path_not_existing_falls_back_to_env(self):
        with patch.dict(
            os.environ,
            {"TEST_VAR_FILE": "/nonexistent/path", "TEST_VAR": "fallback_value"},
            clear=False,
        ):
            result = _read_env_or_file("TEST_VAR")
            assert result == "fallback_value"

    def test_returns_default_when_nothing_set(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("MISSING_")}
        with patch.dict(os.environ, env, clear=True):
            result = _read_env_or_file("MISSING_VAR", default="default_val")
            assert result == "default_val"

    def test_returns_empty_string_when_no_default(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("MISSING_")}
        with patch.dict(os.environ, env, clear=True):
            result = _read_env_or_file("MISSING_VAR")
            assert result == ""


class TestHashiCorpVaultConfig:
    """Tests for HashiCorpVaultConfig dataclass."""

    def test_defaults_from_environment(self):
        env_vars = {
            "VAULT_ADDR": "https://vault.test.com",
            "VAULT_ROLE_ID": "test-role-id",
            "VAULT_SECRET_ID": "test-secret-id",
            "VAULT_MOUNT_POINT": "kv",
            "VAULT_NAMESPACE": "test-ns",
            "VAULT_CA_CERT": "/etc/vault/ca.pem",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = HashiCorpVaultConfig()
            assert config.addr == "https://vault.test.com"
            assert config.role_id == "test-role-id"
            assert config.secret_id == "test-secret-id"
            assert config.mount_point == "kv"
            assert config.namespace == "test-ns"
            assert config.ca_cert == "/etc/vault/ca.pem"

    def test_validate_missing_role_id_raises(self):
        config = HashiCorpVaultConfig()
        config.role_id = ""
        config.secret_id = "some-secret-id"
        with pytest.raises(ConfigurationError, match="VAULT_ROLE_ID"):
            config.validate()

    def test_validate_missing_secret_id_raises(self):
        config = HashiCorpVaultConfig()
        config.role_id = "some-role-id"
        config.secret_id = ""
        with pytest.raises(ConfigurationError, match="VAULT_SECRET_ID"):
            config.validate()

    def test_validate_passes_with_both_set(self):
        config = HashiCorpVaultConfig()
        config.role_id = "role"
        config.secret_id = "secret"  # pragma: allowlist secret
        config.addr = "http://vault:8200"
        # Should not raise
        config.validate()

    def test_tls_skip_verify_parsing(self):
        with patch.dict(os.environ, {"VAULT_TLS_SKIP_VERIFY": "true"}, clear=False):
            config = HashiCorpVaultConfig()
            assert config.tls_skip_verify is True

        with patch.dict(os.environ, {"VAULT_TLS_SKIP_VERIFY": "false"}, clear=False):
            config = HashiCorpVaultConfig()
            assert config.tls_skip_verify is False


class TestHashiCorpVaultProvider:
    """Tests for HashiCorpVaultProvider."""

    def _make_config(self) -> HashiCorpVaultConfig:
        """Create a test config."""
        config = HashiCorpVaultConfig()
        config.addr = "https://vault.test:8200"
        config.role_id = "test-role-id"
        config.secret_id = "test-secret-id"
        config.mount_point = "secret"
        config.approle_mount_point = "approle"
        config.namespace = None
        config.ca_cert = None
        config.client_cert = None
        config.client_key = None
        config.tls_skip_verify = False
        return config

    def test_authenticate_posts_to_approle_login(self):
        """Test that authenticate POSTs to the AppRole login endpoint."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "auth": {
                "client_token": "s.test-token-123",
                "lease_duration": 3600,
                "renewable": True,
            }
        }

        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_response
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            provider.authenticate()

            mock_session.post.assert_called_once_with(
                "https://vault.test:8200/v1/auth/approle/login",
                json={"role_id": "test-role-id", "secret_id": "test-secret-id"},
                timeout=(5, 30),
                allow_redirects=False,
            )
            # Token should be set in session headers
            assert mock_session.headers["X-Vault-Token"] == "s.test-token-123"

    def test_authenticate_failure_raises_external_service_error(self):
        """Test that non-200 response raises ExternalServiceError."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "permission denied"

        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_response
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            with pytest.raises(ExternalServiceError, match="AppRole login failed"):
                provider.authenticate()

    def test_get_secret_kv_v2(self):
        """Test get_secret reads from KV v2 API."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        # Set up pre-authenticated state
        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"data": {"username": "admin", "password": "s3cret"}}  # pragma: allowlist secret
        }
        mock_session.get.return_value = mock_response

        result = provider.get_secret(path="db/postgres", key="password")
        assert result == "s3cret"

        mock_session.get.assert_called_once_with(
            "https://vault.test:8200/v1/secret/data/db/postgres",
            timeout=(5, 30),
            allow_redirects=False,
        )

    def test_get_secret_kv_v1_fallback(self):
        """Test fallback to KV v1 only when v2 returns 404."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        # KV v2 returns 404 — the only status that triggers KV v1 fallback
        kv2_response = MagicMock()
        kv2_response.status_code = 404

        # KV v1 returns data
        kv1_response = MagicMock()
        kv1_response.status_code = 200
        kv1_response.json.return_value = {"data": {"password": "v1_secret"}}  # pragma: allowlist secret

        mock_session.get.side_effect = [kv2_response, kv1_response]

        result = provider.get_secret(path="legacy/secret", key="password")
        assert result == "v1_secret"

    def test_get_secret_kv_v2_permission_denied_raises_immediately(self):
        """Test that 403 from KV v2 raises immediately without falling back to KV v1."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        kv2_response = MagicMock()
        kv2_response.status_code = 403
        kv2_response.text = "permission denied"
        mock_session.get.return_value = kv2_response

        with pytest.raises(ExternalServiceError, match="403"):
            provider.get_secret(path="db/creds", key="password")

        # KV v1 must never be attempted
        mock_session.get.assert_called_once()

    def test_get_secret_kv_v2_non_404_error_raises_immediately(self):
        """Test that non-404/non-200 responses from KV v2 raise without KV v1 fallback."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        for status_code in (400, 429, 500, 503):
            mock_session.reset_mock()
            kv2_response = MagicMock()
            kv2_response.status_code = status_code
            kv2_response.text = "error"
            mock_session.get.return_value = kv2_response

            with pytest.raises(ExternalServiceError, match=str(status_code)):
                provider.get_secret(path="db/creds", key="password")

            # KV v1 must never be attempted for any of these
            mock_session.get.assert_called_once()

    def test_get_secret_single_value_no_key(self):
        """Test get_secret with single-value secret and no key."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"data": {"value": "single_secret"}}}
        mock_session.get.return_value = mock_response

        result = provider.get_secret(path="api/key")
        assert result == "single_secret"

    def test_get_secret_multiple_keys_no_key_raises(self):
        """Test that multiple keys without specifying one raises ValueError."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"data": {"user": "admin", "pass": "secret"}}}
        mock_session.get.return_value = mock_response

        with pytest.raises(ConfigurationError, match="Multiple keys"):
            provider.get_secret(path="db/creds")

    def test_get_secret_missing_key_raises_external_service_error(self):
        """Test that a missing key raises ExternalServiceError."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {"X-Vault-Token": "s.token"}
        provider._session = mock_session
        provider._token = "s.token"
        provider._token_expiry = float("inf")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"data": {"user": "admin"}}}
        mock_session.get.return_value = mock_response

        with pytest.raises(ExternalServiceError, match="nonexistent"):
            provider.get_secret(path="db/creds", key="nonexistent")

    def test_is_available_returns_true_on_200(self):
        """Test is_available with healthy Vault."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        mock_session = MagicMock()
        mock_session.headers = {}
        provider._session = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response

        assert provider.is_available() is True
        mock_session.get.assert_called_with(
            "https://vault.test:8200/v1/sys/health", timeout=(5, 5), allow_redirects=False
        )

    def test_is_available_returns_false_on_exception(self):
        """Test is_available returns False when Vault is unreachable."""
        config = self._make_config()
        config.role_id = ""  # Invalid config
        provider = HashiCorpVaultProvider(config=config)

        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            assert provider.is_available() is False

    def test_tls_config_with_ca_cert(self):
        """Test that CA cert path is set on session.verify."""
        config = self._make_config()

        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            config.ca_cert = f.name

        try:
            provider = HashiCorpVaultProvider(config=config)
            session = provider._build_session()
            assert session.verify == f.name
        finally:
            Path(f.name).unlink()

    def test_tls_skip_verify(self):
        """Test that tls_skip_verify sets verify=False."""
        config = self._make_config()
        config.addr = "http://127.0.0.1:8200"
        config.tls_skip_verify = True

        provider = HashiCorpVaultProvider(config=config)
        session = provider._build_session()
        assert session.verify is False

    def test_mtls_with_client_cert(self):
        """Test that client cert and key are set on session."""
        config = self._make_config()

        with tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as cert_f:
            config.client_cert = cert_f.name
        with tempfile.NamedTemporaryFile(suffix=".key", delete=False) as key_f:
            config.client_key = key_f.name

        try:
            provider = HashiCorpVaultProvider(config=config)
            session = provider._build_session()
            assert session.cert == (cert_f.name, key_f.name)
        finally:
            Path(cert_f.name).unlink()
            Path(key_f.name).unlink()

    def test_namespace_header_set(self):
        """Test that Vault namespace is set as header."""
        config = self._make_config()
        config.namespace = "my-namespace"

        provider = HashiCorpVaultProvider(config=config)
        session = provider._build_session()
        assert session.headers["X-Vault-Namespace"] == "my-namespace"

    def test_re_authentication_on_expired_token(self):
        """Test that get_secret re-authenticates when token is expired."""
        config = self._make_config()
        provider = HashiCorpVaultProvider(config=config)

        # Simulate expired token
        provider._token = "s.expired"
        provider._token_expiry = 0  # Already expired

        mock_session = MagicMock()
        mock_session.headers = {}
        provider._session = mock_session

        # Mock auth response
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {"auth": {"client_token": "s.new-token", "lease_duration": 3600}}

        # Mock secret response
        secret_response = MagicMock()
        secret_response.status_code = 200
        secret_response.json.return_value = {"data": {"data": {"value": "refreshed_secret"}}}

        mock_session.post.return_value = auth_response
        mock_session.get.return_value = secret_response

        result = provider.get_secret(path="test/path")
        assert result == "refreshed_secret"
        # Verify re-authentication happened
        mock_session.post.assert_called_once()


_CANARY = "CANARY-vault-body-7f3a9c"  # pragma: allowlist secret
_ADDR_CANARY = "vault-canary-host.internal"


def _authenticated_provider(config: HashiCorpVaultConfig) -> tuple[HashiCorpVaultProvider, MagicMock]:
    provider = HashiCorpVaultProvider(config=config)
    mock_session = MagicMock()
    mock_session.headers = {"X-Vault-Token": "s.token"}
    provider._session = mock_session
    provider._token = "s.token"
    provider._token_expiry = float("inf")
    return provider, mock_session


def _error_response(*, status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = _CANARY
    response.content = _CANARY.encode()
    response.headers = {
        "Content-Type": "application/json",
        "X-Vault-Request-Id": "req-1",
        "Set-Cookie": _CANARY,
        "X-Echo": _CANARY,
    }
    return response


class TestVaultResponseBodyNeverExposed:
    """A response body must never reach an error message or any log record."""

    def _make_config(self) -> HashiCorpVaultConfig:
        return TestHashiCorpVaultProvider._make_config(TestHashiCorpVaultProvider())  # type: ignore[arg-type]

    def test_login_failure_hides_body(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider = HashiCorpVaultProvider(config=self._make_config())

        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post.return_value = _error_response(status_code=403)
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            with pytest.raises(ExternalServiceError) as exc_info:
                provider.authenticate()

        assert "403" in str(exc_info.value)
        assert _CANARY not in str(exc_info.value)
        assert "HTTP 403" in caplog.text  # the failure was logged, so the absence checks below are meaningful
        assert _CANARY not in caplog.text
        for record in caplog.records:
            assert _CANARY not in record.getMessage()
            assert "test-role-id" not in record.getMessage()
            assert "test-secret-id" not in record.getMessage()

    @pytest.mark.parametrize("status_code", [400, 403, 429, 500, 503])
    def test_kv2_failure_hides_body(self, status_code: int, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider, mock_session = _authenticated_provider(self._make_config())
        mock_session.get.return_value = _error_response(status_code=status_code)

        with pytest.raises(ExternalServiceError) as exc_info:
            provider.get_secret(path="db/creds", key="password")

        assert str(status_code) in str(exc_info.value)
        assert _CANARY not in str(exc_info.value)
        assert f"HTTP {status_code}" in caplog.text
        assert _CANARY not in caplog.text
        assert "db/creds" not in str(exc_info.value)

    def test_kv1_failure_hides_body(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider, mock_session = _authenticated_provider(self._make_config())
        kv2_missing = MagicMock()
        kv2_missing.status_code = 404
        mock_session.get.side_effect = [kv2_missing, _error_response(status_code=500)]

        with pytest.raises(ExternalServiceError) as exc_info:
            provider.get_secret(path="legacy/secret", key="password")

        assert "500" in str(exc_info.value)
        assert _CANARY not in str(exc_info.value)
        assert "HTTP 500" in caplog.text
        assert _CANARY not in caplog.text

    def test_debug_log_records_allowlisted_headers_only(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider, mock_session = _authenticated_provider(self._make_config())
        mock_session.get.return_value = _error_response(status_code=403)

        with pytest.raises(ExternalServiceError):
            provider.get_secret(path="db/creds", key="password")

        assert "HTTP 403" in caplog.text
        assert "req-1" in caplog.text
        assert "application/json" in caplog.text
        assert _CANARY not in caplog.text
        assert "Set-Cookie" not in caplog.text
        assert "s.token" not in caplog.text


class TestVaultTransportErrorsAreCategoryOnly:
    """requests exceptions become category-only errors that never disclose the endpoint."""

    def _make_config(self) -> HashiCorpVaultConfig:
        config = TestHashiCorpVaultProvider._make_config(TestHashiCorpVaultProvider())  # type: ignore[arg-type]
        config.addr = f"https://{_ADDR_CANARY}:8200"
        return config

    @pytest.mark.parametrize(
        ("exc", "category"),
        [
            (requests.exceptions.ConnectionError(f"HTTPSConnectionPool(host='{_ADDR_CANARY}')"), "connection failed"),
            (requests.exceptions.ConnectTimeout(f"timed out {_ADDR_CANARY}"), "request timed out"),
            (requests.exceptions.ReadTimeout(f"timed out {_ADDR_CANARY}"), "request timed out"),
            (requests.exceptions.SSLError(f"bad cert for {_ADDR_CANARY}"), "TLS verification failed"),
            (requests.exceptions.TooManyRedirects(f"{_ADDR_CANARY}"), "request failed"),
        ],
    )
    def test_login_exception_is_category_only(self, exc: Exception, category: str) -> None:
        provider = HashiCorpVaultProvider(config=self._make_config())

        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post.side_effect = exc
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            with pytest.raises(ExternalServiceError) as exc_info:
                provider.authenticate()

        assert category in str(exc_info.value)
        assert _ADDR_CANARY not in str(exc_info.value)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True

    @pytest.mark.parametrize("failing_call", [0, 1])
    def test_read_exception_is_category_only(self, failing_call: int) -> None:
        provider, mock_session = _authenticated_provider(self._make_config())
        kv2_missing = MagicMock()
        kv2_missing.status_code = 404
        boom = requests.exceptions.ConnectionError(f"HTTPSConnectionPool(host='{_ADDR_CANARY}')")
        mock_session.get.side_effect = [boom] if failing_call == 0 else [kv2_missing, boom]

        with pytest.raises(ExternalServiceError) as exc_info:
            provider.get_secret(path="db/creds", key="password")

        assert "connection failed" in str(exc_info.value)
        assert _ADDR_CANARY not in str(exc_info.value)
        assert "db/creds" not in str(exc_info.value)
        assert exc_info.value.__cause__ is None

    def test_availability_failure_logs_category_only(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider, mock_session = _authenticated_provider(self._make_config())
        mock_session.get.side_effect = requests.exceptions.ConnectionError(f"host={_ADDR_CANARY}")

        assert provider.is_available() is False

        assert "connection failed" in caplog.text
        assert _ADDR_CANARY not in caplog.text
        for record in caplog.records:
            assert record.exc_info is None


class TestVaultRedirectsAndTimeouts:
    def _make_config(self) -> HashiCorpVaultConfig:
        return TestHashiCorpVaultProvider._make_config(TestHashiCorpVaultProvider())  # type: ignore[arg-type]

    def test_login_read_and_health_never_follow_redirects(self) -> None:
        provider, mock_session = _authenticated_provider(self._make_config())
        kv2_missing = MagicMock()
        kv2_missing.status_code = 404
        kv1_ok = MagicMock()
        kv1_ok.status_code = 200
        kv1_ok.json.return_value = {"data": {"k": "v"}}
        mock_session.get.side_effect = [kv2_missing, kv1_ok]

        provider.get_secret(path="p", key="k")
        for call in mock_session.get.call_args_list:
            assert call.kwargs["allow_redirects"] is False

        mock_session.get.reset_mock(side_effect=True)
        mock_session.get.return_value = MagicMock(status_code=200)
        provider.is_available()
        assert mock_session.get.call_args.kwargs["allow_redirects"] is False

    def test_redirect_response_is_not_followed_and_fails(self) -> None:
        """A 307 to another host is an error and the token is never sent onward."""
        provider, mock_session = _authenticated_provider(self._make_config())
        redirect = MagicMock()
        redirect.status_code = 307
        redirect.text = _CANARY
        redirect.headers = {"Location": "https://evil.example/steal"}
        mock_session.get.return_value = redirect

        with pytest.raises(ExternalServiceError, match="307") as exc_info:
            provider.get_secret(path="db/creds", key="password")

        assert "evil.example" not in str(exc_info.value)
        mock_session.get.assert_called_once()

    def test_timeouts_are_connect_read_tuples(self) -> None:
        from docpipe.integrations.secrets import hashicorp_vault

        for timeout in (hashicorp_vault._REQUEST_TIMEOUT, hashicorp_vault._HEALTH_TIMEOUT):
            assert isinstance(timeout, tuple)
            assert len(timeout) == 2
            assert all(isinstance(value, int | float) and value > 0 for value in timeout)


class TestVaultTransportValidation:
    def _config(self, *, addr: str, skip_verify: bool = False) -> HashiCorpVaultConfig:
        config = TestHashiCorpVaultProvider._make_config(TestHashiCorpVaultProvider())  # type: ignore[arg-type]
        config.addr = addr
        config.tls_skip_verify = skip_verify
        return config

    @pytest.mark.parametrize(
        "addr",
        [
            "https://vault.internal:8200",
            "http://127.0.0.1:8200",
            "http://localhost:8200",
            "http://LOCALHOST:8200",
            "http://[::1]:8200",
            "http://127.1.2.3:8200",
            "https://127.0.0.1:8200",
        ],
    )
    def test_permitted_addresses(self, addr: str) -> None:
        self._config(addr=addr).validate_transport()

    @pytest.mark.parametrize(
        "addr",
        [
            f"http://{_ADDR_CANARY}:8200",
            "http://10.0.0.5:8200",
            "http://vault.localhost.evil.example:8200",
            "http://127.0.0.1.evil.example:8200",
            "ftp://vault.internal:8200",
            "vault.internal:8200",
            "https://",
            "",
        ],
    )
    def test_plaintext_or_invalid_address_refused_without_echo(self, addr: str) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            self._config(addr=addr).validate_transport()
        assert _ADDR_CANARY not in str(exc_info.value)
        assert "10.0.0.5" not in str(exc_info.value)

    @pytest.mark.parametrize("addr", ["https://vault.internal:8200", "http://vault.internal:8200", "https://10.0.0.5"])
    def test_skip_verify_on_remote_host_refused(self, addr: str) -> None:
        with pytest.raises(ConfigurationError, match="loopback"):
            self._config(addr=addr, skip_verify=True).validate_transport()

    @pytest.mark.parametrize("addr", ["http://127.0.0.1:8200", "https://localhost:8200", "http://[::1]:8200"])
    def test_skip_verify_honored_on_loopback(self, addr: str) -> None:
        self._config(addr=addr, skip_verify=True).validate_transport()
        session = HashiCorpVaultProvider(config=self._config(addr=addr, skip_verify=True))._build_session()
        assert session.verify is False

    def test_build_session_refuses_plaintext_remote(self) -> None:
        provider = HashiCorpVaultProvider(config=self._config(addr="http://vault.internal:8200"))
        with pytest.raises(ConfigurationError, match="https"):
            provider._build_session()

    def test_authenticate_refuses_plaintext_remote_before_any_request(self) -> None:
        provider = HashiCorpVaultProvider(config=self._config(addr="http://vault.internal:8200"))
        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            with pytest.raises(ConfigurationError):
                provider.authenticate()
            mock_session_cls.return_value.post.assert_not_called()

    def test_is_available_false_for_unsafe_transport(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider = HashiCorpVaultProvider(config=self._config(addr=f"http://{_ADDR_CANARY}:8200"))
        with patch("docpipe.integrations.secrets.hashicorp_vault.requests.Session") as mock_session_cls:
            assert provider.is_available() is False
            mock_session_cls.return_value.get.assert_not_called()
        assert "availability check failed" in caplog.text
        assert _ADDR_CANARY not in caplog.text
