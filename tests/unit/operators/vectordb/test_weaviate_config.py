"""Unit tests for WeaviateConfig and format_config_errors."""

import pytest
from pydantic import ValidationError

from docpipe.core.operators.vectordb.adapters.outbound.weaviate.config import (
    ADAPTER_NAME,
    WeaviateConfig,
    format_config_errors,
)


class TestWeaviateConfig:
    """Test suite for WeaviateConfig validation and error formatting."""

    def test_adapter_name(self) -> None:
        """Verify adapter name constant."""
        assert ADAPTER_NAME == "weaviate"

    def test_defaults(self) -> None:
        """Verify all default configuration values."""
        cfg = WeaviateConfig(collection_name="Documents")
        assert cfg.collection_name == "Documents"
        assert cfg.connection_type == "custom"
        assert cfg.host == "localhost"
        assert cfg.port == 8080
        assert cfg.secure is False
        assert cfg.grpc_host is None
        assert cfg.grpc_port == 50051
        assert cfg.grpc_secure is None
        assert cfg.cluster_url is None
        assert cfg.auth_type == "none"
        assert cfg.api_key is None
        assert cfg.bearer_token is None
        assert cfg.username is None
        assert cfg.password is None
        assert cfg.timeout_init == 30
        assert cfg.timeout_query == 60
        assert cfg.timeout_insert == 120
        assert cfg.skip_init_checks is False
        assert cfg.batch_size == 100
        assert cfg.index_type == "hnsw"
        assert cfg.distance_metric == "cosine"
        assert cfg.index_parameters == {}
        assert cfg.add_sparse_vector is False

    @pytest.mark.parametrize(
        "name",
        ["DocumentChunks", "Docs_2025", "A", "Valid_Collection_123"],
    )
    def test_valid_collection_names(self, *, name: str) -> None:
        """Verify valid collection names are accepted."""
        cfg = WeaviateConfig(collection_name=name)
        assert cfg.collection_name == name

    @pytest.mark.parametrize(
        "name",
        ["documentChunks", "2Docs", "Doc-Chunks", "Doc Chunks", "", "_Invalid", "doc"],
    )
    def test_invalid_collection_names(self, *, name: str) -> None:
        """Verify invalid collection names are rejected with exact error message."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(collection_name=name)
        errors = format_config_errors(exc_info.value)
        expected_msg = "collection_name must start with an uppercase ASCII letter and contain only ASCII letters, digits, and underscores"
        assert any(expected_msg in err for err in errors)

    def test_missing_collection_name(self) -> None:
        """Verify missing collection_name yields 'collection_name is not provided'."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig.model_validate({})
        errors = format_config_errors(exc_info.value)
        assert "collection_name is not provided" in errors

    def test_cloud_missing_cluster_url(self) -> None:
        """Verify cloud deployment requires cluster_url."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                connection_type="cloud",
            )
        errors = format_config_errors(exc_info.value)
        assert any("cluster_url is required when connection_type is 'cloud'" in err for err in errors)

    def test_cloud_with_cluster_url(self) -> None:
        """Verify cloud deployment succeeds with cluster_url and auth."""
        cfg = WeaviateConfig(
            collection_name="Documents",
            connection_type="cloud",
            cluster_url="https://xyz.weaviate.cloud",
            auth_type="api_key",
            api_key="secret-key",
        )
        assert cfg.cluster_url == "https://xyz.weaviate.cloud"

    def test_auth_api_key_missing_key(self) -> None:
        """Verify api_key auth requires api_key."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                secure=True,
                auth_type="api_key",
            )
        errors = format_config_errors(exc_info.value)
        assert any("api_key is required when auth_type is 'api_key'" in err for err in errors)

    def test_auth_bearer_token_missing_token(self) -> None:
        """Verify bearer_token auth requires bearer_token."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                secure=True,
                auth_type="bearer_token",
            )
        errors = format_config_errors(exc_info.value)
        assert any("bearer_token is required when auth_type is 'bearer_token'" in err for err in errors)

    @pytest.mark.parametrize(
        ("username", "password"),
        [(None, "pass"), ("user", None), (None, None)],
    )
    def test_auth_client_password_missing_credentials(
        self,
        *,
        username: str | None,
        password: str | None,
    ) -> None:
        """Verify client_password auth requires both username and password."""
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                secure=True,
                auth_type="client_password",
                username=username,
                password=password,
            )
        errors = format_config_errors(exc_info.value)
        assert any("username and password are required when auth_type is 'client_password'" in err for err in errors)

    @pytest.mark.parametrize(
        ("auth_type", "kwargs"),
        [
            ("api_key", {"api_key": "my-secret-key"}),
            ("bearer_token", {"bearer_token": "my-bearer-token"}),
            ("client_password", {"username": "admin", "password": "super-password"}),
        ],
    )
    def test_plaintext_credentials_rejected(self, *, auth_type: str, kwargs: dict) -> None:
        """Verify credentials over plaintext HTTP or gRPC are rejected."""
        expected_msg = (
            "secure and grpc_secure must both be true when auth_type is not 'none'; "
            "credentials must not be sent over an unencrypted connection"
        )

        # 1. secure=False, grpc_secure=None (inherits False)
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                auth_type=auth_type,
                secure=False,
                **kwargs,
            )
        errors = format_config_errors(exc_info.value)
        assert any(expected_msg in err for err in errors)

        # 2. secure=True, grpc_secure=False
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                auth_type=auth_type,
                secure=True,
                grpc_secure=False,
                **kwargs,
            )
        errors = format_config_errors(exc_info.value)
        assert any(expected_msg in err for err in errors)

        # 3. secure=True, grpc_secure=True (accepted)
        cfg_both_secure = WeaviateConfig(
            collection_name="Documents",
            auth_type=auth_type,
            secure=True,
            grpc_secure=True,
            **kwargs,
        )
        assert cfg_both_secure.auth_type == auth_type

        # 4. secure=True, grpc_secure=None (inherits True, accepted)
        cfg_inherit_secure = WeaviateConfig(
            collection_name="Documents",
            auth_type=auth_type,
            secure=True,
            grpc_secure=None,
            **kwargs,
        )
        assert cfg_inherit_secure.auth_type == auth_type

    def test_auth_none_with_plaintext_accepted(self) -> None:
        """Verify auth_type='none' with secure=False is accepted."""
        cfg = WeaviateConfig(
            collection_name="Documents",
            auth_type="none",
            secure=False,
        )
        assert cfg.auth_type == "none"
        assert cfg.secure is False

    def test_ignored_extra_keys(self) -> None:
        """Verify extra keys are ignored and do not cause validation failure."""
        cfg = WeaviateConfig(
            collection_name="Documents",
            unknown_custom_key="should_be_ignored",
            another_extra=123,
        )
        assert cfg.collection_name == "Documents"
        assert not hasattr(cfg, "unknown_custom_key")

    def test_sensitive_fields_in_json_schema(self) -> None:
        """Verify credential fields are marked sensitive in JSON schema."""
        schema = WeaviateConfig.model_json_schema()
        properties = schema.get("properties", {})

        assert properties["api_key"].get("sensitive") is True
        assert properties["bearer_token"].get("sensitive") is True
        assert properties["password"].get("sensitive") is True
        assert properties["username"].get("sensitive") is not True

    def test_pattern_not_in_json_schema(self) -> None:
        """Verify collection_name does not publish a pattern regex in metadata."""
        schema = WeaviateConfig.model_json_schema()
        properties = schema.get("properties", {})
        assert "pattern" not in properties["collection_name"]

    def test_env_var_resolution_valid(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify $VAR and ${VAR} are resolvable without errors."""
        monkeypatch.setenv("TEST_WV_API_KEY", "resolved-api-key")
        monkeypatch.setenv("TEST_WV_BEARER", "resolved-bearer")

        cfg1 = WeaviateConfig(
            collection_name="Documents",
            secure=True,
            auth_type="api_key",
            api_key="$TEST_WV_API_KEY",
        )
        assert cfg1.api_key == "$TEST_WV_API_KEY"

        cfg2 = WeaviateConfig(
            collection_name="Documents",
            secure=True,
            auth_type="bearer_token",
            bearer_token="${TEST_WV_BEARER}",
        )
        assert cfg2.bearer_token == "${TEST_WV_BEARER}"

    def test_unset_env_var_raises_config_error(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify unset environment variable raises a validation error naming the variable."""
        monkeypatch.delenv("NON_EXISTENT_WV_KEY", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                secure=True,
                auth_type="api_key",
                api_key="${NON_EXISTENT_WV_KEY}",
            )
        errors = format_config_errors(exc_info.value)
        assert any("Environment variable NON_EXISTENT_WV_KEY is not set" in err for err in errors)

    def test_format_config_errors_never_discloses_input_values(self) -> None:
        """Verify format_config_errors never contains sensitive input values."""
        secret_value = "super_secret_plaintext_key_xyz_987"
        with pytest.raises(ValidationError) as exc_info:
            WeaviateConfig(
                collection_name="Documents",
                secure=False,
                auth_type="api_key",
                api_key=secret_value,
            )
        errors = format_config_errors(exc_info.value)
        for err in errors:
            assert secret_value not in err
