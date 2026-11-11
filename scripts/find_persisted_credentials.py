#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Find legacy SharePoint/OneDrive credentials persisted in ingest output.

Before this fix, the SharePoint and OneDrive ingest adapters wrote ``client_id``,
``client_secret`` and ``tenant_id`` into each document's ``metadata``. That metadata
was serialized to parquet files and to ``*.meta.json`` storage sidecars, so any output
produced by those adapters may hold the credentials in clear text.

This script scans the given files and directories for those keys and lists the affected
files and the key names found. It never prints, logs or returns a credential value.

Usage:
    python scripts/find_persisted_credentials.py PATH [PATH ...]

Exit status:
    0  no persisted credentials found
    1  at least one affected file found (treat the credentials as disclosed: rotate them)
    2  usage error or nothing could be scanned
"""

import argparse
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

CREDENTIAL_KEYS: frozenset[str] = frozenset({"client_id", "client_secret", "tenant_id"})
PARQUET_SUFFIXES: frozenset[str] = frozenset({".parquet", ".pq"})
JSON_SUFFIX = ".json"
SIDECAR_SUFFIX = ".meta.json"
METADATA_COLUMN = "metadata"


def _has_value(value: Any) -> bool:
    """Return True when a credential key holds something other than null or an empty string."""
    return value is not None and value != ""


def find_credential_keys(*, node: Any) -> set[str]:
    """Return the credential key names present with a non-empty value anywhere in ``node``.

    Only key names are returned, never values.
    """
    found: set[str] = set()
    stack: list[Any] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in CREDENTIAL_KEYS and _has_value(value):
                    found.add(key)
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(item for item in current if isinstance(item, (dict, list)))
    return found


def _keys_in_metadata_cell(*, cell: Any) -> set[str]:
    """Return credential key names in one parquet ``metadata`` cell (JSON string or dict)."""
    if isinstance(cell, str):
        if not cell or not any(key in cell for key in CREDENTIAL_KEYS):
            return set()
        try:
            return find_credential_keys(node=json.loads(cell))
        except json.JSONDecodeError:
            return set()
    return find_credential_keys(node=cell)


def scan_parquet(*, path: Path) -> set[str]:
    """Return credential key names stored in a parquet file's columns or ``metadata`` column."""
    parquet_file = pq.ParquetFile(path)
    column_names = set(parquet_file.schema_arrow.names)

    found: set[str] = set()
    for column in column_names & CREDENTIAL_KEYS:
        for batch in parquet_file.iter_batches(columns=[column]):
            if any(_has_value(item) for item in batch.column(0).to_pylist()):
                found.add(column)
                break

    if METADATA_COLUMN in column_names:
        for batch in parquet_file.iter_batches(columns=[METADATA_COLUMN]):
            for cell in batch.column(0).to_pylist():
                found |= _keys_in_metadata_cell(cell=cell)
            if found >= CREDENTIAL_KEYS:
                break
    return found


def scan_json(*, path: Path) -> set[str]:
    """Return credential key names stored anywhere in a JSON file (for example ``*.meta.json``)."""
    with path.open("r", encoding="utf-8") as handle:
        return find_credential_keys(node=json.load(handle))


def iter_candidate_files(*, paths: Iterable[Path]) -> Iterator[Path]:
    """Yield parquet files and storage sidecars under the given files and directories.

    Inside a directory only ``*.parquet``, ``*.pq`` and ``*.meta.json`` are scanned. A file
    passed explicitly is scanned when it is parquet or any ``.json`` file.
    """
    for root in paths:
        if root.is_file():
            suffix = root.suffix.lower()
            if suffix in PARQUET_SUFFIXES or suffix == JSON_SUFFIX:
                yield root
            continue
        for candidate in sorted(item for item in root.rglob("*") if item.is_file()):
            name = candidate.name.lower()
            if candidate.suffix.lower() in PARQUET_SUFFIXES or name.endswith(SIDECAR_SUFFIX):
                yield candidate


def scan_paths(*, paths: Iterable[Path]) -> tuple[dict[Path, list[str]], list[Path], int]:
    """Scan ``paths`` and return (affected files with key names, unreadable files, files scanned)."""
    affected: dict[Path, list[str]] = {}
    unreadable: list[Path] = []
    scanned = 0
    for file_path in iter_candidate_files(paths=paths):
        try:
            if file_path.suffix.lower() not in PARQUET_SUFFIXES:
                keys = scan_json(path=file_path)
            else:
                keys = scan_parquet(path=file_path)
        except Exception:  # never surface file content through an exception message
            unreadable.append(file_path)
            continue
        scanned += 1
        if keys:
            affected[file_path] = sorted(keys)
    return affected, unreadable, scanned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List parquet files and sidecar JSON that contain legacy persisted "
        "client_id/client_secret/tenant_id values. Values are never printed."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to scan recursively")
    args = parser.parse_args(argv)

    missing = [path for path in args.paths if not path.exists()]
    for path in missing:
        print(f"error: path does not exist: {path}", file=sys.stderr)
    existing = [path for path in args.paths if path.exists()]
    if not existing:
        return 2

    affected, unreadable, scanned = scan_paths(paths=existing)

    for file_path, keys in affected.items():
        print(f"{file_path}: {', '.join(keys)}")
    for file_path in unreadable:
        print(f"warning: could not read {file_path}", file=sys.stderr)

    print(f"Scanned {scanned} file(s); {len(affected)} contain persisted credentials.", file=sys.stderr)
    if affected:
        print(
            "Treat these credentials as disclosed: rotate them, then purge or re-ingest the listed files.",
            file=sys.stderr,
        )
        return 1
    return 2 if missing or (scanned == 0 and unreadable) else 0


if __name__ == "__main__":
    sys.exit(main())
