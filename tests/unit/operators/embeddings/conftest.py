"""Shared fixtures for EmbeddingsOperator tests."""

from unittest.mock import Mock

import pyarrow as pa
import pytest

_ADAPTER_FACTORY_PATH = "docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter"


@pytest.fixture
def mock_llm_adapter():
    """Mock LLM embedding adapter with sane defaults."""
    adapter = Mock()
    adapter.generate_embeddings_batch.return_value = [[0.1] * 384, [0.2] * 384, [0.3] * 384]
    adapter.get_embedding_dimension.return_value = 384
    adapter.get_embedding_batch_size.return_value = 32
    adapter.get_max_concurrent_requests.return_value = 1
    adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    return adapter


@pytest.fixture
def litellm_config():
    """Minimal LiteLLM provider configuration."""
    return {
        "provider": "litellm",
        "embeddings_column": "embeddings",
        "provider_config": {
            "model_id": "openai/text-embedding-3-small",
            "api_key": "<test-api-key>",
        },
    }


@pytest.fixture
def watsonx_config():
    """Minimal Watsonx provider configuration."""
    return {
        "provider": "watsonx",
        "embeddings_column": "embeddings",
        "provider_config": {
            "model_id": "ibm/slate-125m-english-rtrvr",
            "api_key": "<test-api-key>",
            "api_base": "https://us-south.ml.cloud.ibm.com",
            "container_id": "test-project-id",
            "container_kind": "project",
        },
    }


@pytest.fixture
def sample_table_single_doc():
    """PyArrow table with a single document."""
    return pa.table(
        {
            "id": ["doc1"],
            "name": ["Document 1"],
            "content": ["This is a test document with some content."],
        }
    )


@pytest.fixture
def sample_table_multiple_docs():
    """PyArrow table with three documents."""
    return pa.table(
        {
            "id": ["doc1", "doc2", "doc3"],
            "name": ["Document 1", "Document 2", "Document 3"],
            "content": [
                "First document with short content.",
                "Second document with different content.",
                "Third document with unique text.",
            ],
        }
    )


@pytest.fixture
def sample_table_empty():
    """Empty PyArrow table with the standard schema."""
    return pa.table({"id": [], "name": [], "content": []})
