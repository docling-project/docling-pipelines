# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the index selection ``applicability`` metadata of the Milvus and OpenSearch providers.

The metadata is built from the constants the index managers validate against. The parity tests below
pin that every combination the metadata allows passes validation and every combination it omits fails.
"""

from itertools import product
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.milvus.config import MilvusConfig
from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import (
    MilvusIndexManager,
    MilvusIndexTypes,
    MilvusMetricTypes,
)
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.config import OpenSearchConfig
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.index_manager import OpenSearchIndexManager
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.exceptions.docpipe_exceptions import DocpipeException


def _families_by_id() -> dict[str, dict]:
    return {family["id"]: family for family in MilvusConfig.applicability()["index_families"]}


class TestMilvusApplicabilityContent:
    def test_families_match_constants(self):
        families = _families_by_id()
        assert set(families) == {"cpu_dense", "gpu", "binary"}
        assert families["cpu_dense"]["index_types"] == [
            "FLAT",
            "IVF_FLAT",
            "IVF_SQ8",
            "IVF_PQ",
            "HNSW",
            "DISKANN",
            "AUTOINDEX",
        ]
        assert families["cpu_dense"]["metric_types"] == ["L2", "IP", "COSINE"]
        assert families["gpu"]["index_types"] == ["GPU_CAGRA", "GPU_IVF_FLAT", "GPU_IVF_PQ", "GPU_BRUTE_FORCE"]
        assert families["gpu"]["metric_types"] == ["L2", "IP"]
        assert families["binary"]["index_types"] == ["BIN_FLAT", "BIN_IVF_FLAT"]
        assert families["binary"]["metric_types"] == ["HAMMING", "JACCARD"]

    def test_feature_types_per_family(self):
        families = _families_by_id()
        assert families["cpu_dense"]["feature_types"] == ["vector"]
        assert families["gpu"]["feature_types"] == ["vector"]
        assert families["binary"]["feature_types"] == ["vector_binary"]

    def test_lite_subset_and_default(self):
        assert MilvusConfig.applicability()["lite"] == {"index_types": ["FLAT"], "default": "FLAT"}

    def test_families_cover_exactly_the_selectable_index_types(self):
        """No sparse type appears, and every selectable type belongs to one family."""
        in_families = [t for family in _families_by_id().values() for t in family["index_types"]]
        assert len(in_families) == len(set(in_families))
        assert set(in_families) == set(MilvusConfig.model_json_schema()["properties"]["index_type"]["enum"])
        assert set(in_families).isdisjoint(MilvusIndexTypes.ALL_SPARSE_TYPES)

    def test_applicability_returns_fresh_lists(self):
        """Mutating a returned block must not alter the shared constants."""
        MilvusConfig.applicability()["index_families"][0]["index_types"].append("X")
        assert "X" not in MilvusIndexTypes.ALL_DENSE_TYPES


class TestOpenSearchApplicabilityContent:
    def test_engine_algorithm_map(self):
        assert OpenSearchConfig.applicability() == {
            "engine_algorithms": {
                "faiss": ["hnsw", "ivf"],
                "lucene": ["hnsw"],
                "nmslib": ["hnsw"],
                "jvector": ["hnsw"],
            }
        }

    def test_engines_and_algorithms_match_config_enums(self):
        schema = OpenSearchConfig.model_json_schema()["properties"]
        engine_algorithms = OpenSearchConfig.applicability()["engine_algorithms"]
        assert set(engine_algorithms) == set(schema["engine"]["enum"])
        assert {a for algos in engine_algorithms.values() for a in algos} <= set(schema["algorithm"]["enum"])


class TestApplicabilityInOperatorMetadata:
    @pytest.fixture(scope="class")
    def providers(self):
        return VectorDBOperator.get_metadata()["attributes"]["provider_config"]["providers"]

    def test_milvus_block_attached(self, providers):
        assert providers["milvus"]["applicability"] == MilvusConfig.applicability()

    def test_opensearch_block_attached(self, providers):
        assert providers["opensearch"]["applicability"] == OpenSearchConfig.applicability()

    def test_weaviate_has_no_block(self, providers):
        assert "applicability" not in providers["weaviate"]

    def test_existing_defaults_and_values_unchanged(self, providers):
        milvus = providers["milvus"]["properties"]
        assert milvus["index_type"]["default"] == "HNSW"
        assert milvus["metric_type"]["default"] == "L2"
        assert milvus["metric_type"]["valid_values"] == ["L2", "IP", "COSINE", "BM25", "HAMMING", "JACCARD"]
        assert milvus["vector_mode"]["valid_values"] == ["dense", "sparse", "binary", "gpu"]
        opensearch = providers["opensearch"]["properties"]
        assert opensearch["engine"]["valid_values"] == ["faiss", "lucene", "nmslib", "jvector"]
        assert opensearch["algorithm"]["valid_values"] == ["hnsw", "ivf"]
        assert opensearch["algorithm"]["default"] == "hnsw"
        assert opensearch["space_type"]["valid_values"] == ["l2", "cosine", "inner_product"]


def _milvus_validation_error(*, index_type: str, metric_type: str, is_lite: bool = False) -> DocpipeException | None:
    """Build a Milvus index manager for ``index_type``/``metric_type`` and return the validation error, if any."""
    try:
        MilvusIndexManager(
            client=MagicMock(),
            collection_name="parity",
            index_type=index_type,
            metric_type=metric_type,
            is_lite=is_lite,
        )
    except DocpipeException as exc:
        return exc
    return None


class TestMilvusApplicabilityParity:
    """Allowed (index_type, metric_type) pairs pass the index manager; every other pair fails."""

    @staticmethod
    def _allowed_pairs() -> set[tuple[str, str]]:
        return {
            (index_type, metric)
            for family in MilvusConfig.applicability()["index_families"]
            for index_type in family["index_types"]
            for metric in family["metric_types"]
        }

    @staticmethod
    def _selectable_index_types() -> list[str]:
        return list(MilvusConfig.model_json_schema()["properties"]["index_type"]["enum"])

    def test_allowed_pairs_pass_validation(self):
        failures = [
            (index_type, metric, str(error))
            for index_type, metric in sorted(self._allowed_pairs())
            if (error := _milvus_validation_error(index_type=index_type, metric_type=metric)) is not None
        ]
        assert failures == []

    def test_pairs_outside_applicability_fail_validation(self):
        # BM25 is a valid config metric but belongs to the sparse field, so it is never applicable to these.
        all_metrics = list(MilvusMetricTypes.ALL_TYPES)
        unexpectedly_passing = [
            (index_type, metric)
            for index_type, metric in product(self._selectable_index_types(), all_metrics)
            if (index_type, metric) not in self._allowed_pairs()
            and _milvus_validation_error(index_type=index_type, metric_type=metric) is None
        ]
        assert unexpectedly_passing == []

    def test_lite_allows_only_the_lite_subset(self):
        lite = MilvusConfig.applicability()["lite"]
        for index_type in self._selectable_index_types():
            error = _milvus_validation_error(index_type=index_type, metric_type="L2", is_lite=True)
            if index_type in lite["index_types"]:
                assert error is None, f"{index_type} should work on Lite: {error}"
            else:
                assert error is not None, f"{index_type} should be rejected on Lite"


class TestOpenSearchApplicabilityParity:
    """Allowed (engine, algorithm) pairs pass the index manager; every other pair fails."""

    @staticmethod
    def _build(*, engine: str, algorithm: str) -> DocpipeException | None:
        try:
            OpenSearchIndexManager(client=MagicMock(), index_name="parity", engine=engine, algorithm=algorithm)
        except DocpipeException as exc:
            return exc
        return None

    def test_allowed_pairs_pass_validation(self):
        for engine, algorithms in OpenSearchConfig.applicability()["engine_algorithms"].items():
            for algorithm in algorithms:
                assert self._build(engine=engine, algorithm=algorithm) is None, f"{engine}/{algorithm}"

    def test_pairs_outside_the_map_fail_validation(self):
        engine_algorithms = OpenSearchConfig.applicability()["engine_algorithms"]
        every_algorithm = {a for algos in engine_algorithms.values() for a in algos}
        for engine, algorithms in engine_algorithms.items():
            for algorithm in every_algorithm - set(algorithms):
                error = self._build(engine=engine, algorithm=algorithm)
                assert error is not None, f"{engine}/{algorithm} should be rejected"
                assert engine in str(error) and algorithm in str(error)


class TestIndexMismatchMessages:
    """Mismatch errors name the offending values and the accepted alternatives."""

    def test_opensearch_algorithm_not_supported_by_engine(self):
        error = TestOpenSearchApplicabilityParity._build(engine="lucene", algorithm="ivf")
        assert error is not None
        message = str(error)
        assert "'ivf'" in message
        assert "'lucene'" in message
        assert "['hnsw']" in message

    def test_milvus_gpu_index_with_cosine(self):
        error = _milvus_validation_error(index_type="GPU_CAGRA", metric_type="COSINE")
        assert error is not None
        message = str(error)
        assert "GPU_CAGRA" in message
        assert "COSINE" in message
        assert "['L2', 'IP']" in message

    def test_milvus_binary_index_with_l2(self):
        error = _milvus_validation_error(index_type="BIN_FLAT", metric_type="L2")
        assert error is not None
        message = str(error)
        assert "BIN_FLAT" in message
        assert "L2" in message
        assert "['HAMMING', 'JACCARD']" in message

    def test_milvus_non_flat_index_on_lite(self):
        error = _milvus_validation_error(index_type="HNSW", metric_type="L2", is_lite=True)
        assert error is not None
        message = str(error)
        assert "HNSW" in message
        assert "['FLAT']" in message

    def test_milvus_gpu_index_on_lite(self):
        error = _milvus_validation_error(index_type="GPU_CAGRA", metric_type="L2", is_lite=True)
        assert error is not None
        assert "GPU_CAGRA" in str(error)
        assert "FLAT" in str(error)

    def test_milvus_binary_index_without_binary_feature(self):
        manager = MilvusIndexManager(
            client=MagicMock(), collection_name="parity", index_type="BIN_FLAT", metric_type="HAMMING"
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector"})
        message = str(exc_info.value)
        assert "BIN_FLAT" in message
        assert "binary vector feature" in message

    def test_milvus_binary_feature_on_lite(self):
        manager = MilvusIndexManager(
            client=MagicMock(), collection_name="parity", index_type="FLAT", metric_type="L2", is_lite=True
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})
        assert "Milvus Lite" in str(exc_info.value)

    def test_milvus_gpu_index_with_only_binary_features(self):
        manager = MilvusIndexManager(
            client=MagicMock(), collection_name="parity", index_type="GPU_CAGRA", metric_type="L2", vector_mode="gpu"
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_vector_feature_types(feature_types={"embeddings": "vector_binary"})
        assert "GPU_CAGRA" in str(exc_info.value)

    def test_valid_selection_reports_no_error(self):
        assert _milvus_validation_error(index_type="IVF_FLAT", metric_type="COSINE") is None
        assert TestOpenSearchApplicabilityParity._build(engine="faiss", algorithm="ivf") is None


class TestIndexMismatchThroughOperator:
    """Mismatches surface from VectorDBOperator during flow validation, before any client is created."""

    _MILVUS = "docpipe.core.operators.vectordb.adapters.outbound.milvus"
    _OPENSEARCH = "docpipe.core.operators.vectordb.adapters.outbound.opensearch"

    @staticmethod
    def _config(*, provider: str, provider_config: dict) -> dict:
        return {"provider": provider, "provider_config": provider_config, "validating_flow": True}

    def test_milvus_gpu_with_cosine_is_reported_without_a_client(self):
        config = self._config(
            provider="milvus",
            provider_config={
                "collection_name": "c",
                "index_type": "GPU_CAGRA",
                "metric_type": "COSINE",
                "vector_mode": "gpu",
            },
        )
        with patch(f"{self._MILVUS}.adapter.MilvusClient") as mock_client_cls:
            with pytest.raises(DocpipeException) as exc_info:
                VectorDBOperator(config)
        message = str(exc_info.value)
        assert "GPU_CAGRA" in message and "COSINE" in message and "['L2', 'IP']" in message
        mock_client_cls.assert_not_called()

    def test_milvus_lite_with_hnsw_is_reported_without_a_client(self):
        config = self._config(
            provider="milvus",
            provider_config={"collection_name": "c", "auth_type": "lite", "uri": "./d.db", "index_type": "HNSW"},
        )
        with patch(f"{self._MILVUS}.adapter.MilvusClient") as mock_client_cls:
            with pytest.raises(DocpipeException) as exc_info:
                VectorDBOperator(config)
        assert "HNSW" in str(exc_info.value) and "FLAT" in str(exc_info.value)
        mock_client_cls.assert_not_called()

    def test_milvus_lite_without_index_type_builds(self):
        config = self._config(
            provider="milvus",
            provider_config={"collection_name": "c", "auth_type": "lite", "uri": "./d.db"},
        )
        with (
            patch(f"{self._MILVUS}.adapter.MilvusClient") as mock_client_cls,
            patch(f"{self._MILVUS}.batch_processor.MilvusBatchProcessor.__init__", return_value=None),
        ):
            mock_client_cls.return_value.get_client.return_value = MagicMock()
            operator = VectorDBOperator(config)
        assert operator.adapter.index_manager.index_type == "FLAT"

    def test_opensearch_engine_algorithm_mismatch_is_reported_before_index_creation(self):
        config = self._config(
            provider="opensearch",
            provider_config={"index_name": "i", "engine": "lucene", "algorithm": "ivf"},
        )
        with patch(f"{self._OPENSEARCH}.client.OpenSearch") as mock_client_cls:
            with pytest.raises(DocpipeException) as exc_info:
                VectorDBOperator(config)
        message = str(exc_info.value)
        assert "'ivf'" in message and "'lucene'" in message and "['hnsw']" in message
        # OpenSearch connects before its index manager validates, so the guarantee is that no index is created.
        mock_client_cls.return_value.indices.create.assert_not_called()
