# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""The scanner of the conformance suite must itself be able to fail (task E.1).

A suite that scans for a form it cannot recognise passes for the wrong reason, so each form and each sink kind
is shown to be detected here.
"""

import base64
import json
from pathlib import Path
from urllib.parse import quote, quote_plus

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.unit.secrets_conformance.sinks import Sinks, find_leaks, make_canary, structured_leaves, table_text

CANARY = make_canary(parts=["op", "field"])
URL_CANARY = make_canary(parts=["op", "url"], url_like=True)


def _leaks(*, text: str, canary: str = CANARY) -> list[str]:
    sinks = Sinks()
    sinks.add_text(sink="logs", text=text)
    return find_leaks(sinks=sinks, canaries=[canary])


def test_canaries_are_unique_per_field_and_change_under_every_encoding() -> None:
    assert make_canary(parts=["a", "b"]) != make_canary(parts=["a", "c"])
    assert quote(CANARY) != CANARY


@pytest.mark.parametrize(
    "text",
    [
        CANARY,
        CANARY.encode().hex(),
        quote(CANARY),
        quote_plus(CANARY),
        json.dumps({"k": CANARY}),
        repr({"k": CANARY}),
        base64.b64encode(CANARY.encode()).decode(),
        base64.urlsafe_b64encode(CANARY.encode()).decode().rstrip("="),
        base64.b64encode(base64.b64encode(CANARY.encode())).decode(),
        "Authorization: Basic " + base64.b64encode(b"user:" + CANARY.encode()).decode(),
        "Authorization: Basic " + base64.b64encode(b"user:" + CANARY.encode()).decode().rstrip("="),
        "token=" + base64.b64encode(b"u" + CANARY.encode()).decode(),
    ],
    ids=[
        "raw",
        "hex",
        "quote",
        "quote_plus",
        "json",
        "repr",
        "b64",
        "b64url-nopad",
        "double-b64",
        "basic-auth-user-colon",
        "basic-auth-unpadded",
        "b64-offset-one",
    ],
)
def test_every_encoded_or_derived_form_is_detected(*, text: str) -> None:
    assert _leaks(text=f"prefix {text} suffix")


def test_a_url_shaped_canary_is_also_detected_by_its_host_alone() -> None:
    host = URL_CANARY.split("://", 1)[1].split("/", 1)[0]

    assert _leaks(text=f"connection to {host} failed", canary=URL_CANARY)


def test_clean_text_and_other_fields_canaries_are_not_flagged() -> None:
    other = make_canary(parts=["op", "other"])

    assert _leaks(text=f"nothing to see ***, {other}") == []


def test_a_leak_is_reported_with_its_sink_and_form() -> None:
    assert "logs [raw]" in _leaks(text=f"error: {CANARY}")


def test_objects_are_scanned_by_repr_and_by_json() -> None:
    sinks = Sinks()
    sinks.add_object(sink="metadata", value={"nested": [{"reason": f"failed for {CANARY}"}]})

    assert any(item.startswith("metadata [") for item in find_leaks(sinks=sinks, canaries=[CANARY]))


def test_an_object_that_cannot_be_rendered_does_not_stop_the_scan() -> None:
    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("no repr")

    sinks = Sinks()
    sinks.add_object(sink="metadata", value={"x": Hostile(), "y": CANARY})

    assert find_leaks(sinks=sinks, canaries=[CANARY])


def test_files_are_scanned_as_bytes_and_parquet_is_decoded(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "plain.txt").write_text(f"x {CANARY} y", encoding="utf-8")
    # Dictionary-encoded or compressed cell data does not contain the value verbatim; the decoded view does.
    table = pa.table({"msg": [f"failed: {CANARY}"] * 50})
    pq.write_table(table, tmp_path / "t.parquet", compression="zstd")
    sinks = Sinks()

    count = sinks.add_file_tree(root=tmp_path)

    leaked = find_leaks(sinks=sinks, canaries=[CANARY])
    assert count == 2
    assert any(item.startswith("file:sub/plain.txt") for item in leaked)
    assert any(item.startswith("file:t.parquet:decoded") for item in leaked)


def test_a_clean_file_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("nothing", encoding="utf-8")
    sinks = Sinks()
    sinks.add_file_tree(root=tmp_path)

    assert find_leaks(sinks=sinks, canaries=[CANARY]) == []


def test_table_text_covers_column_names_schema_metadata_and_cells() -> None:
    table = pa.table({f"col_{CANARY}": ["v"], "b": [CANARY]}).replace_schema_metadata({"k": f"meta {CANARY}"})

    rendered = json.loads(table_text(table=table))

    assert CANARY in rendered["columns"][0]
    assert CANARY in rendered["schema_metadata"]["k"]
    assert rendered["cells"]["b"] == [CANARY]


def test_structured_leaves_flattens_nested_values() -> None:
    assert sorted(structured_leaves(value={"a": "x", "b": ["y", {"c": "z"}], "d": ""})) == ["x", "y", "z"]
