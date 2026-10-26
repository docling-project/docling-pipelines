"""Unit tests for MilvusAdapter."""

from unittest.mock import MagicMock, patch

import numpy as np
import pyarrow as pa
import pytest


def _make_adapter(extra_config=None):
    """Build a MilvusAdapter with all heavy dependencies mocked."""
    from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

    config = {
        "collection_name": "test_collection",
        "host": "localhost",
        "port": 19530,
    }
    if extra_config:
        config.update(extra_config)

    with (
        patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient.__init__",
            return_value=None,
        ) as _mock_client_init,
        patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.client.MilvusClient.get_client",
        ) as mock_get_client,
        patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager.MilvusIndexManager.__init__",
            return_value=None,
        ),
        patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor.MilvusBatchProcessor.__init__",
            return_value=None,
        ),
    ):
        mock_get_client.return_value = MagicMock()
        adapter = MilvusAdapter(**config)
        # Attach mock sub-components so tests can configure them
        adapter.client_manager = MagicMock()
        adapter.index_manager = MagicMock()
        adapter.batch_processor = MagicMock()

    return adapter


class TestMilvusAdapterGetConfigSchema:
    """Tests for MilvusAdapter.get_config_schema() and the MilvusConfig model."""

    def setup_method(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.config import MilvusConfig

        self.Config = MilvusConfig

    def test_returns_milvus_config_class(self):
        from pydantic import BaseModel

        from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

        schema_cls = MilvusAdapter.get_config_schema()
        assert schema_cls is self.Config
        assert issubclass(schema_cls, BaseModel)

    def test_config_schema_has_expected_fields(self):
        fields = self.Config.model_fields
        assert "collection_name" in fields
        assert "host" in fields
        assert "port" in fields
        assert "index_type" in fields
        assert "metric_type" in fields
        assert "add_sparse_vector" in fields

    def test_defaults(self):
        cfg = self.Config(collection_name="col")
        assert cfg.host == "localhost"
        assert cfg.port == 19530
        assert cfg.index_type == "HNSW"
        assert cfg.metric_type == "L2"
        assert cfg.add_sparse_vector is False
        assert cfg.batch_size == 100
        assert cfg.database == "default"
        assert cfg.secure is False
        assert cfg.index_parameters == {}

    def test_missing_collection_name_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self.Config()

    def test_extra_fields_ignored(self):
        cfg = self.Config(collection_name="col", unknown_field="value")
        assert not hasattr(cfg, "unknown_field")

    # --- Literal: index_type ---

    @pytest.mark.parametrize(
        "value",
        [
            "FLAT",
            "IVF_FLAT",
            "IVF_SQ8",
            "IVF_PQ",
            "HNSW",
            "DISKANN",
            "AUTOINDEX",
            "SPARSE_INVERTED_INDEX",
            "SPARSE_WAND",
            "BIN_FLAT",
            "BIN_IVF_FLAT",
        ],
    )
    def test_index_type_valid(self, value):
        cfg = self.Config(collection_name="col", index_type=value)
        assert cfg.index_type == value

    def test_index_type_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self.Config(collection_name="col", index_type="UNKNOWN_INDEX")

    # --- Literal: metric_type ---

    @pytest.mark.parametrize(
        "value",
        [
            "L2",
            "IP",
            "COSINE",
            "BM25",
            "HAMMING",
            "JACCARD",
            "TANIMOTO",
            "SUBSTRUCTURE",
            "SUPERSTRUCTURE",
        ],
    )
    def test_metric_type_valid(self, value):
        cfg = self.Config(collection_name="col", metric_type=value)
        assert cfg.metric_type == value

    def test_metric_type_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self.Config(collection_name="col", metric_type="EUCLIDEAN")

    # --- add_sparse_vector ---

    def test_add_sparse_vector_true(self):
        cfg = self.Config(collection_name="col", add_sparse_vector=True)
        assert cfg.add_sparse_vector is True

    # --- valid_values surfaces in JSON schema ---

    def test_index_type_enum_in_json_schema(self):
        schema = self.Config.model_json_schema()
        assert "enum" in schema["properties"]["index_type"]

    def test_metric_type_enum_in_json_schema(self):
        schema = self.Config.model_json_schema()
        assert "enum" in schema["properties"]["metric_type"]

    def test_enum_values_match_index_manager_constants(self):
        """Config Literal values must match the runtime allowlists in index_manager.py."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import (
            MilvusIndexTypes,
            MilvusMetricTypes,
        )

        schema = self.Config.model_json_schema()
        assert set(schema["properties"]["index_type"]["enum"]) == set(MilvusIndexTypes.ALL_TYPES)
        assert set(schema["properties"]["metric_type"]["enum"]) == set(MilvusMetricTypes.ALL_TYPES)


class TestMilvusAdapterRefreshIndex:
    def test_refresh_index_does_not_raise(self):
        adapter = _make_adapter()
        # Should complete without error (auto-persist path)
        adapter.refresh_index()


class TestMilvusAdapterDetectVectorDimension:
    def test_delegates_to_detect_vector_dimension_util(self):

        adapter = _make_adapter()

        table = pa.table({"embeddings": [np.random.rand(128).tolist()]})

        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter.detect_vector_dimension",
            return_value=128,
        ) as mock_detect:
            result = adapter.detect_vector_dimension(table=table, column_name="embeddings")

        mock_detect.assert_called_once_with(table=table, embeddings_column="embeddings")
        assert result == 128

    def test_uses_self_embeddings_column_when_column_name_is_none(self):
        adapter = _make_adapter()
        adapter.embeddings_column = "my_embeddings"

        table = pa.table({"my_embeddings": [np.random.rand(64).tolist()]})

        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter.detect_vector_dimension",
            return_value=64,
        ) as mock_detect:
            result = adapter.detect_vector_dimension(table=table, column_name=None)

        mock_detect.assert_called_once_with(table=table, embeddings_column="my_embeddings")
        assert result == 64


class TestMilvusAdapterDetectAllVectorDimensions:
    def test_delegates_to_detect_all_util(self):
        adapter = _make_adapter()

        table = pa.table(
            {
                "emb1": [np.random.rand(128).tolist()],
                "emb2": [np.random.rand(256).tolist()],
            }
        )

        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter.detect_all_vector_dimensions",
            return_value={"emb1": 128, "emb2": 256},
        ) as mock_detect:
            result = adapter.detect_all_vector_dimensions(table, vector_columns=["emb1", "emb2"])

        mock_detect.assert_called_once_with(table=table, vector_columns=["emb1", "emb2"])
        assert result == {"emb1": 128, "emb2": 256}


class TestMilvusAdapterMissingCollectionName:
    def test_missing_collection_name_raises_value_error(self):
        """Adapter raises ValueError when collection_name is absent — guards against invalid state."""
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

        with pytest.raises(ValueError, match="collection_name is required for the Milvus adapter"):
            MilvusAdapter(host="localhost", port=19530)
