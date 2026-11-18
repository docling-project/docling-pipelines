# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Wire format between the API process and an isolation worker.

A message is a UTF-8 JSON header followed by ``header["tables"]`` Arrow IPC streams, each sent as its own
``Connection`` message. Nothing is pickled: the worker runs untrusted code, so the parent must never deserialize
anything it sends with a format that can execute code. Both sides import this module, so it only depends on
``pyarrow`` and the standard library.
"""

import json
from multiprocessing.connection import Connection
from typing import Any, Final

import pyarrow as pa

MAX_ERROR_LENGTH: Final[int] = 2000

TYPE_LOAD: Final[str] = "load"
TYPE_RUN: Final[str] = "run"
TYPE_STOP: Final[str] = "stop"


def table_to_ipc(*, table: pa.Table) -> bytes:
    """Serialize ``table`` as an Arrow IPC stream."""
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def table_from_ipc(*, data: bytes) -> pa.Table:
    """Deserialize an Arrow IPC stream produced by :func:`table_to_ipc`."""
    return pa.ipc.open_stream(pa.py_buffer(data)).read_all()


def send_message(*, conn: Connection, header: dict[str, Any], tables: list[pa.Table] | None = None) -> None:
    """Send ``header`` as JSON, then each table as an Arrow IPC stream.

    Raises:
        TypeError: ``header`` is not JSON serializable.
    """
    tables = tables or []
    payload = json.dumps({**header, "tables": len(tables)}, default=str).encode("utf-8")
    conn.send_bytes(payload)
    for table in tables:
        conn.send_bytes(table_to_ipc(table=table))


def receive_message(*, conn: Connection) -> tuple[dict[str, Any], list[pa.Table]]:
    """Receive one message sent by :func:`send_message`.

    Raises:
        EOFError: The other side closed the connection.
        ValueError: The header is not a JSON object.
    """
    header = json.loads(conn.recv_bytes().decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("message header must be a JSON object")
    count = header.get("tables", 0)
    if not isinstance(count, int) or count < 0:
        raise ValueError("message table count must be a non-negative integer")
    tables = [table_from_ipc(data=conn.recv_bytes()) for _ in range(count)]
    return header, tables


def describe_exception(*, exc: BaseException) -> str:
    """Return a bounded one-line description of ``exc`` for a message header."""
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
