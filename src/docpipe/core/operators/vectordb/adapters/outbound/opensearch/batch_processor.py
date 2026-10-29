#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
OpenSearch Batch Processor
Handles bulk operations including indexing, updates, and deletes with batching logic.
"""

import json
from typing import Any

from opensearchpy import OpenSearch, helpers

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import build_mapping_dict, calculate_batch_size_bytes, feature_mapping_items

logger = get_logger()


# Batch processing constants
DEFAULT_BATCH_SIZE: int = 100
MAX_BATCH_SIZE_MB: int = 3  # Maximum batch size in MB
BULK_INSERT_TIMEOUT: int = 180  # 3 minutes timeout
BULK_DELETE_BATCH_SIZE: int = 500

# Predefined metadata columns to auto-aggregate
METADATA_COLUMNS: list[str] = [
    "name",
    "size",
    "created_time",
    "modified_time",
    "source",
    "mimetype",
    "extension",
    "page_count",
]

# Column name aliases for normalization
# Maps target metadata field names to possible source column names
METADATA_COLUMN_ALIASES: dict[str, list[str]] = {
    "source": ["source", "path"],  # Accept either name
    "page_count": ["page_count", "pages_processed"],  # Accept either name
    "extension": ["extension"],  # Will derive from name/path if missing
    "mimetype": ["mimetype", "mime_type", "content_type"],  # Accept variations
}


class OpenSearchBatchProcessor:
    """
    Manages batch operations for OpenSearch including bulk indexing and deletes.

    Responsibilities:
    - Size-aware batch processing
    - Bulk indexing with error tracking
    - Bulk delete operations
    - Document preparation and validation
    - Query operations
    """

    def __init__(
        self,
        *,
        client: OpenSearch,
        index_name: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        available_features: dict[str, Any] | None = None,
        feature_mappings: list[dict[str, str]] | None = None,
    ) -> None:
        """
        Initialize the batch processor.

        Args:
            client: OpenSearch client instance
            index_name: Name of the index
            batch_size: Maximum documents per batch
            available_features: Feature configuration
            feature_mappings: Canonical list-of-dicts column to field mappings
        """
        self.client = client
        self.index_name = index_name
        self.batch_size = batch_size
        self.available_features = available_features or {}
        self.feature_mappings: list[dict[str, str]] = feature_mappings or []
        self._mapping_dict: dict[str, str] = build_mapping_dict(mappings=self.feature_mappings)

    def prepare_document(self, *, row_data: dict[str, Any]) -> dict[str, Any]:
        """
        Prepare a document for indexing by mapping columns to index fields.

        Automatically aggregates predefined metadata columns into a 'metadata' object.
        Metadata columns can also be individually mapped via feature_mappings.

        Args:
            row_data: Raw row data from PyArrow table

        Returns:
            Prepared document ready for indexing
        """
        doc: dict[str, Any] = {}

        # Process fields defined in feature_mappings
        for feature_name, mapped_name in feature_mapping_items(self.feature_mappings):
            # Get value from row data
            value = row_data.get(feature_name)

            if value is None:
                continue

            # Get feature config for type information and validation
            feature_config: dict[str, Any] = self.available_features.get(feature_name, {})

            # Skip if explicitly marked as unavailable for vector db
            if not feature_config.get(OperatorConstants.Misc.FEATURE_ATTR_AVAILABLE_FOR_VECTOR_DB, True):
                continue

            # Skip binary data types that cannot be JSON serialized
            if isinstance(value, (bytes, bytearray)):
                continue

            # Convert numpy arrays to lists for JSON serialization
            if hasattr(value, "tolist"):
                value = value.tolist()

            # Parse JSON strings for object/nested types if type is specified
            feature_type: str = feature_config.get("type", "text")
            if feature_type in ("object", "nested", "json") and isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    # If parsing fails, keep as string
                    pass

            doc[mapped_name] = value

        # Auto-aggregate metadata columns
        metadata_obj = self._aggregate_metadata_columns(row_data=row_data)
        if metadata_obj:
            doc["metadata"] = metadata_obj

        return doc

    def _normalize_metadata_column(self, *, row_data: dict[str, Any], target_name: str) -> Any:
        """
        Normalize metadata column names and derive missing values.

        Args:
            row_data: Row data dictionary
            target_name: Target metadata field name

        Returns:
            Value for the metadata field, or None if not available
        """
        # Check aliases first
        if target_name in METADATA_COLUMN_ALIASES:
            for alias in METADATA_COLUMN_ALIASES[target_name]:
                if alias in row_data and row_data[alias] is not None:
                    return row_data[alias]

        # Derive extension from name or path
        if target_name == "extension":
            for source_col in ["name", "path", "source"]:
                if row_data.get(source_col):
                    path_str = str(row_data[source_col])
                    if "." in path_str:
                        return path_str.rsplit(".", 1)[-1].lower()
            return None

        # Derive mimetype from extension (basic mapping)
        if target_name == "mimetype":
            extension = self._normalize_metadata_column(row_data=row_data, target_name="extension")
            if extension:
                # Basic MIME type mapping
                mime_map = {
                    "pdf": "application/pdf",
                    "txt": "text/plain",
                    "json": "application/json",
                    "xml": "application/xml",
                    "html": "text/html",
                    "md": "text/markdown",
                    "csv": "text/csv",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }
                return mime_map.get(extension)
            return None

        # For columns without aliases, check direct column name
        if target_name in row_data:
            return row_data[target_name]

        return None

    def _aggregate_metadata_columns(self, *, row_data: dict[str, Any]) -> dict[str, Any]:
        """
        Aggregate predefined metadata columns into a single metadata object.
        Uses column name normalization and derivation for missing fields.

        Args:
            row_data: Row data dictionary

        Returns:
            Dictionary containing aggregated metadata
        """
        metadata: dict[str, Any] = {}

        for col_name in METADATA_COLUMNS:
            # Use normalization to get value
            value = self._normalize_metadata_column(row_data=row_data, target_name=col_name)

            if value is not None:
                # Skip binary data
                if isinstance(value, (bytes, bytearray)):
                    continue

                # Convert numpy arrays to lists
                if hasattr(value, "tolist"):
                    value = value.tolist()

                metadata[col_name] = value

        return metadata

    def bulk_index(self, actions: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
        """
        Perform bulk indexing operation.

        Args:
            actions: List of bulk actions

        Returns:
            Tuple of (success_count, failed_items)
        """
        try:
            success: int
            failed: list[dict[str, Any]]
            success, failed = helpers.bulk(
                self.client,
                actions,
                raise_on_error=False,
                raise_on_exception=False,
                request_timeout=BULK_INSERT_TIMEOUT,
            )
            return success, failed
        except Exception as e:
            logger.error("Bulk indexing failed: %s", e)
            return 0, actions

    def process_batches(self, all_actions: list[list[dict[str, Any]]]) -> tuple[int, list[dict[str, Any]]]:
        """
        Process multiple batches of actions.

        Args:
            all_actions: List of batches, where each batch is a list of actions

        Returns:
            Tuple of (total_success_count, all_failed_items)
        """
        success_count: int = 0
        all_failed: list[dict[str, Any]] = []

        for batch_idx, batch in enumerate(all_actions):
            try:
                logger.info("Processing batch %s/%s with %s documents", batch_idx + 1, len(all_actions), len(batch))

                success: int
                failed: list[dict[str, Any]]
                success, failed = self.bulk_index(batch)
                success_count += success

                if failed:
                    all_failed.extend(failed)

            except Exception as e:
                logger.error("Batch %s indexing failed: %s", batch_idx + 1, e)
                all_failed.extend(batch)

        logger.info("Successfully indexed %s documents in %s batches", success_count, len(all_actions))
        return success_count, all_failed

    def create_batches(self, documents: list[tuple[str, dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        """
        Create size-aware batches from documents.

        Args:
            documents: List of (doc_id, document) tuples

        Returns:
            List of batches, where each batch is a list of actions
        """
        all_actions: list[list[dict[str, Any]]] = []
        current_batch: list[dict[str, Any]] = []
        current_batch_size: int = 0
        max_batch_size_bytes: int = MAX_BATCH_SIZE_MB * 1024 * 1024

        for doc_id, doc in documents:
            prepared_doc = self.prepare_document(row_data=doc)

            action: dict[str, Any] = {
                "_op_type": "update",
                "_index": self.index_name,
                "_id": doc_id,
                "doc": prepared_doc,
                "doc_as_upsert": True,
            }

            # Check batch size
            action_size: int = calculate_batch_size_bytes(documents=[action])
            if current_batch and (
                current_batch_size + action_size > max_batch_size_bytes or len(current_batch) >= self.batch_size
            ):
                all_actions.append(current_batch)
                current_batch = []
                current_batch_size = 0

            current_batch.append(action)
            current_batch_size += action_size

        # Add remaining batch
        if current_batch:
            all_actions.append(current_batch)

        return all_actions

    def query_by_doc_names(self, doc_names: list[str], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Query documents by their names.

        Args:
            doc_names: List of document names to query
            fields: Optional list of fields to return

        Returns:
            List of matching documents
        """
        if not doc_names:
            return []

        try:
            # Build query
            query: dict[str, Any] = {
                "query": {"terms": {"name.keyword": doc_names}},
                "size": len(doc_names),
            }

            if fields:
                query["_source"] = fields

            response: dict[str, Any] = self.client.search(index=self.index_name, body=query)
            hits: list[dict[str, Any]] = response.get("hits", {}).get("hits", [])

            return [hit["_source"] for hit in hits]

        except Exception as e:
            logger.error("Error querying documents: %s", e)
            return []

    def delete_documents_by_ids(self, doc_ids: list[str]) -> tuple[int, int]:
        """
        Delete documents by their IDs.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Tuple of (success_count, failed_count)
        """
        if not doc_ids:
            return 0, 0

        success_count: int = 0
        failed_count: int = 0

        try:
            # Process in batches
            for i in range(0, len(doc_ids), BULK_DELETE_BATCH_SIZE):
                batch: list[str] = doc_ids[i : i + BULK_DELETE_BATCH_SIZE]

                # Build bulk delete actions
                actions: list[dict[str, Any]] = [
                    {"_op_type": "delete", "_index": self.index_name, "_id": doc_id} for doc_id in batch
                ]

                success: int
                failed: list[dict[str, Any]]
                success, failed = helpers.bulk(self.client, actions, raise_on_error=False, raise_on_exception=False)

                success_count += success
                failed_count += len(failed)

            logger.info("Deleted %s documents, %s failed", success_count, failed_count)

        except Exception as e:
            logger.error("Error deleting documents: %s", e)
            failed_count = len(doc_ids)

        return success_count, failed_count

    def get_document_count(self) -> int:
        """
        Get total document count in the index.

        Returns:
            Number of documents in the index
        """
        try:
            response: dict[str, Any] = self.client.count(index=self.index_name)
            return response.get("count", 0)
        except Exception as e:
            logger.error("Error getting document count: %s", e)
            return 0

    def _resolve_source_chunks(self, *, doc_ids: list[str]) -> dict[str, set[str]]:
        """Use a complete scroll snapshot; timeout/partial responses are not proof of absence."""
        if not doc_ids:
            return {}
        id_field = self._mapping_dict.get(OperatorConstants.Misc.ID, OperatorConstants.Misc.ID)
        # _id cannot be sorted: https://docs.opensearch.org/latest/field-types/metadata-fields/id/
        response = self.client.search(
            index=self.index_name,
            scroll="1m",
            body={"query": {"terms": {id_field: doc_ids}}, "_source": [id_field], "size": 1000, "sort": "_doc"},
        )
        scroll_id = response.get("_scroll_id")
        result: dict[str, set[str]] = {}
        try:
            while True:
                if (
                    response.get("timed_out")
                    or response.get("terminated_early")
                    or response.get("_shards", {}).get("failed", 0)
                ):
                    raise RuntimeError("Incomplete OpenSearch source chunk lookup")
                hits = response["hits"]["hits"]
                for hit in hits:
                    source_id = hit["_source"][id_field]
                    result.setdefault(source_id, set()).add(hit["_id"])
                if not hits:
                    return result
                if not scroll_id:
                    raise RuntimeError("OpenSearch source lookup did not return a continuation cursor")
                response = self.client.scroll(body={"scroll_id": scroll_id, "scroll": "1m"})
                scroll_id = response.get("_scroll_id", scroll_id)
        finally:
            if scroll_id:
                self.client.clear_scroll(body={"scroll_id": [scroll_id]})

    def get_chunk_ids_for_documents(self, *, doc_ids: list[str], strict: bool = False) -> dict[str, set[str]]:
        """Return all existing chunk PKs grouped by file ID.

        Searches the index for every document whose stored ``id`` field
        matches any of the supplied file IDs and returns their OpenSearch
        ``_id`` values (chunk PKs) grouped by the original file ID.

        The stored field name for the ``id`` feature is resolved from
        feature_mappings so user-overridden field names are handled correctly.
        Because positional PKs are stable across content changes, re-ingesting
        a modified document produces the same chunk ``_id`` values — OpenSearch
        upserts them in place and stale chunks (e.g. from a document that
        shrank) are deleted before re-insertion.

        Args:
            doc_ids: List of file IDs (``id`` column values) to look up.

        Returns:
            Mapping of file_id -> set of chunk PKs. File IDs with no indexed
            chunks are omitted from the result.
        """
        if strict:
            return self._resolve_source_chunks(doc_ids=doc_ids)
        if not doc_ids:
            return {}

        # Resolve the stored field name for the 'id' feature via feature_mappings.
        id_field: str = self._mapping_dict.get(
            OperatorConstants.Misc.ID,
            OperatorConstants.Misc.ID,
        )

        # Page size for search_after pagination. Keeps each request small while
        # handling any number of chunks without hitting the 10 000 result window cap.
        page_size = 1000

        try:
            result: dict[str, set[str]] = {}
            query: dict[str, Any] = {
                "query": {"terms": {id_field: doc_ids}},
                "_source": [id_field],
                "size": page_size,
                "sort": [{"_id": "asc"}],
            }

            while True:
                response: dict[str, Any] = self.client.search(index=self.index_name, body=query)
                hits: list[dict[str, Any]] = response.get("hits", {}).get("hits", [])

                for hit in hits:
                    chunk_pk: str = hit["_id"]
                    file_id: str | None = hit.get("_source", {}).get(id_field)
                    if file_id:
                        result.setdefault(file_id, set()).add(chunk_pk)

                # A page smaller than page_size (including empty) means no more results
                if len(hits) < page_size:
                    break

                # Advance the cursor to the next page
                query["search_after"] = hits[-1]["sort"]

            return result

        except Exception as e:
            logger.error("Error querying PKs by file IDs: %s", e)
            return {}
