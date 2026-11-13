# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Port interface for incremental metadata storage.

This module defines the abstract interface that all incremental metadata
storage adapters must implement, following hexagonal architecture principles.
"""

from abc import ABC, abstractmethod
from typing import Any

from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord


class IncrementalMetadataStore(ABC):
    """
    Abstract port interface for incremental metadata storage.

    This interface defines the contract that all storage adapters
    (Filesystem, PostgreSQL) must implement. It provides methods
    for managing document processing metadata in incremental workflows.
    """

    @abstractmethod
    def get_processed_docs(self, *, job_id: str) -> dict[str, Any]:
        """
        Retrieve processed document IDs with their modification times and job run IDs.

        Returns only non-deleted documents.

        Args:
            job_id: Unique identifier for the job

        Returns:
            Dictionary mapping doc_id to {"modified_time": ..., "job_run_id": ...}
            for all processed documents

        Raises:
            Exception: If retrieval operation fails
        """
        ...

    @abstractmethod
    def upsert_records(self, *, job_id: str, job_run_id: str, records: list[IncrementalMetadataRecord]) -> None:
        """
        Insert or update incremental metadata records.

        If a record with the same (job_id, doc_id) exists, it will be updated.
        Otherwise, a new record will be created.

        Args:
            job_id: Unique identifier for the job
            job_run_id: Unique identifier for the job run
            records: List of metadata records to upsert

        Raises:
            Exception: If upsert operation fails
        """
        ...

    @abstractmethod
    def get_soft_deleted_doc_ids(self, *, job_id: str) -> set[str]:
        """
        Retrieve document IDs that have been marked as soft-deleted.

        Args:
            job_id: Unique identifier for the job

        Returns:
            Set of document IDs marked as deleted

        Raises:
            Exception: If retrieval operation fails
        """
        ...

    @abstractmethod
    def mark_missing_docs_as_deleted(self, *, job_id: str, doc_ids: list[str]) -> set[str]:
        """
        Mark documents as soft-deleted if they are not in the provided list.

        This is used to track documents that were previously processed but
        are no longer present in the source.

        Args:
            job_id: Unique identifier for the job
            doc_ids: List of currently existing document IDs

        Returns:
            Set of document IDs that were marked as deleted

        Raises:
            Exception: If marking operation fails
        """
        ...

    @abstractmethod
    def unmark_soft_deleted_docs(self, *, job_id: str, doc_ids: list[str] | None = None) -> None:
        """
        Unmark soft-deleted documents, setting deleted flag back to False.

        If doc_ids is None, all soft-deleted documents for the job are unmarked.

        Args:
            job_id: Unique identifier for the job
            doc_ids: Optional list of document IDs to unmark. If None, unmarks all for job.

        Raises:
            Exception: If unmark operation fails
        """
        ...

    @abstractmethod
    def purge_soft_deleted_docs(self, *, job_id: str) -> None:
        """
        Permanently delete all soft-deleted records for a given job.

        Args:
            job_id: Unique identifier for the job

        Raises:
            Exception: If purge operation fails
        """
        ...

    @abstractmethod
    def delete_docs(self, *, job_id: str, doc_ids: list[str]) -> None:
        """
        Permanently delete metadata records for specified documents.

        This is a hard delete operation that removes records from storage.

        Args:
            job_id: Unique identifier for the job
            doc_ids: List of document IDs to delete

        Raises:
            Exception: If deletion operation fails
        """
        ...

    @abstractmethod
    def clear(self, *, job_id: str) -> None:
        """
        Clear all incremental metadata for a specific job.

        This removes all records associated with the job_id.

        Args:
            job_id: Unique identifier for the job

        Raises:
            Exception: If clear operation fails
        """
        ...
