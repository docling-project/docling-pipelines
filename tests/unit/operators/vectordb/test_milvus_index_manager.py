#!/usr/bin/env python3
"""
Unit tests for MilvusIndexManager
"""

from unittest.mock import MagicMock

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
        assert len(MilvusMetricTypes.ALL_TYPES) == 4


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
        assert MilvusIndexTypes.HNSW_SQ == "HNSW_SQ"
        assert MilvusIndexTypes.HNSW_PQ == "HNSW_PQ"
        assert MilvusIndexTypes.HNSW_PRQ == "HNSW_PRQ"
        assert MilvusIndexTypes.DISKANN == "DISKANN"
        assert MilvusIndexTypes.AUTOINDEX == "AUTOINDEX"
        # GPU dense
        assert MilvusIndexTypes.GPU_FLAT == "GPU_FLAT"
        assert MilvusIndexTypes.GPU_IVF_FLAT == "GPU_IVF_FLAT"
        assert MilvusIndexTypes.GPU_IVF_PQ == "GPU_IVF_PQ"
        assert MilvusIndexTypes.GPU_CAGRA == "GPU_CAGRA"
        assert MilvusIndexTypes.GPU_BRUTE_FORCE == "GPU_BRUTE_FORCE"
        # Sparse
        assert MilvusIndexTypes.SPARSE_INVERTED_INDEX == "SPARSE_INVERTED_INDEX"
        assert MilvusIndexTypes.SPARSE_WAND == "SPARSE_WAND"
        assert len(MilvusIndexTypes.ALL_TYPES) == 17

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
            add_sparse_vector=True,
        )

        assert manager.add_sparse_vector is True

    def test_sparse_mode_creates_sparse_vector_field(self, mock_client, basic_features, feature_mappings):
        """Test that sparse mode creates sparse vector field"""
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="sparse_collection",
            available_features=basic_features,
            feature_mappings=feature_mappings,
            add_sparse_vector=True,
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
            add_sparse_vector=True,
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
            add_sparse_vector=False,
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

    def _make_manager(self, mock_client, *, add_sparse_vector: bool = False) -> "MilvusIndexManager":
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
            add_sparse_vector=add_sparse_vector,
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
        manager = self._make_manager(mock_client, add_sparse_vector=False)
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
            add_sparse_vector=True,
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
            add_sparse_vector=True,
            index_parameters={"dim": 384, "M": 8},
        )
        params = manager._get_index_parameters()
        assert "dim" not in params
        assert params.get("M") == 8

    def test_dense_mode_keeps_dim_if_present(self, mock_client):
        manager = MilvusIndexManager(
            client=mock_client,
            collection_name="c",
            add_sparse_vector=False,
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
