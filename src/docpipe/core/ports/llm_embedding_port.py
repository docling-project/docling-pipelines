"""Common interface for LLM embedding generation.

This port defines the contract for all embedding adapters, enabling
pluggable embedding providers across the docpipe framework.
"""

from abc import ABC, abstractmethod
from typing import Any

from docpipe.core.constants.constants import LLMConstants, ServiceConstants


class LLMEmbeddingPort(ABC):
    """Common interface for embedding generation.

    This port is implemented by provider-specific adapters (WatsonX, LiteLLM, HuggingFace, etc.)
    to provide a unified interface for generating embeddings across all operators.
    """

    @abstractmethod
    def generate_embeddings(self, *, text: str) -> list[float]:
        """Generate embeddings for single text.

        Args:
            text: Input text to embed

        Returns:
            List of embedding values (floats)

        Raises:
            Exception: Provider-specific errors
        """
        ...

    @abstractmethod
    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts to embed

        Returns:
            List of embedding lists, one per input text

        Raises:
            Exception: Provider-specific errors
        """
        ...

    @abstractmethod
    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for this model.

        Returns:
            Dimension of embedding vectors

        Raises:
            Exception: Provider-specific errors
        """
        ...

    def get_embedding_batch_size(self) -> int:
        """Maximum number of texts the adapter sends to the provider in one request.

        Callers that do their own batching (for example the EmbeddingsOperator, which
        batches texts across documents) hand ``generate_embeddings_batch`` at most this
        many texts per call, so every call maps to exactly one provider request and the
        adapter's retry logic re-sends only that request.

        Adapters override this to report their configured batch size.

        Returns:
            Positive number of texts per request
        """
        return ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE

    def get_max_concurrent_requests(self) -> int:
        """Maximum number of ``generate_embeddings_batch`` calls a caller may run concurrently.

        The default of 1 is safe for adapters that are not thread-safe or that run local
        inference. HTTP-based adapters override this with their configured value.

        Returns:
            Positive number of concurrent calls
        """
        return 1

    def validate(self) -> dict[str, Any]:
        """Template method for validation.

        This method defines the validation algorithm structure by calling
        the hook method validate_embedding(). Subclasses override the hook
        method to provide specific validation logic.

        Returns:
            Validation result dictionary from validate_embedding()
        """
        return self.validate_embedding()

    def validate_embedding(self) -> dict[str, Any]:
        """Hook method for embedding validation.

        Default implementation returns a valid result. Subclasses should
        override this method to provide specific validation logic.

        Returns:
            Dictionary with validation result:
                - valid: bool indicating if validation passed
                - context: str indicating validation context ("embedding")
                - message: Optional str with additional information
        """
        return {
            LLMConstants.ValidationKeys.VALID: True,
            LLMConstants.ValidationKeys.CONTEXT: LLMConstants.ValidationContexts.EMBEDDING,
        }
