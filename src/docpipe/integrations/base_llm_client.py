# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Base LLM Client with common functionality.

Provides abstract base class with retry logic, error handling,
and validation utilities for LLM client implementations.
"""

import random
import time
from abc import ABC, abstractmethod
from functools import wraps
from typing import Any, Callable, ClassVar, TypeVar

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, DependencyError, ExternalServiceError
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Default retry configuration constants
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0
DEFAULT_BACKOFF_FACTOR = 2.0


def retry_with_backoff(
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay: float = 60.0,
    jitter: bool = False,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay between retries
        max_delay: Maximum delay in seconds (caps exponential backoff)
        jitter: Sleep a random duration between 0 and the current delay ("full jitter")
            instead of the exact delay, so concurrent callers do not retry in lockstep
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        """Wrap ``func`` with the configured retry loop."""

        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            """Call ``func``, retrying matching exceptions with exponential backoff."""
            delay = initial_delay

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt < max_retries - 1:
                        sleep_for = random.uniform(0.0, delay) if jitter else delay  # nosec B311 — retry jitter, not security-sensitive
                        logger.warning(
                            "Attempt %s/%s failed for %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            e,
                            sleep_for,
                        )
                        time.sleep(sleep_for)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        logger.error("All %s attempts failed for %s: %s", max_retries, func.__name__, e)
                        raise

            # This should never be reached, but satisfies type checker
            raise RuntimeError(f"Unexpected: retry loop completed without return or exception in {func.__name__}")

        return wrapper

    return decorator


def require_package(package_name: str, install_command: str) -> None:
    """
    Check if a package is available and raise DependencyError if not.

    Args:
        package_name: Name of the package to check (e.g., 'openai', 'litellm')
        install_command: Installation command to include in error message

    Raises:
        DependencyError: If the package is not installed

    Example:
        require_package('openai', 'pip install openai')
    """
    try:
        __import__(package_name)
    except ImportError as exc:
        raise DependencyError(f"{package_name} package not installed. Install with: {install_command}") from exc


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM clients.

    Provides common functionality for embeddings, chat, and generation
    operations with standardized error handling and validation.
    """

    # Sensitive keys that should never be logged
    SENSITIVE_KEYS: ClassVar[set[str]] = {"api_key", "token", "password", "secret", "authorization", "credentials"}

    def __init__(self, model_name: str, **kwargs):
        """
        Initialize base LLM client.

        Args:
            model_name: Name of the model to use
            **kwargs: Additional configuration parameters
        """
        self.model_name = model_name
        self.config = kwargs

    @staticmethod
    def sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
        """
        Sanitize configuration dictionary by removing sensitive keys.

        Args:
            config: Configuration dictionary to sanitize

        Returns:
            Sanitized configuration with sensitive values masked
        """
        sanitized = {}
        for key, value in config.items():
            if any(sensitive in key.lower() for sensitive in BaseLLMClient.SENSITIVE_KEYS):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        return sanitized

    @abstractmethod
    def generate_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings for the given text.

        Args:
            text: Input text to generate embeddings for

        Returns:
            List of floats representing the embedding vector

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        ...

    @abstractmethod
    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts with provider-optimized processing.

        This method processes multiple texts efficiently using provider-specific
        optimization strategies configured during client initialization:
        - HuggingFace: GPU batch processing (40-50% faster)
        - LiteLLM: Reduced API calls (30-40% faster)
        - Ollama: Concurrent requests (20-30% faster)
        - WatsonX: Configurable batch sizes for API rate limiting

        Batch size and concurrency settings are configured per-provider via
        provider_config, not as method parameters.

        Args:
            texts: List of input texts to generate embeddings for

        Returns:
            List of embedding vectors, one per input text

        Raises:
            NotImplementedError: Must be implemented by subclass
            ConfigurationError: If inputs are invalid
            ExternalServiceError: If embedding generation fails
        """
        ...

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt (single-turn).

        Args:
            prompt: Input prompt for generation
            **kwargs: Additional generation parameters

        Returns:
            Generated text as string

        Raises:
            NotImplementedError: If not supported by the provider
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support text generation")

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Generate response from chat messages (multi-turn).

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional chat parameters

        Returns:
            Generated response as string

        Raises:
            NotImplementedError: If not supported by the provider
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support chat")

    @staticmethod
    @abstractmethod
    def get_model_token_limit(model_name: str) -> int:
        """
        Get the token limit for a specific model.

        Args:
            model_name: Name of the model

        Returns:
            Maximum token limit for the model
        """
        ...

    @staticmethod
    @abstractmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the embedding dimension for a specific model.

        Args:
            model_name: Name of the model

        Returns:
            Embedding dimension for the model
        """
        ...

    def validate_configuration(self) -> None:
        """
        Validate client configuration.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if not self.model_name:
            raise ConfigurationError("model_name is required")

    def _validate_text_input(self, text: str) -> None:
        """
        Validate text input for embeddings/generation.

        Args:
            text: Input text to validate

        Raises:
            ConfigurationError: If text is invalid
        """
        if not text or not isinstance(text, str):
            raise ConfigurationError("text must be a non-empty string")

    def _validate_embeddings_output(self, embeddings: list[float]) -> None:
        """
        Validate embeddings output.

        Args:
            embeddings: Embedding vector to validate

        Raises:
            ExternalServiceError: If embeddings are invalid
        """
        if not embeddings or not isinstance(embeddings, list):
            raise ExternalServiceError(
                f"Invalid embeddings from model '{self.model_name}': "
                f"expected non-empty list, got {type(embeddings).__name__}"
            )

        if not all(isinstance(x, (int, float)) for x in embeddings):
            raise ExternalServiceError(
                f"Invalid embeddings from model '{self.model_name}': all elements must be numeric"
            )
