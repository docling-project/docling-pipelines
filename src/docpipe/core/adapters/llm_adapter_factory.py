"""Unified adapter factory for LLM operations across all providers.

This module provides a centralized factory for creating adapters for:
- LLM inference (chat and text generation)
- Embedding generation
- Text detection (PII/HAP)

Supports two providers:
- WatsonX: IBM watsonx.ai models
- LiteLLM: Unified interface for 100+ LLM providers including Ollama, HuggingFace, OpenAI, etc.
"""

from typing import Any, ClassVar

from docpipe.core.adapters.huggingface import HuggingFaceAdapter
from docpipe.core.adapters.litellm import LiteLLMAdapter
from docpipe.core.adapters.watsonx import WatsonXAdapter
from docpipe.core.constants.constants import ServiceConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.core.ports.text_detection_port import TextDetectionPort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class LLMAdapterFactory:
    """Factory for creating LLM adapters across all capabilities.

    This factory supports three providers:
    - WatsonX: IBM watsonx.ai models for inference, embeddings, and text detection
    - LiteLLM: Unified interface for 100+ LLM providers including:
      * Ollama (via OpenAI-compatible API with model prefix 'openai/')
      * HuggingFace API (via API with model prefix 'huggingface/')
      * OpenAI, Anthropic, Cohere, AWS Bedrock, Google Vertex AI, and 90+ more
    - HuggingFace: Direct HuggingFace support with local model inference or API

    Each provider has a single consolidated adapter that provides all capabilities.
    """

    # Supported providers for inference
    INFERENCE_PROVIDERS: ClassVar[set[str]] = {"watsonx", "litellm"}

    # Supported providers for embeddings
    EMBEDDING_PROVIDERS: ClassVar[set[str]] = {"watsonx", "litellm", "huggingface"}

    # Supported providers for text detection
    TEXT_DETECTION_PROVIDERS: ClassVar[set[str]] = {"watsonx"}

    @staticmethod
    def _positive_int_option(*, provider_config: dict[str, Any], key: str, default: int) -> int:
        """Read a positive integer option from provider_config, falling back to ``default``.

        Missing values use the default silently. Invalid values (non-integers, booleans,
        zero or negative numbers) are reported by the operator's validate(); here they fall
        back to the default with a warning so adapter construction never fails on them.
        """
        value = provider_config.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            logger.warning(
                "Ignoring invalid provider_config.%s=%r; using default %s",
                key,
                value,
                default,
            )
            return default
        return value

    @staticmethod
    def create_inference_adapter(
        *,
        provider: str,
        model_id: str,
        provider_config: dict[str, Any] | None = None,
    ) -> LLMInferencePort:
        """Create an LLM inference adapter for the specified provider.

        Args:
            provider: Provider name ('watsonx' or 'litellm')
            model_id: Model identifier for the provider
            provider_config: Provider-specific configuration dictionary

        Returns:
            Adapter instance with LLMInferencePort interface (chat, generate methods)

        Raises:
            ValueError: If provider is not supported or configuration is invalid

        Examples:
            # WatsonX
            adapter = LLMAdapterFactory.create_inference_adapter(
                provider="watsonx",
                model_id="ibm/granite-13b-chat-v2",
                provider_config={
                    "api_key": "your-api-key",  # pragma: allowlist secret
                    "project_id": "your-project-id",
                    "url": "https://us-south.ml.cloud.ibm.com"
                }
            )

            # LiteLLM with Ollama
            adapter = LLMAdapterFactory.create_inference_adapter(
                provider="litellm",
                model_id="openai/llama2",
                provider_config={
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "<ollama_key>"  # pragma: allowlist secret
                }
            )
        """
        provider = provider.lower()

        if provider not in LLMAdapterFactory.INFERENCE_PROVIDERS:
            raise ValueError(
                f"Unsupported inference provider: {provider}. "
                f"Supported providers: {LLMAdapterFactory.INFERENCE_PROVIDERS}"
            )

        provider_config = provider_config or {}

        if provider == "watsonx":
            return WatsonXAdapter(
                model_name=model_id,
                api_key=provider_config.get("api_key"),
                container_id=provider_config.get("project_id") or provider_config.get("container_id"),
                api_base=provider_config.get("url") or provider_config.get("api_base"),
                container_kind=provider_config.get("container_kind"),
                timeout=provider_config.get("timeout", 120),
            )
        if provider == "litellm":
            # Extract connection-level config (stream, timeout) for the HTTP client
            extra_kwargs = {}
            for key in ("stream", "timeout"):
                if key in provider_config:
                    extra_kwargs[key] = provider_config[key]
            return LiteLLMAdapter(
                model_name=model_id,
                api_key=provider_config.get("api_key"),
                api_base=provider_config.get("api_base"),
                **extra_kwargs,
            )
        raise ValueError(f"Provider '{provider}' not yet implemented for inference")

    @staticmethod
    def create_embedding_adapter(
        *,
        provider: str,
        model_id: str,
        provider_config: dict[str, Any] | None = None,
    ) -> LLMEmbeddingPort:
        """Create an LLM embedding adapter for the specified provider.

        Args:
            provider: Provider name ('watsonx' or 'litellm')
            model_id: Model identifier for the provider
            provider_config: Provider-specific configuration dictionary

        Returns:
            Adapter instance with LLMEmbeddingPort interface (generate_embeddings methods)

        Raises:
            ValueError: If provider is not supported or configuration is invalid

        Examples:
            # WatsonX
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="watsonx",
                model_id="ibm/slate-125m-english-rtrvr",
                provider_config={
                    "api_key": "your-api-key",  # pragma: allowlist secret
                    "project_id": "your-project-id",
                    "url": "https://us-south.ml.cloud.ibm.com"
                }
            )

            # LiteLLM with HuggingFace API
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="litellm",
                model_id="huggingface/sentence-transformers/all-MiniLM-L6-v2",
                provider_config={"api_key": "your-hf-api-key"}  # pragma: allowlist secret
            )

            # HuggingFace with local models
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="huggingface",
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                provider_config={"use_local": True, "device": "cpu"}
            )

            # LiteLLM with Ollama
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="litellm",
                model_id="openai/nomic-embed-text",
                provider_config={
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "<ollama_key>"  # pragma: allowlist secret
                }
            )
        """
        provider = provider.lower()

        if provider not in LLMAdapterFactory.EMBEDDING_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding provider: {provider}. "
                f"Supported providers: {LLMAdapterFactory.EMBEDDING_PROVIDERS}"
            )

        provider_config = provider_config or {}

        if provider == "watsonx":
            return WatsonXAdapter(
                model_name=model_id,
                api_key=provider_config.get("api_key"),
                container_id=provider_config.get("project_id") or provider_config.get("container_id"),
                api_base=provider_config.get("url") or provider_config.get("api_base"),
                container_kind=provider_config.get("container_kind"),
                timeout=provider_config.get("timeout", 120),
                embedding_batch_size=LLMAdapterFactory._positive_int_option(
                    provider_config=provider_config,
                    key=OperatorConstants.Config.BATCH_SIZE,
                    default=ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_BATCH_SIZE,
                ),
                embedding_max_concurrent_requests=LLMAdapterFactory._positive_int_option(
                    provider_config=provider_config,
                    key=OperatorConstants.Config.MAX_CONCURRENT_REQUESTS,
                    default=ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
                ),
            )
        if provider == "litellm":
            return LiteLLMAdapter(
                model_name=model_id,
                api_key=provider_config.get("api_key"),
                api_base=provider_config.get("api_base"),
                batch_size=LLMAdapterFactory._positive_int_option(
                    provider_config=provider_config,
                    key=OperatorConstants.Config.BATCH_SIZE,
                    default=ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
                ),
                max_concurrent_requests=LLMAdapterFactory._positive_int_option(
                    provider_config=provider_config,
                    key=OperatorConstants.Config.MAX_CONCURRENT_REQUESTS,
                    default=ServiceConstants.DEFAULT_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
                ),
            )
        if provider == "huggingface":
            return HuggingFaceAdapter(
                model_name=model_id,
                use_local=provider_config.get("use_local", True),
                api_token=provider_config.get("api_token") or provider_config.get("api_key"),
                device=provider_config.get("device"),
                batch_size=LLMAdapterFactory._positive_int_option(
                    provider_config=provider_config,
                    key=OperatorConstants.Config.BATCH_SIZE,
                    default=ServiceConstants.DEFAULT_EMBEDDINGS_BATCH_SIZE,
                ),
            )
        raise ValueError(f"Provider '{provider}' not yet implemented for embeddings")

    @staticmethod
    def create_text_detection_adapter(
        *,
        provider: str,
        model_id: str,
        provider_config: dict[str, Any],
    ) -> TextDetectionPort:
        """Create a text detection adapter for the specified provider.

        Args:
            provider: Provider name (currently only 'watsonx' is supported)
            model_id: Model identifier for the provider
            provider_config: Provider-specific configuration dictionary

        Returns:
            Adapter instance with TextDetectionPort interface (detect methods)

        Raises:
            ValueError: If provider is not supported or configuration is invalid

        Examples:
            # WatsonX PII/HAP detection
            adapter = LLMAdapterFactory.create_text_detection_adapter(
                provider="watsonx",
                model_id="ibm/granite-13b-chat-v2",
                provider_config={
                    "api_key": "your-api-key",  # pragma: allowlist secret
                    "project_id": "your-project-id",
                    "url": "https://us-south.ml.cloud.ibm.com",
                    "max_tokens": 2000,
                    "temperature": 0.0
                }
            )
        """
        provider = provider.lower()

        if provider not in LLMAdapterFactory.TEXT_DETECTION_PROVIDERS:
            raise ValueError(
                f"Unsupported text detection provider: {provider}. "
                f"Supported providers: {LLMAdapterFactory.TEXT_DETECTION_PROVIDERS}"
            )

        if not model_id:
            raise ValueError("model_id cannot be empty")

        if not provider_config:
            raise ValueError("provider_config cannot be empty")

        if provider == "watsonx":
            return WatsonXAdapter(
                model_name=model_id,
                api_key=provider_config.get("api_key"),
                container_id=provider_config.get("project_id") or provider_config.get("container_id"),
                api_base=provider_config.get("url") or provider_config.get("api_base"),
                container_kind=provider_config.get("container_kind"),
                timeout=provider_config.get("timeout", 120),
            )
        raise ValueError(f"Provider '{provider}' not yet implemented for text detection")

    @staticmethod
    def get_supported_providers(*, capability: str = "inference") -> set[str]:
        """Get the set of supported providers for a specific capability.

        Args:
            capability: Capability type ('inference', 'embedding', or 'text_detection')

        Returns:
            Set of supported provider names for the specified capability

        Raises:
            ValueError: If capability is not recognized
        """
        capability = capability.lower()

        if capability == "inference":
            return LLMAdapterFactory.INFERENCE_PROVIDERS.copy()
        if capability in ("embedding", "embeddings"):
            return LLMAdapterFactory.EMBEDDING_PROVIDERS.copy()
        if capability in ("text_detection", "detection"):
            return LLMAdapterFactory.TEXT_DETECTION_PROVIDERS.copy()
        raise ValueError(f"Unknown capability: {capability}. Supported: 'inference', 'embedding', 'text_detection'")
