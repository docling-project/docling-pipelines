# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Watsonx.ai Model Validator.

Provides model validation with caching to avoid repeated API calls.
"""

from functools import lru_cache

from docpipe.exceptions.docpipe_exceptions import DependencyError, ExternalServiceError
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_available_foundation_models(*, api_key: str, url: str) -> list[dict]:
    """Fetch and cache available foundation models from watsonx.ai.

    This function is cached to avoid repeated API calls. The cache is based
    on the combination of api_key and url. Container information is not needed
    for fetching foundation model specs.

    Args:
        api_key: Watsonx.ai API key
        url: Watsonx.ai API endpoint URL

    Returns:
        List of model specification dictionaries containing model_id, embedding_dimension, etc.

    Raises:
        DependencyError: If ibm-watsonx-ai package is not installed
        ExternalServiceError: If API call fails
    """
    try:
        from ibm_watsonx_ai.foundation_models.utils import get_model_specs
    except ImportError as e:
        raise DependencyError("ibm-watsonx-ai package not installed. Install with: uv sync --extra watsonx") from e

    try:
        logger.info("Fetching available foundation models from watsonx.ai API")
        model_specs = get_model_specs(url=url)

        # API returns a dict with 'resources' key containing the model list
        if not isinstance(model_specs, dict):
            raise ExternalServiceError(f"Unexpected API response type: {type(model_specs)}, expected dict")

        if "resources" not in model_specs:
            raise ExternalServiceError("API response missing 'resources' field")

        resources = model_specs["resources"]
        if not isinstance(resources, list):
            raise ExternalServiceError(f"Unexpected 'resources' type: {type(resources)}, expected list")

        # Return full model specs instead of just IDs
        available_models = [spec for spec in resources if isinstance(spec, dict) and "model_id" in spec]

        if not available_models:
            logger.warning("No models found in API response")
        else:
            logger.info("Found %s available models", len(available_models))

        return available_models
    except Exception as e:
        logger.error("Failed to fetch foundation models: %s", e)
        raise ExternalServiceError(f"Failed to fetch foundation models from watsonx.ai: {e}") from e


def get_model_dimension(*, model_id: str, api_key: str, url: str) -> int:
    """Get the embedding dimension for a specific watsonx.ai model.

    Uses cached model specs from Foundation Models API to extract the
    embedding dimension for the specified model.

    Args:
        model_id: Model ID to look up
        api_key: Watsonx.ai API key
        url: Watsonx.ai API endpoint URL

    Returns:
        Embedding dimension for the model, or 0 if model not found or dimension not available
    """
    try:
        model_specs = get_available_foundation_models(api_key=api_key, url=url)

        # Find the model spec matching the model_id
        for spec in model_specs:
            if spec.get("model_id") == model_id:
                # Extract embedding_dimension from the spec
                dimension = spec.get("embedding_dimension", 0)
                if dimension:
                    logger.info("Found embedding dimension %s for model '%s'", dimension, model_id)
                    return dimension
                logger.warning("Model '%s' found but embedding_dimension not available in spec", model_id)
                return 0

        logger.warning("Model '%s' not found in available models", model_id)
        return 0
    except Exception as e:
        logger.error("Failed to get model dimension for '%s': %s", model_id, e)
        return 0


def validate_model_id(*, model_id: str, api_key: str, url: str) -> bool:
    """Validate that a model ID exists in available foundation models.

    Uses cached foundation models list to avoid repeated API calls.
    Container information is not needed for model validation.

    Args:
        model_id: Model ID to validate
        api_key: Watsonx.ai API key
        url: Watsonx.ai API endpoint URL

    Returns:
        True if model is available, False otherwise
    """
    model_specs = get_available_foundation_models(api_key=api_key, url=url)

    # Extract model IDs from specs for validation
    available_model_ids = [spec.get("model_id") for spec in model_specs if spec.get("model_id")]

    is_valid = model_id in available_model_ids

    if is_valid:
        logger.info("Model '%s' validated successfully", model_id)
    else:
        logger.warning(
            "Model '%s' not found in available models. Available models: %s...",
            model_id,
            available_model_ids[:5],
        )

    return is_valid
