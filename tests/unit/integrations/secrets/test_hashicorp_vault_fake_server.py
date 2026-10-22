"""HashiCorpVaultProvider tests against an in-process fake of the Vault HTTP API.

The provider talks to Vault through a real ``requests.Session``. These tests mount a
transport adapter on that session which answers like a Vault server would (AppRole
login, KV v2 and KV v1 reads), so the provider's TLS settings, headers, status-code
handling and error wrapping run unmodified. No Vault server is needed.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests
from requests.adapters import BaseAdapter

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.hashicorp_vault import HashiCorpVaultProvider

VAULT_ADDR = "http://vault.test:8200"
ROLE_ID = "11111111-2222-3333-4444-555555555555"
SECRET_ID = "66666666-7777-8888-9999-000000000000"  # pragma: allowlist secret
CLIENT_TOKEN = "hvs.CAESIfakeclienttoken"  # pragma: allowlist secret

_VAULT_ENV_VARS = (
    "VAULT_ADDR",
    "VAULT_ROLE_ID",
    "VAULT_ROLE_ID_FILE",
    "VAULT_SECRET_ID",
    "VAULT_SECRET_ID_FILE",
    "VAULT_MOUNT_POINT",
    "VAULT_APPROLE_MOUNT",
    "VAULT_NAMESPACE",
    "VAULT_CA_CERT",
    "VAULT_CLIENT_CERT",
    "VAULT_CLIENT_KEY",
    "VAULT_TLS_SKIP_VERIFY",
)

_RealSession = requests.Session


def _envelope(**overrides: Any) -> dict[str, Any]:
    """Return the response envelope Vault wraps around every successful reply."""
    body: dict[str, Any] = {
        "request_id": "0d6c7a4e-2f7b-4a7e-9a52-3f1d8a2b6c11",
        "lease_id": "",
        "renewable": False,
        "lease_duration": 0,
        "data": None,
        "wrap_info": None,
        "warnings": None,
        "auth": None,
    }
    body.update(overrides)
    return body


class FakeVault(BaseAdapter):
    """Transport adapter that answers requests the way a Vault server does.

    Serves AppRole login on ``auth/approle``, a KV v2 engine and a KV v1 engine
    both mounted at ``secret`` (only one is consulted per path, as the provider
    tries v2 first), and records every request it receives.
    """

    def __init__(self) -> None:
        super().__init__()
        self.kv2: dict[str, dict[str, Any]] = {}
        self.kv1: dict[str, dict[str, Any]] = {}
        self.login_body: dict[str, Any] | None = None
        self.network_errors: dict[str, Callable[[requests.PreparedRequest], Exception]] = {}
        self.requests: list[requests.PreparedRequest] = []
        self.send_kwargs: list[dict[str, Any]] = []

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        """Record the request and return Vault's answer (or raise a network error)."""
        self.requests.append(request)
        self.send_kwargs.append({"timeout": timeout, "verify": verify, "cert": cert})
        path = (request.path_url or "").removeprefix("/v1/")
        if path in self.network_errors:
            raise self.network_errors[path](request)
        if request.method == "POST" and path == "auth/approle/login":
            return self._login(request)
        if request.headers.get("X-Vault-Token") != CLIENT_TOKEN:
            return self._respond(request, status=403, body={"errors": ["permission denied"]})
        if request.method == "GET" and path.startswith("secret/data/"):
            return self._kv2_read(request, secret_path=path.removeprefix("secret/data/"))
        if request.method == "GET" and path.startswith("secret/"):
            return self._kv1_read(request, secret_path=path.removeprefix("secret/"))
        return self._respond(request, status=404, body={"errors": []})

    def close(self) -> None:
        """Nothing to release."""

    def _login(self, request: requests.PreparedRequest) -> requests.Response:
        credentials = json.loads(request.body or b"{}")
        if credentials != {"role_id": ROLE_ID, "secret_id": SECRET_ID}:
            return self._respond(request, status=400, body={"errors": ["invalid role or secret ID"]})
        if self.login_body is not None:
            return self._respond(request, status=200, body=self.login_body)
        auth = {
            "client_token": CLIENT_TOKEN,
            "accessor": "fake-accessor",
            "policies": ["default", "docpipe"],
            "token_policies": ["default", "docpipe"],
            "metadata": {"role_name": "docpipe"},
            "lease_duration": 3600,
            "renewable": True,
            "token_type": "service",
            "orphan": True,
        }
        return self._respond(request, status=200, body=_envelope(auth=auth))

    def _kv2_read(self, request: requests.PreparedRequest, *, secret_path: str) -> requests.Response:
        if secret_path not in self.kv2:
            return self._respond(request, status=404, body={"errors": []})
        metadata = {"created_time": "2026-10-01T12:00:00Z", "deletion_time": "", "destroyed": False, "version": 1}
        return self._respond(
            request, status=200, body=_envelope(data={"data": self.kv2[secret_path], "metadata": metadata})
        )

    def _kv1_read(self, request: requests.PreparedRequest, *, secret_path: str) -> requests.Response:
        if secret_path not in self.kv1:
            return self._respond(request, status=404, body={"errors": []})
        return self._respond(request, status=200, body=_envelope(data=self.kv1[secret_path], lease_duration=2764800))

    @staticmethod
    def _respond(request: requests.PreparedRequest, *, status: int, body: dict[str, Any]) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode("utf-8")
        response.encoding = "utf-8"
        response.url = request.url or ""
        response.request = request
        return response


@pytest.fixture
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> FakeVault:
    """Route every session the provider builds to a fresh FakeVault and set AppRole env vars."""
    vault = FakeVault()

    def session_with_fake_transport() -> requests.Session:
        session = _RealSession()
        session.mount("http://", vault)
        session.mount("https://", vault)
        return session

    monkeypatch.setattr(requests, "Session", session_with_fake_transport)
    for name in _VAULT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VAULT_ADDR", VAULT_ADDR)
    monkeypatch.setenv("VAULT_ROLE_ID", ROLE_ID)
    monkeypatch.setenv("VAULT_SECRET_ID", SECRET_ID)
    return vault


def _connection_refused(request: requests.PreparedRequest) -> Exception:
    return requests.exceptions.ConnectionError("[Errno 111] Connection refused", request=request)


def _read_timeout(request: requests.PreparedRequest) -> Exception:
    return requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)", request=request)


class TestSecretReads:
    """KV v2 / KV v1 reads after a successful AppRole login."""

    def test_reads_kv_v2_secret_with_token_from_approle_login(self, fake_vault: FakeVault) -> None:
        fake_vault.kv2["database/postgres"] = {"username": "docpipe", "password": "pg-pass"}  # pragma: allowlist secret

        value = HashiCorpVaultProvider().get_secret(path="database/postgres", key="password")

        assert value == "pg-pass"  # pragma: allowlist secret
        login, read = fake_vault.requests
        assert (login.method, login.url) == ("POST", f"{VAULT_ADDR}/v1/auth/approle/login")
        assert (read.method, read.url) == ("GET", f"{VAULT_ADDR}/v1/secret/data/database/postgres")
        assert read.headers["X-Vault-Token"] == CLIENT_TOKEN

    def test_falls_back_to_kv_v1_when_kv_v2_path_does_not_exist(self, fake_vault: FakeVault) -> None:
        fake_vault.kv1["legacy/api"] = {"token": "legacy-token"}

        value = HashiCorpVaultProvider().get_secret(path="legacy/api")

        assert value == "legacy-token"
        assert [r.url for r in fake_vault.requests[1:]] == [
            f"{VAULT_ADDR}/v1/secret/data/legacy/api",
            f"{VAULT_ADDR}/v1/secret/legacy/api",
        ]

    def test_secret_missing_from_both_kv_versions_reports_kv_v1_status(self, fake_vault: FakeVault) -> None:
        provider = HashiCorpVaultProvider()

        with pytest.raises(ExternalServiceError, match=r"HTTP 404 for path 'secret/no/such/secret'"):
            provider.get_secret(path="no/such/secret", key="value")

        assert [r.url for r in fake_vault.requests[1:]] == [
            f"{VAULT_ADDR}/v1/secret/data/no/such/secret",
            f"{VAULT_ADDR}/v1/secret/no/such/secret",
        ]

    def test_connection_error_on_kv_v2_read_is_wrapped_without_kv_v1_attempt(self, fake_vault: FakeVault) -> None:
        fake_vault.network_errors["secret/data/database/postgres"] = _connection_refused
        provider = HashiCorpVaultProvider()

        with pytest.raises(
            ExternalServiceError, match="Network error reading secret at path 'secret/database/postgres'"
        ) as exc:
            provider.get_secret(path="database/postgres", key="password")

        assert isinstance(exc.value.__cause__, requests.exceptions.ConnectionError)
        assert len(fake_vault.requests) == 2  # login + KV v2 read only

    def test_timeout_on_kv_v1_fallback_read_is_wrapped(self, fake_vault: FakeVault) -> None:
        fake_vault.network_errors["secret/legacy/api"] = _read_timeout
        provider = HashiCorpVaultProvider()

        with pytest.raises(
            ExternalServiceError, match="Network error reading secret at path 'secret/legacy/api'"
        ) as exc:
            provider.get_secret(path="legacy/api")

        assert isinstance(exc.value.__cause__, requests.exceptions.ReadTimeout)


class TestAppRoleLogin:
    """Failures while logging in with role_id / secret_id."""

    def test_connection_refused_names_vault_address(self, fake_vault: FakeVault) -> None:
        fake_vault.network_errors["auth/approle/login"] = _connection_refused

        with pytest.raises(ExternalServiceError, match=f"Cannot connect to Vault at {VAULT_ADDR}") as exc:
            HashiCorpVaultProvider().authenticate()

        assert isinstance(exc.value.__cause__, requests.exceptions.ConnectionError)

    def test_timeout_is_reported_as_failed_authentication_request(self, fake_vault: FakeVault) -> None:
        fake_vault.network_errors["auth/approle/login"] = _read_timeout

        with pytest.raises(ExternalServiceError, match="Vault authentication request failed: Read timed out") as exc:
            HashiCorpVaultProvider().authenticate()

        assert isinstance(exc.value.__cause__, requests.exceptions.ReadTimeout)

    def test_login_pending_mfa_without_client_token_is_rejected(self, fake_vault: FakeVault) -> None:
        fake_vault.kv2["database/postgres"] = {"password": "pg-pass"}  # pragma: allowlist secret
        fake_vault.login_body = _envelope(
            warnings=["A login request was issued that is subject to MFA validation."],
            auth={
                "client_token": "",
                "accessor": "",
                "policies": None,
                "lease_duration": 0,
                "renewable": False,
                "mfa_requirement": {"mfa_request_id": "5e6a6c3f-0b55-4b52-9f53-7b3c0e4d2a10", "mfa_constraints": {}},
            },
        )
        provider = HashiCorpVaultProvider()

        with pytest.raises(ExternalServiceError, match="Vault login response missing client_token"):
            provider.get_secret(path="database/postgres", key="password")

        assert [r.method for r in fake_vault.requests] == ["POST"]  # no secret read without a token

    def test_rejected_credentials_report_vault_error(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VAULT_SECRET_ID", "revoked-secret-id")  # pragma: allowlist secret

        with pytest.raises(ExternalServiceError, match=r"login failed \(HTTP 400\).*invalid role or secret ID"):
            HashiCorpVaultProvider().authenticate()


class TestConnectionConfiguration:
    """Settings that are validated or applied before the first request leaves the process."""

    def test_empty_vault_addr_is_rejected_before_any_request(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VAULT_ADDR", "")

        with pytest.raises(ConfigurationError, match="VAULT_ADDR must be set"):
            HashiCorpVaultProvider().authenticate()

        assert fake_vault.requests == []

    def test_missing_ca_cert_file_is_rejected_before_any_request(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "missing-ca.pem"
        monkeypatch.setenv("VAULT_CA_CERT", str(missing))

        with pytest.raises(ConfigurationError, match="VAULT_CA_CERT path does not exist"):
            HashiCorpVaultProvider().authenticate()

        assert fake_vault.requests == []

    def test_ca_cert_and_namespace_are_applied_to_vault_requests(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ca_cert = tmp_path / "ca.pem"
        ca_cert.write_text("placeholder CA bundle", encoding="utf-8")
        monkeypatch.setenv("VAULT_CA_CERT", str(ca_cert))
        monkeypatch.setenv("VAULT_NAMESPACE", "team-a")

        HashiCorpVaultProvider().authenticate()

        (login,) = fake_vault.requests
        assert login.headers["X-Vault-Namespace"] == "team-a"
        assert fake_vault.send_kwargs[0]["verify"] == str(ca_cert)

    def test_client_cert_and_key_are_presented_for_mtls(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cert, key = tmp_path / "client.crt", tmp_path / "client.key"
        cert.write_text("placeholder client certificate", encoding="utf-8")
        key.write_text("placeholder client key", encoding="utf-8")
        monkeypatch.setenv("VAULT_CLIENT_CERT", str(cert))
        monkeypatch.setenv("VAULT_CLIENT_KEY", str(key))

        HashiCorpVaultProvider().authenticate()

        assert fake_vault.send_kwargs[0]["cert"] == (str(cert), str(key))

    def test_combined_client_cert_without_separate_key_is_presented_for_mtls(
        self, fake_vault: FakeVault, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        combined = tmp_path / "client-combined.pem"
        combined.write_text("placeholder certificate and key", encoding="utf-8")
        monkeypatch.setenv("VAULT_CLIENT_CERT", str(combined))

        HashiCorpVaultProvider().authenticate()

        assert fake_vault.send_kwargs[0]["cert"] == str(combined)

    @pytest.mark.parametrize(
        ("missing_file", "with_key", "expected_message"),
        [
            ("client.crt", True, "VAULT_CLIENT_CERT path does not exist"),
            ("client.key", True, "VAULT_CLIENT_KEY path does not exist"),
            ("client.crt", False, "VAULT_CLIENT_CERT path does not exist"),
        ],
        ids=["cert-missing-with-key", "key-missing", "cert-missing-without-key"],
    )
    def test_missing_mtls_file_is_rejected_before_any_request(
        self,
        fake_vault: FakeVault,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        missing_file: str,
        with_key: bool,
        expected_message: str,
    ) -> None:
        for name in ("client.crt", "client.key"):
            if name != missing_file:
                (tmp_path / name).write_text("placeholder", encoding="utf-8")
        monkeypatch.setenv("VAULT_CLIENT_CERT", str(tmp_path / "client.crt"))
        if with_key:
            monkeypatch.setenv("VAULT_CLIENT_KEY", str(tmp_path / "client.key"))

        with pytest.raises(ConfigurationError, match=expected_message):
            HashiCorpVaultProvider().authenticate()

        assert fake_vault.requests == []
