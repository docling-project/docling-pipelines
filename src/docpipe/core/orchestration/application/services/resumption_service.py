# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Service implementing node-level failure resumption.

A document that fails at node K of a flow is recorded together with a checkpoint of its input row (the output of
node K-1). On the next run of the same job the document is not re-ingested from scratch: it is deferred and injected
into node K, bypassing nodes 1 to K-1, until it succeeds or exhausts ``max_retry_attempts`` retries.
"""

from enum import StrEnum
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.domain.models.resumption_plan import ResumptionRecord
from docpipe.core.orchestration.domain.ports.resumption_store import ResumptionStore
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

RETRIES_EXHAUSTED_PREFIX = "Maximum retries exhausted"
SINGLE_BATCH_KEY = "__single__"


class ResumptionDecision(StrEnum):
    """Outcome of classifying a re-encountered document at ingest."""

    FRESH = "fresh"
    DEFER = "defer"
    EXHAUSTED = "exhausted"


def resumption_batch_key(*, batch_id: str | None) -> str:
    """Return the key under which the resumption plan stores entries of a batch."""
    return str(batch_id) if batch_id else SINGLE_BATCH_KEY


class ResumptionService:
    """Decides, records and applies node-level resumption of failed documents."""

    def __init__(self, *, store: ResumptionStore, max_retry_attempts: int) -> None:
        self._store = store
        # Total attempts per document = 1 initial execution + max_retry_attempts retries
        self._max_retry_attempts = max(0, max_retry_attempts)

    @property
    def max_retry_attempts(self) -> int:
        """Configured number of retries after the initial attempt."""
        return self._max_retry_attempts

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
        * source newer than the saved modified_time   -> checkpoint invalidated, FRESH
        * retries exhausted                           -> EXHAUSTED (not scheduled automatically)
        * checkpoint missing                          -> record dropped, FRESH (root ingestion)
        * otherwise                                   -> DEFER (resume at the failed node)
        """
        record = self._store.get_record(job_id=job_id, doc_id=doc_id)
        if record is None:
            return ResumptionDecision.FRESH, None

        if record.modified_time is not None and modified_time is not None and modified_time > record.modified_time:
            logger.info("Source of document %s changed since its failure; checkpoint invalidated", doc_id)
            self.discard(job_id=job_id, record=record)
            return ResumptionDecision.FRESH, None

        if record.exhausted or record.failure_count > self._max_retry_attempts:
            return ResumptionDecision.EXHAUSTED, record

        if not self._store.checkpoint_exists(job_id=job_id, path=record.checkpoint_path):
            logger.info("No checkpoint for failed document %s; falling back to root ingestion", doc_id)
            self._store.delete_record(job_id=job_id, doc_id=doc_id)
            return ResumptionDecision.FRESH, None

        return ResumptionDecision.DEFER, record

    def discard(self, *, job_id: str, record: ResumptionRecord) -> None:
        """Delete a record together with its checkpoint."""
        self._store.delete_checkpoint(job_id=job_id, path=record.checkpoint_path)
        self._store.delete_record(job_id=job_id, doc_id=record.doc_id)

    def discard_all(self, *, job_id: str) -> None:
        """Delete every record and checkpoint of a job."""
        for record in self._store.get_all_records(job_id=job_id).values():
            self.discard(job_id=job_id, record=record)

    def discard_all_for_ids(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Delete records and checkpoints for the given documents (used by force ingest)."""
        for doc_id in doc_ids:
            record = self._store.get_record(job_id=job_id, doc_id=doc_id)
            if record is not None:
                self.discard(job_id=job_id, record=record)

    # ------------------------------------------------------------------ planning

    @staticmethod
    def build_plan(
        *,
        entries: list[dict[str, Any]],
        node_ids: list[str],
        batch_keys: list[str],
        node_names: list[str] | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Distribute deferred entries across batches and compute the nodes that carry them.

        Args:
            entries: Deferred entries emitted by ingest (``doc_id``, ``target_node_id``, ``checkpoint_path`` ...).
            node_ids: Node ids of the flow in execution order; ``node_ids[0]`` is the ingest node.
            batch_keys: Keys of the batches, see :func:`resumption_batch_key`.
            node_names: Optional node names aligned with ``node_ids``. Flows compiled from the authoring format get
                new node ids on every run, so an entry whose ``target_node_id`` is unknown is matched by
                ``target_node_name`` and remapped to the node id of the current flow.

        Returns:
            ``(plan, unresolved)``. ``plan`` maps a batch key to its entries, each extended with
            ``pending_node_ids``. ``unresolved`` holds entries whose target node is not part of the flow (or is the
            ingest node); they must be processed as fresh documents.
        """
        plan: dict[str, list[dict[str, Any]]] = {}
        unresolved: list[dict[str, Any]] = []
        position = {node_id: idx for idx, node_id in enumerate(node_ids)}
        name_position = {name: idx for idx, name in enumerate(node_names or []) if name}
        if not batch_keys:
            return plan, list(entries)

        assigned = 0
        for entry in entries:
            target_idx = position.get(entry.get("target_node_id", ""))
            if target_idx is None:
                target_idx = name_position.get(entry.get("target_node_name", ""), 0)
            if target_idx <= 0:
                unresolved.append(entry)
                continue
            key = batch_keys[assigned % len(batch_keys)]
            assigned += 1
            plan.setdefault(key, []).append(
                {**entry, "target_node_id": node_ids[target_idx], "pending_node_ids": node_ids[1:target_idx]}
            )
        return plan, unresolved

    @staticmethod
    def entries_for_node(
        *,
        plan: dict[str, list[dict[str, Any]]] | None,
        batch_id: str | None,
        node_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return ``(inject_here, carried)`` entries of a batch for the given node."""
        if not plan:
            return [], []
        batch_entries = plan.get(resumption_batch_key(batch_id=batch_id), [])
        inject = [e for e in batch_entries if e.get("target_node_id") == node_id]
        carried = [e for e in batch_entries if node_id in e.get("pending_node_ids", [])]
        return inject, carried

    # ------------------------------------------------------------------ executor side

    def inject_checkpoints(
        self,
        *,
        job_id: str,
        table: pa.Table | None,
        entries: list[dict[str, Any]],
    ) -> tuple[pa.Table | None, list[str], list[dict[str, Any]]]:
        """Append checkpoint rows of deferred documents to the node input table.

        Returns:
            ``(table, injected_ids, unavailable_entries)``. Entries whose checkpoint cannot be read or merged are
            returned in ``unavailable_entries`` so the caller can report them as failed.
        """
        injected_ids: list[str] = []
        unavailable: list[dict[str, Any]] = []
        parts: list[pa.Table] = []
        for entry in entries:
            checkpoint = self._store.read_checkpoint(job_id=job_id, path=entry["checkpoint_path"])
            if checkpoint is None or checkpoint.num_rows == 0:
                unavailable.append(entry)
                continue
            parts.append(checkpoint)
            injected_ids.append(entry["doc_id"])

        if not parts:
            return table, injected_ids, unavailable

        try:
            base = [table] if table is not None else []
            merged = pa.concat_tables(base + parts, promote_options="permissive")
        except Exception as exc:
            logger.warning("Failed to merge resumption checkpoints into node input: %s", type(exc).__name__)
            return table, [], list(entries)
        return merged, injected_ids, unavailable

    def record_failure(
        self,
        *,
        job_id: str,
        node_id: str,
        node_name: str,
        input_table: pa.Table,
        doc_id: str,
        doc_name: str,
        reason: str,
    ) -> ResumptionRecord | None:
        """Record a failure of ``doc_id`` at ``node_id`` and persist the checkpoint of its input row.

        Returns the stored record (``exhausted`` set once the retry budget is spent) or ``None`` when the document
        has no input row to checkpoint.
        """
        id_col = OperatorConstants.Misc.ID
        if id_col not in input_table.column_names:
            return None
        rows = input_table.filter(pc.equal(input_table[id_col], doc_id))
        if rows.num_rows == 0:
            return None

        if not doc_name and OperatorConstants.Misc.NAME in rows.column_names:
            doc_name = str(rows[OperatorConstants.Misc.NAME][0].as_py() or "")
        modified_time = self._modified_time(rows=rows)
        existing = self._store.get_record(job_id=job_id, doc_id=doc_id)
        failure_count = (
            existing.failure_count + 1
            if existing and (existing.failed_node_id == node_id or existing.failed_node_name == node_name)
            else 1
        )
        exhausted = failure_count > self._max_retry_attempts

        checkpoint_path = self._store.write_checkpoint(job_id=job_id, node_id=node_id, doc_id=doc_id, table=rows)
        if existing and existing.checkpoint_path and existing.checkpoint_path != checkpoint_path:
            self._store.delete_checkpoint(job_id=job_id, path=existing.checkpoint_path)

        record = ResumptionRecord(
            doc_id=doc_id,
            doc_name=doc_name,
            failed_node_id=node_id,
            failed_node_name=node_name,
            failure_count=failure_count,
            modified_time=modified_time,
            checkpoint_path=checkpoint_path,
            last_reason=reason,
            exhausted=exhausted,
        )
        self._store.save_record(job_id=job_id, record=record)
        logger.info("Recorded failure %d for a document at node %s (exhausted=%s)", failure_count, node_name, exhausted)
        return record

    @staticmethod
    def _modified_time(*, rows: pa.Table) -> int | None:
        column = OperatorConstants.Metadata.MODIFIED_TIME
        if column not in rows.column_names:
            return None
        value = rows[column][0].as_py()
        return value if isinstance(value, int) else None

    def format_exhausted_reason(self, *, record: ResumptionRecord) -> str:
        """Failure reason shown in node metadata and the job run report for retry-exhausted documents."""
        return (
            f"{RETRIES_EXHAUSTED_PREFIX} ({record.failure_count} attempts, "
            f"max_retry_attempts={self._max_retry_attempts}) at node '{record.failed_node_name}': "
            f"{record.last_reason}"
        )

    def clear_completed(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Drop resumption state of documents that completed the whole flow; exhausted records are retained."""
        for doc_id in doc_ids:
            record = self._store.get_record(job_id=job_id, doc_id=doc_id)
            if record is not None and not record.exhausted:
                self.discard(job_id=job_id, record=record)


def retry_attempts_from_config(*, config: dict[str, Any]) -> int:
    """Read ``max_retry_attempts`` from a flow/operator config, falling back to the default."""
    return int(config.get(DocpipeConstants.MAX_RETRY_ATTEMPTS, DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS))
