# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WatsonxDetectionClient (src/docpipe/integrations/watsonx/detection_client.py)."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.rest_client import RestMethod
from docpipe.integrations.watsonx.detection_client import (
    DEFAULT_TIMEOUT_SECONDS,
    WATSONX_API_VERSION,
    WatsonxDetectionClient,
)

MODULE = "docpipe.integrations.watsonx.detection_client"
API_BASE = "https://us-south.ml.cloud.ibm.com"
PAYLOAD = {"input": "My email is john@example.com", "detectors": {"pii": {}}}


@pytest.fixture
def mock_rest_client():
    """Patch RestClient in the client module and yield the single mocked instance."""
    with patch(f"{MODULE}.RestClient") as mock_class:
        instance = MagicMock()
        instance.call_rest_json.return_value = {"detections": []}
        mock_class.return_value = instance
        yield instance


@pytest.fixture
def mock_iam_token():
    """Patch the IAM token call so no network request is made."""
    with patch(f"{MODULE}.WatsonxPipelineOptionsProvider._get_iam_access_token") as mock_token:
        mock_token.side_effect = ["token-1", "token-2", "token-3"]
        yield mock_token


@pytest.fixture
def client(mock_rest_client, mock_iam_token):
    """Create a fully configured detection client."""
    return WatsonxDetectionClient(
        api_key="test-api-key",  # pragma: allowlist secret
        api_base=API_BASE,
        container_id="test-container-id",
        container_kind="project",
        timeout=60,
    )


class TestRequest:
    """Request construction."""

    def test_url_ends_with_detection_path(self, client, mock_rest_client):
        client.detect(payload=PAYLOAD)

        kwargs = mock_rest_client.call_rest_json.call_args.kwargs
        assert kwargs["url"].endswith("/ml/v1/text/detection")
        assert kwargs["method"] == RestMethod.POST
        assert kwargs["expected_status_codes"] == [200]

    def test_version_query_param(self, client, mock_rest_client):
        client.detect(payload=PAYLOAD)

        kwargs = mock_rest_client.call_rest_json.call_args.kwargs
        assert kwargs["query_params"] == {"version": WATSONX_API_VERSION}
        assert WATSONX_API_VERSION == "2024-07-29"

    @pytest.mark.parametrize(
        ("container_kind", "expected_field", "other_field"),
        [("project", "project_id", "space_id"), ("space", "space_id", "project_id")],
    )
    def test_container_field_follows_container_kind(
        self, mock_rest_client, mock_iam_token, container_kind, expected_field, other_field
    ):
        client = WatsonxDetectionClient(
            api_key="test-api-key",  # pragma: allowlist secret
            api_base=API_BASE,
            container_id="cid-1",
            container_kind=container_kind,
        )

        client.detect(payload=PAYLOAD)

        sent = mock_rest_client.call_rest_json.call_args.kwargs["json_data"]
        assert sent[expected_field] == "cid-1"
        assert other_field not in sent
        assert sent["input"] == PAYLOAD["input"]
        assert sent["detectors"] == PAYLOAD["detectors"]

    def test_input_payload_is_not_mutated(self, client):
        payload = dict(PAYLOAD)

        client.detect(payload=payload)

        assert payload == PAYLOAD

    def test_authorization_bearer_header(self, client, mock_rest_client):
        client.detect(payload=PAYLOAD)

        kwargs = mock_rest_client.call_rest_json.call_args.kwargs
        assert kwargs["headers"] == {"Authorization": "Bearer token-1"}

    def test_rest_client_is_built_once_without_token(self, mock_rest_client, mock_iam_token):
        with patch(f"{MODULE}.RestClient") as mock_class:
            mock_class.return_value = mock_rest_client
            mock_rest_client.call_rest_json.return_value = {"detections": []}
            client = WatsonxDetectionClient(
                api_key="test-api-key",  # pragma: allowlist secret
                api_base=API_BASE,
                container_id="cid",
                container_kind="project",
                timeout=75,
            )

            client.detect(payload=PAYLOAD)
            client.detect(payload=PAYLOAD)

        assert mock_class.call_count == 1
        assert "auth_token" not in mock_class.call_args.kwargs
        config = mock_class.call_args.kwargs["config"]
        assert config.timeout == 75
        assert config.retry_max_attempts == 3
        assert config.retry_multiplier == 2.0
        assert config.retry_min_wait == 1.0
        assert config.retry_max_wait == 10.0

    def test_default_timeout_is_passed_to_rest_client_config(self, mock_iam_token):
        with patch(f"{MODULE}.RestClient") as mock_class:
            client = WatsonxDetectionClient(api_key="k", api_base=API_BASE)  # pragma: allowlist secret

        assert DEFAULT_TIMEOUT_SECONDS == 120
        assert client.timeout == DEFAULT_TIMEOUT_SECONDS
        assert mock_class.call_args.kwargs["config"].timeout == DEFAULT_TIMEOUT_SECONDS

    def test_no_network_call_on_construction(self, mock_rest_client, mock_iam_token):
        WatsonxDetectionClient(
            api_key="test-api-key",  # pragma: allowlist secret
            api_base=API_BASE,
            container_id="cid",
            container_kind="project",
        )

        mock_iam_token.assert_not_called()
        mock_rest_client.call_rest_json.assert_not_called()


class TestResponse:
    """Response handling."""

    def test_returns_detections_list(self, client, mock_rest_client):
        detections = [{"detection": "EMAIL", "score": 0.95, "start": 12, "end": 29}]
        mock_rest_client.call_rest_json.return_value = {"detections": detections}

        assert client.detect(payload=PAYLOAD) == detections

    @pytest.mark.parametrize("bad_value", [None, "EMAIL", {"a": 1}, 5])
    def test_non_list_detections_returns_empty(self, client, mock_rest_client, bad_value):
        mock_rest_client.call_rest_json.return_value = {"detections": bad_value}

        assert client.detect(payload=PAYLOAD) == []

    def test_missing_detections_returns_empty(self, client, mock_rest_client):
        mock_rest_client.call_rest_json.return_value = {}

        assert client.detect(payload=PAYLOAD) == []


class TestTokenHandling:
    """IAM token caching and reset."""

    def test_token_fetched_once_across_successful_calls(self, client, mock_iam_token, mock_rest_client):
        for _ in range(3):
            client.detect(payload=PAYLOAD)

        assert mock_iam_token.call_count == 1
        mock_iam_token.assert_called_with(api_key="test-api-key")  # pragma: allowlist secret
        tokens = [c.kwargs["headers"]["Authorization"] for c in mock_rest_client.call_rest_json.call_args_list]
        assert tokens == ["Bearer token-1"] * 3

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_failure_resets_token(self, client, mock_iam_token, mock_rest_client, status_code):
        mock_rest_client.call_rest_json.side_effect = [
            ExternalServiceError(message="denied", error_code=ErrorCode.HTTP_ERROR, status_code=status_code),
            {"detections": []},
        ]

        with pytest.raises(DocpipeException):
            client.detect(payload=PAYLOAD)
        client.detect(payload=PAYLOAD)

        assert mock_iam_token.call_count == 2
        second_headers = mock_rest_client.call_rest_json.call_args_list[1].kwargs["headers"]
        assert second_headers == {"Authorization": "Bearer token-2"}

    def test_server_error_keeps_token(self, client, mock_iam_token, mock_rest_client):
        mock_rest_client.call_rest_json.side_effect = [
            ExternalServiceError(message="boom", error_code=ErrorCode.HTTP_ERROR, status_code=500),
            {"detections": []},
        ]

        with pytest.raises(DocpipeException):
            client.detect(payload=PAYLOAD)
        client.detect(payload=PAYLOAD)

        assert mock_iam_token.call_count == 1
        second_headers = mock_rest_client.call_rest_json.call_args_list[1].kwargs["headers"]
        assert second_headers == {"Authorization": "Bearer token-1"}

    def test_connection_error_keeps_token(self, client, mock_iam_token, mock_rest_client):
        mock_rest_client.call_rest_json.side_effect = [
            ExternalServiceError(message="no route", error_code=ErrorCode.CONNECTION_ERROR),
            {"detections": []},
        ]

        with pytest.raises(DocpipeException):
            client.detect(payload=PAYLOAD)
        client.detect(payload=PAYLOAD)

        assert mock_iam_token.call_count == 1


class TestPreconditions:
    """Configuration checks raise ValueError with the established messages."""

    def test_missing_api_key(self, mock_rest_client, mock_iam_token):
        client = WatsonxDetectionClient(api_base=API_BASE, container_id="cid", container_kind="project")

        with pytest.raises(ValueError, match="WatsonX API key is required for text detection"):
            client.detect(payload=PAYLOAD)

        mock_rest_client.call_rest_json.assert_not_called()

    def test_missing_api_base(self, mock_rest_client, mock_iam_token):
        client = WatsonxDetectionClient(
            api_key="test-api-key",  # pragma: allowlist secret
            container_id="cid",
            container_kind="project",
        )

        with pytest.raises(ValueError, match="WatsonX API base URL is required for text detection"):
            client.detect(payload=PAYLOAD)

        mock_iam_token.assert_not_called()

    @pytest.mark.parametrize(
        ("container_id", "container_kind"),
        [(None, "project"), ("cid", None), (None, None)],
    )
    def test_missing_container(self, mock_rest_client, mock_iam_token, container_id, container_kind):
        client = WatsonxDetectionClient(
            api_key="test-api-key",  # pragma: allowlist secret
            api_base=API_BASE,
            container_id=container_id,
            container_kind=container_kind,
        )

        with pytest.raises(ValueError, match="container id/ container kind is required for WatsonX detection API"):
            client.detect(payload=PAYLOAD)

        mock_iam_token.assert_not_called()


class TestErrorTranslation:
    """ExternalServiceError is raised as DocpipeException with the original status."""

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 429, 500, 503])
    def test_external_service_error_becomes_docpipe_exception(self, client, mock_rest_client, status_code):
        original = ExternalServiceError(
            message="upstream failure", error_code=ErrorCode.HTTP_ERROR, status_code=status_code
        )
        mock_rest_client.call_rest_json.side_effect = original

        with pytest.raises(DocpipeException) as exc_info:
            client.detect(payload=PAYLOAD)

        assert not isinstance(exc_info.value, ExternalServiceError)
        assert exc_info.value.status_code == status_code
        assert "Failed to call WatsonX detection API" in str(exc_info.value)
        assert "upstream failure" in str(exc_info.value)
        assert exc_info.value.__cause__ is original

    def test_missing_status_code_falls_back_to_500(self, client, mock_iam_token, mock_rest_client):
        original = ExternalServiceError(message="no status", error_code=ErrorCode.CONNECTION_ERROR)
        original.status_code = None  # type: ignore[assignment]
        mock_rest_client.call_rest_json.side_effect = [original, {"detections": []}]

        with pytest.raises(DocpipeException) as exc_info:
            client.detect(payload=PAYLOAD)
        client.detect(payload=PAYLOAD)

        assert exc_info.value.status_code == 500
        assert mock_iam_token.call_count == 1
