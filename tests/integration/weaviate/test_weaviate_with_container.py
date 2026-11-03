# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Real-server tests for the Weaviate VectorDB provider.

The suite runs against a Weaviate server and is meant for manual, pre-release
use; it is not wired into CI. The server comes from, in order:

1. ``DOCPIPE_TEST_WEAVIATE_HOST`` (with optional ``DOCPIPE_TEST_WEAVIATE_PORT`` and
   ``DOCPIPE_TEST_WEAVIATE_GRPC_PORT``), used as is;
2. a server already listening on ``localhost:8080`` / ``50051``;
3. ``docker/docker-compose.weaviate.yml`` started with ``docker compose`` or
   ``docker-compose`` and stopped afterwards.

The ``dynamic`` index needs a server with async indexing. It is taken from
``DOCPIPE_TEST_WEAVIATE_ASYNC_HOST`` (``..._ASYNC_PORT``, ``..._ASYNC_GRPC_PORT``), a
server on ``localhost:8081`` / ``50052``, or the ``weaviate-async`` compose service.
Tests that need a server that is not available are skipped with a "BLOCKED" reason;
a skip is not a pass.

The server must run with ``AUTOSCHEMA_ENABLED=false``; the suite fails otherwise.
"""

import contextlib
import os
import secrets
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pytest
import weaviate
from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.classes.data import DataObject
from weaviate.exceptions import WeaviateInsertManyAllFailedError

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.adapter import WeaviateAdapter
from docpipe.core.operators.vectordb.metadata_fetcher import VectorDBMetadataFetcher
from docpipe.core.orchestration.flow_validator import FlowValidator
from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowValidationException

COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker" / "docker-compose.weaviate.yml"
COMPOSE_PROJECT = "docpipe-weaviate-test"
READY_TIMEOUT_SECONDS = 90

DEFAULT_ENDPOINT = ("localhost", 8080, 50051)
ASYNC_ENDPOINT = ("localhost", 8081, 50052)

ADAPTER_MODULE = "docpipe.core.operators.vectordb.adapters.outbound.weaviate"
CLIENT_CONNECT = f"{ADAPTER_MODULE}.client.weaviate.connect_to_custom"

DENSE_DIM = 8
ALT_DIM = 4
STALE_PAGE_LIMIT = 10_000


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------


class Endpoint:
    """Connection details of a Weaviate server."""

    def __init__(self, *, host: str, port: int, grpc_port: int) -> None:
        self.host = host
        self.port = port
        self.grpc_port = grpc_port

    def provider_config(self, **overrides: Any) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "grpc_port": self.grpc_port, **overrides}

    def connect(self) -> weaviate.WeaviateClient:
        return weaviate.connect_to_custom(
            http_host=self.host,
            http_port=self.port,
            http_secure=False,
            grpc_host=self.host,
            grpc_port=self.grpc_port,
            grpc_secure=False,
        )


def _is_ready(endpoint: Endpoint) -> bool:
    try:
        client = endpoint.connect()
    except Exception:
        return False
    try:
        return bool(client.is_ready())
    finally:
        client.close()


def _wait_until_ready(endpoint: Endpoint) -> bool:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _is_ready(endpoint):
            return True
        time.sleep(2)
    return False


def _compose_command() -> list[str] | None:
    """Return the available compose invocation, preferring the plugin."""
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
        if probe.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def _compose(args: list[str]) -> None:
    command = _compose_command()
    if command is None:
        raise RuntimeError("neither 'docker compose' nor 'docker-compose' is available")
    subprocess.run(
        [*command, "-p", COMPOSE_PROJECT, "-f", str(COMPOSE_FILE), *args],
        check=True,
        capture_output=True,
        timeout=180,
    )


def _endpoint_from_env(*, prefix: str, default: tuple[str, int, int]) -> Endpoint | None:
    host = os.getenv(f"{prefix}_HOST")
    if not host:
        return None
    return Endpoint(
        host=host,
        port=int(os.getenv(f"{prefix}_PORT", str(default[1]))),
        grpc_port=int(os.getenv(f"{prefix}_GRPC_PORT", str(default[2]))),
    )


def _resolve_server(*, env_prefix: str, default: tuple[str, int, int], compose_args: list[str]) -> Iterator[Endpoint]:
    """Yield a ready endpoint from the environment, a running server, or compose; skip as blocked otherwise."""
    configured = _endpoint_from_env(prefix=env_prefix, default=default)
    if configured is not None:
        if not _wait_until_ready(configured):
            pytest.skip(f"BLOCKED: Weaviate configured by {env_prefix}_HOST is not ready")
        yield configured
        return

    endpoint = Endpoint(host=default[0], port=default[1], grpc_port=default[2])
    if _is_ready(endpoint):
        yield endpoint
        return

    if _compose_command() is None or not COMPOSE_FILE.exists():
        pytest.skip("BLOCKED: no reachable Weaviate server and no docker compose available to start one")
    try:
        _compose(compose_args)
    except (subprocess.SubprocessError, RuntimeError) as exc:
        pytest.skip(f"BLOCKED: could not start Weaviate with docker compose: {exc}")
    try:
        if not _wait_until_ready(endpoint):
            pytest.skip("BLOCKED: Weaviate started by docker compose did not become ready")
        yield endpoint
    finally:
        with contextlib.suppress(Exception):
            _compose(["--profile", "async", "down", "-v"])


@pytest.fixture(scope="session")
def server() -> Iterator[Endpoint]:
    yield from _resolve_server(
        env_prefix="DOCPIPE_TEST_WEAVIATE",
        default=DEFAULT_ENDPOINT,
        compose_args=["up", "-d", "weaviate"],
    )


@pytest.fixture(scope="session")
def async_server() -> Iterator[Endpoint]:
    yield from _resolve_server(
        env_prefix="DOCPIPE_TEST_WEAVIATE_ASYNC",
        default=ASYNC_ENDPOINT,
        compose_args=["--profile", "async", "up", "-d", "weaviate-async"],
    )


@pytest.fixture(scope="session")
def sdk(server: Endpoint) -> Iterator[weaviate.WeaviateClient]:
    client = server.connect()
    yield client
    client.close()


@pytest.fixture(scope="session", autouse=True)
def _require_strict_schema(sdk: weaviate.WeaviateClient) -> None:
    """Fail the suite when the server accepts properties that were never declared."""
    name = f"DocpipeGuard{uuid.uuid4().hex[:10]}"
    collection = sdk.collections.create(
        name=name,
        properties=[Property(name="declared", data_type=DataType.TEXT)],
        vector_config=Configure.Vectors.self_provided(name="v"),
    )
    accepted = False
    try:
        result = collection.data.insert_many(
            [DataObject(properties={"declared": "a", "undeclared": "b"}, vector=[0.1])]
        )
        accepted = not result.has_errors
    except WeaviateInsertManyAllFailedError:
        accepted = False
    finally:
        sdk.collections.delete(name)
    if accepted:
        pytest.fail("The Weaviate server accepted an undeclared property; AUTOSCHEMA_ENABLED=false is required")


@pytest.fixture
def make_name(sdk: weaviate.WeaviateClient) -> Iterator[Callable[[], str]]:
    """Return a factory of unique collection names; every collection is dropped on teardown."""
    names: list[str] = []

    def _make() -> str:
        name = f"DocpipeIt{uuid.uuid4().hex[:12]}"
        names.append(name)
        return name

    yield _make
    for name in names:
        with contextlib.suppress(Exception):
            sdk.collections.delete(name)


@pytest.fixture
def collection_name(make_name: Callable[[], str]) -> str:
    return make_name()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

EMBEDDING_COLUMNS: dict[str, tuple[str, int]] = {
    "embeddings": ("vector_embeddings", DENSE_DIM),
    "embeddings_alt": ("vector_embeddings_alt", ALT_DIM),
}


def vectordb_config(
    *,
    server: Endpoint,
    collection: str,
    embeddings: tuple[str, ...] = ("embeddings",),
    sparse: bool = False,
    provider_overrides: dict[str, Any] | None = None,
    extra_features: dict[str, dict[str, Any]] | None = None,
    extra_mappings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a fresh ``vectordb`` operator config for a Weaviate collection."""
    features: dict[str, dict[str, Any]] = {
        "doc_id_hash": {
            "type": "string",
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "is_primary": True,
        },
        "content": {"type": "string", "available_for_vector_db": True},
        "name": {"type": "string", "available_for_vector_db": True},
    }
    mappings = [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "name", "mapped_column_name": "doc_name"},
    ]
    for column in embeddings:
        features[column] = {"type": "vector", "available_for_vector_db": True, "mandatory_for_vector_db": True}
        mappings.append({"feature_name": column, "mapped_column_name": EMBEDDING_COLUMNS[column][0]})
    features.update(extra_features or {})
    mappings.extend(extra_mappings or [])
    return {
        "provider": "weaviate",
        "doc_id_column": "doc_id_hash",
        "add_sparse_vector": sparse,
        "provider_config": server.provider_config(collection_name=collection, **(provider_overrides or {})),
        "available_features": features,
        "feature_mappings": mappings,
    }


def make_table(
    *,
    docs: list[dict[str, Any]],
    embeddings: tuple[str, ...] = ("embeddings",),
    include_id: bool = True,
    dims: dict[str, int] | None = None,
    extra_columns: dict[str, pa.Array] | None = None,
) -> pa.Table:
    """Build an in-memory chunked table.

    Each doc is ``{"hash": str, "id": str | None, "name": str, "chunks": list[str]}``.
    """
    rng = np.random.default_rng(7)
    columns: dict[str, Any] = {
        "doc_id_hash": [d["hash"] for d in docs],
        "name": [d.get("name", d["hash"]) for d in docs],
        "content": [" ".join(d["chunks"]) for d in docs],
        "chunked_content": [[{"chunk": text} for text in d["chunks"]] for d in docs],
    }
    if include_id:
        columns["id"] = pa.array([d.get("id") for d in docs], type=pa.string())
    for column in embeddings:
        dim = (dims or {}).get(column, EMBEDDING_COLUMNS[column][1])
        columns[column] = [rng.random((len(d["chunks"]), dim)).tolist() for d in docs]
    columns.update(extra_columns or {})
    return pa.table(columns)


def doc(*, hash_: str, chunks: int, doc_id: str | None = None, prefix: str | None = None) -> dict[str, Any]:
    label = prefix or hash_
    return {
        "hash": hash_,
        "id": doc_id,
        "name": f"{hash_}.txt",
        "chunks": [f"{label} chunk {i}" for i in range(chunks)],
    }


def run(*, config: dict[str, Any], table: pa.Table) -> dict[str, Any]:
    """Run the operator once and return its metadata."""
    _, metadata = VectorDBOperator(config).transform(table)
    return metadata


def failed_ids(metadata: dict[str, Any]) -> list[str]:
    return [entry["id"] for entry in metadata[Metrics.External.FAILED_DOCS]]


def count(sdk: weaviate.WeaviateClient, name: str) -> int:
    return int(sdk.collections.get(name).aggregate.over_all(total_count=True).total_count or 0)


def stored(sdk: weaviate.WeaviateClient, name: str, *, vectors: bool = False) -> list[Any]:
    return sdk.collections.get(name).query.fetch_objects(limit=1000, include_vector=vectors).objects


def create_collection(
    sdk: weaviate.WeaviateClient,
    name: str,
    *,
    properties: list[Property],
    vector: str = "vector_embeddings",
) -> None:
    sdk.collections.create(
        name=name,
        properties=properties,
        vector_config=[Configure.Vectors.self_provided(name=vector, vector_index_config=Configure.VectorIndex.hnsw())],
    )


def standard_properties(
    *, text_tokenization: Tokenization = Tokenization.WORD, pk_tokenization: Tokenization = Tokenization.FIELD
) -> list[Property]:
    return [
        Property(name="pk", data_type=DataType.TEXT, tokenization=pk_tokenization, index_filterable=True),
        Property(name="text", data_type=DataType.TEXT, tokenization=text_tokenization, index_searchable=True),
    ]


# ---------------------------------------------------------------------------
# Writing and re-ingesting
# ---------------------------------------------------------------------------


def test_new_collection_is_created_and_chunks_are_written(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    table = make_table(docs=[doc(hash_="d1", chunks=3), doc(hash_="d2", chunks=3)])

    metadata = run(config=vectordb_config(server=server, collection=collection_name), table=table)

    assert metadata[Metrics.External.PROCESSED_DOCS] == 2
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
    assert count(sdk, collection_name) == 6
    cfg = sdk.collections.get(collection_name).config.get()
    assert list(cfg.vector_config) == ["vector_embeddings"]
    for obj in stored(sdk, collection_name, vectors=True):
        assert len(obj.vector["vector_embeddings"]) == DENSE_DIM
        assert obj.properties["text"]
        assert obj.properties["doc_name"].endswith(".txt")


def test_two_dense_columns_create_two_named_vectors(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    columns = ("embeddings", "embeddings_alt")
    table = make_table(docs=[doc(hash_="d1", chunks=2)], embeddings=columns)

    metadata = run(config=vectordb_config(server=server, collection=collection_name, embeddings=columns), table=table)

    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
    cfg = sdk.collections.get(collection_name).config.get()
    assert sorted(cfg.vector_config) == ["vector_embeddings", "vector_embeddings_alt"]
    for obj in stored(sdk, collection_name, vectors=True):
        assert len(obj.vector["vector_embeddings"]) == DENSE_DIM
        assert len(obj.vector["vector_embeddings_alt"]) == ALT_DIM


def test_reingest_updates_text_in_place_with_stable_object_ids(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=3, prefix="old")]))
    before = {o.properties["pk"]: o.uuid for o in stored(sdk, collection_name)}

    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=3, prefix="new")]))

    after = {o.properties["pk"]: o.uuid for o in stored(sdk, collection_name)}
    assert count(sdk, collection_name) == 3
    assert after == before
    assert all(o.properties["text"].startswith("new") for o in stored(sdk, collection_name))


def test_reingest_with_fewer_chunks_deletes_the_tail(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=5)]))

    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=2)]))

    assert count(sdk, collection_name) == 2


# ---------------------------------------------------------------------------
# Validation and per-chunk failures
# ---------------------------------------------------------------------------


def test_dimension_mismatch_fails_before_any_write(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=2)]))

    metadata = run(
        config=config(),
        table=make_table(docs=[doc(hash_="d2", chunks=2)], dims={"embeddings": ALT_DIM}),
    )

    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert failed_ids(metadata) == ["d2"]
    assert "dimension mismatch" in metadata[Metrics.External.FAILED_DOCS][0]["reason"].lower()
    assert count(sdk, collection_name) == 2


def _page_count_setup(*, server: Endpoint, sdk: weaviate.WeaviateClient, name: str) -> dict[str, Any]:
    create_collection(
        sdk,
        name,
        properties=[*standard_properties(), Property(name="page_count", data_type=DataType.INT)],
    )
    return vectordb_config(
        server=server,
        collection=name,
        extra_features={"page_count": {"type": "int64", "available_for_vector_db": True}},
        extra_mappings=[{"feature_name": "page_count", "mapped_column_name": "page_count"}],
    )


def test_one_rejected_chunk_in_a_batch_is_attributed_to_its_document(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = _page_count_setup(server=server, sdk=sdk, name=collection_name)
    table = make_table(
        docs=[doc(hash_="good", chunks=2), doc(hash_="bad", chunks=1)],
        extra_columns={"page_count": pa.array([None, "not-a-number"], type=pa.string())},
    )

    metadata = run(config=config, table=table)

    assert metadata[Metrics.External.CHUNKS_FAILED_TO_INDEX] == 1
    assert metadata[Metrics.External.CHUNKS_INDEXED_SUCCESSFULLY] == 2
    assert failed_ids(metadata) == ["bad"]
    assert count(sdk, collection_name) == 2


def test_batch_where_every_chunk_is_rejected_reports_each_chunk_failed(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = _page_count_setup(server=server, sdk=sdk, name=collection_name)
    table = make_table(
        docs=[doc(hash_="bad", chunks=1)],
        extra_columns={"page_count": pa.array(["not-a-number"], type=pa.string())},
    )

    metadata = run(config=config, table=table)

    assert metadata[Metrics.External.CHUNKS_FAILED_TO_INDEX] == 1
    assert failed_ids(metadata) == ["bad"]
    assert count(sdk, collection_name) == 0


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def _enrichment(*, provider_config: dict[str, Any], sparse: bool = False) -> dict[str, Any]:
    return VectorDBMetadataFetcher().fetch_metadata(
        adapter_name="weaviate",
        operator_config={"provider": "weaviate", "provider_config": provider_config, "add_sparse_vector": sparse},
        available_features={},
    )


def test_enrichment_describes_an_existing_collection(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    run(
        config=vectordb_config(server=server, collection=collection_name),
        table=make_table(docs=[doc(hash_="d1", chunks=2)]),
    )

    result = _enrichment(provider_config=server.provider_config(collection_name=collection_name))

    assert collection_name in result["available_resources"]
    assert result["is_docpipe_supported_resource"]["supported"] is True
    assert "error" not in result["is_docpipe_supported_resource"]
    assert result["stored_resource_metadata"] == {"vector_similarity": "cosine", "dimension_size": DENSE_DIM}


def test_enrichment_for_a_collection_that_does_not_exist_reports_no_error(
    server: Endpoint, collection_name: str
) -> None:
    result = _enrichment(provider_config=server.provider_config(collection_name=collection_name))

    assert collection_name not in result["available_resources"]
    assert result["is_docpipe_supported_resource"] == {"collection_name": collection_name, "supported": True}


def test_enrichment_for_an_unreachable_server_reports_a_redacted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = secrets.token_hex(16)
    monkeypatch.setenv("DOCPIPE_IT_WEAVIATE_KEY", secret)

    result = _enrichment(
        provider_config={
            "host": "127.0.0.1",
            "port": 1,
            "grpc_port": 2,
            "secure": True,
            "grpc_secure": True,
            "auth_type": "api_key",
            "api_key": "$DOCPIPE_IT_WEAVIATE_KEY",
            "timeout_init": 2,
            "collection_name": "Anything",
        }
    )

    verdict = result["is_docpipe_supported_resource"]
    assert verdict["supported"] is False
    assert verdict["error"]
    assert secret not in verdict["error"]
    assert result["available_resources"] == []


# ---------------------------------------------------------------------------
# Deletes and sparse retrieval
# ---------------------------------------------------------------------------


def test_delete_handles_more_primary_keys_than_one_request_allows(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    total = 1200
    features = {
        "doc_id_hash": {"type": "string", "is_primary": True},
        "content": {"type": "string"},
        "embeddings": {"type": "vector"},
    }
    mappings = [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
    ]
    adapter = WeaviateAdapter(
        **server.provider_config(collection_name=collection_name),
        available_features=features,
        feature_mappings=mappings,
    )
    try:
        adapter.create_index(dimension_mapping={"embeddings": 4})
        rng = np.random.default_rng(3)
        pks = [f"pk-{i}" for i in range(total)]
        documents = [
            (pk, {"doc_id_hash": pk, "content": f"row {i}", "embeddings": rng.random(4).tolist()})
            for i, pk in enumerate(pks)
        ]
        written, failed = adapter.index_documents(documents)
        assert (written, failed) == (total, [])
        assert adapter.get_document_count() == total

        deleted, delete_failed = adapter.delete_documents_by_ids(pks)

        assert (deleted, delete_failed) == (total, 0)
        assert adapter.get_document_count() == 0
    finally:
        adapter.close()


def test_sparse_and_dense_collection_answers_keyword_and_hybrid_queries(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    target = "zorblax"
    table = make_table(
        docs=[{"hash": "d1", "id": None, "name": "d1.txt", "chunks": [f"{target} appears here", "plain"]}]
    )
    run(config=vectordb_config(server=server, collection=collection_name, sparse=True), table=table)
    collection = sdk.collections.get(collection_name)

    bm25 = collection.config.get().inverted_index_config.bm25
    assert (bm25.k1, bm25.b) == (1.2, 0.75)
    keyword_hits = collection.query.bm25(query=target, limit=5).objects
    assert [o.properties["text"] for o in keyword_hits] == [f"{target} appears here"]

    vector = next(o for o in stored(sdk, collection_name, vectors=True) if target in o.properties["text"]).vector[
        "vector_embeddings"
    ]
    hybrid_hits = collection.query.hybrid(
        query=target, vector=vector, target_vector="vector_embeddings", limit=5
    ).objects
    assert hybrid_hits
    assert target in hybrid_hits[0].properties["text"]


def _sparse_only_table() -> pa.Table:
    return make_table(
        docs=[{"hash": "d1", "id": None, "name": "d1.txt", "chunks": ["kestrel alpha", "kestrel beta", "other"]}],
        embeddings=(),
    )


def test_sparse_only_run_creates_a_keyword_only_collection(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name, embeddings=(), sparse=True)  # noqa: E731

    first = run(config=config(), table=_sparse_only_table())

    assert first[Metrics.External.NODE_STATUS] != ExecutionStatus.FAILED.value
    collection = sdk.collections.get(collection_name)
    vector_config = collection.config.get().vector_config
    assert list(vector_config) == ["keyword_only"]
    assert all(getattr(v.vector_index_config, "skip", False) for v in vector_config.values())
    assert count(sdk, collection_name) == 3
    assert len(collection.query.bm25(query="kestrel", limit=5).objects) == 2

    second = run(config=config(), table=_sparse_only_table())

    assert second[Metrics.External.NODE_STATUS] != ExecutionStatus.FAILED.value
    assert second[Metrics.External.FAILED_DOCS_COUNT] == 0
    assert count(sdk, collection_name) == 3


def test_hand_made_keyword_only_collection_serves_sparse_runs_but_not_dense_runs(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    sdk.collections.create(
        name=collection_name,
        properties=standard_properties(),
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.none(),
    )
    cfg = sdk.collections.get(collection_name).config.get()
    assert not cfg.vector_config
    assert cfg.vector_index_config.skip is True

    sparse = run(
        config=vectordb_config(server=server, collection=collection_name, embeddings=(), sparse=True),
        table=_sparse_only_table(),
    )
    assert sparse[Metrics.External.NODE_STATUS] != ExecutionStatus.FAILED.value
    assert count(sdk, collection_name) == 3

    dense = run(
        config=vectordb_config(server=server, collection=collection_name),
        table=make_table(docs=[doc(hash_="d2", chunks=1)]),
    )
    assert dense[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert count(sdk, collection_name) == 3


# ---------------------------------------------------------------------------
# Dynamic index
# ---------------------------------------------------------------------------


def _wait_for_empty_index_queue(*, client: weaviate.WeaviateClient, name: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        nodes = client.cluster.nodes(collection=name, output="verbose")
        if all(shard.vector_queue_length == 0 for node in nodes for shard in node.shards):
            return
        time.sleep(0.5)
    pytest.fail("The vector indexing queue did not drain")


def test_dynamic_index_works_with_async_indexing(async_server: Endpoint, make_name: Callable[[], str]) -> None:
    name = make_name()
    client = async_server.connect()
    try:
        table = make_table(docs=[doc(hash_="d1", chunks=3)])
        metadata = run(
            config=vectordb_config(server=async_server, collection=name, provider_overrides={"index_type": "dynamic"}),
            table=table,
        )
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        _wait_for_empty_index_queue(client=client, name=name)
        collection = client.collections.get(name)
        vector = table["embeddings"][0].as_py()[0]
        hits = collection.query.near_vector(near_vector=vector, target_vector="vector_embeddings", limit=3).objects
        assert len(hits) == 3
    finally:
        with contextlib.suppress(Exception):
            client.collections.delete(name)
        client.close()


def test_dynamic_index_without_async_indexing_is_refused_with_guidance(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    metadata = run(
        config=vectordb_config(server=server, collection=collection_name, provider_overrides={"index_type": "dynamic"}),
        table=make_table(docs=[doc(hash_="d1", chunks=1)]),
    )

    if sdk.collections.exists(collection_name):
        pytest.skip("BLOCKED: this server has async indexing enabled, so 'dynamic' is accepted")
    assert not sdk.collections.exists(collection_name)
    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert "async indexing" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]


# ---------------------------------------------------------------------------
# Identity-property and content-property rules
# ---------------------------------------------------------------------------


def test_word_tokenized_primary_key_is_rejected_and_nothing_is_deleted(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    create_collection(sdk, collection_name, properties=standard_properties(pk_tokenization=Tokenization.WORD))
    sdk.collections.get(collection_name).data.insert(
        properties={"pk": "existing-chunk", "text": "kept"}, vector={"vector_embeddings": [0.1] * DENSE_DIM}
    )

    metadata = run(
        config=vectordb_config(server=server, collection=collection_name),
        table=make_table(docs=[doc(hash_="d1", chunks=2)]),
    )

    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert "pk" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
    assert count(sdk, collection_name) == 1


def test_reingesting_one_file_leaves_other_files_untouched(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    run(
        config=config(),
        table=make_table(docs=[doc(hash_="a", chunks=3, doc_id="file-a"), doc(hash_="b", chunks=3, doc_id="file-b")]),
    )

    run(config=config(), table=make_table(docs=[doc(hash_="a", chunks=1, doc_id="file-a")]))

    assert count(sdk, collection_name) == 4


def test_stale_cleanup_covers_files_larger_than_the_server_result_limit(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    large = STALE_PAGE_LIMIT + 500
    run(
        config=config(),
        table=make_table(docs=[doc(hash_="big", chunks=large, doc_id="big-file")], dims={"embeddings": 4}),
    )
    assert count(sdk, collection_name) == large

    run(
        config=config(),
        table=make_table(docs=[doc(hash_="big", chunks=1, doc_id="big-file")], dims={"embeddings": 4}),
    )

    assert count(sdk, collection_name) == 1


def test_dense_run_is_rejected_when_the_content_property_is_not_word_tokenized(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    create_collection(sdk, collection_name, properties=standard_properties(text_tokenization=Tokenization.FIELD))

    metadata = run(
        config=vectordb_config(server=server, collection=collection_name),
        table=make_table(docs=[doc(hash_="d1", chunks=2)]),
    )

    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert "'text'" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
    assert count(sdk, collection_name) == 0


def test_dense_run_is_rejected_when_content_is_mapped_to_a_field_tokenized_custom_column(
    server: Endpoint, sdk: weaviate.WeaviateClient, collection_name: str
) -> None:
    create_collection(
        sdk,
        collection_name,
        properties=[
            Property(name="pk", data_type=DataType.TEXT, tokenization=Tokenization.FIELD, index_filterable=True),
            Property(name="body", data_type=DataType.TEXT, tokenization=Tokenization.FIELD, index_searchable=True),
        ],
    )
    config = vectordb_config(server=server, collection=collection_name)
    for mapping in config["feature_mappings"]:
        if mapping["feature_name"] == "content":
            mapping["mapped_column_name"] = "body"

    metadata = run(config=config, table=make_table(docs=[doc(hash_="d1", chunks=2)]))

    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value
    assert "'body'" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
    assert count(sdk, collection_name) == 0


# ---------------------------------------------------------------------------
# Connection release
# ---------------------------------------------------------------------------


class _RecordingConnector:
    """Wraps ``weaviate.connect_to_custom`` and remembers every client it opens."""

    def __init__(self, *, unready: bool = False) -> None:
        self.clients: list[weaviate.WeaviateClient] = []
        self._unready = unready
        self._real = weaviate.connect_to_custom

    def __call__(self, **kwargs: Any) -> weaviate.WeaviateClient:
        client = self._real(**kwargs)
        if self._unready:
            client.is_ready = lambda: False  # type: ignore[method-assign]
        self.clients.append(client)
        return client


def _validation_flow(*, server: Endpoint, collection: str) -> dict[str, Any]:
    return {
        "dag": [
            {
                "id": "ingest-1",
                "name": "ingest",
                "operator": "ingest_source",
                "config": {"provider": "filesystem", "provider_config": {"paths": ["/tmp"]}},
                "input_edges": [],
                "output_edges": [{"node_id_ref": "vectordb-1"}],
            },
            {
                "id": "vectordb-1",
                "name": "vectordb",
                "operator": "vectordb",
                "config": {
                    "provider": "weaviate",
                    "provider_config": server.provider_config(collection_name=collection),
                },
                "input_edges": [{"node_id_ref": "ingest-1"}],
                "output_edges": [],
            },
        ]
    }


def test_flow_validation_leaves_no_connection_open(server: Endpoint, collection_name: str) -> None:
    connector = _RecordingConnector()
    validator = FlowValidator(orchestrator=OrchestratorFactory.create_orchestrator(orchestrator_name="python"))

    with patch(CLIENT_CONNECT, connector), contextlib.suppress(FlowValidationException):
        validator.validate_dag(flow_def=_validation_flow(server=server, collection=collection_name), global_config={})

    assert connector.clients
    assert not any(client.is_connected() for client in connector.clients)


def test_adapter_that_cannot_connect_leaves_no_connection_open(server: Endpoint, collection_name: str) -> None:
    connector = _RecordingConnector(unready=True)

    with patch(CLIENT_CONNECT, connector), pytest.raises(DocpipeException):
        WeaviateAdapter(**server.provider_config(collection_name=collection_name))

    assert connector.clients
    assert not any(client.is_connected() for client in connector.clients)


def test_adapter_that_fails_after_connecting_closes_the_connection(server: Endpoint, collection_name: str) -> None:
    connector = _RecordingConnector()

    with (
        patch(CLIENT_CONNECT, connector),
        patch(f"{ADAPTER_MODULE}.adapter.WeaviateIndexManager", side_effect=RuntimeError("rejected")),
        pytest.raises(RuntimeError),
    ):
        WeaviateAdapter(**server.provider_config(collection_name=collection_name))

    assert connector.clients
    assert not any(client.is_connected() for client in connector.clients)


# ---------------------------------------------------------------------------
# Document identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("include_id", [True, False], ids=["null_id_column", "no_id_column"])
def test_documents_without_an_id_keep_separate_chunks(
    server: Endpoint,
    sdk: weaviate.WeaviateClient,
    collection_name: str,
    include_id: bool,
) -> None:
    config = lambda: vectordb_config(server=server, collection=collection_name)  # noqa: E731
    run(
        config=config(),
        table=make_table(docs=[doc(hash_="d1", chunks=3), doc(hash_="d2", chunks=3)], include_id=include_id),
    )
    assert count(sdk, collection_name) == 6
    assert len({o.properties["pk"] for o in stored(sdk, collection_name)}) == 6

    run(config=config(), table=make_table(docs=[doc(hash_="d1", chunks=1)], include_id=include_id))

    remaining = {o.properties["doc_name"] for o in stored(sdk, collection_name)}
    assert count(sdk, collection_name) == 4
    assert remaining == {"d1.txt", "d2.txt"}
    assert sum(1 for o in stored(sdk, collection_name) if o.properties["doc_name"] == "d2.txt") == 3
