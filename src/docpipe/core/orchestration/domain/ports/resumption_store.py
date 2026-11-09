# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port for persisting resumption records and per-document checkpoints."""

from abc import ABC, abstractmethod

import pyarrow as pa

from docpipe.core.orchestration.domain.models.resumption_plan import ResumptionRecord


class ResumptionStore(ABC):
    """Storage contract for node-level failure resumption state."""

    @abstractmethod
    def get_all_records(self, *, job_id: str) -> dict[str, ResumptionRecord]:
        """Return all resumption records of a job keyed by document id."""

    @abstractmethod
    def get_record(self, *, job_id: str, doc_id: str) -> ResumptionRecord | None:
        """Return the record of one document, or ``None``."""

    @abstractmethod
    def save_record(self, *, job_id: str, record: ResumptionRecord) -> None:
        """Create or replace the record of a document."""

    @abstractmethod
    def delete_record(self, *, job_id: str, doc_id: str) -> None:
        """Delete the record of a document; no-op when absent."""

    @abstractmethod
    def write_checkpoint(self, *, job_id: str, node_id: str, doc_id: str, table: pa.Table) -> str:
        """Persist a checkpoint table and return its store-relative path."""

    @abstractmethod
    def read_checkpoint(self, *, job_id: str, path: str) -> pa.Table | None:
        """Read a checkpoint table; return ``None`` when it does not exist."""

    @abstractmethod
    def checkpoint_exists(self, *, job_id: str, path: str | None) -> bool:
        """Return True when the checkpoint exists."""

    @abstractmethod
    def delete_checkpoint(self, *, job_id: str, path: str | None) -> None:
        """Delete a checkpoint; no-op when absent."""
