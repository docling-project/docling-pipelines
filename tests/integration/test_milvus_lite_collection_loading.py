#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Integration tests: Milvus Lite collection loading across process restarts.

A Milvus Lite collection written by one process is reported ``NotLoad`` when a new process
reopens the database, and queries against it fail with code 101 until it is loaded. The
writer and the reader each run in their own interpreter, and the writer exits before the
reader starts, because the Lite server keeps the ``.db`` file locked while its process is
alive. Everything runs in a temporary directory; no shared collection is touched.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pymilvus")
pytest.importorskip("milvus_lite")

COLLECTION = "lite_load_regression"
DIM = 4

WRITER_SCRIPT = """
import json
import sys

from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

cfg = json.loads(sys.argv[1])
adapter = MilvusAdapter(**cfg)
try:
    adapter.create_index(dimension_mapping={"embeddings": cfg["dim"]})
    documents = [
        (pk, {"doc_id_hash": pk, "embeddings": [0.1, 0.2, 0.3, 0.4], "content": "text"})
        for pk in cfg["pks"]
    ]
    adapter.index_documents(documents)
finally:
    adapter.close()
"""

READER_SCRIPT = """
import json
import sys

from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter
from docpipe.exceptions.docpipe_exceptions import DocpipeException

cfg = json.loads(sys.argv[1])
adapter = MilvusAdapter(**cfg)
result = {}
try:
    try:
        result["rows"] = [r["pk"] for r in adapter.query_by_doc_names(doc_names=cfg["query_names"])]
    except DocpipeException as exc:
        result["error"] = str(exc)
    if cfg.get("chunk_file_id"):
        found = adapter.get_chunk_ids_for_documents(doc_ids=[cfg["chunk_file_id"]])
        result["chunk_pks"] = sorted(found.get(cfg["chunk_file_id"], set()))
finally:
    adapter.close()
print("RESULT=" + json.dumps(result))
"""


def _adapter_config(*, db_path: str, collection: str = COLLECTION) -> dict:
    return {
        "collection_name": collection,
        "auth_type": "lite",
        "uri": db_path,
        "index_type": "FLAT",
        "metric_type": "COSINE",
        "batch_size": 100,
        "embeddings_column": "embeddings",
        "vector_dimension": DIM,
        "available_features": {
            "doc_id_hash": {
                "type": "string",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "is_primary": True,
            },
            "embeddings": {"type": "vector", "available_for_vector_db": True, "mandatory_for_vector_db": True},
            "content": {"type": "string", "available_for_vector_db": True},
        },
        "feature_mappings": [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            {"feature_name": "content", "mapped_column_name": "text"},
        ],
    }


def _run_in_process(*, script: str, payload: dict) -> dict:
    """Run a script in a fresh interpreter and return its parsed RESULT line (if any)."""
    completed = subprocess.run(
        [sys.executable, "-c", script, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result_lines = [ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT=")]
    return json.loads(result_lines[0][len("RESULT=") :]) if result_lines else {}


def _write_in_child_process(*, db_path: str, pks: list[str]) -> None:
    """Create the collection and insert rows in a separate process, which exits before returning."""
    _run_in_process(
        script=WRITER_SCRIPT,
        payload={**_adapter_config(db_path=db_path), "dim": DIM, "pks": pks},
    )


def _read_in_child_process(*, db_path: str, query_names: list[str], chunk_file_id: str | None = None) -> dict:
    """Open the collection in a new process and query it, the way a later run does."""
    payload = {**_adapter_config(db_path=db_path), "query_names": query_names}
    if chunk_file_id is not None:
        payload["chunk_file_id"] = chunk_file_id
    return _run_in_process(script=READER_SCRIPT, payload=payload)


@pytest.mark.integration
class TestMilvusLiteCollectionLoading:
    """Collection loading and query behavior against a real Milvus Lite database."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "milvus" / "lite_load.db")

    def test_reopened_collection_is_loaded_before_query(self, db_path: str) -> None:
        """Written by one process, the collection must answer queries from a new process."""
        _write_in_child_process(db_path=db_path, pks=["doc_a", "doc_b"])

        result = _read_in_child_process(db_path=db_path, query_names=["doc_a"])

        assert "error" not in result, f"query failed after reopen: {result.get('error')}"
        assert result["rows"] == ["doc_a"]

    def test_query_with_no_matching_records_returns_empty_list(self, db_path: str) -> None:
        """A successful query with no hits returns [] and is not reported as an error."""
        _write_in_child_process(db_path=db_path, pks=["doc_a"])

        result = _read_in_child_process(db_path=db_path, query_names=["no_such_chunk"])

        assert result == {"rows": []}

    def test_query_on_missing_collection_returns_empty_list(self, db_path: str) -> None:
        """First-run cleanup against a collection that does not exist must return empty, not fail."""
        # The database file exists but the collection was never created.
        _write_in_child_process(db_path=db_path, pks=[])
        cfg = _adapter_config(db_path=db_path, collection="never_created")
        payload = {**cfg, "query_names": ["doc_a"]}
        result = _run_in_process(script=READER_SCRIPT, payload=payload)

        assert result == {"rows": []}

    def test_stale_chunk_lookup_returns_stored_pks_after_reopen(self, db_path: str) -> None:
        """Stale-chunk cleanup needs the stored chunk PKs for a file after the store is reopened."""
        file_id = "/docs/file_a.pdf"
        chunk_pk = f"{hashlib.sha3_512(file_id.encode()).hexdigest()}_contenthash"
        _write_in_child_process(db_path=db_path, pks=[chunk_pk])

        result = _read_in_child_process(db_path=db_path, query_names=[], chunk_file_id=file_id)

        assert result["chunk_pks"] == [chunk_pk]

    def test_stale_chunk_lookup_on_missing_collection_returns_empty(self, db_path: str) -> None:
        """First-run stale cleanup on a missing collection finds nothing and does not fail."""
        _write_in_child_process(db_path=db_path, pks=[])
        cfg = _adapter_config(db_path=db_path, collection="never_created")
        payload = {**cfg, "query_names": [], "chunk_file_id": "/docs/file_a.pdf"}
        result = _run_in_process(script=READER_SCRIPT, payload=payload)

        assert result["chunk_pks"] == []
