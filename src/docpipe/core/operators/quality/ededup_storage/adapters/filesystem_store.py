"""File-locked ededup admissions for workers sharing a directory."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from docpipe.core.operators.quality.ededup_storage.ports.ededup_store import EdedupStore
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.filesystem import get_data_path


class FilesystemEdedupStore(EdedupStore):
    """Persist only ededup memberships using atomic file replacement."""

    def __init__(self, *, config: dict[str, Any] | None = None):
        config = config or {}
        self._base_dir = Path(config.get("base_dir") or get_data_path()).resolve()
        self._lock_timeout = float(config.get("lock_timeout", 120.0))

    def check_and_register_hashes(
        self, *, job_id: str, node_id: str, job_run_id: str, records: dict[str, str]
    ) -> set[str]:
        """Share admissions between instances/processes using the same local directory."""
        if not records:
            return set()
        scope = hashlib.sha256(json.dumps([job_id, node_id, job_run_id]).encode()).hexdigest()
        directory = self._base_dir / "ededup_registry"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"hashes_{scope}.parquet"
        temporary = path.with_suffix(".tmp")
        schema = pa.schema([(key, pa.string()) for key in ("job_id", "node_id", "job_run_id", "hash_value", "doc_id")])
        try:
            with FileLock(str(path.with_suffix(".lock")), timeout=self._lock_timeout):
                previous = pq.read_table(path) if path.exists() else pa.Table.from_pylist([], schema=schema)
                seen = set(previous["hash_value"].to_pylist())
                accepted = set(records) - seen
                if accepted:
                    additions = pa.Table.from_pylist(
                        [
                            {
                                "job_id": job_id,
                                "node_id": node_id,
                                "job_run_id": job_run_id,
                                "hash_value": value,
                                "doc_id": records[value],
                            }
                            for value in sorted(accepted)
                        ],
                        schema=schema,
                    )
                    try:
                        pq.write_table(pa.concat_tables([previous, additions]), temporary)
                        temporary.replace(path)
                    finally:
                        temporary.unlink(missing_ok=True)
                return accepted
        except Exception as exc:
            raise FlowExecutionFailedException("Failed to register deduplication hashes") from exc
