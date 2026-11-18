"""
Environment configuration utilities for OpenSearch, Milvus, and other services.
Loads configuration from .env file or environment variables.
"""

import os

from dotenv import load_dotenv

from docpipe.core.constants.operator_constants import OperatorConstants

# Load .env file from project root
load_dotenv()


def get_opensearch_config() -> dict:
    """
    Load OpenSearch configuration from environment variables.

    Returns:
        dict: Configuration dictionary with all OpenSearch settings using provider_config pattern.
              All provider-specific parameters (including connection settings) are in provider_config.
    """

    def str_to_bool(value: str) -> bool:
        """Convert string to boolean."""
        return value.lower() in ("true", "1", "yes", "on")

    # All OpenSearch-specific parameters go in provider_config
    provider_config: dict[str, str | bool | int] = {
        # Connection settings
        OperatorConstants.VectorDB.HOST: os.getenv(OperatorConstants.VectorDB.OPENSEARCH_HOST, "localhost"),
        OperatorConstants.VectorDB.PORT: int(os.getenv(OperatorConstants.VectorDB.OPENSEARCH_PORT, "9200")),
        OperatorConstants.VectorDB.USE_SSL: str_to_bool(
            os.getenv(OperatorConstants.VectorDB.OPENSEARCH_USE_SSL, "false")
        ),
        OperatorConstants.VectorDB.VERIFY_CERTS: str_to_bool(
            os.getenv(OperatorConstants.VectorDB.OPENSEARCH_VERIFY_CERTS, "false")
        ),
        # KNN engine configuration
        OperatorConstants.VectorDB.ENGINE: os.getenv(OperatorConstants.VectorDB.OPENSEARCH_ENGINE, "faiss"),
        OperatorConstants.VectorDB.ALGORITHM: os.getenv(OperatorConstants.VectorDB.OPENSEARCH_ALGORITHM, "hnsw"),
        OperatorConstants.VectorDB.SPACE_TYPE: os.getenv(OperatorConstants.VectorDB.OPENSEARCH_SPACE_TYPE, "l2"),
        # Performance settings
        OperatorConstants.Config.BATCH_SIZE: int(os.getenv(OperatorConstants.VectorDB.OPENSEARCH_BATCH_SIZE, "100")),
    }

    # Add authentication if configured
    username = os.getenv(OperatorConstants.VectorDB.OPENSEARCH_USERNAME)
    if username:
        provider_config[OperatorConstants.VectorDB.USERNAME] = username

    password = os.getenv(OperatorConstants.VectorDB.OPENSEARCH_PASSWORD)
    if password:
        provider_config[OperatorConstants.VectorDB.PASSWORD] = password

    # Add AWS auth if configured
    if str_to_bool(os.getenv(OperatorConstants.VectorDB.OPENSEARCH_AWS_AUTH, "false")):
        provider_config[OperatorConstants.VectorDB.AWS_AUTH] = True
        provider_config[OperatorConstants.VectorDB.AWS_REGION] = os.getenv(
            OperatorConstants.VectorDB.OPENSEARCH_AWS_REGION, "us-east-1"
        )

    # Add JWT token if configured
    jwt_token = os.getenv(OperatorConstants.VectorDB.OPENSEARCH_JWT_TOKEN)
    if jwt_token:
        provider_config[OperatorConstants.VectorDB.JWT_TOKEN] = jwt_token

    # Add resource name into provider_config — each provider owns its resource key
    provider_config[OperatorConstants.VectorDB.INDEX_NAME] = os.getenv(
        OperatorConstants.VectorDB.OPENSEARCH_INDEX_NAME, "docpipe_test"
    )

    return {
        # Vector dimension
        OperatorConstants.VectorDB.VECTOR_DIMENSION: int(
            os.getenv(OperatorConstants.VectorDB.OPENSEARCH_VECTOR_DIMENSION, "384")
        ),
        OperatorConstants.Columns.DOC_ID_COLUMN: os.getenv(
            OperatorConstants.VectorDB.OPENSEARCH_DOC_ID_COLUMN, "doc_id_hash"
        ),
        OperatorConstants.Columns.EMBEDDINGS_COLUMN: os.getenv(
            OperatorConstants.VectorDB.OPENSEARCH_EMBEDDINGS_COLUMN, "embeddings"
        ),
        # Provider-specific parameters
        OperatorConstants.Config.PROVIDER_CONFIG: provider_config,
    }


def get_milvus_config() -> dict:
    """
    Load Milvus configuration from environment variables.

    Returns:
        dict: Configuration dictionary with all Milvus settings using provider_config pattern.
              All provider-specific parameters (including connection settings) are in provider_config.
    """

    def str_to_bool(value: str) -> bool:
        """Convert string to boolean."""
        return value.lower() in ("true", "1", "yes", "on")

    # All Milvus-specific parameters go in provider_config
    provider_config: dict[str, str | bool | int] = {
        # Authentication type (required)
        OperatorConstants.VectorDB.AUTH_TYPE: os.getenv(OperatorConstants.VectorDB.MILVUS_AUTH_TYPE, "standalone"),
        # Connection settings
        OperatorConstants.VectorDB.HOST: os.getenv(OperatorConstants.VectorDB.MILVUS_HOST, "localhost"),
        OperatorConstants.VectorDB.PORT: int(os.getenv(OperatorConstants.VectorDB.MILVUS_PORT, "19530")),
        # Database configuration
        OperatorConstants.VectorDB.DATABASE: os.getenv(OperatorConstants.VectorDB.MILVUS_DATABASE, "default"),
        # Index configuration
        OperatorConstants.VectorDB.INDEX_TYPE: os.getenv(OperatorConstants.VectorDB.MILVUS_INDEX_TYPE, "HNSW"),
        OperatorConstants.VectorDB.METRIC_TYPE: os.getenv(OperatorConstants.VectorDB.MILVUS_METRIC_TYPE, "L2"),
        # Performance settings
        OperatorConstants.Config.BATCH_SIZE: int(os.getenv(OperatorConstants.VectorDB.MILVUS_BATCH_SIZE, "100")),
    }

    # Add URI if configured (for wx.data or cloud deployments)
    uri = os.getenv(OperatorConstants.VectorDB.MILVUS_URI)
    if uri:
        provider_config[OperatorConstants.VectorDB.URI] = uri

    # Add authentication if configured
    username = os.getenv(OperatorConstants.VectorDB.MILVUS_USERNAME)
    if username:
        provider_config[OperatorConstants.VectorDB.USERNAME] = username

    password = os.getenv(OperatorConstants.VectorDB.MILVUS_PASSWORD)
    if password:
        provider_config[OperatorConstants.VectorDB.PASSWORD] = password

    # Add token if configured (for wx.data)
    token = os.getenv(OperatorConstants.VectorDB.MILVUS_TOKEN)
    if token:
        provider_config[OperatorConstants.VectorDB.TOKEN] = token

    # Add SSL/TLS configuration
    ssl = os.getenv(OperatorConstants.VectorDB.MILVUS_SSL)
    if ssl:
        provider_config[OperatorConstants.VectorDB.SSL] = str_to_bool(ssl)

    ssl_certificate = os.getenv(OperatorConstants.VectorDB.MILVUS_SSL_CERTIFICATE)
    if ssl_certificate:
        provider_config[OperatorConstants.VectorDB.SSL_CERTIFICATE] = ssl_certificate

    # Add resource name into provider_config — each provider owns its resource key
    provider_config[OperatorConstants.VectorDB.COLLECTION_NAME] = os.getenv(
        OperatorConstants.VectorDB.MILVUS_COLLECTION_NAME, "docpipe_test"
    )

    return {
        # Vector dimension
        OperatorConstants.VectorDB.VECTOR_DIMENSION: int(
            os.getenv(OperatorConstants.VectorDB.MILVUS_VECTOR_DIMENSION, "384")
        ),
        OperatorConstants.Columns.DOC_ID_COLUMN: os.getenv(
            OperatorConstants.VectorDB.MILVUS_DOC_ID_COLUMN, "doc_id_hash"
        ),
        OperatorConstants.Columns.EMBEDDINGS_COLUMN: os.getenv(
            OperatorConstants.VectorDB.MILVUS_EMBEDDINGS_COLUMN, "embeddings"
        ),
        # Provider-specific parameters
        OperatorConstants.Config.PROVIDER_CONFIG: provider_config,
    }


def get_env_var(key: str, default: str | None = None) -> str | None:
    """
    Get environment variable value.

    Args:
        key: Environment variable key
        default: Default value if not found

    Returns:
        str: Environment variable value or default
    """
    return os.getenv(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """
    Get boolean environment variable value.

    Args:
        key: Environment variable key
        default: Default value if not found

    Returns:
        bool: Environment variable value as boolean
    """
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int = 0) -> int:
    """
    Get integer environment variable value.

    Args:
        key: Environment variable key
        default: Default value if not found

    Returns:
        int: Environment variable value as integer
    """
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
