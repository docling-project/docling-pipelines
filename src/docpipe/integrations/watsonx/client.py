# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
WatsonX Client for IBM watsonx.ai LLM operations.

Provides a unified interface for interacting with IBM watsonx.ai models,
with support for chat completions and IAM token authentication.
"""

import os
from typing import Any

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.base_llm_client import BaseLLMClient, retry_with_backoff
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.utils.infrastructure.iam_token_manager import IAMTokenManager
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class WatsonXClient(BaseLLMClient):
    """
    WatsonX client for IBM watsonx.ai operations.

    Supports:
    - Chat completions via watsonx.ai text/chat API
    - IAM token authentication
    - Thread-safe token management
    - Automatic token refresh

    Security: api_key and container_id MUST come from environment variables only.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        container_id: str | None = None,
        api_base: str | None = None,
        container_kind: str | None = None,
        timeout: int = 120,
        **kwargs: Any,
    ) -> None:
        """
        Initialize WatsonX client.

        Args:
            model_name: WatsonX model ID (e.g., "ibm/granite-13b-chat-v2")
            api_key: IBM Cloud API key (falls back to WATSONX_API_KEY env var)
            container_id: Project or space ID (falls back to WATSONX_CONTAINER_ID env var)
            api_base: API base URL (falls back to WATSONX_API_BASE_URL env var)
            container_kind: Container type - "project" or "space" (falls back to WATSONX_CONTAINER_KIND env var)
            timeout: Request timeout in seconds (default: 120)
            **kwargs: Additional configuration parameters

        Raises:
            ConfigurationError: If required configuration is missing or invalid

        Security Note:
            Credentials can be provided via parameters or environment variables:
            - api_key parameter or WATSONX_API_KEY env var
            - container_id parameter or WATSONX_CONTAINER_ID env var
        """
        super().__init__(model_name=model_name, **kwargs)

        # Accept credentials from parameters or fall back to environment variables
        self.api_key = api_key or os.getenv("WATSONX_API_KEY")
        self.container_id = container_id or os.getenv("WATSONX_CONTAINER_ID")

        # Non-sensitive config: allow parameters with env var fallback
        self.api_base = api_base or os.getenv("WATSONX_API_BASE_URL")
        self.container_kind = container_kind or os.getenv("WATSONX_CONTAINER_KIND", "project")

        # Validate required configuration
        if not self.api_key:
            msg = (
                "WATSONX_API_KEY environment variable is required. "
                "Set it to your IBM Cloud API key. "
                "For security, API keys must not be passed as parameters."
            )
            raise ConfigurationError(msg)

        if not self.container_id:
            msg = (
                "WATSONX_CONTAINER_ID environment variable is required. "
                "Set it to your watsonx project or space ID. "
                "For security, container IDs must not be passed as parameters."
            )
            raise ConfigurationError(msg)

        if not self.api_base:
            msg = (
                "api_base is required for WatsonX. "
                "Set via api_base parameter or WATSONX_API_BASE_URL environment variable. "
                "Example: https://us-south.ml.cloud.ibm.com"
            )
            raise ConfigurationError(msg)

        if self.container_kind not in ("project", "space"):
            msg = f"container_kind must be 'project' or 'space', got: {self.container_kind}"
            raise ConfigurationError(msg)

        self.timeout = timeout

        # Initialize IAM token manager
        self._token_manager = IAMTokenManager(
            api_key=self.api_key,
            watsonx_url=self.api_base,
        )

        # Configure RestClient
        self._rest_config = RestClientConfig(
            timeout=self.timeout,
            retry_max_attempts=3,
            retry_multiplier=2.0,
            retry_min_wait=1.0,
            retry_max_wait=10.0,
        )

        logger.info(
            "Initialized WatsonXClient with model '%s', container_kind '%s'",
            self.model_name,
            self.container_kind,
        )

    def _get_access_token(self) -> str:
        """
        Get or refresh IAM access token using IAMTokenManager.

        Returns:
            Valid IAM access token

        Raises:
            ExternalServiceError: If token retrieval fails
        """
        try:
            return self._token_manager.get_token()
        except Exception as exc:
            logger.error("Failed to get IAM access token: %s", exc)
            msg = f"Failed to authenticate with watsonx.ai: {exc}"
            raise ExternalServiceError(msg) from exc

    def _get_rest_client(self) -> RestClient:
        """
        Get RestClient with fresh IAM token.

        Returns:
            Configured RestClient instance
        """
        access_token = self._get_access_token()
        return RestClient(config=self._rest_config, auth_token=access_token)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """
        Generate chat completion using WatsonX.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Generated response as string

        Raises:
            ConfigurationError: If messages are invalid
            ExternalServiceError: If API call fails
        """
        if not messages or not isinstance(messages, list):
            err_msg = "messages must be a non-empty list"
            raise ConfigurationError(err_msg)

        try:
            # Convert messages to WatsonX format
            watsonx_messages = []
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "user":
                    # User messages need content array format
                    watsonx_messages.append({"role": role, "content": [{"type": "text", "text": content}]})
                else:
                    # System/assistant messages use simple string format
                    watsonx_messages.append({"role": role, "content": content})

            # Build request payload
            payload: dict[str, Any] = {
                "model_id": self.model_name,
                "messages": watsonx_messages,
                "max_tokens": kwargs.get("max_tokens", 500),
                "temperature": kwargs.get("temperature", 0.0),
                "time_limit": self.timeout * 1000,  # Convert to milliseconds
            }

            # Add container ID
            payload[f"{self.container_kind}_id"] = self.container_id

            # Make API call
            rest_client = self._get_rest_client()
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            chat_url = f"{self.api_base}/ml/v1/text/chat"
            params = {"version": "2023-10-25"}

            logger.debug("Calling WatsonX chat API with model: %s", self.model_name)
            result = rest_client.call_rest_json(
                method=RestMethod.POST,
                url=chat_url,
                json_data=payload,
                headers=headers,
                query_params=params,
                expected_status_codes=[200],
            )

            # Extract response
            choices = result.get("choices", [])
            if not choices:
                err_msg = "No choices in WatsonX API response"
                raise ExternalServiceError(err_msg)

            message = choices[0].get("message", {})
            content = message.get("content", "")

            if not content:
                err_msg = "Empty content in WatsonX API response"
                raise ExternalServiceError(err_msg)

            logger.debug("WatsonX chat completed successfully")
            return content

        except ExternalServiceError as exc:
            # Token manager will automatically refresh on next call
            logger.error("WatsonX chat failed: %s", exc)
            raise

        except Exception as exc:
            logger.error("Unexpected error in WatsonX chat: %s", exc)
            err_msg = f"WatsonX chat failed with model '{self.model_name}': {exc}"
            raise ExternalServiceError(err_msg) from exc

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """
        Generate text from a prompt using chat API.

        Args:
            prompt: Input prompt for generation
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text as string
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages=messages, **kwargs)

    def generate_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings (not supported by WatsonX client).

        WatsonX does not provide a dedicated embeddings API through this client.
        Use sentence-transformers or other embedding models instead.

        Raises:
            NotImplementedError: Always raised as embeddings are not supported
        """
        msg = "WatsonX client does not support embeddings. Use sentence-transformers or other embedding models."
        raise NotImplementedError(msg)

    def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """
        Generate embeddings for multiple texts (not supported).

        Raises:
            NotImplementedError: Always raised as embeddings are not supported
        """
        msg = "WatsonX client does not support embeddings. Use sentence-transformers or other embedding models."
        raise NotImplementedError(msg)

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the embedding dimension (not applicable for WatsonX).

        Returns:
            0 to indicate embeddings are not supported
        """
        return 0

    @staticmethod
    def get_model_token_limit(model_name: str) -> int:
        """
        Get model token limit (not supported for WatsonX).

        WatsonX model token limits are not tracked in the client as they:
        - Change frequently with model updates
        - Vary by model and deployment
        - Should be managed by the WatsonX API itself

        Args:
            model_name: WatsonX model ID

        Raises:
            NotImplementedError: Always raised as token limits are not tracked
        """
        msg = (
            "WatsonX client does not track model token limits. "
            "Token limits vary by model and should be managed by the WatsonX API."
        )
        raise NotImplementedError(msg)

    def validate_configuration(self) -> None:
        """
        Validate WatsonX client configuration.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        super().validate_configuration()

        if not self.api_key:
            msg = "WATSONX_API_KEY environment variable is required"
            raise ConfigurationError(msg)

        if not self.container_id:
            msg = "WATSONX_CONTAINER_ID environment variable is required"
            raise ConfigurationError(msg)

        if not self.api_base:
            msg = "api_base is required for WatsonX"
            raise ConfigurationError(msg)

        if self.container_kind not in ("project", "space"):
            msg = f"container_kind must be 'project' or 'space', got: {self.container_kind}"
            raise ConfigurationError(msg)
