# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Weaviate Batch Processor for bulk document indexing, deletion, queries, and keyset paging."""

import hashlib
import json
from typing import Any

import weaviate
from weaviate.classes.data import DataObject
from weaviate.classes.query import Filter, Sort
from weaviate.util import generate_uuid5

from docpipe.core.constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient, redact_secrets
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import (
    build_mapping_dict,
    calculate_batch_size_bytes,
)

logger = get_logger()

DEFAULT_BATCH_SIZE: int = 100
MAX_BATCH_SIZE_MB: int = 3
BULK_DELETE_BATCH_SIZE: int = 500
KEYSET_PAGE_SIZE: int = 1000
NAME_FEATURES: tuple[str, ...] = ("name", "doc_name")
DEFAULT_NAME_FIELD: str = "doc_name"


class WeaviateBatchProcessor:
    """Manages batch write, delete, query, and keyset-paging operations for Weaviate."""

    def __init__(
        self,
        *,
        client: WeaviateClient | weaviate.WeaviateClient,
        collection_name: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        available_features: dict[str, Any] | None = None,
        feature_mappings: list[dict[str, str]] | None = None,
        primary_key_field: str = "pk",
        embeddings_column: str = OperatorConstants.Operators.EMBEDDINGS,
        add_sparse_vector: bool = False,
        secrets: list[str] | None = None,
    ) -> None:
        self.client_wrapper = client if isinstance(client, WeaviateClient) else None
        self._raw_client = client if not isinstance(client, WeaviateClient) else None
        self.collection_name = collection_name
        self.batch_size = batch_size
        self.available_features = available_features or {}
        self.feature_mappings = feature_mappings or []
        self._mapping_dict = build_mapping_dict(mappings=self.feature_mappings)
        self.primary_key_field = primary_key_field
        self.embeddings_column = embeddings_column
        self.add_sparse_vector = add_sparse_vector
        self.secrets = [s for s in (secrets or []) if s]

    @property
    def client(self) -> weaviate.WeaviateClient:
        if self._raw_client is not None:
            return self._raw_client
        if self.client_wrapper is not None:
            return self.client_wrapper.get_client()
        raise DocpipeException(
            message="No Weaviate client available",
            status_code=500,
            error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
        )

    def _redact(self, text: str) -> str:
        """Redact secrets and authorization headers from error messages."""
        return redact_secrets(text=text, secrets=self.secrets)

    def prepare_document(
        self,
        *,
        row_data: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[float]]]:
        """Prepare document properties and vectors from raw row data.

        Returns:
            Tuple of (properties_dict, vectors_dict)
        """
        properties: dict[str, Any] = {}
        vectors: dict[str, list[float]] = {}

        for entry in self.feature_mappings:
            feature_name = entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name"))
            mapped_name = entry.get(
                OperatorConstants.Misc.MAPPED_COLUMN_NAME,
                entry.get("collection_column", entry.get("mapped_column_name")),
            )
            if not feature_name or not mapped_name:
                continue

            # Weaviate has no field for sparse vectors (BM25 runs over the content property), so the
            # mapping is accepted but never stored, whether or not add_sparse_vector is set.
            if feature_name == OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT:
                continue

            value = row_data.get(feature_name)
            if value is None:
                continue

            feature_config: dict[str, Any] = self.available_features.get(feature_name, {})
            if not feature_config.get(OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB, True):
                continue

            if isinstance(value, (bytes, bytearray)):
                continue

            feature_type: str = feature_config.get("type", "text") if isinstance(feature_config, dict) else "text"

            if feature_type == "vector" or feature_name == self.embeddings_column:
                if hasattr(value, "tolist"):
                    vector_list = [float(x) for x in value.tolist()]
                elif isinstance(value, (list, tuple)):
                    vector_list = [float(x) for x in value]
                else:
                    vector_list = [float(value)]
                vectors[mapped_name] = vector_list
                continue

            if hasattr(value, "tolist"):
                value = value.tolist()

            if feature_type in ("object", "nested", "json"):
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                elif not isinstance(value, str):
                    value = str(value)
            elif feature_type in ("text", "string") and not isinstance(value, str):
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                else:
                    value = str(value)

            properties[mapped_name] = value

        return properties, vectors

    def create_batches(
        self,
        *,
        documents: list[tuple[str, dict[str, Any]]],
    ) -> list[list[DataObject[Any, Any]]]:
        """Create batches of DataObjects respecting batch_size count and 3 MB payload caps."""
        batches: list[list[DataObject[Any, Any]]] = []
        current_batch: list[DataObject[Any, Any]] = []
        current_size: int = 0
        max_size_bytes: int = MAX_BATCH_SIZE_MB * 1024 * 1024

        logger.info(
            "Creating batches from %d documents (batch_size=%d, max_size=%dMB)",
            len(documents),
            self.batch_size,
            MAX_BATCH_SIZE_MB,
        )

        for chunk_pk, doc_data in documents:
            props, vecs = self.prepare_document(row_data=doc_data)
            props[self.primary_key_field] = chunk_pk
            obj_uuid = str(generate_uuid5(chunk_pk))

            doc_size = calculate_batch_size_bytes(documents=[props])

            if current_batch and (len(current_batch) >= self.batch_size or (current_size + doc_size) > max_size_bytes):
                batches.append(current_batch)
                current_batch = []
                current_size = 0

            data_obj = DataObject(
                properties=props,
                uuid=obj_uuid,
                vector=vecs if vecs else None,
            )
            current_batch.append(data_obj)
            current_size += doc_size

        if current_batch:
            batches.append(current_batch)

        logger.info("Created %d batches from %d documents", len(batches), len(documents))
        return batches

    def process_batches(
        self,
        *,
        batches: list[list[DataObject[Any, Any]]],
    ) -> tuple[int, list[dict[str, Any]]]:
        """Insert batches into Weaviate using data.insert_many and collect failed objects."""
        total_success = 0
        all_failed: list[dict[str, Any]] = []

        collection = self.client.collections.get(self.collection_name)

        for i, batch in enumerate(batches):
            try:
                logger.info(
                    "[WEAVIATE INSERT] Batch %d/%d: Inserting %d objects into '%s'",
                    i + 1,
                    len(batches),
                    len(batch),
                    self.collection_name,
                )
                result = collection.data.insert_many(batch)

                error_count = len(result.errors) if result.errors else 0
                if error_count > 0:
                    for idx, err_obj in result.errors.items():
                        chunk_pk = (
                            batch[idx].properties.get("pk", str(batch[idx].uuid))
                            if batch[idx].properties
                            else str(batch[idx].uuid)
                        )
                        err_reason = self._redact(err_obj.message)
                        all_failed.append({"index": {"_id": chunk_pk, "error": {"reason": err_reason}}})

                success_count = len(batch) - error_count
                total_success += success_count

            except Exception as e:
                err_str = self._redact(str(e))
                logger.error("[WEAVIATE INSERT] Batch %d/%d failed: %s", i + 1, len(batches), err_str)
                for obj in batch:
                    chunk_pk = obj.properties.get("pk", str(obj.uuid)) if obj.properties else str(obj.uuid)
                    all_failed.append({"index": {"_id": chunk_pk, "error": {"reason": err_str}}})

        logger.info("[WEAVIATE INSERT] Completed: %d inserted successfully, %d failed", total_success, len(all_failed))
        return total_success, all_failed

    def delete_documents_by_ids(self, *, chunk_pks: list[str]) -> tuple[int, int]:
        """Delete documents by their primary keys in chunks of 500."""
        if not chunk_pks:
            return 0, 0

        total_success = 0
        total_failed = 0
        collection = self.client.collections.get(self.collection_name)

        for i in range(0, len(chunk_pks), BULK_DELETE_BATCH_SIZE):
            chunk_slice = chunk_pks[i : i + BULK_DELETE_BATCH_SIZE]
            uuids = [str(generate_uuid5(pk)) for pk in chunk_slice]
            try:
                res = collection.data.delete_many(where=Filter.by_id().contains_any(uuids))
                total_success += getattr(res, "successful", len(chunk_slice))
                total_failed += getattr(res, "failed", 0)
            except Exception as exc:
                logger.error("Error deleting document batch from Weaviate: %s", self._redact(str(exc)))
                total_failed += len(chunk_slice)

        return total_success, total_failed

    def get_document_count(self) -> int:
        """Get total object count in the collection."""
        try:
            collection = self.client.collections.get(self.collection_name)
            res = collection.aggregate.over_all(total_count=True)
            return int(res.total_count or 0)
        except Exception as exc:
            logger.warning(
                "Error getting document count for collection '%s': %s", self.collection_name, self._redact(str(exc))
            )
            return 0

    def get_chunk_ids_for_documents(self, *, file_ids: list[str]) -> dict[str, list[str]]:
        """Retrieve chunk primary keys for given file IDs using keyset paging."""
        chunk_ids_map: dict[str, list[str]] = {}
        try:
            collection = self.client.collections.get(self.collection_name)
            for file_id in file_ids:
                prefix = f"{hashlib.sha3_512(file_id.encode('utf-8')).hexdigest()}_chunk_"
                file_chunks: list[str] = []
                last_pk: str | None = None

                while True:
                    filt = Filter.by_property("pk").like(f"{prefix}*")
                    if last_pk is not None:
                        filt = filt & Filter.by_property("pk").greater_than(last_pk)

                    res = collection.query.fetch_objects(
                        filters=filt,
                        sort=Sort.by_property("pk", ascending=True),
                        return_properties=["pk"],
                        limit=KEYSET_PAGE_SIZE,
                    )
                    objects = res.objects or []
                    if not objects:
                        break

                    for obj in objects:
                        if obj.properties and "pk" in obj.properties:
                            pk_val = str(obj.properties["pk"])
                            file_chunks.append(pk_val)
                            last_pk = pk_val

                    if len(objects) < KEYSET_PAGE_SIZE:
                        break

                chunk_ids_map[file_id] = file_chunks
            return chunk_ids_map
        except Exception as exc:
            logger.warning("Error querying chunk IDs for file IDs: %s", self._redact(str(exc)))
            return {}

    def _name_field(self) -> str:
        """Return the column mapped to the document name, independent of mapping order."""
        mapped = {
            entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name")): entry.get(
                OperatorConstants.Misc.MAPPED_COLUMN_NAME,
                entry.get("collection_column", entry.get("mapped_column_name")),
            )
            for entry in self.feature_mappings
        }
        for feature in NAME_FEATURES:
            if mapped.get(feature):
                return str(mapped[feature])
        return DEFAULT_NAME_FIELD

    def query_by_doc_names(
        self,
        *,
        doc_names: list[str],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query document properties by matching document names."""
        if not doc_names:
            return []

        name_field = self._name_field()

        try:
            collection = self.client.collections.get(self.collection_name)
            res = collection.query.fetch_objects(
                filters=Filter.by_property(name_field).contains_any(doc_names),
                return_properties=fields,
            )
            return [dict(obj.properties) for obj in (res.objects or []) if obj.properties]
        except Exception as exc:
            logger.warning("Error querying documents by name: %s", self._redact(str(exc)))
            return []
