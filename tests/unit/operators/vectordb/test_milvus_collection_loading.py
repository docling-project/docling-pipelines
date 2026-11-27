#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Regression tests for Milvus collection loading and query error handling.

A collection reopened in a new process reports ``NotLoad`` and rejects queries until it
is loaded. Query failures must surface as errors rather than as empty results, otherwise
stale-chunk and soft-delete cleanup silently skip work.
"""

import hashlib
from unittest.mock import MagicMock

import pytest
from pymilvus.client.types import LoadState

from docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor import MilvusBatchProcessor
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode

FEATURE_MAPPINGS = [{"feature_name": "doc_id_hash", "mapped_column_name": "doc_id_hash"}]


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


def _processor(client: MagicMock) -> MilvusBatchProcessor:
    return MilvusBatchProcessor(
        client=client,
        collection_name="test_collection",
        feature_mappings=FEATURE_MAPPINGS,
    )


def _state(state: LoadState) -> dict[str, LoadState]:
    return {"state": state}


@pytest.mark.unit
class TestCollectionLoadBeforeQuery:
    """Queries must load a collection that is not yet loaded, and only then."""

    def test_query_loads_collection_reported_not_loaded(self, mock_client: MagicMock) -> None:
        """Newly reopened collection (NotLoad) is loaded before the query runs."""
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.return_value = []
        _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        mock_client.load_collection.assert_called_once_with(collection_name="test_collection")
        names = [name for name, _, _ in mock_client.mock_calls]
        assert names == ["get_load_state", "load_collection", "query"]

    def test_already_loaded_collection_is_not_reloaded(self, mock_client: MagicMock) -> None:
        """A collection already in Loaded state skips load_collection entirely."""
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.return_value = []
        _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        mock_client.load_collection.assert_not_called()
        mock_client.query.assert_called_once()

    def test_repeated_queries_check_load_state_once(self, mock_client: MagicMock) -> None:
        """After a successful load the processor caches it; later queries add no load calls."""
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.return_value = []
        processor = _processor(mock_client)

        processor.query_by_doc_names(doc_names=["doc1"])
        processor.query_by_doc_names(doc_names=["doc2"])
        processor.query_by_doc_names(doc_names=["doc3"])

        mock_client.get_load_state.assert_called_once_with(collection_name="test_collection")
        mock_client.load_collection.assert_called_once_with(collection_name="test_collection")
        assert mock_client.query.call_count == 3

    def test_not_exist_collection_returns_empty_without_loading(self, mock_client: MagicMock) -> None:
        """First run: collection does not exist yet. Empty result, no load, no query."""
        mock_client.get_load_state.return_value = _state(LoadState.NotExist)

        result = _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        assert result == []
        mock_client.load_collection.assert_not_called()
        mock_client.query.assert_not_called()

    def test_load_state_check_failure_raises(self, mock_client: MagicMock) -> None:
        """If the load state itself cannot be read, the query raises instead of returning empty."""
        state_error = Exception("state unavailable")
        mock_client.get_load_state.side_effect = state_error

        with pytest.raises(DocpipeException, match=r"Failed to load collection.*state unavailable") as exc_info:
            _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        assert exc_info.value.__cause__ is state_error
        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED
        mock_client.query.assert_not_called()

    def test_load_failure_raises_and_skips_query(self, mock_client: MagicMock) -> None:
        """A failed load_collection surfaces as DocpipeException and the query is never attempted."""
        load_error = Exception("load timeout")
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.load_collection.side_effect = load_error

        with pytest.raises(DocpipeException, match="load timeout") as exc_info:
            _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        assert exc_info.value.__cause__ is load_error
        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED
        mock_client.query.assert_not_called()

    def test_load_failure_is_not_cached(self, mock_client: MagicMock) -> None:
        """After a failed load the next query retries the load rather than trusting a stale flag."""
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.load_collection.side_effect = [Exception("transient"), None]
        mock_client.query.return_value = []
        processor = _processor(mock_client)

        with pytest.raises(DocpipeException):
            processor.query_by_doc_names(doc_names=["doc1"])
        processor.query_by_doc_names(doc_names=["doc1"])

        assert mock_client.load_collection.call_count == 2
        mock_client.query.assert_called_once()

    def test_chunk_pk_query_loads_collection_first(self, mock_client: MagicMock) -> None:
        """Stale-chunk cleanup queries get the same load guarantee as document queries."""
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.return_value = []
        _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"])

        mock_client.load_collection.assert_called_once_with(collection_name="test_collection")
        names = [name for name, _, _ in mock_client.mock_calls]
        assert names == ["get_load_state", "load_collection", "query"]

    def test_chunk_pk_query_on_not_exist_returns_empty(self, mock_client: MagicMock) -> None:
        """First run cleanup on a missing collection returns {} and does not query."""
        mock_client.get_load_state.return_value = _state(LoadState.NotExist)

        result = _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"])

        assert result == {}
        mock_client.query.assert_not_called()


@pytest.mark.unit
class TestQueryResults:
    """Successful queries must be distinguishable from failed ones."""

    def test_matching_records_are_returned(self, mock_client: MagicMock) -> None:
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        rows = [{"doc_id_hash": "doc1", "text": "hello"}]
        mock_client.query.return_value = rows

        assert _processor(mock_client).query_by_doc_names(doc_names=["doc1"]) == rows

    def test_no_matching_records_returns_empty_list(self, mock_client: MagicMock) -> None:
        """A successful query with no hits is an empty list, not an error."""
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.return_value = []

        assert _processor(mock_client).query_by_doc_names(doc_names=["missing"]) == []

    def test_query_exception_is_raised_not_converted_to_empty(self, mock_client: MagicMock) -> None:
        """Regression: a query failure used to return [] and look like a successful empty query."""
        query_error = Exception("rpc error")
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.side_effect = query_error

        with pytest.raises(DocpipeException, match="rpc error") as exc_info:
            _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        assert exc_info.value.__cause__ is query_error
        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED
        mock_client.load_collection.assert_not_called()

    def test_chunk_pk_query_exception_is_raised_not_converted_to_empty(self, mock_client: MagicMock) -> None:
        """Regression: a failed PK lookup used to return {}, hiding stale chunks from cleanup."""
        query_error = Exception("rpc error")
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.side_effect = query_error

        with pytest.raises(DocpipeException, match="rpc error") as exc_info:
            _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"])

        assert exc_info.value.__cause__ is query_error
        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED

    def test_chunk_pk_failure_mid_loop_raises_without_partial_result(self, mock_client: MagicMock) -> None:
        """A failure on a later doc must raise, not return the PKs found for earlier docs."""
        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.side_effect = [
            [{"pk": f"{hash_a}_c1"}],
            Exception("timeout on doc_b"),
        ]

        with pytest.raises(DocpipeException, match="timeout on doc_b") as exc_info:
            _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a", "doc_b"])

        assert exc_info.value.error_code == ErrorCode.OPERATOR_EXECUTION_FAILED
        assert mock_client.query.call_count == 2

    def test_chunk_pk_matching_records_grouped_by_doc(self, mock_client: MagicMock) -> None:
        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.return_value = [{"pk": f"{hash_a}_c1"}, {"pk": f"{hash_a}_c2"}]

        result = _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"])

        assert result == {"doc_a": {f"{hash_a}_c1", f"{hash_a}_c2"}}

    def test_chunk_pk_no_matching_records_returns_empty_dict(self, mock_client: MagicMock) -> None:
        """Successful lookup with no chunks is {} (nothing stale), distinct from a failure."""
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.return_value = []

        assert _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"]) == {}


@pytest.mark.unit
class TestStaleChunkAndSoftDeleteCleanupSemantics:
    """Cleanup relies on the adapter raising on failure and returning {} only when nothing is stored."""

    def test_stale_pk_identification_uses_loaded_query_results(self, mock_client: MagicMock) -> None:
        """Existing PKs come from a loaded query, so stale = existing - new is computed on real data."""
        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.return_value = [{"pk": f"{hash_a}_old"}, {"pk": f"{hash_a}_new"}]

        existing = _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a"])

        assert existing == {"doc_a": {f"{hash_a}_old", f"{hash_a}_new"}}
        mock_client.load_collection.assert_called_once()

    def test_delete_by_ids_still_reports_failed_counts(self, mock_client: MagicMock) -> None:
        """Delete failures stay visible as failed counts so cleanup can log them."""
        mock_client.delete.side_effect = Exception("delete failed")

        success, failed = _processor(mock_client).delete_documents_by_ids(doc_ids=["a", "b"])

        assert (success, failed) == (0, 2)
        mock_client.load_collection.assert_not_called()

    def test_delete_does_not_require_loaded_collection(self, mock_client: MagicMock) -> None:
        """Deletes work on an unloaded collection (verified against Milvus Lite), so no load is forced."""
        mock_client.delete.return_value = {"delete_count": 2}

        success, failed = _processor(mock_client).delete_documents_by_ids(doc_ids=["a", "b"])

        assert (success, failed) == (2, 0)
        mock_client.get_load_state.assert_not_called()
        mock_client.load_collection.assert_not_called()


@pytest.mark.unit
class TestStaleLoadedFlag:
    """The cached loaded flag must not outlive a release, drop or recreation of the collection."""

    def test_release_between_queries_triggers_reload_and_retry(self, mock_client: MagicMock) -> None:
        """Release by another client: the next query reloads the collection and succeeds."""
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.side_effect = [[], Exception("collection not loaded"), []]
        processor = _processor(mock_client)

        assert processor.query_by_doc_names(doc_names=["doc1"]) == []
        assert processor.query_by_doc_names(doc_names=["doc2"]) == []

        assert mock_client.load_collection.call_count == 2
        names = [name for name, _, _ in mock_client.mock_calls]
        assert names == [
            "get_load_state",
            "load_collection",
            "query",
            "query",  # fails on the stale flag
            "get_load_state",
            "get_load_state",
            "load_collection",
            "query",
        ]

    def test_drop_between_queries_returns_empty_without_failing(self, mock_client: MagicMock) -> None:
        """Drop by another client: the collection no longer exists, so the lookup is empty, not an error."""
        mock_client.get_load_state.side_effect = [
            _state(LoadState.Loaded),  # initial check, cached afterwards
            _state(LoadState.NotExist),  # stale-flag diagnosis
            _state(LoadState.NotExist),  # re-check in the retry
        ]
        mock_client.query.side_effect = [[], Exception("collection not found")]
        processor = _processor(mock_client)

        assert processor.query_by_doc_names(doc_names=["doc1"]) == []
        assert processor.query_by_doc_names(doc_names=["doc2"]) == []

        assert mock_client.query.call_count == 2
        mock_client.load_collection.assert_not_called()

    def test_recreate_between_queries_loads_the_new_collection(self, mock_client: MagicMock) -> None:
        """Drop and recreate by another client: the new, unloaded collection is loaded and queried."""
        row = {"pk": "doc1"}
        mock_client.get_load_state.side_effect = [
            _state(LoadState.Loaded),
            _state(LoadState.NotLoad),  # stale-flag diagnosis: recreated collection is unloaded
            _state(LoadState.NotLoad),  # re-check in the retry
        ]
        mock_client.query.side_effect = [[], Exception("collection not loaded"), [row]]
        processor = _processor(mock_client)

        processor.query_by_doc_names(doc_names=["doc1"])
        assert processor.query_by_doc_names(doc_names=["doc1"]) == [row]

        mock_client.load_collection.assert_called_once_with(collection_name="test_collection")

    def test_failure_with_collection_still_loaded_is_raised_without_retry(self, mock_client: MagicMock) -> None:
        """A query error on a still-loaded collection is a real failure and is not retried."""
        query_error = Exception("rpc error")
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.side_effect = [[], query_error]
        processor = _processor(mock_client)
        processor.query_by_doc_names(doc_names=["doc1"])

        with pytest.raises(DocpipeException, match="rpc error") as exc_info:
            processor.query_by_doc_names(doc_names=["doc2"])

        assert exc_info.value.__cause__ is query_error
        assert mock_client.query.call_count == 2
        mock_client.load_collection.assert_not_called()

    def test_unreadable_state_after_failure_raises_original_query_error(self, mock_client: MagicMock) -> None:
        """If the diagnosis itself fails, the original query error is the one reported."""
        query_error = Exception("rpc error")
        mock_client.get_load_state.side_effect = [_state(LoadState.Loaded), Exception("state unavailable")]
        mock_client.query.side_effect = [[], query_error]
        processor = _processor(mock_client)
        processor.query_by_doc_names(doc_names=["doc1"])

        with pytest.raises(DocpipeException, match="rpc error") as exc_info:
            processor.query_by_doc_names(doc_names=["doc2"])

        assert exc_info.value.__cause__ is query_error

    def test_retry_is_limited_to_one_attempt(self, mock_client: MagicMock) -> None:
        """A query that keeps failing after the reload raises instead of looping."""
        retry_error = Exception("still failing")
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.side_effect = [[], Exception("collection not loaded"), retry_error]
        processor = _processor(mock_client)
        processor.query_by_doc_names(doc_names=["doc1"])

        with pytest.raises(DocpipeException, match="still failing") as exc_info:
            processor.query_by_doc_names(doc_names=["doc2"])

        assert exc_info.value.__cause__ is retry_error
        assert mock_client.query.call_count == 3

    def test_first_query_failure_is_not_retried(self, mock_client: MagicMock) -> None:
        """Without a cached flag there is nothing stale to recover from."""
        mock_client.get_load_state.return_value = _state(LoadState.Loaded)
        mock_client.query.side_effect = Exception("rpc error")

        with pytest.raises(DocpipeException):
            _processor(mock_client).query_by_doc_names(doc_names=["doc1"])

        mock_client.query.assert_called_once()

    def test_chunk_pk_lookup_recovers_from_release(self, mock_client: MagicMock) -> None:
        """Stale-chunk cleanup gets the same recovery as document queries."""
        hash_a = hashlib.sha3_512(b"doc_a").hexdigest()
        hash_b = hashlib.sha3_512(b"doc_b").hexdigest()
        mock_client.get_load_state.return_value = _state(LoadState.NotLoad)
        mock_client.query.side_effect = [
            [{"pk": f"{hash_a}_c1"}],
            Exception("collection not loaded"),
            [{"pk": f"{hash_b}_c1"}],
        ]

        result = _processor(mock_client).get_chunk_ids_for_documents(doc_ids=["doc_a", "doc_b"])

        assert result == {"doc_a": {f"{hash_a}_c1"}, "doc_b": {f"{hash_b}_c1"}}
        assert mock_client.load_collection.call_count == 2
