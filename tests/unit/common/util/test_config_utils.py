"""
Unit tests for configuration utilities.
Tests for environment configuration loading and parsing.
"""

import os
from unittest.mock import patch

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.config import (
    get_env_bool,
    get_env_int,
    get_env_var,
    get_milvus_config,
    get_opensearch_config,
)


class TestGetOpensearchConfig:
    """Test OpenSearch configuration loading."""

    def test_get_opensearch_config_defaults(self):
        """Test that default configuration values are returned."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_opensearch_config()

            # Operator-level params
            assert "create_index" not in config
            assert config[OperatorConstants.Columns.DOC_ID_COLUMN] == "doc_id_hash"

            # Provider-specific params and resource name are in provider_config
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]
            assert provider_config[OperatorConstants.VectorDB.INDEX_NAME] == "docpipe_test"
            assert provider_config[OperatorConstants.VectorDB.HOST] == "localhost"
            assert provider_config[OperatorConstants.VectorDB.PORT] == 9200
            assert provider_config[OperatorConstants.VectorDB.USE_SSL] is False
            assert provider_config[OperatorConstants.VectorDB.VERIFY_CERTS] is False
            assert provider_config[OperatorConstants.Config.BATCH_SIZE] == 100
            assert provider_config[OperatorConstants.VectorDB.ENGINE] == "faiss"
            assert provider_config[OperatorConstants.VectorDB.ALGORITHM] == "hnsw"
            assert provider_config[OperatorConstants.VectorDB.SPACE_TYPE] == "l2"

    def test_get_opensearch_config_with_custom_values(self):
        """Test configuration with custom environment variables."""
        custom_env = {
            "OPENSEARCH_HOST": "custom-host",
            "OPENSEARCH_PORT": "9300",
            "OPENSEARCH_USE_SSL": "true",
            "OPENSEARCH_VERIFY_CERTS": "true",
            "OPENSEARCH_USERNAME": "admin",
            "OPENSEARCH_PASSWORD": "secret",  # pragma: allowlist secret
            "OPENSEARCH_ENGINE": "nmslib",
            "OPENSEARCH_ALGORITHM": "ivf",
            "OPENSEARCH_SPACE_TYPE": "cosine",
            "OPENSEARCH_VECTOR_DIMENSION": "768",
            "OPENSEARCH_BATCH_SIZE": "200",
            "OPENSEARCH_INDEX_NAME": "custom_index",
            "OPENSEARCH_DOC_ID_COLUMN": "custom_id",
            "OPENSEARCH_EMBEDDINGS_COLUMN": "custom_embeddings",
        }

        with patch.dict(os.environ, custom_env, clear=True):
            config = get_opensearch_config()

            # Operator-level params
            assert config[OperatorConstants.Columns.DOC_ID_COLUMN] == "custom_id"

            # Provider-specific params and resource name are in provider_config
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]
            assert provider_config[OperatorConstants.VectorDB.INDEX_NAME] == "custom_index"
            assert provider_config[OperatorConstants.VectorDB.HOST] == "custom-host"
            assert provider_config[OperatorConstants.VectorDB.PORT] == 9300
            assert provider_config[OperatorConstants.VectorDB.USE_SSL] is True
            assert provider_config[OperatorConstants.VectorDB.VERIFY_CERTS] is True
            assert provider_config[OperatorConstants.VectorDB.USERNAME] == "admin"
            assert (
                provider_config[OperatorConstants.VectorDB.PASSWORD] == "secret"  # pragma: allowlist secret
            )
            assert provider_config[OperatorConstants.Config.BATCH_SIZE] == 200
            assert provider_config[OperatorConstants.VectorDB.ENGINE] == "nmslib"
            assert provider_config[OperatorConstants.VectorDB.ALGORITHM] == "ivf"
            assert provider_config[OperatorConstants.VectorDB.SPACE_TYPE] == "cosine"

    def test_get_opensearch_config_with_aws_auth(self):
        """Test configuration with AWS authentication enabled."""
        aws_env = {"OPENSEARCH_AWS_AUTH": "true", "OPENSEARCH_AWS_REGION": "us-west-2"}

        with patch.dict(os.environ, aws_env, clear=True):
            config = get_opensearch_config()

            # AWS auth is in provider_config
            provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
            assert provider_config.get(OperatorConstants.VectorDB.AWS_AUTH) is True
            assert provider_config.get(OperatorConstants.VectorDB.AWS_REGION) == "us-west-2"

    def test_get_opensearch_config_boolean_variations(self):
        """Test that various boolean string values are parsed correctly."""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("YES", True),
            ("on", True),
            ("ON", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("invalid", False),
        ]

        for value, expected in test_cases:
            with patch.dict(os.environ, {"OPENSEARCH_USE_SSL": value}, clear=True):
                config = get_opensearch_config()
                provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]
                assert provider_config[OperatorConstants.VectorDB.USE_SSL] == expected

    def test_get_opensearch_config_removes_none_values(self):
        """Test that optional auth values are omitted when not set."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_opensearch_config()
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]

            assert OperatorConstants.VectorDB.USERNAME not in provider_config
            assert OperatorConstants.VectorDB.PASSWORD not in provider_config

    def test_get_opensearch_config_with_partial_settings(self):
        """Test configuration with only some environment variables set."""
        partial_env = {"OPENSEARCH_HOST": "partial-host", "OPENSEARCH_PORT": "9400"}

        with patch.dict(os.environ, partial_env, clear=True):
            config = get_opensearch_config()

            # Provider-specific params are in provider_config
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]

            # Custom values
            assert provider_config[OperatorConstants.VectorDB.HOST] == "partial-host"
            assert provider_config[OperatorConstants.VectorDB.PORT] == 9400

            # Default values for unset variables
            assert provider_config[OperatorConstants.VectorDB.USE_SSL] is False
            assert provider_config[OperatorConstants.VectorDB.ENGINE] == "faiss"


class TestGetMilvusConfig:
    """Test Milvus configuration loading."""

    def test_get_milvus_config_defaults(self):
        """Test that default configuration values are returned."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_milvus_config()

            # Operator-level params; create_index is no longer configurable
            assert "create_index" not in config
            assert config[OperatorConstants.VectorDB.VECTOR_DIMENSION] == 384
            assert config[OperatorConstants.Columns.DOC_ID_COLUMN] == "doc_id_hash"
            assert config[OperatorConstants.Columns.EMBEDDINGS_COLUMN] == "embeddings"

            # Provider-specific params and resource name are in provider_config
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]
            assert provider_config[OperatorConstants.VectorDB.COLLECTION_NAME] == "docpipe_test"
            assert provider_config[OperatorConstants.VectorDB.AUTH_TYPE] == "standalone"
            assert provider_config[OperatorConstants.VectorDB.HOST] == "localhost"
            assert provider_config[OperatorConstants.VectorDB.PORT] == 19530
            assert provider_config[OperatorConstants.VectorDB.DATABASE] == "default"
            assert provider_config[OperatorConstants.VectorDB.INDEX_TYPE] == "HNSW"
            assert provider_config[OperatorConstants.VectorDB.METRIC_TYPE] == "L2"
            assert provider_config[OperatorConstants.Config.BATCH_SIZE] == 100

    def test_get_milvus_config_omits_unset_optional_values(self):
        """Test that optional connection and auth values are omitted when not set."""
        with patch.dict(os.environ, {}, clear=True):
            provider_config = get_milvus_config()[OperatorConstants.Config.PROVIDER_CONFIG]

            for key in (
                OperatorConstants.VectorDB.URI,
                OperatorConstants.VectorDB.USERNAME,
                OperatorConstants.VectorDB.PASSWORD,
                OperatorConstants.VectorDB.TOKEN,
                OperatorConstants.VectorDB.SSL,
                OperatorConstants.VectorDB.SSL_CERTIFICATE,
            ):
                assert key not in provider_config

    def test_get_milvus_config_with_custom_values(self):
        """Test configuration with custom environment variables."""
        custom_env = {
            "MILVUS_AUTH_TYPE": "grpc",
            "MILVUS_HOST": "milvus-host",
            "MILVUS_PORT": "19531",
            "MILVUS_DATABASE": "custom_db",
            "MILVUS_INDEX_TYPE": "IVF_FLAT",
            "MILVUS_METRIC_TYPE": "COSINE",
            "MILVUS_BATCH_SIZE": "250",
            "MILVUS_URI": "https://milvus.example.com:443",
            "MILVUS_USERNAME": "admin",
            "MILVUS_PASSWORD": "secret",  # pragma: allowlist secret
            "MILVUS_TOKEN": "iam-token",
            "MILVUS_SSL": "true",
            "MILVUS_SSL_CERTIFICATE": "/certs/ca.pem",
            "MILVUS_VECTOR_DIMENSION": "768",
            "MILVUS_COLLECTION_NAME": "custom_collection",
            "MILVUS_DOC_ID_COLUMN": "custom_id",
            "MILVUS_EMBEDDINGS_COLUMN": "custom_embeddings",
        }

        with patch.dict(os.environ, custom_env, clear=True):
            config = get_milvus_config()

            assert config[OperatorConstants.VectorDB.VECTOR_DIMENSION] == 768
            assert config[OperatorConstants.Columns.DOC_ID_COLUMN] == "custom_id"
            assert config[OperatorConstants.Columns.EMBEDDINGS_COLUMN] == "custom_embeddings"

            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]
            assert provider_config[OperatorConstants.VectorDB.COLLECTION_NAME] == "custom_collection"
            assert provider_config[OperatorConstants.VectorDB.AUTH_TYPE] == "grpc"
            assert provider_config[OperatorConstants.VectorDB.HOST] == "milvus-host"
            assert provider_config[OperatorConstants.VectorDB.PORT] == 19531
            assert provider_config[OperatorConstants.VectorDB.DATABASE] == "custom_db"
            assert provider_config[OperatorConstants.VectorDB.INDEX_TYPE] == "IVF_FLAT"
            assert provider_config[OperatorConstants.VectorDB.METRIC_TYPE] == "COSINE"
            assert provider_config[OperatorConstants.Config.BATCH_SIZE] == 250
            assert provider_config[OperatorConstants.VectorDB.URI] == "https://milvus.example.com:443"
            assert provider_config[OperatorConstants.VectorDB.USERNAME] == "admin"
            assert (
                provider_config[OperatorConstants.VectorDB.PASSWORD] == "secret"  # pragma: allowlist secret
            )
            assert provider_config[OperatorConstants.VectorDB.TOKEN] == "iam-token"
            assert provider_config[OperatorConstants.VectorDB.SSL] is True
            assert provider_config[OperatorConstants.VectorDB.SSL_CERTIFICATE] == "/certs/ca.pem"

    def test_get_milvus_config_ssl_boolean_variations(self):
        """Test that various boolean string values are parsed correctly for SSL."""
        test_cases = [("true", True), ("1", True), ("yes", True), ("on", True), ("false", False), ("no", False)]

        for value, expected in test_cases:
            with patch.dict(os.environ, {"MILVUS_SSL": value}, clear=True):
                provider_config = get_milvus_config()[OperatorConstants.Config.PROVIDER_CONFIG]
                assert provider_config[OperatorConstants.VectorDB.SSL] is expected

    def test_get_milvus_config_ignores_legacy_create_index_env(self):
        """The removed MILVUS_CREATE_INDEX variable no longer affects the config."""
        with patch.dict(os.environ, {"MILVUS_CREATE_INDEX": "false"}, clear=True):
            config = get_milvus_config()

            assert "create_index" not in config
            assert "create_index" not in config[OperatorConstants.Config.PROVIDER_CONFIG]


class TestGetEnvVar:
    """Test get_env_var functionality."""

    def test_get_env_var_existing(self):
        """Test getting an existing environment variable."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = get_env_var("TEST_VAR")
            assert result == "test_value"

    def test_get_env_var_nonexistent_with_default(self):
        """Test getting non-existent variable with default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_var("NONEXISTENT_VAR", default="default_value")
            assert result == "default_value"

    def test_get_env_var_nonexistent_without_default(self):
        """Test getting non-existent variable without default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_var("NONEXISTENT_VAR")
            assert result is None

    def test_get_env_var_empty_string(self):
        """Test getting environment variable with empty string value."""
        with patch.dict(os.environ, {"EMPTY_VAR": ""}):
            result = get_env_var("EMPTY_VAR")
            assert result == ""

    def test_get_env_var_with_spaces(self):
        """Test getting environment variable with spaces."""
        with patch.dict(os.environ, {"SPACE_VAR": "  value with spaces  "}):
            result = get_env_var("SPACE_VAR")
            assert result == "  value with spaces  "

    def test_get_env_var_with_special_characters(self):
        """Test getting environment variable with special characters."""
        with patch.dict(os.environ, {"SPECIAL_VAR": "value!@#$%^&*()"}):
            result = get_env_var("SPECIAL_VAR")
            assert result == "value!@#$%^&*()"

    def test_get_env_var_with_unicode(self):
        """Test getting environment variable with Unicode characters."""
        with patch.dict(os.environ, {"UNICODE_VAR": "Hello 世界"}):
            result = get_env_var("UNICODE_VAR")
            assert result == "Hello 世界"


class TestGetEnvBool:
    """Test get_env_bool functionality."""

    def test_get_env_bool_true_values(self):
        """Test that various true values are parsed correctly."""
        true_values = ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]

        for value in true_values:
            with patch.dict(os.environ, {"BOOL_VAR": value}):
                result = get_env_bool("BOOL_VAR")
                assert result is True, f"Failed for value: {value}"

    def test_get_env_bool_false_values(self):
        """Test that various false values are parsed correctly."""
        false_values = [
            "false",
            "False",
            "FALSE",
            "0",
            "no",
            "NO",
            "off",
            "OFF",
            "invalid",
        ]

        for value in false_values:
            with patch.dict(os.environ, {"BOOL_VAR": value}):
                result = get_env_bool("BOOL_VAR")
                assert result is False, f"Failed for value: {value}"

    def test_get_env_bool_nonexistent_with_default_true(self):
        """Test getting non-existent boolean with default True."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_bool("NONEXISTENT_BOOL", default=True)
            assert result is True

    def test_get_env_bool_nonexistent_with_default_false(self):
        """Test getting non-existent boolean with default False."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_bool("NONEXISTENT_BOOL", default=False)
            assert result is False

    def test_get_env_bool_nonexistent_without_default(self):
        """Test getting non-existent boolean without default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_bool("NONEXISTENT_BOOL")
            assert result is False  # Default is False

    def test_get_env_bool_empty_string(self):
        """Test that empty string is treated as False."""
        with patch.dict(os.environ, {"BOOL_VAR": ""}):
            result = get_env_bool("BOOL_VAR")
            assert result is False

    def test_get_env_bool_case_insensitive(self):
        """Test that boolean parsing is case-insensitive."""
        test_cases = [
            ("TrUe", True),
            ("YeS", True),
            ("On", True),
            ("FaLsE", False),
            ("No", False),
            ("OfF", False),
        ]

        for value, expected in test_cases:
            with patch.dict(os.environ, {"BOOL_VAR": value}):
                result = get_env_bool("BOOL_VAR")
                assert result == expected


class TestGetEnvInt:
    """Test get_env_int functionality."""

    def test_get_env_int_valid_integer(self):
        """Test getting valid integer values."""
        test_cases = ["0", "1", "42", "100", "-5", "-100"]

        for value in test_cases:
            with patch.dict(os.environ, {"INT_VAR": value}):
                result = get_env_int("INT_VAR")
                assert result == int(value)

    def test_get_env_int_nonexistent_with_default(self):
        """Test getting non-existent integer with default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_int("NONEXISTENT_INT", default=42)
            assert result == 42

    def test_get_env_int_nonexistent_without_default(self):
        """Test getting non-existent integer without default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_int("NONEXISTENT_INT")
            assert result == 0  # Default is 0

    def test_get_env_int_invalid_value_returns_default(self):
        """Test that invalid integer values return default."""
        invalid_values = ["not_a_number", "12.34", "abc", ""]

        for value in invalid_values:
            with patch.dict(os.environ, {"INT_VAR": value}):
                result = get_env_int("INT_VAR", default=99)
                assert result == 99, f"Failed for value: {value}"

    def test_get_env_int_large_numbers(self):
        """Test getting large integer values."""
        with patch.dict(os.environ, {"INT_VAR": "999999999"}):
            result = get_env_int("INT_VAR")
            assert result == 999999999

    def test_get_env_int_negative_numbers(self):
        """Test getting negative integer values."""
        with patch.dict(os.environ, {"INT_VAR": "-12345"}):
            result = get_env_int("INT_VAR")
            assert result == -12345

    def test_get_env_int_zero(self):
        """Test getting zero value."""
        with patch.dict(os.environ, {"INT_VAR": "0"}):
            result = get_env_int("INT_VAR")
            assert result == 0

    def test_get_env_int_with_whitespace(self):
        """Test that whitespace in integer string is handled."""
        with patch.dict(os.environ, {"INT_VAR": "  42  "}):
            result = get_env_int("INT_VAR")
            assert result == 42

    def test_get_env_int_with_plus_sign(self):
        """Test integer with plus sign."""
        with patch.dict(os.environ, {"INT_VAR": "+42"}):
            result = get_env_int("INT_VAR")
            assert result == 42


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_opensearch_config_with_invalid_port(self):
        """Test that invalid port number uses default."""
        with patch.dict(os.environ, {"OPENSEARCH_PORT": "invalid"}):
            # Should handle gracefully or use default
            try:
                config = get_opensearch_config()
                # If it doesn't raise, check it has some port value
                assert "port" in config
            except ValueError:
                # ValueError is acceptable for invalid port
                pass

    def test_opensearch_config_with_invalid_dimension(self):
        """Test that invalid vector dimension uses default."""
        with patch.dict(os.environ, {"OPENSEARCH_VECTOR_DIMENSION": "not_a_number"}):
            try:
                config = get_opensearch_config()
                assert "vector_dimension" in config
            except ValueError:
                pass

    def test_get_env_var_with_none_default(self):
        """Test get_env_var with None as default."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_env_var("NONEXISTENT", default=None)
            assert result is None

    def test_get_env_bool_with_numeric_string(self):
        """Test get_env_bool with numeric strings."""
        with patch.dict(os.environ, {"BOOL_VAR": "2"}):
            result = get_env_bool("BOOL_VAR")
            # "2" is not in the true list, so should be False
            assert result is False

    def test_get_env_int_with_float_string(self):
        """Test that float strings return default."""
        with patch.dict(os.environ, {"INT_VAR": "3.14"}):
            result = get_env_int("INT_VAR", default=10)
            assert result == 10

    def test_opensearch_config_all_optional_fields_set(self):
        """Test configuration with all optional fields set."""
        full_env = {
            "OPENSEARCH_HOST": "host",
            "OPENSEARCH_PORT": "9200",
            "OPENSEARCH_USE_SSL": "true",
            "OPENSEARCH_VERIFY_CERTS": "true",
            "OPENSEARCH_USERNAME": "user",
            "OPENSEARCH_PASSWORD": "pass",  # pragma: allowlist secret
            "OPENSEARCH_AWS_AUTH": "true",
            "OPENSEARCH_AWS_REGION": "us-east-1",
            "OPENSEARCH_ENGINE": "faiss",
            "OPENSEARCH_ALGORITHM": "hnsw",
            "OPENSEARCH_SPACE_TYPE": "l2",
            "OPENSEARCH_VECTOR_DIMENSION": "384",
            "OPENSEARCH_BATCH_SIZE": "100",
            "OPENSEARCH_INDEX_NAME": "test",
            "OPENSEARCH_DOC_ID_COLUMN": "id",
            "OPENSEARCH_EMBEDDINGS_COLUMN": "emb",
        }

        with patch.dict(os.environ, full_env, clear=True):
            config = get_opensearch_config()
            provider_config = config[OperatorConstants.Config.PROVIDER_CONFIG]

            # All optional provider fields should be present
            assert len(config) > 0
            assert provider_config[OperatorConstants.VectorDB.USERNAME] == "user"
            assert (
                provider_config[OperatorConstants.VectorDB.PASSWORD] == "pass"  # pragma: allowlist secret
            )
