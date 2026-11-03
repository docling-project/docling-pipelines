# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for RestClient.

Tests cover sanitization, configuration, URL building, header management,
HTTP methods, retry logic, and error handling.
"""

from unittest.mock import Mock, patch

import pytest
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout

from docpipe.exceptions.docpipe_exceptions import ExternalServiceError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.rest_client import (
    METHOD_CONFIG,
    RestClient,
    RestClientConfig,
    RestMethod,
    sanitize_sensitive_data,
)


class TestSanitizeSensitiveData:
    """Test sanitize_sensitive_data() function."""

    def test_redact_tokens_in_dict(self):
        """Test redacting tokens in dictionary."""
        data = {
            "Authorization": "Bearer secret_token_123",  # pragma: allowlist secret
            "api_key": "my_api_key",  # pragma: allowlist secret
            "token": "user_token",  # pragma: allowlist secret
            "other": "safe_value",
        }
        result = sanitize_sensitive_data(data)

        assert result["Authorization"] == "***REDACTED***"
        assert result["api_key"] == "***REDACTED***"
        assert result["token"] == "***REDACTED***"
        assert result["other"] == "safe_value"

    def test_redact_passwords_in_dict(self):
        """Test redacting passwords in dictionary."""
        data = {
            "password": "secret123",  # pragma: allowlist secret
            "user_password": "pass456",  # pragma: allowlist secret
            "username": "john",
        }
        result = sanitize_sensitive_data(data)

        assert result["password"] == "***REDACTED***"
        assert result["user_password"] == "***REDACTED***"
        assert result["username"] == "john"

    def test_redact_bearer_tokens_in_strings(self):
        """Test redacting Bearer tokens in strings."""
        # Test with Bearer token pattern that matches the regex
        data = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_sensitive_data(data)

        assert "Bearer ***REDACTED***" in result
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result

    def test_redact_basic_auth_in_strings(self):
        """Test redacting Basic auth in strings."""
        # Test with Basic auth pattern that matches the regex
        data = "Basic dXNlcjpwYXNzd29yZA=="
        result = sanitize_sensitive_data(data)

        assert "Basic ***REDACTED***" in result
        assert "dXNlcjpwYXNzd29yZA==" not in result

    def test_handle_none_input(self):
        """Test handling None input."""
        result = sanitize_sensitive_data(None)
        assert result is None

    def test_redact_list_items(self):
        """Test that list items are sanitized recursively."""
        data = [
            {"token": "secret123"},  # pragma: allowlist secret
            {"safe": "value"},
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        ]
        result = sanitize_sensitive_data(data)

        assert result[0]["token"] == "***REDACTED***"
        assert result[1]["safe"] == "value"
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result[2]

    def test_custom_redact_value(self):
        """Test custom redact_value parameter."""
        data = {"password": "secret123"}  # pragma: allowlist secret
        result = sanitize_sensitive_data(data, redact_value="<hidden>")

        assert result["password"] == "<hidden>"

    def test_nested_dict_sanitization(self):
        """Test nested dictionary sanitization."""
        data = {
            "config": {
                "api_key": "secret",  # pragma: allowlist secret
                "endpoint": "https://api.example.com",
            },
            "headers": {
                "Authorization": "Bearer token123",  # pragma: allowlist secret
                "Content-Type": "application/json",
            },
        }
        result = sanitize_sensitive_data(data)

        assert result["config"]["api_key"] == "***REDACTED***"
        assert result["config"]["endpoint"] == "https://api.example.com"
        assert result["headers"]["Authorization"] == "***REDACTED***"
        assert result["headers"]["Content-Type"] == "application/json"

    def test_string_with_multiple_patterns(self):
        """Test string with multiple sensitive patterns."""
        data = "token: abc123, password: secret, api_key: xyz789"
        result = sanitize_sensitive_data(data)

        assert "abc123" not in result
        assert "secret" not in result
        assert "xyz789" not in result
        assert "***REDACTED***" in result


class TestRestClientConfig:
    """Test RestClientConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RestClientConfig()

        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.retry_backoff_factor == 2.0
        assert config.verify_ssl is True

    def test_custom_configuration(self):
        """Test custom configuration values."""
        config = RestClientConfig(
            timeout=60,
            max_retries=5,
            retry_backoff_factor=1.5,
            verify_ssl=False,
        )

        assert config.timeout == 60
        assert config.max_retries == 5
        assert config.retry_backoff_factor == 1.5
        assert config.verify_ssl is False

    def test_ssl_cert_path(self):
        """Test SSL certificate path configuration."""
        config = RestClientConfig(verify_ssl="/path/to/cert.pem")
        assert config.verify_ssl == "/path/to/cert.pem"


class TestRestClientInitialization:
    """Test RestClient initialization."""

    def test_minimal_config(self):
        """Test initialization with minimal config."""
        config = RestClientConfig()
        client = RestClient(config)

        assert client.config == config
        assert client.base_url is None
        assert client.auth_token is None
        assert client.session is not None

    def test_with_base_url_and_auth_token(self):
        """Test initialization with base_url and auth_token."""
        config = RestClientConfig()
        client = RestClient(
            config,
            base_url="https://api.example.com",
            auth_token="test_token_123",
        )

        assert client.base_url == "https://api.example.com"
        assert client.auth_token == "test_token_123"

    def test_base_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from base_url."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com/")

        assert client.base_url == "https://api.example.com"

    def test_session_creation(self):
        """Test that session is created."""
        config = RestClientConfig()
        client = RestClient(config)

        assert isinstance(client.session, requests.Session)


class TestBuildUrl:
    """Test _build_url() method."""

    def test_with_base_url_and_endpoint(self):
        """Test URL building with base_url and endpoint."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        url = client._build_url("users/123")
        assert url == "https://api.example.com/users/123"

    def test_with_full_url_no_base_url(self):
        """Test URL building with full URL (no base_url)."""
        config = RestClientConfig()
        client = RestClient(config)

        url = client._build_url("https://api.example.com/users/123")
        assert url == "https://api.example.com/users/123"

    def test_url_joining_edge_cases(self):
        """Test URL joining edge cases."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        # Leading slash in endpoint
        url1 = client._build_url("/users/123")
        assert url1 == "https://api.example.com/users/123"

        # No leading slash in endpoint
        url2 = client._build_url("users/123")
        assert url2 == "https://api.example.com/users/123"

        # Empty endpoint
        url3 = client._build_url("")
        assert url3 == "https://api.example.com/"


class TestBuildHeaders:
    """Test _build_headers() method."""

    def test_with_auth_token(self):
        """Test headers with auth_token (Bearer token added)."""
        config = RestClientConfig()
        client = RestClient(config, auth_token="test_token")

        headers = client._build_headers()
        assert headers["Authorization"] == "Bearer test_token"

    def test_without_auth_token(self):
        """Test headers without auth_token."""
        config = RestClientConfig()
        client = RestClient(config)

        headers = client._build_headers()
        assert "Authorization" not in headers

    def test_custom_headers_merge(self):
        """Test custom headers merge."""
        config = RestClientConfig()
        client = RestClient(config, auth_token="test_token")

        custom_headers = {
            "Content-Type": "application/json",
            "X-Custom-Header": "custom_value",
        }
        headers = client._build_headers(custom_headers)

        assert headers["Authorization"] == "Bearer test_token"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Custom-Header"] == "custom_value"

    def test_custom_authorization_not_overridden(self):
        """Test that custom Authorization header is not overridden."""
        config = RestClientConfig()
        client = RestClient(config, auth_token="test_token")

        custom_headers = {"Authorization": "Custom auth_value"}
        headers = client._build_headers(custom_headers)

        assert headers["Authorization"] == "Custom auth_value"


class TestCallRestJson:
    """Test call_rest_json() method."""

    @patch.object(RestClient, "call_rest")
    def test_returns_parsed_dict(self, mock_call_rest):
        """Test that call_rest_json returns the parsed JSON dict, not the Response."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.json.return_value = {"id": 1, "name": "Alice"}
        mock_call_rest.return_value = mock_response

        result = client.call_rest_json(
            method=RestMethod.GET,
            url="/users/1",
        )

        assert result == {"id": 1, "name": "Alice"}
        mock_call_rest.assert_called_once()
        mock_response.json.assert_called_once()

    @patch.object(RestClient, "call_rest")
    def test_delegates_to_call_rest_with_all_params(self, mock_call_rest):
        """Test that call_rest_json forwards all parameters to call_rest."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_call_rest.return_value = mock_response

        json_data = {"name": "new_user", "email": "user@example.com"}
        client.call_rest_json(
            method=RestMethod.POST,
            url="/users",
            json_data=json_data,
        )

        mock_call_rest.assert_called_once_with(
            method=RestMethod.POST,
            url="/users",
            action=None,
            json_data=json_data,
            form_data=None,
            query_params=None,
            headers=None,
            expected_status_codes=None,
            timeout=None,
            verify=None,
        )


class TestCallRest:
    """Test call_rest() method."""

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_successful_request(self, mock_call_rest_method):
        """Test successful request."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_call_rest_method.return_value = mock_response

        response = client.call_rest(
            method=RestMethod.GET,
            url="/users",
        )

        assert response.status_code == 200
        mock_call_rest_method.assert_called_once()

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_with_custom_headers(self, mock_call_rest_method):
        """Test request with custom headers."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        custom_headers = {"X-Custom": "value"}
        client.call_rest(
            method=RestMethod.GET,
            url="/users",
            headers=custom_headers,
        )

        call_args = mock_call_rest_method.call_args
        assert "X-Custom" in call_args[1]["headers"]

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_with_query_parameters(self, mock_call_rest_method):
        """Test request with query parameters."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        params = {"page": 1, "limit": 10}
        client.call_rest(
            method=RestMethod.GET,
            url="/users",
            query_params=params,
        )

        call_args = mock_call_rest_method.call_args
        assert call_args[1]["params"] == params

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_with_request_body(self, mock_call_rest_method):
        """Test request with request body."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        json_data = {"name": "test"}
        client.call_rest(
            method=RestMethod.POST,
            url="/users",
            json_data=json_data,
        )

        call_args = mock_call_rest_method.call_args
        assert call_args[1]["json_data"] == json_data

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_http_error_handling(self, mock_call_rest_method):
        """Test HTTP error handling (4xx, 5xx)."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        with pytest.raises(ExternalServiceError) as exc_info:
            client.call_rest(
                method=RestMethod.GET,
                url="/users/999",
            )

        assert exc_info.value.error_code == ErrorCode.HTTP_ERROR
        assert exc_info.value.status_code == 404


class TestCallRestMethodRetryLogic:
    """Test _call_rest_method() retry logic."""

    @patch("requests.Session.request")
    def test_successful_request_no_retry(self, mock_request):
        """Test successful request (no retry)."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_request.return_value = mock_response

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users",
        )

        assert response.status_code == 200
        assert mock_request.call_count == 1

    @patch("requests.Session.request")
    def test_retry_on_connection_error(self, mock_request):
        """Test retry on ConnectionError."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_request.side_effect = [
            ConnectionError("Connection failed"),
            ConnectionError("Connection failed"),
            Mock(status_code=200, headers={}),
        ]

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users",
        )

        assert response.status_code == 200
        assert mock_request.call_count == 3

    @patch("requests.Session.request")
    def test_retry_on_timeout(self, mock_request):
        """Test retry on Timeout."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_request.side_effect = [
            Timeout("Request timeout"),
            Mock(status_code=200, headers={}),
        ]

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users",
        )

        assert response.status_code == 200
        assert mock_request.call_count == 2

    @patch("requests.Session.request")
    def test_retry_on_5xx_status_codes(self, mock_request):
        """Test retry on 5xx status codes."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        mock_response_500.headers = {}
        mock_response_500.raise_for_status.side_effect = HTTPError("Server error")

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.headers = {}

        mock_request.side_effect = [
            mock_response_500,
            mock_response_200,
        ]

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users",
        )

        assert response.status_code == 200
        assert mock_request.call_count == 2

    @patch("requests.Session.request")
    def test_expected_status_codes_suppress_raise(self, mock_request):
        """Test that expected_status_codes prevents HTTPError from being raised."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found")
        mock_request.return_value = mock_response

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users/999",
            expected_status_codes=[404],
        )

        assert response.status_code == 404
        assert mock_request.call_count == 1

    @patch("requests.Session.request")
    def test_no_retry_on_4xx_status_codes(self, mock_request):
        """Test no retry on 4xx status codes."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_request.return_value = mock_response

        response = client._call_rest_method(
            method=RestMethod.GET,
            url="https://api.example.com/users/999",
        )

        assert response.status_code == 404
        assert mock_request.call_count == 1

    @patch("requests.Session.request")
    def test_max_retries_exhausted(self, mock_request):
        """Test max retries exhausted."""
        config = RestClientConfig()
        client = RestClient(config)

        mock_request.side_effect = ConnectionError("Connection failed")

        with pytest.raises(ConnectionError):
            client._call_rest_method(
                method=RestMethod.GET,
                url="https://api.example.com/users",
            )

        assert mock_request.call_count == 3


class TestErrorHandling:
    """Test error handling."""

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_docpipe_exception_raised_on_http_errors(self, mock_call_rest_method):
        """Test DocpipeException raised on HTTP errors."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        with pytest.raises(ExternalServiceError) as exc_info:
            client.call_rest(
                method=RestMethod.GET,
                url="/users",
            )

        assert isinstance(exc_info.value, ExternalServiceError)
        assert exc_info.value.error_code == ErrorCode.HTTP_ERROR

    @patch.object(RestClient, "_call_rest_method_impl")
    def test_error_message_formatting(self, mock_call_rest_method):
        """Test error message formatting."""
        config = RestClientConfig()
        client = RestClient(config, base_url="https://api.example.com")

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden: Access denied"
        mock_response.headers = {}
        mock_call_rest_method.return_value = mock_response

        with pytest.raises(ExternalServiceError) as exc_info:
            client.call_rest(
                method=RestMethod.GET,
                url="/admin",
            )

        error_message = str(exc_info.value)
        assert "403" in error_message
        assert "Forbidden" in error_message

    @patch("requests.Session.request")
    @patch("docpipe.integrations.rest_client.logger")
    def test_sanitized_logging_on_errors(self, mock_logger, mock_request):
        """Test sanitized logging on errors."""
        config = RestClientConfig()
        client = RestClient(
            config,
            base_url="https://api.example.com",
            auth_token="secret_token_123",
        )

        mock_request.side_effect = requests.exceptions.ConnectionError("Connection error")

        with pytest.raises(ExternalServiceError):
            client.call_rest(
                method=RestMethod.GET,
                url="/users",
                headers={"X-API-Key": "secret_key"},
            )

        # Both info (request start) and debug (headers) fire from _call_rest_method_impl
        assert mock_logger.info.called or mock_logger.debug.called

        # Check that sensitive data was sanitized across all log calls
        all_calls = [str(c) for c in mock_logger.info.call_args_list + mock_logger.debug.call_args_list]
        all_str = " ".join(all_calls)
        assert "secret_token_123" not in all_str
        assert "secret_key" not in all_str


class TestMethodConfig:
    """Test METHOD_CONFIG constant."""

    def test_method_config_structure(self):
        """Test METHOD_CONFIG has correct structure."""
        assert RestMethod.GET in METHOD_CONFIG
        assert RestMethod.POST in METHOD_CONFIG
        assert RestMethod.PUT in METHOD_CONFIG
        assert RestMethod.PATCH in METHOD_CONFIG
        assert RestMethod.DELETE in METHOD_CONFIG

    def test_get_method_config(self):
        """Test GET method configuration."""
        config = METHOD_CONFIG[RestMethod.GET]
        assert config["expected_status_codes"] == [200]
        assert config["supports_body"] is False

    def test_post_method_config(self):
        """Test POST method configuration."""
        config = METHOD_CONFIG[RestMethod.POST]
        assert config["expected_status_codes"] == [200, 201, 207]
        assert config["supports_body"] is True

    def test_put_method_config(self):
        """Test PUT method configuration."""
        config = METHOD_CONFIG[RestMethod.PUT]
        assert config["expected_status_codes"] == [200, 201, 204]
        assert config["supports_body"] is True

    def test_patch_method_config(self):
        """Test PATCH method configuration."""
        config = METHOD_CONFIG[RestMethod.PATCH]
        assert config["expected_status_codes"] == [200, 204]
        assert config["supports_body"] is True

    def test_delete_method_config(self):
        """Test DELETE method configuration."""
        config = METHOD_CONFIG[RestMethod.DELETE]
        assert config["expected_status_codes"] == [200, 204]
        assert config["supports_body"] is False
