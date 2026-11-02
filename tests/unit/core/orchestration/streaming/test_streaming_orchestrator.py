# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamingOrchestrator coverage with operator transforms mocked."""

import hashlib
import json
from typing import Any
from uuid import UUID

import pyarrow as pa
import pyarrow.compute as pc

from docpipe.core.operators.extract.extract_operator import ExtractOperator
from docpipe.core.operators.functional.branching_operator import BranchingOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator

CONTENT = "# Quarterly Report\n\nRevenue grew 12% year over year.\n\nOperating costs were flat."
SOURCE = "/documents/report.pdf"
DOC_ID = "3f5e1c2a9b7d4e60a1c8d2f4b6e90713"  # pragma: allowlist secret
TEXT_CONTENT = "Meeting Notes\n\nShip the release on Friday.\n\nReview the open bugs."
TEXT_SOURCE = "/documents/notes.txt"
TEXT_DOC_ID = "9a4c7e1d5b2f48a3b6d0e8c1f7a52b64"  # pragma: allowlist secret
TEXT_METADATA = json.dumps({"source": TEXT_SOURCE, "name": "notes.txt", "extension": ".txt", "size": 412})
CONTENTS = {SOURCE: CONTENT, TEXT_SOURCE: TEXT_CONTENT}


def _ingest_transform(self, table, *args, **kwargs):
    """Mimic ``IngestSourceOperator``: no input table, one row of document metadata and no content yet."""
    document = {
        "id": DOC_ID,
        "name": "report.pdf",
        "document_format": ".pdf",
        "metadata": json.dumps({"source": SOURCE, "name": "report.pdf", "extension": ".pdf", "size": 48213}),
        "source_id": SOURCE,
        "path": SOURCE,
        "modified_time": 1730000000,
    }
    return [pa.Table.from_pylist([document])], {}


def _extract_transform(self, table, *args, **kwargs):
    """Mimic ``ExtractOperator``: add the markdown ``content``, ``pages_processed``, ``doc_id_hash`` and ``entities``."""
    contents = [CONTENTS[path] for path in table["path"].to_pylist()]  # reads the ingest output, one row per document
    table = table.append_column("content", pa.array(contents))
    table = table.append_column("pages_processed", pa.array([1] * len(contents), type=pa.int32()))
    table = table.append_column("doc_id_hash", pa.array([hashlib.sha256(c.encode()).hexdigest() for c in contents]))
    table = table.append_column("entities", pa.array(["{}"] * len(contents)))
    return [table], {}


def _chunker_transform(self, table, *args, **kwargs):
    """Mimic ``ChunkerOperator``: split ``content`` into ``chunked_content`` dicts and drop ``content``."""
    chunked_content = []
    for content in table["content"].to_pylist():
        chunks = content.split("\n\n")
        chunked_content.append(
            [
                {"chunk": chunk, "chunk_sequence_number": seq, "start_index": content.index(chunk)}
                for seq, chunk in enumerate(chunks)
            ]
        )
    table = table.drop_columns(["content"]).append_column("chunked_content", pa.array(chunked_content))
    return [table], {}


def _embeddings_transform(self, table, *args, **kwargs):
    """Mimic ``EmbeddingsOperator``: add one vector per chunk of ``chunked_content``."""
    embeddings = [
        [[len(chunk["chunk"]) / 100, 0.5, 0.25] for chunk in chunks] for chunks in table["chunked_content"].to_pylist()
    ]
    return [table.append_column("embeddings", pa.array(embeddings))], {}


def _vectordb_transform(self, table, *args, **kwargs):
    """Mimic ``VectorDBOperator``: index the rows and return the table unchanged."""
    return [table], {}


def test_streaming_orchestrator_linear(mocker, monkeypatch):
    """The orchestrator runs the linear flow in order, passing each operator's output to the next."""
    # The vector store operator reads these when it is constructed (``__init__``), before ``transform`` runs.
    monkeypatch.setenv("OPENSEARCH_USERNAME", "admin")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "password")  # pragma: allowlist secret
    node_ids = [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000003"),
        UUID("00000000-0000-0000-0000-000000000004"),
        UUID("00000000-0000-0000-0000-000000000005"),
    ]
    flow: dict[str, Any] = {
        "name": "linear-flow",
        "description": "Local PDFs to Docling extraction, simple chunks, Ollama embeddings, and OpenSearch.",
        "global_config": {
            "doc_column": "content",
            "disable_validation": False,
            "force_ingest": True,
            "data_storage_type": "local",
            "storage": "in-memory",
            "execute_type": "local",
            "enable_micro_batching": False,
        },
        "dag": [
            {
                "id": str(node_ids[0]),
                "name": "ingest_source_filesystem",
                "operator": "ingest_source",
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": ["/documents"]},
                    "include_filter": "pdf",
                },
                "input_edges": [],
                "output_edges": [{"node_id_ref": str(node_ids[1])}],
            },
            {
                "id": str(node_ids[1]),
                "name": "extract_with_docling",
                "operator": "extract_operator",
                "config": {
                    "text_extraction": {"provider": "docling_library", "doc_column": "content"},
                    "entity_extraction": {"provider": "none"},
                    "max_workers": 1,
                },
                "input_edges": [{"node_id_ref": str(node_ids[0])}],
                "output_edges": [{"node_id_ref": str(node_ids[2])}],
            },
            {
                "id": str(node_ids[2]),
                "name": "simple_chunker",
                "operator": "chunker",
                "config": {
                    "chunk_type": "simple",
                    "chunk_size": 512,
                    "chunk_overlap": 50,
                    "retain_original_content": False,
                },
                "input_edges": [{"node_id_ref": str(node_ids[1])}],
                "output_edges": [{"node_id_ref": str(node_ids[3])}],
            },
            {
                "id": str(node_ids[3]),
                "name": "ollama_embeddings",
                "operator": "embeddings",
                "config": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/nomic-embed-text",
                        "api_base": "http://ollama:11434/v1",
                        "api_key": "ollama",  # pragma: allowlist secret
                    },
                    "embeddings_column": "embeddings",
                    "overlap_ratio": 0.1,
                },
                "input_edges": [{"node_id_ref": str(node_ids[2])}],
                "output_edges": [{"node_id_ref": str(node_ids[4])}],
            },
            {
                "id": str(node_ids[4]),
                "name": "opensearch_vector_store",
                "operator": "vectordb",
                "config": {
                    "provider": "opensearch",
                    "doc_id_column": "doc_id_hash",
                    "provider_config": {
                        "index_name": "docker-e2e-documents",
                        "host": "opensearch",
                        "port": 9200,
                        "username": "${OPENSEARCH_USERNAME}",
                        "password": "${OPENSEARCH_PASSWORD}",
                        "use_ssl": False,
                        "verify_certs": False,
                        "batch_size": 100,
                        "engine": "faiss",
                        "algorithm": "hnsw",
                        "space_type": "l2",
                    },
                    "feature_mappings": [
                        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                        {"feature_name": "content", "mapped_column_name": "text"},
                        {"feature_name": "name", "mapped_column_name": "doc_name"},
                        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                    ],
                },
                "input_edges": [{"node_id_ref": str(node_ids[3])}],
                "output_edges": [],
            },
        ],
    }
    params: dict[str, Any] = {}

    fake_transforms = {
        IngestSourceOperator: _ingest_transform,
        ExtractOperator: _extract_transform,
        ChunkerOperator: _chunker_transform,
        EmbeddingsOperator: _embeddings_transform,
        VectorDBOperator: _vectordb_transform,
    }
    for operator_class, fake_transform in fake_transforms.items():
        mocker.patch.object(operator_class, "transform", autospec=True, side_effect=fake_transform)

    outputs = StreamingOrchestrator().execute(flow=flow, params=params)

    assert list(outputs) == [node_ids[4]]
    (table,) = outputs[node_ids[4]].tables
    assert table.to_pylist() == [
        {
            "id": DOC_ID,
            "name": "report.pdf",
            "document_format": ".pdf",
            "metadata": json.dumps({"source": SOURCE, "name": "report.pdf", "extension": ".pdf", "size": 48213}),
            "source_id": SOURCE,
            "path": SOURCE,
            "modified_time": 1730000000,
            "pages_processed": 1,
            "doc_id_hash": hashlib.sha256(CONTENT.encode()).hexdigest(),
            "entities": "{}",
            "chunked_content": [
                {"chunk": "# Quarterly Report", "chunk_sequence_number": 0, "start_index": 0},
                {"chunk": "Revenue grew 12% year over year.", "chunk_sequence_number": 1, "start_index": 20},
                {"chunk": "Operating costs were flat.", "chunk_sequence_number": 2, "start_index": 54},
            ],
            "embeddings": [[0.18, 0.5, 0.25], [0.32, 0.5, 0.25], [0.26, 0.5, 0.25]],
        }
    ]


def _ingest_documents_transform(self, table, *args, **kwargs):
    """Mimic ``IngestSourceOperator`` for a folder holding one PDF and one text file."""
    documents = [
        {
            "id": DOC_ID,
            "name": "report.pdf",
            "document_format": ".pdf",
            "metadata": json.dumps({"source": SOURCE, "name": "report.pdf", "extension": ".pdf", "size": 48213}),
            "source_id": SOURCE,
            "path": SOURCE,
            "modified_time": 1730000000,
        },
        {
            "id": TEXT_DOC_ID,
            "name": "notes.txt",
            "document_format": ".txt",
            "metadata": TEXT_METADATA,
            "source_id": TEXT_SOURCE,
            "path": TEXT_SOURCE,
            "modified_time": 1730000500,
        },
    ]
    return [pa.Table.from_pylist(documents)], {}


def _branching_transform(self, table, *args, **kwargs):
    """Mimic ``BranchingOperator``: one filtered table per branch, in the order the branches are configured."""
    tables = []
    branches = {}
    for index, (branch_id, branch) in enumerate(self.branch_criteria.items()):
        criteria = branch["criteria_json"]
        # PyArrow exposes generated compute kernels at runtime, but Mypy does not see them in its module stub.
        rows = table.filter(pc.equal(table[criteria["variable"]], criteria["value"]))  # type: ignore[attr-defined]
        tables.append(rows)
        branches[branch_id] = {"result_index": index, "processed_docs": rows.num_rows}
    return tables, {"branches": branches}


def test_streaming_orchestrator_branching_and_merging(mocker, monkeypatch):
    """The orchestrator splits PDF and text documents into two branches and merges them before the vector store."""
    monkeypatch.setenv("OPENSEARCH_USERNAME", "admin")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "password")  # pragma: allowlist secret
    node_ids = [UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 10)]
    (ingest_id, extract_id, branch_id, chunk_1_id, chunk_2_id, embed_1_id, embed_2_id, merge_id, store_id) = node_ids
    flow: dict[str, Any] = {
        "name": "branching-merging-flow",
        "description": "Local PDFs and text files to Docling extraction, branching by format, chunks, Ollama embeddings, merge, and OpenSearch.",
        "global_config": {
            "doc_column": "content",
            "disable_validation": False,
            "force_ingest": True,
            "data_storage_type": "local",
            "storage": "in-memory",
            "execute_type": "local",
            "enable_micro_batching": False,
        },
        "dag": [
            {
                "id": str(ingest_id),
                "name": "ingest_source_filesystem",
                "operator": "ingest_source",
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": ["/documents"]},
                    "include_filter": "pdf,txt",
                },
                "input_edges": [],
                "output_edges": [{"node_id_ref": str(extract_id)}],
            },
            {
                "id": str(extract_id),
                "name": "extract_with_docling",
                "operator": "extract_operator",
                "config": {
                    "text_extraction": {"provider": "docling_library", "doc_column": "content"},
                    "entity_extraction": {"provider": "none"},
                    "max_workers": 1,
                },
                "input_edges": [{"node_id_ref": str(ingest_id)}],
                "output_edges": [{"node_id_ref": str(branch_id)}],
            },
            {
                "id": str(branch_id),
                "name": "branch_by_format",
                "operator": "branching",
                "config": {
                    "branches": {
                        "branch_1": {
                            "link_name": "pdf_documents",
                            "criteria_json": {"variable": "document_format", "operator": "=", "value": ".pdf"},
                        },
                        "branch_2": {
                            "link_name": "text_documents",
                            "criteria_json": {"variable": "document_format", "operator": "=", "value": ".txt"},
                        },
                    },
                },
                "input_edges": [{"node_id_ref": str(extract_id)}],
                "output_edges": [
                    {"node_id_ref": str(chunk_1_id), "link_name": "branch_1"},
                    {"node_id_ref": str(chunk_2_id), "link_name": "branch_2"},
                ],
            },
            {
                "id": str(chunk_1_id),
                "name": "simple_chunker_1",
                "operator": "chunker",
                "config": {
                    "chunk_type": "simple",
                    "chunk_size": 512,
                    "chunk_overlap": 50,
                    "retain_original_content": False,
                },
                "input_edges": [{"node_id_ref": str(branch_id), "link_name": "branch_1"}],
                "output_edges": [{"node_id_ref": str(embed_1_id)}],
            },
            {
                "id": str(chunk_2_id),
                "name": "simple_chunker_2",
                "operator": "chunker",
                "config": {
                    "chunk_type": "simple",
                    "chunk_size": 512,
                    "chunk_overlap": 50,
                    "retain_original_content": False,
                },
                "input_edges": [{"node_id_ref": str(branch_id), "link_name": "branch_2"}],
                "output_edges": [{"node_id_ref": str(embed_2_id)}],
            },
            {
                "id": str(embed_1_id),
                "name": "ollama_embeddings_1",
                "operator": "embeddings",
                "config": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/nomic-embed-text",
                        "api_base": "http://ollama:11434/v1",
                        "api_key": "ollama",  # pragma: allowlist secret
                    },
                    "embeddings_column": "embeddings",
                    "overlap_ratio": 0.1,
                },
                "input_edges": [{"node_id_ref": str(chunk_1_id)}],
                "output_edges": [{"node_id_ref": str(merge_id)}],
            },
            {
                "id": str(embed_2_id),
                "name": "ollama_embeddings_2",
                "operator": "embeddings",
                "config": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/nomic-embed-text",
                        "api_base": "http://ollama:11434/v1",
                        "api_key": "ollama",  # pragma: allowlist secret
                    },
                    "embeddings_column": "embeddings",
                    "overlap_ratio": 0.1,
                },
                "input_edges": [{"node_id_ref": str(chunk_2_id)}],
                "output_edges": [{"node_id_ref": str(merge_id)}],
            },
            {
                "id": str(merge_id),
                "name": "merge_branches",
                "operator": "merge",
                "config": {
                    "merge_type": "rows",
                    # The engine finds each merge input through ``node_id_ref``, so it is added to the builder test's links.
                    "input_links": [
                        {"node_id_ref": str(embed_1_id), "link_name": "ollama_embeddings_1"},
                        {"node_id_ref": str(embed_2_id), "link_name": "ollama_embeddings_2"},
                    ],
                },
                "input_edges": [{"node_id_ref": str(embed_1_id)}, {"node_id_ref": str(embed_2_id)}],
                "output_edges": [{"node_id_ref": str(store_id)}],
            },
            {
                "id": str(store_id),
                "name": "opensearch_vector_store",
                "operator": "vectordb",
                "config": {
                    "provider": "opensearch",
                    "doc_id_column": "doc_id_hash",
                    "provider_config": {
                        "index_name": "docker-e2e-documents",
                        "host": "opensearch",
                        "port": 9200,
                        "username": "${OPENSEARCH_USERNAME}",
                        "password": "${OPENSEARCH_PASSWORD}",
                        "use_ssl": False,
                        "verify_certs": False,
                        "batch_size": 100,
                        "engine": "faiss",
                        "algorithm": "hnsw",
                        "space_type": "l2",
                    },
                    "feature_mappings": [
                        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                        {"feature_name": "content", "mapped_column_name": "text"},
                        {"feature_name": "name", "mapped_column_name": "doc_name"},
                        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                    ],
                },
                "input_edges": [{"node_id_ref": str(merge_id)}],
                "output_edges": [],
            },
        ],
    }
    params: dict[str, Any] = {}

    fake_transforms = {
        IngestSourceOperator: _ingest_documents_transform,
        ExtractOperator: _extract_transform,
        BranchingOperator: _branching_transform,
        ChunkerOperator: _chunker_transform,
        EmbeddingsOperator: _embeddings_transform,
        VectorDBOperator: _vectordb_transform,
    }
    for operator_class, fake_transform in fake_transforms.items():
        mocker.patch.object(operator_class, "transform", autospec=True, side_effect=fake_transform)

    outputs = StreamingOrchestrator().execute(flow=flow, params=params)

    assert list(outputs) == [store_id]
    (table,) = outputs[store_id].tables
    assert table.to_pylist() == [
        {
            "id": DOC_ID,
            "name": "report.pdf",
            "document_format": ".pdf",
            "metadata": json.dumps({"source": SOURCE, "name": "report.pdf", "extension": ".pdf", "size": 48213}),
            "source_id": SOURCE,
            "path": SOURCE,
            "modified_time": 1730000000,
            "pages_processed": 1,
            "doc_id_hash": hashlib.sha256(CONTENT.encode()).hexdigest(),
            "entities": "{}",
            "chunked_content": [
                {"chunk": "# Quarterly Report", "chunk_sequence_number": 0, "start_index": 0},
                {"chunk": "Revenue grew 12% year over year.", "chunk_sequence_number": 1, "start_index": 20},
                {"chunk": "Operating costs were flat.", "chunk_sequence_number": 2, "start_index": 54},
            ],
            "embeddings": [[0.18, 0.5, 0.25], [0.32, 0.5, 0.25], [0.26, 0.5, 0.25]],
        },
        {
            "id": TEXT_DOC_ID,
            "name": "notes.txt",
            "document_format": ".txt",
            "metadata": TEXT_METADATA,
            "source_id": TEXT_SOURCE,
            "path": TEXT_SOURCE,
            "modified_time": 1730000500,
            "pages_processed": 1,
            "doc_id_hash": hashlib.sha256(TEXT_CONTENT.encode()).hexdigest(),
            "entities": "{}",
            "chunked_content": [
                {"chunk": "Meeting Notes", "chunk_sequence_number": 0, "start_index": 0},
                {"chunk": "Ship the release on Friday.", "chunk_sequence_number": 1, "start_index": 15},
                {"chunk": "Review the open bugs.", "chunk_sequence_number": 2, "start_index": 44},
            ],
            "embeddings": [[0.13, 0.5, 0.25], [0.27, 0.5, 0.25], [0.21, 0.5, 0.25]],
        },
    ]
