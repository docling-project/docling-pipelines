# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Guard the Weaviate sample flow against drift from the adapter config schema."""

import json
from pathlib import Path
from typing import Any

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.weaviate.config import WeaviateConfig

SAMPLE_FLOW_PATH = Path(__file__).resolve().parents[4] / "sample_flows" / "vectordb" / "weaviate_integration.json"


@pytest.fixture(scope="module")
def vectordb_node() -> dict[str, Any]:
    flow = json.loads(SAMPLE_FLOW_PATH.read_text(encoding="utf-8"))
    nodes = [node for node in flow["flow"] if node["type"] == "vectordb"]
    assert len(nodes) == 1
    return nodes[0]


def test_sample_flow_uses_weaviate_provider(vectordb_node: dict[str, Any]) -> None:
    assert vectordb_node["config"]["provider"] == "weaviate"


def test_sample_flow_provider_config_is_valid(vectordb_node: dict[str, Any]) -> None:
    WeaviateConfig(**vectordb_node["config"]["provider_config"])


def test_sample_flow_provider_config_has_no_unknown_keys(vectordb_node: dict[str, Any]) -> None:
    """WeaviateConfig ignores extra keys, so a renamed field would otherwise go unnoticed."""
    unknown = set(vectordb_node["config"]["provider_config"]) - set(WeaviateConfig.model_fields)
    assert not unknown
