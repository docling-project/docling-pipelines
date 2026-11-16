# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WeaviateBatchProcessor."""

from unittest.mock import MagicMock

import pytest
from weaviate.exceptions import WeaviateConnectionError, WeaviateTimeoutError

from docpipe.core.operators.vectordb.adapters.outbound.weaviate.batch_processor import (
    WeaviateBatchProcessor,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestWeaviateBatchProcessor:
    """Test suite for WeaviateBatchProcessor writes, deletes, counts, and queries."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock Weaviate client."""
        return MagicMock()

    def test_prepare_document_mappings_and_types(self, *, mock_client: MagicMock) -> None:
        """Verify prepare_document separates scalar properties and vectors with proper conversions."""
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "collection_column": "pk"},
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "metadata", "collection_column": "meta_info"},
                {"feature_name": "binary_data", "collection_column": "binary_col"},
                {"feature_name": "embeddings", "collection_column": "embeddings"},
                {"feature_name": "sparse_embeddings", "collection_column": "sparse_embeddings"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
                "metadata": {"type": "json"},
                "binary_data": {"type": "binary"},
                "embeddings": {"type": "vector"},
                "sparse_embeddings": {"type": "sparse_vector"},
            },
            add_sparse_vector=True,
        )

        row_data = {
            "doc_id_hash": "hash123",
            "content": "Hello world text",
            "metadata": {"source": "web", "page": 1},
            "binary_data": b"\x00\x01\x02",
            "embeddings": [0.1, 0.2, 0.3],
            "sparse_embeddings": {"indices": [1, 2], "values": [0.5, 0.6]},
            "extra_unmapped": "ignore",
            "none_val": None,
        }

        props, vecs = processor.prepare_document(row_data=row_data)

        assert props["pk"] == "hash123"
        assert props["content"] == "Hello world text"
        assert props["meta_info"] == '{"source": "web", "page": 1}'
        assert "binary_col" not in props  # bytes skipped
        assert "sparse_embeddings" not in props  # sparse_embeddings skipped
        assert "extra_unmapped" not in props
        assert "none_val" not in props

        assert "embeddings" in vecs
        assert vecs["embeddings"] == [0.1, 0.2, 0.3]

    @pytest.mark.parametrize("add_sparse_vector", [True, False])
    def test_prepare_document_never_stores_sparse_embeddings(
        self, *, mock_client: MagicMock, add_sparse_vector: bool
    ) -> None:
        """A mapped sparse_embeddings value reaches neither properties nor vectors, with the flag on or off."""
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "content", "collection_column": "text"},
                {"feature_name": "embeddings", "collection_column": "vector_embeddings"},
                {"feature_name": "sparse_embeddings", "collection_column": "sparse_data"},
            ],
            available_features={
                "content": {"type": "text"},
                "embeddings": {"type": "vector"},
                "sparse_embeddings": {"type": "vector_sparse"},
            },
            embeddings_column="embeddings",
            add_sparse_vector=add_sparse_vector,
        )

        props, vecs = processor.prepare_document(
            row_data={
                "content": "hello",
                "embeddings": [0.1, 0.2],
                "sparse_embeddings": {"indices": [1], "values": [0.5]},
            }
        )

        assert props == {"text": "hello"}
        assert list(vecs) == ["vector_embeddings"]

    def test_create_batches_count_limit_and_uuid_determinism(self, *, mock_client: MagicMock) -> None:
        """Verify create_batches splits by batch_size and generates deterministic UUIDv5."""
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            batch_size=2,
            feature_mappings=[
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "embeddings", "collection_column": "embeddings"},
            ],
            available_features={
                "content": {"type": "text"},
                "embeddings": {"type": "vector"},
            },
        )

        documents = [
            ("chunk_1", {"content": "Doc 1", "embeddings": [0.1, 0.2]}),
            ("chunk_2", {"content": "Doc 2", "embeddings": [0.3, 0.4]}),
            ("chunk_3", {"content": "Doc 3", "embeddings": [0.5, 0.6]}),
        ]

        batches, failed_items = processor.create_batches(documents=documents)
        assert failed_items == []

        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

        obj1 = batches[0][0]
        assert obj1.properties["pk"] == "chunk_1"
        assert obj1.properties["content"] == "Doc 1"
        assert obj1.vector["embeddings"] == [0.1, 0.2]

        # Verify UUID determinism
        batches_again, _ = processor.create_batches(
            documents=[("chunk_1", {"content": "Doc 1", "embeddings": [0.1, 0.2]})]
        )
        assert batches_again[0][0].uuid == obj1.uuid

    def test_create_batches_sparse_only_has_no_vector(self, *, mock_client: MagicMock) -> None:
        """Verify sparse-only documents have vector=None in DataObject."""
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "content", "collection_column": "content"},
            ],
            available_features={"content": {"type": "text"}},
            add_sparse_vector=True,
        )

        batches, _ = processor.create_batches(documents=[("chunk_pk", {"content": "text only"})])
        assert len(batches) == 1
        assert batches[0][0].vector is None

    def test_create_batches_isolates_unpreparable_document(self, *, mock_client: MagicMock) -> None:
        """A non-numeric vector fails only its own chunk; the other chunks are still batched."""
        secret = "wv-secret-value"  # pragma: allowlist secret
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            secrets=[secret],
            feature_mappings=[
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "embeddings", "collection_column": "embeddings"},
            ],
            available_features={"content": {"type": "text"}, "embeddings": {"type": "vector"}},
        )

        batches, failed_items = processor.create_batches(
            documents=[
                ("pk_ok_1", {"content": "a", "embeddings": [0.1, 0.2]}),
                ("pk_bad", {"content": "b", "embeddings": [0.1, f"not-a-number-{secret}"]}),
                ("pk_ok_2", {"content": "c", "embeddings": [0.3, 0.4]}),
            ]
        )

        assert [obj.properties["pk"] for batch in batches for obj in batch] == ["pk_ok_1", "pk_ok_2"]
        assert len(failed_items) == 1
        assert failed_items[0]["index"]["_id"] == "pk_bad"
        reason = failed_items[0]["index"]["error"]["reason"]
        assert secret not in reason
        assert "ValueError" in reason

    def test_process_batches_success(self, *, mock_client: MagicMock) -> None:
        """Verify successful batch insertion."""
        mock_coll = MagicMock()
        mock_result = MagicMock()
        mock_result.errors = {}
        mock_coll.data.insert_many.return_value = mock_result
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[{"feature_name": "content", "collection_column": "content"}],
            available_features={"content": {"type": "text"}},
        )

        batches, _ = processor.create_batches(
            documents=[
                ("pk1", {"content": "doc1"}),
                ("pk2", {"content": "doc2"}),
            ]
        )

        success_count, failed_items = processor.process_batches(batches=batches)
        assert success_count == 2
        assert failed_items == []

    def test_process_batches_partial_errors_redacted(self, *, mock_client: MagicMock) -> None:
        """Verify partial errors from result.errors are mapped and redacted."""
        secret = "secret_wv_token_777"  # pragma: allowlist secret
        mock_coll = MagicMock()
        mock_result = MagicMock()

        mock_err = MagicMock()
        mock_err.message = f"Write error for auth Bearer {secret}"
        mock_result.errors = {1: mock_err}  # second object failed
        mock_coll.data.insert_many.return_value = mock_result
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            secrets=[secret],
            feature_mappings=[{"feature_name": "content", "collection_column": "content"}],
            available_features={"content": {"type": "text"}},
        )

        batches, _ = processor.create_batches(
            documents=[
                ("pk1", {"content": "doc1"}),
                ("pk2", {"content": "doc2"}),
            ]
        )

        success_count, failed_items = processor.process_batches(batches=batches)
        assert success_count == 1
        assert len(failed_items) == 1
        assert failed_items[0]["index"]["_id"] == "pk2"
        reason = failed_items[0]["index"]["error"]["reason"]
        assert secret not in reason
        assert "***" in reason

    def test_process_batches_exception_marks_batch_failed_and_continues(self, *, mock_client: MagicMock) -> None:
        """Verify an exception on batch 1 marks its objects failed and batch 2 still succeeds."""
        mock_coll = MagicMock()
        mock_res2 = MagicMock()
        mock_res2.errors = {}
        mock_coll.data.insert_many.side_effect = [
            RuntimeError("Server crashed on batch 1"),
            mock_res2,
        ]
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            batch_size=1,
            feature_mappings=[{"feature_name": "content", "collection_column": "content"}],
            available_features={"content": {"type": "text"}},
        )

        batches, _ = processor.create_batches(
            documents=[
                ("pk1", {"content": "doc1"}),
                ("pk2", {"content": "doc2"}),
            ]
        )

        success_count, failed_items = processor.process_batches(batches=batches)
        assert success_count == 1
        assert len(failed_items) == 1
        assert failed_items[0]["index"]["_id"] == "pk1"

    def test_delete_documents_by_ids_chunked(self, *, mock_client: MagicMock) -> None:
        """Verify delete_documents_by_ids chunks in 500s."""
        mock_coll = MagicMock()
        mock_del_res = MagicMock()
        mock_del_res.successful = 500
        mock_del_res.failed = 0
        mock_coll.data.delete_many.return_value = mock_del_res
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
        )

        # 1201 keys -> 3 delete calls (500, 500, 201)
        pks = [f"key_{i}" for i in range(1201)]
        total_success, total_failed = processor.delete_documents_by_ids(chunk_pks=pks)

        assert mock_coll.data.delete_many.call_count == 3
        assert total_success == 1500  # 3 * 500 mock returns
        assert total_failed == 0

    def test_get_document_count(self, *, mock_client: MagicMock) -> None:
        """Verify get_document_count returns the count and raises a DocpipeException on error."""
        mock_coll = MagicMock()
        mock_coll.aggregate.over_all.return_value.total_count = 42
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
        )
        assert processor.get_document_count() == 42

        mock_coll.aggregate.over_all.side_effect = RuntimeError("Aggregate failed")
        with pytest.raises(
            DocpipeException, match="Failed to count objects in Weaviate collection 'TestDocs'"
        ) as exc_info:
            processor.get_document_count()
        assert exc_info.value.status_code == 500
        assert exc_info.value.__cause__ is None

    def test_read_failures_for_unreachable_server_are_503(self, *, mock_client: MagicMock) -> None:
        """Connection and timeout errors from the SDK map to 503; chunk-id lookup also raises."""
        processor = WeaviateBatchProcessor(client=mock_client, collection_name="TestDocs")
        for sdk_error in (WeaviateConnectionError("down"), WeaviateTimeoutError("slow")):
            mock_client.collections.get.side_effect = sdk_error
            for call in (
                lambda: processor.get_document_count(),
                lambda: processor.get_chunk_ids_for_documents(file_ids=["f"]),
                lambda: processor.query_by_doc_names(doc_names=["a.pdf"]),
            ):
                with pytest.raises(DocpipeException) as exc_info:
                    call()
                assert exc_info.value.status_code == 503
                assert type(sdk_error).__name__ in str(exc_info.value)

    def test_get_chunk_ids_for_documents_keyset_paging(self, *, mock_client: MagicMock) -> None:
        """Verify keyset paging fetches all chunks across multiple pages."""
        mock_coll = MagicMock()

        # Page 1: 1000 items
        page1_objs = [MagicMock(properties={"pk": f"file1_chunk_{i:04d}"}) for i in range(1000)]
        # Page 2: 250 items (short page -> stop)
        page2_objs = [MagicMock(properties={"pk": f"file1_chunk_{i:04d}"}) for i in range(1000, 1250)]

        res1 = MagicMock(objects=page1_objs)
        res2 = MagicMock(objects=page2_objs)

        mock_coll.query.fetch_objects.side_effect = [res1, res2]
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
        )

        chunks_map = processor.get_chunk_ids_for_documents(file_ids=["file_1"])
        assert "file_1" in chunks_map
        assert len(chunks_map["file_1"]) == 1250
        assert mock_coll.query.fetch_objects.call_count == 2

    @pytest.mark.parametrize(
        "mappings",
        [
            [("id", "file_id"), ("name", "doc_name")],
            [("name", "doc_name"), ("id", "file_id")],
        ],
    )
    def test_query_by_doc_names_ignores_mapping_order(
        self, *, mock_client: MagicMock, mappings: list[tuple[str, str]]
    ) -> None:
        """The name lookup filters the name property whichever mapping is declared first."""
        mock_coll = MagicMock()
        mock_coll.query.fetch_objects.return_value.objects = []
        mock_client.collections.get.return_value = mock_coll
        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[{"feature_name": f, "mapped_column_name": c} for f, c in mappings],
        )
        processor.query_by_doc_names(doc_names=["report.pdf"])
        used = mock_coll.query.fetch_objects.call_args.kwargs["filters"]
        assert used.target == "doc_name"

    def test_query_by_doc_names_error_is_redacted(self, *, mock_client: MagicMock, caplog) -> None:
        secret = "resolved-" + "credential-value"  # pragma: allowlist secret
        mock_client.collections.get.side_effect = RuntimeError(f"denied for {secret}")
        processor = WeaviateBatchProcessor(client=mock_client, collection_name="TestDocs", secrets=[secret])
        with caplog.at_level("DEBUG"):
            with pytest.raises(DocpipeException) as exc_info:
                processor.query_by_doc_names(doc_names=["a.pdf"])
        assert secret not in str(exc_info.value)
        assert "***" in str(exc_info.value)
        assert secret not in caplog.text

    @staticmethod
    def _page(*, start: int, count: int, extra: dict | None = None) -> MagicMock:
        objects = [MagicMock(properties={"pk": f"k_{i:05d}", **(extra or {})}) for i in range(start, start + count)]
        return MagicMock(objects=objects)

    def test_query_by_doc_names_pages_through_all_results(self, *, mock_client: MagicMock) -> None:
        """More matches than one page are all returned, and each later page starts after the last pk."""
        mock_coll = MagicMock()
        mock_coll.query.fetch_objects.side_effect = [
            self._page(start=0, count=1000, extra={"doc_name": "a.pdf"}),
            self._page(start=1000, count=40, extra={"doc_name": "a.pdf"}),
        ]
        mock_client.collections.get.return_value = mock_coll
        processor = WeaviateBatchProcessor(client=mock_client, collection_name="TestDocs")

        results = processor.query_by_doc_names(doc_names=["a.pdf"])

        assert len(results) == 1040
        assert results[-1]["pk"] == "k_01039"
        assert mock_coll.query.fetch_objects.call_count == 2
        first, second = mock_coll.query.fetch_objects.call_args_list
        assert first.kwargs["limit"] == 1000
        assert first.kwargs["return_properties"] is None
        assert "greater_than" not in repr(first.kwargs["filters"]).lower()
        assert second.kwargs["filters"].filters[1].value == "k_00999"

    def test_query_by_doc_names_adds_and_strips_pk_when_not_requested(self, *, mock_client: MagicMock) -> None:
        """pk is fetched to page when fields omit it, and removed from the results."""
        mock_coll = MagicMock()
        mock_coll.query.fetch_objects.side_effect = [
            self._page(start=0, count=1000, extra={"doc_name": "a.pdf"}),
            self._page(start=1000, count=1, extra={"doc_name": "a.pdf"}),
        ]
        mock_client.collections.get.return_value = mock_coll
        processor = WeaviateBatchProcessor(client=mock_client, collection_name="TestDocs")

        results = processor.query_by_doc_names(doc_names=["a.pdf"], fields=["doc_name"])

        assert len(results) == 1001
        assert all(set(row) == {"doc_name"} for row in results)
        assert mock_coll.query.fetch_objects.call_args_list[0].kwargs["return_properties"] == ["doc_name", "pk"]

    def test_query_by_doc_names_keeps_pk_when_requested(self, *, mock_client: MagicMock) -> None:
        mock_coll = MagicMock()
        mock_coll.query.fetch_objects.return_value = self._page(start=0, count=3, extra={"doc_name": "a.pdf"})
        mock_client.collections.get.return_value = mock_coll
        processor = WeaviateBatchProcessor(client=mock_client, collection_name="TestDocs")

        results = processor.query_by_doc_names(doc_names=["a.pdf"], fields=["pk", "doc_name"])

        assert [row["pk"] for row in results] == ["k_00000", "k_00001", "k_00002"]
        assert mock_coll.query.fetch_objects.call_args.kwargs["return_properties"] == ["pk", "doc_name"]

    def test_query_by_doc_names(self, *, mock_client: MagicMock) -> None:
        """Verify query_by_doc_names queries Weaviate and returns property dicts."""
        mock_coll = MagicMock()
        mock_obj1 = MagicMock(properties={"doc_name": "doc1.pdf", "content": "hello"})
        mock_coll.query.fetch_objects.return_value.objects = [mock_obj1]
        mock_client.collections.get.return_value = mock_coll

        processor = WeaviateBatchProcessor(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[{"feature_name": "doc_name", "collection_column": "name_field"}],
        )

        results = processor.query_by_doc_names(doc_names=["doc1.pdf"])
        assert len(results) == 1
        assert results[0]["doc_name"] == "doc1.pdf"
