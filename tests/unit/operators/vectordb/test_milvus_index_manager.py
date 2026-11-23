#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for MilvusIndexManager
"""

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pyarrow as pa
import pytest

from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import (
    INDEX_DEFAULT_PARAMETERS,
    MilvusIndexManager,
    MilvusIndexTypes,
    MilvusMetricTypes,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException


@pytest.fixture
def mock_client():
    """Mock Milvus client"""
    client = MagicMock()
    client.has_collection.return_value = False
    return client


@pytest.fixture
def basic_features():
    """Basic feature configuration"""
    return {
        "doc_id": {
            "name": "Document ID",
            "available_for_vector_db": True,
            "type": "string",
            "is_primary": True,
        },
        "content": {
            "name": "Content",
            "available_for_vector_db": True,
            "type": "string",
        },
        "embeddings": {
            "name": "Embeddings",
            "available_for_vector_db": True,
            "type": "vector",
        },
    }


@pytest.fixture
def feature_mappings():
    """Feature mappings"""
    return [
        {"feature_name": "doc_id", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
    ]


class TestIndexManagerInitialization:
    """Test index manager initialization"""

    def test_basic_initialization(self, mock_client):
        """Test basic initialization with default parameters"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
        )

        assert manager.client == mock_client
        assert manager.collection_name == "test_collection"
        assert manager.index_type == "HNSW"
        assert manager.metric_type == "L2"
        assert manager.primary_key_field == "pk"
        assert manager.auto_id is False

    def test_initialization_with_custom_parameters(self, mock_client):
        """Test initialization with custom parameters"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="custom_collection",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            primary_key_field="id",
            auto_id=True,
        )

        assert manager.collection_name == "custom_collection"
        assert manager.index_type == "IVF_FLAT"
        assert manager.metric_type == "COSINE"
        assert manager.primary_key_field == "id"
        assert manager.auto_id is True

    def test_initialization_with_features(self, mock_client, basic_features, feature_mappings):
        """Test initialization with feature configuration"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
        )

        assert manager.available_features == basic_features
        assert manager.feature_mappings == feature_mappings

    def test_initialization_with_custom_index_parameters(self, mock_client):
        """Test initialization with custom index parameters"""
        custom_params = {"M": 32, "efConstruction": 400}
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="HNSW",
            index_parameters=custom_params,
        )

        assert manager.index_parameters == custom_params

    def test_invalid_index_type(self, mock_client):
        """Test initialization with invalid index type"""
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_collection",
                index_type="INVALID_TYPE",
            )

        assert "Invalid index type" in str(exc_info.value)
        assert "INVALID_TYPE" in str(exc_info.value)

    def test_invalid_metric_type(self, mock_client):
        """Test initialization with invalid metric type"""
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_collection",
                metric_type="INVALID_METRIC",
            )

        assert "Invalid metric type" in str(exc_info.value)
        assert "INVALID_METRIC" in str(exc_info.value)


class TestIndexParameters:
    """Test index parameter handling"""

    def test_get_default_hnsw_parameters(self, mock_client):
        """Test getting default HNSW parameters"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="HNSW",
        )

        params = manager._get_index_parameters()
        assert params == {"M": 16, "efConstruction": 200}

    def test_get_default_ivf_flat_parameters(self, mock_client):
        """Test getting default IVF_FLAT parameters"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="IVF_FLAT",
        )

        params = manager._get_index_parameters()
        assert params == {"nlist": 128}

    def test_get_default_flat_parameters(self, mock_client):
        """Test getting default FLAT parameters"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="FLAT",
        )

        params = manager._get_index_parameters()
        assert params == {}

    def test_custom_parameters_override_defaults(self, mock_client):
        """Test that custom parameters override defaults"""
        custom_params = {"M": 32, "efConstruction": 400}
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="HNSW",
            index_parameters=custom_params,
        )

        params = manager._get_index_parameters()
        assert params == {"M": 32, "efConstruction": 400}

    def test_partial_custom_parameters_merge(self, mock_client):
        """Test that partial custom parameters merge with defaults"""
        custom_params = {"M": 32}
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            index_type="HNSW",
            index_parameters=custom_params,
        )

        params = manager._get_index_parameters()
        assert params == {"M": 32, "efConstruction": 200}


class TestCollectionValidation:
    """Test collection validation"""

    def test_collection_exists_check(self, mock_client):
        """Test checking if collection exists"""
        mock_client.has_collection.return_value = True
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="existing_collection",
        )

        exists = manager.collection_exists()
        assert exists is True
        mock_client.has_collection.assert_called_once_with(collection_name="existing_collection")

    def test_collection_not_exists(self, mock_client):
        """Test checking if collection does not exist"""
        mock_client.has_collection.return_value = False
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="new_collection",
        )

        exists = manager.collection_exists()
        assert exists is False

    def test_validate_existing_collection_matching_dimension(self, mock_client):
        """Test validation passes when existing collection dimensions match."""
        mock_client.describe_collection.return_value = {
            "fields": [
                {"name": "vector_embeddings", "params": {"dim": 384}},
            ]
        }
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="existing_collection",
            feature_mappings=[{"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}],
        )

        manager.validate_existing_collection(dimension_mapping={"embeddings": 384})

    def test_validate_existing_collection_dimension_mismatch(self, mock_client):
        """Test validation fails when existing collection dimensions differ."""
        mock_client.describe_collection.return_value = {
            "fields": [
                {"name": "vector_embeddings", "params": {"dim": 768}},
            ]
        }
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="existing_collection",
            feature_mappings=[{"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}],
        )

        with pytest.raises(DocpipeException, match="existing dimension 768 but current run produced 384"):
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})

    def test_validate_existing_binary_collection_matches_bit_dimension(self, mock_client):
        """A binary field stores its dimension in bits; the runtime bit count must match it."""
        mock_client.describe_collection.return_value = {
            "fields": [{"name": "binary_vec", "type": "BINARY_VECTOR", "params": {"dim": 256}}]
        }
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="existing_binary_collection",
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            available_features={"binary_embeddings": {"type": "vector_binary"}},
            feature_mappings=[{"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"}],
        )

        manager.validate_existing_collection(dimension_mapping={"binary_embeddings": 256})
        with pytest.raises(DocpipeException, match="existing dimension 256 but current run produced 32"):
            manager.validate_existing_collection(dimension_mapping={"binary_embeddings": 32})


class TestVectorDimensionDetection:
    """Test vector dimension detection from PyArrow table"""

    def test_detect_dimension_from_table(self, mock_client):
        """Test detecting vector dimension from PyArrow table using shared utility"""
        from docpipe.utils.operators.vectordb_utils import detect_vector_dimension

        # Create table with embeddings
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        table = pa.table({"embeddings": embeddings})

        dimension = detect_vector_dimension(table=table, embeddings_column="embeddings")
        assert dimension == 3

    def test_detect_dimension_with_numpy_arrays(self, mock_client):
        """Test detecting dimension with numpy arrays using shared utility"""
        from docpipe.utils.operators.vectordb_utils import detect_vector_dimension

        embeddings = [np.array([0.1, 0.2, 0.3, 0.4]), np.array([0.5, 0.6, 0.7, 0.8])]
        table = pa.table({"embeddings": embeddings})

        dimension = detect_vector_dimension(table=table, embeddings_column="embeddings")
        assert dimension == 4

    def test_detect_dimension_missing_column(self, mock_client):
        """Test detecting dimension when embeddings column is missing using shared utility"""
        from docpipe.utils.operators.vectordb_utils import detect_vector_dimension

        table = pa.table({"content": ["text1", "text2"]})

        # The method logs a warning and returns None when column is missing
        dimension = detect_vector_dimension(table=table, embeddings_column="embeddings")
        assert dimension is None


class TestMetricTypes:
    """Test metric type constants"""

    def test_all_metric_types_defined(self):
        """Test that all metric types are properly defined"""
        assert MilvusMetricTypes.L2 == "L2"
        assert MilvusMetricTypes.IP == "IP"
        assert MilvusMetricTypes.COSINE == "COSINE"
        assert MilvusMetricTypes.BM25 == "BM25"
        assert MilvusMetricTypes.HAMMING == "HAMMING"
        assert MilvusMetricTypes.JACCARD == "JACCARD"
        for metric in (
            MilvusMetricTypes.L2,
            MilvusMetricTypes.IP,
            MilvusMetricTypes.COSINE,
            MilvusMetricTypes.BM25,
            MilvusMetricTypes.HAMMING,
            MilvusMetricTypes.JACCARD,
        ):
            assert metric in MilvusMetricTypes.ALL_TYPES
        assert MilvusMetricTypes.GPU_VALID_METRICS == ["L2", "IP"]


class TestIndexTypes:
    """Test index type constants"""

    def test_all_index_types_defined(self):
        """Test that all index types are properly defined"""
        # CPU dense
        assert MilvusIndexTypes.FLAT == "FLAT"
        assert MilvusIndexTypes.IVF_FLAT == "IVF_FLAT"
        assert MilvusIndexTypes.IVF_SQ8 == "IVF_SQ8"
        assert MilvusIndexTypes.IVF_PQ == "IVF_PQ"
        assert MilvusIndexTypes.HNSW == "HNSW"
        assert MilvusIndexTypes.DISKANN == "DISKANN"
        assert MilvusIndexTypes.AUTOINDEX == "AUTOINDEX"
        # GPU dense
        assert not hasattr(MilvusIndexTypes, "GPU_FLAT")
        assert MilvusIndexTypes.GPU_IVF_FLAT == "GPU_IVF_FLAT"
        assert MilvusIndexTypes.GPU_IVF_PQ == "GPU_IVF_PQ"
        assert MilvusIndexTypes.GPU_CAGRA == "GPU_CAGRA"
        assert MilvusIndexTypes.GPU_BRUTE_FORCE == "GPU_BRUTE_FORCE"
        # Sparse
        assert MilvusIndexTypes.SPARSE_INVERTED_INDEX == "SPARSE_INVERTED_INDEX"
        assert MilvusIndexTypes.SPARSE_WAND == "SPARSE_WAND"
        assert MilvusIndexTypes.BIN_FLAT == "BIN_FLAT"
        assert MilvusIndexTypes.BIN_IVF_FLAT == "BIN_IVF_FLAT"
        assert MilvusIndexTypes.BIN_FLAT in MilvusIndexTypes.ALL_TYPES
        assert MilvusIndexTypes.BIN_IVF_FLAT in MilvusIndexTypes.ALL_TYPES
        for gpu_type in ("GPU_CAGRA", "GPU_IVF_FLAT", "GPU_IVF_PQ", "GPU_BRUTE_FORCE"):
            assert gpu_type in MilvusIndexTypes.ALL_TYPES
            assert gpu_type in MilvusIndexTypes.ALL_GPU_TYPES

    def test_default_parameters_for_all_types(self):
        """Test that default parameters exist for all index types"""
        for index_type in MilvusIndexTypes.ALL_TYPES:
            assert index_type in INDEX_DEFAULT_PARAMETERS


class TestMultiModelSupport:
    """Test multi-model embeddings support"""

    @pytest.fixture
    def multi_model_features(self):
        """Feature configuration for multi-model embeddings"""
        return {
            "doc_id_hash": {
                "name": "Document ID",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "string",
                "is_primary": True,
            },
            "content": {
                "name": "Content",
                "available_for_vector_db": True,
                "type": "text",
            },
            "embeddings": {
                "name": "Primary Embeddings",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "vector",
            },
            "embeddings_alt": {
                "name": "Alternative Embeddings",
                "available_for_vector_db": True,
                "type": "vector",
            },
        }

    @pytest.fixture
    def multi_model_mappings(self):
        """Feature mappings for multi-model embeddings"""
        return [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "content", "mapped_column_name": "text"},
            {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            {"feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt"},
        ]

    def test_create_schema_with_multiple_vector_fields(self, mock_client, multi_model_features, multi_model_mappings):
        """Test creating schema with multiple vector fields"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="multi_model_collection",
            available_features=multi_model_features,
            feature_mappings=multi_model_mappings,
        )

        # Dimension mapping for two models
        dimension_mapping = {
            "embeddings": 768,
            "embeddings_alt": 384,
        }

        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Check that both vector fields are created
        field_names = [f.name for f in fields]
        assert "vector_embeddings" in field_names
        assert "vector_embeddings_alt" in field_names

        # Check vector field dimensions
        vector_fields = {f.name: f for f in fields if hasattr(f, "dim")}
        assert vector_fields["vector_embeddings"].dim == 768
        assert vector_fields["vector_embeddings_alt"].dim == 384

    def test_create_collection_with_multiple_vector_indexes(
        self, mock_client, multi_model_features, multi_model_mappings
    ):
        """Test creating collection with indexes for multiple vector fields"""
        mock_client.has_collection.return_value = False
        mock_client.prepare_index_params.return_value = MagicMock()

        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="multi_model_collection",
            available_features=multi_model_features,
            feature_mappings=multi_model_mappings,
        )

        dimension_mapping = {
            "embeddings": 768,
            "embeddings_alt": 384,
        }

        manager.create_collection(dimension_mapping=dimension_mapping)

        # Verify collection was created
        mock_client.create_collection.assert_called_once()

        # Verify index params were prepared
        mock_client.prepare_index_params.assert_called_once()


class TestNullableFields:
    """Test nullable field handling"""

    @pytest.fixture
    def features_with_optional_fields(self):
        """Feature configuration with optional fields"""
        return {
            "doc_id_hash": {
                "name": "Document ID",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "string",
                "is_primary": True,
            },
            "content": {
                "name": "Content",
                "available_for_vector_db": True,
                "type": "text",
            },
            "embeddings": {
                "name": "Embeddings",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "vector",
            },
            "optional_field": {
                "name": "Optional Field",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": False,
                "type": "string",
            },
        }

    @pytest.fixture
    def mappings_with_optional_fields(self):
        """Feature mappings with optional fields"""
        return [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "content", "mapped_column_name": "text"},
            {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            {"feature_name": "optional_field", "mapped_column_name": "optional_data"},
        ]

    def test_optional_fields_are_nullable(
        self, mock_client, features_with_optional_fields, mappings_with_optional_fields
    ):
        """Test that non-mandatory fields are created with nullable=True"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            available_features=features_with_optional_fields,
            feature_mappings=mappings_with_optional_fields,
        )

        dimension_mapping = {"embeddings": 384}
        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Find the optional field
        optional_field = next((f for f in fields if f.name == "optional_data"), None)
        assert optional_field is not None
        assert optional_field.nullable is True

    def test_content_field_is_always_added(
        self, mock_client, features_with_optional_fields, mappings_with_optional_fields
    ):
        """Test that content field is always added and is nullable in dense mode.

        In dense mode the content column is removed by the chunker operator and
        re-populated per chunk; rows without chunk text must not fail insertion,
        so the field is created with nullable=True.
        """
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_collection",
            available_features=features_with_optional_fields,
            feature_mappings=mappings_with_optional_fields,
        )

        dimension_mapping = {"embeddings": 384}
        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Check primary key field (always mandatory, is_primary=True)
        pk_field = next((f for f in fields if f.name == "pk"), None)
        assert pk_field is not None
        assert pk_field.is_primary is True

        # Content field is always added in dense mode and must be nullable so that
        # chunk rows without text do not fail insert.
        content_field = next((f for f in fields if f.name == "text"), None)
        assert content_field is not None
        assert content_field.nullable is True


class TestSparseVectorMode:
    """Test sparse vector mode with hardcoded configuration"""

    def test_sparse_mode_initialization(self, mock_client):
        """Test initialization in sparse vector mode"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="sparse_collection",
            vector_mode="sparse",
        )

        assert manager._is_sparse is True

    def test_sparse_mode_creates_sparse_vector_field(self, mock_client, basic_features, feature_mappings):
        """Test that sparse mode creates sparse vector field"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="sparse_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
            vector_mode="sparse",
        )

        dimension_mapping = {"embeddings": 384}
        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Check for sparse vector field
        field_names = [f.name for f in fields]
        assert "sparse_vector" in field_names

    def test_sparse_mode_content_field_has_analyzer(self, mock_client, basic_features, feature_mappings):
        """Test that content field has enable_analyzer=True in sparse mode"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="sparse_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
            vector_mode="sparse",
        )

        dimension_mapping = {"embeddings": 384}
        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Find content field
        content_field = next((f for f in fields if f.name == "text"), None)
        assert content_field is not None
        assert content_field.enable_analyzer is True

    def test_dense_mode_content_field_no_analyzer(self, mock_client, basic_features, feature_mappings):
        """Test that content field has enable_analyzer=False in dense mode"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="dense_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
            vector_mode="dense",
        )

        dimension_mapping = {"embeddings": 384}
        fields = manager._create_schema_fields(dimension_mapping=dimension_mapping)

        # Find content field
        content_field = next((f for f in fields if f.name == "text"), None)
        assert content_field is not None
        assert content_field.enable_analyzer is False


# ---------------------------------------------------------------------------
# Additional tests to reach 80% coverage
# ---------------------------------------------------------------------------


class TestCollectionExistsEdgeCases:
    """collection_exists error path."""

    def test_collection_exists_returns_false_on_exception(self, mock_client):
        """collection_exists catches exceptions and returns False."""
        mock_client.has_collection.side_effect = Exception("network error")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        assert manager.collection_exists() is False


class TestValidateExistingCollectionEdgeCases:
    """Branches in validate_existing_collection not previously covered."""

    def test_missing_field_in_existing_schema_raises(self, mock_client):
        """A vector field present in dimension_mapping but absent from the existing schema raises."""
        mock_client.has_collection.return_value = True
        mock_client.describe_collection.return_value = {
            "fields": [
                {"name": "pk", "params": {}},
                # 'vector_embeddings' is intentionally absent
            ]
        }
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            feature_mappings=[{"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}],
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="missing from existing collection schema"):
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})

    def test_describe_collection_raises_wrapped_in_docpipe_exception(self, mock_client):
        """Non-DocpipeException from describe_collection is wrapped."""
        mock_client.has_collection.return_value = True
        mock_client.describe_collection.side_effect = RuntimeError("timeout")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="Failed to validate collection"):
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})

    def test_docpipe_exception_is_reraised_directly(self, mock_client):
        """DocpipeException from inner logic propagates unchanged."""
        mock_client.has_collection.return_value = True
        mock_client.describe_collection.return_value = {
            "fields": [{"name": "vector_embeddings", "params": {"dim": 256}}]
        }
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            feature_mappings=[{"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}],
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="dimension mismatch"):
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})


class TestCreateCollectionEdgeCases:
    """create_collection branches not previously covered."""

    def _make_manager(self, mock_client, *, vector_mode: str = "dense") -> "MilvusIndexManager":
        mock_client.has_collection.return_value = False
        mock_client.prepare_index_params.return_value.add_index = lambda **kw: None
        mappings = [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            {"feature_name": "content", "mapped_column_name": "text"},
        ]
        return MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            feature_mappings=mappings,
            vector_mode=vector_mode,
        )

    def test_create_collection_raises_if_already_exists(self, mock_client):
        """create_collection raises DocpipeException (409) when collection already exists."""
        mock_client.has_collection.return_value = True
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 409

    def test_create_collection_dense_mode_calls_create_collection(self, mock_client):
        """Dense mode calls client.create_collection and client.create_index."""
        mock_client.has_collection.return_value = False
        index_params_mock = MagicMock()
        mock_client.prepare_index_params.return_value = index_params_mock
        manager = self._make_manager(mock_client, vector_mode="dense")
        manager.create_collection(dimension_mapping={"embeddings": 384})
        mock_client.create_collection.assert_called_once()
        mock_client.create_index.assert_called_once()

    def test_create_collection_inner_exception_wrapped(self, mock_client):
        """An exception inside create_collection is wrapped in DocpipeException."""
        mock_client.has_collection.return_value = False
        mock_client.create_collection.side_effect = RuntimeError("storage full")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="Failed to create collection"):
            manager.create_collection(dimension_mapping={"embeddings": 384})

    def test_index_failure_drops_partial_collection(self, mock_client):
        """A create_index failure after create_collection drops the dead collection."""
        mock_client.create_index.side_effect = RuntimeError("index build failed")
        manager = self._make_manager(mock_client)

        with pytest.raises(DocpipeException, match="index build failed"):
            manager.create_collection(dimension_mapping={"embeddings": 384})

        mock_client.drop_collection.assert_called_once_with(collection_name="test_col")

    def test_failure_before_collection_creation_does_not_drop(self, mock_client):
        """If client.create_collection itself fails, nothing is dropped."""
        mock_client.create_collection.side_effect = RuntimeError("storage full")
        manager = self._make_manager(mock_client)

        with pytest.raises(DocpipeException, match="storage full"):
            manager.create_collection(dimension_mapping={"embeddings": 384})

        mock_client.drop_collection.assert_not_called()

    def test_drop_failure_does_not_mask_original_error(self, mock_client):
        """A failing cleanup drop still surfaces the original index error."""
        mock_client.create_index.side_effect = RuntimeError("index build failed")
        mock_client.drop_collection.side_effect = RuntimeError("drop failed")
        manager = self._make_manager(mock_client)

        with pytest.raises(DocpipeException, match="index build failed"):
            manager.create_collection(dimension_mapping={"embeddings": 384})

    def test_sparse_index_failure_drops_partial_collection(self, mock_client):
        """A failing sparse create_index (the first index call) also drops the dead collection."""
        mock_client.create_index.side_effect = RuntimeError("sparse index failed")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                {"feature_name": "content", "mapped_column_name": "text"},
            ],
            vector_mode="sparse",
        )

        with pytest.raises(DocpipeException, match="sparse index failed"):
            manager.create_collection(dimension_mapping={"embeddings": 384})

        assert mock_client.create_index.call_count == 1
        mock_client.drop_collection.assert_called_once_with(collection_name="test_col")


class TestCreateCollectionSparseMode:
    """create_collection sparse path — creates sparse index AND dense index."""

    def test_create_collection_sparse_mode_creates_both_indexes(self, mock_client):
        """Sparse mode calls create_index twice: once for sparse, once for dense."""
        mock_client.has_collection.return_value = False
        index_params_mock = MagicMock()
        mock_client.prepare_index_params.return_value = index_params_mock

        mappings = [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            {"feature_name": "content", "mapped_column_name": "text"},
            {"feature_name": "sparse_embeddings", "mapped_column_name": "sparse_vector"},
        ]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            feature_mappings=mappings,
            vector_mode="sparse",
        )
        manager.create_collection(dimension_mapping={"embeddings": 384})

        assert mock_client.create_index.call_count == 2
        mock_client.create_collection.assert_called_once()


class TestGetCollectionInfo:
    """get_collection_info happy path and not-found path."""

    def test_get_collection_info_returns_stats(self, mock_client):
        mock_client.has_collection.return_value = True
        mock_client.get_collection_stats.return_value = {"row_count": 99}
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        info = manager.get_collection_info()
        assert info["row_count"] == 99
        assert info["name"] == "test_col"
        assert info["exists"] is True

    def test_get_collection_info_raises_when_not_exists(self, mock_client):
        mock_client.has_collection.return_value = False
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="does not exist"):
            manager.get_collection_info()

    def test_get_collection_info_stats_exception_wrapped(self, mock_client):
        mock_client.has_collection.return_value = True
        mock_client.get_collection_stats.side_effect = RuntimeError("stats failed")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="Failed to get collection info"):
            manager.get_collection_info()


class TestDropCollection:
    """drop_collection both paths."""

    def test_drop_collection_calls_client_when_exists(self, mock_client):
        mock_client.has_collection.return_value = True
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        manager.drop_collection()
        mock_client.drop_collection.assert_called_once_with(collection_name="test_col")

    def test_drop_collection_no_op_when_not_exists(self, mock_client):
        mock_client.has_collection.return_value = False
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        manager.drop_collection()
        mock_client.drop_collection.assert_not_called()

    def test_drop_collection_exception_wrapped(self, mock_client):
        mock_client.has_collection.return_value = True
        mock_client.drop_collection.side_effect = RuntimeError("drop failed")
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
        )
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises(DocpipeException, match="Failed to drop collection"):
            manager.drop_collection()


class TestMapFeatureTypeToDtype:
    """_map_feature_type_to_milvus_dtype coverage for all mapped and unmapped types."""

    @pytest.fixture
    def manager(self, mock_client):
        return MilvusIndexManager(client=mock_client, collection_name="c")

    @pytest.mark.parametrize(
        ("feature_type", "expected"),
        [
            ("text", "VARCHAR"),
            ("string", "VARCHAR"),
            ("keyword", "VARCHAR"),
            ("long", "INT64"),
            ("integer", "INT32"),
            ("short", "INT16"),
            ("byte", "INT8"),
            ("double", "DOUBLE"),
            ("float", "FLOAT"),
            ("boolean", "BOOL"),
            ("date", "VARCHAR"),
            ("json", "JSON"),
        ],
    )
    def test_known_types_return_correct_dtype(self, manager, feature_type, expected):

        dtype = manager._map_feature_type_to_milvus_dtype(feature_type=feature_type)
        assert dtype is not None
        assert dtype.name == expected

    def test_unknown_type_returns_none(self, manager):
        assert manager._map_feature_type_to_milvus_dtype(feature_type="unsupported_xyz") is None


class TestGetIndexParametersSparse:
    """_get_index_parameters removes 'dim' when in sparse mode."""

    def test_sparse_mode_removes_dim_from_params(self, mock_client):
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="sparse",
            index_parameters={"dim": 384, "M": 8},
        )
        params = manager._get_index_parameters()
        assert "dim" not in params
        assert params.get("M") == 8

    def test_dense_mode_keeps_dim_if_present(self, mock_client):
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="dense",
            index_parameters={"dim": 384},
        )
        params = manager._get_index_parameters()
        assert params.get("dim") == 384


class TestCreateSchemaFieldsSkipBranches:
    """_create_schema_fields skip conditions for vector/pk/sparse/unavailable fields."""

    def test_field_mapping_to_primary_key_is_skipped(self, mock_client):
        """A feature that maps to the primary_key_field name is not added twice."""
        features = {"doc_id": {"available_for_vector_db": True, "type": "string"}}
        mappings = [{"feature_name": "doc_id", "mapped_column_name": "pk"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            available_features=features,
            feature_mappings=mappings,
            primary_key_field="pk",
        )
        fields = manager._create_schema_fields(dimension_mapping={})
        # Only pk and content fields should be present (no duplicate pk)
        field_names = [f.name for f in fields]
        assert field_names.count("pk") == 1

    def test_vector_type_feature_not_in_dimension_mapping_is_skipped(self, mock_client):
        """A feature with type=vector that is NOT in dimension_mapping is skipped."""
        features = {
            "orphan_vec": {"available_for_vector_db": True, "type": "vector"},
        }
        mappings = [{"feature_name": "orphan_vec", "mapped_column_name": "orphan_field"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            available_features=features,
            feature_mappings=mappings,
        )
        fields = manager._create_schema_fields(dimension_mapping={})
        field_names = [f.name for f in fields]
        assert "orphan_field" not in field_names

    def test_unavailable_for_vector_db_field_is_skipped(self, mock_client):
        """A feature with available_for_vector_db=False is excluded from schema."""
        features = {"secret": {"available_for_vector_db": False, "type": "string"}}
        mappings = [{"feature_name": "secret", "mapped_column_name": "secret_field"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            available_features=features,
            feature_mappings=mappings,
        )
        fields = manager._create_schema_fields(dimension_mapping={})
        field_names = [f.name for f in fields]
        assert "secret_field" not in field_names

    def test_field_mapped_to_dense_vector_field_name_is_skipped(self, mock_client):
        """A feature whose mapped name matches DENSE_VECTOR_FIELD_NAME is not re-added."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        features = {"emb": {"available_for_vector_db": True, "type": "string"}}
        mappings = [{"feature_name": "emb", "mapped_column_name": OperatorConstants.VectorDB.DENSE_VECTOR_FIELD_NAME}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            available_features=features,
            feature_mappings=mappings,
        )
        fields = manager._create_schema_fields(dimension_mapping={})
        field_names = [f.name for f in fields]
        assert field_names.count(OperatorConstants.VectorDB.DENSE_VECTOR_FIELD_NAME) == 0


class TestGPUMode:
    """Tests for GPU mode (vector_mode='gpu') support, index types, metrics, and validation."""

    def test_gpu_mode_initialization(self, mock_client):
        """GPU mode initializes successfully with GPU index type and valid metric."""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="gpu",
            index_type="GPU_CAGRA",
            metric_type="L2",
        )
        assert manager.vector_mode == "gpu"
        assert manager.index_type == "GPU_CAGRA"
        assert manager.metric_type == "L2"
        assert manager._is_gpu is True

    def test_gpu_mode_rejects_cpu_index_type(self, mock_client):
        """GPU mode rejects CPU index types."""
        with pytest.raises(DocpipeException, match="not supported in vector_mode='gpu'"):
            MilvusIndexManager(
                client=mock_client,
                collection_name="c",
                vector_mode="gpu",
                index_type="HNSW",
            )

    def test_gpu_mode_rejects_cosine_metric(self, mock_client):
        """GPU mode rejects COSINE metric."""
        with pytest.raises(DocpipeException, match="does not support metric 'COSINE'"):
            MilvusIndexManager(
                client=mock_client,
                collection_name="c",
                vector_mode="gpu",
                index_type="GPU_CAGRA",
                metric_type="COSINE",
            )

    def test_gpu_cagra_graph_degree_validation(self, mock_client):
        """GPU_CAGRA rejects graph_degree > intermediate_graph_degree."""
        with pytest.raises(
            DocpipeException, match=r"graph_degree \(64\) to be less than or equal to intermediate_graph_degree"
        ):
            MilvusIndexManager(
                client=mock_client,
                collection_name="c",
                vector_mode="gpu",
                index_type="GPU_CAGRA",
                index_parameters={"graph_degree": 64, "intermediate_graph_degree": 32},
            )

    def test_gpu_cagra_valid_custom_parameters(self, mock_client):
        """GPU_CAGRA accepts custom parameters where graph_degree <= intermediate_graph_degree."""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="gpu",
            index_type="GPU_CAGRA",
            index_parameters={"graph_degree": 32, "intermediate_graph_degree": 64},
        )
        params = manager._get_index_parameters()
        assert params["graph_degree"] == 32
        assert params["intermediate_graph_degree"] == 64

    def test_default_parameters_for_all_gpu_index_types(self):
        """All GPU index types have entries in INDEX_DEFAULT_PARAMETERS."""
        for gpu_type in MilvusIndexTypes.ALL_GPU_TYPES:
            assert gpu_type in INDEX_DEFAULT_PARAMETERS
        cagra_params = INDEX_DEFAULT_PARAMETERS[MilvusIndexTypes.GPU_CAGRA]
        assert "intermediate_graph_degree" in cagra_params
        assert "graph_degree" in cagra_params
        assert "build_algo" in cagra_params
        assert "cache_dataset_on_device" in cagra_params

    def test_rejection_of_unknown_vector_mode(self, mock_client):
        """Unknown vector_mode raises DocpipeException with 400 status code."""
        with pytest.raises(DocpipeException, match="Invalid vector_mode 'unknown'"):
            MilvusIndexManager(
                client=mock_client,
                collection_name="c",
                vector_mode="unknown",
            )

    def test_gpu_mode_rejected_on_lite(self, mock_client):
        """GPU mode is rejected on Milvus Lite."""
        with pytest.raises(DocpipeException, match="not supported by Milvus Lite"):
            MilvusIndexManager(
                client=mock_client,
                collection_name="c",
                vector_mode="gpu",
                index_type="GPU_CAGRA",
                is_lite=True,
            )

    def test_gpu_accepts_ip(self, mock_client):
        """GPU mode accepts IP metric."""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="gpu",
            index_type="GPU_CAGRA",
            metric_type="IP",
        )
        assert manager.metric_type == "IP"


class TestBinaryVectorIndexSupport:
    """Tests for binary vector index types, metrics, validation, and schema generation."""

    def test_binary_index_types_and_metrics_defined(self):
        """Verify binary index types and metrics constants."""
        assert "BIN_FLAT" in MilvusIndexTypes.ALL_BINARY_TYPES
        assert "BIN_IVF_FLAT" in MilvusIndexTypes.ALL_BINARY_TYPES
        assert "BIN_FLAT" in MilvusIndexTypes.ALL_TYPES
        assert "BIN_IVF_FLAT" in MilvusIndexTypes.ALL_TYPES

        for metric in ["HAMMING", "JACCARD"]:
            assert metric in MilvusMetricTypes.ALL_BINARY_METRIC_TYPES
            assert metric in MilvusMetricTypes.ALL_TYPES

    @pytest.mark.parametrize("metric", ["TANIMOTO", "SUBSTRUCTURE", "SUPERSTRUCTURE"])
    def test_metrics_removed_in_milvus_2_6_are_rejected(self, mock_client, metric):
        """Binary metrics Milvus no longer supports must fail at init, not at index creation."""
        assert metric not in MilvusMetricTypes.ALL_TYPES
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_bin_col",
                index_type=MilvusIndexTypes.BIN_FLAT,
                metric_type=metric,
            )
        assert f"Invalid metric type '{metric}'" in str(exc_info.value)

    def test_valid_binary_index_initialization(self, mock_client):
        """Verify initializing with valid binary index and metric."""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.BIN_IVF_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            index_parameters={"nlist": 256},
        )
        assert manager.index_type == MilvusIndexTypes.BIN_IVF_FLAT
        assert manager.metric_type == MilvusMetricTypes.HAMMING
        params = manager._get_index_parameters()
        assert params.get("nlist") == 256

    def test_binary_index_with_dense_metric_raises(self, mock_client):
        """Binary index type requires a binary metric type."""
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_bin_col",
                index_type=MilvusIndexTypes.BIN_FLAT,
                metric_type=MilvusMetricTypes.COSINE,
            )
        assert "requires a binary metric type" in str(exc_info.value)

    def test_dense_index_with_binary_metric_raises(self, mock_client):
        """Dense index type cannot be paired with a binary-only metric."""
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_dense_col",
                index_type=MilvusIndexTypes.HNSW,
                metric_type=MilvusMetricTypes.HAMMING,
            )
        assert "Invalid metric type 'HAMMING'" in str(exc_info.value)

    def test_milvus_lite_rejects_binary_index_type(self, mock_client):
        """Milvus Lite must reject binary index types at initialization."""
        with pytest.raises(DocpipeException) as exc_info:
            MilvusIndexManager(
                client=mock_client,
                collection_name="test_lite_col",
                index_type=MilvusIndexTypes.BIN_FLAT,
                metric_type=MilvusMetricTypes.HAMMING,
                is_lite=True,
            )
        assert "not supported by Milvus Lite" in str(exc_info.value)

    def test_binary_vector_schema_creation(self, mock_client):
        """Binary vector fields are created with DataType.BINARY_VECTOR and dim."""
        from pymilvus import DataType

        features = {
            "binary_embeddings": {
                "name": "Binary Embeddings",
                "available_for_vector_db": True,
                "type": "vector_binary",
            }
        }
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "bin_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            available_features=features,
            feature_mappings=mappings,
        )
        fields = manager._create_schema_fields(dimension_mapping={"binary_embeddings": 256})
        bin_field = next((f for f in fields if f.name == "bin_vec"), None)
        assert bin_field is not None
        assert bin_field.dtype == DataType.BINARY_VECTOR
        assert bin_field.params.get("dim") == 256

    def test_binary_vector_invalid_dimension_raises(self, mock_client):
        """Binary vector dimension not divisible by 8 must raise DocpipeException."""
        features = {
            "binary_embeddings": {
                "name": "Binary Embeddings",
                "available_for_vector_db": True,
                "type": "vector_binary",
            }
        }
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "bin_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            available_features=features,
            feature_mappings=mappings,
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager._create_schema_fields(dimension_mapping={"binary_embeddings": 250})
        assert "must be a multiple of 8" in str(exc_info.value)

    def test_milvus_lite_rejects_binary_vector_field(self, mock_client):
        """Milvus Lite must reject binary vector field during schema creation."""
        features = {
            "binary_embeddings": {
                "name": "Binary Embeddings",
                "available_for_vector_db": True,
                "type": "vector_binary",
            }
        }
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "bin_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_lite_col",
            index_type=MilvusIndexTypes.FLAT,
            metric_type=MilvusMetricTypes.L2,
            available_features=features,
            feature_mappings=mappings,
            is_lite=True,
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager._create_schema_fields(dimension_mapping={"binary_embeddings": 128})
        assert "not supported by Milvus Lite" in str(exc_info.value)

    @staticmethod
    def _hybrid_manager(
        client: MagicMock, *, binary_type: str = "vector_binary", **overrides: Any
    ) -> MilvusIndexManager:
        """Build a manager with one dense and one binary feature (dense_vec / binary_vec)."""
        features = {
            "dense_embeddings": {"name": "Dense", "available_for_vector_db": True, "type": "vector"},
            "binary_embeddings": {"name": "Binary", "available_for_vector_db": True, "type": binary_type},
        }
        mappings = [
            {"feature_name": "dense_embeddings", "mapped_column_name": "dense_vec"},
            {"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"},
        ]
        kwargs: dict[str, Any] = {
            "index_type": MilvusIndexTypes.HNSW,
            "metric_type": MilvusMetricTypes.COSINE,
            "index_parameters": {"M": 24, "efConstruction": 300},
        }
        kwargs.update(overrides)
        return MilvusIndexManager(
            client=client,
            collection_name="test_hybrid_col",
            available_features=features,
            feature_mappings=mappings,
            **kwargs,
        )

    @staticmethod
    def _add_index_calls(client: MagicMock) -> dict[str, dict[str, Any]]:
        """Return the kwargs of each add_index call keyed by field_name."""
        params = client.prepare_index_params.return_value
        return {c.kwargs["field_name"]: c.kwargs for c in params.add_index.call_args_list}

    def test_multi_vector_dense_and_binary_schema_and_indexes(self, mock_client):
        """Mixed collection: dense keeps its own index/metric/params; binary defaults to BIN_FLAT + HAMMING."""
        from pymilvus import DataType

        manager = self._hybrid_manager(mock_client)
        dim_mapping = {"dense_embeddings": 384, "binary_embeddings": 256}
        fields = manager._create_schema_fields(dimension_mapping=dim_mapping)

        dense_field = next((f for f in fields if f.name == "dense_vec"), None)
        bin_field = next((f for f in fields if f.name == "binary_vec"), None)
        assert dense_field is not None and dense_field.dtype == DataType.FLOAT_VECTOR
        assert bin_field is not None and bin_field.dtype == DataType.BINARY_VECTOR

        manager.create_collection(dimension_mapping=dim_mapping)
        mock_client.create_collection.assert_called_once()
        mock_client.create_index.assert_called_once()

        calls = self._add_index_calls(mock_client)
        assert set(calls) == {"dense_vec", "binary_vec"}
        assert calls["dense_vec"]["index_type"] == MilvusIndexTypes.HNSW
        assert calls["dense_vec"]["metric_type"] == MilvusMetricTypes.COSINE
        assert calls["dense_vec"]["params"] == {"M": 24, "efConstruction": 300}
        assert calls["binary_vec"]["index_type"] == MilvusIndexTypes.BIN_FLAT
        assert calls["binary_vec"]["metric_type"] == MilvusMetricTypes.HAMMING
        assert calls["binary_vec"]["params"] == {}

    def test_vector_type_binary_marks_field_binary(self, mock_client):
        """A feature with vector_type == 'binary' is binary regardless of its type string."""
        from pymilvus import DataType

        manager = self._hybrid_manager(mock_client)
        manager.available_features["binary_embeddings"] = {
            "available_for_vector_db": True,
            "type": "vector",
            "vector_type": "binary",
        }
        fields = manager._create_schema_fields(dimension_mapping={"dense_embeddings": 384, "binary_embeddings": 256})
        bin_field = next(f for f in fields if f.name == "binary_vec")
        assert bin_field.dtype == DataType.BINARY_VECTOR

    def test_binary_index_config_applies_to_binary_field_in_mixed_collection(self, mock_client):
        """BIN_* index_type/metric/params configure the binary field; the dense field gets HNSW/L2 defaults."""
        manager = self._hybrid_manager(
            mock_client,
            index_type=MilvusIndexTypes.BIN_IVF_FLAT,
            metric_type=MilvusMetricTypes.JACCARD,
            index_parameters={"nlist": 64},
        )
        manager.create_collection(dimension_mapping={"dense_embeddings": 384, "binary_embeddings": 256})

        calls = self._add_index_calls(mock_client)
        assert calls["binary_vec"]["index_type"] == MilvusIndexTypes.BIN_IVF_FLAT
        assert calls["binary_vec"]["metric_type"] == MilvusMetricTypes.JACCARD
        assert calls["binary_vec"]["params"] == {"nlist": 64}
        assert calls["dense_vec"]["index_type"] == MilvusIndexTypes.HNSW
        assert calls["dense_vec"]["metric_type"] == MilvusMetricTypes.L2
        assert calls["dense_vec"]["params"] == INDEX_DEFAULT_PARAMETERS[MilvusIndexTypes.HNSW]

    def test_binary_only_collection_honors_bin_index_config(self, mock_client):
        """Binary-only collection with a BIN_* index_type/metric/params uses them as configured."""
        features = {"binary_embeddings": {"available_for_vector_db": True, "type": "vector_binary"}}
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.BIN_IVF_FLAT,
            metric_type=MilvusMetricTypes.JACCARD,
            index_parameters={"nlist": 32},
            available_features=features,
            feature_mappings=mappings,
        )
        manager.create_collection(dimension_mapping={"binary_embeddings": 128})

        calls = self._add_index_calls(mock_client)
        assert calls["binary_vec"]["index_type"] == MilvusIndexTypes.BIN_IVF_FLAT
        assert calls["binary_vec"]["metric_type"] == MilvusMetricTypes.JACCARD
        assert calls["binary_vec"]["params"] == {"nlist": 32}

    def test_binary_field_with_dense_index_and_dense_metric_defaults_to_bin_flat_hamming(self, mock_client):
        """A dense index_type never leaks into a binary field: the field falls back to BIN_FLAT / HAMMING."""
        features = {"binary_embeddings": {"available_for_vector_db": True, "type": "vector_binary"}}
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.HNSW,
            metric_type=MilvusMetricTypes.COSINE,
            index_parameters={"M": 8},
            available_features=features,
            feature_mappings=mappings,
        )
        manager.create_collection(dimension_mapping={"binary_embeddings": 128})

        calls = self._add_index_calls(mock_client)
        assert calls["binary_vec"]["index_type"] == MilvusIndexTypes.BIN_FLAT
        assert calls["binary_vec"]["metric_type"] == MilvusMetricTypes.HAMMING
        assert calls["binary_vec"]["params"] == {}

    def test_binary_field_dense_config_override_logs_warning(self, mock_client):
        """Replacing a configured dense index on a binary field must be visible in the logs."""
        features = {"binary_embeddings": {"available_for_vector_db": True, "type": "vector_binary"}}
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.HNSW,
            metric_type=MilvusMetricTypes.COSINE,
            index_parameters={"M": 8},
            available_features=features,
            feature_mappings=mappings,
        )
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager.logger") as mock_logger:
            manager.create_collection(dimension_mapping={"binary_embeddings": 128})

        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args.args
        assert "cannot use the configured dense index settings" in args[0]
        assert "binary_vec" in args
        assert MilvusIndexTypes.HNSW in args
        assert MilvusMetricTypes.COSINE in args
        assert MilvusIndexTypes.BIN_FLAT in args
        assert MilvusMetricTypes.HAMMING in args

    def test_binary_index_config_on_binary_field_does_not_warn(self, mock_client):
        """No warning when the configured BIN_* index is used as-is."""
        features = {"binary_embeddings": {"available_for_vector_db": True, "type": "vector_binary"}}
        mappings = [{"feature_name": "binary_embeddings", "mapped_column_name": "binary_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_bin_col",
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            available_features=features,
            feature_mappings=mappings,
        )
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager.logger") as mock_logger:
            manager.create_collection(dimension_mapping={"binary_embeddings": 128})

        mock_logger.warning.assert_not_called()

    def test_dense_field_with_dense_index_does_not_warn(self, mock_client):
        """Dense fields keep their configuration, so nothing is overridden and nothing is logged."""
        manager = self._hybrid_manager(mock_client, index_type=MilvusIndexTypes.BIN_FLAT, metric_type="HAMMING")
        with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager.logger") as mock_logger:
            manager.create_collection(dimension_mapping={"dense_embeddings": 384, "binary_embeddings": 256})

        mock_logger.warning.assert_not_called()

    def test_float_only_collection_with_bin_index_type_raises(self, mock_client):
        """A float field must not be silently treated as binary because index_type is BIN_*."""
        features = {"dense_embeddings": {"available_for_vector_db": True, "type": "vector"}}
        mappings = [{"feature_name": "dense_embeddings", "mapped_column_name": "dense_vec"}]
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="test_col",
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            available_features=features,
            feature_mappings=mappings,
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager._create_schema_fields(dimension_mapping={"dense_embeddings": 128})
        assert "no binary vector field" in str(exc_info.value)

    def test_dense_field_stays_float_with_bin_index_type_in_mixed_mode(self, mock_client):
        """In a mixed collection with a BIN_* index_type the dense field stays FLOAT_VECTOR."""
        from pymilvus import DataType

        manager = self._hybrid_manager(
            mock_client,
            index_type=MilvusIndexTypes.BIN_FLAT,
            metric_type=MilvusMetricTypes.HAMMING,
            index_parameters={},
        )
        fields = manager._create_schema_fields(dimension_mapping={"dense_embeddings": 384, "binary_embeddings": 256})
        dense_field = next(f for f in fields if f.name == "dense_vec")
        assert dense_field.dtype == DataType.FLOAT_VECTOR


class TestValidateVectorFeatureTypes:
    """validate_vector_feature_types rejects BIN_* index configs without an upstream binary vector feature."""

    @staticmethod
    def _manager(mock_client, **kwargs):
        return MilvusIndexManager(client=mock_client, collection_name="c", **kwargs)

    def test_bin_index_without_binary_feature_raises(self, mock_client):
        manager = self._manager(mock_client, index_type="BIN_IVF_FLAT", metric_type="HAMMING")
        with pytest.raises(DocpipeException, match="requires a binary vector feature"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector", "content": "string"})

    def test_bin_index_with_binary_feature_passes(self, mock_client):
        manager = self._manager(mock_client, index_type="BIN_FLAT", metric_type="HAMMING")
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})

    def test_dense_index_never_requires_binary_feature(self, mock_client):
        manager = self._manager(mock_client, index_type="HNSW", metric_type="COSINE")
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_mixed_collection_with_one_binary_feature_passes(self, mock_client):
        manager = self._manager(mock_client, index_type="BIN_FLAT", metric_type="HAMMING")
        manager.validate_vector_feature_types(feature_types={"dense_vec": "vector", "bin_vec": "vector_binary"})

    def test_sparse_mode_skips_binary_requirement(self, mock_client):
        """Sparse mode never requires a binary feature, even when index_type is a BIN_* type."""
        manager = self._manager(mock_client, index_type="BIN_FLAT", metric_type="HAMMING", vector_mode="sparse")
        manager.validate_vector_feature_types(feature_types={"content": "string"})

    def test_lite_with_binary_feature_and_flat_index_raises(self, mock_client):
        """FLAT/L2 is valid for Lite, but a binary feature (quantization) still cannot be stored."""
        manager = self._manager(mock_client, index_type="FLAT", metric_type="L2", is_lite=True)
        with pytest.raises(DocpipeException, match="not supported by Milvus Lite"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})

    def test_lite_with_dense_feature_passes(self, mock_client):
        manager = self._manager(mock_client, index_type="FLAT", metric_type="L2", is_lite=True)
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_gpu_mode_with_dense_feature_passes(self, mock_client):
        manager = self._manager(mock_client, vector_mode="gpu", index_type="GPU_CAGRA")
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_gpu_mode_with_only_binary_feature_raises(self, mock_client):
        """GPU indexes cannot index binary vectors, so a binary-only collection never uses the GPU."""
        manager = self._manager(mock_client, vector_mode="gpu", index_type="GPU_CAGRA")
        with pytest.raises(DocpipeException, match="only applies to dense float vectors"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})

    def test_gpu_mode_mixed_dense_and_binary_passes(self, mock_client):
        manager = self._manager(mock_client, vector_mode="gpu", index_type="GPU_CAGRA")
        manager.validate_vector_feature_types(feature_types={"dense_vec": "vector", "bin_vec": "vector_binary"})

    def test_gpu_sparse_mode_skips_check(self, mock_client):
        """A sparse-only flow never runs the GPU/binary feature checks."""
        manager = self._manager(mock_client, vector_mode="sparse")
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})


class TestVectorKindIndexResolution:
    """Index settings applied per vector field for each collection kind (gpu mode)."""

    @staticmethod
    def _build(mock_client, *, vector_mode: str, index_type: str, metric_type: str, features: dict, dims: dict):
        added: list[dict] = []
        mock_client.prepare_index_params.return_value.add_index = lambda **kw: added.append(kw)
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode=vector_mode,
            index_type=index_type,
            metric_type=metric_type,
            available_features=features,
        )
        manager._build_dense_index_params(dimension_mapping=dims)
        return added

    def test_dense_only_gpu_uses_gpu_index(self, mock_client):
        added = self._build(
            mock_client,
            vector_mode="gpu",
            index_type="GPU_CAGRA",
            metric_type="L2",
            features={"embeddings": {"type": "vector"}},
            dims={"embeddings": 384},
        )
        assert [(a["index_type"], a["metric_type"]) for a in added] == [("GPU_CAGRA", "L2")]

    def test_mixed_gpu_dense_and_bin_flat_binary(self, mock_client):
        added = self._build(
            mock_client,
            vector_mode="gpu",
            index_type="GPU_CAGRA",
            metric_type="L2",
            features={"dense_vec": {"type": "vector"}, "bin_vec": {"type": "vector_binary"}},
            dims={"dense_vec": 384, "bin_vec": 256},
        )
        by_type = {a["index_type"]: a["metric_type"] for a in added}
        assert by_type == {"GPU_CAGRA": "L2", "BIN_FLAT": "HAMMING"}

    def test_binary_mode_binary_only(self, mock_client):
        added = self._build(
            mock_client,
            vector_mode="binary",
            index_type="BIN_IVF_FLAT",
            metric_type="JACCARD",
            features={"bin_vec": {"type": "vector_binary"}},
            dims={"bin_vec": 256},
        )
        assert [(a["index_type"], a["metric_type"]) for a in added] == [("BIN_IVF_FLAT", "JACCARD")]

    def test_hybrid_sparse_index_stays_inverted_index_bm25(self, mock_client):
        """Sparse mode keeps SPARSE_INVERTED_INDEX/BM25 for the sparse field and the configured dense index."""
        mock_client.has_collection.return_value = False
        added: list[dict] = []
        mock_client.prepare_index_params.return_value.add_index = lambda **kw: added.append(kw)
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            vector_mode="sparse",
            index_type="HNSW",
            metric_type="COSINE",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                {"feature_name": "content", "mapped_column_name": "text"},
            ],
            available_features={"embeddings": {"type": "vector"}},
        )
        manager.create_collection(dimension_mapping={"embeddings": 384})
        assert {(a["index_type"], a["metric_type"]) for a in added} == {
            ("SPARSE_INVERTED_INDEX", "BM25"),
            ("HNSW", "COSINE"),
        }


class TestHybridDenseFieldValidation:
    """In sparse (hybrid) mode the dense field's index and metric are validated once a dense feature exists."""

    @staticmethod
    def _hybrid(mock_client, **kwargs):
        return MilvusIndexManager(client=mock_client, collection_name="c", vector_mode="sparse", **kwargs)

    def test_hybrid_default_dense_config_passes(self, mock_client):
        self._hybrid(mock_client).validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_gpu_index_with_valid_metric_passes(self, mock_client):
        manager = self._hybrid(mock_client, index_type="GPU_CAGRA", metric_type="IP")
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_gpu_index_with_cosine_raises(self, mock_client):
        manager = self._hybrid(mock_client, index_type="GPU_CAGRA", metric_type="COSINE")
        with pytest.raises(DocpipeException, match="does not support metric 'COSINE'"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_gpu_index_on_lite_raises(self, mock_client):
        """Sparse mode returns early in _validate_index_type, so the dense field is checked for Lite here."""
        manager = self._hybrid(mock_client, index_type="GPU_CAGRA", metric_type="L2", is_lite=True)
        with pytest.raises(DocpipeException, match="not supported by Milvus Lite"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_cpu_index_other_than_flat_on_lite_raises(self, mock_client):
        manager = self._hybrid(mock_client, index_type="HNSW", metric_type="L2", is_lite=True)
        with pytest.raises(DocpipeException, match="not supported by Milvus Lite"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_flat_index_on_lite_passes(self, mock_client):
        manager = self._hybrid(mock_client, index_type="FLAT", metric_type="L2", is_lite=True)
        manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_unknown_index_type_raises(self, mock_client):
        manager = self._hybrid(mock_client, index_type="NOT_AN_INDEX")
        with pytest.raises(DocpipeException, match="cannot be used for the dense vector field"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_binary_index_type_for_dense_field_raises(self, mock_client):
        manager = self._hybrid(mock_client, index_type="BIN_FLAT", metric_type="HAMMING")
        with pytest.raises(DocpipeException, match="cannot be used for the dense vector field"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_invalid_dense_metric_raises(self, mock_client):
        manager = self._hybrid(mock_client, index_type="HNSW", metric_type="HAMMING")
        with pytest.raises(DocpipeException, match="Invalid metric type"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_hybrid_cagra_degree_violation_raises(self, mock_client):
        manager = self._hybrid(
            mock_client,
            index_type="GPU_CAGRA",
            metric_type="L2",
            index_parameters={"graph_degree": 64, "intermediate_graph_degree": 32},
        )
        with pytest.raises(DocpipeException, match="graph_degree"):
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})

    def test_sparse_only_does_not_check_dense_config(self, mock_client):
        """Sparse-only (no dense vector feature): the dense index settings are unused and unchecked."""
        manager = self._hybrid(mock_client, index_type="NOT_AN_INDEX", metric_type="COSINE")
        manager.validate_vector_feature_types(feature_types={"content": "string"})


class TestGpuCagraDegreeCoercion:
    """GPU_CAGRA degree parameters accept ints and numeric strings, and reject anything else."""

    @staticmethod
    def _validate(params):
        MilvusIndexManager.validate_index_config(
            vector_mode="gpu", index_type="GPU_CAGRA", metric_type="L2", index_parameters=params
        )

    def test_numeric_strings_are_compared_as_ints(self):
        with pytest.raises(DocpipeException, match=r"graph_degree \(64\)"):
            self._validate({"graph_degree": "64", "intermediate_graph_degree": "32"})

    def test_valid_numeric_strings_pass(self):
        self._validate({"graph_degree": "32", "intermediate_graph_degree": "64"})

    def test_non_numeric_value_raises(self):
        with pytest.raises(DocpipeException, match="must be an integer"):
            self._validate({"graph_degree": "abc"})

    def test_bool_value_raises(self):
        with pytest.raises(DocpipeException, match="must be an integer"):
            self._validate({"graph_degree": True})
