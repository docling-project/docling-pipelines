"""Unified LiteLLM adapter for inference and embeddings.

This adapter consolidates all LiteLLM capabilities into a single class,
providing a unified interface for:
- LLM inference (chat and text generation)
- Embedding generation

Supports 100+ providers including OpenAI, Anthropic, Cohere, and Ollama.
"""

from typing import Any

from docpipe.core.constants.constants import LLMConstants, ServiceConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.integrations.litellm.client import LiteLLMLLMClient

# Validation Messages
MSG_MODEL_NAME_REQUIRED = "model_name is required"
MSG_API_KEY_VALIDATION_FAILED = "API key validation failed: {error}"  # pragma: allowlist secret


class LiteLLMAdapter(LLMInferencePort, LLMEmbeddingPort):
    """Unified LiteLLM adapter for all LLM capabilities.

    This adapter provides a single interface for LiteLLM operations including
    inference and embeddings across 100+ providers.

    Supports multiple providers:
    - Native LiteLLM providers (OpenAI, Anthropic, Cohere, etc.)
    - Ollama via OpenAI-compatible API (api_base: http://localhost:11434/v1)
    - HuggingFace models via LiteLLM integration

    Attributes:
        client: LiteLLM client instance
        model_name: Default model name (can be overridden per method call)
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        batch_size: int = ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
        max_concurrent_requests: int = ServiceConstants.DEFAULT_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
        **kwargs: Any,
    ):
        """Initialize unified LiteLLM adapter.

        Args:
            model_name: Model identifier with optional provider prefix
                - OpenAI: "gpt-4", "text-embedding-ada-002"
                - Ollama: "openai/llama2", "openai/nomic-embed-text"
                - HuggingFace: "huggingface/sentence-transformers/all-MiniLM-L6-v2"
            api_key: API key for the provider (use "ollama" for Ollama)
            api_base: API base URL (e.g., "http://localhost:11434/v1" for Ollama)
            batch_size: Maximum number of texts per embedding request (default: 32)
            max_concurrent_requests: Maximum number of embedding requests a caller may keep
                in flight at once against this adapter (default: 4)
            **kwargs: Additional LiteLLM client parameters

        Examples:
            # OpenAI
            adapter = LiteLLMAdapter(
                model_name="gpt-4",
                api_key="sk-..."  # pragma: allowlist secret
            )

            # Ollama
            adapter = LiteLLMAdapter(
                model_name="openai/llama2",
                api_key="ollama",  # pragma: allowlist secret
                api_base="http://localhost:11434/v1"
            )

            # HuggingFace
            adapter = LiteLLMAdapter(
                model_name="huggingface/sentence-transformers/all-MiniLM-L6-v2",
                api_key="your-hf-api-key"  # pragma: allowlist secret
            )
        """
        self.client = LiteLLMLLMClient(
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
            batch_size=batch_size,
            **kwargs,
        )
        self.model_name = model_name
        self._max_concurrent_requests = max_concurrent_requests
        self._dimension: int | None = None

    # ==================== Inference Methods ====================

    def chat(
        self,
        *,
        model_name: str | None = None,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Multi-turn chat completion using LiteLLM.

        Args:
            model_name: Model identifier (uses default if not provided)
            messages: List of message dicts with 'role' and 'content' keys
            response_format: Optional response format specification (e.g., {"type": "json_object"})
            **kwargs: LiteLLM-specific parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text response

        Raises:
            Exception: LiteLLM client errors

        Examples:
            # Regular chat
            response = adapter.chat(messages=[
                {"role": "user", "content": "Hello"}
            ])

            # JSON response format
            response = adapter.chat(
                messages=[{"role": "user", "content": "List 3 colors"}],
                response_format={"type": "json_object"}
            )
        """
        # Add response_format to kwargs if provided
        if response_format:
            kwargs["response_format"] = response_format

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model and effective_model != self.client.model_name:
            self.client.model_name = effective_model

        return self.client.chat(messages=messages, **kwargs)

    def generate(
        self,
        *,
        model_name: str | None = None,
        prompt: str,
        response_format: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Single-turn text generation using LiteLLM.

        Args:
            model_name: Model identifier (uses default if not provided)
            prompt: Input prompt text
            response_format: Optional response format specification (e.g., {"type": "json_object"})
            **kwargs: LiteLLM-specific parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text response

        Raises:
            Exception: LiteLLM client errors

        Examples:
            # Regular generation
            response = adapter.generate(prompt="Write a haiku")

            # JSON response format
            response = adapter.generate(
                prompt="List 3 colors in JSON",
                response_format={"type": "json_object"}
            )
        """
        # Add response_format to kwargs if provided
        if response_format:
            kwargs["response_format"] = response_format

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model and effective_model != self.client.model_name:
            self.client.model_name = effective_model

        return self.client.generate(prompt=prompt, **kwargs)

    # ==================== Embedding Methods ====================

    def generate_embeddings(
        self,
        *,
        model_name: str | None = None,
        text: str,
        **kwargs: Any,
    ) -> list[float]:
        """Generate embeddings for single text using LiteLLM.

        Args:
            model_name: Embedding model identifier (uses default if not provided)
            text: Input text to embed
            **kwargs: Additional LiteLLM parameters

        Returns:
            List of embedding values (floats)

        Raises:
            Exception: LiteLLM client errors

        Examples:
            # OpenAI embeddings
            embeddings = adapter.generate_embeddings(
                model_name="text-embedding-ada-002",
                text="Hello world"
            )

            # Ollama embeddings
            embeddings = adapter.generate_embeddings(
                model_name="openai/nomic-embed-text",
                text="Hello world"
            )
        """
        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model and effective_model != self.client.model_name:
            self.client.model_name = effective_model

        return self.client.generate_embeddings(text=text)

    def generate_embeddings_batch(
        self,
        *,
        model_name: str | None = None,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts using LiteLLM.

        Args:
            model_name: Embedding model identifier (uses default if not provided)
            texts: List of input texts to embed
            **kwargs: Additional LiteLLM parameters

        Returns:
            List of embedding lists, one per input text

        Raises:
            Exception: LiteLLM client errors

        Examples:
            embeddings = adapter.generate_embeddings_batch(
                model_name="text-embedding-ada-002",
                texts=["Hello", "World"]
            )
        """
        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model and effective_model != self.client.model_name:
            self.client.model_name = effective_model

        return self.client.generate_embeddings_batch(texts=texts)

    def get_embedding_batch_size(self) -> int:
        """Return the number of texts the LiteLLM client sends per embedding request."""
        return self.client.batch_size

    def get_max_concurrent_requests(self) -> int:
        """Return how many embedding requests callers may keep in flight concurrently."""
        return self._max_concurrent_requests

    def get_embedding_dimension(self, *, model_name: str | None = None) -> int:
        """Get embedding dimension for LiteLLM model.

        Detects dimension by generating a sample embedding if not cached.

        Args:
            model_name: Embedding model identifier (uses default if not provided)

        Returns:
            Dimension of embedding vectors

        Raises:
            Exception: LiteLLM client errors
        """
        if self._dimension is None:
            # Detect dimension by generating sample embedding
            sample = self.generate_embeddings(model_name=model_name, text="test")
            self._dimension = len(sample)
        return self._dimension

    # ==================== Validation Methods ====================

    def _validate_provider_config(self, *, context: str) -> dict[str, Any]:
        """Generic validation that works for all LiteLLM providers.

        Uses a generic approach that:
        1. Validates common requirements (model_name presence)
        2. Leverages LiteLLM's existing validation (delegates to client)

        Args:
            context: Validation context ("inference" or "embedding")

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: Validation context
                - provider: Detected provider name
                - errors: List of validation errors
                - warnings: List of validation warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Detect provider from model name
        provider = self.client._get_provider_from_model(self.model_name)

        # 1. Validate model_name is present
        if not self.model_name or not self.model_name.strip():
            errors.append(MSG_MODEL_NAME_REQUIRED)

        # 2. Check if api_key is available (from parameter or environment)
        # LiteLLM client already handles this in _validate_api_key()
        try:
            self.client._validate_api_key()
        except Exception as e:
            # Only add error if it's a real validation issue
            error_msg = str(e)
            if "API key" in error_msg or "api_key" in error_msg.lower():
                errors.append(MSG_API_KEY_VALIDATION_FAILED.format(error=error_msg))

        return {
            LLMConstants.ValidationKeys.VALID: len(errors) == 0,
            LLMConstants.ValidationKeys.CONTEXT: context,
            LLMConstants.ValidationKeys.PROVIDER: provider,
            LLMConstants.ValidationKeys.ERRORS: errors,
            LLMConstants.ValidationKeys.WARNINGS: warnings,
        }

    def validate_inference(self) -> dict[str, Any]:
        """Hook method override for inference validation.

        Validates provider-specific configuration for LiteLLM inference capabilities.

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: "inference"
                - provider: Detected provider name
                - errors: List of validation errors
                - warnings: List of validation warnings
        """
        return self._validate_provider_config(context=LLMConstants.ValidationContexts.INFERENCE)

    def validate_embedding(self) -> dict[str, Any]:
        """Hook method override for embedding validation.

        Validates provider-specific configuration for LiteLLM embedding capabilities.

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: "embedding"
                - provider: Detected provider name
                - errors: List of validation errors
                - warnings: List of validation warnings
        """
        return self._validate_provider_config(context=LLMConstants.ValidationContexts.EMBEDDING)
