"""Unit tests for OpenSearchAdapter flow-validation hooks."""

from unittest.mock import MagicMock

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter import OpenSearchAdapter
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestValidateVectorFeatureTypes:
    """validate_vector_feature_types rejects binary vector features, which OpenSearch cannot index."""

    @staticmethod
    def _validate(*, feature_types: dict[str, str | None]) -> None:
        # The hook does not read instance state, so a mock instance avoids opening a connection.
        OpenSearchAdapter.validate_vector_feature_types(MagicMock(), feature_types=feature_types)

    def test_rejects_binary_vector_feature(self) -> None:
        with pytest.raises(DocpipeException, match=r"Binary vector features are not supported.*embeddings"):
            self._validate(feature_types={"embeddings": "vector_binary", "content": "string"})

    def test_accepts_dense_vector_feature(self) -> None:
        self._validate(feature_types={"embeddings": "vector", "content": "string"})

    def test_accepts_untyped_features(self) -> None:
        self._validate(feature_types={"embeddings": None})
