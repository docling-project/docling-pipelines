"""Unit tests for binary-vector helpers in vectordb_utils."""

import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.operators.vectordb_utils import (
    calculate_batch_size_bytes,
    detect_vector_dimension,
    is_binary_vector_feature,
    is_dense_or_binary_vector_feature,
)


class TestIsBinaryVectorFeature:
    """Per-field binary classification is decided by the feature's own type only."""

    @pytest.mark.parametrize("type_", [OperatorConstants.Types.TYPE_VECTOR_BINARY, "vector_binary"])
    def test_binary_type_strings(self, type_):
        assert is_binary_vector_feature(feature_config={"type": type_}) is True

    def test_vector_type_binary_marker(self):
        assert is_binary_vector_feature(feature_config={"type": "vector", "vector_type": "binary"}) is True

    @pytest.mark.parametrize("config", [{"type": "vector"}, {"type": "string"}, {}, {"vector_type": "dense"}])
    def test_non_binary_features(self, config):
        assert is_binary_vector_feature(feature_config=config) is False

    def test_index_configuration_is_ignored(self):
        """Index/metric keys must never make a float field binary."""
        config = {"type": "vector", "index_type": "BIN_FLAT", "metric_type": "HAMMING"}
        assert is_binary_vector_feature(feature_config=config) is False


class TestIsDenseOrBinaryVectorFeature:
    @pytest.mark.parametrize("type_", ["vector", "vector_binary"])
    def test_vector_types(self, type_):
        assert is_dense_or_binary_vector_feature(feature_config={"type": type_}) is True

    @pytest.mark.parametrize("type_", ["string", "vector_sparse", "list"])
    def test_non_vector_types(self, type_):
        assert is_dense_or_binary_vector_feature(feature_config={"type": type_}) is False


class TestDetectVectorDimensionBinary:
    def test_flat_bytes_returns_bits(self):
        table = pa.table({"emb": pa.array([b"\x00" * 32, b"\xff" * 32], type=pa.binary())})
        assert detect_vector_dimension(table=table, embeddings_column="emb") == 256

    def test_nested_bytes_returns_bits(self):
        table = pa.table({"emb": pa.array([[b"\x00" * 16, b"\x01" * 16]], type=pa.list_(pa.binary()))})
        assert detect_vector_dimension(table=table, embeddings_column="emb") == 128

    def test_float_dimension_unchanged(self):
        table = pa.table({"emb": pa.array([[0.1, 0.2, 0.3]], type=pa.list_(pa.float32()))})
        assert detect_vector_dimension(table=table, embeddings_column="emb") == 3


class TestCalculateBatchSizeBytesBinary:
    def test_bytes_values_are_measured_not_zero(self):
        docs = [{"pk": "a", "vec": b"\x00" * 64}]
        assert calculate_batch_size_bytes(documents=docs) > 0

    def test_bytes_do_not_trigger_fallback_to_zero(self):
        docs = [{"pk": "a", "vec": bytearray(b"\x01" * 8)}]
        assert calculate_batch_size_bytes(documents=docs) > 0
