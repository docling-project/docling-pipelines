"""Unit tests for LocalFileStore."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.custom_operators.file_store import LocalFileStore


class TestLocalFileStore:
    """Test suite for LocalFileStore implementation."""

    def test_store_and_get_operator_dir(self, *, tmp_path: Path) -> None:
        """Test storing operator file and retrieving directory."""
        store = LocalFileStore(base_dir=tmp_path)

        src_file = tmp_path / "my_op.py"
        src_file.write_text("# sample operator code", encoding="utf-8")

        operator_id = "test-operator-123"
        dir_path = store.store(operator_id=operator_id, operator_file_path=src_file)

        assert Path(dir_path).exists()
        assert (Path(dir_path) / "my_op.py").exists()

        retrieved_dir = store.get_operator_dir(operator_id=operator_id)
        assert retrieved_dir is not None
        assert retrieved_dir == Path(dir_path)

    def test_get_operator_dir_returns_none_when_missing(self, *, tmp_path: Path) -> None:
        """Test getting non-existent operator directory."""
        store = LocalFileStore(base_dir=tmp_path)
        assert store.get_operator_dir(operator_id="nonexistent") is None

    def test_delete_removes_operator_directory(self, *, tmp_path: Path) -> None:
        """Test deleting operator directory."""
        store = LocalFileStore(base_dir=tmp_path)

        src_file = tmp_path / "op.py"
        src_file.write_text("# code", encoding="utf-8")

        operator_id = "del-op-456"
        dir_path = store.store(operator_id=operator_id, operator_file_path=src_file)
        assert Path(dir_path).exists()

        store.delete(operator_id=operator_id)
        assert not Path(dir_path).exists()
        assert store.get_operator_dir(operator_id=operator_id) is None

    def test_get_directory_tree_skips_symlinks(self, *, tmp_path: Path) -> None:
        """Test directory tree generation ignores symlinks."""
        store = LocalFileStore(base_dir=tmp_path)

        # Create operator subfolder and file
        op_dir = tmp_path / "op-1"
        op_dir.mkdir()
        (op_dir / "op.py").write_text("print('hello')", encoding="utf-8")

        # Create symlink
        symlink_path = tmp_path / "symlink_dir"
        try:
            symlink_path.symlink_to(op_dir, target_is_directory=True)
        except OSError:
            pass  # Some platforms/environments disallow symlinks

        tree = store.get_directory_tree()
        child_names = [c["name"] for c in tree.get("children", [])]
        assert "op-1" in child_names
        assert "symlink_dir" not in child_names

    def test_store_cleans_up_tmp_and_reraises_on_write_failure(self, *, tmp_path: Path) -> None:
        """Tmp file is removed and exception propagates when write_bytes raises after creating it."""
        store = LocalFileStore(base_dir=tmp_path)
        src_file = tmp_path / "op.py"
        src_file.write_text("# code", encoding="utf-8")
        tmp_target = tmp_path / "err-op" / ".tmp_op.py"

        original_write_bytes = Path.write_bytes

        def write_then_raise(self, data):
            if self.name.startswith(".tmp_"):
                original_write_bytes(self, data)  # create the tmp file, then fail
                raise OSError("disk full")
            return original_write_bytes(self, data)

        with patch.object(Path, "write_bytes", write_then_raise):
            with pytest.raises(OSError, match="disk full"):
                store.store(operator_id="err-op", operator_file_path=src_file)

        assert not tmp_target.exists()

    def test_store_cleans_up_tmp_and_reraises_on_rename_failure(self, *, tmp_path: Path) -> None:
        """Tmp file is removed and exception propagates when rename raises after a successful write."""
        store = LocalFileStore(base_dir=tmp_path)
        src_file = tmp_path / "op.py"
        src_file.write_text("# code", encoding="utf-8")
        tmp_target = tmp_path / "err-op" / ".tmp_op.py"

        with patch.object(Path, "rename", side_effect=OSError("rename failed")):
            with pytest.raises(OSError, match="rename failed"):
                store.store(operator_id="err-op", operator_file_path=src_file)

        assert not tmp_target.exists()


class TestLocalFileStoreEdgeCases:
    """Test suite for default location, missing inputs and unreadable directories."""

    def test_default_base_dir_is_created_under_data_path(
        self, *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Without base_dir the store uses and creates {DOCPIPE_DATA_PATH}/custom_operators."""
        monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path))

        store = LocalFileStore()

        assert store.base_dir == tmp_path / "custom_operators"
        assert store.base_dir.is_dir()

    def test_store_missing_source_raises_without_leaving_files(self, *, tmp_path: Path) -> None:
        """A source file that cannot be read propagates the error and leaves no file behind."""
        store = LocalFileStore(base_dir=tmp_path / "store")

        with pytest.raises(FileNotFoundError):
            store.store(operator_id="op-1", operator_file_path=tmp_path / "missing.py")

        assert list((tmp_path / "store" / "op-1").iterdir()) == []

    def test_delete_unknown_operator_is_a_no_op(self, *, tmp_path: Path) -> None:
        """Deleting an operator without directory does not raise and leaves other operators untouched."""
        store = LocalFileStore(base_dir=tmp_path)
        (tmp_path / "keep").mkdir()

        store.delete(operator_id="unknown")

        assert store.get_operator_dir(operator_id="keep") == tmp_path / "keep"

    def test_get_directory_tree_of_removed_base_dir_is_empty(self, *, tmp_path: Path) -> None:
        """If the base directory was removed after construction the tree is an empty dict."""
        store = LocalFileStore(base_dir=tmp_path / "store")
        store.base_dir.rmdir()

        assert store.get_directory_tree() == {}

    def test_get_directory_tree_lists_directories_before_files(self, *, tmp_path: Path) -> None:
        """Entries are sorted with directories first, then by name, and files carry their size."""
        store = LocalFileStore(base_dir=tmp_path / "store")
        (store.base_dir / "b-op").mkdir()
        (store.base_dir / "b-op" / "op.py").write_bytes(b"x = 1\n")
        (store.base_dir / "a.json").write_bytes(b"{}")

        tree = store.get_directory_tree()

        assert tree == {
            "name": "store",
            "type": "directory",
            "children": [
                {
                    "name": "b-op",
                    "type": "directory",
                    "children": [{"name": "op.py", "type": "file", "size": 6}],
                },
                {"name": "a.json", "type": "file", "size": 2},
            ],
        }

    def test_get_directory_tree_keeps_unreadable_directory_empty(
        self, *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A directory that cannot be listed appears without children while siblings are still listed."""
        store = LocalFileStore(base_dir=tmp_path / "store")
        locked_dir = store.base_dir / "locked-op"
        locked_dir.mkdir()
        (locked_dir / "op.py").write_bytes(b"x = 1\n")
        (store.base_dir / "open-op").mkdir()
        original_iterdir = Path.iterdir

        def iterdir_denying_locked(path: Path) -> Iterator[Path]:
            if path == locked_dir:
                raise PermissionError(13, "Permission denied", str(path))
            return original_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", iterdir_denying_locked)

        tree = store.get_directory_tree()

        assert tree["children"] == [
            {"name": "locked-op", "type": "directory", "children": []},
            {"name": "open-op", "type": "directory", "children": []},
        ]
