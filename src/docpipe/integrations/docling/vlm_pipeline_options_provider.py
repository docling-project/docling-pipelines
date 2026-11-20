#!/usr/bin/env python3
"""
VLM Pipeline Options Providers
Base class and implementations for creating VLM pipeline options for different engines.
"""

import copy
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from docpipe.core.constants import OperatorConstants
from docpipe.core.constants.constants import ServiceConstants
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()

IBM_CLOUD_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"  # nosec B105
IAM_TOKEN_REQUEST_TIMEOUT = 30


class VlmPipelineOptionsProvider(ABC):
    """
    Abstract base class for VLM pipeline options providers.

    Each provider creates complete VlmPipelineOptions for a specific engine type,
    encapsulating all configuration including authentication, engine options, and
    remote services settings.
    """

    @abstractmethod
    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create complete VlmPipelineOptions for this provider.

        Args:
            preset: VLM preset name (e.g., "granite_docling", "qwen2_vl")
            config: Provider-specific configuration dictionary

        Returns:
            VlmPipelineOptions configured for this provider

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        ...

    @abstractmethod
    def validate_config(self, *, config: dict[str, Any]) -> None:
        """
        Validate provider-specific configuration.

        Args:
            config: Provider-specific configuration dictionary

        Raises:
            ValueError: If configuration is invalid or missing required fields
        """
        ...

    @staticmethod
    def _normalize_openai_compatible_url(*, api_base: str | None, default_url: str) -> str:
        """
        Normalize OpenAI-compatible API base URL by appending /v1/chat/completions if needed.

        This method ensures consistent URL handling across all OpenAI-compatible APIs
        (Ollama, OpenAI, LM Studio). Users can provide just the base URL, and this
        method will append the required path if not already present.

        Args:
            api_base: User-provided API base URL (e.g., "http://localhost:11434")
            default_url: Default URL to use if api_base is None

        Returns:
            Normalized URL with /v1/chat/completions path
        """
        if api_base:
            # Normalize URL: append /v1/chat/completions if not already present
            api_base = api_base.rstrip("/")
            if not api_base.endswith("/v1/chat/completions"):
                return f"{api_base}/v1/chat/completions"
            return api_base
        return default_url

    @staticmethod
    def _ensure_markdown_format(*, vlm_options: Any, preset: str) -> None:
        """
        Ensure MARKDOWN format for API-based VLM engines.

        DOCTAGS format is specific to IBM Granite models, while MARKDOWN is universally
        supported by all VLM models (including Granite). This method converts DOCTAGS
        to MARKDOWN for maximum compatibility across all API-based engines.

        Args:
            vlm_options: VLM options from preset
            preset: Preset name for logging
        """
        from docling.datamodel.pipeline_options_vlm_model import ResponseFormat

        if vlm_options.model_spec.response_format == ResponseFormat.DOCTAGS:
            logger.info(
                f"Preset '{preset}' uses DOCTAGS format. Converting to MARKDOWN for universal API compatibility."
            )
            model_spec = copy.deepcopy(vlm_options.model_spec)
            model_spec.response_format = ResponseFormat.MARKDOWN
            model_spec.prompt = (
                "Convert this document page to markdown format. Include all text, tables, and structure."
            )
            model_spec.stop_strings = []
            vlm_options.model_spec = model_spec

class WatsonxPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """
    Pipeline options provider for IBM watsonx.ai.

    Handles IAM token exchange and watsonx-specific configuration.
    """

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for watsonx.ai.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - api_key: IBM Cloud API key (required)
                - container_id: Watsonx container ID (required)
                - container_kind: Container type, defaults to "project" (optional)
                - model_id: Watsonx model ID (required)
                - api_base: API base URL (optional)
                - max_new_tokens: Maximum tokens to generate (optional)

        Returns:
            VlmPipelineOptions configured for watsonx.ai

        Raises:
            ValueError: If required configuration is missing
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

        # Validate configuration
        self.validate_config(config=config)

        # Get IAM token
        api_key = config.get(OperatorConstants.Config.API_KEY)
        if not api_key:
            raise ValueError(f"'{OperatorConstants.Config.API_KEY}' is required for watsonx.ai")

        access_token = self._get_iam_access_token(api_key=api_key)
        logger.info("Successfully obtained IAM access token for watsonx.ai")

        # Prepare headers
        headers = {"Authorization": f"Bearer {access_token}"}

        # Prepare parameters
        container_kind = config.get(OperatorConstants.Config.CONTAINER_KIND, OperatorConstants.ContainerKinds.PROJECT)
        container_id = config.get(OperatorConstants.Config.CONTAINER_ID)

        vlm_model_name = config.get(OperatorConstants.Config.MODEL_ID)
        max_new_tokens = config.get("max_new_tokens", 2048)

        if not container_id:
            raise ValueError(f"'{OperatorConstants.Config.CONTAINER_ID}' is required for watsonx.ai")
        if not vlm_model_name:
            raise ValueError(f"'{OperatorConstants.Config.MODEL_ID}' is required for watsonx.ai")

        params = {
            f"{container_kind}_id": container_id,
            OperatorConstants.Config.MODEL_ID: vlm_model_name,
            OperatorConstants.Config.PARAMETERS: {
                "max_new_tokens": max_new_tokens,
                "temperature": 0.0,  # Deterministic output for document extraction
            },
        }

        api_base_url = config.get(
            OperatorConstants.Config.API_BASE,
            "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat?version=2023-05-29",
        )

        logger.info(f"Using watsonx.ai model: {vlm_model_name} with {container_kind}_id: {container_id}")

        # Get timeout from config, default to 90 seconds
        timeout = config.get(OperatorConstants.Config.REQUEST_TIMEOUT, 90)

        # Create engine options
        engine_options = ApiVlmEngineOptions(
            engine_type=VlmEngineType.API,
            url=api_base_url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        # Create VLM options from preset
        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        # Ensure MARKDOWN format for API engines
        self._ensure_markdown_format(vlm_options=vlm_options, preset=preset)

        # Return complete pipeline options
        return VlmPipelineOptions(vlm_options=vlm_options, enable_remote_services=True)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """
        Validate watsonx.ai configuration.

        Args:
            config: Provider configuration to validate

        Raises:
            ValueError: If required configuration is missing
        """
        # Check for API key
        if not config.get(OperatorConstants.Config.API_KEY):
            raise ValueError(f"'{OperatorConstants.Config.API_KEY}' is required for watsonx.ai")

        # Check for container ID
        if not config.get(OperatorConstants.Config.CONTAINER_ID):
            raise ValueError(f"'{OperatorConstants.Config.CONTAINER_ID}' is required for watsonx.ai")

        # Check for model ID
        if not config.get(OperatorConstants.Config.MODEL_ID):
            raise ValueError(f"'{OperatorConstants.Config.MODEL_ID}' is required for watsonx.ai")

        # Validate api_base if provided
        api_base = config.get(OperatorConstants.Config.API_BASE)
        if api_base and not api_base.startswith("https://"):
            raise ValueError(f"'{OperatorConstants.Config.API_BASE}' must use HTTPS for watsonx.ai")

    @staticmethod
    def _get_iam_access_token(*, api_key: str) -> str:
        """
        Exchange IBM Cloud API key for IAM access token.

        Args:
            api_key: IBM Cloud API key

        Returns:
            IAM access token

        Raises:
            ValueError: If token exchange fails
        """
        try:
            # Create RestClient with appropriate configuration
            config = RestClientConfig(
                timeout=IAM_TOKEN_REQUEST_TIMEOUT,
                retry_max_attempts=3,
                retry_multiplier=2.0,
                retry_min_wait=1.0,
                retry_max_wait=10.0,
            )
            client = RestClient(config=config)

            # Make POST request with form data
            token_data = client.call_rest_json(
                method=RestMethod.POST,
                url=IBM_CLOUD_IAM_TOKEN_URL,
                form_data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": api_key},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if "access_token" not in token_data:
                raise ValueError("Invalid IAM token response")
            return token_data["access_token"]
        except Exception as e:
            logger.error("IAM token exchange failed - authentication error occurred")
            raise ValueError(f"Failed to authenticate with watsonx: {e}") from e


class OpenAIPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for OpenAI API."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for OpenAI.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - api_key: OpenAI API key (required)
                - model_id: Model name (required)
                - api_base: OpenAI base URL (optional, defaults to https://api.openai.com)
                          Automatically appends /v1/chat/completions if not present

        Returns:
            VlmPipelineOptions configured for OpenAI
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

        self.validate_config(config=config)

        api_key = config.get(OperatorConstants.Config.API_KEY)
        vlm_model_name = config.get(OperatorConstants.Config.MODEL_ID)

        if not api_key:
            raise ValueError(f"'{OperatorConstants.Config.API_KEY}' is required for OpenAI")
        if not vlm_model_name:
            raise ValueError(f"'{OperatorConstants.Config.MODEL_ID}' is required for OpenAI")

        headers = {"Authorization": f"Bearer {api_key}"}
        params = {OperatorConstants.Config.MODEL_NAME: vlm_model_name}

        # Normalize API base URL
        api_base_url = self._normalize_openai_compatible_url(
            api_base=config.get(OperatorConstants.Config.API_BASE),
            default_url="https://api.openai.com/v1/chat/completions",
        )

        # Get timeout from config, default to 90 seconds
        timeout = config.get(OperatorConstants.Config.REQUEST_TIMEOUT, 90)

        engine_options = ApiVlmEngineOptions(
            engine_type=VlmEngineType.API_OPENAI,
            url=api_base_url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        # Ensure MARKDOWN format for API engines
        self._ensure_markdown_format(vlm_options=vlm_options, preset=preset)

        logger.info(f"Using OpenAI engine with API base URL: {api_base_url}")

        return VlmPipelineOptions(vlm_options=vlm_options, enable_remote_services=True)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """Validate OpenAI configuration."""
        if not config.get(OperatorConstants.Config.API_KEY):
            raise ValueError(f"'{OperatorConstants.Config.API_KEY}' is required for OpenAI")
        if not config.get(OperatorConstants.Config.MODEL_ID):
            raise ValueError(f"'{OperatorConstants.Config.MODEL_ID}' is required for OpenAI")


class OllamaPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for Ollama."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for Ollama.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - api_base: Ollama base URL (optional, defaults to {OLLAMA_HOST} from env)
                          Automatically appends /v1/chat/completions if not present
                - model_id: Ollama model name (optional, overrides preset default)

        Returns:
            VlmPipelineOptions configured for Ollama
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

        self.validate_config(config=config)

        # Normalize API base URL
        api_base_url = self._normalize_openai_compatible_url(
            api_base=config.get(OperatorConstants.Config.API_BASE),
            default_url=f"{ServiceConstants.DEFAULT_OLLAMA_HOST}/v1/chat/completions",
        )

        vlm_model_name = config.get(OperatorConstants.Config.MODEL_ID)

        # Build params with model name if provided
        params = {}
        if vlm_model_name:
            # Use 'model' key for OpenAI-compatible API
            params["model"] = vlm_model_name
            logger.info(f"Using Ollama model: {vlm_model_name}")

        # Get timeout from config, default to 90 seconds
        timeout = config.get(OperatorConstants.Config.REQUEST_TIMEOUT, 90)

        engine_options = ApiVlmEngineOptions(
            engine_type=VlmEngineType.API_OLLAMA,
            url=api_base_url,
            params=params if params else {},
            timeout=timeout,
        )

        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        # Ensure MARKDOWN format for API engines
        self._ensure_markdown_format(vlm_options=vlm_options, preset=preset)

        logger.info(f"Using Ollama engine with API base URL: {api_base_url}")

        return VlmPipelineOptions(vlm_options=vlm_options, enable_remote_services=True)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """Ollama has minimal configuration requirements."""


class LMStudioPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for LM Studio."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for LM Studio.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - api_base: LM Studio base URL (optional, defaults to http://localhost:1234)
                          Automatically appends /v1/chat/completions if not present

        Returns:
            VlmPipelineOptions configured for LM Studio
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

        self.validate_config(config=config)

        # Normalize API base URL
        api_base_url = self._normalize_openai_compatible_url(
            api_base=config.get(OperatorConstants.Config.API_BASE),
            default_url="http://localhost:1234/v1/chat/completions",
        )

        # Get timeout from config, default to 90 seconds
        timeout = config.get(OperatorConstants.Config.REQUEST_TIMEOUT, 90)

        engine_options = ApiVlmEngineOptions(
            engine_type=VlmEngineType.API_LMSTUDIO,
            url=api_base_url,
            timeout=timeout,
        )

        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        # Ensure MARKDOWN format for API engines
        self._ensure_markdown_format(vlm_options=vlm_options, preset=preset)

        logger.info(f"Using LM Studio engine with API base URL: {api_base_url}")

        return VlmPipelineOptions(vlm_options=vlm_options, enable_remote_services=True)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """LM Studio has minimal configuration requirements."""


class GenericApiPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for generic API endpoints."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for generic API.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - api_base_url: API URL (required)
                - headers: Custom headers dict (optional)
                - params: Custom params dict (optional)
                - api_key: API key for Bearer token auth (optional)

        Returns:
            VlmPipelineOptions configured for generic API
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

        self.validate_config(config=config)

        # Start with custom headers if provided
        headers = config.get("headers", {}).copy() if config.get("headers") else {}

        # Add Bearer token if api_key provided and Authorization not already set
        api_key = config.get(OperatorConstants.Config.API_KEY)
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"

        # Get custom params
        params = (
            config.get(OperatorConstants.Config.PARAMETERS, {}).copy()
            if config.get(OperatorConstants.Config.PARAMETERS)
            else {}
        )

        api_base_url = config.get(OperatorConstants.Config.API_BASE)
        if not api_base_url:
            raise ValueError(f"{OperatorConstants.Config.API_BASE} is required for generic API")

        # Get timeout from config, default to 90 seconds
        timeout = config.get(OperatorConstants.Config.REQUEST_TIMEOUT, 90)

        engine_options = ApiVlmEngineOptions(
            engine_type=VlmEngineType.API,
            url=api_base_url,
            headers=headers if headers else {},
            params=params if params else {},
            timeout=timeout,
        )

        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        # Ensure MARKDOWN format for API engines
        self._ensure_markdown_format(vlm_options=vlm_options, preset=preset)

        logger.info(f"Using generic API engine with URL: {api_base_url}")

        return VlmPipelineOptions(vlm_options=vlm_options, enable_remote_services=True)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """Validate generic API configuration."""
        if not config.get(OperatorConstants.Config.API_BASE):
            raise ValueError(f"{OperatorConstants.Config.API_BASE} is required for generic API")


class TransformersPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for local Transformers inference."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for Transformers.

        Args:
            preset: VLM preset name
            config: Configuration containing:
                - model_id: Model identifier (optional, overrides preset default)

        Returns:
            VlmPipelineOptions configured for Transformers
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import TransformersVlmEngineOptions

        self.validate_config(config=config)

        vlm_model_name = config.get(OperatorConstants.Config.MODEL_ID)

        engine_options = TransformersVlmEngineOptions()
        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        if vlm_model_name:
            model_spec = copy.deepcopy(vlm_options.model_spec)
            model_spec.default_repo_id = vlm_model_name
            vlm_options.model_spec = model_spec
            logger.info(f"Using Transformers engine for local inference with model: {vlm_model_name}")
        else:
            logger.info("Using Transformers engine for local inference")

        return VlmPipelineOptions(vlm_options=vlm_options)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """Transformers has minimal configuration requirements."""


class MlxPipelineOptionsProvider(VlmPipelineOptionsProvider):
    """Pipeline options provider for MLX inference (macOS optimized)."""

    def create_pipeline_options(self, *, preset: str, config: dict[str, Any]) -> Any:
        """
        Create VlmPipelineOptions for MLX.

        Args:
            preset: VLM preset name
            config: Configuration (minimal requirements for local inference)

        Returns:
            VlmPipelineOptions configured for MLX
        """
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import MlxVlmEngineOptions

        self.validate_config(config=config)

        engine_options = MlxVlmEngineOptions()
        vlm_options = VlmConvertOptions.from_preset(preset, engine_options=engine_options)

        logger.info("Using MLX engine for local inference")

        return VlmPipelineOptions(vlm_options=vlm_options)

    def validate_config(self, *, config: dict[str, Any]) -> None:
        """MLX has minimal configuration requirements."""


class VlmPipelineOptionsProviderFactory:
    """
    Factory for creating VLM pipeline options providers.

    Maps engine types to their corresponding provider implementations.
    """

    _providers: ClassVar[dict[str, type[VlmPipelineOptionsProvider]]] = {
        OperatorConstants.Config.VLM_ENGINE_API: GenericApiPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_API_WATSONX: WatsonxPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_API_OPENAI: OpenAIPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_API_OLLAMA: OllamaPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_API_LMSTUDIO: LMStudioPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS: TransformersPipelineOptionsProvider,
        OperatorConstants.Config.VLM_ENGINE_MLX: MlxPipelineOptionsProvider,
    }

    @classmethod
    def get_provider(cls, *, engine_type: str | None) -> VlmPipelineOptionsProvider:
        """
        Get pipeline options provider for the specified engine type.

        Args:
            engine_type: VLM engine type (e.g., "api", "api_watsonx", "transformers", "mlx")

        Returns:
            Instance of appropriate VlmPipelineOptionsProvider

        Raises:
            ValueError: If engine_type is unknown
        """
        # Default to Transformers if no engine type specified
        if not engine_type:
            engine_type = OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS

        provider_class = cls._providers.get(engine_type)
        if not provider_class:
            raise ValueError(f"Unknown VLM engine type: {engine_type}. Supported types: {list(cls._providers.keys())}")

        return provider_class()

    @classmethod
    def register_provider(cls, *, engine_type: str, provider_class: type[VlmPipelineOptionsProvider]) -> None:
        """
        Register a custom pipeline options provider.

        Args:
            engine_type: Engine type identifier
            provider_class: Provider class to register
        """
        cls._providers[engine_type] = provider_class
