# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""The extract operator hands the adapters what the on-demand fetch needs (task B.4)."""

from docpipe.core.operators.extract.extract_operator import ExtractOperator


def _config(*, with_flow_definition: bool) -> dict:
    config: dict = {
        "text_extraction": {"provider": "docling_library"},
        "entity_extraction": {"provider": "none"},
        "ingest_source": {"provider": "s3", "node_id": "ingest_node", "provider_config": {}},
    }
    if with_flow_definition:
        config["flow_definition"] = {"dag": [{"id": "ingest_node", "config": {"provider": "s3"}}]}
    return config


def test_flow_definition_reaches_the_text_adapter() -> None:
    operator = ExtractOperator(config=_config(with_flow_definition=True))

    assert operator.text_adapter.global_config["flow_definition"]["dag"][0]["id"] == "ingest_node"
    assert operator.text_adapter.global_config["ingest_source"]["node_id"] == "ingest_node"


def test_no_flow_definition_is_added_when_none_was_given() -> None:
    operator = ExtractOperator(config=_config(with_flow_definition=False))

    assert "flow_definition" not in operator.text_adapter.global_config
