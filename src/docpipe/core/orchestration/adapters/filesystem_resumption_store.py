# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Filesystem adapter for the resumption store (one JSON file per record, one parquet file per checkpoint)."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from docpipe.core.orchestration.models.resumption_plan import ResumptionRecord
from docpipe.core.orchestration.ports.resumption_store import ResumptionStore
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class FilesystemResumptionStore(ResumptionStore):
    """Stores state under ``<data_path>/<job_id>/resumption``.

    Records live in ``records/<sha256(doc_id)>.json`` and checkpoints in
    ``checkpoints/<sha256(node_id)>/<sha256(doc_id)>.parquet``. File names are hashes so document and node
    identifiers can never influence the path.
    """

    def __init__(self, *, root: str | None = None) -> None:
        self._root = root

    def _job_dir(self, *, job_id: str) -> Path:
        """Return the validated job-scoped resumption directory."""
        if not job_id or not _SAFE_JOB_ID.match(job_id) or job_id in {".", ".."}:
            msg = "Invalid job_id for resumption store"
            raise ValueError(msg)
        root = self._root if self._root is not None else get_data_path()
        return Path(root) / job_id / "resumption"

    @staticmethod
    def _digest(*, value: str) -> str:
        """Return a filesystem-safe digest of a document id."""
        return hashlib.sha256(value.encode()).hexdigest()

    def _record_path(self, *, job_id: str, doc_id: str) -> Path:
        """Return the path of the record file of a document."""
        return self._job_dir(job_id=job_id) / "records" / f"{self._digest(value=doc_id)}.json"

    def _resolve_checkpoint(self, *, job_id: str, path: str) -> Path | None:
        """Resolve a stored checkpoint path, rejecting anything outside the job directory."""
        job_dir = self._job_dir(job_id=job_id).resolve()
        resolved = (job_dir / path).resolve()
        if not resolved.is_relative_to(job_dir):
            logger.warning("Rejected checkpoint path outside the resumption store")
            return None
        return resolved

    @staticmethod
    def _atomic_write(*, target: Path, data: bytes) -> None:
        """Write bytes through a temporary file and an atomic rename."""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            Path(tmp_name).replace(target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def get_all_records(self, *, job_id: str) -> dict[str, ResumptionRecord]:
        """Return all records of a job keyed by document id."""
        records_dir = self._job_dir(job_id=job_id) / "records"
        result: dict[str, ResumptionRecord] = {}
        if not records_dir.is_dir():
            return result
        for file in records_dir.glob("*.json"):
            try:
                record = ResumptionRecord.model_validate_json(file.read_text())
            except Exception as exc:
                logger.warning("Ignoring unreadable resumption record %s: %s", file.name, type(exc).__name__)
                continue
            result[record.doc_id] = record
        return result

    def get_record(self, *, job_id: str, doc_id: str) -> ResumptionRecord | None:
        """Return the record of one document, or None."""
        path = self._record_path(job_id=job_id, doc_id=doc_id)
        if not path.is_file():
            return None
        try:
            return ResumptionRecord.model_validate_json(path.read_text())
        except Exception as exc:
            logger.warning("Ignoring unreadable resumption record: %s", type(exc).__name__)
            return None

    def save_record(self, *, job_id: str, record: ResumptionRecord) -> None:
        """Create or replace the record of a document."""
        self._atomic_write(
            target=self._record_path(job_id=job_id, doc_id=record.doc_id),
            data=record.model_dump_json().encode(),
        )

    def delete_record(self, *, job_id: str, doc_id: str) -> None:
        """Delete the record of a document."""
        self._record_path(job_id=job_id, doc_id=doc_id).unlink(missing_ok=True)

    def write_checkpoint(self, *, job_id: str, node_id: str, doc_id: str, table: pa.Table) -> str:
        """Persist a checkpoint table and return its path relative to the job's resumption directory."""
        relative = f"checkpoints/{self._digest(value=node_id)}/{self._digest(value=doc_id)}.parquet"
        target = self._job_dir(job_id=job_id) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp_target)
        tmp_target.replace(target)
        return relative

    def read_checkpoint(self, *, job_id: str, path: str) -> pa.Table | None:
        """Read a checkpoint table; return None when missing or unreadable."""
        resolved = self._resolve_checkpoint(job_id=job_id, path=path)
        if resolved is None or not resolved.is_file():
            return None
        try:
            return pq.read_table(resolved)
        except Exception as exc:
            logger.warning("Failed to read resumption checkpoint: %s", type(exc).__name__)
            return None

    def checkpoint_exists(self, *, job_id: str, path: str | None) -> bool:
        """Return True when the checkpoint exists."""
        if not path:
            return False
        resolved = self._resolve_checkpoint(job_id=job_id, path=path)
        return resolved is not None and resolved.is_file()

    def delete_checkpoint(self, *, job_id: str, path: str | None) -> None:
        """Delete a checkpoint if present."""
        if not path:
            return
        resolved = self._resolve_checkpoint(job_id=job_id, path=path)
        if resolved is not None:
            resolved.unlink(missing_ok=True)
