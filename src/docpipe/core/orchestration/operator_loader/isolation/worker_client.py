# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parent side of process isolation: start, talk to, and stop one worker (design D12, task D.3).

The worker is started with ``subprocess.Popen`` rather than ``multiprocessing``'s ``spawn``: both give a fresh
interpreter, but ``spawn`` re-imports the parent's ``__main__`` in the child (the API application, which is
exactly the module that registers secret providers) and always inherits ``os.environ``. ``Popen`` lets the
environment and the inherited descriptors be exactly what the isolation requirement states.
"""

import atexit
import contextlib
import multiprocessing
import os
import shutil
import subprocess  # nosec B404 - launches this package's own worker with a fixed argv, no shell
import sys
import tempfile
import threading
from multiprocessing.connection import Connection
from typing import Any, Final

import pyarrow as pa

from docpipe.core.orchestration.operator_loader.isolation.protocol import (
    TYPE_LOAD,
    TYPE_RUN,
    TYPE_STOP,
    receive_message,
    send_message,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

WORKER_MODULE: Final[str] = "docpipe.core.orchestration.operator_loader.isolation.worker_main"

# Names copied from the parent's environment into the worker's. Anything else, including every credential-like
# variable, is dropped. ``PYTHONPATH`` is kept so a source checkout can import ``docpipe``.
ENVIRONMENT_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "PYTHONPATH", "VIRTUAL_ENV", "DS_LOG_LEVEL"}
)

_STOP_GRACE_SECONDS: Final[float] = 5.0
_MAX_STDERR_LINES: Final[int] = 200


def build_worker_environment(*, parent_environment: dict[str, str]) -> dict[str, str]:
    """Return the allowlisted subset of ``parent_environment`` for a worker."""
    environment = {name: value for name, value in parent_environment.items() if name in ENVIRONMENT_ALLOWLIST}
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


class IsolatedWorkerError(DocpipeException):
    """The worker failed to load an operator, ran it with an error, or exited."""


class IsolatedWorker:
    """One worker process serving one operator class for one run.

    Requests are serialized by a lock: a worker holds one loaded operator class and one pipe, so concurrent batches
    of the same run take turns.
    """

    def __init__(self, *, label: str, source_file: str, load_header: dict[str, Any]) -> None:
        if os.name != "posix":
            raise IsolatedWorkerError("process isolation of custom operators requires a POSIX platform")
        self._label = label
        self._lock = threading.Lock()
        self._closed = False
        self._workdir = tempfile.mkdtemp(prefix="docpipe-worker-")
        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        self._conn: Connection = parent_conn
        try:
            self._process = subprocess.Popen(  # nosec B603 - fixed argv built from sys.executable, no shell
                [sys.executable, "-m", WORKER_MODULE, "--fd", str(child_conn.fileno())],
                env=build_worker_environment(parent_environment=dict(os.environ)),
                cwd=self._workdir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(child_conn.fileno(),),
            )
        except BaseException:
            parent_conn.close()
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise
        finally:
            child_conn.close()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, name=f"worker-stderr-{label}", daemon=True)
        self._stderr_thread.start()
        try:
            self._request(header={"type": TYPE_LOAD, **load_header})
        except BaseException:
            self.stop()
            raise

    @property
    def alive(self) -> bool:
        """True while the process runs and the worker has not been stopped."""
        return not self._closed and self._process.poll() is None

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        logged = 0
        with contextlib.suppress(ValueError, OSError):
            for raw in stream:
                if logged < _MAX_STDERR_LINES:
                    logger.warning("isolated worker %s: %s", self._label, raw.decode("utf-8", "replace").rstrip())
                    logged += 1

    def _request(
        self, *, header: dict[str, Any], tables: list[pa.Table] | None = None
    ) -> tuple[dict[str, Any], list[pa.Table]]:
        with self._lock:
            if self._closed:
                raise IsolatedWorkerError(f"isolated worker for '{self._label}' is stopped")
            try:
                send_message(conn=self._conn, header=header, tables=tables)
                reply, out_tables = receive_message(conn=self._conn)
            except (EOFError, OSError, BrokenPipeError) as exc:
                raise IsolatedWorkerError(f"isolated worker for '{self._label}' exited unexpectedly") from exc
        if reply.get("type") != "ok":
            raise IsolatedWorkerError(f"isolated worker for '{self._label}' failed: {reply.get('message', 'unknown')}")
        return reply, out_tables

    def run(
        self, *, config: dict[str, Any], table: pa.Table, secrets: dict[str, Any] | None = None
    ) -> tuple[list[pa.Table], dict[str, Any], dict[str, Any]]:
        """Run one batch: returns the output tables, the operator metadata and the remaining reply fields.

        ``secrets`` maps JSON-encoded field paths to revealed values. They travel in the message header over the
        private pipe, to this worker only.
        """
        reply, out_tables = self._request(
            header={"type": TYPE_RUN, "config": config, "secrets": secrets or {}}, tables=[table]
        )
        metadata = reply.pop("metadata", {})
        return out_tables, metadata, reply

    def stop(self) -> None:
        """Ask the worker to exit, kill it after a grace period, and remove its private directory. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            with contextlib.suppress(Exception):
                send_message(conn=self._conn, header={"type": TYPE_STOP})
            with contextlib.suppress(Exception):
                self._conn.close()
            try:
                self._process.wait(timeout=_STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            if self._process.stderr is not None:
                with contextlib.suppress(Exception):
                    self._process.stderr.close()
            shutil.rmtree(self._workdir, ignore_errors=True)


class IsolationWorkerPool:
    """Persistent workers keyed by run and operator class, reused across the run's batches."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: dict[tuple[str, str], IsolatedWorker] = {}

    def acquire(self, *, run_id: str, label: str, source_file: str, load_header: dict[str, Any]) -> IsolatedWorker:
        """Return the live worker for ``(run_id, source_file)``, starting it on first use or after a crash."""
        key = (run_id, source_file)
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None and worker.alive:
                return worker
            if worker is not None:
                worker.stop()
            worker = IsolatedWorker(label=label, source_file=source_file, load_header=load_header)
            self._workers[key] = worker
            return worker

    def release_run(self, *, run_id: str) -> None:
        """Stop every worker of ``run_id``."""
        with self._lock:
            keys = [key for key in self._workers if key[0] == run_id]
            workers = [self._workers.pop(key) for key in keys]
        for worker in workers:
            worker.stop()

    def release_all(self) -> None:
        """Stop every worker (process exit and tests)."""
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()

    def size(self) -> int:
        """Number of workers currently held."""
        with self._lock:
            return len(self._workers)


_POOL = IsolationWorkerPool()
atexit.register(_POOL.release_all)


def get_worker_pool() -> IsolationWorkerPool:
    """Return the process-wide worker pool."""
    return _POOL
