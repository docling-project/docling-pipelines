#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Milvus Client
Handles connection setup, authentication, and lifecycle management for Milvus.
"""

from pathlib import Path
from typing import Any

from pymilvus import MilvusClient as PyMilvusClient

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.secrets.registry import register_secret
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class MilvusClient:
    """
    Manages Milvus client connection and authentication.

    Responsibilities:
    - Connection setup with various authentication methods
    - Client lifecycle management
    - Connection validation
    - Support for both standalone Milvus and wx.data
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int = 19530,
        uri: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str = "default",
        timeout: int = 60,
        auth_type: str | None = None,
        secure: bool = False,
    ) -> None:
        """
        Initialize Milvus client with connection parameters.

        Supports multiple authentication types:
        - standalone: Local Milvus (username & password)
        - grpc: IBM wx.data with gRPC (host & port + username with ibmlhapikey_ prefix & API key as password)
        - uri: URI-based connection with embedded API key (format: https://ibmlhapikey_<username>:<api-key>@<host>:<port>)
        - token: IAM token-based authentication (constructs URI: https://ibmlhtoken_<username>:<token>@<host>:<port>)

        Args:
            host: Milvus server host
            port: Milvus server port (default: 19530)
            uri: Full URI for connection (for 'uri' auth_type)
            token: IAM token for authentication (for 'token' auth_type)
            username: Username for authentication. For wx.data grpc: use ibmlhapikey_ prefix. For token: plain username.
            password: Password for standalone, or API key for grpc auth_type
            database: Database name (default: "default")
            timeout: Connection timeout in seconds
            auth_type: Authentication type (standalone, grpc, uri, token). Required.
        """
        self.host = host
        self.port = port
        self.uri = uri
        self.token = token
        self.username = username
        self.password = password
        self.database = database
        self.timeout = timeout
        self.auth_type = auth_type
        self.secure = secure
        self._client: PyMilvusClient | None = None

    def _validate_host_and_port(self) -> None:
        """
        Validate host and port configuration.

        Args:
            auth_type: Authentication type for error messages

        Raises:
            DocpipeException: If host or port is invalid
        """
        if not self.host:
            raise DocpipeException(
                message=f"MilvusDB Error: 'host' is required for {self.auth_type} auth_type",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise DocpipeException(
                message=f"MilvusDB Error: 'port' must be an integer between 1 and 65535 for {self.auth_type} auth_type",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

    def _validate_parameters(self) -> None:
        """
        Validate connection parameters based on auth_type.

        Raises:
            DocpipeException: If connection parameters are invalid
        """
        # Validate auth_type value
        valid_auth_types = ["standalone", "grpc", "uri", "token", "lite"]

        # Validate auth_type is provided
        if not self.auth_type:
            raise DocpipeException(
                message=f"MilvusDB Error: 'auth_type' is required. Must be one of: {valid_auth_types}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if self.auth_type not in valid_auth_types:
            raise DocpipeException(
                message=f"MilvusDB Error: Invalid auth_type '{self.auth_type}'. Must be one of: {valid_auth_types}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Validations based on auth_type
        if self.auth_type == "lite":
            if not self.uri:
                raise DocpipeException(
                    message="MilvusDB Error: 'uri' is required for lite auth_type — provide a local .db file path",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        elif self.auth_type == "uri":
            if not self.uri:
                raise DocpipeException(
                    message="MilvusDB Error: 'uri' is required for uri auth_type",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        elif self.auth_type == "token":
            self._validate_host_and_port()

            if not self.username:
                raise DocpipeException(
                    message=f"MilvusDB Error: 'username' is required for {self.auth_type} auth_type",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )
            if not self.token:
                raise DocpipeException(
                    message=f"MilvusDB Error: 'token' is required for {self.auth_type} auth_type",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        else:  # standalone or grpc
            self._validate_host_and_port()

            if self.auth_type == "grpc":
                if not self.username or not self.password:
                    raise DocpipeException(
                        message=f"MilvusDB Error: 'username' and 'password' are required for {self.auth_type} auth_type",
                        status_code=400,
                        error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                    )

    def connect(self) -> PyMilvusClient:
        """
        Create and return a Milvus client with appropriate authentication.

        Uses auth_type to determine connection method:
        - standalone: MilvusClient with host/port (username/password)
        - grpc: MilvusClient with host/port + secure=True + username/password (IBM wx.data)
        - uri: MilvusClient with pre-constructed URI (format: https://ibmlhapikey_<username>:<api-key>@<host>:<port>)
        - token: Constructs URI from host/port/username/token (format: https://ibmlhtoken_<username>:<token>@<host>:<port>)

        Returns:
            Configured Milvus client

        Raises:
            DocpipeException: If connection parameters are invalid or connection fails
        """
        self._validate_parameters()

        try:
            # Ref: https://milvus.io/api-reference/pymilvus/v2.6.x/MilvusClient/Client/MilvusClient.md
            client_params: dict[str, Any] = {
                "db_name": self.database,
                "timeout": self.timeout,
            }

            if self.auth_type == "lite":
                # Milvus Lite — embedded local database, no external service required.
                # uri is a local .db file path; db_name and timeout are not supported.
                db_path = Path(self.uri)  # type: ignore[arg-type]
                db_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info("Connecting to Milvus Lite at %s", db_path)
                self._client = PyMilvusClient(str(db_path))
                _ = self._client.list_collections()
                logger.info("Successfully connected to Milvus Lite at %s", db_path)
                return self._client

            if self.auth_type == "uri":
                # URI-based connection with API key embedded
                # Format: https://ibmlhapikey_<username>:<api-key>@<host>:<port>
                client_params["uri"] = self.uri
                client_params["secure"] = self.secure

            elif self.auth_type == "token":
                # Token-based connection - construct URI with IAM token
                # Format: https://ibmlhtoken_<username>:<token>@<host>:<port>
                client_params["uri"] = f"https://{self.host}:{self.port}"
                client_params["secure"] = self.secure
                client_params["token"] = f"ibmlhtoken_{self.username}:{self.token}"

            elif self.auth_type == "grpc":
                # IBM wx.data with gRPC — construct https URI, pass credentials as token
                host = self.host if self.host and self.host.startswith("https://") else f"https://{self.host}"
                client_params["uri"] = f"{host}:{self.port}"
                client_params["secure"] = self.secure
                client_params["token"] = f"{self.username}:{self.password}"

            else:
                # Standalone — construct http URI from host/port
                client_params["uri"] = f"http://{self.host}:{self.port}"
                if self.username and self.password:
                    client_params["token"] = f"{self.username}:{self.password}"

            # Strings built here (user:password, ibmlhtoken_<user>:<token>) and a URI with an embedded key
            # are not the registered values, so register them for scrubbing.
            for derived in (client_params.get("token"), client_params.get("uri") if self.auth_type == "uri" else None):
                if derived:
                    register_secret(value=derived)

            logger.info("Connecting to Milvus [%s]", self.auth_type)
            self._client = PyMilvusClient(**client_params)

            # Test connection
            _ = self._client.list_collections()
            logger.info("Successfully connected to Milvus using %s authentication type", self.auth_type)
            return self._client

        except Exception as exc:
            raise DocpipeException(
                message=f"MilvusDB Error: Failed to connect using {self.auth_type} auth_type: {exc}",
                status_code=503,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from exc

    def get_client(self) -> PyMilvusClient:
        """
        Get the Milvus client, creating it if necessary.

        Returns:
            Milvus client instance
        """
        if self._client is None:
            self._client = self.connect()
        return self._client

    def test_connection(self) -> bool:
        """
        Test the connection to Milvus.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            client = self.get_client()
            _ = client.list_collections()
            return True
        except Exception as e:
            logger.error("Connection test failed: %s", e)
            return False

    def close(self) -> None:
        """Close the Milvus client connection."""
        if self._client is not None:
            try:
                self._client.close()
                logger.info("Milvus client connection closed")
            except Exception as e:
                logger.warning("Error closing Milvus client: %s", e)
            finally:
                self._client = None
