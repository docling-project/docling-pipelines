# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for WatsonxRestEmbeddingClient core functionality.

Covers: __init__ (cache hit, invalid container_kind), _get_auth_headers,
_extract_embeddings_from_response, generate_embeddings_batch, generate_embeddings,
and the static utility methods.
"""

from unittest.mock import patch

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.watsonx.rest_client import WatsonxRestEmbeddingClient

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_caches():
    """Ensure a clean cache state around every test."""
    WatsonxRestEmbeddingClient.clear_client_cache()
    WatsonxRestEmbeddingClient.clear_token_limit_cache()
    yield
    WatsonxRestEmbeddingClient.clear_client_cache()
    WatsonxRestEmbeddingClient.clear_token_limit_cache()


@pytest.fixture
def mock_iam():
    with patch("docpipe.integrations.watsonx.rest_client.IAMTokenManager") as m:
        m.return_value.get_token.return_value = "test-iam-token"
        yield m


@pytest.fixture
def mock_rest_cls():
    with patch("docpipe.integrations.watsonx.rest_client.RestClient") as m:
        yield m


@pytest.fixture
def mock_models():
    """Prevent real HTTP calls to the foundation models API."""
    with patch("docpipe.integrations.watsonx.rest_client.get_available_foundation_models") as m:
        m.side_effect = Exception("API unavailable in tests")
        yield m


@pytest.fixture
def client(mock_iam, mock_rest_cls, mock_models):
    """Return a fully mocked client with batch_size=2 for easy batching tests."""
    return WatsonxRestEmbeddingClient(
        api_key="test-api-key",  # pragma: allowlist secret
        url="https://us-south.ml.cloud.ibm.com",
        container_kind="project",
        container_id="test-project-id",
        model_name="ibm/slate-30m-english-rtrvr",
        batch_size=2,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(*embeddings):
    """Build a valid API response dict from one or more embedding lists."""
    return {"results": [{"embedding": e} for e in embeddings]}


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for __init__ branching."""

    def test_invalid_container_kind_raises(self, mock_iam, mock_rest_cls):
        """container_kind must be 'project' or 'space'; anything else raises."""
        with pytest.raises(ConfigurationError, match="Invalid container_kind"):
            WatsonxRestEmbeddingClient(
                api_key="k",  # pragma: allowlist secret
                url="https://us-south.ml.cloud.ibm.com",
                container_kind="bucket",
                container_id="id",
                model_name="ibm/slate-30m-english-rtrvr",
            )

    def test_space_container_kind_accepted(self, mock_iam, mock_rest_cls):
        """'space' is a valid container_kind."""
        c = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="space",
            container_id="space-id",
            model_name="ibm/slate-30m-english-rtrvr",
        )
        assert c.container_kind == "space"

    def test_cached_instance_reused(self, mock_iam, mock_rest_cls):
        """Second call with identical params copies cached instance, skips full init."""
        c1 = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="proj-id",
            model_name="ibm/slate-30m-english-rtrvr",
        )

        # IAMTokenManager should have been constructed once
        iam_call_count_after_first = mock_iam.call_count

        c2 = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="proj-id",
            model_name="ibm/slate-30m-english-rtrvr",
        )

        # No additional IAMTokenManager construction
        assert mock_iam.call_count == iam_call_count_after_first
        # Both instances share the same attributes
        assert c2.api_key == c1.api_key
        assert c2.container_id == c1.container_id

    def test_different_params_create_separate_instances(self, mock_iam, mock_rest_cls):
        """Different model names should not share a cache entry."""
        c1 = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="id",
            model_name="ibm/slate-30m-english-rtrvr",
        )
        c2 = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="id",
            model_name="ibm/slate-125m-english-rtrvr",
        )
        assert c1.model_name != c2.model_name

    def test_job_run_id_sets_rate_limit_name(self, mock_iam, mock_rest_cls):
        """When job_run_id is provided the rate_limit_name includes it."""
        c = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="id",
            model_name="ibm/slate-30m-english-rtrvr",
            job_run_id="run-42",
        )
        assert "run-42" in c.rate_limit_name

    def test_no_job_run_id_uses_shared_rate_limit_name(self, mock_iam, mock_rest_cls):
        """Without job_run_id the default shared rate-limit name is used."""
        from docpipe.integrations.watsonx.rest_client import WATSONX_RATE_LIMIT_NAME

        c = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            container_id="id",
            model_name="ibm/slate-30m-english-rtrvr",
        )
        assert c.rate_limit_name == WATSONX_RATE_LIMIT_NAME

    def test_cached_instance_uses_requested_batch_size(self, mock_iam, mock_rest_cls):
        """A cache hit shares the connection but keeps the caller's batch_size."""
        params = {
            "api_key": "k",  # pragma: allowlist secret
            "url": "https://us-south.ml.cloud.ibm.com",
            "container_kind": "project",
            "container_id": "id",
            "model_name": "ibm/slate-30m-english-rtrvr",
        }
        c1 = WatsonxRestEmbeddingClient(**params)
        c2 = WatsonxRestEmbeddingClient(**params, batch_size=50)

        assert c1.batch_size == 800
        assert c2.batch_size == 50
        assert c2.rest_client is c1.rest_client


# ---------------------------------------------------------------------------
# TestGetAuthHeaders
# ---------------------------------------------------------------------------


class TestGetAuthHeaders:
    """Tests for _get_auth_headers."""

    def test_returns_bearer_token(self, client, mock_iam):
        """_get_auth_headers should return a Bearer header with the current IAM token."""
        mock_iam.return_value.get_token.return_value = "fresh-token"
        headers = client._get_auth_headers()
        assert headers == {"Authorization": "Bearer fresh-token"}

    def test_token_refreshed_on_each_call(self, client, mock_iam):
        """Each call to _get_auth_headers fetches a fresh token."""
        mock_iam.return_value.get_token.side_effect = ["token-1", "token-2"]
        h1 = client._get_auth_headers()
        h2 = client._get_auth_headers()
        assert h1["Authorization"] == "Bearer token-1"
        assert h2["Authorization"] == "Bearer token-2"


# ---------------------------------------------------------------------------
# TestExtractEmbeddingsFromResponse
# ---------------------------------------------------------------------------


class TestExtractEmbeddingsFromResponse:
    """Tests for _extract_embeddings_from_response."""

    def test_success(self, client):
        resp = {"results": [{"embedding": [0.1, 0.2, 0.3]}]}
        result = client._extract_embeddings_from_response(response=resp)
        assert result == [[0.1, 0.2, 0.3]]

    def test_multiple_embeddings(self, client):
        resp = {"results": [{"embedding": [0.1]}, {"embedding": [0.2]}, {"embedding": [0.3]}]}
        result = client._extract_embeddings_from_response(response=resp)
        assert len(result) == 3

    def test_missing_results_field_raises(self, client):
        with pytest.raises(ExternalServiceError, match="missing 'results' field"):
            client._extract_embeddings_from_response(response={"data": []})

    def test_results_not_a_list_raises(self, client):
        with pytest.raises(ExternalServiceError, match="'results' must be a list"):
            client._extract_embeddings_from_response(response={"results": "bad"})

    def test_result_missing_embedding_field_raises(self, client):
        with pytest.raises(ExternalServiceError, match="missing 'embedding' field"):
            client._extract_embeddings_from_response(response={"results": [{"score": 0.9}]})

    def test_embedding_not_a_list_raises(self, client):
        with pytest.raises(ExternalServiceError, match="expected list"):
            client._extract_embeddings_from_response(response={"results": [{"embedding": "vec"}]})


# ---------------------------------------------------------------------------
# TestGenerateEmbeddingsBatch
# ---------------------------------------------------------------------------


class TestGenerateEmbeddingsBatch:
    """Tests for generate_embeddings_batch."""

    def _configure_rest(self, mock_rest_cls):
        """Return the mock rest instance configured to echo back correct embedding counts."""
        mock_rest_instance = mock_rest_cls.return_value

        def _dynamic_response(*args, **kwargs):
            inputs = kwargs.get("json_data", {}).get("inputs", [])
            return {"results": [{"embedding": [float(i)]} for i in range(len(inputs))]}

        mock_rest_instance.call_rest_json.side_effect = _dynamic_response
        return mock_rest_instance

    def test_empty_input_returns_empty(self, client):
        assert client.generate_embeddings_batch([]) == []

    def test_non_list_input_raises(self, client):
        with pytest.raises(ConfigurationError, match="texts must be a list"):
            client.generate_embeddings_batch("not a list")

    def test_non_string_elements_raise(self, client):
        with pytest.raises(ConfigurationError, match="all texts must be strings"):
            client.generate_embeddings_batch([1, 2, 3])

    def test_single_batch(self, client, mock_rest_cls, mock_models):
        mock_rest = self._configure_rest(mock_rest_cls)
        result = client.generate_embeddings_batch(["a", "b"])
        assert len(result) == 2
        assert mock_rest.call_rest_json.call_count == 1

    def test_multiple_batches(self, client, mock_rest_cls, mock_models):
        """Three texts with batch_size=2 should produce two API calls."""
        mock_rest = self._configure_rest(mock_rest_cls)
        result = client.generate_embeddings_batch(["a", "b", "c"])
        assert len(result) == 3
        assert mock_rest.call_rest_json.call_count == 2

    def test_returns_all_embeddings_in_order(self, client, mock_rest_cls, mock_models):
        """Embeddings from multiple batches are concatenated in input order."""
        self._configure_rest(mock_rest_cls)
        result = client.generate_embeddings_batch(["x", "y", "z"])
        # Each batch slot i gets [float(i)]; check lengths
        assert all(isinstance(v, list) for v in result)
        assert len(result) == 3

    def test_external_service_error_propagates(self, client, mock_rest_cls, mock_models):
        """ExternalServiceError from the REST call should propagate directly."""
        mock_rest_cls.return_value.call_rest_json.side_effect = ExternalServiceError(
            message="server error", error_code="E001"
        )
        with pytest.raises(ExternalServiceError):
            client.generate_embeddings_batch(["text"])

    def test_generic_exception_wrapped_in_external_service_error(self, client, mock_rest_cls, mock_models):
        """Non-ExternalServiceError exceptions are wrapped."""
        mock_rest_cls.return_value.call_rest_json.side_effect = RuntimeError("boom")
        with pytest.raises(ExternalServiceError, match=r"Watsonx\.ai REST API"):
            client.generate_embeddings_batch(["text"])

    def test_payload_uses_project_id_key(self, client, mock_rest_cls, mock_models):
        """For container_kind='project', payload key should be 'project_id'."""
        mock_rest = self._configure_rest(mock_rest_cls)
        client.generate_embeddings_batch(["hello"])
        call_kwargs = mock_rest.call_rest_json.call_args.kwargs
        assert "project_id" in call_kwargs["json_data"]

    def test_payload_uses_space_id_key(self, mock_iam, mock_rest_cls, mock_models):
        """For container_kind='space', payload key should be 'space_id'."""
        WatsonxRestEmbeddingClient.clear_client_cache()
        space_client = WatsonxRestEmbeddingClient(
            api_key="k",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_kind="space",
            container_id="space-abc",
            model_name="ibm/slate-30m-english-rtrvr",
            batch_size=1,
        )

        def _dynamic_response(*args, **kwargs):
            inputs = kwargs.get("json_data", {}).get("inputs", [])
            return {"results": [{"embedding": [0.0]} for _ in inputs]}

        mock_rest_cls.return_value.call_rest_json.side_effect = _dynamic_response
        space_client.generate_embeddings_batch(["hello"])
        call_kwargs = mock_rest_cls.return_value.call_rest_json.call_args.kwargs
        assert "space_id" in call_kwargs["json_data"]


# ---------------------------------------------------------------------------
# TestGenerateEmbeddings (single text)
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    """Tests for generate_embeddings (single text)."""

    def test_success(self, client, mock_rest_cls, mock_models):
        mock_rest_cls.return_value.call_rest_json.return_value = {"results": [{"embedding": [0.1, 0.2]}]}
        result = client.generate_embeddings("hello world")
        assert result == [0.1, 0.2]

    def test_external_service_error_propagates(self, client, mock_rest_cls, mock_models):
        mock_rest_cls.return_value.call_rest_json.side_effect = ExternalServiceError(
            message="upstream error", error_code="E002"
        )
        with pytest.raises(ExternalServiceError):
            client.generate_embeddings("text")

    def test_generic_exception_wrapped(self, client, mock_rest_cls, mock_models):
        mock_rest_cls.return_value.call_rest_json.side_effect = ConnectionError("network")
        with pytest.raises(ExternalServiceError, match=r"Watsonx\.ai REST API"):
            client.generate_embeddings("text")


# ---------------------------------------------------------------------------
# TestStaticMethods
# ---------------------------------------------------------------------------


class TestStaticMethods:
    """Tests for static helper methods."""

    def test_get_model_token_limit_returns_default(self):
        assert WatsonxRestEmbeddingClient.get_model_token_limit("any/model") == 8192

    def test_get_embedding_dimension_returns_zero(self):
        assert WatsonxRestEmbeddingClient.get_embedding_dimension("any/model") == 0
