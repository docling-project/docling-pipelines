# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Entry point of an isolation worker: ``python -m ...isolation.worker_main --fd <n>``.

The worker runs untrusted custom operator code. It must hold no secret state, so it never imports the parent-only
modules (``mode`` and ``worker_client`` read the deployment configuration and talk to the provider registry) and it
never registers a provider. It starts with only the allowlisted environment and the one inherited descriptor named by
``--fd``, which is the private pipe to the API process.

Imports are deferred to the first ``load`` message: the cost of importing the operator base is part of the start-up
budget the parent measures, and a worker that fails to start should still be able to report why.
"""

import argparse
import sys
from multiprocessing.connection import Connection
from typing import Any

from docpipe.core.orchestration.operator_loader.isolation.protocol import (
    TYPE_LOAD,
    TYPE_RUN,
    TYPE_STOP,
    describe_exception,
    receive_message,
    send_message,
)


class _Worker:
    """State of one worker: the operator class loaded from the node's source file."""

    def __init__(self) -> None:
        self._operator_class: Any = None

    def load(self, *, header: dict[str, Any]) -> None:
        """Import the operator file and select the class named in ``header``."""
        from pathlib import Path

        from docpipe.core.orchestration.operator_loader.module_import import import_module_from_file
        from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
        from docpipe.core.orchestration.operator_loader.validator import OperatorValidator

        info = OperatorInfo(
            name=header["class_name"],
            short_name=header["short_name"],
            module_path=header["module_path"],
            category=header["category"],
            source_location=header["source_file"],
        )
        module = import_module_from_file(file_path=Path(header["source_file"]))
        operator_class = OperatorValidator.select_operator_class(module=module, operator_info=info)
        if operator_class is None or getattr(operator_class, "short_name", None) != info.short_name:
            raise ImportError(f"operator file for '{info.short_name}' no longer defines that operator")
        self._operator_class = operator_class

    def run(self, *, header: dict[str, Any], tables: list[Any]) -> tuple[dict[str, Any], list[Any]]:
        """Build a fresh operator for this batch, transform, and return the reply header and tables."""
        if self._operator_class is None:
            raise RuntimeError("worker received a run message before a load message")
        operator = self._operator_class(config=header["config"])
        try:
            if header.get("multiple_tables"):
                raise NotImplementedError("untrusted custom operators cannot take several input tables")
            result_tables, metadata = operator.transform(tables[0])
            reply = {
                "metadata": metadata,
                "output_features_to_drop": list(getattr(operator, "output_features_to_drop", []) or []),
                "updated_features": list(getattr(operator, "updated_features", []) or []),
            }
            return reply, list(result_tables)
        finally:
            cleanup = getattr(operator, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception as exc:  # the batch result matters more than cleanup
                    print("operator cleanup failed: " + describe_exception(exc=exc), file=sys.stderr)


def serve(*, conn: Connection) -> None:
    """Handle messages from the parent until it sends ``stop`` or closes the pipe."""
    worker = _Worker()
    while True:
        try:
            header, tables = receive_message(conn=conn)
        except EOFError:
            return
        kind = header.get("type")
        if kind == TYPE_STOP:
            return
        try:
            if kind == TYPE_LOAD:
                worker.load(header=header)
                send_message(conn=conn, header={"type": "ok"})
            elif kind == TYPE_RUN:
                reply, out_tables = worker.run(header=header, tables=tables)
                send_message(conn=conn, header={"type": "ok", **reply}, tables=out_tables)
            else:
                raise ValueError("unknown message type")
        except BaseException as exc:  # the parent needs every failure, including SystemExit
            send_message(conn=conn, header={"type": "error", "message": describe_exception(exc=exc)})


def main(argv: list[str] | None = None) -> int:
    """Parse ``--fd`` and serve on that descriptor."""
    parser = argparse.ArgumentParser(description="docpipe isolation worker (internal)")
    parser.add_argument("--fd", type=int, required=True)
    args = parser.parse_args(argv)
    conn = Connection(args.fd)
    try:
        serve(conn=conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
