# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Filesystem adapter for the resumption store (one JSON file per record)."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from docpipe.core.orchestration.models.resumption_plan import ResumptionRecord
from docpipe.core.orchestration.ports.resumption_store import ResumptionStore
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class FilesystemResumptionStore(ResumptionStore):
    """Stores state under ``<data_path>/<job_id>/resumption``.

    Records live in ``records/<sha256(doc_id)>.json``. File names are hashes so document identifiers can never
    influence the path.
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
