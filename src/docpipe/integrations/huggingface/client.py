# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
HuggingFace LLM Client for embeddings operations.

Provides support for both local sentence-transformers models
and HuggingFace Inference API with thread-safe execution.
"""

import os
import threading
from typing import Any, ClassVar

from docpipe.exceptions.docpipe_exceptions import (
    ConfigurationError,
    ExternalServiceError,
)
from docpipe.integrations.base_llm_client import BaseLLMClient, require_package, retry_with_backoff
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# HuggingFace model configurations
HUGGINGFACE_MODEL_TOKEN_LIMITS: dict[str, int] = {
    "sentence-transformers/all-MiniLM-L6-v2": 512,
    "sentence-transformers/all-mpnet-base-v2": 512,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 512,
    "BAAI/bge-small-en-v1.5": 512,
    "BAAI/bge-base-en-v1.5": 512,
    "BAAI/bge-large-en-v1.5": 512,
}

HUGGINGFACE_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-mpnet-base-v2": 768,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
}

DEFAULT_TOKEN_LIMIT = 512
DEFAULT_EMBEDDING_DIMENSION = 384


class HuggingFaceLLMClient(BaseLLMClient):
    """
    HuggingFace LLM client for embeddings operations.

    Supports:
    - Local inference using sentence-transformers
    - Remote inference via HuggingFace Inference API
    - Thread-safe model loading and inference
    - Device selection (cpu, cuda, mps)
    """

    # Class-level lock for thread-safe model loading
    _model_lock = threading.Lock()
    _loaded_models: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        model_name: str,
        use_local: bool = True,
        api_token: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
        **kwargs,
    ):
        """
        Initialize HuggingFace client.

        Args:
            model_name: HuggingFace model name (e.g., 'sentence-transformers/all-MiniLM-L6-v2')
            use_local: Use local sentence-transformers (True) or API (False)
            api_token: HuggingFace API token (falls back to HF_TOKEN env var)
            device: Device for local inference ('cpu', 'cuda', 'mps', or None for auto)
            batch_size: Number of texts to process in each batch (default: 32)
            **kwargs: Additional configuration parameters

        Raises:
            ImportError: If required packages are not installed
            ValueError: If API token is missing for remote inference
        """
        super().__init__(model_name, **kwargs)

        self.use_local = use_local
        self.api_token = api_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self.device = device
        self.batch_size = batch_size
        self.model: Any = None
        self.client: Any = None

        if self.use_local:
            self._initialize_local_model()
        else:
            self._initialize_api_client()

        logger.info(
            "Initialized HuggingFace client with model '%s' (mode: %s)",
            model_name,
            "local" if use_local else "API",
        )

    def _initialize_local_model(self) -> None:
        """
        Initialize local sentence-transformers model with thread safety.

        Raises:
            ImportError: If sentence-transformers is not installed
        """
        require_package("sentence_transformers", "pip install sentence-transformers")
        from sentence_transformers import SentenceTransformer

        # Thread-safe model loading
        with self._model_lock:
            # Check if model is already loaded
            cache_key = f"{self.model_name}_{self.device}"
            if cache_key in self._loaded_models:
                self.model = self._loaded_models[cache_key]
                logger.debug("Using cached model: %s", cache_key)
                return

            # Load new model
            logger.info("Loading local model: %s", self.model_name)
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self._loaded_models[cache_key] = self.model

    def _initialize_api_client(self) -> None:
        """
        Initialize HuggingFace Inference API client.

        Raises:
            ImportError: If huggingface_hub is not installed
            ValueError: If API token is missing
        """
        if not self.api_token:
            raise ConfigurationError(
                "HuggingFace API token required for remote inference. "
                "Set HF_TOKEN or HUGGINGFACE_TOKEN environment variable "
                "or pass 'api_token' parameter."
            )

        require_package("huggingface_hub", "pip install huggingface_hub")
        from huggingface_hub import InferenceClient

        self.client = InferenceClient(token=self.api_token)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings using HuggingFace.

        Args:
            text: Input text to generate embeddings for

        Returns:
            List of floats representing the embedding vector

        Raises:
            ValueError: If text is invalid or embeddings are malformed
            RuntimeError: If inference fails
        """
        self._validate_text_input(text)

        try:
            if self.use_local:
                return self._generate_local_embeddings(text)
            return self._generate_api_embeddings(text)

        except Exception as e:
            logger.error("Failed to generate embeddings with HuggingFace: %s", e)
            raise ExternalServiceError(
                f"Failed to generate embeddings with HuggingFace model '{self.model_name}': {e}"
            ) from e

    def _generate_local_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings using local sentence-transformers model.

        Args:
            text: Input text

        Returns:
            Embedding vector as list of floats
        """
        if self.model is None:
            raise ConfigurationError("Local model not initialized")

        # Thread-safe inference
        with self._model_lock:
            embedding = self.model.encode(text, convert_to_numpy=True)

        # Convert numpy array to list
        embeddings = embedding.tolist()
        self._validate_embeddings_output(embeddings)
        return embeddings

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts: List of input texts to generate embeddings for

        Returns:
            List of embedding vectors, one per input text

        Raises:
            ValueError: If texts are invalid or embeddings are malformed
            RuntimeError: If inference fails
        """
        if not texts or not isinstance(texts, list):
            raise ConfigurationError("texts must be a non-empty list")

        if not all(isinstance(t, str) and t for t in texts):
            raise ConfigurationError("all texts must be non-empty strings")

        try:
            if self.use_local:
                return self._generate_local_embeddings_batch(texts, self.batch_size)
            return self._generate_api_embeddings_batch(texts, self.batch_size)

        except Exception as e:
            logger.error("Failed to generate batch embeddings with HuggingFace: %s", e)
            raise ExternalServiceError(
                f"Failed to generate batch embeddings with HuggingFace model '{self.model_name}': {e}"
            ) from e

    def _generate_local_embeddings_batch(self, texts: list[str], batch_size: int) -> list[list[float]]:
        """
        Generate embeddings for multiple texts using local sentence-transformers model.

        Args:
            texts: List of input texts
            batch_size: Number of texts to process in each batch

        Returns:
            List of embedding vectors as lists of floats
        """
        if self.model is None:
            raise ConfigurationError("Local model not initialized")

        # Thread-safe batch inference
        with self._model_lock:
            embeddings = self.model.encode(texts, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)

        # Convert numpy array to list of lists
        embeddings_list = embeddings.tolist()

        # Validate each embedding
        for emb in embeddings_list:
            self._validate_embeddings_output(emb)

        return embeddings_list

    @staticmethod
    def _parse_feature_extraction_response(response: Any) -> list[float]:
        """
        Normalise the raw response from ``client.feature_extraction`` into a
        flat list of floats.

        The HuggingFace client returns one of three shapes depending on the
        model and SDK version:
        - numpy array  → call ``.tolist()``, then unwrap outer list if nested
        - nested list  → take ``response[0]``
        - flat list    → use as-is
        """
        if hasattr(response, "tolist"):
            embeddings = response.tolist()
            return embeddings[0] if isinstance(embeddings[0], list) else embeddings
        if isinstance(response, list):
            return response[0] if isinstance(response[0], list) else response
        raise ExternalServiceError(f"Unexpected response format from HuggingFace API: {type(response)}")

    def _generate_api_embeddings_batch(self, texts: list[str], batch_size: int) -> list[list[float]]:
        """
        Generate embeddings for multiple texts using HuggingFace Inference API.

        Note: API batching is done client-side by splitting into smaller batches
        to avoid rate limits and timeouts.

        Args:
            texts: List of input texts
            batch_size: Number of texts to process in each batch

        Returns:
            List of embedding vectors as lists of floats
        """
        if self.client is None:
            raise ConfigurationError("API client not initialized")

        all_embeddings = []

        # Process in batches to avoid rate limits
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            # Process each text in the batch (API doesn't support true batching)
            batch_embeddings = []
            for text in batch:
                response = self.client.feature_extraction(text, model=self.model_name)
                embeddings = self._parse_feature_extraction_response(response)
                self._validate_embeddings_output(embeddings)
                batch_embeddings.append(embeddings)

            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _generate_api_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings using HuggingFace Inference API.

        Args:
            text: Input text

        Returns:
            Embedding vector as list of floats
        """
        if self.client is None:
            raise ConfigurationError("API client not initialized")

        response = self.client.feature_extraction(text, model=self.model_name)
        embeddings = self._parse_feature_extraction_response(response)
        self._validate_embeddings_output(embeddings)
        return embeddings

    @staticmethod
    def get_model_token_limit(model_name: str) -> int:
        """
        Get the token limit for a HuggingFace model.

        Args:
            model_name: Name of the HuggingFace model

        Returns:
            Maximum token limit for the model
        """
        return HUGGINGFACE_MODEL_TOKEN_LIMITS.get(model_name, DEFAULT_TOKEN_LIMIT)

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the embedding dimension for a HuggingFace model.

        Args:
            model_name: Name of the HuggingFace model

        Returns:
            Embedding dimension for the model
        """
        return HUGGINGFACE_EMBEDDING_DIMENSIONS.get(model_name, DEFAULT_EMBEDDING_DIMENSION)

    def validate_configuration(self) -> None:
        """
        Validate HuggingFace client configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        super().validate_configuration()

        if not self.use_local and not self.api_token:
            raise ConfigurationError(
                "HuggingFace API token required for remote inference. "
                "Set HF_TOKEN or HUGGINGFACE_TOKEN environment variable "
                "or pass 'api_token' parameter."
            )
