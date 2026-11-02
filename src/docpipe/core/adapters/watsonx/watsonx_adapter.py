"""Unified WatsonX adapter for inference, embeddings, and text detection.

This adapter consolidates all WatsonX capabilities into a single class,
providing a unified interface for:
- LLM inference (chat and text generation)
- Embedding generation
- Text detection (PII/HAP)
"""

import json
import logging
from typing import Any
from urllib.parse import urljoin

from docpipe.core.constants.constants import LLMConstants, ServiceConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.core.ports.text_detection_port import TextDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.integrations.docling.vlm_pipeline_options_provider import WatsonxPipelineOptionsProvider
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.integrations.watsonx.client import WatsonXClient
from docpipe.integrations.watsonx.rest_client import WatsonxRestEmbeddingClient

logger = logging.getLogger(__name__)


class WatsonXAdapter(LLMInferencePort, LLMEmbeddingPort, TextDetectionPort):
    """Unified WatsonX adapter for all LLM capabilities.

    This adapter provides a single interface for WatsonX operations including
    inference, embeddings, and specialized text detection APIs.

    Attributes:
        client: WatsonX client instance
        model_name: Default model name (can be overridden per method call)
    """

    # WatsonX API version for text detection endpoint
    WATSONX_API_VERSION = "2024-07-29"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        container_id: str | None = None,
        container_kind: str | None = None,
        timeout: int = 120,
        model_name: str | None = None,
        project_id: str | None = None,
        embedding_batch_size: int = ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_BATCH_SIZE,
        embedding_max_concurrent_requests: int = ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_MAX_CONCURRENT_REQUESTS,
    ):
        """Initialize unified WatsonX adapter.

        Args:
            api_key: WatsonX API key
            api_base: WatsonX API base URL
            container_id: WatsonX container ID (project_id or space_id)
            container_kind: WatsonX container kind ('project', 'space', or 'catalog')
            timeout: Request timeout in seconds
            model_name: Default model name (optional, can be overridden per method)
            project_id: Alias for container_id (for backward compatibility)
            embedding_batch_size: Maximum number of texts per embeddings request (default: 800)
            embedding_max_concurrent_requests: Maximum number of embeddings requests a caller may
                keep in flight at once (default: 1; watsonx.ai enforces 8 req/s per instance)
        """
        self.api_key = api_key
        self.api_base = api_base

        # Normalize container_id: accept both container_id and project_id
        # This centralizes the config normalization logic
        if container_id is None and project_id is not None:
            container_id = project_id

        self.container_id = container_id
        self.container_kind = container_kind
        self.timeout = timeout
        self._access_token: str | None = None

        self.client = WatsonXClient(
            model_name=model_name or "",  # Can be empty, will be set per method
            api_key=api_key,
            container_id=container_id,
            api_base=api_base,
            container_kind=container_kind,
            timeout=timeout,
        )

        # Store parameters for lazy initialization of embedding client
        # We don't initialize WatsonxRestEmbeddingClient here because it fetches IAM token immediately
        self._embedding_client: WatsonxRestEmbeddingClient | None = None
        self._embedding_client_params = {
            "api_key": api_key,
            "api_base": api_base,
            "container_id": container_id,
            "container_kind": container_kind,
            "timeout": timeout,
        }
        self._embedding_batch_size = embedding_batch_size
        self._embedding_max_concurrent_requests = embedding_max_concurrent_requests

        self.model_name = model_name
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
        """Multi-turn chat completion using WatsonX.

        Args:
            model_name: Model identifier (uses default if not provided)
            messages: List of message dicts with 'role' and 'content' keys
            response_format: Optional response format specification (passed to kwargs)
            **kwargs: WatsonX-specific parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text response

        Raises:
            Exception: WatsonX client errors
        """
        # Add response_format to kwargs if provided
        if response_format:
            kwargs["response_format"] = response_format

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model:
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
        """Single-turn text generation using WatsonX.

        Args:
            model_name: Model identifier (uses default if not provided)
            prompt: Input prompt text
            response_format: Optional response format specification (passed to kwargs)
            **kwargs: WatsonX-specific parameters (temperature, max_tokens, etc.)

        Returns:
            Generated text response

        Raises:
            Exception: WatsonX client errors
        """
        # Add response_format to kwargs if provided
        if response_format:
            kwargs["response_format"] = response_format

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model:
            self.client.model_name = effective_model

        return self.client.generate(prompt=prompt, **kwargs)

    # ==================== Embedding Methods ====================

    @property
    def embedding_client(self) -> WatsonxRestEmbeddingClient:
        """Lazy initialization of WatsonX embedding client.

        Returns:
            Initialized WatsonxRestEmbeddingClient instance

        Raises:
            DocpipeException: If required parameters are missing
        """
        if self._embedding_client is None:
            # Validate required parameters
            if not self._embedding_client_params.get("api_key"):
                raise DocpipeException(
                    "WatsonX embedding client requires api_key. "
                    "Ensure api_key is provided during adapter initialization."
                )
            if not self._embedding_client_params.get("api_base"):
                raise DocpipeException(
                    "WatsonX embedding client requires api_base. "
                    "Ensure api_base is provided during adapter initialization."
                )
            if not self._embedding_client_params.get("container_id"):
                raise DocpipeException(
                    "WatsonX embedding client requires container_id. "
                    "Ensure container_id is provided during adapter initialization."
                )
            if not self._embedding_client_params.get("container_kind"):
                raise DocpipeException(
                    "WatsonX embedding client requires container_kind. "
                    "Ensure container_kind is provided during adapter initialization."
                )

            # Initialize the embedding client with stored parameters
            self._embedding_client = WatsonxRestEmbeddingClient(
                api_key=self._embedding_client_params["api_key"],
                url=self._embedding_client_params["api_base"],
                container_id=self._embedding_client_params["container_id"],
                container_kind=self._embedding_client_params["container_kind"],
                model_name=self.model_name or "",
                timeout=self._embedding_client_params.get("timeout", 120),
                batch_size=self._embedding_batch_size,
            )
            logger.info("Initialized WatsonX embedding client for model '%s'", self.model_name)

        return self._embedding_client

    def generate_embeddings(
        self,
        *,
        model_name: str | None = None,
        text: str,
        **kwargs: Any,
    ) -> list[float]:
        """Generate embeddings for single text using WatsonX.

        Args:
            model_name: Embedding model identifier (uses default if not provided)
            text: Input text to embed
            **kwargs: Additional WatsonX parameters

        Returns:
            List of embedding values (floats)

        Raises:
            Exception: WatsonX client errors
        """
        if not self.embedding_client:
            raise DocpipeException(
                "WatsonX embedding client not initialized. Ensure api_key, api_base, container_id, and container_kind are provided."
            )

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model:
            self.embedding_client.model_name = effective_model

        return self.embedding_client.generate_embeddings(text=text)

    def generate_embeddings_batch(
        self,
        *,
        model_name: str | None = None,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts using WatsonX.

        Args:
            model_name: Embedding model identifier (uses default if not provided)
            texts: List of input texts to embed
            **kwargs: Additional WatsonX parameters

        Returns:
            List of embedding lists, one per input text

        Raises:
            Exception: WatsonX client errors
        """
        if not self.embedding_client:
            raise DocpipeException(
                "WatsonX embedding client not initialized. Ensure api_key, api_base, container_id, and container_kind are provided."
            )

        # Use provided model_name or fall back to default
        effective_model = model_name or self.model_name
        if effective_model:
            self.embedding_client.model_name = effective_model

        return self.embedding_client.generate_embeddings_batch(texts=texts)

    def get_embedding_batch_size(self) -> int:
        """Return the number of texts the embedding client sends per request."""
        return self._embedding_batch_size

    def get_max_concurrent_requests(self) -> int:
        """Return how many embedding requests callers may keep in flight concurrently."""
        return self._embedding_max_concurrent_requests

    def get_embedding_dimension(self, *, model_name: str | None = None) -> int:
        """Get embedding dimension for WatsonX model.

        Detects dimension by generating a sample embedding if not cached.

        Args:
            model_name: Embedding model identifier (uses default if not provided)

        Returns:
            Dimension of embedding vectors

        Raises:
            Exception: WatsonX client errors
        """
        if self._dimension is None:
            # Detect dimension by generating sample embedding
            sample = self.generate_embeddings(model_name=model_name, text="test")
            self._dimension = len(sample)
        return self._dimension

    # ==================== Text Detection Methods ====================

    def detect(
        self,
        *,
        text: str,
        detection_types: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform text detection using WatsonX specialized API.

        Args:
            text: Input text to analyze
            detection_types: Optional list of detection types (e.g., ["pii", "hap"])
            **kwargs: Additional parameters including 'prompt' for detection instructions

        Returns:
            Detection results dict with structure:
            {
                "success": bool,
                "detections": list[dict],
                "error": str | None
            }

        Raises:
            ValueError: If text is empty or detection fails
        """
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty")

        detector_payload = kwargs.get("detectors")
        if detector_payload is None:
            detector_payload = {
                "pii": {"threshold": 0.5},
                "hap": {"threshold": 0.8},
            }

        payload = {
            OperatorConstants.PIIHAP.INPUT_FIELD: text,
            "detectors": detector_payload,
        }

        try:
            detections = self._call_watsonx_detection_api(payload=payload)
            return {
                "success": True,
                "detections": detections,
                "error": None,
            }
        except Exception as e:
            logger.error("Text detection failed: %s", e)
            return {
                "success": False,
                "detections": [],
                "error": str(e),
            }

    def detect_entities(
        self,
        *,
        text: str,
        prompt: str,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """Detect entities (PII/HAP) in text using a detection prompt.

        Args:
            text: Input text to analyze for entities
            prompt: Detection prompt that instructs the model what to detect
            model_name: Model identifier (uses default if not provided)

        Returns:
            Dictionary containing detection results with structure:
            {
                "detected": bool,
                "entities": list[dict],
                "confidence": float,
                "raw_response": str
            }

        Raises:
            ValueError: If text or prompt is empty, or if detection fails
        """
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty")
        if not prompt or not prompt.strip():
            raise ValueError("Detection prompt cannot be empty")

        try:
            detections = self._call_watsonx_detection_api(
                payload={
                    OperatorConstants.PIIHAP.INPUT_FIELD: text,
                    "detectors": {
                        "pii": {"threshold": 0.5},
                        "hap": {"threshold": 0.8},
                    },
                }
            )
            return {
                "detected": bool(detections),
                "entities": detections,
                "confidence": 1.0 if detections else 0.0,
                "raw_response": json.dumps(
                    {
                        OperatorConstants.PIIHAP.DETECTIONS_FIELD: detections,
                    }
                ),
            }

        except Exception as e:
            logger.error("Entity detection failed: %s", e)
            raise ValueError(f"Entity detection failed: {e}") from e

    def detect_entities_batch(
        self,
        *,
        texts: list[str],
        prompt: str,
        model_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect entities in multiple texts using batch processing.

        Args:
            texts: List of input texts to analyze
            prompt: Detection prompt that instructs the model what to detect
            model_name: Model identifier (uses default if not provided)

        Returns:
            List of detection result dictionaries, one per input text

        Raises:
            ValueError: If texts list is empty or if batch detection fails
        """
        if not texts:
            raise ValueError("Input texts list cannot be empty")
        if not prompt or not prompt.strip():
            raise ValueError("Detection prompt cannot be empty")

        results = []
        for text in texts:
            try:
                result = self.detect_entities(text=text, prompt=prompt, model_name=model_name)
                results.append(result)
            except Exception as e:
                logger.warning("Failed to detect entities in text: %s", e)
                # Return empty result for failed detection
                results.append(
                    {
                        "detected": False,
                        "entities": [],
                        "confidence": 0.0,
                        "error": str(e),
                    }
                )

        return results

    def _get_access_token(self) -> str:
        """Get or refresh IAM access token."""
        if not self.api_key:
            raise ValueError("WatsonX API key is required for text detection")
        if not self._access_token:
            self._access_token = WatsonxPipelineOptionsProvider._get_iam_access_token(api_key=self.api_key)
        return self._access_token

    def _call_watsonx_detection_api(self, *, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Call WatsonX native text detection API."""

        if not self.api_base:
            raise ValueError("WatsonX API base URL is required for text detection")
        if not self.container_kind or not self.container_id:
            raise ValueError("container id/ container kind is required for WatsonX detection API")

        # Use urljoin for safe URL construction to prevent injection risks
        detection_url = urljoin(self.api_base, "/ml/v1/text/detection")
        params = {"version": self.WATSONX_API_VERSION}

        request_payload = dict(payload)
        request_payload[f"{self.container_kind}_id"] = self.container_id

        config = RestClientConfig(
            timeout=self.timeout,
            retry_max_attempts=3,
            retry_multiplier=2.0,
            retry_min_wait=1.0,
            retry_max_wait=10.0,
        )
        client = RestClient(config=config, auth_token=self._get_access_token())

        try:
            result = client.call_rest_json(
                method=RestMethod.POST,
                url=detection_url,
                json_data=request_payload,
                query_params=params,
                expected_status_codes=[200],
            )
            detections = result.get(OperatorConstants.PIIHAP.DETECTIONS_FIELD, [])
            return detections if isinstance(detections, list) else []
        except ExternalServiceError as exc:
            # Only refresh token on authentication errors (401, 403)
            # For other errors (network, payload issues), preserve the token
            if exc.status_code in [401, 403]:
                self._access_token = None
            raise DocpipeException(
                message=f"Failed to call WatsonX detection API: {exc!s}",
                status_code=exc.status_code or 500,
            ) from exc

    # ==================== Validation Methods ====================

    def _validate_config(self, context: str) -> dict[str, Any]:
        """Validate WatsonX configuration for any context.

        Args:
            context: Validation context ("inference", "embedding", or "detection")

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: The validation context
                - errors: List of validation error messages (empty if valid)
                - warnings: List of validation warnings
        """
        errors = []
        warnings = []

        # Validate api_key
        if not self.client.api_key or not self.client.api_key.strip():
            errors.append("api_key is missing or empty")

        # Validate api_base
        if not self.client.api_base or not self.client.api_base.strip():
            errors.append("api_base is missing or empty")

        # Validate container_id
        if not self.client.container_id or not self.client.container_id.strip():
            errors.append("container_id is missing or empty")

        # Validate container_kind
        valid_kinds = ["project", "space"]
        if not self.client.container_kind:
            errors.append("container_kind is missing")
        elif self.client.container_kind not in valid_kinds:
            errors.append(f"container_kind must be one of {valid_kinds}, got: {self.client.container_kind}")

        # Warn if model_name is not set (optional but recommended)
        if not self.model_name:
            warnings.append("model_name is not set - will need to be provided per method call")

        return {
            LLMConstants.ValidationKeys.VALID: len(errors) == 0,
            LLMConstants.ValidationKeys.CONTEXT: context,
            LLMConstants.ValidationKeys.ERRORS: errors,
            LLMConstants.ValidationKeys.WARNINGS: warnings,
        }

    def validate_inference(self) -> dict[str, Any]:
        """Hook method override for inference validation.

        Validates WatsonX configuration for inference operations.

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: "inference"
                - errors: List of validation error messages (empty if valid)
                - warnings: List of validation warnings
        """
        return self._validate_config(LLMConstants.ValidationContexts.INFERENCE)

    def validate_embedding(self) -> dict[str, Any]:
        """Hook method override for embedding validation.

        Validates WatsonX configuration for embedding operations.

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: "embedding"
                - errors: List of validation error messages (empty if valid)
                - warnings: List of validation warnings
        """
        return self._validate_config(LLMConstants.ValidationContexts.EMBEDDING)

    def validate_detection(self) -> dict[str, Any]:
        """Hook method override for detection validation.

        Validates WatsonX configuration for text detection operations.

        Returns:
            Dictionary with validation result:
                - valid: True if all validations pass
                - context: "detection"
                - errors: List of validation error messages (empty if valid)
                - warnings: List of validation warnings
        """
        return self._validate_config(LLMConstants.ValidationContexts.DETECTION)
