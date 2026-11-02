"""HuggingFace adapter for LLM operations.

This adapter provides embeddings using HuggingFace models with support for
both local inference and API-based inference.
"""

from typing import Any

from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.integrations.huggingface.client import HuggingFaceLLMClient


class HuggingFaceAdapter(LLMEmbeddingPort):
    """Adapter for HuggingFace embedding operations.

    Supports both local model inference and HuggingFace Inference API.
    """

    def __init__(
        self,
        model_name: str,
        use_local: bool = True,
        api_token: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
        **kwargs: Any,
    ):
        """Initialize HuggingFace adapter.

        Args:
            model_name: HuggingFace model name (e.g., 'sentence-transformers/all-MiniLM-L6-v2')
            use_local: Use local sentence-transformers (True) or API (False)
            api_token: HuggingFace API token for API inference
            device: Device for local inference ('cpu', 'cuda', 'mps', or None for auto)
            batch_size: Number of texts to process in each batch
            **kwargs: Additional configuration parameters
        """
        self.model_name = model_name
        self.client = HuggingFaceLLMClient(
            model_name=model_name,
            use_local=use_local,
            api_token=api_token,
            device=device,
            batch_size=batch_size,
            **kwargs,
        )

    def generate_embeddings(self, *, text: str) -> list[float]:
        """Generate embeddings for a single text.

        Args:
            text: Input text to embed

        Returns:
            List of floats representing the embedding vector
        """
        return self.client.generate_embeddings(text)

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts to embed

        Returns:
            List of embedding vectors, one per input text
        """
        return self.client.generate_embeddings_batch(texts)

    def get_embedding_batch_size(self) -> int:
        """Return the number of texts encoded per call.

        Concurrency keeps the port default of 1: local inference is CPU/GPU bound and
        the sentence-transformers model is not shared safely across threads.
        """
        return self.client.batch_size

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for this model.

        Returns:
            Dimension of embedding vectors
        """
        return HuggingFaceLLMClient.get_embedding_dimension(self.model_name)

    def validate_embedding(self) -> dict[str, Any]:
        """Validate adapter configuration.

        Returns:
            Dictionary with validation results
        """
        from docpipe.core.constants.constants import LLMConstants

        try:
            # Basic validation - check if client is initialized
            if self.client is None:
                return {
                    LLMConstants.ValidationKeys.VALID: False,
                    LLMConstants.ValidationKeys.CONTEXT: LLMConstants.ValidationContexts.EMBEDDING,
                }

            return {
                LLMConstants.ValidationKeys.VALID: True,
                LLMConstants.ValidationKeys.CONTEXT: LLMConstants.ValidationContexts.EMBEDDING,
            }
        except Exception:
            return {
                LLMConstants.ValidationKeys.VALID: False,
                LLMConstants.ValidationKeys.CONTEXT: LLMConstants.ValidationContexts.EMBEDDING,
            }


# Made with Bob
