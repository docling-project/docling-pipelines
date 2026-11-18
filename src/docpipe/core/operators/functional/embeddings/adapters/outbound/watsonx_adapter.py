# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Watsonx.ai LLM adapter for embedding generation."""

from typing import Any

from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.models.session_info import get_session_info
from docpipe.core.operators.functional.embeddings.adapters.outbound.factories.llm_adapter_factory import (
    register_llm_adapter,
)
from docpipe.core.operators.functional.embeddings.ports.outbound.llm_service import LLMServicePort
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.integrations.watsonx.model_validator import get_model_dimension, validate_model_id
from docpipe.integrations.watsonx.rest_client import WatsonxRestEmbeddingClient
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Configuration keys for Watsonx provider
WATSONX_API_KEY = "api_key"  # pragma: allowlist secret
WATSONX_URL = "url"
WATSONX_CONTAINER_KIND = "container_kind"
WATSONX_CONTAINER_ID = "container_id"


@register_llm_adapter
class WatsonxLLMAdapter(LLMServicePort):
    """Adapter for IBM watsonx.ai embedding service.

    This adapter provides embeddings using IBM watsonx.ai foundation models
    with support for cloud deployments, batch processing, and automatic
    token truncation.

    Features:
        - Cloud-only deployment (no CPD support)
        - Batch processing with configurable batch size
        - Automatic token truncation
        - Support for both project and space containers
        - REST API-based client for direct API calls
    """

    ADAPTER_NAME = "watsonx"
    ADAPTER_DISPLAY_NAME = "IBM watsonx.ai"

    def __init__(self, model_name: str, **adapter_config: Any) -> None:
        """Initialize watsonx adapter.

        Args:
            model_name: Watsonx.ai model ID (e.g., 'ibm/slate-125m-english-rtrvr')
            **adapter_config: Additional configuration containing:
                - api_key: Watsonx.ai API key
                - url or api_base: Watsonx.ai API endpoint URL (either parameter accepted)
                - container_kind: Container type ("project" or "space")
                - container_id: Container ID (project_id or space_id)
                - batch_size: Optional batch size (default: 800)
                - enable_rate_limiting: Optional boolean to enable WatsonX API rate limiting (default: False)

        Raises:
            ConfigurationError: If required config parameters are missing
        """
        self.model_name = model_name

        # Extract required configuration - handle both direct and nested provider_config
        # The embeddings operator extracts provider_config and passes it directly
        provider_config = adapter_config.get(OperatorConstants.Config.PROVIDER_CONFIG, adapter_config)
        try:
            self.api_key = provider_config[WATSONX_API_KEY]
            # Support both 'url' and 'api_base' parameters for flexibility
            self.url = provider_config.get(WATSONX_URL) or provider_config.get("api_base")
            if not self.url:
                raise KeyError("url or api_base")
            self.container_kind = provider_config[WATSONX_CONTAINER_KIND]
            self.container_id = provider_config[WATSONX_CONTAINER_ID]
        except KeyError as e:
            param_name = e.args[0]
            if param_name == "url or api_base":
                raise ConfigurationError(
                    f"Missing required configuration parameter: 'url' or 'api_base'. "
                    f"provider_config must contain: {WATSONX_API_KEY}, {WATSONX_URL} (or 'api_base'), {WATSONX_CONTAINER_KIND}, {WATSONX_CONTAINER_ID}"
                ) from e
            raise ConfigurationError(
                f"Missing required configuration parameter: '{param_name}'. "
                f"provider_config must contain: {WATSONX_API_KEY}, {WATSONX_URL} (or 'api_base'), {WATSONX_CONTAINER_KIND}, {WATSONX_CONTAINER_ID}"
            ) from e

        # Extract optional configuration
        batch_size = provider_config.get("batch_size", 800)
        enable_rate_limiting = provider_config.get("enable_rate_limiting", False)

        # Get job_run_id from session_info for per-job rate limiting
        # This allows each job run to have its own rate limit in Prefect server mode
        session_info = get_session_info()
        job_run_id = session_info.job_run_id if session_info else None

        # Initialize REST API client
        self.client = WatsonxRestEmbeddingClient(
            api_key=self.api_key,
            url=self.url,
            container_kind=self.container_kind,
            container_id=self.container_id,
            model_name=self.model_name,
            batch_size=batch_size,
            job_run_id=job_run_id,
            enable_rate_limiting=enable_rate_limiting,
        )

        # Validate model availability
        is_valid = validate_model_id(
            model_id=self.model_name,
            api_key=self.api_key,
            url=self.url,
        )

        if not is_valid:
            raise ValueError(
                f"Model '{self.model_name}' is not available. "
                "Check model ID or use get_available_foundation_models() to list models."
            )

        logger.info(
            "Initialized WatsonxLLMAdapter with model=%s, batch_size=%s, enable_rate_limiting=%s, job_run_id=%s",
            model_name,
            batch_size,
            enable_rate_limiting,
            job_run_id or "shared",
        )

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        from docpipe.core.operators.shared.llm_provider_config import WatsonxProviderConfig

        return WatsonxProviderConfig

    def generate_embeddings(self, text: str) -> list[float]:
        """Generate embeddings using watsonx.ai.

        Args:
            text: Input text to embed

        Returns:
            List of floats representing the embedding vector

        Raises:
            Exception: If embedding generation fails
        """
        return self.client.generate_embeddings(text)

    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using watsonx.ai.

        Args:
            texts: List of input texts to embed

        Returns:
            List of embedding vectors, one per input text

        Raises:
            Exception: If embedding generation fails
        """
        return self.client.generate_embeddings_batch(texts)

    def get_model_token_limit(self) -> int:
        """Get token limit for watsonx.ai model.

        Uses the Foundation Models API to dynamically look up the token limit
        for the configured model. Falls back to hardcoded values if API call fails.

        Returns:
            Maximum token limit for the model
        """
        return self.client._get_truncate_tokens()

    def get_embedding_dimension(self) -> int | None:
        """Get embedding dimension for watsonx.ai model.

        Uses the Foundation Models API to dynamically look up the embedding
        dimension for the configured model.

        Returns:
            Embedding dimension if known, None otherwise
        """
        dimension = get_model_dimension(model_id=self.model_name, api_key=self.api_key, url=self.url)
        return dimension if dimension > 0 else None
