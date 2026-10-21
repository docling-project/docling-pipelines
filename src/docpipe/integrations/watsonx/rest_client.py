# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""
WatsonX REST API Embedding Client.

Provides embedding generation using IBM watsonx.ai REST API directly,
bypassing the ibm-watsonx-ai SDK. Supports batch processing, retry logic,
and optional rate limiting.

Authentication: API key is exchanged for IAM access token automatically.
"""

import time
from typing import Any, ClassVar

from docpipe.core.constants.constants import ServiceConstants
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.base_llm_client import BaseLLMClient, retry_with_backoff
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.integrations.watsonx.model_validator import get_available_foundation_models
from docpipe.utils.infrastructure.iam_token_manager import IAMTokenManager
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.rate_limiter import rate_limit_context

logger = get_logger(__name__)

# Rate limit for WatsonX AI embeddings API
# Set to 7 req/s to stay safely under the 8 req/s instance limit.
# Provides ~12% headroom for retries and clock skew across distributed workers.
WATSONX_RATE_LIMIT = 7.0
WATSONX_RATE_LIMIT_NAME = "watsonx-embeddings-rest"

# Model-specific token limits for truncate_input_tokens parameter
# Based on watsonx.ai embedding model specifications
# NOTE: These are fallback values. The client now fetches dynamic values from the API.
WATSONX_MODEL_TOKEN_LIMITS = {
    "ibm/slate-30m-english-rtrvr": 512,
    "ibm/slate-125m-english-rtrvr": 512,
    "sentence-transformers/all-minilm-l12-v2": 128,
    "intfloat/multilingual-e5-large": 512,
    "ibm/granite-embedding-278m-multilingual": 512,
}


class WatsonxRestEmbeddingClient(BaseLLMClient):
    """WatsonX REST API embedding client for cloud deployments.

    This client provides embedding generation using IBM watsonx.ai REST API
    directly, bypassing the ibm-watsonx-ai SDK. Supports batch processing,
    token truncation, automatic retry logic, and optional rate limiting.

    Features:
        - Direct REST API calls (no SDK dependency)
        - Cloud-only deployment (no CPD support)
        - Batch processing with configurable batch size (default: 800)
        - Automatic token truncation for long texts
        - Exponential backoff retry logic with 429 handling
        - Per-batch and total processing time logging
        - Support for both project and space containers
        - Optional rate limiting with per-job isolation via job_run_id
        - Singleton pattern for client instances to prevent rate limit issues
    """

    # Class-level cache for client instances
    # Key: (api_key, url, container_kind, container_id, model_name)
    # Value: WatsonxRestEmbeddingClient instance
    _client_cache: ClassVar[dict[tuple[str, str, str, str, str], "WatsonxRestEmbeddingClient"]] = {}

    # Class-level cache for model token limits
    # Key: (api_key, url, model_name)
    # Value: max_sequence_length from API
    _token_limit_cache: ClassVar[dict[tuple[str, str, str], int]] = {}

    def __init__(
        self,
        *,
        api_key: str,
        url: str,
        container_kind: str,
        container_id: str,
        model_name: str,
        batch_size: int = ServiceConstants.DEFAULT_WATSONX_EMBEDDINGS_BATCH_SIZE,
        job_run_id: str | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        enable_rate_limiting: bool = False,
    ) -> None:
        """Initialize watsonx.ai REST API embedding client.

        Args:
            api_key: IBM Cloud API key (exchanged for IAM access token)
            url: Watsonx.ai API endpoint URL (e.g., https://us-south.ml.cloud.ibm.com)
            container_kind: Container type ("project" or "space")
            container_id: Container ID (project_id or space_id)
            model_name: Model ID for embeddings (e.g., ibm/slate-30m-english-rtrvr)
            batch_size: Number of texts to process per batch (default: 800)
            job_run_id: Optional job run ID for per-job rate limiting
            timeout: Request timeout in seconds (default: 60)
            max_retries: Maximum number of retry attempts (default: 3)
            enable_rate_limiting: Whether to apply WatsonX request rate limiting (default: False)

        Raises:
            ConfigurationError: If container_kind is invalid
        """
        # Validate container_kind early
        if container_kind not in ("project", "space"):
            raise ConfigurationError(f"Invalid container_kind: {container_kind}. Must be 'project' or 'space'.")

        # Create cache key based on configuration
        cache_key = (api_key, url, container_kind, container_id, model_name)

        # Check if client instance already exists in cache
        if cache_key in WatsonxRestEmbeddingClient._client_cache:
            cached_instance = WatsonxRestEmbeddingClient._client_cache[cache_key]
            logger.info(
                "Reusing cached REST client instance for model=%s, container_kind=%s, batch_size=%s",
                model_name,
                container_kind,
                batch_size,
            )
            # Copy cached instance attributes to self
            self.__dict__.update(cached_instance.__dict__)
            # batch_size is per-caller configuration, not part of the shared connection state
            self.batch_size = batch_size
            return

        # Initialize base class
        self.model_name = model_name
        self.config: dict[str, Any] = {}

        self.api_key = api_key
        self.url = url.rstrip("/")
        self.container_kind = container_kind
        self.container_id = container_id
        self.batch_size = batch_size
        self.job_run_id = job_run_id
        self.enable_rate_limiting = enable_rate_limiting

        # Create rate limit name based on job_run_id
        # If job_run_id is provided, each job gets its own rate limit (per-job isolation)
        # Otherwise, all jobs share a common rate limit (shared pool)
        self.rate_limit_name = f"{WATSONX_RATE_LIMIT_NAME}-{job_run_id}" if job_run_id else WATSONX_RATE_LIMIT_NAME

        # Initialize IAM token manager for API key → access token exchange
        self.iam_token_manager = IAMTokenManager(api_key=self.api_key, watsonx_url=self.url)

        # Get initial IAM access token
        iam_token = self.iam_token_manager.get_token()

        # Initialize REST client with IAM access token
        rest_config = RestClientConfig(
            timeout=timeout,
            max_retries=max_retries,
            retry_max_attempts=max_retries,
            retry_multiplier=2.0,
            retry_min_wait=1.0,
            retry_max_wait=10.0,
        )
        self.rest_client = RestClient(config=rest_config, base_url=self.url, auth_token=iam_token)

        # Cache the instance
        WatsonxRestEmbeddingClient._client_cache[cache_key] = self

        logger.info(
            "Created and cached new REST client instance for model=%s, container_kind=%s, batch_size=%s, rate_limit_name=%s",
            model_name,
            container_kind,
            batch_size,
            self.rate_limit_name,
        )

    @classmethod
    def clear_client_cache(cls) -> None:
        """Clear the class-level client cache.

        This method is useful for testing or when you need to force
        recreation of client instances (e.g., after credential changes).
        """
        cls._client_cache.clear()
        logger.info("Cleared REST client cache")

    @classmethod
    def clear_token_limit_cache(cls) -> None:
        """Clear the class-level token limit cache.

        This method is useful for testing or when model specifications
        have been updated and you need to refresh the token limits.
        """
        cls._token_limit_cache.clear()
        logger.info("Cleared token limit cache")

    def _fetch_model_token_limit(self) -> int:
        """Fetch the max_sequence_length for the current model from WatsonX API.

        Retrieves model specifications from the foundation models API and extracts
        the max_sequence_length from model_limits. Results are cached to avoid
        repeated API calls.

        Returns:
            Token limit from API, or fallback value if API call fails

        Note:
            This method uses the cached get_available_foundation_models() function
            which is already cached via @lru_cache, so we get automatic caching
            at the API level. We add an additional cache at the client level for
            faster lookups.
        """
        # Check client-level cache first
        cache_key = (self.api_key, self.url, self.model_name)
        if cache_key in WatsonxRestEmbeddingClient._token_limit_cache:
            cached_limit = WatsonxRestEmbeddingClient._token_limit_cache[cache_key]
            logger.debug("Using cached token limit %s for model '%s'", cached_limit, self.model_name)
            return cached_limit

        try:
            # Fetch model specs from API (this call is cached by @lru_cache)
            logger.info("Fetching token limit for model '%s' from WatsonX API", self.model_name)
            model_specs = get_available_foundation_models(api_key=self.api_key, url=self.url)

            # Find the model spec matching the model_name
            for spec in model_specs:
                if spec.get("model_id") == self.model_name:
                    # Extract max_sequence_length from model_limits
                    model_limits = spec.get("model_limits", {})
                    if isinstance(model_limits, dict):
                        max_seq_length = model_limits.get("max_sequence_length")
                        if max_seq_length and isinstance(max_seq_length, int):
                            logger.info(
                                "Found max_sequence_length=%s for model '%s' from API", max_seq_length, self.model_name
                            )
                            # Cache the result
                            WatsonxRestEmbeddingClient._token_limit_cache[cache_key] = max_seq_length
                            return max_seq_length

            # Model found but no max_sequence_length in model_limits
            logger.warning(
                "Model '%s' found but max_sequence_length not available in model_limits. Using fallback value.",
                self.model_name,
            )

        except Exception as e:
            # Log error but don't fail - fall back to hardcoded values
            logger.warning("Failed to fetch token limit from API for model '%s': %s", self.model_name, e)

        # Fall back to hardcoded values
        fallback_limit = WATSONX_MODEL_TOKEN_LIMITS.get(self.model_name, 512)
        logger.info("Using fallback token limit %s for model '%s'", fallback_limit, self.model_name)

        # Cache the fallback value to avoid repeated API calls
        WatsonxRestEmbeddingClient._token_limit_cache[cache_key] = fallback_limit
        return fallback_limit

    def _get_truncate_tokens(self) -> int:
        """Get the truncate_input_tokens value for the current model.

        Fetches the token limit dynamically from the WatsonX foundation models API.
        Falls back to hardcoded values if the API call fails.

        Returns:
            Token limit for truncate_input_tokens parameter

        Note:
            Token limits are fetched from model_limits.max_sequence_length in the API response.
            If the API call fails, falls back to WATSONX_MODEL_TOKEN_LIMITS dictionary:
            - ibm/slate models: 512 tokens
            - sentence-transformers/all-minilm-l12-v2: 128 tokens
            - intfloat/multilingual-e5-large: 512 tokens
            - ibm/granite-embedding-278m-multilingual: 512 tokens
            - Unknown models: 512 tokens (default)
        """
        return self._fetch_model_token_limit()

    def _build_request_payload(self, *, texts: list[str]) -> dict[str, Any]:
        """Build the request payload for the embeddings API.

        Args:
            texts: List of input texts to embed

        Returns:
            Request payload dictionary
        """
        # Build container parameter (project_id or space_id)
        container_param = f"{self.container_kind}_id"

        payload: dict[str, Any] = {
            "model_id": self.model_name,
            container_param: self.container_id,
            "parameters": {"truncate_input_tokens": self._get_truncate_tokens()},
            "inputs": texts,
        }

        return payload

    def _get_auth_headers(self) -> dict[str, str]:
        """Get fresh authentication headers with current IAM token.

        Returns:
            Dictionary with Authorization header containing fresh IAM token
        """
        return {"Authorization": f"Bearer {self.iam_token_manager.get_token()}"}

    def _extract_embeddings_from_response(self, *, response: dict[str, Any]) -> list[list[float]]:
        """Extract embeddings from API response.

        Args:
            response: API response dictionary

        Returns:
            List of embedding vectors

        Raises:
            ExternalServiceError: If response format is invalid
        """
        if "results" not in response:
            raise ExternalServiceError(
                message="Invalid response format: missing 'results' field",
                error_code=ErrorCode.INVALID_RESPONSE,
            )

        results = response["results"]
        if not isinstance(results, list):
            raise ExternalServiceError(
                message=f"Invalid response format: 'results' must be a list, got {type(results).__name__}",
                error_code=ErrorCode.INVALID_RESPONSE,
            )

        embeddings: list[list[float]] = []
        for idx, result in enumerate(results):
            if not isinstance(result, dict) or "embedding" not in result:
                raise ExternalServiceError(
                    message=f"Invalid result format at index {idx}: missing 'embedding' field",
                    error_code=ErrorCode.INVALID_RESPONSE,
                )

            embedding = result["embedding"]
            if not isinstance(embedding, list):
                raise ExternalServiceError(
                    message=f"Invalid embedding format at index {idx}: expected list, got {type(embedding).__name__}",
                    error_code=ErrorCode.INVALID_RESPONSE,
                )

            embeddings.append(embedding)

        return embeddings

    @retry_with_backoff(max_retries=5, initial_delay=2.0, max_delay=60)
    def generate_embeddings(self, text: str) -> list[float]:
        """Generate embeddings for a single text with optional rate limiting.

        Args:
            text: Input text to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            ConfigurationError: If text is invalid
            ExternalServiceError: If embedding generation fails
        """
        self._validate_text_input(text)

        try:
            # Build request payload
            payload = self._build_request_payload(texts=[text])

            # Make API call
            endpoint = "ml/v1/text/embeddings"
            params = {"version": "2023-10-25"}

            # Get fresh IAM token for this request
            headers = self._get_auth_headers()

            if self.enable_rate_limiting:
                # Apply rate limiting to stay within WatsonX AI limits (8 req/s)
                # Uses per-job rate limit if job_run_id is set, otherwise shared limit
                with rate_limit_context(limit_name=self.rate_limit_name, rate=WATSONX_RATE_LIMIT):
                    response = self.rest_client.call_rest_json(
                        method=RestMethod.POST,
                        url=endpoint,
                        json_data=payload,
                        query_params=params,
                        headers=headers,
                        expected_status_codes=[200],
                    )
            else:
                response = self.rest_client.call_rest_json(
                    method=RestMethod.POST,
                    url=endpoint,
                    json_data=payload,
                    query_params=params,
                    headers=headers,
                    expected_status_codes=[200],
                )

            # Extract embeddings from response
            embeddings = self._extract_embeddings_from_response(response=response)

            if not embeddings or len(embeddings) != 1:
                raise ExternalServiceError(
                    message=f"Expected 1 embedding, got {len(embeddings)}",
                    error_code=ErrorCode.INVALID_RESPONSE,
                )

            self._validate_embeddings_output(embeddings[0])
            return embeddings[0]

        except ExternalServiceError:
            # Re-raise ExternalServiceError as-is
            raise
        except Exception as e:
            logger.error("Failed to generate embeddings: %s", e)
            raise ExternalServiceError(
                message=f"Watsonx.ai REST API embedding generation failed: {e}",
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            ) from e

    @retry_with_backoff(max_retries=5, initial_delay=2.0, max_delay=60)
    def generate_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Generate embeddings for multiple texts in batches with optional rate limiting.

        Processes texts in batches to optimize performance and handle large datasets.
        Uses token truncation to handle texts exceeding model limits.
        The batch_size parameter is ignored in favor of the client's configured batch_size.
        When enabled, rate limiting is applied per batch to stay within WatsonX AI limits (8 req/s).

        Args:
            texts: List of input texts to generate embeddings for
            batch_size: Ignored (uses client's batch_size instead)

        Returns:
            List of embedding vectors, one per input text

        Raises:
            ConfigurationError: If inputs are invalid
            ExternalServiceError: If embedding generation fails
        """
        if not texts:
            return []

        if not isinstance(texts, list):
            raise ConfigurationError("texts must be a list")

        if not all(isinstance(t, str) for t in texts):
            raise ConfigurationError("all texts must be strings")

        all_embeddings: list[list[float]] = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size

        logger.info("Processing %s texts in %s batches (batch_size=%s)", len(texts), total_batches, self.batch_size)

        total_start = time.time()

        try:
            # Process in batches
            for batch_idx in range(0, len(texts), self.batch_size):
                batch_start = time.time()
                batch = texts[batch_idx : batch_idx + self.batch_size]
                batch_num = (batch_idx // self.batch_size) + 1

                # Build request payload
                payload = self._build_request_payload(texts=batch)

                # Make API call with fresh IAM token
                endpoint = "ml/v1/text/embeddings"
                params = {"version": "2023-10-25"}

                # Get fresh IAM token for this request
                headers = self._get_auth_headers()

                if self.enable_rate_limiting:
                    # Apply rate limiting per batch to stay within WatsonX AI limits
                    # Uses per-job rate limit if job_run_id is set, otherwise shared limit
                    with rate_limit_context(limit_name=self.rate_limit_name, rate=WATSONX_RATE_LIMIT):
                        response = self.rest_client.call_rest_json(
                            method=RestMethod.POST,
                            url=endpoint,
                            json_data=payload,
                            query_params=params,
                            headers=headers,
                            expected_status_codes=[200],
                        )
                else:
                    response = self.rest_client.call_rest_json(
                        method=RestMethod.POST,
                        url=endpoint,
                        json_data=payload,
                        query_params=params,
                        headers=headers,
                        expected_status_codes=[200],
                    )

                # Extract embeddings from response
                batch_embeddings = self._extract_embeddings_from_response(response=response)

                if len(batch_embeddings) != len(batch):
                    raise ExternalServiceError(
                        message=f"Expected {len(batch)} embeddings, got {len(batch_embeddings)}",
                        error_code=ErrorCode.INVALID_RESPONSE,
                    )

                all_embeddings.extend(batch_embeddings)

                batch_time = time.time() - batch_start
                logger.info(
                    "Batch %s/%s processed (%s texts) in %.2fs", batch_num, total_batches, len(batch), batch_time
                )

            total_time = time.time() - total_start
            logger.info("Total processing time: %.2fs (%s texts, %s batches)", total_time, len(texts), total_batches)

            return all_embeddings

        except ExternalServiceError:
            # Re-raise ExternalServiceError as-is
            raise
        except Exception as e:
            logger.error("Failed to generate embeddings: %s", e)
            raise ExternalServiceError(
                message=f"Watsonx.ai REST API embedding generation failed: {e}",
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            ) from e

    @staticmethod
    def get_model_token_limit(model_name: str) -> int:
        """Get the token limit for a specific watsonx.ai model.

        This is a static method required by BaseLLMClient abstract class.
        For dynamic token limit fetching, use the instance method _get_truncate_tokens().

        Args:
            model_name: Name of the watsonx.ai model

        Returns:
            Maximum token limit for the model (default: 8192)

        Note:
            This method returns a generic default value. For accurate, model-specific
            token limits fetched from the WatsonX API, use the instance method
            _get_truncate_tokens() which queries the Foundation Models API.
        """
        # Return generic default for static method requirement
        # Instance method _get_truncate_tokens() provides dynamic API-based values
        return 8192

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """Get the embedding dimension for a specific watsonx.ai model.

        Args:
            model_name: Name of the watsonx.ai model

        Returns:
            Embedding dimension (0 indicates runtime detection required)

        Note:
            Watsonx.ai embedding dimensions vary by model and require runtime detection.
            Return 0 to indicate dimension should be determined at runtime.
        """
        # Return 0 to indicate runtime detection required
        # Dimension lookup is now handled by the adapter using get_model_dimension()
        return 0
