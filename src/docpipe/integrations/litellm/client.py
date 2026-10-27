# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""
LiteLLM Client for unified multi-provider LLM operations.

Provides a unified interface for multiple LLM providers through LiteLLM,
supporting embeddings and chat completions across OpenAI, Anthropic, Cohere, etc.
"""

import os
from typing import Any

from docpipe.core.constants.constants import ServiceConstants
from docpipe.exceptions.docpipe_exceptions import (
    ConfigurationError,
    ExternalServiceError,
)
from docpipe.integrations.base_llm_client import BaseLLMClient, require_package, retry_with_backoff
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Provider to environment variable mapping
PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_API_KEY",
    "cohere": "COHERE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "vertex_ai": "GOOGLE_APPLICATION_CREDENTIALS",
    "watsonx": "WATSONX_APIKEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

# LiteLLM model configurations (conservative defaults)
LITELLM_MODEL_TOKEN_LIMITS: dict[str, int] = {
    "text-embedding-ada-002": 8191,
    "text-embedding-3-small": 8191,
    "text-embedding-3-large": 8191,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 4096,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
}

DEFAULT_TOKEN_LIMIT = 8191


class LiteLLMLLMClient(BaseLLMClient):
    """
    LiteLLM client for unified multi-provider operations.

    Supports:
    - Embeddings via litellm.embedding()
    - Chat completions via litellm.completion()
    - Multiple providers (OpenAI, Anthropic, Cohere, etc.)
    - Provider-specific API key handling
    """

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        batch_size: int = ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
        **kwargs,
    ):
        """
        Initialize LiteLLM client.

        Args:
            model_name: Model name with optional provider prefix (e.g., 'gpt-4', 'claude-3-opus')
            api_key: API key for the provider (falls back to provider-specific env vars)
            api_base: Optional custom API base URL
            batch_size: Number of texts to process in each batch (default: 32)
            **kwargs: Additional configuration parameters

        Raises:
            ImportError: If litellm package is not installed
            ConfigurationError: If API key is not available
        """
        super().__init__(model_name, **kwargs)

        self.api_base = api_base
        self.batch_size = batch_size
        self.api_key = api_key or self._get_api_key_from_environment(model_name)

        require_package("litellm", "pip install litellm")
        import litellm

        self.litellm = litellm

        # Validate API key availability
        self._validate_api_key()

        # Configure API base if provided
        if self.api_base:
            litellm.api_base = self.api_base

        # Set API key if provided (LiteLLM will use env vars otherwise)
        if self.api_key:
            # Determine provider from model name
            provider = self._get_provider_from_model(model_name)
            self._set_provider_api_key(provider, self.api_key)

        logger.info("Initialized LiteLLM client with model '%s'", model_name)

    def _get_provider_from_model(self, model_name: str) -> str:
        """
        Extract provider name from model string.

        Args:
            model_name: Model name (may include provider prefix)

        Returns:
            Provider name (e.g., 'openai', 'anthropic', 'cohere')
        """
        # Check for explicit provider prefix
        if "/" in model_name:
            return model_name.split("/")[0].lower()

        # Infer from model name patterns
        if model_name.startswith("gpt-") or "text-embedding" in model_name:
            return "openai"
        if model_name.startswith("claude-"):
            return "anthropic"
        if model_name.startswith(("command-", "embed-")):
            return "cohere"
        if model_name.startswith("ollama/"):
            return "ollama"

        # Default to openai
        return "openai"

    def _get_api_key_from_environment(self, model_name: str) -> str | None:
        """
        Resolve provider API key from environment based on model/provider.

        Args:
            model_name: Model name used to infer provider

        Returns:
            API key from the provider-specific environment variable, if present
        """
        provider = self._get_provider_from_model(model_name)
        env_var = PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")
        return os.getenv(env_var)

    def _validate_api_key(self) -> None:
        """
        Validate that API key is available either from parameter or environment.

        Raises:
            ConfigurationError: If API key is not available
        """
        provider = self._get_provider_from_model(self.model_name)
        env_var = PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")

        if self.api_key is None:
            msg = (
                f"API key required for {provider} provider.\n"
                f"Please set {env_var} environment variable or pass api_key parameter.\n"
                f"Example: export {env_var}=your-key-here"
            )
            raise ConfigurationError(msg)

        # Security warning if API key is in parameter (flow config)
        if os.getenv(env_var) and os.getenv(env_var) != self.api_key:
            logger.warning(
                "API key provided via parameter for %s. "
                "For better security, use environment variable %s instead. "
                "API keys in flow files may be committed to version control.",
                provider,
                env_var,
            )

    def _set_provider_api_key(self, provider: str, api_key: str) -> None:
        """
        Set API key for specific provider.

        Args:
            provider: Provider name
            api_key: API key to set
        """
        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "cohere": "COHERE_API_KEY",
            "huggingface": "HUGGINGFACE_API_KEY",
        }

        env_var = env_var_map.get(provider)
        if env_var:
            os.environ[env_var] = api_key

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings using LiteLLM.

        Args:
            text: Input text to generate embeddings for

        Returns:
            List of floats representing the embedding vector

        Raises:
            ValueError: If text is invalid or embeddings are malformed
            RuntimeError: If API call fails
        """
        self._validate_text_input(text)

        try:
            response = self.litellm.embedding(
                model=self.model_name,
                input=text,
                api_key=self.api_key,
                api_base=self.api_base,
                **self.config,
            )

            # Extract embeddings from response
            if hasattr(response, "data") and response.data:
                embeddings = response.data[0]["embedding"]
            elif isinstance(response, dict) and "data" in response:
                embeddings = response["data"][0]["embedding"]
            else:
                msg = f"Unexpected response format from LiteLLM: {type(response)}"
                raise ExternalServiceError(msg)

            self._validate_embeddings_output(embeddings)
            return embeddings

        except Exception as e:
            logger.error("Failed to generate embeddings with LiteLLM: %s", e)
            msg = f"Failed to generate embeddings with LiteLLM model '{self.model_name}': {e}"
            raise ExternalServiceError(msg) from e

    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.

        LiteLLM supports batch embedding requests, which reduces API calls
        and improves performance by 30-40%. Texts are sent in requests of at most
        ``batch_size`` texts; each request is retried on its own, so a transient
        failure re-sends only the request that failed.

        Args:
            texts: List of input texts to generate embeddings for

        Returns:
            List of embedding vectors, one per input text

        Raises:
            ValueError: If texts are invalid or embeddings are malformed
            RuntimeError: If API call fails
        """
        if not texts or not isinstance(texts, list):
            msg = "texts must be a non-empty list"
            raise ConfigurationError(msg)

        if not all(isinstance(t, str) and t for t in texts):
            msg = "all texts must be non-empty strings"
            raise ConfigurationError(msg)

        try:
            all_embeddings = []

            # Process in batches to avoid rate limits and timeouts
            for i in range(0, len(texts), self.batch_size):
                all_embeddings.extend(self._embed_request(batch=texts[i : i + self.batch_size]))

            return all_embeddings

        except Exception as e:
            logger.error("Failed to generate batch embeddings with LiteLLM: %s", e)
            msg = f"Failed to generate batch embeddings with LiteLLM model '{self.model_name}': {e}"
            raise ExternalServiceError(msg) from e

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _embed_request(self, *, batch: list[str]) -> list[list[float]]:
        """
        Send one embedding request for ``batch`` and return its validated vectors.

        Args:
            batch: Texts sent together in a single provider request

        Returns:
            List of embedding vectors, one per text in ``batch``

        Raises:
            ExternalServiceError: If the response format is unexpected or embeddings are malformed
        """
        # LiteLLM supports batch input
        response = self.litellm.embedding(
            model=self.model_name,
            input=batch,
            api_key=self.api_key,
            api_base=self.api_base,
            **self.config,
        )

        # Extract embeddings from response
        if hasattr(response, "data") and response.data:
            batch_embeddings = [item["embedding"] for item in response.data]
        elif isinstance(response, dict) and "data" in response:
            batch_embeddings = [item["embedding"] for item in response["data"]]
        else:
            msg = f"Unexpected response format from LiteLLM: {type(response)}"
            raise ExternalServiceError(msg)

        # Validate each embedding
        for emb in batch_embeddings:
            self._validate_embeddings_output(emb)

        return batch_embeddings

    @staticmethod
    def _extract_streaming_content(response: Any) -> str:
        """Accumulate content from a streamed LiteLLM response."""
        accumulated = ""
        for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    accumulated += delta.content
        return accumulated

    @staticmethod
    def _extract_non_streaming_content(response: Any) -> str:
        """Extract content from a standard (non-streamed) LiteLLM response."""
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content
        if isinstance(response, dict) and "choices" in response:
            return response["choices"][0]["message"]["content"]
        raise ExternalServiceError(f"Unexpected response format from LiteLLM: {type(response)}")

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Generate chat completion using LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Generated response as string

        Raises:
            ValueError: If messages are invalid
            RuntimeError: If API call fails
        """
        if not messages or not isinstance(messages, list):
            msg = "messages must be a non-empty list"
            raise ConfigurationError(msg)

        try:
            # Merge constructor config with call-time parameters
            combined_kwargs = {**self.config, **kwargs}

            # Dynamically read configurations from the Flow JSON (via provider_config)
            requested_timeout = float(combined_kwargs.pop("timeout", 600.0))
            should_stream = combined_kwargs.pop("stream", False)

            response = self.litellm.completion(
                model=self.model_name,
                messages=messages,
                api_key=self.api_key,
                api_base=self.api_base,
                timeout=requested_timeout,
                stream=should_stream,
                **combined_kwargs,
            )

            content = (
                self._extract_streaming_content(response)
                if should_stream
                else self._extract_non_streaming_content(response)
            )

            if not content:
                msg = "Empty response from LiteLLM chat API"
                raise ExternalServiceError(msg)

            return content

        except Exception as e:
            logger.error("Failed to generate chat completion with LiteLLM: %s", e)
            msg = f"Failed to generate chat completion with LiteLLM model '{self.model_name}': {e}"
            raise ExternalServiceError(msg) from e

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt using chat API.

        Args:
            prompt: Input prompt for generation
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text as string
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    @staticmethod
    def get_model_token_limit(model_name: str) -> int:
        """
        Get the token limit for a model.

        Args:
            model_name: Name of the model

        Returns:
            Maximum token limit for the model
        """
        return LITELLM_MODEL_TOKEN_LIMITS.get(model_name, DEFAULT_TOKEN_LIMIT)

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the embedding dimension for a model.

        Args:
            model_name: Name of the model

        Returns:
            Embedding dimension for the model (0 if unknown)
        """
        # LiteLLM supports many models with varying dimensions
        # Return 0 to indicate dimension should be determined at runtime
        return 0

    def validate_configuration(self) -> None:
        """
        Validate LiteLLM client configuration.

        LiteLLM is flexible and can work with various configurations,
        so validation is minimal.
        """
        super().validate_configuration()
