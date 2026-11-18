"""Tests for IAM token manager."""

from unittest.mock import Mock, patch

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.iam_token_manager import IAMTokenManager, TokenData


class TestIAMTokenManager:
    """Test IAMTokenManager."""

    def test_init_cloud_environment(self):
        """Test initialization for IBM Cloud."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        assert manager.environment == "CLOUD"
        assert manager.iam_base_url == IAMTokenManager.IBM_CLOUD_IAM_BASE_URL

    def test_init_mcsp_environment(self):
        """Test initialization for MCSP."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-east.aws.ml.cloud.ibm.com",
        )

        assert manager.environment == "MCSP"
        assert manager.iam_base_url == IAMTokenManager.MCSP_PROD_IAM_BASE_URL

    def test_detect_environment_mcsp_aws(self):
        """Test MCSP detection from AWS URL."""
        assert (
            IAMTokenManager._detect_environment(
                watsonx_url="https://us-east.aws.ml.cloud.ibm.com",
            )
            == "MCSP"
        )

    def test_detect_environment_mcsp_platform(self):
        """Test MCSP detection from SaaS platform URL."""
        assert (
            IAMTokenManager._detect_environment(
                watsonx_url="https://platform.saas.ibm.com/watsonx",
            )
            == "MCSP"
        )

    def test_detect_environment_cloud(self):
        """Test IBM Cloud detection."""
        assert (
            IAMTokenManager._detect_environment(
                watsonx_url="https://us-south.ml.cloud.ibm.com",
            )
            == "CLOUD"
        )

    def test_get_iam_base_url_custom(self):
        """Test custom IAM URL."""
        custom_url = "https://custom-iam.example.com"

        result = IAMTokenManager._get_iam_base_url(
            watsonx_url="https://us-south.ml.cloud.ibm.com",
            custom_iam_url=custom_url,
        )

        assert result == custom_url

    def test_get_iam_base_url_mcsp(self):
        """Test default MCSP IAM URL."""
        result = IAMTokenManager._get_iam_base_url(
            watsonx_url="https://us-east.aws.ml.cloud.ibm.com",
            custom_iam_url=None,
        )

        assert result == IAMTokenManager.MCSP_PROD_IAM_BASE_URL

    def test_get_iam_base_url_cloud(self):
        """Test default IBM Cloud IAM URL."""
        result = IAMTokenManager._get_iam_base_url(
            watsonx_url="https://us-south.ml.cloud.ibm.com",
            custom_iam_url=None,
        )

        assert result == IAMTokenManager.IBM_CLOUD_IAM_BASE_URL

    def test_generate_cache_key(self):
        """Test cache key generation."""
        key = IAMTokenManager._generate_cache_key(api_key="test-api-key")

        assert key.startswith("iam_token:")
        assert len(key) == len("iam_token:") + 64

    @patch("docpipe.utils.infrastructure.iam_token_manager.time.time", return_value=1000.0)
    def test_is_token_valid(self, mock_time):
        """Test token validity check."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        valid_token = TokenData(
            access_token="token",
            expires_at=2000.0,
        )
        expired_token = TokenData(
            access_token="token",
            expires_at=1500.0,
        )

        assert manager._is_token_valid(token_data=valid_token) is True
        assert manager._is_token_valid(token_data=expired_token) is False
        mock_time.assert_called()

    def test_get_token_from_cache(self):
        """Test returning a valid cached token."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        token_data = TokenData(
            access_token="cached-token",
            expires_at=10**12,
        )
        manager._cache.put(
            cache_key=manager._cache_key,
            value=token_data,
        )

        with patch.object(manager, "_fetch_new_token") as mock_fetch:
            result = manager.get_token()

        assert result == "cached-token"
        mock_fetch.assert_not_called()

    def test_get_token_fetches_when_cache_missing(self):
        """Test fetching a token when no cached token exists."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with patch.object(manager, "_fetch_new_token", return_value="new-token") as mock_fetch:
            result = manager.get_token()

        assert result == "new-token"
        mock_fetch.assert_called_once()

    def test_get_token_fetches_when_token_expired(self):
        """Test fetching a new token when cached token is expired."""
        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        expired_token = TokenData(
            access_token="expired-token",
            expires_at=0,
        )
        manager._cache.put(
            cache_key=manager._cache_key,
            value=expired_token,
        )

        with patch.object(manager, "_fetch_new_token", return_value="new-token") as mock_fetch:
            result = manager.get_token()

        assert result == "new-token"
        mock_fetch.assert_called_once()

    @patch("docpipe.utils.infrastructure.iam_token_manager.time.time", return_value=1000.0)
    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_cloud_success(self, mock_post, mock_time):
        """Test fetching a token from IBM Cloud IAM."""
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "access_token": "cloud-token",
            "expires_in": 3600,
        }
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        result = manager._fetch_new_token()

        assert result == "cloud-token"
        mock_post.assert_called_once_with(
            f"{IAMTokenManager.IBM_CLOUD_IAM_BASE_URL}/identity/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": "test-api-key",
            },
            timeout=30,
        )
        response.raise_for_status.assert_called_once()

        cached = manager._cache.get(cache_key=manager._cache_key)
        assert cached.access_token == "cloud-token"
        assert cached.expires_at == 4600.0
        mock_time.assert_called()

    @patch("docpipe.utils.infrastructure.iam_token_manager.time.time", return_value=1000.0)
    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_mcsp_success(self, mock_post, mock_time):
        """Test fetching a token from MCSP IAM."""
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "token": "mcsp-token",
            "expires_in": 1800,
        }
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-east.aws.ml.cloud.ibm.com",
        )

        result = manager._fetch_new_token()

        assert result == "mcsp-token"
        mock_post.assert_called_once_with(
            f"{IAMTokenManager.MCSP_PROD_IAM_BASE_URL}/api/2.0/apikeys/token",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"apikey": "test-api-key"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once()

        cached = manager._cache.get(cache_key=manager._cache_key)
        assert cached.access_token == "mcsp-token"
        assert cached.expires_at == 2800.0
        mock_time.assert_called()

    @patch("docpipe.utils.infrastructure.iam_token_manager.time.time", return_value=1000.0)
    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_mcsp_default_expiration(self, mock_post, mock_time):
        """Test MCSP token default expiration."""
        response = Mock()
        response.ok = True
        response.json.return_value = {"token": "mcsp-token"}
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-east.aws.ml.cloud.ibm.com",
        )

        result = manager._fetch_new_token()

        assert result == "mcsp-token"

        cached = manager._cache.get(cache_key=manager._cache_key)
        assert cached.expires_at == 4600.0

    @pytest.mark.parametrize(
        "watsonx_url",
        [
            "https://us-east.aws.ml.cloud.ibm.com",
            "https://platform.saas.ibm.com/watsonx",
        ],
    )
    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_mcsp_error_response(self, mock_post, watsonx_url):
        """Test MCSP non-success response logging and error handling."""
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.text = "Unauthorized"
        response.raise_for_status.side_effect = RuntimeError("request failed")
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url=watsonx_url,
        )

        with pytest.raises(RuntimeError, match="request failed"):
            manager._fetch_new_token()

    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_cloud_error_response(self, mock_post):
        """Test IBM Cloud non-success response logging and error handling."""
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.text = "Unauthorized"
        response.raise_for_status.side_effect = RuntimeError("request failed")
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with pytest.raises(RuntimeError, match="request failed"):
            manager._fetch_new_token()

    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_request_exception(self, mock_post):
        """Test request exceptions are converted to DocpipeException."""
        mock_post.side_effect = RuntimeError("connection failed")

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with pytest.raises(RuntimeError, match="connection failed"):
            manager._fetch_new_token()

    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_requests_exception(self, mock_post):
        """Test requests RequestException is converted to DocpipeException."""
        import requests

        mock_post.side_effect = requests.exceptions.RequestException("connection failed")

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with pytest.raises(DocpipeException, match="Failed to fetch IAM access token"):
            manager._fetch_new_token()

    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_invalid_response_key(self, mock_post):
        """Test invalid token response is converted to DocpipeException."""
        response = Mock()
        response.ok = True
        response.json.return_value = {}
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with pytest.raises(DocpipeException, match="Invalid IAM token response format"):
            manager._fetch_new_token()

    @patch("docpipe.utils.infrastructure.iam_token_manager.requests.post")
    def test_fetch_new_token_invalid_response_value(self, mock_post):
        """Test invalid response value is converted to DocpipeException."""
        response = Mock()
        response.ok = True
        response.json.side_effect = ValueError("invalid JSON")
        mock_post.return_value = response

        manager = IAMTokenManager(
            api_key="test-api-key",
            watsonx_url="https://us-south.ml.cloud.ibm.com",
        )

        with pytest.raises(DocpipeException, match="Invalid IAM token response format"):
            manager._fetch_new_token()
