#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Integration tests: Milvus server collection loading and query error handling.

Runs against a real Milvus server (default ``127.0.0.1:19530``; override with
``DOCPIPE_TEST_MILVUS_HOST`` / ``DOCPIPE_TEST_MILVUS_PORT``) and is skipped when none is reachable.

Every test creates its own collection under the ``docpipe_it_`` prefix and drops it afterwards.
Cleanup refuses to drop any collection without that prefix, so collections that already exist on the
server are never touched.
"""

import hashlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("pymilvus")

from pymilvus import MilvusClient
from pymilvus.client.types import LoadState

from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode

HOST = os.environ.get("DOCPIPE_TEST_MILVUS_HOST", "127.0.0.1")
PORT = int(os.environ.get("DOCPIPE_TEST_MILVUS_PORT", "19530"))
PREFIX = "docpipe_it_"
DIM = 4


def _server_reachable() -> bool:
    try:
        MilvusClient(uri=f"http://{HOST}:{PORT}", timeout=5).list_collections()
    except Exception:
        return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _server_reachable(), reason=f"Milvus server not reachable at {HOST}:{PORT}"),
]


def _adapter_config(*, collection: str) -> dict[str, Any]:
    return {
        "collection_name": collection,
        "auth_type": "standalone",
        "host": HOST,
        "port": PORT,
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


class _Server:
    """Admin handle for one temporary collection: write rows, flip load state, drop."""

    def __init__(self, *, admin: MilvusClient, collection: str) -> None:
        self.admin = admin
        self.collection = collection
        self._adapters: list[MilvusAdapter] = []

    def adapter(self) -> MilvusAdapter:
        adapter = MilvusAdapter(**_adapter_config(collection=self.collection))
        self._adapters.append(adapter)
        return adapter

    def create_and_fill(self, *, pks: list[str]) -> None:
        """Create the collection through the adapter and insert rows; leaves it unloaded and flushed."""
        writer = self.adapter()
        writer.create_index(dimension_mapping={"embeddings": DIM})
        if pks:
            documents = [(pk, {"doc_id_hash": pk, "embeddings": [0.1, 0.2, 0.3, 0.4], "content": "text"}) for pk in pks]
            success, failed = writer.index_documents(documents)
            assert (success, failed) == (len(pks), [])
            # Make the rows visible to queries regardless of the server's consistency level.
            self.admin.flush(collection_name=self.collection)
        self.release()

    def state(self) -> LoadState:
        return self.admin.get_load_state(collection_name=self.collection)["state"]

    def release(self) -> None:
        self.admin.release_collection(collection_name=self.collection)

    def drop(self) -> None:
        assert self.collection.startswith(PREFIX), "refusing to drop a collection this test did not create"
        self.admin.drop_collection(collection_name=self.collection)

    def cleanup(self) -> None:
        for adapter in self._adapters:
            try:
                adapter.close()
            except Exception:
                pass
        if self.collection.startswith(PREFIX) and self.admin.has_collection(collection_name=self.collection):
            self.admin.drop_collection(collection_name=self.collection)


@pytest.fixture
def server() -> Iterator[_Server]:
    admin = MilvusClient(uri=f"http://{HOST}:{PORT}")
    handle = _Server(admin=admin, collection=f"{PREFIX}{uuid.uuid4().hex[:12]}")
    try:
        yield handle
    finally:
        handle.cleanup()
        admin.close()


class TestQueriesOnUnloadedCollections:
    """A collection that is not loaded must be loaded by the adapter before it is queried."""

    def test_newly_created_unloaded_collection_is_queryable(self, server: _Server) -> None:
        """Created through the adapter, the collection starts unloaded; the first query loads it."""
        server.create_and_fill(pks=["doc_a", "doc_b"])
        assert server.state() == LoadState.NotLoad

        rows = server.adapter().query_by_doc_names(doc_names=["doc_a"])

        assert [row["pk"] for row in rows] == ["doc_a"]

    def test_existing_unloaded_collection_is_queryable_from_a_new_adapter(self, server: _Server) -> None:
        """A later run opens an existing collection with a new adapter and finds the stored rows."""
        server.create_and_fill(pks=["doc_a", "doc_b"])
        # The first adapter loads and releases nothing; a second one starts from a cold collection.
        assert server.adapter().query_by_doc_names(doc_names=["doc_a"])
        server.release()
        assert server.state() == LoadState.NotLoad

        rows = server.adapter().query_by_doc_names(doc_names=["doc_a", "doc_b"])

        assert sorted(row["pk"] for row in rows) == ["doc_a", "doc_b"]

    def test_collection_is_loaded_after_the_first_query(self, server: _Server) -> None:
        """The adapter leaves the collection in the Loaded state and serves later queries from it."""
        server.create_and_fill(pks=["doc_a"])
        adapter = server.adapter()

        adapter.query_by_doc_names(doc_names=["doc_a"])

        assert server.state() == LoadState.Loaded
        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_a"])] == ["doc_a"]

    def test_chunk_pk_lookup_loads_collection_and_returns_stored_pks(self, server: _Server) -> None:
        """Stale-chunk cleanup lookups work on a cold collection."""
        file_id = "/docs/file_a.pdf"
        chunk_pk = f"{hashlib.sha3_512(file_id.encode()).hexdigest()}_contenthash"
        server.create_and_fill(pks=[chunk_pk])

        found = server.adapter().get_chunk_ids_for_documents(doc_ids=[file_id])

        assert found == {file_id: {chunk_pk}}
        assert server.state() == LoadState.Loaded

    def test_query_with_no_matches_returns_empty_list(self, server: _Server) -> None:
        server.create_and_fill(pks=["doc_a"])

        assert server.adapter().query_by_doc_names(doc_names=["no_such_doc"]) == []

    def test_missing_collection_returns_empty_without_creating_it(self, server: _Server) -> None:
        """First-run cleanup: the collection does not exist yet, so lookups are empty and nothing is created."""
        adapter = server.adapter()

        assert adapter.query_by_doc_names(doc_names=["doc_a"]) == []
        assert adapter.get_chunk_ids_for_documents(doc_ids=["/docs/file_a.pdf"]) == {}
        assert not server.admin.has_collection(collection_name=server.collection)


class TestQueryFailurePropagation:
    """A rejected query must surface as an error, never as an empty result."""

    def test_server_side_query_error_raises_docpipe_exception(self, server: _Server) -> None:
        """Asking for a field that is not in the schema is rejected by the server."""
        server.create_and_fill(pks=["doc_a"])

        with pytest.raises(DocpipeException) as exc_info:
            server.adapter().query_by_doc_names(doc_names=["doc_a"], fields=["no_such_field"])

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED
        assert exc_info.value.__cause__ is not None
        assert "no_such_field" in str(exc_info.value)

    def test_failed_query_leaves_the_collection_usable(self, server: _Server) -> None:
        server.create_and_fill(pks=["doc_a"])
        adapter = server.adapter()

        with pytest.raises(DocpipeException):
            adapter.query_by_doc_names(doc_names=["doc_a"], fields=["no_such_field"])

        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_a"])] == ["doc_a"]


class TestCollectionChangesDuringAdapterLifetime:
    """The cached loaded flag must survive release, drop and recreation by another client."""

    def test_release_between_queries_is_recovered(self, server: _Server) -> None:
        server.create_and_fill(pks=["doc_a"])
        adapter = server.adapter()
        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_a"])] == ["doc_a"]

        server.release()
        assert server.state() == LoadState.NotLoad

        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_a"])] == ["doc_a"]
        assert server.state() == LoadState.Loaded

    def test_release_between_chunk_pk_lookups_is_recovered(self, server: _Server) -> None:
        file_id = "/docs/file_a.pdf"
        chunk_pk = f"{hashlib.sha3_512(file_id.encode()).hexdigest()}_contenthash"
        server.create_and_fill(pks=[chunk_pk])
        adapter = server.adapter()
        assert adapter.get_chunk_ids_for_documents(doc_ids=[file_id]) == {file_id: {chunk_pk}}

        server.release()

        assert adapter.get_chunk_ids_for_documents(doc_ids=[file_id]) == {file_id: {chunk_pk}}

    def test_drop_between_queries_returns_empty(self, server: _Server) -> None:
        server.create_and_fill(pks=["doc_a"])
        adapter = server.adapter()
        assert adapter.query_by_doc_names(doc_names=["doc_a"])

        server.drop()

        assert adapter.query_by_doc_names(doc_names=["doc_a"]) == []

    def test_recreate_between_queries_returns_the_new_rows(self, server: _Server) -> None:
        server.create_and_fill(pks=["doc_a"])
        adapter = server.adapter()
        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_a"])] == ["doc_a"]

        server.drop()
        server.create_and_fill(pks=["doc_new"])

        assert [row["pk"] for row in adapter.query_by_doc_names(doc_names=["doc_new"])] == ["doc_new"]
        assert adapter.query_by_doc_names(doc_names=["doc_a"]) == []
