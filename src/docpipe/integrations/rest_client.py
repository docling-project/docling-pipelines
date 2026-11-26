# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
REST client for making HTTP requests with retry logic and error handling.

This module provides a flexible REST client that supports:
- Multiple HTTP methods (GET, POST, PUT, PATCH, DELETE)
- Automatic retry with exponential backoff
- Bearer token authentication
- Request/response logging with sensitive data sanitization
- Configurable timeouts and SSL verification
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, TypedDict
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import requests
from requests import Response
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from docpipe.exceptions.docpipe_exceptions import ExternalServiceError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class RestMethod(Enum):
    """HTTP methods supported by the REST client."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"


class MethodConfig(TypedDict):
    expected_status_codes: list[int]
    supports_body: bool


# Configuration for each HTTP method
METHOD_CONFIG: dict[RestMethod, MethodConfig] = {
    RestMethod.GET: {
        "expected_status_codes": [200],
        "supports_body": False,
    },
    RestMethod.POST: {
        "expected_status_codes": [200, 201, 207],
        "supports_body": True,
    },
    RestMethod.PUT: {
        "expected_status_codes": [200, 201, 204],
        "supports_body": True,
    },
    RestMethod.PATCH: {
        "expected_status_codes": [200, 204],
        "supports_body": True,
    },
    RestMethod.DELETE: {
        "expected_status_codes": [200, 204],
        "supports_body": False,
    },
    RestMethod.HEAD: {
        "expected_status_codes": [200],
        "supports_body": False,
    },
}


def sanitize_sensitive_data(data: Any, redact_value: str = "***REDACTED***") -> Any:
    """
    Redact sensitive information from data for logging purposes.

    Args:
        data: Dictionary, list, string, or other value containing potentially sensitive data
        redact_value: The string to substitute for redacted values (default: "***REDACTED***")

    Returns:
        Sanitized copy of the data with sensitive values redacted
    """
    # Patterns to match sensitive data in strings
    sensitive_patterns = [
        (r'(token|password|api[_-]?key|secret|authorization)[\s:=]+["\']?([^"\'\s,}]+)', r"\1: " + redact_value),
        (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer " + redact_value),
        (r"Basic\s+[A-Za-z0-9+/]+=*", "Basic " + redact_value),
    ]

    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            # Check if key contains sensitive keywords
            if any(keyword in key.lower() for keyword in ["token", "password", "key", "secret", "auth"]):
                sanitized[key] = redact_value
            else:
                sanitized[key] = sanitize_sensitive_data(value, redact_value)
        return sanitized

    if isinstance(data, list):
        return [sanitize_sensitive_data(item, redact_value) for item in data]

    if isinstance(data, str):
        sanitized_str = data
        for pattern, replacement in sensitive_patterns:
            sanitized_str = re.sub(pattern, replacement, sanitized_str, flags=re.IGNORECASE)
        return sanitized_str

    return data


_REDACTED: Final[str] = "***REDACTED***"

# Query/fragment parameter names (lower-cased, with "-" and "_" removed) whose value is a credential.
# Pre-authenticated download URLs, for example the Microsoft Graph ``@microsoft.graph.downloadUrl``
# (``tempauth``), AWS presigned URLs (``X-Amz-Signature``) and Azure SAS URLs (``sig``), carry the
# credential in the query string.
_SENSITIVE_URL_PARAM_KEYWORDS: Final[tuple[str, ...]] = (
    "token",
    "auth",
    "secret",
    "password",
    "passwd",
    "credential",
    "signature",
    "apikey",
)
_SENSITIVE_URL_PARAM_NAMES: Final[frozenset[str]] = frozenset({"sig", "key", "code"})

_URL_IN_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://[^\s'\"<>)]+")
# urllib3 and requests report connection failures as "with url: /path?query" without a scheme or host
_REQUEST_PATH_IN_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(r"(with url: )([^\s'\"<>)]+)")


def _is_sensitive_url_param(*, name: str) -> bool:
    """Return True when a URL parameter name indicates that its value is a credential."""
    normalized = unquote_plus(name).lower().replace("-", "").replace("_", "")
    return normalized in _SENSITIVE_URL_PARAM_NAMES or any(
        keyword in normalized for keyword in _SENSITIVE_URL_PARAM_KEYWORDS
    )


def _redact_url_params(*, params: str, redact_value: str) -> str:
    """Redact the value of every credential parameter in an ``a=b&c=d`` query or fragment string."""
    redacted_parts: list[str] = []
    for part in params.split("&"):
        name, separator, _ = part.partition("=")
        if separator and _is_sensitive_url_param(name=name):
            redacted_parts.append(f"{name}={redact_value}")
        else:
            redacted_parts.append(part)
    return "&".join(redacted_parts)


def sanitize_url(url: str, *, redact_value: str = _REDACTED) -> str:
    """
    Redact credentials from a URL so that it can be logged or placed in an error message.

    The scheme, host, path and non-sensitive query parameters are kept so that logs stay useful. Embedded
    ``user:password@`` credentials are dropped, and the value of any query or fragment parameter that
    looks like a credential (``tempauth``, ``token``, ``sig``, ``X-Amz-Signature`` and similar) is replaced.

    Args:
        url: A full URL or a path with a query string
        redact_value: The string to substitute for redacted values (default: "***REDACTED***")

    Returns:
        The URL with credentials redacted, or ``redact_value`` when the URL cannot be parsed
    """
    try:
        parts = urlsplit(url)
        host = parts.netloc.rpartition("@")[2]
        query = _redact_url_params(params=parts.query, redact_value=redact_value) if parts.query else ""
        fragment = _redact_url_params(params=parts.fragment, redact_value=redact_value) if "=" in parts.fragment else ""
        return urlunsplit((parts.scheme, host, parts.path, query, fragment or parts.fragment))
    except ValueError:
        return redact_value


def sanitize_urls_in_text(text: str, *, redact_value: str = _REDACTED) -> str:
    """
    Redact credentials from every URL embedded in free text such as an exception message.

    Args:
        text: Text that may contain ``http(s)://`` URLs or ``with url: /path?query`` fragments
        redact_value: The string to substitute for redacted values (default: "***REDACTED***")

    Returns:
        The text with credentials in URLs redacted
    """
    text = _URL_IN_TEXT_PATTERN.sub(lambda match: sanitize_url(match.group(0), redact_value=redact_value), text)
    return _REQUEST_PATH_IN_TEXT_PATTERN.sub(
        lambda match: match.group(1) + sanitize_url(match.group(2), redact_value=redact_value), text
    )


def _redact_request_exception(error: requests.exceptions.RequestException) -> str:
    """
    Remove URL credentials from a ``requests`` exception and return its safe text.

    ``requests`` puts the full request URL in the exception message. The exception is chained to the
    ``ExternalServiceError`` that callers log with a traceback, so its arguments are rewritten in place.
    """
    safe_text = sanitize_urls_in_text(str(error))
    error.args = (safe_text,)
    return safe_text


@dataclass
class RestClientConfig:
    """Configuration for REST client behavior."""

    timeout: int = 30
    max_retries: int = 3
    retry_backoff_factor: float = 2.0
    verify_ssl: bool | str = True  # True, False, or path to cert file
    retry_max_attempts: int = 3
    retry_multiplier: float = 2.0
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0


class RestClient:
    """
    REST client with retry logic and error handling.

    Supports bearer token authentication, automatic retries with exponential backoff,
    and comprehensive logging with sensitive data sanitization.
    """

    def __init__(
        self,
        config: RestClientConfig,
        base_url: str | None = None,
        auth_token: str | None = None,
    ):
        """
        Initialize the REST client.

        Args:
            config: Configuration for client behavior
            base_url: Optional base URL to prepend to all requests
            auth_token: Optional bearer token for authentication
        """
        self.config = config
        self.base_url = base_url.rstrip("/") if base_url else None
        self.auth_token = auth_token
        self.session = requests.Session()

        # Apply retry decorator dynamically with config values
        self._call_rest_method = retry(
            retry=retry_if_exception_type(
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError,
                )
            ),
            stop=stop_after_attempt(self.config.retry_max_attempts),
            wait=wait_exponential(
                multiplier=self.config.retry_multiplier, min=self.config.retry_min_wait, max=self.config.retry_max_wait
            ),
            reraise=True,
        )(self._call_rest_method_impl)

    def _build_url(self, endpoint: str) -> str:
        """
        Build full URL from base URL and endpoint.

        Args:
            endpoint: API endpoint path

        Returns:
            Complete URL
        """
        if self.base_url:
            return f"{self.base_url}/{endpoint.lstrip('/')}"
        return endpoint

    def _build_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """
        Build request headers including authentication.

        Args:
            headers: Optional additional headers

        Returns:
            Complete headers dictionary
        """
        request_headers = headers.copy() if headers else {}

        if self.auth_token and "Authorization" not in request_headers:
            request_headers["Authorization"] = f"Bearer {self.auth_token}"

        return request_headers

    def call_rest_json(
        self,
        *,
        method: RestMethod,
        url: str,
        action: str | None = None,
        json_data: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected_status_codes: list[int] | None = None,
        timeout: int | None = None,
        verify: bool | str | None = None,
    ) -> dict[str, Any]:
        """
        Make a REST call and return the parsed JSON response body.

        Args:
            method: HTTP method to use
            url: API endpoint URL or path
            action: Optional human-readable description for logging and error messages
            json_data: Optional JSON body data
            form_data: Optional form-encoded body data (mutually exclusive with json_data)
            query_params: Optional query parameters
            headers: Optional request headers
            expected_status_codes: Optional list of expected status codes
            timeout: Per-call timeout override; falls back to config.timeout
            verify: Per-call SSL verification override; falls back to config.verify_ssl

        Returns:
            Parsed JSON response body as a dictionary

        Raises:
            ExternalServiceError: If request fails
        """
        return self.call_rest(
            method=method,
            url=url,
            action=action,
            json_data=json_data,
            form_data=form_data,
            query_params=query_params,
            headers=headers,
            expected_status_codes=expected_status_codes,
            timeout=timeout,
            verify=verify,
        ).json()

    def call_rest_multipart(
        self,
        *,
        method: RestMethod,
        url: str,
        action: str | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        form_data: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected_status_codes: list[int] | None = None,
        timeout: int | None = None,
        verify: bool | str | None = None,
    ) -> dict[str, Any]:
        """
        Make a REST call with multipart/form-data and return the parsed JSON response body.

        Delegates to ``call_rest`` passing files and form data, so it benefits from
        retry logic, logging, and status-code handling in one place.

        Args:
            method: HTTP method to use
            url: API endpoint URL or path
            action: Optional human-readable description for logging and error messages
            files: Dictionary of files to upload {field_name: (filename, content, mime_type)}
            form_data: Optional form data fields to send alongside files
            query_params: Optional query parameters
            headers: Optional request headers
            expected_status_codes: Optional list of expected status codes
            timeout: Per-call timeout override; falls back to config.timeout
            verify: Per-call SSL verification override; falls back to config.verify_ssl

        Returns:
            Parsed JSON response body as a dictionary

        Raises:
            ExternalServiceError: If request fails
        """
        return self.call_rest(
            method=method,
            url=url,
            action=action,
            form_data=form_data,
            files=files,
            query_params=query_params,
            headers=headers,
            expected_status_codes=expected_status_codes,
            timeout=timeout,
            verify=verify,
        ).json()

    def call_rest(
        self,
        *,
        method: RestMethod,
        url: str,
        action: str | None = None,
        json_data: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected_status_codes: list[Any] | None = None,
        timeout: int | None = None,
        verify: bool | str | None = None,
    ) -> Response:
        """
        Make a generic REST call.

        Args:
            method: HTTP method to use
            url: API endpoint URL or path
            action: Optional human-readable description for logging and error messages
            json_data: Optional JSON body data
            form_data: Optional form-encoded body data (mutually exclusive with json_data)
            files: Optional files for multipart upload
            query_params: Optional query parameters
            headers: Optional request headers
            expected_status_codes: Optional list of expected status codes
            timeout: Per-call timeout override; falls back to config.timeout
            verify: Per-call SSL verification override; falls back to config.verify_ssl

        Returns:
            Response object

        Raises:
            ExternalServiceError: If request fails
        """
        built_url = self._build_url(url)
        request_headers = self._build_headers(headers)

        if expected_status_codes is None:
            expected_status_codes = METHOD_CONFIG[method]["expected_status_codes"]

        try:
            response = self._call_rest_method(
                method=method,
                url=built_url,
                json_data=json_data,
                form_data=form_data,
                files=files,
                params=query_params,
                headers=request_headers,
                timeout=timeout,
                verify=verify,
                expected_status_codes=expected_status_codes,
            )

            # Check status code
            if expected_status_codes and response.status_code not in expected_status_codes:
                error_msg = sanitize_urls_in_text(
                    f"Unexpected status code {response.status_code}. Expected one of {expected_status_codes}. Response: {response.text[:500]}"
                )
                logger.error("%s", error_msg)
                raise ExternalServiceError(
                    message=error_msg,
                    error_code=ErrorCode.HTTP_ERROR,
                    status_code=response.status_code,
                )

            return response

        except requests.exceptions.HTTPError as e:
            safe_error = _redact_request_exception(e)
            logger.error("Request failed: %s", safe_error)
            raise ExternalServiceError(
                message=f"REST request failed: {safe_error}",
                error_code=ErrorCode.HTTP_ERROR,
                status_code=e.response.status_code if e.response is not None else None,
            ) from e
        except requests.exceptions.RequestException as e:
            safe_error = _redact_request_exception(e)
            logger.error("Request failed: %s", safe_error)
            raise ExternalServiceError(
                message=f"REST request failed: {safe_error}",
                error_code=ErrorCode.CONNECTION_ERROR,
            ) from e

    def _call_rest_method_impl(
        self,
        method: RestMethod,
        url: str,
        json_data: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
        verify: bool | str | None = None,
        expected_status_codes: list[int] | None = None,
    ) -> Response:
        """
        Internal method to make REST call with retry logic.

        Args:
            method: HTTP method to use
            url: Complete URL
            json_data: Optional JSON body data
            form_data: Optional form-encoded body data (mutually exclusive with json_data)
            files: Optional files for multipart upload
            params: Optional query parameters
            headers: Optional request headers
            stream: Whether to stream the response body
            timeout: Per-call timeout override; falls back to config.timeout
            verify: Per-call SSL verification override; falls back to config.verify_ssl
            expected_status_codes: Status codes that should be returned as-is even if
                they would normally raise (e.g. 404 when absence is a valid outcome).
                When None, any non-2xx response that raises HTTPError is re-raised.

        Returns:
            Response object

        Raises:
            requests.exceptions.RequestException: If request fails after retries
        """
        # Validate that json_data and form_data are mutually exclusive
        if json_data is not None and form_data is not None:
            raise ValueError("json_data and form_data are mutually exclusive")

        request_type = "multipart " if files is not None else ""
        safe_url = sanitize_url(url)
        if params:
            logger.info(
                "Making %s %srequest to %s with params: %s",
                method.value,
                request_type,
                safe_url,
                sanitize_sensitive_data(params),
            )
        else:
            logger.info("Making %s %srequest to %s", method.value, request_type, safe_url)
        logger.debug("Headers: %s", sanitize_sensitive_data(headers))
        if json_data is not None:
            logger.debug("Body: %s", sanitize_sensitive_data(json_data))
        if form_data is not None:
            logger.debug("Form data: %s", sanitize_sensitive_data(form_data))
        if files is not None:
            logger.debug("Files: %s", list(files.keys()))

        response = self.session.request(
            method=method.value,
            url=url,
            json=json_data,
            data=form_data,
            files=files,
            params=params,
            headers=headers,
            timeout=timeout if timeout is not None else self.config.timeout,
            verify=verify if verify is not None else self.config.verify_ssl,
            stream=stream,
        )

        logger.info("Response status: %s", response.status_code)
        logger.debug("Response headers: %s", dict(response.headers))

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            if expected_status_codes and response.status_code in expected_status_codes:
                return response
            raise

        return response
