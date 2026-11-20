# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for StorageOutputOperator: validation, path derivation and sidecar contents."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.storage_output_operator import (
    StorageOutputOperator,
    _extract_source_relative_path,
    resolve_path_template,
)

_FETCH = "docpipe.core.operators.storage.storage_output_operator.get_binary_content"
_ALL_FEATURES = ["id", "name", "path", "content", "metadata", "document_format"]


def _config(dest: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": "storage_output",
        "id": "node_1",
        "mode": "processed_content",
        "destination_config": {
            "provider": "filesystem",
            "provider_config": {"root_path": str(dest), "create_dirs": True},
            "credentials": {},
        },
        "output_format": {"content_format": "md"},
        "output_structure": {},
    }
    config.update(overrides)
    return config


def _ingest_source(**provider_config: Any) -> dict[str, Any]:
    return {"provider": "filesystem", "provider_config": provider_config}


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


class TestResolvePathTemplate:
    """resolve_path_template normalises the resolved path."""

    def test_empty_relative_dir_collapses_double_slash(self) -> None:
        """An empty {relative_dir} in the middle of a template leaves no '//' behind."""
        resolved = resolve_path_template(
            template="out/{relative_dir}/{name}.{ext}",
            doc_id="d1",
            name="report.pdf",
            ext=".md",
            source_relative_path="report.pdf",
        )
        assert resolved == "out/report.md"

    def test_relative_dir_is_filled(self) -> None:
        """{relative_dir} expands to the source sub-directory."""
        resolved = resolve_path_template(
            template="out/{relative_dir}/{name}.{ext}",
            doc_id="d1",
            name="report.pdf",
            ext="md",
            source_relative_path="sub/report.pdf",
        )
        assert resolved == "out/sub/report.md"


class TestExtractSourceRelativePathWithSourceRoots:
    """Hierarchical mode prefixes the owning source root's folder name."""

    def test_prefixes_matching_root_from_absolute_path(self, tmp_path: Path) -> None:
        """The root whose path joined with relative_path equals absolute_path is used."""
        roots = [str(tmp_path / "sub01"), str(tmp_path / "sub02")]
        meta = {"relative_path": "a/report.pdf", "absolute_path": str(tmp_path / "sub02" / "a" / "report.pdf")}

        result = _extract_source_relative_path({"metadata": json.dumps(meta)}, hierarchical=True, source_paths=roots)

        assert result == "sub02/a/report.pdf"

    def test_falls_back_to_row_path(self, tmp_path: Path) -> None:
        """Without absolute_path in the metadata the row's path is matched."""
        roots = [str(tmp_path / "sub01")]
        row = {"metadata": json.dumps({"relative_path": "r.pdf"}), "path": str(tmp_path / "sub01" / "r.pdf")}

        assert _extract_source_relative_path(row, hierarchical=True, source_paths=roots) == "sub01/r.pdf"

    def test_no_matching_root_returns_relative_path(self, tmp_path: Path) -> None:
        """A file outside every configured root keeps its plain relative path."""
        roots = [str(tmp_path / "sub01")]
        row = {"metadata": json.dumps({"relative_path": "r.pdf"}), "path": str(tmp_path / "other" / "r.pdf")}

        assert _extract_source_relative_path(row, hierarchical=True, source_paths=roots) == "r.pdf"

    def test_no_absolute_path_returns_relative_path(self, tmp_path: Path) -> None:
        """Without any absolute path no root can be matched."""
        row = {"metadata": json.dumps({"relative_path": "r.pdf"})}

        assert _extract_source_relative_path(row, hierarchical=True, source_paths=[str(tmp_path)]) == "r.pdf"

    def test_path_outside_ingest_root_returns_none(self, tmp_path: Path) -> None:
        """A row path that is not below the ingest root yields no relative path."""
        row = {"path": str(tmp_path / "elsewhere" / "r.pdf")}

        assert _extract_source_relative_path(row, ingest_root=str(tmp_path / "root")) is None


class TestValidate:
    """validate reports missing or unknown modes."""

    def test_missing_mode(self, tmp_path: Path) -> None:
        """A missing mode is reported and no column checks follow."""
        config = _config(tmp_path)
        config.pop("mode")
        errors: list[str] = []

        StorageOutputOperator(config).validate(errors, [], available_features=[])

        assert "storage_output: 'mode' is required" in errors
        assert not [e for e in errors if "required column" in e]

    def test_invalid_mode(self, tmp_path: Path) -> None:
        """An unknown mode is reported with the valid values."""
        errors: list[str] = []

        StorageOutputOperator(_config(tmp_path, mode="bogus")).validate(errors, [], available_features=_ALL_FEATURES)

        invalid = [e for e in errors if "invalid mode 'bogus'" in e]
        assert len(invalid) == 1
        assert "processed_content" in invalid[0]
        assert not [e for e in errors if "required column" in e]


class TestTransformPreconditions:
    """Preconditions checked before any document is written."""

    @pytest.mark.parametrize("mode", ["refetch_original", "comprehensive_export"])
    def test_binary_modes_require_ingest_source(self, tmp_path: Path, mode: str) -> None:
        """Modes that refetch the original need an upstream ingest_source."""
        op = StorageOutputOperator(_config(tmp_path, mode=mode))
        table = pa.Table.from_pylist([{"id": "1", "name": "a.pdf", "content": "x"}])

        with pytest.raises(ValueError, match="requires an upstream 'ingest_source'"):
            op.transform(table)

    def test_unreachable_destination_fails_every_document(self, tmp_path: Path) -> None:
        """A failing pre-flight check marks every document failed without writing anything."""
        missing = tmp_path / "missing"
        config = _config(tmp_path)
        config["destination_config"]["provider_config"] = {"root_path": str(missing), "create_dirs": False}
        table = pa.Table.from_pylist(
            [{"id": "1", "name": "a.md", "content": "x"}, {"id": "2", "name": "b.md", "content": "y"}]
        )

        (output,), metadata = StorageOutputOperator(config).transform(table)

        assert output.column("write_status").to_pylist() == ["failed", "failed"]
        errors = output.column("write_error").to_pylist()
        assert all("create_dirs is disabled" in e for e in errors)
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["1", "2"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED
        assert not missing.exists()


class TestIngestRootDerivation:
    """The ingest root is derived from the row paths; unusable paths fall back to flat output."""

    def _run_hierarchical(self, dest: Path, paths: list[str | None]) -> tuple[pa.Table, dict[str, Any]]:
        config = _config(dest, output_structure={"type": "hierarchical"})
        rows = [{"id": str(i), "name": f"doc{i}.pdf", "content": "c", "path": p} for i, p in enumerate(paths)]
        (output,), metadata = StorageOutputOperator(config).transform(pa.Table.from_pylist(rows))
        return output, metadata

    def test_all_paths_null(self, tmp_path: Path) -> None:
        """Without any path no ingest root exists and files land flat in the destination."""
        dest = tmp_path / "dest"
        output, _ = self._run_hierarchical(dest, [None])

        assert output.column("write_status").to_pylist() == ["success"]
        assert _files(dest) == ["doc0.content.md"]

    def test_mixed_absolute_and_relative_paths(self, tmp_path: Path) -> None:
        """Paths without a common root are ignored instead of failing the batch."""
        dest = tmp_path / "dest"
        output, _ = self._run_hierarchical(dest, [str(tmp_path / "src" / "a" / "doc0.pdf"), "rel/doc1.pdf"])

        assert output.column("write_status").to_pylist() == ["success", "success"]
        assert _files(dest) == ["doc0.content.md", "doc1.content.md"]

    def test_common_root_mirrors_sub_directories(self, tmp_path: Path) -> None:
        """With a common root the sub-directories below it are kept."""
        dest = tmp_path / "dest"
        src = tmp_path / "src"
        output, _ = self._run_hierarchical(dest, [str(src / "a" / "doc0.pdf"), str(src / "b" / "doc1.pdf")])

        assert output.column("write_status").to_pylist() == ["success", "success"]
        assert _files(dest) == ["a/doc0.content.md", "b/doc1.content.md"]


class TestFriendlyName:
    """Names without an extension are replaced by the metadata name only when that has one."""

    def _doc_name_passed(self, tmp_path: Path, row: dict[str, Any]) -> str:
        op = StorageOutputOperator(_config(tmp_path))
        result = WriteResult(doc_id="", doc_name="", success=True)
        with patch.object(StorageOutputOperator, "_write_row", return_value=result) as write_row:
            op.transform(pa.Table.from_pylist([row]))
        return write_row.call_args.kwargs["doc_name"]

    def test_metadata_name_with_extension_is_used(self, tmp_path: Path) -> None:
        """A source URL name is replaced by the friendly file name."""
        row = {"id": "1", "name": "box://123", "content": "c", "metadata": json.dumps({"box_name": "r.pdf"})}
        assert self._doc_name_passed(tmp_path, row) == "r.pdf"

    def test_metadata_name_without_extension_is_ignored(self, tmp_path: Path) -> None:
        """A friendly name without an extension does not replace the original name."""
        row = {"id": "1", "name": "box://123", "content": "c", "metadata": json.dumps({"name": "README"})}
        assert self._doc_name_passed(tmp_path, row) == "box://123"

    def test_invalid_metadata_keeps_name(self, tmp_path: Path) -> None:
        """Malformed metadata JSON leaves the original name in place."""
        row = {"id": "1", "name": "box://123", "content": "c", "metadata": "{not json"}
        assert self._doc_name_passed(tmp_path, row) == "box://123"


class TestUnknownMode:
    """A mode that passes the transform checks but has no writer fails per document."""

    def test_unknown_mode_fails_document(self, tmp_path: Path) -> None:
        """The NotImplementedError is caught and recorded as a failed document."""
        op = StorageOutputOperator(_config(tmp_path, mode="bogus"))

        (output,), metadata = op.transform(pa.Table.from_pylist([{"id": "1", "name": "a.md", "content": "x"}]))

        assert output.column("write_status").to_pylist() == ["failed"]
        assert "not yet implemented" in output.column("write_error").to_pylist()[0]
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED
        assert _files(tmp_path) == []


class TestSidecar:
    """The comprehensive_export metadata sidecar."""

    def _export(self, dest: Path, row: dict[str, Any]) -> dict[str, Any]:
        config = _config(
            dest,
            mode="comprehensive_export",
            ingest_source=_ingest_source(paths=[str(dest.parent / "src")]),
            output_format={"content_format": "md", "include_metadata_sidecar": True},
            output_structure={"path_template": "{doc_id}/{name}.{ext}"},
        )
        with patch(_FETCH, return_value=b"%PDF"):
            (output,), _ = StorageOutputOperator(config).transform(pa.Table.from_pylist([row]))
        assert output.column("write_status").to_pylist() == ["success"]
        return json.loads((dest / "d1" / "report.meta.json").read_text(encoding="utf-8"))

    def test_invalid_metadata_json_still_writes_sidecar(self, tmp_path: Path) -> None:
        """Malformed metadata becomes an empty object, completed by scalar row columns."""
        row = {
            "id": "d1",
            "name": "report.pdf",
            "content": "# c",
            "path": str(tmp_path / "src" / "report.pdf"),
            "metadata": "{broken",
            "document_format": "pdf",
            "size": 123,
        }

        sidecar = self._export(tmp_path / "dest", row)

        assert sidecar == {
            "id": "d1",
            "name": "report.pdf",
            "document_format": "pdf",
            "metadata": {"size": 123},
        }

    def test_only_scalar_columns_are_merged_without_overriding_metadata(self, tmp_path: Path) -> None:
        """Scalar extra columns are added; null and list values are left out; metadata keys win."""
        row = {
            "id": "d1",
            "name": "report.pdf",
            "content": "# c",
            "path": str(tmp_path / "src" / "report.pdf"),
            "metadata": json.dumps({"author": "Alice", "size": 1}),
            "document_format": "pdf",
            "size": 999,
            "score": 0.5,
            "ocr": True,
            "owner": "bob",
            "tags": ["x", "y"],
            "note": None,
        }

        sidecar = self._export(tmp_path / "dest", row)

        assert sidecar["metadata"] == {"author": "Alice", "size": 1, "score": 0.5, "ocr": True, "owner": "bob"}
