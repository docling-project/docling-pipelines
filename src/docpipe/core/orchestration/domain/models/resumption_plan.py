# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Domain models for node-level failure resumption."""

from pydantic import BaseModel, Field


class ResumptionRecord(BaseModel):
    """Persistent per-document failure state used to resume a document at the node where it failed."""

    doc_id: str
    doc_name: str = ""
    failed_node_id: str
    failed_node_name: str = ""
    # Consecutive failures at ``failed_node_id``; resets when the document fails at a different node.
    failure_count: int = 1
    # Source modification time captured when the document failed; ``None`` when unknown.
    modified_time: int | None = None
    # Checkpoint location (relative to the store root) holding the failed node's input row, if available.
    checkpoint_path: str | None = None
    last_reason: str = ""
    # True once ``failure_count`` exceeded ``max_retry_attempts``; no further automated resumption.
    exhausted: bool = False


class DeferredDocument(BaseModel):
    """A document scheduled for resumption at a downstream node of the current run."""

    doc_id: str
    doc_name: str = ""
    target_node_id: str
    checkpoint_path: str
    batch_num: int = 0
    # Ancestor nodes of ``target_node_id`` (including ingest) that carry the document as deferred.
    pending_node_ids: list[str] = Field(default_factory=list)
