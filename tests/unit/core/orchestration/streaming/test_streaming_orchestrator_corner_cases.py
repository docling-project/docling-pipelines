# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamingOrchestrator corner cases: empty inputs and unknown operators."""

import re
from typing import Any
from uuid import UUID

import pyarrow as pa
import pytest

from docpipe.core.operators.functional.branching_operator import BranchingOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator

INGEST_ID = UUID("00000000-0000-0000-0000-000000000001")
NEXT_ID = UUID("00000000-0000-0000-0000-000000000002")
LAST_ID = UUID("00000000-0000-0000-0000-000000000003")

INGEST_CONFIG = {"provider": "filesystem", "provider_config": {"paths": ["/documents"]}, "include_filter": "pdf"}
CHUNKER_CONFIG = {"chunk_type": "simple", "chunk_size": 512, "chunk_overlap": 50, "retain_original_content": False}


def _node(
    node_id: UUID, name: str, operator: str, config: dict[str, Any], inputs: list[dict], outputs: list[dict]
) -> dict[str, Any]:
    """Build one DAG node in the runtime-flow format."""
    return {
        "id": str(node_id),
        "name": name,
        "operator": operator,
        "config": config,
        "input_edges": inputs,
        "output_edges": outputs,
    }


def _empty_ingest(self, table, *args, **kwargs):
    """Mimic ``IngestSourceOperator`` finding no documents: an empty table with the ingest columns."""
    schema = pa.schema([("id", pa.string()), ("name", pa.string()), ("document_format", pa.string())])
    return [schema.empty_table()], {}


def test_streaming_orchestrator_empty_input_skips_simple_node(mocker):
    """A simple node that receives an empty table is skipped and the empty table is passed through."""
    flow = {
        "name": "empty-linear-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(NEXT_ID, "simple_chunker", "chunker", CHUNKER_CONFIG, [{"node_id_ref": str(INGEST_ID)}], []),
        ],
    }
    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_empty_ingest)
    chunker_transform = mocker.patch.object(ChunkerOperator, "transform", autospec=True)

    outputs = StreamingOrchestrator().execute(flow=flow, params={})

    chunker_transform.assert_not_called()
    assert list(outputs) == [NEXT_ID]
    (table,) = outputs[NEXT_ID].tables
    assert table.num_rows == 0
    assert table.column_names == ["id", "name", "document_format"]


def test_streaming_orchestrator_empty_input_skips_branching_node(mocker):
    """A branching node that receives an empty table is skipped and every branch gets the empty table."""
    flow = {
        "name": "empty-branching-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(
                NEXT_ID,
                "branch_by_format",
                "branching",
                {"branches": {"branch_1": {"link_name": "pdf_documents"}}},
                [{"node_id_ref": str(INGEST_ID)}],
                [{"node_id_ref": str(LAST_ID), "link_name": "branch_1"}],
            ),
            _node(
                LAST_ID,
                "simple_chunker_1",
                "chunker",
                CHUNKER_CONFIG,
                [{"node_id_ref": str(NEXT_ID), "link_name": "branch_1"}],
                [],
            ),
        ],
    }
    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_empty_ingest)
    branching_transform = mocker.patch.object(BranchingOperator, "transform", autospec=True)
    chunker_transform = mocker.patch.object(ChunkerOperator, "transform", autospec=True)

    outputs = StreamingOrchestrator().execute(flow=flow, params={})

    branching_transform.assert_not_called()
    chunker_transform.assert_not_called()
    assert list(outputs) == [LAST_ID]
    (table,) = outputs[LAST_ID].tables
    assert table.num_rows == 0


def test_streaming_orchestrator_unknown_operator_fails():
    """A node whose operator is not registered fails with a clear error."""
    flow = {
        "name": "unknown-operator-flow",
        "dag": [_node(INGEST_ID, "mystery_step", "does_not_exist", {}, [], [])],
    }

    with pytest.raises(ValueError, match=f"^{re.escape('Operator:does_not_exist not found.')}$"):
        StreamingOrchestrator().execute(flow=flow, params={})
