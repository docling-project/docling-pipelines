#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
OpenSearch Client
Handles connection setup, authentication, and lifecycle management for OpenSearch.
"""

from typing import Any

import boto3
from botocore.credentials import Credentials
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from docpipe.exceptions.docpipe_exceptions import TROUBLESHOOTING_DOCS_URL, DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.secrets.registry import register_secret
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OpenSearchClient:
    """
    Manages OpenSearch client connection and authentication.

    Responsibilities:
    - Connection setup with various authentication methods
    - Client lifecycle management
    - Version detection
    - Connection validation
    """

    def __init__(
        self,
        host: str,
        port: int = 9200,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
        aws_auth: bool = False,
        aws_region: str | None = None,
        jwt_token: str | None = None,
        timeout: int = 60,
    ) -> None:
        """
        Initialize OpenSearch client with connection parameters.

        Args:
            host: OpenSearch server host
            port: OpenSearch server port
            username: Username for basic authentication
            password: Password for basic authentication
            use_ssl: Use SSL connection
            verify_certs: Verify SSL certificates
            aws_auth: Use AWS IAM authentication
            aws_region: AWS region for authentication
            jwt_token: JWT token for Bearer authentication
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.verify_certs = verify_certs
        self.aws_auth = aws_auth
        self.aws_region = aws_region
        self.jwt_token = jwt_token
        self.timeout = timeout

        self._client: OpenSearch | None = None
        self._version: tuple[int, int, int] | None = None

    def _validate_parameters(self) -> None:
        """
        Validate connection parameters.

        Raises:
            DocpipeException: If connection parameters are invalid
        """
        if not self.host:
            raise DocpipeException(
                message="host is required",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )
        if not isinstance(self.host, str) or not self.host.strip():
            raise DocpipeException(
                message="host must be a non-empty string",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if not isinstance(self.port, int):
            raise DocpipeException(
                message="port must be an integer",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )
        if self.port < 1 or self.port > 65535:
            raise DocpipeException(
                message="port must be between 1 and 65535",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if self.aws_auth and not self.aws_region:
            raise DocpipeException(
                message="aws_region is required when aws_auth is enabled",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Ensure only one authentication method is used
        auth_methods_count = sum(
            [
                bool(self.username and self.password),
                self.aws_auth,
                bool(self.jwt_token),
            ]
        )
        if auth_methods_count > 1:
            raise DocpipeException(
                message="Only one authentication method allowed: basic auth, AWS IAM, or JWT token",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

    def connect(self) -> OpenSearch:
        """
        Create and return an OpenSearch client with appropriate authentication.

        Returns:
            Configured OpenSearch client

        Raises:
            DocpipeException: If connection parameters are invalid or connection fails
        """
        self._validate_parameters()

        try:
            connection_params: dict[str, Any] = {
                "hosts": [{"host": self.host, "port": self.port}],
                "use_ssl": self.use_ssl,
                "verify_certs": self.verify_certs,
                "connection_class": RequestsHttpConnection,
                "timeout": self.timeout,
            }

            # Add authentication
            if self.aws_auth:
                credentials: Credentials | None = boto3.Session().get_credentials()
                auth: AWSV4SignerAuth = AWSV4SignerAuth(credentials, self.aws_region or "us-east-1")
                connection_params["http_auth"] = auth
            elif self.jwt_token:
                connection_params["http_auth"] = ("Bearer", self.jwt_token)
            elif self.username and self.password:
                connection_params["http_auth"] = (self.username, self.password)
                # The Basic header is the base64 of this string, which the registry derives.
                register_secret(value=f"{self.username}:{self.password}")

            self._client = OpenSearch(**connection_params)
            logger.info("Connected to OpenSearch at %s:%s", self.host, self.port)

            return self._client
        except Exception as exc:
            raise DocpipeException(
                message=f"Failed to connect to OpenSearch at {self.host}:{self.port}: {exc}",
                status_code=503,
                error_code=ErrorCode.OPENSEARCH_CONNECTION_FAILED,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-opensearch-connection-refused",
            ) from exc

    def get_client(self) -> OpenSearch:
        """
        Get the OpenSearch client, creating it if necessary.

        Returns:
            OpenSearch client instance
        """
        if self._client is None:
            self._client = self.connect()
        return self._client

    def get_version(self) -> tuple[int, int, int]:
        """
        Get OpenSearch server version.

        Returns:
            Version tuple (major, minor, patch)
        """
        if self._version is not None:
            return self._version

        try:
            client = self.get_client()
            info: dict[str, Any] = client.info()
            version_string: str = info.get("version", {}).get("number", "0.0.0")
            parts: list[str] = version_string.split(".")
            version_tuple: tuple[int, int, int] = tuple(int(p) for p in parts[:3])  # type: ignore
            self._version = version_tuple
            logger.info("OpenSearch version: %s", ".".join(map(str, version_tuple)))
            return version_tuple
        except Exception as e:
            logger.warning("Could not retrieve OpenSearch version: %s", e)
            self._version = (0, 0, 0)
            return (0, 0, 0)

    def test_connection(self) -> bool:
        """
        Test the connection to OpenSearch.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            client = self.get_client()
            client.info()
            return True
        except Exception as e:
            logger.error("Connection test failed: %s", e)
            return False

    def close(self) -> None:
        """Close the OpenSearch client connection."""
        if self._client is not None:
            try:
                self._client.close()
                logger.info("OpenSearch client connection closed")
            except Exception as e:
                logger.warning("Error closing OpenSearch client: %s", e)
            finally:
                self._client = None
                self._version = None
