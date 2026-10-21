"""Atomic content admission contract, independent of source tracking."""

from abc import ABC, abstractmethod


class EdedupStore(ABC):
    """Store committed membership per job, node, run, and content hash."""

    @abstractmethod
    def check_and_register_hashes(
        self, *, job_id: str, node_id: str, job_run_id: str, records: dict[str, str]
    ) -> set[str]:
        """Atomically register hash -> document ID candidates and return newly accepted hashes.

        Membership is isolated by job, flow node and run. Return only after the
        registration commits; failures must propagate. Records are admissions,
        not evidence of successful downstream processing. Historical runs remain
        independent, including when runs overlap. Input order does not determine
        the winner between concurrent callers.

        Implementations return only after commit and propagate storage failures.
        """
        ...
