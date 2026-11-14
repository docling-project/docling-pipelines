# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Domain models for node-level failure resumption."""

from pydantic import BaseModel, Field


class FailedNode(BaseModel):
    """A node at which a document failed, together with the run that produced the failure.

    The intermediate output the node consumed is located from ``job_run_id`` and ``batch_num``; no path is persisted.
    """

    node_id: str
    node_name: str = ""
    # Job run in which the document last failed at this node.
    job_run_id: str
    # Micro-batch number of that job run in which the document failed; ``None`` when the run was not micro-batched
    # (or the record predates this field). It selects the ``<batch_num>`` sub-folder of the saved predecessor output.
    batch_num: int | None = None
    # Consecutive failures at this node; a node that later succeeds is removed from the record.
    failure_count: int = 1
    # Original error reported by the node for the latest failure.
    error_message: str = ""
    # True once ``failure_count`` exceeded ``max_retry_attempts``; no further automated resumption.
    exhausted: bool = False


class ResumptionRecord(BaseModel):
    """Persistent per-document failure state used to resume a document at every node where it failed."""

    doc_id: str
    doc_name: str = ""
    # Source modification time captured when the document failed; ``None`` when unknown.
    modified_time: int | None = None
    # A document processed by several branches can fail at several nodes; each one is resumed.
    failed_nodes: list[FailedNode] = Field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        """True when the document exhausted its retries at any of its failed nodes."""
        return any(node.exhausted for node in self.failed_nodes)

    def failed_node(self, *, node_id: str, node_name: str = "") -> FailedNode | None:
        """Return the failure entry of ``node_id``, or None.

        Flows compiled from the authoring format get new node ids on every compile, so an entry is also matched by
        ``node_name`` when no entry carries ``node_id``.
        """
        by_id = next((node for node in self.failed_nodes if node.node_id == node_id), None)
        if by_id is not None or not node_name:
            return by_id
        return next((node for node in self.failed_nodes if node.node_name == node_name), None)


class DeferredRecord(BaseModel):
    """A document scheduled for resumption at one downstream node of the current run."""

    doc_id: str
    doc_name: str = ""
    target_node_id: str
    # Name of the target node; only used to find the node again when its id changed between runs.
    target_node_name: str = ""
    # Job run in which the document failed at ``target_node_id``.
    job_run_id: str
    # Micro-batch number of that job run in which the document failed; ``None`` when it was not micro-batched.
    # Together with ``job_run_id`` it derives the folder of the saved predecessor output.
    batch_num: int | None = None
    failure_count: int = 1
    # Original error reported when the document failed at ``target_node_id``.
    error_message: str = ""
    # Predecessor node whose saved output is the input of ``target_node_id`` and the index of that output.
    source_node_name: str | None = None
    source_output_index: int = 0
    # Ancestor nodes of ``target_node_id`` (excluding ingest) that carry the document as deferred.
    pending_node_ids: list[str] = Field(default_factory=list)
