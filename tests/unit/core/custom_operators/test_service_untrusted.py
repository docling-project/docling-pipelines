# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""CustomOperatorService never executes an uploaded script: not at upload, update, listing or refresh."""

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from docpipe.core.constants.constants import DocpipeConstants, EnvironmentVariables, OrchestratorType
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.core.orchestration.operator_loader.untrusted_descriptor import UntrustedOperatorDescriptor
from docpipe.integrations.secrets.secret_provider import clear_providers
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage

SCRIPT = """
import os
import socket

open({marker!r}, "a").write("executed\\n")
os.environ["D2_SERVICE_CANARY"] = "executed"
socket.create_connection(("127.0.0.1", 9), timeout=0.1)

import pyarrow as pa
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class ServiceCanaryOp(AbstractOperator):
    short_name = "service_canary"
    category = OperatorCategory.Functional
    owner = "custom"

    def transform(self, table: pa.Table, file_name=None):
        return [table], {{}}

    @staticmethod
    def get_metadata():
        return {{"label": "Service canary", "secret_fields": ["{secret_field}"]}}
"""


@pytest.fixture(autouse=True)
def _environment(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS, "true")
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS, str(tmp_path / "data" / "custom_operators"))
    monkeypatch.delenv("D2_SERVICE_CANARY", raising=False)
    OperatorFactoryProvider.operator_factories.clear()
    yield
    OperatorFactoryProvider.operator_factories.clear()
    clear_providers()


@pytest.fixture
def marker(*, tmp_path: Path) -> Path:
    return tmp_path / "service.marker"


@pytest.fixture
def service(*, tmp_path: Path) -> CustomOperatorService:
    return CustomOperatorService(
        file_store=LocalFileStore(base_dir=tmp_path / "data" / "custom_operators"),
        metadata_storage=KeyValueFileSystemStorage(base_dir=tmp_path / "meta"),
    )


def _script(*, tmp_path: Path, marker: Path, secret_field: str = "api_key") -> Path:
    path = tmp_path / "upload" / "service_canary.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text(SCRIPT.format(marker=str(marker), secret_field=secret_field), encoding="utf-8")
    return path


def _assert_not_executed(*, marker: Path) -> None:
    assert not marker.exists()
    assert "D2_SERVICE_CANARY" not in os.environ


def test_upload_update_list_and_refresh_never_execute_the_script(
    *, service: CustomOperatorService, tmp_path: Path, marker: Path
) -> None:
    created = service.create_operator(
        name="Canary",
        description="d",
        operator_file_path=_script(tmp_path=tmp_path, marker=marker),
        original_filename="service_canary.py",
    )
    _assert_not_executed(marker=marker)

    factory = OperatorFactoryProvider.get_operator_factory(orchestrator=OrchestratorType.PYTHON)
    assert issubclass(factory.operators["service_canary"], UntrustedOperatorDescriptor)
    assert factory.operators["service_canary"].get_metadata()["secret_fields"] == ["api_key"]

    updated = service.update_operator(
        operator_id=created.id,
        operator_file_path=_script(tmp_path=tmp_path, marker=marker, secret_field="token"),
        original_filename="service_canary.py",
    )
    _assert_not_executed(marker=marker)
    assert updated.short_name == "service_canary"
    assert factory.operators["service_canary"].get_metadata()["secret_fields"] == ["token"]

    assert [op.id for op in service.list_operators()] == [created.id]
    service.get_operator(operator_id=created.id)
    _assert_not_executed(marker=marker)

    factory.refresh_operators()
    _assert_not_executed(marker=marker)

    service.delete_operator(operator_id=created.id)
    assert "service_canary" not in factory.operators
    _assert_not_executed(marker=marker)
