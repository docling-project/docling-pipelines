# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Service implementing node-level failure resumption.

A document that fails at node K of a flow is recorded with the node, the job run and the original error. On the next
run of the same job the document is not re-ingested from scratch: it is deferred and its input row is read back from
the intermediate output that node K-1 saved in the failed run (available when ``data_storage_type`` is not
``memory``). The row is injected into node K, bypassing nodes 1 to K-1, until the document succeeds or exhausts
``max_retry_attempts`` retries. A document that failed at several nodes (for example in different branches) is
resumed at each of them.
"""

import hashlib
import re
from collections import defaultdict
from enum import StrEnum
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.compute as pc

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.models.resumption_plan import DeferredRecord, FailedNode, ResumptionRecord
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

RETRIES_EXHAUSTED_PREFIX = "Maximum retries exhausted"
SINGLE_BATCH_KEY = "__single__"
_BRANCH_CRITERIA = "branch_criteria"
_RECORDS_COLLECTION = "resumption"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class NodeOutputTableName(Protocol):
    """Resolves the table holding the saved output of a node in an earlier job run."""

    def __call__(self, *, job_run_id: str, node_name: str, output_index: int) -> str:
        """Return the name of the table in the table storage."""


class ResumptionDecision(StrEnum):
    """Outcome of classifying a re-encountered document at ingest."""

    FRESH = "fresh"
    DEFER = "defer"
    EXHAUSTED = "exhausted"


def resumption_batch_key(*, batch_id: str | None) -> str:
    """Return the key under which the resumption plan stores entries of a batch."""
    return str(batch_id) if batch_id else SINGLE_BATCH_KEY


class ResumptionService:
    """Decides, records and applies node-level resumption of failed documents.

    Failure records are kept in a key-value storage, one record per document under the collection
    ``<job_id>/resumption``. The rows a document is resumed from are read from a table storage that holds the
    intermediate node outputs of the flow; no copy of the data is made.
    """

    def __init__(
        self,
        *,
        record_storage: KeyValueStoragePort,
        max_retry_attempts: int,
        table_storage: TableStoragePort | None = None,
        output_table_name: NodeOutputTableName | None = None,
    ) -> None:
        self._record_storage = record_storage
        self._table_storage = table_storage
        self._output_table_name = output_table_name
        # Total attempts per document = 1 initial execution + max_retry_attempts retries
        self._max_retry_attempts = max(0, max_retry_attempts)

    @property
    def max_retry_attempts(self) -> int:
        """Configured number of retries after the initial attempt."""
        return self._max_retry_attempts

    # ------------------------------------------------------------------ record storage

    @staticmethod
    def _collection(*, job_id: str) -> str:
        """Return the collection of the records of a job; the job id must be a plain name."""
        if not job_id or not _SAFE_ID.match(job_id) or job_id in {".", ".."}:
            msg = "Invalid job_id for resumption records"
            raise ValueError(msg)
        return f"{job_id}/{_RECORDS_COLLECTION}"

    @staticmethod
    def _key(*, doc_id: str) -> str:
        """Return the record key of a document; a digest, so document ids never influence the path."""
        return hashlib.sha256(doc_id.encode()).hexdigest()

    def _get_record(self, *, job_id: str, doc_id: str) -> ResumptionRecord | None:
        """Return the record of one document, or None when absent or unreadable."""
        collection = self._collection(job_id=job_id)
        try:
            data = self._record_storage.get_record(collection=collection, key=self._key(doc_id=doc_id))
            return ResumptionRecord.model_validate(data) if data is not None else None
        except Exception as exc:
            logger.warning("Ignoring unreadable resumption record: %s", type(exc).__name__)
            return None

    def _get_all_records(self, *, job_id: str) -> list[ResumptionRecord]:
        """Return all readable records of a job."""
        records = []
        for data in self._record_storage.list_records(collection=self._collection(job_id=job_id)):
            try:
                records.append(ResumptionRecord.model_validate(data))
            except Exception as exc:
                logger.warning("Ignoring unreadable resumption record: %s", type(exc).__name__)
        return records

    def _save_record(self, *, job_id: str, record: ResumptionRecord) -> None:
        """Create or replace the record of a document."""
        self._record_storage.save_record(
            collection=self._collection(job_id=job_id),
            key=self._key(doc_id=record.doc_id),
            data=record.model_dump(mode="json"),
        )

    def _delete_record(self, *, job_id: str, doc_id: str) -> None:
        """Delete the record of a document; nothing happens when it does not exist."""
        self._record_storage.delete_record(collection=self._collection(job_id=job_id), key=self._key(doc_id=doc_id))

    # ------------------------------------------------------------------ ingest side

    def classify(
        self,
        *,
        job_id: str,
        doc_id: str,
        modified_time: int | None,
    ) -> tuple[ResumptionDecision, ResumptionRecord | None]:
        """Decide how a document seen at ingest must be handled.

        * no record                                   -> FRESH
        * source newer than the saved modified_time   -> failure state invalidated, FRESH
        * retries exhausted at any failed node        -> EXHAUSTED (not scheduled automatically)
        * otherwise                                   -> DEFER (resume at every failed node)
        """
        record = self._get_record(job_id=job_id, doc_id=doc_id)
        if record is None:
            return ResumptionDecision.FRESH, None

        if record.modified_time is not None and modified_time is not None and modified_time > record.modified_time:
            logger.info("Source of document %s changed since its failure; saved failure state invalidated", doc_id)
            self.discard(job_id=job_id, record=record)
            return ResumptionDecision.FRESH, None

        if not record.failed_nodes:
            self.discard(job_id=job_id, record=record)
            return ResumptionDecision.FRESH, None

        if record.exhausted:
            return ResumptionDecision.EXHAUSTED, record

        return ResumptionDecision.DEFER, record

    def discard(self, *, job_id: str, record: ResumptionRecord) -> None:
        """Delete a record."""
        self._delete_record(job_id=job_id, doc_id=record.doc_id)

    def discard_all(self, *, job_id: str) -> None:
        """Delete every record of a job."""
        for record in self._get_all_records(job_id=job_id):
            self.discard(job_id=job_id, record=record)

    def discard_all_for_ids(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Delete records for the given documents (used by force ingest and unusable resumption entries)."""
        for doc_id in doc_ids:
            record = self._get_record(job_id=job_id, doc_id=doc_id)
            if record is not None:
                self.discard(job_id=job_id, record=record)

    # ------------------------------------------------------------------ planning

    @staticmethod
    def build_plan(
        *,
        entries: list[dict[str, Any]],
        op_flow: list[dict[str, Any]],
        batch_keys: list[str],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Distribute deferred entries across batches and compute the nodes that carry them.

        Args:
            entries: One :class:`DeferredRecord` dump per (document, failed node) emitted by ingest.
            op_flow: Flow nodes in execution order; ``op_flow[0]`` is the ingest node.
            batch_keys: Keys of the batches, see :func:`resumption_batch_key`.

        Returns:
            ``(plan, unresolved)``. ``plan`` maps a batch key to its entries, each extended with the saved output
            to read (``source_node_name``, ``source_output_index``) and ``pending_node_ids``. ``unresolved`` holds
            the entries of documents that cannot be resumed (target node missing from the flow, the ingest node, or
            a node with several inputs); they are re-ingested fresh on the next run. All entries of a document go
            to the same batch.
        """
        plan: dict[str, list[dict[str, Any]]] = {}
        if not batch_keys:
            return plan, list(entries)

        node_ids = [str(node[OperatorConstants.Columns.ID]) for node in op_flow]
        by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            by_doc[entry["doc_id"]].append(entry)

        unresolved: list[dict[str, Any]] = []
        assigned = 0
        for doc_entries in by_doc.values():
            resolved = [
                ResumptionService._resolve_entry(entry=entry, op_flow=op_flow, node_ids=node_ids)
                for entry in doc_entries
            ]
            if any(item is None for item in resolved):
                unresolved.extend(doc_entries)
                continue
            key = batch_keys[assigned % len(batch_keys)]
            assigned += 1
            plan.setdefault(key, []).extend(item for item in resolved if item is not None)
        return plan, unresolved

    @staticmethod
    def _resolve_entry(
        *, entry: dict[str, Any], op_flow: list[dict[str, Any]], node_ids: list[str]
    ) -> dict[str, Any] | None:
        """Extend a deferred entry with the saved output it is read from; None when it cannot be resumed.

        The target is looked up by ``target_node_id``. Only when the id is not part of the flow (authoring-format
        flows get new ids on every compile) is the node found again by ``target_node_name``.
        """
        target_id = entry["target_node_id"]
        if target_id not in node_ids:
            target_name = entry.get("target_node_name") or ""
            names = [str(node.get(OperatorConstants.Columns.NAME, "")) for node in op_flow]
            if not target_name or names.count(target_name) != 1:
                return None
            target_id = node_ids[names.index(target_name)]
            entry = {**entry, "target_node_id": target_id}
        target_idx = node_ids.index(target_id)
        if target_idx <= 0:
            return None
        target = op_flow[target_idx]
        edges = target.get(DocpipeConstants.INPUT_EDGES) or []
        if len(edges) > 1:
            return None
        source = op_flow[target_idx - 1]
        if edges:
            source_id = edges[0].get(DocpipeConstants.NODE_ID_REF)
            if source_id not in node_ids:
                return None
            source = op_flow[node_ids.index(source_id)]
        return {
            **entry,
            "source_node_name": str(source.get(OperatorConstants.Columns.NAME, "")),
            "source_output_index": ResumptionService._output_index(source=source, target=target),
            "pending_node_ids": ResumptionService._ancestors(op_flow=op_flow, node_ids=node_ids, index=target_idx),
        }

    @staticmethod
    def _ancestors(*, op_flow: list[dict[str, Any]], node_ids: list[str], index: int) -> list[str]:
        """Node ids between the ingest node (excluded) and ``op_flow[index]`` (excluded) that lead to it.

        Flows without edges are sequential, so every earlier node is an ancestor. In a DAG only the nodes reachable
        backwards through the input edges are, which keeps nodes of sibling branches out.
        """
        if not any(node.get(DocpipeConstants.INPUT_EDGES) for node in op_flow):
            return node_ids[1:index]
        found: set[str] = set()
        stack = [node_ids[index]]
        while stack:
            current = op_flow[node_ids.index(stack.pop())]
            for edge in current.get(DocpipeConstants.INPUT_EDGES) or []:
                parent = edge.get(DocpipeConstants.NODE_ID_REF)
                if parent in node_ids and parent != node_ids[0] and parent not in found:
                    found.add(parent)
                    stack.append(parent)
        return [node_id for node_id in node_ids[1:index] if node_id in found]

    @staticmethod
    def _output_index(*, source: dict[str, Any], target: dict[str, Any]) -> int:
        """Index of the source output feeding ``target``; only branching nodes have more than one output."""
        if source.get(OperatorConstants.Misc.OPERATOR) != OperatorConstants.Operators.BRANCHING:
            return 0
        link_id = target.get(OperatorConstants.Misc.LINK_ID)
        branches = (source.get(OperatorConstants.Config.CONFIG) or {}).get(_BRANCH_CRITERIA) or []
        for idx, branch in enumerate(branches):
            if branch.get(OperatorConstants.Misc.LINK_ID) == link_id:
                return idx
        return 0

    @staticmethod
    def entries_for_node(
        *,
        plan: dict[str, list[dict[str, Any]]] | None,
        batch_id: str | None,
        node_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return ``(inject_here, carried)`` entries of a batch for the given node.

        A document injected at this node is not reported as carried by it, even when it is still deferred to a
        later node.
        """
        if not plan:
            return [], []
        batch_entries = plan.get(resumption_batch_key(batch_id=batch_id), [])
        inject = [e for e in batch_entries if e.get("target_node_id") == node_id]
        injected_ids = {e["doc_id"] for e in inject}
        carried = [
            e for e in batch_entries if node_id in e.get("pending_node_ids", []) and e["doc_id"] not in injected_ids
        ]
        return inject, carried

    # ------------------------------------------------------------------ executor side

    def inject_saved_rows(
        self,
        *,
        table: pa.Table | None,
        entries: list[dict[str, Any]],
    ) -> tuple[pa.Table | None, list[str], list[dict[str, Any]]]:
        """Append the saved input rows of deferred documents to the node input table.

        Returns:
            ``(table, injected_ids, unavailable_entries)``. Entries whose saved output cannot be read or merged are
            returned in ``unavailable_entries`` so the caller can report them as failed.
        """
        if self._table_storage is None or self._output_table_name is None:
            return table, [], list(entries)

        groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            key = (entry["job_run_id"], entry.get("source_node_name") or "", int(entry.get("source_output_index", 0)))
            groups[key].append(entry)

        injected_ids: list[str] = []
        unavailable: list[dict[str, Any]] = []
        parts: list[pa.Table] = []
        for (job_run_id, node_name, output_index), group in groups.items():
            rows = self._read_saved_rows(
                job_run_id=job_run_id,
                node_name=node_name,
                output_index=output_index,
                doc_ids=[entry["doc_id"] for entry in group],
            )
            found = set(rows[OperatorConstants.Misc.ID].to_pylist()) if rows is not None else set()
            for entry in group:
                if entry["doc_id"] in found:
                    injected_ids.append(entry["doc_id"])
                else:
                    unavailable.append(entry)
            if rows is not None and rows.num_rows > 0:
                parts.append(rows)

        if not parts:
            return table, [], unavailable

        try:
            base = [table] if table is not None else []
            merged = pa.concat_tables(base + parts, promote_options="permissive")
        except Exception as exc:
            logger.warning("Failed to merge saved node output into node input: %s", type(exc).__name__)
            return table, [], list(entries)
        return merged, injected_ids, unavailable

    def _read_saved_rows(
        self,
        *,
        job_run_id: str,
        node_name: str,
        output_index: int,
        doc_ids: list[str],
    ) -> pa.Table | None:
        """Read the rows of ``doc_ids`` from the saved output of a node; None when missing or unreadable."""
        if self._table_storage is None or self._output_table_name is None:
            return None
        if not doc_ids or not _SAFE_ID.match(job_run_id) or job_run_id in {".", ".."}:
            return None
        table_name = self._output_table_name(job_run_id=job_run_id, node_name=node_name, output_index=output_index)
        if '"' in table_name:
            return None
        placeholders = ", ".join("?" for _ in doc_ids)
        query = f'SELECT * FROM "{table_name}" WHERE {OperatorConstants.Misc.ID} IN ({placeholders})'  # nosec B608 - the table name holds no quote; ids are bound parameters
        try:
            if not self._table_storage.table_exists(table_name=table_name):
                return None
            rows = self._table_storage.execute_query(query=query, params=list(doc_ids))
        except Exception as exc:
            logger.warning("Failed to read saved node output for resumption: %s", type(exc).__name__)
            return None
        return rows if rows.num_rows > 0 else None

    def record_failure(
        self,
        *,
        job_id: str,
        job_run_id: str,
        node_id: str,
        node_name: str,
        input_table: pa.Table,
        doc_id: str,
        doc_name: str,
        reason: str,
    ) -> ResumptionRecord | None:
        """Record a failure of ``doc_id`` at ``node_id`` together with the original error message.

        A document that already failed at the node keeps the job run of its first failure: that run is the one whose
        saved output holds the node's input row, because a resumed document is not part of a later run's upstream
        output. Failures at other nodes of the document are kept, so every failed node is resumed.

        Returns the stored record (the node entry is ``exhausted`` once the retry budget is spent) or ``None`` when
        the document has no input row to record.
        """
        id_col = OperatorConstants.Misc.ID
        if id_col not in input_table.column_names:
            return None
        rows = input_table.filter(pc.equal(input_table[id_col], doc_id))
        if rows.num_rows == 0:
            return None

        if not doc_name and OperatorConstants.Misc.NAME in rows.column_names:
            doc_name = str(rows[OperatorConstants.Misc.NAME][0].as_py() or "")
        existing = self._get_record(job_id=job_id, doc_id=doc_id)
        previous = existing.failed_node(node_id=node_id, node_name=node_name) if existing else None
        failure_count = previous.failure_count + 1 if previous else 1
        failed_node = FailedNode(
            node_id=node_id,
            node_name=node_name,
            job_run_id=previous.job_run_id if previous else job_run_id,
            failure_count=failure_count,
            error_message=reason,
            exhausted=failure_count > self._max_retry_attempts,
        )
        others = [node for node in existing.failed_nodes if node is not previous] if existing else []
        record = ResumptionRecord(
            doc_id=doc_id,
            doc_name=doc_name,
            modified_time=self._modified_time(rows=rows),
            failed_nodes=[*others, failed_node],
        )
        self._save_record(job_id=job_id, record=record)
        logger.info(
            "Recorded failure %d for a document at node %s (exhausted=%s)",
            failure_count,
            node_name,
            failed_node.exhausted,
        )
        return record

    def clear_node_success(self, *, job_id: str, node_id: str, node_name: str = "", doc_ids: list[str]) -> None:
        """Drop the failure entry of a node for documents that passed it; exhausted entries are retained.

        A record without any failed node left is deleted.
        """
        for doc_id in doc_ids:
            record = self._get_record(job_id=job_id, doc_id=doc_id)
            if record is None:
                continue
            node = record.failed_node(node_id=node_id, node_name=node_name)
            if node is None or node.exhausted:
                continue
            remaining = [n for n in record.failed_nodes if n is not node]
            if remaining:
                self._save_record(job_id=job_id, record=record.model_copy(update={"failed_nodes": remaining}))
            else:
                self._delete_record(job_id=job_id, doc_id=doc_id)

    @staticmethod
    def to_deferred_records(*, record: ResumptionRecord) -> list[DeferredRecord]:
        """One deferred record per node the document has to be resumed at."""
        return [
            DeferredRecord(
                doc_id=record.doc_id,
                doc_name=record.doc_name,
                target_node_id=node.node_id,
                target_node_name=node.node_name,
                job_run_id=node.job_run_id,
                failure_count=node.failure_count,
                error_message=node.error_message,
            )
            for node in record.failed_nodes
        ]

    @staticmethod
    def _modified_time(*, rows: pa.Table) -> int | None:
        """Return the source modified_time of the first row, or None when absent."""
        column = OperatorConstants.Metadata.MODIFIED_TIME
        if column not in rows.column_names:
            return None
        value = rows[column][0].as_py()
        return value if isinstance(value, int) else None

    def format_exhausted_reason(self, *, record: ResumptionRecord) -> str:
        """Failure reason shown in node metadata and the job run report for retry-exhausted documents.

        Names every node that exhausted its retries together with the original error it reported.
        """
        return "; ".join(
            f"{RETRIES_EXHAUSTED_PREFIX} ({node.failure_count} attempts, "
            f"max_retry_attempts={self._max_retry_attempts}) at node '{node.node_name}': {node.error_message}"
            for node in record.failed_nodes
            if node.exhausted
        )


def retry_attempts_from_config(*, config: dict[str, Any]) -> int:
    """Read ``max_retry_attempts`` from a flow/operator config, falling back to the default."""
    return int(config.get(DocpipeConstants.MAX_RETRY_ATTEMPTS, DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS))
