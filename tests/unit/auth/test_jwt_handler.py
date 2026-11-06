"""Unit tests for JWT token handling."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from pydantic import ValidationError

from docpipe.api.auth.jwt_handler import (
    _JWT_SECRET_MIN_LENGTH,
    JWTConfig,
    create_access_token,
    verify_token,
)

# Must be ≥ 32 characters to pass the length validator.
_VALID_SECRET = "a-sufficiently-long-test-secret-key"  # pragma: allowlist secret


@pytest.fixture
def jwt_config():
    """Create JWT configuration for testing."""
    return JWTConfig(
        jwt_secret_key=_VALID_SECRET,
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
    )


class TestJWTConfig:
    """Test JWT configuration."""

    def test_jwt_config_valid_key_accepted(self):
        """A key meeting the minimum length is accepted."""
        config = JWTConfig(jwt_secret_key=_VALID_SECRET)
        assert config.jwt_algorithm == "HS256"
        assert config.jwt_access_token_expire_minutes == 30

    def test_jwt_config_empty_key_rejected(self):
        """An empty key is rejected by the validator."""
        with pytest.raises(ValidationError, match="JWT secret key must be at least"):
            JWTConfig(jwt_secret_key="")

    def test_jwt_config_short_key_rejected(self):
        """A key shorter than the minimum is rejected."""
        with pytest.raises(ValidationError, match="JWT secret key must be at least"):
            JWTConfig(jwt_secret_key="short")  # pragma: allowlist secret

    def test_jwt_config_key_at_minimum_length_accepted(self):
        """A key exactly at the minimum length is accepted."""
        key = "x" * _JWT_SECRET_MIN_LENGTH
        config = JWTConfig(jwt_secret_key=key)
        assert config.jwt_secret_key == key

    def test_jwt_config_custom_values(self):
        """Test JWT config with custom values."""
        config = JWTConfig(
            jwt_secret_key=_VALID_SECRET,
            jwt_algorithm="HS512",
            jwt_access_token_expire_minutes=60,
        )
        assert config.jwt_secret_key == _VALID_SECRET
        assert config.jwt_algorithm == "HS512"
        assert config.jwt_access_token_expire_minutes == 60


class TestCreateAccessToken:
    """Test access token creation."""

    def test_create_token_with_user_data(self, jwt_config):
        """Test creating token with user data."""
        data = {
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
        }

        token = create_access_token(data, jwt_config)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_expiration(self, jwt_config):
        """Test that token contains expiration claim."""
        data = {"username": "testuser"}
        token = create_access_token(data, jwt_config)

        # Decode without verification to check claims
        payload = jwt.decode(
            token,
            jwt_config.jwt_secret_key,
            algorithms=[jwt_config.jwt_algorithm],
        )

        assert "exp" in payload
        assert "username" in payload
        assert payload["username"] == "testuser"

    def test_token_expiration_time(self, jwt_config):
        """Test that token expiration is set correctly."""
        data = {"username": "testuser"}
        before_creation = datetime.now(UTC)
        token = create_access_token(data, jwt_config)
        after_creation = datetime.now(UTC)

        payload = jwt.decode(
            token,
            jwt_config.jwt_secret_key,
            algorithms=[jwt_config.jwt_algorithm],
        )

        _exp_time = datetime.fromtimestamp(payload["exp"], tz=UTC)
        expected_min = before_creation + timedelta(minutes=jwt_config.jwt_access_token_expire_minutes)
        expected_max = after_creation + timedelta(minutes=jwt_config.jwt_access_token_expire_minutes)

        assert expected_min <= expected_max

    def test_token_preserves_data(self, jwt_config):
        """Test that token preserves all provided data."""
        data = {
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "custom_field": "custom_value",
        }

        token = create_access_token(data, jwt_config)
        payload = jwt.decode(
            token,
            jwt_config.jwt_secret_key,
            algorithms=[jwt_config.jwt_algorithm],
        )

        assert payload["username"] == data["username"]
        assert payload["email"] == data["email"]
        assert payload["full_name"] == data["full_name"]
        assert payload["custom_field"] == data["custom_field"]


class TestVerifyToken:
    """Test token verification."""

    def test_verify_valid_token(self, jwt_config):
        """Test verifying a valid token."""
        data = {"username": "testuser", "email": "test@example.com"}
        token = create_access_token(data, jwt_config)

        payload = verify_token(token, jwt_config)

        assert payload is not None
        assert payload["username"] == "testuser"
        assert payload["email"] == "test@example.com"

    def test_verify_token_without_username(self, jwt_config):
        """Test verifying token without username claim."""
        data = {"email": "test@example.com"}
        token = create_access_token(data, jwt_config)

        payload = verify_token(token, jwt_config)

        assert payload is None

    def test_verify_expired_token(self, jwt_config):
        """Test verifying an expired token."""
        data: dict[str, Any] = {"username": "testuser"}
        # Create token with past expiration
        to_encode = data.copy()
        expire = datetime.now(UTC) - timedelta(minutes=1)
        to_encode.update({"exp": expire.timestamp()})

        token = jwt.encode(
            to_encode,
            jwt_config.jwt_secret_key,
            algorithm=jwt_config.jwt_algorithm,
        )

        payload = verify_token(token, jwt_config)

        assert payload is None

    def test_verify_token_wrong_secret(self, jwt_config):
        """Test verifying token with wrong secret."""
        data = {"username": "testuser"}
        token = create_access_token(data, jwt_config)

        wrong_config = JWTConfig(
            jwt_secret_key="wrong-secret-key-that-is-long-enough",  # pragma: allowlist secret
            jwt_algorithm="HS256",
        )

        payload = verify_token(token, wrong_config)

        assert payload is None

    def test_verify_malformed_token(self, jwt_config):
        """Test verifying a malformed token."""
        malformed_token = "not.a.valid.jwt.token"

        payload = verify_token(malformed_token, jwt_config)

        assert payload is None

    def test_verify_token_wrong_algorithm(self, jwt_config):
        """Test verifying token with wrong algorithm."""
        data = {"username": "testuser"}
        # Create token with HS512
        token = jwt.encode(
            data,
            jwt_config.jwt_secret_key,
            algorithm="HS512",
        )

        payload = verify_token(token, jwt_config)

        assert payload is None

    def test_verify_empty_token(self, jwt_config):
        """Test verifying an empty token."""
        payload = verify_token("", jwt_config)

        assert payload is None


def _b64url(raw: bytes) -> str:
    """Base64url-encode without padding, as used in JWT segments."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_json(data: dict[str, Any]) -> str:
    return _b64url(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def _future_exp() -> int:
    return int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())


class TestCreateAccessTokenEdgeCases:
    """Additional create_access_token behaviour."""

    def test_expiration_matches_configured_lifetime(self, jwt_config):
        before = datetime.now(UTC).replace(microsecond=0)
        token = create_access_token({"username": "testuser"}, jwt_config)
        after = datetime.now(UTC)

        payload = jwt.decode(token, jwt_config.jwt_secret_key, algorithms=[jwt_config.jwt_algorithm])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        lifetime = timedelta(minutes=jwt_config.jwt_access_token_expire_minutes)

        assert before + lifetime <= exp <= after + lifetime

    def test_input_data_is_not_mutated(self, jwt_config):
        data = {"username": "testuser"}

        create_access_token(data, jwt_config)

        assert data == {"username": "testuser"}

    def test_token_header_uses_configured_algorithm(self):
        config = JWTConfig(jwt_secret_key=_VALID_SECRET, jwt_algorithm="HS512")

        token = create_access_token({"username": "testuser"}, config)

        assert jwt.get_unverified_header(token)["alg"] == "HS512"
        assert verify_token(token, config) is not None

    def test_unsupported_algorithm_raises(self):
        config = JWTConfig(jwt_secret_key=_VALID_SECRET, jwt_algorithm="NOT-AN-ALG")

        with pytest.raises(NotImplementedError, match="not supported"):
            create_access_token({"username": "testuser"}, config)


class TestVerifyTokenTampering:
    """verify_token must reject anything that was not signed by us, unmodified."""

    def test_tampered_payload_is_rejected(self, jwt_config):
        token = create_access_token({"username": "alice"}, jwt_config)
        header, _, signature = token.split(".")
        forged_payload = _b64url_json({"username": "admin", "exp": _future_exp()})

        assert verify_token(f"{header}.{forged_payload}.{signature}", jwt_config) is None

    def test_tampered_signature_is_rejected(self, jwt_config):
        token = create_access_token({"username": "alice"}, jwt_config)
        header, payload, signature = token.split(".")
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

        assert verify_token(f"{header}.{payload}.{flipped}", jwt_config) is None

    def test_stripped_signature_is_rejected(self, jwt_config):
        token = create_access_token({"username": "alice"}, jwt_config)
        header, payload, _ = token.split(".")

        assert verify_token(f"{header}.{payload}.", jwt_config) is None

    @pytest.mark.parametrize("alg", ["none", "None", "NONE"])
    def test_alg_none_token_is_rejected(self, *, jwt_config, alg):
        header = _b64url_json({"alg": alg, "typ": "JWT"})
        payload = _b64url_json({"username": "admin", "exp": _future_exp()})

        assert verify_token(f"{header}.{payload}.", jwt_config) is None

    def test_token_signed_with_other_hmac_algorithm_is_rejected(self, jwt_config):
        """Only the configured algorithm is accepted, even with the right secret."""
        token = jwt.encode(
            {"username": "alice", "exp": _future_exp()},
            jwt_config.jwt_secret_key,
            algorithm="HS384",
        )

        assert verify_token(token, jwt_config) is None

    def test_token_without_exp_is_rejected(self, jwt_config):
        """Regression: correctly signed tokens without ``exp`` used to be accepted forever."""
        token = jwt.encode({"username": "alice"}, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)

        assert verify_token(token, jwt_config) is None

    def test_token_not_yet_valid_is_rejected(self, jwt_config):
        not_before = int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())
        token = jwt.encode(
            {"username": "alice", "exp": _future_exp() + 3600, "nbf": not_before},
            jwt_config.jwt_secret_key,
            algorithm=jwt_config.jwt_algorithm,
        )

        assert verify_token(token, jwt_config) is None

    def test_null_username_claim_is_rejected(self, jwt_config):
        token = jwt.encode(
            {"username": None, "exp": _future_exp()},
            jwt_config.jwt_secret_key,
            algorithm=jwt_config.jwt_algorithm,
        )

        assert verify_token(token, jwt_config) is None

    @pytest.mark.parametrize("token", ["abc", "a.b", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.!!!.sig"])
    def test_garbage_tokens_are_rejected(self, *, jwt_config, token):
        assert verify_token(token, jwt_config) is None

    def test_non_string_token_is_rejected_not_raised(self, jwt_config):
        """Non-PyJWTError failures inside the decoder are swallowed and reported as invalid."""
        assert verify_token(None, jwt_config) is None  # type: ignore[arg-type]

    def test_unexpected_decoder_error_returns_none(self, jwt_config):
        token = create_access_token({"username": "alice"}, jwt_config)

        with patch("docpipe.api.auth.jwt_handler.jwt.decode", side_effect=RuntimeError("boom")):
            assert verify_token(token, jwt_config) is None
