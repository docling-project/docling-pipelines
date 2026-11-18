#!/usr/bin/env python3

import asyncio
import gzip
import io
import os
import tarfile
import zipfile
from typing import Literal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.adapter import (
    FilesystemSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.config import (
    FilesystemSourceConfig,
)


async def collect_async(async_gen):
    return [item async for item in async_gen]


def _write_zip(path, *, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _write_tar(path, *, entries: dict[str, bytes], mode: Literal["w", "w:gz"]) -> None:
    with tarfile.open(path, mode=mode) as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


class TestFilesystemSourceConfig:
    def test_accepts_single_path_in_list(self, tmp_path):
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=True,
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        assert config.paths == [str(tmp_path)]

    def test_accepts_multiple_paths(self, tmp_path):
        second = tmp_path / "sub"
        second.mkdir()
        config = FilesystemSourceConfig(
            paths=[str(tmp_path), str(second)],
            recursive=True,
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        assert config.paths == [str(tmp_path), str(second)]

    def test_rejects_missing_paths(self):
        with pytest.raises(ValidationError, match="Root path does not exist"):
            FilesystemSourceConfig(
                paths=["/definitely/missing/path"],
                recursive=True,
                max_file_size_mb=None,
                follow_symlinks=False,
            )

    def test_rejects_empty_list(self, tmp_path):
        with pytest.raises(ValidationError, match="at least one path"):
            FilesystemSourceConfig(
                paths=[],
                recursive=True,
                max_file_size_mb=None,
                follow_symlinks=False,
            )

    def test_accepts_file_path(self, tmp_path):
        """Test that config accepts file paths (single file mode)."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test content")

        config = FilesystemSourceConfig(
            paths=[str(file_path)],
            recursive=True,
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        assert config.paths == [str(file_path.resolve())]

    def test_normalizes_extensions_and_validates_size(self, tmp_path):
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=True,
            file_extensions=["txt", ".pdf"],
            max_file_size_mb=5,
            follow_symlinks=False,
        )
        assert config.file_extensions == [".txt", ".pdf"]
        assert config.max_file_size_mb == 5

    def test_rejects_non_positive_max_file_size(self, tmp_path):
        with pytest.raises(ValidationError, match="Input should be greater than or equal to 1"):
            FilesystemSourceConfig(
                paths=[str(tmp_path)],
                recursive=True,
                max_file_size_mb=0,
                follow_symlinks=False,
            )


class TestFilesystemSourceAdapter:
    def test_build_config_from_operator_params(self, tmp_path):
        second = tmp_path / "sub"
        second.mkdir()
        adapter = FilesystemSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "paths": [str(tmp_path), str(second)],
                "recursive": False,
                "exclude_patterns": ["*.tmp"],
                "follow_symlinks": True,
                "max_file_size_mb": 3,
            },
            included_extensions=["txt"],
        )
        config_data = config.model_dump()

        assert type(config).__name__ == "FilesystemSourceConfig"
        assert config_data["paths"] == [str(tmp_path), str(second)]
        assert config_data["recursive"] is False
        assert config_data["file_extensions"] == [".txt"]
        assert config_data["exclude_patterns"] == ["*.tmp"]
        assert config_data["follow_symlinks"] is True
        assert config_data["max_file_size_mb"] == 3

    def test_walk_directory_non_recursive_and_filters(self, tmp_path):
        included = tmp_path / "keep.txt"
        included.write_text("hello")
        excluded = tmp_path / "skip.tmp"
        excluded.write_text("tmp")
        nested_dir = tmp_path / "nested"
        nested_dir.mkdir()
        (nested_dir / "nested.txt").write_text("nested")

        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=False,
            file_extensions=[".txt"],
            exclude_patterns=["*.tmp"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()

        result = list(adapter._walk_directory(tmp_path, config))
        assert result == [included]

    def test_should_include_file_and_exclusion(self, tmp_path):
        adapter = FilesystemSourceAdapter()
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=True,
            file_extensions=[".txt"],
            exclude_patterns=["*ignore*"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        assert adapter._should_include_file(tmp_path / "ok.txt", config) is True
        assert adapter._should_include_file(tmp_path / "ok.pdf", config) is False
        assert adapter._should_include_file(tmp_path / "ignore.txt", config) is False
        assert adapter._is_excluded(str(tmp_path / "ignore.txt"), config) is True
        assert adapter._is_excluded(str(tmp_path / "ok.txt"), config) is False

    def test_fetch_documents_skips_large_files(self, tmp_path):
        """Test that large files are skipped in directory mode."""
        small = tmp_path / "small.txt"
        small.write_text("hello")
        large = tmp_path / "large.txt"
        large.write_text("x" * 10)

        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=False,
            file_extensions=[".txt"],
            max_file_size_mb=1,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()

        # Store original stat results
        tmp_path_stat = tmp_path.stat()
        large_stat = large.stat()
        small_stat = small.stat()

        def fake_stat(self):
            """Return appropriate stat based on path."""
            path_str = str(self)
            if path_str == str(tmp_path):
                return tmp_path_stat
            if path_str == str(large):
                # Return large file stat (2MB) — should be skipped
                return os.stat_result(
                    (
                        large_stat.st_mode,
                        large_stat.st_ino,
                        large_stat.st_dev,
                        large_stat.st_nlink,
                        large_stat.st_uid,
                        large_stat.st_gid,
                        2 * 1024 * 1024,  # 2MB size
                        int(large_stat.st_atime),
                        int(large_stat.st_mtime),
                        int(large_stat.st_ctime),
                    )
                )
            if path_str == str(small):
                return small_stat
            return type(self).stat(self)

        with (
            patch.object(
                FilesystemSourceAdapter,
                "_walk_directory",
                return_value=iter([small, large]),
            ),
            patch(
                "pathlib.Path.stat",
                fake_stat,
            ),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        # small.txt yielded (lazy, no read), large.txt skipped due to size limit
        assert len(docs) == 1
        assert docs[0].name == "small.txt"
        assert docs[0].content == b""

    def test_fetch_documents_returns_document(self, tmp_path):
        file_path = tmp_path / "doc.txt"
        file_path.write_text("hello world")
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=False,
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()

        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.name == "doc.txt"
        assert doc.content == b""  # lazy loading: content empty until fetch_binary_content() called
        assert doc.extension == ".txt"
        assert doc.metadata["relative_path"] == "doc.txt"
        assert doc.metadata["archive_depth"] == 0

    def test_fetch_documents_expands_zip_lazily_and_preserves_nested_archive(self, tmp_path, monkeypatch):
        inner_bytes = io.BytesIO()
        with zipfile.ZipFile(inner_bytes, mode="w") as nested:
            nested.writestr("inside.txt", b"nested")

        archive_path = tmp_path / "bundle #1.zip"
        _write_zip(
            archive_path,
            entries={
                "folder/report.txt": b"report",
                "nested.zip": inner_bytes.getvalue(),
            },
        )
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=False,
            file_extensions=[".txt", ".zip"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert [doc.name for doc in docs] == ["folder/report.txt", "nested.zip"]
        assert all(doc.content == b"" for doc in docs)
        assert all(doc.metadata["archive_depth"] == 1 for doc in docs)
        assert all(doc.metadata["source_archive"] == str(archive_path.absolute()) for doc in docs)
        assert docs[0].metadata["archive_entry"] == "folder/report.txt"
        assert docs[0].source_url == docs[0].metadata["source_id"]
        assert "%23" in docs[0].source_url

        def fail_if_archive_is_materialized(_path):
            raise AssertionError("ZIP archives must not be loaded into memory in full")

        monkeypatch.setattr(type(archive_path), "read_bytes", fail_if_archive_is_materialized)
        assert adapter.fetch_binary_content(source_id=docs[0].source_url, provider_config={}) == b"report"
        assert adapter.fetch_binary_content(source_id=docs[1].source_url, provider_config={}) == inner_bytes.getvalue()

    def test_archive_entry_is_read_without_extracting_its_path(self, tmp_path):
        outside_path = tmp_path.parent / f"{tmp_path.name}-outside.txt"
        archive_path = tmp_path / "bundle.zip"
        _write_zip(archive_path, entries={f"../{outside_path.name}": b"content"})
        config = FilesystemSourceConfig(
            paths=[str(archive_path)],
            recursive=False,
            file_extensions=[".txt"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert adapter.fetch_binary_content(source_id=docs[0].source_url, provider_config={}) == b"content"
        assert not outside_path.exists()

    @pytest.mark.parametrize(
        ("suffix", "mode"),
        [(".tar", "w"), (".tar.gz", "w:gz"), (".tgz", "w:gz")],
    )
    def test_fetch_documents_expands_tar_formats(self, tmp_path, monkeypatch, suffix, mode):
        archive_path = tmp_path / f"bundle{suffix}"
        _write_tar(archive_path, entries={"folder/report.txt": b"report"}, mode=mode)
        config = FilesystemSourceConfig(
            paths=[str(archive_path)],
            recursive=False,
            file_extensions=[".txt"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].extension == ".txt"

        def fail_if_archive_is_materialized(_path):
            raise AssertionError("TAR archives must not be loaded into memory in full")

        monkeypatch.setattr(type(archive_path), "read_bytes", fail_if_archive_is_materialized)
        assert adapter.fetch_binary_content(source_id=docs[0].source_url, provider_config={}) == b"report"

    def test_fetch_documents_expands_single_stream_gzip(self, tmp_path, monkeypatch):
        archive_path = tmp_path / "notes.txt.gz"
        with gzip.open(archive_path, mode="wb") as archive:
            archive.write(b"notes")
        config = FilesystemSourceConfig(
            paths=[str(archive_path)],
            recursive=False,
            file_extensions=[".txt"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        assert docs[0].name == "notes.txt"
        assert docs[0].size is None

        def fail_if_archive_is_materialized(_path):
            raise AssertionError("GZIP archives must not be loaded into memory in full")

        monkeypatch.setattr(type(archive_path), "read_bytes", fail_if_archive_is_materialized)
        assert adapter.fetch_binary_content(source_id=docs[0].source_url, provider_config={}) == b"notes"

    def test_fetch_binary_content_reads_file_uri(self, tmp_path):
        file_path = tmp_path / "doc with spaces.txt"
        file_path.write_text("hello file uri")

        adapter = FilesystemSourceAdapter()
        content = adapter.fetch_binary_content(
            source_id=file_path.resolve().as_uri(),
            provider_config={"paths": [str(tmp_path)]},
        )

        assert content == b"hello file uri"

    def test_test_connection_variants(self, tmp_path):
        adapter = FilesystemSourceAdapter()
        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=True,
            max_file_size_mb=None,
            follow_symlinks=False,
        )

        success, message = asyncio.run(adapter.test_connection(config))
        assert success is True
        assert "Successfully connected" in message

        with patch("pathlib.Path.exists", return_value=False):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Path does not exist" in message

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=False),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Path is not a file" in message

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("os.access", return_value=False),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Path is not readable" in message

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("os.access", return_value=True),
            patch("pathlib.Path.iterdir", side_effect=PermissionError),
        ):
            success, message = asyncio.run(adapter.test_connection(config))
            assert success is False
            assert "Permission denied" in message

    def test_build_config_with_provider_config(self, tmp_path):
        """build_config_from_operator_params accepts the unified provider_config key."""
        adapter = FilesystemSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "paths": [str(tmp_path)],
                "recursive": False,
                "exclude_patterns": ["*.log"],
                "follow_symlinks": False,
                "max_file_size_mb": 10,
            },
            included_extensions=["pdf"],
        )
        assert config.paths == [str(tmp_path)]
        assert config.recursive is False
        assert config.file_extensions == [".pdf"]
        assert config.max_file_size_mb == 10

    def test_fetch_documents_single_file_mode(self, tmp_path):
        """Single file path yields exactly one document with correct metadata."""
        import asyncio

        file_path = tmp_path / "single.pdf"
        file_path.write_text("content")
        config = FilesystemSourceConfig(
            paths=[str(file_path)],
            recursive=False,
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.name == "single.pdf"
        assert doc.content == b""
        assert doc.extension == ".pdf"
        assert "absolute_path" in doc.metadata
        assert "parent_directory" in doc.metadata
        assert "relative_path" not in doc.metadata  # single-file mode, no relative_path

    def test_fetch_documents_single_file_skipped_if_too_large(self, tmp_path):
        """Single file exceeding max_file_size_mb is skipped (yields nothing)."""
        import asyncio
        import os
        from unittest.mock import patch

        file_path = tmp_path / "big.pdf"
        file_path.write_text("x")
        config = FilesystemSourceConfig(
            paths=[str(file_path)],
            recursive=False,
            max_file_size_mb=1,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()

        real_stat = file_path.stat()

        def fake_stat(self):
            if str(self) == str(file_path):
                return os.stat_result(
                    (
                        real_stat.st_mode,
                        real_stat.st_ino,
                        real_stat.st_dev,
                        real_stat.st_nlink,
                        real_stat.st_uid,
                        real_stat.st_gid,
                        2 * 1024 * 1024,  # 2 MB
                        int(real_stat.st_atime),
                        int(real_stat.st_mtime),
                        int(real_stat.st_ctime),
                    )
                )
            return type(self).stat(self)

        with patch("pathlib.Path.stat", fake_stat):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        assert docs == []

    def test_fetch_documents_walk_recursive(self, tmp_path):
        """Recursive walk yields files in nested subdirectories."""
        import asyncio

        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.txt").write_text("root")
        (sub / "nested.txt").write_text("nested")

        config = FilesystemSourceConfig(
            paths=[str(tmp_path)],
            recursive=True,
            file_extensions=[".txt"],
            max_file_size_mb=None,
            follow_symlinks=False,
        )
        adapter = FilesystemSourceAdapter()
        docs = asyncio.run(collect_async(adapter.fetch_documents(config)))

        names = {doc.name for doc in docs}
        assert "root.txt" in names
        assert "nested.txt" in names

    def test_fetch_binary_content_relative_path_resolved_via_base(self, tmp_path):
        """Relative source_id is resolved against the first path in provider_config."""
        file_path = tmp_path / "doc.txt"
        file_path.write_text("relative content")

        adapter = FilesystemSourceAdapter()
        content = adapter.fetch_binary_content(
            source_id="doc.txt",
            provider_config={"paths": [str(tmp_path)]},
        )
        assert content == b"relative content"

    def test_fetch_binary_content_returns_none_for_missing_file(self, tmp_path):
        """Returns None when the file does not exist."""
        adapter = FilesystemSourceAdapter()
        result = adapter.fetch_binary_content(
            source_id=str(tmp_path / "nonexistent.txt"),
            provider_config={},
        )
        assert result is None

    def test_fetch_binary_content_returns_none_for_directory(self, tmp_path):
        """Returns None when source_id points to a directory, not a file."""
        adapter = FilesystemSourceAdapter()
        result = adapter.fetch_binary_content(
            source_id=str(tmp_path),
            provider_config={},
        )
        assert result is None

    def test_fetch_binary_content_returns_none_on_permission_error(self, tmp_path):
        """Returns None when the file cannot be read due to a PermissionError."""
        from unittest.mock import patch

        file_path = tmp_path / "secret.txt"
        file_path.write_text("secret")

        adapter = FilesystemSourceAdapter()
        with patch("pathlib.Path.open", side_effect=PermissionError("denied")):
            result = adapter.fetch_binary_content(
                source_id=str(file_path),
                provider_config={},
            )
        assert result is None

    def test_fetch_binary_content_returns_none_on_unexpected_error(self, tmp_path):
        """Returns None on any unexpected exception during file reading."""
        from unittest.mock import patch

        file_path = tmp_path / "file.txt"
        file_path.write_text("data")

        adapter = FilesystemSourceAdapter()
        with patch("pathlib.Path.open", side_effect=OSError("disk error")):
            result = adapter.fetch_binary_content(
                source_id=str(file_path),
                provider_config={},
            )
        assert result is None

    def test_get_config_schema_returns_filesystem_config(self):
        """get_config_schema returns FilesystemSourceConfig."""
        adapter = FilesystemSourceAdapter()
        assert adapter.get_config_schema() is FilesystemSourceConfig
