#!/usr/bin/env python3
"""
Comprehensive unit tests for refactored EmbeddingsOperator using unified LLM adapters.

Tests cover:
- Initialization with litellm and watsonx providers
- Transform method with various scenarios
- Unified adapter integration
- Error handling
- Configuration validation
- Metadata validation
"""

import hashlib
from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.embeddings import EmbeddingsOperator
from docpipe.core.operators.functional.embeddings.adapters.outbound.factories.llm_adapter_factory import (
    LLMAdapterFactory,
)


# Test Fixtures
@pytest.fixture
def litellm_config():
    """Configuration for LiteLLM provider."""
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
    """Configuration for Watsonx provider."""
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
    data = {
        "id": ["doc1"],
        "name": ["Document 1"],
        "content": ["This is a test document with some content."],
    }
    return pa.table(data)


@pytest.fixture
def sample_table_multiple_docs():
    """PyArrow table with multiple documents."""
    data = {
        "id": ["doc1", "doc2", "doc3"],
        "name": ["Document 1", "Document 2", "Document 3"],
        "content": [
            "First document with short content.",
            "Second document with different content.",
            "Third document with unique text.",
        ],
    }
    return pa.table(data)


@pytest.fixture
def sample_table_empty():
    """Empty PyArrow table."""
    data: dict[str, list[str]] = {
        "id": [],
        "name": [],
        "content": [],
    }
    return pa.table(data)


@pytest.fixture
def mock_llm_adapter():
    """Mock LLM adapter for testing."""
    adapter = Mock()
    adapter.generate_embeddings_batch.return_value = [[0.1] * 384, [0.2] * 384, [0.3] * 384]
    adapter.get_embedding_dimension.return_value = 384
    adapter.get_embedding_batch_size.return_value = 32
    adapter.get_max_concurrent_requests.return_value = 1
    adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    return adapter


# Initialization Tests
class TestEmbeddingsOperatorInitialization:
    """Test operator initialization with unified adapters."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_init_with_litellm_provider(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test initialization with LiteLLM provider."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        assert operator.provider == "litellm"
        assert operator.model_id == "openai/text-embedding-3-small"
        assert operator.embeddings_column == "embeddings"
        mock_factory.assert_called_once_with(
            provider="litellm",
            model_id="openai/text-embedding-3-small",
            provider_config={"model_id": "openai/text-embedding-3-small", "api_key": "<test-api-key>"},
        )

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_init_with_watsonx_provider(self, mock_factory, watsonx_config, mock_llm_adapter):
        """Test initialization with Watsonx provider."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(watsonx_config)

        assert operator.provider == "watsonx"
        assert operator.model_id == "ibm/slate-125m-english-rtrvr"
        mock_factory.assert_called_once_with(
            provider="watsonx",
            model_id="ibm/slate-125m-english-rtrvr",
            provider_config={
                "model_id": "ibm/slate-125m-english-rtrvr",
                "api_key": "<test-api-key>",
                "api_base": "https://us-south.ml.cloud.ibm.com",
                "container_id": "test-project-id",
                "container_kind": "project",
            },
        )

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_init_with_default_values(self, mock_factory, mock_llm_adapter):
        """Test initialization with default values."""
        mock_factory.return_value = mock_llm_adapter

        config = {"provider_config": {"model_id": "text-embedding-3-small"}}
        operator = EmbeddingsOperator(config)

        assert operator.provider == "litellm"  # Default provider
        assert operator.model_id == "text-embedding-3-small"
        assert operator.embeddings_column == OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT

    def test_init_with_invalid_provider(self):
        """Test initialization with invalid provider."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        config = {
            "provider": "invalid_provider",
            "model_id": "test-model",
        }

        with pytest.raises(DocpipeException, match="Unsupported"):
            EmbeddingsOperator(config)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_get_required_features(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test get_required_features returns correct list."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        required = operator.get_required_features()

        assert len(required) == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_adapter_validation_called_on_init(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that validate() is called during operator initialization."""
        mock_llm_adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
        mock_factory.return_value = mock_llm_adapter

        _ = EmbeddingsOperator(litellm_config)

        # Verify adapter was created and validated
        mock_factory.assert_called_once()
        mock_llm_adapter.validate.assert_called_once()

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_adapter_validation_failure_raises_error(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that validation failures raise DocpipeException."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        mock_llm_adapter.validate.return_value = {"valid": False, "errors": ["API key is required"], "warnings": []}
        mock_factory.return_value = mock_llm_adapter

        with pytest.raises(DocpipeException, match="API key is required"):
            EmbeddingsOperator(litellm_config)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_adapter_validation_with_warnings(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that warnings don't block operator initialization."""
        mock_llm_adapter.validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": ["Consider setting api_base for better performance"],
        }
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        # Operator should be created successfully
        assert operator is not None


# Metadata Tests
class TestEmbeddingsOperatorMetadata:
    """Test operator metadata methods."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_get_metadata_structure(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test get_metadata returns correct structure."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        metadata = operator.get_metadata()

        assert isinstance(metadata, dict)
        assert OperatorConstants.Misc.CATEGORY in metadata
        assert OperatorConstants.Config.FEATURES in metadata
        assert OperatorConstants.Config.ATTRIBUTES in metadata
        assert OperatorConstants.Misc.IS_OPERATOR_AVAILABLE in metadata
        assert metadata[OperatorConstants.Misc.IS_OPERATOR_AVAILABLE] is True
        assert "provider" in metadata[OperatorConstants.Config.ATTRIBUTES]
        provider_attr = metadata[OperatorConstants.Config.ATTRIBUTES]["provider"]
        assert OperatorConstants.Config.VALID_VALUES in provider_attr
        assert set(provider_attr[OperatorConstants.Config.VALID_VALUES]) == set(LLMAdapterFactory.list_adapters())

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_get_metadata_features(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test metadata includes correct features."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        metadata = operator.get_metadata()

        features = metadata[OperatorConstants.Config.FEATURES]

        assert OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT in features

        # Check embeddings feature details
        embeddings_feature = features[OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT]
        assert embeddings_feature[OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB] is True
        assert embeddings_feature[OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB] is True
        assert embeddings_feature[OperatorConstants.Misc.TYPE] == OperatorConstants.Types.TYPE_VECTOR

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_includes_new_parameters(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test metadata includes new parameter names (provider, model_id in provider_config)."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        metadata = operator.get_metadata()

        attributes = metadata[OperatorConstants.Config.ATTRIBUTES]

        # Check new parameter names are present
        assert "provider" in attributes
        # model_id is nested in provider_config.providers.<provider>.properties
        assert "provider_config" in attributes
        assert "providers" in attributes["provider_config"]
        assert "model_id" in attributes["provider_config"]["providers"]["litellm"]["properties"]

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_label_is_generic(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that metadata label is generic (not provider-specific)."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        metadata = operator.get_metadata()

        assert metadata[OperatorConstants.Misc.LABEL] == "Embeddings"


# Validation Tests
class TestEmbeddingsOperatorValidation:
    """Test operator validation logic."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_valid_config(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation with valid configuration."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content"]

        operator.validate(errors, warnings, available_features)

        assert len(errors) == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_missing_both_content_and_chunked_content(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation with missing both content and chunked_content features."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []  # No content or chunked_content

        operator.validate(errors, warnings, available_features)

        assert len(errors) > 0
        error_msg = str(errors[0])
        assert "content" in error_msg.lower() or "chunked_content" in error_msg.lower()

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_with_chunked_content_only(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation passes with only chunked_content feature (no content)."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["chunked_content"]  # Only chunked_content

        operator.validate(errors, warnings, available_features)

        # Should not have errors since chunked_content is available
        assert len(errors) == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_with_content_only(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation passes with only content feature."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content"]  # Only content

        operator.validate(errors, warnings, available_features)

        # Should not have errors since content is available
        assert len(errors) == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_supported_providers(self, mock_factory, mock_llm_adapter):
        """Test validation accepts only litellm and watsonx providers."""
        mock_factory.return_value = mock_llm_adapter

        for provider in ["litellm", "watsonx"]:
            config = {
                "provider": provider,
                "provider_config": {
                    "model_id": "test-model",
                },
            }
            operator = EmbeddingsOperator(config)
            errors: list[str] = []
            warnings: list[str] = []

            operator.validate(errors, warnings, ["content"])

            # Should not have provider-related errors
            assert not any("provider" in err.lower() for err in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_missing_chunker_warning(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation warns when chunked_content feature is missing (no Chunker before Embeddings)."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content", "id", "name"]  # No chunked_content feature

        operator.validate(errors, warnings, available_features)

        # Should have no errors
        assert len(errors) == 0
        # Should have warning about missing Chunker
        assert len(warnings) > 0
        warning_msg = str(warnings[0])
        assert "chunker" in warning_msg.lower()

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_with_chunker_no_warning(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation passes without warning when chunked_content feature is present (Chunker before Embeddings)."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content", "id", "name", "chunked_content"]  # Has chunked_content

        operator.validate(errors, warnings, available_features)

        # Should have no errors
        assert len(errors) == 0
        # Should have no warnings about Chunker
        chunker_warnings = [w for w in warnings if "chunker" in str(w).lower()]
        assert len(chunker_warnings) == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_no_content_or_chunked_content_errors(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that an error is raised when neither content nor chunked_content is available."""
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, [])
        assert any("content" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_passes_with_content_column(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation passes when content column is available."""
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        content_errors = [e for e in errors if "requires either" in str(e)]
        assert content_errors == []

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_passes_with_chunked_content_column(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation passes when chunked_content column is available."""
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, [OperatorConstants.Columns.CHUNKED_CONTENT])
        content_errors = [e for e in errors if "requires either" in str(e)]
        assert content_errors == []

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_unsupported_provider(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when provider is not a supported value."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {**litellm_config, "provider": "not_a_real_provider"}
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("provider" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_invalid_overlap_ratio_type(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when overlap_ratio is not a float."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {**litellm_config, "overlap_ratio": "high"}
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("overlap_ratio" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_overlap_ratio_out_of_range(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when overlap_ratio is outside [0, 0.8]."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {**litellm_config, "overlap_ratio": 0.9}
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("overlap_ratio" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_invalid_token_limit(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when token_limit is negative."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {**litellm_config, "token_limit": -1}
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("token_limit" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_provider_config_missing_model_id(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when provider_config is missing model_id."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {**litellm_config, "provider_config": {"api_key": "x"}}
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("model_id" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_provider_config_invalid_max_concurrent_requests(
        self, mock_factory, litellm_config, mock_llm_adapter
    ):
        """Test validation error when max_concurrent_requests is negative."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {
            **litellm_config,
            "provider_config": {**litellm_config["provider_config"], "max_concurrent_requests": -5},
        }
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("max_concurrent_requests" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_provider_config_invalid_batch_size(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test validation error when batch_size is zero or negative."""
        mock_factory.return_value = mock_llm_adapter
        cfg = {
            **litellm_config,
            "provider_config": {**litellm_config["provider_config"], "batch_size": 0},
        }
        op = EmbeddingsOperator(cfg)
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert any("batch_size" in str(e) for e in errors)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_warns_when_chunked_content_absent(self, mock_factory, litellm_config, mock_llm_adapter):
        """A warning is issued when chunked_content is not in available_features."""
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
        assert len(warnings) >= 1

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_validate_no_chunked_content_warning_when_present(self, mock_factory, litellm_config, mock_llm_adapter):
        """No CHUNKER_OPERATOR_MISSING warning when chunked_content is in available_features."""
        from docpipe.exceptions.error_messages import ValidationCodeMessages

        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(
            errors,
            warnings,
            [OperatorConstants.Columns.DOC_COLUMN_DEFAULT, OperatorConstants.Columns.CHUNKED_CONTENT],
        )
        chunker_warnings = [w for w in warnings if w == ValidationCodeMessages.CHUNKER_OPERATOR_MISSING]
        assert chunker_warnings == []


# Transform Method Tests
class TestEmbeddingsOperatorTransform:
    """Test the transform method with unified adapters."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_single_document(self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc):
        """Test transform with a single document."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_single_doc)

        assert len(result_tables) == 1
        result_table = result_tables[0]

        # Check embeddings column was added
        assert "embeddings" in result_table.column_names
        assert result_table.num_rows == 1

        # Check metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == 1
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        # Verify adapter was called with keyword arguments
        mock_llm_adapter.generate_embeddings_batch.assert_called()
        call_args = mock_llm_adapter.generate_embeddings_batch.call_args
        assert "texts" in call_args.kwargs

    @patch("docpipe.core.operators.functional.doc_id_hash.DocIdHashOperator.transform")
    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_multiple_documents(
        self, mock_factory, mock_doc_hash_transform, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test transform with multiple documents."""

        # Mock the embedding adapter to return embeddings for each text
        def mock_batch_embeddings(texts):
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        # Mock DocIdHashOperator to add doc_id_hash column
        table_with_hash = sample_table_multiple_docs.append_column("doc_id_hash", pa.array(["hash1", "hash2", "hash3"]))
        mock_doc_hash_transform.return_value = ([table_with_hash], {})

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_multiple_docs)

        result_table = result_tables[0]

        # Check all documents were processed
        assert result_table.num_rows == 3
        assert "embeddings" in result_table.column_names

        # Check metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == 3
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_with_watsonx_provider(
        self, mock_factory, watsonx_config, mock_llm_adapter, sample_table_single_doc
    ):
        """Test transform with Watsonx provider."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 768]
        mock_llm_adapter.get_embedding_dimension.return_value = 768
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(watsonx_config)
        result_tables, metadata = operator.transform(sample_table_single_doc)

        result_table = result_tables[0]

        # Check embeddings were generated
        assert result_table.num_rows == 1
        assert "embeddings" in result_table.column_names
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_empty_table(self, mock_factory, litellm_config, mock_llm_adapter, sample_table_empty):
        """Test transform with an empty table."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_empty)

        result_table = result_tables[0]

        # Should handle empty table gracefully
        assert result_table.num_rows == 0
        assert metadata[Metrics.External.TOTAL_DOCS] == 0
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_missing_content_column(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test transform with missing content column."""
        mock_factory.return_value = mock_llm_adapter

        # Create table without content column
        data = {
            "id": ["doc1"],
            "name": ["Document 1"],
        }
        table = pa.table(data)

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(table)

        result_table = result_tables[0]

        # Document should fail and be removed
        assert result_table.num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_transform_preserves_existing_columns(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that transform preserves existing columns."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        # Create table with extra columns
        data = {
            "id": ["doc1"],
            "name": ["Document 1"],
            "content": ["Test content"],
            "extra_column": ["extra_value"],
        }
        table = pa.table(data)

        operator = EmbeddingsOperator(litellm_config)
        result_tables, _metadata = operator.transform(table)

        result_table = result_tables[0]

        # Check all original columns are preserved
        assert "id" in result_table.column_names
        assert "name" in result_table.column_names
        assert "content" in result_table.column_names
        assert "extra_column" in result_table.column_names
        assert "embeddings" in result_table.column_names


# Document Hash Tests
class TestEmbeddingsDocumentHash:
    """Test document hash generation and preservation."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_automatic_hash_generation(self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc):
        """Test automatic hash generation when missing."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, _metadata = operator.transform(sample_table_single_doc)

        result_table = result_tables[0]

        # Check hash column was added
        assert "doc_id_hash" in result_table.column_names
        doc_hash = result_table["doc_id_hash"][0].as_py()
        assert doc_hash is not None
        assert len(doc_hash) == 64  # SHA-256 hash length

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_hash_preservation_when_present(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test hash preservation when already present."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        # Create table with existing hash
        existing_hash = "existing_hash_value_123"
        data = {
            "id": ["doc1"],
            "name": ["Document 1"],
            "content": ["Test content"],
            "doc_id_hash": [existing_hash],
        }
        table = pa.table(data)

        operator = EmbeddingsOperator(litellm_config)
        result_tables, _metadata = operator.transform(table)

        result_table = result_tables[0]

        # Hash should be preserved
        doc_hash = result_table["doc_id_hash"][0].as_py()
        assert doc_hash == existing_hash

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_generate_document_hash_consistency(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that hash generation is consistent for same content."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        content = "Test document content"
        hash1 = operator._generate_document_hash(content)
        hash2 = operator._generate_document_hash(content)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hash length

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_generate_document_hash_different_content(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test that different content produces different hashes."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        hash1 = operator._generate_document_hash("Content 1")
        hash2 = operator._generate_document_hash("Content 2")

        assert hash1 != hash2


class TestEmbeddingsStaticMethods:
    """Verify _generate_document_hash is a pure static helper."""

    def test_generate_document_hash_is_static(self):
        """The hash helper must be a staticmethod (no instance state needed)."""
        import inspect

        assert isinstance(inspect.getattr_static(EmbeddingsOperator, "_generate_document_hash"), staticmethod)

    def test_generate_document_hash_class_call(self):
        """Static call produces the known SHA-256 hex digest without an instance."""
        expected = hashlib.sha256(b"Test document content").hexdigest()

        assert EmbeddingsOperator._generate_document_hash("Test document content") == expected
        assert len(expected) == 64


# Error Handling Tests
class TestEmbeddingsErrorHandling:
    """Test error handling with unified adapters."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_adapter_error_handling(self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc):
        """Test handling of adapter errors."""
        mock_llm_adapter.generate_embeddings_batch.side_effect = Exception("API error")
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_single_doc)

        result_table = result_tables[0]

        # Document should fail and be removed
        assert result_table.num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_per_document_error_tracking(
        self, mock_factory, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test per-document error tracking."""
        # Make second document fail
        # One text per request so each provider call carries exactly one document
        mock_llm_adapter.get_embedding_batch_size.return_value = 1
        call_count = [0]

        def mock_batch_embeddings(texts):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Processing error")
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_multiple_docs)

        result_table = result_tables[0]

        # Two documents should succeed, one should fail
        assert result_table.num_rows == 2
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert len(metadata[Metrics.External.FAILED_DOCS]) == 1

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_graceful_failure_continues_processing(
        self, mock_factory, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test that processing continues after individual document failures."""
        # Make first document fail, others succeed
        # One text per request so each provider call carries exactly one document
        mock_llm_adapter.get_embedding_batch_size.return_value = 1
        call_count = [0]

        def mock_batch_embeddings(texts):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("First document error")
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(sample_table_multiple_docs)

        result_table = result_tables[0]

        # Should process remaining documents
        assert result_table.num_rows == 2
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1


# Metadata Validation Tests
class TestEmbeddingsMetadataValidation:
    """Test metadata structure and content validation."""

    @patch("docpipe.core.operators.functional.doc_id_hash.DocIdHashOperator.transform")
    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_includes_processed_docs_count(
        self, mock_factory, mock_doc_hash_transform, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test metadata includes processed_docs count."""

        # Mock the embedding adapter to return embeddings for each text
        def mock_batch_embeddings(texts):
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        # Mock DocIdHashOperator
        table_with_hash = sample_table_multiple_docs.append_column("doc_id_hash", pa.array(["hash1", "hash2", "hash3"]))
        mock_doc_hash_transform.return_value = ([table_with_hash], {})

        operator = EmbeddingsOperator(litellm_config)
        _result_tables, metadata = operator.transform(sample_table_multiple_docs)

        assert Metrics.External.PROCESSED_DOCS in metadata
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_includes_failed_docs_count(
        self, mock_factory, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test metadata includes failed_docs count."""
        # Make one document fail
        # One text per request so each provider call carries exactly one document
        mock_llm_adapter.get_embedding_batch_size.return_value = 1
        call_count = [0]

        def mock_batch_embeddings(texts):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Error")
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        _result_tables, metadata = operator.transform(sample_table_multiple_docs)

        assert Metrics.External.FAILED_DOCS_COUNT in metadata
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_includes_node_status(
        self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc
    ):
        """Test metadata includes node_status."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        _result_tables, metadata = operator.transform(sample_table_single_doc)

        assert Metrics.External.NODE_STATUS in metadata
        # Should be Completed when all succeed
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_node_status_with_errors(
        self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc
    ):
        """Test node_status is COMPLETED_WITH_ERRORS when failures occur."""
        mock_llm_adapter.generate_embeddings_batch.side_effect = Exception("Error")
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        _result_tables, metadata = operator.transform(sample_table_single_doc)

        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_metadata_completeness(self, mock_factory, litellm_config, mock_llm_adapter, sample_table_single_doc):
        """Test that all required metadata fields are present."""
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)
        _result_tables, metadata = operator.transform(sample_table_single_doc)

        # Check all required fields
        required_fields = [
            Metrics.External.TOTAL_DOCS,
            Metrics.External.PROCESSED_DOCS,
            Metrics.External.FAILED_DOCS_COUNT,
            Metrics.External.FAILED_DOCS,
            Metrics.External.NODE_STATUS,
        ]

        for field in required_fields:
            assert field in metadata, f"Missing required metadata field: {field}"


# Integration Tests
class TestEmbeddingsOperatorIntegration:
    """Integration-style tests combining multiple features."""

    @patch("docpipe.core.operators.functional.doc_id_hash.DocIdHashOperator.transform")
    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_full_pipeline_with_hash_and_embeddings(
        self, mock_factory, mock_doc_hash_transform, litellm_config, mock_llm_adapter, sample_table_multiple_docs
    ):
        """Test full pipeline: generate embeddings and hashes."""

        # Mock the embedding adapter to return embeddings for each text
        def mock_batch_embeddings(texts):
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        # Mock DocIdHashOperator
        table_with_hash = sample_table_multiple_docs.append_column("doc_id_hash", pa.array(["hash1", "hash2", "hash3"]))
        mock_doc_hash_transform.return_value = ([table_with_hash], {})

        operator = EmbeddingsOperator(litellm_config)
        result_tables, _metadata = operator.transform(sample_table_multiple_docs)

        result_table = result_tables[0]

        # Check both embeddings and hashes were added
        assert "embeddings" in result_table.column_names
        assert "doc_id_hash" in result_table.column_names

        # Verify all rows have both
        for i in range(result_table.num_rows):
            assert result_table["embeddings"][i].as_py() is not None
            assert result_table["doc_id_hash"][i].as_py() is not None

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_mixed_success_and_failure_documents(self, mock_factory, litellm_config, mock_llm_adapter):
        """Test processing with mix of successful and failed documents."""
        # Make every other document fail
        # One text per request so each provider call carries exactly one document
        mock_llm_adapter.get_embedding_batch_size.return_value = 1
        call_count = [0]

        def mock_batch_embeddings(texts):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise Exception("Error")
            return [[0.1] * 384] * len(texts)

        mock_llm_adapter.generate_embeddings_batch.side_effect = mock_batch_embeddings
        mock_factory.return_value = mock_llm_adapter

        # Create table with 4 documents
        data = {
            "id": [f"doc{i}" for i in range(4)],
            "name": [f"Document {i}" for i in range(4)],
            "content": [f"Content {i}" for i in range(4)],
        }
        table = pa.table(data)

        operator = EmbeddingsOperator(litellm_config)
        result_tables, metadata = operator.transform(table)

        result_table = result_tables[0]

        # Should have 2 successful, 2 failed
        assert result_table.num_rows == 2
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2


class TestEmbeddingsOperatorDimAndCaching:
    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_doc_id_op_is_cached_at_init(self, mock_factory, litellm_config, mock_llm_adapter):
        """_doc_id_op must be set on the instance during __init__, not lazily in transform()."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        assert hasattr(operator, "_doc_id_op"), "_doc_id_op should be set in __init__"
        from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator

        assert isinstance(operator._doc_id_op, DocIdHashOperator)

    @patch("docpipe.core.operators.functional.doc_id_hash.DocIdHashOperator.__init__")
    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_doc_id_op_instantiated_once_across_multiple_transforms(
        self, mock_factory, mock_doc_id_init, litellm_config, mock_llm_adapter
    ):
        """DocIdHashOperator.__init__ must be called exactly once (at operator init),
        not on every transform() call."""
        mock_doc_id_init.return_value = None  # __init__ returns None
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        # __init__ called once during EmbeddingsOperator.__init__
        assert mock_doc_id_init.call_count == 1

        # Patch transform on the cached instance to avoid real execution
        with patch.object(operator._doc_id_op, "transform") as mock_transform:
            table_with_hash = pa.table(
                {
                    "id": ["doc1"],
                    "name": ["Document 1"],
                    "content": ["Test content"],
                    "doc_id_hash": ["hash1"],
                }
            )
            mock_transform.return_value = ([table_with_hash], {})
            mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * 384]

            table_without_hash = pa.table(
                {
                    "id": ["doc1"],
                    "name": ["Document 1"],
                    "content": ["Test content"],
                }
            )

            operator.transform(table_without_hash)
            operator.transform(table_without_hash)

        # __init__ must still be exactly 1 — not called again per transform
        assert mock_doc_id_init.call_count == 1

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_embedding_dim_cached_after_first_successful_call(self, mock_factory, litellm_config, mock_llm_adapter):
        """_embedding_dim starts as None and is set after the first successful embedding."""
        mock_factory.return_value = mock_llm_adapter

        operator = EmbeddingsOperator(litellm_config)

        assert operator._embedding_dim is None, "_embedding_dim should be None before any embedding call"

        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.5] * 768]

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["Document 1"],
                "content": ["Some text"],
                "doc_id_hash": ["hash1"],
            }
        )
        operator.transform(table)

        assert operator._embedding_dim == 768, "_embedding_dim should reflect the model's actual output dimension"

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_zero_vector_uses_model_dimension_not_hardcoded_384(self, mock_factory, litellm_config, mock_llm_adapter):
        """Empty-text zero-vector inside _embed_documents must use the model's actual output dimension.

        The zero-vector path is reached when a text entry is empty/whitespace inside the
        text list passed to _embed_documents (not at the document level).  We test
        _embed_documents directly so we can control which slot is empty.
        """
        mock_factory.return_value = mock_llm_adapter

        # Simulate a 1536-d model (e.g. text-embedding-3-large)
        model_dim = 1536
        # Only the non-empty text produces an embedding
        mock_llm_adapter.generate_embeddings_batch.return_value = [[0.1] * model_dim]

        operator = EmbeddingsOperator(litellm_config)
        # Pre-seed the dimension as if a prior call already established it
        operator._embedding_dim = model_dim

        # Pass two texts: one real, one whitespace-only (triggers the zero-vector branch)
        result = operator._embed_documents(texts_per_doc=[["Real content", "   "]])[0]

        assert len(result) == 2
        zero_vec = result[1]
        assert len(zero_vec) == model_dim, (
            f"Zero-vector should be {model_dim}-d (matching model output), got {len(zero_vec)}-d"
        )
        assert all(v == 0.0 for v in zero_vec)

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_zero_vector_falls_back_to_384_when_no_successful_embedding(
        self, mock_factory, litellm_config, mock_llm_adapter
    ):
        """When _embedding_dim has not been set yet, zero-vector falls back to dimension 384."""
        mock_factory.return_value = mock_llm_adapter
        # No embeddings returned — nothing to seed _embedding_dim from
        mock_llm_adapter.generate_embeddings_batch.return_value = []

        operator = EmbeddingsOperator(litellm_config)
        assert operator._embedding_dim is None

        # All-whitespace list: every entry hits the zero-vector branch, nothing seeds _embedding_dim
        result = operator._embed_documents(texts_per_doc=[["   "]])[0]

        assert len(result) == 1
        assert len(result[0]) == 384, "Should fall back to 384 when no model dimension is known yet"
        assert all(v == 0.0 for v in result[0])


class TestEmbeddingsProviderSchemas:
    """Tests for _get_embeddings_provider_schemas."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_returns_litellm_and_watsonx(self, mock_factory, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        schemas = EmbeddingsOperator._get_embeddings_provider_schemas()
        assert "litellm" in schemas
        assert "watsonx" in schemas

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_schemas_contain_properties(self, mock_factory, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        schemas = EmbeddingsOperator._get_embeddings_provider_schemas()
        for name, schema in schemas.items():
            assert "properties" in schema, f"Schema for {name} missing 'properties'"

    @pytest.mark.parametrize(
        ("provider", "batch_size", "max_concurrent_requests"),
        [("litellm", 32, 4), ("watsonx", 800, 1)],
    )
    def test_metadata_exposes_request_shaping_options(self, provider, batch_size, max_concurrent_requests):
        providers = EmbeddingsOperator.get_metadata()["attributes"]["provider_config"]["providers"]
        properties = providers[provider]["properties"]

        assert properties["batch_size"]["default"] == batch_size
        assert properties["batch_size"]["min_value"] == 1
        assert properties["batch_size"]["type"] == "int64"
        assert properties["max_concurrent_requests"]["default"] == max_concurrent_requests
        assert properties["max_concurrent_requests"]["min_value"] == 1
        assert properties["max_concurrent_requests"]["type"] == "int64"
        assert "model_id" in properties

    @pytest.mark.parametrize(
        ("provider", "batch_size", "max_concurrent_requests"),
        [("litellm", 32, 4), ("watsonx", 800, 1)],
    )
    def test_schema_defaults_match_factory_defaults(self, provider, batch_size, max_concurrent_requests):
        from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory

        with (
            patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as litellm_client,
            patch("docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"),
        ):
            litellm_client.return_value.batch_size = 32
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider=provider, model_id="m", provider_config={"api_key": "k"}
            )

        assert adapter.get_embedding_batch_size() == batch_size
        assert adapter.get_max_concurrent_requests() == max_concurrent_requests

    def test_shared_inference_schemas_do_not_offer_embedding_options(self):
        from docpipe.core.operators.shared.llm_provider_config import LLMProviderConfig, WatsonxProviderConfig

        for config_cls in (LLMProviderConfig, WatsonxProviderConfig):
            properties = config_cls.model_json_schema()["properties"]
            assert "batch_size" not in properties
            assert "max_concurrent_requests" not in properties

    @pytest.mark.parametrize("bad_value", [0, -1])
    def test_embedding_schemas_reject_non_positive_values(self, bad_value):
        from pydantic import ValidationError

        from docpipe.core.operators.shared.llm_provider_config import (
            LLMEmbeddingProviderConfig,
            WatsonxEmbeddingProviderConfig,
        )

        for config_cls in (LLMEmbeddingProviderConfig, WatsonxEmbeddingProviderConfig):
            with pytest.raises(ValidationError):
                config_cls(batch_size=bad_value)
            with pytest.raises(ValidationError):
                config_cls(max_concurrent_requests=bad_value)


class TestEmbeddingsParseChunkedContent:
    """Tests for _parse_chunked_content edge cases."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_parse_list_of_dicts(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        table = pa.table(
            {
                "id": ["d1"],
                "name": ["doc"],
                "content": ["text"],
                "doc_id_hash": ["h1"],
                "chunked_content": [[{"chunk": "hello", "start_index": 0}]],
            }
        )
        texts = operator._parse_chunked_content(table, 0, "doc")
        assert texts == ["hello"]

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_parse_list_of_strings(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        table = pa.table(
            {
                "id": ["d1"],
                "name": ["doc"],
                "content": ["text"],
                "doc_id_hash": ["h1"],
                "chunked_content": [["chunk one", "chunk two"]],
            }
        )
        texts = operator._parse_chunked_content(table, 0, "doc")
        assert texts == ["chunk one", "chunk two"]

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_parse_json_string(self, mock_factory, litellm_config, mock_llm_adapter):
        import json as _json

        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        chunks_json = _json.dumps([{"chunk": "parsed chunk", "start_index": 0}])
        table = pa.table(
            {
                "id": ["d1"],
                "name": ["doc"],
                "content": ["text"],
                "doc_id_hash": ["h1"],
                "chunked_content": [chunks_json],
            }
        )
        texts = operator._parse_chunked_content(table, 0, "doc")
        assert texts == ["parsed chunk"]

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_parse_empty_raises_docpipe_exception(self, mock_factory, litellm_config, mock_llm_adapter):
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        mock_factory.return_value = mock_llm_adapter
        operator = EmbeddingsOperator(litellm_config)
        table = pa.table(
            {
                "id": ["d1"],
                "name": ["doc"],
                "content": ["text"],
                "doc_id_hash": ["h1"],
                "chunked_content": [None],
            }
        )
        with pytest.raises(DocpipeException):
            operator._parse_chunked_content(table, 0, "doc")


class TestEmbeddingsBuildChunkText:
    """Tests for _build_chunk_text_for_embedding."""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_with_summary_prepends_abstract(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        _ = EmbeddingsOperator(litellm_config)
        chunk = {"chunk": "body text", "summary": "summary text"}
        result = EmbeddingsOperator._build_chunk_text_for_embedding(chunk=chunk)
        assert result.startswith("abstract: summary text")
        assert "content: body text" in result

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_without_summary_returns_chunk_text(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        _ = EmbeddingsOperator(litellm_config)
        chunk = {"chunk": "body text"}
        result = EmbeddingsOperator._build_chunk_text_for_embedding(chunk=chunk)
        assert result == "body text"

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_empty_chunk_returns_empty_string(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        result = EmbeddingsOperator._build_chunk_text_for_embedding(chunk={"chunk": ""})
        assert result == ""

    @patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter")
    def test_build_chunk_text_preserves_content_as_is(self, mock_factory, litellm_config, mock_llm_adapter):
        mock_factory.return_value = mock_llm_adapter
        chunk = {"chunk": "Clean Content with <tag>"}
        result = EmbeddingsOperator._build_chunk_text_for_embedding(chunk=chunk)
        assert result == "Clean Content with <tag>"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
