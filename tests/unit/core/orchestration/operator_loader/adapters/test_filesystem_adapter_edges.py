"""FilesystemAdapter edge cases: special paths, skipped classes, cache handling, unloadable files."""

import os
import sys
from pathlib import Path

import pytest

from docpipe.core.orchestration.operator_loader.adapters.filesystem_adapter import FilesystemAdapter

_OPERATORS = '''
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class NamedOp(AbstractOperator):
    """Has a short_name and is discovered."""

    short_name: str = "named_op"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = "custom"

    def transform(self, table, file_name=None):
        return [table], {}


class NamelessOp(AbstractOperator):
    """Declares no short_name, so discovery skips it."""

    def transform(self, table, file_name=None):
        return [table], {}
'''


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes need a POSIX filesystem")
def test_path_that_is_neither_file_nor_directory(tmp_path: Path) -> None:
    fifo = tmp_path / "operators.pipe"
    getattr(os, "mkfifo")(fifo)  # noqa: B009 - os.mkfifo does not exist on Windows type stubs

    with pytest.raises(ValueError, match="Path must be a file or directory"):
        FilesystemAdapter(str(fifo))


def test_classes_without_short_name_are_not_listed(tmp_path: Path) -> None:
    (tmp_path / "ops.py").write_text(_OPERATORS)

    operators = FilesystemAdapter(str(tmp_path)).list_operators()

    assert [op.short_name for op in operators] == ["named_op"]


def test_clear_cache_tolerates_modules_already_unloaded(tmp_path: Path) -> None:
    (tmp_path / "ops.py").write_text(_OPERATORS)
    adapter = FilesystemAdapter(str(tmp_path))
    module = adapter.load_operator(operator_info=adapter.list_operators()[0])
    del sys.modules[module.__name__]

    adapter.clear_cache()

    assert adapter._loaded_modules == {}


def test_file_without_import_spec_cannot_be_loaded(tmp_path: Path) -> None:
    not_python = tmp_path / "operator.txt"
    not_python.write_text("print('not importable')")
    adapter = FilesystemAdapter(str(tmp_path))

    with pytest.raises(ImportError, match="Could not load module spec"):
        adapter._load_module_from_file(file_path=not_python)
