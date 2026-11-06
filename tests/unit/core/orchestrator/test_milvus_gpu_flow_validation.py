# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Validator-level tests: /validate_flow rejects invalid Milvus GPU / vector_mode configurations."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.assets.flows.application.services.validation_service import ValidationService

SAMPLE_FLOW = Path(__file__).resolve().parents[4] / "sample_flows" / "vectordb" / "milvus_gpu_integration.json"
BINARY_SAMPLE_FLOW = (
    Path(__file__).resolve().parents[4] / "sample_flows" / "vectordb" / "milvus_binary_integration.json"
)


@pytest.fixture(autouse=True)
def _mock_milvus_connection() -> Iterator[MagicMock]:
    """Validation instantiates the Milvus adapter, which connects on init; keep the tests offline."""
    with patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.client.PyMilvusClient") as mock_client:
        yield mock_client


def _load_flow(*, path: Path = SAMPLE_FLOW) -> dict[str, Any]:
    return json.loads(path.read_text())


def _provider_config(*, flow_definition: dict[str, Any]) -> dict[str, Any]:
    node = next(node for node in flow_definition["flow"] if node["type"] == "vectordb")
    return node["config"]["provider_config"]


def _validate(*, flow_definition: dict[str, Any]) -> dict[str, Any]:
    return ValidationService().validate_flow(flow_definition=flow_definition, is_elyra=False)


def test_gpu_sample_flow_validates_as_shipped() -> None:
    """The committed GPU sample (vector_mode gpu + GPU_CAGRA + L2) passes validation."""
    result = _validate(flow_definition=_load_flow())

    assert result["status"] == "SUCCEEDED", result.get("errors")


def test_gpu_with_cosine_metric_fails_validation() -> None:
    flow_definition = copy.deepcopy(_load_flow())
    _provider_config(flow_definition=flow_definition)["metric_type"] = "COSINE"

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "does not support metric 'COSINE'" in json.dumps(result.get("errors"))


def test_gpu_cagra_graph_degree_above_intermediate_fails_validation() -> None:
    flow_definition = copy.deepcopy(_load_flow())
    _provider_config(flow_definition=flow_definition)["index_parameters"] = {
        "graph_degree": 64,
        "intermediate_graph_degree": 32,
    }

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "graph_degree" in json.dumps(result.get("errors"))


def test_gpu_with_cpu_index_type_fails_validation() -> None:
    flow_definition = copy.deepcopy(_load_flow())
    _provider_config(flow_definition=flow_definition)["index_type"] = "HNSW"

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "not supported in vector_mode='gpu'" in json.dumps(result.get("errors"))


def test_gpu_on_milvus_lite_fails_validation() -> None:
    flow_definition = copy.deepcopy(_load_flow())
    provider_config = _provider_config(flow_definition=flow_definition)
    provider_config["auth_type"] = "lite"
    provider_config["uri"] = "./data/milvus/gpu.db"

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "not supported by Milvus Lite" in json.dumps(result.get("errors"))


def test_invalid_vector_mode_fails_validation() -> None:
    flow_definition = copy.deepcopy(_load_flow())
    _provider_config(flow_definition=flow_definition)["vector_mode"] = "quantum"

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"


def test_gpu_with_binary_only_vectors_fails_validation() -> None:
    """GPU indexes cannot index binary vectors: a quantized (binary-only) flow must not claim GPU mode."""
    flow_definition = copy.deepcopy(_load_flow(path=BINARY_SAMPLE_FLOW))
    provider_config = _provider_config(flow_definition=flow_definition)
    provider_config["vector_mode"] = "gpu"
    provider_config["index_type"] = "GPU_CAGRA"
    provider_config["metric_type"] = "L2"

    result = _validate(flow_definition=flow_definition)

    assert result["status"] == "FAILED"
    assert "only applies to dense float vectors" in json.dumps(result.get("errors"))
