# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""In-process tests of the isolation worker's message loop (task D.3).

The worker normally runs in a child process, which coverage tools never see. These tests drive ``serve`` and ``main``
in the test process over a real ``multiprocessing`` pipe, so the message handling is measured and checked directly.
"""

import os
import sys
from collections.abc import Generator
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from docpipe.core.orchestration.operator_loader.isolation import worker_main
from docpipe.core.orchestration.operator_loader.isolation.protocol import (
    TYPE_LOAD,
    TYPE_RUN,
    TYPE_STOP,
    receive_message,
    send_message,
)

OPERATOR_SOURCE = """
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class WorkerOp(AbstractOperator):
    short_name = "worker_op"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, config):
        super().__init__(config)
        self.config = config
        self.output_features_to_drop = ["dropped"]
        self.updated_features = ["upper"]

    def transform(self, table, file_name=None):
        if self.config.get("mode") == "fail":
            raise ValueError("boom")
        out = table.append_column("upper", pa.array([str(v).upper() for v in table.column(0).to_pylist()]))
        return [out], {"rows": table.num_rows, "echo": self.config.get("echo")}

    def cleanup(self):
        if self.config.get("mode") == "cleanup_fails":
            raise RuntimeError("cleanup went wrong")

    @staticmethod
    def get_metadata():
        return {"label": "Worker"}
"""


@pytest.fixture(autouse=True)
def _forget_loaded_operator_modules() -> Generator[None, None, None]:
    """``load`` executes the file in this process; do not leave its module behind for other tests."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("custom_operator_worker_op_"):
            del sys.modules[name]


@pytest.fixture
def operator_file(*, tmp_path: Path) -> Path:
    path = tmp_path / "worker_op.py"
    path.write_text(OPERATOR_SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def pipe() -> Generator[tuple[Connection, Connection], None, None]:
    parent, child = Pipe()
    yield parent, child
    parent.close()
    child.close()


def _load_header(*, source_file: Path, short_name: str = "worker_op") -> dict[str, Any]:
    return {
        "type": TYPE_LOAD,
        "class_name": "WorkerOp",
        "short_name": short_name,
        "module_path": "worker_op",
        "category": "Functional",
        "source_file": str(source_file),
    }


def _run_header(*, config: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"type": TYPE_RUN, "config": config or {}, **extra}


def _table() -> pa.Table:
    return pa.table({"text": ["a", "b", "c"]})


def _serve_and_collect(*, pipe: tuple[Connection, Connection], messages: list[tuple[dict[str, Any], list[pa.Table]]]):
    """Queue ``messages`` and a final stop, run the worker loop to completion, and return its replies."""
    parent, child = pipe
    for header, tables in messages:
        send_message(conn=parent, header=header, tables=tables)
    send_message(conn=parent, header={"type": TYPE_STOP})

    worker_main.serve(conn=child)

    replies = []
    while parent.poll():
        replies.append(receive_message(conn=parent))
    return replies


class TestServe:
    def test_load_then_run_returns_the_table_metadata_and_feature_lists(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe,
            messages=[
                (_load_header(source_file=operator_file), []),
                (_run_header(config={"echo": "x"}), [_table()]),
            ],
        )

        assert [header["type"] for header, _ in replies] == ["ok", "ok"]
        header, tables = replies[1]
        assert header["metadata"] == {"rows": 3, "echo": "x"}
        assert header["output_features_to_drop"] == ["dropped"]
        assert header["updated_features"] == ["upper"]
        assert tables[0].column("upper").to_pylist() == ["A", "B", "C"]

    def test_run_before_load_is_an_error_and_the_worker_keeps_serving(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe,
            messages=[
                (_run_header(), [_table()]),
                (_load_header(source_file=operator_file), []),
                (_run_header(), [_table()]),
            ],
        )

        assert [header["type"] for header, _ in replies] == ["error", "ok", "ok"]
        assert "before a load message" in replies[0][0]["message"]

    def test_unknown_message_type_is_an_error(self, *, pipe: tuple[Connection, Connection]) -> None:
        replies = _serve_and_collect(pipe=pipe, messages=[({"type": "frobnicate"}, [])])

        assert replies[0][0]["type"] == "error"
        assert "unknown message type" in replies[0][0]["message"]

    def test_load_of_a_file_that_no_longer_defines_the_operator_is_an_error(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe, messages=[(_load_header(source_file=operator_file, short_name="other_op"), [])]
        )

        assert replies[0][0]["type"] == "error"
        assert "ImportError" in replies[0][0]["message"]
        assert "other_op" in replies[0][0]["message"]

    def test_load_of_a_missing_file_is_an_error(self, *, pipe: tuple[Connection, Connection], tmp_path: Path) -> None:
        replies = _serve_and_collect(pipe=pipe, messages=[(_load_header(source_file=tmp_path / "gone.py"), [])])

        assert replies[0][0]["type"] == "error"

    def test_operator_exception_is_reported_and_the_worker_stays_usable(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe,
            messages=[
                (_load_header(source_file=operator_file), []),
                (_run_header(config={"mode": "fail"}), [_table()]),
                (_run_header(), [_table()]),
            ],
        )

        assert [header["type"] for header, _ in replies] == ["ok", "error", "ok"]
        assert "ValueError: boom" in replies[1][0]["message"]

    def test_several_input_tables_are_refused(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe,
            messages=[
                (_load_header(source_file=operator_file), []),
                (_run_header(multiple_tables=True), [_table(), _table()]),
            ],
        )

        assert replies[1][0]["type"] == "error"
        assert "NotImplementedError" in replies[1][0]["message"]

    def test_a_failing_cleanup_does_not_replace_the_batch_result(
        self, *, pipe: tuple[Connection, Connection], operator_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        replies = _serve_and_collect(
            pipe=pipe,
            messages=[
                (_load_header(source_file=operator_file), []),
                (_run_header(config={"mode": "cleanup_fails"}), [_table()]),
            ],
        )

        assert replies[1][0]["type"] == "ok"
        assert "operator cleanup failed: RuntimeError: cleanup went wrong" in capsys.readouterr().err

    def test_stop_ends_the_loop_without_a_reply(self, *, pipe: tuple[Connection, Connection]) -> None:
        assert _serve_and_collect(pipe=pipe, messages=[]) == []

    def test_a_closed_pipe_ends_the_loop(self, *, pipe: tuple[Connection, Connection]) -> None:
        parent, child = pipe
        parent.close()

        worker_main.serve(conn=child)


class TestMain:
    def test_main_serves_on_the_inherited_descriptor_and_returns_zero(
        self, *, pipe: tuple[Connection, Connection]
    ) -> None:
        parent, child = pipe
        # ``main`` takes ownership of the descriptor and closes it, so hand it a duplicate.
        descriptor = os.dup(child.fileno())
        send_message(conn=parent, header={"type": "frobnicate"})
        send_message(conn=parent, header={"type": TYPE_STOP})

        assert worker_main.main(["--fd", str(descriptor)]) == 0

        header, _ = receive_message(conn=parent)
        assert header["type"] == "error"

    def test_main_requires_the_descriptor(self, *, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            worker_main.main([])

        assert excinfo.value.code == 2
        assert "--fd" in capsys.readouterr().err
