#!/usr/bin/env python3
"""
Integration test: Ingest -> Extract (docling_library) -> Chunk (docling hybrid) ->
Embeddings (sentence-transformers/all-MiniLM-L6-v2) -> Milvus Lite (.db file).

Runs entirely locally — no Docker, Podman, or external Milvus service required.
All Milvus data is written to a temporary directory and cleaned up after the test.
"""

from pathlib import Path
from typing import Any

import pytest

from docpipe.core.constants.constants import Metrics


def _fixture_dir() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "customer_support_docs"


def _has_milvus_lite() -> bool:
    try:
        import milvus_lite  # noqa: F401

        return True
    except ImportError:
        return False


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

# Explicit feature_mappings: source column -> Milvus field name.
# These must agree with the schema fields created by MilvusIndexManager.
FEATURE_MAPPINGS: list[dict[str, str]] = [
    {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
    {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
    {"feature_name": "content", "mapped_column_name": "text"},
    {"feature_name": "name", "mapped_column_name": "document_name"},
    {"feature_name": "id", "mapped_column_name": "document_id"},
]

AVAILABLE_FEATURES: dict[str, Any] = {
    "doc_id_hash": {
        "type": "string",
        "available_for_vector_db": True,
        "mandatory_for_vector_db": True,
        "is_primary": True,
    },
    "embeddings": {
        "type": "vector",
        "available_for_vector_db": True,
        "mandatory_for_vector_db": True,
    },
    "content": {
        "type": "string",
        "available_for_vector_db": True,
    },
    "name": {
        "type": "string",
        "available_for_vector_db": True,
    },
    "id": {
        "type": "string",
        "available_for_vector_db": True,
    },
}


def _vdb_config(*, db_path: str, collection: str = "test_collection") -> dict[str, Any]:
    """Build a VectorDBOperator config for Milvus Lite."""
    return {
        "provider": "milvus",
        "doc_id_column": "doc_id_hash",
        "add_sparse_vector": False,
        "available_features": AVAILABLE_FEATURES,
        "feature_mappings": FEATURE_MAPPINGS,
        "provider_config": {
            "collection_name": collection,
            "auth_type": "lite",
            "uri": db_path,
            "index_type": "FLAT",
            "metric_type": "COSINE",
            "batch_size": 100,
        },
    }


def _run_pipeline(*, fixture_dir: str, max_files: int = 3) -> Any:
    """Run ingest -> extract -> chunk -> embed and return the embedded table."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.core.operators.functional.chunker import ChunkerOperator
    from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator
    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    (ingest_table,), _ = IngestSourceOperator(
        config={
            "provider": "filesystem",
            "provider_config": {"paths": [fixture_dir]},
            "include_filter": "txt",
            "max_files": max_files,
            "force_ingest": True,
        }
    ).transform(None)

    (extract_table,), _ = ExtractOperator(
        config={
            "text_extraction": {"provider": "docling_library", "doc_column": "content"},
            "entity_extraction": {"provider": "none"},
        }
    ).transform(ingest_table)

    (chunk_table,), _ = ChunkerOperator(
        config={
            "chunk_type": "hybrid",
            "doc_column": "content",
            "chunk_size": 256,
            "chunk_overlap": 50,
            "retain_original_content": False,
        }
    ).transform(extract_table)

    (embed_table,), _ = EmbeddingsOperator(
        config={
            "provider": "huggingface",
            "embeddings_column": "embeddings",
            "provider_config": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "use_local": True,
            },
        }
    ).transform(chunk_table)

    return embed_table


# ------------------------------------------------------------------
# Test class
# ------------------------------------------------------------------


@pytest.mark.skipif(not _fixture_dir().exists(), reason="fixtures/customer_support_docs not found")
@pytest.mark.skipif(not _has_milvus_lite(), reason="milvus-lite not installed")
class TestIngestExtractChunkEmbedMilvusLite:
    """End-to-end integration tests: filesystem ingest -> docling extract -> hybrid chunk
    -> sentence-transformer embeddings -> Milvus Lite storage.
    """

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> str:
        """Return a fresh .db path inside a temporary directory."""
        return str(tmp_path / "milvus" / "test.db")

    def test_full_pipeline_with_feature_mappings(self, db_path: str) -> None:
        """
        Given: .txt fixtures on disk and explicit feature_mappings
        When:  the full ingest->extract->chunk->embed->milvus_lite pipeline runs
        Then:
          - All operators complete without errors
          - Chunks are indexed using the explicit field names from feature_mappings
            (pk, vector_embeddings, text, document_name, document_id)
          - The .db file exists on disk
          - Re-opening the database returns the collection with row_count > 0
        """
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

        embed_table = _run_pipeline(fixture_dir=str(_fixture_dir()))

        assert embed_table.num_rows > 0, "No rows after embedding"
        assert "embeddings" in embed_table.column_names, "embeddings column missing"

        # ── VectorDB (Milvus Lite) with explicit feature_mappings ──────────────
        vdb_op = VectorDBOperator(config=_vdb_config(db_path=db_path))
        (_vdb_table,), vdb_meta = vdb_op.transform(embed_table)

        assert vdb_meta.get("processed_docs", 0) > 0, f"VectorDB reported 0 processed docs. Metadata: {vdb_meta}"
        assert vdb_meta.get(Metrics.External.CHUNKS_FAILED_TO_INDEX, 0) == 0, (
            f"Some chunks failed to index. Metadata: {vdb_meta}"
        )

        # ── Persistence + field name check ─────────────────────────────────────
        assert Path(db_path).exists(), ".db file was not created on disk"

        from pymilvus import MilvusClient

        client2 = MilvusClient(db_path)
        try:
            assert "test_collection" in client2.list_collections(), "Collection not found after re-open"
            stats = client2.get_collection_stats("test_collection")
            row_count = int(stats.get("row_count", 0))
            assert row_count > 0, "Row count is 0 after re-opening the database"

            # Verify field names match the explicit feature_mappings
            desc = client2.describe_collection("test_collection")
            stored_field_names = {f["name"] for f in desc.get("fields", [])}
            for mapping in FEATURE_MAPPINGS:
                expected_field = mapping["mapped_column_name"]
                assert expected_field in stored_field_names, (
                    f"Expected Milvus field '{expected_field}' (from feature_mapping "
                    f"'{mapping['feature_name']}') not found in collection schema. "
                    f"Actual fields: {stored_field_names}"
                )
        finally:
            client2.close()

    def test_incremental_reindex_no_duplicates(self, db_path: str) -> None:
        """
        Given: documents already indexed in a Milvus Lite collection (run 1)
        When:  the same documents are processed and indexed again (run 2)
        Then:
          - Run 2 completes without errors
          - The row count after run 2 equals the row count after run 1
            (stale PK cleanup removed old chunks; re-inserted the same number)
          - No duplicate primary keys exist
        """
        from pymilvus import MilvusClient

        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

        fixture_dir = str(_fixture_dir())

        # ── Run 1: initial indexing ────────────────────────────────────────────
        embed_table = _run_pipeline(fixture_dir=fixture_dir)
        vdb_op1 = VectorDBOperator(config=_vdb_config(db_path=db_path))
        _, meta1 = vdb_op1.transform(embed_table)

        assert meta1.get("processed_docs", 0) > 0, f"Run 1 failed. meta={meta1}"

        client1 = MilvusClient(db_path)
        try:
            row_count_after_run1 = int(client1.get_collection_stats("test_collection").get("row_count", 0))
        finally:
            client1.close()

        assert row_count_after_run1 > 0, "No rows after run 1"

        # ── Run 2: same documents re-indexed (incremental) ─────────────────────
        # Re-run the full upstream pipeline to get the same embed_table.
        # The VectorDBOperator should: query existing PKs, detect no stale ones
        # (same content = same composite PKs), delete nothing, upsert the same rows.
        embed_table2 = _run_pipeline(fixture_dir=fixture_dir)
        vdb_op2 = VectorDBOperator(config=_vdb_config(db_path=db_path))
        _, meta2 = vdb_op2.transform(embed_table2)

        assert meta2.get("processed_docs", 0) > 0, f"Run 2 failed. meta={meta2}"

        client2 = MilvusClient(db_path)
        try:
            row_count_after_run2 = int(client2.get_collection_stats("test_collection").get("row_count", 0))
        finally:
            client2.close()

        # Row count must not grow — same chunks, same PKs, no duplicates.
        assert row_count_after_run2 == row_count_after_run1, (
            f"Row count changed after re-indexing same documents: "
            f"run1={row_count_after_run1}, run2={row_count_after_run2}. "
            "This indicates duplicate inserts (stale PK cleanup may have failed)."
        )

    def test_unsupported_index_type_rejected(self, db_path: str) -> None:
        """Milvus Lite must reject non-FLAT index types at initialization time."""
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        with pytest.raises((DocpipeException, Exception), match=r"(?i)flat|lite|unsupported|index"):
            VectorDBOperator(
                config={
                    "provider": "milvus",
                    "doc_id_column": "doc_id_hash",
                    "provider_config": {
                        "collection_name": "bad_index",
                        "auth_type": "lite",
                        "uri": db_path,
                        "index_type": "HNSW",  # Not supported by Lite
                        "metric_type": "COSINE",
                    },
                }
            )
