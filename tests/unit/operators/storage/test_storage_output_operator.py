# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for StorageOutputOperator — processed_content mode."""

import json as _json
import sys
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

# box_sdk_gen is an optional dependency not installed in the test environment.
# Pre-mock it before any docpipe import triggers the box adapter import chain.
if "box_sdk_gen" not in sys.modules:
    _box_mock = MagicMock()
    sys.modules["box_sdk_gen"] = _box_mock
    for _attr in (
        "BoxClient",
        "BoxJWTAuth",
        "JWTConfig",
        "CreateFolderParent",
        "UploadFileAttributes",
        "UploadFileAttributesParentField",
    ):
        sys.modules[f"box_sdk_gen.{_attr}"] = MagicMock()

from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.storage_output_operator import StorageOutputOperator, _extract_source_relative_path


def _make_table(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def _base_config(tmp_path, overrides: dict | None = None) -> dict:
    config = {
        "name": "storage_output",
        "id": "node_1",
        "mode": "processed_content",
        "destination_config": {
            "provider": "filesystem",
            "provider_config": {
                "root_path": str(tmp_path),
                "create_dirs": True,
                "overwrite_existing": True,
            },
            "credentials": {},
        },
        "output_format": {
            "content_format": "md",
        },
        "output_structure": {
            "path_template": "{doc_id}.{ext}",
        },
    }
    if overrides:
        config.update(overrides)
    return config


@pytest.mark.parametrize("credentials_in_provider_config", [True, False])
def test_s3_destination_accepts_ui_and_legacy_credentials(credentials_in_provider_config):
    provider_config = {"bucket": "bucket", "key_prefix": "exports/"}
    credentials = {}
    keys = {"access_key": "key", "secret_key": "secret"}  # pragma: allowlist secret
    if credentials_in_provider_config:
        provider_config.update(keys)
    else:
        credentials.update(keys)

    op = StorageOutputOperator(
        {
            "mode": "processed_content",
            "destination_config": {
                "provider": "s3",
                "provider_config": provider_config,
                "credentials": credentials,
            },
        }
    )
    table = _make_table([{"id": "1", "name": "doc.md", "content": "text"}])
    result = WriteResult(doc_id="1", doc_name="doc.md", success=True)

    with (
        patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter.S3DestinationAdapter.validate_destination",
            return_value=None,
        ),
        patch.object(StorageOutputOperator, "_write_row", return_value=result),
    ):
        output, _ = op.transform(table)

    assert output[0].column("write_status").to_pylist() == ["success"]


class TestStorageOutputOperatorValidation:
    def test_missing_mode_raises_on_transform(self, tmp_path):
        config = _base_config(tmp_path)
        config.pop("mode")
        op = StorageOutputOperator(config)
        with pytest.raises(ValueError, match="mode"):
            op.transform(
                _make_table(
                    [{"id": "1", "name": "a", "content": "x", "path": "/p", "metadata": "{}", "document_format": "pdf"}]
                )
            )

    def test_missing_destination_config_raises_on_transform(self, tmp_path):
        config = _base_config(tmp_path)
        config.pop("destination_config")
        op = StorageOutputOperator(config)
        with pytest.raises(ValueError, match="destination_config"):
            op.transform(
                _make_table(
                    [{"id": "1", "name": "a", "content": "x", "path": "/p", "metadata": "{}", "document_format": "pdf"}]
                )
            )

    def test_invalid_adapter_config_marks_docs_failed_and_flow_continues(self, tmp_path):
        """A bad adapter config (e.g. missing S3 prefix) must NOT raise — it marks all docs
        failed and returns a valid output table so downstream operators are unaffected."""
        config = _base_config(tmp_path)
        config["destination_config"] = {
            "provider": "filesystem",
            "provider_config": {},  # missing root_path — causes KeyError in build_config
            "credentials": {},
        }
        op = StorageOutputOperator(config)
        table = _make_table(
            [
                {"id": "1", "name": "doc1.md", "content": "x", "path": "/p", "metadata": "{}", "document_format": "md"},
                {"id": "2", "name": "doc2.md", "content": "y", "path": "/q", "metadata": "{}", "document_format": "md"},
            ]
        )
        # Must not raise
        output_tables, metadata = op.transform(table)

        assert output_tables
        assert output_tables[0].num_rows == 2
        write_statuses = output_tables[0].column("write_status").to_pylist()
        assert all(s == "failed" for s in write_statuses)
        # Downstream flow continues — metadata is returned, not an exception
        assert metadata is not None

    def test_validate_method_reports_missing_content_column(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        errors: list[str] = []
        warnings: list[str] = []
        op.validate(errors, warnings, available_features=["id", "name", "path", "metadata", "document_format"])
        assert any("content" in e for e in errors)

    def test_get_metadata_declares_sensitive_credentials(self):
        metadata = StorageOutputOperator.get_metadata()
        attributes = metadata.get("attributes", {})
        dest_cfg = attributes.get("destination_config", {})
        properties = dest_cfg.get("properties", {})
        credentials = properties.get("credentials", {})
        assert credentials.get("sensitive") is True


class TestStorageOutputOperatorProcessedContent:
    def test_writes_md_files_to_disk(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "file1.pdf",
                    "content": "# Hello",
                    "path": "/src/file1.pdf",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
                {
                    "id": "doc2",
                    "name": "file2.pdf",
                    "content": "# World",
                    "path": "/src/file2.pdf",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        _output_tables, _metadata = op.transform(table)

        assert (tmp_path / "doc1.content.md").exists()
        assert (tmp_path / "doc2.content.md").exists()
        assert (tmp_path / "doc1.content.md").read_text() == "# Hello"

    def test_output_table_has_write_result_columns(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "file1.pdf",
                    "content": "Hello",
                    "path": "/src/file1.pdf",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        output_tables, _ = op.transform(table)
        out = output_tables[0]

        assert "write_status" in out.schema.names
        assert "destination_path" in out.schema.names
        assert "bytes_written" in out.schema.names
        assert "write_error" in out.schema.names

    def test_output_table_passes_through_input_columns(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "file1.pdf",
                    "content": "Hello",
                    "path": "/src/file1.pdf",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        output_tables, _ = op.transform(table)
        out = output_tables[0]

        for col in ["id", "name", "content", "path", "metadata", "document_format"]:
            assert col in out.schema.names

    def test_metadata_counts_are_correct(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "f1.pdf",
                    "content": "A",
                    "path": "/p1",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
                {
                    "id": "doc2",
                    "name": "f2.pdf",
                    "content": "B",
                    "path": "/p2",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        _, metadata = op.transform(table)

        assert metadata["documents_in_scope"] == 2
        assert metadata["processed_docs"] == 2
        assert metadata["failed_docs_count"] == 0

    def test_write_failure_recorded_in_output_and_metadata(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "f1.pdf",
                    "content": "A",
                    "path": "/p",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        with patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter.FilesystemDestinationAdapter.write_document",
            side_effect=PermissionError("denied"),
        ):
            output_tables, metadata = op.transform(table)

        out = output_tables[0]
        assert out["write_status"][0].as_py() == "failed"
        assert metadata["failed_docs_count"] == 1
        assert metadata["processed_docs"] == 0

    def test_writes_txt_format(self, tmp_path):
        config = _base_config(tmp_path, {"output_format": {"content_format": "txt"}})
        op = StorageOutputOperator(config)
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "f.pdf",
                    "content": "plain text",
                    "path": "/p",
                    "metadata": "{}",
                    "document_format": "pdf",
                },
            ]
        )

        op.transform(table)

        assert (tmp_path / "doc1.content.txt").exists()

    def test_writes_json_format(self, tmp_path):
        config = _base_config(tmp_path, {"output_format": {"content_format": "json"}})
        op = StorageOutputOperator(config)
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "f.pdf",
                    "content": "some content",
                    "path": "/p",
                    "metadata": '{"key": "val"}',
                    "document_format": "pdf",
                },
            ]
        )

        op.transform(table)

        import json

        written = json.loads((tmp_path / "doc1.content.json").read_text())
        assert written["content"] == "some content"

    def test_empty_table_returns_empty_output(self, tmp_path):
        op = StorageOutputOperator(_base_config(tmp_path))
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("name", pa.string()),
                ("content", pa.string()),
                ("path", pa.string()),
                ("metadata", pa.string()),
                ("document_format", pa.string()),
            ]
        )
        table = pa.table({col: [] for col in schema.names}, schema=schema)

        output_tables, metadata = op.transform(table)

        assert output_tables[0].num_rows == 0
        assert metadata["documents_in_scope"] == 0

    def test_empty_content_is_skipped_not_uploaded(self, tmp_path):
        """Documents with no extracted content must be skipped, not written as 0-byte files.

        This covers the case where extraction is skipped upstream (e.g. unsupported
        file extension) so the content column is absent or empty.
        """
        op = StorageOutputOperator(_base_config(tmp_path))
        table = _make_table(
            [
                {
                    "id": "doc1",
                    "name": "https://app.box.com/file/123",
                    "content": "",  # extraction was skipped — no content
                    "path": "https://app.box.com/file/123",
                    "metadata": '{"box_name": "TR-INV_001.pdf"}',
                    "document_format": "pdf",
                },
            ]
        )

        output_tables, metadata = op.transform(table)
        out = output_tables[0]

        # No file should have been written to disk
        assert list(tmp_path.iterdir()) == []

        # Row must be counted as skipped, not processed or failed
        assert metadata["processed_docs"] == 0
        assert metadata["skipped_docs_count"] == 1
        assert metadata["failed_docs_count"] == 0

        # write_status column must reflect "skipped"
        assert out["write_status"][0].as_py() == "skipped"


# ---------------------------------------------------------------------------
# Tests for refetch_original mode
# ---------------------------------------------------------------------------


def _refetch_config(tmp_path, overrides: dict | None = None) -> dict:
    # ingest_source is at the top level, simulating what the orchestrator merges
    # from the upstream ingest_source node into the operator config at runtime.
    config = {
        "name": "storage_output",
        "id": "node_1",
        "mode": "refetch_original",
        "ingest_source": {
            "provider": "filesystem",
            "connection_params": {"root_path": "/src"},
            "credentials": {},
        },
        "destination_config": {
            "provider": "filesystem",
            "provider_config": {
                "root_path": str(tmp_path),
                "create_dirs": True,
                "overwrite_existing": True,
            },
            "credentials": {},
        },
        "output_structure": {
            "path_template": "{doc_id}.{ext}",
        },
    }
    if overrides:
        config.update(overrides)
    return config


def _comprehensive_config(tmp_path, overrides: dict | None = None) -> dict:
    # ingest_source is at the top level, simulating what the orchestrator merges
    # from the upstream ingest_source node into the operator config at runtime.
    config = {
        "name": "storage_output",
        "id": "node_1",
        "mode": "comprehensive_export",
        "ingest_source": {
            "provider": "filesystem",
            "connection_params": {"root_path": "/src"},
            "credentials": {},
        },
        "destination_config": {
            "provider": "filesystem",
            "provider_config": {
                "root_path": str(tmp_path),
                "create_dirs": True,
                "overwrite_existing": True,
            },
            "credentials": {},
        },
        "output_format": {
            "content_format": "md",
            "include_metadata_sidecar": True,
        },
        "output_structure": {
            "path_template": "{doc_id}/{name}.{ext}",
        },
    }
    if overrides:
        config.update(overrides)
    return config


_FULL_ROW = {
    "id": "doc1",
    "name": "report.pdf",
    "content": "# Extracted",
    "path": "file:///src/report.pdf",
    "metadata": '{"author": "Alice"}',
    "document_format": "pdf",
}


class TestStorageOutputOperatorRefetchOriginal:
    def test_writes_binary_to_disk(self, tmp_path):
        op = StorageOutputOperator(_refetch_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"%PDF binary"
            _output_tables, _metadata = op.transform(table)

        assert (tmp_path / "doc1.pdf").exists()
        assert (tmp_path / "doc1.pdf").read_bytes() == b"%PDF binary"

    def test_fetch_binary_content_called_with_path(self, tmp_path):
        config = _refetch_config(tmp_path)
        op = StorageOutputOperator(config)
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"data"
            op.transform(table)

        mock_fetch.assert_called_once_with(
            doc_metadata={"path": "file:///src/report.pdf", "name": "report.pdf"},
            global_config=config,
        )

    def test_failed_fetch_recorded_as_failure(self, tmp_path):
        op = StorageOutputOperator(_refetch_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = None  # source not found
            output_tables, metadata = op.transform(table)

        out = output_tables[0]
        assert out["write_status"][0].as_py() == "failed"
        assert metadata["failed_docs_count"] == 1

    def test_output_table_has_write_result_columns(self, tmp_path):
        op = StorageOutputOperator(_refetch_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"data"
            output_tables, _ = op.transform(table)

        out = output_tables[0]
        for col in ["write_status", "destination_path", "bytes_written", "write_error"]:
            assert col in out.schema.names

    def test_metadata_counts_correct(self, tmp_path):
        op = StorageOutputOperator(_refetch_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"data"
            _, metadata = op.transform(table)

        assert metadata["processed_docs"] == 1
        assert metadata["failed_docs_count"] == 0


class TestStorageOutputOperatorComprehensiveExport:
    def test_writes_three_files_per_document(self, tmp_path):
        op = StorageOutputOperator(_comprehensive_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"%PDF"
            op.transform(table)

        # original binary
        assert (tmp_path / "doc1" / "report.pdf").exists()
        # extracted content
        assert (tmp_path / "doc1" / "report.content.md").exists()
        # metadata sidecar
        assert (tmp_path / "doc1" / "report.meta.json").exists()

    def test_sidecar_not_written_when_disabled(self, tmp_path):
        config = _comprehensive_config(
            tmp_path,
            {"output_format": {"content_format": "md", "include_metadata_sidecar": False}},
        )
        op = StorageOutputOperator(config)
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"%PDF"
            op.transform(table)

        assert not (tmp_path / "doc1" / "report.meta.json").exists()
        assert (tmp_path / "doc1" / "report.pdf").exists()
        assert (tmp_path / "doc1" / "report.content.md").exists()

    def test_sidecar_contains_metadata(self, tmp_path):
        op = StorageOutputOperator(_comprehensive_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"%PDF"
            op.transform(table)

        sidecar = _json.loads((tmp_path / "doc1" / "report.meta.json").read_text())
        assert sidecar["id"] == "doc1"
        assert sidecar["name"] == "report.pdf"
        assert "author" in sidecar["metadata"]

    def test_original_binary_content_is_verbatim(self, tmp_path):
        op = StorageOutputOperator(_comprehensive_config(tmp_path))
        table = _make_table([_FULL_ROW])
        original_bytes = b"%PDF-1.4 binary content"

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = original_bytes
            op.transform(table)

        assert (tmp_path / "doc1" / "report.pdf").read_bytes() == original_bytes

    def test_metadata_counts_correct(self, tmp_path):
        op = StorageOutputOperator(_comprehensive_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"data"
            _, metadata = op.transform(table)

        assert metadata["processed_docs"] == 1
        assert metadata["failed_docs_count"] == 0

    def test_failed_fetch_recorded_as_failure(self, tmp_path):
        op = StorageOutputOperator(_comprehensive_config(tmp_path))
        table = _make_table([_FULL_ROW])

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = None
            output_tables, metadata = op.transform(table)

        out = output_tables[0]
        assert out["write_status"][0].as_py() == "failed"
        assert metadata["failed_docs_count"] == 1


# ---------------------------------------------------------------------------
# Tests for _extract_source_relative_path — S3 hierarchical path derivation
# ---------------------------------------------------------------------------


class TestExtractSourceRelativePath:
    """Unit tests for the module-level helper that resolves relative paths."""

    def test_returns_explicit_relative_path_when_present(self):
        row = {"metadata": _json.dumps({"relative_path": "sub01/report.pdf"})}
        assert _extract_source_relative_path(row) == "sub01/report.pdf"

    def test_filesystem_relative_path_takes_precedence_over_key(self):
        """When both relative_path and key are set, relative_path wins (filesystem adapter wins)."""
        row = {"metadata": _json.dumps({"relative_path": "sub01/report.pdf", "key": "prefix/sub01/report.pdf"})}
        assert _extract_source_relative_path(row, source_prefix="prefix/") == "sub01/report.pdf"

    def test_s3_key_stripped_of_prefix_with_trailing_slash(self):
        row = {"metadata": _json.dumps({"key": "vt_workspace/source_files/sub01/1kb_file.txt"})}
        result = _extract_source_relative_path(row, source_prefix="vt_workspace/source_files/")
        assert result == "sub01/1kb_file.txt"

    def test_s3_key_stripped_of_prefix_leading_slash_normalised(self):
        """Both key and prefix may carry a leading slash — normalisation ensures they match."""
        row = {"metadata": _json.dumps({"key": "vt_workspace/source_files/sub01/hello.txt"})}
        result = _extract_source_relative_path(row, source_prefix="/vt_workspace/source_files/")
        assert result == "sub01/hello.txt"

    def test_s3_key_file_at_prefix_root_returns_filename_only(self):
        """A file directly under the source prefix has no sub-directory component."""
        row = {"metadata": _json.dumps({"key": "vt_workspace/source_files/TR-INV_017.pdf"})}
        result = _extract_source_relative_path(row, source_prefix="vt_workspace/source_files/")
        assert result == "TR-INV_017.pdf"

    def test_s3_key_with_no_prefix_match_returns_none(self):
        """When the key doesn't start with the prefix, return None rather than a wrong path."""
        row = {"metadata": _json.dumps({"key": "other_prefix/file.pdf"})}
        result = _extract_source_relative_path(row, source_prefix="vt_workspace/source_files/")
        assert result is None

    def test_no_metadata_returns_none(self):
        assert _extract_source_relative_path({}) is None

    def test_empty_metadata_returns_none(self):
        assert _extract_source_relative_path({"metadata": "{}"}) is None

    def test_s3_key_present_but_no_prefix_returns_none(self):
        """Without a source_prefix there is no way to compute a relative path from the key."""
        row = {"metadata": _json.dumps({"key": "vt_workspace/source_files/sub01/file.pdf"})}
        assert _extract_source_relative_path(row) is None

    def test_malformed_metadata_returns_none(self):
        assert _extract_source_relative_path({"metadata": "not-json"}) is None


class TestStorageOutputOperatorS3Hierarchical:
    """Integration-style tests verifying S3 hierarchical output structure via the filesystem adapter."""

    def _s3_refetch_config(self, tmp_path) -> dict:
        return {
            "name": "storage_output",
            "id": "node_s3",
            "mode": "refetch_original",
            "ingest_source": {
                "provider": "s3",
                "provider_config": {
                    "bucket": "my-bucket",
                    "prefix": "vt_workspace/source_files/",
                    "region": "us-east-1",
                },
            },
            "destination_config": {
                "provider": "filesystem",
                "provider_config": {
                    "root_path": str(tmp_path),
                    "create_dirs": True,
                },
                "credentials": {},
            },
            "output_structure": {
                "type": "hierarchical",
                "overwrite_existing": True,
            },
        }

    def _s3_row(self, key: str, name: str) -> dict:
        return {
            "id": key,
            "name": name,
            "content": "",
            "path": f"s3://my-bucket/{key}",
            "metadata": _json.dumps({"bucket": "my-bucket", "key": key}),
            "document_format": name.rsplit(".", 1)[-1] if "." in name else "",
        }

    def test_subdirectory_preserved_in_hierarchical_mode(self, tmp_path):
        from unittest.mock import patch

        config = self._s3_refetch_config(tmp_path)
        op = StorageOutputOperator(config)
        row = self._s3_row("vt_workspace/source_files/sub01/1kb_file.txt", "1kb_file.txt")

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"hello"
            op.transform(_make_table([row]))

        assert (tmp_path / "sub01" / "1kb_file.txt").exists()

    def test_root_level_file_has_no_subdirectory(self, tmp_path):
        from unittest.mock import patch

        config = self._s3_refetch_config(tmp_path)
        op = StorageOutputOperator(config)
        row = self._s3_row("vt_workspace/source_files/TR-INV_017.pdf", "TR-INV_017.pdf")

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"%PDF"
            op.transform(_make_table([row]))

        assert (tmp_path / "TR-INV_017.pdf").exists()
        assert not (tmp_path / "vt_workspace").exists()

    def test_multiple_nesting_levels_preserved(self, tmp_path):
        from unittest.mock import patch

        config = self._s3_refetch_config(tmp_path)
        op = StorageOutputOperator(config)
        row = self._s3_row("vt_workspace/source_files/a/b/c/deep.pdf", "deep.pdf")

        with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content") as mock_fetch:
            mock_fetch.return_value = b"data"
            op.transform(_make_table([row]))

        assert (tmp_path / "a" / "b" / "c" / "deep.pdf").exists()


class TestStorageOutputOperatorMetadata:
    """Tests for StorageOutputOperator.get_metadata() attribute exposure."""

    def test_get_metadata_returns_attributes_key(self):
        meta = StorageOutputOperator.get_metadata()
        from docpipe.core.constants.operator_constants import OperatorConstants

        assert OperatorConstants.Config.ATTRIBUTES in meta
        assert meta[OperatorConstants.Config.ATTRIBUTES]

    def test_get_metadata_top_level_attribute_keys(self):
        from docpipe.core.constants.operator_constants import OperatorConstants

        attrs = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]
        assert "mode" in attrs
        assert "destination_config" in attrs
        assert "output_format" in attrs
        assert "output_structure" in attrs

    def test_mode_attribute_is_required_string_with_valid_values(self):
        from docpipe.core.constants.constants import AttributeDataTypes
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.core.operators.storage.domain.models import WriteMode

        mode = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["mode"]
        assert mode[OperatorConstants.Config.REQUIRED] is True
        assert mode[OperatorConstants.Misc.TYPE] == AttributeDataTypes.STRING
        assert set(mode[OperatorConstants.Config.VALID_VALUES]) == {m.value for m in WriteMode}

    def test_destination_config_attribute_is_required_json(self):
        from docpipe.core.constants.constants import AttributeDataTypes
        from docpipe.core.constants.operator_constants import OperatorConstants

        dest = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["destination_config"]
        assert dest[OperatorConstants.Config.REQUIRED] is True
        assert dest[OperatorConstants.Misc.TYPE] == AttributeDataTypes.JSON

    def test_destination_config_properties_has_provider_and_provider_config(self):
        from docpipe.core.constants.operator_constants import OperatorConstants

        props = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["destination_config"][
            OperatorConstants.Config.PROPERTIES
        ]
        assert OperatorConstants.Config.PROVIDER in props
        assert OperatorConstants.Config.PROVIDER_CONFIG in props
        assert OperatorConstants.Config.CREDENTIALS in props

    def test_destination_provider_valid_values_includes_all_providers(self):
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
            DestinationAdapterFactory,
        )

        valid_values = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["destination_config"][
            OperatorConstants.Config.PROPERTIES
        ][OperatorConstants.Config.PROVIDER][OperatorConstants.Config.VALID_VALUES]
        assert set(valid_values) == set(DestinationAdapterFactory.get_registered_names())

    def test_destination_provider_config_has_non_empty_providers_dict(self):
        from docpipe.core.constants.operator_constants import OperatorConstants

        provider_config = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES][
            "destination_config"
        ][OperatorConstants.Config.PROPERTIES][OperatorConstants.Config.PROVIDER_CONFIG]
        providers = provider_config[OperatorConstants.Config.PROVIDERS]
        assert isinstance(providers, dict)
        assert len(providers) > 0

    def test_output_format_attribute_is_optional_json_with_correct_properties(self):
        from docpipe.core.constants.constants import AttributeDataTypes
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.core.operators.storage.domain.models import ContentFormat

        fmt = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["output_format"]
        assert fmt.get(OperatorConstants.Config.REQUIRED) is not True
        assert fmt[OperatorConstants.Misc.TYPE] == AttributeDataTypes.JSON
        props = fmt[OperatorConstants.Config.PROPERTIES]
        assert "content_format" in props
        assert set(props["content_format"][OperatorConstants.Config.VALID_VALUES]) == {f.value for f in ContentFormat}
        assert "include_metadata_sidecar" in props
        assert props["include_metadata_sidecar"][OperatorConstants.Config.DEFAULT] is False

    def test_output_structure_attribute_is_optional_json_with_correct_properties(self):
        from docpipe.core.constants.constants import AttributeDataTypes
        from docpipe.core.constants.operator_constants import OperatorConstants

        struct = StorageOutputOperator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]["output_structure"]
        assert struct.get(OperatorConstants.Config.REQUIRED) is not True
        assert struct[OperatorConstants.Misc.TYPE] == AttributeDataTypes.JSON
        props = struct[OperatorConstants.Config.PROPERTIES]
        assert "type" in props
        assert set(props["type"][OperatorConstants.Config.VALID_VALUES]) == {"flat", "hierarchical"}
        assert "path_template" in props
        assert "overwrite_existing" in props
        assert props["overwrite_existing"][OperatorConstants.Config.DEFAULT] is True


class TestStorageOutputOperatorWriteErrorColumn:
    """The ``write_error`` column is persisted with the table, so registered secret values never reach it."""

    def teardown_method(self):
        from docpipe.integrations.secrets.registry import get_registry

        get_registry().clear_all()

    def test_write_error_column_is_scrubbed(self):
        from docpipe.integrations.secrets.registry import register_secret

        marker = "credentials-path-marker-7f3a/token.json"  # pragma: allowlist secret
        register_secret(value=marker)
        results = [
            WriteResult(
                doc_id="a",
                doc_name="a.txt",
                success=False,
                error_message=f"Failed to load OAuth credentials: Credentials file not found: {marker}",
            ),
            WriteResult(doc_id="b", doc_name="b.txt", success=True),
        ]

        out = StorageOutputOperator._build_output_table(_make_table([_FULL_ROW, _FULL_ROW]), results)

        errors = out["write_error"].to_pylist()
        assert marker not in (errors[0] or "")
        assert "Credentials file not found" in errors[0]
        assert errors[1] is None
