"""Unit tests for LLMEmbeddingPort abstract interface."""

from typing import Any

import pytest

from docpipe.core.constants.constants import LLMConstants
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort


class _ConcreteEmbeddingPort(LLMEmbeddingPort):
    """Minimal concrete implementation for testing the base class."""

    def generate_embeddings(self, *, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def get_embedding_dimension(self) -> int:
        return 3


class _CustomValidationPort(LLMEmbeddingPort):
    """Concrete implementation that overrides validate_embedding."""

    def generate_embeddings(self, *, text: str) -> list[float]:
        return [0.5]

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        return [[0.5] for _ in texts]

    def get_embedding_dimension(self) -> int:
        return 1

    def validate_embedding(self) -> dict[str, Any]:
        return {
            LLMConstants.ValidationKeys.VALID: False,
            LLMConstants.ValidationKeys.CONTEXT: LLMConstants.ValidationContexts.EMBEDDING,
            LLMConstants.ValidationKeys.ERRORS: ["custom error"],
        }


# ---------------------------------------------------------------------------
# Default validate / validate_embedding
# ---------------------------------------------------------------------------


def test_validate_returns_valid_true_by_default():
    port = _ConcreteEmbeddingPort()
    result = port.validate()
    assert result[LLMConstants.ValidationKeys.VALID] is True


def test_validate_context_is_embedding():
    port = _ConcreteEmbeddingPort()
    result = port.validate()
    assert result[LLMConstants.ValidationKeys.CONTEXT] == LLMConstants.ValidationContexts.EMBEDDING


def test_validate_embedding_returns_valid_result():
    port = _ConcreteEmbeddingPort()
    result = port.validate_embedding()
    assert result[LLMConstants.ValidationKeys.VALID] is True
    assert result[LLMConstants.ValidationKeys.CONTEXT] == LLMConstants.ValidationContexts.EMBEDDING


def test_validate_delegates_to_validate_embedding():
    """validate() must call validate_embedding() and return its result."""
    port = _CustomValidationPort()
    result = port.validate()
    assert result[LLMConstants.ValidationKeys.VALID] is False
    assert LLMConstants.ValidationKeys.ERRORS in result


# ---------------------------------------------------------------------------
# Abstract methods are enforced
# ---------------------------------------------------------------------------


def test_cannot_instantiate_abstract_class():
    with pytest.raises(TypeError):
        LLMEmbeddingPort()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Concrete method behaviour
# ---------------------------------------------------------------------------


def test_generate_embeddings_returns_floats():
    port = _ConcreteEmbeddingPort()
    result = port.generate_embeddings(text="hello")
    assert isinstance(result, list)
    assert all(isinstance(v, float) for v in result)


def test_generate_embeddings_batch_returns_list_of_lists():
    port = _ConcreteEmbeddingPort()
    result = port.generate_embeddings_batch(texts=["a", "b"])
    assert len(result) == 2
    assert all(isinstance(row, list) for row in result)


def test_get_embedding_dimension_returns_int():
    port = _ConcreteEmbeddingPort()
    assert port.get_embedding_dimension() == 3


# ---------------------------------------------------------------------------
# Request shaping defaults
# ---------------------------------------------------------------------------


def test_default_embedding_batch_size():
    port = _ConcreteEmbeddingPort()
    assert port.get_embedding_batch_size() == 32


def test_default_max_concurrent_requests_is_serial():
    port = _ConcreteEmbeddingPort()
    assert port.get_max_concurrent_requests() == 1
