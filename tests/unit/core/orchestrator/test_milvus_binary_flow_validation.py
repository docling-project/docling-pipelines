"""Validator-level tests: /validate_flow rejects BIN_* indexes without a binary vector feature."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.assets.flows.application.services.validation_service import ValidationService

SAMPLE_FLOW = Path(__file__).resolve().parents[4] / "sample_flows" / "vectordb" / "milvus_binary_integration.json"


@pytest.fixture(autouse=True)
def _mock_milvus_connection() -> Iterator[MagicMock]:
    """Validation instantiates the Milvus adapter, which connects on init; keep the tests offline."""
    with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.PyMilvusClient") as mock_client:
        yield mock_client


def _load_flow() -> dict[str, Any]:
    return json.loads(SAMPLE_FLOW.read_text())


def _validate(*, flow_definition: dict[str, Any]) -> dict[str, Any]:
    return ValidationService().validate_flow(flow_definition=flow_definition, is_elyra=False)


def test_binary_sample_flow_validates_as_shipped() -> None:
    """The committed sample (quantization: binary + BIN_IVF_FLAT) passes validation."""
    result = _validate(flow_definition=_load_flow())

    assert result["status"] == "SUCCEEDED", result.get("errors")


def test_bin_index_without_quantization_fails_validation() -> None:
    """Dropping quantization leaves no binary vector feature, so the BIN_* index is rejected."""
    flow_definition = copy.deepcopy(_load_flow())
    embeddings_node = next(node for node in flow_definition["flow"] if node["type"] == "embeddings")
    del embeddings_node["config"]["quantization"]

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "requires a binary vector feature" in json.dumps(result.get("errors"))
