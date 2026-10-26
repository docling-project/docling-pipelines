"""HashiCorp Vault secret provider using AppRole authentication via REST API.

Uses the Vault HTTP API directly with the `requests` library (already a project
dependency), avoiding any third-party Vault SDK.

Authentication uses role_id + secret_id (AppRole), which avoids short-lived
user tokens. The provider automatically re-authenticates when the generated
token approaches expiry.

Vault API reference:
    - AppRole login: POST /v1/auth/{mount}/login
    - KV v2 read:    GET  /v1/{mount}/data/{path}
    - KV v1 read:    GET  /v1/{mount}/{path}

Connection credentials are read from environment variables:
    VAULT_ADDR              - Vault server URL (default: http://127.0.0.1:8200)
    VAULT_ROLE_ID           - AppRole role ID
    VAULT_SECRET_ID         - AppRole secret ID
    VAULT_MOUNT_POINT       - KV secrets engine mount (default: secret)
    VAULT_APPROLE_MOUNT     - AppRole auth mount (default: approle)
    VAULT_NAMESPACE         - Vault Enterprise namespace (optional)
    VAULT_CA_CERT           - Path to CA certificate for TLS (optional)
    VAULT_CLIENT_CERT       - Path to client certificate for mTLS (optional)
    VAULT_CLIENT_KEY        - Path to client private key for mTLS (optional)
    VAULT_TLS_SKIP_VERIFY   - Skip TLS verification, dev only (default: false)

For Docker/Kubernetes, credentials can also be provided as file-backed
secrets using the _FILE suffix convention:
    VAULT_ROLE_ID_FILE      - Path to file containing role_id
    VAULT_SECRET_ID_FILE    - Path to file containing secret_id
"""

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.secret_provider import SecretProvider
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


def _read_env_or_file(env_var: str, *, default: str = "") -> str:
    """Read value from environment variable or file-backed secret.

    Checks in order:
    1. {env_var}_FILE - path to a file containing the value
       (Docker secrets / Kubernetes mounted secrets pattern)
    2. {env_var} - direct environment variable

    This pattern works for:
    - Local: VAULT_ROLE_ID=xxx in .env
    - Docker: -v /run/secrets/vault_role_id + VAULT_ROLE_ID_FILE=/run/secrets/vault_role_id
    - Kubernetes: secretKeyRef -> env var, OR secret volume -> file

    Args:
        env_var: Base environment variable name.
        default: Default value if neither source provides a value.

    Returns:
        The resolved value.
    """
    file_path = os.environ.get(f"{env_var}_FILE")
    if file_path and Path(file_path).is_file():
        with Path(file_path).open() as f:
            return f.read().strip()

    return os.environ.get(env_var, default)


@dataclass
class HashiCorpVaultConfig:
    """Configuration for HashiCorp Vault connection.

    All values default to environment variables, making it work identically
    across local (.env), Docker (env vars), and Kubernetes (secretKeyRef).

    Attributes:
        addr: Vault server URL.
        role_id: AppRole role ID for authentication.
        secret_id: AppRole secret ID for authentication.
        mount_point: KV secrets engine mount point.
        approle_mount_point: AppRole auth method mount point.
        namespace: Vault Enterprise namespace (optional).
        ca_cert: Path to CA certificate for server TLS verification.
        client_cert: Path to client certificate for mutual TLS.
        client_key: Path to client private key for mutual TLS.
        tls_skip_verify: Skip TLS verification (development only).
    """

    addr: str = field(default_factory=lambda: os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"))
    role_id: str = field(default_factory=lambda: _read_env_or_file("VAULT_ROLE_ID"))
    secret_id: str = field(default_factory=lambda: _read_env_or_file("VAULT_SECRET_ID"))
    mount_point: str = field(default_factory=lambda: os.environ.get("VAULT_MOUNT_POINT", "secret"))
    approle_mount_point: str = field(default_factory=lambda: os.environ.get("VAULT_APPROLE_MOUNT", "approle"))
    namespace: str | None = field(default_factory=lambda: os.environ.get("VAULT_NAMESPACE"))
    ca_cert: str | None = field(default_factory=lambda: os.environ.get("VAULT_CA_CERT"))
    client_cert: str | None = field(default_factory=lambda: os.environ.get("VAULT_CLIENT_CERT"))
    client_key: str | None = field(default_factory=lambda: os.environ.get("VAULT_CLIENT_KEY"))
    tls_skip_verify: bool = field(
        default_factory=lambda: os.environ.get("VAULT_TLS_SKIP_VERIFY", "false").lower() in ("true", "1", "yes")
    )

    def validate(self) -> None:
        """Validate that required configuration is present.

        Raises:
            ConfigurationError: If required fields are missing.
        """
        if not self.role_id:
            msg = "VAULT_ROLE_ID (or VAULT_ROLE_ID_FILE) must be set. See .env.example for configuration details."
            raise ConfigurationError(msg)
        if not self.secret_id:
            msg = "VAULT_SECRET_ID (or VAULT_SECRET_ID_FILE) must be set. See .env.example for configuration details."
            raise ConfigurationError(msg)
        if not self.addr:
            msg = "VAULT_ADDR must be set."
            raise ConfigurationError(msg)


# Buffer before token expiry to trigger re-authentication (seconds)
_TOKEN_REFRESH_BUFFER = 60

# HTTP timeout for Vault API calls (seconds)
_REQUEST_TIMEOUT = 30


def _log_vault_response(*, method: str, url: str, response: "requests.Response") -> None:
    """Log the full Vault HTTP response at DEBUG level for error diagnosis.

    Only emitted when DS_LOG_LEVEL=DEBUG. Logs method, URL, status code,
    response headers, and body so that Vault-side error messages are fully visible.

    Args:
        method: HTTP method used (GET, POST, etc.).
        url: Full request URL.
        response: The requests.Response object from the failed call.
    """
    logger.debug(
        "Vault %s %s -> HTTP %d\nResponse headers: %s\nResponse body: %s",
        method,
        url,
        response.status_code,
        dict(response.headers),
        response.text,
    )


class HashiCorpVaultProvider(SecretProvider):
    """HashiCorp Vault provider using AppRole + optional mTLS.

    Uses the Vault HTTP API directly via `requests` - no third-party Vault SDK.

    Features:
    - AppRole authentication (role_id + secret_id) - no user tokens needed
    - Automatic re-authentication before token expiry
    - TLS with custom CA certificate
    - Mutual TLS (mTLS) with client certificate
    - KV v2 with KV v1 fallback
    - Thread-safe operation
    """

    def __init__(self, *, config: HashiCorpVaultConfig | None = None) -> None:
        """Initialize the provider.

        Args:
            config: Vault configuration. If None, reads from environment variables.
        """
        self._config = config or HashiCorpVaultConfig()
        self._token: str | None = None
        self._token_expiry: float = 0
        self._lock = threading.Lock()
        self._session: requests.Session | None = None

    def _build_session(self) -> requests.Session:
        """Build a requests Session with TLS configuration.

        Returns:
            Configured requests.Session instance.
        """
        session = requests.Session()

        # TLS verification
        if self._config.tls_skip_verify:
            session.verify = False
        elif self._config.ca_cert:
            if not Path(self._config.ca_cert).is_file():
                msg = f"VAULT_CA_CERT path does not exist: {self._config.ca_cert}"
                raise ConfigurationError(msg)
            session.verify = self._config.ca_cert
        else:
            session.verify = True

        # Client certificate for mTLS
        if self._config.client_cert and self._config.client_key:
            if not Path(self._config.client_cert).is_file():
                msg = f"VAULT_CLIENT_CERT path does not exist: {self._config.client_cert}"
                raise ConfigurationError(msg)
            if not Path(self._config.client_key).is_file():
                msg = f"VAULT_CLIENT_KEY path does not exist: {self._config.client_key}"
                raise ConfigurationError(msg)
            session.cert = (self._config.client_cert, self._config.client_key)
        elif self._config.client_cert:
            if not Path(self._config.client_cert).is_file():
                msg = f"VAULT_CLIENT_CERT path does not exist: {self._config.client_cert}"
                raise ConfigurationError(msg)
            session.cert = self._config.client_cert

        # Vault namespace header (Vault Enterprise / HCP Vault)
        if self._config.namespace:
            session.headers["X-Vault-Namespace"] = self._config.namespace

        return session

    def authenticate(self) -> None:
        """Authenticate to Vault using AppRole credentials.

        POST /v1/auth/{approle_mount}/login
        Body: {"role_id": "...", "secret_id": "..."}

        Raises:
            ConfigurationError: If configuration is invalid.
            ExternalServiceError: If authentication fails.
        """
        self._config.validate()

        if self._session is None:
            self._session = self._build_session()

        url = "{}/v1/auth/{}/login".format(
            self._config.addr.rstrip("/"),
            self._config.approle_mount_point,
        )

        payload = {
            "role_id": self._config.role_id,
            "secret_id": self._config.secret_id,
        }

        try:
            response = self._session.post(url, json=payload, timeout=_REQUEST_TIMEOUT)
        except requests.exceptions.ConnectionError as e:
            msg = f"Cannot connect to Vault at {self._config.addr}: {e}"
            raise ExternalServiceError(msg) from e
        except requests.exceptions.RequestException as e:
            msg = f"Vault authentication request failed: {e}"
            raise ExternalServiceError(msg) from e

        if response.status_code != 200:
            _log_vault_response(method="POST", url=url, response=response)
            msg = f"Vault AppRole login failed (HTTP {response.status_code}): {response.text}"
            raise ExternalServiceError(msg)

        data = response.json()
        auth_data = data.get("auth", {})
        self._token = auth_data.get("client_token")
        lease_duration = auth_data.get("lease_duration", 3600)
        self._token_expiry = time.time() + lease_duration

        if not self._token:
            msg = "Vault login response missing client_token"
            raise ExternalServiceError(msg)

        # Set token header for subsequent requests
        self._session.headers["X-Vault-Token"] = self._token

        logger.info(
            "Authenticated with HashiCorp Vault (AppRole), token valid for %d seconds",
            lease_duration,
        )

    def _ensure_authenticated(self) -> None:
        """Re-authenticate if token is expired or approaching expiry."""
        with self._lock:
            if self._token is None or time.time() >= (self._token_expiry - _TOKEN_REFRESH_BUFFER):
                self.authenticate()

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        """Retrieve a secret value from Vault.

        Attempts KV v2 first (GET /v1/{mount}/data/{path}),
        falls back to KV v1 (GET /v1/{mount}/{path}).

        Args:
            path: Secret path under the mount point (e.g., "database/postgres").
            key: Specific key within the secret data (e.g., "password").

        Returns:
            The secret value as a string.

        Raises:
            ExternalServiceError: If the specified key does not exist or secret cannot be retrieved.
            ConfigurationError: If no key is specified and the secret has multiple keys.
        """
        self._ensure_authenticated()

        data = self._read_secret_data(path=path)

        if key:
            if key not in data:
                msg = f"Key '{key}' not found at vault path '{self._config.mount_point}/{path}'."
                raise ExternalServiceError(msg)
            return str(data[key])

        # No key specified - return the single value or raise if ambiguous
        if len(data) == 1:
            return str(next(iter(data.values())))

        msg = f"Multiple keys at vault path '{self._config.mount_point}/{path}'. Specify a key using #key_name."
        raise ConfigurationError(msg)

    def _read_secret_data(self, *, path: str) -> dict:
        """Read secret data from Vault, trying KV v2 then v1.

        KV v2: GET /v1/{mount}/data/{path}  -> response.data.data
        KV v1: GET /v1/{mount}/{path}       -> response.data

        Args:
            path: Secret path under the mount point.

        Returns:
            Dictionary of key-value pairs from the secret.

        Raises:
            ExternalServiceError: If the secret cannot be read.
        """
        # get_secret() always runs _ensure_authenticated() first, which builds the session.
        assert self._session is not None, "authenticate() must be called before reading secrets"
        base_url = self._config.addr.rstrip("/")
        mount = self._config.mount_point

        # Try KV v2 first (most common)
        kv2_url = f"{base_url}/v1/{mount}/data/{path}"
        try:
            response = self._session.get(kv2_url, timeout=_REQUEST_TIMEOUT)
            if response.status_code == 200:
                resp_data = response.json()
                return resp_data["data"]["data"]
            if response.status_code != 404:
                # 403 permission denied, 400 bad request, 429 rate limited, 503 sealed, etc.
                # None of these mean "try KV v1" — fail immediately with the real status.
                _log_vault_response(method="GET", url=kv2_url, response=response)
                msg = f"Vault returned HTTP {response.status_code} for path '{mount}/{path}': {response.text}"
                raise ExternalServiceError(msg)
            # 404 only: path not found under KV v2 /data/ prefix — fall through to KV v1
        except requests.exceptions.RequestException as kv2_error:
            msg = f"Network error reading secret at path '{mount}/{path}': {kv2_error}"
            raise ExternalServiceError(msg) from kv2_error

        # Fallback to KV v1 (only reached on 404 from KV v2)
        kv1_url = f"{base_url}/v1/{mount}/{path}"
        try:
            response = self._session.get(kv1_url, timeout=_REQUEST_TIMEOUT)
            if response.status_code == 200:
                resp_data = response.json()
                return resp_data["data"]
            _log_vault_response(method="GET", url=kv1_url, response=response)
            msg = f"Vault returned HTTP {response.status_code} for path '{mount}/{path}': {response.text}"
            raise ExternalServiceError(msg)
        except requests.exceptions.RequestException as kv1_error:
            msg = f"Network error reading secret at path '{mount}/{path}': {kv1_error}"
            raise ExternalServiceError(msg) from kv1_error

    def is_available(self) -> bool:
        """Check if Vault is reachable and initialized.

        GET /v1/sys/health

        Returns:
            True if Vault is accessible, False otherwise.
        """
        try:
            if self._session is None:
                self._session = self._build_session()

            url = "{}/v1/sys/health".format(self._config.addr.rstrip("/"))
            response = self._session.get(url, timeout=5)
            # Vault returns 200 if initialized+unsealed, 429/472/473 for other states
            return response.status_code in (200, 429, 472, 473)
        except Exception as e:
            logger.warning("Vault availability check failed for %s: %s", self._config.addr, e, exc_info=True)
            return False
