# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
WatsonX text detection client for IBM watsonx.ai.

Calls the native ``/ml/v1/text/detection`` REST endpoint (PII/HAP detectors).
The client owns the endpoint path, the API version, the container id payload
field, retry settings, and IAM token caching with reset on 401/403.
"""

from typing import Any
from urllib.parse import urljoin

from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.integrations.docling.vlm_pipeline_options_provider import WatsonxPipelineOptionsProvider
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod

# WatsonX API version for text detection endpoint
WATSONX_API_VERSION = "2024-07-29"

# Default request timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 120

_DETECTION_PATH = "/ml/v1/text/detection"
_DETECTIONS_FIELD = "detections"
_AUTH_FAILURE_STATUS_CODES = (401, 403)


class WatsonxDetectionClient:
    """WatsonX REST client for the text detection API.

    One ``RestClient`` is created without a token and reused for every call.
    The IAM token is cached on the instance and sent as a per-call
    ``Authorization`` header, so a refreshed token takes effect without
    rebuilding the REST client. Construction makes no network call; the IAM
    token is fetched on the first ``detect()`` call.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        container_id: str | None = None,
        container_kind: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the detection client.

        Args:
            api_key: IBM Cloud API key (exchanged for an IAM access token on first use)
            api_base: WatsonX API base URL
            container_id: Container ID (project_id or space_id)
            container_kind: Container kind used as the payload field prefix ("project" or "space")
            timeout: Request timeout in seconds (default: ``DEFAULT_TIMEOUT_SECONDS``)
        """
        self.api_key = api_key
        self.api_base = api_base
        self.container_id = container_id
        self.container_kind = container_kind
        self.timeout = timeout
        self._access_token: str | None = None

        config = RestClientConfig(
            timeout=timeout,
            retry_max_attempts=3,
            retry_multiplier=2.0,
            retry_min_wait=1.0,
            retry_max_wait=10.0,
        )
        self._rest_client = RestClient(config=config)

    def _get_access_token(self) -> str:
        """Get or fetch the cached IAM access token."""
        if not self.api_key:
            raise ValueError("WatsonX API key is required for text detection")
        if not self._access_token:
            self._access_token = WatsonxPipelineOptionsProvider._get_iam_access_token(api_key=self.api_key)
        return self._access_token

    def detect(self, *, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Call the WatsonX native text detection API.

        Args:
            payload: Request payload with the ``input`` and ``detectors`` fields.
                The container id field is added by this client.

        Returns:
            The ``detections`` list from the response, or an empty list if the
            response field is not a list.

        Raises:
            ValueError: If api_base, container_kind/container_id, or api_key is missing
            DocpipeException: If the detection request fails
        """
        if not self.api_base:
            raise ValueError("WatsonX API base URL is required for text detection")
        if not self.container_kind or not self.container_id:
            raise ValueError("container id/ container kind is required for WatsonX detection API")

        # Use urljoin for safe URL construction to prevent injection risks
        detection_url = urljoin(self.api_base, _DETECTION_PATH)
        params = {"version": WATSONX_API_VERSION}

        request_payload = dict(payload)
        request_payload[f"{self.container_kind}_id"] = self.container_id

        headers = {"Authorization": f"Bearer {self._get_access_token()}"}

        try:
            result = self._rest_client.call_rest_json(
                method=RestMethod.POST,
                url=detection_url,
                json_data=request_payload,
                query_params=params,
                headers=headers,
                expected_status_codes=[200],
            )
            detections = result.get(_DETECTIONS_FIELD, [])
            return detections if isinstance(detections, list) else []
        except ExternalServiceError as exc:
            # Only refresh token on authentication errors (401, 403)
            # For other errors (network, payload issues), preserve the token
            if exc.status_code in _AUTH_FAILURE_STATUS_CODES:
                self._access_token = None
            raise DocpipeException(
                message=f"Failed to call WatsonX detection API: {exc!s}",
                status_code=exc.status_code or 500,
            ) from exc
