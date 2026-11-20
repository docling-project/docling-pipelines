# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Canary forms and the sink scanner for the secret conformance suite (task E.1).

The forms are derived here, independently of ``SecretRegistry.derive_forms``. If the suite reused the
production list, a form the scrubber does not know would also be a form the test does not look for.
"""

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import pyarrow as pa
import pyarrow.parquet as pq

# Shortest canary fragment the scanner looks for in the "partial" forms (see ``forms_of``).
_MIN_FRAGMENT = 8


def make_canary(*, parts: Iterable[str], url_like: bool = False) -> str:
    """Return a deterministic, unique canary for one ``(operator, provider, field)``.

    The value carries characters that every encoding changes (``/ + & = :``) so that each derived form
    differs from the raw one.
    """
    digest = hashlib.sha256("/".join(parts).encode()).hexdigest()[:12]
    if url_like:
        return f"https://cnry-{digest}.example.test/a/b+c&d=1:e"
    return f"CNRY-{digest}/p+w&x=1:y"


def _b64_variants(*, raw: bytes) -> dict[str, str]:
    """Return the base64 forms of ``raw``: standard and URL-safe, padded and unpadded."""
    standard = base64.b64encode(raw).decode("ascii")
    urlsafe = base64.urlsafe_b64encode(raw).decode("ascii")
    return {
        "b64": standard,
        "b64-nopad": standard.rstrip("="),
        "b64url": urlsafe,
        "b64url-nopad": urlsafe.rstrip("="),
    }


def forms_of(*, canary: str) -> dict[str, str]:
    """Return ``{label: needle}`` for the canary and every encoded or derived form the suite looks for.

    * ``raw``, ``hex`` (lower and upper), ``quote``, ``quote_plus``, JSON-escaped, and ``repr`` escaped.
    * base64, standard and URL-safe, padded and unpadded.
    * A base64 of ``user:canary`` and ``canary:`` fragments at each of the three alignments, so an
      ``Authorization: Basic ...`` header or a Milvus ``user:password`` token is found even though its
      encoding of the canary depends on the offset. Only the characters wholly determined by the canary
      are used as the needle.
    * The same alignments for ``double`` base64, and the host of a URL-shaped canary.
    """
    raw = canary.encode("utf-8")
    forms: dict[str, str] = {
        "raw": canary,
        "hex": raw.hex(),
        "hex-upper": raw.hex().upper(),
        "quote": quote(canary),
        "quote-safe-empty": quote(canary, safe=""),
        "quote_plus": quote_plus(canary),
        "json": json.dumps(canary)[1:-1],
        "json-ascii-off": json.dumps(canary, ensure_ascii=False)[1:-1],
        "repr": repr(canary)[1:-1],
    }
    forms.update(_b64_variants(raw=raw))
    forms.update({f"double-{label}": value for label, value in _b64_variants(raw=forms["b64"].encode()).items()})
    if "://" in canary:
        # A URL-shaped canary is also leaked by its host alone.
        forms["host"] = canary.split("://", 1)[1].split("/", 1)[0]
    for offset in (1, 2):
        shifted = base64.b64encode(b"u" * offset + raw).decode("ascii").rstrip("=")
        # Characters before ``skip`` mix the prefix bits; the last two depend on padding.
        skip = (offset * 4 + 2) // 3 + 1
        fragment = shifted[skip:-2]
        if len(fragment) >= _MIN_FRAGMENT:
            forms[f"b64-derived-offset{offset}"] = fragment
    return forms


@dataclass
class Sinks:
    """The text and bytes captured from one scenario, keyed by sink name."""

    texts: dict[str, str] = field(default_factory=dict)
    blobs: dict[str, bytes] = field(default_factory=dict)

    def add_text(self, *, sink: str, text: str) -> None:
        """Append ``text`` to a named text sink."""
        self.texts[sink] = self.texts.get(sink, "") + "\n" + text

    def add_object(self, *, sink: str, value: Any) -> None:
        """Append both the ``repr`` and a JSON rendering of ``value`` to a named text sink."""
        self.add_text(sink=sink, text=safe_repr(value=value))
        self.add_text(sink=sink, text=json.dumps(value, default=safe_repr_kw, ensure_ascii=False))

    def add_file_tree(self, *, root: Path) -> int:
        """Capture every file below ``root``; parquet files are also captured decoded. Return the file count."""
        count = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            count += 1
            key = f"file:{path.relative_to(root)}"
            data = path.read_bytes()
            self.blobs[key] = data
            if path.suffix == ".parquet":
                try:
                    self.add_text(sink=f"{key}:decoded", text=_decode_parquet(path=path))
                except Exception:  # nosec B110 - an unreadable file is still scanned as bytes
                    pass
        return count


def safe_repr(*, value: Any) -> str:
    """Return ``repr(value)`` without ever raising."""
    try:
        return repr(value)
    except Exception as exc:
        return f"<unrepresentable {type(value).__name__}: {type(exc).__name__}>"


def safe_repr_kw(value: Any) -> str:
    """``json.dumps`` default hook: render any object through ``repr``."""
    return safe_repr(value=value)


def _decode_parquet(*, path: Path) -> str:
    table = pq.read_table(path)
    return table_text(table=table)


def table_text(*, table: pa.Table) -> str:
    """Render a table's column names, schema metadata, and every cell as text."""
    meta = {k.decode(errors="replace"): v.decode(errors="replace") for k, v in (table.schema.metadata or {}).items()}
    cells = {name: table.column(name).to_pylist() for name in table.column_names}
    return json.dumps({"columns": table.column_names, "schema_metadata": meta, "cells": cells}, default=safe_repr_kw)


def find_leaks(*, sinks: Sinks, canaries: Iterable[str]) -> list[str]:
    """Return ``"sink: form"`` for every sink that contains any form of any canary."""
    found: list[str] = []
    for canary in canaries:
        for label, needle in forms_of(canary=canary).items():
            if not needle:
                continue
            found.extend(f"{sink} [{label}]" for sink, text in sinks.texts.items() if needle in text)
            data = needle.encode("utf-8")
            found.extend(f"{sink} [{label}]" for sink, blob in sinks.blobs.items() if data in blob)
    return sorted(set(found))


def structured_leaves(*, value: Mapping[str, Any] | list[Any] | str) -> list[str]:
    """Return every non-empty string leaf of a structured secret."""
    if isinstance(value, str):
        return [value] if value else []
    items = value.values() if isinstance(value, Mapping) else value
    leaves: list[str] = []
    for item in items:
        leaves.extend(structured_leaves(value=item))
    return leaves
