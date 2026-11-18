# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for ``describe_operator_file``: the AST-derived descriptor data of an operator file."""

from pathlib import Path

from docpipe.core.custom_operators.validation import describe_operator_file, validate_operator_file

OPERATOR_TEMPLATE = """
import os
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class DescribedOp(AbstractOperator):
    short_name = "described_op"
    category = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_CUSTOM

    def transform(self, table: pa.Table):
        return [table], {{}}

    @staticmethod
    def get_metadata():
{metadata_body}
"""


def _write(*, tmp_path: Path, metadata_body: str) -> Path:
    path = tmp_path / "described_op.py"
    path.write_text(OPERATOR_TEMPLATE.format(metadata_body=metadata_body), encoding="utf-8")
    return path


def test_reads_declared_secret_fields_and_label_as_literals(*, tmp_path: Path) -> None:
    path = _write(
        tmp_path=tmp_path,
        metadata_body=(
            '        return {"label": "Described", "secret_fields": ["api_key", "credentials.*"],\n'
            '                "secret_fields_by_provider": {"provider": {"s3": ["secret_access_key"]}}}'
        ),
    )

    described = describe_operator_file(operator_file_path=path)

    assert described["short_name"] == "described_op"
    assert described["category"] == "Quality"
    assert described["class_name"] == "DescribedOp"
    assert described["metadata"] == {
        "label": "Described",
        "secret_fields": ["api_key", "credentials.*"],
        "secret_fields_by_provider": {"provider": {"s3": ["secret_access_key"]}},
    }


def test_resolves_docpipe_constant_keys_without_importing_the_file(*, tmp_path: Path) -> None:
    path = _write(
        tmp_path=tmp_path,
        metadata_body=(
            "        return {OperatorConstants.Misc.LABEL: 'Hello', OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: True}"
        ),
    )

    assert describe_operator_file(operator_file_path=path)["metadata"] == {
        "label": "Hello",
        "is_operator_available": True,
    }


def test_drops_entries_that_are_not_statically_known(*, tmp_path: Path) -> None:
    path = _write(
        tmp_path=tmp_path,
        metadata_body=(
            '        return {"label": "Kept", "from_env": os.environ["HOME"], "called": open("x"),\n'
            '                "secret_fields": ["a", os.environ["B"]], **{"spread": 1}}'
        ),
    )

    assert describe_operator_file(operator_file_path=path)["metadata"] == {"label": "Kept"}


def test_dynamic_get_metadata_yields_empty_metadata(*, tmp_path: Path) -> None:
    path = _write(tmp_path=tmp_path, metadata_body="        data = {}\n        return data")

    assert describe_operator_file(operator_file_path=path)["metadata"] == {}


def test_does_not_resolve_private_or_unknown_attribute_chains(*, tmp_path: Path) -> None:
    path = _write(
        tmp_path=tmp_path,
        metadata_body=(
            '        return {"a": OperatorConstants.__dict__, "b": os.path.sep, "c": Unknown.value, "label": "ok"}'
        ),
    )

    assert describe_operator_file(operator_file_path=path)["metadata"] == {"label": "ok"}


def test_validate_operator_file_keeps_its_three_key_result(*, tmp_path: Path) -> None:
    path = _write(tmp_path=tmp_path, metadata_body='        return {"secret_fields": ["a"]}')

    assert validate_operator_file(operator_file_path=path) == {
        "short_name": "described_op",
        "category": "Quality",
        "class_name": "DescribedOp",
    }
