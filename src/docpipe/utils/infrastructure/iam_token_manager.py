# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""IBM Cloud and MCSP IAM token manager for WatsonX API authentication.

This module handles the exchange of IBM Cloud and MCSP API keys for IAM access tokens,
with automatic caching and refresh before expiration. Supports both IBM Cloud and
MCSP (AWS) environments with different IAM endpoints and request formats.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.caching import LRUCache

logger = logging.getLogger(__name__)


@dataclass
class TokenData:
    """Container for cached token data."""

    access_token: str
    expires_at: float


class IAMTokenManager:
    """Manages IBM Cloud and MCSP IAM access tokens with caching and auto-refresh.

    This class handles:
    - Exchanging API keys for IAM access tokens (IBM Cloud and MCSP)
    - Environment detection from WatsonX URL (MCSP vs IBM Cloud)
    - Caching tokens with expiration tracking using project's caching infrastructure
    - Auto-refreshing tokens before they expire (10 minute buffer)
    - Thread-safe token access via LRUCache
    - Multi-tenant support via API key-based cache keys

    Environment Detection:
    - MCSP: URLs containing ".aws." or "platform.saas.ibm.com"
    - IBM Cloud: All other URLs (default)

    IAM Endpoints:
    - IBM Cloud: https://iam.cloud.ibm.com/identity/token
    - MCSP Production: https://account-iam.platform.saas.ibm.com/api/2.0/apikeys/token
    """

    # IBM Cloud IAM endpoint
    IBM_CLOUD_IAM_BASE_URL = "https://iam.cloud.ibm.com"

    # MCSP IAM endpoint
    MCSP_PROD_IAM_BASE_URL = "https://account-iam.platform.saas.ibm.com"

    REFRESH_BUFFER_SECONDS = 600  # Refresh 10 minutes before expiry
    CACHE_TTL_SECONDS = 3600  # 1 hour TTL for cache entries

    def __init__(self, *, api_key: str, watsonx_url: str, iam_url: str | None = None) -> None:
        """Initialize IAM token manager.

        Args:
            api_key: IBM Cloud or MCSP API key for authentication
            watsonx_url: WatsonX API endpoint URL (used for environment detection)
            iam_url: Optional custom IAM URL (overrides auto-detection)
        """
        self.api_key = api_key
        self.watsonx_url = watsonx_url
        self.environment = self._detect_environment(watsonx_url=watsonx_url)
        self.iam_base_url = self._get_iam_base_url(watsonx_url=watsonx_url, custom_iam_url=iam_url)
        self._cache = LRUCache(maxsize=128, ttl=self.CACHE_TTL_SECONDS)
        self._cache_key = self._generate_cache_key(api_key=api_key)

        logger.debug(
            "Initialized IAMTokenManager: environment=%s, iam_base_url=%s",
            self.environment,
            self.iam_base_url,
        )

    @staticmethod
    def _detect_environment(*, watsonx_url: str) -> str:
        """Detect environment from WatsonX URL.

        Args:
            watsonx_url: WatsonX API endpoint URL

        Returns:
            Environment type: "MCSP" or "CLOUD"
        """
        if ".aws." in watsonx_url or "platform.saas.ibm.com" in watsonx_url:
            return "MCSP"
        return "CLOUD"

    @staticmethod
    def _get_iam_base_url(*, watsonx_url: str, custom_iam_url: str | None) -> str:
        """Get IAM base URL based on environment.

        Args:
            watsonx_url: WatsonX API endpoint URL
            custom_iam_url: Optional custom IAM URL (overrides auto-detection)

        Returns:
            IAM base URL
        """
        if custom_iam_url:
            return custom_iam_url

        env = IAMTokenManager._detect_environment(watsonx_url=watsonx_url)
        if env == "MCSP":
            return IAMTokenManager.MCSP_PROD_IAM_BASE_URL
        return IAMTokenManager.IBM_CLOUD_IAM_BASE_URL

    @staticmethod
    def _generate_cache_key(*, api_key: str) -> str:
        """Generate cache key from API key hash.

        Args:
            api_key: IBM Cloud or MCSP API key

        Returns:
            Cache key string
        """
        from docpipe.integrations.secrets.registry import cache_key_digest

        return f"iam_token:{cache_key_digest(namespace='iam_token', parts=[api_key])}"

    def get_token(self) -> str:
        """Get valid IAM access token, refreshing if needed.

        Returns:
            Valid IAM access token

        Raises:
            DocpipeException: If token fetch fails
        """
        token_data = self._cache.get(cache_key=self._cache_key)

        if token_data and self._is_token_valid(token_data=token_data):
            return token_data.access_token

        return self._fetch_new_token()

    def _is_token_valid(self, *, token_data: TokenData) -> bool:
        """Check if cached token is still valid.

        Args:
            token_data: Cached token data to validate

        Returns:
            True if token hasn't expired (with buffer), False otherwise
        """
        return time.time() < (token_data.expires_at - self.REFRESH_BUFFER_SECONDS)

    def _fetch_new_token(self) -> str:
        """Exchange API key for new IAM access token.

        Returns:
            New IAM access token

        Raises:
            DocpipeException: If token exchange fails
        """
        logger.debug("Fetching new IAM access token for %s environment", self.environment)

        try:
            if self.environment == "MCSP":
                # MCSP format: JSON request body, token field in response
                url = f"{self.iam_base_url}/api/2.0/apikeys/token"
                headers = {"Content-Type": "application/json", "Accept": "application/json"}
                response = requests.post(
                    url,
                    headers=headers,
                    json={"apikey": self.api_key},
                    timeout=30,
                )

                # Log response details for debugging before raising
                if not response.ok:
                    logger.error(
                        "MCSP IAM token request failed - Status: %s, Response: %s",
                        response.status_code,
                        response.text,
                    )

                response.raise_for_status()

                mcsp_response: dict[str, Any] = response.json()
                access_token = mcsp_response["token"]
                # MCSP tokens typically have a default expiration (e.g., 3600 seconds)
                # If not provided in response, use a safe default
                expires_in = mcsp_response.get("expires_in", 3600)
                expires_at = time.time() + expires_in

            else:
                # IBM Cloud format: form-urlencoded request, access_token field in response
                url = f"{self.iam_base_url}/identity/token"
                headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
                response = requests.post(
                    url,
                    headers=headers,
                    data={
                        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                        "apikey": self.api_key,
                    },
                    timeout=30,
                )

                # Log response details for debugging before raising
                if not response.ok:
                    logger.error(
                        "IBM Cloud IAM token request failed - Status: %s, Response: %s",
                        response.status_code,
                        response.text,
                    )

                response.raise_for_status()

                cloud_response: dict[str, Any] = response.json()
                access_token = cloud_response["access_token"]
                expires_in = cloud_response["expires_in"]
                expires_at = time.time() + expires_in

            # Cache the token data
            token_data = TokenData(access_token=access_token, expires_at=expires_at)
            self._cache.put(cache_key=self._cache_key, value=token_data)

            logger.debug(
                "Successfully fetched %s IAM token, expires in %s seconds",
                self.environment,
                expires_in,
            )
            return access_token

        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to fetch IAM access token from {self.environment}: {e}"
            logger.error(error_msg)
            raise DocpipeException(message=error_msg) from e
        except (KeyError, ValueError) as e:
            error_msg = f"Invalid IAM token response format from {self.environment}: {e}"
            logger.error(error_msg)
            raise DocpipeException(message=error_msg) from e
