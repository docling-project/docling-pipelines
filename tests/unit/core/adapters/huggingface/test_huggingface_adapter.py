"""Tests for the HuggingFace embedding adapter."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters.huggingface import HuggingFaceAdapter
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort

_HF_CLIENT = "docpipe.core.adapters.huggingface.huggingface_adapter.HuggingFaceLLMClient"
_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class TestHuggingFaceAdapter:
    """Test suite for HuggingFaceAdapter delegation to HuggingFaceLLMClient."""

    @pytest.fixture
    def mock_client_class(self):
        """Patch the HuggingFace client class used by the adapter."""
        with patch(_HF_CLIENT) as client_cls:
            client_cls.return_value = Mock()
            yield client_cls

    @pytest.fixture
    def adapter(self, mock_client_class):
        """Create a HuggingFace adapter backed by a mock client."""
        return HuggingFaceAdapter(model_name=_MODEL, use_local=True, device="cpu", batch_size=8)

    def test_implements_embedding_port(self, adapter):
        """Adapter implements the LLMEmbeddingPort interface."""
        assert isinstance(adapter, LLMEmbeddingPort)

    def test_client_initialization_parameters(self, mock_client_class):
        """Constructor forwards all options (including extra kwargs) to the client."""
        HuggingFaceAdapter(
            model_name=_MODEL,
            use_local=False,
            api_token="hf-test-token",  # pragma: allowlist secret
            device="cuda",
            batch_size=4,
            normalize=True,
        )

        mock_client_class.assert_called_once_with(
            model_name=_MODEL,
            use_local=False,
            api_token="hf-test-token",  # pragma: allowlist secret
            device="cuda",
            batch_size=4,
            normalize=True,
        )

    def test_generate_embeddings_delegates_to_client(self, adapter, mock_client_class):
        """Single-text embedding is delegated to the client and its result returned."""
        client = mock_client_class.return_value
        client.generate_embeddings.return_value = [0.1, 0.2, 0.3]

        result = adapter.generate_embeddings(text="hello")

        assert result == [0.1, 0.2, 0.3]
        client.generate_embeddings.assert_called_once_with("hello")

    def test_generate_embeddings_batch_delegates_to_client(self, adapter, mock_client_class):
        """Batch embedding is delegated to the client and its result returned."""
        client = mock_client_class.return_value
        client.generate_embeddings_batch.return_value = [[0.1], [0.2]]

        result = adapter.generate_embeddings_batch(texts=["a", "b"])

        assert result == [[0.1], [0.2]]
        client.generate_embeddings_batch.assert_called_once_with(["a", "b"])

    def test_generate_embeddings_propagates_client_errors(self, adapter, mock_client_class):
        """Client errors are not swallowed by the adapter."""
        mock_client_class.return_value.generate_embeddings.side_effect = RuntimeError("model failure")

        with pytest.raises(RuntimeError, match="model failure"):
            adapter.generate_embeddings(text="hello")

    def test_get_embedding_batch_size_reads_client(self, adapter, mock_client_class):
        """Batch size reported by the adapter comes from the client."""
        mock_client_class.return_value.batch_size = 8

        assert adapter.get_embedding_batch_size() == 8

    def test_get_max_concurrent_requests_defaults_to_one(self, adapter):
        """Local inference keeps the port default of a single in-flight request."""
        assert adapter.get_max_concurrent_requests() == 1

    def test_get_embedding_dimension_uses_static_lookup(self, adapter, mock_client_class):
        """Dimension lookup uses the client's static helper with the adapter's model name."""
        mock_client_class.get_embedding_dimension.return_value = 384

        assert adapter.get_embedding_dimension() == 384
        mock_client_class.get_embedding_dimension.assert_called_once_with(_MODEL)

    def test_validate_embedding_valid_when_client_present(self, adapter):
        """Validation passes when the client has been initialized."""
        result = adapter.validate_embedding()

        assert result == {"valid": True, "context": "embedding"}

    def test_validate_embedding_invalid_when_client_missing(self, adapter):
        """Validation fails when the client is missing."""
        adapter.client = None

        result = adapter.validate_embedding()

        assert result == {"valid": False, "context": "embedding"}
