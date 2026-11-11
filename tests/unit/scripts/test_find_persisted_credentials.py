# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for scripts/find_persisted_credentials.py."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "find_persisted_credentials.py"

SECRET_VALUE = "CANARY-secret-value-9f3a"  # pragma: allowlist secret
CLIENT_ID_VALUE = "CANARY-client-id-1b2c"
TENANT_VALUE = "CANARY-tenant-id-7d8e"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("find_persisted_credentials", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _leaky_metadata() -> dict:
    return {
        "provider": "sharepoint",
        "client_id": CLIENT_ID_VALUE,
        "client_secret": SECRET_VALUE,
        "tenant_id": TENANT_VALUE,
    }


def _write_parquet(*, path: Path, columns: dict) -> None:
    pq.write_table(pa.table(columns), path)


def _assert_no_values(*, text: str) -> None:
    for value in (SECRET_VALUE, CLIENT_ID_VALUE, TENANT_VALUE):
        assert value not in text


class TestFindCredentialKeys:
    def test_finds_nested_keys(self) -> None:
        node = {"a": [{"b": {"client_secret": "x"}}], "tenant_id": "t"}
        assert script.find_credential_keys(node=node) == {"client_secret", "tenant_id"}

    def test_ignores_empty_and_null_values(self) -> None:
        node = {"client_id": "", "client_secret": None, "tenant_id": ""}
        assert script.find_credential_keys(node=node) == set()

    def test_clean_node(self) -> None:
        assert script.find_credential_keys(node={"provider": "sharepoint"}) == set()


class TestScanParquet:
    def test_metadata_json_string(self, tmp_path: Path) -> None:
        path = tmp_path / "out.parquet"
        _write_parquet(path=path, columns={"metadata": [json.dumps(_leaky_metadata())]})
        assert script.scan_parquet(path=path) == {"client_id", "client_secret", "tenant_id"}

    def test_credential_columns(self, tmp_path: Path) -> None:
        path = tmp_path / "cols.parquet"
        _write_parquet(path=path, columns={"client_secret": [SECRET_VALUE], "content": ["x"]})
        assert script.scan_parquet(path=path) == {"client_secret"}

    def test_empty_credential_column_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.parquet"
        _write_parquet(path=path, columns={"client_secret": [""], "metadata": ["not json client_id"]})
        assert script.scan_parquet(path=path) == set()

    def test_clean_parquet(self, tmp_path: Path) -> None:
        path = tmp_path / "clean.parquet"
        _write_parquet(path=path, columns={"metadata": [json.dumps({"provider": "sharepoint"})]})
        assert script.scan_parquet(path=path) == set()


class TestScanJson:
    def test_sidecar(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.meta.json"
        path.write_text(json.dumps({"metadata": _leaky_metadata()}), encoding="utf-8")
        assert script.scan_json(path=path) == {"client_id", "client_secret", "tenant_id"}


class TestIterCandidateFiles:
    def test_directory_filters_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.parquet").write_bytes(b"")
        (tmp_path / "b.meta.json").write_text("{}", encoding="utf-8")
        (tmp_path / "c.json").write_text("{}", encoding="utf-8")
        (tmp_path / "d.txt").write_text("x", encoding="utf-8")
        names = {p.name for p in script.iter_candidate_files(paths=[tmp_path])}
        assert names == {"a.parquet", "b.meta.json"}

    def test_explicit_json_file_is_scanned(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{}", encoding="utf-8")
        assert list(script.iter_candidate_files(paths=[path])) == [path]


class TestMain:
    def test_affected_files_exit_1_and_no_values_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_parquet(path=tmp_path / "out.parquet", columns={"metadata": [json.dumps(_leaky_metadata())]})
        (tmp_path / "doc.meta.json").write_text(json.dumps({"metadata": _leaky_metadata()}), encoding="utf-8")

        code = script.main([str(tmp_path)])

        captured = capsys.readouterr()
        assert code == 1
        assert "out.parquet" in captured.out
        assert "doc.meta.json" in captured.out
        assert "client_secret" in captured.out
        _assert_no_values(text=captured.out + captured.err)

    def test_clean_directory_exit_0(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_parquet(path=tmp_path / "ok.parquet", columns={"metadata": [json.dumps({"provider": "x"})]})
        assert script.main([str(tmp_path)]) == 0
        assert capsys.readouterr().out == ""

    def test_nonexistent_path_exit_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert script.main([str(tmp_path / "missing")]) == 2
        assert "does not exist" in capsys.readouterr().err

    def test_unreadable_file_warns_without_content(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "bad.parquet").write_text(f"client_secret {SECRET_VALUE}", encoding="utf-8")

        code = script.main([str(tmp_path)])

        captured = capsys.readouterr()
        assert code == 2
        assert "could not read" in captured.err
        _assert_no_values(text=captured.out + captured.err)

    def test_unreadable_file_does_not_hide_affected_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "bad.parquet").write_text("garbage", encoding="utf-8")
        _write_parquet(path=tmp_path / "out.parquet", columns={"metadata": [json.dumps(_leaky_metadata())]})
        assert script.main([str(tmp_path)]) == 1
        capsys.readouterr()
