# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for WatsonX REST client dynamic token limit functionality.

Tests the _fetch_model_token_limit() method and related caching behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.integrations.watsonx.rest_client import (
    WATSONX_MODEL_TOKEN_LIMITS,
    WatsonxRestEmbeddingClient,
)


@pytest.fixture
def mock_iam_token_manager():
    """Mock IAM token manager to avoid real authentication."""
    with patch("docpipe.integrations.watsonx.rest_client.IAMTokenManager") as mock:
        mock_instance = MagicMock()
        mock_instance.get_token.return_value = "mock-token"
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_rest_client():
    """Mock REST client to avoid real API calls."""
    with patch("docpipe.integrations.watsonx.rest_client.RestClient") as mock:
        yield mock


@pytest.fixture
def sample_model_specs():
    """Sample model specifications from WatsonX API."""
    return [
        {
            "model_id": "ibm/slate-125m-english-rtrvr-v2",
            "label": "slate-125m-english-rtrvr-v2",
            "model_limits": {"max_sequence_length": 512},
            "embedding_dimension": 768,
        },
        {
            "model_id": "intfloat/multilingual-e5-large",
            "label": "multilingual-e5-large",
            "model_limits": {"max_sequence_length": 512},
            "embedding_dimension": 1024,
        },
        {
            "model_id": "sentence-transformers/all-minilm-l12-v2",
            "label": "all-minilm-l12-v2",
            "model_limits": {},  # No max_sequence_length
            "embedding_dimension": 384,
        },
        {
            "model_id": "test/model-without-limits",
            "label": "model-without-limits",
            # No model_limits key at all
            "embedding_dimension": 512,
        },
    ]


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before and after each test."""
    WatsonxRestEmbeddingClient.clear_client_cache()
    WatsonxRestEmbeddingClient.clear_token_limit_cache()
    yield
    WatsonxRestEmbeddingClient.clear_client_cache()
    WatsonxRestEmbeddingClient.clear_token_limit_cache()


class TestDynamicTokenLimitRetrieval:
    """Test dynamic token limit retrieval from WatsonX API."""

    def test_fetch_token_limit_from_api_success(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test successful token limit retrieval from API."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            token_limit = client._get_truncate_tokens()

            assert token_limit == 512
            mock_get_models.assert_called_once_with(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
            )

    def test_fetch_token_limit_caching(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test that token limits are cached after first fetch."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            # First call should fetch from API
            token_limit_1 = client._get_truncate_tokens()
            assert token_limit_1 == 512
            assert mock_get_models.call_count == 1

            # Second call should use cache
            token_limit_2 = client._get_truncate_tokens()
            assert token_limit_2 == 512
            assert mock_get_models.call_count == 1  # No additional API call

    def test_fetch_token_limit_fallback_when_model_not_found(
        self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs
    ):
        """Test fallback to hardcoded values when model not found in API."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="unknown/model",
            )

            token_limit = client._get_truncate_tokens()

            # Should fall back to default 512
            assert token_limit == 512

    def test_fetch_token_limit_fallback_when_no_max_sequence_length(
        self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs
    ):
        """Test fallback when model_limits exists but max_sequence_length is missing."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="sentence-transformers/all-minilm-l12-v2",
            )

            token_limit = client._get_truncate_tokens()

            # Should fall back to hardcoded value for this model
            assert token_limit == WATSONX_MODEL_TOKEN_LIMITS["sentence-transformers/all-minilm-l12-v2"]
            assert token_limit == 128

    def test_fetch_token_limit_fallback_when_no_model_limits_key(
        self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs
    ):
        """Test fallback when model_limits key is missing entirely."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="test/model-without-limits",
            )

            token_limit = client._get_truncate_tokens()

            # Should fall back to default 512
            assert token_limit == 512

    def test_fetch_token_limit_fallback_on_api_error(self, *, mock_iam_token_manager, mock_rest_client):
        """Test fallback to hardcoded values when API call fails."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.side_effect = Exception("API error")

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-30m-english-rtrvr",
            )

            token_limit = client._get_truncate_tokens()

            # Should fall back to hardcoded value
            assert token_limit == WATSONX_MODEL_TOKEN_LIMITS["ibm/slate-30m-english-rtrvr"]
            assert token_limit == 512

    def test_fetch_token_limit_uses_hardcoded_for_known_models(self, *, mock_iam_token_manager, mock_rest_client):
        """Test that hardcoded values are used as fallback for known models."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.side_effect = Exception("API error")

            for model_name, expected_limit in WATSONX_MODEL_TOKEN_LIMITS.items():
                WatsonxRestEmbeddingClient.clear_client_cache()
                WatsonxRestEmbeddingClient.clear_token_limit_cache()

                client = WatsonxRestEmbeddingClient(
                    api_key="test-key",  # pragma: allowlist secret
                    url="https://test.ibm.com",
                    container_kind="project",
                    container_id="test-id",
                    model_name=model_name,
                )

                token_limit = client._get_truncate_tokens()
                assert token_limit == expected_limit, f"Failed for model {model_name}"


class TestTokenLimitCacheManagement:
    """Test token limit cache management functionality."""

    def test_clear_token_limit_cache(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test clearing the token limit cache."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            # First call populates cache
            client._get_truncate_tokens()
            assert mock_get_models.call_count == 1

            # Clear cache
            WatsonxRestEmbeddingClient.clear_token_limit_cache()

            # Next call should fetch from API again
            client._get_truncate_tokens()
            assert mock_get_models.call_count == 2

    def test_cache_isolation_between_models(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test that cache is isolated per model."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client1 = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            client2 = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="intfloat/multilingual-e5-large",
            )

            # Each model should have its own cache entry
            limit1 = client1._get_truncate_tokens()
            limit2 = client2._get_truncate_tokens()

            assert limit1 == 512
            assert limit2 == 512
            # Both should fetch from API (different models)
            assert mock_get_models.call_count == 2

    def test_cache_isolation_between_api_keys(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test that cache is isolated per API key."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client1 = WatsonxRestEmbeddingClient(
                api_key="test-key-1",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            client2 = WatsonxRestEmbeddingClient(
                api_key="test-key-2",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            # Each API key should have its own cache entry
            limit1 = client1._get_truncate_tokens()
            limit2 = client2._get_truncate_tokens()

            assert limit1 == 512
            assert limit2 == 512
            # Both should fetch from API (different API keys)
            assert mock_get_models.call_count == 2


class TestTokenLimitIntegration:
    """Test integration of token limits with embedding generation."""

    def test_token_limit_used_in_request_payload(self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs):
        """Test that fetched token limit is used in request payload."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            mock_get_models.return_value = sample_model_specs

            client = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            # Build request payload
            payload = client._build_request_payload(texts=["test text"])

            # Verify token limit is in payload
            assert "parameters" in payload
            assert "truncate_input_tokens" in payload["parameters"]
            assert payload["parameters"]["truncate_input_tokens"] == 512

    def test_different_models_use_different_token_limits(
        self, *, mock_iam_token_manager, mock_rest_client, sample_model_specs
    ):
        """Test that different models use their respective token limits."""
        with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as mock_get_models:
            # Add a model with different token limit
            custom_specs = [
                *sample_model_specs,
                {
                    "model_id": "test/custom-model",
                    "model_limits": {"max_sequence_length": 1024},
                },
            ]
            mock_get_models.return_value = custom_specs

            client1 = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="ibm/slate-125m-english-rtrvr-v2",
            )

            client2 = WatsonxRestEmbeddingClient(
                api_key="test-key",  # pragma: allowlist secret
                url="https://test.ibm.com",
                container_kind="project",
                container_id="test-id",
                model_name="test/custom-model",
            )

            payload1 = client1._build_request_payload(texts=["test"])
            payload2 = client2._build_request_payload(texts=["test"])

            assert payload1["parameters"]["truncate_input_tokens"] == 512
            assert payload2["parameters"]["truncate_input_tokens"] == 1024
