# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port for persisting resumption records."""

from abc import ABC, abstractmethod

from docpipe.core.orchestration.models.resumption_plan import ResumptionRecord


class ResumptionStore(ABC):
    """Storage contract for node-level failure resumption state.

    Only failure records are stored. The data a document is resumed from is the intermediate node output that the
    flow already writes when ``data_storage_type`` is not ``memory``.
    """

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
