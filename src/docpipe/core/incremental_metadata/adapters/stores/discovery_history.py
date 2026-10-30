# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Temporary indexed history used by source synchronization, independent of durable stores."""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from docpipe.core.incremental_metadata.domain.ports.incremental_metadata_store import DiscoveryHistory


class _SqliteDiscoveryHistory(DiscoveryHistory):
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._active_count = connection.execute("SELECT count(*) FROM history WHERE deleted = 0").fetchone()[0]

    def __len__(self) -> int:
        return self._active_count

    def __iter__(self) -> Iterator[str]:
        cursor = self._connection.execute("SELECT id FROM history WHERE deleted = 0")
        try:
            for row in cursor:
                yield row[0]
        finally:
            cursor.close()

    def __getitem__(self, doc_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT modified_time FROM history WHERE id = ? AND deleted = 0", (doc_id,)
        ).fetchone()
        if row is None:
            raise KeyError(doc_id)
        return {"modified_time": row[0]}

    def mark_seen(self, doc_id: str) -> None:
        self._connection.execute("UPDATE history SET seen = 1 WHERE id = ? AND seen = 0", (doc_id,))

    def missing_ids(self) -> set[str]:
        return {row[0] for row in self._connection.execute("SELECT id FROM history WHERE seen = 0")}

    def returned_ids(self) -> set[str]:
        return {row[0] for row in self._connection.execute("SELECT id FROM history WHERE seen = 1 AND deleted = 1")}

    def newly_missing_count(self) -> int:
        return self._connection.execute("SELECT count(*) FROM history WHERE seen = 0 AND deleted = 0").fetchone()[0]


@contextmanager
def open_discovery_history(records: Iterable[tuple[str, int | None, bool]]) -> Iterator[DiscoveryHistory]:
    """Spool bounded record batches to disk and always remove the snapshot afterward."""
    with TemporaryDirectory(prefix="docpipe-discovery-") as directory:
        connection = sqlite3.connect(str(Path(directory) / "history.sqlite"), check_same_thread=False)
        try:
            connection.execute("PRAGMA cache_size = -2048")
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute(
                "CREATE TABLE history (id TEXT PRIMARY KEY, modified_time INTEGER, deleted INTEGER, "
                "seen INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID"
            )
            for batch in batched(records, 1000):
                connection.executemany("INSERT INTO history (id, modified_time, deleted) VALUES (?, ?, ?)", batch)
            connection.commit()
            yield _SqliteDiscoveryHistory(connection)
        finally:
            connection.close()
            close = getattr(records, "close", None)
            if close is not None:
                close()
