# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Weaviate client wrapper for connection, authentication, and lifecycle management."""

import contextlib
import re
from typing import Any

import grpc
import weaviate
from weaviate.classes.init import AdditionalConfig, Auth, Timeout
from weaviate.exceptions import (
    UnexpectedStatusCodeError,
    WeaviateConnectionError,
    WeaviateGRPCUnavailableError,
    WeaviateTimeoutError,
)

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_AUTH_HEADER_RE = re.compile(r"(?i)(bearer\s+)[^\s\"',]+")


def redact_secrets(*, text: str, secrets: list[str]) -> str:
    """Replace each non-empty secret and any bearer token in text with a mask."""
    if not text:
        return text
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return _AUTH_HEADER_RE.sub(r"\1***", redacted)


_UNREACHABLE_ERRORS = (WeaviateConnectionError, WeaviateTimeoutError, WeaviateGRPCUnavailableError)
_UNREACHABLE_GRPC_CODES = (grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE)
_SUPPORTED_CONNECTION_TYPES = ("on-prem", "cloud")


def sdk_status_code(exc: BaseException) -> int | None:
    """Return the HTTP/gRPC status code of an SDK status error, else None. Decided by type, never by message text."""
    if isinstance(exc, UnexpectedStatusCodeError):
        return int(exc.status_code)
    return None


def _is_unreachable(exc: BaseException) -> bool:
    """True when exc, or any exception in its cause/context chain, means the server is unreachable or timed out.

    The SDK wraps gRPC failures (for example DEADLINE_EXCEEDED on a query) in ``WeaviateQueryError`` raised inside
    ``except RpcError``, so the gRPC status is only present on the chained exception, never on the outer type.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _UNREACHABLE_ERRORS):
            return True
        if isinstance(current, grpc.RpcError):
            code = getattr(current, "code", None)
            with contextlib.suppress(Exception):
                if callable(code) and code() in _UNREACHABLE_GRPC_CODES:
                    return True
        current = current.__cause__ or current.__context__
    return False


def to_docpipe_exception(*, exc: Exception, operation: str, secrets: list[str]) -> DocpipeException:
    """Convert any exception raised by a Weaviate operation into a DocpipeException with a redacted message.

    A DocpipeException is returned unchanged. An unreachable or timed-out server (decided from the exception and its
    chain) gives status 503, any other failure 500. The caller must raise the result with ``from None``: the SDK
    exception can carry credentials, so it must not stay reachable through ``__cause__`` where tracebacks and
    ``logger.exception`` would print it unredacted.
    """
    if isinstance(exc, DocpipeException):
        return exc
    status = sdk_status_code(exc)
    detail = f"{exc.__class__.__name__}"
    if status is not None:
        detail += f", status {status}"
    message = redact_secrets(text=f"{operation} ({detail}): {exc}", secrets=secrets)
    return DocpipeException(
        message=message,
        status_code=503 if _is_unreachable(exc) else 500,
        error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
    )


class WeaviateClient:
    """Manages connection, authentication, and lifecycle for the Weaviate Python SDK client.

    Responsibilities:
    - On-prem and Weaviate Cloud connection creation
    - Authentication credential construction (none, api_key, bearer_token, client_password)
    - Connection validation and is_ready check
    - Idempotent resource cleanup and client closure
    - Secret redaction across error messages and log output
    """

    def __init__(
        self,
        *,
        connection_type: str = "on-prem",
        host: str = "localhost",
        port: int = 8080,
        secure: bool = False,
        grpc_host: str | None = None,
        grpc_port: int = 50051,
        grpc_secure: bool | None = None,
        cluster_url: str | None = None,
        auth_type: str = "none",
        api_key: str | None = None,
        bearer_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_init: int = 30,
        timeout_query: int = 60,
        timeout_insert: int = 120,
        skip_init_checks: bool = False,
    ) -> None:
        self.connection_type = connection_type
        self.host = host
        self.port = port
        self.secure = secure
        self.grpc_host = grpc_host
        self.grpc_port = grpc_port
        self.grpc_secure = grpc_secure
        self.cluster_url = cluster_url
        self.auth_type = auth_type
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.username = username
        self.password = password
        self.timeout_init = timeout_init
        self.timeout_query = timeout_query
        self.timeout_insert = timeout_insert
        self.skip_init_checks = skip_init_checks

        self._client: weaviate.WeaviateClient | None = None
        self._resolved_secrets: list[str] = []

    @property
    def resolved_secrets(self) -> list[str]:
        """Resolved credential values, available once the connection has been built."""
        return list(self._resolved_secrets)

    def _redact(self, text: str) -> str:
        """Redact known credentials and Authorization headers from text."""
        return redact_secrets(text=text, secrets=self._resolved_secrets)

    def _resolve_and_build_auth(self) -> Any:
        """Resolve credentials from environment variables and construct Auth object."""
        self._resolved_secrets = []
        if self.auth_type == "none":
            return None

        if self.auth_type == "api_key":
            if not self.api_key:
                raise DocpipeException(
                    message="api_key is required when auth_type is 'api_key'",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )
            try:
                resolved_key = str(resolve_env_var(self.api_key))
            except ValueError as exc:
                raise DocpipeException(
                    message=str(exc),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                ) from None
            self._resolved_secrets.append(resolved_key)
            return Auth.api_key(resolved_key)

        if self.auth_type == "bearer_token":
            if not self.bearer_token:
                raise DocpipeException(
                    message="bearer_token is required when auth_type is 'bearer_token'",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )
            try:
                resolved_bearer = str(resolve_env_var(self.bearer_token))
            except ValueError as exc:
                raise DocpipeException(
                    message=str(exc),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                ) from None
            self._resolved_secrets.append(resolved_bearer)
            return Auth.bearer_token(resolved_bearer)

        if self.auth_type == "client_password":
            if not self.username or not self.password:
                raise DocpipeException(
                    message="username and password are required when auth_type is 'client_password'",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )
            try:
                resolved_user = str(resolve_env_var(self.username))
                resolved_pass = str(resolve_env_var(self.password))
            except ValueError as exc:
                raise DocpipeException(
                    message=str(exc),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                ) from None
            self._resolved_secrets.append(resolved_pass)
            return Auth.client_password(username=resolved_user, password=resolved_pass)

        raise DocpipeException(
            message=f"Unsupported auth_type: '{self.auth_type}'",
            status_code=400,
            error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
        )

    def connect(self) -> weaviate.WeaviateClient:
        """Establish connection to Weaviate, verify readiness, and return client."""
        if self._client is not None:
            return self._client

        effective_grpc_secure = self.secure if self.grpc_secure is None else self.grpc_secure

        # The client can be built without WeaviateConfig validation (flow enrichment), so it enforces the
        # connection type and the TLS rule itself and never falls through to an unchecked connection.
        if self.connection_type not in _SUPPORTED_CONNECTION_TYPES:
            raise DocpipeException(
                message=(
                    f"Unsupported connection_type: '{self.connection_type}'. "
                    f"Use one of: {', '.join(_SUPPORTED_CONNECTION_TYPES)}"
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if self.connection_type == "on-prem" and self.auth_type != "none":
            if not (self.secure and effective_grpc_secure):
                raise DocpipeException(
                    message=(
                        "secure and grpc_secure must both be true when auth_type is not 'none'; "
                        "credentials must not be sent over an unencrypted connection"
                    ),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        target = self.cluster_url if self.connection_type == "cloud" else f"{self.host}:{self.port}"
        auth_credentials = self._resolve_and_build_auth()

        additional_config = AdditionalConfig(
            timeout=Timeout(
                init=self.timeout_init,
                query=self.timeout_query,
                insert=self.timeout_insert,
            )
        )

        logger.info(
            "Connecting to Weaviate at %s (connection_type=%s, auth_type=%s)",
            target,
            self.connection_type,
            self.auth_type,
        )

        raw_client: weaviate.WeaviateClient | None = None
        try:
            if self.connection_type == "cloud":
                if not self.cluster_url:
                    raise DocpipeException(
                        message="cluster_url is required when connection_type is 'cloud'",
                        status_code=400,
                        error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                    )
                raw_client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=self.cluster_url,
                    auth_credentials=auth_credentials,
                    additional_config=additional_config,
                    skip_init_checks=self.skip_init_checks,
                )
            else:
                resolved_grpc_host = self.grpc_host if self.grpc_host is not None else self.host
                raw_client = weaviate.connect_to_custom(
                    http_host=self.host,
                    http_port=self.port,
                    http_secure=self.secure,
                    grpc_host=resolved_grpc_host,
                    grpc_port=self.grpc_port,
                    grpc_secure=effective_grpc_secure,
                    auth_credentials=auth_credentials,
                    additional_config=additional_config,
                    skip_init_checks=self.skip_init_checks,
                )

            if not raw_client.is_ready():
                raw_client.close()
                raw_client = None
                msg = f"Weaviate deployment at '{target}' is not ready"
                raise DocpipeException(
                    message=self._redact(msg),
                    status_code=503,
                    error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
                )

            self._client = raw_client
            return self._client
        except Exception as exc:
            if raw_client is not None:
                with contextlib.suppress(Exception):
                    raw_client.close()
                raw_client = None

            if isinstance(exc, DocpipeException):
                raise

            err_cls = exc.__class__.__name__
            msg = f"Failed to connect to Weaviate at '{target}' ({err_cls}): {exc}"
            raise DocpipeException(
                message=self._redact(msg),
                status_code=503,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from None

    def get_client(self) -> weaviate.WeaviateClient:
        """Return connected Weaviate client, connecting if not already connected."""
        if self._client is None:
            return self.connect()
        return self._client

    def is_ready(self) -> bool:
        """Check if Weaviate server is reachable and ready."""
        try:
            client = self.get_client()
            return bool(client.is_ready())
        except Exception:
            return False

    def close(self) -> None:
        """Close connection to Weaviate idempotently."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.warning("Error closing Weaviate client: %s", self._redact(str(exc)))
            finally:
                self._client = None
